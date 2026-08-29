#!/usr/bin/env bash
# ts-config.sh — view/change the saved terminal-stack config (leader key, theme,
# tmux prefix, apps, WezTerm mux + session restore) and re-apply. Driven by the
# `tstack config` shell wrapper (zsh) and runnable standalone. On Windows the pwsh
# tstack config is the counterpart.
#
# Usage:
#   tstack config                 interactive menu
#   tstack config show            print the current config
#   tstack config leader <chord>  e.g. ctrl-space, ctrl-a, alt-x
#   tstack config theme  <mode>   dark | light | follow
#   tstack config tmux   <chord>  tmux prefix, e.g. ctrl-a
#   tstack config apps [recommended|all|none|id,id,...]   (no arg → interactive picker)
#   tstack config mux [on|off|...]  hand-off to tstack mux (WezTerm multiplexer domain)
#   tstack config restore <on|off>  reopen the last WezTerm session at startup
#   tstack config atuin   <on|off>  atuin shell history (owns Ctrl+R when on)
#   tstack config ghostty [on|off|status|diff]   managed Ghostty config (macOS)
#   tstack config agents [show|<tool> on|off|status|repair|uninstall]
#   tstack config wezterm [status|changes|install <chan>|upgrade]
#   tstack config wizard          re-run the whole install questionnaire
#
# Config lives in chezmoi [data] (~/.config/chezmoi/chezmoi.toml); changes are
# persisted with ts_save_config, then `chezmoi apply` re-renders every file.
set -euo pipefail

CZ="${TERMINAL_STACK_CHEZMOI:-}"
if [ -z "$CZ" ]; then
    if [ -x "$HOME/.local/bin/chezmoi" ]; then CZ="$HOME/.local/bin/chezmoi"
    elif command -v chezmoi >/dev/null 2>&1; then CZ="$(command -v chezmoi)"
    else echo "tstack config: chezmoi not found on PATH." >&2; exit 1; fi
fi
SRC="${TERMINAL_STACK_DIR:-$("$CZ" source-path 2>/dev/null || true)}"
if [ ! -d "$SRC/bootstrap" ]; then
    echo "tstack config: cannot locate the terminal-stack clone (set TERMINAL_STACK_DIR)." >&2
    exit 1
fi
# shellcheck source=_config.sh
. "$SRC/bootstrap/_config.sh"
# shellcheck source=_wizard.sh
. "$SRC/bootstrap/_wizard.sh"
# _detect.sh supplies ts_is_headless, which run_wizard needs to decide whether to
# ask the terminal-emulator question. It is side-effect free and documented as
# "sourced after _config.sh and _wizard.sh", which is exactly here.
# shellcheck source=_detect.sh
. "$SRC/bootstrap/_detect.sh"

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
                echo "tstack config: no supported package manager; recorded selection only."
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
    # Ghostty is a macOS row in the picker, so this is the only arm it needs.
    case " $sel " in *" ghostty "*)
        if [ "$(uname -s)" = Darwin ] && command -v brew >/dev/null 2>&1; then
            brew list --cask ghostty >/dev/null 2>&1 || brew install --cask ghostty || true
        fi ;;
    esac
}

# Re-run the whole questionnaire, not just one answer. `tstack config apps` re-asks
# the apps question alone; this replays every prompt the installer asks and
# persists all of it — which also sidesteps ts_save_config's positional trap,
# since every value is being re-stated anyway. TS_ASSUME_YES=1 makes it
# non-interactive, and the per-question TS_* vars still skip individual prompts.
run_wizard() {
    # Ask about the terminal emulator, same rule as the bootstraps: a GUI host
    # gets the question, a headless one does not. Without this `tstack config wizard`
    # never asked, TS_WIZ_TERMINALS came back empty, and it reported
    # "Terminal emulator: none selected" — so a re-run could not switch channel,
    # which is precisely what someone runs the wizard again to do.
    ts_is_headless || TS_WIZ_ASK_TERMINALS=1
    ts_wizard_collect || { echo "tstack config: wizard cancelled; nothing changed."; return 0; }

    # Save BEFORE installing. An install that fails must never cost the user the
    # answers they just gave — the same ordering the bootstraps now use.
    ts_save_config "${TS_WIZ_LEADER:-ctrl-space}" "${TS_WIZ_THEME:-dark}" "${TS_WIZ_TMUX:-ctrl-b}" ${TS_WIZ_APPS:-}
    ts_agents_save_config "${TS_WIZ_HEADROOM:-off}" "${TS_WIZ_HEADROOM_CURSOR:-mcp}" "${TS_WIZ_CAVEMAN:-off}" "${TS_WIZ_AGENTMEMORY:-off}"
    # The memory answer itself. Stored through ts_memory_apply, not through
    # ts_agents_save_config, because that helper writes only independent toggles
    # and this one also DERIVES agentmemoryEnabled. Without this line the wizard
    # asked the question and threw the answer away.
    ts_memory_apply "${TS_WIZ_MEMORY_BACKEND:-agentmemory}"
    ts_wez_mux_set "${TS_WIZ_WEZ_MUX:-off}"
    ts_wez_restore_set "${TS_WIZ_WEZ_RESTORE:-off}"
    ts_atuin_set "${TS_WIZ_ATUIN:-off}"
    ts_starship_set "${TS_WIZ_STARSHIP:-terminal-stack}" || true
    ts_cc_tts_apply_wizard_choice "${TS_WIZ_CC_TTS:-off}" off "${TS_WIZ_CC_TTS_MESSAGE:-}"

    install_apps "${TS_WIZ_APPS:-}" || ts_note_failure "optional apps" "retry: tstack config apps"
    # The pwsh $runWizard has always installed the chosen emulator; this side
    # never did, so a `tstack config wizard` that picked WezTerm silently did nothing.
    install_terminals "${TS_WIZ_TERMINALS:-}" || ts_note_failure "terminal emulator" "retry: tstack config wezterm install <channel>"
    ts_report_installed_apps "${TS_WIZ_APPS:-}"
    ts_report_failures
    finish
}

# Reopening the last WezTerm session at startup. Stored on its own like the mux
# key, so flipping it need not re-state every other choice.
set_restore() { ts_wez_restore_set "$1"; finish; }

# atuin owns Ctrl+R when on. Stored on its own like the mux/restore keys.
# `finish` re-applies, which is what re-renders the sourced zsh fragment --
# the setting alone changes nothing until chezmoi rewrites atuin.zsh.
set_atuin() { ts_atuin_set "$1"; finish; }

# ── Ghostty ───────────────────────────────────────────────────────────────────
# The CLI tool picker. Sources the wizard's answer file rather than capturing
# stdout: the menu goes to the terminal and only the answers go to the file, so
# there is no $( ) boundary for a rendered menu to leak into.
run_wizard_apps() {
    local spec="${1:-}" wiz rc=0
    wiz="$(mktemp "${TMPDIR:-/tmp}/tsapps.XXXXXX")" || return 1
    if [ -n "$spec" ]; then export TS_APPS="$spec"; fi
    if run_py wizard --only apps --emit sh --out "$wiz"; then
        # shellcheck disable=SC1090
        . "$wiz"
        rm -f "$wiz"
        printf '%s\n' "${TS_WIZ_APPS:-}"
    else
        rc=$?
        rm -f "$wiz"
        return "$rc"
    fi
}

# Every hand-off to the Python implementation goes through here. ts_python
# returns 1 and prints nothing when there is no interpreter; unguarded,
# `"$(ts_python)" ...` then expands to an empty command word and `set -e` kills
# the script with a bare `: command not found`.
run_py() {
    local _py
    _py="$(ts_python)" || {
        echo "tstack config: python3 (3.10+) is required for this command." >&2
        return 1
    }
    TERMINAL_STACK_DIR="$SRC" TERMINAL_STACK_CHEZMOI="$CZ" \
        "$_py" "$SRC/tstack/main.py" "$@"
}

# Ghostty. One implementation in tstack/ghostty.py, reached the same way mux and
# wezterm are: this used to be ~160 lines here, ~90 more in $PROFILE, and a third
# copy of the themeMode -> theme mapping in each. macOS only -- the command says
# so itself on any other platform.
run_ghostty() {
    run_py ghostty "$@"
}

# The mux has its own verbs (kill/restart/reset), so tstack config just hands off.
run_mux() {
    run_py mux "$@"
}

# WezTerm build info / channel switching. Hand-off like run_mux: the logic lives
# in tstack/commands/wezterm.py so `tstack wezterm` works standalone too.
run_wezterm() {
    run_py wezterm "$@"
}

# ── memory backend ───────────────────────────────────────────────────────────
# One slot, three values, and the derived state moves with it. See
# docs/decisions.md, "Why only one memory backend runs".
memory_show() {
    local b; b="$(ts_agent_get memoryBackend)"
    echo "memory backend: $b"
    case "$b" in
        agentmemory) echo "  AgentMemory remembers (3111), Headroom compresses (8787)." ;;
        headroom)    echo "  Headroom remembers and compresses; AgentMemory is not installed." ;;
        none)        echo "  No memory. Headroom still compresses if it is enabled." ;;
    esac
    echo "  agentmemory wiring: $(ts_agent_get agentmemoryEnabled)   headroom: $(ts_agent_get headroomEnabled)"
    local env_file spec
    env_file="$(ts_stack_env_file headroom 2>/dev/null || true)"
    if [ -n "$env_file" ] && [ -f "$env_file" ]; then
        spec="$(ts_env_value "$env_file" COMPOSE_FILE 2>/dev/null || true)"
        echo "  headroom COMPOSE_FILE: ${spec:-docker-compose.yml}"
        # Drift is worth naming rather than silently correcting: a hand-edited
        # COMPOSE_FILE is somebody trying to do something, and quietly undoing it
        # is worse than saying it disagrees.
        if [ "${spec:-docker-compose.yml}" != "$(ts_memory_compose_spec "$b")" ]; then
            echo "  $WARN COMPOSE_FILE does not match the backend — fix: tstack config memory $b"
        fi
    fi
}

memory_set() {
    local backend="$1" before
    before="$(ts_agent_get memoryBackend)"
    ts_memory_apply "$backend" || return 1
    echo "saved: memoryBackend = $backend"

    # The agent wiring is what actually captures, so it moves with the setting.
    # tstack agents refuses to persist a state it cannot verify, which is why this
    # runs it rather than only writing the key.
    if [ "$backend" = agentmemory ]; then
        run_agent_adapter agentmemory on || echo "  $WARN AgentMemory wiring failed; retry: tstack config agents agentmemory repair" >&2
    elif [ "$before" = agentmemory ]; then
        run_agent_adapter agentmemory off || true
        echo "  AgentMemory hooks removed from Claude/Codex/Cursor."
    fi

    # Restart rather than print the command: the setting and the running state
    # must not disagree, and a headroom that is still running the old compose
    # file is exactly the silent mismatch this whole change exists to remove.
    if command -v docker >/dev/null 2>&1; then
        echo "  restarting headroom so the change takes effect..."
        run_py services restart headroom || \
            echo "  $WARN headroom restart failed — run: tstack services restart headroom" >&2
    else
        echo "  no docker on PATH; apply it later with: tstack services restart headroom"
    fi
}

agents_show() {
    echo "coding agents (user-global on this computer):"
    echo "  headroom   : $(ts_agent_get headroomEnabled)   (Cursor: $(ts_agent_get headroomCursorMode))"
    echo "  caveman    : $(ts_agent_get cavemanEnabled)"
    echo "  agentmemory: $(ts_agent_get agentmemoryEnabled)   (memory backend: $(ts_agent_get memoryBackend))"
}

run_agent_adapter() {
    local tool="$1" action="$2" cursor_mode="${3:-$(ts_agent_get headroomCursorMode)}"
    run_py agents "$tool" "$action" "$cursor_mode"
}

agents_set() {
    local tool="$1" action="$2" key=""
    case "$tool" in
        headroom) key=headroomEnabled ;;
        caveman) key=cavemanEnabled ;;
        agentmemory) key=agentmemoryEnabled ;;
        # No tstack agents adapter: this one only records intent, and tstack services acts
        # on it. status defers to tstack services, which is the thing that knows.
        playwright) key=playwrightEnabled ;;
        *) echo "usage: tstack config agents <headroom|caveman|agentmemory|playwright> on|off|status|repair|uninstall" >&2; return 2 ;;
    esac
    # AgentMemory is DERIVED from memoryBackend, so turning it on directly while
    # the backend is something else would create a two-memory-system machine --
    # the exact combination the install wizard is built to make unreachable.
    if [ "$tool" = agentmemory ] && [ "$action" = on ]; then
        local backend; backend="$(ts_agent_get memoryBackend)"
        if [ "$backend" != agentmemory ]; then
            echo "$WARN memoryBackend is '$backend', so AgentMemory is not this machine's memory system." >&2
            echo "      Only one runs. To switch:  tstack config memory agentmemory" >&2
            return 2
        fi
    fi
    case "$action" in
        on)
            if [ "$tool" = playwright ]; then ts_agent_set "$key" on
            else run_agent_adapter "$tool" on && ts_agent_set "$key" on; fi ;;
        off)
            if [ "$tool" = playwright ]; then ts_agent_set "$key" off
            else run_agent_adapter "$tool" off; ts_agent_set "$key" off; fi ;;
        uninstall) run_agent_adapter "$tool" uninstall; ts_agent_set "$key" off ;;
        status|repair)
            if [ "$tool" = playwright ]; then echo "  playwright: $(ts_agent_get playwrightEnabled) — run 'tstack services status' for the container"
            else run_agent_adapter "$tool" "$action"; fi ;;
        *) echo "usage: tstack config agents $tool on|off|status|repair|uninstall" >&2; return 2 ;;
    esac
}

agents_config() {
    local sub="${1:-}" action="${2:-}" extra="${3:-}"
    case "$sub" in
        ''|show) agents_show ;;
        headroom)
            if [ "$action" = dashboard ]; then run_agent_adapter headroom dashboard; return; fi
            if [ "$action" = cursor ]; then
                case "$extra" in mcp|byok|off) ;; *) echo "usage: tstack config agents headroom cursor <mcp|byok|off>" >&2; return 2;; esac
                ts_agent_set headroomCursorMode "$extra"
                [ "$(ts_agent_get headroomEnabled)" = on ] && run_agent_adapter headroom repair "$extra" || true
                agents_show
                return
            fi
            agents_set headroom "${action:-status}" ;;
        caveman|agentmemory) agents_set "$sub" "${action:-status}" ;;
        *) echo "tstack config agents: unknown tool '$sub'" >&2; return 2 ;;
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
    echo "  wezmux     : $(ts_wez_mux_get)   (tstack mux on|off|status)"
    echo "  wezrestore : $(ts_wez_restore_get)   (tstack config restore on|off)"
    echo "  atuin      : $(ts_atuin_get)   (tstack config atuin on|off)"
    # Not Darwin-gated. tstack/commands/config.py dropped the same gate because a
    # WSL user's Ghostty setting was invisible in `show` while `tstack config
    # ghostty` still worked -- and this menu offers `g) ghostty` on every
    # platform, so gating only the display let you toggle a setting you could
    # not see. ts_ghostty_get returns a sane value everywhere.
    echo "  ghostty    : $(ts_ghostty_get)   (tstack config ghostty on|off)"
    echo "  wezterm    : $(ts_wezterm_channel)$(_ts_cfg_wezterm_built)   (tstack config wezterm)"
    echo "  headroom   : $(ts_agent_get headroomEnabled)   (Cursor: $(ts_agent_get headroomCursorMode))"
    echo "  caveman    : $(ts_agent_get cavemanEnabled)"
    echo "  agentmemory: $(ts_agent_get agentmemoryEnabled)"
}

# ── the menu's own prompts ──
# The install questionnaire is Python now, so its per-question bash functions are
# gone -- but this menu is not the questionnaire. It edits ONE setting at a time
# and re-applies, which is the whole reason to open it rather than re-run the
# wizard. These ask the same questions with the same options, and default to
# whatever is currently SAVED: a menu's default is the value you already have,
# not the value a fresh install would pick.
menu_leader() {
    ts_prompt_choice "$(cur leaderChord ctrl-space)" \
        'Leader key (WezTerm) - prefix for pane / tab / workspace commands:' '' \
        'ctrl-space|Ctrl+Space' 'ctrl-a|Ctrl+A|tmux muscle memory' \
        'ctrl-b|Ctrl+B|tmux default' 'alt-space|Alt+Space'
}

menu_theme() {
    ts_prompt_choice "$(cur themeMode dark)" 'Theme:' '' \
        'dark|dark|Catppuccin Mocha' 'light|light|VS Code Light Modern' \
        'follow|follow OS appearance|WezTerm switches live'
}

# usage: menu_on_off <settings-key> <title> <off-note> <on-note>
menu_on_off() {
    ts_prompt_choice "$(cur "$1" off)" "$2" '' "off|off|$3" "on|on|$4"
}

menu() {
    while true; do
        echo
        show
        echo
        echo "  1) leader key   2) theme   3) tmux prefix   4) apps   5) re-apply   6) Claude TTS   7) WezTerm mux   8) session restore   9) coding agents   a) atuin   g) ghostty   t) WezTerm build   w) re-run wizard   q) quit"
        local c; c="$(ts_tty_prompt 'Choose: ')"
        case "$c" in
            1) set_leader "$(menu_leader)" ;;
            2) set_theme  "$(menu_theme)" ;;
            3) local t; t="$(ts_tty_prompt 'tmux prefix chord (e.g. ctrl-a) [ctrl-b]: ')"; set_tmux "${t:-ctrl-b}" ;;
            4) local sel; sel="$(run_wizard_apps '')" && set_apps "$sel" ;;
            5) finish ;;
            6) ts_config_tts show; echo; ts_config_tts_menu ;;
            7) run_mux status ;;
            8) set_restore "$(menu_on_off weztermRestore 'WezTerm session restore (reopen the last session at startup):' 'start clean every time' 'reopen the last session')" ;;
            9) agents_menu ;;
            a|A) set_atuin "$(menu_on_off atuinEnabled 'atuin shell history (replaces Ctrl+R):' 'keep fzf on Ctrl+R' 'atuin owns Ctrl+R')" ;;
            g|G) run_ghostty status ;;
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
    leader) [ -n "${2:-}" ] || { echo "usage: tstack config leader <chord>" >&2; exit 2; }; set_leader "$2" ;;
    theme)  [ -n "${2:-}" ] || { echo "usage: tstack config theme <dark|light|follow>" >&2; exit 2; }; set_theme "$2" ;;
    tmux)   [ -n "${2:-}" ] || { echo "usage: tstack config tmux <chord>" >&2; exit 2; }; set_tmux "$2" ;;
    apps)
        # The picker is tstack/wizard/ now, like the rest of the questionnaire.
        # A spec on the command line is passed through as TS_APPS, which is the
        # same escape hatch a scripted install uses -- one expansion, not two.
        _apps_sel="$(run_wizard_apps "${2:-}")" || exit $?
        set_apps "$_apps_sel" ;;
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
            echo "usage: tstack config restore <on|off>" >&2; exit 2 ;; esac
        set_restore "$2" ;;
    atuin)
        case "${2:-}" in on|off) ;; *)
            echo "usage: tstack config atuin <on|off>" >&2; exit 2 ;; esac
        set_atuin "$2" ;;
    prompt)
        # prompt_status/_list/_preview/_set were deleted with the ghostty port and
        # never replaced, so every one of these was a `command not found` exit 127.
        # tstack/commands/config.py owns the verb; hand off like ghostty/mux/wezterm.
        shift
        run_py config prompt "$@" ;;
    ghostty)
        shift
        run_ghostty "$@" ;;
    memory)
        case "${2:-status}" in
            agentmemory|headroom|none) memory_set "$2" ;;
            status|show) memory_show ;;
            *) echo "usage: tstack config memory [agentmemory|headroom|none|status]" >&2; exit 2 ;;
        esac ;;
    agents)
        shift
        agents_config "$@" ;;
    -h|--help|help)
        sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'
        echo "  tts show|on|off|test|reset|engine|message|voice|..."
        echo "  mux status|on|off|list|kill|restart|reset  (see: tstack mux -h)"
        echo "  restore on|off   reopen the last WezTerm session at startup"
        echo "  atuin on|off     atuin shell history; when on it owns Ctrl+R (fzf keeps Ctrl+T/Alt+C)"
        echo "  prompt [status|list|<name>|preview <name>]   which Starship prompt; list renders every option"
        echo "  ghostty [on|off|status|diff]   managed Ghostty config (macOS/Windows; off restores your backup)"
        echo "  memory [agentmemory|headroom|none|status]   which memory system runs — only ever one"
        echo "  agents [show|<headroom|caveman|agentmemory> on|off|status|repair|uninstall]"
        echo "  wezterm [status|changes|install <stable|nightly>|upgrade]  (see: tstack wezterm -h)"
        echo "  wizard           re-run the whole install questionnaire (TS_ASSUME_YES=1 to accept defaults)"
        echo "  agents headroom cursor <mcp|byok|off> | dashboard"
        ;;
    *) echo "tstack config: unknown command '$1' (try: show, get, set, leader, theme, tmux, apps, tts, mux, restore, atuin, prompt, ghostty, memory, agents, wezterm, wizard)" >&2; exit 2 ;;
esac
