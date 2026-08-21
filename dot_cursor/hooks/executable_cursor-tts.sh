#!/usr/bin/env bash
# cursor-tts.sh — Cursor Agent stop hook → local TTS (same config as Claude Code).
# Reads stop-event JSON from stdin; speaks only on error; returns {} immediately.
# Daemon-first (the daemon holds/cools Cursor's per-turn stop storms) with
# direct-path fallback — never silence.
set -euo pipefail

input="$(cat 2>/dev/null || true)"
state=error

if command -v jq >/dev/null 2>&1 && [ -n "$input" ]; then
    case "$(printf '%s' "$input" | jq -r '.status // "completed"')" in
        error)   state=error ;;
        aborted) printf '{}\n'; exit 0 ;;
        *)       printf '{}\n'; exit 0 ;;
    esac
elif [[ "$input" != *'"status"'*'"error"'* ]]; then
    printf '{}\n'
    exit 0
fi

LIB="${HOME}/.claude/hooks/cc-tts-lib.sh"
notify="${HOME}/.claude/hooks/cc-tts-notify.sh"
if [ ! -f "$LIB" ] || [ ! -f "$notify" ]; then
    printf '{}\n'
    exit 0
fi
# shellcheck source=/dev/null
. "$LIB"

if cc_tts_windows_hook cursor cursor_stop "$state" "$input" >/dev/null 2>&1; then
    printf '{}\n'
    exit 0
fi

export CC_TTS_HOOK_JSON="$input"
export CC_TTS_PREFIX=Cursor
export CC_TTS_SOURCE=cursor
if cc_tts_daemon_ready; then
    (
        cc_tts_daemon_send cursor cursor_stop "$state" "$input" \
            || "$notify" "$state"
    ) >/dev/null 2>&1 &
else
    "$notify" "$state" &
fi
printf '{}\n'
exit 0
