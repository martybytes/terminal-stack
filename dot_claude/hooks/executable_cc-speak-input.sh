#!/usr/bin/env bash
# cc-speak-input.sh — Claude Code input hooks (Notification / PermissionRequest / AskUserQuestion).
# Usage: cc-speak-input.sh <notification|permission|question>
# Daemon-first with direct-path fallback — never silence.
set -euo pipefail
event="${1:-question}"
input="$(cat 2>/dev/null || true)"

LIB="$(dirname "$0")/cc-tts-lib.sh"
# shellcheck source=cc-tts-lib.sh
. "$LIB"

cc_tts_parse_input_state "$input" "$event"
state="${CC_TTS_PARSED_STATE:-question}"
override="${CC_TTS_PARSED_OVERRIDE:-}"

export CC_TTS_HOOK_JSON="$input"
export CC_TTS_SOURCE=claude
notify="$(dirname "$0")/cc-tts-notify.sh"
if cc_tts_daemon_ready; then
    (
        cc_tts_daemon_send claude "$event" "$state" "$input" "$override" \
            || "$notify" "$state" "$override"
    ) >/dev/null 2>&1 &
    exit 0
fi
"$notify" "$state" "$override" &
exit 0
