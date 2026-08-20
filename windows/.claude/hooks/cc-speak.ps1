param(
    [Parameter(Mandatory)][ValidateSet('waiting', 'error')][string]$State,
    [string]$OverrideText,
    [switch]$Foreground
)

$inputJson = ''
try {
    if ([Console]::IsInputRedirected) {
        $inputJson = [Console]::In.ReadToEnd()
    }
} catch {}

$notify = Join-Path $PSScriptRoot 'cc-tts-notify.ps1'
if ($Foreground) {
    $args = @('-File', $notify, '-State', $State, '-Source', 'claude', '-Foreground')
    if ($OverrideText) { $args += @('-OverrideText', $OverrideText) }
    pwsh.exe -NoLogo -NonInteractive -ExecutionPolicy Bypass @args
    return
}

. (Join-Path $PSScriptRoot 'cc-tts-lib.ps1')

# Daemon first: session-aware queueing/coalescing/ducking. Any failure falls
# back to the classic direct path below — never silence.
if (Test-CcTtsDaemonReady) {
    $event = if ($State -eq 'error') { 'stop_failure' } else { 'stop' }
    if (Send-CcTtsDaemonEvent -Source claude -Event $event -State $State -InputJson $inputJson -Override $OverrideText) {
        return
    }
}

$cfg = Initialize-CcTtsConfig
if (-not $cfg -or -not $cfg.enabled) { return }
if (-not (Test-CcTtsEventEnabled $State)) { return }

$project = if ($env:CLAUDE_PROJECT_DIR) { Split-Path -Leaf $env:CLAUDE_PROJECT_DIR } else { Split-Path -Leaf $PWD }
$text = if ($OverrideText) { $OverrideText } else { Build-CcTtsSpeech -Source claude -State $State -Project $project }
if (-not $text) { return }

$args = @(
    '-NoLogo', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', $notify,
    '-State', $State,
    '-Source', 'claude',
    '-Foreground',
    '-OverrideText', $text
)
Start-Process pwsh.exe -ArgumentList $args -WindowStyle Hidden | Out-Null
