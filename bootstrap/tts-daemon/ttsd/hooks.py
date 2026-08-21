"""Windows hook client and direct-speech fallback for the packaged executable."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

from . import history, speaklock
from .config import Config, daemon_root, state_dir
from .events import EventError, parse_event
from .playback import Playback
from .process import popen_hidden
from .registry import Registry
from .summarize import Summarizer
from .synth import Synth

log = logging.getLogger(__name__)


def _json(raw: bytes) -> dict:
    try:
        value = json.loads(raw.decode("utf-8")) if raw else {}
        return value if isinstance(value, dict) else {}
    except (UnicodeDecodeError, ValueError):
        return {}


def _first_question(data: dict, cursor: bool = False) -> str:
    tool_input = data.get("tool_input") or {}
    questions = tool_input.get("questions") if isinstance(tool_input, dict) else None
    if not isinstance(questions, list) or not questions or not isinstance(questions[0], dict):
        return ""
    first = questions[0]
    keys = ("prompt", "question", "header") if cursor else ("question", "prompt", "header")
    return next((str(first[key]) for key in keys if first.get(key)), "")


def build_payload(source: str, event: str, state: str, raw: bytes) -> dict | None:
    """Normalize Claude/Cursor/Codex hook JSON into the daemon protocol."""
    data = _json(raw)
    override = ""
    project_override = ""
    source = source.lower()
    event = event.lower()
    state = state.lower()

    if source == "cursor":
        roots = data.get("workspace_roots")
        if isinstance(roots, list) and roots:
            project_override = str(roots[0])
        if event == "cursor_stop":
            status = str(data.get("status") or "").lower()
            if status in ("", "aborted", "completed"):
                return None
            state = "error"
        elif event == "cursor_response":
            state = "waiting"
        elif event == "cursor_question":
            if str(data.get("tool_name") or "") not in ("AskQuestion", "AskUserQuestion"):
                return None
            state = "question"
            override = _first_question(data, cursor=True)
    elif event in ("question", "ask_user_question"):
        event = "question"
        state = "question"
        override = _first_question(data)
    elif event in ("permission", "permission_request"):
        event = "permission"
        state = "permission"
        override = str(data.get("tool_name") or data.get("message") or "")
    elif event == "notification":
        state = "question"
        override = str(data.get("message") or "")

    pdir = (os.environ.get("CLAUDE_PROJECT_DIR")
            or project_override
            or os.environ.get("CURSOR_PROJECT_DIR")
            or str(data.get("cwd") or "")
            or os.getcwd())
    sid = (data.get("session_id") or data.get("conversation_id")
           or data.get("thread_id") or f"dir:{pdir}")
    project = Path(pdir).name or "a project"
    message_text = (data.get("last_assistant_message") or data.get("text") or "")
    if isinstance(data.get("afterAgentResponse"), dict):
        message_text = data["afterAgentResponse"].get("text") or message_text

    return {
        "v": 1,
        "source": source,
        "host": "windows",
        "event": event,
        "state": state,
        "session_key": f"{source}:{sid}",
        "project": {"dir": pdir, "name": project},
        "cwd": str(data.get("cwd") or os.getcwd()),
        "transcript_path": str(data.get("transcript_path") or ""),
        "override": override,
        "message": {
            "text": str(message_text),
            "error_type": str(data.get("error_type") or ""),
            "notification_type": str(data.get("notification_type") or ""),
            "tool_name": str(data.get("tool_name") or ""),
            "stop_status": str(data.get("status") or ""),
        },
        "wezterm": {"pane": str(os.environ.get("WEZTERM_PANE") or "")},
        "ts": time.time(),
    }


def _post(cfg: Config, payload: dict) -> bool:
    port = int(os.environ.get("CC_TTS_DAEMON_PORT_OVERRIDE")
               or cfg.get("daemon.port", 8890))
    timeout = max(0.05, float(cfg.get("daemon.postTimeoutMs", 250)) / 1000)
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/event",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status in (200, 202)
    except OSError:
        return False


def _direct_command(path: Path) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "_direct", str(path)]
    return [sys.executable, "-m", "ttsd", "_direct", str(path)]


def _spawn_direct(payload: dict) -> bool:
    path = state_dir() / f"direct-{uuid.uuid4().hex}.json"
    try:
        # Inside the try on purpose. An unusable state directory must return False so the
        # caller speaks in-process, not raise past it and take the whole hook down.
        state_dir().mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        env = os.environ.copy()
        if getattr(sys, "frozen", False):
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        popen_hidden(
            _direct_command(path), detached=True, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
        return True
    except OSError as exc:
        log.warning("direct worker launch failed: %s", exc)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def _daemon_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "daemon", "--no-tray"]
    return [sys.executable, "-m", "ttsd", "daemon", "--no-tray"]


def _ensure_daemon(cfg: Config) -> bool:
    """Start the daemon and wait briefly for it to listen. True if it is up afterwards.

    Idempotent by construction: two hooks racing here both spawn, and the loser fails to
    bind port 8890 and exits. A bind failure means "someone else won", not an error -- so
    this only ever reports whether the port answers, never which process won it. Guarded by
    a lock file so a flapping daemon cannot be respawned on every single hook.
    """
    port = int(os.environ.get("CC_TTS_DAEMON_PORT_OVERRIDE") or cfg.get("daemon.port", 8890))
    marker = state_dir() / "daemon-start.lock"
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        if marker.exists() and (time.time() - marker.stat().st_mtime) < 30:
            return False  # a very recent attempt is already in flight or just failed
        marker.write_text(f"{os.getpid()} {time.time():.3f}", encoding="utf-8")
    except OSError:
        pass

    log.info("tts daemon not answering on %s; starting it", port)
    try:
        env = os.environ.copy()
        if getattr(sys, "frozen", False):
            env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        popen_hidden(
            _daemon_command(), detached=True, env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
    except OSError as exc:
        log.warning("tts daemon launch failed: %s", exc)
        return False

    # Budget kept short: the hook is on the agent's critical path, and failing over to the
    # direct worker is cheap and correct.
    deadline = time.time() + float(cfg.get("daemon.startWaitSec", 3))
    while time.time() < deadline:
        time.sleep(0.15)
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/healthz", timeout=0.3) as response:
                if response.status == 200:
                    log.info("tts daemon came up on %s", port)
                    return True
        except OSError:
            continue
    return False


def submit_hook(source: str, event: str, state: str, raw: bytes) -> int:
    payload = build_payload(source, event, state, raw)
    if payload is None:
        return 0
    cfg = Config()
    if not cfg.get("enabled", False):
        return 0
    if payload.get("state") and payload["state"] not in (cfg.get("events") or []):
        return 0
    if cfg.get("daemon.enabled", False):
        if _post(cfg, payload):
            return 0
        # The daemon is enabled but not answering. Autostart is logon-only and there is no
        # watchdog, so before this it stayed dead for the rest of the session and every
        # hook quietly took the unserialized direct path -- which is how overlapping
        # voices went unnoticed for 15 hours. Start it and try once more.
        if _ensure_daemon(cfg) and _post(cfg, payload):
            return 0
    if not _spawn_direct(payload):
        return direct_speak(payload)
    return 0


def direct_speak_file(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 1
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
    return direct_speak(payload)


def direct_speak(payload: dict) -> int:
    cfg = Config()
    if not cfg.get("enabled", False):
        return 0
    try:
        event = parse_event(payload)
    except EventError:
        return 1
    registry = Registry(
        voice_pool=list(cfg.get("voices.pool", []) or []),
        per_session_voice=bool(cfg.get("voices.perSession", False)),
        ttl_min=float(cfg.get("daemon.sessionTtlMin", 240)),
        persist_path=daemon_root() / "state" / "sessions.json",
    )
    registry.touch(event.session_key, event.source, event.project_name,
                   event.project_dir, event.pane, event.state)
    line = Summarizer(cfg).line_for_batch([event], registry)
    if not line:
        return 0
    voice = registry.get(event.session_key)
    selected_voice = (registry.voice_for(voice, str(cfg.get("kokoro.voice", "am_adam")))
                      if voice else "")
    # Several hooks can describe one user-facing event -- a Claude AskUserQuestion trips
    # Notification, PermissionRequest and PreToolUse -- and each spawns its own detached
    # worker. The daemon collapses those on one thread; here the shared history is the only
    # place these processes can agree on what has already been said.
    dedupe_sec = float(cfg.get("debounceSec", 5) or 0)
    if history.recently_spoken(event.session_key, event.priority, dedupe_sec):
        history.record(history.DEDUPED, event=event, line=line)
        log.info("duplicate suppressed: %s p%s already spoken within %.0fs",
                 event.session_key, event.priority, dedupe_sec)
        return 0

    with speaklock.hold(float(cfg.get("lock.waitSec", 30)),
                        float(cfg.get("lock.staleSec", 90))):
        # Re-check under the lock: a sibling worker may have spoken while we queued. This
        # second look is what actually collapses the three-hooks-one-event case, because
        # the first check raced with them.
        if history.recently_spoken(event.session_key, event.priority, dedupe_sec):
            history.record(history.DEDUPED, event=event, line=line)
            return 0

        started = time.monotonic()
        synth = Synth(cfg)
        result = synth.synthesize(line, selected_voice)
        synth_ms = int((time.monotonic() - started) * 1000)
        if result is None:
            history.record("synth_failed", event=event, line=line)
            return 1

        playback = Playback()
        play_started = time.monotonic()
        spoke = result.media is not None and playback.play(result.media)
        if not spoke:
            spoke = playback.speak_sapi(result.sapi_text or line)
        history.record(
            history.SPOKEN if spoke else "play_failed", event=event, line=line,
            engine=str(getattr(result, "engine", "") or ""), synth_ms=synth_ms,
            play_ms=int((time.monotonic() - play_started) * 1000),
        )
        history.prune(float(cfg.get("history.days", 14)))
        return 0 if spoke else 1


def test_payload(source: str) -> dict:
    project = Path.cwd().name or "a project"
    return {
        "v": 1, "source": source, "host": "windows", "event": "stop",
        "state": "waiting", "session_key": f"{source}:cc-tts-test",
        "project": {"dir": str(Path.cwd()), "name": project},
        "cwd": str(Path.cwd()), "transcript_path": "", "override": "",
        "message": {"text": "", "error_type": "", "notification_type": "",
                    "tool_name": "", "stop_status": ""},
        "wezterm": {"pane": str(os.environ.get("WEZTERM_PANE") or "")},
        "ts": time.time(),
    }
