# ts-verify.ps1 - agent007memory: prove the console proxies to AgentMemory and
# serves its own UI. Run by `tstack services test`; safe to run by hand. Exit 0 = pass.
#
# POSIX twin: ts-verify.sh. Change one, change the other.
#
# "Up (healthy)" is not evidence here. This container's healthcheck asks its own
# /healthz, which answers whether or not the upstream it exists to proxy is
# reachable - and an unreachable upstream is exactly the failure that matters,
# because every MCP client is pointed at 3111, not at the server's own 3110.
$ErrorActionPreference = 'Stop'

$bypass  = if ($env:AGENTMEMORY_BYPASS_URL)  { $env:AGENTMEMORY_BYPASS_URL }  else { 'http://127.0.0.1:3110' }
$proxy   = if ($env:AGENTMEMORY_URL)         { $env:AGENTMEMORY_URL }         else { 'http://127.0.0.1:3111' }
$console = if ($env:AGENTMEMORY_CONSOLE_URL) { $env:AGENTMEMORY_CONSOLE_URL } else { 'http://127.0.0.1:3114' }
$script:rc = 0

function Pass([string]$m) { Write-Host "  OK   $m" -ForegroundColor Green }
function Fail([string]$m) { Write-Host "  X    $m" -ForegroundColor Yellow; $script:rc = 1 }

function Get2xx([string]$Url, [int]$Seconds = 10) {
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $r = Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
            if ([int]$r.StatusCode -ge 200 -and [int]$r.StatusCode -lt 300) { return $true }
        } catch { }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    return $false
}

if (Get2xx "$console/healthz") { Pass 'console healthz (3114)' }
else { Fail "the console UI is not answering at $console" }

# The proxy is only meaningful relative to the server behind it, so both are
# asked and the verdict names which of the two is actually down.
if (Get2xx "$proxy/agentmemory/livez") {
    Pass 'proxy forwards to agentmemory (3111 -> ts-agentmemory-server:3111)'
} elseif (Get2xx "$bypass/agentmemory/livez" 2) {
    Fail 'the proxy on 3111 is not forwarding, though the server behind it is healthy - is this container on ts-agentmemory-net?'
} else {
    Fail 'the agentmemory server itself is down, so the proxy has nothing to forward to (start it: tstack services up agentmemory)'
}

# The UI is a single-page app, so an empty 200 is a failed build, not a pass.
$body = ''
try { $body = (Invoke-WebRequest -Uri "$console/" -TimeoutSec 10 -UseBasicParsing -ErrorAction Stop).Content } catch { }
if (-not $body) {
    Fail "the console UI returned an empty body at $console/ - the image built without its front end"
} elseif ($body -match '<div id="?root' -or $body -match '<script') {
    Pass 'the console UI serves its application shell'
} else {
    Fail "the console UI answered without an application shell at $console/"
}

exit $script:rc
