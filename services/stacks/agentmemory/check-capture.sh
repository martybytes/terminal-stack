#!/usr/bin/env bash
# check-capture.sh — verify agentmemory is actually usable from Claude Code,
# Cursor and Codex, not just serving HTTP. Checks the capture-hook wiring, the
# secret's single source of truth, capture recency, the read path, project
# scoping and duplicate capture; --apply additionally runs a real hook end to
# end and cleans up after itself.
# macOS/Linux twin of check-capture.ps1 (canonical). Port changes both ways.
#
# Usage:  ./check-capture.sh [--apply]
# When:   Capture has gone quiet, or after any agentmemory plugin update — a
#         plugin update silently reverts the hook wiring this checks.
# Note:   A healthy server proves nothing about capture. Reads and writes fail
#         independently: the API stays healthy, the circuit breaker stays
#         closed, and MCP searches keep succeeding while no observation has been
#         recorded for hours. That is the failure this script exists to make
#         loud. Exits non-zero when it finds problems.
set -euo pipefail

_self="${BASH_SOURCE[0]}"
while [ -L "$_self" ]; do
    _d="$(cd -- "$(dirname -- "$_self")" && pwd)"; _self="$(readlink "$_self")"
    case "$_self" in /*) ;; *) _self="$_d/$_self" ;; esac
done
SCRIPT_DIR="$(cd -- "$(dirname -- "$_self")" && pwd -P)"
# shellcheck source=../../_stack.sh
. "$SCRIPT_DIR/../../_stack.sh"

while [ $# -gt 0 ]; do
    arg="$(tss_normalise_flag "$1")"
    if tss_parse_common_flag "$arg" "${2:-}"; then shift "$TSS_FLAG_CONSUMED"; continue; fi
    die "unknown option: $1 (try --help)"
done

stack_dir="$SCRIPT_DIR"
cd "$stack_dir"

# The .ps1 never initialises $probeSessions (it is first touched with += inside
# one branch, then read in two others), and it never adds section D's probe to
# it at all. Declared here, appended by BOTH probes, and drained from an EXIT
# trap so a mid-script failure still cleans up — which is what the .ps1's
# per-section try/finally was reaching for and could not achieve across sections.
TSS_PROBE_SESSIONS=''
HMAC=''

cleanup_probe_sessions() {
    [ -n "$TSS_PROBE_SESSIONS" ] || return 0
    [ -n "$HMAC" ] || return 0
    local sid n=0
    for sid in $TSS_PROBE_SESSIONS; do
        http_post_json_auth 'http://127.0.0.1:3111/agentmemory/forget' "$HMAC" \
            "{\"sessionId\":$(json_str "$sid")}" 15 >/dev/null 2>&1 \
            || warn "could not forget probe session $sid — remove it from the viewer (http://localhost:3113) if it lingers"
        n=$((n + 1))
    done
    info "cleaned up $n probe session(s)"
}
trap cleanup_probe_sessions EXIT

tss_mode >/dev/null
printf '%scheck-capture  mode=%s  stack=%s%s\n' "$C_WHITE" "$TSS_MODE" "$stack_dir" "$C_RESET"
[ "$TSS_APPLY" = 1 ] || printf '%s(read-only checks; add --apply to also run the end-to-end probe)%s\n' "$C_DIM" "$C_RESET"

require_docker

# --------------------------------------------------------------------------
section 'A. Client wiring lives in terminal-stack'

# Which hooks are registered, what they run and what environment they carry is
# terminal-stack's job (bootstrap/ts-agentmemory.*), which already manages
# ~/.claude, ~/.cursor and ~/.codex. Duplicating its checks here would drift
# from them, so this only locates the entry point — and says so loudly when
# there isn't one, because on macOS/Linux that is the difference between
# "agentmemory works" and "agentmemory silently never records anything".
# The PATH probe that used to lead this list looked for an executable named
# `ts-agentmemory`. There never was one: it was a bootstrap script reached through
# a zsh wrapper, and `tstack` is a shell function too, so `command -v` cannot see
# either from a non-interactive script. It matched nothing on every host, silently,
# and the clone-path candidates below are what actually resolved. The canonical
# runtime clone location now leads, which is where `tstack update` keeps it.
ts_entry=''
for cand in \
    "${TERMINAL_STACK_DIR:-}/bootstrap/ts-agentmemory.sh" \
    "${XDG_DATA_HOME:-$HOME/.local/share}/terminal-stack/bootstrap/ts-agentmemory.sh" \
    "$TSS_ROOT/../terminal-stack/bootstrap/ts-agentmemory.sh" \
    "$HOME/Documents/Workspace/src/github.com/martybytes/terminal-stack/bootstrap/ts-agentmemory.sh"
do
    [ -n "$cand" ] && [ -e "$cand" ] && { ts_entry="$cand"; break; }
done

if [ -n "$ts_entry" ]; then
    info "harness wiring: $ts_entry"
    info 'Run `tstack agentmemory --check` (or `tstack doctor`) to report reverted'
    info 'hook-script edits, which is what a plugin upgrade silently causes.'
else
    fail 'no agentmemory harness entry point found — no terminal-stack clone at any known location, so host-side hook wiring cannot be verified.'
    info 'Consequence: the server can store observations, but nothing may be sending any.'
    info 'The API stays healthy, MCP tools resolve, searches answer — and capture is dead.'
    info 'Section D will fail below, and that is the correct result, not a bug in this script.'
    info 'Fix: install terminal-stack, or set TERMINAL_STACK_DIR to an existing clone.'
fi
info 'What follows is the server side: secret, capture, search, project scoping.'

# Section D needs the plugin root to run a real hook. Resolved quietly — whether
# the wiring is correct is terminal-stack's question, not this file's.
plugin_root=''
installed="$HOME/.claude/plugins/installed_plugins.json"
if [ -f "$installed" ]; then
    plugin_root="$(node -e '
      const fs=require("node:fs");
      try{
        const j=JSON.parse(fs.readFileSync(process.argv[1],"utf8"));
        let e=(j.plugins||{})["agentmemory@agentmemory"];
        if(Array.isArray(e)) e=e[0];
        if(e&&e.installPath) process.stdout.write(e.installPath);
      }catch{}
    ' "$installed" 2>/dev/null || true)"
fi
[ -n "$plugin_root" ] || info 'agentmemory Claude plugin not found; the end-to-end capture probe will be skipped.'

# --------------------------------------------------------------------------
section 'B. Secret - single source of truth'

# /data/.hmac in the container is authoritative. Windows keeps a copy in the
# User environment (HKCU); Unix has no equivalent, so the cache is a 0600 file
# under ~/.config/docker-local. Either way a HARDCODED copy in a config file
# works until the secret rotates and then fails silently — and rotation is
# exactly when you least want a silent failure.
HMAC="$(docker compose exec -T agentmemory cat /data/.hmac 2>/dev/null | tr -d '\r\n' || true)"

if [ -z "$HMAC" ]; then
    fail 'could not read /data/.hmac — is the agentmemory container running? (../stack.sh --status)'
else
    info "/data/.hmac: ${#HMAC} chars"

    cache="$(tss_secret_cache_path)"
    if [ -n "${AGENTMEMORY_SECRET:-}" ]; then
        if [ "$AGENTMEMORY_SECRET" = "$HMAC" ]; then pass 'exported AGENTMEMORY_SECRET matches /data/.hmac'
        else fail 'the exported AGENTMEMORY_SECRET does not match /data/.hmac — stale after a rotation. Re-export it.'; fi
    elif [ -f "$cache" ]; then
        mode="$(_tss_file_mode "$cache")"
        if [ "$mode" != 600 ]; then
            fail "$cache is mode ${mode:-unknown}, not 600 — any local user can read the bearer. chmod 600 it."
        elif [ "$(tr -d '\r\n' < "$cache")" = "$HMAC" ]; then
            pass "cached secret in $cache matches /data/.hmac"
        else
            fail "$cache does not match /data/.hmac — stale after a rotation. Refresh or delete it."
        fi
    else
        # Not a failure by itself: everything here reads the container directly.
        # It matters for the HOOKS, which read process.env and have no fallback.
        warn 'AGENTMEMORY_SECRET is not exported and no 0600 cache exists.'
        info 'Hooks read it from process.env with no fallback: without it they post'
        info 'without a bearer, the server answers 401, and the hook swallows it.'
        info "Fix: export it in ~/.zshenv (NOT ~/.zshrc — hook subprocesses are"
        info '     non-interactive, so ~/.zshrc is never sourced for them), and for'
        info '     GUI-launched Cursor/Codex also: launchctl setenv AGENTMEMORY_SECRET <value>'
    fi

    # Guard against re-introducing a hardcoded copy. The .ps1 scans two files;
    # on Unix a shell rc is exactly where someone would paste it, so scan those too.
    for cfg in "$HOME/.claude/settings.json" "$HOME/.cursor/mcp.json" \
               "$HOME/.codex/config.toml" "$HOME/.zshenv" "$HOME/.zshrc" \
               "$HOME/.zprofile" "$HOME/.bashrc" "$HOME/.profile"; do
        [ -f "$cfg" ] || continue
        if grep -qF "$HMAC" "$cfg" 2>/dev/null; then
            fail "hardcoded secret in $cfg — remove it and reference the environment variable, or rotation will break this client silently."
        else
            pass "no hardcoded secret in $(basename "$cfg")"
        fi
    done
fi

# --------------------------------------------------------------------------
section 'C. Capture recency'

# Informational, not pass/fail: an idle machine legitimately has no recent
# capture. What matters is whether this is stale relative to when you were last
# working.
last_line="$(docker compose logs --no-color --timestamps agentmemory 2>/dev/null \
    | grep 'Observation captured' | tail -n 1 || true)"

if [ -z "$last_line" ]; then
    warn 'no "Observation captured" line in the retained logs at all'
    info 'Logs rotate at max-size 10m / max-file 3, so this can be rotation rather than failure.'
    [ -n "$ts_entry" ] || info 'On this host it is more likely the missing hook wiring reported in section A.'
else
    # `docker compose logs` prefixes each line with the container name, so pull
    # the timestamp out by shape rather than by position.
    stamp="$(printf '%s' "$last_line" | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z?' | head -n 1 || true)"
    age="$(tss_iso_age_minutes "$stamp")"
    if [ -z "$age" ]; then
        info 'newest capture: could not read a timestamp from the log line'
    else
        info "newest capture: $stamp ($age min ago)"
        [ "$age" -gt 120 ] && warn 'over 2h old — if you have been working in Claude Code or Cursor since then, capture is broken. Check section A.'
    fi
fi

# --------------------------------------------------------------------------
section 'D. End-to-end probe'

if [ -z "$plugin_root" ] || [ -z "$HMAC" ]; then
    warn 'skipped — needs a resolved plugin root and a readable /data/.hmac (see above)'
elif [ "$TSS_APPLY" != 1 ]; then
    step 'run the installed post-tool-use hook against a synthetic payload, confirm the session lands, then forget it'
    info 'Nothing else proves capture works: the hook always exits 0, so only the server-side record counts.'
else
    probe_id="check-capture-probe-$(tss_rand_hex 12)"
    TSS_PROBE_SESSIONS="$TSS_PROBE_SESSIONS $probe_id"
    hook_script="$plugin_root/scripts/post-tool-use.mjs"

    if [ ! -f "$hook_script" ]; then
        fail "hook script not found: $hook_script"
    else
        # Build the JSON with an encoder, never string interpolation. The Windows
        # rationale was that a path's \D becomes an invalid JSON escape; that
        # specific hazard is gone here, but cwd can still contain quotes, spaces
        # or non-ASCII, and the hook parses stdin in a bare try/catch that
        # returns on failure — so a malformed payload makes it exit 0 having done
        # nothing, which looks exactly like success.
        payload="$(node -e '
          const [sid,cwd]=process.argv.slice(1);
          process.stdout.write(JSON.stringify({
            session_id:sid, cwd, hook_event_name:"PostToolUse", tool_name:"Bash",
            tool_input:{command:"check-capture probe"},
            tool_response:{stdout:"check-capture probe"}
          }));
        ' "$probe_id" "$stack_dir")"

        step "post a synthetic observation as session $probe_id"
        landed=0
        # 3111 is the console proxy — the path hooks actually take. If that
        # fails, 3110 is agentmemory direct, separating a console fault from a
        # real one.
        for port in 3111 3110; do
            if [ "$port" = 3110 ]; then info 'retrying via the 3110 bypass — 3111 (console proxy) did not land'
            else                        info 'probing via 3111 (console proxy, the path hooks use)'; fi
            # Per-invocation environment prefix rather than mutating this
            # process's env for the rest of the script.
            printf '%s' "$payload" | CLAUDE_PLUGIN_ROOT="$plugin_root" \
                AGENTMEMORY_SECRET="$HMAC" AGENTMEMORY_URL="http://localhost:$port" \
                node "$hook_script" >/dev/null 2>&1 || true
            i=0
            while [ $i -lt 10 ]; do
                sleep 1; i=$((i + 1))
                if http_get_auth "http://127.0.0.1:$port/agentmemory/sessions?limit=60" "$HMAC" 5 2>/dev/null \
                    | grep -qF "$probe_id"; then landed=1; break; fi
            done
            [ "$landed" = 1 ] && { pass "capture works end to end (via $port)"; break; }
        done

        if [ "$landed" != 1 ]; then
            fail 'PROBE FAILED — the hook ran and exited 0, but no observation reached the server. Capture is broken.'
            info 'Check section A first (hook wiring), then the secret in section B.'
            info 'The hook does fetch(...).catch(() => {}) then exit(0), so it never reports its own failure.'
        fi
    fi
fi

# --------------------------------------------------------------------------
section 'E. Read path - does search answer'

# Sections A-D only prove writes. On 2026-08-21 every one of them passed while
# retrieval was dead in two independent ways, so check both. A patched request
# path awaiting an unreleased startup promise hangs until the engine kills the
# invocation at 180s; the MCP bridge reports that as an empty result set, so
# "no results" is indistinguishable from "nothing matched". A short timeout
# tells them apart: a healthy search answers well under a second.
if [ -z "$HMAC" ]; then
    warn 'search probe skipped - needs a readable /data/.hmac (see section B)'
else
    search_body='{"query":"the","limit":1}'
    t0="$(date +%s)"
    if resp="$(http_post_json_auth 'http://127.0.0.1:3110/agentmemory/search' "$HMAC" "$search_body" 20 2>/dev/null)"; then
        elapsed_ms="$(node -e 'process.stdout.write(String(Date.now()-Number(process.argv[1])*1000))' "$t0" 2>/dev/null || echo '?')"
        n="$(printf '%s' "$resp" | node -e '
          let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
            try{const j=JSON.parse(s);process.stdout.write(String((j.results||[]).length));}catch{process.stdout.write("0");}
          });' 2>/dev/null || echo 0)"
        if [ "$n" -gt 0 ]; then
            pass "search answered in ${elapsed_ms} ms with $n result(s)"
        else
            # An empty store is legitimate; an empty result for a stopword when
            # memories exist is not.
            warn "search answered in ${elapsed_ms} ms but returned nothing - expected at least one hit for a stopword query"
            info 'If the store is genuinely empty this is fine; otherwise check the request path for an unreleased startup gate.'
        fi
    else
        fail 'search failed'
        info 'A ~180s hang ending in 504 means a request path is awaiting something that never resolves.'
        info 'MCP memory_recall / memory_smart_search report this as an empty result set, not an error.'
    fi
fi

# --------------------------------------------------------------------------
section 'H. Project persistence and filtering'

if [ -n "$HMAC" ]; then
    if all_mem="$(http_get_auth 'http://127.0.0.1:3110/agentmemory/memories?limit=5000' "$HMAC" 60 2>/dev/null)"; then
        unprojected="$(printf '%s' "$all_mem" | node -e '
          let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
            try{const j=JSON.parse(s);process.stdout.write(String((j.memories||[]).filter(m=>!m.project).length));}
            catch{process.stdout.write("-1");}
          });' 2>/dev/null || echo -1)"
        if [ "$unprojected" = 0 ]; then pass 'every memory carries a project'
        elif [ "$unprojected" = -1 ]; then warn 'could not parse the memories response'
        else warn "$unprojected memories carry no project - ./migrate-memory-projects.sh reports them"; fi
    else
        warn 'could not count untagged memories'
    fi
fi

if [ "$TSS_APPLY" != 1 ]; then
    step 'save a probe memory under one project, prove the filter includes it and excludes it from another, then delete it'
elif [ -z "$HMAC" ]; then
    warn 'project regression skipped - no readable secret'
else
    tag="check-capture-project-$(tss_rand_hex 10)"
    proj_a="$tag-a"; proj_b="$tag-b"
    saved_id=''
    body="{\"content\":$(json_str "$tag probe memory for project persistence"),\"type\":\"fact\",\"project\":$(json_str "$proj_a")}"
    if resp="$(http_post_json_auth 'http://127.0.0.1:3110/agentmemory/remember' "$HMAC" "$body" 30 2>/dev/null)"; then
        saved_id="$(printf '%s' "$resp" | node -e '
          let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
            try{const j=JSON.parse(s);const m=j.memory||j;process.stdout.write(String(m.id||""));}catch{}
          });' 2>/dev/null || true)"
        saved_proj="$(printf '%s' "$resp" | node -e '
          let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
            try{const j=JSON.parse(s);const m=j.memory||j;process.stdout.write(String(m.project||""));}catch{}
          });' 2>/dev/null || true)"
        if [ "$saved_proj" = "$proj_a" ]; then pass "save round-trips project ($proj_a)"
        else fail "saved memory came back with project '$saved_proj' instead of '$proj_a'"; fi

        if [ -n "$saved_id" ]; then
            if http_get_auth "http://127.0.0.1:3110/agentmemory/memories?project=$proj_a&limit=50" "$HMAC" 30 2>/dev/null | grep -qF "$saved_id"
            then pass "project filter returns it under $proj_a"
            else fail "project=$proj_a did not return the probe memory"; fi

            if http_get_auth "http://127.0.0.1:3110/agentmemory/memories?project=$proj_b&limit=50" "$HMAC" 30 2>/dev/null | grep -qF "$saved_id"
            then fail "project=$proj_b wrongly returned the probe memory - the filter is not restricting"
            else pass "project filter excludes it from $proj_b"; fi

            del="{\"memoryIds\":[$(json_str "$saved_id")],\"reason\":\"check-capture probe\"}"
            if http_delete_json_auth 'http://127.0.0.1:3110/agentmemory/governance/memories' "$HMAC" "$del" 30 >/dev/null 2>&1
            then pass 'probe memory removed'
            else warn "could not delete probe memory $saved_id - remove it from the viewer"; fi
        fi
    else
        fail 'project regression failed: could not save the probe memory'
    fi
fi

# --------------------------------------------------------------------------
section 'I. Duplicate observation capture'

# Codex loads both ~/.codex/hooks.json (Desktop) and the plugin's
# hooks.codex.json (CLI), so one event can arrive twice, milliseconds apart,
# differing only in its timestamp.
scan_duplicate_pairs() {                  # <since-ms> -> prints "<pairs> <rows>"
    http_get_auth "http://127.0.0.1:3114/api/requests?limit=300" "$HMAC" 15 2>/dev/null \
    | node -e '
        let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
          const since=Number(process.argv[1]);
          let rows=[];
          try{
            const j=JSON.parse(s);
            rows=(Array.isArray(j)?j:(j.requests||[]))
              .filter(r=>r.route==="/agentmemory/observe" && r.ts>=since && (since===0||r.status===201))
              .sort((a,b)=>a.ts-b.ts);
          }catch{}
          let pairs=0;
          for(let i=1;i<rows.length;i++){
            const a=rows[i-1],b=rows[i];
            // Only pairs where BOTH were STORED count: a 201 followed by a
            // deduplicated 200 is one observation, the desired outcome.
            if(a.agent===b.agent&&a.reqBytes===b.reqBytes&&(b.ts-a.ts)<=1500) pairs++;
          }
          process.stdout.write(pairs+" "+rows.length);
        });' "$1" 2>/dev/null || printf '0 0'
}

if [ "$TSS_APPLY" != 1 ]; then
    step 'post one observation twice and confirm only one is stored'
    if [ -n "$HMAC" ]; then
        read -r pairs rows <<EOF
$(scan_duplicate_pairs 0)
EOF
        if [ "${rows:-0}" = 0 ]; then info 'console feed empty or unreadable; the --apply probe checks this directly'
        elif [ "${pairs:-0}" = 0 ]; then pass "no duplicate observe pairs in the last $rows captures"
        else warn "$pairs near-identical observe pairs still stored in the last $rows captures"; fi
    fi
elif [ -z "$HMAC" ]; then
    warn 'duplicate check skipped - no readable secret'
else
    sid="check-capture-dupe-$(tss_rand_hex 10)"
    TSS_PROBE_SESSIONS="$TSS_PROBE_SESSIONS $sid"
    mk_obs() {                            # <millis-suffix>
        node -e '
          const [sid,ms]=process.argv.slice(1);
          const t=new Date().toISOString().replace(/\.\d{3}Z$/,"."+ms+"Z");
          process.stdout.write(JSON.stringify({
            hookType:"post_tool_use", sessionId:sid, project:"check-capture",
            cwd:"/check-capture", timestamp:t,
            data:{tool_name:"Bash",tool_input:{command:"check-capture dedupe probe"}}
          }));' "$sid" "$1"
    }
    if http_post_json_auth 'http://127.0.0.1:3110/agentmemory/observe' "$HMAC" "$(mk_obs 001)" 20 >/dev/null 2>&1 \
    && second="$(http_post_json_auth 'http://127.0.0.1:3110/agentmemory/observe' "$HMAC" "$(mk_obs 999)" 20 2>/dev/null)"; then
        # Deliberately not asserting that the server suppressed it: duplicate
        # hook invocations are dropped client-side, inside the hook, before the
        # request is made. A raw POST bypasses that, so this only exercises
        # agentmemory's own content-based guard.
        case "$second" in *'"deduplicated":true'*|*'"deduped":true'*)
            info 'agentmemory own content guard also rejected the identical repeat' ;;
        esac
        sleep 2
        count="$(http_get_auth 'http://127.0.0.1:3110/agentmemory/sessions?limit=5000' "$HMAC" 30 2>/dev/null \
          | node -e '
            let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{
              try{const j=JSON.parse(s);const m=(j.sessions||[]).filter(x=>x.id===process.argv[1]);
                process.stdout.write(m.length===1?String(m[0].observationCount):"-1");}
              catch{process.stdout.write("-1");}
            });' "$sid" 2>/dev/null || echo -1)"
        if [ "$count" = 1 ]; then pass 'exactly one observation stored'
        elif [ "$count" = -1 ]; then warn 'could not read back the probe session'
        else fail "stored $count observations for one event"; fi

        # The outcome that actually matters: real hook traffic must not arrive
        # twice. Only recent rows — the feed reaches back before the client-side
        # guard existed, and those historical duplicates would fail this forever.
        since="$(node -e 'process.stdout.write(String(Date.now()-10*60*1000))')"
        read -r pairs rows <<EOF
$(scan_duplicate_pairs "$since")
EOF
        if [ "${rows:-0}" -lt 2 ]; then info 'too few recent captures to scan for duplicates'
        elif [ "${pairs:-0}" = 0 ]; then pass "no duplicate captures across the last $rows stored in 10 min"
        else fail "$pairs duplicated captures in the last 10 min - run `tstack agentmemory --check` in terminal-stack"; fi
    else
        fail 'duplicate probe failed: could not post the observation'
    fi
fi

# --------------------------------------------------------------------------
printf '\n'
if [ "$TSS_PROBLEMS" = 0 ]; then
    printf '%sNo problems found (%s).%s\n' "$C_GREEN" "$TSS_MODE" "$C_RESET"
    [ "$TSS_APPLY" = 1 ] || printf '%sRe-run with --apply to prove capture end to end.%s\n' "$C_DIM" "$C_RESET"
else
    printf '%s%s problem(s) found - see the X lines above.%s\n' "$C_YELLOW" "$TSS_PROBLEMS" "$C_RESET"
fi
printf '%sPlugins, hooks, permissions and environment are read at process start: after any fix, restart Claude Code, Cursor and Codex.%s\n' "$C_DIM" "$C_RESET"

# Unlike the .ps1, which always exits 0, this mirrors the health so it can be
# used in a pipeline or a hook — the ts-doctor.sh house rule.
[ "$TSS_PROBLEMS" = 0 ]
