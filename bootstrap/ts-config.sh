#!/usr/bin/env bash
# ts-config.sh — view/change the saved terminal-stack config (leader key, theme,
# tmux prefix, apps, WezTerm mux + session restore) and re-apply. Driven by the
# `ts-config` shell wrapper (zsh) and runnable standalone. On Windows the pwsh
# ts-config is the counterpart.
#
# Usage:
#   ts-config                 interactive menu
#   ts-config show            print the current config
#   ts-config leader <chord>  e.g. ctrl-space, ctrl-a, alt-x
#   ts-config theme  <mode>   dark | light | follow
#   ts-config tmux   <chord>  tmux prefix, e.g. ctrl-a
#   ts-config apps [recommended|all|none|id,id,...]   (no arg → interactive picker)
#   ts-config mux [on|off|...]  hand-off to ts-mux (WezTerm multiplexer domain)
#   ts-config restore <on|off>  reopen the last WezTerm session at startup
#
# Config lives in chezmoi [data] (~/.config/chezmoi/chezmoi.toml); changes are
# persisted with ts_save_config, then `chezmoi apply` re-renders every file.
set -euo pipefail

CZ="${TERMINAL_STACK_CHEZMOI:-}"
if [ -z "$CZ" ]; then
    if [ -x "$HOME/.local/bin/chezmoi" ]; then CZ="$HOME/.local/bin/chezmoi"
    elif command -v chezmoi >/dev/null 2>&1; then CZ="$(command -v chezmoi)"
    else echo "ts-config: chezmoi not found on PATH." >&2; exit 1; fi
fi
SRC="${TERMINAL_STACK_DIR:-$("$CZ" source-path 2>/dev/null || true)}"
if [ ! -d "$SRC/bootstrap" ]; then
    echo "ts-config: cannot locate the terminal-stack clone (set TERMINAL_STACK_DIR)." >&2
    exit 1
fi
# shellcheck source=_config.sh
. "$SRC/bootstrap/_config.sh"
# shellcheck source=_wizard.sh
. "$SRC/bootstrap/_wizard.sh"

cur()     { local v; v="$(ts_data_get "$1" 2>/dev/null || true)"; [ -n "$v" ] && echo "$v" || echo "$2"; }
curapps() { ts_data_get_apps 2>/dev/null || true; }

finish() {
    echo "==> applying…"
    "$CZ" apply
    echo "==> done."
}

# Install the selected apps for the current platform (idempotent; never uninstalls).
install_apps() {
    local apps="$*"
    case "$(uname -s)" in
        Darwin) ts_brew_install_apps $apps ;;
        *)
            if command -v apt-get >/dev/null 2>&1; then
                # shellcheck source=_common-debian.sh
                . "$SRC/bootstrap/_common-debian.sh"
                common_install_selected_apps "$apps"
            else
                echo "ts-config: no supported package manager; recorded selection only."
            fi ;;
    esac
}

# shellcheck disable=SC2046
set_leader() { ts_save_config "$1" "$(cur themeMode dark)" "$(cur tmuxPrefix ctrl-b)" $(curapps); finish; }
# shellcheck disable=SC2046
set_theme()  { ts_save_config "$(cur leaderChord ctrl-space)" "$1" "$(cur tmuxPrefix ctrl-b)" $(curapps); finish; }
# shellcheck disable=SC2046
set_tmux()   { ts_save_config "$(cur leaderChord ctrl-space)" "$(cur themeMode dark)" "$1" $(curapps); finish; }
# shellcheck disable=SC2086
set_apps()   { ts_save_config "$(cur leaderChord ctrl-space)" "$(cur themeMode dark)" "$(cur tmuxPrefix ctrl-b)" $1; install_apps "$1"; finish; }

# Reopening the last WezTerm session at startup. Stored on its own like the mux
# key, so flipping it need not re-state every other choice.
set_restore() { ts_wez_restore_set "$1"; finish; }

# The mux has its own verbs (kill/restart/reset), so ts-config just hands off.
run_mux() {
    TERMINAL_STACK_DIR="$SRC" TERMINAL_STACK_CHEZMOI="$CZ" bash "$SRC/bootstrap/ts-mux.sh" "$@"
}

show() {
    echo "terminal-stack config:"
    echo "  leader     : $(cur leaderChord ctrl-space)   (WezTerm: $(cur leaderMods CTRL)+$(cur leaderKey phys:Space))"
    echo "  theme      : $(cur themeMode dark)   (baked palette: $(cur resolvedTheme dark))"
    echo "  tmux       : $(cur tmuxPrefix ctrl-b)   (prefix: $(cur tmuxPrefixResolved C-b))"
    echo "  apps       : $(curapps)"
    echo "  wezmux     : $(ts_wez_mux_get)   (ts-mux on|off|status)"
    echo "  wezrestore : $(ts_wez_restore_get)   (ts-config restore on|off)"
}

menu() {
    while true; do
        echo
        show
        echo
        echo "  1) leader key   2) theme   3) tmux prefix   4) apps   5) re-apply   6) Claude TTS   7) WezTerm mux   8) session restore   q) quit"
        local c; c="$(ts_tty_prompt 'Choose: ')"
        case "$c" in
            1) set_leader "$(ts_prompt_leader)" ;;
            2) set_theme  "$(ts_prompt_theme)" ;;
            3) local t; t="$(ts_tty_prompt 'tmux prefix chord (e.g. ctrl-a) [ctrl-b]: ')"; set_tmux "${t:-ctrl-b}" ;;
            4) set_apps "$(ts_prompt_apps)" ;;
            5) finish ;;
            6) ts_config_tts show; echo; ts_config_tts_menu ;;
            7) run_mux status ;;
            8) local r; r="$(ts_prompt_wezterm_restore)"; set_restore "$r" ;;
            q|Q|"") return 0 ;;
            *) echo "?" ;;
        esac
    done
}

case "${1:-}" in
    "")     menu ;;
    show)   show ;;
    leader) [ -n "${2:-}" ] || { echo "usage: ts-config leader <chord>" >&2; exit 2; }; set_leader "$2" ;;
    theme)  [ -n "${2:-}" ] || { echo "usage: ts-config theme <dark|light|follow>" >&2; exit 2; }; set_theme "$2" ;;
    tmux)   [ -n "${2:-}" ] || { echo "usage: ts-config tmux <chord>" >&2; exit 2; }; set_tmux "$2" ;;
    apps)
        if [ -n "${2:-}" ]; then set_apps "$(ts_expand_apps "$2")"
        else set_apps "$(ts_pick_apps)"; fi ;;
    tts)
        shift
        ts_config_tts "$@" ;;
    mux)
        shift
        run_mux "$@" ;;
    restore)
        case "${2:-}" in on|off) ;; *)
            echo "usage: ts-config restore <on|off>" >&2; exit 2 ;; esac
        set_restore "$2" ;;
    -h|--help|help)
        sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
        echo "  tts show|on|off|test|reset|engine|message|voice|..."
        echo "  mux status|on|off|list|kill|restart|reset  (see: ts-mux -h)"
        echo "  restore on|off   reopen the last WezTerm session at startup"
        ;;
    *) echo "ts-config: unknown command '$1' (try: show, leader, theme, tmux, apps, tts, mux, restore)" >&2; exit 2 ;;
esac
