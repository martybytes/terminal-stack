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
function wspu {
    $r = Get-TsWorkspaceSibling 'Public'
    if ($r) { Set-Location $r } else { Write-Warning 'wspu: no *_Public sibling' }
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
# ---- workspace-nav-end ----

function Set-WezTabTitle([string]$title) {
    if (-not $env:WEZTERM_PANE) { return }
    & wezterm.exe cli set-tab-title $title 2>$null
    # Empty title marks CC exit -> clear cc_state; WezTerm Lua restores pane bg.
    if (-not $title) {
        try {
            [Console]::Out.Write("$([char]27)]1337;SetUserVar=cc_state=$([char]7)")
        } catch {}
    }
}

function cc    { Set-WezTabTitle "cc • $(Split-Path -Leaf $PWD)"; try { claude @args } finally { Set-WezTabTitle "" } }
function ccc   { Set-WezTabTitle "cc • $(Split-Path -Leaf $PWD)"; try { claude --continue @args } finally { Set-WezTabTitle "" } }
function ccd   { Set-WezTabTitle "cc • $(Split-Path -Leaf $PWD)"; try { claude --dangerously-skip-permissions @args } finally { Set-WezTabTitle "" } }
function ccdc  { Set-WezTabTitle "cc • $(Split-Path -Leaf $PWD)"; try { claude --dangerously-skip-permissions --continue @args } finally { Set-WezTabTitle "" } }
function ccr   { Set-WezTabTitle "cc • $(Split-Path -Leaf $PWD)"; try { claude --resume @args } finally { Set-WezTabTitle "" } }
function ccdr  { Set-WezTabTitle "cc • $(Split-Path -Leaf $PWD)"; try { claude --dangerously-skip-permissions --resume @args } finally { Set-WezTabTitle "" } }
function cca   { Set-WezTabTitle "cc • agents"; try { claude agents } finally { Set-WezTabTitle "" } }

# Escape hatch: vanilla pwsh, no profile (no starship/zoxide/aliases).
# Nested — `exit` drops back to the customized shell.
function plain { Set-WezTabTitle "plain • $(Split-Path -Leaf $PWD)"; try { pwsh -NoLogo -NoProfile @args } finally { Set-WezTabTitle "" } }

# ---- starship-stack-start ----

# Cursor/Claude agent shells set TERM=dumb and CURSOR_AGENT=1 — skip prompt chrome there.
function Test-TsAgentShell {
    if ($env:CURSOR_AGENT -eq '1') { return $true }
    if ($env:TERM -eq 'dumb') { return $true }
    if ($env:CI -eq 'true' -or $env:CI -eq '1') { return $true }
    return $false
}

# Native console children (Claude Code, etc.) can SetConsoleOutputCP back to 437 on exit; [Console]::OutputEncoding caches and won't catch it, so probe the OS codepage directly.
if (-not ('Native.ConsoleCP' -as [type])) {
    Add-Type -Namespace Native -Name ConsoleCP -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern uint GetConsoleOutputCP();
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern bool SetConsoleOutputCP(uint wCodePageID);
'@ | Out-Null
}
[Native.ConsoleCP]::SetConsoleOutputCP(65001) | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::InputEncoding  = [System.Text.Encoding]::UTF8

if (-not (Test-TsAgentShell)) {
    Invoke-Expression (&starship init powershell)
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

if (Get-Command zoxide -ErrorAction SilentlyContinue) {
    Invoke-Expression (& { (zoxide init powershell | Out-String) })
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
# Resolution order: -SourceDir → $env:TERMINAL_STACK_DIR → install.ps1 default
# ($env:USERPROFILE\terminal-stack). We deliberately do NOT consult
# `chezmoi source-path` here: on Windows that returns chezmoi's default
# sourceDir (~/.local/share/chezmoi) regardless of where the actual clone
# lives, because Windows users don't configure chezmoi.toml (the WSL side does).
function Resolve-TsSourceDir([string]$SourceDir) {
    if (-not $SourceDir) { $SourceDir = $env:TERMINAL_STACK_DIR }
    if (-not $SourceDir) { $SourceDir = Join-Path $env:USERPROFILE 'terminal-stack' }
    if (-not (Test-Path (Join-Path $SourceDir '.git'))) {
        Write-Warning "terminal-stack clone not found at $SourceDir. Pass -SourceDir <path> or re-run install.ps1."
        return $null
    }
    return $SourceDir
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

    $SourceDir = Resolve-TsSourceDir $SourceDir
    if (-not $SourceDir) { return }

    # Preflight: a resolved dir that isn't a terminal-stack clone means a stale /
    # moved install. Nudge toward ts-doctor rather than pulling the wrong repo.
    $remote = & git -C $SourceDir config --get remote.origin.url 2>$null
    if ($remote -notmatch 'terminal-stack') {
        Write-Warning "ts-update: '$SourceDir' doesn't look like a terminal-stack clone. Run 'ts-doctor' to check."
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
        Write-Host "==> recorded rollback point: $(& git -C $SourceDir rev-parse --short HEAD) (ts-rollback to undo)"
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
}
Set-Alias -Name ts-update -Value Update-TerminalStack

# Undo the last ts-update: reset the clone to the recorded pre-update SHA and
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
    Write-Host "==> resetting $SourceDir to $sha (recorded before last ts-update)"
    & git -C $SourceDir reset --hard $sha
    if ($LASTEXITCODE -ne 0) { return }
    Invoke-TsSync $SourceDir
    Write-Host '==> done. run ts-update to return to latest.'
}
Set-Alias -Name ts-rollback -Value Restore-TerminalStack

# Configure the stack: leader key, theme (dark/light/follow), tmux prefix, apps.
# Bare `ts-config` opens an interactive menu; `ts-config theme follow` etc. set one
# value. Writes %LOCALAPPDATA%\terminal-stack\config.json and re-syncs the Windows
# files. NOTE: in a combined WSL+Windows setup, prefer running `ts-config` from WSL
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

    $c = Get-TsConfig
    $leader = if ($c.leaderChord) { $c.leaderChord } else { 'ctrl-space' }
    $theme  = if ($c.themeMode)   { $c.themeMode }   else { 'dark' }
    $tmux   = if ($c.tmuxPrefix)  { $c.tmuxPrefix }  else { 'ctrl-b' }
    $apps   = @($c.apps)
    $ccTts  = if ($c.ccTts) { $c.ccTts } else { Get-CcTtsDefaults }

    $save = {
        param($Tts = $ccTts)
        Save-TsConfig -LeaderChord $leader -ThemeMode $theme -TmuxPrefix $tmux -Apps $apps -CcTts $Tts | Out-Null
        Export-CcTtsJson
        Invoke-TsSync $src
        Write-Host '==> done.'
    }

    switch ($Action) {
        '' {
            while ($true) {
                Write-Host ''
                Write-Host 'terminal-stack config:'
                Write-Host "  leader : $leader"
                Write-Host "  theme  : $theme   (palette $(Get-TsResolvedTheme $theme))"
                Write-Host "  tmux   : $tmux"
                Write-Host "  apps   : $($apps -join ', ')"
                Write-Host "  cc-tts : $(if ($ccTts.enabled) { 'on' } else { 'off' })"
                Write-Host ''
                Write-Host '  1) leader  2) theme  3) tmux prefix  4) apps  5) re-apply  6) Claude TTS  q) quit'
                switch (Read-Host 'Choose') {
                    '1' { $leader = Read-TsLeader; & $save }
                    '2' { $theme  = Read-TsTheme;  & $save }
                    '3' { $t = Read-Host 'tmux prefix chord (e.g. ctrl-a) [ctrl-b]'; $tmux = if ($t) { $t } else { 'ctrl-b' }; & $save }
                    '4' { $apps = @(Read-TsApps); Install-TsApps $apps; & $save }
                    '5' { & $save }
                    '6' {
                        Show-CcTtsConfig
                        switch (Read-Host 'TTS: a) on  b) off  c) test  d) back') {
                            'a' { $ccTts.enabled = $true; & $save $ccTts }
                            'b' { $ccTts.enabled = $false; & $save $ccTts }
                            'c' { Invoke-TsConfigTts -Sub test -Apply $save }
                        }
                    }
                    default { return }
                }
            }
        }
        'show' {
            Write-Host "leader : $leader"
            Write-Host "theme  : $theme   (palette $(Get-TsResolvedTheme $theme))"
            Write-Host "tmux   : $tmux"
            Write-Host "apps   : $($apps -join ', ')"
        }
        'leader' { if (-not $Value) { Write-Warning 'usage: ts-config leader <chord>'; return }; $leader = $Value; & $save }
        'theme'  { if (-not $Value) { Write-Warning 'usage: ts-config theme <dark|light|follow>'; return }; $theme = $Value; & $save }
        'tmux'   { if (-not $Value) { Write-Warning 'usage: ts-config tmux <chord>'; return }; $tmux = $Value; & $save }
        'apps'   {
            if ($Value) {
                switch ($Value) {
                    'recommended' { $apps = $script:TsAppsRecommended }
                    'all'         { $apps = $script:TsAppsAll }
                    'none'        { $apps = @() }
                    default       { $apps = ($Value -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
                }
            } else { $apps = @(Read-TsApps) }
            Install-TsApps $apps; & $save
        }
        'tts' {
            Invoke-TsConfigTts -Sub $Value -Arg $Rest[0] -Arg2 $Rest[1] -Apply {
                param($Tts)
                $ccTts = $Tts
                & $save $Tts
            }
        }
        default { Write-Warning "ts-config: unknown command '$Action' (show, leader, theme, tmux, apps, tts)" }
    }
}
Set-Alias -Name ts-config -Value Set-TerminalStackConfig

# Probe known clone locations for one that actually contains the repo — used so
# the doctor still runs when $env:TERMINAL_STACK_DIR / the default path is wrong.
function Find-TsAnyClone {
    foreach ($d in @(
        $env:TERMINAL_STACK_DIR,
        (Join-Path $env:USERPROFILE 'terminal-stack'),
        'C:\DATA\Workspace\terminal-stack',
        (Join-Path $env:USERPROFILE 'code\terminal-stack'),
        (Join-Path $env:USERPROFILE 'Documents\Workspace\terminal-stack')
    )) {
        if ($d -and (Test-Path (Join-Path $d 'bootstrap\_cleanup.ps1'))) { return $d }
    }
    return $null
}

# Persist $env:TERMINAL_STACK_DIR to profile.local.ps1 so ts-update / ts-config
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

# Diagnose / repair the Windows install: missing/moved clone, stale config, leftover
# old clones. `ts-doctor` checks (read-only); `ts-doctor -Repair` fixes (persist the
# real clone path, re-sync, offer cleanup). Counterpart of the POSIX `ts-doctor`.
function Invoke-TsDoctor {
    [CmdletBinding()] param([switch]$Repair, [switch]$Quiet)
    $clone = Find-TsAnyClone
    if (-not $clone) { Write-Warning 'No terminal-stack clone found. Re-run install.ps1 (irm ... | iex).'; return }
    . (Join-Path $clone 'bootstrap\_cleanup.ps1')
    $src = Resolve-TsSourceDir
    if (-not $src) { $src = $clone }
    if ($Repair) {
        if ((Resolve-Path $clone).Path -ne (Resolve-Path $src).Path) { Set-TsSourceDirPersisted $clone; $src = $clone }
        Invoke-TsSync $src
        Invoke-TsCleanupMenu $src
        Test-TsInstall -SourceDir $src | Out-Null
    } else {
        Test-TsInstall -SourceDir $src -Quiet:$Quiet | Out-Null
    }
}
function Test-TerminalStack    { [CmdletBinding()] param([switch]$Quiet) Invoke-TsDoctor -Quiet:$Quiet }
function Repair-TerminalStack  { Invoke-TsDoctor -Repair }
Set-Alias -Name ts-doctor -Value Invoke-TsDoctor
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

function cctts {
    param([string]$Action, [string]$Extra)
    switch ($Action) {
        'on'   { ts-config tts on }
        'off'  { ts-config tts off }
        'test' { ts-config tts test }
        'show' { ts-config tts show }
        default {
            $en = $false
            $cfgPath = Join-Path $env:LOCALAPPDATA 'terminal-stack\config.json'
            if (Test-Path $cfgPath) {
                try { $en = [bool](Get-Content $cfgPath -Raw | ConvertFrom-Json).ccTts.enabled } catch {}
            }
            if ($en) { Write-Host 'CC TTS: ON  (cctts off to disable; ts-config tts for settings)' }
            else     { Write-Host 'CC TTS: OFF (cctts on to enable)' }
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
    $resolved = foreach ($p in $Paths) {
        $full = Resolve-Path -LiteralPath $p -ErrorAction SilentlyContinue
        if     ($full)                                 { $full.Path }
        elseif ([System.IO.Path]::IsPathRooted($p))    { $p }
        else                                           { Join-Path (Get-Location).Path $p }
    }
    & $exe @resolved
}
# ---- editor-launch-end ----

# ---- doc-start ----
# `doc` — personal markdown knowledge base. Topics live in <clone>/docs/kb
# (tracked) + ~/.doc.local (untracked personal layer); rendered by glow, bat
# fallback. On Windows, sync-windows.ps1 also mirrors docs/kb to
# %LOCALAPPDATA%\terminal-stack\docs\kb (read fallback; edit/sync use the clone).
# See docs/kb/_index.md. (`ref`/`wzr` are separate for now.)
function Get-DocRoot {
    $cands = @()
    if ($env:DOC_ROOT) { $cands += $env:DOC_ROOT }
    if ($env:TERMINAL_STACK_DIR) { $cands += (Join-Path $env:TERMINAL_STACK_DIR 'docs\kb') }
    foreach ($base in @('C:\DATA\Workspace', (Join-Path $env:USERPROFILE 'workspace'),
                        (Join-Path $env:USERPROFILE 'Documents\Workspace'), $env:USERPROFILE)) {
        $cands += (Join-Path $base 'terminal-stack\docs\kb')
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
    if     (Get-Command glow -EA SilentlyContinue) { & glow -p $path }
    elseif (Get-Command bat  -EA SilentlyContinue) { & bat --language=markdown --paging=always $path }
    else   { Get-Content -LiteralPath $path }
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
    $prev = if (Get-Command glow -EA SilentlyContinue) { 'glow -s dark {2}' } else { 'bat --color=always --style=plain {2}' }
    $sel = ($idx | ForEach-Object { "$($_.Label)`t$($_.Path)" }) |
        fzf --delimiter="`t" --with-nth=1 --query=$query --preview=$prev --preview-window='right,60%,wrap' --header='enter=open'
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
    $sel = $rows | fzf --delimiter="`t" --with-nth=1 --query=$query `
        --preview='bat --color=always --highlight-line {3} {2}' --preview-window='right,60%,wrap' `
        --header='enter = put command on your prompt'
    if ($sel) { [Microsoft.PowerShell.PSConsoleReadLine]::Insert((($sel -split "`t")[0])) }
}

function Invoke-DocGrep([string]$pat) {
    if (-not $pat) { Write-Host 'usage: doc -g <pattern>'; return }
    $files = @((Get-DocIndex 'all').Path)
    if (-not $files) { Write-Warning 'doc: no docs'; return }
    if (Get-Command rg -EA SilentlyContinue) { & rg --line-number --heading --color=always $pat @files }
    else { Select-String -Path $files -Pattern $pat | ForEach-Object { "$($_.Filename):$($_.LineNumber): $($_.Line.Trim())" } }
}

function Invoke-DocEdit([string]$mode, [string]$arg, [string]$os) {
    $editor = if ($env:EDITOR) { $env:EDITOR } elseif (Get-Command micro -EA SilentlyContinue) { 'micro' } else { 'notepad' }
    if ($mode -eq 'new') {
        if (-not $arg) { Write-Host 'usage: doc new <os>/<name>   e.g. doc new linux/foo'; return }
        $p = Join-Path (Get-DocRoot) ($arg -replace '/', '\')
        if (-not $p.EndsWith('.md')) { $p += '.md' }
        New-Item -ItemType Directory -Force -Path (Split-Path $p) | Out-Null
        if (-not (Test-Path -LiteralPath $p)) { "# $((Split-Path $p -Leaf) -replace '\.md$','')`n" | Set-Content -LiteralPath $p -Encoding utf8 }
        & $editor $p
    } else {
        $m = @(Get-DocIndex 'all' | Where-Object { $_.Label -like "*$arg*" })
        if ($m.Count -ge 1) { & $editor $m[0].Path } else { Write-Warning "doc edit: no topic matching '$arg'" }
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
doc                     fuzzy-find a topic (glow preview) -> open in pager
doc <topic>             open a topic directly (e.g. doc veracrypt, doc ssh-keys)
doc -g <pattern>        grep across every topic
doc cmd [pattern]       find a command and drop it on your prompt
doc tui                 glow's tree browser
doc edit <topic>        edit a topic   |   doc new <os>/<name>   scaffold one
doc ls                  list topics (this OS + common + local)
doc --os <linux|macos|windows> ...    browse another OS
doc sync [msg]          commit doc edits back to the repo (+ changelog, confirm push)
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
        '^(tui)$'       { $r = Get-DocRoot; if (Get-Command glow -EA SilentlyContinue) { & glow $r } else { Write-Warning 'doc tui needs glow (winget install charmbracelet.glow)' }; break }
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
function ccat { & bat --paging=never @args }

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

# ---- local-overrides-start ----
# Per-machine overrides (not synced by the stack). The Windows counterpart of
# ~/.zshrc.local — see profile.local.ps1.example. Keep this block last so
# local definitions win.
$tsLocalProfile = Join-Path (Split-Path $PROFILE) 'profile.local.ps1'
if (Test-Path $tsLocalProfile) { . $tsLocalProfile }
# ---- local-overrides-end ----
