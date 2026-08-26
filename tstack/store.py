"""The saved-settings store: chezmoi `[data]` and the Windows `config.json` mirror.

READ SIDE ONLY for now. Writes arrive with the config port (phase 4), and when
they do they arrive HERE and nowhere else -- one writer is the whole point. Two
stores that each render a valid file from their own copy is how this stack lost
all five Claude TTS hooks in one day, and how a pwsh-side `tts` save stopped
surviving a WSL apply.

Two stores, one meaning:

    chezmoi [data]   authoritative wherever chezmoi runs (WSL, native Linux, macOS)
    config.json      the Windows mirror, written by ts_mirror_windows_config;
                     the only store a Windows-standalone install has

They spell the same answer differently -- `[data]` holds "on"/"off"/"true"
strings, the mirror holds real JSON booleans -- so anything comparing them has to
compare meaning, not spelling. `normalise()` is that.
"""

from __future__ import annotations

import functools
import json
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
