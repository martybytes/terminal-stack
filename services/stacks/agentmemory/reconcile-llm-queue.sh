#!/usr/bin/env bash
# reconcile-llm-queue.sh — quarantine stale durable LLM queue records and run one
# bounded, state-driven recovery pass.
# macOS/Linux twin of reconcile-llm-queue.ps1 (canonical). Port changes both ways.
#
# Usage:  ./reconcile-llm-queue.sh [--apply] [--backup-root <dir>]
#           [--max-planned-terra-calls N] [--max-estimated-cost-usd N]
#           [--recovery-timeout-seconds N] [--post-recovery-soak-seconds N]
# When:   Queue telemetry is stuck with old active jobs or a historical DLQ
#         after provider recovery.
# Note:   Preview-only unless --apply. Apply takes a cold full-volume backup,
#         moves the exact /data/queue_store directory to a timestamped
#         quarantine directory, starts with a fresh queue, and lets
#         AgentMemory's own startup reconciliation enqueue only work still
#         missing from durable state. It never bulk-redrives the DLQ and never
#         deletes the quarantine or the backup.
set -euo pipefail

_self="${BASH_SOURCE[0]}"
while [ -L "$_self" ]; do
    _d="$(cd -- "$(dirname -- "$_self")" && pwd)"; _self="$(readlink "$_self")"
    case "$_self" in /*) ;; *) _self="$_d/$_self" ;; esac
done
SCRIPT_DIR="$(cd -- "$(dirname -- "$_self")" && pwd -P)"
# shellcheck source=../_common.sh
. "$SCRIPT_DIR/../_common.sh"

backup_root="$(dl_backup_root)"
max_terra=25
max_cost=1.00
recovery_timeout=600
soak_seconds=105

while [ $# -gt 0 ]; do
    arg="$(dl_normalise_flag "$1")"
    if dl_parse_common_flag "$arg" "${2:-}"; then shift "$DL_FLAG_CONSUMED"; continue; fi
    case "$arg" in
        --backup-root)                backup_root="${2:?needs a value}"; shift 2 ;;
        --max-planned-terra-calls)    max_terra="${2:?needs a value}";   dl_require_int  --max-planned-terra-calls "$max_terra" 1 1000; shift 2 ;;
        --max-estimated-cost-usd)     max_cost="${2:?needs a value}";    dl_require_num  --max-estimated-cost-usd "$max_cost" 0.01 1000; shift 2 ;;
        --recovery-timeout-seconds)   recovery_timeout="${2:?needs a value}"; dl_require_int --recovery-timeout-seconds "$recovery_timeout" 60 3600; shift 2 ;;
        --post-recovery-soak-seconds) soak_seconds="${2:?needs a value}"; dl_require_int --post-recovery-soak-seconds "$soak_seconds" 90 600; shift 2 ;;
        *) die "unknown option: $1 (try --help)" ;;
    esac
done

stack_dir="$SCRIPT_DIR"
compose_file="$stack_dir/docker-compose.yml"
volume_name='agentmemory_iii-data'
API='http://127.0.0.1:3110/agentmemory'
[ -f "$compose_file" ] || die "docker-compose.yml missing in $stack_dir"
cd "$stack_dir"

st="$(stamp)"
quarantine_name="queue_store.quarantine-$st"
printf '%s' "$quarantine_name" | grep -qE '^queue_store\.quarantine-[0-9]{8}-[0-9]{6}$' \
    || die "unexpected quarantine name: $quarantine_name"

mkdir -p "$backup_root" 2>/dev/null || true
backup_root_full="$(dl_realpath "$backup_root")" || die "cannot resolve backup root: $backup_root"
dl_backup_root_sane "$backup_root_full" \
    || die "backup root is too broad or outside \$HOME: $backup_root_full
Set DOCKER_LOCAL_ALLOW_ANY_BACKUP_ROOT=1 to override, or pass --backup-root."
backup_dir="$backup_root_full/$st"

# ---- embedded programs -------------------------------------------------------
# Both of these run INSIDE the container and are already platform-neutral, so
# they are copied verbatim. Quoted heredocs: nothing here may be expanded by the
# host shell, and .gitattributes guarantees LF, which `sh -c` with `set -eu`
# needs (a stray CR would end up inside a variable value).
read -r -d '' ANALYSIS_JS <<'ANALYSIS_EOF' || true
const fs = require("fs");
function readJsonFile(path) {
  const bytes = fs.readFileSync(path);
  for (let i = bytes.length - 1; i >= 0; i -= 1) {
    if (bytes[i] !== 125) continue;
    try { return JSON.parse(bytes.subarray(0, i + 1).toString("utf8")); } catch {}
  }
  throw new Error(`could not decode ${path}`);
}
function state(scope) {
  const path = `/data/state_store.db/${encodeURIComponent(scope)}.bin`;
  return fs.existsSync(path) ? readJsonFile(path) : {};
}
function queueLists() {
  const path = "/data/queue_store/_queue_lists.bin";
  return fs.existsSync(path) ? readJsonFile(path) : {};
}
function activeJobs(lists) {
  const ids = lists["queue:__fn_queue::agentmemory-llm:active"] || [];
  const jobs = [];
  let missingFiles = 0;
  for (const id of ids) {
    const path = `/data/queue_store/${encodeURIComponent(`queue:__fn_queue::agentmemory-llm:jobs:${id}`)}.bin`;
    if (!fs.existsSync(path)) { missingFiles += 1; continue; }
    const row = readJsonFile(path);
    jobs.push(row[""] || Object.values(row)[0]);
  }
  return { jobs, missingFiles };
}
function familyCounts(jobs) {
  return jobs.reduce((out, job) => {
    const family = job?.data?.family || "missing";
    out[family] = (out[family] || 0) + 1;
    return out;
  }, {});
}
const lists = queueLists();
const active = activeJobs(lists);
const dlqRows = (lists["queue:__fn_queue::agentmemory-llm:dlq"] || []).map((value) => JSON.parse(value).job);
const sessionRows = Object.values(state("mem:sessions"));
const sessions = sessionRows.filter((row) => row?.id);
const summaries = state("mem:summaries");
const config = state("mem:config");
const observationCache = new Map();
function observations(sessionId) {
  if (!observationCache.has(sessionId)) {
    observationCache.set(sessionId, Object.values(state(`mem:obs:${sessionId}`)));
  }
  return observationCache.get(sessionId);
}
const summaryMinimum = Number(process.env.AGENTMEMORY_AUTO_SUMMARY_MIN_OBSERVATIONS || 10);
const summaryDeltaMinimum = Number(process.env.AGENTMEMORY_AUTO_SUMMARY_MIN_NEW_OBSERVATIONS || 25);
const summaryMaximumAge = Number(process.env.AGENTMEMORY_AUTO_SUMMARY_MAX_AGE_MS || 3600000);
const graphMinimum = Number(process.env.AGENTMEMORY_AUTO_GRAPH_MIN_NEW_OBSERVATIONS || 10);
const graphMaximum = Number(process.env.AGENTMEMORY_AUTO_GRAPH_MAX_OBSERVATIONS_PER_RUN || 25);
let rawObservations = 0;
const summaryDue = [];
const graphDue = [];
for (const session of sessions) {
  const rows = observations(session.id);
  rawObservations += rows.filter((row) => row && !row.title).length;
  const compressed = rows.filter((row) => row?.title).sort((a, b) => {
    const at = new Date(a.timestamp || a.createdAt || 0).getTime();
    const bt = new Date(b.timestamp || b.createdAt || 0).getTime();
    return at - bt || String(a.id || "").localeCompare(String(b.id || ""));
  });
  const existing = summaries[session.id];
  const delta = Math.max(0, compressed.length - (Number(existing?.observationCount) || 0));
  const age = existing?.createdAt ? Date.now() - new Date(existing.createdAt).getTime() : Infinity;
  if (compressed.length >= summaryMinimum && (!existing || delta >= summaryDeltaMinimum || (delta > 0 && age >= summaryMaximumAge))) {
    summaryDue.push(session.id);
  }
  const marker = config[`graph:auto:${session.id}`];
  const markedIndex = marker?.lastObservationId ? compressed.findIndex((row) => row.id === marker.lastObservationId) : -1;
  const start = markedIndex >= 0 ? markedIndex + 1 : Math.min(Number(marker?.processedObservationCount) || 0, compressed.length);
  const pending = compressed.length - start;
  if (compressed.length > 0 && pending > 0 && (!marker || pending >= graphMinimum)) {
    graphDue.push({
      sessionId: session.id,
      markerCount: Number(marker?.processedObservationCount) || 0,
      pending
    });
  }
}
function compressionState(jobs) {
  const out = { raw: 0, alreadyCompressed: 0, missingObservation: 0, malformed: 0 };
  for (const job of jobs.filter((row) => row?.data?.family === "compression")) {
    const data = job.data;
    if (!data.sessionId || !data.observationId) { out.malformed += 1; continue; }
    const row = observations(data.sessionId).find((item) => item?.id === data.observationId);
    if (!row) out.missingObservation += 1;
    else if (row.title) out.alreadyCompressed += 1;
    else out.raw += 1;
  }
  return out;
}
const waitingKey = "queue:__fn_queue::agentmemory-llm:waiting";
const activeKey = "queue:__fn_queue::agentmemory-llm:active";
const dlqKey = "queue:__fn_queue::agentmemory-llm:dlq";
console.log(JSON.stringify({
  sessions: sessions.length,
  malformedSessions: sessionRows.length - sessions.length,
  rawObservations,
  summaryDueSessionIds: summaryDue,
  graphDue,
  projectedTerraCalls: graphDue.length + summaryDue.length * 3,
  queue: {
    waiting: (lists[waitingKey] || []).length,
    active: (lists[activeKey] || []).length,
    dlq: (lists[dlqKey] || []).length,
    activeMissingFiles: active.missingFiles,
    activeByFamily: familyCounts(active.jobs),
    dlqByFamily: familyCounts(dlqRows),
    activeCompressionState: compressionState(active.jobs),
    dlqCompressionState: compressionState(dlqRows)
  },
  graphPolicy: { minimumNew: graphMinimum, maximumPerRun: graphMaximum }
}));
ANALYSIS_EOF

read -r -d '' QUARANTINE_SH <<'QUARANTINE_EOF' || true
set -eu
src=/data/queue_store
case "${QUEUE_QUARANTINE_NAME:-}" in
  queue_store.quarantine-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) echo "invalid quarantine name" >&2; exit 20 ;;
esac
dst="/data/$QUEUE_QUARANTINE_NAME"
[ -d "$src" ] || { echo "queue store is not a directory" >&2; exit 21; }
[ ! -L "$src" ] || { echo "queue store is a symbolic link" >&2; exit 22; }
resolved="$(readlink -f "$src")"
[ "$resolved" = "$src" ] || { echo "unexpected resolved queue path: $resolved" >&2; exit 23; }
[ ! -e "$dst" ] || { echo "quarantine target already exists" >&2; exit 24; }
count="$(find "$src" -mindepth 1 -maxdepth 1 -print | wc -l)"
echo "validated queue store entries=$count source=$src target=$dst"
mv "$src" "$dst"
mkdir "$src"
chown 1000:1000 "$src"
sync
QUARANTINE_EOF

# ---- money and map arithmetic, all in node -----------------------------------
# bash has no floats and bash 3.2 no associative arrays, so every cost figure,
# group-by-average and marker diff is computed here and comes back as plain
# fields. Crucially the COMPARISONS happen in node too and return 0/1 verdicts:
# bash never compares a float.
metrics() {                               # <telemetry-json> <max-terra> <max-cost>
    printf '%s' "$1" | node -e '
      let s=""; process.stdin.on("data",d=>s+=d).on("end",()=>{
        const [maxTerra,maxCost]=process.argv.slice(1).map(Number);
        let j={}; try{ j=JSON.parse(s); }catch{}
        const calls=j.calls||[];
        const cost=(rows)=>rows.reduce((t,c)=>{
          if(c.promptTokens==null||c.completionTokens==null) return t;
          if(c.model==="gpt-5.6-terra") return t + c.promptTokens*2/1e6 + c.completionTokens*12/1e6;
          if(c.model==="gpt-5.6-luna")  return t + c.promptTokens*0.20/1e6 + c.completionTokens*1.20/1e6;
          return t;
        },0);
        const terra=calls.filter(c=>c.model==="gpt-5.6-terra").length;
        const luna =calls.filter(c=>c.model==="gpt-5.6-luna").length;
        const actual=cost(calls);
        const failed=calls.filter(c=>c.outcome==="failure").length;
        const q=j.queue||{};
        const circuit=(j.circuitBreaker&&j.circuitBreaker.state)||"unknown";
        const tripped=(terra>maxTerra||actual>maxCost||(q.dlq_depth||0)>0||circuit==="open")?1:0;
        const settled=((q.depth||0)===0&&(q.dlq_depth||0)===0&&(j.activeJobs||0)===0)?1:0;
        process.stdout.write([q.depth||0,q.dlq_depth||0,j.activeJobs||0,terra,luna,
          actual.toFixed(2),circuit,tripped,settled,failed].join(" "));
      });' "$2" "$3"
}

projected_cost() {                        # <analysis-json> <telemetry-json> <max-cost>
    node -e '
      const [aRaw,tRaw,maxCost]=process.argv.slice(1);
      let a={},t={}; try{a=JSON.parse(aRaw);}catch{} try{t=JSON.parse(tRaw);}catch{}
      const cost=(rows)=>rows.reduce((s,c)=>{
        if(c.promptTokens==null||c.completionTokens==null) return s;
        if(c.model==="gpt-5.6-terra") return s + c.promptTokens*2/1e6 + c.completionTokens*12/1e6;
        if(c.model==="gpt-5.6-luna")  return s + c.promptTokens*0.20/1e6 + c.completionTokens*1.20/1e6;
        return s;
      },0);
      const ok=(t.calls||[]).filter(c=>c.outcome==="success"&&c.model==="gpt-5.6-terra"
        &&c.promptTokens!=null&&c.completionTokens!=null);
      const avg=(family)=>{
        const byJob={};
        for(const c of ok.filter(c=>c.family===family)) (byJob[c.jobId]??=[]).push(c);
        const costs=Object.values(byJob).map(cost);
        return costs.length?costs.reduce((x,y)=>x+y,0)/costs.length:null;
      };
      // Conservative fallbacks use recent observed job shapes if telemetry was reset.
      const g=avg("graph")??0.023, sm=avg("summary")??0.135;
      const projected=(a.graphDue||[]).length*g+(a.summaryDueSessionIds||[]).length*sm;
      process.stdout.write([g.toFixed(4),sm.toFixed(4),projected.toFixed(2),
        projected>Number(maxCost)?1:0].join(" "));
    ' "$1" "$2" "$3"
}

markers_not_advanced() {                  # <before-json> <after-json> -> count
    node -e '
      const [b,a]=process.argv.slice(1).map(x=>{try{return JSON.parse(x);}catch{return {};}});
      const before={}, after={};
      for(const r of b.graphDue||[]) before[String(r.sessionId)]=Number(r.markerCount)||0;
      for(const r of a.graphDue||[]) after[String(r.sessionId)]=Number(r.markerCount)||0;
      let n=0;
      for(const id of Object.keys(before))
        if(id in after && after[id]<=before[id]) n++;
      process.stdout.write(String(n));
    ' "$1" "$2"
}

state_analysis() {
    docker compose exec -T agentmemory node -e "$ANALYSIS_JS" 2>/dev/null
}

llm_telemetry() {                         # <secret>
    http_get_auth "$API/llm/telemetry?limit=500" "$1" 30
}

# The safety guards must stop the stack BEFORE failing. Deliberately an explicit
# call rather than a trap: a trap would also fire on the clean path.
stop_stack_then_die() {                   # <message>
    docker compose stop console agentmemory >/dev/null 2>&1 || true
    die "$1"
}

# ---- preflight ---------------------------------------------------------------
dl_mode >/dev/null
printf '%sreconcile-llm-queue  mode=%s  stack=%s%s\n' "$C_WHITE" "$DL_MODE" "$stack_dir" "$C_RESET"
[ "$DL_APPLY" = 1 ] || info 'read-only preview; add --apply to back up, quarantine, and reconcile'

section 'Preflight'
docker compose config --quiet || die 'docker compose config failed'
docker volume inspect "$volume_name" >/dev/null 2>&1 || die "Docker volume $volume_name does not exist"
image="$(dl_compose_image "$stack_dir" agentmemory)" || die 'could not resolve the agentmemory image'
docker image inspect "$image" >/dev/null 2>&1 || die "AgentMemory image is not built: $image"

# Must run BEFORE anything stops the stack: if the bind mount is unusable, the
# stack would otherwise already be down when the backup fails.
dl_assert_docker_shareable "$backup_root_full" \
    || die "Docker Desktop for Mac cannot bind-mount $backup_root_full — it only shares \$HOME, /tmp, /private and /Volumes by default."

secret="$(agentmemory_secret "$stack_dir" || true)"
[ -n "$secret" ] || die 'AgentMemory HMAC secret is unavailable'
wait_http_200 "$API/livez" 60 || die "timed out waiting for $API/livez"

before="$(state_analysis)" || die 'state analysis failed'
printf '%s' "$before" | node -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{JSON.parse(s);})' 2>/dev/null \
    || die "state analysis returned invalid JSON: $(printf '%s' "$before" | head -c 300)"
telemetry_before="$(llm_telemetry "$secret")" || die 'could not read LLM telemetry'

read -r sessions malformed raw sum_due graph_due proj_terra q_wait q_active q_dlq q_missing dlq_families <<EOF
$(printf '%s' "$before" | node -e '
  let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
    const j=JSON.parse(s), q=j.queue||{};
    process.stdout.write([j.sessions,j.malformedSessions,j.rawObservations,
      (j.summaryDueSessionIds||[]).length,(j.graphDue||[]).length,j.projectedTerraCalls,
      q.waiting,q.active,q.dlq,q.activeMissingFiles,
      JSON.stringify(q.dlqByFamily||{})].join(" "));
  });')
EOF

read -r graph_avg summary_avg projected cost_tripped <<EOF
$(projected_cost "$before" "$telemetry_before" "$max_cost")
EOF

info "sessions=$sessions malformed_sessions=$malformed raw=$raw summaries_due=$sum_due graphs_due=$graph_due"
info "queue waiting=$q_wait active=$q_active dlq=$q_dlq"
info "DLQ families: $dlq_families"
info "projected Terra provider calls=$proj_terra; estimated cost=\$$projected"
[ "$proj_terra" -le "$max_terra" ] || die "projected Terra calls $proj_terra exceed safety limit $max_terra"
[ "$cost_tripped" = 0 ] || die "projected cost \$$projected exceeds safety limit \$$max_cost"
[ "$q_missing" -eq 0 ] || die "queue has $q_missing active references without job files"
info 'preflight safety limits passed'

# ---- backup and quarantine ---------------------------------------------------
section 'Cold backup and queue quarantine'
step 'stop console and agentmemory'
step "write full-volume backup to $backup_dir/agentmemory-volume.tgz"
step "move /data/queue_store to /data/$quarantine_name and create a fresh queue store"

archive=''
if [ "$DL_APPLY" = 1 ]; then
    mkdir -p "$backup_dir"
    resolved_backup="$(dl_realpath "$backup_dir")" || die "cannot resolve $backup_dir"
    dl_assert_within "$backup_root_full" "$resolved_backup" \
        || die "resolved backup directory escaped backup root: $resolved_backup"

    docker compose stop console agentmemory || die 'failed to stop the stack'
    docker run --rm --entrypoint sh \
        -v "${volume_name}:/source:ro" -v "${resolved_backup}:/backup" "$image" \
        -c 'tar -C /source -czf /backup/agentmemory-volume.tgz .' \
        || die 'volume backup failed; stack remains stopped and queue is unchanged'

    archive="$resolved_backup/agentmemory-volume.tgz"
    [ -f "$archive" ] || die "backup archive is missing: $archive; stack remains stopped and queue is unchanged"
    size="$(file_size "$archive")"
    [ "$size" -ge 1048576 ] || die "backup archive is unexpectedly small ($size bytes): $archive; stack remains stopped and queue is unchanged"
    info "backup size=$(awk -v b="$size" 'BEGIN{printf "%.1f", b/1048576}') MB"

    docker run --rm --entrypoint sh -e "QUEUE_QUARANTINE_NAME=$quarantine_name" \
        -v "${volume_name}:/data" "$image" -c "$QUARANTINE_SH" \
        || die 'queue quarantine failed; stack remains stopped and the full-volume backup is available'
    info "quarantined queue at /data/$quarantine_name"
fi

# ---- state-driven recovery ---------------------------------------------------
section 'State-driven recovery'
step 'start the stack and allow exactly one startup reconciliation pass'
step "require an empty healthy queue for $soak_seconds seconds (covers the full retry window)"
step "enforce Terra provider-call limit $max_terra and estimated-cost limit \$$max_cost"

if [ "$DL_APPLY" = 1 ]; then
    docker compose up -d || die 'stack start failed'
    wait_http_200 "$API/livez" 180 || stop_stack_then_die "timed out waiting for $API/livez"
    wait_http_200 'http://127.0.0.1:3114/healthz' 180 || stop_stack_then_die 'timed out waiting for the console'
    sleep 15

    deadline=$(( $(date +%s) + recovery_timeout ))
    settled_at=0
    last_telemetry=''
    while [ "$(date +%s)" -lt "$deadline" ]; do
        last_telemetry="$(llm_telemetry "$secret")" || stop_stack_then_die 'telemetry read failed during recovery'
        read -r depth dlq active terra luna actual circuit tripped settled failed <<EOF
$(metrics "$last_telemetry" "$max_terra" "$max_cost")
EOF
        info "queue=$depth dlq=$dlq active=$active terra_calls=$terra cost=\$$actual circuit=$circuit"

        [ "$tripped" = 0 ] || stop_stack_then_die 'recovery safety guard tripped; stack stopped, new queue preserved, quarantine and backup untouched'

        if [ "$settled" = 1 ]; then
            if [ "$settled_at" = 0 ]; then
                settled_at="$(date +%s)"
                info "queue first settled; beginning $soak_seconds-second retry-window soak"
            fi
            [ $(( $(date +%s) - settled_at )) -ge "$soak_seconds" ] && break
        else
            settled_at=0
        fi
        sleep 5
    done
    [ "$settled_at" != 0 ] && [ $(( $(date +%s) - settled_at )) -ge "$soak_seconds" ] \
        || stop_stack_then_die "recovery did not settle within $recovery_timeout seconds; stack stopped for inspection"

    after="$(state_analysis)" || die 'post-recovery state analysis failed'
    read -r depth dlq active terra luna actual circuit tripped settled failed <<EOF
$(metrics "$last_telemetry" "$max_terra" "$max_cost")
EOF
    [ "$failed" -eq 0 ] || die "recovery settled with $failed provider failure rows"

    read -r a_raw a_sum a_wait a_active a_dlq a_graph <<EOF
$(printf '%s' "$after" | node -e '
  let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
    const j=JSON.parse(s), q=j.queue||{};
    process.stdout.write([j.rawObservations,(j.summaryDueSessionIds||[]).length,
      q.waiting,q.active,q.dlq,(j.graphDue||[]).length].join(" "));
  });')
EOF
    [ "$a_raw" -eq 0 ] || die "recovery left $a_raw raw observations"
    [ "$a_sum" -eq 0 ] || die "recovery left $a_sum summaries due"
    { [ "$a_active" -eq 0 ] && [ "$a_wait" -eq 0 ] && [ "$a_dlq" -eq 0 ]; } \
        || die 'fresh queue store is not empty after recovery'

    not_advanced="$(markers_not_advanced "$before" "$after")"
    [ "$not_advanced" -eq 0 ] || die "graph markers did not advance for $not_advanced due sessions"

    info "post-recovery raw=0 summaries_due=0 graph_sessions_remaining=$a_graph"
    info "actual provider calls: Terra=$terra Luna=$luna; estimated cost=\$$actual"
    info "backup=$archive"
    info "quarantine=/data/$quarantine_name"
fi

printf '\n'
if [ "$DL_APPLY" = 1 ]; then printf '%sDone (APPLY): stale queue records quarantined and current state reconciled.%s\n' "$C_GREEN" "$C_RESET"
else printf '%sNothing changed (preview). Re-run with --apply after reviewing the counts above.%s\n' "$C_WHITE" "$C_RESET"; fi
