#!/usr/bin/env bash
# migrate-memory-projects.sh — report memories that carry no project, and
# backfill only the ones AgentMemory can infer unambiguously. Dry run unless
# --apply is passed.
# macOS/Linux twin of migrate-memory-projects.ps1 (canonical). Port both ways.
#
# Usage:  ./migrate-memory-projects.sh [--apply]
# When:   After noticing untagged memories (check-capture reports the count), or
#         after a run of agent work where saves omitted the project argument.
# Note:   Inference is AgentMemory's own `infer-memory-projects` migration step,
#         which derives a project from the sessions a memory is linked to and
#         refuses anything ambiguous. This script never invents a project of its
#         own. Memories saved through memory_save arrive with sessionIds: [], so
#         the step can never infer them — that is correct, not broken; guessing
#         would write a permanent wrong answer. The fix for new memories is to
#         pass `project` to memory_save.
set -euo pipefail

_self="${BASH_SOURCE[0]}"
while [ -L "$_self" ]; do
    _d="$(cd -- "$(dirname -- "$_self")" && pwd)"; _self="$(readlink "$_self")"
    case "$_self" in /*) ;; *) _self="$_d/$_self" ;; esac
done
SCRIPT_DIR="$(cd -- "$(dirname -- "$_self")" && pwd -P)"
# shellcheck source=../_common.sh
. "$SCRIPT_DIR/../_common.sh"

while [ $# -gt 0 ]; do
    arg="$(dl_normalise_flag "$1")"
    if dl_parse_common_flag "$arg" "${2:-}"; then shift "$DL_FLAG_CONSUMED"; continue; fi
    die "unknown option: $1 (try --help)"
done

stack_dir="$SCRIPT_DIR"
[ -f "$stack_dir/docker-compose.yml" ] || die "docker-compose.yml missing in $stack_dir"
cd "$stack_dir"

# 3110 is the direct API; 3111 is the console proxy.
API='http://127.0.0.1:3110/agentmemory'

mode="$([ "$DL_APPLY" = 1 ] && printf 'APPLY' || printf 'DRY RUN')"
printf '%smigrate-memory-projects  mode=%s%s\n' "$C_WHITE" "$mode" "$C_RESET"
[ "$DL_APPLY" = 1 ] || printf '%s(no writes; add --apply to run the real backfill)%s\n' "$C_DIM" "$C_RESET"

# ---- secret: never stored in a tracked file --------------------------------
hmac="$(agentmemory_secret "$stack_dir" || true)"
[ -n "$hmac" ] || die 'No AGENTMEMORY_SECRET available and /data/.hmac is unreadable — is the container running?'

# --------------------------------------------------------------------------
section 'Current project coverage'

all_json="$(http_get_auth "$API/memories?limit=5000" "$hmac" 60)" \
    || die "could not read $API/memories — is the container running? (../stack.sh --status)"

# Rendering happens in node: this needs grouping, sorting, column alignment and
# title truncation, all of which bash does badly and which must match the .ps1
# output closely enough to read as the same report.
printf '%s' "$all_json" | node -e '
let s=""; process.stdin.on("data",d=>s+=d).on("end",()=>{
  let j; try { j=JSON.parse(s); } catch { console.log("       could not parse the memories response"); process.exit(0); }
  const mem=j.memories||[];
  const un=mem.filter(m=>!m.project);
  console.log(`       ${mem.length} memories total; ${un.length} with no project`);
  const by={};
  for (const m of mem) if (m.project) by[m.project]=(by[m.project]||0)+1;
  for (const [k,v] of Object.entries(by).sort((a,b)=>b[1]-a[1]))
    console.log("         "+k.padEnd(28)+" "+v);
});'

# --------------------------------------------------------------------------
section 'What AgentMemory can infer'

dry="$([ "$DL_APPLY" = 1 ] && printf 'false' || printf 'true')"
if result="$(http_post_json_auth "$API/migrate" "$hmac" "{\"step\":\"infer-memory-projects\",\"dryRun\":$dry}" 300)"; then
    # The step reports updated/skipped/ambiguous; shapes vary by version, so
    # print whatever came back rather than assuming one shape.
    printf '%s' "$result" | node -e '
    let s=""; process.stdin.on("data",d=>s+=d).on("end",()=>{
      let j; try { j=JSON.parse(s); } catch { console.log("       "+s.slice(0,200)); process.exit(0); }
      const out=[];
      for (const k of ["updated","skipped","ambiguous","total"]) {
        let v=j[k]; if (v===undefined && j.result) v=j.result[k];
        if (v!==undefined && v!==null) out.push(k+"="+v);
      }
      console.log("       "+(out.length?out.join("  "):JSON.stringify(j)));
    });'
else
    warn 'migrate step failed — the API rejected the request or timed out'
fi

if [ "$DL_APPLY" = 1 ]; then step 'ran infer-memory-projects for real (ambiguous records untouched)'
else                          step 'would run infer-memory-projects; nothing was written'; fi

# --------------------------------------------------------------------------
section 'Ambiguous records - reported, never reassigned'

printf '%s' "$all_json" | node -e '
let s=""; process.stdin.on("data",d=>s+=d).on("end",()=>{
  let j; try { j=JSON.parse(s); } catch { process.exit(0); }
  const un=(j.memories||[]).filter(m=>!m.project)
    .sort((a,b)=>String(a.createdAt||"").localeCompare(String(b.createdAt||"")));
  if (!un.length) { console.log("       no untagged memories"); return; }
  console.log("       Evidence below is everything stored. Tag by hand, or re-save with an explicit project.");
  console.log("");
  for (const m of un) {
    const sessions=m.sessionIds||[], files=m.files||[];
    let title=String(m.title||"");
    if (title.length>68) title=title.slice(0,65)+"...";
    console.log("  "+m.id);
    console.log(`     created  ${m.createdAt}   agent ${m.agentId||"-"}   type ${m.type}`);
    console.log(`     sessions ${sessions.length?sessions.join(","):"none (cannot be inferred)"}   origin ${(m.origin&&m.origin.channel)||"-"}`);
    if (files.length) console.log("     files    "+files.join(", "));
    console.log("     title    "+title);
  }
  console.log("");
  const noSession=un.filter(m=>!(m.sessionIds||[]).length).length;
  if (noSession>0)
    console.log(`  !    ${noSession} of ${un.length} have no sessionIds at all, so no amount of re-running this can infer them.`);
  const byAgent={};
  for (const m of un) { const k=m.agentId||"(none)"; byAgent[k]=(byAgent[k]||0)+1; }
  console.log("       by agent: "+Object.entries(byAgent).map(([k,v])=>k+"="+v).join("  "));
});'

printf '\n'
if [ "$DL_APPLY" = 1 ]; then printf '%sDone (APPLY).%s\n' "$C_GREEN" "$C_RESET"
else printf '%sNothing changed (dry run). Add --apply to backfill the inferable records.%s\n' "$C_WHITE" "$C_RESET"; fi
