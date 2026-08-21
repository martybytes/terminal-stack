"""Focused tests for the Codex rollout/dashboard helper."""

import importlib.util
import json
import sys
from pathlib import Path


HELPER = Path(__file__).resolve().parents[1] / "dot_codex/hooks/terminal_stack.py"
SPEC = importlib.util.spec_from_file_location("terminal_stack_codex", HELPER)
assert SPEC and SPEC.loader
codex = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = codex
SPEC.loader.exec_module(codex)


def test_bar_thresholds_and_size():
    assert codex.GREEN in codex.bar(69)
    assert codex.YELLOW in codex.bar(70)
    assert codex.RED in codex.bar(90)
    assert codex.visible_len(codex.bar(42)) == 10


def test_patch_counts_add_delete_and_unified_update():
    item = {
        "changes": [
            {"kind": "add", "content": "one\ntwo\n"},
            {"kind": "delete", "content": "old\n"},
            {"kind": "update", "unified_diff": "--- a/x\n+++ b/x\n-old\n+new\n+more\n"},
        ]
    }
    assert codex.count_patch(item) == (4, 2)


def test_rollout_token_context_and_patch_dedupe():
    state = codex.RolloutState()
    state.consume({"type": "turn_context", "payload": {
        "model": "gpt-test", "effort": "high", "approval_policy": "never",
        "sandbox_policy": {"type": "danger-full-access"},
    }})
    state.consume({"type": "event_msg", "payload": {
        "type": "token_count",
        "info": {
            "last_token_usage": {"total_tokens": 250},
            "total_token_usage": {"total_tokens": 800},
            "model_context_window": 1000,
        },
        "rate_limits": {"primary": {"used_percent": 40, "window_minutes": 300}},
    }})
    patch = {"type": "event_msg", "payload": {"type": "patch_apply_end",
             "call_id": "p1", "success": True, "diff": "-a\n+b\n+c\n"}}
    state.consume(patch)
    state.consume(patch)
    assert (state.model, state.effort, state.context_tokens, state.total_tokens) == (
        "gpt-test", "high", 250, 800)
    assert (state.added, state.removed) == (2, 1)
    assert "yolo" in codex.strip_ansi(codex.permission_label(state))


def test_incremental_reader(tmp_path):
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_text(json.dumps({"type": "session_meta", "payload": {
        "cli_version": "1.2.3", "cwd": str(tmp_path)}}) + "\n", encoding="utf-8")
    reader = codex.RolloutReader()
    reader.select(rollout)
    reader.refresh()
    assert reader.state.version == "1.2.3"
    with rollout.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"type": "turn_context", "payload": {
            "model": "next", "effort": "medium"}}) + "\n")
    reader.refresh()
    assert reader.state.model == "next"


def test_lines_fit_three_rows():
    state = codex.RolloutState(model="gpt-test", effort="high", version="1.0")
    git = {"branch": "main", "dirty": 2, "ahead": 1, "behind": 0, "repo": "owner/repo"}
    lines = codex.dashboard_lines("/work/repo", state, git, 50)
    assert len(lines) == 3
    assert all(codex.visible_len(line) <= 50 for line in lines)
