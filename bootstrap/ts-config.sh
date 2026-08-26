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
#   tstack config ghostty [on|off|status|diff]   managed Ghostty config (macOS/Windows)
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
    case " $sel " in *" ghostty "*)
        if [ "$(uname -s)" = Darwin ] && command -v brew >/dev/null 2>&1; then
            brew list --cask ghostty >/dev/null 2>&1 || brew install --cask ghostty || true
        elif [ -d /mnt/c/Users ]; then
            # Windows: noctty/winghostty is offered but never installed for you.
            # winget carries AmanThanvi.winghostty, currently the same 1.3.123 the
            # releases page ships. Either is fine; the managed config lands the same
            # way. Same rule as WezTerm: asked, never forced.
            echo "==> Ghostty on Windows is noctty (ships as winghostty today):"
            echo "      winget install AmanThanvi.winghostty"
            echo "      or https://github.com/amanthanvi/noctty/releases"
            echo "    The managed config is written by the sync either way."
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
    ts_wez_mux_set "${TS_WIZ_WEZ_MUX:-off}"
    ts_wez_restore_set "${TS_WIZ_WEZ_RESTORE:-off}"
    ts_atuin_set "${TS_WIZ_ATUIN:-off}"
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
# Two platforms, one setting. On macOS this manages ~/.config/ghostty/; on WSL it
# manages the WINDOWS-side copy under /mnt/c/…/AppData/Local/ghostty/, because
# there is a Ghostty for Windows after all: noctty (github.com/amanthanvi/noctty),
# Ghostty's terminal core in a native Win32 app. It still ships its release assets
# under its former name winghostty — the rebrand landed in main on 2026-08-20,
# after the v1.3.123 tag, so no release carries the new name yet.
#
# It reads the upstream-compatible %LOCALAPPDATA%\ghostty\config as well as its
# own %LOCALAPPDATA%\<appname>\config.ghostty, and we target the upstream one on
# purpose: <appname> is `winghostty` today and `noctty` the day the rename ships,
# so the app-named path would silently stop being read on upgrade day.
#
# Native Linux is still refused: those hosts are headless, the GUI lives elsewhere.
# See docs/decisions.md § "Why Ghostty is managed on Windows too".
GHOSTTY_PLATFORM=""
GHOSTTY_DIR=""
GHOSTTY_CFG=""
GHOSTTY_THEME=""

# Resolve the platform and the paths, or explain why we cannot.
ghostty_paths() {
    [ -n "$GHOSTTY_PLATFORM" ] && return 0
    if [ "$(uname -s)" = Darwin ]; then
        GHOSTTY_PLATFORM=darwin
        GHOSTTY_DIR="$HOME/.config/ghostty"
    elif [ -d /mnt/c/Users ]; then
        local u=""
        if [ -n "$CZ" ] && [ -x "$CZ" ]; then
            u="$("$CZ" execute-template '{{ if hasKey . "windowsUsername" }}{{ .windowsUsername }}{{ end }}' 2>/dev/null || true)"
        fi
        if [ -z "$u" ] && [ -x /mnt/c/Windows/System32/cmd.exe ]; then
            u="$(/mnt/c/Windows/System32/cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n' || true)"
        fi
        if [ -z "$u" ]; then
            echo "tstack config ghostty: could not resolve the Windows username." >&2
            echo "  Add windowsUsername to [data] in ~/.config/chezmoi/chezmoi.toml." >&2
            return 1
        fi
        GHOSTTY_PLATFORM=wsl
        GHOSTTY_DIR="/mnt/c/Users/$u/AppData/Local/ghostty"
    else
        echo "tstack config ghostty: macOS or WSL only. Ghostty runs on macOS, and on" >&2
        echo "  Windows as noctty/winghostty; this stack's native-Linux hosts are" >&2
        echo "  headless, so there is no GUI here to configure." >&2
        return 1
    fi
    GHOSTTY_CFG="$GHOSTTY_DIR/config"
    GHOSTTY_THEME="$GHOSTTY_DIR/themes/vs-code-light-modern"
    return 0
}

# Render the Windows template the way the sync will. sed is safe for exactly
# these two tokens — both are single-line and neither value can contain a `#`,
# which is why the sync's own no-sed rule (multi-line __CC_TTS_*__ tokens) does
# not apply. `follow` needs a split dark:…,light:… theme, which always tracks the
# OS, so it cannot be expressed by pinning window-theme.
ghostty_render_windows() {
    local mode gt gw
    mode="$(ts_data_get themeMode 2>/dev/null || echo dark)"
    case "$mode" in
        light)  gt='vs-code-light-modern'; gw='light' ;;
        follow) gt='dark:Catppuccin Mocha,light:vs-code-light-modern'; gw='auto' ;;
        *)      gt='Catppuccin Mocha'; gw='dark' ;;
    esac
    sed -e "s#__GHOSTTY_THEME__#$gt#g" -e "s#__GHOSTTY_WINDOW_THEME__#$gw#g" \
        "$SRC/windows/AppData/Local/ghostty/config.tmpl"
}

ghostty_status() {
    ghostty_paths || return 1
    echo "ghostty config: $(ts_ghostty_get)   (target: $GHOSTTY_PLATFORM)"
    if [ -e "$GHOSTTY_CFG" ]; then
        if head -20 "$GHOSTTY_CFG" | grep -q 'managed by terminal-stack'; then
            echo "  $GHOSTTY_CFG  (ours)"
        else
            echo "  $GHOSTTY_CFG  (NOT ours — apply would replace it; a backup is taken first)"
        fi
    else
        echo "  $GHOSTTY_CFG  (absent)"
    fi
    [ -e "$GHOSTTY_THEME" ] && echo "  $GHOSTTY_THEME  (custom light theme)"
    local b
    b="$(ls -1t "$GHOSTTY_DIR"/config.bak.* 2>/dev/null | head -1 || true)"
    [ -n "$b" ] && echo "  newest backup: $b"
    ghostty_status_binary
}

# The binary half differs enough per platform to be worth splitting out.
ghostty_status_binary() {
    if [ "$GHOSTTY_PLATFORM" = darwin ]; then
        if command -v ghostty >/dev/null 2>&1; then
            echo "  ghostty: $(ghostty --version 2>/dev/null | head -1)"
            if [ -e "$GHOSTTY_CFG" ]; then
                if ghostty +validate-config --config-file="$GHOSTTY_CFG" >/dev/null 2>&1; then
                    echo "  validate: ok"
                else
                    echo "  validate: FAILED —"
                    ghostty +validate-config --config-file="$GHOSTTY_CFG" 2>&1 | sed 's/^/    /'
                fi
            fi
        else
            echo "  ghostty: not installed (tstack config wizard installs the cask)"
        fi
        return 0
    fi

    # Windows, reached over WSL interop. Both names, post-rename first.
    local exe="" c
    for c in "/mnt/c/Program Files/noctty/noctty.com" \
             "/mnt/c/Program Files/winghostty/winghostty.com"; do
        [ -x "$c" ] && { exe="$c"; break; }
    done
    if [ -z "$exe" ]; then
        echo "  noctty/winghostty: not installed"
        echo "    releases: https://github.com/amanthanvi/noctty/releases"
        return 0
    fi
    echo "  $(basename "$exe" .com): $("$exe" --version 2>/dev/null | head -1)"
    # NO validate step, deliberately. `+validate-config` fails with FileTooBig on
    # winghostty 1.3.123 even for a 14-byte config, and `+show-config` reports
    # nothing at all for an unknown key or a bad value — so unlike macOS there is
    # no honest syntax gate to run here. Printing "validate: ok" would be a lie.
    echo "  validate: unavailable on this build (see docs/decisions.md)"
}

# What apply would change, without applying it.
ghostty_diff() {
    ghostty_paths || return 1
    if [ "$GHOSTTY_PLATFORM" = darwin ]; then
        "$CZ" diff -- "$GHOSTTY_CFG" "$GHOSTTY_THEME" 2>/dev/null || true
        return 0
    fi
    # The Windows copy is not chezmoi-managed (windows/** is chezmoi-ignored and
    # mirrored by the sync), so diff the rendered template against what is live.
    local tmp; tmp="$(mktemp)"
    ghostty_render_windows > "$tmp" || { rm -f "$tmp"; return 1; }
    if [ -e "$GHOSTTY_CFG" ]; then
        diff -u "$GHOSTTY_CFG" "$tmp" && echo "ghostty config: up to date"
    else
        echo "ghostty config: $GHOSTTY_CFG would be created"
    fi
    rm -f "$tmp"
    if [ -e "$GHOSTTY_THEME" ]; then
        diff -u "$GHOSTTY_THEME" \
            "$SRC/windows/AppData/Local/ghostty/themes/vs-code-light-modern" \
            && echo "ghostty theme: up to date"
    else
        echo "ghostty theme: $GHOSTTY_THEME would be created"
    fi
}

ghostty_reload_hint() {
    if [ "$GHOSTTY_PLATFORM" = darwin ]; then
        echo "Reload Ghostty with Cmd+Shift+, (or restart it)."
    else
        echo "Reload with Ctrl+Shift+, (or restart it)."
    fi
}

# `off` is a real revert, not merely "stop managing": restore the newest backup
# if there is one, else remove our files so Ghostty falls back to its defaults.
# Deliberately NOT a .chezmoiignore removal rule or a sync deletion — those are
# evaluated on every machine and would wipe a hand-written config on a box that
# never opted in. This removes for THIS machine, because it was asked to.
ghostty_off() {
    ghostty_paths || return 1
    ts_ghostty_set off
    local b
    b="$(ls -1t "$GHOSTTY_DIR"/config.bak.* 2>/dev/null | head -1 || true)"
    if [ -n "$b" ] && [ -e "$b" ]; then
        cp -p -- "$b" "$GHOSTTY_CFG"
        echo "==> restored $GHOSTTY_CFG from $b"
    elif [ -e "$GHOSTTY_CFG" ]; then
        rm -f -- "$GHOSTTY_CFG"
        echo "==> removed $GHOSTTY_CFG (no backup existed; Ghostty uses its defaults)"
    fi
    [ -e "$GHOSTTY_THEME" ] && { rm -f -- "$GHOSTTY_THEME"; echo "==> removed $GHOSTTY_THEME"; }
    echo "==> ghostty config off. $(ghostty_reload_hint)"
    finish
}

ghostty_on() {
    ghostty_paths || return 1
    ts_ghostty_set on
    finish
    echo "==> ghostty config on. $(ghostty_reload_hint)"
}

# The mux has its own verbs (kill/restart/reset), so tstack config just hands off.
run_mux() {
    TERMINAL_STACK_DIR="$SRC" TERMINAL_STACK_CHEZMOI="$CZ" bash "$SRC/bootstrap/ts-mux.sh" "$@"
}

# WezTerm build info / channel switching. Hand-off like run_mux: the logic lives
# in bootstrap/ts-wezterm.sh so `tstack wezterm` works standalone too.
run_wezterm() {
    TERMINAL_STACK_DIR="$SRC" TERMINAL_STACK_CHEZMOI="$CZ" \
        bash "$SRC/bootstrap/ts-wezterm.sh" "$@"
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
        bash "$SRC/bootstrap/ts-stack.sh" restart headroom ||             echo "  $WARN headroom restart failed — run: tstack services restart headroom" >&2
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
    bash "$SRC/bootstrap/ts-agents.sh" "$tool" "$action" "$cursor_mode"
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
    if [ "$(uname -s)" = Darwin ]; then
        echo "  ghostty    : $(ts_ghostty_get)   (tstack config ghostty on|off)"
    fi
    echo "  wezterm    : $(ts_wezterm_channel)$(_ts_cfg_wezterm_built)   (tstack config wezterm)"
    echo "  headroom   : $(ts_agent_get headroomEnabled)   (Cursor: $(ts_agent_get headroomCursorMode))"
    echo "  caveman    : $(ts_agent_get cavemanEnabled)"
    echo "  agentmemory: $(ts_agent_get agentmemoryEnabled)"
}

menu() {
    while true; do
        echo
        show
        echo
        echo "  1) leader key   2) theme   3) tmux prefix   4) apps   5) re-apply   6) Claude TTS   7) WezTerm mux   8) session restore   9) coding agents   a) atuin   g) ghostty   t) WezTerm build   w) re-run wizard   q) quit"
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
            a|A) set_atuin "$(ts_prompt_atuin)" ;;
            g|G) ghostty_status ;;
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
            echo "usage: tstack config restore <on|off>" >&2; exit 2 ;; esac
        set_restore "$2" ;;
    atuin)
        case "${2:-}" in on|off) ;; *)
            echo "usage: tstack config atuin <on|off>" >&2; exit 2 ;; esac
        set_atuin "$2" ;;
    ghostty)
        case "${2:-status}" in
            on)     ghostty_on ;;
            off)    ghostty_off ;;
            status) ghostty_status ;;
            diff)   ghostty_diff ;;
            *) echo "usage: tstack config ghostty [on|off|status|diff]" >&2; exit 2 ;;
        esac ;;
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
        echo "  ghostty [on|off|status|diff]   managed Ghostty config (macOS only; off restores your backup)"
        echo "  memory [agentmemory|headroom|none|status]   which memory system runs — only ever one"
        echo "  agents [show|<headroom|caveman|agentmemory> on|off|status|repair|uninstall]"
        echo "  wezterm [status|changes|install <stable|nightly>|upgrade]  (see: tstack wezterm -h)"
        echo "  wizard           re-run the whole install questionnaire (TS_ASSUME_YES=1 to accept defaults)"
        echo "  agents headroom cursor <mcp|byok|off> | dashboard"
        ;;
    *) echo "tstack config: unknown command '$1' (try: show, leader, theme, tmux, apps, tts, mux, restore, atuin, ghostty, agents, wezterm, wizard)" >&2; exit 2 ;;
esac
