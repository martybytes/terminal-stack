<#
.NAME        migrate-memory-projects
.SYNOPSIS    Report memories that carry no project, and backfill only the ones AgentMemory can
             infer unambiguously. Dry run unless -Apply is passed.
.PLATFORM    windows
.USAGE       .\migrate-memory-projects.ps1 [-Apply]
.WHEN        After noticing untagged memories (check-capture.ps1 reports the count), or
             after a run of agent work where saves omitted the optional project argument.
.NOTE        Inference is AgentMemory's own `infer-memory-projects` migration step, which derives a
             project from the sessions a memory is linked to and refuses anything ambiguous: no
             sessionIds, no session with a project, or no majority project all count as ambiguous
             and are left alone. This script never invents a project of its own.

             Memories saved through memory_save arrive with sessionIds: [] — nothing links them to
             a session — so the step cannot infer them and will report them as ambiguous forever.
             That is correct rather than broken: guessing would write a permanent wrong answer.
             This script lists them with whatever evidence exists so they can be tagged by hand,
             or simply re-saved with an explicit project.

             The fix for new memories is to pass `project` to memory_save. The MCP schema exposes
             it, REST validates it, and it persists — it is only ever missing because the caller
             omitted it.
#>
param(
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$stackDir = [System.IO.Path]::GetFullPath($PSScriptRoot)
if (-not (Test-Path -LiteralPath (Join-Path $stackDir 'docker-compose.yml') -PathType Leaf)) {
    throw "docker-compose.yml missing in $stackDir"
}

$execute = $Apply
$mode = if ($Apply) { 'APPLY' } else { 'DRY RUN' }
$api = 'http://127.0.0.1:3110/agentmemory'   # 3110 is the direct API; 3111 is the console proxy

function Section([string]$t) { Write-Host "`n=== $t ===" -ForegroundColor Cyan }
function Step([string]$t)    { $tag = if ($execute) { '[DO]  ' } else { '[would]' }; Write-Host "$tag $t" -ForegroundColor ($(if ($execute) { 'Green' } else { 'Yellow' })) }
function Info([string]$t)    { Write-Host "       $t" -ForegroundColor DarkGray }
function Warn([string]$t)    { Write-Host "  !    $t" -ForegroundColor Yellow }

Write-Host "migrate-memory-projects  mode=$mode" -ForegroundColor White
if (-not $execute) { Write-Host '(no writes; add -Apply to run the real backfill)' -ForegroundColor DarkGray }

# ---- secret: never stored in a tracked file --------------------------------
$hmac = [Environment]::GetEnvironmentVariable('AGENTMEMORY_SECRET', 'User')
if (-not $hmac) {
    Push-Location $stackDir
    try { $hmac = (& docker compose exec -T agentmemory cat /data/.hmac 2>$null | Out-String).Trim() } catch { $hmac = $null }
    Pop-Location
}
if (-not $hmac) { throw 'No AGENTMEMORY_SECRET available and /data/.hmac is unreadable — is the container running?' }
$headers = @{ Authorization = "Bearer $hmac" }

# --------------------------------------------------------------------------
Section 'Current project coverage'

$all = Invoke-RestMethod -Uri "$api/memories?limit=5000" -Headers $headers -TimeoutSec 60
$memories = @($all.memories)
$unprojected = @($memories | Where-Object { -not $_.project })
Info "$($memories.Count) memories total; $($unprojected.Count) with no project"

$byProject = $memories | Where-Object { $_.project } | Group-Object project | Sort-Object Count -Descending
foreach ($g in $byProject) { Info ("  {0,-28} {1}" -f $g.Name, $g.Count) }

# --------------------------------------------------------------------------
Section 'What AgentMemory can infer'

$migrateBody = @{ step = 'infer-memory-projects'; dryRun = (-not $execute) } | ConvertTo-Json
$result = Invoke-RestMethod -Method Post -Uri "$api/migrate" -Headers $headers `
    -ContentType 'application/json' -Body $migrateBody -TimeoutSec 300

# The step reports updated/skipped/ambiguous; shapes vary by version, so print what came back.
$summary = @()
foreach ($name in @('updated', 'skipped', 'ambiguous', 'total')) {
    $value = $result.$name
    if ($null -eq $value -and $result.PSObject.Properties.Name -contains 'result') { $value = $result.result.$name }
    if ($null -ne $value) { $summary += "$name=$value" }
}
if ($summary.Count -gt 0) { Info ($summary -join '  ') } else { Info ($result | ConvertTo-Json -Depth 6 -Compress) }

if ($execute) { Step 'ran infer-memory-projects for real (ambiguous records untouched)' }
else { Step 'would run infer-memory-projects; nothing was written' }

# --------------------------------------------------------------------------
Section 'Ambiguous records - reported, never reassigned'

if ($unprojected.Count -eq 0) {
    Info 'no untagged memories'
} else {
    Info 'Evidence below is everything stored. Tag by hand, or re-save with an explicit project.'
    Write-Host ''
    foreach ($m in ($unprojected | Sort-Object createdAt)) {
        $sessions = @($m.sessionIds)
        $files = @($m.files)
        $title = [string]$m.title
        if ($title.Length -gt 68) { $title = $title.Substring(0, 65) + '...' }
        Write-Host ("  {0}" -f $m.id) -ForegroundColor White
        Write-Host ("     created  {0}   agent {1}   type {2}" -f $m.createdAt, ($(if ($m.agentId) { $m.agentId } else { '-' })), $m.type) -ForegroundColor DarkGray
        Write-Host ("     sessions {0}   origin {1}" -f ($(if ($sessions.Count) { $sessions -join ',' } else { 'none (cannot be inferred)' })), ($(if ($m.origin.channel) { $m.origin.channel } else { '-' }))) -ForegroundColor DarkGray
        if ($files.Count) { Write-Host ("     files    {0}" -f ($files -join ', ')) -ForegroundColor DarkGray }
        Write-Host ("     title    {0}" -f $title) -ForegroundColor DarkGray
    }
    Write-Host ''
    $noSession = @($unprojected | Where-Object { -not @($_.sessionIds).Count }).Count
    if ($noSession -gt 0) {
        Warn "$noSession of $($unprojected.Count) have no sessionIds at all, so no amount of re-running this can infer them."
    }
    $byAgent = $unprojected | Group-Object { if ($_.agentId) { $_.agentId } else { '(none)' } }
    Info ("by agent: " + (($byAgent | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join '  '))
}

Write-Host ''
if (-not $execute) { Write-Host 'Nothing changed (dry run). Add -Apply to backfill the inferable records.' -ForegroundColor White }
else { Write-Host 'Done (APPLY).' -ForegroundColor Green }
