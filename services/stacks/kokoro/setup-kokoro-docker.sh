#!/usr/bin/env bash
# setup-kokoro-docker.sh — create (or start) a local Kokoro TTS container
# reachable at http://127.0.0.1:8880. Previews by default; --undo removes it
# (still needs --apply).
# macOS/Linux twin of setup-kokoro-docker.ps1 (canonical). Port changes both ways.
#
# Usage:  ./setup-kokoro-docker.sh [--cpu] [--gpu-tag <tag>] [--port <n>]
#                                  [--container-name <name>] [--apply] [--undo]
# When:   Standing up (or tearing down) the local Kokoro TTS container. See
#         README.md here for the full writeup, including the Blackwell/GPU-tag
#         gotcha this script works around.
# Note:   docker-compose.yml is canonical in this repo; this script is the
#         preview-mode escape hatch. The .ps1 is a deliberate copy of
#         claude-local/tools/windows/system/setup-kokoro-docker.ps1 — port
#         changes to both. Both paths bind 127.0.0.1 only.
set -euo pipefail

_self="${BASH_SOURCE[0]}"
while [ -L "$_self" ]; do
    _d="$(cd -- "$(dirname -- "$_self")" && pwd)"; _self="$(readlink "$_self")"
    case "$_self" in /*) ;; *) _self="$_d/$_self" ;; esac
done
SCRIPT_DIR="$(cd -- "$(dirname -- "$_self")" && pwd -P)"
# shellcheck source=../_common.sh
. "$SCRIPT_DIR/../_common.sh"

use_cpu=0
gpu_tag='v0.8.0-cu128'
port=8880
container_name='kokoro'

# The .ps1 hardcodes ':latest' for the CPU image. This file pins instead, because
# docs/conventions.md forbids ':latest' and a new file should not inherit an old
# violation. Registered in the divergence register; bring the .ps1 into line the
# next time it is touched. v0.8.0 is the same upstream release as the GPU tags.
cpu_tag='v0.8.0'

while [ $# -gt 0 ]; do
    arg="$(dl_normalise_flag "$1")"
    if dl_parse_common_flag "$arg" "${2:-}"; then shift "$DL_FLAG_CONSUMED"; continue; fi
    case "$arg" in
        --cpu)            use_cpu=1; shift ;;
        --gpu-tag)        gpu_tag="${2:?--gpu-tag needs a value}"; shift 2 ;;
        --cpu-tag)        cpu_tag="${2:?--cpu-tag needs a value}"; shift 2 ;;
        --port)           port="${2:?--port needs a value}"; dl_require_int --port "$port" 1 65535; shift 2 ;;
        --container-name) container_name="${2:?--container-name needs a value}"; shift 2 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

require_docker

# Docker Desktop for Mac has no GPU passthrough of any kind. REFUSE rather than
# quietly substituting the CPU image: something that starts fine and is silently
# wrong later is precisely the failure mode kokoro's Blackwell gotcha is about,
# and a silent switch would hide which image you are actually running.
if [ "$DL_UNDO" != 1 ] && [ "$use_cpu" != 1 ] && [ "$(dl_os)" = darwin ]; then
    die "Docker Desktop for Mac has no NVIDIA GPU passthrough (and no Metal/MPS passthrough), so the GPU image cannot run here.
Re-run with --cpu, or use compose with Profile C, which is what this stack expects on a Mac:
  ../stack.sh --stack kokoro --up --apply"
fi

if [ "$use_cpu" = 1 ]; then image="ghcr.io/remsky/kokoro-fastapi-cpu:$cpu_tag"
else                        image="ghcr.io/remsky/kokoro-fastapi-gpu:$gpu_tag"; fi

dl_mode >/dev/null
printf '%ssetup-kokoro-docker  mode=%s  image=%s  port=%s%s\n' "$C_WHITE" "$DL_MODE" "$image" "$port" "$C_RESET"
[ "$DL_APPLY" = 1 ] || printf '%s(preview only — re-run with --apply to perform, or --undo --apply to remove)%s\n' "$C_DIM" "$C_RESET"

if [ "$DL_UNDO" != 1 ] && [ "$use_cpu" != 1 ] && have nvidia-smi; then
    section 'GPU headroom'
    nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv,noheader 2>/dev/null \
        | while IFS= read -r l; do [ -n "$l" ] && info "$l"; done
    info 'this container will share the display GPU if one drives your monitors — see README.md'
fi

# The macOS analogue of the Blackwell gotcha: an image with no matching manifest
# either gets emulated (very slow) or refuses to start.
if [ "$DL_UNDO" != 1 ]; then
    case "$(uname -m)" in
        arm64|aarch64) want_arch=arm64 ;;
        x86_64|amd64)  want_arch=amd64 ;;
        *)             want_arch='' ;;
    esac
    if [ -n "$want_arch" ]; then
        # Capture the status explicitly: 2 ("could not tell") and 1 ("definitely
        # absent") mean very different things, and a bare $? after a failed
        # condition silently breaks the day a line is inserted above it.
        arch_rc=0; dl_image_has_arch "$image" "$want_arch" || arch_rc=$?
        case "$arch_rc" in
            0) ;;
            2) info "could not reach the registry to confirm $image has a linux/$want_arch image" ;;
            *) warn "$image has NO linux/$want_arch image — Docker will emulate it (very slow) or fail to start" ;;
        esac
    fi
fi

section 'Container status'
existing="$(docker ps -a --filter "name=^${container_name}$" --format '{{.Names}}|{{.Status}}' 2>/dev/null | head -n 1)"

if [ "$DL_UNDO" = 1 ]; then
    if [ -z "$existing" ]; then
        info "no container named '$container_name' — nothing to remove"
    else
        name="${existing%%|*}"
        step "docker rm -f $name  (removes the container; the pulled image stays cached — 'docker rmi $image' to reclaim disk)"
        if [ "$DL_APPLY" = 1 ]; then docker rm -f "$name" >/dev/null; info 'removed'; fi
    fi
else
    if [ -n "$existing" ]; then
        name="${existing%%|*}"; status="${existing#*|}"
        case "$status" in
            Up*) info "'$name' already running ($status) — nothing to do" ;;
            *)   step "docker start $name  (existing container is stopped: $status)"
                 if [ "$DL_APPLY" = 1 ]; then docker start "$name" >/dev/null; info 'started'; fi ;;
        esac
    else
        step "docker pull $image"
        if [ "$DL_APPLY" = 1 ]; then
            docker pull "$image" || die "docker pull failed for $image"
        fi
        # Loopback-bound on purpose: this API has no auth (../docs/conventions.md).
        set -- run -d --name "$container_name" --restart unless-stopped
        [ "$use_cpu" = 1 ] || set -- "$@" --gpus all
        set -- "$@" -p "127.0.0.1:${port}:8880" "$image"
        step "docker $*"
        if [ "$DL_APPLY" = 1 ]; then
            docker "$@" >/dev/null || die "docker run failed for $container_name"
            info "created '$container_name'"
        fi
    fi
fi

if [ "$DL_UNDO" != 1 ]; then
    section 'Verification'
    if [ "$DL_APPLY" = 1 ]; then
        info 'waiting for the app to come up...'
        ok=0; i=0
        while [ "$i" -lt 20 ]; do
            sleep 1; i=$((i + 1))
            state="$(docker inspect "$container_name" --format '{{.State.Status}}' 2>/dev/null || echo '')"
            case "$state" in exited|restarting) break ;; esac
            # Readiness only — NOT the loopback assertion, which runs below once
            # something is actually listening to assert about.
            port_listening "$port" || continue
            if [ "$(http_status "http://127.0.0.1:$port/docs" 3)" = 200 ]; then ok=1; break; fi
        done
        if [ "$ok" = 1 ]; then
            info "http://127.0.0.1:$port/docs responded 200 — Kokoro is up"
        else
            info 'not responding yet — recent container logs:'
            docker logs --tail 20 "$container_name" 2>&1 | while IFS= read -r l; do info "  $l"; done
        fi
        # The .ps1 never verifies the bind it just built by hand. This is the
        # repo's single most important rule, so assert it here too.
        assert_loopback_only "$port" || warn 'the port above is NOT loopback-only — fix before using this'
    else
        info "after --apply, verify with: curl -fsS -o /dev/null -w '%{http_code}\\n' http://127.0.0.1:$port/docs"
    fi
fi

dl_summary
