"""Config loading for ttsd.

Reads the same merged view the shell hooks use: ~/.claude/tts/config.json
(chezmoi-rendered) deep-merged with the untracked ~/.claude/tts/local.json
(local wins, keys starting with "_" skipped) — the exact semantics of
cc_tts_init_config in dot_claude/hooks/cc-tts-lib.sh.

Values are read with dotted paths against code-level defaults, so a
config.json predating any given key still yields today's behavior.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "engine": "kokoro",
    "events": ["waiting", "error", "question", "permission"],
    "sources": {
        "claude": {"prefixEnabled": True, "prefix": "Claude"},
        "cursor": {"prefixEnabled": True, "prefix": "Cursor"},
        "codex": {"prefixEnabled": True, "prefix": "Codex"},
    },
    "announce": {
        "includeProject": True,
        "messageMode": "template",
        "templates": {
            "waiting": "Done in {project}. I'm waiting for you.",
            "error": "Error in {project}. You may want to look.",
            "question": "I have a question for you.",
            "permission": "Permission needed in {project}.",
        },
    },
    "excitement": 0.25,
    "kokoro": {
        "url": "http://127.0.0.1:8880",
        "voice": "am_adam",
        "speed": 1.0,
        "format": "mp3",
        "timeoutSec": 15,
    },
    "chatterbox": {
        "url": "http://127.0.0.1:8881",
        "voice": "adam",
        "energy": 0.25,
        "cfgWeight": 0.5,
        "temperature": 0.6,
        "timeoutSec": 60,
    },
    "edge": {"enabled": True, "voice": "en-US-AndrewMultilingualNeural"},
    "maxChars": 120,
    "debounceSec": 5,
    # Global mute chord, handled by ttsd/hotkey.py while the daemon runs. Empty
    # disables it. Code-level default on purpose: overriding it belongs in the
    # untracked local.json, not in a new chezmoi [data] key.
    "hotkey": "ctrl+alt+shift+m",
    "player": "auto",
    "daemon": {
        "enabled": False,
        "port": 8890,
        "coalesceSec": 1.8,
        "coalesceCapSec": 4.0,
        "doneMaxAgeSec": 20,
        "interactiveMaxAgeSec": 120,
        "maxQueue": 12,
        "postTimeoutMs": 250,
        "hostOverride": "",
        "suppressFocused": False,
        "idleRestoreSec": 0.7,
        "sessionTtlMin": 240,
        "cursor": {"holdSec": 3, "cooldownSec": 15},
    },
    "summarize": {
        "mode": "template",
        "haiku": {
            "model": "claude-haiku-4-5",
            "keyEnv": "ANTHROPIC_API_KEY",
            "timeoutSec": 3,
        },
        "ollama": {
            "url": "http://127.0.0.1:11434",
            "model": "llama3.2:3b",
            "timeoutSec": 4,
        },
        "emptyMeansSilent": False,
    },
    "music": {
        "mode": "duck",
        "duckPercent": 30,
        "smartThresholdSec": 5,
        "apps": "all",
        "maxDuckSec": 15,
    },
    "voices": {
        "perSession": False,
        "pool": ["am_adam", "am_michael", "af_heart", "bm_george"],
    },
    "quietHours": {
        "enabled": False,
        "start": "22:00",
        "end": "07:00",
        "allowInteractive": True,
    },
}


def _deep_merge(base: Any, overlay: Any) -> Any:
    """local.json wins key-by-key; "_"-prefixed keys in the overlay skipped."""
    if isinstance(base, dict) and isinstance(overlay, dict):
        out = dict(base)
        for k, v in overlay.items():
            if isinstance(k, str) and k.startswith("_"):
                continue
            out[k] = _deep_merge(base.get(k), v) if k in base else v
        return out
    return overlay if overlay is not None else base


def tts_config_dir() -> Path:
    return Path.home() / ".claude" / "tts"


def daemon_root() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "terminal-stack" / "tts-daemon"


def state_dir() -> Path:
    return daemon_root() / "state"


def logs_dir() -> Path:
    return daemon_root() / "logs"


class Config:
    """Thread-safe merged config with dotted-path access and hot reload."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        merged: Any = {}
        for name in ("config.json", "local.json"):
            path = tts_config_dir() / name
            if not path.is_file():
                continue
            try:
                merged = _deep_merge(merged, json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError) as exc:
                log.warning("ignoring unreadable %s: %s", path, exc)
        with self._lock:
            self._data = merged if isinstance(merged, dict) else {}
        log.info("config reloaded (%d top-level keys)", len(self._data))

    def get(self, dotted: str, default: Any = None) -> Any:
        """cfg.get('daemon.cursor.holdSec') — falls back to DEFAULTS, then default."""
        with self._lock:
            found = self._walk(self._data, dotted)
        if found is not None:
            return found
        built_in = self._walk(DEFAULTS, dotted)
        return built_in if built_in is not None else default

    @staticmethod
    def _walk(data: Any, dotted: str) -> Any:
        node = data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data)) if self._data else {}

    # ── local.json writes (tray toggles) ──────────────────────────────────

    def write_local(self, dotted: str, value: Any) -> None:
        """Persist one override into local.json (tray menu changes)."""
        path = tts_config_dir() / "local.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, ValueError):
            data = {}
        node = data
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        self.reload()


def load_or_create_token() -> str:
    """Shared secret for the non-loopback (WSL-facing) listener."""
    path = state_dir() / "token"
    try:
        token = path.read_text(encoding="utf-8").strip()
        if token:
            return token
    except OSError:
        pass
    token = secrets.token_hex(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    return token
