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
#   TS_APPS=recommended|all|none|id,id,...   (none or "skip all" = no optional apps)
#   TS_WEZTERM=nightly|stable|skip           (macOS only; WSL/Linux never install it)
#   TS_CC_TTS=on|off|skip   Claude Code Kokoro TTS at install
#   TS_ASSUME_YES=1         skip the review prompt (answers still come from the above)
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

# One definition of "is there a human here" for every prompt in the wizard, so
# headless behaviour can't drift between questions. pwsh twin: _config.ps1
# Test-TsInteractive.
ts_is_interactive() { { true > /dev/tty; } 2>/dev/null; }

# The menu prompt every wizard question uses. Marks the default and says how to
# take it, accepts the option's name as well as its number, and RE-PROMPTS on
# anything else — the old `case "$ans" in *) default ;; esac` silently selected
# option 1 for a typo, a stray 'y', or a fat-fingered '9', which is the opposite
# of what a default is for.
#
# usage: ts_prompt_choice <default-key> <title> <intro-or-empty> "key|label|note"...
# Writes the menu to /dev/tty (the caller captures stdout for the chosen key).
# Twin of bootstrap/_config.ps1 Read-TsChoice — keep the rendered output identical.
ts_prompt_choice() {
    local def="$1" title="$2" intro="$3"; shift 3
    local n=0 opt rest key label note mark suffix ans i lower
    {
        printf '\n%s\n' "$title"
        [ -n "$intro" ] && printf '%s\n' "$intro"
        for opt in "$@"; do
            n=$((n + 1))
            key="${opt%%|*}"; rest="${opt#*|}"
            label="${rest%%|*}"; note="${rest#*|}"
            [ "$note" = "$label" ] && note=""
            mark=" "; suffix=""
            [ -n "$note" ] && suffix="  ($note)"
            if [ "$key" = "$def" ]; then mark=">"; suffix="$suffix  [default — press Enter]"; fi
            printf ' %s  %d) %s%s\n' "$mark" "$n" "$label" "$suffix"
        done
    } > /dev/tty 2>/dev/null
    n=0; for opt in "$@"; do n=$((n + 1)); done

    if ! ts_is_interactive; then
        printf 'Choose [1-%d, Enter=default]: (non-interactive — taking the default)\n' "$n" \
            > /dev/tty 2>/dev/null
        printf '%s\n' "$def"
        return 0
    fi
    local tries=0
    while [ "$tries" -lt 3 ]; do
        tries=$((tries + 1))
        ans="$(ts_tty_prompt "Choose [1-$n, Enter=default]: ")"
        ans="$(printf '%s' "$ans" | tr -d '[:space:]')"
        [ -z "$ans" ] && { printf '%s\n' "$def"; return 0; }
        case "$ans" in
            ''|*[!0-9]*) ;;
            *)  if [ "$ans" -ge 1 ] && [ "$ans" -le "$n" ]; then
                    i=0
                    for opt in "$@"; do
                        i=$((i + 1))
                        [ "$i" = "$ans" ] && { printf '%s\n' "${opt%%|*}"; return 0; }
                    done
                fi ;;
        esac
        lower="$(printf '%s' "$ans" | tr 'A-Z' 'a-z')"
        for opt in "$@"; do
            key="${opt%%|*}"
            [ "$lower" = "$(printf '%s' "$key" | tr 'A-Z' 'a-z')" ] \
                && { printf '%s\n' "$key"; return 0; }
        done
        printf "  '%s' is not one of the choices — enter 1-%s, a name, or press Enter for the default.\n" \
            "$ans" "$n" > /dev/tty 2>/dev/null
    done
    printf '  three invalid answers — taking the default.\n' > /dev/tty 2>/dev/null
    printf '%s\n' "$def"
}

ts_prompt_leader() {
    local c
    c="$(ts_prompt_choice ctrl-space \
        'Leader key (WezTerm) — prefix for pane / tab / workspace commands:' '' \
        'ctrl-space|Ctrl+Space' \
        'ctrl-a|Ctrl+A|tmux muscle memory' \
        'ctrl-b|Ctrl+B|tmux default' \
        'alt-space|Alt+Space' \
        'custom|custom chord')"
    [ "$c" != custom ] && { printf '%s\n' "$c"; return 0; }
    local chord; chord="$(ts_tty_prompt 'Enter chord (mod-key, e.g. ctrl-x or alt-space): ')"
    printf '%s\n' "${chord:-ctrl-space}"
}

ts_prompt_theme() {
    ts_prompt_choice dark 'Theme:' '' \
        'dark|dark|Catppuccin Mocha' \
        'light|light|VS Code Light Modern' \
        'follow|follow OS appearance|WezTerm switches live'
}

# WezTerm used to be an unconditional cask install on macOS. It isn't universal
# (iTerm/Ghostty users, machines that already have it), so it is a choice now.
# WSL and native Linux never install WezTerm — the GUI lives on the host.
ts_prompt_wezterm() {
    if [ -n "${TS_WEZTERM:-}" ]; then printf '%s\n' "$TS_WEZTERM"; return 0; fi
    if command -v wezterm >/dev/null 2>&1; then
        ts_prompt_choice skip 'Terminal emulator (WezTerm):' \
            "  Found: $(command -v wezterm)" \
            'skip|keep the installed WezTerm' \
            'nightly|reinstall/upgrade to nightly|what this config targets' \
            'stable|reinstall/upgrade to stable'
    else
        ts_prompt_choice nightly 'Terminal emulator (WezTerm):' '' \
            'nightly|WezTerm nightly|what this config targets' \
            'stable|WezTerm stable|brew cask wezterm' \
            'skip|skip — I use a different terminal'
    fi
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

# Customize: a single comma-separated line, or Enter to walk the list one by
# one. Fourteen consecutive Y/n prompts is a lot to sit through when you already
# know you want three of them.
ts_pick_apps() {
    local selected="" id def a csv want unknown=""
    printf '\n  Available: %s\n' "$TS_APPS_ALL" > /dev/tty 2>/dev/null
    csv="$(ts_tty_prompt '  Type a comma-separated list, or Enter to be asked one at a time: ')"
    if [ -n "$csv" ]; then
        want=" $(printf '%s' "$csv" | tr ',' ' ' | tr 'A-Z' 'a-z') "
        for id in $TS_APPS_ALL; do
            case "$want" in *" $id "*) selected="$selected $id" ;; esac
        done
        for id in $(printf '%s' "$csv" | tr ',' ' '); do
            case " $TS_APPS_ALL " in *" $id "*) ;; *) unknown="$unknown $id" ;; esac
        done
        [ -n "$unknown" ] && printf '  not in the catalog, ignored:%s\n' "$unknown" > /dev/tty 2>/dev/null
        printf '  Selected: %s\n' "${selected:- <none>}" > /dev/tty 2>/dev/null
        echo "${selected# }"
        return 0
    fi
    for id in $TS_APPS_ALL; do
        case " $TS_APPS_RECOMMENDED " in *" $id "*) def=Y ;; *) def=n ;; esac
        a="$(ts_tty_prompt "  install $id — $(ts_app_desc "$id")? [$def]: ")"
        a="${a:-$def}"
        case "$a" in y|Y|yes|YES) selected="$selected $id" ;; esac
    done
    echo "${selected# }"
}

ts_prompt_apps() {
    local intro choice
    # ts_apps_install_note prints its own trailing blank line; strip it so the
    # menu stays a single block.
    intro="$(ts_apps_install_note 2>/dev/null || true)"
    intro="${intro:+$intro
}  recommended: $TS_APPS_RECOMMENDED
  also available: $TS_APPS_OPTIONAL"
    choice="$(ts_prompt_choice recommended \
        'Optional CLI tools (font, Starship, chezmoi, zsh — always installed):' "$intro" \
        'recommended|install the recommended set' \
        "all|install everything|recommended + $(echo "$TS_APPS_OPTIONAL" | tr ' ' ',' | sed 's/,/, /g')" \
        'customize|choose which ones' \
        'none|skip all optional apps')"
    case "$choice" in
        all)       echo "$TS_APPS_ALL" ;;
        none)      echo "" ;;
        customize) ts_pick_apps ;;
        *)         echo "$TS_APPS_RECOMMENDED" ;;
    esac
}

# Render the collected answers for review before anything is installed.
ts_wizard_review() {
    local theme_label
    case "$TS_WIZ_THEME" in
        dark)   theme_label='dark (Catppuccin Mocha)' ;;
        light)  theme_label='light (VS Code Light Modern)' ;;
        follow) theme_label='follow OS appearance' ;;
        *)      theme_label="$TS_WIZ_THEME" ;;
    esac
    printf '\n%s Review\n' "$INFO"
    printf '    Leader       %s\n' "$TS_WIZ_LEADER"
    printf '    Theme        %s\n' "$theme_label"
    [ -n "${TS_WIZ_WEZTERM:-}" ] && printf '    WezTerm      %s\n' "$TS_WIZ_WEZTERM"
    printf '    tmux prefix  %s\n' "$TS_WIZ_TMUX"
    printf '    Apps         %s\n' "${TS_WIZ_APPS:-<none>}"
    printf '    Claude TTS   %s\n' "${TS_WIZ_CC_TTS:-off}"
}

# Ask each question once. Env vars skip their prompt individually.
#
# TS_WIZ_ASKED counts the questions a human was actually shown. It is tallied
# here, in the parent shell, and NOT inside ts_prompt_choice — every prompt is
# called through $(...), so an increment there would be discarded with the
# subshell. ts_wizard_collect uses the tally to decide whether reviewing makes
# sense: a run whose every answer came from TS_* env vars has nothing to review,
# and prompting anyway would block forever when /dev/tty exists but nobody is
# watching it (CI, a detached install).
ts_wizard_ask() {
    TS_WIZ_ASKED=0

    # The leader key only matters for WezTerm (a GUI app). On a headless server
    # there's no WezTerm to drive, so skip the question and keep the default.
    if [ -n "${TS_LEADER:-}" ]; then TS_WIZ_LEADER="$TS_LEADER"
    elif command -v ts_is_headless >/dev/null 2>&1 && ts_is_headless; then TS_WIZ_LEADER=ctrl-space
    else TS_WIZ_LEADER="$(ts_prompt_leader)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1)); fi

    if [ -n "${TS_THEME:-}" ]; then TS_WIZ_THEME="$TS_THEME"
    else TS_WIZ_THEME="$(ts_prompt_theme)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1)); fi

    # Only asked where the installer can actually install it (macOS).
    if [ "${TS_WIZ_ASK_WEZTERM:-0}" = "1" ]; then
        TS_WIZ_WEZTERM="$(ts_prompt_wezterm)"
        [ -n "${TS_WEZTERM:-}" ] || TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1))
    fi

    if [ -n "${TS_APPS:-}" ]; then TS_WIZ_APPS="$(ts_expand_apps "$TS_APPS")"
    else TS_WIZ_APPS="$(ts_prompt_apps)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1)); fi

    TS_WIZ_TMUX="${TS_TMUX:-ctrl-b}"

    # Normalise here rather than passing the raw env value through: the review
    # screen and the saved config should say on/off, not the user's "skip".
    if [ -n "${TS_CC_TTS:-}" ]; then
        case "$TS_CC_TTS" in on) TS_WIZ_CC_TTS=on ;; *) TS_WIZ_CC_TTS=off ;; esac
    else
        TS_WIZ_CC_TTS="$(ts_prompt_cc_tts)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1))
    fi
}

# Gather choices into TS_WIZ_* (no chezmoi writes here), then show them for
# review so a mis-typed answer costs a keystroke instead of a re-run.
ts_wizard_collect() {
    ts_wizard_ask
    while :; do
        ts_wizard_review
        if [ "${TS_ASSUME_YES:-}" = "1" ] || [ "${TS_WIZ_ASKED:-0}" -eq 0 ] || ! ts_is_interactive; then
            printf '  (nothing to review — proceeding)\n'
            break
        fi
        local a; a="$(ts_tty_prompt '  [P]roceed / [e]dit / [q]uit: ')"
        case "$a" in
            e|E|edit) ts_wizard_ask; continue ;;
            q|Q|quit) echo "$INFO quit — nothing was installed or changed."; return 1 ;;
            ''|p|P|proceed|y|Y|yes) break ;;
            *) printf "  '%s' is not one of the choices — Enter to proceed, 'e' to edit, 'q' to quit.\n" "$a" ;;
        esac
    done

    export TS_WIZ_LEADER TS_WIZ_THEME TS_WIZ_APPS TS_WIZ_TMUX TS_WIZ_CC_TTS TS_WIZ_WEZTERM
    echo "$INFO Config: leader=$TS_WIZ_LEADER theme=$TS_WIZ_THEME tmux-prefix=$TS_WIZ_TMUX cc-tts=${TS_WIZ_CC_TTS:-off}"
    echo "$INFO Apps: ${TS_WIZ_APPS:-<none>}"
}
