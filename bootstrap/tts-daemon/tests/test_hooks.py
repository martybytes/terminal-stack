"""Hook normalization tests — no network, audio, or Windows UI required."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ttsd.hooks import build_payload


def raw(value: dict) -> bytes:
    return json.dumps(value).encode("utf-8")


def test_claude_stop_payload():
    payload = build_payload(
        "claude", "stop", "waiting",
        raw({"session_id": "s1", "cwd": "C:/work/alpha",
             "last_assistant_message": "Finished the change."}),
    )
    assert payload is not None
    assert payload["source"] == "claude"
    assert payload["session_key"] == "claude:s1"
    assert payload["project"]["name"] == "alpha"
    assert payload["message"]["text"] == "Finished the change."


def test_claude_question_extracts_question():
    payload = build_payload(
        "claude", "question", "question",
        raw({"tool_input": {"questions": [{"question": "Which port?"}]}}),
    )
    assert payload is not None
    assert payload["state"] == "question"
    assert payload["override"] == "Which port?"


def test_codex_request_user_input_extracts_question():
    payload = build_payload(
        "codex", "question", "question",
        raw({
            "session_id": "c1",
            "cwd": "C:/work/obsidian-marty",
            "tool_name": "request_user_input",
            "tool_input": {"questions": [{"question": "Which calendar?"}]},
        }),
    )
    assert payload is not None
    assert payload["source"] == "codex"
    assert payload["session_key"] == "codex:c1"
    assert payload["state"] == "question"
    assert payload["override"] == "Which calendar?"


def test_cursor_aborted_stop_is_silent():
    assert build_payload(
        "cursor", "cursor_stop", "waiting", raw({"status": "aborted"}),
    ) is None


def test_cursor_completed_stop_is_silent_because_response_hook_speaks():
    assert build_payload(
        "cursor", "cursor_stop", "waiting", raw({"status": "completed"}),
    ) is None


def test_cursor_after_response_preserves_completion_text():
    payload = build_payload(
        "cursor", "cursor_response", "waiting",
        raw({"conversation_id": "c1", "text": "Implemented and tested."}),
    )
    assert payload is not None
    assert payload["state"] == "waiting"
    assert payload["message"]["text"] == "Implemented and tested."


def test_cursor_error_stop_is_normalized():
    payload = build_payload(
        "cursor", "cursor_stop", "waiting",
        raw({"status": "error", "conversation_id": "c1",
             "workspace_roots": ["C:/work/beta"]}),
    )
    assert payload is not None
    assert payload["state"] == "error"
    assert payload["session_key"] == "cursor:c1"
    assert payload["project"]["name"] == "beta"


def test_cursor_non_question_tool_is_silent():
    assert build_payload(
        "cursor", "cursor_question", "question",
        raw({"tool_name": "Read", "tool_input": {}}),
    ) is None


def test_codex_response_text_is_preserved():
    payload = build_payload(
        "codex", "stop", "waiting",
        raw({"thread_id": "t1", "cwd": "C:/work/gamma",
             "afterAgentResponse": {"text": "Implemented and tested."}}),
    )
    assert payload is not None
    assert payload["session_key"] == "codex:t1"
    assert payload["message"]["text"] == "Implemented and tested."


# ── never silence: an unusable state root must not take the process down ──────
#
# Both of these were unguarded, and a live run with LOCALAPPDATA pointing at a file
# crashed the EXE with a FileNotFoundError before it said a word. Losing the log or the
# spawn is a nuisance; dying on the way to speech is a fault.

def _unusable_state_root(tmp_path, monkeypatch):
    """Point LOCALAPPDATA at a regular file, so every mkdir beneath it fails."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("file where the state directory should be", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(blocker))
    return blocker


def test_logging_setup_survives_an_unusable_state_root(tmp_path, monkeypatch):
    import logging

    from ttsd.__main__ import _setup_logging

    _unusable_state_root(tmp_path, monkeypatch)
    root = logging.getLogger()
    saved = root.handlers[:]
    try:
        _setup_logging(console=False)  # must not raise
    finally:
        root.handlers[:] = saved


def test_spawn_direct_reports_failure_instead_of_raising(tmp_path, monkeypatch):
    """Returning False is what makes submit_hook fall back to speaking in-process."""
    from ttsd.hooks import _spawn_direct

    _unusable_state_root(tmp_path, monkeypatch)
    assert _spawn_direct({"v": 1, "source": "claude"}) is False


def test_claude_idle_reminder_is_silent_because_stop_already_spoke():
    """idle_prompt repeats the Stop announcement a minute later, and used to say it as a question."""
    assert build_payload(
        "claude", "notification", "question",
        raw({"session_id": "s1", "notification_type": "idle_prompt",
             "message": "Claude is waiting for your input"}),
    ) is None


def test_claude_other_notifications_still_speak_as_questions():
    payload = build_payload(
        "claude", "notification", "question",
        raw({"session_id": "s1", "notification_type": "permission_prompt",
             "message": "Claude needs your permission to use Bash"}),
    )
    assert payload is not None
    assert payload["state"] == "question"
    assert payload["override"] == "Claude needs your permission to use Bash"


def _submit_with(monkeypatch, entrypoint, speak_sdk=None):
    """Run submit_hook with the daemon POST stubbed; returns (rc, posted payloads)."""
    import ttsd.hooks as hooks

    settings = {"enabled": True, "daemon.enabled": True,
                "events": ["waiting", "error", "question", "permission"]}
    if speak_sdk is not None:
        settings["sources.claude.speakSdk"] = speak_sdk

    class _Cfg:
        def get(self, dotted, default=None):
            return settings.get(dotted, default)

    posted = []
    monkeypatch.setattr(hooks, "Config", _Cfg)
    monkeypatch.setattr(hooks.mute, "is_muted", lambda: False)
    monkeypatch.setattr(hooks, "_post", lambda cfg, payload: posted.append(payload) or True)
    monkeypatch.setattr(hooks, "_spawn_direct", lambda *a, **k: False)
    monkeypatch.delenv("CC_TTS_REPORT_DISABLED", raising=False)
    if entrypoint is None:
        monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    else:
        monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", entrypoint)
    rc = hooks.submit_hook("claude", "stop", "waiting",
                           raw({"session_id": "s1", "cwd": "C:/work/forge42"}))
    return rc, posted


def test_sdk_driven_claude_session_is_silent_by_default(monkeypatch):
    """Obsidian's Claudian runs claude.exe through the SDK with the user's hooks."""
    rc, posted = _submit_with(monkeypatch, "sdk-ts")
    assert rc == 0
    assert posted == []


def test_sdk_driven_claude_session_speaks_when_opted_in(monkeypatch):
    rc, posted = _submit_with(monkeypatch, "sdk-ts", speak_sdk=True)
    assert rc == 0
    assert len(posted) == 1


def test_terminal_claude_session_still_speaks(monkeypatch):
    for entrypoint in ("cli", None):
        _, posted = _submit_with(monkeypatch, entrypoint)
        assert len(posted) == 1, entrypoint


def test_sdk_gate_applies_to_claude_only(monkeypatch):
    from ttsd.hooks import is_sdk_session

    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "sdk-ts")
    assert is_sdk_session("claude")
    assert not is_sdk_session("cursor")
    assert not is_sdk_session("codex")
