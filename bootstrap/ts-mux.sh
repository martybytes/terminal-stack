#!/usr/bin/env bash
# ts-mux.sh — turn the WezTerm multiplexer domain on/off and drive the live mux
# server. Driven by the `ts-mux` shell wrapper (zsh) and runnable standalone.
#
# The pwsh `ts-mux` (Invoke-TsMux in $PROFILE) is the PARALLEL implementation for
# Windows-standalone installs, not a wrapper: change one, change the other, and
# keep the -h output byte-identical.
#
# The setting lives with the rest of the saved config — chezmoi [data]
# `weztermMux`, mirrored to %LOCALAPPDATA%\terminal-stack\config.json — and
# renders into .wezterm.lua as `local MUX_ENABLED = '<on|off>' == 'on'`
# (__WEZ_MUX__ on the Windows mirror). Nothing here edits .wezterm.lua directly.
#
# On WSL the GUI, the mux server and the rendered config are all on the WINDOWS
# side, so the process commands go through interop (tasklist.exe / taskkill.exe /
# wezterm.exe), never the Linux process table.
set -euo pipefail

HELP='ts-mux — WezTerm multiplexer domain: keep panes alive when the GUI dies.

Usage:
  ts-mux [status]   the setting, the mux server, and the panes it hosts
  ts-mux on         host panes in the mux domain (unix domain "main")
  ts-mux off        spawn panes locally (the default)
  ts-mux list       wezterm cli list — every pane the mux knows about
  ts-mux kill       stop wezterm-mux-server       [KILLS EVERY PANE IT HOSTS]
  ts-mux restart    stop it, then start a fresh one, so it re-reads the config
  ts-mux reset      back to default: off + re-apply + kill + clear stale sockets
  ts-mux -h         this help

  -y, --yes         skip the confirmation for kill / restart / reset

With the mux on, your shells run inside wezterm-mux-server instead of the GUI, so
a GUI crash leaves every pane (and everything running in it) alive and relaunching
WezTerm reattaches. The costs are why it is off by default: the mux server loads
its OWN copy of .wezterm.lua, so a config change needs "ts-mux restart" — which
kills every pane — and not just a GUI reload; and the Claude per-pane tint needs
pane:inject_output, which mux panes do not have.

on/off re-render .wezterm.lua and take effect for newly spawned tabs; relaunch
WezTerm for a clean switch. Panes already hosted in the mux stay there until you
close them or run "ts-mux kill". The setting is saved with the rest of the config
(chezmoi [data] weztermMux / config.json weztermMux) and shown by "ts-config show".'

# Help before anything else: `ts-mux -h` must work on a box where the clone or
# chezmoi is the very thing that is broken.
case "${1:-}" in -h|--help|help) printf '%s
' "$HELP"; exit 0 ;; esac

CZ="${TERMINAL_STACK_CHEZMOI:-}"
if [ -z "$CZ" ]; then
    if [ -x "$HOME/.local/bin/chezmoi" ]; then CZ="$HOME/.local/bin/chezmoi"
    elif command -v chezmoi >/dev/null 2>&1; then CZ="$(command -v chezmoi)"
    else echo "ts-mux: chezmoi not found on PATH." >&2; exit 1; fi
fi
SRC="${TERMINAL_STACK_DIR:-$("$CZ" source-path 2>/dev/null || true)}"
if [ ! -d "$SRC/bootstrap" ]; then
    echo "ts-mux: cannot locate the terminal-stack clone (set TERMINAL_STACK_DIR)." >&2
    exit 1
fi
# shellcheck source=_config.sh
. "$SRC/bootstrap/_config.sh"
# shellcheck source=_wizard.sh
. "$SRC/bootstrap/_wizard.sh"

ASSUME_YES=0

# ── platform + binary resolution ────────────────────────────────────────────────
ts_is_wsl() { [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; }

# The `wezterm` CLI (Windows .exe under WSL — the mux it talks to is the Windows one).
wez_cli() {
    if ts_is_wsl; then
        command -v wezterm.exe >/dev/null 2>&1 && { command -v wezterm.exe; return 0; }
        [ -x "/mnt/c/Program Files/WezTerm/wezterm.exe" ] \
            && { echo "/mnt/c/Program Files/WezTerm/wezterm.exe"; return 0; }
        return 1
    fi
    command -v wezterm >/dev/null 2>&1 && { command -v wezterm; return 0; }
    return 1
}

mux_bin() {
    if ts_is_wsl; then
        command -v wezterm-mux-server.exe >/dev/null 2>&1 && { command -v wezterm-mux-server.exe; return 0; }
        [ -x "/mnt/c/Program Files/WezTerm/wezterm-mux-server.exe" ] \
            && { echo "/mnt/c/Program Files/WezTerm/wezterm-mux-server.exe"; return 0; }
        return 1
    fi
    command -v wezterm-mux-server >/dev/null 2>&1 && { command -v wezterm-mux-server; return 0; }
    return 1
}

# PIDs of every running mux server, one per line (empty when none).
mux_pids() {
    if ts_is_wsl; then
        local tl=/mnt/c/Windows/System32/tasklist.exe
        [ -x "$tl" ] || return 0
        # CSV so a localized "INFO: No tasks…" line can't be mistaken for a row.
        "$tl" /FI "IMAGENAME eq wezterm-mux-server.exe" /NH /FO CSV 2>/dev/null \
            | tr -d '\r' | awk -F'","' '/^"wezterm-mux-server\.exe"/ { print $2 }'
        return 0
    fi
    pgrep -f '(^|/)wezterm-mux-server' 2>/dev/null || true
}

# The Windows username, for the /mnt/c paths below. Same order as the sync hook:
# chezmoi [data] first, then cmd.exe interop — a clone installed before the
# bootstrap started recording windowsUsername has only the second.
win_user() {
    local wu; wu="$(ts_data_get windowsUsername 2>/dev/null || true)"
    [ -n "$wu" ] && { echo "$wu"; return 0; }
    if [ -x /mnt/c/Windows/System32/cmd.exe ]; then
        wu="$(/mnt/c/Windows/System32/cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n' || true)"
        [ -n "$wu" ] && { echo "$wu"; return 0; }
    fi
    return 1
}

# The RENDERED config the GUI actually loads — used to spot a saved setting that
# has not been applied yet.
rendered_cfg() {
    if ts_is_wsl; then
        local wu; wu="$(win_user)" || return 1
        [ -f "/mnt/c/Users/$wu/.wezterm.lua" ] \
            && { echo "/mnt/c/Users/$wu/.wezterm.lua"; return 0; }
        return 1
    fi
    [ -f "$HOME/.wezterm.lua" ] && { echo "$HOME/.wezterm.lua"; return 0; }
    return 1
}

rendered_mux() {
    local f v; f="$(rendered_cfg)" || return 1
    v="$(sed -n "s/^local MUX_ENABLED = '\(on\|off\)'.*/\1/p" "$f" | head -n1)"
    [ -n "$v" ] && { echo "$v"; return 0; }
    # A config rendered before this toggle existed: the domain was unconditional.
    if grep -q "^config.default_domain = 'main'" "$f"
    then echo "on (pre-toggle)"; else echo "off (pre-toggle)"; fi
}

# WezTerm's runtime dirs, where a crashed server can leave a stale socket behind.
sock_dirs() {
    [ -n "${XDG_RUNTIME_DIR:-}" ] && echo "$XDG_RUNTIME_DIR/wezterm"
    echo "$HOME/.local/share/wezterm"
    if ts_is_wsl; then
        local wu; wu="$(win_user 2>/dev/null || true)"
        [ -n "$wu" ] && echo "/mnt/c/Users/$wu/AppData/Local/wezterm"
    fi
    true  # an empty username above must not trip `set -e`
}

# ── plumbing ────────────────────────────────────────────────────────────────────
finish() {
    echo "==> applying…"
    "$CZ" apply
    echo "==> done."
}

confirm() {  # confirm <prompt>
    [ "$ASSUME_YES" = 1 ] && return 0
    if ! { true > /dev/tty; } 2>/dev/null; then
        echo "ts-mux: no terminal to confirm on — re-run with -y if you mean it." >&2
        return 1
    fi
    local a; a="$(ts_tty_prompt "$1 [y/N]: ")"
    case "$a" in y|Y|yes|YES) return 0 ;; *) echo "aborted."; return 1 ;; esac
}

# ── subcommands ─────────────────────────────────────────────────────────────────
show_status() {
    local setting rendered pids cli panes
    setting="$(ts_wez_mux_get)"
    echo "ts-mux:"
    echo "  setting  : $setting   (saved as weztermMux)"

    rendered="$(rendered_mux 2>/dev/null || true)"
    if [ -z "$rendered" ]; then
        echo "  rendered : (no .wezterm.lua found — run 'chezmoi apply')"
    elif [ "$rendered" != "$setting" ]; then
        echo "  rendered : $rendered   !! stale — run 'chezmoi apply' (Windows: sync-windows.ps1)"
    else
        echo "  rendered : $rendered   ($(rendered_cfg))"
    fi

    pids="$(mux_pids)"
    if [ -n "$pids" ]; then
        echo "  server   : running (pid $(echo "$pids" | tr '\n' ' ' | sed 's/ $//'))"
    else
        echo "  server   : not running"
    fi

    if cli="$(wez_cli 2>/dev/null)"; then
        panes="$("$cli" cli list 2>/dev/null | tail -n +2 | grep -c . || true)"
        [ -n "$panes" ] && echo "  panes    : $panes   ('ts-mux list' for detail)"
    fi

    if [ "$setting" = off ] && [ -n "$pids" ]; then
        echo "  note     : panes spawned while the mux was on are still hosted by it;"
        echo "             they stay alive until you close them or run 'ts-mux kill'."
    fi
}

set_mux() {  # set_mux <on|off>
    local want="$1" cur; cur="$(ts_wez_mux_get)"
    if [ "$cur" = "$want" ]; then
        echo "==> mux already $want; re-applying anyway to refresh the rendered config."
    fi
    ts_wez_mux_set "$want"
    finish
    if [ "$want" = on ]; then
        echo "    Panes now spawn into the mux domain 'main'. Relaunch WezTerm for a"
        echo "    clean switch; 'ts-mux status' shows the server once it starts."
    else
        echo "    New tabs spawn locally again. Panes already hosted by the mux stay"
        echo "    there until you close them or run 'ts-mux kill'."
    fi
}

do_list() {
    local cli
    cli="$(wez_cli)" || { echo "ts-mux: wezterm CLI not found on PATH." >&2; return 1; }
    "$cli" cli list
}

do_kill() {
    local pids
    pids="$(mux_pids)"
    if [ -z "$pids" ]; then echo "==> wezterm-mux-server is not running."; return 0; fi
    confirm "Stop wezterm-mux-server (pid $(echo "$pids" | tr '\n' ' ' | sed 's/ $//'))? Every pane it hosts dies — including this one, if you are in one" || return 1
    if ts_is_wsl; then
        /mnt/c/Windows/System32/taskkill.exe /IM wezterm-mux-server.exe /F >/dev/null 2>&1 || true
    else
        pkill -f '(^|/)wezterm-mux-server' 2>/dev/null || true
        local i
        for i in 1 2 3 4 5; do [ -z "$(mux_pids)" ] && break; sleep 1; done
        [ -n "$(mux_pids)" ] && pkill -9 -f '(^|/)wezterm-mux-server' 2>/dev/null
        true  # a still-empty pid list above must not trip `set -e`
    fi
    if [ -n "$(mux_pids)" ]; then
        echo "!! wezterm-mux-server is still running — kill it by hand." >&2
        return 1
    fi
    echo "==> wezterm-mux-server stopped."
}

do_start() {
    local bin
    if [ -n "$(mux_pids)" ]; then echo "==> wezterm-mux-server is already running."; return 0; fi
    bin="$(mux_bin)" || {
        echo "ts-mux: wezterm-mux-server not found — relaunch WezTerm and it will spawn one." >&2
        return 1
    }
    echo "==> starting wezterm-mux-server --daemonize"
    "$bin" --daemonize >/dev/null 2>&1 \
        || { echo "ts-mux: start failed — relaunch WezTerm and it will spawn one." >&2; return 1; }
}

clear_sockets() {
    local d f n=0
    while IFS= read -r d; do
        [ -n "$d" ] && [ -d "$d" ] || continue
        for f in "$d"/sock "$d"/gui-sock-*; do
            [ -e "$f" ] || continue
            rm -f -- "$f" && n=$((n + 1))
        done
    done < <(sock_dirs)
    echo "==> cleared $n stale socket file(s)"
}

do_reset() {
    confirm "Reset the WezTerm mux: set it off, re-apply, stop the server (every pane it hosts dies) and clear stale sockets" || return 1
    ASSUME_YES=1
    ts_wez_mux_set off
    finish
    do_kill || true
    clear_sockets
    echo "==> mux reset to the default (off)."
}

# ── dispatch ────────────────────────────────────────────────────────────────────
CMD=""
for a in "$@"; do
    case "$a" in
        -y|--yes) ASSUME_YES=1 ;;
        -h|--help|help) printf '%s\n' "$HELP"; exit 0 ;;
        -*) echo "ts-mux: unknown flag '$a' (try: ts-mux -h)" >&2; exit 2 ;;
        *) [ -z "$CMD" ] && CMD="$a" || { echo "ts-mux: unexpected argument '$a'" >&2; exit 2; } ;;
    esac
done

case "$CMD" in
    ""|status) show_status ;;
    on)        set_mux on ;;
    off)       set_mux off ;;
    list)      do_list ;;
    kill)      do_kill ;;
    restart)   do_kill && do_start ;;
    reset)     do_reset ;;
    *) echo "ts-mux: unknown command '$CMD' (status, on, off, list, kill, restart, reset)" >&2; exit 2 ;;
esac
