#!/usr/bin/env bash
# Put the spliced ~/.claude/settings.json back behind its symlink.
#
# Pairs with run_before_25-claude-settings-link-record.sh, which recorded where
# the link pointed before chezmoi replaced it with a regular file. See that
# script for the measurement, and for why the two basenames must differ.
#
# The move is deliberately in this order:
#
#   1. copy the spliced content over the REAL file (the one the other tool
#      tracks, so its next `git status` shows the change honestly)
#   2. only then replace our regular file with the link again
#
# Backwards, and a failure between the two steps leaves the link pointing at
# stale content while the spliced version is deleted. This way the worst case is
# a correct file with no link, which is exactly the state chezmoi left and which
# the next apply repairs.
#
# Non-fatal throughout: an apply must not fail because somebody else's symlink
# could not be restored. The dotfiles are the deliverable.

set -u

TARGET="$HOME/.claude/settings.json"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/terminal-stack"
RECORD="$STATE_DIR/claude-settings-symlink"

[ -f "$RECORD" ] || exit 0
DEST="$(cat "$RECORD" 2>/dev/null || true)"
rm -f "$RECORD"

[ -n "$DEST" ] || exit 0

# Nothing to do if the apply did not in fact replace the link. chezmoi's
# behaviour here is a fact about chezmoi, not a promise, and a future version
# that writes through links on its own must not make this script undo its work.
if [ -L "$TARGET" ]; then
    exit 0
fi
[ -f "$TARGET" ] || exit 0

# The destination has to still be a real file we can write. If the other tool's
# repo moved or was deleted mid-apply, leave the regular file alone and say so:
# a settings.json that exists and is correct beats a link into nothing.
if [ ! -f "$DEST" ] || [ ! -w "$DEST" ]; then
    echo "!! ~/.claude/settings.json was a symlink to $DEST, which is no longer writable." >&2
    echo "   The spliced file is in place as a regular file; the link was not restored." >&2
    exit 0
fi

# Always copy, even when the content is unchanged. The obvious optimisation
# here was `cmp -s` first -- and `cmp` lives in diffutils, which a minimal Arch
# container does not have: it failed with "command not found" on the very first
# end-to-end run. There is nothing to buy anyway. git compares content, not
# mtimes, so an identical write leaves the other tool`s repo clean, and one cp
# of a settings file is not a cost worth a dependency.
if ! cp -- "$TARGET" "$DEST"; then
    echo "!! could not write ~/.claude/settings.json through to $DEST; link not restored." >&2
    exit 0
fi
rm -f "$TARGET"
if ! ln -s "$DEST" "$TARGET"; then
    # The content is safe in $DEST; put a copy back so Claude Code still has a
    # file to read. Losing the link is survivable, losing the file is not.
    cp -- "$DEST" "$TARGET" 2>/dev/null || true
    echo "!! restored ~/.claude/settings.json content but could not recreate the symlink." >&2
    exit 0
fi
echo "==> ~/.claude/settings.json: spliced through its symlink to $DEST"
