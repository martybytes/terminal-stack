#!/usr/bin/env bash
# ts-verify.sh — agent007memory: prove the console proxies to AgentMemory and
# serves its own UI. Run by `tstack services test`; safe to run by hand. Exit 0 = pass.
#
# Windows twin: ts-verify.ps1. Change one, change the other.
#
# "Up (healthy)" is not evidence here. This container's healthcheck asks its own
# /healthz, which answers whether or not the upstream it exists to proxy is
# reachable -- and an unreachable upstream is exactly the failure that matters,
# because every MCP client is pointed at 3111, not at the server's own 3110.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
# shellcheck source=../../_stack.sh
. "$ROOT/_stack.sh"

BYPASS="${AGENTMEMORY_BYPASS_URL:-http://127.0.0.1:3110}"   # the server itself
PROXY="${AGENTMEMORY_URL:-http://127.0.0.1:3111}"           # this container
CONSOLE="${AGENTMEMORY_CONSOLE_URL:-http://127.0.0.1:3114}"
rc=0

if tss_wait_http "$CONSOLE/healthz" 10 2xx; then pass 'console healthz (3114)'
else fail "the console UI is not answering at $CONSOLE"; rc=1; fi

# The proxy is only meaningful relative to the server behind it, so both are
# asked and the verdict names which of the two is actually down.
if tss_wait_http "$PROXY/agentmemory/livez" 10 2xx; then
    pass 'proxy forwards to agentmemory (3111 -> ts-agentmemory-server:3111)'
elif tss_wait_http "$BYPASS/agentmemory/livez" 2 2xx; then
    fail 'the proxy on 3111 is not forwarding, though the server behind it is healthy — is this container on ts-agentmemory-net?'
    rc=1
else
    fail 'the agentmemory server itself is down, so the proxy has nothing to forward to (start it: tstack services up agentmemory)'
    rc=1
fi

# The UI is a single-page app, so an empty 200 is a failed build, not a pass.
body="$(curl -s --max-time 10 "$CONSOLE/" 2>/dev/null)"
case "$body" in
    *"<div id=\"root\""*|*"<div id=root"*|*"<script"*) pass 'the console UI serves its application shell' ;;
    '') fail "the console UI returned an empty body at $CONSOLE/ — the image built without its front end"; rc=1 ;;
    *)  fail "the console UI answered without an application shell at $CONSOLE/"; rc=1 ;;
esac

exit $rc
