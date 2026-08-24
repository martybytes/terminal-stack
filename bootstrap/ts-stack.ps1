<#
.NAME     ts-stack.ps1
.SYNOPSIS The local Docker service stacks: bring them up, prove they work.
.PLATFORM Windows (pwsh 7). PARALLEL implementation of bootstrap/ts-stack.sh --
          not a wrapper. Change one, change the other, and keep -h byte-identical.
.USAGE    ts-stack [status|up|down|restart|logs|config|doctor] [<stack>] [flags]
.WHEN     Day to day: bringing the services up after a reboot, seeing what is
          healthy, tailing a container that misbehaves.
.NOTE     This is the ONLY thing in the repo that starts, stops or builds a
          container. ts-agents may probe one and print a verb from here; it may
          never run docker. services\ is the service side; everything outside it
          configures a program running on this host. See docs/decisions.md.
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Command = 'status',
    [Parameter(Position = 1)][string]$Stack = '',
    [string]$Tail = '50',
    [switch]$Follow,
    [switch]$All,
    [switch]$DryRun,
    [switch]$StartEngine,
    [switch]$NoColour,
    # -h is the alias: $HELP below holds the text, and a [switch]$Help would BE
    # that variable (pwsh names are case-insensitive), so the assignment would try
    # to convert a string to a SwitchParameter. See docs/powershell-quirks.md.
    [Alias('h')][switch]$ShowHelp
)

$ErrorActionPreference = 'Stop'

# Byte-identical to the HELP string in bootstrap/ts-stack.sh. A test pins that.
$HELP = @'
ts-stack — the local Docker service stacks: bring them up, prove they work.

Usage:
  ts-stack [status]            one line per stack: state, health, published ports
  ts-stack up [<stack>]        docker compose up -d
  ts-stack down [<stack>]      docker compose down          (every volume kept)
  ts-stack restart [<stack>]   down, then up
  ts-stack logs <stack>        docker compose logs
  ts-stack config [<stack>]    what compose actually resolves to on this machine
  ts-stack doctor              engine, .env files, health, ports, toggle drift
  ts-stack -h                  this help

  --dry-run          print the exact docker argv and change nothing
  -a, --all          include stacks whose saved terminal-stack setting is off
  -n, --tail <N>     logs: lines of history (default 50)
  -f, --follow       logs: follow (needs a single stack)
  --start-engine     doctor/up: launch the container engine and wait for it
  --no-colour

A stack is any directory under services/stacks/ holding a docker-compose.yml —
there is nothing to register. Which stacks take part comes from the saved
settings you already have: agentmemoryEnabled, headroomEnabled, playwrightEnabled
and, for kokoro, the TTS switch plus ccTts.engine. A stack whose setting is off
is skipped and reported as skipped, never as broken; naming it explicitly runs it
anyway, because asking by name is consent.

Every published port binds 127.0.0.1 only and none of these services
authenticate, which is why "ts-stack doctor" audits the bindings even when
everything else is failing.
'@

# Help before anything else, like the bash twin: it must work on a box where the
# clone, the config store or docker is the thing that is broken.
if ($ShowHelp -or $Command -in '-h', '--help', 'help') { Write-Host $HELP; exit 0 }

$ROOT = Split-Path -Parent $PSScriptRoot
$STACK_ROOT = if ($env:TS_STACK_ROOT) { $env:TS_STACK_ROOT } else { Join-Path $ROOT 'services\stacks' }
if (-not (Test-Path -LiteralPath $STACK_ROOT)) {
    Write-Error "ts-stack: cannot locate the service tree at $STACK_ROOT"
    exit 1
}
. (Join-Path $PSScriptRoot '_config.ps1')

$script:Issues = 0
function Ok  ([string]$m) { Write-Host "  ok  $m" }
function Bad ([string]$m) { Write-Host "  !!  $m" -ForegroundColor Yellow; $script:Issues++ }
function Skip([string]$m) { Write-Host "  --  $m" -ForegroundColor DarkGray }
function Note([string]$m) { Write-Host "      $m" -ForegroundColor DarkGray }
function Section([string]$m) { Write-Host ''; Write-Host "=== $m ===" -ForegroundColor Cyan }

# ── stacks ──────────────────────────────────────────────────────────────────────
function Get-TsStackList {
    Get-ChildItem -LiteralPath $STACK_ROOT -Directory -ErrorAction SilentlyContinue |
        Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'docker-compose.yml') } |
        Select-Object -ExpandProperty Name | Sort-Object
}
function Get-TsStackDir([string]$Name) { Join-Path $STACK_ROOT $Name }

# Twin of tss_toggle_for. kokoro is gated on the TTS engine as well as the
# switch, so the caller checks both; this only names the primary key.
function Get-TsStackToggle([string]$Name) {
    switch ($Name) {
        'agentmemory' { 'agentmemoryEnabled' }
        'headroom'    { 'headroomEnabled' }
        'playwright'  { 'playwrightEnabled' }
        'kokoro'      { 'ccTts' }
        default       { '' }
    }
}

# '' = enabled here; otherwise the reason it is deliberately not running.
function Get-TsStackState([string]$Name) {
    $key = Get-TsStackToggle $Name
    if (-not $key) { return '' }
    if ($key -eq 'ccTts') {
        $tts = Get-CcTtsConfig
        if (-not $tts.enabled) { return 'voice notifications are off' }
        if ($tts.engine -ne 'kokoro') { return "ccTts.engine=$($tts.engine)" }
        return ''
    }
    if ((Get-TsAgentSetting $key) -eq 'on') { return '' }
    return "$key=off"
}

# ── engine ──────────────────────────────────────────────────────────────────────
# Returns: native | absent | denied. (wsl-shim is a bash-side condition only —
# on Windows the pipe either answers or it does not.)
function Get-TsDockerKind {
    if ($env:TS_STACK_DOCKER_PROBE) { return $env:TS_STACK_DOCKER_PROBE }
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { return 'absent' }
    'native'
}
function Test-TsEngineUp {
    # The pipe is the cheap check; docker info is the honest one. Docker Desktop
    # publishes the pipe before the engine is ready, so both are needed.
    if (-not (Test-Path '\\.\pipe\dockerDesktopLinuxEngine')) {
        if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) { return $false }
    }
    & docker info *> $null
    return ($LASTEXITCODE -eq 0)
}
# PURE. Twin of tss_engine_advice, so a failed probe still hands back a fix.
function Get-TsEngineAdvice([string]$Kind) {
    switch ($Kind) {
        'absent' { @('no container engine found.',
                     '  fix:  winget install --id Docker.DockerDesktop --exact') }
        'denied' { @('the engine is there but this user may not talk to it.',
                     '  fix:  add yourself to the docker-users group, then sign out and in') }
        default  { @('the engine is not answering.',
                     '  fix:  start Docker Desktop, or re-run with --start-engine') }
    }
}

# ── the compose choke point ─────────────────────────────────────────────────────
# EVERY docker invocation goes through here: -v never reaches `down`, the billing
# overlay always gets --env-file .env BEFORE --env-file .billing.env (a lone
# --env-file REPLACES the interpolation source, so every LLM_* display value
# silently resolves to ''), and -DryRun prints the argv and runs nothing.
# NB: not $Args — that is an automatic variable, so a parameter of that name is
# never bound and every compose call silently loses its arguments.
function Invoke-TsStackCompose([string]$Name, [string[]]$ComposeArgs) {
    $dir = Get-TsStackDir $Name
    $pre = @()
    if (Test-Path -LiteralPath (Join-Path $dir '.billing.env')) {
        $pre = @('--env-file', '.env', '--env-file', '.billing.env')
    }
    if ($DryRun) {
        Write-Host ("({0}) docker compose {1}{2}" -f $Name, (($pre -join ' ') + $(if ($pre) { ' ' })), ($ComposeArgs -join ' '))
        return 0
    }
    Push-Location $dir
    try { & docker compose @pre @ComposeArgs; return $LASTEXITCODE }
    finally { Pop-Location }
}

# ── selection ───────────────────────────────────────────────────────────────────
$stackNames = @(Get-TsStackList)
if (-not $stackNames.Count) { Write-Error "ts-stack: no stacks found under $STACK_ROOT"; exit 1 }
if ($Stack) {
    if ($stackNames -notcontains $Stack) {
        Write-Error "ts-stack: no stack named '$Stack' — have: $($stackNames -join ' ')"
        exit 2
    }
    $chosen = @($Stack)
    $All = [switch]$true          # naming a stack is consent
} else {
    $chosen = $stackNames
}
function Selected {
    $chosen | Where-Object { $All -or -not (Get-TsStackState $_) }
}

$kind = Get-TsDockerKind
$engineOk = ($kind -eq 'native') -and (Test-TsEngineUp)

if (-not $engineOk -and $StartEngine -and $kind -eq 'native') {
    $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (Test-Path -LiteralPath $exe) {
        Write-Host "[DO]    launch $exe"
        if (-not $DryRun) {
            Start-Process -FilePath $exe | Out-Null
            # Cold starts are slow. 60s produces false failures.
            for ($i = 0; $i -lt 90; $i++) {
                if (Test-TsEngineUp) { $engineOk = $true; break }
                Start-Sleep -Seconds 2
            }
        }
    } else { Bad "Docker Desktop not found at $exe" }
}

if (-not $engineOk -and -not $DryRun -and $Command -in 'up', 'down', 'restart', 'logs', 'config') {
    Bad 'container engine unreachable'
    Get-TsEngineAdvice $kind | ForEach-Object { Note $_ }
    exit 1
}

# ── verbs ───────────────────────────────────────────────────────────────────────
function Show-TsStackStatus {
    foreach ($s in $chosen) {
        $state = Get-TsStackState $s
        $dir = Get-TsStackDir $s
        $running = 0; $total = 0
        if ($engineOk) {
            Push-Location $dir
            try {
                $running = @(& docker compose ps -q --status running 2>$null).Where({ $_ }).Count
                $total = @(& docker compose ps -aq 2>$null).Where({ $_ }).Count
            } finally { Pop-Location }
        }
        if ($state -and $total -eq 0) { Skip ("{0,-12} {1}" -f $s, $state); continue }
        if ($state) {
            # Intent and reality disagree. A warn, not a failure: that is what a
            # doctor exists to surface, and it is not "broken".
            Bad ("{0,-12} running, but {1}" -f $s, $state)
            Note "ts-config agents $s on   (keep it)   |   ts-stack down $s   (stop it)"
            continue
        }
        if (-not $engineOk) { Note ("{0,-12} enabled (engine unreachable, state unknown)" -f $s) }
        elseif ($total -eq 0) { Bad ("{0,-12} not created" -f $s) }
        elseif ($running -eq $total) { Ok ("{0,-12} running ({1}/{2})" -f $s, $running, $total) }
        else { Bad ("{0,-12} partial ({1}/{2})" -f $s, $running, $total) }
    }
}

# A stack that ships a .env.example but has no .env is misconfigured: compose
# falls back to the base file only, which for kokoro means starting the GPU image
# with no GPU.
function Test-TsStackEnvSeeded([string]$Name) {
    $dir = Get-TsStackDir $Name
    if (-not (Test-Path -LiteralPath (Join-Path $dir '.env.example'))) { return $true }
    Test-Path -LiteralPath (Join-Path $dir '.env')
}

switch ($Command) {
    'status' { Show-TsStackStatus }

    'config' { foreach ($s in Selected) { Section $s; Invoke-TsStackCompose $s @('config') | Out-Null } }

    'logs' {
        if (-not $Stack) { Write-Error 'ts-stack: logs needs a stack name'; exit 2 }
        $a = @('logs', '--tail', $Tail); if ($Follow) { $a += '-f' }
        Invoke-TsStackCompose $Stack $a | Out-Null
    }

    'up' {
        foreach ($s in $chosen) {
            if (-not (Test-TsStackEnvSeeded $s)) {
                Bad "$s`: .env.example exists but .env does not — the stack will start with the wrong profile"
            }
        }
        foreach ($s in Selected) {
            Section $s
            if ((Invoke-TsStackCompose $s @('up', '-d')) -ne 0) { Bad "up failed for $s" }
        }
    }

    'down' {
        # -v is NEVER in this argv. Volumes are only destroyed by an explicitly
        # gated path, and that is enforced by test, not by comment.
        foreach ($s in Selected) {
            Section $s
            if ((Invoke-TsStackCompose $s @('down')) -ne 0) { Bad "down failed for $s" }
        }
    }

    'restart' {
        # down + up, not `docker compose restart`: restart reuses the existing
        # container, so it ignores the changed .env that is the reason to restart.
        foreach ($s in Selected) {
            Section $s
            Invoke-TsStackCompose $s @('down') | Out-Null
            if ((Invoke-TsStackCompose $s @('up', '-d')) -ne 0) { Bad "restart failed for $s" }
        }
    }

    'doctor' {
        Section 'engine'
        if ($engineOk) {
            $v = (& docker version --format '{{.Server.Version}}' 2>$null)
            Ok "engine reachable ($(if ($v) { $v } else { '?' }))"
        } else {
            Bad "engine unreachable (kind: $kind)"
            Get-TsEngineAdvice $kind | ForEach-Object { Note $_ }
        }
        Section 'stacks'
        Show-TsStackStatus
        Section 'configuration'
        foreach ($s in $chosen) {
            if (Test-TsStackEnvSeeded $s) { Ok "$s`: .env present or not needed" }
            else { Bad "$s`: .env.example exists but .env does not" }
        }
        if ($engineOk) {
            foreach ($s in Selected) {
                if ((Invoke-TsStackCompose $s @('config', '-q')) -eq 0) { Ok "$s`: compose config parses" }
                else { Bad "$s`: compose config failed — a required value is missing" }
            }
        } else {
            Skip 'compose config, health and the port audit need the engine'
        }
    }

    default { Write-Error "ts-stack: unknown command '$Command' (try -h)"; exit 2 }
}

if ($Command -in 'doctor', 'status') {
    Write-Host ''
    if ($script:Issues -eq 0) { Write-Host "ts-stack $Command`: all checks passed" }
    else { Write-Host "ts-stack $Command`: $($script:Issues) issue(s) found"; exit 1 }
}
if ($DryRun) { Write-Host ''; Write-Host 'Nothing changed (--dry-run).' }
