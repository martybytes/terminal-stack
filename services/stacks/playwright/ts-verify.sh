#!/usr/bin/env bash
# ts-verify.sh — playwright: prove the MCP server actually drives a browser.
# Run by `ts-stack test`; safe to run by hand. Exit 0 = pass.
#
# Windows twin: ts-verify.ps1. Change one, change the other.
#
# A healthy container proves the process started, not that a browser can be
# opened in it. check-playwright.mjs opens two isolated sessions and closes
# them; this is the thin wrapper `ts-stack test` discovers by filename.
set -uo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ROOT="$(cd -- "$HERE/../.." && pwd -P)"
# shellcheck source=../../_stack.sh
. "$ROOT/_stack.sh"

if ! have node; then
    warn 'node is not installed — skipping the browser session check'
    exit 0
fi

if node "$HERE/check-playwright.mjs"; then
    pass 'two isolated browser sessions opened and closed'
    exit 0
fi
fail 'the MCP server did not complete a browser session'
exit 1
