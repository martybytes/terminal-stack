"""Config loading for ttsd.

Reads the same merged view the shell hooks use: ~/.claude/tts/config.json
(chezmoi-rendered) deep-merged with the untracked ~/.claude/tts/local.json
(local wins, keys starting with "_" skipped) — the exact semantics of
cc_tts_init_config in dot_claude/hooks/cc-tts-lib.sh.

Values are read with dotted paths against code-level defaults, so a
config.json predating any given key still yields today's behavior.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import secrets
import tempfile
import threading
import time
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


# ── file plumbing shared by the local.json writer ─────────────────────────────


def _read_json_dict(path: Path) -> dict:
    """A JSON object from disk, or {} for anything that is not one. Never raises."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _dated_sibling(path: Path, tag: str) -> Path:
    """`local.json` -> `local.json.bad.YYYYMMDD`, never clobbering a same-day file.

    Same convention every script in this repo uses for backups, including the `.N` suffix
    rule, because a same-day re-run must not destroy the first copy.
    """
    stamp = time.strftime("%Y%m%d")
    candidate = path.with_name(f"{path.name}{tag}.{stamp}")
    index = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}{tag}.{stamp}.{index}")
        index += 1
    return candidate


def _write_json_atomic(path: Path, data: dict) -> bool:
    """Write pretty JSON via a temp file in the same directory, then os.replace."""
    try:
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".local-", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.write("\n")
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    except (OSError, TypeError, ValueError) as exc:
        log.warning("could not write %s: %s", path, exc)
        return False
    return True


@contextlib.contextmanager
def _file_lock(path: Path, wait_sec: float = 3.0, stale_sec: float = 30.0):
    """Best-effort exclusive lock. Yields True when held, False when it gave up.

    Proceeds after `wait_sec` rather than refusing: a settings save that silently does
    nothing because of a leftover lock file would be worse than an interleaved write. A
    lock older than `stale_sec` is reclaimed. Atomic exclusive create is the mutex; a
    read-then-write check would let two writers a millisecond apart both pass.
    """
    fd = None
    deadline = time.time() + max(0.0, wait_sec)
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except OSError:
                age = 0.0
            if age > stale_sec:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            if time.time() >= deadline:
                log.info("config lock busy for %.0fs; writing anyway", wait_sec)
                break
            time.sleep(0.05)
        except OSError as exc:
            log.debug("config lock unavailable (%s); writing anyway", exc)
            break
    try:
        yield fd is not None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


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

    def layers(self) -> tuple[dict, dict]:
        """(rendered config.json, local.json overrides), both as fresh copies.

        The dashboard has to show which layer a value came from. Without that it would be
        possible to "change" a setting in the UI, see no effect, and have no way to learn
        that an override two files away is winning -- which is the exact confusion this
        whole feature exists to end.
        """
        base = _read_json_dict(tts_config_dir() / "config.json")
        local = _read_json_dict(tts_config_dir() / "local.json")
        return base, local

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data)) if self._data else {}

    # ── local.json writes (tray toggles) ──────────────────────────────────

    def write_local(self, dotted: str, value: Any) -> None:
        """Persist one override into local.json (tray menu changes)."""
        self.write_local_many({dotted: value})

    def write_local_many(self, updates: dict[str, Any]) -> bool:
        """Persist several overrides in ONE read-modify-write. False if nothing was saved.

        Three properties the previous version lacked, each of which a settings form makes
        likely rather than theoretical:

        - **Atomic.** It wrote in place, so a crash or a full disk mid-write left truncated
          JSON. `Config.reload` then drops the *whole* overlay as unreadable, which reads to
          a user as every local setting reverting at once.
        - **Locked.** Read-modify-write with no lock: a tray toggle and a form submit
          interleaving lose one of the two writes. Exclusive-create is the mutex, the same
          idiom and the same reasoning as `speaklock.py`.
        - **Non-destructive.** `except ValueError: data = {}` meant one bad byte caused the
          next write to replace every other override with a single-key document. A corrupt
          file is now preserved and named, never silently rewritten.
        """
        if not updates:
            return True
        path = tts_config_dir() / "local.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("cannot create %s: %s", path.parent, exc)
            return False

        with _file_lock(path.with_suffix(".json.lock")):
            data = self._read_local_preserving(path)
            for dotted, value in updates.items():
                node = data
                parts = [part for part in dotted.split(".") if part]
                if not parts:
                    continue
                for part in parts[:-1]:
                    # A scalar sitting where a branch is needed has to be replaced, or the
                    # requested key cannot exist at all. setdefault will not do it: it
                    # returns the existing scalar rather than overwriting it.
                    if not isinstance(node.get(part), dict):
                        node[part] = {}
                    node = node[part]
                node[parts[-1]] = value
            if not _write_json_atomic(path, data):
                return False
        self.reload()
        return True

    @staticmethod
    def _read_local_preserving(path: Path) -> dict:
        """Existing overrides, or {} after moving an unparseable file aside."""
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except OSError as exc:
            log.warning("cannot read %s (%s); starting from an empty overlay", path, exc)
            return {}
        try:
            data = json.loads(raw)
        except ValueError:
            spoiled = _dated_sibling(path, ".bad")
            try:
                os.replace(path, spoiled)
                log.error("%s was not valid JSON; kept it as %s", path.name, spoiled.name)
            except OSError as exc:
                log.error("%s is not valid JSON and could not be set aside: %s", path, exc)
            return {}
        return data if isinstance(data, dict) else {}


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
