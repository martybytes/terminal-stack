<#
.NAME        setup-kokoro-docker
.SYNOPSIS    Create (or start) a local Kokoro TTS container reachable at http://127.0.0.1:8880, GPU-accelerated by default. Previews by default; -Undo removes it (still needs -Apply).
.PLATFORM    windows
.USAGE       .\setup-kokoro-docker.ps1 [-Cpu] [-GpuTag <tag>] [-Port <int>] [-ContainerName <name>] [-Apply] [-Undo]
.WHEN        Standing up (or tearing down) the local Kokoro TTS container. See README.md in this folder for the full writeup, including the Blackwell/GPU-tag gotcha this script works around.
.NOTE        docker-compose.yml is canonical in this repo; this script is the preview-mode escape hatch. It is a deliberate copy of claude-local/tools/windows/system/setup-kokoro-docker.ps1 — port changes to both. Both paths now bind 127.0.0.1 only.
#>
param(
    [switch]$Cpu,                    # use ghcr.io/remsky/kokoro-fastapi-cpu instead of the GPU image (avoids sharing the display GPU)
    [string]$GpuTag = 'v0.8.0-cu128', # GPU image tag; default targets Blackwell (RTX 50-series, sm_120) - the ':latest' tag ships cu126 and lacks sm_120 kernels ("no kernel image is available"). Use 'v0.8.0-cu126' on GTX 900-RTX 40 series cards.
    [int]$Port = 8880,
    [string]$ContainerName = 'kokoro',
    [switch]$Apply,                  # write switch; without it, preview only
    [switch]$Undo                    # remove the container instead of creating it (still requires -Apply to act)
)

$ErrorActionPreference = 'Stop'
$execute = $Apply
$mode    = if ($Undo -and $Apply) { 'UNDO' } elseif ($Apply) { 'APPLY' } else { 'PREVIEW' }
$image   = if ($Cpu) { 'ghcr.io/remsky/kokoro-fastapi-cpu:latest' } else { "ghcr.io/remsky/kokoro-fastapi-gpu:$GpuTag" }

function Section([string]$t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Step([string]$t)    { $tag = if ($execute) { '[DO]  ' } else { '[would]' }; Write-Host "$tag $t" -ForegroundColor ($(if ($execute) { 'Green' } else { 'Yellow' })) }
function Info([string]$t)    { Write-Host "       $t" -ForegroundColor DarkGray }
function Have([string]$c)    { [bool](Get-Command $c -ErrorAction SilentlyContinue) }

Write-Host "setup-kokoro-docker  mode=$mode  image=$image  port=$Port" -ForegroundColor White
if (-not $execute) { Write-Host '(preview only — re-run with -Apply to perform, or -Undo -Apply to remove)' -ForegroundColor DarkGray }

if (-not (Have 'docker')) { throw 'docker CLI not found on PATH — install/launch Docker Desktop first.' }
$null = & docker info 2>&1
if ($LASTEXITCODE -ne 0) { throw 'Docker daemon not responding — is Docker Desktop running?' }

if (-not $Undo -and -not $Cpu -and (Have 'nvidia-smi')) {
    Section 'GPU headroom'
    (& nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader 2>$null) -split "`n" |
        Where-Object { $_ } | ForEach-Object { Info $_ }
    Info 'this container will share the display GPU if one drives your monitors — see README.md'
}

Section 'Container status'
$existingRows = @((& docker ps -a --filter "name=^$ContainerName`$" --format '{{.Names}}|{{.Status}}' 2>$null) -split "`n" | Where-Object { $_ })
$existingLine = $existingRows[0]

if ($Undo) {
    if (-not $existingLine) {
        Info "no container named '$ContainerName' — nothing to remove"
    } else {
        $name, $status = $existingLine -split '\|', 2
        Step "docker rm -f $name  (removes the container; the pulled image stays cached — 'docker rmi $image' to reclaim disk)"
        if ($execute) {
            & docker rm -f $name *> $null
            Info 'removed'
        }
    }
} else {
    if ($existingLine) {
        $name, $status = $existingLine -split '\|', 2
        if ($status -like 'Up*') {
            Info "'$name' already running ($status) — nothing to do"
        } else {
            Step "docker start $name  (existing container is stopped: $status)"
            if ($execute) { & docker start $name *> $null; Info 'started' }
        }
    } else {
        Step "docker pull $image"
        if ($execute) {
            & docker pull $image
            if ($LASTEXITCODE -ne 0) { throw "docker pull failed for $image" }
        }

        $gpuArgs = if ($Cpu) { @() } else { @('--gpus', 'all') }
        $runArgs = @('run', '-d', '--name', $ContainerName, '--restart', 'unless-stopped') + $gpuArgs + @('-p', "127.0.0.1:${Port}:8880", $image)
        Step ("docker " + ($runArgs -join ' '))
        if ($execute) {
            & docker @runArgs
            if ($LASTEXITCODE -ne 0) { throw "docker run failed for $ContainerName" }
            Info "created '$ContainerName'"
        }
    }
}

if (-not $Undo) {
    Section 'Verification'
    if ($execute) {
        Info 'waiting for the app to come up...'
        $ok = $false
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Seconds 1
            $state = (& docker inspect $ContainerName --format '{{.State.Status}}' 2>$null)
            if ($state -eq 'exited' -or $state -eq 'restarting') { break }
            if (-not (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)) { continue }
            try {
                $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/docs" -UseBasicParsing -TimeoutSec 3
                if ($resp.StatusCode -eq 200) { $ok = $true; break }
            } catch { }
        }
        if ($ok) {
            Info "http://127.0.0.1:$Port/docs responded 200 — Kokoro is up"
        } else {
            Info 'not responding yet — recent container logs:'
            (& docker logs --tail 20 $ContainerName 2>&1) -split "`n" | ForEach-Object { Info "  $_" }
        }
    } else {
        Info "after -Apply, verify with: Invoke-WebRequest http://127.0.0.1:$Port/docs"
    }
}

Write-Host ''
if (-not $execute) { Write-Host 'Nothing changed (preview). Add -Apply to perform, or -Undo -Apply to remove.' -ForegroundColor White }
else { Write-Host "Done ($mode)." -ForegroundColor Green }
