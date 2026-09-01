#!/usr/bin/env bash
# Keep the Omarchy integration current, on every apply.
#
# Same shape as run_after_90-sync-windows.sh, and for the same reason: the thing
# it maintains lives OUTSIDE chezmoi's target tree, so chezmoi cannot notice it
# has drifted. Here that is three files under ~/.config/omarchy -- a WezTerm
# theme template and two event hooks -- which are additive files in Omarchy's own
# extension points rather than anything chezmoi manages.
#
# It self-no-ops everywhere else, which is what lets the same source tree stay
# correct on macOS, WSL, Debian and plain Arch. The two guards are separate on
# purpose: not-Omarchy is silent (there is nothing to say on a Mac), while
# Omarchy-but-no-clone is worth a line, because that is a broken install rather
# than a different platform.
#
# `tstack omarchy off` writes a sentinel that the sync respects, so this never
# reinstates files someone deliberately removed.

set -u

[ -r /etc/os-release ] || exit 0
grep -qi '^ID=omarchy' /etc/os-release 2>/dev/null || exit 0

command -v python3 >/dev/null 2>&1 || exit 0

# The clone, resolved the same way the hooks resolve it. chezmoi knows where the
# source tree is, and this script IS in it -- but a run_after script is executed
# from a temporary copy, so $0's directory is not the clone.
TS_CLONE=""
for d in "${TERMINAL_STACK_DIR:-}" \
         "${XDG_DATA_HOME:-$HOME/.local/share}/terminal-stack" \
         "$HOME/.local/share/terminal-stack"; do
    [ -n "$d" ] && [ -f "$d/tstack/main.py" ] && TS_CLONE="$d" && break
done
if [ -z "$TS_CLONE" ]; then
    echo "!! omarchy integration: no terminal-stack clone found; skipped." >&2
    echo "   Run 'tstack doctor' (or set TERMINAL_STACK_DIR) and re-apply." >&2
    exit 0
fi

# Non-fatal by construction. An apply must not fail because a desktop
# integration could not be refreshed -- the dotfiles are the deliverable, this
# is a convenience on top of them.
python3 "$TS_CLONE/tstack/main.py" omarchy sync || true
