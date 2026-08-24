#!/usr/bin/env bash
# stack.sh — drive every Docker stack in this repo from one place: list, status,
# up, down, logs. Read-only actions run immediately; --up and --down preview
# unless you pass --apply.
# macOS/Linux twin of stack.ps1 (canonical). Port changes both ways.
#
# Usage:  ./stack.sh [--list|--status|--up|--down|--logs] [--stack <name>]
#                    [--tail <n>] [--follow] [--apply]
# When:   Day to day: bringing the local stacks up after a reboot, checking
#         what's healthy, or tailing a container that misbehaves. Run
#         ./bootstrap.sh first on a new machine.
set -euo pipefail

_self="${BASH_SOURCE[0]}"
while [ -L "$_self" ]; do
    _d="$(cd -- "$(dirname -- "$_self")" && pwd)"; _self="$(readlink "$_self")"
    case "$_self" in /*) ;; *) _self="$_d/$_self" ;; esac
done
SCRIPT_DIR="$(cd -- "$(dirname -- "$_self")" && pwd -P)"
# shellcheck source=_common.sh
. "$SCRIPT_DIR/_common.sh"

want_stack=''
do_list=0; do_status=0; do_up=0; do_down=0; do_logs=0
tail_n=50; follow=0

while [ $# -gt 0 ]; do
    arg="$(dl_normalise_flag "$1")"
    if dl_parse_common_flag "$arg" "${2:-}"; then shift "$DL_FLAG_CONSUMED"; continue; fi
    case "$arg" in
        --list)   do_list=1;   shift ;;
        --status) do_status=1; shift ;;
        --up)     do_up=1;     shift ;;
        --down)   do_down=1;   shift ;;
        --logs)   do_logs=1;   shift ;;
        --follow) follow=1;    shift ;;
        --stack)  want_stack="${2:?--stack needs a value}"; shift 2 ;;
        --tail)   tail_n="${2:?--tail needs a value}"; dl_require_int --tail "$tail_n" 0 100000; shift 2 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

require_docker

# A "stack" is any top-level directory holding a docker-compose.yml. New stacks
# need no registration here — drop the directory in and it is picked up. The
# glob is already lexically sorted, so no explicit sort is needed.
stacks=''
for d in "$DL_ROOT"/*/; do
    [ -f "$d/docker-compose.yml" ] || continue
    stacks="$stacks $(basename "$d")"
done
stacks="${stacks# }"

if [ -n "$want_stack" ]; then
    found=''
    for s in $stacks; do [ "$s" = "$want_stack" ] && found="$s"; done
    [ -n "$found" ] || die "no stack named '$want_stack' — run ./stack.sh --list to see what exists"
    stacks="$found"
fi
[ -n "$stacks" ] || die "no stacks found under $DL_ROOT"

# Default action
if [ $((do_list + do_status + do_up + do_down + do_logs)) -eq 0 ]; then do_list=1; fi

n_stacks=0
for s in $stacks; do n_stacks=$((n_stacks + 1)); done
if [ "$follow" = 1 ] && [ "$n_stacks" -gt 1 ]; then
    die '--follow needs a single stack — pass --stack <name>'
fi

# A stack that ships a .env.example but has no .env is misconfigured: compose
# silently falls back to the base file only, which for kokoro means starting the
# GPU image with no GPU access. Surface it on every action.
for s in $stacks; do
    dl_env_seeded "$DL_ROOT/$s" || \
        warn "$s: .env.example exists but .env does not — run ./bootstrap.sh --apply first, or this stack will start with the wrong profile"
done

for s in $stacks; do
    dir="$DL_ROOT/$s"

    if [ "$do_list" = 1 ]; then
        files="$(dl_compose_files "$dir" | tr '\n' ' ' | sed 's/ $//; s/ / + /g')"
        # grep -c exits 1 on zero matches, which set -e would treat as fatal.
        running="$( ( cd "$dir" && docker compose ps -q --status running 2>/dev/null ) | grep -c . || true )"
        total="$(   ( cd "$dir" && docker compose ps -aq 2>/dev/null )               | grep -c . || true )"
        if [ "$total" -eq 0 ]; then state='not created'; colour="$C_DIM"
        elif [ "$running" -eq "$total" ]; then state="running ($running/$total)"; colour="$C_GREEN"
        else state="partial ($running/$total)"; colour="$C_YELLOW"; fi
        printf '%s%-14s %s%s\n' "$colour" "$s" "$state" "$C_RESET"
        info "compose files: $files"
    fi

    if [ "$do_status" = 1 ]; then
        section "$s"
        ( cd "$dir" && docker compose ps )
    fi

    if [ "$do_logs" = 1 ]; then
        section "$s logs"
        if [ "$follow" = 1 ]; then ( cd "$dir" && docker compose logs --tail "$tail_n" -f )
        else                        ( cd "$dir" && docker compose logs --tail "$tail_n" ); fi
    fi

    if [ "$do_up" = 1 ]; then
        section "$s"
        step 'docker compose up -d'
        if [ "$DL_APPLY" = 1 ]; then
            ( cd "$dir" && docker compose up -d ) || warn "up failed for $s — see the output above"
        fi
    fi

    if [ "$do_down" = 1 ]; then
        section "$s"
        step 'docker compose down   (containers only; named volumes and cached images are kept)'
        if [ "$DL_APPLY" = 1 ]; then
            ( cd "$dir" && docker compose down ) || warn "down failed for $s — see the output above"
        fi
    fi
done

printf '\n'
if [ $((do_up + do_down)) -gt 0 ] && [ "$DL_APPLY" != 1 ]; then
    printf '%sNothing changed (preview). Add --apply to perform.%s\n' "$C_WHITE" "$C_RESET"
elif [ $((do_up + do_down)) -gt 0 ]; then
    printf '%sDone. Verify with: ./stack.sh --status%s\n' "$C_GREEN" "$C_RESET"
fi
