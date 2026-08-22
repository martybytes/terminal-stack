# windows-bootstrap.ps1 — install Windows-side prerequisites for the terminal-stack
# Idempotent: re-run safely. Each install runs only if winget reports the package not installed.
# Pass -WhatIf to dry-run.
# See ../INSTALL.md § Scripted for context.

[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$IncludeOptional
)

$ErrorActionPreference = 'Stop'

# Config store + app catalog + wizard prompts (Save-TsConfig, $TsWingetIds,
# Read-TsChoice, Read-TsLeader/Theme/Wezterm/Apps, etc.).
. (Join-Path $PSScriptRoot '_config.ps1')

# Packages that didn't install, reported together at the end. A Write-Warning
# mid-run scrolls past and gets missed — a WezTerm nightly failure did exactly
# that in the field, and the install looked clean.
$script:TsFailedPackages = @()

function Install-WingetPackage {
    param([Parameter(Mandatory)][string]$Id, [string]$Because)
    if (-not $PSCmdlet.ShouldProcess($Id, 'winget install')) { return $true }
    Write-Host "==> winget install $Id"
    $out = & winget install --id $Id --exact --silent --accept-source-agreements --accept-package-agreements 2>&1
    $out | Select-Object -Last 3
    if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq -1978335189) {
        # -1978335189 = APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE (already at latest)
        return $true
    }
    $reason = if ($out -match 'hash does not match') { 'installer hash mismatch (stale manifest)' }
              else { "winget exit code $LASTEXITCODE" }
    Write-Warning "winget install $Id failed: $reason"
    $script:TsFailedPackages += [pscustomobject]@{ Id = $Id; Reason = $reason; Because = $Because }
    return $false
}

# WezTerm nightly's winget manifest is republished more often than its hash is
# refreshed, so a nightly install fails outright on a bad day. Stable is a fine
# fallback — the config targets nightly features but degrades rather than breaks.
function Install-TsWezterm {
    param([Parameter(Mandatory)][string]$Choice)
    switch ($Choice) {
        'skip'   { Write-Host '==> WezTerm: skipped'; return }
        'stable' { Install-WingetPackage -Id 'wez.wezterm' -Because 'terminal emulator' | Out-Null; return }
        default  {
            if (Install-WingetPackage -Id 'wez.wezterm.nightly' -Because 'terminal emulator') { return }
            Write-Host '==> nightly unavailable; falling back to WezTerm stable'
            # The nightly failure is now handled, not outstanding.
            $script:TsFailedPackages = @($script:TsFailedPackages | Where-Object { $_.Id -ne 'wez.wezterm.nightly' })
            Install-WingetPackage -Id 'wez.wezterm' -Because 'terminal emulator (nightly fallback)' | Out-Null
        }
    }
}

function Test-WingetAvailable {
    try {
        & winget --version | Out-Null
        return $true
    } catch {
        return $false
    }
}

# Workspace root for the ws/wsp/wspu profile functions. Same contract as the
# WSL/Linux/Mac bootstraps: $env:WORKSPACE_DIR skips the prompt.
function Get-TsDetectedWorkspace {
    foreach ($d in @(
        'C:\DATA\Workspace',
        (Join-Path $env:USERPROFILE 'workspace'),
        (Join-Path $env:USERPROFILE 'Documents\Workspace')
    )) { if (Test-Path $d) { return $d } }
    return $null
}

function Read-TsWorkspaceDir {
    if ($env:WORKSPACE_DIR) {
        Write-Host "==> WORKSPACE_DIR=$($env:WORKSPACE_DIR) (from env; skipping prompt)"
        return $env:WORKSPACE_DIR
    }
    $detected = Get-TsDetectedWorkspace
    $promptDefault = if ($detected) { $detected } else { 'none' }
    if (-not (Test-TsInteractive)) { return $detected }
    Write-Host ''
    $answer = Read-Host "Workspace directory [$promptDefault]"
    if ($answer) { $answer.Trim() } else { $detected }
}

# Preflight
if (-not (Test-WingetAvailable)) {
    throw "winget not available. Install App Installer from the Microsoft Store, then re-run."
}

if ($PSVersionTable.PSVersion.Major -lt 7) {
    Write-Warning "Running under PowerShell $($PSVersionTable.PSVersion). PowerShell 7+ is recommended. Continuing anyway."
}

Write-Host '==> Terminal stack Windows bootstrap'
Write-Host '    Detected: ' -NoNewline
Write-Host "PowerShell $($PSVersionTable.PSVersion); user $env:USERNAME"

# ── Wizard ──────────────────────────────────────────────────────────────────────
# Every answer is collected first and shown for review before anything is
# installed or written, so a mis-typed choice costs a keystroke instead of a
# re-run. Env vars (TS_LEADER / TS_THEME / TS_WEZTERM / TS_WEZ_MUX /
# TS_WEZ_RESTORE / TS_APPS / TS_CC_TTS / WORKSPACE_DIR) still skip their prompt
# individually.
function Read-TsWizard {
    $w = [ordered]@{
        Leader    = (Read-TsLeader)
        Theme     = (Read-TsTheme)
        Wezterm   = (Read-TsWezterm)
        WezMux    = (Read-TsWeztermMux)
        WezRestore = (Read-TsWeztermRestore)
        Apps      = @(Read-TsApps)
        CcTts     = (Read-TsCcTts)
        Headroom  = (Read-TsAgentToggle TS_HEADROOM 'Headroom prompt compression and monitoring?' @(
            '  Expects docker-local on 127.0.0.1:8787 and its MCP sidecar on 8788.',
            '  This installer never manages those containers.'
        ))
        Caveman   = (Read-TsAgentToggle TS_CAVEMAN 'Caveman terse output for all projects?' @(
            '  Installs the pinned user-scope plugin/skill; no project files are changed.'
        ))
        Agentmemory = (Read-TsAgentToggle TS_AGENTMEMORY 'AgentMemory for all projects?' @(
            '  Expects docker-local on 127.0.0.1:3111; terminal-stack owns only agent wiring.'
        ))
        Workspace = (Read-TsWorkspaceDir)
    }
    # Tray daemon follow-up only makes sense when TTS itself was enabled.
    $w.CcTtsDaemon = if ($w.CcTts -eq 'on') { Read-TsCcTtsDaemon } else { 'off' }
    $w.HeadroomCursor = if ($w.Headroom -eq 'on') { Read-TsHeadroomCursorMode } else { 'mcp' }
    return $w
}

function Show-TsWizardReview($w) {
    $themeLabel = switch ($w.Theme) {
        'dark'   { 'dark (Catppuccin Mocha)' }
        'light'  { 'light (VS Code Light Modern)' }
        'follow' { 'follow OS appearance' }
        default  { $w.Theme }
    }
    Write-Host ''
    Write-Host '==> Review'
    Write-Host ("    Leader           {0}" -f $w.Leader)
    Write-Host ("    Theme            {0}" -f $themeLabel)
    Write-Host ("    WezTerm          {0}" -f $w.Wezterm)
    Write-Host ("    WezTerm mux      {0}" -f $w.WezMux)
    Write-Host ("    Session restore  {0}" -f $w.WezRestore)
    Write-Host ("    Apps             {0}" -f $(if ($w.Apps.Count) { $w.Apps -join ', ' } else { '<none>' }))
    Write-Host ("    Claude TTS       {0}" -f $w.CcTts)
    if ($w.CcTts -eq 'on') { Write-Host ("    TTS daemon       {0}" -f $w.CcTtsDaemon) }
    Write-Host ("    Headroom         {0} (Cursor: {1})" -f $w.Headroom, $w.HeadroomCursor)
    Write-Host ("    Caveman          {0}" -f $w.Caveman)
    Write-Host ("    AgentMemory      {0}" -f $w.Agentmemory)
    Write-Host ("    Workspace        {0}" -f $(if ($w.Workspace) { $w.Workspace } else { '<none detected>' }))
}

# Plain if/else, not switch: `break`/`continue` inside a PowerShell switch bind
# to the switch, not the enclosing loop, which would make "edit" fall straight
# through to the install.
$wizard = Read-TsWizard
while ($true) {
    Show-TsWizardReview $wizard
    if (-not (Test-TsInteractive)) { Write-Host '  (non-interactive — proceeding)'; break }
    $a = (Read-Host '  [P]roceed / [e]dit / [q]uit').Trim()
    if ($a -match '^(e|edit)$') { $wizard = Read-TsWizard; continue }
    if ($a -match '^(q|quit)$') { Write-Host '==> quit — nothing was installed or changed.'; return }
    if (-not $a -or $a -match '^(p|proceed|y|yes)$') { break }
    Write-Host "  '$a' is not one of the choices — Enter to proceed, 'e' to edit, 'q' to quit."
}

$leaderChord  = $wizard.Leader
$themeMode    = $wizard.Theme
$selectedApps = @($wizard.Apps)
$ccTtsChoice  = $wizard.CcTts
$ccTts        = Set-CcTtsWizardChoice $ccTtsChoice
Write-Host ''
Write-Host "==> Config: leader=$leaderChord theme=$themeMode wezterm=$($wizard.Wezterm) wez-mux=$($wizard.WezMux) wez-restore=$($wizard.WezRestore) cc-tts=$ccTtsChoice headroom=$($wizard.Headroom) caveman=$($wizard.Caveman) agentmemory=$($wizard.Agentmemory)"

# Required packages (always installed; not part of the picker). WezTerm is NOT
# here — it is a wizard choice, see Read-TsWezterm.
$requiredPackages = @(
    'DEVCOM.JetBrainsMonoNerdFont',     # Nerd Font for glyph rendering
    'Starship.Starship',                # Shell prompt
    'twpayne.chezmoi'                   # Dotfile manager (used to apply this repo)
)
foreach ($pkg in $requiredPackages) { Install-WingetPackage -Id $pkg -Because 'required' | Out-Null }

Install-TsWezterm -Choice $wizard.Wezterm

# Selected toggleable apps (catalog id -> winget id).
foreach ($id in $selectedApps) {
    if ($script:TsWingetIds.ContainsKey($id)) {
        Install-WingetPackage -Id $script:TsWingetIds[$id] -Because $id | Out-Null
    }
}

# Save the chosen config to %LOCALAPPDATA%\terminal-stack\config.json — read by
# sync-windows.ps1 (and the WSL hook's mirror) to render the Windows .tmpl files.
if ($PSCmdlet.ShouldProcess('terminal-stack config.json', 'save config')) {
    Save-TsConfig -LeaderChord $leaderChord -ThemeMode $themeMode -Apps $selectedApps -WeztermMux $wizard.WezMux -WeztermRestore $wizard.WezRestore -CcTts $ccTts -HeadroomEnabled $wizard.Headroom -HeadroomCursorMode $wizard.HeadroomCursor -CavemanEnabled $wizard.Caveman -AgentmemoryEnabled $wizard.Agentmemory | Out-Null
    Export-CcTtsJson
    Write-Host "==> Saved config to $(Get-TsConfigPath)"
    if ($wizard.CcTts -eq 'on') {
        $installerArgs = if ($wizard.CcTtsDaemon -eq 'on') { @() } `
            else { @('-NoStart', '-NoAutostart') }
        if (Invoke-TsCcTtsDaemonInstaller $installerArgs) {
            $ccTts.daemon.enabled = ($wizard.CcTtsDaemon -eq 'on')
            Save-TsConfig -LeaderChord $leaderChord -ThemeMode $themeMode -Apps $selectedApps -WeztermMux $wizard.WezMux -WeztermRestore $wizard.WezRestore -CcTts $ccTts -HeadroomEnabled $wizard.Headroom -HeadroomCursorMode $wizard.HeadroomCursor -CavemanEnabled $wizard.Caveman -AgentmemoryEnabled $wizard.Agentmemory | Out-Null
            Export-CcTtsJson
        } else {
            Write-Warning 'TTS executable build failed; voice hooks were not enabled.'
            $ccTts.enabled = $false
            $ccTts.daemon.enabled = $false
            Save-TsConfig -LeaderChord $leaderChord -ThemeMode $themeMode -Apps $selectedApps -WeztermMux $wizard.WezMux -WeztermRestore $wizard.WezRestore -CcTts $ccTts -HeadroomEnabled $wizard.Headroom -HeadroomCursorMode $wizard.HeadroomCursor -CavemanEnabled $wizard.Caveman -AgentmemoryEnabled $wizard.Agentmemory | Out-Null
            Export-CcTtsJson
        }
    }
}

if (-not $WhatIfPreference) {
    $agentsInstaller = Join-Path $PSScriptRoot 'ts-agents.ps1'
    if ($wizard.Headroom -eq 'on') { & $agentsInstaller -Tool headroom -Action on -CursorMode $wizard.HeadroomCursor | Out-Host }
    if ($wizard.Caveman -eq 'on') { & $agentsInstaller -Tool caveman -Action on | Out-Host }
    if ($wizard.Agentmemory -eq 'on') { & $agentsInstaller -Tool agentmemory -Action on | Out-Host }
}

# Git include — stack aliases + delta config. The included file lands at
# %USERPROFILE%\.config\git\terminal-stack.gitconfig via sync-windows.ps1
# (which runs after this bootstrap); git silently skips missing includes,
# so ordering is safe. Forward slashes: git accepts them on Windows and they
# survive .gitconfig escaping.
$gitInclude = ($env:USERPROFILE -replace '\\', '/') + '/.config/git/terminal-stack.gitconfig'
$existingIncludes = & git config --global --get-all include.path 2>$null
if ($existingIncludes -match 'terminal-stack\.gitconfig') {
    Write-Host '==> git include.path already set'
} elseif ($PSCmdlet.ShouldProcess($gitInclude, 'git config --global --add include.path')) {
    Write-Host "==> Adding git include.path -> $gitInclude"
    & git config --global --add include.path $gitInclude
}

# Persist the workspace answer ONLY when it differs from the autodetect
# (Get-TsWorkspace in $PROFILE covers the detected case).
$wsDetected = Get-TsDetectedWorkspace
$wsChoice = $wizard.Workspace
if (-not $wsChoice) {
    Write-Warning 'No workspace directory found or chosen. Set one later: $env:WORKSPACE_DIR in profile.local.ps1'
} elseif ($wsChoice -eq $wsDetected) {
    Write-Host "==> Workspace: $wsChoice (autodetected; no override needed)"
} else {
    if (-not (Test-Path $wsChoice)) { Write-Warning "$wsChoice does not exist (yet) — ws will warn until it does." }
    # pwsh 7's $PROFILE is Documents\PowerShell\...; resolve via MyDocuments so
    # this works even when the bootstrap itself runs under Windows PowerShell 5.
    $localProfile = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\profile.local.ps1'
    if ($PSCmdlet.ShouldProcess($localProfile, "persist WORKSPACE_DIR=$wsChoice")) {
        New-Item -ItemType Directory -Force -Path (Split-Path $localProfile) | Out-Null
        $line = "`$env:WORKSPACE_DIR = '$wsChoice'"
        if ((Test-Path $localProfile) -and (Get-Content $localProfile | Where-Object { $_ -match '^\s*\$env:WORKSPACE_DIR\s*=' })) {
            (Get-Content $localProfile) -replace '^\s*\$env:WORKSPACE_DIR\s*=.*', $line | Set-Content $localProfile
            Write-Host "==> Updated WORKSPACE_DIR in $localProfile"
        } else {
            Add-Content -Path $localProfile -Value $line
            Write-Host "==> Wrote WORKSPACE_DIR=$wsChoice to $localProfile"
        }
    }
}

Write-Host ''
if ($script:TsFailedPackages.Count) {
    Write-Host "==> $($script:TsFailedPackages.Count) package(s) did not install:"
    foreach ($f in $script:TsFailedPackages) {
        Write-Host ("    {0}  ({1}) — {2}" -f $f.Id, $f.Because, $f.Reason)
        Write-Host ("      retry: winget install --id {0} --exact" -f $f.Id)
    }
    Write-Host '    Everything else was configured; re-run this bootstrap once they install.'
    Write-Host ''
}
Write-Host '==> Windows bootstrap done.'
Write-Host '    Next: run bootstrap\wsl-bootstrap.sh inside WSL Ubuntu, then chezmoi apply.'
Write-Host '    See INSTALL.md § Scripted for the full sequence.'
