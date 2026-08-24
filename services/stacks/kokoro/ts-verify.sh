#!/usr/bin/env bash
# ts-verify.sh — kokoro: prove it actually synthesises audio.
# Run by `ts-stack test`; safe to run by hand. Exit 0 = pass.
#
# Windows twin: ts-verify.ps1. Change one, change the other.
#
# This stack's documented failure is a CUDA build that does not match the card:
# the container reports Up and then crash-loops, so "Up (healthy)" proves
# nothing. RestartCount and a real synthesis are what prove it.
set -uo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
# shellcheck source=../../_stack.sh
. "$ROOT/_stack.sh"

KOKORO="${KOKORO_URL:-http://127.0.0.1:8880}"
rc=0

# 1. Not crash-looping. A restarting container passes a health check between
#    restarts, which is exactly how this failure hides.
restarts="$(docker inspect -f '{{.RestartCount}}' ts-kokoro-tts 2>/dev/null || echo '')"
if [ -z "$restarts" ]; then
    fail 'ts-kokoro-tts does not exist'
    rc=1
elif [ "$restarts" = 0 ]; then
    pass 'no restarts'
else
    fail "ts-kokoro-tts has restarted $restarts time(s) — likely a CUDA build that does not match this card (see README.md)"
    rc=1
fi

# 2. Synthesis. Written to a temp file the trap removes, never into the stack
#    directory: an out.mp3 left behind is how that name ended up in .gitignore.
out="$(mktemp)"; trap 'rm -f "$out"' EXIT
code="$(curl -s -o "$out" -w '%{http_code}' --max-time 60 \
        -X POST "$KOKORO/v1/audio/speech" -H 'content-type: application/json' \
        -d '{"model":"kokoro","input":"terminal stack verification","voice":"am_adam","response_format":"mp3"}' \
        2>/dev/null || echo 000)"
bytes="$(file_size "$out" 2>/dev/null || echo 0)"
case "$code" in
    2??)
        if [ "$bytes" -gt 2048 ]; then pass "synthesised ${bytes} bytes of audio"
        else fail "synthesis answered 2xx but produced only ${bytes} bytes"; rc=1; fi ;;
    000) fail "no response from $KOKORO"; rc=1 ;;
    *)   fail "synthesis answered $code"; rc=1 ;;
esac

exit $rc
