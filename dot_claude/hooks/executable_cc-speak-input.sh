#!/usr/bin/env bash
# cc-speak-input.sh — agent input hooks (Notification / AskUserQuestion).
# The `permission` state is still accepted (ts-config tts test, and Cursor), but no
# Claude hook sends it any more: PermissionRequest echoed the tool name twice and
# Notification already announces permission prompts in Claude’s own words.
# Usage: cc-speak-input.sh <notification|permission|question>
# Daemon-first with direct-path fallback — never silence.
set -euo pipefail
event="${1:-question}"
input="$(cat 2>/dev/null || true)"
source="${CC_TTS_SOURCE:-claude}"

LIB="$(dirname "$0")/cc-tts-lib.sh"
# shellcheck source=cc-tts-lib.sh
. "$LIB"

if cc_tts_windows_hook "$source" "$event" question "$input" >/dev/null 2>&1; then
    exit 0
fi

cc_tts_parse_input_state "$input" "$event"
state="${CC_TTS_PARSED_STATE:-question}"
override="${CC_TTS_PARSED_OVERRIDE:-}"

export CC_TTS_HOOK_JSON="$input"
export CC_TTS_SOURCE="$source"
notify="$(dirname "$0")/cc-tts-notify.sh"
if cc_tts_daemon_ready; then
    (
        cc_tts_daemon_send "$source" "$event" "$state" "$input" "$override" \
            || "$notify" "$state" "$override"
    ) >/dev/null 2>&1 &
    exit 0
fi
"$notify" "$state" "$override" &
exit 0
