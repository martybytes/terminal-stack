#!/usr/bin/env bash
# ts-doctor.sh — diagnose and repair the terminal-stack install. Driven by the
# `tstack doctor` shell wrapper (zsh) and runnable standalone. On Windows the pwsh
# Test-TerminalStack / Repair-TerminalStack are the counterparts.
#
# Usage:
#   tstack doctor                 run health checks (read-only)
#   tstack doctor --repair        diagnose, then fix issues (repoint sourceDir,
#                             re-apply, offer to clean up old clones/leftovers)
#   tstack doctor --quiet         checks only, suppress the per-check "ok" lines
#
# Run from WSL in a combined WSL+Windows setup — it repoints the WSL chezmoi
# source of truth. Exit status mirrors the health (0 healthy, 1 issues found).
set -euo pipefail

CZ="${TERMINAL_STACK_CHEZMOI:-}"
if [ -z "$CZ" ]; then
    if [ -x "$HOME/.local/bin/chezmoi" ]; then CZ="$HOME/.local/bin/chezmoi"
    elif command -v chezmoi >/dev/null 2>&1; then CZ="$(command -v chezmoi)"
    else echo "tstack doctor: chezmoi not found on PATH." >&2; exit 1; fi
fi
export TERMINAL_STACK_CHEZMOI="$CZ"

# Locate this script's dir to source the libs (works via symlink/source-path too).
DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=_config.sh
. "$DIR/_config.sh"
# shellcheck source=_wizard.sh
. "$DIR/_wizard.sh"
# shellcheck source=_cleanup.sh
. "$DIR/_cleanup.sh"
# shellcheck source=_doctor.sh
. "$DIR/_doctor.sh"

case "${1:-}" in
    ""|check)        ts_doctor ;;
    --quiet|-q)      TS_DOCTOR_QUIET=1 ts_doctor ;;
    --repair|repair|fix)
                     # Pass an explicit desired clone if the caller set one.
                     ts_repair "${TERMINAL_STACK_DIR:-}" ;;
    -h|--help|help)  sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) echo "tstack doctor: unknown command '$1' (try: --repair, --quiet, --help)" >&2; exit 2 ;;
esac
