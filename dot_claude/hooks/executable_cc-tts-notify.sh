#!/usr/bin/env bash
# cc-tts-notify.sh — synthesize + play (shared by Claude Code and Cursor hooks).
# Usage: cc-tts-notify.sh <waiting|error|question|permission> [override-text]
# Env: CC_TTS_SOURCE=claude|cursor|codex|test; CC_TTS_FOREGROUND=1; CC_TTS_HOOK_JSON=…
set -euo pipefail
LIB="$(dirname "$0")/cc-tts-lib.sh"
# shellcheck source=cc-tts-lib.sh
. "$LIB"

state="${1:-}"
override_text="${2:-}"
source="${CC_TTS_SOURCE:-claude}"
_foreground=0
[ -n "${CC_TTS_FOREGROUND:-}" ] && _foreground=1

case "$state" in waiting|error|question|permission) ;; *)
    echo "usage: cc-tts-notify.sh <waiting|error|question|permission> [override-text]" >&2
    exit 2
    ;;
esac

cc_tts_init_config
[ -f "$CONFIG" ] || { [ "$_foreground" -eq 1 ] && echo "cc-tts-notify: missing config" >&2; exit 1; }
[ "$_foreground" -eq 0 ] && [ "$(cc_tts_json .enabled false)" != true ] && exit 0
# Absolute: no priority escape, and checked here because this path plays audio itself
# rather than delegating to the Windows EXE. A foreground run (cc-tts-test) is exempt --
# you asked for that one.
[ "$_foreground" -eq 0 ] && cc_tts_muted && exit 0
cc_tts_event_enabled "$state" || exit 0

project_dir="${CLAUDE_PROJECT_DIR:-${CURSOR_PROJECT_DIR:-$PWD}}"
if [ -n "${CC_TTS_HOOK_JSON:-}" ] && command -v jq >/dev/null 2>&1; then
    wr="$(printf '%s' "$CC_TTS_HOOK_JSON" | jq -r '.workspace_roots[0] // empty' 2>/dev/null || true)"
    [ -n "$wr" ] && project_dir="$wr"
fi
project="$(basename "$project_dir")"

text="$(cc_tts_build_speech "$source" "$state" "$project" "$override_text")"
[ -n "$text" ] || exit 0

cache_dir="${HOME}/.cache/terminal-stack"
debounce_file="${cache_dir}/cc-tts.last"
lock_file="${cache_dir}/cc-tts.play.lock"
mkdir -p "$cache_dir" 2>/dev/null || true

if [ "$_foreground" -eq 0 ]; then
    debounce="$(cc_tts_json .debounceSec 5)"
    now=$(date +%s 2>/dev/null || echo 0)
    if [ -f "$debounce_file" ]; then
        last=$(cat "$debounce_file" 2>/dev/null || echo 0)
        if [ "$((now - last))" -lt "$debounce" ] 2>/dev/null; then
            exit 0
        fi
    fi
    echo "$now" > "$debounce_file" 2>/dev/null || true
fi

_hooks="$(dirname "$0")"
_worker() {
    local out ext ok=1
    ext="$(cc_tts_json .kokoro.format mp3)"
    out="$(cc_tts_temp_media "$ext")"
    [ -n "$out" ] || return 1
    cc_tts_synth "$text" "$out" && ok=0
    if [ "$ok" -eq 0 ] && [ -s "$out" ]; then
        local i=0
        while [ -f "$lock_file" ] && [ "$i" -lt 30 ]; do sleep 0.2; i=$((i + 1)); done
        : > "$lock_file" 2>/dev/null || true
        CC_TTS_CONFIG="$CONFIG" "$_hooks/cc-tts-play.sh" "$out" || true
        rm -f "$lock_file" 2>/dev/null || true
    fi
    rm -f "$out" 2>/dev/null || true
}

if [ "$_foreground" -eq 1 ]; then
    _worker
    exit $?
fi

( _worker ) >/dev/null 2>&1 &
exit 0
