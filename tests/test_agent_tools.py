"""Regression tests for per-machine, user-global coding-agent integrations."""

import json
import os
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
    # dot_zshrc is deliberately NOT in this list: it is a zsh file and uses zsh-only
    # syntax (glob patterns in [[ ]], ${(P)var}, typeset -g "$var=..."), so `bash -n`
    # rejects it. It gets its own zsh gate below.
    files = [
        "bootstrap/_config.sh", "bootstrap/_wizard.sh", "bootstrap/ts-config.sh",
        "bootstrap/ts-agents.sh", "bootstrap/wsl-bootstrap.sh",
        "bootstrap/linux-bootstrap.sh", "bootstrap/mac-bootstrap.sh",
        "run_after_90-sync-windows.sh",
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
                 "bandwhich", "gping", "bat", "eza", "fd", "ripgrep", "fzf", "tree"):
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
    assert set(ai) == {"claude", "codex", "cursor-agent", "grok", "gemini"}
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
