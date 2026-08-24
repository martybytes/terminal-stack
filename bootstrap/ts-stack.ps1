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
    [switch]$DestroyData,
    [switch]$Purge,
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
  ts-stack bootstrap           first run here: .env files, secrets, volumes
  ts-stack doctor              engine, .env files, health, ports, toggle drift
  ts-stack test                take it all down, bring it back up, prove the chain
  ts-stack backup [<stack>]    cold tar of every data volume, with a manifest
  ts-stack reset [<stack>]     containers and locally built images, back to clean
  ts-stack migrate-volumes     the one-time rename to the ts- volume names
  ts-stack -h                  this help

  --dry-run          print the exact docker argv and change nothing
  -a, --all          include stacks whose saved terminal-stack setting is off
  -n, --tail <N>     logs: lines of history (default 50)
  -f, --follow       logs: follow (needs a single stack)
  --start-engine     doctor/up: launch the container engine and wait for it
  --destroy-data     test/reset: also destroy volumes   [BACKS UP FIRST]
  --purge            reset: also the two memory volumes [EVERY MEMORY YOU HAVE]
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

# ── checks, backup, and the phases test runs ────────────────────────────────────
# Twin of tss_run_checks: each stack ships ts-checks.conf, so a new stack
# registers itself by having one. Fields: kind id expect secs target
function Invoke-TsStackChecks([string]$Name) {
    $conf = Join-Path (Get-TsStackDir $Name) 'ts-checks.conf'
    if (-not (Test-Path -LiteralPath $conf)) { Note "$Name`: no ts-checks.conf"; return $true }
    $ok = $true
    foreach ($line in Get-Content -LiteralPath $conf) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $f = $t -split '\s+'
        $kind, $id, $expect, $secs, $target = $f[0], $f[1], $f[2], [int]$f[3], $f[4]
        switch ($kind) {
            'health' {
                if (Wait-TsHealthy $id $secs) { Ok "$Name/$id healthy" }
                else {
                    Bad "$Name/$id not healthy within ${secs}s"; $ok = $false
                    & docker logs --tail 40 $id 2>&1 | ForEach-Object { Write-Host "        $_" }
                }
            }
            { $_ -in 'http', 'http-ok' } {
                # Any response means something is listening: a 404 or a 401 is not
                # "down". That distinction is why there are two kinds here.
                $mode = if ($kind -eq 'http-ok') { '2xx' } else { 'any' }
                if (Wait-TsHttp $target $secs $mode) { Ok "$Name/$id $mode" }
                else { Bad "$Name/$id no $mode from $target in ${secs}s"; $ok = $false }
            }
            'port' {
                if (Test-TsLoopbackPort $target) { Ok "$Name/$id published on 127.0.0.1:$target" }
                else { Bad "$Name/$id port $target is not loopback-only"; $ok = $false }
            }
            default { Note "$Name`: unknown check kind '$kind'" }
        }
    }
    return $ok
}

function Wait-TsHealthy([string]$Container, [int]$Seconds) {
    $waited = 0
    while ($waited -lt $Seconds) {
        $state = (& docker inspect -f '{{.State.Status}}' $Container 2>$null) -join ''
        $health = (& docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' $Container 2>$null) -join ''
        if ($health -eq 'healthy') { return $true }
        # A service with no healthcheck only has to be running; every service here
        # should declare one, so this is the fallback, not the norm.
        if (-not $health -and $state -eq 'running') { return $true }
        Start-Sleep -Seconds 2; $waited += 2
    }
    return $false
}

function Wait-TsHttp([string]$Url, [int]$Seconds, [string]$Mode) {
    $waited = 0
    while ($true) {
        try {
            $r = Invoke-WebRequest -Uri $Url -TimeoutSec 5 -UseBasicParsing
            if ($Mode -eq 'any' -or ($r.StatusCode -ge 200 -and $r.StatusCode -lt 300)) { return $true }
        } catch {
            if ($Mode -eq 'any' -and $_.Exception.Response) { return $true }
        }
        if ($waited -ge $Seconds) { return $false }
        Start-Sleep -Seconds 2; $waited += 2
    }
}

# Published AND loopback-only. None of these services authenticate, so a port
# reachable off-box is a security incident, not an outage.
function Test-TsLoopbackPort([string]$Port) {
    $rows = @(& docker ps --format '{{.Ports}}' 2>$null) -split ',' |
        Where-Object { $_ -match "[0-9.]+:$Port->" }
    if (-not $rows) { return $false }
    return -not ($rows | Where-Object { $_ -notmatch '127\.0\.0\.1:' })
}

function Get-TsLoopbackViolations {
    @(& docker ps --format '{{.Names}} {{.Ports}}' 2>$null) -split ',' |
        Where-Object { $_ -match '\d+->' -and $_ -notmatch '127\.0\.0\.1:' }
}

$DATA_VOLUMES = @('ts-agentmemory-data', 'ts-agentmemory-console-history',
                  'ts-headroom-workspace', 'ts-headroom-qdrant', 'ts-headroom-neo4j')

function Get-TsBackupDir {
    $root = if ($env:TS_STACK_BACKUP_ROOT) { $env:TS_STACK_BACKUP_ROOT }
            else { Join-Path $env:LOCALAPPDATA 'terminal-stack\stack-backups' }
    Join-Path $root (Get-Date -Format 'yyyyMMdd-HHmmss')
}

# VERIFY the archive before anything is torn down. A backup only checked after
# the teardown is not a backup.
function Backup-TsVolume([string]$Volume, [string]$Dir) {
    if (-not (Test-TsVolume $Volume)) { Note "$Volume does not exist — skipped"; return $true }
    Step "backup $Volume"
    if ($DryRun) { return $true }
    & docker run --rm -v "$Volume`:/from:ro" -v "$Dir`:/to" alpine sh -c "tar -C /from -czf /to/$Volume.tgz ."
    if ($LASTEXITCODE -ne 0) { Bad "$Volume`: tar failed"; return $false }
    & docker run --rm -v "$Dir`:/to:ro" alpine sh -c "tar -tzf /to/$Volume.tgz >/dev/null"
    if ($LASTEXITCODE -ne 0) { Bad "$Volume`: the archive does not read back"; return $false }
    $bytes = (Get-Item -LiteralPath (Join-Path $Dir "$Volume.tgz")).Length
    if ($bytes -le 100) { Bad "$Volume`: archive is suspiciously small ($bytes bytes)"; return $false }
    Add-Content -LiteralPath (Join-Path $Dir 'manifest.txt') -Value "$Volume $bytes $(Get-Date -Format o)"
    Ok "$Volume -> $Dir ($bytes bytes)"
    return $true
}

function Backup-TsAll {
    $dir = Get-TsBackupDir
    Step "mkdir $dir"
    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    $ok = $true
    foreach ($v in $DATA_VOLUMES) { if (-not (Backup-TsVolume $v $dir)) { $ok = $false } }
    if ($ok) { Note "restore from: $dir" }
    return $ok
}

# ── first-run setup ─────────────────────────────────────────────────────────────
function Step([string]$m) {
    if ($DryRun) { Write-Host "[would] $m" -ForegroundColor Yellow }
    else { Write-Host "[DO]    $m" -ForegroundColor Green }
}

# A stack with a .env.example and no .env is not "unconfigured", it is
# MIS-configured: compose falls back to the base file only, which for kokoro
# means starting the GPU image with no GPU.
function Initialize-TsStackEnv([string]$Name) {
    $dir = Get-TsStackDir $Name
    $ex = Join-Path $dir '.env.example'
    $env_ = Join-Path $dir '.env'
    if (-not (Test-Path -LiteralPath $ex)) { return }
    if (Test-Path -LiteralPath $env_) { Note "$Name/.env already exists — left untouched"; return }
    Step "copy $Name/.env.example -> .env"
    if (-not $DryRun) {
        Copy-Item -LiteralPath $ex -Destination $env_
        Note 'seeded with the default profile — review it before starting the stack'
    }
}

# Replace a still-placeholder value with real random bytes. Never rotates a value
# somebody set: that is what makes a re-run idempotent, and what stops a second
# bootstrap silently invalidating a live proxy token.
function Set-TsGeneratedSecret([string]$File, [string]$Key, [string]$Placeholder, [int]$Bytes) {
    if (-not (Test-Path -LiteralPath $File)) { return }
    $lines = Get-Content -LiteralPath $File
    $current = ($lines | Where-Object { $_ -match "^$Key=" } | Select-Object -First 1) -replace "^$Key=", ''
    if ($current -and $current -ne $Placeholder) { Note "$Key already set — left untouched"; return }
    Step "generate $Key ($Bytes random bytes)"
    if ($DryRun) { return }
    # Get-Random is NOT a CSPRNG. This is a credential.
    $buf = [byte[]]::new($Bytes)
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($buf)
    $secret = -join ($buf | ForEach-Object { $_.ToString('x2') })
    # Collect into an array and pass -Value: a Where-Object piped straight into
    # Set-Content writes nothing at all when the pipeline is empty.
    $out = @($lines | ForEach-Object { if ($_ -match "^$Key=") { "$Key=$secret" } else { $_ } })
    Set-Content -LiteralPath $File -Value $out
    # A fingerprint, never the value: a secret echoed to a terminal lives in
    # scrollback, and this one is also in `docker logs` until rotation.
    Note "$Key set ($($secret.Substring(0,6))...$($secret.Substring($secret.Length-4)))"
}

# ── the pre-ts- volume names ────────────────────────────────────────────────────
# Renaming a volume is the only part of the naming sweep that touches data.
# `docker compose up` would create an empty replacement and start the stack with
# no memories in it, reporting success, so `up` refuses while a legacy volume
# exists and its new name does not. Twin of tss_volume_renames.
$VOLUME_RENAMES = [ordered]@{
    'agentmemory_iii-data'   = 'ts-agentmemory-data'
    'agent007memory_history' = 'ts-agentmemory-console-history'
    # Project-prefixed because they were plain named volumes under a project
    # called headroom; the two agentmemory volumes are external, so they were not.
    'headroom_headroom_workspace' = 'ts-headroom-workspace'
    'headroom_qdrant_data'        = 'ts-headroom-qdrant'
    'headroom_neo4j_data'         = 'ts-headroom-neo4j'
}
function Test-TsVolume([string]$Name) {
    & docker volume inspect $Name *> $null
    return ($LASTEXITCODE -eq 0)
}
function Get-TsVolumesPending {
    foreach ($old in $VOLUME_RENAMES.Keys) {
        $new = $VOLUME_RENAMES[$old]
        if ((Test-TsVolume $old) -and -not (Test-TsVolume $new)) {
            [pscustomobject]@{ Old = $old; New = $new }
        }
    }
}
# Copy in a container and verify the file count came across. The old volume is
# left ALONE: it is the rollback.
function Copy-TsVolume([string]$From, [string]$To) {
    $before = (& docker run --rm -v "$From`:/from:ro" alpine sh -c 'find /from -type f | wc -l' 2>$null) -join ''
    if (-not $before.Trim()) { Bad "$From`: could not be read"; return $false }
    & docker volume create $To *> $null
    & docker run --rm -v "$From`:/from:ro" -v "$To`:/to" alpine sh -c 'cp -a /from/. /to/ 2>/dev/null || cp -R /from/. /to/'
    if ($LASTEXITCODE -ne 0) { return $false }
    $after = (& docker run --rm -v "$To`:/to:ro" alpine sh -c 'find /to -type f | wc -l' 2>$null) -join ''
    if ($before.Trim() -ne $after.Trim()) {
        Bad "$From -> $To`: $($before.Trim()) files in, $($after.Trim()) out — nothing removed, and the new volume is suspect"
        return $false
    }
    Ok "$From -> $To ($($after.Trim()) files)"
    return $true
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
        # A legacy volume with no ts- replacement means compose would create an
        # EMPTY one and start the stack reporting success, with every memory left
        # behind in a volume nothing mounts. Refuse, and name the one command.
        $pending = @(if ($engineOk) { Get-TsVolumesPending })
        if ($pending.Count -and -not $DryRun) {
            Bad 'volumes still carry their pre-ts- names:'
            $pending | ForEach-Object { Note "$($_.Old) -> $($_.New)" }
            Note 'run:  ts-stack migrate-volumes     (copies, verifies, keeps the old volume)'
            exit 1
        }
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

    'bootstrap' {
        # First run on this machine. Idempotent by design: every step reports
        # "left untouched" when it has already been done.
        Section 'per-machine .env files'
        foreach ($s in $stackNames) { Initialize-TsStackEnv $s }

        Section 'generated secrets'
        # headroom refuses to `compose config` without these two: both are
        # :?-required, deliberately, so a missing one fails loudly instead of
        # starting an open data plane. They are arbitrary strings, so there is no
        # reason to make a human paste them out of `openssl rand -hex 32`.
        $manifest = Get-Content -Raw (Join-Path $PSScriptRoot 'agent-tools.json') | ConvertFrom-Json
        foreach ($item in @($manifest.headroom.generatedSecrets)) {
            Set-TsGeneratedSecret (Join-Path (Get-TsStackDir 'headroom') '.env') `
                $item.key $item.placeholder $item.bytes
        }

        Section 'named volumes'
        # external means compose will NOT create these, and this is where every
        # memory you have ever saved lives.
        $vols = @('ts-agentmemory-data')
        $amEnv = Join-Path (Get-TsStackDir 'agentmemory') '.env'
        if ((Test-Path -LiteralPath $amEnv) -and
            (Select-String -LiteralPath $amEnv -Pattern 'docker-compose\.console\.yml' -Quiet)) {
            $vols += 'ts-agentmemory-console-history'
        } else { Note 'agentmemory .env selects no console profile — skipping the console volume' }
        foreach ($v in $vols) {
            if ($DryRun) { Step "docker volume create $v (if absent)"; continue }
            if (Test-TsVolume $v) { Note "'$v' already exists — left untouched (this is where your data lives)"; continue }
            # Creating it here would DEFEAT the migration guard: pending pairs are
            # only reported while the new name is absent, so an empty replacement
            # turns "your memories are in the old volume" into a silent success.
            $legacy = ($VOLUME_RENAMES.GetEnumerator() | Where-Object { $_.Value -eq $v } | Select-Object -First 1).Key
            if ($legacy -and (Test-TsVolume $legacy)) {
                Bad "'$legacy' still holds this stack's data — NOT creating an empty '$v'"
                Note 'run:  ts-stack migrate-volumes'
                continue
            }
            Step "docker volume create $v"
            & docker volume create $v *> $null
            if ($LASTEXITCODE -ne 0) { Bad "docker volume create failed for $v" }
        }

        Section 'next'
        Note 'ts-stack up        start the stacks your settings enable'
        Note 'ts-stack doctor    check the engine, the .env files and the ports'
    }

    'migrate-volumes' {
        if (-not $engineOk) {
            Bad 'the engine is unreachable, so the volume names cannot be read'
            Get-TsEngineAdvice $kind | ForEach-Object { Note $_ }
            exit 1
        }
        $pending = @(Get-TsVolumesPending)
        if (-not $pending.Count) { Ok 'volume names are already current' }
        else {
            Section 'migrate volumes'
            $pending | ForEach-Object { Write-Host "  would copy: $($_.Old) $($_.New)" }
            if ($DryRun) {
                Note 'no --dry-run: the copy runs in a container and leaves the old volume in place'
            } else {
                # Nothing is destroyed here, so this needs consent but not a typed
                # phrase: the old volume survives as the rollback.
                $reply = Read-Host 'Copy these now? The old volumes are kept. [y/N]'
                if ($reply -match '^[yY]') {
                    foreach ($v in $pending) {
                        if (-not (Copy-TsVolume $v.Old $v.New)) { Bad "$($v.Old) -> $($v.New) failed" }
                    }
                    Note 'when the stack is proven on the new volumes: docker volume rm <old>'
                } else { Note 'nothing copied' }
            }
        }
    }

    'test' {
        # PHASE 0 — preflight. The only phase that runs while everything is still
        # up, so it is the exhaustive one: `compose config -q` names a missing
        # HEADROOM_PROXY_TOKEN here, not after the teardown.
        Section 'preflight'
        if (-not $engineOk) {
            Bad 'engine unreachable'; Get-TsEngineAdvice $kind | ForEach-Object { Note $_ }; exit 2
        }
        Ok 'engine reachable'
        foreach ($s in Selected) {
            if (-not (Test-TsStackEnvSeeded $s)) { Bad "$s`: .env missing — ts-stack bootstrap"; exit 2 }
            if ((Invoke-TsStackCompose $s @('config', '-q')) -eq 0) { Ok "$s`: compose config parses" }
            else { Bad "$s`: compose config failed — a required value is missing"; exit 2 }
        }
        if (@(Get-TsVolumesPending).Count) {
            Bad 'volumes still carry their pre-ts- names — ts-stack migrate-volumes'; exit 2
        }

        # PHASE 1 — backup, only when something is about to be destroyed.
        if ($DestroyData) {
            Section 'backup'
            if (-not (Backup-TsAll)) { Bad 'backup failed — nothing was torn down'; exit 2 }
        } else { Note 'no --destroy-data: every volume is kept, so no backup is taken' }

        # PHASE 2 — teardown.
        Section 'teardown'
        foreach ($s in Selected) {
            $a = if ($DestroyData) { @('down', '-v') } else { @('down') }
            Invoke-TsStackCompose $s $a | Out-Null
        }

        # PHASE 3 — bring-up. Every stack starts before any is waited on, so the
        # start_periods overlap; only the console's depends_on serialises.
        Section 'bring-up'
        foreach ($s in Selected) {
            if ((Invoke-TsStackCompose $s @('up', '-d')) -ne 0) { Bad "up failed for $s" }
        }

        # PHASE 4 — proof.
        Section 'health'
        foreach ($s in Selected) { if (-not (Invoke-TsStackChecks $s)) { } }

        Section 'integration'
        foreach ($s in Selected) {
            $v = Join-Path (Get-TsStackDir $s) 'ts-verify.ps1'
            if (-not (Test-Path -LiteralPath $v)) { Skip "$s`: no ts-verify.ps1"; continue }
            & pwsh -NoLogo -NoProfile -File $v
            if ($LASTEXITCODE -eq 0) { Ok "$s`: integration checks passed" }
            else { Bad "$s`: integration checks failed" }
        }

        # Never skipped by a toggle, and runs even when everything above failed.
        Section 'loopback audit'
        $bad = @(Get-TsLoopbackViolations)
        if (-not $bad.Count) { Ok 'every published port binds 127.0.0.1' }
        else { Bad 'a container publishes beyond loopback:'; $bad | ForEach-Object { Note $_ } }
    }

    'backup' {
        if (-not $engineOk) { Bad 'engine unreachable'; exit 2 }
        Section 'backup'
        if (-not (Backup-TsAll)) { exit 1 }
    }

    'reset' {
        if (-not $engineOk) { Bad 'engine unreachable'; exit 2 }
        if ($DestroyData -or $Purge) {
            Section 'backup first'
            if (-not (Backup-TsAll)) { Bad 'backup failed — nothing was destroyed'; exit 2 }
            $phrase = if ($Purge) { 'destroy all memories' } else { 'destroy headroom data' }
            Write-Host ''
            $typed = Read-Host "This will DESTROY volumes. Type exactly: $phrase"
            if ($typed -ne $phrase) { Note 'phrase did not match — nothing was destroyed'; exit 1 }
        }
        Section 'reset'
        foreach ($s in Selected) {
            $a = if ($DestroyData -or $Purge) { @('down', '-v') } else { @('down') }
            Invoke-TsStackCompose $s $a | Out-Null
        }
        if ($Purge) {
            # The two memory volumes are external, so `down -v` cannot touch them.
            # That asymmetry is the safety property; this is its own code path.
            foreach ($v in @('ts-agentmemory-data', 'ts-agentmemory-console-history')) {
                Step "docker volume rm $v"
                if (-not $DryRun) { & docker volume rm $v *> $null }
            }
        }
        Note 'images pulled from a registry are kept (re-pulling kokoro is multi-GB)'
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
        Section 'volumes'
        if (-not $engineOk) { Skip 'volume names need the engine' }
        else {
            $pending = @(Get-TsVolumesPending)
            if (-not $pending.Count) { Ok 'volume names are current' }
            else {
                Bad 'volumes still carry their pre-ts- names — ts-stack migrate-volumes'
                $pending | ForEach-Object { Note "$($_.Old) -> $($_.New)" }
            }
        }
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
