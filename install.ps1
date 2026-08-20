# install.ps1 — one-liner Windows installer for the terminal-stack.
# Usage (from a fresh box, PowerShell 7+):
#   irm https://raw.githubusercontent.com/martybytes/terminal-stack/main/install.ps1 | iex
#
# Optional: override the clone location before invoking.
#   $env:TERMINAL_STACK_DIR = 'D:\dotfiles\terminal-stack'; irm ... | iex
# Two caveats on that override: a target inside a workspace root is refused by
# default (wso migrate would relocate it), and a pin already persisted in
# profile.local.ps1 with no clone behind it is treated as a leftover and ignored
# -- $PROFILE sets that variable in every session, so it is not evidence of intent.
#
# What it does:
#   1. Verifies winget is available (App Installer).
#   2. Ensures Git is installed (winget Git.Git if missing).
#   3. Clones github.com/martybytes/terminal-stack to $TERMINAL_STACK_DIR
#      (default: %LOCALAPPDATA%\terminal-stack\stack — the app-data dir the
#      stack already owns). git pull if already cloned; an existing clone at a
#      legacy location is offered a move to the canonical path instead.
#   4. Runs bootstrap\windows-bootstrap.ps1 from the clone.
#   5. Prints the WSL one-liner for the next step (chezmoi apply runs in WSL).

$ErrorActionPreference = 'Stop'

Write-Host '==> terminal-stack Windows installer'

if ($PSVersionTable.PSVersion.Major -lt 7) {
    Write-Warning "Running under PowerShell $($PSVersionTable.PSVersion). PowerShell 7+ is recommended; the stack's `$PROFILE` targets pwsh 7. Continuing."
}

# 1. winget preflight
try { & winget --version | Out-Null } catch {
    throw "winget not found. Install 'App Installer' from the Microsoft Store, then re-run."
}

# 2. Git
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host '==> Installing Git (winget Git.Git)'
    & winget install --id Git.Git --exact --silent --accept-source-agreements --accept-package-agreements 2>&1 |
        Select-Object -Last 3
    # Add Git to current session PATH so the clone below works without a new shell.
    $gitDir = Join-Path $env:ProgramFiles 'Git\cmd'
    if (Test-Path (Join-Path $gitDir 'git.exe')) {
        $env:Path = "$gitDir;$env:Path"
    }
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw "git not on PATH after install. Open a new pwsh window and re-run the installer."
    }
} else {
    Write-Host "==> git already present ($((Get-Command git).Source))"
}

# 3. Choose clone location (a live $env:TERMINAL_STACK_DIR skips the prompt), then clone.
# Canonical default: inside the app-data dir the stack already owns (see
# docs/decisions.md § "Runtime clone location"). Canonical needs no pin.
$repoUrl = 'https://github.com/martybytes/terminal-stack.git'
$defaultDir = Join-Path $env:LOCALAPPDATA 'terminal-stack\stack'

# Workspace roots, in probe order. Keep in sync with bootstrap\_workspace.ps1
# Get-TsWsRoot and the profile's Get-TsWorkspace — this copy exists because
# install.ps1 runs before any clone is on disk.
function Test-TsInWorkspaceRoot([string]$Path) {
    if (-not $Path) { return $false }
    $p = $Path.TrimEnd('\')
    foreach ($r in @(
        $env:WORKSPACE_DIR,
        'C:\DATA\Workspace',
        (Join-Path $env:USERPROFILE 'workspace'),
        (Join-Path $env:USERPROFILE 'Documents\Workspace')
    )) {
        if (-not $r) { continue }
        if (($p + '\') -like ($r.TrimEnd('\') + '\*')) { return $true }
    }
    return $false
}
# A dev clone at a wso tier path is a deliberate choice, not an accident.
# Twin of bootstrap\_cleanup.ps1 Test-TsDevClone.
function Test-TsDevClonePath([string]$Path) {
    ($Path -replace '\\', '/') -match '/(src|public|archive|local|scratch)/[^/]+\.[^/]+/[^/]+/[^/]+/?$'
}

$pin = $env:TERMINAL_STACK_DIR
if ($pin) {
    # profile.local.ps1 is dot-sourced by $PROFILE, so a pin written by an earlier
    # install is present in EVERY pwsh session — `irm ... | iex` never sees a clean
    # environment. A value that matches that persisted line is therefore not a
    # deliberate override, and is only worth honouring while a clone still lives
    # there. A pin exported for this run alone is untouched.
    $plps = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\profile.local.ps1'
    $pinPattern = "^\s*\`$env:TERMINAL_STACK_DIR\s*=\s*['`"]?" + [regex]::Escape($pin.TrimEnd('\'))
    $persisted = (Test-Path $plps) -and
                 [bool]((Get-Content $plps) | Where-Object { $_ -match $pinPattern })
    if ($persisted -and -not (Test-Path (Join-Path $pin '.git'))) {
        Write-Host "==> ignoring a stale `$env:TERMINAL_STACK_DIR pin ($pin — no clone there)"
        Write-Host "    the line in $plps is removed once the clone lands at the canonical path."
        $env:TERMINAL_STACK_DIR = $null
        $pin = $null
    }
}

if ($pin) {
    $targetDir = $pin
    Write-Host "==> Clone location: $targetDir (from `$env:TERMINAL_STACK_DIR)"
} elseif ([Console]::IsInputRedirected) {
    # No one to answer (CI, a piped host). Read-Host would block on a pipe that
    # never closes rather than returning the default.
    $targetDir = $defaultDir
    Write-Host "==> Clone location: $targetDir (non-interactive)"
} else {
    $answer = Read-Host "Where should the terminal-stack repo live? [$defaultDir]"
    $targetDir = if ($answer) { $answer.Trim() } else { $defaultDir }
}

# The runtime clone must not live inside a workspace root: `wso migrate` derives
# a repo's destination from its origin and will happily relocate it to a tier
# path, orphaning the install. That has happened. Dev-clone tier paths are
# exempt — pinning one is deliberate (docs/decisions.md § "Runtime clone location").
if ((Test-TsInWorkspaceRoot $targetDir) -and -not (Test-TsDevClonePath $targetDir)) {
    Write-Host ''
    Write-Warning "$targetDir is inside a workspace root."
    Write-Host "    'wso migrate' can relocate it out from under the install."
    if ([Console]::IsInputRedirected) {
        Write-Host "==> non-interactive: using the canonical location $defaultDir instead."
        $targetDir = $defaultDir
    } else {
        $a = Read-Host "  Use $defaultDir instead? [Y/n]"
        if ($a -notmatch '^(n|no)$') {
            $targetDir = $defaultDir
            Write-Host "==> Clone location: $targetDir"
        } else {
            Write-Host "==> keeping $targetDir — re-run 'wso plan' after any workspace migration."
        }
    }
    Write-Host ''
}

# 3a. An existing clone at a legacy location: pull it first (that lands the
# move routine inside it), then offer to move it to the target instead of
# cloning fresh — preserves history, stashes, and any dirty state.
# Minimal legacy scan; master list: bootstrap\_cleanup.ps1 Get-TsCleanupCloneCandidates.
if (-not (Test-Path (Join-Path $targetDir '.git'))) {
    $legacy = $null
    foreach ($d in @(
        (Join-Path $env:USERPROFILE 'code\terminal-stack'),
        (Join-Path $env:USERPROFILE 'terminal-stack'),
        (Join-Path $env:USERPROFILE 'Workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE 'workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE 'Documents\Workspace\terminal-stack'),
        (Join-Path $env:USERPROFILE '.local\share\chezmoi'),
        'C:\DATA\Workspace\terminal-stack'
    )) {
        if (-not (Test-Path (Join-Path $d '.git'))) { continue }
        # Name alone isn't enough — check the origin, like the bash twin does.
        if ((& git -C $d config --get remote.origin.url 2>$null) -notmatch 'terminal-stack') { continue }
        $legacy = $d; break
    }
    if ($legacy) {
        Write-Host "==> Existing clone found at $legacy"
        # Default [M]ove without asking when there is no one to ask — Read-Host
        # blocks on a pipe rather than returning empty.
        $choice = if ([Console]::IsInputRedirected) { '' } else {
            Read-Host "  [M]ove it to $targetDir / [K]eep it there / [F]resh clone at the new location? [M]"
        }
        switch -Regex ($choice) {
            '^(k|keep)$'  { $targetDir = $legacy; Write-Host "==> Keeping $legacy" }
            '^(f|fresh)$' { }
            default {
                & git -C $legacy pull --ff-only 2>$null | Out-Null
                $legacyCleanup = Join-Path $legacy 'bootstrap\_cleanup.ps1'
                if (Test-Path $legacyCleanup) { . $legacyCleanup }
                if (Get-Command Move-TsClone -ErrorAction SilentlyContinue) {
                    if (-not (Move-TsClone -Source $legacy -Dest $targetDir)) {
                        Write-Warning 'Move failed; falling back to a fresh clone.'
                    }
                } else {
                    Write-Warning 'This clone predates the move routine; cloning fresh instead (old clone offered for cleanup later).'
                }
            }
        }
    }
}

if (Test-Path (Join-Path $targetDir '.git')) {
    Write-Host "==> Repo already at $targetDir; git pull"
    & git -C $targetDir pull --ff-only
} else {
    Write-Host "==> Cloning $repoUrl -> $targetDir"
    & git clone $repoUrl $targetDir
}

# 3b. Offer to clean up old clones + retired leftover files (pre-ticked checklist;
# confirms before removing). Also persist a non-default clone path so ts-update /
# ts-config can find it later.
$cleanup = Join-Path $targetDir 'bootstrap\_cleanup.ps1'
if (Test-Path $cleanup) {
    . $cleanup
    Invoke-TsCleanupMenu $targetDir
}
# Pins are only for NON-canonical locations; the canonical path resolves on its
# own, and a stale pin there would shadow future relocations.
if ($targetDir.TrimEnd('\') -ne $defaultDir.TrimEnd('\')) {
    $localProfile = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'PowerShell\profile.local.ps1'
    New-Item -ItemType Directory -Force -Path (Split-Path $localProfile) | Out-Null
    $line = "`$env:TERMINAL_STACK_DIR = '$targetDir'"
    if ((Test-Path $localProfile) -and (Get-Content $localProfile | Where-Object { $_ -match '^\s*\$env:TERMINAL_STACK_DIR\s*=' })) {
        (Get-Content $localProfile) -replace '^\s*\$env:TERMINAL_STACK_DIR\s*=.*', $line | Set-Content $localProfile
    } else {
        Add-Content -Path $localProfile -Value $line
    }
    Write-Host "==> persisted `$env:TERMINAL_STACK_DIR = $targetDir to $localProfile"
} elseif (Get-Command Clear-TsSourceDirPin -ErrorAction SilentlyContinue) {
    Clear-TsSourceDirPin
}

# 4. Bootstrap (winget packages + binaries)
$bootstrap = Join-Path $targetDir 'bootstrap\windows-bootstrap.ps1'
if (-not (Test-Path $bootstrap)) {
    throw "Expected bootstrap script not found at $bootstrap"
}
Write-Host "==> Running $bootstrap"
& $bootstrap

# 5. Sync windows/** to %USERPROFILE% and docs/kb/** to
#    %LOCALAPPDATA%\terminal-stack\docs\kb\ (PowerShell-native equivalent of the WSL
#    run_after hook). Lands $PROFILE, .wezterm.lua, .claude\settings.json, doc topics, etc.
#    without needing WSL.
$sync = Join-Path $targetDir 'scripts\sync-windows.ps1'
if (Test-Path $sync) {
    Write-Host "==> Running $sync"
    & $sync -SourceDir $targetDir
} else {
    Write-Warning "$sync not found; Windows-side dotfiles were not applied."
}

# 5b. Health check (non-fatal): clone + config + $PROFILE marker; flags old clones.
if (Test-Path $cleanup) {
    . $cleanup
    Test-TsInstall -SourceDir $targetDir -Quiet | Out-Null
}

# 6. Next-step hint
Write-Host ''
Write-Host '==> Windows install done.'
Write-Host "    Clone: $targetDir"
Write-Host '    Update later from any pwsh window:  ts-update'
Write-Host ''
Write-Host '    If you also use WSL Ubuntu, apply the WSL-side dotfiles too:'
Write-Host '        curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-wsl.sh | bash'
Write-Host ''
Write-Host '    For native Linux / macOS hosts (run on that machine instead):'
Write-Host '        curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-linux.sh | bash'
Write-Host '        curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-mac.sh | bash'
