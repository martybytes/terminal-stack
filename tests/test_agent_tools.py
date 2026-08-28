"""Regression tests for per-machine, user-global coding-agent integrations."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.shell_support import BASH, bash_path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "bootstrap/agent-tools.json"


def repo_file(rel: str) -> Path:
    """A repo path a test asserts about, which therefore MUST exist.

    Tests shaped "string X must (not) appear in file Y" go silently vacuous the
    moment Y is deleted: `assert "docker compose" not in ""` passes forever while
    enforcing nothing. Routing every such test through here turns a moved or
    deleted target into a loud failure that names itself.
    """
    path = ROOT / rel
    assert path.exists(), (
        f"{rel} does not exist. If it moved, repoint this test. If its logic moved "
        f"into tstack/, repoint the assertion at the new module -- the rule outlives "
        f"the file that happened to implement it. Do not delete the test."
    )
    return path


def read_repo(rel: str) -> str:
    return repo_file(rel).read_text(encoding="utf-8")


def impl_paths(name: str) -> list[Path]:
    """Every file implementing a tstack subcommand right now, per commands.conf.

    Following the registry is what stops a rule from going quiet at port time: a
    test written against bootstrap/ts-agents.sh keeps enforcing itself once the
    subcommand becomes tstack/commands/agents.py, because this resolves to
    whatever the table currently points at.
    """
    out: list[Path] = []
    for row in read_repo("tstack/commands.conf").splitlines():
        row = row.strip()
        if not row or row.startswith("#"):
            continue
        fields = row.split(None, 3)
        if len(fields) < 4 or fields[0] != name:
            continue
        for token, owner in (
            (fields[1], "dot_zshrc"),
            (fields[2], "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1"),
        ):
            if token == "-":
                continue
            if token == "python":
                out.append(repo_file(f"tstack/commands/{name}.py"))
            elif token.startswith("@"):
                out.append(repo_file(owner))
            else:
                out.append(repo_file(token))
    assert out, f"{name!r} is not in tstack/commands.conf"
    return out


def test_manifest_pins_reviewed_versions_and_local_endpoints():
    cfg = json.loads(MANIFEST.read_text(encoding="utf-8"))
    # Repinned 2026-08-23: ghcr.io/chopratejas/headroom no longer resolves at all
    # (manifest 404), while ghcr.io/headroomlabs-ai/headroom:0.36.5 does (200).
    assert cfg["headroom"]["version"] == "0.36.5"
    assert cfg["headroom"]["dockerImage"] == "ghcr.io/headroomlabs-ai/headroom:0.36.5"
    assert cfg["headroom"]["proxyUrl"] == "http://127.0.0.1:8787"
    # Port 8788 serves dashboard only. MCP starts on demand through Docker stdio;
    # registering that command avoids Codex probing nonexistent HTTP /mcp.
    assert cfg["headroom"]["dashboardUrl"] == "http://127.0.0.1:8788/dashboard"
    assert "mcpUrl" not in cfg["headroom"]
    assert cfg["headroom"]["mcp"] == {
        "transport": "stdio",
        "container": "ts-headroom-proxy",
        "command": "headroom",
        "args": [
            "mcp",
            "serve",
            "--transport",
            "stdio",
            "--proxy-url",
            "http://127.0.0.1:8787",
        ],
    }
    assert cfg["caveman"]["version"] == "2.2.0"
    assert cfg["caveman"]["source"].endswith("#v2.2.0")
    assert cfg["agentmemory"]["version"] == "0.9.29"


def test_no_project_scope_or_docker_mutation_in_lifecycle_adapters():
    """ts-agents never runs docker itself: it prints the verb to run.

    Resolved through tstack/commands.conf so the rule survives the port. The old
    form read two hard-coded bootstrap paths and would have passed vacuously the
    day those files were deleted, enforcing nothing while looking green.
    """
    text = "".join(p.read_text(encoding="utf-8") for p in impl_paths("agents"))
    assert text.strip(), "agents implementation resolved to empty text"
    assert "--scope','project" not in text
    assert "--scope project" not in text
    assert "docker compose" not in text.lower()
    assert "docker rm" not in text.lower()
    assert "restart: unless-stopped" not in text.lower()


def test_launch_wrappers_are_process_local_and_have_stock_escape_hatches():
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    assert "function claude-stock" in ps and "function codex-stock" in ps
    assert "claude-stock()" in zsh and "codex-stock()" in zsh
    assert "finally" in ps and "$env:ANTHROPIC_BASE_URL = $savedBase" in ps
    assert "ANTHROPIC_BASE_URL=http://127.0.0.1:8787" in zsh
    assert 'ANTHROPIC_CUSTOM_HEADERS="$custom_headers"' in zsh
    assert "http://127.0.0.1:8787/stats" in zsh
    assert "X-Headroom-Proxy-Token" in zsh
    assert 'model_provider="headroom"' in zsh
    assert "model_providers.headroom.env_http_headers.X-Headroom-Proxy-Token" in zsh
    assert "model_providers.openai" not in zsh
    assert 'model_provider="headroom"' in ps
    assert "model_providers.headroom.env_http_headers.X-Headroom-Proxy-Token" in ps
    assert "model_providers.openai" not in ps
    assert 'openai_base_url="http://127.0.0.1:8787/v1"' in ps
    assert 'openai_base_url="http://127.0.0.1:8787/v1"' in zsh


def test_ts_update_owns_chezmoi_conflict_handling_and_runtime_guard():
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    update = zsh[zsh.index("_ts_chezmoi_conflicts() {") : zsh.index("_tstack_rollback() {")]
    assert "status --path-style absolute --exclude scripts" in update
    assert "[o]verwrite, [m]erge, [v]iew again, or [q]uit" in update
    assert "apply --dry-run --error-on-conflict --no-tty" in update
    assert "apply --error-on-conflict --no-tty" in update
    assert "apply --force --no-tty" in update
    assert "runtime clone has uncommitted changes" in update
    assert "Shell configuration changed" in update
    assert "Restart this shell now to activate the update? [Y/n]" in update
    assert "jobs -p" in update and "exec zsh" in update
    assert "runtime clone has uncommitted changes" in ps
    assert "PowerShell profile changed" in ps
    assert "Open a new PowerShell tab" in ps
    assert ps.index("runtime clone has uncommitted changes") < ps.index("fetch --quiet")


def test_codex_profile_is_partially_owned_on_every_sync_path():
    modifier = ROOT / "dot_codex/modify_private_terminal-stack.config.toml.tmpl"
    assert modifier.exists() and os.access(modifier, os.X_OK)
    assert not (ROOT / "dot_codex/terminal-stack.config.toml.tmpl").exists()
    body = modifier.read_text(encoding="utf-8")
    assert "hooks.state" in body and "state_sections" in body
    ps_sync = (ROOT / "scripts/sync-windows.ps1").read_text(encoding="utf-8")
    wsl_sync = (ROOT / "run_after_90-sync-windows.sh").read_text(encoding="utf-8")
    assert "StartsWith('modify_')" in ps_sync
    assert "== modify_*" in wsl_sync


def test_headroom_enable_requires_authenticated_proxy(monkeypatch, capsys):
    """`on` and `repair` must refuse while the proxy will not authenticate.

    Registering an MCP command that cannot answer leaves every client retrying a
    broken command on every start, silently.
    """
    from tstack.commands import agents

    out = agents.Out()
    headroom = agents.Headroom(ROOT, out, "mcp")
    monkeypatch.setattr(headroom, "probe_auth", lambda: (False, "HTTP 401"))
    registered = []
    monkeypatch.setattr(headroom, "register", lambda add: registered.append(add))

    assert headroom.run("on") == 1
    assert headroom.run("repair") == 1
    assert registered == [], "registrations were changed despite a failed probe"
    text = capsys.readouterr().out
    assert "HTTP 401" in text, "the reason must reach the person reading it"
    assert "leaving direct mode unchanged" in text
    assert "registrations were not changed" in text

    monkeypatch.setattr(headroom, "probe_auth", lambda: (True, ""))
    monkeypatch.setattr(headroom, "status", lambda: True)
    assert headroom.run("on") == 0
    assert registered == [True]


def test_turning_headroom_off_clears_the_saved_setting_too(capsys):
    """`off` must BOTH remove the client wiring and clear the saved setting, in
    that order. Asserted as intent rather than one exact line: playwright has no
    adapter call, so the arm is no longer a single statement."""
    config = read_repo("bootstrap/ts-config.sh")
    off_arm = config[config.index("        off)") :]
    off_arm = off_arm[: off_arm.index(";;")]
    assert 'run_agent_adapter "$tool" off' in off_arm
    assert 'ts_agent_set "$key" off' in off_arm


def test_pwsh_profile_caches_tool_init_instead_of_respawning():
    """A WezTerm pane spent most of a second spawning starship (twice), zoxide and
    the C# compiler before it drew a prompt. The generated init only changes when
    the binary does, so it is cached and dot-sourced."""
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    assert "function Get-TsToolInit" in ps
    # Keyed on the producing binary, or an upgrade would keep serving stale init.
    helper = ps[ps.index("function Get-TsToolInit") : ps.index("# ---- shell-init-cache-end ----")]
    assert "LastWriteTimeUtc.Ticks" in helper and ".Length" in helper
    # Hands back a file; the CALLER dot-sources it. Doing that inside the helper
    # would put starship's New-Module and zoxide's `function global:` in a scope
    # the prompt never sees.
    assert "[pscustomobject]@{ Path" in helper
    assert "\n    . $cache" not in helper and "\n        . $cache" not in helper
    # starship's own bootstrap re-runs starship; ask for the full init directly.
    assert "init powershell --print-full-init" in ps
    assert "Invoke-Expression (&starship init powershell)" not in ps
    assert "Invoke-Expression (& { (zoxide init powershell | Out-String) })" not in ps
    for tool in ("starship", "zoxide"):
        call = ps[ps.index(f"-Name {tool} -Exe") :]
        call = call[: call.index("\n") + 200]
        assert ". $tsInit.Path" in call, f"{tool} init is not dot-sourced from the cache"
    # fnm must NOT be cached: its output embeds a per-shell FNM_MULTISHELL_PATH.
    assert "-Name fnm -Exe" not in ps


def test_console_codepage_helper_is_compiled_once_not_per_shell():
    """Add-Type runs the C# compiler every session (~340ms per pane) and caches
    nothing between them, so the P/Invoke is precompiled to an assembly."""
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    block = ps[
        ps.index("if (-not ('Native.ConsoleCP' -as [type])) {") : ps.index(
            "[Native.ConsoleCP]::SetConsoleOutputCP(65001)"
        )
    ]
    assert "-OutputAssembly" in block and "Add-Type -Path" in block
    # Never compile straight onto the target: another pane may have it loaded.
    assert '$tsCpTmp = "$tsCpDll.$PID.tmp"' in block and "Move-Item" in block
    # And the in-memory compile stays as the fallback.
    assert block.count("-MemberDefinition $tsCpSrc") == 2


def test_fnm_ignores_package_json_engines_in_both_shells():
    """engines.node made every `cd` into a JS repo spawn fnm (738ms measured), and
    an engines range no fnm-INSTALLED version satisfies turned the cd into an
    interactive install prompt -- with a system node that already satisfied it."""
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    for name, text in (("dot_zshrc", zsh), ("$PROFILE", ps)):
        assert "--resolve-engines=false" in text, f"{name} still resolves package.json engines"
    # fnm before 1.36 has no such flag and exits non-zero; an empty eval would
    # leave fnm unwired with nothing printed, so both sides keep a fallback.
    assert '_ts_fnm_env="$(fnm env --use-on-cd --shell zsh 2>/dev/null)"' in zsh
    assert (
        "if (-not $tsFnmEnv.Trim()) { $tsFnmEnv = fnm env --use-on-cd --shell powershell | Out-String }"
        in ps
    )


def test_headroom_auth_probe_retries_and_names_the_failure(monkeypatch):
    """A single 2s probe called a cold proxy broken, and `on`/`repair` gate on it,
    so a slow first hit printed "registrations were not changed" with no cause -
    while the missing MCP registrations meant the fix stayed missing.

    Retry a connection failure; never retry a real HTTP answer; put the reason in
    the message.
    """
    import urllib.error

    from tstack.commands import agents

    headroom = agents.Headroom(ROOT, agents.Out(), "mcp")
    monkeypatch.setattr(headroom, "token", lambda: "t")

    attempts = []

    def refuse(request, timeout=None):
        attempts.append(timeout)
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(agents.urllib.request, "urlopen", refuse)
    assert headroom.probe_auth() == (False, "unreachable")
    assert attempts == [5, 5], "a connection failure must be retried exactly once"
    assert all(t == 5 for t in attempts), "2s produced false negatives on a cold container"

    attempts.clear()

    def unauthorized(request, timeout=None):
        attempts.append(timeout)
        raise urllib.error.HTTPError("u", 401, "no", {}, None)

    monkeypatch.setattr(agents.urllib.request, "urlopen", unauthorized)
    assert headroom.probe_auth() == (False, "HTTP 401")
    assert len(attempts) == 1, "a real HTTP answer is conclusive and must not be retried"

    monkeypatch.setattr(headroom, "token", lambda: "")
    ok, why = headroom.probe_auth()
    assert not ok and "HEADROOM_PROXY_TOKEN" in why


def test_the_headroom_token_is_never_printed(monkeypatch, capsys):
    """It is a credential. The probe reports HTTP status, never the value."""
    from tstack.commands import agents

    headroom = agents.Headroom(ROOT, agents.Out(), "mcp")
    monkeypatch.setattr(headroom, "token", lambda: "sekrit-token-value")
    monkeypatch.setattr(headroom, "probe_auth", lambda: (False, "unreachable"))
    monkeypatch.setattr(headroom, "mcp_spec", lambda: None)
    monkeypatch.setattr(agents, "find_agent", lambda name: None)
    headroom.status()
    assert "sekrit-token-value" not in capsys.readouterr().out


def test_headroom_mcp_uses_docker_stdio_and_removes_failed_registrations(monkeypatch):
    """Port 8788 is dashboard-only; the MCP server starts on demand over Docker
    stdio. Registering it without proving the handshake leaves Codex probing a
    command that cannot answer, so a failed probe REMOVES stale registrations
    rather than leaving them."""
    from tstack.commands import agents

    calls = []
    monkeypatch.setattr(agents, "find_agent", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(agents, "_run", lambda argv, timeout=60, stdin=None: calls.append(argv))
    written = []
    monkeypatch.setattr(agents, "_write_cursor_mcp", lambda name, entry: written.append(entry))

    headroom = agents.Headroom(ROOT, agents.Out(), "mcp")
    monkeypatch.setattr(headroom, "mcp_spec", lambda: ("/usr/bin/docker", ["exec", "-i", "c", "x"]))
    monkeypatch.setattr(headroom, "mcp_ready", lambda: True)
    monkeypatch.setattr(agents.Path, "is_dir", lambda self: True)
    headroom.register(add=True)
    flat = [" ".join(c) for c in calls]
    assert any("mcp add --scope user headroom -- /usr/bin/docker exec -i c x" in f for f in flat)
    assert any("codex mcp add headroom -- /usr/bin/docker exec -i c x" in f for f in flat)
    assert written and written[-1]["command"] == "/usr/bin/docker"

    calls.clear()
    written.clear()
    monkeypatch.setattr(headroom, "mcp_ready", lambda: False)
    headroom.mcp_reason = "docker MCP command failed"
    headroom.register(add=True)
    flat = [" ".join(c) for c in calls]
    assert any("mcp remove --scope user headroom" in f for f in flat)
    assert any("codex mcp remove headroom" in f for f in flat)
    assert written == [None], "a failed handshake must clear the Cursor entry"
    assert not any("mcp add" in f for f in flat)


def test_the_mcp_handshake_is_json_rpc_not_a_port_check(monkeypatch):
    """`initialize` has to come back naming headroom AND advertising tools. A
    container that merely accepts stdin is not an MCP server."""
    from tstack.commands import agents

    headroom = agents.Headroom(ROOT, agents.Out(), "mcp")
    monkeypatch.setattr(headroom, "mcp_spec", lambda: ("/usr/bin/docker", ["exec"]))

    class Got:
        returncode = 0
        stdout = ""

    monkeypatch.setattr(agents, "_run", lambda argv, timeout=60, stdin=None: Got())
    Got.stdout = '{"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"other"}}}'
    assert headroom.mcp_ready() is False
    assert "not a Headroom MCP server" in headroom.mcp_reason

    Got.stdout = (
        '{"jsonrpc":"2.0","id":1,"result":{"serverInfo":{"name":"headroom"},'
        '"capabilities":{"tools":{}}}}'
    )
    assert headroom.mcp_ready() is True

    Got.returncode = 1
    assert headroom.mcp_ready() is False
    assert "docker MCP command failed" in headroom.mcp_reason


def test_the_codex_registration_check_requires_stdio_transport(monkeypatch):
    from tstack.commands import agents

    class Got:
        returncode = 0
        stdout = "transport: stdio\ncommand: /usr/bin/docker\nargs: exec -i c x\n"

    monkeypatch.setattr(agents, "find_agent", lambda name: "/usr/bin/codex")
    monkeypatch.setattr(agents, "_run", lambda argv, timeout=60, stdin=None: Got())
    headroom = agents.Headroom(ROOT, agents.Out(), "mcp")
    spec = ("/usr/bin/docker", ["exec", "-i", "c", "x"])
    assert headroom.codex_registered(spec) is True

    Got.stdout = "transport: http\ncommand: /usr/bin/docker\n"
    assert headroom.codex_registered(spec) is False


def test_claude_instructions_fit_claude_code_limit():
    assert (ROOT / "CLAUDE.md").stat().st_size <= 40_000


def test_updates_reconcile_only_enabled_tools():
    ps = (ROOT / "scripts/sync-windows.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "run_after_90-sync-windows.sh").read_text(encoding="utf-8")
    for key in ("headroomEnabled", "cavemanEnabled", "agentmemoryEnabled"):
        assert key in ps
    for key in ("HEADROOM_ENABLED", "CAVEMAN_ENABLED", "AGENTMEMORY_ENABLED"):
        assert key in sh


def test_headroom_off_preserves_foreign_cursor_mcp(tmp_path, monkeypatch):
    """Cursor's mcp.json belongs to the user: removing our entry must leave every
    other server exactly as it was, and never rewrite a file we cannot parse."""
    from tstack.commands import agents

    home = tmp_path / "home"
    cursor = home / ".cursor"
    cursor.mkdir(parents=True)
    mcp = cursor / "mcp.json"
    mcp.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "foreign": {"url": "http://127.0.0.1:9999/mcp"},
                    "headroom": {"command": "docker", "args": ["exec"]},
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(agents, "user_root", lambda: home)
    agents._write_cursor_mcp("headroom", None)
    servers = json.loads(mcp.read_text(encoding="utf-8"))["mcpServers"]
    assert servers == {"foreign": {"url": "http://127.0.0.1:9999/mcp"}}
    assert list(cursor.glob("mcp.json.bak.*")), "the file was rewritten with no backup"


def test_a_malformed_cursor_config_is_never_overwritten(tmp_path, monkeypatch, capsys):
    from tstack.commands import agents

    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    mcp = home / ".cursor" / "mcp.json"
    mcp.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(agents, "user_root", lambda: home)
    agents._write_cursor_mcp("headroom", {"command": "docker", "args": []})
    assert mcp.read_text(encoding="utf-8") == "{ not json"
    assert "refusing to overwrite malformed JSON" in capsys.readouterr().err


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
    result = subprocess.run(
        [shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )
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
    cfg_path.write_text(
        json.dumps(
            {
                "leaderChord": "ctrl-space",
                "themeMode": "dark",
                "tmuxPrefix": "ctrl-b",
                "weztermMux": "off",
                "weztermRestore": "off",
                "apps": [],
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update({"USERPROFILE": str(home), "LOCALAPPDATA": str(local)})
    helper = ROOT / "bootstrap/_config.ps1"
    command = f". '{helper}'; $null = Save-TsConfig"
    result = subprocess.run(
        [shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )
    assert result.returncode == 0, result.stderr
    cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    assert cfg["agentmemoryEnabled"] == "on"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_shell_entrypoints_parse():
    # dot_zshrc is deliberately NOT in this list: it is a zsh file and uses zsh-only
    # syntax (glob patterns in [[ ]], ${(P)var}, typeset -g "$var=..."), so `bash -n`
    # rejects it. It gets its own zsh gate below.
    files = [
        "bootstrap/_config.sh",
        "bootstrap/_wizard.sh",
        "bootstrap/ts-config.sh",
        "bootstrap/ts-agents.sh",
        "bootstrap/wsl-bootstrap.sh",
        "bootstrap/linux-bootstrap.sh",
        "bootstrap/mac-bootstrap.sh",
        "run_after_90-sync-windows.sh",
        # These were never covered by the gate; a syntax error in any of them
        # only showed up when someone ran the command.
        "bootstrap/wso.sh",
        "bootstrap/_workspace.sh",
        "bootstrap/_common-debian.sh",
        "bootstrap/ts-smb.sh",
        "bootstrap/_smb.sh",
        "bootstrap/_smb_setup.sh",
        "bootstrap/ts-rclone-config.sh",
    ]
    result = subprocess.run(
        [BASH, "-n", *files],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh is unavailable")
def test_zshrc_parses_under_zsh():
    result = subprocess.run(
        [shutil.which("zsh"), "-n", "dot_zshrc"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )
    assert result.returncode == 0, result.stderr


# PowerShell variable names are case-insensitive, so a local named $foo inside a
# function that takes a parameter $Foo IS that parameter. When the parameter is
# typed, its converter stays attached to the variable and coerces every later
# assignment: Read-TsMulti assigned a scriptblock to $exclusive alongside a
# [string[]]$Exclusive parameter, the block became a one-element string array of
# its own source text, and `& $exclusive -1` tried to run that text as a command
# name. Every Read-TsMulti call died, which is the entire Windows wizard. The
# bug is invisible in review and the bash twins cannot have it (bash keeps
# functions and variables in separate namespaces), so it needs a gate.
_PS_COLLISION_SCAN = r"""
$bad = @()
foreach ($f in (Get-ChildItem -Path . -Recurse -Include *.ps1,*.psm1 -File |
                Where-Object { $_.FullName -notmatch '[\\/]\.git[\\/]' })) {
    $errs = $null
    $ast = [System.Management.Automation.Language.Parser]::ParseFile(
        $f.FullName, [ref]$null, [ref]$errs)
    if ($errs -and $errs.Count) { $bad += "PARSE $($f.Name): $($errs[0].Message)"; continue }
    foreach ($fn in $ast.FindAll({ param($n)
            $n -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true)) {
        $ps = @()
        if ($fn.Parameters) { $ps += $fn.Parameters }
        if ($fn.Body.ParamBlock) { $ps += $fn.Body.ParamBlock.Parameters }
        $typed = @{}
        foreach ($p in $ps) {
            if ($p.StaticType -and $p.StaticType.FullName -ne 'System.Object') {
                $typed[$p.Name.VariablePath.UserPath] = $p.StaticType.FullName
            }
        }
        if ($typed.Count -eq 0) { continue }
        foreach ($a in $fn.Body.FindAll({ param($n)
                $n -is [System.Management.Automation.Language.AssignmentStatementAst] }, $true)) {
            if ($a.Left -isnot [System.Management.Automation.Language.VariableExpressionAst]) { continue }
            $name = $a.Left.VariablePath.UserPath
            foreach ($k in $typed.Keys) {
                if ($name -ceq $k) { continue }
                if ($name -ieq $k) {
                    $bad += ("{0}:{1} {2}() assigns `${3}, which IS the [{4}]`${5} parameter" -f
                        $f.Name, $a.Left.Extent.StartLineNumber, $fn.Name, $name, $typed[$k], $k)
                }
            }
        }
    }
}
if ($bad) { $bad | ForEach-Object { Write-Output $_ }; exit 1 }
exit 0
"""


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell 7 is unavailable")
def test_no_pwsh_local_shadows_a_typed_parameter():
    result = subprocess.run(
        [
            shutil.which("pwsh"),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            _PS_COLLISION_SCAN,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# --- agent CLI resolution ----------------------------------------------------
# Regression cover for the bug where `ccd` died with "claude executable was not
# found on PATH when this shell loaded" in every top-level login shell: the
# resolver ran ~650 lines before ~/.local/bin was added to PATH, and it cached
# the (empty) result for the life of the shell.


def test_local_bin_is_on_path_before_the_agent_resolvers():
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    export_at = zsh.index('export PATH="$HOME/.local/bin:$PATH"')
    resolver_at = zsh.index("_ts_agent_bin() {")
    assert export_at < resolver_at, (
        "~/.local/bin must join PATH before the agent CLI resolvers run — "
        "otherwise claude/codex installed there are invisible to every login shell"
    )


def test_agent_binaries_resolve_lazily_not_at_shell_load():
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    # No load-time snapshot of either CLI.
    assert 'typeset -g _TS_CLAUDE_BIN="${commands[' not in zsh
    assert 'typeset -g _TS_CODEX_BIN="${commands[' not in zsh
    assert 'typeset -g _TS_CLAUDE_BIN=""' in zsh
    assert 'typeset -g _TS_CODEX_BIN=""' in zsh
    # The resolver rebuilds zsh's command hash, or a CLI installed since startup
    # stays invisible.
    resolver = zsh[zsh.index("_ts_agent_bin() {") :]
    resolver = resolver[: resolver.index("\n}\n") + 2]
    assert "rehash" in resolver
    assert '"$HOME/.local/bin/$name"' in resolver
    # Callers must not capture it in $( ) — that subshell would discard the cache.
    assert "$(_ts_claude_bin)" not in zsh
    assert "$(_ts_codex_bin)" not in zsh
    for fn in ("claude-stock()", "codex-stock()"):
        assert fn in zsh
    assert "was not found on PATH when this shell loaded" not in zsh

    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    assert "function Get-TsAgentCommand" in ps
    assert "$script:TsClaudeCommand = @('claude.exe'" not in ps
    assert "$script:TsCodexCommand = @('codex.exe'" not in ps
    assert "was not found on PATH when this profile loaded" not in ps


def test_cursor_launcher_is_defined_unconditionally():
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    # Gating the *definition* on `command -v cursor` left `c` undefined for the
    # life of any shell that started before Cursor's shell command was installed.
    assert "command -v cursor >/dev/null 2>&1 && c()" not in zsh
    assert "\nc() {" in zsh


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh is unavailable")
def test_agent_resolver_picks_up_a_cli_installed_after_shell_load(tmp_path):
    """The end-to-end proof: a binary that appears mid-session is found without
    restarting the shell, and the resolved path is cached in the caller."""
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    zsh_src = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    resolver = zsh_src[zsh_src.index("_ts_agent_bin() {") :]
    resolver = resolver[: resolver.index("\n}\n") + 2]
    script = f"""
{resolver}
typeset -g PROBE=""
_ts_agent_bin faketool PROBE && print "FOUND_TOO_EARLY"
print "before=[$PROBE]"
print '#!/bin/sh\\necho ok' > "$HOME/.local/bin/faketool"
chmod +x "$HOME/.local/bin/faketool"
_ts_agent_bin faketool PROBE || print "NOT_FOUND"
print "after=[$PROBE]"
"""
    result = subprocess.run(
        [shutil.which("zsh"), "-c", script],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "TERM": "dumb"},
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )
    assert result.returncode == 0, result.stderr
    assert "FOUND_TOO_EARLY" not in result.stdout
    assert "NOT_FOUND" not in result.stdout
    assert "before=[]" in result.stdout
    assert f"after=[{home}/.local/bin/faketool]" in result.stdout


# --- ~/.claude/settings.json partial ownership --------------------------------
# docs/decisions.md § "Why ~/.claude/settings.json is spliced, not copied" called
# this: the POSIX side was a whole-file target, "correct only as long as WSL-side
# Claude Code has no plugins and no per-machine keys". It grew one
# (agentPushNotifEnabled), so it is a modify_ splice now, like the Windows side.


def test_posix_claude_settings_is_a_splice_not_a_whole_file_target():
    assert not (ROOT / "dot_claude/settings.json.tmpl").exists(), (
        "a whole-file settings.json target silently deletes keys Claude Code writes"
    )
    script = ROOT / "dot_claude/modify_settings.json.tmpl"
    assert script.exists()
    assert os.access(script, os.X_OK), "chezmoi modify_ scripts must be executable"
    body = script.read_text(encoding="utf-8")
    assert body.startswith("#!"), "modify_ scripts need a shebang"
    # Ownership is derived from the rendered fragment, matching the pwsh helper.
    for key in ('"statusLine"', '"hooks"', '"theme"'):
        assert key in body


@pytest.mark.skipif(not shutil.which("python3"), reason="python3 is unavailable")
def test_claude_settings_splice_preserves_foreign_keys(tmp_path):
    """The whole point: keys Claude Code owns survive an apply."""
    src = (ROOT / "dot_claude/modify_settings.json.tmpl").read_text(encoding="utf-8")
    # Render the chezmoi template the crude way — the only directives used are
    # .chezmoi.homeDir and the ccTtsEnabled / resolvedTheme guards.
    import re

    rendered = re.sub(r"\{\{ if [^}]*\}\}|\{\{ end \}\}", "", src)
    rendered = re.sub(r"\{\{[^}]*\}\}", "/home/test", rendered)
    script = tmp_path / "modify.py"
    script.write_text(rendered, encoding="utf-8")
    script.chmod(0o755)

    live = json.dumps(
        {
            "model": "claude-opus-5",
            "enabledPlugins": {"agentmemory@local": True},
            "permissions": {"defaultMode": "ask"},
            "agentPushNotifEnabled": True,
            "theme": "light",
        }
    )
    result = subprocess.run(
        [sys.executable, str(script)],
        input=live,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    for key in ("model", "enabledPlugins", "permissions", "agentPushNotifEnabled"):
        assert key in out, f"{key} was destroyed by the splice"
    assert "statusLine" in out and "hooks" in out

    # A live file we cannot parse is echoed back untouched rather than replaced.
    broken = "{ not json"
    result = subprocess.run(
        [sys.executable, str(script)],
        input=broken,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )
    assert result.returncode == 0
    assert result.stdout == broken


def test_repo_infrastructure_is_not_deployed_to_home():
    """tests/** used to be missing here, so chezmoi wrote the suite into ~/tests/."""
    ignore = (ROOT / ".chezmoiignore").read_text(encoding="utf-8")
    for path in ("tests/**", "bootstrap/**", "docs/**", "scripts/**"):
        assert path in ignore, f"{path} would be deployed into $HOME"


def test_dropbox_jump_exists_in_both_shells():
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    # Must be shell functions: a child process cannot cd its parent.
    assert "_ts_dropbox() {" in zsh and "\ndb() {" in zsh and "dbx() { db" in zsh
    assert "function Get-TsDropbox" in ps and "function db {" in ps and "function dbx" in ps
    # $DROPBOX_DIR wins, and resolution is at call time (no load-time snapshot).
    assert '[[ -n "${DROPBOX_DIR:-}" ]]' in zsh
    assert "if ($env:DROPBOX_DIR) { return $env:DROPBOX_DIR }" in ps
    # macOS moved Dropbox under CloudStorage; that candidate must be probed first.
    dropbox = zsh[zsh.index("_ts_dropbox() {") :]
    assert dropbox.index("Library/CloudStorage/Dropbox") < dropbox.index('"$HOME/Dropbox"')


# --- terminal emulators: channel choice, Ghostty, and the opt-out --------------


def test_terminal_emulator_stays_optional_on_every_platform():
    """Nothing may force-install an emulator: the opt-out is the point."""
    win = (ROOT / "bootstrap/windows-bootstrap.ps1").read_text(encoding="utf-8")
    required = win[win.index("$requiredPackages = @(") :]
    required = required[: required.index(")")]
    assert "wezterm" not in required.lower(), "WezTerm must not be a required package"
    assert "Terminal emulator: none selected" in (ROOT / "bootstrap/_config.ps1").read_text(
        encoding="utf-8"
    )
    mac = (ROOT / "bootstrap/mac-bootstrap.sh").read_text(encoding="utf-8")
    assert "Terminal emulator: none selected" in mac
    deb = (ROOT / "bootstrap/_common-debian.sh").read_text(encoding="utf-8")
    assert "Terminal emulator: none selected" in deb
    # WSL and headless hosts are never asked and never install one.
    assert "if ! ts_is_headless && ! _ts_is_wsl; then TS_WIZ_ASK_TERMINALS=1; fi" in deb
    assert "if ts_is_headless || _ts_is_wsl; then return 0; fi" in deb


def test_multi_select_prompts_render_identically():
    """ts_prompt_multi and Read-TsMulti are a byte-identical pair, like ts_prompt_choice."""
    sh = (ROOT / "bootstrap/_wizard.sh").read_text(encoding="utf-8")
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "ts_prompt_multi() {" in sh and "function Read-TsMulti" in ps
    # Row format: bash %2d == pwsh {1,2}
    assert r"'  [%s] %2d) %s%s\n'" in sh
    assert '"  [{0}] {1,2}) {2}{3}"' in ps
    for line in (
        "Toggle a number, [a]ll, [n]one, Enter to continue, [s]kip",
        "(non-interactive — keeping the defaults)",
        "(several are fine), a, n, s, or Enter",
    ):
        assert line in sh, line
        assert line in ps, line
    # The whitespace-stripping trap: "1 2" must stay two tokens.
    multi = sh[sh.index("ts_prompt_multi() {") :]
    assert "tr -d '[:space:]'" not in multi[: multi.index("\n}\n")]
    assert "-split '[,\\s]+'" in ps


def test_wezterm_env_vars_map_onto_channels():
    sh = (ROOT / "bootstrap/_wizard.sh").read_text(encoding="utf-8")
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    for body in (sh, ps):
        assert "TS_TERMINALS" in body
        assert "TS_WEZTERM" in body, "the older spelling must keep working"
        assert "wezterm-nightly" in body and "wezterm-stable" in body
    # nightly is a real answer again, not a warning.
    assert "nightly is retired" not in sh and "nightly is retired" not in ps


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_wezterm_env_var_channel_mapping_is_exact():
    """TS_TERMINALS / TS_WEZTERM must resolve to the channel the user named."""
    cases = {
        "TS_TERMINALS=none": ("", ""),
        "TS_TERMINALS=wezterm-stable": ("wezterm-stable", "stable"),
        "TS_TERMINALS=wezterm-nightly,ghostty": ("wezterm-nightly ghostty", "nightly"),
        # a bare `wezterm` has never named a channel: take the default one
        "TS_TERMINALS=wezterm": ("wezterm-nightly", "nightly"),
        "TS_WEZTERM=nightly": ("wezterm-nightly", "nightly"),
        "TS_WEZTERM=stable": ("wezterm-stable", "stable"),
        "TS_WEZTERM=skip": ("", ""),
    }
    for env, (want_sel, want_chan) in cases.items():
        k, v = env.split("=", 1)
        r = subprocess.run(
            [
                BASH,
                "-c",
                ". bootstrap/_config.sh >/dev/null 2>&1; . bootstrap/_wizard.sh; "
                'sel="$(ts_prompt_terminals)"; printf "%s|%s" "$sel" "$(ts_terminals_channel "$sel")"',
            ],
            cwd=ROOT,
            env={**os.environ, k: v},
            text=True,
            capture_output=True,
            check=False,
            timeout=300,
            start_new_session=True,
        )
        assert r.returncode == 0, r.stderr
        sel, chan = r.stdout.split("|")
        assert sel.strip() == want_sel, f"{env}: got selection {sel!r}"
        assert chan.strip() == want_chan, f"{env}: got channel {chan!r}"


def test_wezterm_version_string_parses_to_a_date():
    """The build date is IN the release name, so it needs no network call."""
    from tstack.commands import wezterm

    assert wezterm.version_parse("wezterm 20240203-110809-5046fc22") == (
        "20240203-110809-5046fc22",
        "20240203",
        "5046fc22",
    )
    assert wezterm.version_parse("20260331-040028-577474d8") == (
        "20260331-040028-577474d8",
        "20260331",
        "577474d8",
    )
    assert wezterm.version_parse("not a version") is None, (
        "unparseable input must produce nothing, not a bad guess"
    )
    assert wezterm.fmt_date("20240203") == "2024-02-03"
    assert wezterm.fmt_date("whatever") == "whatever"


def test_changelog_slicer_counts_against_a_fixture(monkeypatch):
    """Pinned to a saved copy of upstream's changelog, so the assertion does not
    drift as upstream adds bullets."""
    from tstack.commands import wezterm

    fixture = ROOT / "tests/fixtures/wezterm-changelog.md"
    assert fixture.exists()
    monkeypatch.setattr(wezterm, "changelog_fetch", lambda: fixture)

    tally = wezterm.changes_tally("20240203-110809-5046fc22")
    counts = dict(zip(tally.split()[::2], (int(n) for n in tally.split()[1::2]), strict=False))
    # Hand-counted from the fixture: the Continuous/Nightly section only, since
    # 20240203 is where the slice stops.
    assert counts == {"Changed": 20, "New": 32, "Fixed": 74, "Updated": 9}, tally
    assert sum(counts.values()) == 135

    # A version that is not in the changelog slices nothing away - everything is
    # newer than it - so the count must be strictly larger.
    older_tally = wezterm.changes_tally("19700101-000000-00000000")
    older = dict(
        zip(older_tally.split()[::2], (int(n) for n in older_tally.split()[1::2]), strict=False)
    )
    assert sum(older.values()) > sum(counts.values())


def test_wezterm_queries_fail_open_when_offline(monkeypatch, capsys):
    """No network must degrade to version-and-date, never block or error."""
    from tstack.commands import wezterm

    monkeypatch.setattr(wezterm, "_gh_api", lambda path: None)
    monkeypatch.setattr(wezterm, "changelog_fetch", lambda: None)
    monkeypatch.setattr(
        wezterm, "installed", lambda: ("20240203-110809-5046fc22", "20240203", "5046fc22")
    )
    monkeypatch.setattr(wezterm, "channel", lambda: "stable")
    assert wezterm.status() == 0
    out = capsys.readouterr().out
    assert "offline" in out
    assert "20240203-110809-5046fc22" in out, "the part that always works must still print"

    # And an offline probe reports "nothing to offer", not an error.
    assert wezterm.update_available() == ""


def test_every_wezterm_network_call_is_bounded():
    """An unbounded fetch in a status command hangs a shell, which is how this
    stack learned to bound them."""
    body = (ROOT / "tstack/commands/wezterm.py").read_text(encoding="utf-8")
    for i, line in enumerate(body.splitlines(), 1):
        if "urlopen(" in line:
            assert "timeout=" in line, f"tstack/commands/wezterm.py:{i}: unbounded urlopen"
    # The one shell pipeline left is the apt keyring import, which is not a fetch
    # in a status path and is bounded by apt itself.
    assert body.count("shell=True") == 1


def test_wezterm_channel_switch_removes_the_other_one_both_ways(monkeypatch):
    """The two packages install to the same place, so a switch must uninstall
    first - and that must work in BOTH directions, not just nightly->stable."""
    from tstack import platform as _plat
    from tstack.commands import wezterm

    calls = []
    monkeypatch.setattr(wezterm, "channel", lambda: "stable")
    monkeypatch.setattr(wezterm, "_brew_install", lambda w, o, label: calls.append((w, o)))
    monkeypatch.setattr(wezterm, "_apt_install", lambda w, o: calls.append((w, o)))

    monkeypatch.setattr(_plat, "kind", lambda: _plat.MACOS)
    monkeypatch.setattr(wezterm.shutil, "which", lambda name: "/opt/homebrew/bin/brew")
    wezterm.install("nightly")
    wezterm.install("stable")
    assert calls == [("wezterm@nightly", "wezterm"), ("wezterm", "wezterm@nightly")]

    calls.clear()
    monkeypatch.setattr(_plat, "kind", lambda: _plat.LINUX)
    wezterm.install("nightly")
    wezterm.install("stable")
    assert calls == [("wezterm-nightly", "wezterm"), ("wezterm", "wezterm-nightly")]

    # A hand-placed binary is not ours to replace, in either direction.
    calls.clear()
    monkeypatch.setattr(wezterm, "channel", lambda: "unknown")
    wezterm.install("nightly")
    assert calls == []

    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert (
        "$other = if ($Channel -eq 'nightly') { 'wez.wezterm' } else { 'wez.wezterm.nightly' }"
        in ps
    )
    # The removal must be conditional on switching, never unconditional: a machine
    # that declines WezTerm entirely must keep whatever it already had.
    sh = (ROOT / "bootstrap/_wezterm.sh").read_text(encoding="utf-8")
    assert "stable-only policy" not in sh and "stable-only policy" not in ps


def test_nothing_installs_or_upgrades_wezterm_automatically():
    """The whole point: every path asks first."""
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    upd = zsh[zsh.index("_tstack_update() {") :]
    upd = upd[: upd.index("\n}\n")]
    assert "wezterm update-available" in upd
    assert "Upgrade WezTerm now? [y/N]" in upd
    assert "wezterm upgrade" in upd
    # Non-interactive must print the command, never run it.
    assert "Upgrade it with: tstack config wezterm upgrade" in upd
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    assert "Get-TsWezUpdateAvailable" in ps
    assert "Upgrade WezTerm now? [y/N]" in ps
    assert "Upgrade it with: tstack config wezterm upgrade" in ps


def test_ts_config_exposes_wezterm():
    sh = (ROOT / "bootstrap/ts-config.sh").read_text(encoding="utf-8")
    assert "run_wezterm()" in sh
    assert "wezterm)\n        shift\n        run_wezterm" in sh
    assert "wezterm, wizard)" in sh, "the unknown-command hint must list it"
    # -h is generated from the header comment: the sed range must still cover it.
    rng = sh[sh.index("sed -n '2,") :]
    end = int(rng[len("sed -n '2,") :].split("p")[0])
    header = sh.splitlines()[1:end]
    assert any("tstack config wezterm" in line for line in header), (
        "the wezterm line is outside the range -h prints"
    )
    # run_wizard installs the emulator it just asked about (it used not to).
    wiz = sh[sh.index("run_wizard() {") :]
    wiz = wiz[: wiz.index("\n}\n")]
    assert "install_terminals" in wiz


# --- app catalog: groups, new tools, the ai group ------------------------------


def _sh_eval(snippet):
    """Run a snippet with bootstrap/_config.sh sourced, return stdout."""
    r = subprocess.run(
        [BASH, "-c", f". bootstrap/_config.sh >/dev/null 2>&1; {snippet}"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_every_catalog_id_belongs_to_exactly_one_group():
    """An id in no group is unreachable from the group picker; one in two is ambiguous."""
    all_ids = _sh_eval('echo "$TS_APPS_ALL"').split()
    groups = _sh_eval('echo "$TS_APP_GROUPS"').split()
    seen = {}
    for g in groups:
        for member in _sh_eval(f"ts_app_group_members {g}").split():
            assert member not in seen, f"{member} is in both {seen[member]} and {g}"
            seen[member] = g
    assert set(all_ids) == set(seen), (
        f"ungrouped: {sorted(set(all_ids) - set(seen))}; "
        f"grouped but not in catalog: {sorted(set(seen) - set(all_ids))}"
    )


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_new_tools_are_in_the_catalog_with_descriptions():
    all_ids = _sh_eval('echo "$TS_APPS_ALL"').split()
    for tool in (
        "duf",
        "ncdu",
        "dust",
        "gdu",
        "btop",
        "bottom",
        "glances",
        "bandwhich",
        "gping",
        "bat",
        "eza",
        "fd",
        "ripgrep",
        "fzf",
        "tree",
        "atuin",
        "yazi",
        "pi",
    ):
        assert tool in all_ids, f"{tool} missing from the catalog"
        assert _sh_eval(f"ts_app_desc {tool}"), f"{tool} has no description"
    # bottom's binary is btm, not bottom.
    assert _sh_eval("ts_app_bin bottom") == "btm"
    # gdu collides with GNU coreutils' g-prefixed du; brew renames the TUI to
    # gdu-go when coreutils is present, so the mapping must follow reality.
    assert _sh_eval("ts_app_bin gdu") in ("gdu", "gdu-go")
    assert _sh_eval("gdu-go() { :; }; command -v gdu-go >/dev/null && ts_app_bin gdu") in (
        "gdu",
        "gdu-go",
    )
    # fd closes the documented sessionizer gap (README says it is needed).
    assert "needs `fd`" in (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_agent_clis_are_asked_about_and_default_to_all():
    """Default-to-all, but still a question: every group starts ticked and every
    tool inside stays individually untickable."""
    ai = _sh_eval("ts_app_group_members ai").split()
    assert set(ai) == {"claude", "codex", "cursor-agent", "grok", "gemini", "pi"}
    recommended = _sh_eval('echo "$TS_APPS_RECOMMENDED"').split()
    for tool in ai:
        assert tool in recommended, f"{tool} should be pre-ticked (default to all)"
    # The group picker pre-ticks every group, ai included.
    wiz = (ROOT / "bootstrap/_wizard.sh").read_text(encoding="utf-8")
    assert 'case "$g" in ai) ;;' not in wiz, "the ai group must not be singled out any more"
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "if ($g -ne 'ai')" not in ps
    # …but it is still a prompt, not a forced install.
    assert "ts_prompt_multi" in wiz


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_python_and_runtimes_are_in_the_questionnaire():
    groups = _sh_eval('echo "$TS_APP_GROUPS"').split()
    assert "python" in groups and "runtimes" in groups
    py = _sh_eval("ts_app_group_members python").split()
    for tool in ("python", "uv", "pipx", "ruff", "ipython", "httpie", "poetry", "pre-commit"):
        assert tool in py, f"{tool} missing from the python group"
    assert set(_sh_eval("ts_app_group_members runtimes").split()) == {"fnm", "node"}
    # python's binary is python3, not python.
    assert _sh_eval("ts_app_bin python") == "python3"
    for tool in [*py, "fnm"]:
        assert _sh_eval(f"ts_app_desc {tool}"), f"{tool} has no description"


def test_agent_cli_installers_use_the_real_upstream_commands():
    sh = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    # grok ships a standalone binary — no Node needed — and its installer would
    # otherwise append a PATH line to the ~/.zshrc chezmoi owns whole-file.
    assert "https://x.ai/cli/install.sh" in sh
    assert 'GROK_BIN_DIR="$HOME/.local/bin"' in sh
    assert "https://x.ai/cli/install.ps1" in ps
    # gemini and codex are npm-only, each with its own floor.
    assert "@google/gemini-cli" in sh and "@google/gemini-cli" in ps
    assert "@openai/codex" in sh and "@openai/codex" in ps
    # No brew fallback for gemini: that formula is deprecated upstream.
    assert "brew install gemini-cli" not in sh
    assert "deprecated upstream" in sh


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_node_managed_binaries_are_visible_to_the_update_check():
    """Global npm binaries live under fnm's per-shell PATH entry; without loading
    fnm's env first, tstack update would nag about codex/gemini forever."""
    sh = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    assert "ts_load_node_env" in sh
    pending = sh[sh.index("ts_apps_pending() {") :]
    assert "ts_load_node_env" in pending[: pending.index("\n}\n")]
    report = sh[sh.index("ts_report_installed_apps() {") :]
    assert "ts_load_node_env" in report[: report.index("\n}\n")]


def test_fnm_is_wired_into_both_shells():
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    assert "fnm env --use-on-cd --shell zsh" in zsh
    assert "fnm env --use-on-cd --shell powershell" in ps
    # Guarded, so a machine without fnm is unaffected.
    assert "if command -v fnm >/dev/null; then" in zsh
    assert "if (Get-Command fnm -ErrorAction SilentlyContinue) {" in ps
    # grok's completions are carried by us, because its installer's ~/.zshrc edit
    # is reverted by the next chezmoi apply.
    assert '"$HOME/.grok/completions/zsh"' in zsh


def test_agent_clis_are_not_installed_through_a_package_manager():
    sh = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "ts_install_ai_cli" in sh and "function Install-TsAiCli" in ps
    # npm installs must be gated on the Node version, not attempted blindly —
    # each package has its own floor (codex 16, gemini 20).
    assert "ts_node_major" in sh and '-ge "$want"' in sh
    assert "$major -ge $want" in ps
    assert "want=16" in sh and "want=20" in sh
    # grok has a real upstream installer now (xAI ship a standalone binary), so
    # the old "no official package" placeholder must be gone from both sides.
    for body in (sh, ps):
        assert "no official CLI package this stack can install for you" not in body
        assert "x.ai/cli/install" in body


def test_arch_aware_github_fallbacks():
    """The eza/delta/lazydocker fallbacks used to hard-code x86_64 and miss on arm64."""
    deb = (ROOT / "bootstrap/_common-debian.sh").read_text(encoding="utf-8")
    for line in deb.splitlines():
        if "common_install_github_binary" in line:
            assert "x86_64" not in line, f"arch-blind fallback: {line.strip()}"


def test_ts_config_wizard_replays_the_whole_questionnaire():
    sh = (ROOT / "bootstrap/ts-config.sh").read_text(encoding="utf-8")
    assert "run_wizard()" in sh
    assert "wizard|reconfigure) run_wizard ;;" in sh
    # It must re-state every value, or ts_save_config drops the ones it omits.
    wiz = sh[sh.index("run_wizard() {") :]
    wiz = wiz[: wiz.index("\n}\n")]
    for call in (
        "ts_wizard_collect",
        "ts_save_config",
        "ts_agents_save_config",
        "ts_wez_mux_set",
        "ts_wez_restore_set",
        "ts_cc_tts_apply_wizard_choice",
    ):
        assert call in wiz, f"run_wizard does not persist {call}"
    # -h is generated from the header comment: the sed range must still cover it.
    rng = sh[sh.index("sed -n '2,") :]
    end = int(rng[len("sed -n '2,") :].split("p")[0])
    header = sh.splitlines()[1:end]
    assert any("tstack config wizard" in line for line in header), (
        "the wizard line is outside the range -h prints"
    )
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    assert "$runWizard = {" in ps and "'wizard'" in ps


def test_shared_pwsh_prompts_live_where_both_callers_can_reach_them():
    """$PROFILE dot-sources _config.ps1 only; a prompt in windows-bootstrap.ps1
    is invisible to `tstack config wizard`."""
    cfg = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    boot = (ROOT / "bootstrap/windows-bootstrap.ps1").read_text(encoding="utf-8")
    for fn in ("function Read-TsWizard", "function Install-TsTerminals"):
        assert fn in cfg, f"{fn} must live in _config.ps1"
        assert fn not in boot, f"{fn} is duplicated in windows-bootstrap.ps1"


def test_wizard_callees_are_all_defined_in_config_ps1():
    """Naming the two moved functions is not enough: `Read-TsWizard` calling a
    prompt that stayed in windows-bootstrap.ps1 is a runtime crash for
    `tstack config wizard` only (this is how Read-TsWorkspaceDir broke it). Derive
    the callee list from the body instead of maintaining it by hand."""
    cfg = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    body = cfg[cfg.index("function Read-TsWizard") :]
    body = body[: body.index("\nfunction ", 1)]
    called = set(re.findall(r"\b((?:Read|Get|Test|Show|Save|Install)-Ts[A-Za-z]+)", body))
    called.discard("Read-TsWizard")
    missing = sorted(n for n in called if not re.search(r"^function " + n + r"\b", cfg, re.M))
    assert not missing, f"Read-TsWizard calls {missing}, which tstack config wizard cannot see"


def test_pwsh_wizard_persists_the_workspace_answer():
    """The questionnaire asks for a workspace root; dropping the answer on the
    `tstack config wizard` path is a silent behaviour difference from the installer."""
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    cfg = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "function Save-TsWorkspaceOverride" in cfg
    assert "Save-TsWorkspaceOverride $w.Workspace" in ps
    # And a half-finished questionnaire must not be persisted over real answers.
    assert "did not complete" in ps


# ── tstack smb ──────────────────────────────────────────────────────────────────────


def _smb_eval(tmp_path, local_conf, snippet, tracked="set default_user guest\n"):
    """Run a snippet with bootstrap/_smb.sh sourced against a sandboxed store."""
    lib = tmp_path / "lib"
    lib.mkdir(exist_ok=True)
    (lib / "shares.conf").write_text(tracked, encoding="utf-8", newline="\n")
    cfg = tmp_path / "cfg" / "terminal-stack"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "shares.local.conf").write_text(local_conf, encoding="utf-8", newline="\n")
    env = dict(
        os.environ, XDG_CONFIG_HOME=bash_path(tmp_path / "cfg"), TS_SMB_LIB_DIR=bash_path(lib)
    )
    r = subprocess.run(
        [BASH, "-c", f". bootstrap/_smb.sh >/dev/null 2>&1; {snippet}"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=env,
        timeout=300,
        start_new_session=True,
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_smb_store_parses_stanzas(tmp_path):
    conf = "share media\n  host nas.lan\n  path Media\n  user marty\n"
    assert _smb_eval(tmp_path, conf, 'ts_smb_get media host ""') == "nas.lan"
    assert _smb_eval(tmp_path, conf, 'ts_smb_get media path ""') == "Media"
    assert _smb_eval(tmp_path, conf, "ts_smb_names") == "media"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_smb_store_last_match_wins(tmp_path):
    """The local file must be able to override ONE field without restating a stanza."""
    conf = "share media\n  host nas.lan\n  path Media\n  vfs off\nshare media\n  vfs writes\n"
    assert _smb_eval(tmp_path, conf, 'ts_smb_get media vfs ""') == "writes"
    assert _smb_eval(tmp_path, conf, 'ts_smb_get media host ""') == "nas.lan"
    # ...and the name is not duplicated by the second stanza.
    assert _smb_eval(tmp_path, conf, "ts_smb_names") == "media"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_smb_store_falls_back_to_set_defaults(tmp_path):
    conf = "share media\n  host nas.lan\n  path Media\n"
    assert (
        _smb_eval(tmp_path, conf, 'ts_smb_get media user ""', tracked="set default_user guest\n")
        == "guest"
    )


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_smb_flags_tail_keeps_its_spaces(tmp_path):
    """`flags` is the one free-form tail; the space-delimited store cannot hold it,
    so it lives in its own accumulator. An inline comment is stripped, and so is
    the whitespace the strip leaves behind."""
    conf = (
        "share media\n  host nas.lan\n  path Media\n"
        "  flags --transfers 8 --smb-idle-timeout 5m   # tuned\n"
    )
    assert _smb_eval(tmp_path, conf, "ts_smb_flags media") == "--transfers 8 --smb-idle-timeout 5m"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_smb_validate_catches_the_share_vs_path_trap(tmp_path):
    """`share` opens a stanza, so writing `share Media` for the SMB share name
    silently opens a second one. That mistake must be reported, not absorbed."""
    conf = "share media\n  host nas.lan\n  share Media\n"
    out = _smb_eval(tmp_path, conf, "ts_smb_validate || true")
    # Stanza names are folded to lower case, so `share Media` merges back into the
    # `media` stanza rather than creating a spurious one — the mistake therefore
    # shows up as a missing `path`, and the message has to say why.
    assert "has no path" in out
    assert "'share' opens a stanza" in out
    assert _smb_eval(tmp_path, conf, "ts_smb_names") == "media"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_smb_help_works_without_a_clone():
    """`tstack smb -h` must work on a box where the clone or chezmoi is the broken thing."""
    env = {k: v for k, v in os.environ.items() if k != "TERMINAL_STACK_DIR"}
    env.update({"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"})
    r = subprocess.run(
        [BASH, "bootstrap/ts-smb.sh", "-h"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
        env=env,
        timeout=300,
        start_new_session=True,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("tstack smb —")
    assert "Windows is not supported yet" in r.stdout


def test_smb_never_offers_a_password_flag():
    """A password in argv is world-readable via /proc/PID/cmdline, and a mount is
    long-lived. --password prompts; --password-stdin reads. There is no third form."""
    src = (ROOT / "bootstrap/ts-smb.sh").read_text(encoding="utf-8")
    assert "--password-stdin" in src
    # The flag parser must treat --password as a BOOLEAN. Every value-taking flag
    # in that loop ends with `shift`; --password must not, or it would be pulling
    # a secret off the command line.
    arm = [l for l in src.splitlines() if "--password)" in l]
    assert arm, "no --password arm in the flag loop"
    assert "shift" not in arm[0], f"--password consumes a value: {arm[0]}"
    assert "OPT_PASSWORD=1" in arm[0]
    # the connection string builder must never interpolate a password
    lib = (ROOT / "bootstrap/_smb.sh").read_text(encoding="utf-8")
    conn = lib[lib.index("ts_smb_conn() {") :]
    conn = conn[: conn.index("\n}\n")]
    assert "pass" not in conn


def test_smb_never_stats_a_mountpoint_to_test_liveness():
    """On a dead FUSE mount, stat/ls/test -d block forever and take the shell with
    them. Liveness must come from the kernel mount table only."""
    lib = (ROOT / "bootstrap/_smb.sh").read_text(encoding="utf-8")
    fn = lib[lib.index("ts_smb_is_mounted() {") :]
    fn = fn[: fn.index("\n}\n")]
    for forbidden in ("test -d", "[ -d ", "stat ", "ls "):
        assert forbidden not in fn, f"ts_smb_is_mounted touches the path: {forbidden}"
    assert "/proc/self/mounts" in fn or "mount " in fn


def test_smb_does_not_auto_enable_fskit():
    """fuse-t's FSKit backend fails outright on macOS 26.6 with fuse-t 1.2.6
    ("fuse: mount failed with error: -1") while the default nfs backend does not."""
    src = (ROOT / "bootstrap/ts-smb.sh").read_text(encoding="utf-8")
    mount_fn = src[src.index("cmd_mount() {") :]
    mount_fn = mount_fn[: mount_fn.index("\n}\n")]
    code = "\n".join(l for l in mount_fn.splitlines() if not l.strip().startswith("#"))
    assert "backend=fskit" not in code


def test_smb_exists_and_is_not_claimed_for_pwsh():
    """Bash-only by decision, not by drift.

    The registry has to say so explicitly -- a '-' in the Windows column is what
    makes `tstack smb` report "not available on Windows" instead of "not found",
    and the help has to agree so nobody 'fixes' the missing twin silently.
    """
    rows = [
        r.split(None, 3)
        for r in read_repo("tstack/commands.conf").splitlines()
        if r.strip() and not r.startswith("#")
    ]
    smb = next((r for r in rows if r[0] == "smb"), None)
    assert smb, "smb missing from tstack/commands.conf"
    assert smb[1].endswith("ts-smb.sh"), smb
    assert smb[2] == "-", "the Windows column must stay '-', not a guessed twin"
    assert "THERE IS NO pwsh TWIN YET" in read_repo("bootstrap/ts-smb.sh")


def test_rclone_is_in_the_catalog_with_a_description():
    cfg = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    assert "rclone" in cfg
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "rclone     = 'Rclone.Rclone'" in ps
    assert "'rclone'" in ps


def test_guided_rclone_only_intercepts_exact_bare_config():
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    body = zsh[zsh.index("rclone() {") :]
    body = body[: body.index("\n}\n")]
    assert '(( $# == 1 )) && [[ "$1" == config ]]' in body
    assert '"$_TS_RCLONE_BIN" "$@"' in body
    assert "rclone-stock()" in zsh
    wizard = (ROOT / "bootstrap/ts-rclone-config.sh").read_text(encoding="utf-8")
    assert "This does NOT choose a folder" in wizard
    assert "rclone config providers" not in wizard  # always use the resolved binary
    assert "config providers" in wizard
    assert "Tier 5  deprecated" in wizard


def test_smb_guided_setup_verifies_before_transactional_save():
    setup = (ROOT / "bootstrap/_smb_setup.sh").read_text(encoding="utf-8")
    verify = setup.index("verifying that")
    review = setup.index("Review — nothing has been saved yet")
    store = setup.index("ts_smb_cred_set", review)
    write = setup.index(".shares.local.conf.XXXXXX", review)
    assert verify < review < store
    assert verify < review < write
    assert "RCLONE_SMB_PASS" in setup
    assert "--password" not in setup
    assert "rolled back" in setup
    assert "tailscale status --json" in setup


def test_tailscale_helpers_and_topic_cover_identity_and_diagnostics():
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    for name in ("tail-self", "tail-hosts", "tail-ip", "tail-fqdn", "tail-find"):
        assert f"{name}()" in zsh
    for name in ("tail-status", "tail-ping", "tail-netcheck", "tail-nc", "tail-ssh"):
        assert f"alias {name}=" in zsh
    topic = (ROOT / "docs/kb/common/tools/tailscale.md").read_text(encoding="utf-8")
    for command in (
        "tailscale ip -4",
        "tailscale status --json",
        "tailscale ping",
        "tailscale netcheck",
        "tailscale whois",
    ):
        assert command in topic
    assert "https://tailscale.com/kb/1080/cli" in topic


# ── atuin / arch-tag regressions ────────────────────────────────────────────────


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_common_arch_tag_rust_uses_aarch64_not_arm64():
    """cargo-dist projects (atuin, yazi) name their ARM asset `aarch64`, while
    `gnu` yields `arm64`. Getting this wrong fails *silently on ARM only*: the
    asset regex matches nothing, x86_64 boxes keep working, and the tool is
    quietly missing on every Pi/ARM server."""
    lib = ROOT / "bootstrap/_common-debian.sh"
    fn = re.search(r"^common_arch_tag\(\) \{.*?^\}", lib.read_text(encoding="utf-8"), re.S | re.M)
    assert fn, "common_arch_tag not found"

    def tag(machine, style):
        script = f'{fn.group(0)}\nuname() {{ echo "{machine}"; }}\ncommon_arch_tag {style}\n'
        return subprocess.run(
            [BASH, "-c", script],
            capture_output=True,
            text=True,
            timeout=300,
            start_new_session=True,
        ).stdout.strip()

    assert tag("aarch64", "rust") == "aarch64"
    assert tag("arm64", "rust") == "aarch64"
    assert tag("x86_64", "rust") == "x86_64"
    # The existing styles must not have shifted.
    assert tag("aarch64", "gnu") == "arm64"
    assert tag("aarch64", "deb") == "arm64"
    assert tag("x86_64", "deb") == "amd64"


def test_atuin_is_gated_by_a_setting_not_a_presence_check():
    """atuin *replaces* Ctrl+R and its binary is often installed but dormant, so
    a `command -v atuin` guard in dot_zshrc would hijack the binding without the
    user choosing it. The gate must be the rendered fragment."""
    rc = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    assert "terminal-stack/atuin.zsh" in rc, "dot_zshrc must source the fragment"
    # Ignore comments: the file explains at length why this guard is wrong, so a
    # raw substring match would hit the explanation rather than real code.
    code = [l for l in rc.splitlines() if not l.lstrip().startswith("#")]
    assert not any("command -v atuin" in l for l in code), (
        "dot_zshrc must NOT gate atuin on a presence check"
    )
    # dot_zshrc stays a non-template so `chezmoi re-add ~/.zshrc` keeps working.
    assert not (ROOT / "dot_zshrc.tmpl").exists()
    frag = ROOT / "dot_config/terminal-stack/atuin.zsh.tmpl"
    assert frag.exists()
    body = frag.read_text(encoding="utf-8")
    assert "atuinEnabled" in body and "--disable-up-arrow" in body
    # Sourced AFTER fzf, or fzf would win Ctrl+R.
    assert rc.index("fzf --zsh") < rc.index("terminal-stack/atuin.zsh")


def test_atuin_history_filter_mirrors_the_zsh_secret_filter():
    """atuin records via its own preexec and never sees zshaddhistory(), so the
    secret patterns are duplicated on purpose. If they drift, secrets the stack
    refuses to write to ~/.zsh_history land in atuin's SQLite database."""
    cfg = (ROOT / "dot_config/atuin/config.toml.tmpl").read_text(encoding="utf-8")
    rc = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    zline = next(l for l in rc.splitlines() if "ANTHROPIC_API_KEY=" in l and "=~" in l)
    for pat in (
        "ANTHROPIC_API_KEY=",
        "OPENAI_API_KEY=",
        "GITHUB_TOKEN=",
        "GH_TOKEN=",
        "NPM_TOKEN=",
        "_KEY=",
        "_SECRET=",
        "_PASSWORD=",
        "_TOKEN=",
        "sk-[A-Za-z0-9_-]{20,}",
    ):
        assert pat in zline, f"{pat} vanished from zshaddhistory"
        assert pat in cfg, f"{pat} missing from atuin history_filter"
    assert "secrets_filter = true" in cfg
    assert "auto_sync = false" in cfg


def test_atuin_has_no_winget_id_and_no_pwsh_init():
    """There is no winget manifest for atuin and `atuin init` has no PowerShell
    target, so an id here would always fail. Absent is the honest answer."""
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    ids = ps.split("$script:TsWingetIds")[1].split("}")[0]
    # Comment lines name atuin to explain the absence; only assignments count.
    assigns = [l for l in ids.splitlines() if "=" in l and not l.lstrip().startswith("#")]
    assert not any(l.strip().startswith("atuin") for l in assigns), (
        "atuin must not have a winget id"
    )
    assert "yazi       = 'sxyazi.yazi'" in ids, "yazi's winget id is real and verified"


# ── Ghostty ─────────────────────────────────────────────────────────────────────


def _wez_light_scheme():
    """PALETTES.light.scheme_def out of dot_wezterm.lua.tmpl."""
    lua = (ROOT / "dot_wezterm.lua.tmpl").read_text(encoding="utf-8")
    sd = lua[lua.index("scheme_def = {") :]
    sd = sd[: sd.index("\n    },")]

    def one(key):
        return re.search(rf"{key} = '(#[0-9A-Fa-f]{{6}})'", sd).group(1).lower()

    def arr(key):
        block = re.search(rf"{key} = \{{(.*?)\}}", sd, re.S).group(1)
        return [c.lower() for c in re.findall(r"'(#[0-9A-Fa-f]{6})'", block)]

    return one, arr


def test_ghostty_light_theme_matches_the_wezterm_palette():
    """Ghostty ships no VS Code Light Modern builtin, so the stack carries one.
    It is generated from the same hexes as WezTerm's PALETTES.light so the two
    terminals render the light theme identically; this pins them together."""
    theme = (ROOT / "dot_config/ghostty/themes/vs-code-light-modern").read_text(encoding="utf-8")
    one, arr = _wez_light_scheme()
    pal = dict(re.findall(r"^palette = (\d+)=(#[0-9a-f]{6})$", theme, re.M))
    ansi, brights = arr("ansi"), arr("brights")
    assert len(pal) == 16, f"expected 16 palette entries, got {len(pal)}"
    for i, c in enumerate(ansi):
        assert pal[str(i)] == c, f"palette {i} drifted from the Lua ansi table"
    for i, c in enumerate(brights):
        assert pal[str(i + 8)] == c, f"palette {i + 8} drifted from the Lua brights"
    for key, lua_key in (
        ("background", "background"),
        ("foreground", "foreground"),
        ("cursor-color", "cursor_bg"),
        ("cursor-text", "cursor_fg"),
        ("selection-background", "selection_bg"),
        ("selection-foreground", "selection_fg"),
    ):
        got = re.search(rf"^{key} = (#[0-9a-f]{{6}})$", theme, re.M).group(1)
        assert got == one(lua_key), f"{key} drifted from the Lua scheme_def"


def test_ghostty_config_follows_theme_mode_not_resolved_theme():
    """Ghostty's dark:/light: syntax follows the OS itself, so it belongs in
    WezTerm's live-switching class, not Starship/tmux's bake-at-apply class.
    Reading resolvedTheme would silently freeze `follow` until the next apply."""
    cfg = (ROOT / "dot_config/ghostty/config.tmpl").read_text(encoding="utf-8")
    assert "themeMode" in cfg
    assert "resolvedTheme" not in cfg, "Ghostty must not bake resolvedTheme"
    assert "dark:Catppuccin Mocha,light:vs-code-light-modern" in cfg
    # Ghostty has no inline comments: a `#` after a value becomes the value.
    for ln in cfg.splitlines():
        st = ln.strip()
        if st.startswith("#") or st.startswith("{{") or "=" not in st:
            continue
        assert "#" not in st.split("=", 1)[1] or "color" in st or "palette" in st, (
            f"inline comment would be parsed as part of the value: {ln!r}"
        )


def test_ghostty_is_gated_and_never_removed_by_chezmoi():
    """.chezmoiignore is evaluated on every machine, so a removal rule there
    would wipe a hand-written Ghostty config on a box that never opted in.
    Removal is tstack config ghostty off's job, for the machine you run it on."""
    ign = (ROOT / ".chezmoiignore").read_text(encoding="utf-8")
    assert ign.count(".config/ghostty/**") == 2, "expected a darwin gate and an off gate"
    rm = (ROOT / ".chezmoiremove").read_text(encoding="utf-8")
    assert "ghostty" not in rm, ".chezmoiremove must never target ghostty"
    hook = ROOT / "run_before_20-backup-ghostty.sh"
    assert hook.exists() and os.access(hook, os.X_OK), "backup hook must exist and be executable"
    body = hook.read_text(encoding="utf-8")
    assert "managed by terminal-stack" in body, "must skip a config that is already ours"
    assert "Darwin" in body, "must no-op off macOS"


# ── Ghostty on Windows (noctty / winghostty) ────────────────────────────────────

WIN_GHOSTTY = "windows/AppData/Local/ghostty"


def test_windows_ghostty_targets_the_upstream_config_dir():
    r"""noctty reads BOTH its own %LOCALAPPDATA%\<appname>\config.ghostty and the
    upstream-compatible %LOCALAPPDATA%\ghostty\config. We target the upstream one
    because <appname> is `winghostty` today and `noctty` the day the rebrand ships
    (it is in main since 2026-08-20 but no release carries it yet) — the app-named
    path would silently stop being read on upgrade day. Verified against 1.3.123."""
    assert (ROOT / WIN_GHOSTTY / "config.tmpl").exists()
    assert (ROOT / WIN_GHOSTTY / "themes/vs-code-light-modern").exists()
    for bad in ("AppData/Local/winghostty", "AppData/Local/noctty"):
        assert not (ROOT / bad).exists(), (
            f"{bad} is app-named and breaks on the rename; use AppData/Local/ghostty"
        )


def test_windows_ghostty_theme_is_byte_identical_to_the_macos_one():
    """Two copies exist because chezmoi manages the macOS one and the Windows sync
    mirrors the other. A test already pins the macOS copy to the WezTerm palette,
    so pinning the pair keeps Windows on that palette transitively."""
    mac = (ROOT / "dot_config/ghostty/themes/vs-code-light-modern").read_bytes()
    win = (ROOT / WIN_GHOSTTY / "themes/vs-code-light-modern").read_bytes()
    assert mac == win, "the Windows Ghostty theme drifted from the macOS one"


def test_windows_ghostty_config_carries_no_foreign_token():
    """Windows mirror files get blind token substitution, so ANY __TOKEN__ the
    sync knows about is replaced — including one that only appears inside a
    comment. A comment here mentioning __TMUX_PREFIX__ was rewritten to `C-b`
    mid-sentence before this test existed."""
    cfg = (ROOT / WIN_GHOSTTY / "config.tmpl").read_text(encoding="utf-8")
    found = set(re.findall(r"__[A-Z0-9_]+__", cfg))
    assert found == {"__GHOSTTY_THEME__", "__GHOSTTY_WINDOW_THEME__"}, (
        f"unexpected token(s) in the Windows Ghostty config: {sorted(found)}"
    )


def test_windows_ghostty_config_uses_tokens_not_go_templates():
    """The Windows sync substitutes tokens with str.replace; it has no template
    engine, so a `{{ if }}` would be copied through literally."""
    cfg = (ROOT / WIN_GHOSTTY / "config.tmpl").read_text(encoding="utf-8")
    assert "{{" not in cfg, "Go-template syntax never renders on the Windows side"
    # Ghostty has no inline comments: a `#` after a value becomes the value.
    for ln in cfg.splitlines():
        st = ln.strip()
        if st.startswith("#") or "=" not in st:
            continue
        val = st.split("=", 1)[1]
        assert "#" not in val, f"inline comment would be parsed as part of the value: {ln!r}"


def test_windows_ghostty_drops_the_macos_only_directives():
    """macos-option-as-alt is absent from this build's option set and is silently
    ignored rather than diagnosed, so shipping it would be harmless but dishonest.
    font-thicken and window-colorspace are macOS rendering niceties, and there is
    no Cmd key to bind."""
    cfg = (ROOT / WIN_GHOSTTY / "config.tmpl").read_text(encoding="utf-8")
    body = "\n".join(l for l in cfg.splitlines() if not l.strip().startswith("#"))
    for directive in ("macos-option-as-alt", "font-thicken", "window-colorspace"):
        assert directive not in body, f"{directive} is macOS-only"
    assert "cmd+" not in body, "there is no Cmd key on Windows"


def test_ghostty_theme_mapping_is_the_same_in_both_sync_paths():
    """Ghostty's config format has no conditionals and Windows mirror files get
    token substitution, so themeMode -> theme is resolved in the sync. That means
    the mapping exists three times (bash sync, pwsh sync, tstack config diff) and all
    of them must agree, or `tstack config ghostty diff` reports a phantom change."""
    sources = {
        "run_after_90-sync-windows.sh": (ROOT / "run_after_90-sync-windows.sh"),
        "scripts/sync-windows.ps1": (ROOT / "scripts/sync-windows.ps1"),
        "bootstrap/ts-config.sh": (ROOT / "bootstrap/ts-config.sh"),
    }
    for name, path in sources.items():
        body = path.read_text(encoding="utf-8")
        assert "dark:Catppuccin Mocha,light:vs-code-light-modern" in body, (
            f"{name}: follow must use a split theme (it is what tracks the OS)"
        )
        assert "vs-code-light-modern" in body and "Catppuccin Mocha" in body, name
        for wt in ("'light'", "'auto'", "'dark'"):
            assert wt in body, f"{name}: missing window-theme value {wt}"


def test_ghostty_off_skips_the_windows_subtree_without_deleting_it():
    """Same rule as the macOS .chezmoiignore gate: `off` stops the config being
    re-rendered. Deleting is tstack config's job, for the machine you run it on — a
    sync-side deletion runs everywhere and would wipe a hand-written config."""
    sh = (ROOT / "run_after_90-sync-windows.sh").read_text(encoding="utf-8")
    ps = (ROOT / "scripts/sync-windows.ps1").read_text(encoding="utf-8")
    assert "AppData/Local/ghostty/*" in sh and "GHOSTTY_CFG_ON" in sh
    assert "AppData/Local/ghostty/*" in ps and "tsGhosttyOn" in ps
    for name, body in (("bash", sh), ("pwsh", ps)):
        assert (
            "rm -rf" not in body.lower() or "ghostty" not in body.lower().split("rm -rf")[1][:200]
        ), f"{name} sync must never delete the Ghostty tree"


def test_ghostty_is_offered_on_windows_but_never_installed():
    """It is a real Windows option now, but like the WezTerm channels it is asked,
    never forced — so it must NOT gain a winget id in the terminal table."""
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    # Cut at the closing paren on its OWN line: the block's comments contain
    # parenthesised URLs, so splitting on the first ")" truncates mid-comment.
    cand = ps.split("$script:TsTerminalCandidates")[1].split(chr(10) + ")")[0]
    assert "Key = 'ghostty'" in cand, "Ghostty must be offered on Windows"
    # Split on the ASSIGNMENT: the candidates block above mentions this variable
    # by name in a comment, and splitting on the bare name lands there instead.
    ids = ps.split("$script:TsTerminalWingetIds = @{")[1].split("}")[0]
    assert "ghostty" not in ids, "offered, never auto-installed"
    assert "no Windows build available" not in ps, "that claim is obsolete"


def test_pwsh_preticked_list_survives_appending():
    """A PowerShell `switch` unrolls a one-element array to a SCALAR, so `+=` on
    the result concatenates strings instead of appending: the preticked list
    silently became the single key 'wezterm-nightlyghostty' and the whole question
    rendered unticked. The @( ) around the switch is what prevents it."""
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    block = ps.split("$preticked = ")[1][:400]
    assert block.startswith("@(switch"), (
        "wrap the switch in @( ) or += will concatenate instead of append"
    )


def test_windows_ghostty_pins_the_same_shell_as_wezterm():
    """noctty's shell picker will hand you "Windows PowerShell" — PowerShell 5.1,
    which this stack does not configure at all (its profile is pwsh-7-only) and
    which runs under a separately-tracked execution policy that defaults to
    Restricted, so it refuses to dot-source any profile. WezTerm pins pwsh; this
    must too, or the two terminals on one machine open different shells."""
    cfg = (ROOT / WIN_GHOSTTY / "config.tmpl").read_text(encoding="utf-8")
    body = [l.strip() for l in cfg.splitlines() if not l.strip().startswith("#")]
    assert any(l.startswith("command =") and "pwsh" in l for l in body), (
        "the Windows Ghostty config must pin pwsh, like WezTerm's default_prog"
    )
    wez = (ROOT / "windows/.wezterm.lua.tmpl").read_text(encoding="utf-8")
    assert "'pwsh.exe'" in wez, "WezTerm's default_prog moved; keep the pair aligned"


def test_windows_ghostty_is_opaque_so_the_dwm_backdrop_stays_off():
    """noctty turns `background-opacity < 1` PLUS a blur into a DWM tabbed
    backdrop, which is drawn under the Win32 chrome as well as the terminal and
    washes out the command palette. The macOS twin's 0.97 + blur 20 is therefore
    a deliberate divergence, not drift."""
    cfg = (ROOT / WIN_GHOSTTY / "config.tmpl").read_text(encoding="utf-8")
    body = [l.strip() for l in cfg.splitlines() if not l.strip().startswith("#")]
    opacity = [l for l in body if l.startswith("background-opacity")]
    assert opacity == ["background-opacity = 1"], (
        f"anything below 1 re-enables the backdrop: {opacity!r}"
    )
    assert not [l for l in body if l.startswith("background-blur")], (
        "a blur is the other half of shouldUseSystemBackdrop; leave it unset"
    )
    # The macOS side keeps the translucent look; this pair is meant to differ.
    mac = (ROOT / "dot_config/ghostty/config.tmpl").read_text(encoding="utf-8")
    assert "background-opacity = 0.97" in mac, (
        "if macOS went opaque too, this test's premise needs revisiting"
    )


def test_cursor_agent_has_a_real_windows_installer():
    """It does have one — the same URL as POSIX with ?win32=true, which serves a
    PowerShell script instead of a shell one. Install-TsAiCli used to warn "no
    Windows installer this stack can call; install it inside WSL", so ticking it
    on Windows could never succeed."""
    # _uncommented: the block records the old wrong claim verbatim in a comment.
    # `#` starts a comment in pwsh as in shell, so the helper works on both.
    ps = _uncommented((ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8"))
    assert "cursor.com/install?win32=true" in ps, (
        "cursor-agent must install on Windows, not defer to WSL"
    )
    assert "no Windows installer this stack can call" not in ps, "that claim is obsolete"
    # POSIX keeps the shell-script form of the same endpoint.
    sh = _uncommented((ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8"))
    assert "cursor.com/install" in sh and "win32" not in sh, (
        "the POSIX twin must NOT take the win32 branch"
    )


def test_pending_apps_refreshes_path_before_probing():
    """Get-TsAppsPending reads PATH to decide what is missing, so it must refresh
    from the persisted Machine+User values first — the way the POSIX twin calls
    ts_load_node_env. Without it, anything installed since this process started
    (an installer that edited the User PATH; fnm, whose entry is per-shell) reads
    as missing: grok, gemini and pi were all installed and all three were offered
    again on every tstack update."""
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    body = ps.split("function Get-TsAppsPending {")[1].split("\nfunction ")[0]
    assert "Update-TsSessionPath" in body, (
        "refresh PATH before probing, or the pending list reports false positives"
    )
    sh = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    tw = sh.split("ts_apps_pending() {")[1].split("\n}")[0]
    assert "ts_load_node_env" in tw, "the POSIX twin's equivalent moved; keep the pair aligned"


# ── agentmemory bash port ───────────────────────────────────────────────────────


def _uncommented(text):
    """Shell source with comment lines dropped. These files document at length
    why a construct is absent, so a raw substring match hits the explanation
    rather than real code."""
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


AM_SH = ROOT / "bootstrap/_agentmemory.sh"
AM_PS = ROOT / "bootstrap/_agentmemory.ps1"
AM_ENTRY = ROOT / "bootstrap/ts-agentmemory.sh"


def test_agentmemory_sh_entry_point_exists_where_check_capture_probes():
    """docker-local/agentmemory/check-capture.sh looks for this exact path and
    fails loudly when it finds none. The name is not negotiable."""
    assert AM_ENTRY.exists() and os.access(AM_ENTRY, os.X_OK)
    assert AM_SH.exists() and (ROOT / "bootstrap/_merge_json_settings.sh").exists()


def test_agentmemory_hook_commands_are_posix_not_cmd_exe():
    """A cmd.exe `set X=…&&` chain written into a hooks file on a Mac fails
    SILENTLY — precisely the failure this wiring exists to prevent."""
    body = AM_ENTRY.read_text(encoding="utf-8")
    assert "cmd /d /s /c" not in body
    assert "AGENTMEMORY_URL=%s AGENTMEMORY_INJECT_CONTEXT=true node" in body
    # Both variables inlined per command, never inherited: an exported variable
    # only reaches processes started after it was set.
    assert "AGENTMEMORY_INJECT_CONTEXT=true" in body


def test_agentmemory_codex_check_requires_all_scripts_and_exact_hook_registrations():
    ps = read_repo("bootstrap/ts-agentmemory.ps1")
    sh = AM_ENTRY.read_text(encoding="utf-8")
    for event in (
        "SessionStart",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
        "PreCompact",
        "Stop",
    ):
        assert event in ps and event in sh
    assert "Test-AmCodexHookRegistrations" in ps
    assert "$set.P.Count -ne $script:CodexScripts.Count" in ps
    assert "has a stale AgentMemory command" in ps
    assert "am_check_codex_hooks" in sh
    assert '"$plugin_count" -ne 6' in sh
    assert '"$stable_count" -ne 6' in sh
    assert "has a stale AgentMemory command" in sh
    # The status probe falls back to a TCP connect: the REST server answers 404
    # on / and 401 on /health, so "no 2xx" is not "not listening".
    agents_impl = "".join(p.read_text(encoding="utf-8") for p in impl_paths("agents"))
    assert "tcp_answers" in agents_impl
    assert 'tcp_answers("127.0.0.1", 3111)' in agents_impl


def test_agentmemory_secret_recovery_uses_the_unix_cache_not_the_registry():
    """`reg query HKCU\\Environment` throws on Unix, is caught, and leaves the
    401 recovery a permanent no-op."""
    sh = AM_SH.read_text(encoding="utf-8")
    sh_code = _uncommented(sh)
    assert "reg query" not in sh_code, "the Windows registry read must not survive the port"
    assert "XDG_CONFIG_HOME" in sh
    # Both cache paths, new first. The legacy read stays because this JavaScript is
    # injected into vendor files on live machines and is only rewritten when
    # --apply runs, so a machine can carry the old reader for a while after the
    # clone updates. Dropping it turns 401-recovery back into a permanent no-op.
    assert '["terminal-stack", "docker-local"]' in sh
    assert '"agentmemory.secret"' in sh
    # The marker must be explicit and shared by every form of the block: with it
    # defaulting to $New, an already-patched file fails the marker test, matches
    # the `function authHeaders() {` anchor the block itself ends with, and gets a
    # SECOND copy of the whole recovery block.
    ps = AM_PS.read_text(encoding="utf-8")
    for text, name in ((sh, "bash"), (ps, "pwsh")):
        i = text.index("stale secret recovery")
        j = text.index("duplicate-invocation guard helper", i)
        assert "'let amFreshSecret = null;'" in text[i:j], (
            f"the {name} twin's recovery edit has no explicit marker"
        )
    # The .ps1 keeps its registry form; this is a deliberate divergence, not drift.
    assert "reg query" in ps


def test_agentmemory_edit_text_matches_the_powershell_twin():
    """Edits keep the @T/@N encoding so the two files' edit text diffs directly.
    These anchors are what break if either side is edited alone."""
    sh, ps = AM_SH.read_text(encoding="utf-8"), AM_PS.read_text(encoding="utf-8")
    for anchor in (
        'const REST_URL = process.env["AGENTMEMORY_URL"] || "http://localhost:3111";',
        'const INJECT_CONTEXT = process.env["AGENTMEMORY_INJECT_CONTEXT"] === "true";',
        "@Tif (isSdkChildContext(data)) return;",
        "//#region src/hooks/pre-tool-use.ts",
    ):
        assert anchor in sh, f"{anchor!r} missing from the bash twin"
        assert anchor in ps, f"{anchor!r} missing from the pwsh twin"
    # Edit ordering is load-bearing: the duplicate-guard helper anchors on the
    # shebang, which the pre-tool-use project-helper edit must consume first.
    assert sh.index("pre-tool-use gains the project helpers") < sh.index(
        "duplicate-invocation guard helper"
    )


def test_agentmemory_is_bash32_clean_and_uses_python_for_json():
    """The repo states bash 3.2: no associative arrays, no mapfile, no ${x,,}.
    JSON is python3 here (json_get in ts-agents.sh), never node."""
    for f in (AM_SH, AM_ENTRY, ROOT / "bootstrap/_merge_json_settings.sh"):
        body = _uncommented(f.read_text(encoding="utf-8"))
        assert "declare -A" not in body, f"{f.name}: associative array"
        assert "mapfile" not in body, f"{f.name}: mapfile is bash 4"
        assert "${x,,}" not in body and ",,}" not in body, f"{f.name}: bash 4 case conversion"
        assert "readlink -f" not in body, f"{f.name}: not portable to older macOS"
        assert "sed -i" not in body, f"{f.name}: sed -i differs on BSD vs GNU"
        assert "node -e" not in body, f"{f.name}: JSON in bash is python3 here"


def test_doctor_checks_agentmemory_natively_not_only_on_wsl():
    """The rule outlives the shell that used to hold it.

    The old bash doctor gated this check on [ -d /mnt/c/Users ], so macOS and
    Linux never checked - and never wired - anything at all. Repointed at
    tstack/commands/doctor.py when doctor was ported; the check must still run
    everywhere, and must still call the bash twin off Windows.
    """
    body = read_repo("tstack/commands/doctor.py")
    seg = body[body.index("def check_agentmemory_wiring") : body.index("def _tts_port")]
    assert "ts-agentmemory.sh" in seg, "doctor must know about the bash twin"
    assert "ts-agentmemory.ps1" in seg, "and the pwsh one on Windows"
    assert "--check" in seg
    assert "/mnt/c/Users" not in seg, (
        "the check must not be gated on a Windows path again - that is the bug"
    )


def test_the_agents_command_invokes_the_hook_wiring(monkeypatch, tmp_path):
    """Installing the plugin is only half the job: without the deployment edits
    the hooks POST nothing and retrieval never fires, and nothing logs it because
    every vendor hook does fetch(...).catch(() => {}) then exits 0. Re-run on
    every on/repair, because a plugin upgrade replaces the cache and silently
    reverts every edit."""
    from tstack.commands import agents

    ran = []
    monkeypatch.setattr(agents, "find_agent", lambda name: None)
    monkeypatch.setattr(agents.subprocess, "run", lambda argv, **k: ran.append(argv) or _Ok())
    memory = agents.AgentMemory(ROOT, agents.Out())
    monkeypatch.setattr(memory, "adapter", lambda: ["bash", "ts-agentmemory.sh"])

    memory.install()
    assert ran and ran[-1][-1] == "--apply"

    ran.clear()
    memory.remove(uninstall=False)
    # The undo runs FIRST, while the plugin cache it patched is still present:
    # the restore reads the backups beside the vendor scripts.
    assert ran[0][-2:] == ["--undo", "--apply"]


class _Ok:
    returncode = 0
    stdout = ""
    stderr = ""


def test_tmux_title_format_uses_the_variable_name_not_the_shorthand():
    """tmux owns the outer terminal's title while attached, which is the only way
    a project name survives Claude Code in a Ghostty tab. The substitution must
    address `session_name`: inside #{...} tmux wants the variable name, and
    `#{s/^cc-//:#S}` silently evaluates to an EMPTY string — a blank tab title,
    which is worse than the noisy one it replaced."""
    conf = (ROOT / "dot_tmux.conf.tmpl").read_text(encoding="utf-8")
    line = next(l for l in conf.splitlines() if l.startswith("set -g set-titles-string"))
    assert "session_name" in line, "must use the variable name, not #S"
    assert ":#S}" not in line, "#{...:#S} renders empty — see the comment above it"
    assert "s/^cc-//" in line, "ccs's cc- prefix must be stripped from the tab title"
    assert "set -g set-titles on" in conf


def test_cc_wrappers_stop_claude_overwriting_the_tab_title():
    """The wrappers set the tab to the project leaf, but Claude Code then writes
    its own OSC title ('✳ Claude Code', later the conversation slug) and wins.
    Only WezTerm has a sticky tab title a script can set; everywhere else the
    wrapper's OSC 2 survives solely because Claude is told not to write one."""
    rc = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    for name in ("cc()", "ccc()", "ccd()", "ccdc()", "ccr()", "ccdr()", "cca()"):
        line = next(l for l in rc.splitlines() if l.startswith(name))
        assert "CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1" in line, (
            f"{name} would have its tab title overwritten by Claude"
        )
        assert "_ts_tab_title" in line
    for name in (
        "function cc ",
        "function ccc ",
        "function ccd ",
        "function ccdc",
        "function ccr ",
        "function ccdr",
        "function cca ",
    ):
        line = next(l for l in ps.splitlines() if l.startswith(name))
        assert "CLAUDE_CODE_DISABLE_TERMINAL_TITLE" in line, (
            f"{name.strip()} (pwsh) would have its tab title overwritten"
        )
        assert "Set-TsTabTitle" in line
    # The old WezTerm-only names must be fully retired on both sides.
    assert "_wez_tab_title" not in rc
    assert "Set-WezTabTitle" not in ps


def test_tab_title_helper_skips_tmux_and_falls_back_to_osc2():
    """tmux owns the outer title while attached and substitutes its own string,
    so emitting OSC 2 there would be swallowed. WezTerm gets its sticky
    override; everything else (Ghostty, Terminal.app) gets OSC 2."""
    rc = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    body = rc[rc.index("_ts_tab_title() {") :]
    body = body[: body.index("\n}\n") + 3]
    assert "WEZTERM_PANE" in body and "set-tab-title" in body
    assert '-z "$TMUX"' in body, "must not emit OSC 2 inside tmux"
    assert "\\033]2;%s\\007" in body or "033]2;" in body


# ── installer robustness ────────────────────────────────────────────────────────

BOOTSTRAP_SH = sorted((ROOT / "bootstrap").glob("*.sh"))


def test_no_bare_variable_followed_by_non_ascii():
    """macOS ships bash 3.2, whose legal_variable_char() is not multibyte-aware:
    under en_US.UTF-8 the lead byte of a UTF-8 char passes isalnum(), so
    `"$desired…"` parses the NAME as `desired\\xE2` — never set — and `set -u`
    aborts. It crashed `tstack doctor --repair` mid-run, after repointing sourceDir
    and before `chezmoi apply`. `bash -n` cannot catch it; brace the variable."""
    bad = []
    pat = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7F\s]")
    for f in BOOTSTRAP_SH:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue  # prose explaining the trap is not the trap
            if pat.search(line):
                bad.append(f"{f.name}:{i}: {line.strip()}")
    assert not bad, "brace these: " + "; ".join(bad)


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_optional_installs_are_never_fatal():
    """`set -e` exempts only the NON-final members of an && / || list, so
    `brew list --cask zed || brew install --cask zed` is not guarded at all. That
    one line aborted a real install at line 55 of 207 and discarded every wizard
    answer. Every optional install must end in a `||` fallback."""
    cfg = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    assert "ts_note_failure" in cfg and "ts_report_failures" in cfg
    for f in (ROOT / "bootstrap/_config.sh", ROOT / "bootstrap/mac-bootstrap.sh"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            st = line.strip()
            if st.startswith("#") or "brew install" not in st:
                continue
            # The prerequisite formulae are deliberately fatal: without
            # zsh/git/starship/chezmoi there is no stack to configure.
            if "zsh git starship chezmoi" in st:
                continue
            assert st.endswith("\\") or "||" in st, f"{f.name}:{i} unguarded install: {st}"
    # --adopt destroyed a real /Applications/Zed.app; never reintroduce it.
    # Comments explaining that are not the thing being banned.
    code = _uncommented(cfg)
    assert "--adopt" not in code, "brew --cask --adopt can delete the app it adopts"
    assert "--cask --force" not in code


def test_wizard_answers_persist_before_any_optional_install():
    """Persistence used to run at the very end, so an install that aborted the
    script threw away every answer the user had just typed. Two shapes satisfy
    this: macOS persists inline before its installs; the Debian wrappers hand
    _common-debian.sh a TS_PERSIST_HOOK that it calls before any optional step."""
    mac = _uncommented((ROOT / "bootstrap/mac-bootstrap.sh").read_text(encoding="utf-8"))
    assert mac.index("ts_save_config") < mac.index("ts_brew_install_apps"), (
        "mac-bootstrap installs apps before saving the wizard answers"
    )
    # The agent WIRING needs the CLIs installed, so it alone stays late.
    assert mac.index("ts_agents_apply_wizard") > mac.index("ts_save_config")

    deb = (ROOT / "bootstrap/_common-debian.sh").read_text(encoding="utf-8")
    body = deb[deb.index("common_install_all() {") :]
    body = body[: body.index("\n}\n")]
    body = _uncommented(body)  # index the calls, not the prose about them
    hook = body.index("TS_PERSIST_HOOK")
    for installer in ("common_install_selected_apps", "common_install_terminals"):
        assert hook < body.index(installer), (
            f"_common-debian.sh: {installer} runs before the persistence hook"
        )
    # chezmoi must precede the hook: ts_save_config runs `chezmoi init`.
    assert body.index("common_chezmoi") < hook

    for name in ("linux-bootstrap.sh", "wsl-bootstrap.sh"):
        w = (ROOT / "bootstrap" / name).read_text(encoding="utf-8")
        assert "TS_PERSIST_HOOK=_ts_persist_wizard" in w, f"{name} sets no hook"
        assert "ts_save_config" in w[w.index("_ts_persist_wizard() {") :], (
            f"{name}: the hook does not actually save"
        )


def test_terminal_tick_list_enforces_one_wezterm_channel_live():
    """Both casks own /Applications/WezTerm.app, so both ticked is impossible.
    The constraint used to run only after Enter, so the screen showed [x] [x]."""
    wiz = (ROOT / "bootstrap/_wizard.sh").read_text(encoding="utf-8")
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "TS_MULTI_EXCLUSIVE" in wiz
    assert 'TS_MULTI_EXCLUSIVE="wezterm-nightly wezterm-stable"' in wiz
    assert "$Exclusive" in ps and "-Exclusive @('wezterm-nightly', 'wezterm-stable')" in ps
    # The env path returned early without the constraint on both sides.
    assert "ts_terminals_one_channel" in wiz
    assert wiz.count("ts_terminals_one_channel") >= 3  # def + env path + picker


# The exclusive collapse is driven by the index of whatever was just ticked. That
# index is only a "winner" when it is IN the group: ticking an option outside it
# gave every ticked member a $keep no member could equal, so the whole group was
# cleared. On macOS the terminal question is the only exclusive one and Ghostty is
# the only non-member, so ticking Ghostty returned Ghostty ALONE — WezTerm dropped
# out of the selection with nothing on screen to say so. Both twins had it; the
# pwsh side was unreachable behind the Read-TsMulti crash.
_EXCL_CASES = [
    # answers typed,  expected selection
    (["3", ""], ["wezterm-nightly", "ghostty"]),  # non-member must not collapse
    (["2", ""], ["wezterm-stable"]),  # member still evicts its rival
    (["3", "2", ""], ["wezterm-stable", "ghostty"]),
    (["2", "3", ""], ["wezterm-stable", "ghostty"]),
    (["a", ""], ["wezterm-nightly", "ghostty"]),  # all: group collapses to the tie-break
    (["1", ""], []),
]

# ts_prompt_multi reads its answer inside a nested $( ), so a shell-variable
# cursor would reset on every call. Keep it on disk.
_EXCL_BASH = """
. bootstrap/_config.sh >/dev/null 2>&1
. bootstrap/_wizard.sh
ts_is_interactive() { return 0; }
Q=$(mktemp); N=$(mktemp); echo 0 > "$N"
printf '%s\n' ANSWERS > "$Q"
ts_tty_prompt() { local i; i=$(cat "$N"); sed -n "$((i+1))p" "$Q"; echo $((i+1)) > "$N"; }
TS_MULTI_EXCLUSIVE="wezterm-nightly wezterm-stable" ts_prompt_multi \
    "wezterm-nightly" "T:" "" \
    "wezterm-nightly|nightly|" "wezterm-stable|stable|" "ghostty|ghostty|"
rm -f "$Q" "$N"
"""

_EXCL_PWSH = (
    ". ./bootstrap/_config.ps1; "
    "function Test-TsInteractive { $true }; "
    "$script:q = [System.Collections.Queue]::new(@(ANSWERS)); "
    "function Read-Host { param([string]$Prompt) "
    "if ($script:q.Count) { $script:q.Dequeue() } else { '' } }; "
    "$r = Read-TsMulti -Title 'T:' -Options @("
    "@{Key='wezterm-nightly';Label='nightly'},"
    "@{Key='wezterm-stable';Label='stable'},"
    "@{Key='ghostty';Label='ghostty'}) "
    "-Preticked @('wezterm-nightly') "
    "-Exclusive @('wezterm-nightly','wezterm-stable') 6>$null; "
    "Write-Output ('RESULT=' + ($r -join ' '))"
)


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_exclusive_group_survives_a_non_member_tick_bash():
    for answers, want in _EXCL_CASES:
        script = _EXCL_BASH.replace("ANSWERS", " ".join(f'"{a}"' for a in answers))
        r = subprocess.run(
            [BASH, "-c", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            stdin=subprocess.DEVNULL,
            timeout=60,
            start_new_session=True,
        )
        assert r.stdout.split() == want, f"{answers}: got {r.stdout.split()!r}"


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell 7 is unavailable")
def test_exclusive_group_survives_a_non_member_tick_pwsh():
    """The pwsh twin must reach the same six answers as the bash one."""
    for answers, want in _EXCL_CASES:
        command = _EXCL_PWSH.replace("ANSWERS", ",".join(f"'{a}'" for a in answers))
        r = subprocess.run(
            [shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=300,
            start_new_session=True,
        )
        line = next((l for l in r.stdout.splitlines() if l.startswith("RESULT=")), None)
        assert line is not None, r.stdout + r.stderr
        assert line[len("RESULT=") :].split() == want, f"{answers}: got {line!r}"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_installed_apps_report_survives_a_tool_that_rejects_version():
    """The report assigned a four-stage pipeline directly, so under
    `set -euo pipefail` any tool whose --version exits non-zero killed the
    function — and with it `finish`, so `chezmoi apply` silently never ran.
    tmux is exactly that tool (it wants -V) and is FIRST in the recommended
    list, so this fired on every single run."""
    script = (
        "set -euo pipefail\n"
        ". bootstrap/_config.sh >/dev/null 2>&1\n"
        # A binary that exits non-zero for BOTH --version and -V is the worst case.
        "mkdir -p /tmp/_tsbin\n"
        'printf "#!/bin/sh\\nexit 3\\n" > /tmp/_tsbin/tmux; chmod +x /tmp/_tsbin/tmux\n'
        'PATH=/tmp/_tsbin:$PATH ts_report_installed_apps "tmux" >/dev/null\n'
        "echo SURVIVED\n"
    )
    r = subprocess.run(
        [BASH, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        start_new_session=True,
    )
    assert "SURVIVED" in r.stdout, f"report aborted: {r.stderr.strip()[:200]}"
    # And the guard must be in the source, not incidental.
    cfg = _uncommented((ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8"))
    body = cfg[cfg.index("ts_report_installed_apps()") :]
    body = body[: body.index("\n}\n")]
    assert "--version 2>/dev/null || true" in body, "version probe must not be fatal"
    assert "-V 2>/dev/null" in body, "tmux-style tools need the -V fallback"


def test_ts_config_wizard_asks_about_terminals_and_saves_first():
    """`tstack config wizard` never set TS_WIZ_ASK_TERMINALS, so it skipped the
    question and reported 'none selected' — a re-run could not switch WezTerm
    channel, which is a main reason to run it again. And like the bootstraps it
    must save before installing."""
    body = _uncommented((ROOT / "bootstrap/ts-config.sh").read_text(encoding="utf-8"))
    rw = body[body.index("run_wizard()") :]
    rw = rw[: rw.index("\n}\n")]
    assert "TS_WIZ_ASK_TERMINALS=1" in rw, "tstack config wizard must ask about terminals"
    assert rw.index("ts_save_config") < rw.index("install_apps"), (
        "run_wizard installs before saving the answers"
    )
    assert "ts_note_failure" in rw, "installs here must not be fatal either"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_wizard_prompts_run_without_undefined_functions():
    """A RUNTIME smoke test, because the static text checks around it missed two
    real regressions: `exclusive -1` was called before its function was defined,
    and ts-config.sh called ts_is_headless without sourcing _detect.sh. Both
    printed 'command not found' in a live run and silently skipped their work."""
    script = (
        'SRC="$PWD"\n'
        '. "$SRC/bootstrap/_config.sh" >/dev/null 2>&1\n'
        '. "$SRC/bootstrap/_wizard.sh"\n'
        '. "$SRC/bootstrap/_detect.sh"\n'
        # every function ts-config.sh / the bootstraps call on the wizard path
        "for f in ts_is_headless ts_is_interactive ts_prompt_multi ts_prompt_choice \\\n"
        "         ts_prompt_terminals ts_terminals_one_channel ts_wizard_collect \\\n"
        "         ts_note_failure ts_report_failures; do\n"
        '  command -v "$f" >/dev/null || echo "UNDEFINED: $f"\n'
        "done\n"
        # and actually drive the picker, which is where the ordering bug lived
        'TS_MULTI_EXCLUSIVE="a b" ts_prompt_multi "a b" "T:" "" "a|A|" "b|B|" "c|C|"\n'
    )
    # start_new_session detaches the child from the controlling terminal, so
    # opening /dev/tty fails - which is the state this test already says it
    # expects ("legitimately absent under pytest"). stdin=DEVNULL is not enough:
    # ts_prompt_multi reads from /dev/tty, not stdin, so wherever a tty exists
    # the prompt blocks forever. It does under WSL and it does not under Git
    # Bash, which is why this passed on Windows and hung on Linux.
    # The timeout turns any future regression of that shape into a failure
    # rather than a hang.
    r = subprocess.run(
        [BASH, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        timeout=120,
    )
    assert "UNDEFINED:" not in r.stdout, r.stdout
    # /dev/tty is legitimately absent under pytest; anything else is a real fault.
    noise = [l for l in r.stderr.splitlines() if l.strip() and "/dev/tty" not in l]
    assert not noise, "wizard emitted errors: " + "; ".join(noise)
    # The exclusive group must have collapsed a pre-tick of BOTH a and b.
    picked = r.stdout.replace("UNDEFINED:", "").split()
    assert picked == ["a"], f"exclusive group not applied: {picked!r}"


def test_ts_config_sources_what_it_calls():
    """ts-config.sh called ts_is_headless, which lives in _detect.sh and was
    never sourced there."""
    body = (ROOT / "bootstrap/ts-config.sh").read_text(encoding="utf-8")
    # Match the SOURCE STATEMENT, not the shellcheck comment above it.
    src_line = next(
        (l for l in body.splitlines() if l.strip().startswith(". ") and "_detect.sh" in l), None
    )
    assert src_line, "ts-config.sh must source _detect.sh"
    assert body.index(src_line) < body.index("ts_is_headless ||"), (
        "_detect.sh sourced after first use of ts_is_headless"
    )


# ── wizard recommendations + readiness probing ──────────────────────────────────


def test_service_probes_treat_any_http_response_as_up(monkeypatch):
    """AgentMemory answers 404 on / and 401 on /agentmemory/health, and `curl
    -fsS` turns either into a failure - so this reported the service DOWN while it
    was up and serving. Any HTTP response proves something is listening."""
    import urllib.error

    from tstack.commands import agents

    def answer(status):
        def probe(url, timeout=None):
            raise urllib.error.HTTPError(url, status, "no", {}, None)

        return probe

    for status in (401, 404, 500):
        monkeypatch.setattr(agents.urllib.request, "urlopen", answer(status))
        assert agents.http_answers("http://127.0.0.1:3111") is True, status

    def refuse(url, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(agents.urllib.request, "urlopen", refuse)
    assert agents.http_answers("http://127.0.0.1:3111") is False

    # And the shell that still probes services keeps the same rule.
    body = _uncommented(read_repo("bootstrap/_config.sh"))
    assert "curl -fsS" not in body or "ts_probe_http_ok" in body


def test_wizard_recommends_and_probes_before_offering():
    """Blind on/off questions let a machine be wired to a service that is not
    running — which then fails later and silently, because the agentmemory hooks
    swallow errors and exit 0. Probe first, default from what was found."""
    wiz = (ROOT / "bootstrap/_wizard.sh").read_text(encoding="utf-8")
    for fn in ("ts_prompt_wezterm_mux", "ts_prompt_wezterm_restore", "ts_prompt_atuin"):
        body = wiz[wiz.index(f"{fn}() {{") :]
        body = body[: body.index("\n}\n")]
        assert "RECOMMENDATION:" in body, f"{fn} has no recommendation"
    # atuin now defaults to ON; the other two stay off.
    at = wiz[wiz.index("ts_prompt_atuin() {") :]
    at = at[: at.index("\n}\n")]
    assert "ts_prompt_choice on " in at, "atuin should default to on"
    for fn in ("ts_prompt_wezterm_mux", "ts_prompt_wezterm_restore"):
        b = wiz[wiz.index(f"{fn}() {{") :]
        b = b[: b.index("\n}\n")]
        assert "ts_prompt_choice off " in b, f"{fn} should default to off"
    # Headroom and AgentMemory are no longer two independent toggles -- that is
    # what made "both memory systems on" reachable -- but the reason for probing
    # them is unchanged: a machine wired to a service that is not running fails
    # later and silently. Both probes run inside the one memory question, and
    # their output is in what the question prints.
    mem = wiz[wiz.index("ts_prompt_memory_backend() {") :]
    mem = mem[: mem.index("\n}\n")]
    assert "ts_probe_agentmemory" in mem and "ts_probe_headroom" in mem, (
        "the memory question must probe both services before offering"
    )
    assert mem.index("ts_probe_agentmemory") < mem.index("ts_prompt_choice"), (
        "probe before offering, not after"
    )
    assert "${am_report}" in mem and "${hr_report}" in mem, (
        "the probe output must reach the question the user reads"
    )
    assert "RECOMMENDATION:" in mem
    # The default is a CHOICE, not a probe result. Deriving it from the probe
    # would recommend "none" on a first install -- where nothing is running yet,
    # by definition -- and talk a newcomer out of the feature they came for.
    assert "ts_prompt_choice agentmemory " in mem, "the recommended answer must be agentmemory"
    # And the two blind toggles must not come back.
    assert 'TS_WIZ_HEADROOM="$(ts_prompt_agent_toggle' not in wiz
    assert 'TS_WIZ_AGENTMEMORY="$(ts_prompt_agent_toggle' not in wiz


def test_platform_impossible_apps_are_not_offered_forever():
    """nvtop is Linux-only, so on macOS it can never install — it was reported
    missing on every tstack update, accepted, and printed 'Linux-only; skipping'."""
    cfg = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    assert "ts_app_installable" in cfg
    pend = cfg[cfg.index("ts_apps_pending() {") :]
    pend = pend[: pend.index("\n}\n")]
    assert "ts_app_installable" in pend, "pending list must filter impossible ids"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_nightly_is_preticked_even_when_stable_is_installed():
    """Pre-ticking 'whatever is installed' meant a stable box saw nightly
    unticked, so pressing Enter — the thing everyone does — silently kept a
    February 2024 build that this stack's WezTerm config is not written for.
    Nightly is pre-selected regardless; only a hand-installed WezTerm
    ('unknown', not ours to replace) leaves both unticked."""
    wiz = (ROOT / "bootstrap/_wizard.sh").read_text(encoding="utf-8")
    body = wiz[wiz.index("ts_prompt_terminals() {") :]
    body = body[: body.index("\n}\n")]
    assert 'stable)  preticked="wezterm-stable"' not in body, "installed-wins pre-tick is back"
    assert "RECOMMENDATION: nightly" in body

    def pretick(channel):
        script = (
            ". bootstrap/_config.sh >/dev/null 2>&1\n"
            ". bootstrap/_wizard.sh\n"
            f"ts_wezterm_channel() {{ echo {channel}; }}\n"
            # Stub the intro: it fetches upstream release data over the network,
            # which makes this test slow and dependent on being online.
            "ts_wezterm_prompt_intro() { :; }\n"
            # non-interactive keeps the pre-ticks, so the answer IS the pre-tick
            "ts_prompt_terminals 2>/dev/null\n"
        )
        r = subprocess.run(
            [BASH, "-c", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=300,
            start_new_session=True,
        )
        return r.stdout.split()

    for ch in ("stable", "nightly", "none"):
        assert "wezterm-nightly" in pretick(ch), f"{ch}: nightly not pre-ticked"
        assert "wezterm-stable" not in pretick(ch), f"{ch}: stable pre-ticked"
    # A hand-placed WezTerm is left alone.
    got = pretick("unknown")
    assert "wezterm-nightly" not in got and "wezterm-stable" not in got, got

    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "'stable'  { @('wezterm-stable') }" not in ps, "pwsh twin still installed-wins"


# ── TTS on macOS: self summarizer + the say floor ──────────────────────────────

CC_TTS_LIB = ROOT / "dot_claude/hooks/cc-tts-lib.sh"


def _self_summary_sh(text):
    r = subprocess.run(
        [
            BASH,
            "-c",
            '. dot_claude/hooks/cc-tts-lib.sh 2>/dev/null; cc_tts_self_summary "$1"',
            "_",
            text,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        start_new_session=True,
    )
    return r.stdout.strip()


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_self_summarizer_matches_the_python_daemon():
    """`self` was implemented only in ttsd/summarize.py, which runs inside the
    Windows EXE — so on macOS/Linux it was accepted, persisted and never read,
    while STILL appending the marker block to ~/.claude/CLAUDE.md. The shell
    twin must agree with the Python on the same input, the parity rule this
    repo already applies to its bash/pwsh twins."""
    sys.path.insert(0, str(ROOT / "bootstrap/tts-daemon"))
    try:
        from ttsd.summarize import Summarizer
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"ttsd not importable: {exc}")
    cases = [
        "x <!-- speak: All tests pass. -->",
        "<!-- speak: a --> <!-- speak: b two -->",  # last marker wins
        "# Heading\n- Migrated the parser to the new tokenizer and every single "
        "one of the tests now passes cleanly.\nmore",  # 15-word cap
        "```\ncode here\n```\nRefactored the loader.",  # fenced code dropped
        "Just one short sentence. And a second one.",
        "",
    ]
    for c in cases:
        assert _self_summary_sh(c) == Summarizer._self_summary(c).strip(), (
            f"shell/python disagree on {c!r}"
        )


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_codex_direct_stop_message_feeds_self_summary(tmp_path):
    """Codex Stop input carries the final response at the top level, unlike
    Claude's transcript-shaped payload. Missing that field silently fell back
    to the fixed template even when the user selected self."""
    config = tmp_path / "tts.json"
    config.write_text(json.dumps({"summarize": {"mode": "self"}}), encoding="utf-8", newline="\n")
    script = r"""
        export CC_TTS_SOURCE=codex
        export CC_TTS_HOOK_JSON='{"last_assistant_message":"Done. <!-- speak: Codex used its own summary. -->"}'
        . dot_claude/hooks/cc-tts-lib.sh 2>/dev/null
        cc_tts_build_speech codex waiting terminal-stack
    """
    env = dict(os.environ, CC_TTS_CONFIG=bash_path(config))
    result = subprocess.run(
        [BASH, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env=env,
        timeout=300,
        start_new_session=True,
    )
    assert "Codex used its own summary" in result.stdout
    assert "I'm waiting for you" not in result.stdout


def test_ghostty_preserves_standard_macos_window_cycle_shortcut():
    cfg = (ROOT / "dot_config/ghostty/config.tmpl").read_text(encoding="utf-8")
    assert "toggle_quick_terminal" not in cfg
    assert "quick-terminal-" not in cfg
    assert "global:cmd+grave_accent" not in cfg


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_speak_marker_is_never_spoken_verbatim():
    """In hook mode the raw final message IS the speech text, so a
    <!-- speak: … --> comment would be read out loud. _speakable() is
    Python-side only and has no shell twin."""
    r = subprocess.run(
        [
            BASH,
            "-c",
            ". dot_claude/hooks/cc-tts-lib.sh 2>/dev/null; "
            'cc_tts_strip_markers "Done. <!-- speak: hidden text --> tail"',
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        start_new_session=True,
    )
    assert "hidden text" not in r.stdout and "<!--" not in r.stdout, r.stdout
    lib = CC_TTS_LIB.read_text(encoding="utf-8")
    assert "cc_tts_strip_markers" in lib
    # self applies to the done event only, matching summarize.py:84-99.
    body = lib[lib.index("cc_tts_build_speech() {") :]
    assert '[ "$state" = waiting ]' in body, "self must not fire on question/permission/error"


def test_macos_has_a_synthesis_floor():
    """The ladder was Kokoro -> Chatterbox -> edge-tts -> SILENCE. Windows falls
    back to SAPI; /usr/bin/say ships with every Mac and was never used, so a
    stock Mac could have TTS fully 'on' and hear nothing, with the worker
    detached and its output discarded."""
    lib = CC_TTS_LIB.read_text(encoding="utf-8")
    assert "cc_tts_synth_say" in lib
    synth = lib[lib.index("\ncc_tts_synth() {") :]
    synth = synth[: synth.index("\n}\n")]
    # say must be the LAST rung of the FALLBACK chain, after edge.
    #
    # The anchor moved when `say` became a selectable engine: it now also appears
    # in the `case` above, where being first is the whole point of choosing it.
    # The rule did not move -- say must never be preferred over a real engine
    # that was NOT chosen -- so the assertion is scoped to the chain after the
    # case rather than to the whole function.
    chain = synth[synth.index("esac") :]
    assert chain.index("cc_tts_synth_edge") < chain.index("cc_tts_synth_say"), (
        "say must be the floor, not preferred over a real engine"
    )
    # And being chosen has to be distinguishable from falling through, or the
    # daily "using the system voice" notice nags about a deliberate decision.
    case = synth[: synth.index("esac")]
    assert "cc_tts_synth_say" in case and "chosen" in case, (
        "the chosen path must pass a marker the fallback path does not"
    )
    say = lib[lib.index("cc_tts_synth_say() {") :]
    say = say[: say.index("\n}\n")]
    # `say -o out.mp3` exits 0 and writes a 16-byte junk file: it picks format
    # from the extension and only really writes AIFF.
    assert ".aiff" in say, "say must synthesise to .aiff, not the caller's extension"
    assert "-gt 1024" in say, "must reject the junk-file case, not trust exit status"


def test_ts_config_and_tts_are_findable_by_name():
    """`doc tstack` matched ZERO labels — the material existed inside
    common/stack.md, which no one would guess. And the cross-platform half of
    the TTS docs lived in windows/, which the picker hides on other OSes."""
    kb = ROOT / "docs/kb/common"
    assert (kb / "tstack.md").exists(), "no page named for tstack"
    assert (kb / "tts.md").exists(), "no OS-neutral TTS page"
    # The support matrix is the point of the TTS page.
    tts = (kb / "tts.md").read_text(encoding="utf-8")
    for must in ("macOS / native Linux", "daemon-only", "say", "SAPI", "self"):
        assert must in tts, f"tts.md missing {must!r}"
    # stack.md should point at the new page, not duplicate it.
    stack = (kb / "stack.md").read_text(encoding="utf-8")
    assert "doc tstack" in stack
    assert "tstack config agents headroom cursor" not in stack, "table left behind in stack.md"
    # _index.md advertised windows/ as "pwsh, winget" and omitted the TTS page.
    idx = (ROOT / "docs/kb/_index.md").read_text(encoding="utf-8")
    assert "TTS" in idx.split("`windows/`")[1].split("\n")[0]


def test_doc_reports_a_miss_before_falling_back_to_fzf():
    """A zero-match query dropped straight into fzf, which re-queried the
    NARROWER per-OS index — so the user got an empty picker and no message."""
    rc = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    body = rc[rc.index("_doc_open() {") :]
    body = body[: body.index("\n}\n")]
    miss = body.index("no topic matching")
    fzf = body.index("_doc_finder")
    assert miss < fzf, "must report the miss before handing off to fzf"


def test_tts_wizard_is_platform_aware_and_asks_what_it_says():
    """One binary question was the whole TTS wizard; engine, voice and message
    mode were never asked. And daemon-only modes must not be offered on a host
    that cannot run a daemon."""
    tts = (ROOT / "bootstrap/_cc_tts.sh").read_text(encoding="utf-8")
    assert "ts_prompt_cc_tts_message" in tts, "no question about what it says"
    msg = tts[tts.index("ts_prompt_cc_tts_message() {") :]
    msg = msg[: msg.index("\n}\n")]
    assert "RECOMMENDATION: self" in msg
    for mode in ("self", "template", "hook"):
        assert f"'{mode}|{mode}|" in msg, f"{mode} not offered"
    for daemon_only in ("haiku", "ollama"):
        assert f"'{daemon_only}|" not in msg, f"{daemon_only} needs a daemon; must not be offered"
    # Probed, not hardcoded.
    assert "ts_cc_tts_engine_report" in tts
    # Daemon-only settings refuse rather than storing a value nothing reads.
    code = _uncommented(tts)
    for verb in ("music", "duck-level"):
        arm = code[code.index(f"        {verb})") :]
        arm = arm[: arm.index("\n            ;;")]
        assert "ts_cc_tts_daemon_supported" in arm, f"{verb} has no platform guard"
    # Bare `tstack config tts` shows status like every sibling verb.
    assert "''|show)" in tts


def test_wizard_does_not_reset_tuned_tts_keys():
    """ts_cc_tts_apply_wizard_choice reset every key on BOTH on and off, so each
    `tstack config wizard` silently discarded any `tstack config tts …` tuning."""
    body = (ROOT / "bootstrap/_cc_tts.sh").read_text(encoding="utf-8")
    fn = body[body.index("ts_cc_tts_apply_wizard_choice() {") :]
    fn = fn[: fn.index("\n}\n")]
    assert '[ -n "$configured" ] || ts_cc_tts_reset_defaults' in fn, (
        "defaults must only be seeded on a never-configured host"
    )


def test_say_is_a_selectable_engine_and_is_macos_gated():
    """`say` was the floor and nothing else: not a legal `engine` value, and no
    way to pick which of the Mac's 184 voices it used. It is now both, and the
    setter refuses it off Darwin rather than saving a choice that can never take
    effect -- Windows falls back to SAPI and Linux has no floor at all."""
    sh = repo_file("bootstrap/_cc_tts.sh").read_text(encoding="utf-8")
    assert "kokoro|chatterbox|say|auto" in sh, "the engine enum must accept say"
    arm = sh[sh.index("        engine)") :]
    arm = arm[: arm.index("        message)")]
    assert "Darwin" in arm, "say must be refused off macOS at set time"


def test_the_engine_enum_agrees_across_every_copy_that_can_serve_it():
    """Three copies existed and one was wrong (the Python schema said `edge`,
    which the setter refuses). The daemon's list is DELIBERATELY different and
    stays that way: it is Windows-only, and `say` is macOS-only."""
    sh = repo_file("bootstrap/_cc_tts.sh").read_text(encoding="utf-8")
    schema_py = repo_file("tstack/schema.py").read_text(encoding="utf-8")
    assert '"kokoro", "chatterbox", "say", "auto"' in schema_py
    assert "kokoro|chatterbox|say|auto" in sh
    daemon = repo_file("bootstrap/tts-daemon/ttsd/settings_schema.py").read_text(encoding="utf-8")
    assert '("kokoro", "chatterbox", "auto")' in daemon, (
        "the daemon is Windows-only, so it must NOT offer the macOS say engine"
    )


def test_the_say_voice_reaches_the_runtime_config():
    """A setting the reader never sees is a setting that does nothing. The
    reader is cc-tts-lib.sh's `.say.voice`, rendered by config.json.tmpl and
    mirrored by ts_cc_tts_json_for_mirror."""
    assert '"voice": {{ index . "ccTtsSayVoice"' in repo_file(
        "dot_claude/tts/config.json.tmpl"
    ).read_text(encoding="utf-8")
    assert "ccTtsSayVoice" in repo_file(".chezmoi.toml.tmpl").read_text(encoding="utf-8")
    sh = repo_file("bootstrap/_cc_tts.sh").read_text(encoding="utf-8")
    assert '"say": {' in sh, "the Windows mirror must carry the say block"
    lib = repo_file("dot_claude/hooks/cc-tts-lib.sh").read_text(encoding="utf-8")
    assert "cc_tts_json .say.voice" in lib, "nothing reads it"
    # `say -v ""` is an error, not a synonym for the system voice, so an unset
    # value must omit the flag rather than pass it empty.
    say = lib[lib.index("cc_tts_synth_say() {") :]
    say = say[: say.index("\n}\n")]
    assert 'say -o "$tmp"' in say, "an unset voice must omit -v entirely"


def test_listing_voices_asks_the_engine_rather_than_a_hardcoded_table():
    """kokoro ships 68 and the set moves with the image; a Mac has 184 with more
    downloadable. Any list checked in here would be wrong on somebody's machine
    the week it was written."""
    sh = repo_file("bootstrap/_cc_tts.sh").read_text(encoding="utf-8")
    fn = sh[sh.index("ts_cc_tts_list_voices() {") :]
    fn = fn[: fn.index("\n}\n")]
    assert "/v1/audio/voices" in fn, "kokoro's own list endpoint"
    assert "say -v '?'" in fn, "the macOS list"
    assert "am_adam" not in fn and "af_heart" not in fn, "no hardcoded voice names"


def test_the_voice_pool_moved_out_of_the_way_of_listing():
    """`voices` used to set the daemon's per-session rotation pool -- unrelated
    to picking a voice, and read only on Windows. It lists now; the pool is
    `voice-pool`. The old CSV form is redirected rather than silently honoured,
    which a voice name can never be mistaken for because it has no comma."""
    sh = repo_file("bootstrap/_cc_tts.sh").read_text(encoding="utf-8")
    assert "        voice-pool)" in sh
    arm = sh[sh.index("        voices)") :]
    arm = arm[: arm.index("        voice-pool)")]
    assert "*,*)" in arm, "a CSV must be routed to voice-pool, not treated as a name"
    assert "ts_cc_tts_list_voices" in arm


def test_windows_has_a_synthesis_floor_too():
    """The macOS gap, still open on the platform this stack started on.

    Invoke-CcTtsSynth's ladder ended at edge-tts and returned $false, so a
    native-Windows host with the daemon off, kokoro down and edge-tts absent
    produced nothing. SAPI is the floor, and it SPEAKS rather than writing a
    file: the Windows playback path is cc-tts-play.ps1, which requires ffplay and
    errors without it, so a file-based floor would still be silent on exactly the
    machine that needs one.
    """
    lib = repo_file("windows/.claude/hooks/cc-tts-lib.ps1").read_text(encoding="utf-8")
    assert "function Invoke-CcTtsSapiSpeak" in lib
    fn = lib[lib.index("function Invoke-CcTtsSapiSpeak") :]
    fn = fn[: fn.index("\nfunction ")]
    assert "SAPI.SpVoice" in fn and ".Speak(" in fn
    assert "OutFile" not in fn and "OutPath" not in fn, (
        "the floor must not depend on a file, and so not on ffplay"
    )
    assert "catch" in fn, "a failing floor must leave things no worse than silence"

    notify = repo_file("windows/.claude/hooks/cc-tts-notify.ps1").read_text(encoding="utf-8")
    worker = notify[notify.index("function Start-SpeakWorker") :]
    worker = worker[: worker.index("\nif ($Foreground)")]
    # Both early returns were silence; both must now fall through to the floor.
    assert worker.count("Invoke-CcTtsSapiSpeak") == 2, (
        "every path that gave up before playing must reach the floor"
    )


# --------------------------------------------------------------- tstack agents llm


def _llm_env(tmp_path, monkeypatch, body: str | None):
    """A throwaway stack root. TS_STACK_ROOT is what stacks.stack_root honours."""
    root = tmp_path / "stacks" / "agentmemory"
    root.mkdir(parents=True)
    if body is not None:
        (root / ".env").write_text(body, encoding="utf-8")
    monkeypatch.setenv("TS_STACK_ROOT", str(tmp_path / "stacks"))
    return root


def test_no_chat_provider_is_reported_as_a_supported_state(tmp_path, monkeypatch, capsys):
    """The point of the command. An absent LLM is a CHOICE with four named
    consequences, not a fault -- storage, search and embeddings are unaffected,
    and telling someone their memory server is broken because they never wired a
    model to it is how a supported configuration reads as an outage.
    """
    from tstack.commands import agents

    _llm_env(tmp_path, monkeypatch, "EMBEDDING_PROVIDER=local\n")
    rc = agents.Llm(ROOT, agents.Out()).run("status")
    text = capsys.readouterr().out

    assert rc == 0, "no provider is not a failure"
    assert "supported state" in text
    for name, _ in agents.LLM_FEATURES:
        assert f"off  {name}" in text, f"{name} must be named as switched off"
    for name, _ in agents.LLM_UNAFFECTED:
        assert f"ok  {name}" in text, f"{name} works without a model and must say so"
    assert "llmfit" in text, "the way to pick a model that fits this machine"


def test_an_endpoint_with_no_model_leaves_every_feature_off(tmp_path, monkeypatch, capsys):
    """`inferenceActive` is driven by the MODEL, not the URL (see the console's
    shared/llmEndpoint.ts). A base URL with an empty OPENAI_MODEL therefore reads
    as configured everywhere while every family stays off -- the exact shape that
    has to be called out rather than shown as a tick.
    """
    from tstack.commands import agents

    _llm_env(tmp_path, monkeypatch, "OPENAI_BASE_URL=http://127.0.0.1:9/v1\nOPENAI_MODEL=\n")
    rc = agents.Llm(ROOT, agents.Out()).run("status")
    text = capsys.readouterr().out

    assert rc == 1
    assert "OPENAI_MODEL is empty" in text
    for name, _ in agents.LLM_FEATURES:
        assert f"off  {name}" in text


def test_an_unreachable_provider_is_louder_than_no_provider(tmp_path, monkeypatch, capsys):
    """The asymmetry this whole workstream exists for: unset is a clean skip,
    set-but-unreachable dead-letters silently. Port 9 is discard -- nothing
    answers, and nothing is dialled outside the machine.
    """
    from tstack.commands import agents

    _llm_env(tmp_path, monkeypatch, "OPENAI_BASE_URL=http://127.0.0.1:9/v1\nOPENAI_MODEL=m\n")
    out = agents.Out()
    rc = agents.Llm(ROOT, out).run("status")
    text = capsys.readouterr().out

    assert rc == 1 and out.failures
    assert "dead-letter" in text


def test_a_host_probe_is_never_reported_as_container_reachability(tmp_path, monkeypatch, capsys):
    """A container's DNS is Docker's embedded resolver and its egress a separate
    path, so reaching an endpoint from here proves nothing about the server. The
    success line has to say so, and name the check that does dial from inside.
    """
    from tstack.commands import agents

    _llm_env(tmp_path, monkeypatch, "OPENAI_BASE_URL=http://example.invalid/v1\nOPENAI_MODEL=m\n")
    monkeypatch.setattr(agents, "http_answers", lambda *a, **k: True)
    agents.Llm(ROOT, agents.Out()).run("status")
    text = capsys.readouterr().out

    assert "does not prove the container can reach it" in text
    assert "tstack services test agentmemory" in text


def test_llm_has_no_action_but_status(tmp_path, monkeypatch, capsys):
    """`on`/`off` are valid ACTIONS for the other tools, so main() lets them
    through to here. Rejected as a usage error (2), not as a probe failure (1)."""
    from tstack.commands import agents

    _llm_env(tmp_path, monkeypatch, "")
    assert agents.Llm(ROOT, agents.Out()).run("on") == 2
    assert "is a report" in capsys.readouterr().err


def test_the_llm_report_reads_the_env_file_rather_than_the_container(tmp_path, monkeypatch):
    """It must be right while the stack is DOWN -- that is when someone is most
    likely to be asking why nothing is being summarised. Reading compose's own
    interpolation source keeps one copy of the truth and needs no engine.
    """
    from tstack.commands import agents

    _llm_env(tmp_path, monkeypatch, "OPENAI_BASE_URL=http://h/v1\nOPENAI_MODEL=m\n")
    assert agents.Llm(ROOT, agents.Out()).configured() == ("http://h/v1", "m")


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_llmfit_is_offered_but_never_routed_through_the_agent_cli_installer():
    """`llmfit recommend` is how someone picks a model AgentMemory's four
    LLM-only features can actually run on, so it has to be installable rather
    than merely documented.

    It is NOT in the `ai` group, and that is load-bearing rather than tidiness:
    `ts_app_is_ai` reads that group as the install ROUTE, so a packaged binary
    put there is handed to ts_install_ai_cli, which has no branch for it and
    prints "no agent-CLI installer defined" instead of installing anything.
    """
    all_ids = _sh_eval('echo "$TS_APPS_ALL"').split()
    assert "llmfit" in all_ids
    assert _sh_eval("ts_app_group_of llmfit") == "models"
    assert _sh_eval("ts_app_is_ai llmfit && echo yes || echo no") == "no"
    assert _sh_eval("ts_app_desc llmfit"), "an id with no description is blank in the picker"
    # Optional, not recommended: it is a one-off sizing tool, not daily kit.
    assert "llmfit" not in _sh_eval('echo "$TS_APPS_RECOMMENDED"').split()
    # macOS installs the brew formula; Debian/WSL has no apt package at all, so
    # the release tarball is the only path there.
    cfg = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    assert 'llmfit)     formulae="$formulae llmfit"' in cfg
    deb = (ROOT / "bootstrap/_common-debian.sh").read_text(encoding="utf-8")
    assert 'common_install_github_binary "AlexsJones/llmfit"' in deb


def test_the_windows_catalog_does_not_claim_a_winget_package_that_does_not_exist():
    """The rule is "can this platform install it", never "is it in winget" -- and
    the answer for llmfit is no: it has a windows-msvc release but no manifest.
    Listed in the group so the two catalogs describe the same world, absent from
    $TsAppsAll so the picker skips it, exactly as tmux and ncdu are handled.
    """
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "models  = @{ Desc = 'local model sizing'; Members = @('llmfit') }" in ps
    body = ps[ps.index("$script:TsAppsOptional") :].splitlines()[0]
    assert "llmfit" not in body, "no verified winget id, so it must not be offered on Windows"
    assert (
        "'llmfit'"
        not in ps[ps.index("$script:TsWingetIds") : ps.index("$script:TsAppsRecommended")]
    )


def test_a_running_local_runtime_is_offered_with_the_container_side_url(
    tmp_path, monkeypatch, capsys
):
    """ "What do I even put there" is the question that stops people, and the
    answer is usually a runtime already running on their machine.

    The URL offered is the CONTAINER's, not the host's. Inside a container
    `localhost` is the container, so copying `http://localhost:11434/v1` out of a
    browser produces the silent dead-letter state -- which is precisely the shape
    this whole command exists to keep people out of.
    """
    from tstack.commands import agents

    _llm_env(tmp_path, monkeypatch, "")
    monkeypatch.setattr(
        agents, "local_llm_models", lambda port, **k: ["llama3.1:8b"] if port == 11434 else None
    )
    agents.Llm(ROOT, agents.Out()).run("status")
    text = capsys.readouterr().out

    assert "OPENAI_BASE_URL=http://host.docker.internal:11434/v1" in text
    assert "OPENAI_MODEL=llama3.1:8b" in text
    assert "localhost:11434" not in text, "the host URL must never be the one offered"


def test_a_runtime_that_is_up_with_no_model_is_not_silently_treated_as_absent(
    tmp_path, monkeypatch, capsys
):
    """An empty model list is a THIRD state. The endpoint would be right and the
    configuration would still do nothing, so `None` and `[]` must not collapse."""
    from tstack.commands import agents

    _llm_env(tmp_path, monkeypatch, "")
    monkeypatch.setattr(agents, "local_llm_models", lambda port, **k: [] if port == 1234 else None)
    agents.Llm(ROOT, agents.Out()).run("status")
    text = capsys.readouterr().out

    assert "none loaded" in text
    assert "<load a model first>" in text


def test_local_runtime_detection_survives_whatever_is_actually_on_that_port(monkeypatch):
    """The port is a hint; anything can listen there. HTML, a 500, a socket that
    accepts and says nothing -- none of them may raise out of a status report.
    """
    import urllib.error

    from tstack.commands import agents

    class Fake:
        def __init__(self, body: bytes) -> None:
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self.body

    for body, want in (
        (b"<html>not an api</html>", None),  # invalid JSON
        (b'{"object":"list"}', []),  # valid JSON, no data key
        (b'{"data":"not-a-list"}', []),
        (b'{"data":[{"no":"id"}]}', []),
        (b'{"data":[{"id":"m"}]}', ["m"]),
    ):
        monkeypatch.setattr(agents.urllib.request, "urlopen", lambda *a, _b=body, **k: Fake(_b))
        assert agents.local_llm_models(11434) == want

    def refuse(*a, **k):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(agents.urllib.request, "urlopen", refuse)
    assert agents.local_llm_models(11434) is None


def test_the_container_can_resolve_the_host_on_every_platform():
    """`host.docker.internal` is free on Docker Desktop and does NOT exist on
    native Linux unless it is mapped -- so the same OPENAI_BASE_URL that worked
    on a Mac resolved to nothing on a server, and agentmemory dead-lettered
    silently. Mapping it makes the one URL this command prints correct on all
    three platforms; `host-gateway` is accepted (and redundant) on Desktop.
    """
    body = (ROOT / "services/stacks/agentmemory/docker-compose.yml").read_text(encoding="utf-8")
    assert '"host.docker.internal:host-gateway"' in body
