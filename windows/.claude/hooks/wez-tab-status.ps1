param([Parameter(Mandatory)][ValidateSet('thinking','working','waiting','error')][string]$State)
if (-not $env:WEZTERM_PANE) { return }
$project = if ($env:CLAUDE_PROJECT_DIR) {
    Split-Path -Leaf $env:CLAUDE_PROJECT_DIR
} else {
    Split-Path -Leaf $PWD
}
# Bare project name only — no 'cc'/state prefix. WezTerm's format-tab-title
# already shows the Claude icon and per-pane state dots (driven by the cc_state
# user var below); a prefix would just waste tab width.
& wezterm.exe cli set-tab-title $project 2>$null

# Per-pane background tint by state (OSC 11; this pane only). Written to CONOUT$
# so it reaches the WezTerm pane even though the hook's stdout is captured by Claude
# Code. Catppuccin-accent dark tints — tune to taste. Reset happens in cc on exit.
# NOTE: on Windows ConPTY swallows OSC 11, so the *primary* path is the WezTerm
# user-var-changed handler (driven by the cc_state OSC 1337 below), which re-emits
# this tint via pane:inject_output. This raw OSC 11 is the non-ConPTY/mux fallback.
$bg = switch ($State) {
    { $_ -in 'thinking', 'working' } { '#4a3020'; break }  # warm/peach — working
    'waiting' { '#1e3828'; break }                          # green — your turn / done
    'error'   { '#3a1828'; break }                          # red — failed / attention
    default   { $null }
}
if ($bg) {
    try {
        $seq = [System.Text.Encoding]::ASCII.GetBytes("$([char]27)]11;$bg$([char]7)")
        $h = [System.IO.File]::Open('CONOUT$', 'Open', 'Write', 'ReadWrite')
        $h.Write($seq, 0, $seq.Length); $h.Flush(); $h.Dispose()
    } catch {}
}

# Per-pane Claude state as a WezTerm user var (read by format-tab-title). OSC 1337
# SetUserVar (base64); `wezterm cli set-user-var` doesn't exist, so write to CONOUT$.
# Cleared by the cc wrapper on exit.
$cc = switch ($State) {
    { $_ -in 'thinking', 'working' } { 'working'; break }
    'waiting' { 'done'; break }
    'error'   { 'error'; break }
    default   { '' }
}
try {
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($cc))
    $uv = [Text.Encoding]::ASCII.GetBytes("$([char]27)]1337;SetUserVar=cc_state=$b64$([char]7)")
    $h2 = [System.IO.File]::Open('CONOUT$', 'Open', 'Write', 'ReadWrite')
    $h2.Write($uv, 0, $uv.Length); $h2.Flush(); $h2.Dispose()
} catch {}

# Toast notification — fires for 'waiting' (done) and 'error' if the sentinel file exists.
# Toggle: ccnotify on / ccnotify off
if ($State -in 'waiting', 'error') {
    $toastFile = Join-Path $env:USERPROFILE '.claude\.toast-notify'
    if (Test-Path $toastFile) {
        try {
            Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
            $icon = New-Object System.Windows.Forms.NotifyIcon
            $icon.Icon = [System.Drawing.SystemIcons]::Application
            $icon.BalloonTipTitle = 'Claude Code'
            $icon.BalloonTipText = if ($State -eq 'error') { "Error: $project" } else { "Done: $project" }
            $icon.BalloonTipIcon = if ($State -eq 'error') { 'Error' } else { 'Info' }
            $icon.Visible = $true
            $icon.ShowBalloonTip(6000)
            Start-Sleep -Milliseconds 500
            $icon.Dispose()
        } catch {}
    }
}

# Barge-in signal for the ttsd daemon: a new prompt in this session cancels its
# queued "done"/"error" announcements. Advisory only — no fallback action.
if ($State -eq 'thinking') {
    $inputJson = ''
    try {
        if ([Console]::IsInputRedirected) { $inputJson = [Console]::In.ReadToEnd() }
    } catch {}
    try {
        . (Join-Path $PSScriptRoot 'cc-tts-lib.ps1')
        if (Test-CcTtsDaemonReady) {
            Send-CcTtsDaemonEvent -Source claude -Event prompt_submit -InputJson $inputJson | Out-Null
        }
    } catch {}
}
