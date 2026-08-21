# install-tts-daemon.ps1 — build and install the console-free TTS executable.
#
# Python is a build-time dependency only. Runtime hooks and autostart invoke
# terminal-stack-tts.exe directly; no python.exe, cmd.exe, PowerShell, ffplay,
# or ffprobe process is involved when a hook speaks.

[CmdletBinding()]
param(
    [switch]$Uninstall,
    [switch]$Purge,
    [switch]$NoStart,
    [switch]$NoAutostart
)

$ErrorActionPreference = 'Stop'

$daemonRoot = Join-Path $env:LOCALAPPDATA 'terminal-stack\tts-daemon'
$exePath = Join-Path $daemonRoot 'terminal-stack-tts.exe'
$previousPath = Join-Path $daemonRoot 'terminal-stack-tts.previous.exe'
$legacyVenv = Join-Path $daemonRoot 'venv'
$legacyLauncher = Join-Path $daemonRoot 'run-daemon.cmd'
$runKeyPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$runKeyName = 'terminal-stack-tts-daemon'
$buildScript = Join-Path $PSScriptRoot 'tts-daemon\build.ps1'

function Get-TtsdPort {
    $cfg = Join-Path $env:USERPROFILE '.claude\tts\config.json'
    if (Test-Path -LiteralPath $cfg) {
        try {
            $port = (Get-Content -LiteralPath $cfg -Raw | ConvertFrom-Json).daemon.port
            if ($port) { return [int]$port }
        } catch {}
    }
    return 8890
}

function Test-TtsdHealthy {
    param([int]$Port)
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/healthz" `
            -TimeoutSec 2 -UseBasicParsing
        return ($response.StatusCode -eq 200)
    } catch { return $false }
}

function Stop-Ttsd {
    param([int]$Port)
    if (-not (Test-TtsdHealthy -Port $Port)) { return }
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$Port/v1/duck/release" `
            -Method Post -TimeoutSec 3 -UseBasicParsing | Out-Null
    } catch {}
    try {
        Invoke-WebRequest -Uri "http://127.0.0.1:$Port/v1/shutdown" `
            -Method Post -TimeoutSec 3 -UseBasicParsing | Out-Null
    } catch {}
    foreach ($attempt in 1..20) {
        if (-not (Test-TtsdHealthy -Port $Port)) { return }
        Start-Sleep -Milliseconds 250
    }
    throw "The existing TTS daemon did not stop on port $Port."
}

function Assert-ManagedPath {
    param([string]$Path)
    $root = [IO.Path]::GetFullPath($daemonRoot).TrimEnd('\')
    $candidate = [IO.Path]::GetFullPath($Path)
    if (-not $candidate.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to modify a path outside the TTS install: $candidate"
    }
}

function Remove-LegacyRuntime {
    foreach ($path in @($legacyLauncher, $legacyVenv)) {
        Assert-ManagedPath -Path $path
        if (Test-Path -LiteralPath $path) {
            $item = Get-Item -LiteralPath $path -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing to remove legacy runtime reparse point: $path"
            }
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
}

$port = Get-TtsdPort

if ($Uninstall) {
    Stop-Ttsd -Port $port
    try {
        Remove-ItemProperty -Path $runKeyPath -Name $runKeyName -ErrorAction Stop
    } catch {}
    if ($Purge) {
        foreach ($path in @($exePath, $previousPath, $legacyLauncher, $legacyVenv)) {
            Assert-ManagedPath -Path $path
            if (-not (Test-Path -LiteralPath $path)) { continue }
            $item = Get-Item -LiteralPath $path -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Refusing to purge reparse point: $path"
            }
            Remove-Item -LiteralPath $path -Recurse -Force
        }
    }
    Write-Host 'tts daemon: stopped and removed from autostart' -ForegroundColor Green
    if (-not $Purge) { Write-Host "  executable kept at $exePath; -Purge removes it" }
    exit 0
}

if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw "TTS build script not found: $buildScript"
}

# Build and validate before disturbing a running installation.
$stageDir = Join-Path $env:TEMP ("terminal-stack-tts-stage-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stageDir | Out-Null
try {
    Write-Host 'Building terminal-stack-tts.exe (Python is used only for this build) ...'
    & $buildScript -OutputDirectory $stageDir
    if ($LASTEXITCODE -ne 0) { throw 'TTS executable build failed.' }
    $stagedExe = Join-Path $stageDir 'terminal-stack-tts.exe'
    if (-not (Test-Path -LiteralPath $stagedExe -PathType Leaf)) {
        throw "Build did not produce $stagedExe"
    }
    $validation = Start-Process -FilePath $stagedExe -ArgumentList 'version' `
        -WindowStyle Hidden -Wait -PassThru
    if ($validation.ExitCode -ne 0) {
        throw "Built TTS executable failed validation (exit $($validation.ExitCode))."
    }

    New-Item -ItemType Directory -Path $daemonRoot -Force | Out-Null
    Stop-Ttsd -Port $port

    $newPath = Join-Path $daemonRoot 'terminal-stack-tts.new.exe'
    Assert-ManagedPath -Path $newPath
    Copy-Item -LiteralPath $stagedExe -Destination $newPath -Force
    try {
        if (Test-Path -LiteralPath $previousPath) {
            Remove-Item -LiteralPath $previousPath -Force
        }
        if (Test-Path -LiteralPath $exePath) {
            Move-Item -LiteralPath $exePath -Destination $previousPath
        }
        Move-Item -LiteralPath $newPath -Destination $exePath
    } catch {
        if ((-not (Test-Path -LiteralPath $exePath)) `
                -and (Test-Path -LiteralPath $previousPath)) {
            Move-Item -LiteralPath $previousPath -Destination $exePath
        }
        throw
    }

    if (-not $NoAutostart) {
        New-ItemProperty -Path $runKeyPath -Name $runKeyName `
            -Value "`"$exePath`" daemon" -PropertyType String -Force | Out-Null
    } else {
        try {
            Remove-ItemProperty -Path $runKeyPath -Name $runKeyName -ErrorAction Stop
        } catch {}
    }

    # Best effort: loopback always works; WSL NAT needs this inbound rule.
    $ruleName = 'terminal-stack ttsd (WSL)'
    if (-not (Get-NetFirewallRule -DisplayName $ruleName -ErrorAction SilentlyContinue)) {
        try {
            New-NetFirewallRule -DisplayName $ruleName -Direction Inbound -Action Allow `
                -Protocol TCP -LocalPort $port -RemoteAddress 172.16.0.0/12 `
                -Profile Any -ErrorAction Stop | Out-Null
            Write-Host "Firewall rule added for WSL to daemon (port $port)."
        } catch {
            Write-Host 'Note: WSL firewall rule was not added (admin is required).' `
                -ForegroundColor Yellow
        }
    }

    if (-not $NoStart) {
        Start-Process -FilePath $exePath -ArgumentList 'daemon' -WindowStyle Hidden
        $healthy = $false
        foreach ($attempt in 1..30) {
            Start-Sleep -Milliseconds 500
            if (Test-TtsdHealthy -Port $port) { $healthy = $true; break }
        }
        if (-not $healthy) {
            throw "Daemon did not answer /healthz; check $daemonRoot\logs\ttsd.log"
        }
        Write-Host "tts daemon: running on http://127.0.0.1:$port" `
            -ForegroundColor Green
    } else {
        Write-Host "tts executable: installed at $exePath" -ForegroundColor Green
    }

    # For daemon installs this is deliberately after the health probe. Direct
    # installs have already passed the packaged command validation above.
    Remove-LegacyRuntime
} finally {
    $resolvedTemp = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\')
    $resolvedStage = [IO.Path]::GetFullPath($stageDir)
    if ($resolvedStage.StartsWith($resolvedTemp + '\', [StringComparison]::OrdinalIgnoreCase) `
            -and (Split-Path -Leaf $resolvedStage) -like 'terminal-stack-tts-stage-*' `
            -and (Test-Path -LiteralPath $resolvedStage -PathType Container)) {
        Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
}
