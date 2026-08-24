<#
.NAME        configure-openai-billing
.SYNOPSIS    Validate a dedicated OpenAI billing project and write non-secret console settings.
.USAGE       .\configure-openai-billing.ps1 -AdminKeyFile <path> -ProjectId <project_id> [-Apply]
             .\configure-openai-billing.ps1 -RefreshHints [-Apply]
.NOTES       Preview by default. No key is printed or copied into .billing.env — only masked
             fingerprints (first six characters and last four), which cannot authenticate.
             -RefreshHints re-derives those fingerprints after a key rotation without an Admin
             key and without any network call, so the Admin key's Organization Administration
             permission can stay at None.
#>
[CmdletBinding(DefaultParameterSetName = 'Configure')]
param(
    [Parameter(Mandatory=$true, ParameterSetName='Configure')][string]$AdminKeyFile,
    [Parameter(Mandatory=$true, ParameterSetName='Configure')][string]$ProjectId,
    [Parameter(Mandatory=$false, ParameterSetName='Configure')][string]$InferenceKeyFile,
    [Parameter(Mandatory=$true, ParameterSetName='RefreshHints')][switch]$RefreshHints,
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'
$stackDir = $PSScriptRoot
$outputPath = Join-Path $stackDir '.billing.env'
$rootEnvPath = Join-Path (Split-Path -Parent $stackDir) '.env'

function Read-RawSecret([string]$Path, [string]$Label) {
    $resolved = (Resolve-Path -LiteralPath $Path -ErrorAction Stop).Path
    $value = (Get-Content -Raw -LiteralPath $resolved -ErrorAction Stop).Trim()
    if (-not $value) { throw "$Label file is empty." }
    if ($value -match '[\r\n]') { throw "$Label file must contain exactly one raw key." }
    if ($value -match '^(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=' -or $value.StartsWith("'") -or $value.StartsWith('"') -or $value.EndsWith("'") -or $value.EndsWith('"')) {
        throw "$Label file must contain only the raw key, without OPENAI_API_KEY=, export, or quotes."
    }
    return [pscustomobject]@{ Path = $resolved; Value = $value }
}

# Masked fingerprint for display in the console: the key's own `sk-<role>-`
# prefix, six identifying characters, an ellipsis, and the last four. That is
# the same head-and-tail shape provider dashboards use, and it is enough to tell
# two keys apart during a rotation. Not a secret: 10 of 164 characters, and the
# prefix and length are not attacker-useful on their own.
function Get-KeyHint([string]$Value) {
    $ellipsis = [string][char]0x2026
    $prefix = ''
    $body = $Value
    if ($Value -match '^(sk-[A-Za-z0-9]+-)(.+)$') {
        $prefix = $Matches[1]
        $body = $Matches[2]
    }
    # Never emit a fingerprint that covers most of a short or unexpected value.
    if ($body.Length -lt 24) { return "$prefix$ellipsis" }
    return "$prefix$($body.Substring(0, 6))$ellipsis$($body.Substring($body.Length - 4))"
}

# The inference key has exactly one untracked source: the repo-root .env. Read
# it for its fingerprint only — the key itself never enters .billing.env and
# never reaches the console.
function Get-InferenceKeyHint([string]$EnvPath) {
    if (-not (Test-Path -LiteralPath $EnvPath)) { return $null }
    $line = Select-String -LiteralPath $EnvPath -Pattern '^\s*OPENAI_API_KEY=(.+)$' | Select-Object -First 1
    if (-not $line) { return $null }
    $value = $line.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'")
    if (-not $value -or $value -like '*replace-me*' -or $value -like 'sk-proj-...*') { return $null }
    return Get-KeyHint $value
}

function Read-BillingSetting([string]$Path, [string]$Name) {
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    $line = Select-String -LiteralPath $Path -Pattern "^\s*$([regex]::Escape($Name))=(.*)$" | Select-Object -First 1
    if (-not $line) { return $null }
    return $line.Matches[0].Groups[1].Value.Trim()
}

# One writer so line order stays stable and a rotation produces a minimal diff.
function Write-BillingEnv([string]$Path, [string]$Id, [string]$NameJson, [string]$AdminHostPath, [string]$AdminHint, [string]$InferenceHint) {
    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.Add("OPENAI_BILLING_PROJECT_ID=$Id")
    $lines.Add("OPENAI_BILLING_PROJECT_NAME=$NameJson")
    $lines.Add('OPENAI_ADMIN_KEY_FILE=/run/secrets/openai-admin-key')
    $lines.Add("OPENAI_ADMIN_KEY_FILE_HOST=$AdminHostPath")
    # Display-only masked fingerprints, consumed by the console's LLM_* mirrors.
    if ($InferenceHint) { $lines.Add("LLM_API_KEY_HINT=$InferenceHint") }
    if ($AdminHint)     { $lines.Add("LLM_ADMIN_KEY_HINT=$AdminHint") }
    Set-Content -LiteralPath $Path -Value ($lines -join [Environment]::NewLine) -Encoding utf8NoBOM
}

# ---------------------------------------------------------------------------
# -RefreshHints: re-derive both fingerprints in place after a key rotation.
# No Admin key parameter, no network call, no other setting changed.
# ---------------------------------------------------------------------------
if ($PSCmdlet.ParameterSetName -eq 'RefreshHints') {
    if (-not (Test-Path -LiteralPath $outputPath)) {
        throw "No $outputPath to refresh. Run this script with -AdminKeyFile and -ProjectId first."
    }
    $existingId = Read-BillingSetting $outputPath 'OPENAI_BILLING_PROJECT_ID'
    $existingName = Read-BillingSetting $outputPath 'OPENAI_BILLING_PROJECT_NAME'
    $adminHostPath = Read-BillingSetting $outputPath 'OPENAI_ADMIN_KEY_FILE_HOST'
    if (-not $existingId) { throw "$outputPath has no OPENAI_BILLING_PROJECT_ID — re-run full configuration." }
    if (-not $adminHostPath) { throw "$outputPath has no OPENAI_ADMIN_KEY_FILE_HOST — re-run full configuration." }
    if (-not $existingName) { $existingName = ConvertTo-Json 'OpenAI project' -Compress }

    $adminHint = $null
    if (Test-Path -LiteralPath $adminHostPath) {
        $adminHint = Get-KeyHint (Read-RawSecret $adminHostPath 'Admin key').Value
    } else {
        Write-Warning "Admin key file not found at $adminHostPath — leaving LLM_ADMIN_KEY_HINT unset."
    }
    $inferenceHint = Get-InferenceKeyHint $rootEnvPath
    if (-not $inferenceHint) { Write-Warning "No usable OPENAI_API_KEY in $rootEnvPath — leaving LLM_API_KEY_HINT unset." }

    Write-Host "Inference key fingerprint: $(if ($inferenceHint) { $inferenceHint } else { '(none)' })" -ForegroundColor DarkGray
    Write-Host "Admin key fingerprint:     $(if ($adminHint) { $adminHint } else { '(none)' })" -ForegroundColor DarkGray
    if (-not $Apply) {
        Write-Host 'Preview only. Re-run with -Apply to update .billing.env.' -ForegroundColor Yellow
        exit 0
    }
    Write-BillingEnv $outputPath $existingId $existingName $adminHostPath $adminHint $inferenceHint
    Write-Host "Refreshed key fingerprints in $outputPath." -ForegroundColor Green
    Write-Host 'Recreate the console to pick them up:' -ForegroundColor Green
    Write-Host 'docker compose --env-file .env --env-file .billing.env -f docker-compose.yml -f docker-compose.console.yml -f docker-compose.billing.yml up -d' -ForegroundColor Cyan
    exit 0
}

if ($ProjectId -notmatch '^proj_[A-Za-z0-9]+$') { throw 'ProjectId must be an OpenAI project ID beginning with proj_.' }
if ($PSBoundParameters.ContainsKey('InferenceKeyFile')) {
    Write-Warning '-InferenceKeyFile is deprecated and ignored. Billing is scoped to the dedicated OpenAI project, and the inference key fingerprint is read from the repo-root .env.'
}

$admin = Read-RawSecret $AdminKeyFile 'Admin key'
$headers = @{ Authorization = "Bearer $($admin.Value)" }
$escapedProjectId = [uri]::EscapeDataString($ProjectId)
$project = Invoke-RestMethod -Method Get -Uri "https://api.openai.com/v1/organization/projects/$escapedProjectId" -Headers $headers -TimeoutSec 30
if ([string]$project.id -ne $ProjectId) { throw 'OpenAI returned a different project than requested.' }
if ([string]$project.status -ne 'active') { throw "OpenAI project is not active (status: $($project.status))." }
$projectName = ([string]$project.name).Trim()
if (-not $projectName) { $projectName = 'OpenAI project' }
if ($projectName -match '[\r\n]') { throw 'OpenAI project name contains unsupported line breaks.' }

$end = [DateTimeOffset]::new([DateTime]::UtcNow.Date)
$start = $end.AddDays(-1)
$startTime = $start.ToUnixTimeSeconds()
$endTime = $end.ToUnixTimeSeconds()
$costUrl = "https://api.openai.com/v1/organization/costs?start_time=$startTime&end_time=$endTime&bucket_width=1d&limit=1&group_by=project_id&project_ids=$escapedProjectId"
$null = Invoke-RestMethod -Method Get -Uri $costUrl -Headers $headers -TimeoutSec 30

$adminHint = Get-KeyHint $admin.Value
$inferenceHint = Get-InferenceKeyHint $rootEnvPath
if (-not $inferenceHint) { Write-Warning "No usable OPENAI_API_KEY in $rootEnvPath — leaving LLM_API_KEY_HINT unset." }

Write-Host "Validated active OpenAI project '$projectName' and project-scoped Costs API access." -ForegroundColor Green
Write-Host "Billing settings: $outputPath" -ForegroundColor DarkGray
Write-Host "Inference key fingerprint: $(if ($inferenceHint) { $inferenceHint } else { '(none)' })" -ForegroundColor DarkGray
Write-Host "Admin key fingerprint:     $adminHint" -ForegroundColor DarkGray
if (-not $Apply) {
    Write-Host 'Preview only. Re-run with -Apply to write .billing.env.' -ForegroundColor Yellow
    exit 0
}

$projectNameValue = ConvertTo-Json $projectName -Compress
Write-BillingEnv $outputPath $ProjectId $projectNameValue $admin.Path.Replace('\','/') $adminHint $inferenceHint
Write-Host 'Wrote non-secret project billing settings. Organization Administration may now return to None.' -ForegroundColor Green
Write-Host 'Deploy with:' -ForegroundColor Green
Write-Host 'docker compose --env-file .env --env-file .billing.env -f docker-compose.yml -f docker-compose.console.yml -f docker-compose.billing.yml up -d' -ForegroundColor Cyan
