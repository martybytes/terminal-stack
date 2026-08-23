#!/usr/bin/env bash
# run_before_20-backup-ghostty.sh — preserve a pre-existing Ghostty config before
# the first managed apply overwrites it.
#
# Why this exists: on POSIX, `chezmoi apply` overwrites a $HOME file with NO
# backup. The repo's .bak.YYYYMMDD[.N] convention only fires in the Windows sync
# hook and the merge helpers, so a hand-written ~/.config/ghostty/config would
# vanish silently the first time this stack managed it. CLAUDE.md's rule is
# explicit: anything that overwrites a user file writes a backup first.
#
# It also makes `ts-config ghostty off` a real revert rather than a delete —
# that command restores the newest backup this script leaves behind.
#
# Runs before every apply, but does nothing once the file is ours: the marker
# check means a managed config is never backed up over and over.
set -eu

cfg="${HOME}/.config/ghostty/config"

# macOS only, matching the .chezmoiignore gate. Nothing to do elsewhere.
[ "$(uname -s 2>/dev/null || true)" = Darwin ] || exit 0
[ -e "$cfg" ] || exit 0

# Already ours? Then chezmoi is only re-rendering its own file; a backup here
# would produce a new .bak on every single apply.
if head -20 "$cfg" 2>/dev/null | grep -q 'managed by terminal-stack'; then
    exit 0
fi

stamp="$(date +%Y%m%d)"
base="$cfg.bak.$stamp"
bak="$base"
n=1
while [ -e "$bak" ]; do
    bak="$base.$n"
    n=$((n + 1))
done

# cp -p, not mv: leave the original in place so a failed apply changes nothing.
if cp -p -- "$cfg" "$bak" 2>/dev/null; then
    printf '==> backed up %s -> %s\n' "$cfg" "$bak"
fi
