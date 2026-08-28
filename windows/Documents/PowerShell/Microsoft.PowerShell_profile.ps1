$env:_ZO_ECHO = '1'
$env:_ZO_EXCLUDE_DIRS = 'C:\Windows\*;*\node_modules\*;*\.git\*;*\target\*;*\dist\*;*\build\*'

function zoxide-prune {
  zoxide query -l | Where-Object { -not (Test-Path $_) } | ForEach-Object { zoxide remove $_ }
}

# ---- workspace-nav-start ----
# Workspace navigation (mirrors the zsh ws* functions). $env:WORKSPACE_DIR
# (set in profile.local.ps1) wins; otherwise the first existing autodetect
# candidate. Resolved at call time so the local override always applies.
function Get-TsWorkspace {
    if ($env:WORKSPACE_DIR) { return $env:WORKSPACE_DIR }
    foreach ($d in @(
        'C:\DATA\Workspace',
        (Join-Path $env:USERPROFILE 'workspace'),
        (Join-Path $env:USERPROFILE 'Documents\Workspace')
    )) {
        if (Test-Path $d) { return $d }
    }
    return $null
}
# Sibling resolver: handles both Workspace_Personal and Workspace-Personal naming.
function Get-TsWorkspaceSibling([string]$Suffix) {
    $root = Get-TsWorkspace
    if (-not $root) { return $null }
    foreach ($d in @("${root}_${Suffix}", "${root}-${Suffix}")) {
        if (Test-Path $d) { return $d }
    }
    return $null
}
function ws {
    $r = Get-TsWorkspace
    if ($r) { Set-Location $r } else { Write-Warning 'ws: no workspace found — set $env:WORKSPACE_DIR in profile.local.ps1' }
}
function wsp {
    $r = Get-TsWorkspaceSibling 'Personal'
    if ($r) { Set-Location $r } else { Write-Warning 'wsp: no *_Personal sibling' }
}
# wspu prefers the organised public\ tier and falls back to the old *_Public
# sibling root, so it keeps working before, during and after `wso migrate`.
function wspu {
    $root = Get-TsWorkspace
    if ($root) {
        foreach ($d in @((Join-Path $root 'public\github.com'), (Join-Path $root 'public'))) {
            if (Test-Path -LiteralPath $d) { Set-Location $d; return }
        }
    }
    $r = Get-TsWorkspaceSibling 'Public'
    if ($r) { Set-Location $r } else { Write-Warning 'wspu: no public\ tier and no *_Public sibling' }
}

# --- organised tree: per-owner jumps -----------------------------------------
# Repos live at <workspace>\<tier>\<host>\<owner>\<repo>; see `doc workspace-org`.
# These stay profile functions rather than moving into `wso` because a child
# process cannot change the parent shell's directory.
function Set-TsWsOrgLocation([string]$Owner, [string]$Name) {
    $root = Get-TsWorkspace
    if (-not $root) { Write-Warning "${Name}: no workspace found"; return }
    foreach ($d in @((Join-Path $root "src\github.com\$Owner"),
                     (Join-Path $root "archive\github.com\$Owner"))) {
        if (Test-Path -LiteralPath $d) { Set-Location $d; return }
    }
    Write-Warning "${Name}: $root\src\github.com\$Owner does not exist yet - run 'wso plan'"
}
function ws37 { Set-TsWsOrgLocation '37metrics'        'ws37' }
function ws42 { Set-TsWsOrgLocation 'dimension42ai'    'ws42' }
function wsmb { Set-TsWsOrgLocation 'martybytes'       'wsmb' }
function wsmd { Set-TsWsOrgLocation 'moleculardesigns' 'wsmd' }
function wsar {
    $root = Get-TsWorkspace
    if (-not $root) { Write-Warning 'wsar: no workspace found'; return }
    foreach ($d in @((Join-Path $root 'archive\github.com'), (Join-Path $root 'archive'))) {
        if (Test-Path -LiteralPath $d) { Set-Location $d; return }
    }
    Write-Warning 'wsar: nothing archived on this machine yet'
}

# wsj — fuzzy-jump to any repo in the tree. This is what makes the deep paths
# free: you never type them. Falls back to a filtered menu without fzf.
function wsj {
    param([string]$Query)
    $root = Get-TsWorkspace
    if (-not $root) { Write-Warning 'wsj: no workspace found'; return }
    $repos = @()
    foreach ($t in @('src', 'public', 'archive', 'local')) {
        $p = Join-Path $root $t
        if (-not (Test-Path -LiteralPath $p)) { continue }
        $repos += Get-ChildItem -LiteralPath $p -Directory -Recurse -Depth 4 -Force -ErrorAction SilentlyContinue |
                  Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName '.git') } |
                  ForEach-Object { $_.FullName.Substring($root.Length).TrimStart('\') }
    }
    if (-not $repos.Count) { Write-Warning "wsj: no repos found under $root - run 'wso plan'"; return }
    $sel = $null
    if (Get-Command fzf -ErrorAction SilentlyContinue) {
        $sel = $repos | Sort-Object | fzf --height 40% --reverse --query "$Query" --prompt 'repo> '
    } elseif ($Query) {
        $hits = @($repos | Where-Object { $_ -like "*$Query*" } | Sort-Object)
        if (-not $hits.Count) { Write-Warning "wsj: no repo matching '$Query'"; return }
        if ($hits.Count -eq 1) { $sel = $hits[0] }
        else {
            for ($i = 0; $i -lt $hits.Count; $i++) { "{0,3}) {1}" -f ($i + 1), $hits[$i] }
            $n = Read-Host 'select [1]'
            if (-not $n) { $n = 1 }
            $sel = $hits[[int]$n - 1]
        }
    } else {
        Write-Warning "wsj: fzf not installed - pass a search term, e.g. 'wsj ironcl'"; return
    }
    if ($sel) { Set-Location (Join-Path $root $sel) }
}

# Work workspace. $env:WORK_WORKSPACE_DIR (set in profile.local.ps1) wins;
# otherwise the *_Work / *-Work sibling of the main workspace — same naming rule
# as wsp/wspu. `wsw --set` writes that override for you, so a machine whose work
# tree lives somewhere unrelated to the main workspace needs no hand-editing.
function Get-TsWorkspaceWork {
    if ($env:WORK_WORKSPACE_DIR) { return $env:WORK_WORKSPACE_DIR }
    return (Get-TsWorkspaceSibling 'Work')
}
function Set-TsWorkspaceWork([string]$Path) {
    if (-not $Path) { $Path = (Get-Location).Path }
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        Write-Warning "wsw: not a directory: $Path"
        return
    }
    $full = (Resolve-Path -LiteralPath $Path).Path
    $rc   = Join-Path (Split-Path $PROFILE) 'profile.local.ps1'
    $line = "`$env:WORK_WORKSPACE_DIR = '" + ($full -replace "'", "''") + "'"
    if (Test-Path -LiteralPath $rc) {
        $stamp = Get-Date -Format 'yyyyMMdd'
        $bak = "$rc.bak.$stamp"; $n = 1
        while (Test-Path -LiteralPath $bak) { $bak = "$rc.bak.$stamp.$n"; $n++ }
        Copy-Item -LiteralPath $rc -Destination $bak -Force
        Write-Host "wsw: backup $bak"
        $kept = @(Get-Content -LiteralPath $rc | Where-Object { $_ -notmatch '^\s*\$env:WORK_WORKSPACE_DIR\s*=' })
        Set-Content -LiteralPath $rc -Value ($kept + $line) -Encoding utf8
        Write-Host "wsw: updated $rc"
    } else {
        $dir = Split-Path -Parent $rc
        if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        Set-Content -LiteralPath $rc -Encoding utf8 -Value @(
            '# Per-machine pwsh overrides — not synced by the stack.', $line)
        Write-Host "wsw: created $rc"
    }
    $env:WORK_WORKSPACE_DIR = $full
    Write-Host "wsw: WORK_WORKSPACE_DIR=$full"
}
function wsw {
    if ($args.Count -gt 0) {
        switch -Regex ([string]$args[0]) {
            '^(--set|-s|-set)$' { Set-TsWorkspaceWork ([string]$args[1]); return }
            '^(--show|-show)$'  {
                $r = Get-TsWorkspaceWork
                if ($r) { Write-Output $r } else { Write-Warning 'wsw: no work workspace configured' }
                return
            }
            '^(-h|--help|-help)$' {
                Write-Output 'wsw              cd to the work workspace'
                Write-Output 'wsw --set [dir]  define it in profile.local.ps1 (default: current dir)'
                Write-Output 'wsw --show       print the resolved path'
                return
            }
        }
    }
    $r = Get-TsWorkspaceWork
    if ($r) {
        Set-Location $r
    } else {
        Write-Warning "wsw: no work workspace found — looked for `$env:WORK_WORKSPACE_DIR and *_Work/*-Work siblings of $(Get-TsWorkspace)"
        Write-Warning "wsw: run 'wsw --set [dir]' to define one in profile.local.ps1"
    }
}
# Project-specific shortcuts (wscalibra, wsnetsuite, …) belong in
# profile.local.ps1 — see profile.local.ps1.example.

# Dropbox navigation (mirrors the zsh db function). $env:DROPBOX_DIR (set in
# profile.local.ps1) wins; otherwise Dropbox's own info.json, then the usual
# candidates. Resolved at call time so the local override always applies.
function Get-TsDropbox {
    if ($env:DROPBOX_DIR) { return $env:DROPBOX_DIR }
    # info.json is authoritative: it is the only thing that gets a relocated
    # folder, a Business account, or two linked accounts right.
    foreach ($info in @(
        (Join-Path $env:LOCALAPPDATA 'Dropbox\info.json'),
        (Join-Path $env:APPDATA 'Dropbox\info.json')
    )) {
        if (-not (Test-Path -LiteralPath $info)) { continue }
        try {
            $cfg = Get-Content -LiteralPath $info -Raw | ConvertFrom-Json
            foreach ($account in @('personal', 'business')) {
                $prop = $cfg.PSObject.Properties[$account]
                if ($prop -and $prop.Value.path -and (Test-Path -LiteralPath $prop.Value.path)) {
                    return $prop.Value.path
                }
            }
        } catch {}
    }
    foreach ($d in @(
        (Join-Path $env:USERPROFILE 'Dropbox'),
        (Join-Path $env:USERPROFILE 'Dropbox (Personal)'),
        (Join-Path $env:USERPROFILE 'Dropbox (Business)')
    )) {
        if (Test-Path -LiteralPath $d) { return $d }
    }
    return $null
}
function db {
    $r = Get-TsDropbox
    if ($r) { Set-Location $r } else { Write-Warning 'db: no Dropbox found — set $env:DROPBOX_DIR in profile.local.ps1' }
}
function dbx { db @args }
# ---- workspace-nav-end ----

# POSIX twin: _ts_tab_title in dot_zshrc. Three terminals, three mechanisms,
# because only one of them has a sticky per-tab title reachable from a script:
#   WezTerm  `wezterm cli set-tab-title` - a real tab-title override that
#            survives the running app's own OSC.
#   tmux     tmux OWNS the outer title while attached: it swallows our OSC 2 and
#            substitutes set-titles-string, so we skip.
#   else     plain OSC 2, which only STAYS because the cc* wrappers set
#            CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1 so Claude writes no title of
#            its own. Without that pair this is pointless.
function Set-TsTabTitle([string]$title) {
    if ($env:WEZTERM_PANE) {
        & wezterm.exe cli set-tab-title $title 2>$null
    } elseif (-not $env:TMUX -and $title) {
        try { [Console]::Out.Write("$([char]27)]2;$title$([char]7)") } catch {}
    }
    # Empty title marks CC exit -> clear cc_state; WezTerm Lua restores pane bg.
    if (-not $title) {
        try {
            [Console]::Out.Write("$([char]27)]1337;SetUserVar=cc_state=$([char]7)")
        } catch {}
    }
}

# Agent-tool settings are read at launch, so `tstack config agents ...` takes effect
# in already-open shells. Headroom routing is process-local and restored in a
# finally block; no provider URL leaks into later commands or child shells.
function Get-TsAgentRuntimeSetting([string]$Name, [string]$Default = 'off') {
    $envName = switch ($Name) {
        'headroomEnabled' { 'TS_HEADROOM' }
        'headroomCursorMode' { 'TS_HEADROOM_CURSOR' }
        'cavemanEnabled' { 'TS_CAVEMAN' }
        'agentmemoryEnabled' { 'TS_AGENTMEMORY' }
    }
    if ($envName) {
        $override = [Environment]::GetEnvironmentVariable($envName, 'Process')
        if ($override) { return $override.ToLowerInvariant() }
    }
    $path = Join-Path $env:LOCALAPPDATA 'terminal-stack\config.json'
    try {
        $cfg = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        $prop = $cfg.PSObject.Properties[$Name]
        if ($prop -and $prop.Value) { return "$($prop.Value)".ToLowerInvariant() }
    } catch {}
    return $Default
}

$script:TsHeadroomProbeAt = [datetime]::MinValue
$script:TsHeadroomProbeOk = $false
$script:TsHeadroomWarned = $false
function Get-TsHeadroomToken {
    if ($env:HEADROOM_PROXY_TOKEN) { return $env:HEADROOM_PROXY_TOKEN }
    $file = $env:HEADROOM_ENV_FILE
    if (-not $file) {
        # <clone>\services\stacks\headroom\.env — from the clone, not by walking
        # the workspace for a sibling repo (the runtime clone is not in it).
        $src = Resolve-TsSourceDir
        if ($src) { $file = Join-Path $src 'services\stacks\headroom\.env' }
    }
    if (-not $file -or -not (Test-Path -LiteralPath $file)) { return $null }
    $line = Get-Content -LiteralPath $file | Where-Object { $_ -match '^HEADROOM_PROXY_TOKEN=' } | Select-Object -First 1
    if ($line) { return ($line -replace '^HEADROOM_PROXY_TOKEN=', '') }
    return $null
}
function Test-TsHeadroomRuntime {
    if ((Get-TsAgentRuntimeSetting headroomEnabled) -ne 'on') { return $false }
    if (((Get-Date) - $script:TsHeadroomProbeAt).TotalSeconds -lt 5) { return $script:TsHeadroomProbeOk }
    $script:TsHeadroomProbeAt = Get-Date
    $script:TsHeadroomProbeOk = $false
    $token = Get-TsHeadroomToken
    if (-not $token) { return $false }
    try {
        $r = Invoke-WebRequest -Uri 'http://127.0.0.1:8787/stats' -TimeoutSec 2 -UseBasicParsing `
            -Headers @{ 'X-Headroom-Proxy-Token' = $token }
        $script:TsHeadroomProbeOk = ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300)
    } catch {}
    return $script:TsHeadroomProbeOk
}

# Resolve an agent CLI at CALL time and cache the hit, rather than snapshotting it
# when the profile loads. These CLIs are routinely installed into an already-open
# shell, and a load-time snapshot left every wrapper in that session throwing
# "not found on PATH" until a new one was opened. POSIX twin: _ts_agent_bin in
# dot_zshrc. -CommandType Application excludes our own claude/codex *functions*,
# so this cannot recurse.
function Get-TsAgentCommand {
    param([Parameter(Mandatory)][string]$Name)
    $var = "Ts${Name}Command"
    $cached = Get-Variable -Name $var -Scope Script -ValueOnly -ErrorAction SilentlyContinue
    # Re-test the path: it self-heals a cached location the CLI later replaced.
    if ($cached -and (Test-Path -LiteralPath $cached)) { return $cached }
    $probe = { @("$Name.exe", "$Name.cmd", $Name) |
        ForEach-Object { Get-Command $_ -CommandType Application -ErrorAction SilentlyContinue } |
        Select-Object -First 1 -ExpandProperty Source }
    $found = & $probe
    if (-not $found) {
        # An installer that just ran wrote the User PATH; this process still holds
        # the copy it started with. Refresh from the registry and probe once more —
        # the pwsh analogue of zsh's rehash.
        $env:PATH = @(
            [Environment]::GetEnvironmentVariable('PATH', 'Machine'),
            [Environment]::GetEnvironmentVariable('PATH', 'User')
        ) -join ';'
        $found = & $probe
    }
    if ($found) { Set-Variable -Name $var -Scope Script -Value $found }
    return $found
}
$script:TsClaudeCommand = $null
function Get-TsClaudeCommand {
    $bin = Get-TsAgentCommand 'Claude'
    if (-not $bin) { throw 'claude: not found. Install it from https://claude.ai/install (or run the native installer), then retry.' }
    return $bin
}
function claude-stock {
    $bin = Get-TsClaudeCommand
    & $bin @args
}
function claude {
    $bin = Get-TsClaudeCommand
    if ((Get-TsAgentRuntimeSetting headroomEnabled) -ne 'on') { & $bin @args; return }
    if (-not (Test-TsHeadroomRuntime)) {
        if (-not $script:TsHeadroomWarned) {
            Write-Warning 'Headroom is enabled but unavailable on 127.0.0.1:8787; this Claude launch is going direct.'
            $script:TsHeadroomWarned = $true
        }
        & $bin @args
        return
    }
    $savedBase = $env:ANTHROPIC_BASE_URL
    $savedSearch = $env:ENABLE_TOOL_SEARCH
    $savedProject = $env:HEADROOM_PROJECT
    $savedHeaders = $env:ANTHROPIC_CUSTOM_HEADERS
    try {
        $env:ANTHROPIC_BASE_URL = 'http://127.0.0.1:8787'
        if (-not $env:ENABLE_TOOL_SEARCH) { $env:ENABLE_TOOL_SEARCH = 'true' }
        $env:HEADROOM_PROJECT = Split-Path -Leaf $PWD
        $header = 'X-Headroom-Proxy-Token: ' + (Get-TsHeadroomToken)
        $env:ANTHROPIC_CUSTOM_HEADERS = if ($savedHeaders) { "$savedHeaders`n$header" } else { $header }
        & $bin @args
    } finally {
        $env:ANTHROPIC_BASE_URL = $savedBase
        $env:ENABLE_TOOL_SEARCH = $savedSearch
        $env:HEADROOM_PROJECT = $savedProject
        $env:ANTHROPIC_CUSTOM_HEADERS = $savedHeaders
    }
}

# Bare project leaf as the tab title — no 'cc' prefix: the WezTerm tab bar's
# Claude icon and state dots already say Claude, and the prefix wasted tab width.
function cc    { Set-TsTabTitle "$(Split-Path -Leaf $PWD)"; $p=$env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE; $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE='1'; try { claude @args } finally { $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE=$p; Set-TsTabTitle "" } }
function ccc   { Set-TsTabTitle "$(Split-Path -Leaf $PWD)"; $p=$env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE; $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE='1'; try { claude --continue @args } finally { $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE=$p; Set-TsTabTitle "" } }
function ccd   { Set-TsTabTitle "$(Split-Path -Leaf $PWD)"; $p=$env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE; $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE='1'; try { claude --dangerously-skip-permissions @args } finally { $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE=$p; Set-TsTabTitle "" } }
function ccdc  { Set-TsTabTitle "$(Split-Path -Leaf $PWD)"; $p=$env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE; $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE='1'; try { claude --dangerously-skip-permissions --continue @args } finally { $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE=$p; Set-TsTabTitle "" } }
function ccr   { Set-TsTabTitle "$(Split-Path -Leaf $PWD)"; $p=$env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE; $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE='1'; try { claude --resume @args } finally { $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE=$p; Set-TsTabTitle "" } }
function ccdr  { Set-TsTabTitle "$(Split-Path -Leaf $PWD)"; $p=$env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE; $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE='1'; try { claude --dangerously-skip-permissions --resume @args } finally { $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE=$p; Set-TsTabTitle "" } }
function cca   { Set-TsTabTitle "agents"; $p=$env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE; $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE='1'; try { claude agents } finally { $env:CLAUDE_CODE_DISABLE_TERMINAL_TITLE=$p; Set-TsTabTitle "" } }

# Interactive Codex sessions get a three-row WezTerm dashboard. Utility commands
# remain stock, and codex-stock is an explicit no-enhancements escape hatch.
$script:TsCodexCommand = $null
function Get-TsCodexCommand {
    $bin = Get-TsAgentCommand 'Codex'
    if (-not $bin) { throw 'codex: not found. Install it with: npm install -g @openai/codex  (or see github.com/openai/codex/releases)' }
    return $bin
}

function Test-TsCodexInteractive {
    param([object[]]$CliArgs)
    if ($CliArgs -contains '-h' -or $CliArgs -contains '--help' -or
        $CliArgs -contains '-V' -or $CliArgs -contains '--version') { return $false }

    $valueOptions = @(
        '-c', '--config', '--enable', '--disable', '-i', '--image', '-m', '--model', '--local-provider',
        '-p', '--profile', '-s', '--sandbox', '-C', '--cd', '--add-dir',
        '-a', '--ask-for-approval', '--remote', '--remote-auth-token-env'
    )
    $utilityCommands = @(
        'exec', 'e', 'review', 'login', 'logout', 'mcp', 'plugin', 'mcp-server',
        'app-server', 'remote-control', 'app', 'completion', 'update', 'doctor',
        'sandbox', 'debug', 'apply', 'a', 'archive', 'delete', 'migrate-rollouts',
        'unarchive', 'cloud', 'exec-server', 'features', 'help'
    )
    $skipValue = $false
    foreach ($argValue in $CliArgs) {
        $argText = [string]$argValue
        if ($skipValue) { $skipValue = $false; continue }
        if ($argText -eq '--') { return $true }
        if ($argText -match '^--[^=]+=') { continue }
        if ($valueOptions -contains $argText) { $skipValue = $true; continue }
        if ($argText.StartsWith('-')) { continue }
        if ($argText -in @('resume', 'fork')) { return $true }
        return ($utilityCommands -notcontains $argText)
    }
    return $true
}

function codex-stock {
    $bin = Get-TsCodexCommand
    & $bin @args
}

function Invoke-TsCodex {
    param([switch]$Yolo, [object[]]$CliArgs)
    $helper = Join-Path $HOME '.codex\hooks\terminal_stack.py'
    $profile = Join-Path $HOME '.codex\terminal-stack.config.toml'
    $python = Get-Command py.exe -ErrorAction SilentlyContinue
    $parent = $env:WEZTERM_PANE
    $sidecar = $null
    $launched = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $codexArgs = @()
    if ($Yolo) { $codexArgs += '--yolo' }
    # Resolve before the sidecar pane is spawned: throwing later would leave an
    # orphaned dashboard pane behind.
    $bin = Get-TsCodexCommand

    if ($python -and (Test-Path -LiteralPath $helper) -and (Test-Path -LiteralPath $profile)) {
        $codexArgs += @('-p', 'terminal-stack')
    } else {
        Write-Warning 'terminal-stack: Codex dashboard/profile unavailable; running without enhancements.'
    }

    if ($parent -and $python -and (Test-Path -LiteralPath $helper) -and
        (Get-Command wezterm.exe -ErrorAction SilentlyContinue)) {
        $sidecarArgs = @(
            'cli', 'split-pane', '--pane-id', $parent, '--bottom', '--cells', '3', '--',
            'py.exe', '-3', $helper, 'dashboard', '--pane', $parent,
            '--cwd', $PWD.Path, '--launched-at', [string]$launched
        )
        $paneOutput = & wezterm.exe @sidecarArgs 2>$null
        if ($paneOutput -match '^\d+$') { $sidecar = $paneOutput.Trim() }
        & wezterm.exe cli activate-pane --pane-id $parent 2>$null | Out-Null
    }

    $previousParent = $env:TS_CODEX_PARENT_PANE
    $previousOpenAiBase = $env:OPENAI_BASE_URL
    $previousHeadroomProject = $env:HEADROOM_PROJECT
    $previousHeadroomToken = $env:HEADROOM_PROXY_TOKEN
    $env:TS_CODEX_PARENT_PANE = $parent
    $exitCode = 0
    try {
        if ((Get-TsAgentRuntimeSetting headroomEnabled) -eq 'on') {
            if (Test-TsHeadroomRuntime) {
                $env:OPENAI_BASE_URL = 'http://127.0.0.1:8787/v1'
                $env:HEADROOM_PROJECT = Split-Path -Leaf $PWD
                $env:HEADROOM_PROXY_TOKEN = Get-TsHeadroomToken
                $codexArgs += @(
                    '--config', 'model_provider="headroom"',
                    '--config', 'openai_base_url="http://127.0.0.1:8787/v1"',
                    '--config', 'model_providers.headroom.name="OpenAI via Headroom proxy"',
                    '--config', 'model_providers.headroom.base_url="http://127.0.0.1:8787/v1"',
                    '--config', 'model_providers.headroom.supports_websockets=true',
                    '--config', 'model_providers.headroom.requires_openai_auth=true',
                    '--config', 'model_providers.headroom.env_http_headers.X-Headroom-Proxy-Token="HEADROOM_PROXY_TOKEN"'
                )
            } elseif (-not $script:TsHeadroomWarned) {
                Write-Warning 'Headroom is enabled but unavailable on 127.0.0.1:8787; this Codex launch is going direct.'
                $script:TsHeadroomWarned = $true
            }
        }
        & $bin @codexArgs @CliArgs
        $exitCode = $LASTEXITCODE
    } finally {
        if ($sidecar -and $sidecar -match '^\d+$') {
            & wezterm.exe cli kill-pane --pane-id $sidecar 2>$null | Out-Null
        }
        if ($python -and $parent -and (Test-Path -LiteralPath $helper)) {
            & py.exe -3 $helper cleanup --pane $parent 2>$null | Out-Null
        }
        $env:TS_CODEX_PARENT_PANE = $previousParent
        $env:OPENAI_BASE_URL = $previousOpenAiBase
        $env:HEADROOM_PROJECT = $previousHeadroomProject
        $env:HEADROOM_PROXY_TOKEN = $previousHeadroomToken
    }
    $global:LASTEXITCODE = $exitCode
}
function codex {
    if (Test-TsCodexInteractive -CliArgs $args) {
        Invoke-TsCodex -CliArgs $args
    } else {
        codex-stock @args
    }
}
function cy  { Invoke-TsCodex -Yolo -CliArgs $args }
function cyr { $resumeArgs = @('resume') + $args; Invoke-TsCodex -Yolo -CliArgs $resumeArgs }

# Escape hatch: vanilla pwsh, no profile (no starship/zoxide/aliases).
# Nested — `exit` drops back to the customized shell.
function plain { Set-TsTabTitle "plain • $(Split-Path -Leaf $PWD)"; try { pwsh -NoLogo -NoProfile @args } finally { Set-TsTabTitle "" } }

# ---- shell-init-cache-start ----
# Every external process this profile starts is expensive on a machine whose
# antivirus scans each exec: measured 300ms-2s per spawn here, and `starship init
# powershell` spawns starship TWICE (a bootstrap that re-runs it with
# --print-full-init). A new WezTerm pane paid that for starship, zoxide and fnm
# before it drew a prompt. The generated text only changes when the binary does,
# so cache it, keyed on the exe's path, mtime and size.
#
# Hand back a FILE for the caller to dot-source, not a string to
# Invoke-Expression: measured 427ms against 612ms for the same 10KB of starship
# init, because the parse of a file is not the parse of a dynamic string.
# And the caller dot-sources it, not this function -- $PROFILE runs in the global
# scope, a function body does not, and starship's `New-Module` / zoxide's
# `function global:` definitions would land somewhere the prompt never sees.
#
# The cache is ours and machine-local: no dated backup (that rule is for user
# files), and a stale or unreadable one is simply regenerated. The stamp is a
# comment line, so the cache stays a plain dot-sourceable script.
function Get-TsToolInit {
    param(
        [Parameter(Mandatory)][string]$Name,
        [Parameter(Mandatory)][string]$Exe,
        [Parameter(Mandatory)][scriptblock]$Generate
    )

    $item = Get-Item -LiteralPath $Exe -ErrorAction SilentlyContinue
    $key = if ($item) { "$($item.FullName)|$($item.LastWriteTimeUtc.Ticks)|$($item.Length)" } else { $Exe }
    $stamp = "# ts-init-cache $key"
    $cache = Join-Path $env:LOCALAPPDATA "terminal-stack\cache\$Name-init.ps1"

    try {
        if ((([System.IO.File]::ReadLines($cache)) | Select-Object -First 1) -eq $stamp) {
            return [pscustomobject]@{ Path = $cache; Text = $null }
        }
    } catch { }

    $text = (& $Generate | Out-String)
    if (-not $text.Trim()) { return $null }
    # %TEMP% is the fallback target rather than a straight give-up: dot-sourcing a
    # file is the fast path, so a locked-down %LOCALAPPDATA% should cost one
    # regeneration per shell, not the slower parse for the life of the machine.
    foreach ($target in @($cache, (Join-Path $env:TEMP "ts-$Name-init.ps1"))) {
        try {
            $dir = Split-Path -Parent $target
            if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
            # Another pane may be regenerating the same file: write private, then swap.
            $tmp = "$target.$PID.tmp"
            Set-Content -LiteralPath $tmp -Value ($stamp + "`n" + $text) -Encoding UTF8 -NoNewline
            Move-Item -LiteralPath $tmp -Destination $target -Force
            return [pscustomobject]@{ Path = $target; Text = $text }
        } catch { }
    }
    # Nowhere to write: hand back the text so the shell still gets its prompt.
    return [pscustomobject]@{ Path = $null; Text = $text }
}
# ---- shell-init-cache-end ----

# ---- starship-stack-start ----

# Cursor/Claude agent shells set TERM=dumb and CURSOR_AGENT=1 — skip prompt chrome there.
function Test-TsAgentShell {
    if ($env:CURSOR_AGENT -eq '1') { return $true }
    if ($env:TERM -eq 'dumb') { return $true }
    if ($env:CI -eq 'true' -or $env:CI -eq '1') { return $true }
    return $false
}

# Native console children (Claude Code, etc.) can SetConsoleOutputCP back to 437 on exit; [Console]::OutputEncoding caches and won't catch it, so probe the OS codepage directly.
# Compiling this C# at every shell start cost ~340ms (Add-Type runs the compiler;
# PowerShell caches nothing between sessions). Compile once to an assembly under
# %LOCALAPPDATA% and load that instead -- ~25ms. The in-memory compile stays as
# the fallback, so a missing or unloadable cache only costs what it used to.
if (-not ('Native.ConsoleCP' -as [type])) {
    $tsCpSrc = @'
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern uint GetConsoleOutputCP();
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern bool SetConsoleOutputCP(uint wCodePageID);
'@
    $tsCpDll = Join-Path $env:LOCALAPPDATA 'terminal-stack\cache\ts-consolecp.dll'
    if (-not (Test-Path -LiteralPath $tsCpDll)) {
        try {
            New-Item -ItemType Directory -Force -Path (Split-Path $tsCpDll) | Out-Null
            # Never compile straight onto the target: another pane may have it loaded,
            # and a locked overwrite would throw where a swap just loses the race.
            $tsCpTmp = "$tsCpDll.$PID.tmp"
            Add-Type -Namespace Native -Name ConsoleCP -MemberDefinition $tsCpSrc -OutputAssembly $tsCpTmp -ErrorAction Stop
            Move-Item -LiteralPath $tsCpTmp -Destination $tsCpDll -Force
        } catch { Remove-Item -LiteralPath "$tsCpDll.$PID.tmp" -Force -ErrorAction SilentlyContinue }
    }
    if (Test-Path -LiteralPath $tsCpDll) { try { Add-Type -Path $tsCpDll } catch { } }
    if (-not ('Native.ConsoleCP' -as [type])) {
        Add-Type -Namespace Native -Name ConsoleCP -MemberDefinition $tsCpSrc | Out-Null
    }
}
[Native.ConsoleCP]::SetConsoleOutputCP(65001) | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8

if (-not (Test-TsAgentShell)) {
    # --print-full-init is what `starship init powershell` itself re-runs starship
    # for; asking for it directly is one spawn instead of two, and none when cached.
    $tsStarship = (Get-Command starship -ErrorAction SilentlyContinue).Source
    if ($tsStarship) {
        $tsInit = Get-TsToolInit -Name starship -Exe $tsStarship -Generate {
            & $tsStarship init powershell --print-full-init
        }
        if ($tsInit.Path) { . $tsInit.Path } elseif ($tsInit.Text) { Invoke-Expression $tsInit.Text }
    }
    if (Get-Command Enable-TransientPrompt -ErrorAction SilentlyContinue) { Enable-TransientPrompt }

    function Invoke-Starship-PreCommand {
        if ([Native.ConsoleCP]::GetConsoleOutputCP() -ne 65001) {
            [Native.ConsoleCP]::SetConsoleOutputCP(65001) | Out-Null
            [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
            [Console]::InputEncoding  = [System.Text.Encoding]::UTF8
        }
        $loc = $executionContext.SessionState.Path.CurrentLocation
        if ($loc.Provider.Name -eq 'FileSystem') {
            $hostName = ($env:COMPUTERNAME).ToLower()
            $providerPath = $loc.ProviderPath -replace '\\', '/'
            Write-Host -NoNewline "`e]7;file://${hostName}/${providerPath}`a"
            $leaf = Split-Path -Leaf $loc.Path
            if ([string]::IsNullOrEmpty($leaf)) { $leaf = $loc.Path }
            Write-Host -NoNewline "`e]0;pwsh • $leaf`a"
        }
    }
}
# ---- starship-stack-end ----

# ---- cli-tools-start ----
# Default editor: micro (a nano alternative), when installed. git follows $EDITOR.
if (Get-Command micro -ErrorAction SilentlyContinue) { $env:EDITOR = 'micro' }

# v - open Neovim. POSIX twin: the `v` alias in dot_zshrc's cli-tools block.
# Defined unconditionally and resolved per call, for the same reason `c` is:
# gating the *definition* on Get-Command left the name silently undefined when
# the tool was installed mid-session.
# NOTE: fzf's Ctrl+T / Ctrl+R / Alt+C key bindings are WSL-side only. Native
# pwsh has no fzf bindings - Ctrl+R here is PSReadLine's own reverse search.
# See docs/kb/windows/pwsh.md.
function v { nvim @args }

# y - yazi, returning to whatever directory you exited in. POSIX twin: y() in
# dot_zshrc. yazi writes its final cwd to --cwd-file and we Set-Location there,
# because a child process cannot change its parent's directory.
function y {
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        yazi @args --cwd-file="$tmp"
        $cwd = Get-Content -LiteralPath $tmp -Raw -Encoding UTF8 -ErrorAction SilentlyContinue
        if ($cwd) { $cwd = $cwd.Trim() }
        if ($cwd -and $cwd -ne $PWD.Path) { Set-Location -LiteralPath $cwd }
    } finally {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
}

# fnm — Node version manager. --use-on-cd auto-switches on .nvmrc/.node-version,
# which is the whole reason to run a manager rather than a single winget node.
# POSIX twin: the fnm line in dot_zshrc's cli-tools block.
# --resolve-engines=false on purpose. fnm reads package.json `engines.node` when
# no .nvmrc/.node-version is present, which means every `cd` into a JS repo spawns
# fnm (~350ms here), and an `engines` range that no fnm-INSTALLED version
# satisfies turns the cd into an interactive "Do you want to install it? [y/N]"
# -- even when the active node already satisfies it (system node 26 vs `>=24`).
# An explicit .nvmrc/.node-version pin is still honoured; that one is a choice,
# an engines range is metadata. With this off, fnm's own hook stops testing for
# package.json at all, so the cd costs nothing.
# The fallback matters: fnm before 1.36 has no --resolve-engines and exits
# non-zero, and Invoke-Expression of an empty string would leave fnm unwired
# with nothing printed.
if (Get-Command fnm -ErrorAction SilentlyContinue) {
    $tsFnmEnv = fnm env --use-on-cd --resolve-engines=false --shell powershell 2>$null | Out-String
    if (-not $tsFnmEnv.Trim()) { $tsFnmEnv = fnm env --use-on-cd --shell powershell | Out-String }
    Invoke-Expression $tsFnmEnv
}

$tsZoxide = (Get-Command zoxide -ErrorAction SilentlyContinue).Source
if ($tsZoxide) {
    $tsInit = Get-TsToolInit -Name zoxide -Exe $tsZoxide -Generate { & $tsZoxide init powershell }
    if ($tsInit.Path) { . $tsInit.Path } elseif ($tsInit.Text) { Invoke-Expression $tsInit.Text }
}

if (Get-Command eza -ErrorAction SilentlyContinue) {
    # Bold blue directories everywhere (matches WezTerm ANSI blue in both themes).
    $env:EZA_COLORS = 'di=1;34:da=1;34:ln=1;36'
    # Built-in `ls` is an alias to Get-ChildItem; remove before redefining as a function.
    Remove-Item Alias:ls -Force -ErrorAction SilentlyContinue
    function ls { eza --icons=always --git --group-directories-first @args }
    function ll { eza -l --icons=always --git --group-directories-first @args }
    function la { eza -la --icons=always --git --group-directories-first @args }
    function lt { eza --tree --icons=always --git --group-directories-first @args }
}

# lsr — "list by recent": top-level directories ranked by the newest LastWriteTime
# among their immediate children (one level deep, no recursion). A directory's own
# timestamp only moves when entries are added or removed, so `ls -lt`/eza bury a
# project whose files you edited all day. Mirrors the zsh lsr.
# Emits objects rather than Format-Table output, so `lsr | Where-Object ...` works.
function lsr {
    param([string]$Path = '.', [switch]$All)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        Write-Warning "lsr: not a directory: $Path"
        return
    }
    # -Force on the CHILDREN always (hidden files still count as activity); on the
    # top-level listing only with -All. Note "hidden" is the hidden ATTRIBUTE here,
    # where the zsh version keys off a leading dot.
    Get-ChildItem -LiteralPath $Path -Directory -Force:$All -ErrorAction SilentlyContinue |
        ForEach-Object {
            $newest = Get-ChildItem -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue |
                      Sort-Object LastWriteTime -Descending |
                      Select-Object -First 1
            [pscustomobject]@{
                Name   = $_.Name
                Latest = if ($newest) { $newest.LastWriteTime } else { $null }
                Item   = if ($newest) { $newest.Name } else { '(empty)' }
            }
        } |
        # Explicit MinValue key so empty dirs pin to the bottom instead of relying
        # on however Sort-Object happens to order $null.
        Sort-Object -Property @{
            Expression = { if ($_.Latest) { $_.Latest } else { [datetime]::MinValue } }
        } -Descending
}

# lsrr — lsr, capped at the 20 most recent. Same parameters as lsr, and still
# emits objects, so it composes the same way.
function lsrr { lsr @args | Select-Object -First 20 }

# ref — alias into the `doc` knowledge base (replaced the old command-reference file).
function ref { doc @args }

# rmf <path...> — delete file(s)/folder(s) recursively with no confirmation prompts.
function rmf {
    param([Parameter(Mandatory, ValueFromRemainingArguments = $true)][string[]]$Paths)
    Remove-Item -Path $Paths -Recurse -Force -Confirm:$false
}
# ---- cli-tools-end ----

# ---- git-shortcuts-start ----
# Git muscle-memory, matching the zsh side (oh-my-zsh git plugin + stack
# overrides). gp always means PULL and gl always means LOG on this stack.
function gst { git status @args }
function gp  { git pull @args }
function gco { git checkout @args }
function gf  { git fetch @args }
function gl  { git log --oneline --graph --decorate -10 @args }
function gd  { git diff @args }
function ga  { git add @args }
function gb  { git branch @args }
# ---- git-shortcuts-end ----

# ---- terminal-stack-update-start ----
# Resolution order: -SourceDir → $env:TERMINAL_STACK_DIR → canonical location →
# legacy candidates in list order. We deliberately do NOT consult
# `chezmoi source-path` here: on Windows that returns chezmoi's default
# sourceDir (~/.local/share/chezmoi) regardless of where the actual clone
# lives, because Windows users don't configure chezmoi.toml (the WSL side does).

# The canonical runtime clone location — inside the app-data dir the stack
# already owns (config.json, rollback-sha, docs mirror). Pins are only for
# NON-canonical locations. Twin copies: bootstrap/_cleanup.ps1 (parse-time
# isolation), bootstrap/_config.sh ts_canonical_clone_dir (bash).
function Get-TsCanonicalCloneDir { Join-Path $env:LOCALAPPDATA 'terminal-stack\stack' }

# True when a path is a DEV clone at a wso workspace tier path
# (<tier>/<host-with-dot>/<owner>/<repo>). Dev clones are invisible to
# auto-resolution unless pinned. Twin of bootstrap/_cleanup.sh ts_is_dev_clone.
function Test-TsDevClone([string]$Path) {
    ($Path -replace '\\', '/') -match '/(src|public|archive|local|scratch)/[^/]+\.[^/]+/[^/]+/[^/]+/?$'
}

# CANONICAL CLONE CANDIDATE LIST (pwsh replica) — pin, then canonical, then
# legacy defaults. Keep in sync with docs/decisions.md § "Runtime clone location"
# and the siblings: bootstrap/_cleanup.sh ts_clone_candidates (master),
# dot_zshrc _ts_clone_candidates, bootstrap/_cleanup.ps1 Get-TsCleanupCloneCandidates.
function Get-TsCloneCandidates {
    $seen = @{}
    @(
        $env:TERMINAL_STACK_DIR,
        (Get-TsCanonicalCloneDir),
        (Join-Path $env:USERPROFILE 'code\terminal-stack'),
        (Join-Path $env:USERPROFILE 'terminal-stack'),
        (Join-Path $env:USERPROFILE 'Workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE 'workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE 'Documents\Workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE '.local\share\chezmoi'),
        'C:\DATA\Workspace\terminal-stack'
    ) | Where-Object {
        if (-not $_) { return $false }
        $k = $_.ToLower(); if ($seen[$k]) { $false } else { $seen[$k] = $true; $true }
    }
}

# A path is a terminal-stack clone when it is a git repo whose origin names the
# project. The name test is necessary but NOT sufficient to pick one: a stale
# install under ~\terminal-stack from an old account still matches, which is
# exactly how a machine ends up re-syncing an ancient profile over a current one.
# Dev clones (workspace tier paths) are skipped unless they ARE the pin.
function Get-TsClones {
    $out = foreach ($d in (Get-TsCloneCandidates)) {
        if (-not (Test-Path (Join-Path $d '.git'))) { continue }
        if ((Test-TsDevClone $d) -and $d -ne $env:TERMINAL_STACK_DIR) { continue }
        $origin = & git -C $d config --get remote.origin.url 2>$null
        if ($origin -notmatch 'terminal-stack') { continue }
        $ct = & git -C $d log -1 --format=%ct 2>$null
        [pscustomobject]@{
            Path   = $d
            Origin = ([string]$origin).Trim()
            Commit = if ($ct) { [int64]$ct } else { 0 }
            Short  = (& git -C $d log -1 --format='%h %s' 2>$null)
        }
    }
    # Candidate order IS the priority: pin > canonical > legacy. (Ranking by
    # newest commit was removed — it would prefer a dev clone the moment you
    # commit to it, updating the tree you're developing in.)
    return @($out)
}

# Resolve the clone to operate on. An explicit -SourceDir or $env:TERMINAL_STACK_DIR
# always wins. Otherwise take the highest-priority real clone and, when more than
# one exists, say so — silently choosing between two clones is how the wrong
# profile gets deployed.
#
# The two pin sources are NOT equivalent when the pin is dangling. -SourceDir is
# typed per call, so a bad one is a mistake worth failing on. $env:TERMINAL_STACK_DIR
# arrives from profile.local.ps1 in every session, so a stale line there would
# otherwise brick tstack update / wso / doc machine-wide with no way out — it degrades
# to the normal candidate search instead.
function Resolve-TsSourceDir([string]$SourceDir) {
    # Initialized up front: it is only assigned in the stale-pin branch below, and reading
    # an unset variable is a terminating error under Set-StrictMode -- which a caller's
    # session can have on for reasons that have nothing to do with this repo.
    $stalePin = $false
    if ($SourceDir) {
        if (-not (Test-Path (Join-Path $SourceDir '.git'))) {
            Write-Warning "terminal-stack clone not found at $SourceDir. Pass -SourceDir <path> or re-run install.ps1."
            return $null
        }
        return $SourceDir
    }
    if ($env:TERMINAL_STACK_DIR) {
        if (Test-Path (Join-Path $env:TERMINAL_STACK_DIR '.git')) {
            return $env:TERMINAL_STACK_DIR
        }
        Write-Warning "stale `$env:TERMINAL_STACK_DIR pin: no clone at $($env:TERMINAL_STACK_DIR) — searching the usual locations."
        Write-Host   "  Clear it with 'tstack doctor --repair', or delete the line from $(Join-Path (Split-Path $PROFILE) 'profile.local.ps1')."
        $stalePin = $true
    }
    $clones = Get-TsClones
    if (-not $clones.Count) {
        Write-Warning 'No terminal-stack clone found. Pass -SourceDir <path> or re-run install.ps1.'
        return $null
    }
    if ($stalePin) { Write-Host "  using $($clones[0].Path)" }
    if ($clones.Count -gt 1) {
        Write-Warning "$($clones.Count) terminal-stack clones found; using the highest-priority location:"
        foreach ($c in $clones) {
            $mark = if ($c.Path -eq $clones[0].Path) { '->' } else { '  ' }
            Write-Host ("  {0} {1}" -f $mark, $c.Path)
            Write-Host ("       {0}  |  {1}" -f $c.Origin, $c.Short)
        }
        Write-Host "  Consolidate with 'tstack doctor --repair' (or pin one: Set-TsSourceDirPersisted '<path>')"
    }
    return $clones[0].Path
}

function Invoke-TsSync([string]$SourceDir) {
    $sync = Join-Path $SourceDir 'scripts\sync-windows.ps1'
    if (Test-Path $sync) {
        & $sync -SourceDir $SourceDir
    } else {
        Write-Warning "$sync not found; Windows-side dotfiles not applied."
    }
}

function Get-TsStateFile {
    Join-Path $env:LOCALAPPDATA 'terminal-stack\rollback-sha'
}

function Update-TerminalStack {
    [CmdletBinding()]
    param([string]$SourceDir)

    $profileHashBefore = if (Test-Path -LiteralPath $PROFILE) {
        (Get-FileHash -LiteralPath $PROFILE -Algorithm SHA256).Hash
    } else { '' }

    $SourceDir = Resolve-TsSourceDir $SourceDir
    if (-not $SourceDir) { return }

    # Preflight: a resolved dir that isn't a terminal-stack clone means a stale /
    # moved install. Nudge toward tstack doctor rather than pulling the wrong repo.
    $remote = & git -C $SourceDir config --get remote.origin.url 2>$null
    if ($remote -notmatch 'terminal-stack') {
        Write-Warning "tstack update: '$SourceDir' doesn't look like a terminal-stack clone. Run 'tstack doctor' to check."
    }
    Write-Host "==> clone: $SourceDir"
    $dirty = @(& git -C $SourceDir status --porcelain 2>$null)
    if ($dirty.Count) {
        Write-Warning 'tstack update: runtime clone has uncommitted changes; refusing to fetch, pull, or sync.'
        $dirty | ForEach-Object { Write-Host "  $_" }
        Write-Host '  Make changes in the workspace dev clone, commit them, then rerun tstack update.'
        return
    }
    # Location notice only — moving is tstack doctor's job, never a side effect of updating.
    $canon = Get-TsCanonicalCloneDir
    if ($SourceDir.TrimEnd('\') -ne $canon.TrimEnd('\') -and -not (Test-TsDevClone $SourceDir)) {
        Write-Host "tstack update: note — clone is at a legacy location; run 'tstack doctor --repair' to move it to $canon."
    }
    # A second clone is not just untidy: whichever one tstack update picks is the one
    # that overwrites $PROFILE, so an unnoticed leftover silently reinstates an
    # old profile. Offer to pin the choice once rather than re-deciding it on
    # every run. Skipped when pinned, non-interactive, or already canonical
    # (canonical needs no pin — consolidate via tstack doctor instead).
    if (-not $env:TERMINAL_STACK_DIR -and $SourceDir.TrimEnd('\') -ne $canon.TrimEnd('\')) {
        $all = Get-TsClones
        if ($all.Count -gt 1 -and -not [Console]::IsInputRedirected) {
            $a = Read-Host "Pin '$SourceDir' as this machine's clone and stop asking? [y/N]"
            if ($a -match '^(y|Y|yes|YES)$') { Set-TsSourceDirPersisted $SourceDir }
        }
    }

    & git -C $SourceDir fetch --quiet
    if ($LASTEXITCODE -ne 0) { Write-Warning 'git fetch failed; not applying.'; return }

    # '@{u}' must be quoted — pwsh would otherwise parse it as a hashtable.
    $incoming = & git -C $SourceDir log --oneline 'HEAD..@{u}' 2>$null
    if ($incoming) {
        Write-Host '==> incoming changes:'
        $incoming | ForEach-Object { Write-Host "  $_" }
        # Record the rollback point only when something is actually incoming —
        # a no-op re-run must not clobber the last real rollback point.
        $stateFile = Get-TsStateFile
        New-Item -ItemType Directory -Force -Path (Split-Path $stateFile) | Out-Null
        (& git -C $SourceDir rev-parse HEAD) | Set-Content $stateFile
        Write-Host "==> recorded rollback point: $(& git -C $SourceDir rev-parse --short HEAD) (tstack rollback to undo)"
        & git -C $SourceDir pull --ff-only
        if ($LASTEXITCODE -ne 0) { Write-Warning 'git pull failed; not applying.'; return }
    } else {
        Write-Host '==> already up to date'
    }
    # Re-bake the resolved (light/dark) palette from the live OS theme so a
    # `follow`-mode user who toggled Windows appearance gets the new palette on
    # this update. No-op for fixed dark/light; non-fatal if the helper is absent.
    $cfgHelper = Join-Path $SourceDir 'bootstrap\_config.ps1'
    if (Test-Path $cfgHelper) {
        try { . $cfgHelper; Update-TsResolvedTheme } catch { Write-Warning "resolvedTheme refresh skipped: $_" }
    }
    Invoke-TsSync $SourceDir

    # Config files are only half an update: a release that adds a CLI tool is
    # inert until the tool exists. Offer the gap rather than installing behind
    # your back, and skip the question entirely when there is nothing to do or
    # nobody to ask.
    if (Test-Path $cfgHelper) {
        try {
            . $cfgHelper
            $pending = @(Get-TsAppsPending)
            if ($pending.Count) {
                Write-Host "==> $($pending.Count) app(s) from the catalog are not installed:"
                foreach ($p in $pending) { Write-Host ("    {0,-10} {1}" -f $p, (Get-TsAppDesc $p)) }
                if ([Console]::IsInputRedirected) {
                    Write-Host "    Install them with: tstack config apps"
                } else {
                    $a = Read-Host 'Install them now? [y/N]'
                    if ($a -match '^(y|Y|yes|YES)$') {
                        Install-TsApps $pending
                        # Record them, so the selection reflects what is actually here.
                        $cfg = Get-TsConfig
                        $merged = @(@($cfg.apps) + $pending | Where-Object { $_ } | Select-Object -Unique)
                        Save-TsConfig -LeaderChord $cfg.leaderChord -ThemeMode $cfg.themeMode `
                                      -TmuxPrefix $cfg.tmuxPrefix -Apps $merged | Out-Null
                    } else {
                        Write-Host '    Skipped. Run tstack config apps when you want them.'
                    }
                }
            }
        } catch { Write-Warning "app check skipped: $_" }
    }

    # A WezTerm upgrade is not a stack update, but tstack update is the moment you are
    # already thinking about being current — and neither channel ever moves on its
    # own. Silent unless there is genuinely something newer on the channel you are
    # already on; silent too when WezTerm is absent, hand-installed, or offline.
    if (Test-Path $cfgHelper) {
        try {
            . $cfgHelper
            $wezNew = Get-TsWezUpdateAvailable
            if ($wezNew) {
                Write-Host "==> WezTerm: $wezNew"
                if ([Console]::IsInputRedirected) {
                    Write-Host '    Upgrade it with: tstack config wezterm upgrade'
                } else {
                    $a = Read-Host 'Upgrade WezTerm now? [y/N]'
                    if ($a -match '^(y|Y|yes|YES)$') { Update-TsWezterm }
                    else { Write-Host "    Skipped. 'tstack config wezterm' for the details, 'tstack config wezterm upgrade' to do it." }
                }
            }
        } catch { Write-Warning "WezTerm check skipped: $_" }
    }

    # The tts daemon keeps running its pre-pull code. Like the mux server it is
    # never auto-restarted (it may be mid-announcement or holding a duck) —
    # nudge instead, same philosophy as tstack mux restart.
    if (Test-Path $cfgHelper) {
        try {
            . $cfgHelper
            $ttsCfg = Get-CcTtsConfig
            if ($ttsCfg -and $ttsCfg.daemon -and $ttsCfg.daemon.enabled) {
                $port = if ($ttsCfg.daemon.port) { [int]$ttsCfg.daemon.port } else { 8890 }
                $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/healthz" -TimeoutSec 2 -UseBasicParsing
                $sha = & git -C $SourceDir rev-parse HEAD 2>$null
                if ($sha -and ($r.Content -notmatch [regex]::Escape($sha))) {
                    Write-Host "tstack update: note — the tts daemon is running the previous build; 'tstack config tts daemon restart' when convenient."
                }
            }
        } catch {}
    }
    $profileHashAfter = if (Test-Path -LiteralPath $PROFILE) {
        (Get-FileHash -LiteralPath $PROFILE -Algorithm SHA256).Hash
    } else { '' }
    if ($profileHashBefore -ne $profileHashAfter) {
        Write-Host ''
        Write-Host '==> PowerShell profile changed.'
        Write-Host 'The files on disk are current, but this shell still has the old functions loaded.'
        Write-Host 'Open a new PowerShell tab after this command finishes to activate the update.'
    }
}

# Undo the last tstack update: reset the clone to the recorded pre-update SHA and
# re-apply. Manual fallback (state file missing): README § Updating & rollback.
function Restore-TerminalStack {
    [CmdletBinding()]
    param([string]$SourceDir)

    $SourceDir = Resolve-TsSourceDir $SourceDir
    if (-not $SourceDir) { return }

    $stateFile = Get-TsStateFile
    if (-not (Test-Path $stateFile)) {
        Write-Warning "no recorded rollback point ($stateFile)."
        Write-Warning "Manual procedure: git -C $SourceDir reset --hard <sha>; scripts\sync-windows.ps1"
        return
    }
    $sha = (Get-Content $stateFile -First 1).Trim()
    & git -C $SourceDir rev-parse --verify --quiet "$sha^{commit}" *> $null
    if ($LASTEXITCODE -ne 0) { Write-Warning "recorded SHA $sha not found in $SourceDir."; return }

    # The clone may double as a dev checkout — never reset --hard over real work.
    if (& git -C $SourceDir status --porcelain) {
        Write-Warning "$SourceDir has uncommitted changes; refusing to reset --hard. Commit or stash first."
        return
    }
    Write-Host "==> resetting $SourceDir to $sha (recorded before last tstack update)"
    & git -C $SourceDir reset --hard $sha
    if ($LASTEXITCODE -ne 0) { return }
    Invoke-TsSync $SourceDir
    Write-Host '==> done. run tstack update to return to latest.'
}

# Configure the stack: leader key, theme (dark/light/follow), tmux prefix, apps,
# and the WezTerm mux / startup-restore toggles.
# Bare `tstack config` opens an interactive menu; `tstack config theme follow` etc. set one
# value. Writes %LOCALAPPDATA%\terminal-stack\config.json and re-syncs the Windows
# files. NOTE: in a combined WSL+Windows setup, prefer running `tstack config` from WSL
# (its chezmoi apply is authoritative for the Windows-side files).
function Set-TerminalStackConfig {
    [CmdletBinding()]
    param(
        [Parameter(Position = 0)][string]$Action,
        [Parameter(Position = 1)][string]$Value,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest
    )

    $src = Resolve-TsSourceDir
    if (-not $src) { return }
    $helper = Join-Path $src 'bootstrap\_config.ps1'
    if (-not (Test-Path $helper)) { Write-Warning "$helper not found; cannot configure."; return }
    . $helper

    # Get-TsProp rather than dot access, for the strictness reason above: a config.json
    # written before a key existed makes every one of these a terminating error.
    $c = Get-TsConfig
    $leader = Get-TsProp $c leaderChord 'ctrl-space'
    $theme  = Get-TsProp $c themeMode   'dark'
    $tmux   = Get-TsProp $c tmuxPrefix  'ctrl-b'
    $apps   = @(Get-TsProp $c apps @())
    $ccTts  = Get-TsProp $c ccTts (Get-CcTtsDefaults)
    $headroom = Get-TsAgentSetting headroomEnabled
    $headroomCursor = Get-TsAgentSetting headroomCursorMode
    $caveman = Get-TsAgentSetting cavemanEnabled
    $agentmemory = Get-TsAgentSetting agentmemoryEnabled
    $memoryBackend = Get-TsAgentSetting memoryBackend

    # Re-run the whole questionnaire, not just one answer. `tstack config apps`
    # re-asks the apps question alone; this replays every prompt the installer
    # asks and persists all of it. POSIX twin: run_wizard in bootstrap/ts-config.sh.
    # Runs the questionnaire, installs, and persists; returns the answers so the
    # CALLER can refresh its own variables. A scriptblock invoked with & gets a
    # child scope, so assignments in here would not reach the menu's copies and
    # the menu would keep printing the pre-wizard values.
    $runWizard = {
        $w = Read-TsWizard
        # A prompt that throws leaves $w null or half-filled, and Save-TsConfig would
        # then persist '' over real answers (ValidateSet only catches some of them).
        if (-not $w -or -not $w.Leader -or -not $w.Theme -or -not $w.Headroom) {
            Write-Warning 'tstack config wizard: the questionnaire did not complete — nothing was installed or saved.'
            return $null
        }
        Install-TsTerminals -Selected $w.Terminals
        Install-TsApps @($w.Apps)
        Save-TsConfig -LeaderChord $w.Leader -ThemeMode $w.Theme -TmuxPrefix $tmux -Apps @($w.Apps) -CcTts $ccTts `
            -WeztermMux $w.WezMux -WeztermRestore $w.WezRestore `
            -HeadroomEnabled $w.Headroom -HeadroomCursorMode $w.HeadroomCursor `
            -CavemanEnabled $w.Caveman -AgentmemoryEnabled $w.Agentmemory `
            -MemoryBackend $w.MemoryBackend | Out-Null
        Set-TsMemoryComposeFile $w.MemoryBackend
        Export-CcTtsJson
        Save-TsWorkspaceOverride $w.Workspace
        Invoke-TsSync $src
        Show-TsInstalledApps @($w.Apps)
        Write-Host '==> done.'
        return $w
    }

    $save = {
        param($Tts = $ccTts)
        Save-TsConfig -LeaderChord $leader -ThemeMode $theme -TmuxPrefix $tmux -Apps $apps -CcTts $Tts `
            -HeadroomEnabled $headroom -HeadroomCursorMode $headroomCursor `
            -CavemanEnabled $caveman -AgentmemoryEnabled $agentmemory `
            -MemoryBackend $memoryBackend | Out-Null
        Export-CcTtsJson
        Invoke-TsSync $src
        Write-Host '==> done.'
    }

    $agentsShow = {
        Write-Host 'coding agents (user-global on this computer):'
        Write-Host "  headroom   : $headroom   (Cursor: $headroomCursor)"
        Write-Host "  caveman    : $caveman"
        Write-Host "  agentmemory: $agentmemory   (memory backend: $memoryBackend)"
    }
    $agentsRun = {
        param([string]$Tool, [string]$Verb, [string]$CursorMode = $headroomCursor)
        Invoke-TstackSub -Name 'agents' -Forwarded @($Tool, $Verb, $CursorMode) | Out-Host
        return ($LASTEXITCODE -eq 0)
    }

    switch ($Action) {
        '' {
            while ($true) {
                Write-Host ''
                Write-Host 'terminal-stack config:'
                Write-Host "  leader     : $leader"
                Write-Host "  theme      : $theme   (palette $(Get-TsResolvedTheme $theme))"
                Write-Host "  tmux       : $tmux"
                Write-Host "  apps       : $($apps -join ', ')"
                Write-Host "  cc-tts     : $(if ($ccTts.enabled) { 'on' } else { 'off' })"
                Write-Host "  wezmux     : $(Get-TsWeztermMux)"
                Write-Host "  wezrestore : $(Get-TsWeztermRestore)"
                Write-Host "  wezterm    : $(Get-TsWezChannel)   (tstack config wezterm)"
                Write-Host "  headroom   : $headroom   (Cursor: $headroomCursor)"
                Write-Host "  caveman    : $caveman"
                Write-Host "  agentmemory: $agentmemory"
                Write-Host ''
                Write-Host '  1) leader  2) theme  3) tmux prefix  4) apps  5) re-apply  6) Claude TTS  7) WezTerm mux  8) session restore  9) coding agents  t) WezTerm build  w) re-run wizard  q) quit'
                switch (Read-Host 'Choose') {
                    '1' { $leader = Read-TsLeader; & $save }
                    '2' { $theme  = Read-TsTheme;  & $save }
                    '3' { $t = Read-Host 'tmux prefix chord (e.g. ctrl-a) [ctrl-b]'; $tmux = if ($t) { $t } else { 'ctrl-b' }; & $save }
                    '4' { $apps = @(Read-TsApps); Install-TsApps $apps; Show-TsInstalledApps $apps; & $save }
                    '5' { & $save }
                    '6' {
                        Show-CcTtsConfig
                        switch (Read-Host 'TTS: a) on  b) off  c) test  d) daemon status  e) back') {
                            'a' { $ccTts.enabled = $true; & $save $ccTts }
                            'b' { $ccTts.enabled = $false; & $save $ccTts }
                            'c' { Invoke-TsConfigTts -Sub test -Apply $save }
                            'd' { Show-CcTtsDaemonStatus }
                        }
                    }
                    't' { Show-TsWezStatus }
                    'w' {
                        $w = & $runWizard
                        if ($w) {
                            $leader = $w.Leader; $theme = $w.Theme; $apps = @($w.Apps)
                            $headroom = $w.Headroom; $headroomCursor = $w.HeadroomCursor
                            $caveman = $w.Caveman; $agentmemory = $w.Agentmemory
                        }
                    }
                    '7' { Invoke-TstackSub -Name 'mux' -Forwarded @('status') }
                    '8' { $restore = Read-TsWeztermRestore; Save-TsConfig -WeztermRestore $restore | Out-Null; Invoke-TsSync $src; Write-Host '==> done.' }
                    '9' {
                        & $agentsShow
                        $which = Read-Host 'Agent: headroom, caveman, agentmemory, or Enter to go back'
                        if (-not $which) { continue }
                        if ($which -notin 'headroom','caveman','agentmemory') { Write-Warning "unknown agent tool '$which'"; continue }
                        $verb = Read-Host 'Action: status, on, off, repair, uninstall [status]'
                        if (-not $verb) { $verb = 'status' }
                        $Value = $which; $Rest = @($verb)
                        # Run through the same branch as the noninteractive command below.
                        if (& $agentsRun $which $verb) {
                            if ($verb -eq 'on') { Set-Variable -Name $which -Value 'on' }
                            if ($verb -in 'off','uninstall') { Set-Variable -Name $which -Value 'off' }
                            if ($which -eq 'agentmemory') { $agentmemory = (Get-Variable $which).Value }
                            elseif ($which -eq 'headroom') { $headroom = (Get-Variable $which).Value }
                            elseif ($which -eq 'caveman') { $caveman = (Get-Variable $which).Value }
                            if ($verb -in 'on','off','uninstall') { & $save }
                        }
                    }
                    default { return }
                }
            }
        }
        'show' {
            Write-Host "leader     : $leader"
            Write-Host "theme      : $theme   (palette $(Get-TsResolvedTheme $theme))"
            Write-Host "tmux       : $tmux"
            Write-Host "apps       : $($apps -join ', ')"
            Write-Host "wezmux     : $(Get-TsWeztermMux)   (tstack mux on|off|status)"
            Write-Host "wezrestore : $(Get-TsWeztermRestore)   (tstack config restore on|off)"
            Write-Host "headroom   : $headroom   (Cursor: $headroomCursor)"
            Write-Host "caveman    : $caveman"
            Write-Host "agentmemory: $agentmemory"
        }
        'leader' { if (-not $Value) { Write-Warning 'usage: tstack config leader <chord>'; return }; $leader = $Value; & $save }
        'theme'  { if (-not $Value) { Write-Warning 'usage: tstack config theme <dark|light|follow>'; return }; $theme = $Value; & $save }
        'tmux'   { if (-not $Value) { Write-Warning 'usage: tstack config tmux <chord>'; return }; $tmux = $Value; & $save }
        'apps'   {
            if ($Value) {
                switch ($Value) {
                    'recommended' { $apps = $script:TsAppsRecommended }
                    'all'         { $apps = $script:TsAppsAll }
                    'none'        { $apps = @() }
                    default       { $apps = ($Value -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
                }
            } else { $apps = @(Read-TsApps) }
            Install-TsApps $apps; Show-TsInstalledApps $apps; & $save
        }
        'wezterm' {
            switch ($Value) {
                ''         { Show-TsWezStatus }
                'status'   { Show-TsWezStatus }
                'upgrade'  { Update-TsWezterm }
                'install'  {
                    if ($Rest[0] -notin 'stable', 'nightly') { Write-Warning 'usage: tstack config wezterm install <stable|nightly>'; return }
                    Install-TsWezterm $Rest[0]
                }
                'changes'  {
                    $inst = Get-TsWezInstalled
                    if (-not $inst) { Write-Warning 'WezTerm is not installed, so there is no build to compare against.'; return }
                    $text = Get-TsWezChangesText $inst.Version
                    if (-not $text) { Write-Warning "could not fetch upstream's changelog (offline?)"; return }
                    if (Get-Command glow -ErrorAction SilentlyContinue) {
                        "# WezTerm changes since $($inst.Version)`n`n$text" | & glow -p -
                    } else {
                        "# WezTerm changes since $($inst.Version)`n`n$text" | Out-Host -Paging
                    }
                }
                default    { Write-Warning "tstack config wezterm: unknown '$Value' (status, changes, install <stable|nightly>, upgrade)" }
            }
        }
        'wizard'       { $null = & $runWizard }
        'reconfigure'  { $null = & $runWizard }
        'tts' {
            Invoke-TsConfigTts -Sub $Value -Arg $Rest[0] -Arg2 $Rest[1] -Apply {
                param($Tts)
                $ccTts = $Tts
                & $save $Tts
            }
        }
        # Which memory system runs. ONE slot: AgentMemory and Headroom do the same
        # job, and running both leaves two half-filled stores with no way to know
        # which one holds the answer. POSIX twin: memory_show / memory_set in
        # bootstrap/ts-config.sh -- keep the verbs and the reported facts aligned.
        'memory' {
            $want = if ($Value) { $Value } else { 'status' }
            if ($want -in 'status','show') {
                Write-Host "memory backend: $memoryBackend"
                switch ($memoryBackend) {
                    'agentmemory' { Write-Host '  AgentMemory remembers (3111), Headroom compresses (8787).' }
                    'headroom'    { Write-Host '  Headroom remembers and compresses; AgentMemory is not installed.' }
                    'none'        { Write-Host '  No memory. Headroom still compresses if it is enabled.' }
                }
                Write-Host "  agentmemory wiring: $agentmemory   headroom: $headroom"
                $envFile = Get-TsStackEnvFile 'headroom'
                if (Test-Path -LiteralPath $envFile) {
                    $spec = 'docker-compose.yml'
                    $hit = Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^COMPOSE_FILE=' } | Select-Object -First 1
                    if ($hit) { $spec = $hit -replace '^COMPOSE_FILE=', '' }
                    Write-Host "  headroom COMPOSE_FILE: $spec"
                    # Named rather than silently corrected: a hand-edited COMPOSE_FILE
                    # is somebody trying to do something, and quietly undoing it is
                    # worse than saying the two disagree.
                    if ($spec -ne (Get-TsMemoryComposeSpec $memoryBackend)) {
                        Write-Warning "COMPOSE_FILE does not match the backend - fix: tstack config memory $memoryBackend"
                    }
                }
                return
            }
            if ($want -notin 'agentmemory','headroom','none') {
                Write-Warning 'usage: tstack config memory [agentmemory|headroom|none|status]'
                return
            }
            $before = $memoryBackend
            $memoryBackend = $want
            $agentmemory = if ($want -eq 'agentmemory') { 'on' } else { 'off' }
            & $save
            Set-TsMemoryComposeFile $want
            Write-Host "saved: memoryBackend = $want"

            # The agent wiring is what actually captures, so it moves with the
            # setting rather than waiting for a second command nobody runs.
            if ($want -eq 'agentmemory') {
                if (-not (& $agentsRun agentmemory on)) {
                    Write-Warning 'AgentMemory wiring failed; retry: tstack config agents agentmemory repair'
                }
            } elseif ($before -eq 'agentmemory') {
                & $agentsRun agentmemory off | Out-Null
                Write-Host '  AgentMemory hooks removed from Claude/Codex/Cursor.'
            }

            # Restart rather than print the command: the setting and the running
            # state must not disagree, and a headroom still running the old compose
            # file is exactly the silent mismatch this change exists to remove.
            $python = Get-TstackPython
            $entry  = Join-Path $src 'tstack\main.py'
            if ($python -and (Test-Path -LiteralPath $entry)) {
                Write-Host '  restarting headroom so the change takes effect...'
                & $python $entry services restart headroom | Out-Host
                if ($LASTEXITCODE -ne 0) { Write-Warning 'headroom restart failed - run: tstack services restart headroom' }
            }
        }
        'agents' {
            $agentTool = $Value
            $verb = if ($Rest.Count) { $Rest[0] } else { '' }
            if (-not $agentTool -or $agentTool -eq 'show') { & $agentsShow; return }
            if ($agentTool -notin 'headroom','caveman','agentmemory') {
                Write-Warning 'usage: tstack config agents <headroom|caveman|agentmemory> on|off|status|repair|uninstall'
                return
            }
            if ($agentTool -eq 'headroom' -and $verb -eq 'dashboard') {
                & $agentsRun headroom dashboard | Out-Null
                return
            }
            if ($agentTool -eq 'headroom' -and $verb -eq 'cursor') {
                $mode = if ($Rest.Count -gt 1) { $Rest[1] } else { '' }
                if ($mode -notin 'mcp','byok','off') { Write-Warning 'usage: tstack config agents headroom cursor <mcp|byok|off>'; return }
                $headroomCursor = $mode
                & $save
                if ($headroom -eq 'on') { & $agentsRun headroom repair $mode | Out-Null }
                & $agentsShow
                return
            }
            # AgentMemory is DERIVED from memoryBackend, so turning it on directly
            # while the backend is something else would create a two-memory-system
            # machine -- the combination the wizard is built to make unreachable.
            if ($agentTool -eq 'agentmemory' -and $verb -eq 'on' -and $memoryBackend -ne 'agentmemory') {
                Write-Warning "memoryBackend is '$memoryBackend', so AgentMemory is not this machine's memory system."
                Write-Host   '      Only one runs. To switch:  tstack config memory agentmemory'
                return
            }
            if (-not $verb) { $verb = 'status' }
            if ($verb -notin 'on','off','status','repair','uninstall') {
                Write-Warning "usage: tstack config agents $agentTool on|off|status|repair|uninstall"
                return
            }
            $ok = & $agentsRun $agentTool $verb
            if (-not $ok -and $verb -notin 'off','uninstall') { return }
            if ($verb -eq 'on') {
                if ($agentTool -eq 'headroom') { $headroom = 'on' }
                elseif ($agentTool -eq 'caveman') { $caveman = 'on' }
                else { $agentmemory = 'on' }
                & $save
            } elseif ($verb -in 'off','uninstall') {
                if ($agentTool -eq 'headroom') { $headroom = 'off' }
                elseif ($agentTool -eq 'caveman') { $caveman = 'off' }
                else { $agentmemory = 'off' }
                & $save
            }
        }
        # Reopening the last WezTerm session at startup. Stored on its own like the
        # mux key, so flipping it need not re-state every other choice.
        'restore' {
            if ($Value -notin 'on', 'off') { Write-Warning 'usage: tstack config restore <on|off>'; return }
            Save-TsConfig -WeztermRestore $Value | Out-Null
            Invoke-TsSync $src
            Write-Host '==> done.'
        }
        # Managed Ghostty config. There IS a Ghostty for Windows: noctty
        # (github.com/amanthanvi/noctty), Ghostty's terminal core in a native
        # Win32 app, still shipping release assets under its former name
        # winghostty. POSIX twin: the ghostty_* functions in bootstrap/ts-config.sh
        # — keep the verbs and the reported facts aligned.
        #
        # NOTE for a combined WSL+Windows box: prefer running this from WSL. Its
        # chezmoi apply is authoritative for the Windows-side files, same caveat
        # as the rest of tstack config.
        # Ghostty. One implementation in tstack/ghostty.py, reached the same way
        # mux does: this branch was ~90 lines and carried its own copy of the
        # themeMode -> theme mapping, which had to be kept in agreement with the
        # bash side and both syncs by a test.
        'ghostty' {
            $gArgs = @(@($Value) + @($Rest) | Where-Object { $_ })
            Invoke-TstackSub -Name 'ghostty' -Forwarded $gArgs
        }
        # The mux has its own verbs (kill/restart/reset), so tstack config just hands off.
        'mux'    {
            $muxArgs = @(@($Value) + @($Rest) | Where-Object { $_ })
            Invoke-TstackSub -Name 'mux' -Forwarded $muxArgs
        }
        default { Write-Warning "tstack config: unknown command '$Action' (show, leader, theme, tmux, apps, tts, mux, restore, ghostty, memory, agents, wezterm, wizard)" }
    }
}

# Probe known clone locations for one that actually contains the repo — used so
# the doctor still runs when $env:TERMINAL_STACK_DIR / the default path is wrong.
# Same priority as Get-TsCloneCandidates; dev clones skipped unless pinned.
function Find-TsAnyClone {
    foreach ($d in (Get-TsCloneCandidates)) {
        if (-not $d) { continue }
        if ((Test-TsDevClone $d) -and $d -ne $env:TERMINAL_STACK_DIR) { continue }
        if (Test-Path (Join-Path $d 'bootstrap\_cleanup.ps1')) { return $d }
    }
    return $null
}

# Persist $env:TERMINAL_STACK_DIR to profile.local.ps1 so tstack update / tstack config
# find a clone that isn't at the default %USERPROFILE%\terminal-stack.
function Set-TsSourceDirPersisted([string]$SourceDir) {
    $localProfile = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\profile.local.ps1'
    New-Item -ItemType Directory -Force -Path (Split-Path $localProfile) | Out-Null
    $line = "`$env:TERMINAL_STACK_DIR = '$SourceDir'"
    if ((Test-Path $localProfile) -and (Get-Content $localProfile | Where-Object { $_ -match '^\s*\$env:TERMINAL_STACK_DIR\s*=' })) {
        (Get-Content $localProfile) -replace '^\s*\$env:TERMINAL_STACK_DIR\s*=.*', $line | Set-Content $localProfile
    } else {
        Add-Content -Path $localProfile -Value $line
    }
    $env:TERMINAL_STACK_DIR = $SourceDir
    Write-Host "==> persisted `$env:TERMINAL_STACK_DIR = $SourceDir to $localProfile"
}


# tstack — the single entry point. Routing lives in tstack/commands.conf in the
# clone, so this function never grows a branch per subcommand: adding one, or
# porting one to Python, is a table edit and nothing else. Twin: tstack() in
# dot_zshrc.
#
# Help is rendered by tstack/cli.py and never here. Three implementations of one
# help text is precisely the problem this port exists to remove, and Python is
# already a hard requirement of this stack (scripts/sync-windows.ps1 throws
# without it).

# Python 3.10+, matching the bar bootstrap/tts-daemon already sets. `py -3` is
# tried first on purpose: a bare `python` on a fresh Windows box is often the
# Microsoft Store stub, which opens a store page instead of running anything.
function Get-TstackPython {
    foreach ($candidate in @(
            @{ Exe = 'py';     Arguments = @('-3') },
            @{ Exe = 'python'; Arguments = @() },
            @{ Exe = 'python3'; Arguments = @() })) {
        $found = Get-Command $candidate.Exe -CommandType Application `
            -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $found) { continue }
        try {
            $reported = & $found.Source @($candidate.Arguments + @(
                    '-c', 'import sys; print("%d.%d" % sys.version_info[:2])'))
            if ($reported -and ([version]$reported.Trim() -ge [version]'3.10')) {
                return [pscustomobject]@{ Exe = $found.Source; Arguments = $candidate.Arguments }
            }
        } catch {}
    }
    return $null
}

# One parsed row of tstack/commands.conf, or $null. Column 2 is the Windows
# implementation token; see the conf file header for the vocabulary.
function Get-TstackImpl([string]$SourceDir, [string]$Name) {
    $conf = Join-Path $SourceDir 'tstack\commands.conf'
    if (-not (Test-Path -LiteralPath $conf)) { return $null }
    foreach ($row in Get-Content -LiteralPath $conf) {
        $trimmed = $row.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $fields = $trimmed -split '\s+', 4
        if ($fields.Count -lt 4) { continue }
        if ($fields[0] -eq $Name) { return $fields[2] }
    }
    return $null
}

function Get-TstackNames([string]$SourceDir) {
    $conf = Join-Path $SourceDir 'tstack\commands.conf'
    if (-not (Test-Path -LiteralPath $conf)) { return @() }
    $out = foreach ($row in Get-Content -LiteralPath $conf) {
        $trimmed = $row.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) { continue }
        $fields = $trimmed -split '\s+', 4
        if ($fields.Count -ge 4) { $fields[0] }
    }
    return @($out)
}

# No param block on purpose. A [CmdletBinding()] parameter set would try to bind
# `--version` and `-h` as PowerShell parameter names before tstack ever saw them.
# Run a PORTED subcommand from inside another $PROFILE function. The shim
# (Invoke-Tstack) is for what the user types; this is for one stack function
# handing off to another, which used to be a direct call to a pwsh twin.
function Invoke-TstackSub {
    param([string]$Name, [string[]]$Forwarded = @())
    $src = Resolve-TsSourceDir
    if (-not $src) { Write-Warning "tstack ${Name}: no terminal-stack clone found."; return }
    $python = Get-TstackPython
    if (-not $python) { Write-Warning 'tstack: python3 not found on PATH.'; return }
    & $python (Join-Path $src 'tstack\main.py') $Name @Forwarded
}

function Invoke-Tstack {
    $source = Resolve-TsSourceDir
    if (-not $source) { return }
    $passed = @($args)

    $wantsMeta = ($passed.Count -eq 0) -or
        ($passed[0] -in @('-h', '--help', 'help', '--version', '-V'))

    if ($wantsMeta) {
        $python = Get-TstackPython
        if (-not $python) {
            Write-Warning 'tstack: Python 3.10+ not found; it is required. Install it, then rerun.'
            return
        }
        $forwarded = @(if ($passed.Count -eq 0) { '--help' } else { $passed })
        Invoke-TstackPython -Python $python -SourceDir $source -Forwarded $forwarded
        return
    }

    $name = $passed[0]
    # The @() is load-bearing. An `if` used as an expression unrolls a
    # single-element result to a scalar, and splatting a scalar string that
    # starts with '-' re-parses it as a parameter token: `tstack services -h`
    # arrived at the services implementation as two arguments, '-' and 'h', and
    # reported "no stack named 'h'". With no tail it splatted one empty string.
    # Both parse cleanly and both are silent. See docs/powershell-quirks.md.
    $tail = @(if ($passed.Count -gt 1) { $passed[1..($passed.Count - 1)] } else { @() })
    $impl = Get-TstackImpl -SourceDir $source -Name $name

    if (-not $impl) {
        Write-Warning "tstack: unknown command '$name'"
        Write-Host "  try: $((Get-TstackNames -SourceDir $source) -join ', ')"
        return
    }

    if ($impl -eq '-') {
        Write-Warning "tstack ${name}: not available on Windows."
        return
    }

    if ($impl -eq 'python') {
        $python = Get-TstackPython
        if (-not $python) {
            Write-Warning "tstack ${name}: Python 3.10+ not found; it is required."
            return
        }
        Invoke-TstackPython -Python $python -SourceDir $source -Forwarded (@($name) + $tail)
        return
    }

    if ($impl.StartsWith('@')) {
        # Runs in THIS session on purpose: update offers to reload the profile and
        # rollback prompts, neither of which a child process can do for its parent.
        & $impl.Substring(1) @tail
        return
    }

    $script = Join-Path $source ($impl -replace '/', '\')
    if (-not (Test-Path -LiteralPath $script)) {
        Write-Warning "tstack ${name}: $script not found; run 'tstack update'."
        return
    }
    if ($impl.EndsWith('.ps1')) {
        & $script @tail
    } else {
        Write-Warning "tstack ${name}: '$impl' is not runnable on Windows."
    }
}

# TERMINAL_STACK_DIR is set for the child only, then restored. Leaving it set
# would turn a one-shot resolution into a session-wide pin, which is exactly the
# state Resolve-TsSourceDir has to warn about elsewhere.
function Invoke-TstackPython($Python, [string]$SourceDir, [string[]]$Forwarded) {
    $previous = $env:TERMINAL_STACK_DIR
    try {
        $env:TERMINAL_STACK_DIR = $SourceDir
        $entry = Join-Path $SourceDir 'tstack\main.py'
        & $Python.Exe @($Python.Arguments + @($entry) + $Forwarded)
    } finally {
        if ($null -eq $previous) {
            Remove-Item Env:\TERMINAL_STACK_DIR -ErrorAction SilentlyContinue
        } else {
            $env:TERMINAL_STACK_DIR = $previous
        }
    }
}

Set-Alias -Name tstack -Value Invoke-Tstack

# Completion reads the same table. Cached per session: Resolve-TsSourceDir shells
# out to git, which is far too slow to run on every TAB.
$script:TstackSubcommands = @()
Register-ArgumentCompleter -Native -CommandName tstack -ScriptBlock {
    param($wordToComplete, $commandAst, $cursorPosition)
    if (-not $script:TstackSubcommands -or $script:TstackSubcommands.Count -eq 0) {
        $resolved = Resolve-TsSourceDir 3>$null 4>$null
        if (-not $resolved) { return }
        $script:TstackSubcommands = Get-TstackNames -SourceDir $resolved
    }
    $script:TstackSubcommands |
        Where-Object { $_ -like "$wordToComplete*" } |
        ForEach-Object {
            [System.Management.Automation.CompletionResult]::new(
                $_, $_, 'ParameterValue', $_)
        }
}

# ---- terminal-stack-update-end ----

# ---- claude-code-start ----
function ccnotify {
    param([string]$Action)
    $f = "$HOME\.claude\.toast-notify"
    switch ($Action) {
        'on'  { New-Item $f -ItemType File -Force | Out-Null; Write-Host 'CC toast: ON' }
        'off' { Remove-Item $f -ErrorAction SilentlyContinue; Write-Host 'CC toast: OFF' }
        default {
            if (Test-Path $f) { Write-Host 'CC toast: ON  (ccnotify off to disable)' }
            else              { Write-Host 'CC toast: OFF (ccnotify on  to enable)'  }
        }
    }
}

# The instant mute -- same sentinel the tray icon and the global hotkey use, so all
# three agree and it survives the daemon dying. Writes no config store, runs no apply.
function ccmute {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest)
    $exe = Join-Path $env:LOCALAPPDATA 'terminal-stack\tts-daemon\terminal-stack-tts.exe'
    if (-not (Test-Path -LiteralPath $exe)) {
        Write-Warning "terminal-stack-tts.exe not found at $exe (tstack config tts daemon install)"
        return
    }
    & $exe mute @Rest | Out-Host
}

function cctts {
    param([string]$Action, [string]$Extra)
    switch ($Action) {
        'on'   { tstack config tts on }
        'off'  { tstack config tts off }
        'test' { tstack config tts test }
        'show' { tstack config tts show }
        default {
            # The effective value, not the mirror: local.json is deep-merged over
            # config.json and wins, so the mirror can say ON while the machine is silent.
            $en = $false
            foreach ($f in @((Join-Path $HOME '.claude\tts\local.json'),
                             (Join-Path $HOME '.claude\tts\config.json'))) {
                if (-not (Test-Path -LiteralPath $f)) { continue }
                try {
                    $j = Get-Content $f -Raw | ConvertFrom-Json
                    $p = $j.PSObject.Properties['enabled']
                    if ($p) { $en = [bool]$p.Value; break }
                } catch {}
            }
            if ($en) { Write-Host 'CC TTS: ON  (cctts off to disable; tstack config tts for settings)' }
            else     { Write-Host 'CC TTS: OFF (cctts on to enable)' }
            ccmute status
        }
    }
}
# ---- claude-code-end ----

# ---- wzr-start ----
# wzr — WezTerm key reference. Now a thin alias into `doc` (docs/kb/wezterm/*).
# `wzr` browses the WezTerm topics; `wzr panes` opens that one.
function wzr { param([string]$Topic) if ($Topic) { doc "wezterm/$Topic" } else { doc wezterm } }
# ---- wzr-end ----

# ---- editor-launch-start ----
# npp [files...] — open file(s) in Notepad++ (like `ws`, but launches an editor).
# Resolve the exe lazily and invoke with the call operator `&` (the install path
# has spaces, so it must be invoked, not run as a bare command). GUI app, so `&`
# returns to the prompt immediately rather than blocking.
function npp {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Paths)
    $exe = (Get-Command notepad++ -ErrorAction SilentlyContinue).Source
    if (-not $exe) {
        foreach ($c in @("$env:ProgramFiles\Notepad++\notepad++.exe",
                         "${env:ProgramFiles(x86)}\Notepad++\notepad++.exe")) {
            if (Test-Path $c) { $exe = $c; break }
        }
    }
    if (-not $exe) {
        Write-Warning 'npp: Notepad++ not found — install it or add notepad++.exe to PATH'
        return
    }
    if (-not $Paths) { & $exe; return }
    # Resolve each arg against the current dir so relative paths open correctly;
    # a not-yet-existing path is passed through (Notepad++ opens a new buffer).
    # @(...) forces an array even for one path — foreach with a single output
    # collapses $resolved to a bare string, and `& $exe @resolved` on a string
    # splats its individual CHARACTERS as separate arguments (PowerShell splat
    # gotcha), which silently truncated every single-file open to its first
    # character before this was caught.
    $resolved = @(foreach ($p in $Paths) {
        $full = Resolve-Path -LiteralPath $p -ErrorAction SilentlyContinue
        if     ($full)                                 { $full.Path }
        elseif ([System.IO.Path]::IsPathRooted($p))    { $p }
        else                                           { Join-Path (Get-Location).Path $p }
    })
    & $exe @resolved
}

# pm [files...] — open file(s) in PrettyMark (like `npp`, but for PrettyMark's md viewer).
function pm {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Paths)
    $exe = (Get-Command prettymark -ErrorAction SilentlyContinue).Source
    if (-not $exe) {
        $c = "$env:ProgramFiles\PrettyMark\PrettyMark.exe"
        if (Test-Path $c) { $exe = $c }
    }
    if (-not $exe) {
        Write-Warning 'pm: PrettyMark not found — install it or add PrettyMark.exe to PATH'
        return
    }
    if (-not $Paths) { & $exe; return }
    # @(...) forces an array even for one path — see the comment on npp above.
    $resolved = @(foreach ($p in $Paths) {
        $full = Resolve-Path -LiteralPath $p -ErrorAction SilentlyContinue
        if     ($full)                               { $full.Path }
        elseif ([System.IO.Path]::IsPathRooted($p))  { $p }
        else                                          { Join-Path (Get-Location).Path $p }
    })
    & $exe @resolved
}

# pm's Paths only makes sense as markdown files — restrict Tab-completion to
# .md files (and directories, so subfolders stay navigable). No key-rebinding
# needed: Tab already cycles whatever a completer returns, so `pm ` + Tab
# cycling every .md file and `pm ins` + Tab narrowing to INSTALL.md are the
# same completer, just with an empty vs. partial $wordToComplete.
Register-ArgumentCompleter -CommandName pm -ParameterName Paths -ScriptBlock {
    param($commandName, $parameterName, $wordToComplete, $commandAst, $fakeBoundParameters)
    # A trailing separator means "list this directory's contents" — Split-Path
    # would otherwise treat the directory name itself as the leaf-in-progress
    # and match the directory, not descend into it.
    if ($wordToComplete -and $wordToComplete[-1] -in '\', '/') {
        $dir = $wordToComplete; $leaf = ''
    } elseif ($wordToComplete) {
        $dir = Split-Path $wordToComplete -Parent
        $leaf = Split-Path $wordToComplete -Leaf
    } else {
        $dir = ''; $leaf = ''
    }
    $searchDir = if ($dir) { $dir } else { '.' }
    Get-ChildItem -LiteralPath $searchDir -ErrorAction SilentlyContinue |
        Where-Object { $_.PSIsContainer -or $_.Extension -eq '.md' } |
        Where-Object { $_.Name -like "$leaf*" } |
        Sort-Object { -not $_.PSIsContainer }, Name |
        ForEach-Object {
            $rel = if ($dir) { Join-Path $dir $_.Name } else { $_.Name }
            if ($_.PSIsContainer) { $rel += '\' }
            $text = if ($rel -match "[\s']") { "'$($rel -replace "'", "''")'" } else { $rel }
            [System.Management.Automation.CompletionResult]::new($text, $_.Name, 'ParameterValue', $rel)
        }
}

# c [folder] — open folder in Cursor with the classic UI (like `npp`, but for Cursor).
function c {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Paths)
    $exe = (Get-Command cursor -ErrorAction SilentlyContinue).Source
    if (-not $exe) {
        Write-Warning 'c: cursor CLI not found on PATH — install Cursor and enable its shell command'
        return
    }
    if (-not $Paths) { $Paths = @('.') }
    & $exe @Paths --classic
}
# ---- editor-launch-end ----

# ---- doc-start ----
# `doc` — personal markdown knowledge base. Topics live in <clone>/docs/kb
# (tracked) + ~/.doc.local (untracked personal layer); rendered by glow, bat
# fallback. On Windows, sync-windows.ps1 also mirrors docs/kb to
# %LOCALAPPDATA%\terminal-stack\docs\kb (read fallback; edit/sync use the clone).
# See docs/kb/_index.md. (`ref`/`wzr` are separate for now.)
function Get-DocRoot {
    # Overrides, then the clone candidates (canonical first, dev clones skipped
    # unless pinned), then the read-only %LOCALAPPDATA% mirror LAST — note the
    # mirror (…\terminal-stack\docs\kb) is distinct from the canonical clone's kb
    # (…\terminal-stack\stack\docs\kb).
    $cands = @()
    if ($env:DOC_ROOT) { $cands += $env:DOC_ROOT }
    foreach ($d in (Get-TsCloneCandidates)) {
        if ((Test-TsDevClone $d) -and $d -ne $env:TERMINAL_STACK_DIR) { continue }
        $cands += (Join-Path $d 'docs\kb')
    }
    if ($env:LOCALAPPDATA) { $cands += (Join-Path $env:LOCALAPPDATA 'terminal-stack\docs\kb') }
    foreach ($c in $cands) { if ($c -and (Test-Path -LiteralPath $c -PathType Container)) { return (Resolve-Path -LiteralPath $c).Path } }
    return $null
}
function Get-DocRepo {
    $src = Resolve-TsSourceDir
    if (-not $src) { return $null }
    $kb = Join-Path $src 'docs\kb'
    if (Test-Path -LiteralPath $kb -PathType Container) { return (Resolve-Path -LiteralPath $src).Path }
    return $null
}
function Get-DocLocal { if ($env:DOC_LOCAL) { $env:DOC_LOCAL } else { Join-Path $env:USERPROFILE '.doc.local' } }

# Rendering style: the repo ships glamour style JSONs in docs/kb/_style (they
# ride the same mirror sync as the topics), so glow renders identically on
# every platform/build. Theme follows the saved resolvedTheme; override with
# $env:DOC_STYLE (dark | light | path\to\style.json).
function Get-DocStyle {
    $theme = $env:DOC_STYLE
    if ($theme -and (Test-Path -LiteralPath $theme)) { return $theme }
    if ($theme -notin @('dark', 'light')) {
        $theme = 'dark'
        $cfg = Join-Path $env:LOCALAPPDATA 'terminal-stack\config.json'
        if (Test-Path -LiteralPath $cfg) {
            try {
                $j = Get-Content -LiteralPath $cfg -Raw | ConvertFrom-Json
                if ($j.resolvedTheme -in @('dark', 'light')) { $theme = $j.resolvedTheme }
            } catch {}
        }
    }
    $root = Get-DocRoot
    if ($root) {
        $f = Join-Path $root "_style\$theme.json"
        if (Test-Path -LiteralPath $f) { return $f }
    }
    return $theme
}
# Reading width: terminal width minus a hair, capped for readability.
function Get-DocWidth {
    $w = 100
    try { $w = $Host.UI.RawUI.WindowSize.Width } catch {}
    if (-not $w -or $w -lt 1) { $w = 100 }
    $w -= 2
    if ($w -gt 100) { $w = 100 }
    if ($w -lt 40)  { $w = 40 }
    return $w
}

function Get-DocIndex([string]$Os = 'windows') {
    $roots = [ordered]@{}
    $r = Get-DocRoot; if ($r) { $roots[$r] = '' }
    $l = Get-DocLocal; if (Test-Path -LiteralPath $l) { $roots[(Resolve-Path -LiteralPath $l).Path] = ' [local]' }
    $subs = if ($Os -eq 'all') { $null } else { @('common', 'wezterm', $Os) }
    foreach ($root in $roots.Keys) {
        $tag = $roots[$root]
        $files = if ($subs) {
            @(foreach ($s in $subs) { $d = Join-Path $root $s; if (Test-Path -LiteralPath $d) { Get-ChildItem -LiteralPath $d -Recurse -File -Filter *.md } }) +
            @(Get-ChildItem -LiteralPath $root -File -Filter *.md)
        } else { Get-ChildItem -LiteralPath $root -Recurse -File -Filter *.md }
        foreach ($f in $files) {
            $rel = ($f.FullName.Substring($root.Length).TrimStart('\', '/') -replace '\.md$', '') -replace '\\', '/'
            [pscustomobject]@{ Label = "$rel$tag"; Path = $f.FullName }
        }
    }
}

function Invoke-DocView([string]$path) {
    if (-not (Test-Path -LiteralPath $path)) { Write-Warning "doc: not found: $path"; return }
    # Render at an explicit width + shipped style, page with less when available
    # (Git for Windows ships less; search with /, q quits, short topics print
    # straight through thanks to -F).
    $glow = Get-Command glow -EA SilentlyContinue
    $less = Get-Command less -EA SilentlyContinue
    if ($glow -and $less) { & glow -s (Get-DocStyle) -w (Get-DocWidth) $path | & $less -RF }
    elseif ($glow)        { & glow -p $path }
    elseif (Get-Command bat -EA SilentlyContinue) { & bat --language=markdown --paging=always $path }
    else {
        try { Get-Content -LiteralPath $path | Out-Host -Paging }
        catch { Get-Content -LiteralPath $path }
    }
}

function Invoke-DocOpen([string]$query, [string]$os) {
    $m = @(Get-DocIndex 'all' | Where-Object { $_.Label -like "*$query*" })
    if ($m.Count -eq 0) {
        if (Get-Command fzf -EA SilentlyContinue) { Invoke-DocFinder $os $query }   # no exact hit -> fuzzy finder
        else { Write-Warning "doc: no topic matching '$query' (try: doc ls)" }
        return
    }
    # If every match is the same topic (tracked + its [local] twin), open the [local] one.
    $bases = $m | Group-Object { $_.Label -replace ' \[local\]$', '' }
    if ($bases.Count -eq 1) {
        $pick = ($m | Where-Object { $_.Label -match '\[local\]$' } | Select-Object -First 1)
        if (-not $pick) { $pick = $m[0] }
        Invoke-DocView $pick.Path; return
    }
    if (Get-Command fzf -EA SilentlyContinue) { Invoke-DocFinder $os $query }
    else { Write-Host "Multiple matches for '$query':"; $m | ForEach-Object { "  $($_.Label)" } }
}

function Invoke-DocFinder([string]$os, [string]$query) {
    if (-not (Get-Command fzf -EA SilentlyContinue)) { Write-Warning 'doc: fzf not installed'; return }
    $idx = Get-DocIndex $os | Sort-Object Label
    if (-not $idx) { Write-Warning 'doc: no topics found'; return }
    # Preview runs through cmd.exe on Windows, so the width var is %…% syntax;
    # fzf exports FZF_PREVIEW_COLUMNS to the preview process.
    $prev = if (Get-Command glow -EA SilentlyContinue) {
        "glow -s `"$(Get-DocStyle)`" -w %FZF_PREVIEW_COLUMNS% {2}"
    } else { 'bat --color=always --style=plain {2}' }
    $ed = if ($env:EDITOR) { $env:EDITOR } elseif (Get-Command micro -EA SilentlyContinue) { 'micro' } else { 'notepad' }
    $sel = ($idx | ForEach-Object { "$($_.Label)`t$($_.Path)" }) |
        fzf --delimiter="`t" --with-nth=1 --query=$query --border --prompt='doc> ' `
            --preview=$prev --preview-window='right,60%,wrap,border-left' `
            --bind='ctrl-u:preview-half-page-up,ctrl-d:preview-half-page-down,ctrl-/:toggle-preview' `
            --bind="alt-e:execute($ed {2})" `
            --header='enter=open · ctrl-u/d=scroll preview · ctrl-/=toggle · alt-e=edit'
    if ($sel) { Invoke-DocView (($sel -split "`t")[-1]) }
}

# Find an individual command across all docs and drop it on the prompt to run.
function Invoke-DocCmd([string]$query) {
    if (-not (Get-Command fzf -EA SilentlyContinue)) { Write-Warning 'doc: fzf not installed'; return }
    $rows = foreach ($f in (Get-DocIndex 'all')) {
        $n = 0; $infence = $false
        foreach ($line in (Get-Content -LiteralPath $f.Path)) {
            $n++
            if ($line -match '^\s*```') { $infence = -not $infence; continue }
            if ($infence) { $t = $line.Trim(); if ($t -and $t -notmatch '^#') { "$t`t$($f.Path)`t$n" } }
        }
    }
    if (-not $rows) { Write-Warning 'doc: no commands found'; return }
    $cprev = if (Get-Command bat -EA SilentlyContinue) {
        'bat --color=always --highlight-line {3} {2}'
    } else { 'type {2}' }   # cmd builtin — no highlight, but never breaks without bat
    $sel = $rows | fzf --delimiter="`t" --with-nth=1 --query=$query --border --prompt='cmd> ' `
        --preview=$cprev --preview-window='right,60%,wrap,border-left' `
        --bind='ctrl-u:preview-half-page-up,ctrl-d:preview-half-page-down,ctrl-/:toggle-preview' `
        --header='enter = put command on your prompt · ctrl-u/d=scroll preview'
    if ($sel) { [Microsoft.PowerShell.PSConsoleReadLine]::Insert((($sel -split "`t")[0])) }
}

function Invoke-DocGrep([string]$pat) {
    if (-not $pat) { Write-Host 'usage: doc -g <pattern>'; return }
    $files = @((Get-DocIndex 'all').Path)
    if (-not $files) { Write-Warning 'doc: no docs'; return }
    $out = if (Get-Command rg -EA SilentlyContinue) { & rg --line-number --heading --color=always $pat @files }
           else { Select-String -Path $files -Pattern $pat | ForEach-Object { "$($_.Filename):$($_.LineNumber): $($_.Line.Trim())" } }
    if (-not $out) { return }
    # Page long results (less ships with Git for Windows); plain output otherwise.
    $less = Get-Command less -EA SilentlyContinue
    if ($less) { $out | & $less -RF } else { $out }
}

function Invoke-DocEdit([string]$mode, [string]$arg, [string]$os) {
    $editor = if ($env:EDITOR) { $env:EDITOR } elseif (Get-Command micro -EA SilentlyContinue) { 'micro' } else { 'notepad' }
    # Edits belong in the clone (or ~/.doc.local) — never the %LOCALAPPDATA%
    # mirror, which the next sync overwrites.
    $repo = Get-DocRepo
    $root = if ($repo) { Join-Path $repo 'docs\kb' } else { Get-DocRoot }
    $mirror = Join-Path $env:LOCALAPPDATA 'terminal-stack\docs\kb'
    if ($mode -eq 'new') {
        if (-not $arg) { Write-Host 'usage: doc new <os>/<name>   e.g. doc new linux/foo'; return }
        if ($root -like "$mirror*") {
            Write-Warning 'doc new: only the read-only mirror is available — clone terminal-stack (or set $env:TERMINAL_STACK_DIR) first.'
            return
        }
        $p = Join-Path $root ($arg -replace '/', '\')
        if (-not $p.EndsWith('.md')) { $p += '.md' }
        New-Item -ItemType Directory -Force -Path (Split-Path $p) | Out-Null
        if (-not (Test-Path -LiteralPath $p)) { "# $((Split-Path $p -Leaf) -replace '\.md$','')`n" | Set-Content -LiteralPath $p -Encoding utf8 }
        & $editor $p
    } else {
        $m = @(Get-DocIndex 'all' | Where-Object { $_.Label -like "*$arg*" })
        if ($m.Count -lt 1) { Write-Warning "doc edit: no topic matching '$arg'"; return }
        $target = $m[0].Path
        if ($target -like "$mirror*") {
            $rel = $target.Substring($mirror.Length).TrimStart('\')
            $cand = if ($repo) { Join-Path $repo "docs\kb\$rel" } else { $null }
            if ($cand -and (Test-Path -LiteralPath $cand)) { $target = $cand }
            else { Write-Warning "doc edit: '$arg' resolves to the read-only mirror — clone terminal-stack to edit it."; return }
        }
        & $editor $target
    }
}

function Update-DocChangelog([string]$repo, [string[]]$topics) {
    $cl = Join-Path $repo 'CHANGELOG.md'
    if (-not (Test-Path -LiteralPath $cl)) { return }
    $lines = [System.Collections.Generic.List[string]](Get-Content -LiteralPath $cl)
    $bullet = "- **Docs:** updated $((($topics | ForEach-Object { '`' + $_ + '`' }) -join ', '))."
    $ui = -1
    for ($i = 0; $i -lt $lines.Count; $i++) { if ($lines[$i] -match '^## \[Unreleased\]') { $ui = $i; break } }
    if ($ui -lt 0) { return }
    $docsIdx = -1
    for ($i = $ui + 1; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^## ') { break }
        if ($lines[$i] -match '^### Docs\s*$') { $docsIdx = $i; break }
    }
    if ($docsIdx -ge 0) {
        $ins = $docsIdx + 1
        if ($ins -lt $lines.Count -and $lines[$ins] -eq '') { $ins++ }
        $lines.Insert($ins, $bullet)
    } else {
        $block = @('', '### Docs', '', $bullet)
        for ($k = $block.Count - 1; $k -ge 0; $k--) { $lines.Insert($ui + 1, $block[$k]) }
    }
    Set-Content -LiteralPath $cl -Value $lines -Encoding utf8
}

function Invoke-DocSync([string]$msg) {
    $repo = Get-DocRepo
    if (-not $repo) { Write-Warning 'doc sync: no terminal-stack clone (set $env:TERMINAL_STACK_DIR)'; return }
    Push-Location $repo
    try {
        $changed = & git status --porcelain -- docs/kb
        if (-not $changed) { Write-Host 'doc sync: no changes under docs/kb.'; return }
        Write-Host 'doc sync: changes:'; $changed | ForEach-Object { "  $_" }
        $topics = @($changed | ForEach-Object { (($_ -replace '^...', '') -replace '^docs/kb/', '' -replace '\.md$', '').Trim('"', ' ') } | Sort-Object -Unique)
        Update-DocChangelog $repo $topics
        & git add -- docs/kb CHANGELOG.md
        $prefill = if ($msg) { $msg } else { "docs(kb): update $($topics -join ', ')" }
        & git commit -e -m $prefill
        if ($LASTEXITCODE -ne 0) { Write-Warning 'doc sync: commit aborted; staged changes left in place.'; return }
        $ans = Read-Host 'push to origin? [y/N]'
        if ($ans -match '^(y|yes)$') { & git push } else { Write-Host "doc sync: not pushed (git -C `"$repo`" push)" }
    } finally { Pop-Location }
}

function Write-DocHelp {
    @'
doc                     fuzzy-find a topic (live preview) -> open in less
doc <topic>             open a topic directly (e.g. doc veracrypt, doc ssh-keys)
doc -g <pattern>        grep across every topic (paged)
doc cmd [pattern]       find a command and drop it on your prompt
doc tui [local]         glow's tree browser (tracked kb; 'local' = ~/.doc.local)
doc edit <topic>        edit a topic   |   doc new <os>/<name>   scaffold one
doc ls                  list topics (this OS + common + local)
doc --os <linux|macos|windows> ...    browse another OS
doc sync [msg]          commit doc edits back to the repo (+ changelog, confirm push)

picker keys: ctrl-u/ctrl-d scroll preview · ctrl-/ toggle preview · alt-e edit
reader keys: j/k or arrows scroll · /pattern searches · q quits
style: docs/kb/_style/<dark|light>.json follows your theme ($env:DOC_STYLE overrides)
'@
}

function doc {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)
    $os = 'windows'; $rest = @()
    if ($Arguments) {
        for ($i = 0; $i -lt $Arguments.Count; $i++) {
            if ($Arguments[$i] -eq '--os' -and $i + 1 -lt $Arguments.Count) { $os = $Arguments[$i + 1]; $i++ }
            else { $rest += $Arguments[$i] }
        }
    }
    $cmd = if ($rest.Count) { $rest[0] } else { '' }
    $tail = if ($rest.Count -gt 1) { ($rest[1..($rest.Count - 1)] -join ' ') } else { '' }
    if (-not (Get-DocRoot)) { Write-Warning "doc: can't find docs/kb (set `$env:TERMINAL_STACK_DIR or `$env:DOC_ROOT)"; return }
    switch -Regex ($cmd) {
        '^$'            { Invoke-DocFinder $os ''; break }
        '^(find)$'      { Invoke-DocFinder $os $tail; break }
        '^(-g|grep)$'   { Invoke-DocGrep $tail; break }
        '^(cmd|c)$'     { Invoke-DocCmd $tail; break }
        '^(tui)$'       {
            if (-not (Get-Command glow -EA SilentlyContinue)) { Write-Warning 'doc tui needs glow (winget install charmbracelet.glow)' }
            elseif ($tail -eq 'local') {
                $l = Get-DocLocal
                if (Test-Path -LiteralPath $l) { & glow $l } else { Write-Warning "doc tui local: $l does not exist" }
            }
            else { & glow (Get-DocRoot) }
            break
        }
        '^(ls|list)$'   { Get-DocIndex $os | Sort-Object Label | ForEach-Object { $_.Label }; break }
        '^(edit|new)$'  { Invoke-DocEdit $cmd $tail $os; break }
        '^(sync)$'      { Invoke-DocSync $tail; break }
        '^(-h|--help|help)$' { Write-DocHelp; break }
        default         { Invoke-DocOpen $cmd $os; break }
    }
}
# ---- doc-end ----

# ---- clipboard-start ----
# ccat — bat without paging (we deliberately don't shadow `cat`/Get-Content).
function ccat {
    if (-not (Get-Command bat -ErrorAction SilentlyContinue)) {
        Write-Warning 'ccat: bat not found — install it or use Get-Content'
        return
    }
    & bat --paging=never @args
}

# clipcopy — pipe input to the clipboard; catclip — a file's contents.
function clipcopy { $input | Set-Clipboard }
function catclip {
    param([Parameter(Mandatory)][string]$Path)
    Get-Content -LiteralPath $Path -Raw | Set-Clipboard
}

# hgrep — search PowerShell (PSReadLine) command history.
function hgrep {
    param([Parameter(ValueFromRemainingArguments)][string[]]$Pattern)
    if (-not $Pattern) { Write-Host 'usage: hgrep <pattern>'; return }
    $h = (Get-PSReadLineOption).HistorySavePath
    if (Test-Path -LiteralPath $h) { Select-String -LiteralPath $h -Pattern ($Pattern -join ' ') | ForEach-Object { $_.Line } }
}
# ---- clipboard-end ----

# ---- workspace-organizer-start ----
# wso — workspace organizer. Thin wrapper: the verbs live in the clone
# (bootstrap\_workspace.ps1 + _workspace_cmd.ps1) so they can be fixed with a
# `tstack update` rather than a profile re-sync, and so the same code serves a
# standalone invocation. The bash twin is bootstrap/wso.sh.
function wso {
    param([Parameter(ValueFromRemainingArguments)] [string[]]$Arguments)
    $src = Resolve-TsSourceDir
    if (-not $src) { return }
    $lib = Join-Path $src 'bootstrap\_workspace.ps1'
    if (-not (Test-Path -LiteralPath $lib)) {
        Write-Warning "$lib not found; cannot run wso. Try 'tstack update'."
        return
    }
    . $lib
    # Hand the resolved clone to the library so Get-TsWsRuntimeClone can never
    # disagree with Resolve-TsSourceDir — a disagreement switches off the
    # "never migrate the runtime clone" guard, and `wso migrate` then relocates
    # the install. The zsh twin does the same (dot_zshrc wso).
    $prevPin = $env:TERMINAL_STACK_DIR
    try {
        $env:TERMINAL_STACK_DIR = $src
        Invoke-Wso @Arguments
    } finally {
        if ($null -eq $prevPin) { Remove-Item Env:TERMINAL_STACK_DIR -ErrorAction SilentlyContinue }
        else { $env:TERMINAL_STACK_DIR = $prevPin }
    }
}
# ---- workspace-organizer-end ----

# ---- local-overrides-start ----
# Per-machine overrides (not synced by the stack). The Windows counterpart of
# ~/.zshrc.local — see profile.local.ps1.example. Keep this block last so
# local definitions win.
$tsLocalProfile = Join-Path (Split-Path $PROFILE) 'profile.local.ps1'
if (Test-Path $tsLocalProfile) { . $tsLocalProfile }
# ---- local-overrides-end ----
