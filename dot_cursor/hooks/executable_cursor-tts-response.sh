#!/usr/bin/env bash
# Cursor afterAgentResponse hook → completion TTS with final response text.
set -euo pipefail

input="$(cat 2>/dev/null || true)"
[ -n "$input" ] || { printf '{}\n'; exit 0; }

LIB="${HOME}/.claude/hooks/cc-tts-lib.sh"
notify="${HOME}/.claude/hooks/cc-tts-notify.sh"
if [ ! -f "$LIB" ] || [ ! -f "$notify" ]; then
    printf '{}\n'
    exit 0
fi
# shellcheck source=/dev/null
. "$LIB"

if cc_tts_windows_hook cursor cursor_response waiting "$input" >/dev/null 2>&1; then
    printf '{}\n'
    exit 0
fi

export CC_TTS_HOOK_JSON="$input"
export CC_TTS_PREFIX=Cursor
export CC_TTS_SOURCE=cursor
if cc_tts_daemon_ready; then
    (
        cc_tts_daemon_send cursor cursor_response waiting "$input" \
            || "$notify" waiting
    ) >/dev/null 2>&1 &
else
    "$notify" waiting &
fi
printf '{}\n'
exit 0
