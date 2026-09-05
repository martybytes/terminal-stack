#!/usr/bin/env bash
# _wizard.sh - the shim that runs the install questionnaire.
#
# The questionnaire itself is tstack/wizard/, one Python implementation that
# replaced 944 lines of bash here and ~800 of PowerShell in _config.ps1. Two
# implementations of fourteen questions had to be kept in agreement by hand, and
# had not been: the pwsh tick-list rejected a whole multi-answer where bash
# applied the valid tokens and warned about the rest.
#
# What is left here is the hand-off, because the four bootstraps are bash and
# need the answers as shell variables.

# The wizard is one Python program now (tstack/wizard/), replacing this file's
# bash and the Read-Ts* half of bootstrap/_config.ps1. It writes the answers to a
# file we source rather than to stdout: there is no $( ) boundary, so a stray
# line of output cannot corrupt an answer, and every TS_WIZ_* is exported
# unconditionally so `set -u` cannot fire on an unguarded read.
#
# Exit 3 is "the user quit at the review", which each caller already handles as
# cancelled. The `if` makes a non-zero exit non-fatal under `set -e`.
ts_wizard_collect() {
    local _wiz _rc=0 _python
    _python="$(ts_python 2>/dev/null || command -v python3 || true)"
    if [ -z "$_python" ]; then
        echo "!! python3 is required to run the install questionnaire." >&2
        return 1
    fi
    _wiz="$(mktemp "${TMPDIR:-/tmp}/tswiz.XXXXXX")" || return 1
    # The confirmed answer, not a re-detect. A caller that has already resolved
    # this -- possibly by ASKING -- must win: overwriting it here made an
    # explicit TS_HEADLESS_RESOLVED=1 silently ineffective, which is the kind of
    # override that looks like it worked.
    if [ -z "${TS_HEADLESS_RESOLVED:-}" ]; then
        if ts_is_headless 2>/dev/null; then TS_HEADLESS_RESOLVED=1; else TS_HEADLESS_RESOLVED=0; fi
    fi
    export TS_HEADLESS_RESOLVED
    local _root
    _root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
    # TERMINAL_STACK_DIR pins the clone for the Python side. Without it,
    # apps.catalog() falls back to paths.resolve_source_dir()'s fixed candidate
    # list -- and the wizard runs BEFORE chezmoi is configured, so on a clone at
    # any other path the catalog came back empty and the questionnaire offered no
    # tools at all, silently.
    #
    # TS_ASSUME_YES goes through the ENVIRONMENT, not as a flag: `${VAR:+...}`
    # tests non-empty, so TS_ASSUME_YES=0 skipped the review here while
    # `tstack wizard` (which reads the value, not its presence) still showed it.
    if TERMINAL_STACK_DIR="${TERMINAL_STACK_DIR:-$_root}" \
            "$_python" "$_root/tstack/main.py" wizard \
            --emit sh --out "$_wiz" \
            ${TS_WIZ_ASK_TERMINALS:+--ask-terminals}; then
        # shellcheck disable=SC1090
        . "$_wiz"
        rm -f "$_wiz"
    else
        _rc=$?
        rm -f "$_wiz"
        return "$_rc"
    fi
    echo "==> Config: leader=$TS_WIZ_LEADER theme=$TS_WIZ_THEME tmux-prefix=$TS_WIZ_TMUX wez-mux=$TS_WIZ_WEZ_MUX wez-restore=$TS_WIZ_WEZ_RESTORE cc-tts=$TS_WIZ_CC_TTS headroom=$TS_WIZ_HEADROOM caveman=$TS_WIZ_CAVEMAN agentmemory=$TS_WIZ_AGENTMEMORY"
    echo "==> Apps: ${TS_WIZ_APPS:-<none>}"
    return 0
}
