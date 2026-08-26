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
# Read-TsChoice, Read-TsMulti, Read-TsLeader/Theme/Terminals/Apps, etc.).
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

# Stable only. Nightly's winget manifest is republished more often than its hash
# is refreshed, so `Installer hash does not match` was a routine outcome rather
# than an exotic one — and the trade-off (upstream stable is old) is written up in
# docs/decisions.md § "Why WezTerm is stable-only, and why the emulator is still a
# choice". Nothing here installs nightly; a nightly a previous bootstrap left is
# removed FIRST and unconditionally, whether or not WezTerm was selected this run.
# Install-TsTerminals now lives in bootstrap/_config.ps1 (dot-sourced above) so
# `tstack config wizard` can call it too; it uses Install-WingetPackage when that is
# in scope, so this script keeps its end-of-run failure report.

function Test-WingetAvailable {
    try {
        & winget --version | Out-Null
        return $true
    } catch {
        return $false
    }
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
# Read-TsWizard now lives in bootstrap/_config.ps1 (dot-sourced above) so that
# `tstack config wizard` can replay the identical questionnaire.

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
    Write-Host ("    Terminals        {0}" -f $(if ($w.Terminals) { $w.Terminals -join ' ' } else { '<none>' }))
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
Write-Host "==> Config: leader=$leaderChord theme=$themeMode terminals=$(if ($wizard.Terminals) { $wizard.Terminals -join ',' } else { 'none' }) wez-mux=$($wizard.WezMux) wez-restore=$($wizard.WezRestore) cc-tts=$ccTtsChoice headroom=$($wizard.Headroom) caveman=$($wizard.Caveman) agentmemory=$($wizard.Agentmemory)"

# Required packages (always installed; not part of the picker). Terminal
# emulators are NOT here — they are a wizard choice, see Read-TsTerminals.
$requiredPackages = @(
    'DEVCOM.JetBrainsMonoNerdFont',     # Nerd Font for glyph rendering
    'Starship.Starship',                # Shell prompt
    'twpayne.chezmoi'                   # Dotfile manager (used to apply this repo)
)
foreach ($pkg in $requiredPackages) { Install-WingetPackage -Id $pkg -Because 'required' | Out-Null }

Install-TsTerminals -Selected $wizard.Terminals

# Selected toggleable apps (catalog id -> winget id). Uses Install-WingetPackage
# rather than Install-TsApps so a failure lands in the end-of-run report — which
# is also why the two non-winget routes below are repeated here rather than
# delegated: skip either one and the tools it owns are silently never installed.
foreach ($id in $selectedApps) {
    if (Test-TsAppIsAi $id) { continue }   # not winget packages; handled below
    if (Test-TsAppIsPy $id) { continue }   # PyPI, not winget; handled below
    if ($script:TsWingetIds.ContainsKey($id)) {
        Install-WingetPackage -Id $script:TsWingetIds[$id] -Because $id | Out-Null
    } else {
        Write-Host "==> ${id}: no Windows package available; skipped"
    }
}
# Python tools before the agent CLIs: `python` and `uv` are winget entries above,
# and Install-TsPyTool prefers uv. Refresh PATH so one installed moments ago is
# visible to this process.
if (@($selectedApps | Where-Object { Test-TsAppIsPy $_ }).Count) {
    Update-TsSessionPath
    foreach ($id in $selectedApps) { if (Test-TsAppIsPy $id) { Install-TsPyTool $id } }
}
foreach ($id in $selectedApps) { if (Test-TsAppIsAi $id) { Install-TsAiCli $id } }
Update-TsSessionPath
Show-TsInstalledApps $selectedApps

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

# The interpreter tstack runs on. Same probe shape as
# bootstrap/tts-daemon/build.ps1 rather than a third spelling of it.
function Find-Python {
    foreach ($name in @('python', 'python3')) {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($found) { return $found.Source }
    }
    return $null
}

if (-not $WhatIfPreference) {
    # One implementation on every platform: tstack/commands/agents.py, run
    # through the same entry point the `tstack agents` shim uses.
    $agentsEntry = Join-Path (Split-Path -Parent $PSScriptRoot) 'tstack\main.py'
    $agentsPython = Find-Python
    if ($agentsPython -and (Test-Path -LiteralPath $agentsEntry)) {
        if ($wizard.Headroom -eq 'on') { & $agentsPython $agentsEntry agents headroom on $wizard.HeadroomCursor | Out-Host }
        if ($wizard.Caveman -eq 'on') { & $agentsPython $agentsEntry agents caveman on | Out-Host }
        if ($wizard.Agentmemory -eq 'on') { & $agentsPython $agentsEntry agents agentmemory on | Out-Host }
    } else {
        Write-Warning 'python3 not found; skipped the coding-agent wiring. Re-run: tstack config agents <tool> repair'
    }
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
# (Get-TsWorkspace in $PROFILE covers the detected case). Save-TsWorkspaceOverride
# lives in _config.ps1 so `tstack config wizard` persists the answer the same way.
if ($PSCmdlet.ShouldProcess('Documents\PowerShell\profile.local.ps1', "persist WORKSPACE_DIR=$($wizard.Workspace)")) {
    Save-TsWorkspaceOverride $wizard.Workspace
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
