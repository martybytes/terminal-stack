param(
    [Parameter(Mandatory)][ValidateSet('notification', 'permission', 'question')][string]$Event,
    [string]$Source = 'claude'
)

$inputJson = ''
try {
    if ([Console]::IsInputRedirected) {
        $inputJson = [Console]::In.ReadToEnd()
    }
} catch {}

. (Join-Path $PSScriptRoot 'cc-tts-lib.ps1')
$parsed = Parse-CcTtsInputHook -InputJson $inputJson -Event $Event

# Daemon first; direct path below is the fallback — never silence.
if (Test-CcTtsDaemonReady) {
    if (Send-CcTtsDaemonEvent -Source $Source -Event $Event -State $parsed.State -InputJson $inputJson -Override $parsed.Override) {
        return
    }
}

$notify = Join-Path $PSScriptRoot 'cc-tts-notify.ps1'
$args = @(
    '-NoLogo', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', $notify,
    '-State', $parsed.State,
    '-Source', $Source
)
if ($parsed.Override) { $args += @('-OverrideText', $parsed.Override) }
Start-Process pwsh.exe -ArgumentList $args -WindowStyle Hidden | Out-Null
