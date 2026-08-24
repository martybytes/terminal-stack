<#
.NAME        stack
.SYNOPSIS    Drive every Docker stack in this repo from one place — list, status, up, down, logs. Read-only actions run immediately; -Up and -Down preview unless you pass -Apply.
.PLATFORM    windows
.USAGE       .\stack.ps1 [-List|-Status|-Up|-Down|-Logs] [-Stack <name>] [-Tail <int>] [-Follow] [-Apply]
.WHEN        Day-to-day: bringing the local stacks up after a reboot, checking what's healthy, or tailing a container that misbehaves. Run .\bootstrap.ps1 first on a new machine.
#>
param(
    [string]$Stack,          # limit to one stack (directory name); default is all
    [switch]$List,           # default action: one line per stack
    [switch]$Status,         # docker compose ps per stack
    [switch]$Up,             # docker compose up -d       (needs -Apply)
    [switch]$Down,           # docker compose down        (needs -Apply)
    [switch]$Logs,           # docker compose logs
    [int]$Tail = 50,         # lines of history for -Logs
    [switch]$Follow,         # -Logs: follow (implies a single stack)
    [switch]$Apply           # write switch; without it, -Up/-Down preview only
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

function Section([string]$t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Step([string]$t)    { $tag = if ($Apply) { '[DO]  ' } else { '[would]' }; Write-Host "$tag $t" -ForegroundColor ($(if ($Apply) { 'Green' } else { 'Yellow' })) }
function Info([string]$t)    { Write-Host "       $t" -ForegroundColor DarkGray }
function Warn([string]$t)    { Write-Host "  !    $t" -ForegroundColor Yellow }
function Have([string]$c)    { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

if (-not (Have 'docker')) { throw 'docker CLI not found on PATH — install/launch Docker Desktop first.' }
$null = & docker info 2>&1
if ($LASTEXITCODE -ne 0) { throw 'Docker daemon not responding — is Docker Desktop running?' }

# A "stack" is any top-level directory holding a docker-compose.yml. New stacks
# need no registration here — drop the directory in and it is picked up.
$stacks = @(Get-ChildItem -Path $root -Directory |
    Where-Object { Test-Path (Join-Path $_.FullName 'docker-compose.yml') } |
    Sort-Object Name)

if ($Stack) {
    $stacks = @($stacks | Where-Object { $_.Name -eq $Stack })
    if (-not $stacks) { throw "no stack named '$Stack' — run .\stack.ps1 -List to see what exists" }
}
if (-not $stacks) { throw "no stacks found under $root" }

# Default action
if (-not ($List -or $Status -or $Up -or $Down -or $Logs)) { $List = $true }
if ($Follow -and $stacks.Count -gt 1) { throw '-Follow needs a single stack — pass -Stack <name>' }

# Which compose files a stack will actually merge, per its .env. `docker compose
# ls` reports the files a project was *created* with, which goes stale the moment
# you add an overlay — so read the current intent instead.
function Get-ComposeFiles($dir) {
    $sep = ':'
    $spec = $null
    $envFile = Join-Path $dir '.env'
    if (Test-Path $envFile) {
        foreach ($line in (Get-Content $envFile)) {
            if ($line -match '^\s*COMPOSE_PATH_SEPARATOR\s*=\s*(.+?)\s*$') { $sep  = $Matches[1] }
            if ($line -match '^\s*COMPOSE_FILE\s*=\s*(.+?)\s*$')           { $spec = $Matches[1] }
        }
    }
    if (-not $spec) { return @('docker-compose.yml') }
    return @($spec -split [regex]::Escape($sep) | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

# A stack that ships a .env.example but has no .env is misconfigured: compose
# silently falls back to the base file only, which for kokoro means starting the
# GPU image with no GPU access. Surface it on every action.
function Test-EnvSeeded($dir) {
    $ex = Join-Path $dir '.env.example'
    $en = Join-Path $dir '.env'
    if ((Test-Path $ex) -and -not (Test-Path $en)) { return $false }
    return $true
}

foreach ($s in $stacks) {
    if (-not (Test-EnvSeeded $s.FullName)) {
        Warn "$($s.Name): .env.example exists but .env does not — run .\bootstrap.ps1 -Apply first, or this stack will start with the wrong profile"
    }
}

foreach ($s in $stacks) {
    Push-Location $s.FullName
    try {
        if ($List) {
            $files = Get-ComposeFiles $s.FullName
            $running = @((& docker compose ps -q --status running 2>$null) -split "`n" | Where-Object { $_.Trim() }).Count
            $total   = @((& docker compose ps -aq 2>$null) -split "`n" | Where-Object { $_.Trim() }).Count
            $state   = if ($total -eq 0) { 'not created' } elseif ($running -eq $total) { "running ($running/$total)" } else { "partial ($running/$total)" }
            $colour  = if ($total -eq 0) { 'DarkGray' } elseif ($running -eq $total) { 'Green' } else { 'Yellow' }
            Write-Host ('{0,-14} {1}' -f $s.Name, $state) -ForegroundColor $colour
            Info ("compose files: " + ($files -join ' + '))
        }

        if ($Status) {
            Section $s.Name
            & docker compose ps
        }

        if ($Logs) {
            Section "$($s.Name) logs"
            if ($Follow) { & docker compose logs --tail $Tail -f }
            else         { & docker compose logs --tail $Tail }
        }

        if ($Up) {
            Section $s.Name
            Step 'docker compose up -d'
            if ($Apply) {
                & docker compose up -d
                if ($LASTEXITCODE -ne 0) { Warn "up failed for $($s.Name) — see the output above" }
            }
        }

        if ($Down) {
            Section $s.Name
            Step 'docker compose down   (containers only; named volumes and cached images are kept)'
            if ($Apply) {
                & docker compose down
                if ($LASTEXITCODE -ne 0) { Warn "down failed for $($s.Name) — see the output above" }
            }
        }
    }
    finally { Pop-Location }
}

Write-Host ''
if (($Up -or $Down) -and -not $Apply) {
    Write-Host 'Nothing changed (preview). Add -Apply to perform.' -ForegroundColor White
} elseif ($Up -or $Down) {
    Write-Host 'Done. Verify with: .\stack.ps1 -Status' -ForegroundColor Green
}
