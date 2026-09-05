"""What a setting's valid values are RIGHT NOW, and how to see or hear one.

The settings schema knows a setting's type and its fixed options. It cannot know
the 68 voices a running kokoro happens to serve, the presets the installed
starship happens to ship, or what a prompt looks like -- those are live facts
about this machine, and hardcoding any of them is how a list goes stale without
anyone noticing.

So a `Setting` names a PROVIDER rather than carrying values, and this module is
where a provider is asked. Three things a caller can want:

  options(name)          what may I choose, on this machine, now
  preview(name, value)   what does it LOOK like        (starship)
  sample(name, value)    what does it SOUND like       (voices)

`tstack config tts voices` and `tstack config prompt list` were already doing all
of this in shell, which is exactly why the dashboard could not: the knowledge was
in the CLI's output rather than in something two front ends could call. This is
that something.

EVERY PROBE MAY FAIL, AND THAT IS NORMAL. kokoro is a container someone may not
be running; starship is installed by the bootstrap AFTER the wizard asks; `say`
is macOS-only. A provider returns what it found, an empty list is a real answer,
and no caller may treat "nothing to offer" as an error.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import platform as plat
from . import store

# Provider names. A Setting carries one of these strings; nothing else may.
APPS = "apps"
STARSHIP = "starship-presets"
KOKORO_VOICES = "kokoro-voices"
SAY_VOICES = "say-voices"

STACK_PROMPT = "terminal-stack"

# Voice ids are two lowercase letters, an underscore, then the name: `af_heart`,
# `am_adam`. Used to pull them out of a payload without depending on which of the
# two shapes the server returns -- the docker image answers {"voices":[...]} and
# mlx-audio {"object":"list","data":[...]}.
_VOICE = re.compile(r'"([a-z]{2}_[a-z0-9]+)"')


@dataclass(frozen=True)
class Choice:
    value: str
    label: str = ""
    note: str = ""

    def display(self) -> str:
        return self.label or self.value


def _run(argv: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str] | None:
    """Run a probe and hand back its output, or None when it produced none.

    The encoding is NAMED. `text=True` alone decodes with the locale codec, which
    on a Windows console is cp1252 -- and starship's own preset output carries
    bytes cp1252 has no mapping for. The decode then raises inside
    subprocess's reader THREAD, so the call returns with `returncode == 0` and
    `stdout == None`, every caller's `got.returncode != 0` guard passes, and the
    next `.strip()` dies with an AttributeError a long way from the cause. That
    took out `tstack wizard` entirely on Windows, and eleven tests with it.

    `stdout is None` is therefore also treated as failure: a decoder can still
    fail on some other input, and a caller reading None is the failure mode this
    exists to end.
    """
    try:
        got = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return got if got.stdout is not None else None


# ------------------------------------------------------------------- starship


def starship_presets() -> list[str]:
    """Starship's built-in preset names, from starship itself.

    `--list` emits a trailing blank line; a bare pass-through turns it into an
    empty entry in every menu.
    """
    exe = shutil.which("starship")
    if not exe:
        return []
    got = _run([exe, "preset", "--list"])
    if got is None or got.returncode != 0:
        return []
    return [line.strip() for line in got.stdout.splitlines() if line.strip()]


def _preset_config(name: str) -> Path | None:
    """A preset written to a temp file, ready for `starship prompt`.

    Redirected, never `-o`: that flag refuses to overwrite an existing file, and
    `mkstemp` has already created one. The command fails, the file stays empty,
    and the preview silently renders nothing.
    """
    exe = shutil.which("starship")
    if not exe:
        return None
    got = _run([exe, "preset", name])
    if got is None or got.returncode != 0 or not got.stdout.strip():
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False, encoding="utf-8") as handle:
        handle.write(got.stdout)
    return Path(handle.name)


def starship_preview(name: str) -> str | None:
    """One prompt rendered exactly as a terminal would show it, or None.

    STARSHIP_SHELL must be EMPTY rather than unset: given a shell name starship
    emits that shell's escaping (zsh's `%{...%}`), which a preview prints as
    literal punctuation instead of colour. Empty selects the plain-ANSI path.
    """
    exe = shutil.which("starship")
    if not exe:
        return None
    temporary: Path | None = None
    if name == STACK_PROMPT:
        config = Path.home() / ".config" / "starship.toml"
        if not config.is_file():
            return None
    else:
        temporary = _preset_config(name)
        if temporary is None:
            return None
        config = temporary
    try:
        got = subprocess.run(
            [exe, "prompt"],
            capture_output=True,
            text=True,
            # Named for the same reason as in _run above: the locale codec on a
            # Windows console cannot decode what starship renders, and the
            # failure surfaces as a None stdout rather than an exception here.
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
            start_new_session=True,
            env={**_environ(), "STARSHIP_SHELL": "", "STARSHIP_CONFIG": str(config)},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return got.stdout or None


def _environ() -> dict[str, str]:
    import os

    return dict(os.environ)


# --------------------------------------------------------------------- voices


def kokoro_voices() -> list[str]:
    """What the configured kokoro-compatible server actually serves.

    `?model=` is sent only when a model is configured: mlx-audio 400s without it
    (it resolves the voice packs out of that HuggingFace snapshot), the docker
    image has no such parameter, and the default request must stay the one that
    is known to work.
    """
    url = store.get("ccTtsKokoroUrl", "http://127.0.0.1:8880").rstrip("/")
    model = store.get("ccTtsKokoroModel", "kokoro")
    query = f"?model={model}" if model and model != "kokoro" else ""
    try:
        with urllib.request.urlopen(f"{url}/v1/audio/voices{query}", timeout=4) as response:
            body = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError, ValueError):
        return []
    return sorted(set(_VOICE.findall(body)))


def say_voices() -> list[Choice]:
    """The installed macOS system voices, English first.

    `say -v '?'` prints `Name  lang  # sample sentence`; the language is worth
    keeping because the name alone does not tell you Daniel is en_GB.
    """
    exe = shutil.which("say")
    if not exe:
        return []
    got = _run([exe, "-v", "?"])
    if got is None or got.returncode != 0:
        return []
    english: list[Choice] = []
    other: list[Choice] = []
    for line in got.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        name, lang = parts[0], parts[1]
        if not re.fullmatch(r"[a-z]{2}[-_][A-Z]{2}", lang):
            continue
        (english if lang.startswith("en") else other).append(Choice(name, name, lang))
    return english + other


# ------------------------------------------------------------------ the front


def app_options() -> list[Choice]:
    """The CLI tool catalog, filtered to what this machine can install.

    Grouped in file order, which is picker order, with the group name as the
    note -- so a 47-row list still reads as sections.
    """
    from . import apps as catalog

    here = plat.kind()
    return [
        Choice(a.id, a.id, f"{a.group}: {a.description}")
        for a in catalog.catalog()
        if a.installable(here)
    ]


def options(provider: str) -> list[Choice]:
    """Every value this machine can offer for a provider, right now.

    An empty list is a real answer -- the container is down, starship is not
    installed yet, `say` is not this platform -- and never an error.
    """
    if provider == STARSHIP:
        stack = Choice(STACK_PROMPT, STACK_PROMPT, "this stack's own two-line prompt")
        return [stack, *(Choice(p, p, "starship built-in") for p in starship_presets())]
    if provider == APPS:
        return app_options()
    if provider == KOKORO_VOICES:
        return [Choice(v, v, _voice_hint(v)) for v in kokoro_voices()]
    if provider == SAY_VOICES:
        installed = say_voices()
        # The empty value is a REAL choice -- an unset ccTtsSayVoice means "the
        # system voice" -- but only where there is a `say` to have one. Offering
        # it on Linux would be a menu entry for a thing that does not exist.
        if not installed:
            return []
        return [Choice("", "(system voice)", "whatever macOS is set to"), *installed]
    return []


def _voice_hint(voice: str) -> str:
    """kokoro's naming: first letter is the language, second the gender."""
    languages = {
        "a": "American",
        "b": "British",
        "e": "Spanish",
        "f": "French",
        "h": "Hindi",
        "i": "Italian",
        "j": "Japanese",
        "p": "Portuguese",
        "z": "Mandarin",
    }
    if len(voice) < 2:
        return ""
    language = languages.get(voice[0], "")
    gender = {"f": "female", "m": "male"}.get(voice[1], "")
    return " ".join(part for part in (language, gender) if part)


def can_sample(provider: str) -> bool:
    """Is there anything to HEAR? Advertising a key that does nothing is a small
    lie, and a menu that offers `s` on a prompt preset is exactly that."""
    return provider in (KOKORO_VOICES, SAY_VOICES)


def can_preview(provider: str) -> bool:
    """Is there anything to SEE beyond the name?"""
    return provider == STARSHIP


def is_multi(provider: str) -> bool:
    """Does this setting hold MANY of its options rather than one?

    `apps` is the only one, and it is why the picker needs a tick-list at all:
    every other provider answers "which one", this one answers "which ones".
    """
    return provider == APPS


def preview(provider: str, value: str) -> str | None:
    """What this value LOOKS like, or None when there is nothing to show."""
    if provider == STARSHIP:
        return starship_preview(value)
    return None


def sample(provider: str, value: str) -> tuple[bool, str]:
    """Speak one voice. Returns (played, message).

    Never raises: this is reached from a keypress in a dashboard, and a failed
    sample must leave the screen up and say why.
    """
    if provider == SAY_VOICES:
        return _sample_say(value)
    if provider == KOKORO_VOICES:
        return _sample_kokoro(value)
    return (False, "nothing to hear for this setting")


def _sample_say(voice: str) -> tuple[bool, str]:
    exe = shutil.which("say")
    if not exe:
        return (False, "say is not available on this platform")
    text = f"Hello, I am {voice}. This is how I sound." if voice else "This is the system voice."
    argv = [exe, *(["-v", voice] if voice else []), "--", text]
    got = _run(argv, timeout=30)
    if got is None or got.returncode != 0:
        return (False, f"say could not speak '{voice}'")
    return (True, f"played {voice or 'the system voice'}")


def _sample_kokoro(voice: str) -> tuple[bool, str]:
    url = store.get("ccTtsKokoroUrl", "http://127.0.0.1:8880").rstrip("/")
    payload = json.dumps(
        {
            "model": store.get("ccTtsKokoroModel", "kokoro"),
            "input": f"Hello, I am {voice}. This is how I sound.",
            "voice": voice,
            "response_format": "mp3",
        }
    ).encode()
    request = urllib.request.Request(
        f"{url}/v1/audio/speech", data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            audio = response.read()
    except (urllib.error.URLError, OSError, ValueError):
        return (False, f"no answer from {url} - is the kokoro container up?")
    if not audio:
        return (False, f"{url} returned no audio for '{voice}'")

    with tempfile.NamedTemporaryFile("wb", suffix=".mp3", delete=False) as handle:
        handle.write(audio)
    path = Path(handle.name)
    try:
        return _play(path, voice)
    finally:
        path.unlink(missing_ok=True)


def _play(path: Path, voice: str) -> tuple[bool, str]:
    """Same ladder the TTS hooks use, minus the daemon: afplay on macOS, else
    ffplay. A missing player is reported, never silently treated as success."""
    if plat.kind() == plat.MACOS and shutil.which("afplay"):
        got = _run([str(shutil.which("afplay")), str(path)], timeout=60)
        if got is not None and got.returncode == 0:
            return (True, f"played {voice}")
    ffplay = shutil.which("ffplay")
    if ffplay:
        got = _run(
            [ffplay, "-nodisp", "-autoexit", "-hide_banner", "-loglevel", "quiet", str(path)],
            timeout=60,
        )
        if got is not None and got.returncode == 0:
            return (True, f"played {voice}")
    return (False, "synthesised it, but found no audio player (afplay or ffplay)")
