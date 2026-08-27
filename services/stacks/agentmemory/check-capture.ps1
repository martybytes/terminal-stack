<#
.NAME        check-capture
.SYNOPSIS    Verify agentmemory is actually usable from Claude Code, Cursor, and Codex, not just serving HTTP. Checks MCP/plugin enablement, permissions, capture hooks, the secret's single source of truth, and capture recency; -Apply additionally runs a real hook end to end and cleans up after itself.
.PLATFORM    windows
.USAGE       .\check-capture.ps1 [-Apply]
.WHEN        Capture has gone quiet, or after any agentmemory plugin update — a plugin update silently reverts the hook wiring this checks. Safe to re-run; the -Apply probe removes the observation it writes.
.NOTE        A healthy server proves nothing about capture. Reads and writes fail independently: the API stays healthy, the circuit breaker stays closed, and MCP searches keep succeeding while no observation has been recorded for hours. That is the failure this script exists to make loud.
#>
param(
    [switch]$Apply   # write switch; without it, the end-to-end probe is skipped
)

$ErrorActionPreference = 'Stop'
$execute  = $Apply
$mode     = if ($Apply) { 'APPLY' } else { 'PREVIEW' }
$stackDir = $PSScriptRoot

function Section([string]$t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Step([string]$t)    { $tag = if ($execute) { '[DO]  ' } else { '[would]' }; Write-Host "$tag $t" -ForegroundColor ($(if ($execute) { 'Green' } else { 'Yellow' })) }
function Info([string]$t)    { Write-Host "       $t" -ForegroundColor DarkGray }
function Warn([string]$t)    { Write-Host "  !    $t" -ForegroundColor Yellow }
function Have([string]$c)    { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Pass([string]$t)    { Write-Host "  OK   $t" -ForegroundColor Green }
function Json([object]$o)    { $o | ConvertTo-Json -Depth 12 -Compress }

$problems = 0
function Fail([string]$t) { $script:problems++; Warn $t }

Write-Host "check-capture  mode=$mode  stack=$stackDir" -ForegroundColor White
if (-not $execute) { Write-Host '(read-only checks; add -Apply to also run the end-to-end probe)' -ForegroundColor DarkGray }

if (-not (Have 'docker')) { throw 'docker CLI not found on PATH' }

# --------------------------------------------------------------------------
Section 'A. Client wiring lives in terminal-stack'

# Which hooks are registered, what they run, and what environment they carry moved to
# terminal-stack (bootstrap/ts-agentmemory.ps1), which already manages ~/.claude,
# ~/.cursor and ~/.codex. Checking it from here would duplicate `tstack agentmemory --check`
# and drift from it, so this section only points at the right command.
Info 'Harness wiring: run  tstack agentmemory --check  (or tstack doctor) from the terminal-stack clone.'
Info 'It reports reverted hook-script edits, which is what a plugin upgrade silently causes.'
Info 'What follows here is the server side: secret, capture, search, project scoping.'

# Section D runs a real hook script against a synthetic payload -- the only check that
# proves capture works end to end -- so it still needs the plugin root. Resolved quietly:
# whether the wiring is correct is terminal-stack's question, not this file's.
$pluginRoot = $null
$installed = Join-Path $env:USERPROFILE '.claude\plugins\installed_plugins.json'
if (Test-Path -LiteralPath $installed) {
    try {
        $entry = (Get-Content $installed -Raw | ConvertFrom-Json).plugins.'agentmemory@agentmemory'
        if ($entry) { $pluginRoot = @($entry)[0].installPath }
    } catch { $pluginRoot = $null }
}
if (-not $pluginRoot) { Info 'agentmemory Claude plugin not found; the end-to-end capture probe will be skipped.' }

# --------------------------------------------------------------------------
Section 'B. Secret - single source of truth'

# The hook scripts and the MCP bridge both read AGENTMEMORY_SECRET straight from
# process.env, so the User-scope environment variable is the one place it belongs.
# A hardcoded copy in a config file works until the secret rotates, then fails
# silently — and rotation is exactly when you least want a silent failure.
$hmac = $null
Push-Location $stackDir
try {
    $hmac = (& docker compose exec -T agentmemory cat /data/.hmac 2>$null | Out-String).Trim()
} catch {
} finally {
    Pop-Location
}

if (-not $hmac) {
    Fail 'could not read /data/.hmac — is the agentmemory container running? (..\stack.ps1 -Status)'
} else {
    Info "/data/.hmac: $($hmac.Length) chars"

    $userSecret = [Environment]::GetEnvironmentVariable('AGENTMEMORY_SECRET', 'User')
    if (-not $userSecret) {
        Fail 'AGENTMEMORY_SECRET is not set as a User environment variable — hooks post without a bearer, the server answers 401, and the hook swallows it.'
        Info "Fix: [Environment]::SetEnvironmentVariable('AGENTMEMORY_SECRET', '<value of /data/.hmac>', 'User')"
    } elseif ($userSecret -ne $hmac) {
        Fail 'the User AGENTMEMORY_SECRET does not match /data/.hmac — stale after a rotation. Re-set it.'
    } else {
        Pass 'User AGENTMEMORY_SECRET matches /data/.hmac'
    }

    # Guard against re-introducing a hardcoded copy. Cursor should hold the
    # placeholder ${env:AGENTMEMORY_SECRET}, not the value itself.
    foreach ($cfg in @("$env:USERPROFILE\.claude\settings.json", "$env:USERPROFILE\.cursor\mcp.json")) {
        if (Test-Path $cfg) {
            if (Select-String -Path $cfg -Pattern ([regex]::Escape($hmac)) -Quiet) {
                Fail "hardcoded secret in $cfg — remove it and rely on the User environment variable, or rotation will break this client silently."
            } else {
                Pass "no hardcoded secret in $(Split-Path $cfg -Leaf)"
            }
        }
    }
}

# --------------------------------------------------------------------------
Section 'C. Capture recency'

# Informational, not pass/fail: an idle machine legitimately has no recent
# capture. What matters is whether this is stale *relative to when you were
# last working*.
Push-Location $stackDir
try {
    $last = & docker compose logs --no-color --timestamps agentmemory 2>$null |
        Select-String 'Observation captured' | Select-Object -Last 1
} finally {
    Pop-Location
}

if (-not $last) {
    Warn 'no "Observation captured" line in the retained logs at all'
    Info 'Logs rotate at max-size 10m / max-file 3, so this can be rotation rather than failure.'
} else {
    # `docker compose logs` prefixes each line with the container name
    # ("agentmemory-agentmemory-1  | 2026-08-20T22:19:..."), so pull the
    # timestamp out by shape rather than by position.
    $stamp = ([regex]'\d{4}-\d{2}-\d{2}T[\d:.]+Z?').Match($last.Line).Value
    try {
        if (-not $stamp) { throw 'no timestamp in log line' }
        $when = [DateTimeOffset]::Parse($stamp)
        $age  = [DateTimeOffset]::UtcNow - $when
        Info ("newest capture: {0:yyyy-MM-dd HH:mm:ss}Z ({1:N0} min ago)" -f $when.UtcDateTime, $age.TotalMinutes)
        if ($age.TotalMinutes -gt 120) {
            Warn 'over 2h old — if you have been working in Claude Code or Cursor since then, capture is broken. Check section A.'
        }
    } catch {
        Info "newest capture: could not read a timestamp from the log line"
    }
}

# --------------------------------------------------------------------------
Section 'D. End-to-end probe'

if (-not $pluginRoot -or -not $hmac) {
    Warn 'skipped — needs a resolved plugin root and a readable /data/.hmac (see above)'
} elseif (-not $execute) {
    Step 'run the installed post-tool-use hook against a synthetic payload, confirm the session lands, then forget it'
    Info 'Nothing else proves capture works: the hook always exits 0, so only the server-side record counts.'
} else {
    $probeId = "check-capture-probe-$([guid]::NewGuid().ToString('N').Substring(0, 12))"
    $script  = Join-Path $pluginRoot 'scripts\post-tool-use.mjs'

    # ConvertTo-Json, never string interpolation: the hook parses stdin inside a
    # bare try/catch that returns on failure, so a Windows path whose \D becomes an
    # invalid JSON escape makes the hook exit 0 having done nothing — which looks
    # exactly like success.
    $payload = [ordered]@{
        session_id      = $probeId
        cwd             = $stackDir
        hook_event_name = 'PostToolUse'
        tool_name       = 'Bash'
        tool_input      = [ordered]@{ command = 'check-capture probe' }
        tool_response   = [ordered]@{ stdout  = 'check-capture probe' }
    } | ConvertTo-Json -Depth 5 -Compress

    Step "post a synthetic observation as session $probeId"
    $env:CLAUDE_PLUGIN_ROOT = $pluginRoot
    $env:AGENTMEMORY_SECRET = $hmac
    $headers = @{ Authorization = "Bearer $hmac" }

    # 3111 is the console proxy — the path the hooks actually take. If that fails,
    # 3110 is agentmemory direct, which separates a console fault from a real one.
    $landed = $false
    foreach ($port in @(3111, 3110)) {
        $env:AGENTMEMORY_URL = "http://localhost:$port"
        if ($port -eq 3110) { Info 'retrying via the 3110 bypass — 3111 (console proxy) did not land' }
        else                { Info 'probing via 3111 (console proxy, the path hooks use)' }

        $payload | & node $script | Out-Null

        foreach ($i in 1..10) {
            Start-Sleep -Milliseconds 700
            try {
                $r = Invoke-RestMethod -Uri "http://127.0.0.1:$port/agentmemory/sessions?limit=60" -Headers $headers -TimeoutSec 5
                if ($r.sessions.id -contains $probeId) { $landed = $true; break }
            } catch {
            }
        }
        if ($landed) { Pass "capture works end to end (via $port)"; break }
    }

    if (-not $landed) {
        Fail 'PROBE FAILED — the hook ran and exited 0, but no observation reached the server. Capture is broken.'
        Info 'Check section A first (hook wiring), then the secret in section B.'
        Info 'The hook does fetch(...).catch(() => {}) then exit(0), so it never reports its own failure.'
    } else {
        Step "forget probe session $probeId"
        try {
            $body = @{ sessionId = $probeId } | ConvertTo-Json
            Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3111/agentmemory/forget' -Headers $headers `
                -ContentType 'application/json' -Body $body -TimeoutSec 10 | Out-Null
            Pass 'probe observation removed'
        } catch {
            Warn "could not forget $probeId — remove it from the viewer (http://localhost:3113) if it lingers"
        }
    }
}


# --------------------------------------------------------------------------
Section 'E. Read path - does search answer'

# Sections A-D only prove writes. On 2026-08-21 every one of them passed while
# retrieval was completely dead in two independent ways, so check both.

# Search itself. The injection flag moved to terminal-stack with the rest of the
# harness wiring; a hung request path is a server fault and stays here. A patched request path that awaits an unreleased startup
# promise hangs until the engine kills the invocation at 180s; the MCP bridge
# reports that as an empty result set, so "no results" is indistinguishable from
# "nothing matched". A short timeout tells them apart: a healthy search on this
# store answers well under a second.
if (-not $hmac) {
    Warn 'search probe skipped - needs a readable /data/.hmac (see section B)'
} else {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    try {
        $r = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3110/agentmemory/search' `
            -Headers @{ Authorization = "Bearer $hmac" } -ContentType 'application/json' `
            -Body (@{ query = 'the'; limit = 1 } | ConvertTo-Json) -TimeoutSec 20
        $sw.Stop()
        $n = @($r.results).Count
        if ($n -gt 0) {
            Pass "search answered in $([int]$sw.ElapsedMilliseconds) ms with $n result(s)"
        } else {
            # An empty store is legitimate; an empty result for a stopword when
            # memories exist is not.
            Warn "search answered in $([int]$sw.ElapsedMilliseconds) ms but returned nothing - expected at least one hit for a stopword query"
            Info 'If the store is genuinely empty this is fine; otherwise check the request path for an unreleased startup gate.'
        }
    } catch {
        $sw.Stop()
        Fail "search failed after $([int]$sw.ElapsedMilliseconds) ms: $($_.Exception.Message)"
        Info 'A ~180s hang ending in 504 means a request path is awaiting something that never resolves.'
        Info 'MCP memory_recall / memory_smart_search report this as an empty result set, not an error.'
    }
}


# Section D only builds $headers on the -Apply path; the sections below read the API in
# preview mode too.
$headers = if ($hmac) { @{ Authorization = "Bearer $hmac" } } else { @{} }

# Invoke-RestMethod hands a top-level JSON array back as ONE Object[], so @(...) wraps it
# instead of flattening it and every per-row test silently degrades into an array
# comparison that is always truthy. Piping enumerates it properly.
function Get-AmRequestFeed([int]$Limit) {
    $raw = Invoke-RestMethod -Uri "http://127.0.0.1:3114/api/requests?limit=$Limit" -Headers $headers -TimeoutSec 15
    return @($raw | ForEach-Object { $_ })
}

# --------------------------------------------------------------------------
Section 'H. Project persistence and filtering'

$unprojectedCount = $null
try {
    $allMem = Invoke-RestMethod -Uri "http://127.0.0.1:3110/agentmemory/memories?limit=5000" -Headers $headers -TimeoutSec 60
    $unprojectedCount = @(@($allMem.memories) | Where-Object { -not $_.project }).Count
    if ($unprojectedCount -eq 0) { Pass 'every memory carries a project' }
    else { Warn "$unprojectedCount memories carry no project - .\migrate-memory-projects.ps1 reports them" }
} catch {
    Warn "could not count untagged memories: $($_.Exception.Message)"
}

if (-not $execute) {
    Step 'save a probe memory under one project, prove the filter includes it and excludes it from another, then delete it'
} elseif (-not $hmac) {
    Warn 'project regression skipped - no readable secret'
} else {
    $tag = "check-capture-project-$([guid]::NewGuid().ToString('N').Substring(0,10))"
    $projA = "$tag-a"
    $projB = "$tag-b"
    $saved = $null
    try {
        $body = @{ content = "$tag probe memory for project persistence"; type = 'fact'; project = $projA } | ConvertTo-Json
        $resp = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3110/agentmemory/remember' -Headers $headers `
            -ContentType 'application/json' -Body $body -TimeoutSec 30
        $saved = if ($resp.memory) { $resp.memory } else { $resp }

        if ($saved.project -eq $projA) { Pass "save round-trips project ($projA)" }
        else { Fail "saved memory came back with project '$($saved.project)' instead of '$projA'" }

        $inA = Invoke-RestMethod -Uri "http://127.0.0.1:3110/agentmemory/memories?project=$projA&limit=50" -Headers $headers -TimeoutSec 30
        if (@($inA.memories | Where-Object { $_.id -eq $saved.id }).Count -eq 1) { Pass "project filter returns it under $projA" }
        else { Fail "project=$projA did not return the probe memory" }

        $inB = Invoke-RestMethod -Uri "http://127.0.0.1:3110/agentmemory/memories?project=$projB&limit=50" -Headers $headers -TimeoutSec 30
        if (@($inB.memories | Where-Object { $_.id -eq $saved.id }).Count -eq 0) { Pass "project filter excludes it from $projB" }
        else { Fail "project=$projB wrongly returned the probe memory - the filter is not restricting" }

        $found = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3110/agentmemory/search' -Headers $headers `
            -ContentType 'application/json' -Body (@{ query = "$tag probe memory"; limit = 10; format = 'compact' } | ConvertTo-Json) -TimeoutSec 30
        $hit = @($found.results | Where-Object { $_.obsId -eq $saved.id })
        if ($hit.Count -eq 0) { Warn 'probe memory not in search results yet (indexing lag)' }
        elseif ($hit[0].project -eq $projA) { Pass 'search results carry project' }
        else { Fail "search returned the probe with project '$($hit[0].project)'" }
    } catch {
        Fail "project regression failed: $($_.Exception.Message)"
    } finally {
        if ($saved -and $saved.id) {
            try {
                Invoke-RestMethod -Method Delete -Uri 'http://127.0.0.1:3110/agentmemory/governance/memories' -Headers $headers `
                    -ContentType 'application/json' -Body (@{ memoryIds = @($saved.id); reason = 'check-capture probe' } | ConvertTo-Json) -TimeoutSec 30 | Out-Null
                Pass 'probe memory removed'
            } catch { Warn "could not delete probe memory $($saved.id) - remove it from the viewer" }
        }
    }
}

# --------------------------------------------------------------------------
Section 'I. Duplicate observation capture'

# Codex loads both ~/.codex/hooks.json (Desktop) and the plugin's hooks.codex.json (CLI),
# so one event arrives twice, milliseconds apart, differing only in its timestamp.
if (-not $execute) {
    Step 'post one observation twice and confirm only one is stored'
    try {
        $feed = Get-AmRequestFeed 300
        $rows = @($feed | Where-Object { $_.route -eq '/agentmemory/observe' } | Sort-Object ts)
        $pairs = 0
        for ($i = 1; $i -lt $rows.Count; $i++) {
            $a = $rows[$i - 1]; $b = $rows[$i]
            if ($a.agent -eq $b.agent -and $a.reqBytes -eq $b.reqBytes -and ($b.ts - $a.ts) -le 1500 -and $b.status -eq 201) { $pairs++ }
        }
        if ($pairs -eq 0) { Pass "no duplicate observe pairs in the last $($rows.Count) captures" }
        else { Warn "$pairs near-identical observe pairs still stored in the last $($rows.Count) captures" }
    } catch {
        Info 'console feed unreadable; the -Apply probe checks this directly'
    }
} elseif (-not $hmac) {
    Warn 'duplicate check skipped - no readable secret'
} else {
    $sid = "check-capture-dupe-$([guid]::NewGuid().ToString('N').Substring(0,10))"
    $probeSessions += $sid
    $mk = {
        param($ms)
        @{
            hookType = 'post_tool_use'; sessionId = $sid; project = 'check-capture'
            cwd = 'C:/check-capture'; timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.$ms" + 'Z')
            data = @{ tool_name = 'Bash'; tool_input = @{ command = 'check-capture dedupe probe' } }
        } | ConvertTo-Json -Depth 6
    }
    try {
        $first = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3110/agentmemory/observe' -Headers $headers `
            -ContentType 'application/json' -Body (& $mk '001') -TimeoutSec 20
        $second = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3110/agentmemory/observe' -Headers $headers `
            -ContentType 'application/json' -Body (& $mk '999') -TimeoutSec 20
        # Deliberately not asserting that the server suppressed it: duplicate hook
        # invocations are dropped client-side now, inside the hook, before the request is
        # made (terminal-stack bootstrap/_agentmemory.ps1). A raw POST bypasses that
        # entirely, so this only exercises agentmemory's own content-based guard.
        if ($second.deduplicated -eq $true -or $second.deduped -eq $true) {
            Info 'agentmemory own content guard also rejected the identical repeat'
        }
        Start-Sleep -Seconds 2
        $sessions = Invoke-RestMethod -Uri 'http://127.0.0.1:3110/agentmemory/sessions?limit=5000' -Headers $headers -TimeoutSec 30
        $mine = @($sessions.sessions | Where-Object { $_.id -eq $sid })
        if ($mine.Count -eq 1 -and $mine[0].observationCount -eq 1) { Pass 'exactly one observation stored' }
        elseif ($mine.Count -eq 1) { Fail "stored $($mine[0].observationCount) observations for one event" }

        # The outcome that actually matters: real hook traffic must not arrive twice.
        try {
            # Only pairs where BOTH were STORED (201) count: a 201 followed by a
            # deduplicated 200 is one observation, which is the desired outcome, not a
            # fault. And only recent rows -- the feed reaches back before the client
            # guard existed, and those historical duplicates would fail this forever.
            $since = [DateTimeOffset]::UtcNow.AddMinutes(-10).ToUnixTimeMilliseconds()
            $rows = @(Get-AmRequestFeed 300 |
                Where-Object { $_.route -eq '/agentmemory/observe' -and $_.ts -ge $since -and $_.status -eq 201 } |
                Sort-Object ts)
            $pairs = 0
            for ($i = 1; $i -lt $rows.Count; $i++) {
                $a = $rows[$i - 1]; $b = $rows[$i]
                if ($a.agent -eq $b.agent -and $a.reqBytes -eq $b.reqBytes -and ($b.ts - $a.ts) -le 1500) { $pairs++ }
            }
            if ($rows.Count -lt 2) { Info 'too few recent captures to scan for duplicates' }
            elseif ($pairs -eq 0) { Pass "no duplicate captures across the last $($rows.Count) stored in 10 min" }
            else { Fail "$pairs duplicated captures in the last 10 min - run `tstack agentmemory --check` in terminal-stack" }
        } catch { Warn 'console feed unreadable; could not scan for duplicate pairs' }
    } catch {
        Fail "duplicate probe failed: $($_.Exception.Message)"
    }
}

if ($execute -and $probeSessions.Count -gt 0) {
    foreach ($sid in $probeSessions) {
        try {
            Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:3111/agentmemory/forget' -Headers $headers `
                -ContentType 'application/json' -Body (@{ sessionId = $sid } | ConvertTo-Json) -TimeoutSec 15 | Out-Null
        } catch { Warn "could not forget probe session $sid" }
    }
    Info "cleaned up $($probeSessions.Count) probe session(s)"
}

# --------------------------------------------------------------------------
Write-Host ''
if ($problems -eq 0) {
    Write-Host "No problems found ($mode)." -ForegroundColor Green
    if (-not $execute) { Write-Host 'Re-run with -Apply to prove capture end to end.' -ForegroundColor DarkGray }
} else {
    Write-Host "$problems problem(s) found - see the ! lines above." -ForegroundColor Yellow
}
Write-Host 'Plugins, hooks, permissions, and environment are read at process start: after any fix, restart Claude Code, Cursor, and Codex.' -ForegroundColor DarkGray
