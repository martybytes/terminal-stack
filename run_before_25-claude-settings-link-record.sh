#!/usr/bin/env bash
# Record whether ~/.claude/settings.json is a SYMLINK, before the apply eats it.
#
# THE MEASUREMENT THIS EXISTS FOR
#
# `dot_claude/modify_settings.json.tmpl` is a chezmoi modify_ script: chezmoi
# hands it the live file on stdin and writes back what it prints. The script
# never touches the filesystem -- chezmoi does -- and chezmoi writes a REGULAR
# FILE. Probed directly (archlinux + chezmoi 2.72, a symlinked target and a
# one-line modify_ script):
#
#     before   ~/.claude/settings.json -> /root/real/settings.json
#     after    -rw-r--r-- ~/.claude/settings.json   {"model":"opus","theme":"spliced"}
#              /root/real/settings.json             {"model":"opus"}
#
# The splice succeeded and the link is gone. Worse than losing the link: the
# file the OTHER tool tracks is still there, still referenced by its repo, and
# now permanently out of date -- with nothing anywhere saying so. On this fleet
# that other tool is omarchy-dots, whose stow tree owns ~/.claude/settings.json
# and syncs it to every machine.
#
# So the write has to go THROUGH the link. chezmoi cannot be asked to do that,
# and the modify_ script cannot do it either (it only produces bytes). The pair
# of scripts around the apply can: this one remembers the link, and
# run_after_25 puts the spliced content in the real file and restores it.
#
# NOT Omarchy-specific, deliberately. Any dotfile manager that symlinks this
# file -- stow, GNU stow, yadm, a hand-rolled bootstrap -- hits exactly this,
# and none of them is easier to detect than the symlink itself.

set -u

TARGET="$HOME/.claude/settings.json"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/terminal-stack"
RECORD="$STATE_DIR/claude-settings-symlink"

# Always clear first. A stale record from a previous apply -- when the file WAS
# a link and now legitimately is not -- would otherwise make run_after_25
# recreate a link the user deliberately replaced.
rm -f "$RECORD"

[ -L "$TARGET" ] || exit 0

# The link's destination, absolute, walked by hand.
#
# NOT `readlink -f`: that is GNU-only, and this script runs on macOS on every
# apply. BSD readlink had no -f for years and `realpath` is not on older macOS
# either -- the same rule bootstrap/_smb.sh and services/_stack.sh already write
# down. The failure would have been silent and macOS-only: DEST empty, exit 0,
# no record, and the restore below simply never runs, so a macOS user whose
# ~/.claude/settings.json is a symlink (yadm and stow are common there too) gets
# exactly the clobber this pair exists to prevent, with nothing to see.
#
# Bounded at 40 hops. A symlink CYCLE would otherwise spin here forever, and an
# apply that hangs is worse than an apply that skips a nicety.
p="$TARGET"
hops=0
while [ -L "$p" ]; do
    hops=$((hops + 1))
    if [ "$hops" -gt 40 ]; then
        echo "!! ~/.claude/settings.json: symlink chain too deep (a cycle?); not recorded." >&2
        exit 0
    fi
    t="$(readlink -- "$p" 2>/dev/null || true)"
    [ -n "$t" ] || exit 0
    case "$t" in
        /*) p="$t" ;;
        *)  p="$(dirname -- "$p")/$t" ;;
    esac
done

# Absolute and free of `..`, so the restore writes where we think it does. The
# directory is resolved with `cd -P`; the basename is kept as-is because the
# file itself is what we are after, not whatever it might further resolve to.
[ -f "$p" ] || exit 0
DEST="$(cd -- "$(dirname -- "$p")" 2>/dev/null && pwd -P)/$(basename -- "$p")"
[ -f "$DEST" ] || exit 0

mkdir -p "$STATE_DIR"
printf '%s\n' "$DEST" > "$RECORD"
