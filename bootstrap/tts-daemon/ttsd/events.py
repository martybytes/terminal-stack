"""Event normalization: hook POST bodies → internal Event objects.

The senders (cc-tts-lib.sh / cc-tts-lib.ps1) pre-map every hook to a legacy
`state` (waiting|error|question|permission), so an unknown future `event`
string still schedules correctly off its state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# Priority classes (lower = more urgent).
P0_INTERACTIVE = 0  # question / permission — Claude is blocked on the user
P1_ERROR = 1
P2_DONE = 2
P3_INFO = 3

# Events that signal "the user is already engaged with this session";
# they carry no speech, only registry activity + barge-in.
ACTIVITY_EVENTS = {"prompt_submit", "session_start", "working"}
SESSION_END_EVENTS = {"session_end"}

_STATE_CLASS = {
    "question": P0_INTERACTIVE,
    "permission": P0_INTERACTIVE,
    "error": P1_ERROR,
    "waiting": P2_DONE,
}


class EventError(ValueError):
    """Raised for a POST body we cannot schedule."""


@dataclass
class Event:
    source: str  # claude | cursor | test
    event: str  # stop, notification, cursor_stop, prompt_submit, ...
    state: str  # waiting | error | question | permission | "" (activity)
    session_key: str
    project_name: str
    project_dir: str = ""
    cwd: str = ""
    text: str = ""  # last_assistant_message / afterAgentResponse.text
    override: str = ""  # explicit spoken text (question body, notification msg)
    error_type: str = ""
    notification_type: str = ""
    tool_name: str = ""
    stop_status: str = ""
    transcript_path: str = ""
    pane: str = ""
    host: str = ""
    ts: float = field(default_factory=time.time)

    @property
    def priority(self) -> int:
        return _STATE_CLASS.get(self.state, P3_INFO)

    @property
    def is_activity(self) -> bool:
        return self.event in ACTIVITY_EVENTS

    @property
    def is_session_end(self) -> bool:
        return self.event in SESSION_END_EVENTS


def _text(value: object, limit: int = 20000) -> str:
    if not isinstance(value, str):
        return ""
    return value[:limit]


def parse_event(body: dict) -> Event:
    if not isinstance(body, dict):
        raise EventError("body must be a JSON object")
    source = _text(body.get("source")).lower()
    if source not in ("claude", "cursor", "test"):
        raise EventError(f"unknown source {source!r}")
    session_key = _text(body.get("session_key"), 256)
    if not session_key:
        raise EventError("session_key required")
    event = _text(body.get("event"), 64).lower()
    state = _text(body.get("state"), 32).lower()
    if not event and not state:
        raise EventError("event or state required")
    if state and state not in _STATE_CLASS and event not in ACTIVITY_EVENTS | SESSION_END_EVENTS:
        raise EventError(f"unknown state {state!r}")

    project = body.get("project") or {}
    if not isinstance(project, dict):
        project = {}
    message = body.get("message") or {}
    if not isinstance(message, dict):
        message = {}
    wezterm = body.get("wezterm") or {}
    if not isinstance(wezterm, dict):
        wezterm = {}

    name = _text(project.get("name"), 256)
    pdir = _text(project.get("dir"), 4096)
    cwd = _text(body.get("cwd"), 4096)
    if not name:
        leaf_source = pdir or cwd
        name = leaf_source.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] if leaf_source else "a project"

    ts = body.get("ts")
    return Event(
        source=source,
        event=event or state,
        state=state,
        session_key=session_key,
        project_name=name,
        project_dir=pdir,
        cwd=cwd,
        text=_text(message.get("text")),
        override=_text(body.get("override"), 2000),
        error_type=_text(message.get("error_type"), 64),
        notification_type=_text(message.get("notification_type"), 64),
        tool_name=_text(message.get("tool_name"), 128),
        stop_status=_text(message.get("stop_status"), 32),
        transcript_path=_text(body.get("transcript_path"), 4096),
        pane=_text(wezterm.get("pane"), 32),
        host=_text(body.get("host"), 16),
        ts=float(ts) if isinstance(ts, (int, float)) else time.time(),
    )
