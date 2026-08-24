#!/usr/bin/env bash
# check-playwright.sh — functionally verify the local Playwright MCP server,
# browser automation, and per-client isolation.
# macOS/Linux twin of check-playwright.ps1 (canonical). Port changes both ways.
#
# Usage:  ./check-playwright.sh
# When:   After starting or upgrading the Playwright stack, or when an agent
#         cannot use its browser tools.
# Note:   Read-only diagnostic. It creates two temporary isolated browser
#         sessions and closes them. All the real logic lives in
#         check-playwright.mjs, which is already platform-neutral and shared
#         with the .ps1 — this is only the prerequisite check and the wrapper.
set -euo pipefail

_self="${BASH_SOURCE[0]}"
while [ -L "$_self" ]; do
    _d="$(cd -- "$(dirname -- "$_self")" && pwd)"; _self="$(readlink "$_self")"
    case "$_self" in /*) ;; *) _self="$_d/$_self" ;; esac
done
SCRIPT_DIR="$(cd -- "$(dirname -- "$_self")" && pwd -P)"
# shellcheck source=../../_stack.sh
. "$SCRIPT_DIR/../../_stack.sh"

while [ $# -gt 0 ]; do
    arg="$(tss_normalise_flag "$1")"
    if tss_parse_common_flag "$arg" "${2:-}"; then shift "$TSS_FLAG_CONSUMED"; continue; fi
    die "unknown option: $1 (try --help)"
done

check_script="$SCRIPT_DIR/check-playwright.mjs"

need node 'node not found on PATH.'
[ -f "$check_script" ] || die "Missing check script: $check_script"

# Deliberately not `exec node ...`: the tailored failure message below is the
# point of this wrapper.
# Capture the status first: inside `if ! cmd; then`, $? is the status of the
# negated test, not of node.
rc=0
node "$check_script" || rc=$?
[ "$rc" = 0 ] || die "Playwright MCP functional check failed with exit code $rc."
