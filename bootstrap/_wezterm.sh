#!/usr/bin/env bash
# _wezterm.sh - shims onto `tstack wezterm`. Sourced (never executed) by
# _wizard.sh, mac-bootstrap.sh, _common-debian.sh and ts-config.sh. Do not `exit`
# here - return non-zero.
#
# THIS FILE HOLDS NO LOGIC. It used to hold 446 lines of it, five of whose
# functions existed only to pipe JSON into an embedded `python3 -c` heredoc; that
# now lives in tstack/commands/wezterm.py, once, and these are the four-line
# wrappers the installers still need because they run before that package is on
# any path they know about.
#
# Everything here fails OPEN and SILENT, exactly as before: a report that degrades
# to nothing is fine, one that errors a shell during an install is not.

: "${INFO:=$'\033[1;34m==>\033[0m'}"
: "${WARN:=$'\033[1;33m!!\033[0m'}"

# The interpreter and the entry point. TERMINAL_STACK_DIR wins, then chezmoi's
# view, then this file's own location - the installers set none of them reliably,
# and a shim that cannot find the CLI must degrade rather than fail.
_ts_wez_entry() {
    local src="${TERMINAL_STACK_DIR:-}"
    if [ -z "$src" ] && [ -n "${SRC:-}" ]; then src="$SRC"; fi
    if [ -z "$src" ]; then
        src="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd -P)" || return 1
    fi
    [ -f "$src/tstack/main.py" ] || return 1
    printf '%s\n' "$src/tstack/main.py"
}

_ts_wez() {
    local entry python
    entry="$(_ts_wez_entry)" || return 1
    for python in python3 python; do
        command -v "$python" >/dev/null 2>&1 || continue
        PYTHONIOENCODING=utf-8 "$python" "$entry" wezterm "$@"
        return $?
    done
    return 1
}

# "version|date|hash", or non-zero when WezTerm is not installed.
ts_wezterm_installed() { _ts_wez installed; }

# stable | nightly | unknown | none
ts_wezterm_channel() { _ts_wez channel 2>/dev/null || echo none; }

# YYYYMMDD -> YYYY-MM-DD
ts_wez_fmt_date() {
    case "${1:-}" in
        [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9])
            printf '%s-%s-%s\n' "${1:0:4}" "${1:4:2}" "${1:6:2}" ;;
        *) printf '%s\n' "${1:-}" ;;
    esac
}

# A wizard selection ("wezterm-nightly ghostty") -> the WezTerm channel, or "".
ts_terminals_channel() { _ts_wez terminals-channel "${1:-}" 2>/dev/null || echo ""; }

ts_wezterm_status()        { _ts_wez status; }
ts_wezterm_prompt_intro()  { _ts_wez intro 2>/dev/null || true; }
ts_wezterm_install()       { _ts_wez install "${1:-}"; }
ts_wezterm_upgrade()       { _ts_wez upgrade; }
ts_wezterm_update_available() { _ts_wez update-available 2>/dev/null; }
