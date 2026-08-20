# cursor-tts-input.ps1 — Cursor postToolUse when agent asks a question (AskQuestion).
$inputJson = ''
try {
    if ([Console]::IsInputRedirected) {
        $inputJson = [Console]::In.ReadToEnd()
    }
} catch {}

if ($inputJson) {
    try {
        $data = $inputJson | ConvertFrom-Json
        $tool = [string]$data.tool_name
        if ($tool -notin @('AskQuestion', 'AskUserQuestion')) {
            Write-Output '{}'
            return
        }
        if ($data.workspace_roots -and $data.workspace_roots.Count -gt 0) {
            $env:CURSOR_PROJECT_DIR = $data.workspace_roots[0]
        }
    } catch {
        Write-Output '{}'
        return
    }
} else {
    Write-Output '{}'
    return
}

. (Join-Path (Join-Path $env:USERPROFILE '.claude\hooks') 'cc-tts-lib.ps1')
$parsed = Parse-CcTtsInputHook -InputJson $inputJson -Event 'cursor_question'

# Daemon first; direct path below is the fallback — never silence.
if (Test-CcTtsDaemonReady) {
    if (Send-CcTtsDaemonEvent -Source cursor -Event cursor_question -State $parsed.State -InputJson $inputJson -Override $parsed.Override) {
        Write-Output '{}'
        return
    }
}

$cfg = Initialize-CcTtsConfig
if (-not $cfg -or -not $cfg.enabled) { Write-Output '{}'; return }
if (-not (Test-CcTtsEventEnabled 'question')) { Write-Output '{}'; return }
$notify = Join-Path $env:USERPROFILE '.claude\hooks\cc-tts-notify.ps1'
if (-not (Test-Path -LiteralPath $notify)) {
    Write-Output '{}'
    return
}

$args = @(
    '-NoLogo', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', $notify,
    '-State', $parsed.State,
    '-Source', 'cursor'
)
if ($parsed.Override) { $args += @('-OverrideText', $parsed.Override) }
if ($env:CURSOR_PROJECT_DIR) { $args += @('-ProjectDir', $env:CURSOR_PROJECT_DIR) }

Start-Process pwsh.exe -ArgumentList $args -WindowStyle Hidden | Out-Null
Write-Output '{}'
