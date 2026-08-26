"""Throwaway environments for characterization, and output normalisation.

Never the real store. `docs/verifying-changes.md` section 4 is the recipe this
follows: a temp HOME with its own chezmoi.toml on POSIX, an overridden
LOCALAPPDATA on Windows. A doctor run against a live machine records that
machine's Docker state, TTS settings and clone paths, none of which reproduce
anywhere else - which is how a characterization corpus becomes untrustworthy and
then gets deleted.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Every sandbox this corpus knows how to build. Adding one is a function here
# plus a name in a fixture; nothing else.
SANDBOXES = ("empty-home", "clone-only")


def build(name: str, root: Path) -> dict[str, str]:
    """Create sandbox `name` under `root` and return the env overrides for it."""
    if name not in SANDBOXES:
        raise ValueError(f"unknown sandbox {name!r}; known: {', '.join(SANDBOXES)}")

    home = root / "home"
    home.mkdir(parents=True, exist_ok=True)
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),
        "LOCALAPPDATA": str(home / "AppData" / "Local"),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_STATE_HOME": str(home / ".local" / "state"),
        "XDG_DATA_HOME": str(home / ".local" / "share"),
        # Deliberately empty: the interesting case is a machine where nothing is
        # set up, because that is what a real first run looks like and what every
        # "it worked on mine" bug hides behind.
        "TERMINAL_STACK_DIR": "",
        # Point at a path that cannot exist so no real chezmoi is consulted.
        "TERMINAL_STACK_CHEZMOI": str(root / "no-such-chezmoi"),
        "NO_COLOR": "1",
    }

    if name == "clone-only":
        clone = root / "clone"
        clone.mkdir(parents=True, exist_ok=True)
        _git(clone, "init", "-q", str(clone))
        _git(clone, "remote", "add", "origin", "https://github.com/martybytes/terminal-stack.git")
        env["TERMINAL_STACK_DIR"] = str(clone)

    return env


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )


def child_env(overrides: dict[str, str]) -> dict[str, str]:
    """A clean-ish environment: the real one, minus anything that would leak the
    developer's own install into a recording."""
    env = dict(os.environ)
    for leaky in ("TERMINAL_STACK_DIR", "TERMINAL_STACK_CHEZMOI", "TS_DOCTOR_QUIET"):
        env.pop(leaky, None)
    env.update({k: v for k, v in overrides.items() if v != ""})
    for k, v in overrides.items():
        if v == "":
            env.pop(k, None)
    return env


# ANSI must go FIRST. The first version of this list ran the duration pattern
# ahead of it and matched "34m" inside the colour code \x1b[1;34m, turning every
# marker into "[1;<DURATION>". A normaliser that mangles the text it is meant to
# stabilise produces fixtures that look plausible and pin nothing.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_SUBS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b[0-9a-f]{40}\b"), "<SHA>"),
    (re.compile(r"\b[0-9a-f]{7,12}\b"), "<SHORT-SHA>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*"), "<TIMESTAMP>"),
    # Deliberately narrow. A bare `s` or `m` alternative matches far more than a
    # duration -- including the tail of a hex colour code.
    (re.compile(r"\b\d+(?:\.\d+)? ?(?:ms|seconds|minutes)\b"), "<DURATION>"),
)


def normalise(text: str, sandbox_root: Path | None = None) -> list[str]:
    """Stable, comparable output lines.

    Absolute paths, SHAs and durations differ on every machine, so a fixture that
    pins them can only ever pass where it was recorded.
    """
    text = _ANSI.sub("", text)
    # The real Windows account name reaches WSL through interop, which no env
    # override can intercept. Scrub it before it reaches a tracked fixture.
    for user in filter(None, (os.environ.get("USERNAME"), os.environ.get("USER"))):
        text = text.replace(f"/Users/{user}/", "/Users/<USER>/")
        text = text.replace(f"\\Users\\{user}\\", "\\Users\\<USER>\\")
        text = text.replace(f"/home/{user}", "/home/<USER>")
    # The shell emits em dashes; tstack/ is ASCII-only by rule, and Git Bash on
    # Windows hands back U+FFFD for them anyway depending on the console codepage.
    # Compare the message, not the dash glyph.
    for dash in ("—", "–", "�"):
        text = text.replace(dash, "-")
    if sandbox_root is not None:
        for variant in {
            str(sandbox_root),
            str(sandbox_root).replace("\\", "/"),
            str(sandbox_root).replace("/", "\\"),
        }:
            text = text.replace(variant, "<SANDBOX>")
    text = text.replace(str(ROOT), "<REPO>").replace(str(ROOT).replace("\\", "/"), "<REPO>")
    for pattern, repl in _SUBS:
        text = pattern.sub(repl, text)
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    lines = [ln for ln in lines if not _host_dependent(ln)]
    while lines and not lines[-1]:
        lines.pop()
    return lines


# Lines whose content is a property of the recording MACHINE, not of the code.
# On WSL the config-divergence check reads the real Windows mirror through
# interop -- LOCALAPPDATA cannot redirect it, because bash's ts_win_user asks
# cmd.exe -- so recording those lines would both leak personal settings into a
# tracked file and pin a result that reproduces nowhere else. The README says
# environment-dependent output is not pinned; this is where that is enforced.
_HOST_DEPENDENT = (
    "config stores disagree on",
    "[data] wins for",
    "agentmemory hook wiring",
    "agentmemory secret",
    "tts daemon",
    "kokoro",
    "Claude TTS hooks",
    "other terminal-stack clones",
    # The tally counts the problems above, so it varies with them. What the
    # fixtures pin is WHICH problems are found, not how many the host happened to
    # have; the exit code still carries healthy-vs-not.
    "issue(s) found",
)

_ORPHAN = re.compile(r"^\s+[/\\<][^\s]*$")


def _host_dependent(line: str) -> bool:
    if any(marker in line for marker in _HOST_DEPENDENT):
        return True
    # An indented bare path is a continuation of a note whose header was just
    # dropped -- keeping it would leave a path with nothing explaining it.
    return bool(_ORPHAN.match(line))


def find_bash() -> str | None:
    """The bash that can run this repo's scripts.

    On Windows, shutil.which("bash") finds C:\\Windows\\System32\\bash.exe -- the
    WSL launcher -- before Git Bash. It reports OSTYPE=linux-gnu and cannot take
    Windows paths, so it fails in a way that reads like a script bug. Delegates
    to the suite's existing resolver rather than growing a second one.
    """
    sys.path.insert(0, str(ROOT))
    from tests.shell_support import find_bash as _find

    return _find()
