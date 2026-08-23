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
#   ts-config agents [show|<tool> on|off|status|repair|uninstall]
#   ts-config wezterm [status|changes|install <chan>|upgrade]
#   ts-config wizard          re-run the whole install questionnaire
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
# The installed build date, for the `show` line. No network — the date is in the
# version string. Empty when WezTerm is absent.
_ts_cfg_wezterm_built() {
    local inst d; inst="$(ts_wezterm_installed 2>/dev/null || true)"
    [ -n "$inst" ] || return 0
    d="$(printf '%s' "$inst" | cut -d'|' -f2)"
    [ -n "$d" ] && printf '   (built %s)' "$(ts_wez_fmt_date "$d")"
}
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
set_apps()   { ts_save_config "$(cur leaderChord ctrl-space)" "$(cur themeMode dark)" "$(cur tmuxPrefix ctrl-b)" $1; install_apps "$1"; ts_report_installed_apps "$1"; finish; }

# Install the chosen terminal emulator(s) for this platform. Never uninstalls,
# except the other WezTerm channel when switching (they cannot coexist).
install_terminals() {
    local sel="$1" channel
    [ -n "$sel" ] || { echo "==> Terminal emulator: none selected; skipping."; return 0; }
    channel="$(ts_terminals_channel "$sel")"
    [ -n "$channel" ] && ts_wezterm_install "$channel"
    case " $sel " in *" ghostty "*)
        if [ "$(uname -s)" = Darwin ] && command -v brew >/dev/null 2>&1; then
            brew list --cask ghostty >/dev/null 2>&1 || brew install --cask ghostty || true
        fi ;;
    esac
}

# Re-run the whole questionnaire, not just one answer. `ts-config apps` re-asks
# the apps question alone; this replays every prompt the installer asks and
# persists all of it — which also sidesteps ts_save_config's positional trap,
# since every value is being re-stated anyway. TS_ASSUME_YES=1 makes it
# non-interactive, and the per-question TS_* vars still skip individual prompts.
run_wizard() {
    ts_wizard_collect || { echo "ts-config: wizard cancelled; nothing changed."; return 0; }
    install_apps "${TS_WIZ_APPS:-}"
    # The pwsh $runWizard has always installed the chosen emulator; this side
    # never did, so a `ts-config wizard` that picked WezTerm silently did nothing.
    install_terminals "${TS_WIZ_TERMINALS:-}"
    ts_save_config "${TS_WIZ_LEADER:-ctrl-space}" "${TS_WIZ_THEME:-dark}" "${TS_WIZ_TMUX:-ctrl-b}" ${TS_WIZ_APPS:-}
    ts_agents_save_config "${TS_WIZ_HEADROOM:-off}" "${TS_WIZ_HEADROOM_CURSOR:-mcp}" "${TS_WIZ_CAVEMAN:-off}" "${TS_WIZ_AGENTMEMORY:-off}"
    ts_wez_mux_set "${TS_WIZ_WEZ_MUX:-off}"
    ts_wez_restore_set "${TS_WIZ_WEZ_RESTORE:-off}"
    ts_cc_tts_apply_wizard_choice "${TS_WIZ_CC_TTS:-off}"
    ts_report_installed_apps "${TS_WIZ_APPS:-}"
    finish
}

# Reopening the last WezTerm session at startup. Stored on its own like the mux
# key, so flipping it need not re-state every other choice.
set_restore() { ts_wez_restore_set "$1"; finish; }

# The mux has its own verbs (kill/restart/reset), so ts-config just hands off.
run_mux() {
    TERMINAL_STACK_DIR="$SRC" TERMINAL_STACK_CHEZMOI="$CZ" bash "$SRC/bootstrap/ts-mux.sh" "$@"
}

# WezTerm build info / channel switching. Hand-off like run_mux: the logic lives
# in bootstrap/ts-wezterm.sh so `ts-wezterm` works standalone too.
run_wezterm() {
    TERMINAL_STACK_DIR="$SRC" TERMINAL_STACK_CHEZMOI="$CZ" \
        bash "$SRC/bootstrap/ts-wezterm.sh" "$@"
}

agents_show() {
    echo "coding agents (user-global on this computer):"
    echo "  headroom   : $(ts_agent_get headroomEnabled)   (Cursor: $(ts_agent_get headroomCursorMode))"
    echo "  caveman    : $(ts_agent_get cavemanEnabled)"
    echo "  agentmemory: $(ts_agent_get agentmemoryEnabled)"
}

run_agent_adapter() {
    local tool="$1" action="$2" cursor_mode="${3:-$(ts_agent_get headroomCursorMode)}"
    bash "$SRC/bootstrap/ts-agents.sh" "$tool" "$action" "$cursor_mode"
}

agents_set() {
    local tool="$1" action="$2" key=""
    case "$tool" in
        headroom) key=headroomEnabled ;;
        caveman) key=cavemanEnabled ;;
        agentmemory) key=agentmemoryEnabled ;;
        *) echo "usage: ts-config agents <headroom|caveman|agentmemory> on|off|status|repair|uninstall" >&2; return 2 ;;
    esac
    case "$action" in
        on) run_agent_adapter "$tool" on && ts_agent_set "$key" on ;;
        off) run_agent_adapter "$tool" off; ts_agent_set "$key" off ;;
        uninstall) run_agent_adapter "$tool" uninstall; ts_agent_set "$key" off ;;
        status|repair) run_agent_adapter "$tool" "$action" ;;
        *) echo "usage: ts-config agents $tool on|off|status|repair|uninstall" >&2; return 2 ;;
    esac
}

agents_config() {
    local sub="${1:-}" action="${2:-}" extra="${3:-}"
    case "$sub" in
        ''|show) agents_show ;;
        headroom)
            if [ "$action" = dashboard ]; then run_agent_adapter headroom dashboard; return; fi
            if [ "$action" = cursor ]; then
                case "$extra" in mcp|byok|off) ;; *) echo "usage: ts-config agents headroom cursor <mcp|byok|off>" >&2; return 2;; esac
                ts_agent_set headroomCursorMode "$extra"
                [ "$(ts_agent_get headroomEnabled)" = on ] && run_agent_adapter headroom repair "$extra" || true
                agents_show
                return
            fi
            agents_set headroom "${action:-status}" ;;
        caveman|agentmemory) agents_set "$sub" "${action:-status}" ;;
        *) echo "ts-config agents: unknown tool '$sub'" >&2; return 2 ;;
    esac
}

agents_menu() {
    while true; do
        echo; agents_show; echo
        echo '  1) Headroom  2) Caveman  3) AgentMemory  4) Headroom Cursor mode  q) back'
        local c a tool; c="$(ts_tty_prompt 'Choose: ')"
        case "$c" in
            1) tool=headroom ;;
            2) tool=caveman ;;
            3) tool=agentmemory ;;
            4) a="$(ts_prompt_choice mcp 'Cursor Headroom mode:' '' 'mcp|MCP only|subscription models stay direct' 'byok|BYOK proxy|provider API key and separate billing' 'off|off')"; agents_config headroom cursor "$a"; continue ;;
            q|Q|'') return ;;
            *) echo '?'; continue ;;
        esac
        a="$(ts_prompt_choice status "$tool:" '' 'status|status' 'on|enable / repair' 'off|disable, preserve data' 'uninstall|remove terminal-stack-owned client pieces')"
        agents_config "$tool" "$a"
    done
}

show() {
    echo "terminal-stack config:"
    echo "  leader     : $(cur leaderChord ctrl-space)   (WezTerm: $(cur leaderMods CTRL)+$(cur leaderKey phys:Space))"
    echo "  theme      : $(cur themeMode dark)   (baked palette: $(cur resolvedTheme dark))"
    echo "  tmux       : $(cur tmuxPrefix ctrl-b)   (prefix: $(cur tmuxPrefixResolved C-b))"
    echo "  apps       : $(curapps)"
    echo "  wezmux     : $(ts_wez_mux_get)   (ts-mux on|off|status)"
    echo "  wezrestore : $(ts_wez_restore_get)   (ts-config restore on|off)"
    echo "  wezterm    : $(ts_wezterm_channel)$(_ts_cfg_wezterm_built)   (ts-config wezterm)"
    echo "  headroom   : $(ts_agent_get headroomEnabled)   (Cursor: $(ts_agent_get headroomCursorMode))"
    echo "  caveman    : $(ts_agent_get cavemanEnabled)"
    echo "  agentmemory: $(ts_agent_get agentmemoryEnabled)"
}

menu() {
    while true; do
        echo
        show
        echo
        echo "  1) leader key   2) theme   3) tmux prefix   4) apps   5) re-apply   6) Claude TTS   7) WezTerm mux   8) session restore   9) coding agents   t) WezTerm build   w) re-run wizard   q) quit"
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
            9) agents_menu ;;
            t|T) run_wezterm status ;;
            w|W) run_wizard ;;
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
    wezterm)
        shift
        run_wezterm "$@" ;;
    wizard|reconfigure) run_wizard ;;
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
    agents)
        shift
        agents_config "$@" ;;
    -h|--help|help)
        sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
        echo "  tts show|on|off|test|reset|engine|message|voice|..."
        echo "  mux status|on|off|list|kill|restart|reset  (see: ts-mux -h)"
        echo "  restore on|off   reopen the last WezTerm session at startup"
        echo "  agents [show|<headroom|caveman|agentmemory> on|off|status|repair|uninstall]"
        echo "  wezterm [status|changes|install <stable|nightly>|upgrade]  (see: ts-wezterm -h)"
        echo "  wizard           re-run the whole install questionnaire (TS_ASSUME_YES=1 to accept defaults)"
        echo "  agents headroom cursor <mcp|byok|off> | dashboard"
        ;;
    *) echo "ts-config: unknown command '$1' (try: show, leader, theme, tmux, apps, tts, mux, restore, agents, wezterm, wizard)" >&2; exit 2 ;;
esac
