#!/usr/bin/env bash
# _wizard.sh — interactive install wizard (POSIX/Debian/macOS side).
# Sourced by _common-debian.sh (WSL/Linux) and mac-bootstrap.sh. Depends on the
# app-catalog vars + helpers from _config.sh (source that first).
#
# ts_wizard_collect gathers the user's choices into TS_WIZ_* globals WITHOUT
# touching chezmoi (chezmoi.toml may not exist yet at this point in the bootstrap).
# The bootstrap installs the selected apps, writes chezmoi.toml, then persists the
# choices with ts_save_config (from _config.sh). Env vars skip each prompt:
#   TS_LEADER=ctrl-a   TS_THEME=dark|light|follow   TS_TMUX=ctrl-b
#   TS_APPS=recommended|all|none|id,id,...   (none or menu option 3 = skip all optional apps)
#   TS_CC_TTS=on|off|skip   Claude Code Kokoro TTS at install
#
# This file is sourced, not executed. Do not `exit`; return non-zero instead.

# Prompt on the controlling terminal: under curl|bash, stdin is the script pipe,
# so read from /dev/tty. Returns "" when there is no terminal (CI).
ts_tty_prompt() {
    local answer=""
    # Read with readline (-e) so Backspace and the arrow keys edit the line
    # instead of inserting raw control codes (^?, ^[[D); -p shows the prompt.
    # Skip cleanly when there is no controlling terminal (CI / non-interactive).
    if { true > /dev/tty; } 2>/dev/null; then
        IFS= read -e -r -p "$1" answer < /dev/tty || answer=""
    fi
    echo "$answer"
}

ts_prompt_leader() {
    {
        printf '\nLeader key (WezTerm) — prefix for pane / tab / workspace commands:\n'
        printf '  1) Ctrl+Space  (recommended)\n'
        printf '  2) Ctrl+A\n'
        printf '  3) Ctrl+B\n'
        printf '  4) custom (type a chord like ctrl-x or alt-space)\n'
    } > /dev/tty 2>/dev/null
    local ans; ans="$(ts_tty_prompt 'Choose [1]: ')"
    case "$ans" in
        2) echo ctrl-a ;;
        3) echo ctrl-b ;;
        4) local c; c="$(ts_tty_prompt 'Enter chord (mod-key, e.g. ctrl-x): ')"; echo "${c:-ctrl-space}" ;;
        *) echo ctrl-space ;;
    esac
}

ts_prompt_theme() {
    {
        printf '\nTheme:\n'
        printf '  1) dark   (Catppuccin Mocha, recommended)\n'
        printf '  2) light  (VS Code Light Modern)\n'
        printf '  3) follow OS appearance\n'
    } > /dev/tty 2>/dev/null
    local ans; ans="$(ts_tty_prompt 'Choose [1]: ')"
    case "$ans" in
        2) echo light ;;
        3) echo follow ;;
        *) echo dark ;;
    esac
}

# Expand a TS_APPS env value (recommended|all|none|csv) to a space list.
ts_expand_apps() {
    case "$1" in
        recommended) echo "$TS_APPS_RECOMMENDED" ;;
        all)         echo "$TS_APPS_ALL" ;;
        none|"")     echo "" ;;
        *)           echo "$1" | tr ',' ' ' ;;
    esac
}

ts_pick_apps() {
    local selected="" id def a
    for id in $TS_APPS_ALL; do
        case " $TS_APPS_RECOMMENDED " in *" $id "*) def=Y ;; *) def=n ;; esac
        a="$(ts_tty_prompt "  install $id — $(ts_app_desc "$id")? [$def]: ")"
        a="${a:-$def}"
        case "$a" in y|Y|yes|YES) selected="$selected $id" ;; esac
    done
    echo "${selected# }"
}

ts_prompt_apps() {
    {
        printf '\nOptional CLI tools (WezTerm, font, Starship, chezmoi, zsh — always installed):\n'
        ts_apps_install_note
        printf '  1) Install recommended set:\n     %s\n' "$TS_APPS_RECOMMENDED"
        printf '  2) Customize (choose each)\n'
        printf '  3) Skip all optional apps\n'
    } > /dev/tty 2>/dev/null
    local ans; ans="$(ts_tty_prompt 'Choose [1]: ')"
    case "$ans" in
        2) ts_pick_apps ;;
        3) echo "" ;;
        *) echo "$TS_APPS_RECOMMENDED" ;;
    esac
}

# Gather choices into TS_WIZ_* (no chezmoi writes here).
ts_wizard_collect() {
    # The leader key only matters for WezTerm (a GUI app). On a headless server
    # there's no WezTerm to drive, so skip the question and keep the default.
    if [ -n "${TS_LEADER:-}" ]; then TS_WIZ_LEADER="$TS_LEADER"
    elif command -v ts_is_headless >/dev/null 2>&1 && ts_is_headless; then TS_WIZ_LEADER=ctrl-space
    else TS_WIZ_LEADER="$(ts_prompt_leader)"; fi

    if [ -n "${TS_THEME:-}" ]; then TS_WIZ_THEME="$TS_THEME"
    else TS_WIZ_THEME="$(ts_prompt_theme)"; fi

    if [ -n "${TS_APPS:-}" ]; then TS_WIZ_APPS="$(ts_expand_apps "$TS_APPS")"
    else TS_WIZ_APPS="$(ts_prompt_apps)"; fi

    TS_WIZ_TMUX="${TS_TMUX:-ctrl-b}"

    if [ -n "${TS_CC_TTS:-}" ]; then TS_WIZ_CC_TTS="$TS_CC_TTS"
    else TS_WIZ_CC_TTS="$(ts_prompt_cc_tts)"; fi

    export TS_WIZ_LEADER TS_WIZ_THEME TS_WIZ_APPS TS_WIZ_TMUX TS_WIZ_CC_TTS
    echo "$INFO Config: leader=$TS_WIZ_LEADER theme=$TS_WIZ_THEME tmux-prefix=$TS_WIZ_TMUX cc-tts=${TS_WIZ_CC_TTS:-off}"
    echo "$INFO Apps: ${TS_WIZ_APPS:-<none>}"
}
