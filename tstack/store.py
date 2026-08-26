"""The saved-settings store: chezmoi `[data]` and the Windows `config.json` mirror.

ONE WRITER. Every persisted setting goes through set() / set_list() below and
nowhere else. Two stores that each render a valid file from their own copy is how
this stack lost all five Claude TTS hooks in one day, and how a pwsh-side `tts`
save stopped surviving a WSL apply.

Two stores, one meaning:

    chezmoi [data]   authoritative wherever chezmoi runs (WSL, native Linux, macOS)
    config.json      the Windows mirror, written by ts_mirror_windows_config;
                     the only store a Windows-standalone install has

They spell the same answer differently -- `[data]` holds "on"/"off"/"true"
strings, the mirror holds real JSON booleans -- so anything comparing them has to
compare meaning, not spelling. `normalise()` is that.
"""

from __future__ import annotations

import contextlib
import functools
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from . import platform as plat

MISSING = "__missing__"

# The keys worth rendering in one batch. A per-key `chezmoi execute-template`
# spawn costs seconds on a combined WSL+Windows host -- bootstrap/_config.sh
# measured 49 spawns at 229s -- so everything is fetched at once.
DATA_KEYS = (
    "leaderChord",
    "themeMode",
    "resolvedTheme",
    "tmuxPrefix",
    "weztermMux",
    "weztermRestore",
    "atuinEnabled",
    "ghosttyConfig",
    "memoryBackend",
    "agentmemoryEnabled",
    "headroomEnabled",
    "headroomCursorMode",
    "cavemanEnabled",
    "playwrightEnabled",
    "ccTtsEnabled",
    "ccTtsDaemon",
    "ccTtsEngine",
    "ccTtsSummarizer",
    "windowsUsername",
)

# Documented defaults, applied when a key has never been written. A machine that
# never answered a question must read as the old behaviour, not as empty.
DEFAULTS: dict[str, str] = {
    "themeMode": "dark",
    "weztermMux": "off",
    "weztermRestore": "off",
    "atuinEnabled": "off",
    "ghosttyConfig": "on",
    "memoryBackend": "agentmemory",
    "headroomEnabled": "off",
    "headroomCursorMode": "mcp",
    "cavemanEnabled": "off",
    "playwrightEnabled": "off",
    "ccTtsEnabled": "false",
    "ccTtsDaemon": "off",
    "ccTtsEngine": "kokoro",
}

TRUTHY = {"on", "true", "yes", "1", "enabled"}
FALSEY = {"off", "false", "no", "0", "disabled", ""}


def normalise(value: str | bool | None) -> str:
    """Collapse a stored value to 'true' / 'false', or return it unchanged.

    The two stores disagree in spelling by design, so a divergence check that
    compares raw strings reports a difference on every machine and is therefore
    ignored, which is worse than not having it.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    text = "" if value is None else str(value).strip()
    low = text.lower()
    if low in TRUTHY:
        return "true"
    if low in FALSEY:
        return "false"
    return text


@functools.lru_cache(maxsize=1)
def chezmoi_data() -> dict[str, str]:
    """Every `[data]` key, in one `chezmoi execute-template` call.

    Empty when chezmoi is absent, which is the normal state of a
    Windows-standalone install rather than an error.
    """
    chezmoi = plat.find_chezmoi()
    if not chezmoi or not Path(chezmoi).exists():
        return {}
    # `key=<<value>>` framing, so a value containing whitespace or a newline
    # survives the round trip.
    # Go template braces, so an f-string would need every one doubled. Kept as
    # explicit concatenation because the doubled form is unreadable and this text
    # has to stay diffable against bootstrap/_config.sh's ts_data_prefetch.
    template = "".join(
        '{{ if hasKey . "' + k + '" }}' + k + '=<<{{ index . "' + k + '" }}>>\n{{ end }}'
        for k in DATA_KEYS
    )
    try:
        out = subprocess.run(
            [chezmoi, "execute-template", template],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if out.returncode != 0:
        return {}
    found: dict[str, str] = {}
    for line in out.stdout.splitlines():
        if "=<<" in line and line.endswith(">>"):
            key, _, rest = line.partition("=<<")
            found[key] = rest[:-2]
    return found


@functools.lru_cache(maxsize=1)
def mirror_path() -> Path | None:
    base = plat.local_app_data()
    return base / "terminal-stack" / "config.json" if base else None


@functools.lru_cache(maxsize=1)
def mirror() -> dict[str, Any]:
    """The Windows `config.json`, or {} when there is no Windows side."""
    path = mirror_path()
    if not path or not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def mirror_value(dotted: str) -> str:
    """One dotted path out of the mirror, or MISSING.

    MISSING rather than empty on purpose: a mirror written by an older version
    simply lacks the key, and reporting that as a disagreement would make the
    divergence check cry wolf on every machine that has not re-synced.
    """
    node: Any = mirror()
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return MISSING
        node = node[part]
    if isinstance(node, bool):
        return "true" if node else "false"
    return str(node)


def get(key: str, default: str | None = None) -> str:
    """A setting, preferring chezmoi `[data]`, then the mirror, then the default."""
    data = chezmoi_data()
    if key in data and data[key] != "":
        return data[key]
    from_mirror = mirror_value(key)
    if from_mirror != MISSING and from_mirror != "":
        return from_mirror
    if default is not None:
        return default
    return DEFAULTS.get(key, "")


# chezmoi [data] key -> dotted path in the Windows mirror. Only the keys whose
# disagreement changes what gets rendered are worth reporting: a mismatch here
# means one side will silently undo the other on its next apply.
DIVERGENCE_PAIRS: tuple[tuple[str, str], ...] = (
    ("ccTtsEnabled", "ccTts.enabled"),
    ("ccTtsDaemon", "ccTts.daemon.enabled"),
    ("ccTtsEngine", "ccTts.engine"),
    ("ccTtsSummarizer", "ccTts.summarize.mode"),
    ("leaderChord", "leaderChord"),
    ("themeMode", "themeMode"),
    ("tmuxPrefix", "tmuxPrefix"),
    ("weztermMux", "weztermMux"),
    ("weztermRestore", "weztermRestore"),
    ("headroomEnabled", "headroomEnabled"),
    ("headroomCursorMode", "headroomCursorMode"),
    ("cavemanEnabled", "cavemanEnabled"),
    ("agentmemoryEnabled", "agentmemoryEnabled"),
)


def divergences() -> list[tuple[str, str, str]]:
    """(key, chezmoi value, mirror value) for every key the two stores disagree on.

    Report only, never repair: a disagreement can be a deliberate pwsh-side
    change, and overwriting it would be the same silent loss the check exists to
    expose.
    """
    data = chezmoi_data()
    if not data or not mirror():
        return []
    out = []
    for key, dotted in DIVERGENCE_PAIRS:
        theirs = mirror_value(dotted)
        mine = data.get(key, MISSING)
        # Absent on EITHER side is "never written here", not "disagrees". The
        # reasoning is symmetric and the first version only applied it to the
        # mirror, so a key set on Windows and never set in [data] read as drift
        # on every machine that had not re-run the wizard.
        if theirs == MISSING or mine == MISSING or mine == "" or theirs == "":
            continue
        if normalise(mine) != normalise(theirs):
            out.append((key, mine, theirs))
    return out


def clear_cache() -> None:
    """Drop every memoised read. Tests inject a store and must not inherit.

    Tolerates a name that has been monkeypatched to a plain function: teardown
    runs after the patch is in place, and a fixture that raises there fails every
    test in the module for a reason that has nothing to do with any of them.
    """
    for fn in (chezmoi_data, mirror, mirror_path):
        clear = getattr(fn, "cache_clear", None)
        if clear is not None:
            clear()


# ---------------------------------------------------------------- write side
#
# ONE writer. Two stores that each render a valid file from their own copy is how
# this stack lost all five Claude TTS hooks in a single day, and why a pwsh-side
# `tts` save stopped surviving a WSL apply. Everything that persists a setting
# goes through set() or save(); nothing else may touch chezmoi.toml or the mirror.


class StoreError(RuntimeError):
    """A write could not be completed. Never swallowed: a save that reports
    success while changing nothing is the failure mode this file exists to end."""


def toml_path() -> Path:
    """chezmoi's config, which holds the [data] block. Mirrors ts_toml."""
    return Path.home() / ".config" / "chezmoi" / "chezmoi.toml"


def writes_to_mirror() -> bool:
    """True when config.json is the authoritative store, not chezmoi [data].

    A Windows-standalone install has no chezmoi at all: `sync-windows.ps1` renders
    from config.json and nothing ever reads a chezmoi.toml. Writing [data] there
    creates a file no code path consults, so the save reports success and changes
    nothing that matters - the exact failure this module exists to prevent, just
    on one platform instead of all of them.

    WSL is NOT this case even though it can see the mirror: chezmoi is
    authoritative there, and `ts_mirror_windows_config` derives config.json from
    [data] afterwards.
    """
    if plat.kind() != plat.WINDOWS:
        return False
    chezmoi = plat.find_chezmoi()
    return not (chezmoi and Path(chezmoi).exists())


def _set_in_mirror(key: str, value: object) -> None:
    """Write one key into the Windows config.json, preserving everything else."""
    path = mirror_path()
    if path is None:
        raise StoreError("no %LOCALAPPDATA%: cannot locate the Windows config mirror")
    current: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except (OSError, ValueError) as exc:
            # Never overwrite a file we could not read: it may hold settings this
            # version does not know about, and clobbering them is silent loss.
            raise StoreError(
                f"{path} is not readable JSON; refusing to overwrite it: {exc}"
            ) from exc
    current[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(current, indent=2) + "\n")
    clear_cache()


def _render_line(key: str, value: str) -> str:
    return f'{key} = "{value}"'


def set(key: str, value: str) -> None:
    """Write one key into chezmoi [data], creating the block if needed.

    Port of ts_data_set. Three cases, in the same order:
      1. the key already exists   -> replace that line in place
      2. [data] exists            -> insert immediately after the header
      3. neither                  -> append a [data] block

    Values are written quoted. A list value (apps) is the caller's job to format,
    because TOML arrays are not strings and quoting one would corrupt it.
    """
    if writes_to_mirror():
        _set_in_mirror(key, value)
        return
    path = toml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # Through _atomic_write like every other path, so a failure surfaces as a
        # StoreError rather than a bare OSError. This used to be the one case that
        # reported differently, and it is the worst one to get wrong: it is the
        # fresh-install path.
        _atomic_write(path, "[data]\n" + _render_line(key, value) + "\n")
        clear_cache()
        return

    original = path.read_text(encoding="utf-8")
    lines = original.split("\n")
    prefix = f"{key} = "
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = _render_line(key, value)
            break
    else:
        for i, line in enumerate(lines):
            if line.strip() == "[data]":
                lines.insert(i + 1, _render_line(key, value))
                break
        else:
            if lines and lines[-1] != "":
                lines.append("")
            lines += ["[data]", _render_line(key, value), ""]

    updated = "\n".join(lines)
    _atomic_write(path, updated)
    clear_cache()


def set_list(key: str, values: list[str]) -> None:
    """A TOML array, for `apps`. Quoted per element, never as one string."""
    if writes_to_mirror():
        # A JSON array, not a TOML one: the mirror is JSON.
        _set_in_mirror(key, list(values))
        return
    rendered = ", ".join(f'"{v}"' for v in values)
    path = toml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = path.read_text(encoding="utf-8") if path.exists() else "[data]\n"
    lines = body.split("\n")
    literal = f"{key} = [{rendered}]"
    prefix = f"{key} = "
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            lines[i] = literal
            break
    else:
        for i, line in enumerate(lines):
            if line.strip() == "[data]":
                lines.insert(i + 1, literal)
                break
        else:
            lines += ["[data]", literal, ""]
    _atomic_write(path, "\n".join(lines))
    clear_cache()


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file in the same directory, then replace.

    A half-written chezmoi.toml is worse than an unchanged one: chezmoi refuses to
    run at all, which takes out every command in the stack including the doctor
    that would have explained it.
    """
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError as exc:
        raise StoreError(f"could not write {path}: {exc}") from exc
    finally:
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()


def chezmoi_init() -> bool:
    """Re-run `chezmoi init`, which regenerates the DERIVED keys.

    leaderKey, leaderMods, tmuxPrefixResolved and resolvedTheme are computed by
    .chezmoi.toml.tmpl from the keys the user actually chose. Skipping this leaves
    them describing the previous answer, so the leader chord changes in [data] and
    nothing in the rendered configs moves.
    """
    chezmoi = plat.find_chezmoi()
    if not chezmoi or not Path(chezmoi).exists():
        return False
    try:
        out = subprocess.run(
            [chezmoi, "init"],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0
