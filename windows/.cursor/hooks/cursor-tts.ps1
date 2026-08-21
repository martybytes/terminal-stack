# cursor-tts.ps1 — Cursor Agent stop hook → error TTS.
$inputJson = ''
try {
    if ([Console]::IsInputRedirected) {
        $inputJson = [Console]::In.ReadToEnd()
    }
} catch {}

$state = 'error'
if ($inputJson) {
    try {
        $data = $inputJson | ConvertFrom-Json
        switch ($data.status) {
            'error'   { $state = 'error'; break }
            'aborted' { Write-Output '{}'; return }
            default   { Write-Output '{}'; return }
        }
        if ($data.workspace_roots -and $data.workspace_roots.Count -gt 0) {
            $env:CURSOR_PROJECT_DIR = $data.workspace_roots[0]
        }
    } catch {}
}

. (Join-Path (Join-Path $env:USERPROFILE '.claude\hooks') 'cc-tts-lib.ps1')

# Daemon first (it holds/cools Cursor's per-turn stop storms); direct path
# below is the fallback — never silence.
if (Test-CcTtsDaemonReady) {
    if (Send-CcTtsDaemonEvent -Source cursor -Event cursor_stop -State $state -InputJson $inputJson) {
        Write-Output '{}'
        return
    }
}

$cfg = Initialize-CcTtsConfig
if (-not $cfg -or -not $cfg.enabled) { Write-Output '{}'; return }
if (-not (Test-CcTtsEventEnabled $state)) { Write-Output '{}'; return }

$notify = Join-Path $env:USERPROFILE '.claude\hooks\cc-tts-notify.ps1'
if (-not (Test-Path -LiteralPath $notify)) {
    Write-Output '{}'
    return
}

$args = @(
    '-NoLogo', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', $notify,
    '-State', $state,
    '-Source', 'cursor'
)
if ($env:CURSOR_PROJECT_DIR) {
    $args += @('-ProjectDir', $env:CURSOR_PROJECT_DIR)
}

Start-Process pwsh.exe -ArgumentList $args -WindowStyle Hidden | Out-Null
Write-Output '{}'
