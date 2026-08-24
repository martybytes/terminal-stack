<#
.NAME     ts-verify.ps1
.SYNOPSIS kokoro: prove it actually synthesises audio.
.PLATFORM Windows (pwsh 7). Twin of ts-verify.sh -- change one, change the other.
.USAGE    ts-verify.ps1            (run by `ts-stack test`; safe by hand)
.NOTE     This stack's documented failure is a CUDA build that does not match the
          card: the container reports Up and then crash-loops, so "Up (healthy)"
          proves nothing. RestartCount and a real synthesis are what prove it.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Continue'
$kokoro = if ($env:KOKORO_URL) { $env:KOKORO_URL } else { 'http://127.0.0.1:8880' }
$rc = 0
function Pass([string]$m) { Write-Host "  OK   $m" -ForegroundColor Green }
function Fail([string]$m) { Write-Host "  X    $m" -ForegroundColor Yellow; $script:rc = 1 }

# 1. Not crash-looping. A restarting container passes a health check between
#    restarts, which is exactly how this failure hides.
$restarts = (& docker inspect -f '{{.RestartCount}}' ts-kokoro-tts 2>$null) -join ''
if (-not $restarts) { Fail 'ts-kokoro-tts does not exist' }
elseif ($restarts -eq '0') { Pass 'no restarts' }
else { Fail "ts-kokoro-tts has restarted $restarts time(s) — likely a CUDA build that does not match this card (see README.md)" }

# 2. Synthesis. Written to a temp file that is removed afterwards, never into the
#    stack directory: an out.mp3 left behind is how that name ended up in
#    .gitignore.
$out = [System.IO.Path]::GetTempFileName()
try {
    $body = @{ model = 'kokoro'; input = 'terminal stack verification'
               voice = 'am_adam'; response_format = 'mp3' } | ConvertTo-Json
    Invoke-WebRequest -Uri "$kokoro/v1/audio/speech" -Method Post -TimeoutSec 60 -UseBasicParsing `
        -ContentType 'application/json' -Body $body -OutFile $out
    $bytes = (Get-Item -LiteralPath $out).Length
    if ($bytes -gt 2048) { Pass "synthesised $bytes bytes of audio" }
    else { Fail "synthesis answered 2xx but produced only $bytes bytes" }
} catch {
    Fail "synthesis failed against $kokoro"
} finally {
    Remove-Item -LiteralPath $out -Force -ErrorAction SilentlyContinue
}

exit $rc
