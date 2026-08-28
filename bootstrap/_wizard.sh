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
#   TS_TERMINALS=wezterm-nightly,wezterm-stable,ghostty|none
#                                            (macOS/desktop Linux; WSL uses the host's)
#     (TS_WEZTERM=nightly|stable|skip is the older spelling and still maps across)
#   TS_WEZ_MUX=on|off                        WezTerm multiplexer domain (tstack mux)
#   TS_WEZ_RESTORE=on|off                    reopen the last session at startup
#   TS_CC_TTS=on|off|skip   Claude Code Kokoro TTS at install
#   TS_CC_TTS_DAEMON=on|off route TTS through the Windows tray daemon (WSL only)
#   TS_HEADROOM=on|off TS_HEADROOM_CURSOR=mcp|byok|off
#   TS_CAVEMAN=on|off TS_AGENTMEMORY=on|off
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

# ── the first question ───────────────────────────────────────────────────────
# Everything else in this wizard is downstream of it, which is why it is first.
#
# Most people who find this repo want the prompt. Asking about the leader key,
# the mux, voice notifications and a memory backend BEFORE establishing that is
# fourteen questions aimed at someone who wanted one thing, and the honest answer
# to "can I just have the prompt" has to be yes.
#
# NOT a saved setting, deliberately. It decides what the REST of this wizard asks
# and what those answers default to, and every one of them is saved on its own -
# so a stored `profile` would be a second copy of state that can disagree with
# the settings it produced. Re-running the wizard asks again, which is correct:
# the answer is about what you want now, not about what this machine is.
ts_prompt_profile() {
    local c
    {
        printf '\n  This is what you would get:\n\n'
    } > /dev/tty 2>/dev/null
    ts_starship_preview terminal-stack > /dev/tty 2>/dev/null || true

    c="$(ts_prompt_choice full \
        'How much of this do you want?' \
        '  RECOMMENDATION: full on your own machine - the pieces are individually
  switchable afterwards with `tstack config`, and nothing here is hard to undo.
  Take prompt on a box that is not yours, or when you came for the prompt.' \
        'prompt|just the prompt|Starship + a Nerd Font. Your shell config, aliases and terminal are left alone' \
        'shell|prompt and terminal|adds the managed zsh/tmux/WezTerm configs and the CLI tools' \
        'full|the whole stack|adds the agent wiring, the Docker services, voice notifications and memory')"
    printf '%s\n' "$c"
}

# Offered whenever someone is choosing a prompt at all. Rendering each option is
# the entire value: a preset name tells you nothing, and this is a decision about
# what you look at every day.
ts_prompt_starship_preset() {
    local c opts=() p cur
    cur="$(ts_starship_get 2>/dev/null || echo terminal-stack)"
    if ! ts_starship_presets >/dev/null 2>&1; then
        # starship is installed by the bootstrap AFTER the wizard runs on a fresh
        # machine, so this is the normal first-install path rather than an error.
        printf '%s\n' "$cur"
        return 0
    fi
    {
        printf '\n  Every prompt, rendered here so you can see them:\n\n'
        printf '    terminal-stack\n'
    } > /dev/tty 2>/dev/null
    ts_starship_preview terminal-stack > /dev/tty 2>/dev/null || true
    for p in $(ts_starship_presets); do
        printf '    %s\n' "$p" > /dev/tty 2>/dev/null
        ts_starship_preview "$p" > /dev/tty 2>/dev/null || true
    done
    opts=("terminal-stack|terminal-stack|this stack's own two-line prompt, themed by tstack config theme")
    for p in $(ts_starship_presets); do
        opts+=("$p|$p")
    done
    c="$(ts_prompt_choice "$cur" 'Which prompt?' '' ${opts[@]+"${opts[@]}"})"
    printf '%s\n' "$c"
}

# ── are you going to write code here? ────────────────────────────────────────
# The second question, and the one that decides which half of the app catalog is
# offered. A file server and a development laptop want genuinely different sets:
# nobody administering a box needs fnm, poetry or six agent CLIs, and offering
# them is how a 30-item tick-list becomes something people skip past.
ts_prompt_development() {
    local c
    c="$(ts_prompt_choice yes \
        'Will you write code on this machine?' \
        '  Only decides which tools are pre-ticked and whether the agent and memory
  questions are asked at all. Everything stays individually selectable.' \
        'yes|yes, this is a development machine|git tooling, language runtimes, Python tools, the AI agent CLIs' \
        'no|no, I administer it|monitors, disk and network tools, editors, search - no runtimes, no agents')"
    printf '%s\n' "$c"
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

# Which GUI terminal emulators to install — a tick-list, so each is individually
# opt-in and "none" is one keystroke away. WezTerm appears TWICE, once per
# channel: upstream's newest stable is 20240203 (February 2024, no cut since),
# so nightly is what this stack's Lua config targets and is the pre-selected
# answer — but it is never automatic, and the intro shows the real build dates
# so the choice is made on facts rather than on a default nobody read.
# WSL and native Linux headless hosts never install one — the GUI lives elsewhere.
# See docs/decisions.md § "Why the WezTerm channel is a question, and why it is
# not a saved setting".
ts_terminal_candidates() {
    printf '%s\n' \
        'wezterm-nightly|WezTerm nightly|current builds; what this stack configures' \
        'wezterm-stable|WezTerm stable|20240203 — upstream has not cut one since' \
        'ghostty|Ghostty|GPU-accelerated, platform-native UI'
}

# One WezTerm, one channel. Both casks own /Applications/WezTerm.app and the two
# apt packages own /usr/bin/wezterm, so installing both is impossible. Nightly
# wins, matching ts_terminals_channel's tie-break.
ts_terminals_one_channel() {
    local sel=" $1 "
    case "$sel" in
        *" wezterm-nightly "*)
            case "$sel" in *" wezterm-stable "*)
                printf 'note: both WezTerm channels ticked — installing nightly (they cannot coexist).\n' >&2
                sel="$(printf '%s' "$sel" | tr ' ' '\n' | grep -v '^wezterm-stable$' | tr '\n' ' ')" ;;
            esac ;;
    esac
    printf '%s\n' "$(printf '%s' "$sel" | tr -s ' ' | sed 's/^ //; s/ $//')"
}

ts_prompt_terminals() {
    # TS_TERMINALS=wezterm-nightly,ghostty | wezterm-stable | none.
    # TS_WEZTERM is the older spelling and still maps across, so an unattended
    # install neither breaks nor silently gets a channel it did not ask for.
    local value="${TS_TERMINALS:-}"
    if [ -z "$value" ] && [ -n "${TS_WEZTERM:-}" ]; then
        case "$TS_WEZTERM" in
            skip|none) value=none ;;
            stable)    value=wezterm-stable ;;
            nightly)   value=wezterm-nightly ;;
            *)         value=wezterm-nightly ;;
        esac
    fi
    if [ -n "$value" ]; then
        if [ "$value" = none ]; then printf '\n'; return 0; fi
        # `wezterm` on its own has never named a channel; take the default one.
        # Done token by token: BSD sed has no \b, and a substring match would
        # also mangle wezterm-nightly.
        local tok out=""
        for tok in $(printf '%s' "$value" | tr ',' ' '); do
            [ "$tok" = wezterm ] && tok=wezterm-nightly
            out="$out $tok"
        done
        # The same one-channel rule the picker enforces. This path returned early
        # without it, so TS_TERMINALS=wezterm-nightly,wezterm-stable put BOTH
        # keys in the saved list — harmless only by luck, because
        # ts_terminals_channel happens to prefer nightly on a tie.
        printf '%s\n' "$(ts_terminals_one_channel "${out# }")"
        return 0
    fi

    local entry id preticked="" chosen intro
    local -a opts=()
    while IFS= read -r entry; do
        [ -n "$entry" ] || continue
        opts+=("$entry")
    done < <(ts_terminal_candidates)

    # NIGHTLY is pre-selected, including on a machine that already has stable.
    #
    # This used to pre-tick whatever was installed, which meant a stable box saw
    # nightly unticked and pressing Enter kept a build from February 2024 —
    # upstream has cut no stable since, and this stack's Lua config targets
    # current builds. "Keep what you have" is the wrong default when what you
    # have is two and a half years old and the config is written for newer.
    #
    # The one exception is `unknown`: a WezTerm installed outside a package
    # manager is not ours to replace, so neither channel is ticked and Enter
    # leaves it alone. Same rule ts_wezterm_install applies at install time.
    case "$(ts_wezterm_channel 2>/dev/null || echo none)" in
        unknown) preticked="" ;;
        *)       preticked="wezterm-nightly" ;;
    esac
    command -v ghostty >/dev/null 2>&1 && preticked="$preticked ghostty"

    intro="$(ts_wezterm_prompt_intro 2>/dev/null || true)"
    if command -v ghostty >/dev/null 2>&1; then
        intro="${intro:+$intro
}  Ghostty:  $(ghostty --version 2>/dev/null | head -1)"
    fi
    # A RECOMMENDATION line, like the other behaviour questions. Only shown when
    # a channel is actually pre-ticked — on an `unknown` install we are
    # deliberately not recommending anything.
    if [ -n "$preticked" ]; then
        intro="${intro:+$intro
}  RECOMMENDATION: nightly. Upstream's newest stable is 20240203 — February
  2024, with no cut since — and this stack's WezTerm config targets current
  builds, so stable misses features it assumes. Nightly is what upstream's
  author uses daily.
  Picking nightly SWAPS the cask: both own /Applications/WezTerm.app, so the
  other channel is removed first. Your config and sessions are untouched, and
  nothing upgrades on its own afterwards — tstack update only offers."
    fi

    # The two WezTerm channels are mutually exclusive, so the tick-list enforces
    # it live: ticking nightly visibly unticks stable. Before this, the screen
    # showed [x] [x] and the choice was silently corrected only after Enter.
    TS_MULTI_EXCLUSIVE="wezterm-nightly wezterm-stable" \
        chosen="$(ts_prompt_multi "${preticked# }" 'Terminal emulator:' "$intro" "${opts[@]}")"

    # Belt to the tick-list's braces: the live constraint above should make this
    # unreachable, but a non-interactive run keeps whatever was pre-ticked.
    ts_terminals_one_channel "$chosen"
}

# The multiplexer domain (tstack mux). Asked wherever a WezTerm GUI actually runs —
# macOS, Windows, and WSL, whose GUI is the Windows one — and skipped headless.
# Default off: it changes how every pane is hosted and how a config reload
# behaves, which is a decision to make once at install rather than inherit.
# Twin of bootstrap/_config.ps1 Read-TsWeztermMux — keep the rendering identical.
ts_prompt_wezterm_mux() {
    if [ -n "${TS_WEZ_MUX:-}" ]; then
        case "$TS_WEZ_MUX" in on) printf 'on\n' ;; *) printf 'off\n' ;; esac
        return 0
    fi
    ts_prompt_choice off 'WezTerm multiplexer (keeps panes alive when the GUI dies):' \
'  RECOMMENDATION: off. You only want this if WezTerm crashes on you often
  enough to be worth the cost, and it costs real day-to-day comfort:
    - every config change needs "tstack mux restart", which KILLS every pane;
    - mux panes lose the Claude state tint, so the tab bar stops telling you
      which sessions are working, done or waiting;
    - the server holds your shells, so it is one more thing to restart.
  On: shells run in wezterm-mux-server, so a GUI crash leaves panes alive and
  relaunching WezTerm reattaches. Off: the GUI owns them, and closing it ends
  them - which is what most people actually expect.' \
        'off|off|panes are spawned by the GUI' \
        'on|on|panes survive a GUI crash'
}

# Reopen the last session at WezTerm start (resurrect's gui-startup restore).
# Asked wherever a WezTerm GUI runs and skipped headless, same rule as the mux.
# Default off: a terminal that silently reopens yesterday's shells is a surprise,
# and the autosave runs either way so Leader+L can restore on demand.
# Twin of bootstrap/_config.ps1 Read-TsWeztermRestore — keep the rendering identical.
ts_prompt_wezterm_restore() {
    if [ -n "${TS_WEZ_RESTORE:-}" ]; then
        case "$TS_WEZ_RESTORE" in on) printf 'on\n' ;; *) printf 'off\n' ;; esac
        return 0
    fi
    ts_prompt_choice off 'WezTerm session restore (reopen the last session at startup):' \
'  RECOMMENDATION: off. A terminal that silently reopens yesterday shells is a
  surprise, and the panes come back without their processes - you get the
  layout and the scrollback, not the running commands, which is easy to
  mistake for a session that is still live.
  You lose nothing by saying off: the autosave runs either way, so Leader+L
  restores the same session on demand, when you actually want it.
  On: every launch replays the last autosaved session.' \
        'off|off|start clean every time' \
        'on|on|reopen the last session'
}

# atuin — SQLite shell history, and a much better Ctrl+R than fzf's.
# Default off, and asked rather than inferred: atuin *replaces* an existing key
# binding, and its binary is frequently already installed but dormant (a brew
# dependency, an old manual install), so a presence check would take Ctrl+R
# without anyone choosing it. Skipped headless, like the other behaviour toggles.
#
# NO PowerShell twin, deliberately: `atuin init` has no PowerShell target (zsh,
# bash, fish, nu, xonsh only) and there is no winget manifest for it, so native
# pwsh gets no integration to offer. On a Windows machine this question is asked
# by the WSL wizard, which is where atuin actually runs. Same reasoning as the
# Ghostty note in bootstrap/_config.ps1's $TsTerminalCandidates — the missing
# twin is a decision, not drift, so the byte-identical rule does not apply here.
ts_prompt_atuin() {
    if [ -n "${TS_ATUIN:-}" ]; then
        case "$TS_ATUIN" in on) printf 'on\n' ;; *) printf 'off\n' ;; esac
        return 0
    fi
    ts_prompt_choice on 'atuin shell history (replaces Ctrl+R):' \
'  RECOMMENDATION: on. It is the single biggest day-to-day upgrade here -
  Ctrl+R searches every shell'"'"'s history from one SQLite database, with the
  directory and exit status of each command, and no 100k-line ceiling.
  What changes: Ctrl+R becomes atuin instead of fzf. Ctrl+T, Alt+C and
  Up-arrow are untouched, and `history`/`hgrep` still read zsh'"'"'s own file,
  so nothing you already use stops working.
  Secrets are filtered the same way as ~/.zsh_history, so API keys do not
  land in the database either. Nothing syncs anywhere: no account is set up
  and auto-sync is off, so it all stays on this machine.
  Reversible any time with `tstack config atuin off`.' \
        'off|off|keep fzf on Ctrl+R' \
        'on|on|atuin owns Ctrl+R'
}

# The tick-list prompt for questions with more than one answer. Same rendering as
# ts_cleanup_menu's checklist, which is the house style for a multi-select; the
# note suffix follows ts_prompt_choice. Menu goes to /dev/tty, the chosen keys go
# to stdout space-separated, so callers capture with $( ) — which is also why
# TS_WIZ_ASKED must be tallied by the caller, never in here.
#
# usage: ts_prompt_multi <preticked-space-list> <title> <intro-or-empty> "key|label|note"...
# Twin of bootstrap/_config.ps1 Read-TsMulti — keep the rendered output identical.
# TS_MULTI_EXCLUSIVE — optional space-separated keys that are mutually
# exclusive. Ticking one visibly unticks the others, so the screen can never show
# a combination the caller will refuse. Passed as a global rather than a new
# positional argument so this stays signature-compatible with its pwsh twin
# Read-TsMulti (which takes it as -Exclusive); the RENDERED OUTPUT is unchanged
# either way, which is what the byte-identical rule actually constrains.
ts_prompt_multi() {
    local preticked=" $1 " title="$2" intro="$3"; shift 3
    local -a keys=() labels=() notes=() ticks=()
    local opt key rest label note i n ans tok idx
    local excl=" ${TS_MULTI_EXCLUSIVE:-} "

    for opt in "$@"; do
        key="${opt%%|*}"; rest="${opt#*|}"
        label="${rest%%|*}"; note="${rest#*|}"
        [ "$note" = "$label" ] && note=""
        keys+=("$key"); labels+=("$label"); notes+=("$note")
        case "$preticked" in *" $key "*) ticks+=(1) ;; *) ticks+=(0) ;; esac
    done
    n=${#keys[@]}
    [ "$n" -eq 0 ] && { printf '\n'; return 0; }

    render() {
        {
            printf '\n%s\n' "$title"
            [ -n "$intro" ] && printf '%s\n' "$intro"
            for i in $(seq 0 $((n - 1))); do
                local mark=" " suffix=""
                [ "${ticks[$i]}" = "1" ] && mark="x"
                [ -n "${notes[$i]}" ] && suffix="  (${notes[$i]})"
                printf '  [%s] %2d) %s%s\n' "$mark" "$((i + 1))" "${labels[$i]}" "$suffix"
            done
        } > /dev/tty 2>/dev/null
    }

    # Keep at most one member of the exclusive group ticked. <keep> is the index
    # that just won; -1 means "no winner", in which case the FIRST ticked member
    # survives — matching ts_terminals_channel's nightly-wins tie-break.
    exclusive() {
        local keep="$1" j first=-1
        [ "$excl" = "  " ] && return 0
        # A winner only wins its OWN group. Ticking an option outside the group
        # used to collapse it anyway — $keep was an index no member could equal,
        # so every ticked member failed the `$j = $keep` test and was cleared.
        # On macOS that meant ticking Ghostty silently unticked WezTerm.
        if [ "$keep" -ge 0 ]; then
            case "$excl" in *" ${keys[$keep]} "*) ;; *) return 0 ;; esac
        fi
        for j in $(seq 0 $((n - 1))); do
            case "$excl" in *" ${keys[$j]} "*) ;; *) continue ;; esac
            [ "${ticks[$j]}" = "1" ] || continue
            if [ "$keep" -ge 0 ]; then
                [ "$j" = "$keep" ] || ticks[$j]=0
            elif [ "$first" -lt 0 ]; then first=$j
            else ticks[$j]=0
            fi
        done
    }

    emit() {
        local out=""
        for i in $(seq 0 $((n - 1))); do
            [ "${ticks[$i]}" = "1" ] && out="$out ${keys[$i]}"
        done
        printf '%s\n' "${out# }"
    }

    # Normalise the pre-ticks before the first render: a machine mid-channel-switch
    # can legitimately have both installed. Must come AFTER the helper is defined
    # — bash resolves function names at call time, so doing this up with the tick
    # parsing printed "exclusive: command not found" and silently skipped it.
    exclusive -1
    render
    if ! ts_is_interactive; then
        printf 'Toggle a number, [a]ll, [n]one, Enter to continue, [s]kip: (non-interactive — keeping the defaults)\n' \
            > /dev/tty 2>/dev/null
        emit; unset -f render emit 2>/dev/null; return 0
    fi

    while true; do
        ans="$(ts_tty_prompt 'Toggle a number, [a]ll, [n]one, Enter to continue, [s]kip: ')"
        case "$ans" in
            "")        break ;;
            s|S|skip)  for i in $(seq 0 $((n - 1))); do ticks[$i]=0; done; break ;;
            a|A|all)   for i in $(seq 0 $((n - 1))); do ticks[$i]=1; done; exclusive -1; render; continue ;;
            n|N|no|none) for i in $(seq 0 $((n - 1))); do ticks[$i]=0; done; render; continue ;;
        esac
        # Several toggles in one answer: "1 3" and "1,3" both work. Deliberately
        # NOT ts_prompt_choice's `tr -d [:space:]` — that would fuse 1 2 into 12.
        local bad=0
        for tok in $(printf '%s' "$ans" | tr ',' ' '); do
            case "$tok" in
                ''|*[!0-9]*) bad=1; continue ;;
            esac
            idx=$((tok - 1))
            if [ "$idx" -ge 0 ] && [ "$idx" -lt "$n" ]; then
                if [ "${ticks[$idx]}" = "1" ]; then ticks[$idx]=0
                else ticks[$idx]=1; exclusive "$idx"; fi
            else
                bad=1
            fi
        done
        [ "$bad" = "1" ] && printf '  ? enter a number 1-%s (several are fine), a, n, s, or Enter\n' "$n" > /dev/tty 2>/dev/null
        render
    done
    emit
    unset -f render emit exclusive 2>/dev/null
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
    local selected="" id csv want unknown=""
    printf '\n  Available: %s\n' "$TS_APPS_ALL" > /dev/tty 2>/dev/null
    csv="$(ts_tty_prompt '  Type a comma-separated list, or Enter to pick from a list: ')"
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
    # Thirty consecutive Y/n prompts is a lot to sit through, so the walk is a
    # tick-list per group rather than one question per tool.
    ts_pick_apps_by_item
}

# Build the "key|label|note" option list for a group, labelling with the id so the
# saved selection and the menu use the same words.
_ts_app_options_for_group() {
    local id
    for id in $(ts_app_group_members "$1"); do
        printf '%s|%s|%s\n' "$id" "$id" "$(ts_app_desc "$id")"
    done
}

# Tier 3: walk the groups, tick-list within each. Pre-ticked = the recommended
# set FOR THIS MACHINE'S CLASS, so Enter through the lot lands somewhere sensible
# whether you are setting up a laptop or a server. Every tool stays individually
# tickable either way -- the class decides the defaults, never the menu.
ts_pick_apps_by_item() {
    local g selected="" chosen pretick
    local -a opts
    pretick="$(ts_apps_for_class "${TS_WIZ_APP_CLASS:-developer}")"
    for g in $TS_APP_GROUPS; do
        opts=()
        while IFS= read -r line; do [ -n "$line" ] && opts+=("$line"); done < <(_ts_app_options_for_group "$g")
        [ ${#opts[@]} -eq 0 ] && continue
        chosen="$(ts_prompt_multi "$pretick" "  $(ts_app_group_desc "$g"):" '' "${opts[@]}")"
        [ -n "$chosen" ] && selected="$selected $chosen"
    done
    echo "${selected# }"
}

# Tier 2: tick whole groups; every member of a ticked group is selected.
ts_pick_app_groups() {
    local g selected="" chosen preticked=""
    local -a opts=()
    for g in $TS_APP_GROUPS; do
        opts+=("$g|$(ts_app_group_desc "$g")|$(ts_app_group_members "$g")")
        # Every group starts ticked, the agent CLIs included — they are still a
        # question, and every tool inside is still individually untickable.
        preticked="$preticked $g"
    done
    chosen="$(ts_prompt_multi "${preticked# }" '  Tool groups:' '' "${opts[@]}")"
    for g in $chosen; do selected="$selected $(ts_app_group_members "$g")"; done
    echo "${selected# }"
}

# The re-run case is the one that bites: this wizard is not only an installer,
# it is what `ts-config reconfigure` and a repeat bootstrap run. Defaulting to
# `recommended` on a machine that already has a larger saved selection meant
# pressing Enter through the questions SHRANK `apps` in chezmoi [data] -- the
# binaries stayed, the record of wanting them did not, and the next ts-update
# had nothing to nag about. So when a selection already exists it becomes both
# the first option and the default, and the recommended set is still one key away.
ts_prompt_apps() {
    local intro choice saved def
    saved="$(ts_data_get_apps 2>/dev/null || true)"
    # ts_apps_install_note prints its own trailing blank line; strip it so the
    # menu stays a single block.
    intro="$(ts_apps_install_note 2>/dev/null || true)"
    intro="${intro:+$intro
}  recommended: $(ts_apps_for_class "${TS_WIZ_APP_CLASS:-developer}")
  also available: everything else in the catalog"
    local opts=()
    def=recommended
    if [ -n "$saved" ]; then
        def=keep
        opts=("keep|keep this machine's current selection|$(echo "$saved" | wc -w | tr -d ' ') tools already chosen here")
    fi
    # ${opts[@]+"${opts[@]}"}, not "${opts[@]}": bash 3.2 -- the only bash on macOS
    # -- treats an EMPTY array as unbound under `set -u`, and every bootstrap runs
    # `set -euo pipefail`. The empty case here is a machine with no saved apps,
    # i.e. a first install, so the bare form would break exactly the fresh run.
    opts=(${opts[@]+"${opts[@]}"}
        "recommended|install the recommended set|the ${TS_WIZ_APP_CLASS:-developer} set for this machine"
        "all|install everything|recommended + $(echo "$TS_APPS_OPTIONAL" | tr ' ' ',' | sed 's/,/, /g')"
        "groups|choose whole groups|$(echo "$TS_APP_GROUPS" | tr ' ' ',' | sed 's/,/, /g')"
        'customize|choose individual tools'
        'none|skip all optional apps')
    choice="$(ts_prompt_choice "$def" \
        'Optional CLI tools (font, Starship, chezmoi, zsh — always installed):' "$intro" \
        "${opts[@]}")"
    case "$choice" in
        keep)      echo "$saved" ;;
        all)       echo "$TS_APPS_ALL" ;;
        none)      echo "" ;;
        groups)    ts_pick_app_groups ;;
        customize) ts_pick_apps ;;
        *)         ts_apps_for_class "${TS_WIZ_APP_CLASS:-developer}" ;;
    esac
}

# <env-var> <title> <intro> [default] [on-note]
# The default is a parameter so a caller can probe the service first and answer
# the question the way the machine actually is, instead of always defaulting off
# and letting someone wire an agent to something that is not running.
ts_prompt_agent_toggle() {
    local env_name="$1" title="$2" note="$3" def="${4:-off}" onnote="${5:-user-global on this computer}" value=""
    eval "value=\${$env_name:-}"
    if [ -n "$value" ]; then case "$value" in on) echo on ;; *) echo off ;; esac; return; fi
    ts_prompt_choice "$def" "$title" "$note" \
        'off|off|configure later with tstack config agents' \
        "on|on|$onnote"
}

# ONE question, replacing the two independent "Headroom?" / "AgentMemory?"
# toggles that used to sit here. They ask about two things that do the same job,
# so every combination was reachable, including the one nobody wants: two memory
# systems, each holding half the story.
#
# The probes still speak. A recommendation in this repo says what it FOUND, and
# a machine that already has memories is a different question from a fresh one.
ts_prompt_memory_backend() {
    local value=""
    value="${TS_MEMORY_BACKEND:-}"
    if [ -n "$value" ]; then
        case "$value" in agentmemory|headroom|none) echo "$value" ;; *) echo agentmemory ;; esac
        return
    fi
    # A pre-merge unattended install only knew the two booleans. Honour them
    # rather than ignoring them, so an old script cannot land on a combination
    # this menu will not offer.
    if [ -n "${TS_AGENTMEMORY:-}" ] || [ -n "${TS_HEADROOM:-}" ]; then
        if [ "${TS_AGENTMEMORY:-off}" = on ]; then echo agentmemory; else echo none; fi
        return
    fi

    local am_report hr_report
    am_report="$(ts_probe_agentmemory 2>/dev/null || true)"
    hr_report="$(ts_probe_headroom 2>/dev/null || true)"

    ts_prompt_choice agentmemory 'Memory and compression:' \
"  RECOMMENDATION: AgentMemory remembers, Headroom compresses.
  Only ONE memory system runs. They overlap, and two stores means two
  half-filled ones with no way to tell which holds the answer you want.
${am_report}${hr_report}
  Compression is not a memory feature and is unaffected by this: Headroom
  compresses by trimming tool schemas and code, and calls no model of its own.
  Headroom's memory additionally runs Qdrant and Neo4j (about 940 MB); the
  other answers never pull those images." \
        'agentmemory|AgentMemory remembers, Headroom compresses|the default' \
        'headroom|Headroom does both|AgentMemory is not installed' \
        'none|Headroom compresses only|no memory at all' \
        'off|Neither|no proxy, no memory'
}

ts_prompt_headroom_cursor() {
    [ -n "${TS_HEADROOM_CURSOR:-}" ] && { case "$TS_HEADROOM_CURSOR" in mcp|byok|off) echo "$TS_HEADROOM_CURSOR";; *) echo mcp;; esac; return; }
    ts_prompt_choice mcp 'Cursor Headroom mode:' \
'  MCP keeps Cursor subscription model traffic direct. BYOK routes model traffic
  through Headroom but requires a provider API key and separate provider billing.' \
        'mcp|MCP only|recommended for Cursor subscriptions' \
        'byok|BYOK proxy|provider API key required' \
        'off|off'
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
    printf '    Scope            %s\n' "${TS_WIZ_PROFILE:-full}"
    printf '    Prompt           %s\n' "${TS_WIZ_STARSHIP:-terminal-stack}"
    # `prompt` pins every remaining answer rather than asking. Showing them makes
    # that visible instead of implied -- and a review that silently omits what it
    # decided for you is how "I didn't choose that" happens.
    if [ "${TS_WIZ_PROFILE:-full}" = prompt ]; then
        printf '    Theme            %s\n' "$theme_label"
        printf '    Everything else  left alone (no tools, no configs, no agents)\n'
        return 0
    fi
    printf '    For development  %s\n' "${TS_WIZ_DEV:-yes}"
    printf '    Leader           %s\n' "$TS_WIZ_LEADER"
    printf '    Theme            %s\n' "$theme_label"
    [ "${TS_WIZ_ASK_TERMINALS:-0}" = "1" ] && printf '    Terminals        %s\n' "${TS_WIZ_TERMINALS:-<none>}"
    printf '    WezTerm mux      %s\n' "${TS_WIZ_WEZ_MUX:-off}"
    printf '    Session restore  %s\n' "${TS_WIZ_WEZ_RESTORE:-off}"
    printf '    atuin (Ctrl+R)   %s\n' "${TS_WIZ_ATUIN:-off}"
    printf '    tmux prefix      %s\n' "$TS_WIZ_TMUX"
    printf '    Apps             %s\n' "${TS_WIZ_APPS:-<none>}"
    printf '    Claude TTS       %s\n' "${TS_WIZ_CC_TTS:-off}"
    [ "${TS_WIZ_CC_TTS:-off}" = on ] && printf '    Voice says       %s\n' "${TS_WIZ_CC_TTS_MESSAGE:-template}"
    [ "${TS_WIZ_CC_TTS:-off}" = on ] && printf '    TTS daemon       %s\n' "${TS_WIZ_CC_TTS_DAEMON:-off}"
    printf '    Headroom         %s (Cursor: %s)\n' "${TS_WIZ_HEADROOM:-off}" "${TS_WIZ_HEADROOM_CURSOR:-mcp}"
    printf '    Caveman          %s\n' "${TS_WIZ_CAVEMAN:-off}"
    printf '    Memory backend   %s\n' "${TS_WIZ_MEMORY_BACKEND:-agentmemory}"
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
    local _mem=""
    TS_WIZ_CC_TTS_MESSAGE="${TS_WIZ_CC_TTS_MESSAGE:-template}"
    TS_WIZ_ASKED=0

    # ── first: how much of this do you want ────────────────────────────────
    # Everything below is downstream of it. TS_PROFILE=prompt|shell|full skips.
    if [ -n "${TS_PROFILE:-}" ]; then
        case "$TS_PROFILE" in prompt|shell|full) TS_WIZ_PROFILE="$TS_PROFILE" ;; *) TS_WIZ_PROFILE=full ;; esac
    elif command -v ts_is_headless >/dev/null 2>&1 && ts_is_headless; then
        # A headless server has no GUI terminal to configure, but it does have a
        # shell and it is exactly the machine someone administers. `shell` is the
        # only profile whose questions all still mean something there.
        TS_WIZ_PROFILE=shell
    else TS_WIZ_PROFILE="$(ts_prompt_profile)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1)); fi

    # ── second: is this a development machine ──────────────────────────────
    # Decides which half of the catalog is pre-ticked, and whether the agent and
    # memory questions are asked at all. Meaningless for `prompt`, which installs
    # no tools.
    if [ "$TS_WIZ_PROFILE" = prompt ]; then
        TS_WIZ_DEV=no
    elif [ -n "${TS_DEVELOPMENT:-}" ]; then
        case "$TS_DEVELOPMENT" in yes|on|true) TS_WIZ_DEV=yes ;; *) TS_WIZ_DEV=no ;; esac
    elif command -v ts_is_headless >/dev/null 2>&1 && ts_is_headless; then TS_WIZ_DEV=no
    else TS_WIZ_DEV="$(ts_prompt_development)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1)); fi
    case "$TS_WIZ_DEV" in yes) TS_WIZ_APP_CLASS=developer ;; *) TS_WIZ_APP_CLASS=sysadmin ;; esac

    # Which prompt. Asked for every profile, because it is the one thing all
    # three have in common -- and for `prompt` it is very nearly the whole
    # install. ts_prompt_starship_preset returns the current value untouched when
    # starship is not installed yet, which on a fresh machine it is not: the
    # bootstrap installs it after this runs.
    if [ -n "${TS_STARSHIP_PRESET:-}" ]; then TS_WIZ_STARSHIP="$TS_STARSHIP_PRESET"
    elif [ "$TS_WIZ_PROFILE" = prompt ]; then
        TS_WIZ_STARSHIP="$(ts_prompt_starship_preset)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1))
    else TS_WIZ_STARSHIP="$(ts_starship_get 2>/dev/null || echo terminal-stack)"; fi

    # `prompt` means what it says: Starship and a Nerd Font, and nothing else
    # touched. Every remaining answer is pinned to its off/default value rather
    # than asked, and the review screen shows them so it is visible rather than
    # implied.
    if [ "$TS_WIZ_PROFILE" = prompt ]; then
        TS_WIZ_LEADER=ctrl-space; TS_WIZ_TMUX=ctrl-b
        TS_WIZ_THEME="${TS_THEME:-}"
        [ -n "$TS_WIZ_THEME" ] || { TS_WIZ_THEME="$(ts_prompt_theme)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1)); }
        TS_WIZ_APPS=""
        TS_WIZ_WEZ_MUX=off; TS_WIZ_WEZ_RESTORE=off; TS_WIZ_ATUIN=off
        TS_WIZ_CC_TTS=off; TS_WIZ_CC_TTS_DAEMON=off; TS_WIZ_CC_TTS_MESSAGE=template
        TS_WIZ_HEADROOM=off; TS_WIZ_CAVEMAN=off; TS_WIZ_AGENTMEMORY=off
        TS_WIZ_MEMORY_BACKEND=none; TS_WIZ_HEADROOM_CURSOR=mcp
        return 0
    fi

    # The leader key only matters for WezTerm (a GUI app). On a headless server
    # there's no WezTerm to drive, so skip the question and keep the default.
    if [ -n "${TS_LEADER:-}" ]; then TS_WIZ_LEADER="$TS_LEADER"
    elif command -v ts_is_headless >/dev/null 2>&1 && ts_is_headless; then TS_WIZ_LEADER=ctrl-space
    else TS_WIZ_LEADER="$(ts_prompt_leader)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1)); fi

    if [ -n "${TS_THEME:-}" ]; then TS_WIZ_THEME="$TS_THEME"
    else TS_WIZ_THEME="$(ts_prompt_theme)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1)); fi

    # Only asked where the installer can actually install it (macOS).
    if [ "${TS_WIZ_ASK_TERMINALS:-0}" = "1" ]; then
        TS_WIZ_TERMINALS="$(ts_prompt_terminals)"
        { [ -n "${TS_TERMINALS:-}" ] || [ -n "${TS_WEZTERM:-}" ]; } || TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1))
    fi

    # The mux only matters where a WezTerm GUI runs; a headless server has none,
    # so skip the question there — same rule as the leader key above.
    if [ -n "${TS_WEZ_MUX:-}" ]; then
        case "$TS_WEZ_MUX" in on) TS_WIZ_WEZ_MUX=on ;; *) TS_WIZ_WEZ_MUX=off ;; esac
    elif command -v ts_is_headless >/dev/null 2>&1 && ts_is_headless; then TS_WIZ_WEZ_MUX=off
    else TS_WIZ_WEZ_MUX="$(ts_prompt_wezterm_mux)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1)); fi

    # Same GUI-only rule as the mux above: a headless server has no WezTerm.
    if [ -n "${TS_WEZ_RESTORE:-}" ]; then
        case "$TS_WEZ_RESTORE" in on) TS_WIZ_WEZ_RESTORE=on ;; *) TS_WIZ_WEZ_RESTORE=off ;; esac
    elif command -v ts_is_headless >/dev/null 2>&1 && ts_is_headless; then TS_WIZ_WEZ_RESTORE=off
    else TS_WIZ_WEZ_RESTORE="$(ts_prompt_wezterm_restore)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1)); fi

    # atuin. Headless is fine here — unlike the WezTerm questions this is a
    # shell binding, and a headless server has a shell. Asked, never inferred:
    # see ts_prompt_atuin. TS_WIZ_ASKED is tallied here, not inside the prompt,
    # because prompts run through $( ) and a subshell increment is discarded.
    if [ -n "${TS_ATUIN:-}" ]; then
        case "$TS_ATUIN" in on) TS_WIZ_ATUIN=on ;; *) TS_WIZ_ATUIN=off ;; esac
    else TS_WIZ_ATUIN="$(ts_prompt_atuin)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1)); fi

    if [ -n "${TS_APPS:-}" ]; then TS_WIZ_APPS="$(ts_expand_apps "$TS_APPS")"
    else TS_WIZ_APPS="$(ts_prompt_apps)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1)); fi

    # Never asked, but a re-run must not silently reset it: this used to be a bare
    # `${TS_TMUX:-ctrl-b}`, so any machine whose prefix had been changed had it
    # forced back to ctrl-b by the next reconfigure. Saved value first, then the
    # default for a machine that has never answered.
    TS_WIZ_TMUX="${TS_TMUX:-}"
    [ -n "$TS_WIZ_TMUX" ] || TS_WIZ_TMUX="$(ts_data_get tmuxPrefix 2>/dev/null || true)"
    [ -n "$TS_WIZ_TMUX" ] || TS_WIZ_TMUX=ctrl-b

    # Normalise here rather than passing the raw env value through: the review
    # screen and the saved config should say on/off, not the user's "skip".
    if [ -n "${TS_CC_TTS:-}" ]; then
        case "$TS_CC_TTS" in on) TS_WIZ_CC_TTS=on ;; *) TS_WIZ_CC_TTS=off ;; esac
    elif [ "$TS_WIZ_PROFILE" != full ]; then
        # Voice notifications announce what an AGENT is doing. Without the agent
        # wiring there is nothing to announce, so the question is not asked.
        TS_WIZ_CC_TTS=off
    else
        TS_WIZ_CC_TTS="$(ts_prompt_cc_tts)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1))
    fi

    # Follow-up: WHAT it says. Only worth asking once voice is on, and only
    # `self`/`template`/`hook` are offered — haiku and ollama need the daemon,
    # so they are never shown on a host that cannot run one.
    if [ "$TS_WIZ_CC_TTS" = on ]; then
        TS_WIZ_CC_TTS_MESSAGE="$(ts_prompt_cc_tts_message)"
        [ -n "${TS_CC_TTS_MESSAGE:-}" ] || TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1))
    else
        TS_WIZ_CC_TTS_MESSAGE=template
    fi

    # Tray daemon follow-up (TS_CC_TTS_DAEMON=on|off skips): only when TTS was
    # enabled and this host can reach a Windows side (WSL); native Linux and
    # headless hosts keep classic direct playback.
    if [ "$TS_WIZ_CC_TTS" = on ] && [ -d /mnt/c/Users ] \
        && ! { command -v ts_is_headless >/dev/null 2>&1 && ts_is_headless; }; then
        if [ -n "${TS_CC_TTS_DAEMON:-}" ]; then
            case "$TS_CC_TTS_DAEMON" in on) TS_WIZ_CC_TTS_DAEMON=on ;; *) TS_WIZ_CC_TTS_DAEMON=off ;; esac
        else
            TS_WIZ_CC_TTS_DAEMON="$(ts_prompt_cc_tts_daemon)"; TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1))
        fi
    else
        TS_WIZ_CC_TTS_DAEMON=off
    fi

    # `shell` is the prompt and the terminal, and a machine that is not for
    # writing code has no agents to wire: in both cases the memory and caveman
    # questions are about something that is not being installed. Skipped rather
    # than asked-and-defaulted, so the wizard is shorter for the people it is
    # shorter for.
    if [ "$TS_WIZ_PROFILE" != full ] || [ "$TS_WIZ_DEV" != yes ] \
        || { command -v ts_is_headless >/dev/null 2>&1 && ts_is_headless; }; then
        TS_WIZ_HEADROOM="${TS_HEADROOM:-off}"; TS_WIZ_CAVEMAN="${TS_CAVEMAN:-off}"; TS_WIZ_AGENTMEMORY="${TS_AGENTMEMORY:-off}"
        TS_WIZ_MEMORY_BACKEND="${TS_MEMORY_BACKEND:-none}"
        [ "$TS_WIZ_AGENTMEMORY" = on ] && TS_WIZ_MEMORY_BACKEND=agentmemory
    else
        # ONE question. Headroom and AgentMemory used to be asked separately,
        # which made "both memory systems on" a single keystroke away.
        #
        # Interrogate before offering: wiring an agent to a service that is not
        # running fails LATER and silently, so the probes decide what the
        # question says about this machine.
        _mem="$(ts_prompt_memory_backend)"
        [ -n "${TS_MEMORY_BACKEND:-}" ] || TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1))
        case "$_mem" in
            agentmemory) TS_WIZ_MEMORY_BACKEND=agentmemory; TS_WIZ_AGENTMEMORY=on;  TS_WIZ_HEADROOM=on ;;
            headroom)    TS_WIZ_MEMORY_BACKEND=headroom;    TS_WIZ_AGENTMEMORY=off; TS_WIZ_HEADROOM=on ;;
            none)        TS_WIZ_MEMORY_BACKEND=none;        TS_WIZ_AGENTMEMORY=off; TS_WIZ_HEADROOM=on ;;
            *)           TS_WIZ_MEMORY_BACKEND=none;        TS_WIZ_AGENTMEMORY=off; TS_WIZ_HEADROOM=off ;;
        esac
        TS_WIZ_CAVEMAN="$(ts_prompt_agent_toggle TS_CAVEMAN 'Caveman terse output for all projects?' '  Installs the pinned user-scope plugin/skill; no project files are changed.')"
        [ -n "${TS_CAVEMAN:-}" ] || TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1))
    fi
    if [ "$TS_WIZ_HEADROOM" = on ]; then
        TS_WIZ_HEADROOM_CURSOR="$(ts_prompt_headroom_cursor)"
        [ -n "${TS_HEADROOM_CURSOR:-}" ] || TS_WIZ_ASKED=$((TS_WIZ_ASKED + 1))
    else TS_WIZ_HEADROOM_CURSOR="${TS_HEADROOM_CURSOR:-mcp}"; fi
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

    export TS_WIZ_PROFILE TS_WIZ_DEV TS_WIZ_APP_CLASS TS_WIZ_STARSHIP
    export TS_WIZ_LEADER TS_WIZ_THEME TS_WIZ_APPS TS_WIZ_TMUX TS_WIZ_CC_TTS TS_WIZ_CC_TTS_DAEMON TS_WIZ_CC_TTS_MESSAGE TS_WIZ_TERMINALS TS_WIZ_WEZ_MUX TS_WIZ_WEZ_RESTORE TS_WIZ_HEADROOM TS_WIZ_HEADROOM_CURSOR TS_WIZ_CAVEMAN TS_WIZ_AGENTMEMORY TS_WIZ_MEMORY_BACKEND TS_WIZ_ATUIN
    # These two lines summarise the CHOICES. They are printed before anything is
    # written, and used to read exactly like a save confirmation — which is how a
    # run that lost every answer still looked successful. The bootstraps now
    # persist immediately after this, and say so themselves when they do.
    echo "$INFO Config: leader=$TS_WIZ_LEADER theme=$TS_WIZ_THEME tmux-prefix=$TS_WIZ_TMUX wez-mux=${TS_WIZ_WEZ_MUX:-off} wez-restore=${TS_WIZ_WEZ_RESTORE:-off} cc-tts=${TS_WIZ_CC_TTS:-off} headroom=${TS_WIZ_HEADROOM:-off} caveman=${TS_WIZ_CAVEMAN:-off} agentmemory=${TS_WIZ_AGENTMEMORY:-off}"
    echo "$INFO Apps: ${TS_WIZ_APPS:-<none>}"
}
