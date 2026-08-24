#!/usr/bin/env bash
# ts-stack.sh — the local Docker service stacks: bring them up, prove they work.
# Driven by the `ts-stack` shell wrapper (zsh) and runnable standalone.
#
# The pwsh `ts-stack` (bootstrap/ts-stack.ps1) is the PARALLEL implementation for
# Windows-standalone installs, not a wrapper: change one, change the other, and
# keep the -h output byte-identical.
#
# This is the ONLY thing in the repo that starts, stops or builds a container.
# `ts-agents` may probe one and print a verb from here; it may never run docker
# (tests/test_agent_tools.py pins that, as a substring match over the whole file,
# so not even in a comment). services/ is the service side; everything outside it
# configures a program running on this host. See docs/decisions.md.
#
# On WSL with Docker Desktop's integration switched off, `docker` on PATH is
# Desktop's stub: it exits 1 for every command and prints its complaint on
# STDOUT. Mutating verbs re-exec the pwsh twin through interop rather than
# proxying docker.exe, because compose resolves -f, build contexts and bind
# mounts as WINDOWS paths and a \\wsl.localhost 9p share is not reliably
# bind-mountable — a failure that would land after the stack was already down.
set -euo pipefail

HELP='ts-stack — the local Docker service stacks: bring them up, prove they work.

Usage:
  ts-stack [status]            one line per stack: state, health, published ports
  ts-stack up [<stack>]        docker compose up -d
  ts-stack down [<stack>]      docker compose down          (every volume kept)
  ts-stack restart [<stack>]   down, then up
  ts-stack logs <stack>        docker compose logs
  ts-stack config [<stack>]    what compose actually resolves to on this machine
  ts-stack bootstrap           first run here: .env files, secrets, volumes
  ts-stack doctor              engine, .env files, health, ports, toggle drift
  ts-stack migrate-volumes     the one-time rename to the ts- volume names
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
everything else is failing.'

# Help before anything else: `ts-stack -h` must work on a box where the clone,
# chezmoi or docker is the very thing that is broken.
case "${1:-}" in -h|--help|help) printf '%s\n' "$HELP"; exit 0 ;; esac

CZ="${TERMINAL_STACK_CHEZMOI:-}"
if [ -z "$CZ" ]; then
    if [ -x "$HOME/.local/bin/chezmoi" ]; then CZ="$HOME/.local/bin/chezmoi"
    elif command -v chezmoi >/dev/null 2>&1; then CZ="$(command -v chezmoi)"
    else CZ=""; fi
fi
SRC="${TERMINAL_STACK_DIR:-}"
if [ -z "$SRC" ] && [ -n "$CZ" ]; then SRC="$("$CZ" source-path 2>/dev/null || true)"; fi
if [ -z "$SRC" ]; then
    # Standalone: this script sits in <clone>/bootstrap/.
    _self="${BASH_SOURCE[0]}"
    while [ -L "$_self" ]; do
        _d="$(cd -- "$(dirname -- "$_self")" && pwd)"; _self="$(readlink "$_self")"
        case "$_self" in /*) ;; *) _self="$_d/$_self" ;; esac
    done
    SRC="$(cd -- "$(dirname -- "$_self")/.." && pwd -P)"
fi
if [ ! -d "$SRC/services/stacks" ]; then
    echo "ts-stack: cannot locate the service tree (set TERMINAL_STACK_DIR)." >&2
    exit 1
fi

# ── args ────────────────────────────────────────────────────────────────────────
cmd=""; want_stack=""; tail_n=50; follow=0; all=0; start_engine=0
while [ $# -gt 0 ]; do
    case "$1" in
        status|up|down|restart|logs|config|doctor|bootstrap|migrate-volumes)
            [ -z "$cmd" ] || { echo "ts-stack: two commands given ($cmd, $1)" >&2; exit 2; }
            cmd="$1"; shift ;;
        --dry-run)      TS_STACK_DRY_RUN=1; shift ;;
        -a|--all)       all=1; shift ;;
        -f|--follow)    follow=1; shift ;;
        -n|--tail)      tail_n="${2:?--tail needs a value}"; shift 2 ;;
        --start-engine) start_engine=1; shift ;;
        --no-colour|--no-color) NO_COLOR=1; shift ;;
        --stack)        want_stack="${2:?--stack needs a value}"; shift 2 ;;
        -*)             echo "ts-stack: unknown option: $1 (try -h)" >&2; exit 2 ;;
        *)              [ -z "$want_stack" ] || { echo "ts-stack: two stacks given" >&2; exit 2; }
                        want_stack="$1"; shift ;;
    esac
done
cmd="${cmd:-status}"
export TS_STACK_DRY_RUN="${TS_STACK_DRY_RUN:-0}"
export NO_COLOR="${NO_COLOR:-}"
case "$tail_n" in *[!0-9]*|'') echo "ts-stack: --tail wants a number" >&2; exit 2 ;; esac

# ── libraries ───────────────────────────────────────────────────────────────────
# shellcheck source=_config.sh
. "$SRC/bootstrap/_config.sh"
# shellcheck source=_cc_tts.sh
. "$SRC/bootstrap/_cc_tts.sh"
# shellcheck source=../services/_stack.sh
. "$SRC/services/_stack.sh"

# ── WSL: hand mutating work to the Windows twin ─────────────────────────────────
if [ "$(tss_docker_kind)" = wsl-shim ] && [ "$TS_STACK_DRY_RUN" != 1 ]; then
    case "$cmd" in
        up|down|restart|logs|config)
            ps=""
            for p in "/mnt/c/Program Files/PowerShell/7/pwsh.exe" \
                     "/mnt/c/Program Files/PowerShell/7-preview/pwsh.exe"; do
                [ -x "$p" ] && { ps="$p"; break; }
            done
            if [ -n "$ps" ]; then
                echo "ts-stack: no Linux Docker CLI in this WSL distro — re-running the Windows twin."
                win="$(wslpath -w "$SRC/bootstrap/ts-stack.ps1")"
                set -- "$cmd"
                [ -n "$want_stack" ] && set -- "$@" "$want_stack"
                exec "$ps" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass \
                    -File "$win" "$@"
            fi
            echo "ts-stack: no Linux Docker CLI in this WSL distro, and no pwsh 7 to hand off to." >&2
            tss_engine_advice "$(tss_os)" wsl-shim >&2
            exit 1 ;;
    esac
fi

# ── which stacks ────────────────────────────────────────────────────────────────
# "" = enabled, "off:<why>" = deliberately not running here.
stack_state() {                             # <stack>
    local key; key="$(tss_toggle_for "$1")"
    case "$key" in
        '') printf '' ;;
        ccTts)
            local on engine
            on="$(ts_cc_tts_get enabled 2>/dev/null || echo true)"
            engine="$(ts_cc_tts_get engine 2>/dev/null || echo kokoro)"
            if [ "$on" != true ]; then printf 'off:voice notifications are off'
            elif [ "$engine" != kokoro ]; then printf 'off:ccTts.engine=%s' "$engine"
            else printf ''; fi ;;
        *)
            if [ "$(ts_agent_get "$key" 2>/dev/null || echo off)" = on ]; then printf ''
            else printf 'off:%s=off' "$key"; fi ;;
    esac
}

all_stacks="$(tss_stack_list)"
[ -n "$all_stacks" ] || { echo "ts-stack: no stacks found under $TSS_STACKS" >&2; exit 1; }
if [ -n "$want_stack" ]; then
    printf '%s\n' "$all_stacks" | grep -qx -- "$want_stack" \
        || { echo "ts-stack: no stack named '$want_stack' — have: $(printf '%s' "$all_stacks" | tr '\n' ' ')" >&2; exit 2; }
    stacks="$want_stack"; all=1        # naming a stack is consent
else
    stacks="$all_stacks"
fi

# ── engine ──────────────────────────────────────────────────────────────────────
kind="$(tss_docker_kind)"
engine_ok=0
[ "$kind" = native ] && docker info >/dev/null 2>&1 && engine_ok=1

if [ "$engine_ok" = 0 ] && [ "$start_engine" = 1 ] && [ "$kind" = native ]; then
    case "$(tss_os)" in
        darwin) step 'open -a Docker'; [ "$TS_STACK_DRY_RUN" = 1 ] || open -a Docker 2>/dev/null || true ;;
        linux)  step 'systemctl start docker'; [ "$TS_STACK_DRY_RUN" = 1 ] || sudo systemctl start docker || true ;;
    esac
    # Cold starts are slow; 60s produces false failures.
    i=0
    while [ "$i" -lt 90 ]; do
        docker info >/dev/null 2>&1 && { engine_ok=1; break; }
        i=$((i + 1)); sleep 2
    done
fi

need_engine=0
case "$cmd" in up|down|restart|logs|config|status) need_engine=1 ;; esac
if [ "$need_engine" = 1 ] && [ "$engine_ok" = 0 ] && [ "$TS_STACK_DRY_RUN" != 1 ]; then
    if [ "$cmd" = status ]; then
        warn "container engine unreachable — reporting the settings only"
    else
        warn "container engine unreachable"
        tss_engine_advice "$(tss_os)" "$kind" >&2
        exit 1
    fi
fi

# ── output ──────────────────────────────────────────────────────────────────────
# terminal-stack's doctor vocabulary, so `ts-doctor` can indent this straight in.
# The absorbed tree keeps its own OK/X/! gutter in services/**; two dialects in
# one command is worse than either.
issues=0
_ok()   { printf '  ok  %s
' "$1"; }
_bad()  { printf '  %s %s
' "$WARN" "$1"; issues=$((issues + 1)); }
_skip() { printf '  --  %s
' "$1"; }
_note() { printf '      %s
' "$1"; }

# ── verbs ───────────────────────────────────────────────────────────────────────

cmd_status() {
    local s state dir running total ports
    for s in $stacks; do
        state="$(stack_state "$s")"
        dir="$(tss_stack_dir "$s")"
        running=0; total=0
        if [ "$engine_ok" = 1 ]; then
            running="$( ( cd "$dir" && docker compose ps -q --status running 2>/dev/null ) | grep -c . || true )"
            total="$(   ( cd "$dir" && docker compose ps -aq 2>/dev/null )               | grep -c . || true )"
        fi
        if [ -n "$state" ] && [ "$total" = 0 ]; then
            printf '  --  %-12s %s\n' "$s" "${state#off:}"
            continue
        fi
        if [ -n "$state" ]; then
            # Intent and reality disagree. A warn, not a failure: this is exactly
            # what a doctor exists to surface, and it is not "broken".
            printf '  %s   %-12s running, but %s\n' "$WARN" "$s" "${state#off:}"
            printf '      %s\n' "ts-config agents ${s} on   (keep it)   |   ts-stack down $s   (stop it)"
            issues=$((issues + 1))
            continue
        fi
        if [ "$engine_ok" = 0 ]; then
            printf '      %-12s enabled (engine unreachable, state unknown)\n' "$s"
        elif [ "$total" = 0 ]; then
            printf '  %s   %-12s not created\n' "$WARN" "$s"; issues=$((issues + 1))
        elif [ "$running" = "$total" ]; then
            ports="$( ( cd "$dir" && docker compose ps --format '{{.Publishers}}' 2>/dev/null ) \
                      | tr ',' '\n' | sed -n 's/.*127\.0\.0\.1:\([0-9]*\).*/\1/p' | sort -un | tr '\n' ' ' )"
            printf '  ok  %-12s running (%s/%s)  %s\n' "$s" "$running" "$total" "$ports"
        else
            printf '  %s   %-12s partial (%s/%s)\n' "$WARN" "$s" "$running" "$total"; issues=$((issues + 1))
        fi
    done
}

# Every action warns when a stack ships a .env.example but has no .env: compose
# then silently falls back to the base file, which for kokoro means starting the
# GPU image with no GPU.
warn_unseeded() {
    local s
    for s in $stacks; do
        tss_env_seeded "$(tss_stack_dir "$s")" \
            || warn "$s: .env.example exists but .env does not — the stack will start with the wrong profile"
    done
}

selected() {                                # stacks that actually take part
    local s state out=''
    for s in $stacks; do
        state="$(stack_state "$s")"
        if [ -n "$state" ] && [ "$all" != 1 ]; then continue; fi
        out="$out $s"
    done
    printf '%s' "${out# }"
}

case "$cmd" in
    status) cmd_status ;;

    config)
        for s in $(selected); do
            section "$s"
            tss_compose "$s" config
        done ;;

    logs)
        [ -n "$want_stack" ] || { echo "ts-stack: logs needs a stack name" >&2; exit 2; }
        if [ "$follow" = 1 ]; then tss_compose "$want_stack" logs --tail "$tail_n" -f
        else                       tss_compose "$want_stack" logs --tail "$tail_n"; fi ;;

    up)
        # A legacy volume with no ts- replacement means compose would create an
        # EMPTY one and start the stack reporting success, with every memory left
        # behind in a volume nothing mounts. Refuse, and name the one command.
        pending="$(tss_volumes_pending 2>/dev/null || true)"
        if [ -n "$pending" ] && [ "$TS_STACK_DRY_RUN" != 1 ]; then
            _bad 'volumes still carry their pre-ts- names:'
            printf '%s\n' "$pending" | sed 's/^/        /'
            _note 'run:  ts-stack migrate-volumes     (copies, verifies, keeps the old volume)'
            exit 1
        fi
        warn_unseeded
        for s in $(selected); do
            section "$s"
            tss_compose "$s" up -d || _bad "up failed for $s"
        done ;;

    down)
        # -v is NEVER in this argv. Volumes are only ever destroyed by an
        # explicitly gated path, and that is enforced by test, not by comment.
        for s in $(selected); do
            section "$s"
            tss_compose "$s" down || _bad "down failed for $s"
        done ;;

    restart)
        # down + up, not `docker compose restart`: restart reuses the existing
        # container, so it does not pick up the changed .env or overlay that is
        # the reason anyone restarts.
        for s in $(selected); do
            section "$s"
            tss_compose "$s" down || true
            tss_compose "$s" up -d || _bad "restart failed for $s"
        done ;;

    bootstrap)
        # First run on this machine. Idempotent by design: every step reports
        # "left untouched" when it has already been done, so re-running after
        # adding a stack is the normal way to use it.
        # The library's step/info helpers read TSS_APPLY, so --dry-run maps onto it.
        TSS_APPLY=1
        [ "$TS_STACK_DRY_RUN" = 1 ] && TSS_APPLY=0
        section 'per-machine .env files'
        for s in $all_stacks; do tss_seed_env "$(tss_stack_dir "$s")"; done
        if [ -f "$SRC/services/.env" ]; then info 'services/.env already exists — left untouched'
        elif [ -f "$SRC/services/.env.example" ]; then
            step 'copy services/.env.example -> .env'
            [ "$TSS_APPLY" = 1 ] && cp "$SRC/services/.env.example" "$SRC/services/.env"
        fi

        section 'generated secrets'
        # headroom refuses to `compose config` without these two: both are
        # :?-required, deliberately, so a missing one fails loudly instead of
        # starting an open data plane. They are arbitrary strings, so there is no
        # reason to make a human paste them out of `openssl rand -hex 32`.
        python3 - "$SRC/bootstrap/agent-tools.json" <<'PY' | while IFS=$'\t' read -r key placeholder bytes; do
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8"))
for item in cfg.get("headroom", {}).get("generatedSecrets", []):
    print("%s\t%s\t%s" % (item["key"], item["placeholder"], item["bytes"]))
PY
            tss_fill_secret "$(tss_stack_dir headroom)/.env" "$key" "$placeholder" "$bytes"
        done

        section 'named volumes'
        # The two external volumes have to exist before the first `up`, because
        # external means compose will not create them. This is where every memory
        # you have ever saved lives, so an existing one is never touched.
        vols='ts-agentmemory-data'
        case "$(tss_compose_files "$(tss_stack_dir agentmemory)" | tr '\n' ' ')" in
            *docker-compose.console.yml*) vols="$vols ts-agentmemory-console-history" ;;
            *) info 'agentmemory .env selects no console profile — skipping the console volume' ;;
        esac
        for v in $vols; do
            if [ "$TSS_APPLY" = 0 ]; then step "docker volume create $v (if absent)"; continue; fi
            if docker volume inspect "$v" >/dev/null 2>&1; then
                info "'$v' already exists — left untouched (this is where your data lives)"
                continue
            fi
            # Creating it here would DEFEAT the migration guard: pending pairs are
            # only reported while the new name is absent, so an empty replacement
            # turns "your memories are in the old volume" into a silent success.
            legacy=""
            for pair in $(tss_volume_renames | tr ' ' ':'); do
                case "$pair" in *:"$v") legacy="${pair%%:*}" ;; esac
            done
            if [ -n "$legacy" ] && docker volume inspect "$legacy" >/dev/null 2>&1; then
                _bad "'$legacy' still holds this stack's data — NOT creating an empty '$v'"
                _note 'run:  ts-stack migrate-volumes'
                continue
            fi
            step "docker volume create $v"
            docker volume create "$v" >/dev/null || _bad "docker volume create failed for $v"
        done

        section 'next'
        _note 'ts-stack up        start the stacks your settings enable'
        _note 'ts-stack doctor    check the engine, the .env files and the ports' ;;

    migrate-volumes)
        # With the engine down `docker volume inspect` fails for BOTH names, so an
        # empty pending list means "unknown", not "current". Saying otherwise is a
        # false all-clear about the one operation that touches data.
        if [ "$engine_ok" = 0 ]; then
            _bad 'the engine is unreachable, so the volume names cannot be read'
            tss_engine_advice "$(tss_os)" "$kind" | sed 's/^/      /'
            exit 1
        fi
        pending="$(tss_volumes_pending 2>/dev/null || true)"
        if [ -z "$pending" ]; then
            _ok 'volume names are already current'
        else
            section 'migrate volumes'
            printf '%s\n' "$pending" | sed 's/^/  would copy: /'
            if [ "$TS_STACK_DRY_RUN" = 1 ]; then
                _note 'no --dry-run: the copy runs in a container and leaves the old volume in place'
            else
                # Nothing is destroyed here, so this needs consent but not a typed
                # phrase: the old volume survives as the rollback.
                printf 'Copy these now? The old volumes are kept. [y/N]: '
                read -r reply </dev/tty || reply=n
                case "$reply" in
                    [yY]*)
                        printf '%s\n' "$pending" | while read -r o n; do
                            [ -n "$o" ] || continue
                            tss_volume_copy "$o" "$n" || _bad "$o -> $n failed"
                        done
                        _note 'when the stack is proven on the new volumes: docker volume rm <old>' ;;
                    *) _note 'nothing copied' ;;
                esac
            fi
        fi ;;

    doctor)
        section 'engine'
        if [ "$engine_ok" = 1 ]; then
            _ok "engine reachable ($(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '?'))"
        else
            _bad "engine unreachable (kind: $kind)"
            tss_engine_advice "$(tss_os)" "$kind" | sed 's/^/      /'
        fi
        section 'stacks'
        cmd_status
        section 'volumes'
        pending="$(tss_volumes_pending 2>/dev/null || true)"
        if [ "$engine_ok" = 0 ]; then _skip 'volume names need the engine'
        elif [ -z "$pending" ]; then _ok 'volume names are current'
        else
            _bad 'volumes still carry their pre-ts- names — ts-stack migrate-volumes'
            printf '%s\n' "$pending" | sed 's/^/        /'
        fi
        section 'configuration'
        for s in $stacks; do
            if tss_env_seeded "$(tss_stack_dir "$s")"; then _ok "$s: .env present or not needed"
            else _bad "$s: .env.example exists but .env does not"; fi
        done
        if [ "$engine_ok" = 1 ]; then
            for s in $(selected); do
                if tss_compose "$s" config -q >/dev/null 2>&1; then _ok "$s: compose config parses"
                else _bad "$s: compose config failed — a required value is missing"; fi
            done
        else
            _skip 'compose config, health and the port audit need the engine'
        fi ;;
esac

if [ "$cmd" = doctor ] || [ "$cmd" = status ]; then
    printf '\n'
    if [ "$issues" = 0 ]; then printf 'ts-stack %s: all checks passed\n' "$cmd"
    else printf 'ts-stack %s: %s issue(s) found\n' "$cmd" "$issues"; exit 1; fi
fi
if [ "$TS_STACK_DRY_RUN" = 1 ]; then
    printf '\n%s\n' 'Nothing changed (--dry-run).'
fi
