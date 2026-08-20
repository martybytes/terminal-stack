#!/usr/bin/env bash
state="${1:-}"
[ -z "$WEZTERM_PANE" ] && exit 0
case "$state" in
    thinking|working|waiting|error) ;;
    *) exit 0 ;;
esac
project_dir="${CLAUDE_PROJECT_DIR:-$PWD}"
project=$(basename "$project_dir")
# Bare project name only — no 'cc'/state prefix. WezTerm's format-tab-title
# already shows the Claude icon and per-pane state dots (driven by the cc_state
# user var below); a prefix would just waste tab width.
# wezterm on Mac/native-Linux; wezterm.exe via interop on WSL.
if command -v wezterm >/dev/null 2>&1; then
    wezterm cli set-tab-title "$project" 2>/dev/null || true
elif command -v wezterm.exe >/dev/null 2>&1; then
    wezterm.exe cli set-tab-title "$project" 2>/dev/null || true
fi

# ── Per-pane background tint by Claude state (OSC 11; this pane only) ─────────
# Each WezTerm pane is its own terminal, so OSC 11 colours only THIS pane. Written
# to the controlling TTY (the hook's stdout is captured by Claude Code); DCS-wrapped
# for tmux passthrough (needs allow-passthrough on). Catppuccin-accent dark tints —
# tune the hexes to taste. Reset to base happens in the cc() wrapper on exit.
# NOTE: under WezTerm the primary path is the user-var-changed handler (driven by
# the cc_state OSC 1337 below), which re-emits this tint via pane:inject_output —
# required on Windows, where ConPTY swallows OSC 11. This raw OSC 11 still covers
# non-ConPTY mux/SSH panes that inject_output can't reach.
case "$state" in
    thinking|working) _bg='#4a3020' ;;   # warm/peach — working
    waiting)          _bg='#1e3828' ;;   # green — your turn / done
    error)            _bg='#3a1828' ;;   # red — failed / needs attention
    *)                _bg='' ;;
esac
if [ -n "$_bg" ]; then
    _seq=$(printf '\033]11;%s\007' "$_bg")
    [ -n "$TMUX" ] && _seq=$(printf '\033Ptmux;\033%s\033\\' "$_seq")
    printf '%s' "$_seq" > /dev/tty 2>/dev/null || true
fi

# ── Per-pane Claude state as a WezTerm user var (read by format-tab-title) ───
# OSC 1337 SetUserVar (base64). `wezterm cli set-user-var` doesn't exist in this
# build, so emit the escape to the pane TTY (DCS-wrapped under tmux). Cleared by
# the cc() wrapper on exit.
case "$state" in
    thinking|working) _cc='working' ;;
    waiting)          _cc='done' ;;
    error)            _cc='error' ;;
    *)                _cc='' ;;
esac
_uv=$(printf '\033]1337;SetUserVar=cc_state=%s\007' "$(printf '%s' "$_cc" | base64 | tr -d '\n')")
[ -n "$TMUX" ] && _uv=$(printf '\033Ptmux;\033%s\033\\' "$_uv")
printf '%s' "$_uv" > /dev/tty 2>/dev/null || true

# Toast notification — fires for 'waiting' (done) and 'error' if sentinel file exists.
# Toggle: ccnotify on / ccnotify off
if [ "$state" = "waiting" ] || [ "$state" = "error" ]; then
    if [ -f "$HOME/.claude/.toast-notify" ]; then
        _msg="Done: $project"
        [ "$state" = "error" ] && _msg="Error: $project"
        if command -v notify-send >/dev/null 2>&1; then
            notify-send "Claude Code" "$_msg" 2>/dev/null || true
        elif command -v osascript >/dev/null 2>&1; then
            osascript -e "display notification \"$_msg\" with title \"Claude Code\"" 2>/dev/null || true
        fi
    fi
fi

# ── Barge-in signal for the ttsd daemon (backgrounded, best-effort) ──────────
# A new prompt in this session cancels its queued "done"/"error" announcements
# — the user is already looking at this pane. No fallback action: this event
# is advisory, so a dead daemon just means no cancellation.
if [ "$state" = "thinking" ] && [ -f "$HOME/.claude/hooks/cc-tts-lib.sh" ]; then
    _input="$(cat 2>/dev/null || true)"
    (
        . "$HOME/.claude/hooks/cc-tts-lib.sh"
        cc_tts_daemon_ready || exit 0
        cc_tts_daemon_send claude prompt_submit "" "$_input" || true
    ) >/dev/null 2>&1 &
fi
