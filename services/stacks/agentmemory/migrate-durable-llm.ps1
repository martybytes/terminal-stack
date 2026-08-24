<#
.NAME        migrate-durable-llm
.SYNOPSIS    Back up AgentMemory, deploy the durable LLM queue + graph v2 state, and verify it. Preview-only unless -Apply is passed.
.PLATFORM    windows
.USAGE       .\migrate-durable-llm.ps1 [-Apply] [-BackupRoot %LOCALAPPDATA%\terminal-stack\stack-backups]
.WHEN        First deployment of the AgentMemory 0.9.29 durable-queue compatibility layer. Safe to re-run after graph v2 is active.
#>
param(
    [switch]$Apply,
    [string]$BackupRoot = '%LOCALAPPDATA%\terminal-stack\stack-backups'
)

$ErrorActionPreference = 'Stop'
$stackDir = [System.IO.Path]::GetFullPath($PSScriptRoot)
$expectedStack = [System.IO.Path]::GetFullPath((Join-Path (Split-Path $PSScriptRoot -Parent) 'agentmemory'))

# The console lives in its OWN compose project (ts-agent007memory) since the
# split, so `docker compose stop console` from this directory stops nothing and
# reports nothing -- it would have left the console reading a volume this script
# is about to move. Stop it where it actually lives, and only if it is there.
function Invoke-AmConsole([ValidateSet('stop', 'up')][string]$Action) {
    $dir = Join-Path (Split-Path -Parent $stackDir) 'agent007memory'
    if (-not (Test-Path -LiteralPath (Join-Path $dir 'docker-compose.yml'))) { return }
    Push-Location $dir
    try {
        if ($Action -eq 'stop') { & docker compose stop } else { & docker compose up -d }
    } finally { Pop-Location }
}
if ($stackDir -ne $expectedStack) { throw "unexpected stack directory: $stackDir" }
if (-not (Test-Path -LiteralPath (Join-Path $stackDir 'docker-compose.yml') -PathType Leaf)) { throw "docker-compose.yml missing in $stackDir" }

$backupRootFull = [System.IO.Path]::GetFullPath($BackupRoot)
if ([string]::IsNullOrWhiteSpace($backupRootFull) -or $backupRootFull -eq [System.IO.Path]::GetPathRoot($backupRootFull)) {
    throw "backup root is too broad: $backupRootFull"
}
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir = Join-Path $backupRootFull $stamp
$mode = if ($Apply) { 'APPLY' } else { 'PREVIEW' }

function Section([string]$text) { Write-Host "`n=== $text ===" -ForegroundColor Cyan }
function Step([string]$text) { Write-Host ($(if ($Apply) { '[DO]   ' } else { '[would]' }) + " $text") -ForegroundColor $(if ($Apply) { 'Green' } else { 'Yellow' }) }
function Info([string]$text) { Write-Host "       $text" -ForegroundColor DarkGray }

Write-Host "migrate-durable-llm  mode=$mode  stack=$stackDir" -ForegroundColor White

Push-Location $stackDir
try {
    Section 'Preflight'
    & docker compose config --quiet
    if ($LASTEXITCODE -ne 0) { throw 'docker compose config failed' }
    & docker volume inspect ts-agentmemory-data *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Docker volume ts-agentmemory-data does not exist' }
    $secret = (& docker compose exec -T agentmemory cat /data/.hmac).Trim()
    if (-not $secret) { throw 'could not read AgentMemory HMAC before backup' }
    Info 'compose config, external volume, and HMAC are present'

    Section 'Cold backup'
    Step "stop console and agentmemory"
    Step "create $backupDir\agentmemory-volume.tgz"
    if ($Apply) {
        New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
        $resolvedBackup = [System.IO.Path]::GetFullPath((Resolve-Path -LiteralPath $backupDir))
        $rootBoundary = $backupRootFull.TrimEnd('\') + '\'
        if (-not ($resolvedBackup + '\').StartsWith($rootBoundary, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "resolved backup directory escaped backup root: $resolvedBackup"
        }
        Invoke-AmConsole stop
        & docker compose stop agentmemory
        if ($LASTEXITCODE -ne 0) { throw 'failed to stop stack for backup' }
        & docker run --rm --entrypoint sh -v 'ts-agentmemory-data:/source:ro' -v "${resolvedBackup}:/backup" agentmemory-agentmemory:latest -c 'tar -C /source -czf /backup/agentmemory-volume.tgz .'
        if ($LASTEXITCODE -ne 0) { throw 'volume backup failed; stack remains stopped' }
        $archive = Join-Path $resolvedBackup 'agentmemory-volume.tgz'
        if (-not (Test-Path -LiteralPath $archive -PathType Leaf) -or (Get-Item -LiteralPath $archive).Length -lt 1MB) { throw "backup archive is missing or unexpectedly small: $archive" }
        Info ("backup: {0:N1} MB" -f ((Get-Item -LiteralPath $archive).Length / 1MB))
    }

    Section 'Deploy'
    Step 'build the patched AgentMemory image and recreate the stack'
    if ($Apply) {
        & docker compose build agentmemory
        if ($LASTEXITCODE -ne 0) { throw 'image build failed' }
        & docker compose up -d
        if ($LASTEXITCODE -ne 0) { throw 'stack start failed' }
        Invoke-AmConsole up
    }

    Section 'Verify graph migration'
    Step 'wait for authenticated graph migration status=complete'
    if ($Apply) {
        $headers = @{ Authorization = "Bearer $secret" }
        $migration = $null
        foreach ($attempt in 1..120) {
            try {
                $migration = Invoke-RestMethod -Headers $headers -Uri 'http://127.0.0.1:3110/agentmemory/admin/graph-migration' -TimeoutSec 10
                if ($migration.active -and $migration.manifest.status -eq 'complete') { break }
                if ($migration.manifest.status -eq 'failed') { throw 'graph v2 migration reported failed' }
            } catch {
                if ($_.Exception.Message -like '*reported failed*') { throw }
            }
            Start-Sleep -Seconds 5
        }
        if (-not $migration.active -or $migration.manifest.status -ne 'complete') { throw 'graph v2 migration did not complete within 10 minutes' }
        Info "graph v2: $($migration.manifest.totalNodes) nodes, $($migration.manifest.totalEdges) edges, $($migration.manifest.shards) shards"
    }

    Section 'Verify durable LLM work'
    Step 'confirm startup recovery requeued raw observations, reconciled counts, and exposed queue/DLQ telemetry'
    if ($Apply) {
        $telemetry = Invoke-RestMethod -Headers $headers -Uri 'http://127.0.0.1:3110/agentmemory/llm/telemetry?limit=20' -TimeoutSec 30
        Info "queue depth: $($telemetry.queue.depth); active: $($telemetry.activeJobs); DLQ: $($telemetry.queue.dlq_depth)"
        if ($telemetry.queue.dlq_depth -gt 0) { throw 'LLM queue DLQ is not empty' }
        foreach ($url in @('http://127.0.0.1:3110/agentmemory/livez', 'http://127.0.0.1:3111/agentmemory/livez', 'http://127.0.0.1:3114/healthz')) {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 10
            if ($response.StatusCode -ne 200) { throw "verification failed: $url returned $($response.StatusCode)" }
        }
        Info 'bypass, proxy, and console health checks returned 200'
    }
} finally {
    Pop-Location
}

Write-Host "`ndone ($mode)" -ForegroundColor White
if (-not $Apply) { Write-Host 're-run with -Apply to back up, deploy, migrate, and verify' -ForegroundColor DarkGray }
