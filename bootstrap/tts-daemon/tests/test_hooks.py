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
