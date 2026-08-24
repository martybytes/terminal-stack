#!/usr/bin/env bash
# ts-verify.sh — agentmemory: prove a memory can be written and read back.
# Run by `ts-stack test`; safe to run by hand. Exit 0 = pass.
#
# Windows twin: ts-verify.ps1. Change one, change the other.
#
# Health is not evidence here. Every vendor hook does fetch(...).catch(() => {})
# then exit(0), so a machine wired to a server that is up but refusing writes
# captures nothing and reports nothing. The only proof is a round trip.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
# shellcheck source=../../_stack.sh
. "$ROOT/_stack.sh"

BYPASS="${AGENTMEMORY_BYPASS_URL:-http://127.0.0.1:3110}"   # the server itself
PROXY="${AGENTMEMORY_URL:-http://127.0.0.1:3111}"           # the console in front of it
CONSOLE="${AGENTMEMORY_CONSOLE_URL:-http://127.0.0.1:3114}"
rc=0

# 1. The bypass FIRST. If 3110 answers and 3111 does not, the console is down --
#    which is a different verdict from "agentmemory is down", and the one people
#    get wrong because 3111 is the port everything is configured to use.
if tss_wait_http "$BYPASS/agentmemory/livez" 10 2xx; then pass 'server livez (3110 bypass)'
else fail "the agentmemory server itself is not answering at $BYPASS"; rc=1; fi

if tss_wait_http "$PROXY/agentmemory/livez" 10 2xx; then pass 'console proxy livez (3111)'
else
    if tss_wait_http "$BYPASS/agentmemory/livez" 2 2xx; then
        fail 'the console proxy on 3111 is down (the server behind it is fine)'
    else
        fail 'neither the console proxy nor the server is answering'
    fi
    rc=1
fi

if tss_wait_http "$CONSOLE/healthz" 10 2xx; then pass 'console healthz (3114)'
else fail "the console UI is not answering at $CONSOLE"; rc=1; fi

# 2. The secret every host uses must be the one the container has. A stale copy
#    401s every request for the life of a long-running shell, silently.
secret="$(agentmemory_secret "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null || true)"
if [ -z "$secret" ]; then
    warn 'no agentmemory secret available — skipping the round trip'
    exit $rc
fi
pass 'secret resolved (container, cache or environment)'

# 3. The round trip. Write through the CONSOLE, the way every wired agent does,
#    then read it back. The read is retried; the write never is, because a second
#    POST would create a second observation.
probe="ts-stack-verify-$$-$(date +%s)"
# The body is hook-shaped, copied from the vendor post-tool-use.mjs: hookType,
# sessionId, project, cwd, timestamp and a data object. Guessing at it gets a 400.
payload="$(cat <<EOF
{"hookType":"post_tool_use","sessionId":"$probe","project":"ts-stack-verify",
 "cwd":"/ts-stack-verify","timestamp":"$(date -u +%Y-%m-%dT%H:%M:%SZ)",
 "data":{"tool_name":"ts-stack","tool_input":{"probe":"$probe"},"tool_output":"$probe"}}
EOF
)"
code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
        -X POST "$PROXY/agentmemory/observe" \
        -H 'content-type: application/json' -H "Authorization: Bearer $secret" \
        -d "$payload" 2>/dev/null || echo 000)"
case "$code" in
    2??) pass "wrote a probe observation ($probe)" ;;
    401) fail 'the server refused the secret (401) — the cached copy is stale'; exit 1 ;;
    000) fail 'no response when writing a probe observation'; exit 1 ;;
    *)   fail "writing a probe observation answered $code"; exit 1 ;;
esac

# The read is what proves capture, and it is retried because indexing is not
# instant. Sessions first: an observation is RECORDED immediately, while search
# has to index it, so checking search alone turns a slow index into a false
# failure. Search is POST {"query": ...} -- GET is 405 and {"q": ...} is 400.
found=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -s --max-time 8 -H "Authorization: Bearer $secret" \
        "$PROXY/agentmemory/sessions?limit=50" 2>/dev/null | grep -q "$probe"; then
        found=sessions; break
    fi
    if curl -s --max-time 8 -X POST -H 'content-type: application/json' \
        -H "Authorization: Bearer $secret" -d "{\"query\":\"$probe\",\"limit\":20}" \
        "$PROXY/agentmemory/search" 2>/dev/null | grep -q "$probe"; then
        found=search; break
    fi
    sleep 2
done
case "$found" in
    search)   pass 'read the probe back through search — capture and retrieval both work' ;;
    sessions) pass 'the probe was recorded (found in sessions; search may still be indexing)' ;;
    *)        fail 'the probe was written but never came back from sessions or search'; rc=1 ;;
esac

exit $rc
