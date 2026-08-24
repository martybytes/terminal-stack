<#
.NAME        reconcile-llm-queue
.SYNOPSIS    Quarantine stale durable LLM queue records and run one bounded, state-driven recovery pass.
.PLATFORM    windows
.USAGE       .\reconcile-llm-queue.ps1 [-Apply] [-BackupRoot C:\DATA\Backups\agentmemory]
.WHEN        Queue telemetry is stuck with old active jobs or a historical DLQ after provider recovery.
.NOTE        Preview-only unless -Apply is passed. Apply takes a cold full-volume backup, moves the
             exact /data/queue_store directory to a timestamped quarantine directory, starts with a
             fresh queue, and lets AgentMemory's existing startup reconciliation enqueue only work
             still missing from durable state. It never bulk-redrives the DLQ and never deletes the
             quarantine or backup.
#>
param(
    [switch]$Apply,
    [string]$BackupRoot = 'C:\DATA\Backups\agentmemory',
    [ValidateRange(1, 1000)]
    [int]$MaxPlannedTerraCalls = 25,
    [ValidateRange(0.01, 1000)]
    [decimal]$MaxEstimatedCostUsd = 1.00,
    [ValidateRange(60, 3600)]
    [int]$RecoveryTimeoutSeconds = 600,

    [ValidateRange(90, 600)]
    [int]$PostRecoverySoakSeconds = 105
)

$ErrorActionPreference = 'Stop'
$stackDir = [System.IO.Path]::GetFullPath($PSScriptRoot)
$composeFile = Join-Path $stackDir 'docker-compose.yml'
$volumeName = 'ts-agentmemory-data'
$api = 'http://127.0.0.1:3110/agentmemory'
$mode = if ($Apply) { 'APPLY' } else { 'PREVIEW' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$quarantineName = "queue_store.quarantine-$stamp"

if (-not (Test-Path -LiteralPath $composeFile -PathType Leaf)) {
    throw "docker-compose.yml missing in $stackDir"
}
if ($quarantineName -notmatch '^queue_store\.quarantine-[0-9]{8}-[0-9]{6}$') {
    throw "unexpected quarantine name: $quarantineName"
}

$backupRootFull = [System.IO.Path]::GetFullPath($BackupRoot)
$backupRootPath = [System.IO.Path]::GetPathRoot($backupRootFull)
if ([string]::IsNullOrWhiteSpace($backupRootFull) -or $backupRootFull -eq $backupRootPath) {
    throw "backup root is too broad: $backupRootFull"
}
$backupDir = Join-Path $backupRootFull $stamp

function Section([string]$Text) { Write-Host "`n=== $Text ===" -ForegroundColor Cyan }
function Step([string]$Text) {
    $tag = if ($Apply) { '[DO]   ' } else { '[would]' }
    Write-Host "$tag $Text" -ForegroundColor ($(if ($Apply) { 'Green' } else { 'Yellow' }))
}
function Info([string]$Text) { Write-Host "       $Text" -ForegroundColor DarkGray }
function Warn([string]$Text) { Write-Host "  !    $Text" -ForegroundColor Yellow }

function Invoke-Compose {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,
        [switch]$Capture
    )
    if ($Capture) {
        $output = & docker compose @Arguments 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw "docker compose $($Arguments -join ' ') failed:`n$output" }
        return $output.Trim()
    }
    & docker compose @Arguments
    if ($LASTEXITCODE -ne 0) { throw "docker compose $($Arguments -join ' ') failed" }
}

function Get-AgentMemorySecret {
    $value = [Environment]::GetEnvironmentVariable('AGENTMEMORY_SECRET', 'User')
    if ($value) { return $value.Trim() }
    return (Invoke-Compose -Arguments @('exec', '-T', 'agentmemory', 'cat', '/data/.hmac') -Capture).Trim()
}

$analysisScript = @'
const fs = require("fs");
function readJsonFile(path) {
  const bytes = fs.readFileSync(path);
  for (let i = bytes.length - 1; i >= 0; i -= 1) {
    if (bytes[i] !== 125) continue;
    try { return JSON.parse(bytes.subarray(0, i + 1).toString("utf8")); } catch {}
  }
  throw new Error(`could not decode ${path}`);
}
function state(scope) {
  const path = `/data/state_store.db/${encodeURIComponent(scope)}.bin`;
  return fs.existsSync(path) ? readJsonFile(path) : {};
}
function queueLists() {
  const path = "/data/queue_store/_queue_lists.bin";
  return fs.existsSync(path) ? readJsonFile(path) : {};
}
function activeJobs(lists) {
  const ids = lists["queue:__fn_queue::agentmemory-llm:active"] || [];
  const jobs = [];
  let missingFiles = 0;
  for (const id of ids) {
    const path = `/data/queue_store/${encodeURIComponent(`queue:__fn_queue::agentmemory-llm:jobs:${id}`)}.bin`;
    if (!fs.existsSync(path)) { missingFiles += 1; continue; }
    const row = readJsonFile(path);
    jobs.push(row[""] || Object.values(row)[0]);
  }
  return { jobs, missingFiles };
}
function familyCounts(jobs) {
  return jobs.reduce((out, job) => {
    const family = job?.data?.family || "missing";
    out[family] = (out[family] || 0) + 1;
    return out;
  }, {});
}
const lists = queueLists();
const active = activeJobs(lists);
const dlqRows = (lists["queue:__fn_queue::agentmemory-llm:dlq"] || []).map((value) => JSON.parse(value).job);
const sessionRows = Object.values(state("mem:sessions"));
const sessions = sessionRows.filter((row) => row?.id);
const summaries = state("mem:summaries");
const config = state("mem:config");
const observationCache = new Map();
function observations(sessionId) {
  if (!observationCache.has(sessionId)) {
    observationCache.set(sessionId, Object.values(state(`mem:obs:${sessionId}`)));
  }
  return observationCache.get(sessionId);
}
const summaryMinimum = Number(process.env.AGENTMEMORY_AUTO_SUMMARY_MIN_OBSERVATIONS || 10);
const summaryDeltaMinimum = Number(process.env.AGENTMEMORY_AUTO_SUMMARY_MIN_NEW_OBSERVATIONS || 25);
const summaryMaximumAge = Number(process.env.AGENTMEMORY_AUTO_SUMMARY_MAX_AGE_MS || 3600000);
const graphMinimum = Number(process.env.AGENTMEMORY_AUTO_GRAPH_MIN_NEW_OBSERVATIONS || 10);
const graphMaximum = Number(process.env.AGENTMEMORY_AUTO_GRAPH_MAX_OBSERVATIONS_PER_RUN || 25);
let rawObservations = 0;
const summaryDue = [];
const graphDue = [];
for (const session of sessions) {
  const rows = observations(session.id);
  rawObservations += rows.filter((row) => row && !row.title).length;
  const compressed = rows.filter((row) => row?.title).sort((a, b) => {
    const at = new Date(a.timestamp || a.createdAt || 0).getTime();
    const bt = new Date(b.timestamp || b.createdAt || 0).getTime();
    return at - bt || String(a.id || "").localeCompare(String(b.id || ""));
  });
  const existing = summaries[session.id];
  const delta = Math.max(0, compressed.length - (Number(existing?.observationCount) || 0));
  const age = existing?.createdAt ? Date.now() - new Date(existing.createdAt).getTime() : Infinity;
  if (compressed.length >= summaryMinimum && (!existing || delta >= summaryDeltaMinimum || (delta > 0 && age >= summaryMaximumAge))) {
    summaryDue.push(session.id);
  }
  const marker = config[`graph:auto:${session.id}`];
  const markedIndex = marker?.lastObservationId ? compressed.findIndex((row) => row.id === marker.lastObservationId) : -1;
  const start = markedIndex >= 0 ? markedIndex + 1 : Math.min(Number(marker?.processedObservationCount) || 0, compressed.length);
  const pending = compressed.length - start;
  if (compressed.length > 0 && pending > 0 && (!marker || pending >= graphMinimum)) {
    graphDue.push({
      sessionId: session.id,
      markerCount: Number(marker?.processedObservationCount) || 0,
      pending
    });
  }
}
function compressionState(jobs) {
  const out = { raw: 0, alreadyCompressed: 0, missingObservation: 0, malformed: 0 };
  for (const job of jobs.filter((row) => row?.data?.family === "compression")) {
    const data = job.data;
    if (!data.sessionId || !data.observationId) { out.malformed += 1; continue; }
    const row = observations(data.sessionId).find((item) => item?.id === data.observationId);
    if (!row) out.missingObservation += 1;
    else if (row.title) out.alreadyCompressed += 1;
    else out.raw += 1;
  }
  return out;
}
const waitingKey = "queue:__fn_queue::agentmemory-llm:waiting";
const activeKey = "queue:__fn_queue::agentmemory-llm:active";
const dlqKey = "queue:__fn_queue::agentmemory-llm:dlq";
console.log(JSON.stringify({
  sessions: sessions.length,
  malformedSessions: sessionRows.length - sessions.length,
  rawObservations,
  summaryDueSessionIds: summaryDue,
  graphDue,
  projectedTerraCalls: graphDue.length + summaryDue.length * 3,
  queue: {
    waiting: (lists[waitingKey] || []).length,
    active: (lists[activeKey] || []).length,
    dlq: (lists[dlqKey] || []).length,
    activeMissingFiles: active.missingFiles,
    activeByFamily: familyCounts(active.jobs),
    dlqByFamily: familyCounts(dlqRows),
    activeCompressionState: compressionState(active.jobs),
    dlqCompressionState: compressionState(dlqRows)
  },
  graphPolicy: { minimumNew: graphMinimum, maximumPerRun: graphMaximum }
}));
'@

function Get-StateAnalysis {
    $json = Invoke-Compose -Arguments @('exec', '-T', 'agentmemory', 'node', '-e', $analysisScript) -Capture
    try { return $json | ConvertFrom-Json -Depth 20 }
    catch { throw "state analysis returned invalid JSON:`n$json" }
}

function Get-LlmTelemetry {
    param([hashtable]$Headers)
    return Invoke-RestMethod -Headers $Headers -Uri "$api/llm/telemetry?limit=500" -TimeoutSec 30
}

function Get-CallCostUsd {
    param([object[]]$Calls)
    $total = [decimal]0
    foreach ($call in @($Calls)) {
        if ($null -eq $call.promptTokens -or $null -eq $call.completionTokens) { continue }
        if ($call.model -eq 'gpt-5.6-terra') {
            $total += ([decimal]$call.promptTokens * [decimal]2 / 1000000)
            $total += ([decimal]$call.completionTokens * [decimal]12 / 1000000)
        } elseif ($call.model -eq 'gpt-5.6-luna') {
            $total += ([decimal]$call.promptTokens * [decimal]0.20 / 1000000)
            $total += ([decimal]$call.completionTokens * [decimal]1.20 / 1000000)
        }
    }
    return $total
}

function Get-ProjectedCostUsd {
    param(
        [object]$Analysis,
        [object]$Telemetry
    )
    $successful = @($Telemetry.calls | Where-Object {
        $_.outcome -eq 'success' -and $_.model -eq 'gpt-5.6-terra' -and
        $null -ne $_.promptTokens -and $null -ne $_.completionTokens
    })
    $familyAverages = @{}
    foreach ($family in @('graph', 'summary')) {
        $jobCosts = @()
        foreach ($group in @($successful | Where-Object family -eq $family | Group-Object jobId)) {
            $jobCosts += Get-CallCostUsd -Calls @($group.Group)
        }
        if ($jobCosts.Count -gt 0) {
            $familyAverages[$family] = [decimal](($jobCosts | Measure-Object -Average).Average)
        }
    }
    # Conservative fallbacks use recent observed job shapes if telemetry was reset.
    if (-not $familyAverages.ContainsKey('graph')) { $familyAverages.graph = [decimal]0.023 }
    if (-not $familyAverages.ContainsKey('summary')) { $familyAverages.summary = [decimal]0.135 }
    return [pscustomobject]@{
        graphJobAverage = $familyAverages.graph
        summaryJobAverage = $familyAverages.summary
        projected = ([decimal]$Analysis.graphDue.Count * $familyAverages.graph) +
                    ([decimal]$Analysis.summaryDueSessionIds.Count * $familyAverages.summary)
    }
}

function Wait-ForHttp200 {
    param(
        [Parameter(Mandatory)]
        [string]$Uri,
        [int]$TimeoutSeconds = 180
    )
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -TimeoutSec 10
            if ($response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 3
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "timed out waiting for $Uri"
}

Write-Host "reconcile-llm-queue  mode=$mode  stack=$stackDir" -ForegroundColor White
if (-not $Apply) { Info 'read-only preview; add -Apply to back up, quarantine, and reconcile' }

Push-Location $stackDir
try {
    Section 'Preflight'
    Invoke-Compose -Arguments @('config', '--quiet')
    & docker volume inspect $volumeName *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker volume $volumeName does not exist" }
    $composeConfigJson = Invoke-Compose -Arguments @('config', '--format', 'json') -Capture
    try { $composeConfig = $composeConfigJson | ConvertFrom-Json -Depth 30 }
    catch { throw "docker compose config returned invalid JSON:`n$composeConfigJson" }
    $image = [string]$composeConfig.services.agentmemory.image
    if ([string]::IsNullOrWhiteSpace($image)) { $image = "$($composeConfig.name)-agentmemory" }
    & docker image inspect $image *> $null
    if ($LASTEXITCODE -ne 0) { throw "AgentMemory image is not built: $image" }
    $secret = Get-AgentMemorySecret
    if ([string]::IsNullOrWhiteSpace($secret)) { throw 'AgentMemory HMAC secret is unavailable' }
    $headers = @{ Authorization = "Bearer $secret" }
    Wait-ForHttp200 -Uri "$api/livez" -TimeoutSeconds 60
    $before = Get-StateAnalysis
    $telemetryBefore = Get-LlmTelemetry -Headers $headers
    $cost = Get-ProjectedCostUsd -Analysis $before -Telemetry $telemetryBefore

    Info "sessions=$($before.sessions) malformed_sessions=$($before.malformedSessions) raw=$($before.rawObservations) summaries_due=$($before.summaryDueSessionIds.Count) graphs_due=$($before.graphDue.Count)"
    Info "queue waiting=$($before.queue.waiting) active=$($before.queue.active) dlq=$($before.queue.dlq)"
    Info "DLQ families: $($before.queue.dlqByFamily | ConvertTo-Json -Compress)"
    Info ('projected Terra provider calls={0}; estimated cost=${1:N2}' -f $before.projectedTerraCalls, $cost.projected)
    if ($before.projectedTerraCalls -gt $MaxPlannedTerraCalls) {
        throw "projected Terra calls $($before.projectedTerraCalls) exceed safety limit $MaxPlannedTerraCalls"
    }
    if ($cost.projected -gt $MaxEstimatedCostUsd) {
        throw ('projected cost ${0:N2} exceeds safety limit ${1:N2}' -f $cost.projected, $MaxEstimatedCostUsd)
    }
    if ($before.queue.activeMissingFiles -gt 0) {
        throw "queue has $($before.queue.activeMissingFiles) active references without job files"
    }
    Info 'preflight safety limits passed'

    Section 'Cold backup and queue quarantine'
    Step "stop console and agentmemory"
    Step "write full-volume backup to $backupDir\agentmemory-volume.tgz"
    Step "move /data/queue_store to /data/$quarantineName and create a fresh queue store"
    if ($Apply) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        $resolvedBackup = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $backupDir))
        $backupBoundary = $backupRootFull.TrimEnd('\') + '\'
        if (-not ($resolvedBackup + '\').StartsWith($backupBoundary, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "resolved backup directory escaped backup root: $resolvedBackup"
        }

        Invoke-Compose -Arguments @('stop', 'console', 'agentmemory')
        & docker run --rm --entrypoint sh -v "${volumeName}:/source:ro" -v "${resolvedBackup}:/backup" $image -c 'tar -C /source -czf /backup/agentmemory-volume.tgz .'
        if ($LASTEXITCODE -ne 0) { throw 'volume backup failed; stack remains stopped and queue is unchanged' }
        $archive = Join-Path $resolvedBackup 'agentmemory-volume.tgz'
        if (-not (Test-Path -LiteralPath $archive -PathType Leaf) -or (Get-Item -LiteralPath $archive).Length -lt 1MB) {
            throw "backup archive is missing or unexpectedly small: $archive; stack remains stopped and queue is unchanged"
        }
        Info ('backup size={0:N1} MB' -f ((Get-Item -LiteralPath $archive).Length / 1MB))

        $quarantineScript = @'
set -eu
src=/data/queue_store
case "${QUEUE_QUARANTINE_NAME:-}" in
  queue_store.quarantine-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) echo "invalid quarantine name" >&2; exit 20 ;;
esac
dst="/data/$QUEUE_QUARANTINE_NAME"
[ -d "$src" ] || { echo "queue store is not a directory" >&2; exit 21; }
[ ! -L "$src" ] || { echo "queue store is a symbolic link" >&2; exit 22; }
resolved="$(readlink -f "$src")"
[ "$resolved" = "$src" ] || { echo "unexpected resolved queue path: $resolved" >&2; exit 23; }
[ ! -e "$dst" ] || { echo "quarantine target already exists" >&2; exit 24; }
count="$(find "$src" -mindepth 1 -maxdepth 1 -print | wc -l)"
echo "validated queue store entries=$count source=$src target=$dst"
mv "$src" "$dst"
mkdir "$src"
chown 1000:1000 "$src"
sync
'@
        & docker run --rm --entrypoint sh -e "QUEUE_QUARANTINE_NAME=$quarantineName" -v "${volumeName}:/data" $image -c $quarantineScript
        if ($LASTEXITCODE -ne 0) { throw 'queue quarantine failed; stack remains stopped and the full-volume backup is available' }
        Info "quarantined queue at /data/$quarantineName"
    }

    Section 'State-driven recovery'
    Step 'start the stack and allow exactly one startup reconciliation pass'
    Step "require an empty healthy queue for $PostRecoverySoakSeconds seconds (covers the full retry window)"
    Step "enforce Terra provider-call limit $MaxPlannedTerraCalls and estimated-cost limit `$$MaxEstimatedCostUsd"
    if ($Apply) {
        Invoke-Compose -Arguments @('up', '-d')
        Wait-ForHttp200 -Uri "$api/livez" -TimeoutSeconds 180
        Wait-ForHttp200 -Uri 'http://127.0.0.1:3114/healthz' -TimeoutSeconds 180
        Start-Sleep -Seconds 15

        $deadline = [DateTimeOffset]::UtcNow.AddSeconds($RecoveryTimeoutSeconds)
        $settledAt = $null
        $lastTelemetry = $null
        while ([DateTimeOffset]::UtcNow -lt $deadline) {
            $lastTelemetry = Get-LlmTelemetry -Headers $headers
            $terraCalls = @($lastTelemetry.calls | Where-Object model -eq 'gpt-5.6-terra').Count
            $actualCost = Get-CallCostUsd -Calls @($lastTelemetry.calls)
            $circuit = [string]$lastTelemetry.circuitBreaker.state
            Info ('queue={0} dlq={1} active={2} terra_calls={3} cost=${4:N2} circuit={5}' -f
                $lastTelemetry.queue.depth, $lastTelemetry.queue.dlq_depth, $lastTelemetry.activeJobs,
                $terraCalls, $actualCost, $circuit)

            if ($terraCalls -gt $MaxPlannedTerraCalls -or $actualCost -gt $MaxEstimatedCostUsd -or
                $lastTelemetry.queue.dlq_depth -gt 0 -or $circuit -eq 'open') {
                Invoke-Compose -Arguments @('stop', 'console', 'agentmemory')
                throw 'recovery safety guard tripped; stack stopped, new queue preserved, quarantine and backup untouched'
            }
            if ($lastTelemetry.queue.depth -eq 0 -and $lastTelemetry.queue.dlq_depth -eq 0 -and $lastTelemetry.activeJobs -eq 0) {
                if ($null -eq $settledAt) {
                    $settledAt = [DateTimeOffset]::UtcNow
                    Info "queue first settled; beginning $PostRecoverySoakSeconds-second retry-window soak"
                }
                if (([DateTimeOffset]::UtcNow - $settledAt).TotalSeconds -ge $PostRecoverySoakSeconds) { break }
            } else {
                $settledAt = $null
            }
            Start-Sleep -Seconds 5
        }
        if ($null -eq $settledAt -or ([DateTimeOffset]::UtcNow - $settledAt).TotalSeconds -lt $PostRecoverySoakSeconds) {
            Invoke-Compose -Arguments @('stop', 'console', 'agentmemory')
            throw "recovery did not settle within $RecoveryTimeoutSeconds seconds; stack stopped for inspection"
        }

        $after = Get-StateAnalysis
        $failedCalls = @($lastTelemetry.calls | Where-Object outcome -eq 'failure')
        if ($failedCalls.Count -gt 0) { throw "recovery settled with $($failedCalls.Count) provider failure rows" }
        if ($after.rawObservations -ne 0) { throw "recovery left $($after.rawObservations) raw observations" }
        if ($after.summaryDueSessionIds.Count -ne 0) { throw "recovery left $($after.summaryDueSessionIds.Count) summaries due" }
        if ($after.queue.active -ne 0 -or $after.queue.waiting -ne 0 -or $after.queue.dlq -ne 0) {
            throw 'fresh queue store is not empty after recovery'
        }

        $beforeMarkers = @{}
        foreach ($row in @($before.graphDue)) { $beforeMarkers[[string]$row.sessionId] = [int]$row.markerCount }
        $afterMarkers = @{}
        foreach ($row in @($after.graphDue)) { $afterMarkers[[string]$row.sessionId] = [int]$row.markerCount }
        $notAdvanced = @()
        foreach ($sessionId in $beforeMarkers.Keys) {
            if ($afterMarkers.ContainsKey($sessionId) -and $afterMarkers[$sessionId] -le $beforeMarkers[$sessionId]) {
                $notAdvanced += $sessionId
            }
        }
        if ($notAdvanced.Count -gt 0) { throw "graph markers did not advance for $($notAdvanced.Count) due sessions" }

        $actualCost = Get-CallCostUsd -Calls @($lastTelemetry.calls)
        $terraCalls = @($lastTelemetry.calls | Where-Object model -eq 'gpt-5.6-terra').Count
        $lunaCalls = @($lastTelemetry.calls | Where-Object model -eq 'gpt-5.6-luna').Count
        Info "post-recovery raw=0 summaries_due=0 graph_sessions_remaining=$($after.graphDue.Count)"
        Info ('actual provider calls: Terra={0} Luna={1}; estimated cost=${2:N2}' -f $terraCalls, $lunaCalls, $actualCost)
        Info "backup=$archive"
        Info "quarantine=/data/$quarantineName"
    }

    Write-Host ''
    if ($Apply) { Write-Host 'Done (APPLY): stale queue records quarantined and current state reconciled.' -ForegroundColor Green }
    else { Write-Host 'Nothing changed (preview). Re-run with -Apply after reviewing the counts above.' -ForegroundColor White }
} finally {
    Pop-Location
}
