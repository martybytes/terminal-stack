# _merge_cursor_settings.ps1 — shallow-merge stack-owned Cursor IDE terminal keys
# from windows\AppData\Roaming\Cursor\User\terminal-stack.terminal.json
# into %APPDATA%\Cursor\User\settings.json (backup before write).
# Invoked by scripts\sync-windows.ps1 and run_after_90-sync-windows.sh.
#
# The textual key-splice engine lives in _merge_json_settings.ps1 (shared with
# _merge_claude_settings.ps1); this file is the Cursor-specific front end: where the
# fragment and the live file are, and the __PWSH_EXE__ / __GIT_CMD_DIR__ expansion.

$tsMergeEngine = Join-Path $PSScriptRoot '_merge_json_settings.ps1'
if (-not (Test-Path -LiteralPath $tsMergeEngine)) {
    throw "merge-cursor-settings: splice engine not found: $tsMergeEngine"
}
. $tsMergeEngine

# ---- environment resolution ------------------------------------------------
# The fragment ships __TOKEN__ placeholders rather than literal paths: pwsh may be
# under Program Files, Program Files (x86), or a per-user winget/Store install in
# %LOCALAPPDATA%\Microsoft\WindowsApps, and Git may be per-user too.

function Resolve-TsPwshPath {
    $cmd = Get-Command pwsh.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and $cmd.Source) { return $cmd.Source }
    foreach ($p in @(
        (Join-Path $env:ProgramFiles 'PowerShell\7\pwsh.exe'),
        (Join-Path $env:ProgramFiles 'PowerShell\7-preview\pwsh.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'PowerShell\7\pwsh.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps\pwsh.exe')
    )) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    return 'pwsh.exe'   # last resort: rely on PATH
}

function Resolve-TsGitCmdDir {
    # Prefer <install root>/cmd. Get-Command often finds git.exe in mingw64/bin,
    # which is the wrong thing to put on PATH: it is full of MSYS DLLs and ships a
    # curl.exe that shadows Windows' own System32/curl.exe. <root>/cmd holds just
    # git/gitk/git-lfs/scalar and is the directory Git for Windows means for PATH.
    $cmd = Get-Command git.exe -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($cmd -and $cmd.Source) {
        $probe = Split-Path -Parent $cmd.Source
        for ($i = 0; $i -lt 3 -and $probe; $i++) {
            $candidate = Join-Path $probe 'cmd'
            if (Test-Path -LiteralPath (Join-Path $candidate 'git.exe')) { return $candidate }
            $probe = Split-Path -Parent $probe
        }
        return (Split-Path -Parent $cmd.Source)   # non-standard layout: use what we found
    }
    foreach ($p in @(
        (Join-Path $env:ProgramFiles 'Git\cmd'),
        (Join-Path ${env:ProgramFiles(x86)} 'Git\cmd'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Git\cmd')
    )) {
        if ($p -and (Test-Path -LiteralPath $p)) { return $p }
    }
    return $null
}

function Expand-TsFragmentTokens([string]$text) {
    $text = $text -replace '__PWSH_EXE__', (ConvertTo-TsJsonStringBody (Resolve-TsPwshPath))
    $gitDir = Resolve-TsGitCmdDir
    if ($gitDir) {
        return $text -replace '__GIT_CMD_DIR__', (ConvertTo-TsJsonStringBody $gitDir)
    }
    # No Git found: drop the prefix and its separator rather than emit ";${env:Path}".
    return ($text -replace '__GIT_CMD_DIR__;', '') -replace '__GIT_CMD_DIR__', ''
}

# ---- entry point ------------------------------------------------------------

function Merge-TsCursorSettings {
    [CmdletBinding()]
    param(
        [string]$FragmentPath,
        [string]$LivePath
    )

    if (-not $FragmentPath) {
        # Prefer the repo copy next to this script: %APPDATA% can be redirected
        # (roaming profile / OneDrive KFM) away from %USERPROFILE%\AppData\Roaming,
        # which would leave the mirrored fragment somewhere we never look.
        $candidates = @()
        if ($PSScriptRoot) {
            $candidates += (Join-Path $PSScriptRoot '..\windows\AppData\Roaming\Cursor\User\terminal-stack.terminal.json')
        }
        if ($env:APPDATA) { $candidates += (Join-Path $env:APPDATA 'Cursor\User\terminal-stack.terminal.json') }
        if ($env:USERPROFILE) { $candidates += (Join-Path $env:USERPROFILE 'AppData\Roaming\Cursor\User\terminal-stack.terminal.json') }
        foreach ($c in $candidates) {
            if (Test-Path -LiteralPath $c) { $FragmentPath = (Resolve-Path -LiteralPath $c).Path; break }
        }
    }
    if (-not $FragmentPath -or -not (Test-Path -LiteralPath $FragmentPath)) {
        Write-Warning 'merge-cursor-settings: fragment not found; skipping.'
        return
    }

    if (-not $LivePath) {
        $appData = $env:APPDATA
        if (-not $appData) {
            Write-Warning 'merge-cursor-settings: $env:APPDATA is unset; skipping.'
            return
        }
        # Only touch Cursor if Cursor is actually installed — otherwise we would
        # manufacture a phantom %APPDATA%\Cursor\User profile on every apply.
        $cursorRoot = Join-Path $appData 'Cursor'
        if (-not (Test-Path -LiteralPath $cursorRoot -PathType Container)) {
            Write-Host 'merge-cursor-settings: Cursor not installed; skipping.'
            return
        }
        $LivePath = Join-Path $appData 'Cursor\User\settings.json'
    }

    $fragText = Expand-TsFragmentTokens (Get-Content -LiteralPath $FragmentPath -Raw -Encoding UTF8)
    Merge-TsJsonSettings -FragmentPath $FragmentPath -LivePath $LivePath `
        -FragmentText $fragText -Label 'merge-cursor-settings'
}

if ($MyInvocation.InvocationName -ne '.') {
    Merge-TsCursorSettings @args
}
