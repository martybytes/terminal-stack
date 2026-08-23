"""Regression tests for per-machine, user-global coding-agent integrations."""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "bootstrap/agent-tools.json"
PS_ADAPTER = ROOT / "bootstrap/ts-agents.ps1"


def test_manifest_pins_reviewed_versions_and_local_endpoints():
    cfg = json.loads(MANIFEST.read_text(encoding="utf-8"))
    # Repinned 2026-08-23: ghcr.io/chopratejas/headroom no longer resolves at all
    # (manifest 404), while ghcr.io/headroomlabs-ai/headroom:0.36.5 does (200).
    assert cfg["headroom"]["version"] == "0.36.5"
    assert cfg["headroom"]["dockerImage"] == "ghcr.io/headroomlabs-ai/headroom:0.36.5"
    assert cfg["headroom"]["proxyUrl"] == "http://127.0.0.1:8787"
    # 8788/mcp is CORRECT and must not be "fixed". Verified 2026-08-23 against
    # the upstream checkout: headroom/cli/mcp.py sets DEFAULT_HTTP_PORT = 8788
    # and DEFAULT_HTTP_PATH = "/mcp" for `headroom mcp serve --transport http`.
    # It looks dead because nothing STARTS that server — docker-local's compose
    # runs only the proxy on 8787, and `mcp serve` defaults to stdio transport.
    # That is an operational gap in docker-local, not a wrong URL here. (8788
    # also appears in headroom's RUST_DEV.md as an unrelated internal port for a
    # Rust-proxy dev setup, which is what makes this look like a typo.)
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
    # dot_zshrc is deliberately NOT in this list: it is a zsh file and uses zsh-only
    # syntax (glob patterns in [[ ]], ${(P)var}, typeset -g "$var=..."), so `bash -n`
    # rejects it. It gets its own zsh gate below.
    files = [
        "bootstrap/_config.sh", "bootstrap/_wizard.sh", "bootstrap/ts-config.sh",
        "bootstrap/ts-agents.sh", "bootstrap/wsl-bootstrap.sh",
        "bootstrap/linux-bootstrap.sh", "bootstrap/mac-bootstrap.sh",
        "run_after_90-sync-windows.sh",
        # These were never covered by the gate; a syntax error in any of them
        # only showed up when someone ran the command.
        "bootstrap/ts-mux.sh", "bootstrap/ts-wezterm.sh", "bootstrap/ts-doctor.sh",
        "bootstrap/wso.sh", "bootstrap/_workspace.sh", "bootstrap/_doctor.sh",
        "bootstrap/_common-debian.sh",
        "bootstrap/ts-smb.sh", "bootstrap/_smb.sh",
    ]
    result = subprocess.run([shutil.which("bash"), "-n", *files], cwd=ROOT,
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh is unavailable")
def test_zshrc_parses_under_zsh():
    result = subprocess.run([shutil.which("zsh"), "-n", "dot_zshrc"], cwd=ROOT,
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr


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
    resolver = zsh[zsh.index("_ts_agent_bin() {"):]
    resolver = resolver[:resolver.index("\n}\n") + 2]
    assert "rehash" in resolver
    assert '"$HOME/.local/bin/$name"' in resolver
    # Callers must not capture it in $( ) — that subshell would discard the cache.
    assert '$(_ts_claude_bin)' not in zsh
    assert '$(_ts_codex_bin)' not in zsh
    for fn in ("claude-stock()", "codex-stock()"):
        assert fn in zsh
    assert "was not found on PATH when this shell loaded" not in zsh

    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(encoding="utf-8")
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
    resolver = zsh_src[zsh_src.index("_ts_agent_bin() {"):]
    resolver = resolver[:resolver.index("\n}\n") + 2]
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
    result = subprocess.run([shutil.which("zsh"), "-c", script],
                            env={"HOME": str(home), "PATH": "/usr/bin:/bin", "TERM": "dumb"},
                            text=True, capture_output=True, check=False)
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

    live = json.dumps({
        "model": "claude-opus-5",
        "enabledPlugins": {"agentmemory@local": True},
        "permissions": {"defaultMode": "ask"},
        "agentPushNotifEnabled": True,
        "theme": "light",
    })
    result = subprocess.run([sys.executable, str(script)], input=live,
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    for key in ("model", "enabledPlugins", "permissions", "agentPushNotifEnabled"):
        assert key in out, f"{key} was destroyed by the splice"
    assert "statusLine" in out and "hooks" in out

    # A live file we cannot parse is echoed back untouched rather than replaced.
    broken = "{ not json"
    result = subprocess.run([sys.executable, str(script)], input=broken,
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0
    assert result.stdout == broken


def test_repo_infrastructure_is_not_deployed_to_home():
    """tests/** used to be missing here, so chezmoi wrote the suite into ~/tests/."""
    ignore = (ROOT / ".chezmoiignore").read_text(encoding="utf-8")
    for path in ("tests/**", "bootstrap/**", "docs/**", "scripts/**"):
        assert path in ignore, f"{path} would be deployed into $HOME"


def test_dropbox_jump_exists_in_both_shells():
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(encoding="utf-8")
    # Must be shell functions: a child process cannot cd its parent.
    assert "_ts_dropbox() {" in zsh and "\ndb() {" in zsh and "dbx() { db" in zsh
    assert "function Get-TsDropbox" in ps and "function db {" in ps and "function dbx" in ps
    # $DROPBOX_DIR wins, and resolution is at call time (no load-time snapshot).
    assert '[[ -n "${DROPBOX_DIR:-}" ]]' in zsh
    assert 'if ($env:DROPBOX_DIR) { return $env:DROPBOX_DIR }' in ps
    # macOS moved Dropbox under CloudStorage; that candidate must be probed first.
    dropbox = zsh[zsh.index("_ts_dropbox() {"):]
    assert dropbox.index("Library/CloudStorage/Dropbox") < dropbox.index('"$HOME/Dropbox"')


# --- terminal emulators: channel choice, Ghostty, and the opt-out --------------

def test_terminal_emulator_stays_optional_on_every_platform():
    """Nothing may force-install an emulator: the opt-out is the point."""
    win = (ROOT / "bootstrap/windows-bootstrap.ps1").read_text(encoding="utf-8")
    required = win[win.index("$requiredPackages = @("):]
    required = required[:required.index(")")]
    assert "wezterm" not in required.lower(), "WezTerm must not be a required package"
    assert "Terminal emulator: none selected" in (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
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
    for line in ("Toggle a number, [a]ll, [n]one, Enter to continue, [s]kip",
                 "(non-interactive — keeping the defaults)",
                 "(several are fine), a, n, s, or Enter"):
        assert line in sh, line
        assert line in ps, line
    # The whitespace-stripping trap: "1 2" must stay two tokens.
    multi = sh[sh.index("ts_prompt_multi() {"):]
    assert "tr -d '[:space:]'" not in multi[:multi.index("\n}\n")]
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


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
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
            [shutil.which("bash"), "-c",
             '. bootstrap/_config.sh >/dev/null 2>&1; . bootstrap/_wizard.sh; '
             'sel="$(ts_prompt_terminals)"; printf "%s|%s" "$sel" "$(ts_terminals_channel "$sel")"'],
            cwd=ROOT, env={**os.environ, k: v}, text=True, capture_output=True, check=False)
        assert r.returncode == 0, r.stderr
        sel, chan = r.stdout.split("|")
        assert sel.strip() == want_sel, f"{env}: got selection {sel!r}"
        assert chan.strip() == want_chan, f"{env}: got channel {chan!r}"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_wezterm_version_string_parses_to_a_date():
    """The build date is IN the release name, so it needs no network call."""
    r = subprocess.run(
        [shutil.which("bash"), "-c",
         '. bootstrap/_wezterm.sh; ts_wez_version_parse "wezterm 20240203-110809-5046fc22"; '
         'ts_wez_version_parse "20260331-040028-577474d8"; ts_wez_version_parse "not a version"'],
        cwd=ROOT, text=True, capture_output=True, check=False)
    assert r.returncode == 0, r.stderr
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    assert lines[0] == "20240203-110809-5046fc22|20240203|5046fc22"
    assert lines[1] == "20260331-040028-577474d8|20260331|577474d8"
    assert len(lines) == 2, "unparseable input must produce nothing, not a bad guess"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_changelog_slicer_counts_against_a_fixture():
    """Pinned to a saved copy of upstream's changelog, so the assertion does not
    drift as upstream adds bullets."""
    fixture = ROOT / "tests/fixtures/wezterm-changelog.md"
    assert fixture.exists()
    r = subprocess.run(
        [shutil.which("bash"), "-c",
         f'. bootstrap/_wezterm.sh; ts_wez_changelog_fetch() {{ printf "%s\n" "{fixture}"; }}; '
         'ts_wez_changes_tally 20240203-110809-5046fc22'],
        cwd=ROOT, text=True, capture_output=True, check=False)
    assert r.returncode == 0, r.stderr
    tally = r.stdout.strip()
    # Hand-counted from the fixture: the Continuous/Nightly section only, since
    # 20240203 is where the slice stops.
    counts = dict(zip(tally.split()[::2], (int(n) for n in tally.split()[1::2])))
    assert counts == {"Changed": 20, "New": 32, "Fixed": 74, "Updated": 9}, tally
    assert sum(counts.values()) == 135

    # A version that is not in the changelog slices nothing away — everything is
    # newer than it — so the count must be strictly larger.
    r2 = subprocess.run(
        [shutil.which("bash"), "-c",
         f'. bootstrap/_wezterm.sh; ts_wez_changelog_fetch() {{ printf "%s\n" "{fixture}"; }}; '
         'ts_wez_changes_tally 19700101-000000-00000000'],
        cwd=ROOT, text=True, capture_output=True, check=False)
    older = dict(zip(r2.stdout.split()[::2], (int(n) for n in r2.stdout.split()[1::2])))
    assert sum(older.values()) > sum(counts.values())


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_wezterm_queries_fail_open_when_offline():
    """No network must degrade to version-and-date, never block or error."""
    r = subprocess.run(
        [shutil.which("bash"), "-c",
         '. bootstrap/_wezterm.sh; gh() { return 1; }; curl() { return 1; }; '
         'ts_wezterm_status; echo "RC=$?"'],
        cwd=ROOT, text=True, capture_output=True, check=False)
    assert r.returncode == 0, r.stderr
    assert "RC=0" in r.stdout
    assert "offline" in r.stdout
    # Every network call is bounded.
    body = (ROOT / "bootstrap/_wezterm.sh").read_text(encoding="utf-8")
    for line in body.splitlines():
        if "curl " in line and "--max-time" not in line and not line.strip().startswith("#"):
            assert "gpg.key" in line, f"unbounded curl: {line.strip()}"


def test_wezterm_channel_switch_removes_the_other_one_both_ways():
    """The two packages install to the same place, so a switch must uninstall
    first — and that must work in BOTH directions, not just nightly->stable."""
    sh = (ROOT / "bootstrap/_wezterm.sh").read_text(encoding="utf-8")
    assert "_ts_wez_brew_install wezterm@nightly wezterm" in sh
    assert "_ts_wez_brew_install wezterm         wezterm@nightly" in sh
    assert "_ts_wez_apt_install wezterm-nightly wezterm" in sh
    assert "_ts_wez_apt_install wezterm         wezterm-nightly" in sh
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "$other = if ($Channel -eq 'nightly') { 'wez.wezterm' } else { 'wez.wezterm.nightly' }" in ps
    # The removal must be conditional on switching, never unconditional: a machine
    # that declines WezTerm entirely must keep whatever it already had.
    assert "stable-only policy" not in sh and "stable-only policy" not in ps


def test_nothing_installs_or_upgrades_wezterm_automatically():
    """The whole point: every path asks first."""
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    upd = zsh[zsh.index("ts-update() {"):]
    upd = upd[:upd.index("\n}\n")]
    assert "ts_wezterm_update_available" in upd
    assert "Upgrade WezTerm now? [y/N]" in upd
    assert 'ts-wezterm.sh" upgrade' in upd
    # Non-interactive must print the command, never run it.
    assert "Upgrade it with: ts-config wezterm upgrade" in upd
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(encoding="utf-8")
    assert "Get-TsWezUpdateAvailable" in ps
    assert "Upgrade WezTerm now? [y/N]" in ps
    assert "Upgrade it with: ts-config wezterm upgrade" in ps


def test_ts_config_exposes_wezterm():
    sh = (ROOT / "bootstrap/ts-config.sh").read_text(encoding="utf-8")
    assert "run_wezterm()" in sh
    assert "wezterm)\n        shift\n        run_wezterm" in sh
    assert "wezterm, wizard)" in sh, "the unknown-command hint must list it"
    # -h is generated from the header comment: the sed range must still cover it.
    rng = sh[sh.index("sed -n '2,"):]
    end = int(rng[len("sed -n '2,"):].split("p")[0])
    header = sh.splitlines()[1:end]
    assert any("ts-config wezterm" in line for line in header), \
        "the wezterm line is outside the range -h prints"
    # run_wizard installs the emulator it just asked about (it used not to).
    wiz = sh[sh.index("run_wizard() {"):]
    wiz = wiz[:wiz.index("\n}\n")]
    assert "install_terminals" in wiz



# --- app catalog: groups, new tools, the ai group ------------------------------

def _sh_eval(snippet):
    """Run a snippet with bootstrap/_config.sh sourced, return stdout."""
    r = subprocess.run([shutil.which("bash"), "-c",
                        f'. bootstrap/_config.sh >/dev/null 2>&1; {snippet}'],
                       cwd=ROOT, text=True, capture_output=True, check=False)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_every_catalog_id_belongs_to_exactly_one_group():
    """An id in no group is unreachable from the group picker; one in two is ambiguous."""
    all_ids = _sh_eval('echo "$TS_APPS_ALL"').split()
    groups = _sh_eval('echo "$TS_APP_GROUPS"').split()
    seen = {}
    for g in groups:
        for member in _sh_eval(f'ts_app_group_members {g}').split():
            assert member not in seen, f"{member} is in both {seen[member]} and {g}"
            seen[member] = g
    assert set(all_ids) == set(seen), (
        f"ungrouped: {sorted(set(all_ids) - set(seen))}; "
        f"grouped but not in catalog: {sorted(set(seen) - set(all_ids))}"
    )


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_new_tools_are_in_the_catalog_with_descriptions():
    all_ids = _sh_eval('echo "$TS_APPS_ALL"').split()
    for tool in ("duf", "ncdu", "dust", "gdu", "btop", "bottom", "glances",
                 "bandwhich", "gping", "bat", "eza", "fd", "ripgrep", "fzf", "tree",
                 "atuin", "yazi", "pi"):
        assert tool in all_ids, f"{tool} missing from the catalog"
        assert _sh_eval(f'ts_app_desc {tool}'), f"{tool} has no description"
    # bottom's binary is btm, not bottom.
    assert _sh_eval('ts_app_bin bottom') == "btm"
    # gdu collides with GNU coreutils' g-prefixed du; brew renames the TUI to
    # gdu-go when coreutils is present, so the mapping must follow reality.
    assert _sh_eval('ts_app_bin gdu') in ("gdu", "gdu-go")
    assert _sh_eval('gdu-go() { :; }; command -v gdu-go >/dev/null && ts_app_bin gdu') in ("gdu", "gdu-go")
    # fd closes the documented sessionizer gap (README says it is needed).
    assert "needs `fd`" in (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_agent_clis_are_asked_about_and_default_to_all():
    """Default-to-all, but still a question: every group starts ticked and every
    tool inside stays individually untickable."""
    ai = _sh_eval('ts_app_group_members ai').split()
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


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_python_and_runtimes_are_in_the_questionnaire():
    groups = _sh_eval('echo "$TS_APP_GROUPS"').split()
    assert "python" in groups and "runtimes" in groups
    py = _sh_eval('ts_app_group_members python').split()
    for tool in ("python", "uv", "pipx", "ruff", "ipython", "httpie", "poetry", "pre-commit"):
        assert tool in py, f"{tool} missing from the python group"
    assert set(_sh_eval('ts_app_group_members runtimes').split()) == {"fnm", "node"}
    # python's binary is python3, not python.
    assert _sh_eval('ts_app_bin python') == "python3"
    for tool in py + ["fnm"]:
        assert _sh_eval(f'ts_app_desc {tool}'), f"{tool} has no description"


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


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_node_managed_binaries_are_visible_to_the_update_check():
    """Global npm binaries live under fnm's per-shell PATH entry; without loading
    fnm's env first, ts-update would nag about codex/gemini forever."""
    sh = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    assert "ts_load_node_env" in sh
    pending = sh[sh.index("ts_apps_pending() {"):]
    assert "ts_load_node_env" in pending[:pending.index("\n}\n")]
    report = sh[sh.index("ts_report_installed_apps() {"):]
    assert "ts_load_node_env" in report[:report.index("\n}\n")]


def test_fnm_is_wired_into_both_shells():
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(encoding="utf-8")
    assert "fnm env --use-on-cd --shell zsh" in zsh
    assert "fnm env --use-on-cd --shell powershell" in ps
    # Guarded, so a machine without fnm is unaffected.
    assert 'command -v fnm    >/dev/null && eval "$(fnm env' in zsh
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
    assert 'want=16' in sh and 'want=20' in sh
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
    wiz = sh[sh.index("run_wizard() {"):]
    wiz = wiz[:wiz.index("\n}\n")]
    for call in ("ts_wizard_collect", "ts_save_config", "ts_agents_save_config",
                 "ts_wez_mux_set", "ts_wez_restore_set", "ts_cc_tts_apply_wizard_choice"):
        assert call in wiz, f"run_wizard does not persist {call}"
    # -h is generated from the header comment: the sed range must still cover it.
    rng = sh[sh.index("sed -n '2,"):]
    end = int(rng[len("sed -n '2,"):].split("p")[0])
    header = sh.splitlines()[1:end]
    assert any("ts-config wizard" in line for line in header), \
        "the wizard line is outside the range -h prints"
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(encoding="utf-8")
    assert "$runWizard = {" in ps and "'wizard'" in ps


def test_shared_pwsh_prompts_live_where_both_callers_can_reach_them():
    """$PROFILE dot-sources _config.ps1 only; a prompt in windows-bootstrap.ps1
    is invisible to `ts-config wizard`."""
    cfg = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    boot = (ROOT / "bootstrap/windows-bootstrap.ps1").read_text(encoding="utf-8")
    for fn in ("function Read-TsWizard", "function Install-TsTerminals"):
        assert fn in cfg, f"{fn} must live in _config.ps1"
        assert fn not in boot, f"{fn} is duplicated in windows-bootstrap.ps1"


# ── ts-smb ──────────────────────────────────────────────────────────────────────

def _smb_eval(tmp_path, local_conf, snippet, tracked="set default_user guest\n"):
    """Run a snippet with bootstrap/_smb.sh sourced against a sandboxed store."""
    lib = tmp_path / "lib"; lib.mkdir(exist_ok=True)
    (lib / "shares.conf").write_text(tracked, encoding="utf-8")
    cfg = tmp_path / "cfg" / "terminal-stack"; cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "shares.local.conf").write_text(local_conf, encoding="utf-8")
    env = dict(os.environ, XDG_CONFIG_HOME=str(tmp_path / "cfg"),
               TS_SMB_LIB_DIR=str(lib))
    r = subprocess.run([shutil.which("bash"), "-c",
                        f'. bootstrap/_smb.sh >/dev/null 2>&1; {snippet}'],
                       cwd=ROOT, text=True, capture_output=True, check=False, env=env)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_smb_store_parses_stanzas(tmp_path):
    conf = "share media\n  host nas.lan\n  path Media\n  user marty\n"
    assert _smb_eval(tmp_path, conf, 'ts_smb_get media host ""') == "nas.lan"
    assert _smb_eval(tmp_path, conf, 'ts_smb_get media path ""') == "Media"
    assert _smb_eval(tmp_path, conf, 'ts_smb_names') == "media"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_smb_store_last_match_wins(tmp_path):
    """The local file must be able to override ONE field without restating a stanza."""
    conf = ("share media\n  host nas.lan\n  path Media\n  vfs off\n"
            "share media\n  vfs writes\n")
    assert _smb_eval(tmp_path, conf, 'ts_smb_get media vfs ""') == "writes"
    assert _smb_eval(tmp_path, conf, 'ts_smb_get media host ""') == "nas.lan"
    # ...and the name is not duplicated by the second stanza.
    assert _smb_eval(tmp_path, conf, 'ts_smb_names') == "media"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_smb_store_falls_back_to_set_defaults(tmp_path):
    conf = "share media\n  host nas.lan\n  path Media\n"
    assert _smb_eval(tmp_path, conf, 'ts_smb_get media user ""',
                     tracked="set default_user guest\n") == "guest"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_smb_flags_tail_keeps_its_spaces(tmp_path):
    """`flags` is the one free-form tail; the space-delimited store cannot hold it,
    so it lives in its own accumulator. An inline comment is stripped, and so is
    the whitespace the strip leaves behind."""
    conf = ("share media\n  host nas.lan\n  path Media\n"
            "  flags --transfers 8 --smb-idle-timeout 5m   # tuned\n")
    assert _smb_eval(tmp_path, conf, 'ts_smb_flags media') == \
        "--transfers 8 --smb-idle-timeout 5m"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_smb_validate_catches_the_share_vs_path_trap(tmp_path):
    """`share` opens a stanza, so writing `share Media` for the SMB share name
    silently opens a second one. That mistake must be reported, not absorbed."""
    conf = "share media\n  host nas.lan\n  share Media\n"
    out = _smb_eval(tmp_path, conf, 'ts_smb_validate || true')
    # Stanza names are folded to lower case, so `share Media` merges back into the
    # `media` stanza rather than creating a spurious one — the mistake therefore
    # shows up as a missing `path`, and the message has to say why.
    assert "has no path" in out
    assert "'share' opens a stanza" in out
    assert _smb_eval(tmp_path, conf, 'ts_smb_names') == "media"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_smb_help_works_without_a_clone():
    """`ts-smb -h` must work on a box where the clone or chezmoi is the broken thing."""
    env = {k: v for k, v in os.environ.items() if k != "TERMINAL_STACK_DIR"}
    env.update({"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"})
    r = subprocess.run([shutil.which("bash"), "bootstrap/ts-smb.sh", "-h"],
                       cwd=ROOT, text=True, capture_output=True, check=False, env=env)
    assert r.returncode == 0, r.stderr
    assert r.stdout.startswith("ts-smb —")
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
    conn = lib[lib.index("ts_smb_conn() {"):]
    conn = conn[:conn.index("\n}\n")]
    assert "pass" not in conn


def test_smb_never_stats_a_mountpoint_to_test_liveness():
    """On a dead FUSE mount, stat/ls/test -d block forever and take the shell with
    them. Liveness must come from the kernel mount table only."""
    lib = (ROOT / "bootstrap/_smb.sh").read_text(encoding="utf-8")
    fn = lib[lib.index("ts_smb_is_mounted() {"):]
    fn = fn[:fn.index("\n}\n")]
    for forbidden in ("test -d", "[ -d ", "stat ", "ls "):
        assert forbidden not in fn, f"ts_smb_is_mounted touches the path: {forbidden}"
    assert "/proc/self/mounts" in fn or "mount " in fn


def test_smb_does_not_auto_enable_fskit():
    """fuse-t's FSKit backend fails outright on macOS 26.6 with fuse-t 1.2.6
    ("fuse: mount failed with error: -1") while the default nfs backend does not."""
    src = (ROOT / "bootstrap/ts-smb.sh").read_text(encoding="utf-8")
    mount_fn = src[src.index("cmd_mount() {"):]
    mount_fn = mount_fn[:mount_fn.index("\n}\n")]
    code = "\n".join(l for l in mount_fn.splitlines() if not l.strip().startswith("#"))
    assert "backend=fskit" not in code


def test_smb_exists_in_zshrc_and_is_not_claimed_for_pwsh():
    """Bash-only by decision, not by drift: the zsh wrapper exists, and the help
    says Windows is unsupported so nobody 'fixes' the missing twin silently."""
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    assert "\nts-smb() {" in zsh
    assert "bootstrap/ts-smb.sh" in zsh
    src = (ROOT / "bootstrap/ts-smb.sh").read_text(encoding="utf-8")
    assert "THERE IS NO pwsh TWIN YET" in src


def test_rclone_is_in_the_catalog_with_a_description():
    cfg = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    assert "rclone" in cfg
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "rclone     = 'Rclone.Rclone'" in ps
    assert "'rclone'" in ps


# ── atuin / arch-tag regressions ────────────────────────────────────────────────

@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_common_arch_tag_rust_uses_aarch64_not_arm64():
    """cargo-dist projects (atuin, yazi) name their ARM asset `aarch64`, while
    `gnu` yields `arm64`. Getting this wrong fails *silently on ARM only*: the
    asset regex matches nothing, x86_64 boxes keep working, and the tool is
    quietly missing on every Pi/ARM server."""
    lib = ROOT / "bootstrap/_common-debian.sh"
    fn = re.search(r"^common_arch_tag\(\) \{.*?^\}", lib.read_text(encoding="utf-8"),
                   re.S | re.M)
    assert fn, "common_arch_tag not found"
    def tag(machine, style):
        script = (f'{fn.group(0)}\nuname() {{ echo "{machine}"; }}\n'
                  f'common_arch_tag {style}\n')
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True).stdout.strip()
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
    assert not any("command -v atuin" in l for l in code), \
        "dot_zshrc must NOT gate atuin on a presence check"
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
    for pat in ("ANTHROPIC_API_KEY=", "OPENAI_API_KEY=", "GITHUB_TOKEN=",
                "GH_TOKEN=", "NPM_TOKEN=", "_KEY=", "_SECRET=", "_PASSWORD=",
                "_TOKEN=", "sk-[A-Za-z0-9_-]{20,}"):
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
    assert not any(l.strip().startswith("atuin") for l in assigns), \
        "atuin must not have a winget id"
    assert "yazi       = 'sxyazi.yazi'" in ids, "yazi's winget id is real and verified"


# ── Ghostty ─────────────────────────────────────────────────────────────────────

def _wez_light_scheme():
    """PALETTES.light.scheme_def out of dot_wezterm.lua.tmpl."""
    lua = (ROOT / "dot_wezterm.lua.tmpl").read_text(encoding="utf-8")
    sd = lua[lua.index("scheme_def = {"):]
    sd = sd[:sd.index("\n    },")]
    def one(key):
        return re.search(r"%s = '(#[0-9A-Fa-f]{6})'" % key, sd).group(1).lower()
    def arr(key):
        block = re.search(r"%s = \{(.*?)\}" % key, sd, re.S).group(1)
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
    assert len(pal) == 16, "expected 16 palette entries, got %d" % len(pal)
    for i, c in enumerate(ansi):
        assert pal[str(i)] == c, "palette %d drifted from the Lua ansi table" % i
    for i, c in enumerate(brights):
        assert pal[str(i + 8)] == c, "palette %d drifted from the Lua brights" % (i + 8)
    for key, lua_key in (("background", "background"), ("foreground", "foreground"),
                         ("cursor-color", "cursor_bg"), ("cursor-text", "cursor_fg"),
                         ("selection-background", "selection_bg"),
                         ("selection-foreground", "selection_fg")):
        got = re.search(r"^%s = (#[0-9a-f]{6})$" % key, theme, re.M).group(1)
        assert got == one(lua_key), "%s drifted from the Lua scheme_def" % key


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
        assert "#" not in st.split("=", 1)[1] or "color" in st or "palette" in st, \
            "inline comment would be parsed as part of the value: %r" % ln


def test_ghostty_is_gated_and_never_removed_by_chezmoi():
    """.chezmoiignore is evaluated on every machine, so a removal rule there
    would wipe a hand-written Ghostty config on a box that never opted in.
    Removal is ts-config ghostty off's job, for the machine you run it on."""
    ign = (ROOT / ".chezmoiignore").read_text(encoding="utf-8")
    assert ign.count(".config/ghostty/**") == 2, "expected a darwin gate and an off gate"
    rm = (ROOT / ".chezmoiremove").read_text(encoding="utf-8")
    assert "ghostty" not in rm, ".chezmoiremove must never target ghostty"
    hook = ROOT / "run_before_20-backup-ghostty.sh"
    assert hook.exists() and os.access(hook, os.X_OK), "backup hook must exist and be executable"
    body = hook.read_text(encoding="utf-8")
    assert "managed by terminal-stack" in body, "must skip a config that is already ours"
    assert "Darwin" in body, "must no-op off macOS"


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


def test_agentmemory_secret_recovery_uses_the_unix_cache_not_the_registry():
    """`reg query HKCU\\Environment` throws on Unix, is caught, and leaves the
    401 recovery a permanent no-op."""
    sh = AM_SH.read_text(encoding="utf-8")
    sh_code = _uncommented(sh)
    assert "reg query" not in sh_code, "the Windows registry read must not survive the port"
    assert "XDG_CONFIG_HOME" in sh
    assert 'docker-local", "agentmemory.secret"' in sh
    # The .ps1 keeps its registry form; this is a deliberate divergence, not drift.
    assert "reg query" in AM_PS.read_text(encoding="utf-8")


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
    assert sh.index("pre-tool-use gains the project helpers") < \
        sh.index("duplicate-invocation guard helper")


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
    """The [ -d /mnt/c/Users ] gate meant macOS and Linux never checked — and
    never wired — anything at all."""
    body = (ROOT / "bootstrap/_doctor.sh").read_text(encoding="utf-8")
    assert "ts-agentmemory.sh" in body, "doctor must know about the bash twin"
    seg = body[body.index("agentmemory hook wiring"):]
    assert "--check" in seg


def test_ts_agents_invokes_the_hook_wiring():
    """Installing the plugin is only half the job: without the deployment edits
    the hooks POST nothing and nothing logs it."""
    body = (ROOT / "bootstrap/ts-agents.sh").read_text(encoding="utf-8")
    assert "ts-agentmemory.sh" in body
    assert "--apply" in body and "--undo --apply" in body


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
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(encoding="utf-8")
    for name in ("cc()", "ccc()", "ccd()", "ccdc()", "ccr()", "ccdr()", "cca()"):
        line = next(l for l in rc.splitlines() if l.startswith(name))
        assert "CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1" in line, \
            f"{name} would have its tab title overwritten by Claude"
        assert "_ts_tab_title" in line
    for name in ("function cc ", "function ccc ", "function ccd ", "function ccdc",
                 "function ccr ", "function ccdr", "function cca "):
        line = next(l for l in ps.splitlines() if l.startswith(name))
        assert "CLAUDE_CODE_DISABLE_TERMINAL_TITLE" in line, \
            f"{name.strip()} (pwsh) would have its tab title overwritten"
        assert "Set-TsTabTitle" in line
    # The old WezTerm-only names must be fully retired on both sides.
    assert "_wez_tab_title" not in rc
    assert "Set-WezTabTitle" not in ps


def test_tab_title_helper_skips_tmux_and_falls_back_to_osc2():
    """tmux owns the outer title while attached and substitutes its own string,
    so emitting OSC 2 there would be swallowed. WezTerm gets its sticky
    override; everything else (Ghostty, Terminal.app) gets OSC 2."""
    rc = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    body = rc[rc.index("_ts_tab_title() {"):]
    body = body[:body.index("\n}\n") + 3]
    assert "WEZTERM_PANE" in body and "set-tab-title" in body
    assert '-z "$TMUX"' in body, "must not emit OSC 2 inside tmux"
    assert "\\033]2;%s\\007" in body or "033]2;" in body


# ── installer robustness ────────────────────────────────────────────────────────

BOOTSTRAP_SH = sorted((ROOT / "bootstrap").glob("*.sh"))


def test_no_bare_variable_followed_by_non_ascii():
    """macOS ships bash 3.2, whose legal_variable_char() is not multibyte-aware:
    under en_US.UTF-8 the lead byte of a UTF-8 char passes isalnum(), so
    `"$desired…"` parses the NAME as `desired\\xE2` — never set — and `set -u`
    aborts. It crashed `ts-doctor --repair` mid-run, after repointing sourceDir
    and before `chezmoi apply`. `bash -n` cannot catch it; brace the variable."""
    bad = []
    pat = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*[^\x00-\x7F\s]")
    for f in BOOTSTRAP_SH:
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue          # prose explaining the trap is not the trap
            if pat.search(line):
                bad.append(f"{f.name}:{i}: {line.strip()}")
    assert not bad, "brace these: " + "; ".join(bad)


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
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
            assert st.endswith("\\") or "||" in st, \
                f"{f.name}:{i} unguarded install: {st}"
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
    assert mac.index("ts_save_config") < mac.index("ts_brew_install_apps"), \
        "mac-bootstrap installs apps before saving the wizard answers"
    # The agent WIRING needs the CLIs installed, so it alone stays late.
    assert mac.index("ts_agents_apply_wizard") > mac.index("ts_save_config")

    deb = (ROOT / "bootstrap/_common-debian.sh").read_text(encoding="utf-8")
    body = deb[deb.index("common_install_all() {"):]
    body = body[:body.index("\n}\n")]
    body = _uncommented(body)   # index the calls, not the prose about them
    hook = body.index("TS_PERSIST_HOOK")
    for installer in ("common_install_selected_apps", "common_install_terminals"):
        assert hook < body.index(installer), \
            f"_common-debian.sh: {installer} runs before the persistence hook"
    # chezmoi must precede the hook: ts_save_config runs `chezmoi init`.
    assert body.index("common_chezmoi") < hook

    for name in ("linux-bootstrap.sh", "wsl-bootstrap.sh"):
        w = (ROOT / "bootstrap" / name).read_text(encoding="utf-8")
        assert "TS_PERSIST_HOOK=_ts_persist_wizard" in w, f"{name} sets no hook"
        assert "ts_save_config" in w[w.index("_ts_persist_wizard() {"):], \
            f"{name}: the hook does not actually save"


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
    assert wiz.count("ts_terminals_one_channel") >= 3   # def + env path + picker


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_installed_apps_report_survives_a_tool_that_rejects_version():
    """The report assigned a four-stage pipeline directly, so under
    `set -euo pipefail` any tool whose --version exits non-zero killed the
    function — and with it `finish`, so `chezmoi apply` silently never ran.
    tmux is exactly that tool (it wants -V) and is FIRST in the recommended
    list, so this fired on every single run."""
    script = (
        'set -euo pipefail\n'
        '. bootstrap/_config.sh >/dev/null 2>&1\n'
        # A binary that exits non-zero for BOTH --version and -V is the worst case.
        'mkdir -p /tmp/_tsbin\n'
        'printf "#!/bin/sh\\nexit 3\\n" > /tmp/_tsbin/tmux; chmod +x /tmp/_tsbin/tmux\n'
        'PATH=/tmp/_tsbin:$PATH ts_report_installed_apps "tmux" >/dev/null\n'
        'echo SURVIVED\n')
    r = subprocess.run(["bash", "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert "SURVIVED" in r.stdout, f"report aborted: {r.stderr.strip()[:200]}"
    # And the guard must be in the source, not incidental.
    cfg = _uncommented((ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8"))
    body = cfg[cfg.index("ts_report_installed_apps()"):]
    body = body[:body.index("\n}\n")]
    assert '--version 2>/dev/null || true' in body, "version probe must not be fatal"
    assert '-V 2>/dev/null' in body, "tmux-style tools need the -V fallback"


def test_ts_config_wizard_asks_about_terminals_and_saves_first():
    """`ts-config wizard` never set TS_WIZ_ASK_TERMINALS, so it skipped the
    question and reported 'none selected' — a re-run could not switch WezTerm
    channel, which is a main reason to run it again. And like the bootstraps it
    must save before installing."""
    body = _uncommented((ROOT / "bootstrap/ts-config.sh").read_text(encoding="utf-8"))
    rw = body[body.index("run_wizard()"):]
    rw = rw[:rw.index("\n}\n")]
    assert "TS_WIZ_ASK_TERMINALS=1" in rw, "ts-config wizard must ask about terminals"
    assert rw.index("ts_save_config") < rw.index("install_apps"), \
        "run_wizard installs before saving the answers"
    assert "ts_note_failure" in rw, "installs here must not be fatal either"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
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
        'for f in ts_is_headless ts_is_interactive ts_prompt_multi ts_prompt_choice \\\n'
        '         ts_prompt_terminals ts_terminals_one_channel ts_wizard_collect \\\n'
        '         ts_note_failure ts_report_failures; do\n'
        '  command -v "$f" >/dev/null || echo "UNDEFINED: $f"\n'
        'done\n'
        # and actually drive the picker, which is where the ordering bug lived
        'TS_MULTI_EXCLUSIVE="a b" ts_prompt_multi "a b" "T:" "" "a|A|" "b|B|" "c|C|"\n')
    r = subprocess.run(["bash", "-c", script], cwd=ROOT,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert "UNDEFINED:" not in r.stdout, r.stdout
    # /dev/tty is legitimately absent under pytest; anything else is a real fault.
    noise = [l for l in r.stderr.splitlines()
             if l.strip() and "/dev/tty" not in l]
    assert not noise, "wizard emitted errors: " + "; ".join(noise)
    # The exclusive group must have collapsed a pre-tick of BOTH a and b.
    picked = r.stdout.replace("UNDEFINED:", "").split()
    assert picked == ["a"], f"exclusive group not applied: {picked!r}"


def test_ts_config_sources_what_it_calls():
    """ts-config.sh called ts_is_headless, which lives in _detect.sh and was
    never sourced there."""
    body = (ROOT / "bootstrap/ts-config.sh").read_text(encoding="utf-8")
    # Match the SOURCE STATEMENT, not the shellcheck comment above it.
    src_line = next((l for l in body.splitlines()
                     if l.strip().startswith(". ") and "_detect.sh" in l), None)
    assert src_line, "ts-config.sh must source _detect.sh"
    assert body.index(src_line) < body.index("ts_is_headless ||"), \
        "_detect.sh sourced after first use of ts_is_headless"


# ── wizard recommendations + readiness probing ──────────────────────────────────

@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_service_probes_treat_any_http_response_as_up():
    """AgentMemory answers 404 on / and 401 on /agentmemory/health. `curl -fsS`
    turns either into a failure, which is why `ts-agents agentmemory status`
    reported the service down while it was up and serving. Any response proves
    something is listening; only a refused connection is 'down'."""
    script = (
        '. bootstrap/_config.sh >/dev/null 2>&1\n'
        # port 9 (discard) is reliably not an HTTP server
        'ts_probe_http http://127.0.0.1:9 1 && echo BAD_UP || echo ok_down\n'
        'ts_probe_http_ok http://127.0.0.1:9 1 && echo BAD_OK || echo ok_not_ok\n')
    r = subprocess.run(["bash", "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert "BAD_" not in r.stdout, r.stdout
    assert r.stdout.split() == ["ok_down", "ok_not_ok"], r.stdout
    agents = _uncommented((ROOT / "bootstrap/ts-agents.sh").read_text(encoding="utf-8"))
    assert 'curl -fsS --max-time 1 "$(json_get agentmemory.restUrl)"' not in agents, \
        "-f makes a 404/401 look like the service is down"


def test_wizard_recommends_and_probes_before_offering():
    """Blind on/off questions let a machine be wired to a service that is not
    running — which then fails later and silently, because the agentmemory hooks
    swallow errors and exit 0. Probe first, default from what was found."""
    wiz = (ROOT / "bootstrap/_wizard.sh").read_text(encoding="utf-8")
    for fn in ("ts_prompt_wezterm_mux", "ts_prompt_wezterm_restore", "ts_prompt_atuin"):
        body = wiz[wiz.index(f"{fn}() {{"):]
        body = body[:body.index("\n}\n")]
        assert "RECOMMENDATION:" in body, f"{fn} has no recommendation"
    # atuin now defaults to ON; the other two stay off.
    at = wiz[wiz.index("ts_prompt_atuin() {"):]
    at = at[:at.index("\n}\n")]
    assert "ts_prompt_choice on " in at, "atuin should default to on"
    for fn in ("ts_prompt_wezterm_mux", "ts_prompt_wezterm_restore"):
        b = wiz[wiz.index(f"{fn}() {{"):]
        b = b[:b.index("\n}\n")]
        assert "ts_prompt_choice off " in b, f"{fn} should default to off"
    # The agent toggles must be probe-driven, not hardcoded off.
    assert "ts_probe_headroom" in wiz and "ts_probe_agentmemory" in wiz
    assert "_hr_def" in wiz and "_am_def" in wiz
    # Compare against the PROMPT call, not the headless/env-override branch that
    # also assigns TS_WIZ_HEADROOM earlier in the same function.
    ask = wiz[wiz.index("ts_wizard_ask() {"):]
    prompt_call = 'TS_WIZ_HEADROOM="$(ts_prompt_agent_toggle'
    assert prompt_call in ask
    assert ask.index("ts_probe_headroom") < ask.index(prompt_call), \
        "headroom must be probed before it is offered"
    am_call = 'TS_WIZ_AGENTMEMORY="$(ts_prompt_agent_toggle'
    assert ask.index("ts_probe_agentmemory") < ask.index(am_call), \
        "agentmemory must be probed before it is offered"


def test_platform_impossible_apps_are_not_offered_forever():
    """nvtop is Linux-only, so on macOS it can never install — it was reported
    missing on every ts-update, accepted, and printed 'Linux-only; skipping'."""
    cfg = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    assert "ts_app_installable" in cfg
    pend = cfg[cfg.index("ts_apps_pending() {"):]
    pend = pend[:pend.index("\n}\n")]
    assert "ts_app_installable" in pend, "pending list must filter impossible ids"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_nightly_is_preticked_even_when_stable_is_installed():
    """Pre-ticking 'whatever is installed' meant a stable box saw nightly
    unticked, so pressing Enter — the thing everyone does — silently kept a
    February 2024 build that this stack's WezTerm config is not written for.
    Nightly is pre-selected regardless; only a hand-installed WezTerm
    ('unknown', not ours to replace) leaves both unticked."""
    wiz = (ROOT / "bootstrap/_wizard.sh").read_text(encoding="utf-8")
    body = wiz[wiz.index("ts_prompt_terminals() {"):]
    body = body[:body.index("\n}\n")]
    assert "stable)  preticked=\"wezterm-stable\"" not in body, \
        "installed-wins pre-tick is back"
    assert "RECOMMENDATION: nightly" in body

    def pretick(channel):
        script = (
            '. bootstrap/_config.sh >/dev/null 2>&1\n'
            '. bootstrap/_wizard.sh\n'
            f'ts_wezterm_channel() {{ echo {channel}; }}\n'
            # Stub the intro: it fetches upstream release data over the network,
            # which makes this test slow and dependent on being online.
            'ts_wezterm_prompt_intro() { :; }\n'
            # non-interactive keeps the pre-ticks, so the answer IS the pre-tick
            'ts_prompt_terminals 2>/dev/null\n')
        r = subprocess.run(["bash", "-c", script], cwd=ROOT, capture_output=True,
                           text=True, stdin=subprocess.DEVNULL)
        return r.stdout.split()

    for ch in ("stable", "nightly", "none"):
        assert "wezterm-nightly" in pretick(ch), f"{ch}: nightly not pre-ticked"
        assert "wezterm-stable" not in pretick(ch), f"{ch}: stable pre-ticked"
    # A hand-placed WezTerm is left alone.
    got = pretick("unknown")
    assert "wezterm-nightly" not in got and "wezterm-stable" not in got, got

    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "'stable'  { @('wezterm-stable') }" not in ps, "pwsh twin still installed-wins"
