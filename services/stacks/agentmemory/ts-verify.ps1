<#
.NAME     ts-verify.ps1
.SYNOPSIS agentmemory: prove a memory can be written and read back.
.PLATFORM Windows (pwsh 7). Twin of ts-verify.sh -- change one, change the other.
.USAGE    ts-verify.ps1            (run by `ts-stack test`; safe by hand)
.NOTE     Health is not evidence here. Every vendor hook does
          fetch(...).catch(() => {}) then exit(0), so a machine wired to a server
          that is up but refusing writes captures nothing and reports nothing.
          The only proof is a round trip.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$bypass  = if ($env:AGENTMEMORY_BYPASS_URL) { $env:AGENTMEMORY_BYPASS_URL } else { 'http://127.0.0.1:3110' }
$proxy   = if ($env:AGENTMEMORY_URL) { $env:AGENTMEMORY_URL } else { 'http://127.0.0.1:3111' }
$console = if ($env:AGENTMEMORY_CONSOLE_URL) { $env:AGENTMEMORY_CONSOLE_URL } else { 'http://127.0.0.1:3114' }
$rc = 0
function Pass([string]$m) { Write-Host "  OK   $m" -ForegroundColor Green }
function Fail([string]$m) { Write-Host "  X    $m" -ForegroundColor Yellow; $script:rc = 1 }
function Warn([string]$m) { Write-Host "  !    $m" -ForegroundColor Yellow }
function Get2xx([string]$Url) {
    try {
        $r = Invoke-WebRequest -Uri $Url -TimeoutSec 10 -UseBasicParsing
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300)
    } catch { return $false }
}

# 1. The bypass FIRST. If 3110 answers and 3111 does not, the console is down --
#    a different verdict from "agentmemory is down", and the one people get wrong
#    because 3111 is the port everything is configured to use.
if (Get2xx "$bypass/agentmemory/livez") { Pass 'server livez (3110 bypass)' }
else { Fail "the agentmemory server itself is not answering at $bypass" }

if (Get2xx "$proxy/agentmemory/livez") { Pass 'console proxy livez (3111)' }
elseif (Get2xx "$bypass/agentmemory/livez") { Fail 'the console proxy on 3111 is down (the server behind it is fine)' }
else { Fail 'neither the console proxy nor the server is answering' }

if (Get2xx "$console/healthz") { Pass 'console healthz (3114)' }
else { Fail "the console UI is not answering at $console" }

# 2. The secret every host uses must be the one the container has. A stale copy
#    401s every request for the life of a long-running shell, silently.
$secret = $env:AGENTMEMORY_SECRET
if (-not $secret) {
    $secret = (& docker exec ts-agentmemory-server cat /data/.hmac 2>$null) -join ''
    if (-not $secret) { $secret = (& docker exec agentmemory-agentmemory-1 cat /data/.hmac 2>$null) -join '' }
    $secret = $secret.Trim()
}
if (-not $secret) { Warn 'no agentmemory secret available — skipping the round trip'; exit $rc }
Pass 'secret resolved (container or environment)'

# 3. The round trip. Write through the CONSOLE, the way every wired agent does,
#    then read it back. The read is retried; the write never is, because a second
#    POST would create a second observation. The body is hook-shaped, copied from
#    the vendor post-tool-use.mjs -- guessing at it gets a 400.
$probe = "ts-stack-verify-$PID-$([int][double]::Parse((Get-Date -UFormat %s)))"
$payload = @{
    hookType  = 'post_tool_use'
    sessionId = $probe
    project   = 'ts-stack-verify'
    cwd       = '/ts-stack-verify'
    timestamp = (Get-Date).ToUniversalTime().ToString('o')
    data      = @{ tool_name = 'ts-stack'; tool_input = @{ probe = $probe }; tool_output = $probe }
} | ConvertTo-Json -Depth 5
try {
    $r = Invoke-WebRequest -Uri "$proxy/agentmemory/observe" -Method Post -TimeoutSec 20 -UseBasicParsing `
        -ContentType 'application/json' -Headers @{ Authorization = "Bearer $secret" } -Body $payload
    Pass "wrote a probe observation ($probe)"
} catch {
    $code = $_.Exception.Response.StatusCode.value__
    if ($code -eq 401) { Fail 'the server refused the secret (401) — the cached copy is stale' }
    else { Fail "writing a probe observation answered $code" }
    exit 1
}

# Sessions first: an observation is RECORDED immediately, while search has to
# index it, so checking search alone turns a slow index into a false failure.
# Search is POST {"query": ...} -- GET is 405 and {"q": ...} is 400.
$found = ''
foreach ($i in 1..10) {
    try {
        $r = Invoke-WebRequest -Uri "$proxy/agentmemory/sessions?limit=50" -TimeoutSec 8 -UseBasicParsing `
            -Headers @{ Authorization = "Bearer $secret" }
        if ($r.Content -match [regex]::Escape($probe)) { $found = 'sessions'; break }
    } catch {}
    try {
        $r = Invoke-WebRequest -Uri "$proxy/agentmemory/search" -Method Post -TimeoutSec 8 -UseBasicParsing `
            -ContentType 'application/json' -Headers @{ Authorization = "Bearer $secret" } `
            -Body (@{ query = $probe; limit = 20 } | ConvertTo-Json)
        if ($r.Content -match [regex]::Escape($probe)) { $found = 'search'; break }
    } catch {}
    Start-Sleep -Seconds 2
}
switch ($found) {
    'search'   { Pass 'read the probe back through search — capture and retrieval both work' }
    'sessions' { Pass 'the probe was recorded (found in sessions; search may still be indexing)' }
    default    { Fail 'the probe was written but never came back from sessions or search' }
}

exit $rc
