#!/usr/bin/env bash
# cursor-tts-input.sh — Cursor postToolUse hook when agent asks a question (AskQuestion).
# Daemon-first with direct-path fallback — never silence.
set -euo pipefail

input="$(cat 2>/dev/null || true)"
tool_name=""
if command -v jq >/dev/null 2>&1 && [ -n "$input" ]; then
    tool_name="$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null || true)"
fi
case "$tool_name" in
    AskQuestion|AskUserQuestion) ;;
    *) printf '{}\n'; exit 0 ;;
esac

LIB="${HOME}/.claude/hooks/cc-tts-lib.sh"
notify="${HOME}/.claude/hooks/cc-tts-notify.sh"
if [ ! -f "$LIB" ] || [ ! -f "$notify" ]; then
    printf '{}\n'
    exit 0
fi
# shellcheck source=/dev/null
. "$LIB"

if cc_tts_windows_hook cursor cursor_question question "$input" >/dev/null 2>&1; then
    printf '{}\n'
    exit 0
fi

cc_tts_parse_input_state "$input" cursor_question
state="${CC_TTS_PARSED_STATE:-question}"
override="${CC_TTS_PARSED_OVERRIDE:-}"

export CC_TTS_HOOK_JSON="$input"
export CC_TTS_SOURCE=cursor
if cc_tts_daemon_ready; then
    (
        cc_tts_daemon_send cursor cursor_question "$state" "$input" "$override" \
            || "$notify" "$state" "$override"
    ) >/dev/null 2>&1 &
else
    "$notify" "$state" "$override" &
fi
printf '{}\n'
exit 0
