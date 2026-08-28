param(
    [Parameter(Mandatory)][ValidateSet('waiting', 'error', 'question', 'permission')][string]$State,
    [string]$OverrideText,
    [string]$ProjectDir,
    [string]$Source = 'claude',
    [switch]$Foreground
)

. (Join-Path $PSScriptRoot 'cc-tts-lib.ps1')

$cfg = Initialize-CcTtsConfig
if (-not $cfg) { return }
if (-not $cfg.enabled) { return }
if (-not (Test-CcTtsEventEnabled $State)) { return }

$project = if ($ProjectDir) {
    Split-Path -Leaf $ProjectDir
} elseif ($env:CURSOR_PROJECT_DIR) {
    Split-Path -Leaf $env:CURSOR_PROJECT_DIR
} elseif ($env:CLAUDE_PROJECT_DIR) {
    Split-Path -Leaf $env:CLAUDE_PROJECT_DIR
} else {
    Split-Path -Leaf $PWD
}

$text = Build-CcTtsSpeech -Source $Source -State $State -Project $project -OverrideText $OverrideText
if (-not $text) { return }

$cacheDir = Join-Path $env:LOCALAPPDATA 'terminal-stack'
$debounceFile = Join-Path $cacheDir 'cc-tts.last'
$lockFile = Join-Path $cacheDir 'cc-tts.play.lock'
if (-not (Test-Path $cacheDir)) { New-Item -ItemType Directory -Path $cacheDir -Force | Out-Null }

if (-not $Foreground) {
    $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $debounce = [int](Get-CcTtsConfigValue 'debounceSec' 5)
    if (Test-Path $debounceFile) {
        $last = [int64](Get-Content $debounceFile -ErrorAction SilentlyContinue)
        if (($now - $last) -lt $debounce) { return }
    }
    Set-Content -LiteralPath $debounceFile -Value $now -NoNewline
}

function Start-SpeakWorker([string]$SpeakText) {
    $ext = Get-CcTtsConfigValue 'kokoro.format' 'mp3'
    $out = Join-Path $env:TEMP ("cc-tts-{0}.{1}" -f [guid]::NewGuid().ToString('N'), $ext)
    try {
        # Every `return` below used to mean silence. SAPI is the floor: it needs
        # no engine, no file and no ffplay, so it is what "voice notifications
        # are on" degrades to instead of nothing.
        if (-not (Invoke-CcTtsSynth -Text $SpeakText -OutPath $out)) {
            [void](Invoke-CcTtsSapiSpeak -Text $SpeakText)
            return
        }
        if (-not (Test-Path -LiteralPath $out) -or (Get-Item $out).Length -eq 0) {
            [void](Invoke-CcTtsSapiSpeak -Text $SpeakText)
            return
        }
        $wait = 0
        while ((Test-Path $lockFile) -and ($wait -lt 30)) {
            Start-Sleep -Milliseconds 200
            $wait++
        }
        New-Item -ItemType File -Path $lockFile -Force | Out-Null
        $play = Join-Path $env:USERPROFILE '.claude\hooks\cc-tts-play.ps1'
        if (Test-Path -LiteralPath $play) { & $play -MediaPath $out }
        elseif (Get-Command ffplay -ErrorAction SilentlyContinue) {
            & ffplay -nodisp -autoexit -hide_banner -loglevel quiet $out 2>$null
        }
    } finally {
        Remove-Item $lockFile -ErrorAction SilentlyContinue
        Remove-Item $out -ErrorAction SilentlyContinue
    }
}

if ($Foreground) {
    Start-SpeakWorker $text
    return
}

$self = $MyInvocation.MyCommand.Path
$args = @(
    '-NoLogo', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', $self,
    '-State', $State,
    '-Source', $Source,
    '-Foreground'
)
if ($ProjectDir) { $args += @('-ProjectDir', $ProjectDir) }
$args += @('-OverrideText', $text)
Start-Process -FilePath 'pwsh.exe' -ArgumentList $args -WindowStyle Hidden | Out-Null
