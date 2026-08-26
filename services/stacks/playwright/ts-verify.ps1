<#
.NAME     ts-verify.ps1
.SYNOPSIS playwright: prove the MCP server actually drives a browser.
.PLATFORM Windows (pwsh 7). Twin of ts-verify.sh -- change one, change the other.
.USAGE    ts-verify.ps1            (run by `tstack services test`; safe by hand)
.NOTE     A healthy container proves the process started, not that a browser can
          be opened in it. check-playwright.mjs opens two isolated sessions and
          closes them; this is the thin wrapper tstack services test discovers.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
function Pass([string]$m) { Write-Host "  OK   $m" -ForegroundColor Green }
function Fail([string]$m) { Write-Host "  X    $m" -ForegroundColor Yellow }
function Warn([string]$m) { Write-Host "  !    $m" -ForegroundColor Yellow }

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Warn 'node is not installed -- skipping the browser session check'
    exit 0
}

& node (Join-Path $PSScriptRoot 'check-playwright.mjs')
if ($LASTEXITCODE -eq 0) {
    Pass 'two isolated browser sessions opened and closed'
    exit 0
}
Fail 'the MCP server did not complete a browser session'
exit 1
