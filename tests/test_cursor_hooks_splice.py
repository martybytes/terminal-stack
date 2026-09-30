"""~/.cursor/hooks.json on WSL/Linux/macOS is spliced per ENTRY, never copied.

docs/decisions.md § "Why `~/.cursor/hooks.json` needs per-entry ownership"
closed with: "The WSL-side dot_cursor/hooks.json.tmpl is still a whole-file
chezmoi target ... The day Cursor is wired to agentmemory inside WSL, it needs
a `modify_` script." That day was 2026-09-30: `tstack agents` wired Cursor to
agentmemory on WSL, `chezmoi diff` showed every AGENTMEMORY_URL entry about to
go, and `tstack update` refused the apply.

The modify_ script here is the POSIX twin of bootstrap/_merge_cursor_hooks.ps1.
Same three markers, same ours-then-theirs order, same "an event nobody uses any
more disappears" rule. These tests drive the real script (crudely rendered)
through subprocess, the way chezmoi runs it.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from tests.shell_support import BASH

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "dot_cursor/modify_hooks.json.tmpl"
PWSH_TWIN = ROOT / "bootstrap/_merge_cursor_hooks.ps1"
HOME = "/home/test"

AGENTMEMORY = (
    "AGENTMEMORY_URL=http://localhost:3111/_agent/cursor AGENTMEMORY_INJECT_CONTEXT=true "
    'node "/home/test/.cursor/hooks/agentmemory/%s.mjs"'
)


def _render(tts_on: bool) -> str:
    src = SCRIPT.read_text(encoding="utf-8")
    if tts_on:
        rendered = re.sub(r"\{\{-? if [^}]*\}\}|\{\{-? end \}\}", "", src)
    else:
        rendered = re.sub(r"\{\{-? if .*?\{\{-? end \}\}", "", src, flags=re.DOTALL)
    return re.sub(r"\{\{[^}]*\}\}", HOME, rendered)


@pytest.fixture
def splice(tmp_path):
    def run(live: str, *, tts_on: bool = True) -> subprocess.CompletedProcess:
        script = tmp_path / ("on.py" if tts_on else "off.py")
        script.write_text(_render(tts_on), encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(script)],
            input=live,
            text=True,
            capture_output=True,
            check=False,
            timeout=300,
            start_new_session=True,
        )

    return run


def _live_with_agentmemory() -> dict:
    """What `tstack agents` left on the WSL machine: our four entries first, then
    agentmemory's seven, two of them sharing our `stop` and `postToolUse`."""
    return {
        "version": 1,
        "hooks": {
            "afterFileEdit": [{"command": "cat > /dev/null", "timeout": 1}],
            "afterAgentResponse": [
                {"command": f"{HOME}/.cursor/hooks/cursor-tts-response.sh", "timeout": 15}
            ],
            "stop": [
                {"command": f"{HOME}/.cursor/hooks/cursor-tts.sh", "timeout": 15},
                {"command": AGENTMEMORY % "stop"},
            ],
            "postToolUse": [
                {
                    "matcher": "AskQuestion|AskUserQuestion",
                    "command": f"{HOME}/.cursor/hooks/cursor-tts-input.sh",
                    "timeout": 15,
                },
                {"command": AGENTMEMORY % "post-tool-use"},
            ],
            "sessionStart": [{"command": AGENTMEMORY % "session-start"}],
            "beforeSubmitPrompt": [{"command": AGENTMEMORY % "prompt-submit"}],
            "preToolUse": [
                {"command": AGENTMEMORY % "pre-tool-use", "matcher": "Shell|Read|Write|Grep"}
            ],
            "postToolUseFailure": [{"command": AGENTMEMORY % "post-tool-failure"}],
            "sessionEnd": [{"command": AGENTMEMORY % "session-end"}],
        },
    }


def _agentmemory_count(doc: dict) -> int:
    return sum("agentmemory" in e.get("command", "") for v in doc["hooks"].values() for e in v)


def test_posix_cursor_hooks_is_a_splice_not_a_whole_file_target():
    assert not (ROOT / "dot_cursor/hooks.json.tmpl").exists(), (
        "a whole-file hooks.json target deletes agentmemory's Cursor hooks"
    )
    assert SCRIPT.exists()
    assert os.access(SCRIPT, os.X_OK), "chezmoi modify_ scripts must be executable"
    body = SCRIPT.read_text(encoding="utf-8")
    assert body.startswith("#!"), "modify_ scripts need a shebang"
    assert "cursor-tts" in body and "cat > /dev/null" in body


def test_the_markers_match_the_pwsh_twin():
    """Twins: change one, change the other. The markers ARE the ownership rule."""
    ps = PWSH_TWIN.read_text(encoding="utf-8")
    ps_block = ps.split("$script:TsCursorHookMarkers = @(", 1)[1].split("\n)", 1)[0]
    ps_markers = set(re.findall(r"^\s*'([^']+)'", ps_block, flags=re.MULTILINE))
    py = SCRIPT.read_text(encoding="utf-8")
    py_block = py.split("MARKERS = (", 1)[1].split("\n)", 1)[0]
    py_markers = set(re.findall(r'^\s*"([^"]+)",', py_block, flags=re.MULTILINE))
    assert py_markers == ps_markers == {"terminal-stack", "cursor-tts", "cat > /dev/null"}


def test_agentmemory_entries_survive_in_the_events_we_share(splice):
    """The whole point. `stop` and `postToolUse` hold ours AND theirs."""
    live = _live_with_agentmemory()
    got = splice(json.dumps(live))
    assert got.returncode == 0, got.stderr
    out = json.loads(got.stdout)
    assert _agentmemory_count(out) == 7, "an agentmemory hook was destroyed by the splice"
    assert out == live, "an already-converged file must come back unchanged"
    # Ours first, theirs after, in the shared events.
    assert "cursor-tts.sh" in out["hooks"]["stop"][0]["command"]
    assert "agentmemory" in out["hooks"]["stop"][1]["command"]
    assert "cursor-tts-input.sh" in out["hooks"]["postToolUse"][0]["command"]


def test_the_splice_is_idempotent(splice):
    first = splice(json.dumps(_live_with_agentmemory()))
    second = splice(first.stdout)
    assert second.stdout == first.stdout


def test_turning_tts_off_removes_ours_and_only_ours(splice):
    """With TTS off we render no hooks at all -- so every marker has to carry
    the removal, including the marker-less-looking `cat > /dev/null` no-op."""
    got = splice(json.dumps(_live_with_agentmemory()), tts_on=False)
    assert got.returncode == 0, got.stderr
    out = json.loads(got.stdout)
    assert _agentmemory_count(out) == 7
    for event in ("afterFileEdit", "afterAgentResponse"):
        assert event not in out["hooks"], f"{event} was ours alone and must disappear"
    assert len(out["hooks"]["stop"]) == 1 and "agentmemory" in out["hooks"]["stop"][0]["command"]
    assert len(out["hooks"]["postToolUse"]) == 1
    assert "cursor-tts" not in got.stdout and "cat > /dev/null" not in got.stdout


def test_a_legacy_entry_is_replaced_not_duplicated(splice):
    """An older render (different timeout, a .ps1 path) matches on the marker,
    so an upgrade replaces it instead of double-speaking every event."""
    live = {
        "version": 1,
        "hooks": {
            "stop": [
                {"command": "pwsh -File C:/Users/x/.cursor/hooks/cursor-tts.ps1", "timeout": 5},
                {"command": AGENTMEMORY % "stop"},
            ]
        },
    }
    out = json.loads(splice(json.dumps(live)).stdout)
    assert len(out["hooks"]["stop"]) == 2
    assert out["hooks"]["stop"][0]["command"] == f"{HOME}/.cursor/hooks/cursor-tts.sh"
    assert "agentmemory" in out["hooks"]["stop"][1]["command"]


def test_unrelated_top_level_keys_and_live_event_order_survive(splice):
    live = {
        "somebodyElses": {"a": 1},
        "hooks": {"sessionEnd": [{"command": AGENTMEMORY % "session-end"}]},
        "version": 1,
    }
    got = splice(json.dumps(live))
    out = json.loads(got.stdout, object_pairs_hook=lambda p: p)
    keys = [k for k, _ in out]
    assert keys[0] == "somebodyElses", "the live file's key order is preserved"
    hooks = dict(out)["hooks"]
    events = [k for k, _ in hooks]
    assert events[0] == "sessionEnd", "live event order first, then template-only events"
    assert events[-1] == "postToolUse"


def test_an_unparseable_live_file_is_echoed_back_untouched(splice):
    broken = "{ not json"
    got = splice(broken)
    assert got.returncode == 0
    assert got.stdout == broken
    assert "leaving it untouched" in got.stderr
    got = splice("[1, 2]")
    assert got.stdout == "[1, 2]"


def test_a_fresh_machine_gets_the_fragment(splice):
    out = json.loads(splice("").stdout)
    assert out["version"] == 1
    assert set(out["hooks"]) == {"afterFileEdit", "afterAgentResponse", "stop", "postToolUse"}
    out = json.loads(splice("", tts_on=False).stdout)
    assert out == {"version": 1, "hooks": {}}


# --- ts-apply.sh: a modify_ target is never a "conflict" ---------------------
# `chezmoi status` marks a hand-edited modify_ target M in column 1 just like a
# plain file, but chezmoi APPLIES it without asking (2.70, verified): the script
# rebuilds the file from whatever is there. Reporting it made `tstack update`
# refuse the whole apply, with no TTY, over agentmemory's Cursor hooks.

FAKE_CHEZMOI = """#!/usr/bin/env bash
case "$1" in
  status)
    printf 'MM %s/.cursor/hooks.json\\n' "$FAKE_HOME"
    printf 'MM %s/.zshrc\\n' "$FAKE_HOME"
    printf ' M %s/.tmux.conf\\n' "$FAKE_HOME"
    ;;
  source-path)
    case "$3" in
      */.cursor/hooks.json) echo "$FAKE_SRC/dot_cursor/modify_hooks.json.tmpl" ;;
      */.zshrc) echo "$FAKE_SRC/dot_zshrc" ;;
      *) exit 1 ;;
    esac
    ;;
  *) exit 0 ;;
esac
"""


@pytest.mark.skipif(BASH is None, reason="needs bash")
def test_ts_apply_does_not_count_a_modify_target_as_a_conflict(tmp_path):
    fake = tmp_path / "chezmoi"
    fake.write_text(FAKE_CHEZMOI, encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    home = tmp_path / "home"
    home.mkdir()
    env = {
        **os.environ,
        "HOME": str(home),
        "FAKE_HOME": str(home),
        "FAKE_SRC": str(ROOT),
        "TERMINAL_STACK_CHEZMOI": str(fake),
        "NO_COLOR": "1",
    }
    got = subprocess.run(
        [BASH, str(ROOT / "bootstrap/ts-apply.sh"), "--check"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        start_new_session=True,
    )
    out = got.stdout + got.stderr
    assert got.returncode == 4, out
    assert "1 file(s) would make chezmoi stop and ask" in out
    assert ".zshrc" in out
    assert ".cursor/hooks.json" not in out, "a spliced file is re-spliced, never asked about"
    assert ".tmux.conf" not in out, "column 2 alone is a plain pending change"
