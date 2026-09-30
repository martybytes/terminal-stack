"""wso: the two twins agree, and neither dies on the edge cases the audit found.

Bash functions run for real (sourced, with a per-machine workspace.local.conf
under a throwaway HOME); the PowerShell twin is held to the same behaviour by
text gates, since pwsh does not run in this suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.shell_support import BASH

ROOT = Path(__file__).resolve().parent.parent
WSO = ROOT / "bootstrap" / "wso.sh"
LIB = ROOT / "bootstrap" / "_workspace.sh"
PS_CMD = (ROOT / "bootstrap" / "_workspace_cmd.ps1").read_text(encoding="utf-8")
PS_LIB = (ROOT / "bootstrap" / "_workspace.ps1").read_text(encoding="utf-8")
needs_bash = pytest.mark.skipif(
    BASH is None or sys.platform == "win32",
    reason="needs bash; on Windows the pwsh twin is the implementation",
)


def _env(tmp_path: Path, conf: str = "") -> dict[str, str]:
    home = tmp_path / "home"
    (home / ".config" / "terminal-stack").mkdir(parents=True)
    (home / ".config" / "terminal-stack" / "workspace.local.conf").write_text(
        conf, encoding="utf-8"
    )
    root = tmp_path / "Workspace"
    (root / "src").mkdir(parents=True)
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "WORKSPACE_DIR": str(root),
        "NO_COLOR": "1",
    }


def _bash(env: dict[str, str], script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        start_new_session=True,
    )


def _lib(env: dict[str, str], body: str) -> str:
    got = _bash(
        env,
        f'ROOT="$WORKSPACE_DIR"; TS_WS_LIB_DIR="{ROOT / "bootstrap"}"; export TS_WS_LIB_DIR; . "{LIB}"; {body}',
    )
    assert got.returncode == 0, got.stderr
    return got.stdout.strip()


@needs_bash
def test_a_known_org_comes_back_in_workspace_conf_spelling(tmp_path):
    """A remote spelled MIXEDCASE filed under that case on Linux; sync then looked
    for the conf spelling, said it was missing, and synceverything cloned twice."""
    env = _env(tmp_path, "org MixedCase src\n")
    assert _lib(env, "ts_ws_canon_owner MIXEDCASE") == "MixedCase"
    assert _lib(env, "ts_ws_canon_owner mixedcase") == "MixedCase"
    assert _lib(env, "ts_ws_canon_owner Stranger") == "Stranger", "unknown owners keep their own"
    assert "MixedCase" in _lib(env, "ts_ws_own_owners").split()


@needs_bash
def test_a_trailing_org_flag_is_a_usage_error_not_a_silent_exit(tmp_path):
    """`shift 2` with one argument left failed under set -e: exit 1, no message."""
    env = _env(tmp_path)
    for verb in ("status", "plan", "sync", "synceverything", "archive"):
        got = _bash(env, f'bash "{WSO}" {verb} --org')
        assert got.returncode == 2, (verb, got.returncode, got.stderr)
        assert "--org needs a value" in got.stderr, verb


@needs_bash
def test_the_pin_cleanup_removes_assignments_only(tmp_path):
    """`sed '/TERMINAL_STACK_DIR/d'` also deleted comments and conditionals that
    merely mentioned the variable; the pwsh twin only ever removed assignments.
    (And `sed -i` itself failed on macOS, whose sed wants `-i ''`.)"""
    plps = tmp_path / "profile.local.ps1"
    plps.write_text(
        "# TERMINAL_STACK_DIR pins the clone\n"
        "$env:TERMINAL_STACK_DIR = 'C:\\x'\n"
        "if ($env:TERMINAL_STACK_DIR) { Write-Host hi }\n",
        encoding="utf-8",
    )
    src = (ROOT / "bootstrap/_cleanup.sh").read_text(encoding="utf-8")
    lines = [
        ln.strip()
        for ln in src.splitlines()
        if "TERMINAL_STACK_DIR[[:space:]]*=" in ln or '"$plps.tmp.$$" "$plps"' in ln
    ]
    assert len(lines) == 2, lines
    cmd = f'plps="{plps.as_posix()}"\n' + "\n".join(lines)
    got = subprocess.run(
        [BASH, "-c", cmd],
        check=False,
        timeout=30,
        start_new_session=True,
        capture_output=True,
        text=True,
    )
    assert got.returncode == 0, got.stderr
    assert plps.read_text(encoding="utf-8") == (
        "# TERMINAL_STACK_DIR pins the clone\nif ($env:TERMINAL_STACK_DIR) { Write-Host hi }\n"
    )


def test_undo_last_survives_a_log_the_powershell_side_wrote():
    sh = WSO.read_text(encoding="utf-8")
    assert "dd=\"${dd%$'\\r'}\"" in sh, "bash strips a CRLF tail on read"
    assert "Add-Content -LiteralPath $log" not in PS_CMD, "pwsh no longer writes CRLF run logs"
    assert PS_CMD.count("| Add-TsWsLogLine $log") == 3
    assert 'AppendAllText($Log, "$Line`n"' in PS_CMD


def test_the_twins_agree_on_the_edge_cases():
    # workspace.conf spelling wins in both
    assert "OrgNames" in PS_LIB and "TS_WS_ORG_NAMES" in LIB.read_text(encoding="utf-8")
    # archive age floors in both (bash: integer division)
    assert "[Math]::Floor(($now - $act).TotalDays)" in PS_CMD
    # a trailing --org is refused in both, with the same words
    assert "'wso: --org needs a value'" in PS_CMD
    # pwsh reports failure through $LASTEXITCODE where bash returns 1
    assert PS_CMD.count("$global:LASTEXITCODE = 1") >= 3
    # no src orgs is said in both
    for text in (WSO.read_text(encoding="utf-8"), PS_CMD):
        assert "workspace.conf lists no src orgs" in text
    # the gh-not-found line says the same thing in both
    assert "Install it (wso doctor lists how)." in PS_CMD
    # the empty-tier count prints one number, not two
    assert "grep -c . || echo 0" not in WSO.read_text(encoding="utf-8")
    # the mangled doctor note is a proper string now
    ps_cleanup = (ROOT / "bootstrap/_cleanup.ps1").read_text(encoding="utf-8")
    assert (
        "\"  note: other terminal-stack clones present ('tstack doctor --repair' can clean them up):\""
        in ps_cleanup
    )
