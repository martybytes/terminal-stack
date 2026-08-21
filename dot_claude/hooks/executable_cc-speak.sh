#!/usr/bin/env bash
# cc-speak.sh — Claude Code TTS hook (Stop / StopFailure).
# Usage: cc-speak.sh <waiting|error> [override-text]
# Tries the ttsd daemon first (session-aware queueing/coalescing/ducking);
# any failure falls back to the classic direct path — never silence.
set -euo pipefail
state="${1:-}"
case "$state" in waiting|error) ;; *) exit 0 ;; esac
input="$(cat 2>/dev/null || true)"

LIB="$(dirname "$0")/cc-tts-lib.sh"
# shellcheck source=cc-tts-lib.sh
. "$LIB"

notify="$(dirname "$0")/cc-tts-notify.sh"
source="${CC_TTS_SOURCE:-claude}"
export CC_TTS_SOURCE="$source"
if cc_tts_daemon_ready; then
    event=stop
    [ "$state" = error ] && event=stop_failure
    (
        cc_tts_daemon_send "$source" "$event" "$state" "$input" "${2:-}" \
            || CC_TTS_HOOK_JSON="$input" "$notify" "$state" "${2:-}"
    ) >/dev/null 2>&1 &
    exit 0
fi
CC_TTS_HOOK_JSON="$input" exec "$notify" "$state" "${2:-}"
