#!/usr/bin/env bash
# migrate-durable-llm.sh — back up AgentMemory, deploy the durable LLM queue +
# graph v2 state, and verify it. Preview-only unless --apply is passed.
# macOS/Linux twin of migrate-durable-llm.ps1 (canonical). Port both ways.
#
# Usage:  ./migrate-durable-llm.sh [--apply] [--backup-root <dir>]
# When:   First deployment of the AgentMemory 0.9.29 durable-queue compatibility
#         layer. Safe to re-run after graph v2 is active.
# Note:   The backup root defaults under $HOME rather than the .ps1's C:\DATA,
#         which is also what Docker Desktop for Mac shares by default — a bind
#         mount from outside $HOME fails at run time.
set -euo pipefail

_self="${BASH_SOURCE[0]}"
while [ -L "$_self" ]; do
    _d="$(cd -- "$(dirname -- "$_self")" && pwd)"; _self="$(readlink "$_self")"
    case "$_self" in /*) ;; *) _self="$_d/$_self" ;; esac
done
SCRIPT_DIR="$(cd -- "$(dirname -- "$_self")" && pwd -P)"
# shellcheck source=../../_stack.sh
. "$SCRIPT_DIR/../../_stack.sh"

# The console lives in its OWN compose project (ts-agent007memory) since the
# split, so `docker compose stop console` from this directory stops nothing and
# says nothing -- it would have left the console reading a volume this script is
# about to move. Stop it where it actually lives, and only if it is there.
am_console() {                            # stop | up
    local dir="$stack_dir/../agent007memory"
    [ -f "$dir/docker-compose.yml" ] || return 0
    case "$1" in
        stop) ( cd "$dir" && docker compose stop ) ;;
        up)   ( cd "$dir" && docker compose up -d ) ;;
    esac
}


backup_root="$(tss_backup_root)"
while [ $# -gt 0 ]; do
    arg="$(tss_normalise_flag "$1")"
    if tss_parse_common_flag "$arg" "${2:-}"; then shift "$TSS_FLAG_CONSUMED"; continue; fi
    case "$arg" in
        --backup-root) backup_root="${2:?--backup-root needs a value}"; shift 2 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

stack_dir="$SCRIPT_DIR"
[ "$(basename "$stack_dir")" = agentmemory ] || die "unexpected stack directory: $stack_dir"
[ -f "$stack_dir/docker-compose.yml" ] || die "docker-compose.yml missing in $stack_dir"
cd "$stack_dir"

mkdir -p "$backup_root" 2>/dev/null || true
backup_root_full="$(tss_realpath "$backup_root")" || die "cannot resolve backup root: $backup_root"
tss_backup_root_sane "$backup_root_full" \
    || die "backup root is too broad or outside \$HOME: $backup_root_full
Set TS_STACK_ALLOW_ANY_BACKUP_ROOT=1 to override, or pass --backup-root."
tss_assert_docker_shareable "$backup_root_full" \
    || die "Docker Desktop for Mac cannot bind-mount $backup_root_full — it only shares \$HOME, /tmp, /private and /Volumes by default. Pick a path under \$HOME or add it in Settings -> Resources -> File sharing."

backup_dir="$backup_root_full/$(stamp)"

tss_mode >/dev/null
printf '%smigrate-durable-llm  mode=%s  stack=%s%s\n' "$C_WHITE" "$TSS_MODE" "$stack_dir" "$C_RESET"

section 'Preflight'
docker compose config --quiet || die 'docker compose config failed'
docker volume inspect ts-agentmemory-data >/dev/null 2>&1 || die 'Docker volume ts-agentmemory-data does not exist'
secret="$(docker compose exec -T agentmemory cat /data/.hmac 2>/dev/null | tr -d '\r\n' || true)"
[ -n "$secret" ] || die 'could not read AgentMemory HMAC before backup'
info 'compose config, external volume, and HMAC are present'

section 'Cold backup'
step 'stop console and agentmemory'
step "create $backup_dir/agentmemory-volume.tgz"
if [ "$TSS_APPLY" = 1 ]; then
    mkdir -p "$backup_dir"
    resolved_backup="$(tss_realpath "$backup_dir")" || die "cannot resolve $backup_dir"
    # The resolved path is bind-mounted into a container that writes into it, so
    # a symlinked or ..-bearing root must not be able to escape.
    tss_assert_within "$backup_root_full" "$resolved_backup" \
        || die "resolved backup directory escaped backup root: $resolved_backup"

    am_console stop || die 'failed to stop the console'
    docker compose stop agentmemory || die 'failed to stop stack for backup'

    # Derive the image rather than hardcoding agentmemory-agentmemory:latest,
    # which is right only because the compose project name happens to match the
    # directory name. reconcile-llm-queue.ps1 already derives it properly.
    image="$(tss_compose_image "$stack_dir" agentmemory)" || die 'could not resolve the agentmemory image'
    info "backup image: $image"
    docker run --rm --entrypoint sh \
        -v 'ts-agentmemory-data:/source:ro' -v "${resolved_backup}:/backup" \
        "$image" -c 'tar -C /source -czf /backup/agentmemory-volume.tgz .' \
        || die 'volume backup failed; stack remains stopped'

    archive="$resolved_backup/agentmemory-volume.tgz"
    [ -f "$archive" ] || die "backup archive is missing: $archive"
    size="$(file_size "$archive")"
    [ "$size" -ge 1048576 ] || die "backup archive is unexpectedly small ($size bytes): $archive"
    info "backup: $(awk -v b="$size" 'BEGIN{printf "%.1f", b/1048576}') MB"
fi

section 'Deploy'
step 'build the patched AgentMemory image and recreate the stack'
if [ "$TSS_APPLY" = 1 ]; then
    docker compose build agentmemory console || die 'image build failed'
    docker compose up -d || die 'stack start failed'
    am_console up || die 'console start failed'
fi

section 'Verify graph migration'
step 'wait for authenticated graph migration status=complete'
if [ "$TSS_APPLY" = 1 ]; then
    done_ok=0; attempt=0
    while [ $attempt -lt 120 ]; do
        attempt=$((attempt + 1))
        m="$(http_get_auth 'http://127.0.0.1:3110/agentmemory/admin/graph-migration' "$secret" 10 2>/dev/null || true)"
        if [ -n "$m" ]; then
            verdict="$(printf '%s' "$m" | node -e '
              let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
                try{const j=JSON.parse(s);const st=j.manifest&&j.manifest.status;
                  if(st==="failed"){process.stdout.write("failed");return;}
                  process.stdout.write(j.active&&st==="complete"?"complete":"pending");
                }catch{process.stdout.write("pending");}
              });' 2>/dev/null || echo pending)"
            [ "$verdict" = failed ] && die 'graph v2 migration reported failed'
            if [ "$verdict" = complete ]; then
                done_ok=1
                printf '%s' "$m" | node -e '
                  let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
                    try{const j=JSON.parse(s).manifest||{};
                      console.log(`       graph v2: ${j.totalNodes} nodes, ${j.totalEdges} edges, ${j.shards} shards`);}catch{}
                  });'
                break
            fi
        fi
        sleep 5
    done
    [ "$done_ok" = 1 ] || die 'graph v2 migration did not complete within 10 minutes'
fi

section 'Verify durable LLM work'
step 'confirm startup recovery requeued raw observations, reconciled counts, and exposed queue/DLQ telemetry'
if [ "$TSS_APPLY" = 1 ]; then
    t="$(http_get_auth 'http://127.0.0.1:3110/agentmemory/llm/telemetry?limit=20' "$secret" 30)" \
        || die 'could not read LLM telemetry'
    read -r depth active dlq <<EOF
$(printf '%s' "$t" | node -e '
  let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
    try{const j=JSON.parse(s);const q=j.queue||{};
      process.stdout.write(`${q.depth??0} ${j.activeJobs??0} ${q.dlq_depth??0}`);}
    catch{process.stdout.write("0 0 0");}
  });')
EOF
    info "queue depth: $depth; active: $active; DLQ: $dlq"
    [ "${dlq:-0}" -eq 0 ] || die 'LLM queue DLQ is not empty'
    for url in 'http://127.0.0.1:3110/agentmemory/livez' \
               'http://127.0.0.1:3111/agentmemory/livez' \
               'http://127.0.0.1:3114/healthz'; do
        code="$(http_status "$url" 10)"
        [ "$code" = 200 ] || die "verification failed: $url returned $code"
    done
    info 'bypass, proxy, and console health checks returned 200'
fi

printf '\n%sdone (%s)%s\n' "$C_WHITE" "$TSS_MODE" "$C_RESET"
[ "$TSS_APPLY" = 1 ] || printf '%sre-run with --apply to back up, deploy, migrate, and verify%s\n' "$C_DIM" "$C_RESET"
