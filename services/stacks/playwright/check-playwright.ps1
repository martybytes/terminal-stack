<#
.NAME        check-playwright
.SYNOPSIS    Functionally verify the local Playwright MCP server, browser automation, and per-client isolation.
.PLATFORM    windows
.USAGE       .\check-playwright.ps1
.WHEN        After starting or upgrading the Playwright stack, or when an agent cannot use its browser tools.
.NOTE        This is a read-only diagnostic. It creates two temporary isolated browser sessions and closes them.
#>

$ErrorActionPreference = 'Stop'
$checkScript = Join-Path $PSScriptRoot 'check-playwright.mjs'

if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'node not found on PATH.' }
if (-not (Test-Path -LiteralPath $checkScript -PathType Leaf)) { throw "Missing check script: $checkScript" }

& node $checkScript
if ($LASTEXITCODE -ne 0) { throw "Playwright MCP functional check failed with exit code $LASTEXITCODE." }
