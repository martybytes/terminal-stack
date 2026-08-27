# cc-tts-test.ps1 — end-to-end TTS test (synth + play).
#   -Daemon          POST a synthetic event to the ttsd daemon; expect it spoken.
#   -DaemonFallback  route cc-speak at a dead port; the direct path must still speak.
param(
    [string]$Source = 'test',
    [string]$Phrase = '',
    [switch]$Daemon,
    [switch]$DaemonFallback
)

. (Join-Path $PSScriptRoot 'cc-tts-lib.ps1')

if ($Daemon) {
    if (-not (Test-CcTtsDaemonReady)) {
        Write-Error 'daemon not enabled in config (tstack config tts daemon status)'
        exit 1
    }
    $hook = '{"session_id":"cc-tts-test","last_assistant_message":"Daemon test. <!-- speak: Daemon test successful. -->"}'
    if (Send-CcTtsDaemonEvent -Source $Source -Event stop -State waiting -InputJson $hook -Override 'Daemon test from cc-tts-test.') {
        Write-Host 'cc-tts-test: daemon accepted the event — expect speech shortly.'
        exit 0
    }
    Write-Error 'daemon did not accept the event (tstack config tts daemon status)'
    exit 1
}

if ($DaemonFallback) {
    Write-Host 'cc-tts-test: simulating a dead daemon (port 1) — direct playback must still sound.'
    $env:CC_TTS_DAEMON_PORT_OVERRIDE = '1'
    try {
        '{"session_id":"cc-tts-test-fallback"}' |
            & (Join-Path $PSScriptRoot 'cc-speak.ps1') -State waiting -OverrideText 'Fallback test: direct playback works.'
    } finally {
        Remove-Item Env:CC_TTS_DAEMON_PORT_OVERRIDE -ErrorAction SilentlyContinue
    }
    Write-Host 'cc-tts-test: fallback path invoked (listen for the phrase).'
    exit 0
}

$configPath = Join-Path $env:USERPROFILE '.claude\tts\config.json'
if (-not (Test-Path -LiteralPath $configPath)) {
    $configPath = Join-Path $env:USERPROFILE '.claude\tts.json'
}
if (-not (Test-Path -LiteralPath $configPath)) {
    Write-Error "Missing TTS config — run sync-windows or chezmoi apply"
    exit 1
}

$cfg = Initialize-CcTtsConfig
$k = $cfg.kokoro
Write-Host "cc-tts-test: source=$Source kokoro $($k.url) voice $($k.voice)"

try {
    $r = Invoke-WebRequest -Uri ($k.url.TrimEnd('/') + '/health') -TimeoutSec 2 -UseBasicParsing
    Write-Host "cc-tts-test: kokoro up ($($r.StatusCode))"
} catch {
    Write-Warning 'cc-tts-test: kokoro not reachable'
}

if (-not $Phrase) {
    $Phrase = Build-CcTtsSpeech -Source $Source -State waiting -Project (Split-Path -Leaf $PWD) -OverrideText ''
}
if (-not $Phrase) { $Phrase = 'Terminal stack TTS test.' }

Write-Host "cc-tts-test: phrase=$Phrase"
& (Join-Path $PSScriptRoot 'cc-tts-notify.ps1') -State waiting -Source $Source -OverrideText $Phrase -Foreground
Write-Host 'cc-tts-test: done.'
