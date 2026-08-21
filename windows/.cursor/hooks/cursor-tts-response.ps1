# cursor-tts-response.ps1 — Cursor afterAgentResponse → completion TTS.
$inputJson = ''
try {
    if ([Console]::IsInputRedirected) {
        $inputJson = [Console]::In.ReadToEnd()
    }
} catch {}

if (-not $inputJson) { Write-Output '{}'; return }
try {
    $data = $inputJson | ConvertFrom-Json
    if ($data.workspace_roots -and $data.workspace_roots.Count -gt 0) {
        $env:CURSOR_PROJECT_DIR = $data.workspace_roots[0]
    }
} catch { Write-Output '{}'; return }

. (Join-Path (Join-Path $env:USERPROFILE '.claude\hooks') 'cc-tts-lib.ps1')

if (Test-CcTtsDaemonReady) {
    if (Send-CcTtsDaemonEvent -Source cursor -Event cursor_response `
            -State waiting -InputJson $inputJson) {
        Write-Output '{}'
        return
    }
}

$cfg = Initialize-CcTtsConfig
if (-not $cfg -or -not $cfg.enabled -or -not (Test-CcTtsEventEnabled 'waiting')) {
    Write-Output '{}'
    return
}
$notify = Join-Path $env:USERPROFILE '.claude\hooks\cc-tts-notify.ps1'
if (-not (Test-Path -LiteralPath $notify)) { Write-Output '{}'; return }

$env:CC_TTS_HOOK_JSON = $inputJson
$args = @(
    '-NoLogo', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', $notify, '-State', 'waiting', '-Source', 'cursor'
)
if ($env:CURSOR_PROJECT_DIR) { $args += @('-ProjectDir', $env:CURSOR_PROJECT_DIR) }
Start-Process pwsh.exe -ArgumentList $args -WindowStyle Hidden | Out-Null
Write-Output '{}'
