"""Regression tests for per-machine, user-global coding-agent integrations."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "bootstrap/agent-tools.json"
PS_ADAPTER = ROOT / "bootstrap/ts-agents.ps1"


def test_manifest_pins_reviewed_versions_and_local_endpoints():
    cfg = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert cfg["headroom"]["version"] == "0.36.3"
    assert cfg["headroom"]["dockerImage"] == "ghcr.io/chopratejas/headroom:0.36.3"
    assert cfg["headroom"]["proxyUrl"] == "http://127.0.0.1:8787"
    assert cfg["headroom"]["mcpUrl"] == "http://127.0.0.1:8788/mcp"
    assert cfg["caveman"]["version"] == "2.2.0"
    assert cfg["caveman"]["source"].endswith("#v2.2.0")
    assert cfg["agentmemory"]["version"] == "0.9.29"


def test_no_project_scope_or_docker_mutation_in_lifecycle_adapters():
    text = (PS_ADAPTER.read_text(encoding="utf-8") +
            (ROOT / "bootstrap/ts-agents.sh").read_text(encoding="utf-8"))
    assert "--scope','project" not in text
    assert "--scope project" not in text
    assert "docker compose" not in text.lower()
    assert "docker rm" not in text.lower()
    assert "restart: unless-stopped" not in text.lower()


def test_launch_wrappers_are_process_local_and_have_stock_escape_hatches():
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(encoding="utf-8")
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    assert "function claude-stock" in ps and "function codex-stock" in ps
    assert "claude-stock()" in zsh and "codex-stock()" in zsh
    assert "finally" in ps and "$env:ANTHROPIC_BASE_URL = $savedBase" in ps
    assert "ANTHROPIC_BASE_URL=http://127.0.0.1:8787" in zsh
    assert "openai_base_url=\"http://127.0.0.1:8787/v1\"" in ps
    assert "openai_base_url=\"http://127.0.0.1:8787/v1\"" in zsh


def test_updates_reconcile_only_enabled_tools():
    ps = (ROOT / "scripts/sync-windows.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "run_after_90-sync-windows.sh").read_text(encoding="utf-8")
    for key in ("headroomEnabled", "cavemanEnabled", "agentmemoryEnabled"):
        assert key in ps
    for key in ("HEADROOM_ENABLED", "CAVEMAN_ENABLED", "AGENTMEMORY_ENABLED"):
        assert key in sh


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell 7 is unavailable")
def test_headroom_off_preserves_foreign_cursor_mcp(tmp_path):
    home = tmp_path / "home"
    cursor = home / ".cursor"
    cursor.mkdir(parents=True)
    mcp = cursor / "mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {
        "foreign": {"url": "http://127.0.0.1:9999/mcp"},
        "headroom": {"url": "http://127.0.0.1:8788/mcp"},
    }}), encoding="utf-8")
    env = os.environ.copy()
    env["USERPROFILE"] = str(home)
    env["PATH"] = ""
    result = subprocess.run(
        [shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-NonInteractive",
         "-File", str(PS_ADAPTER), "-Tool", "headroom", "-Action", "off"],
        env=env, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    servers = json.loads(mcp.read_text(encoding="utf-8"))["mcpServers"]
    assert servers == {"foreign": {"url": "http://127.0.0.1:9999/mcp"}}


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell 7 is unavailable")
def test_windows_config_preserves_agent_settings_when_other_values_change(tmp_path):
    home = tmp_path / "home"
    local = tmp_path / "local"
    home.mkdir()
    env = os.environ.copy()
    env.update({"USERPROFILE": str(home), "LOCALAPPDATA": str(local)})
    helper = ROOT / "bootstrap/_config.ps1"
    command = (
        f". '{helper}'; "
        "$null = Save-TsConfig -HeadroomEnabled on -HeadroomCursorMode byok "
        "-CavemanEnabled on -AgentmemoryEnabled off; "
        "$null = Save-TsConfig -ThemeMode light"
    )
    result = subprocess.run([shutil.which("pwsh"), "-NoLogo", "-NoProfile",
                             "-NonInteractive", "-Command", command],
                            env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    cfg = json.loads((local / "terminal-stack/config.json").read_text(encoding="utf-8-sig"))
    assert cfg["themeMode"] == "light"
    assert cfg["headroomEnabled"] == "on"
    assert cfg["headroomCursorMode"] == "byok"
    assert cfg["cavemanEnabled"] == "on"
    assert cfg["agentmemoryEnabled"] == "off"


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell 7 is unavailable")
def test_existing_agentmemory_install_migrates_missing_toggle_to_on(tmp_path):
    home = tmp_path / "home"
    local = tmp_path / "local"
    (home / ".claude/plugins/cache/agentmemory/agentmemory/0.9.29").mkdir(parents=True)
    cfg_path = local / "terminal-stack/config.json"
    cfg_path.parent.mkdir(parents=True)
    cfg_path.write_text(json.dumps({
        "leaderChord": "ctrl-space", "themeMode": "dark", "tmuxPrefix": "ctrl-b",
        "weztermMux": "off", "weztermRestore": "off", "apps": [],
    }), encoding="utf-8")
    env = os.environ.copy()
    env.update({"USERPROFILE": str(home), "LOCALAPPDATA": str(local)})
    helper = ROOT / "bootstrap/_config.ps1"
    command = f". '{helper}'; $null = Save-TsConfig"
    result = subprocess.run([shutil.which("pwsh"), "-NoLogo", "-NoProfile",
                             "-NonInteractive", "-Command", command],
                            env=env, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    assert cfg["agentmemoryEnabled"] == "on"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_shell_entrypoints_parse():
    files = [
        "bootstrap/_config.sh", "bootstrap/_wizard.sh", "bootstrap/ts-config.sh",
        "bootstrap/ts-agents.sh", "bootstrap/wsl-bootstrap.sh",
        "bootstrap/linux-bootstrap.sh", "bootstrap/mac-bootstrap.sh",
        "run_after_90-sync-windows.sh", "dot_zshrc",
    ]
    result = subprocess.run([shutil.which("bash"), "-n", *files], cwd=ROOT,
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
