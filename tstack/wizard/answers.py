"""Answers supplied up front, from a JSON file: `tstack wizard --answers FILE`.

The file is the SAME shape `--emit json` writes (the PascalCase keys the pwsh
bootstrap reads), so a run can be recorded on one machine and replayed on
another, and a richer front end -- a local web page, say -- only has to produce
that object for the installer to follow it.

It is applied by translating each key into the `TS_*` variable its question
already honours. Every question in flow.py skips itself when its variable is
set, so there is one skip mechanism, not two that could disagree. A question the
file does not mention is asked as usual.

Strict on purpose: an unknown key or an impossible value is refused with the
key named, before anything is asked. A typo silently ignored would install a
machine the file did not describe.
"""

from __future__ import annotations

import json
from pathlib import Path

ON_OFF = ("on", "off")

# key -> (environment variable, allowed values or None for free text)
SCALARS: dict[str, tuple[str, tuple[str, ...] | None]] = {
    "Profile": ("TS_PROFILE", ("prompt", "shell", "full")),
    "Development": ("TS_DEVELOPMENT", ("yes", "no")),
    "StarshipPreset": ("TS_STARSHIP_PRESET", None),
    "Leader": ("TS_LEADER", None),
    "Theme": ("TS_THEME", ("dark", "light", "follow")),
    "Tmux": ("TS_TMUX", None),
    "WezMux": ("TS_WEZ_MUX", ON_OFF),
    "WezRestore": ("TS_WEZ_RESTORE", ON_OFF),
    "Atuin": ("TS_ATUIN", ON_OFF),
    "Herdr": ("TS_HERDR", ON_OFF),
    "CcTts": ("TS_CC_TTS", ON_OFF),
    "CcTtsMessage": ("TS_CC_TTS_MESSAGE", ("self", "template", "hook")),
    "CcTtsDaemon": ("TS_CC_TTS_DAEMON", ON_OFF),
    "MemoryBackend": ("TS_MEMORY_BACKEND", ("agentmemory", "headroom", "none", "off")),
    "Headroom": ("TS_HEADROOM", ON_OFF),
    "HeadroomCursor": ("TS_HEADROOM_CURSOR", ("mcp", "byok", "off")),
    "Caveman": ("TS_CAVEMAN", ON_OFF),
    "Agentmemory": ("TS_AGENTMEMORY", ON_OFF),
    "Services": ("TS_SERVICES", ON_OFF),
}

# Lists. An EMPTY list is an answer ("none"), not an absence: TS_APPS="" would
# read as unset and ask the question the file already answered.
LISTS: dict[str, str] = {
    "Apps": "TS_APPS",
    "Terminals": "TS_TERMINALS",
}

# Emitted by --emit json but derived, never answered: accepted and ignored so a
# recorded file round-trips.
DERIVED = ("AppClass", "Asked")


class AnswersError(ValueError):
    """A key or value the file must not contain. The message names it."""


def to_env(payload: object) -> dict[str, str]:
    """The `TS_*` variables a parsed answers object stands for."""
    if not isinstance(payload, dict):
        raise AnswersError("the answers file must hold one JSON object")
    env: dict[str, str] = {}
    for key, value in payload.items():
        if key in DERIVED:
            continue
        if key in LISTS:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise AnswersError(f"{key}: expected a list of strings")
            env[LISTS[key]] = ",".join(value) if value else "none"
            continue
        if key not in SCALARS:
            raise AnswersError(f"{key}: not a wizard answer (see `tstack wizard -h`)")
        name, allowed = SCALARS[key]
        if not isinstance(value, str) or not value.strip():
            raise AnswersError(f"{key}: expected a non-empty string")
        if "\n" in value or not value.isascii():
            raise AnswersError(f"{key}: must be one line of ASCII")
        if allowed is not None and value not in allowed:
            raise AnswersError(f"{key}: '{value}' is not one of {', '.join(allowed)}")
        env[name] = value
    return env


def load(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise AnswersError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise AnswersError(f"{path} is not valid JSON: {exc}") from exc
    return to_env(payload)
