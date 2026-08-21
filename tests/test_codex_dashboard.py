"""Focused tests for the Codex rollout/dashboard helper."""

import importlib.util
import json
import sys
import tomllib
from pathlib import Path


HELPER = Path(__file__).resolve().parents[1] / "dot_codex/hooks/terminal_stack.py"
PROFILE = Path(__file__).resolve().parents[1] / "dot_codex/terminal-stack.config.toml.tmpl"
SPEC = importlib.util.spec_from_file_location("terminal_stack_codex", HELPER)
assert SPEC and SPEC.loader
codex = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = codex
SPEC.loader.exec_module(codex)


def test_enhanced_profile_hides_native_status_line():
    profile = tomllib.loads(PROFILE.read_text(encoding="utf-8"))
    assert profile["tui"]["status_line"] == []


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
            "total_token_usage": {
                "total_tokens": 800, "input_tokens": 500, "output_tokens": 200,
                "cached_input_tokens": 100, "reasoning_output_tokens": 50,
            },
            "model_context_window": 1000,
        },
        "rate_limits": {
            "primary": {"used_percent": 40, "window_minutes": 300},
            "plan_type": "team", "credits": {"balance": "12.5", "unlimited": False},
        },
    }})
    patch = {"type": "event_msg", "payload": {"type": "patch_apply_end",
             "call_id": "p1", "success": True, "diff": "-a\n+b\n+c\n"}}
    state.consume(patch)
    state.consume(patch)
    assert (state.model, state.effort, state.context_tokens, state.total_tokens) == (
        "gpt-test", "high", 250, 800)
    assert (state.input_tokens, state.output_tokens, state.cached_tokens) == (500, 200, 100)
    assert (state.plan_type, state.credit_balance) == ("team", "12.5")
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
    state = codex.RolloutState(
        model="gpt-test", effort="high", version="1.0", activity="TOOL",
        current_action="edit 2 files", turn_started=900, turn_active=True,
        context_tokens=600, context_window=1000, total_tokens=800,
        input_tokens=500, output_tokens=200, cached_tokens=100,
        added=12, removed=3, approval="never", sandbox="danger-full-access",
        rates=[
            {"used_percent": 40, "window_minutes": 300, "resets_at": 1200},
            {"used_percent": 75, "window_minutes": 10080, "resets_at": 9999},
        ],
    )
    git = {
        "branch": "feature", "upstream": "origin/feature", "dirty": 5,
        "staged": 1, "modified": 2, "deleted": 1, "untracked": 1,
        "conflicts": 0, "ahead": 1, "behind": 2, "repo": "owner/repo",
        "root": "/work/repo", "stash": 2, "commit_age": 90, "worktree": True,
    }
    pr = {"number": "42", "review": "approved", "ci": "pass", "merge": "ready"}
    wide = codex.dashboard_lines(
        "/work/repo/src", state, git, 500, pr=pr, launched_at=800, now=1000,
        audio_fault="TTS daemon offline",
    )
    plain = [codex.strip_ansi(line) for line in wide]
    assert len(wide) == 3
    assert "owner/repo" in plain[0] and "origin/feature" in plain[0]
    assert "stashes" in plain[1] and "PR #42" in plain[1]
    assert "[TOOL]" in plain[2] and "5h" in plain[2] and "weekly" in plain[2]
    assert "TTS daemon offline" in plain[2]
    assert "codex 1.0" in plain[2]

    narrow = codex.dashboard_lines("/work/repo/src", state, git, 50, pr=pr, now=1000)
    assert len(narrow) == 3
    assert all(codex.visible_len(line) <= 50 for line in narrow)
    assert "feature" in codex.strip_ansi(narrow[0])
    assert "±12/3" in codex.strip_ansi(narrow[1])


def test_activity_lifecycle_and_failed_tool():
    state = codex.RolloutState()
    state.consume({"type": "event_msg", "payload": {"type": "task_started", "started_at": 100}})
    assert state.turn_active and state.activity == "THINK"
    state.consume({"type": "event_msg", "payload": {"type": "item_completed", "item": {
        "type": "CommandExecution", "command": "pytest -q", "status": "failed", "exit_code": 1,
    }}})
    assert state.activity == "TOOL" and "pytest" in state.current_action
    assert state.tool_failures == 1
    state.consume({"type": "event_msg", "payload": {"type": "task_complete", "duration_ms": 2500}})
    assert not state.turn_active and state.activity == "DONE" and state.last_turn_seconds == 2.5


def test_pr_health_summary():
    raw = {
        "number": 9, "isDraft": False, "reviewDecision": "APPROVED",
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": [{"status": "COMPLETED", "conclusion": "SUCCESS"}],
    }
    assert codex.pr_health(raw) == {
        "number": "9", "review": "approved", "ci": "pass", "merge": "ready",
    }
    raw["statusCheckRollup"] = [{"status": "COMPLETED", "conclusion": "FAILURE"}]
    assert codex.pr_health(raw)["ci"] == "fail"
