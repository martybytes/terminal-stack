<#
.NAME     ts-verify.ps1
.SYNOPSIS headroom: prove the proxy is not just up, but enforcing.
.PLATFORM Windows (pwsh 7). Twin of ts-verify.sh -- change one, change the other.
.USAGE    ts-verify.ps1            (run by `ts-stack test`; safe by hand)
.NOTE     "Up (healthy)" is not evidence for this stack. The interesting failure
          is a proxy that answers /readyz while accepting UNAUTHENTICATED /v1
          traffic: healthy from the outside, and an open data plane.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$proxy = if ($env:HEADROOM_PROXY_URL) { $env:HEADROOM_PROXY_URL } else { 'http://127.0.0.1:8787' }
$dash  = if ($env:HEADROOM_DASHBOARD_URL) { $env:HEADROOM_DASHBOARD_URL } else { 'http://127.0.0.1:8788' }
$rc = 0
function Pass([string]$m) { Write-Host "  OK   $m" -ForegroundColor Green }
function Fail([string]$m) { Write-Host "  X    $m" -ForegroundColor Yellow; $script:rc = 1 }
function Warn([string]$m) { Write-Host "  !    $m" -ForegroundColor Yellow }

$envFile = Join-Path $PSScriptRoot '.env'
$token = $env:HEADROOM_PROXY_TOKEN
if (-not $token -and (Test-Path -LiteralPath $envFile)) {
    $line = Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^HEADROOM_PROXY_TOKEN=' } | Select-Object -First 1
    if ($line) { $token = $line -replace '^HEADROOM_PROXY_TOKEN=', '' }
}

# 1. Readiness. /readyz is a genuine readiness endpoint, so 2xx is the right test
#    -- unlike a reachability probe, where any HTTP response means "answering".
try {
    $r = Invoke-WebRequest -Uri "$proxy/readyz" -TimeoutSec 10 -UseBasicParsing
    if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) { Pass 'proxy /readyz is 2xx' }
    else { Fail "proxy /readyz answered $($r.StatusCode)" }
} catch { Fail "proxy /readyz did not answer 2xx at $proxy" }

# 2. The token is ENFORCED. Assert on the BODY, not the status: a refused
#    connection also produces a non-2xx and would otherwise read as a pass.
$body = ''
try {
    $r = Invoke-WebRequest -Uri "$proxy/v1/chat/completions" -Method Post -TimeoutSec 8 -UseBasicParsing `
        -ContentType 'application/json' -Body '{"model":"x","messages":[]}'
    $body = $r.Content
} catch {
    # ErrorDetails FIRST. pwsh 7 throws on 4xx with the response stream already
    # consumed, so GetResponseStream() throws and the body reads as EMPTY -- which
    # made this check report a refused connection against a proxy that had just
    # answered 401 {"error":"unauthorized"}. The stream stays as the 5.1 fallback.
    if ($_.ErrorDetails -and $_.ErrorDetails.Message) { $body = $_.ErrorDetails.Message }
    elseif ($_.Exception.Response) {
        try { $body = (New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())).ReadToEnd() } catch {}
    }
}
if (-not $body) {
    Fail 'unauthenticated /v1 returned an empty body — that is a refused connection, not a refusal'
} elseif ($body -match 'unauthorized') {
    Pass 'unauthenticated /v1 is refused by the proxy'
} elseif ($body -match '(?i)api.key') {
    # headroom refusing you and the UPSTREAM provider refusing headroom are
    # different outcomes, and only one of them is this stack's problem.
    Fail 'unauthenticated /v1 reached the upstream provider — the proxy is NOT enforcing its token'
} else {
    Fail "unauthenticated /v1 answered with something unexpected: $($body.Substring(0, [Math]::Min(120, $body.Length)))"
}

# 3. The token WORKS.
if (-not $token) {
    Warn 'no HEADROOM_PROXY_TOKEN in .env or the environment — skipping the authenticated check'
} else {
    try {
        $r = Invoke-WebRequest -Uri "$proxy/stats" -TimeoutSec 8 -UseBasicParsing `
            -Headers @{ 'X-Headroom-Proxy-Token' = $token }
        if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) { Pass 'authenticated /stats is 2xx' }
        else { Fail "authenticated /stats answered $($r.StatusCode)" }
    } catch {
        Fail 'authenticated /stats failed — the token in .env does not match the running proxy'
    }
}

# 4. The dashboard gateway injects the token server-side, so it must work with NO
#    headers set. That is the whole reason it exists.
try {
    $r = Invoke-WebRequest -Uri "$dash/dashboard" -TimeoutSec 8 -UseBasicParsing
    if ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300) { Pass 'dashboard is reachable without a token' }
    else { Fail "dashboard answered $($r.StatusCode)" }
} catch { Fail "dashboard did not answer 2xx at $dash/dashboard" }

exit $rc
