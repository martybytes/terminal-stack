#!/usr/bin/env bash
# cc-tts-test.sh — end-to-end TTS test (synth + play).
# Usage: cc-tts-test.sh [--source claude|cursor|codex|test] [--daemon | --daemon-fallback] ["optional phrase"]
#   --daemon           POST a synthetic event to the ttsd daemon; expect it spoken.
#   --daemon-fallback  point the sender at a dead port; the direct path must still speak.
set -euo pipefail

source=test
phrase=""
mode=direct
while [ $# -gt 0 ]; do
    case "$1" in
        --source|-s)
            source="${2:-test}"
            shift 2
            ;;
        --daemon)
            mode=daemon
            shift
            ;;
        --daemon-fallback)
            mode=fallback
            shift
            ;;
        *)
            phrase="$1"
            shift
            ;;
    esac
done

notify="${HOME}/.claude/hooks/cc-tts-notify.sh"
LIB="${HOME}/.claude/hooks/cc-tts-lib.sh"
[ -f "$notify" ] || { echo "cc-tts-test: $notify not found (chezmoi apply)" >&2; exit 1; }
[ -f "$LIB" ] && . "$LIB"

if [ "$mode" = daemon ]; then
    # POST a synthetic stop event; the daemon should accept (202) and speak it.
    cc_tts_daemon_ready || { echo "cc-tts-test: daemon not enabled/reachable from this host (tstack config tts daemon status)" >&2; exit 1; }
    input='{"session_id":"cc-tts-test","last_assistant_message":"Daemon test. <!-- speak: Daemon test successful. -->"}'
    if cc_tts_daemon_send "$source" stop waiting "$input" "Daemon test from cc-tts-test."; then
        echo "cc-tts-test: daemon accepted the event — expect speech shortly."
        exit 0
    fi
    echo "cc-tts-test: daemon did not accept the event (tstack config tts daemon status)" >&2
    exit 1
fi

if [ "$mode" = fallback ]; then
    # The crucial guarantee: a dead daemon must degrade to direct speech.
    echo "cc-tts-test: simulating a dead daemon (port 1) — direct playback must still sound."
    printf '{"session_id":"cc-tts-test-fallback"}' \
        | CC_TTS_DAEMON_PORT_OVERRIDE=1 \
          "$(dirname "$notify")/cc-speak.sh" waiting "Fallback test: direct playback works."
    echo "cc-tts-test: fallback path invoked (listen for the phrase)."
    exit 0
fi

if [ -z "$phrase" ] && [ -f "$LIB" ]; then
    cc_tts_init_config
    phrase="$(cc_tts_build_speech "$source" waiting "$(basename "${PWD}")" "")"
fi
[ -n "$phrase" ] || phrase="Terminal stack TTS test."

echo "cc-tts-test: source=$source phrase=$phrase" >&2
export CC_TTS_VERBOSE=1
export CC_TTS_SOURCE="$source"
CC_TTS_FOREGROUND=1 "$notify" waiting "$phrase"
