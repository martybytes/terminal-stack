#!/usr/bin/env bash
# ts-apply.sh — `chezmoi apply`, with the conflict question explained before it
# is asked, and answered safely when it is.
#
# Why this exists. Left to itself, chezmoi asks:
#
#     .zshrc has changed since chezmoi last wrote it?
#     > diff/overwrite/all-overwrite/skip/quit
#
# and that is the whole prompt. It does not say which of your edits is at
# stake, that `overwrite` discards it PERMANENTLY (chezmoi takes no backup on
# POSIX), or where personal settings are supposed to live so this stops
# happening. In practice the right answer is nearly always all-overwrite, and
# the user had no way to know that.
#
# Worse, the installers run `chezmoi apply -v </dev/null`. With no TTY chezmoi
# cannot ask, so a RE-INSTALL over any hand-edited file died with
#
#     chezmoi: .zshrc: could not open a new TTY: open /dev/tty: ...
#
# under `set -e`, aborting the install with nothing explaining why.
#
# So: find the conflicts first, explain them, and either resolve them with a
# backup or say exactly what to do. By the time `chezmoi apply` runs there is
# nothing left for it to ask about.
#
#   ts-apply.sh              interactive: explain, then ask per file
#   ts-apply.sh --overwrite  back up every conflict and take the stack's version
#   ts-apply.sh --check      report conflicts and exit; change nothing
#   ts-apply.sh -v           pass -v to the final apply
set -euo pipefail

_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_config.sh
. "$_dir/_config.sh"

OVERWRITE=0
CHECK=0
VERBOSE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --overwrite) OVERWRITE=1 ;;
        --check)     CHECK=1 ;;
        -v|--verbose) VERBOSE="-v" ;;
        -h|--help)
            sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "ts-apply: unknown option '$1'" >&2; exit 2 ;;
    esac
    shift
done

CZ="${TERMINAL_STACK_CHEZMOI:-}"
if [ -z "$CZ" ]; then
    if [ -x "$HOME/.local/bin/chezmoi" ]; then CZ="$HOME/.local/bin/chezmoi"
    elif command -v chezmoi >/dev/null 2>&1; then CZ="$(command -v chezmoi)"
    else echo "$WARN chezmoi not found on PATH." >&2; exit 1; fi
fi

# The files chezmoi will stop and ask about.
#
# Column 1 of `chezmoi status` is the destination against what chezmoi last
# wrote, and THAT is what triggers the prompt -- verified against chezmoi
# 2.72. Column 2 is the destination against the target, which is a plain
# pending change and applies silently. Filtering on both columns (as an earlier
# version did) happens to agree on today's cases but describes the wrong rule.
# Scripts are excluded: they are not files anyone hand-edits.
ts_apply_conflicts() {
    "$CZ" status --path-style absolute --exclude scripts 2>/dev/null |
        awk 'substr($0,1,1) != " " { print substr($0,4) }'
}

ts_apply_explain() {
    local n="$1"
    cat <<EXPLAIN

$WARN $n file(s) in your home directory differ from what terminal-stack last
   installed. Something changed them after the fact -- you, an editor, or
   another tool's installer appending a line.

   Applying replaces them, so each one is a decision:

     overwrite   take terminal-stack's version. Your current file is copied to
                 <file>.bak.YYYYMMDD first, so this is reversible.
     all         the same for every remaining file. Usually what you want.
     diff        show exactly what would change.
     merge       open chezmoi's merge tool. Note it edits the SOURCE CLONE,
                 which 'tstack update' then refuses to run from until you
                 commit or discard that change.
     quit        stop. Nothing is applied, nothing is backed up.

   Personal settings do not belong in these files -- the stack owns them
   outright and rewrites them on every update. Put your own in:

     ~/.zshrc.local                             (zsh; see dot_zshrc.local.example)
     Documents\\PowerShell\\profile.local.ps1     (Windows PowerShell)

   Those two are never managed and never overwritten, so anything you move
   there survives this question for good.

EXPLAIN
}

# Back up, then let chezmoi write its version. --force is what stops it asking
# again; the backup is what makes that safe, because a POSIX `chezmoi apply`
# writes no backup of its own.
ts_apply_take_ours() {
    local target bak
    for target in "$@"; do
        if bak="$(ts_backup_file "$target")"; then
            echo "    backed up $target -> $bak"
        fi
    done
    "$CZ" apply --force --no-tty -- "$@"
}

# The general apply, once nothing is left to ask about.
#
# The re-check is not paranoia: if anything still counted as a conflict, a plain
# `chezmoi apply` would stop and ask -- and in an installer, which has no stdin,
# that is the "could not open a new TTY" dead end this whole script exists to
# remove. Better to say which file and stop.
ts_apply_finish() {
    local remaining
    remaining="$(ts_apply_conflicts)"
    if [ -n "$remaining" ]; then
        echo "$WARN these files still differ, so the apply was not run:" >&2
        printf '%s\n' "$remaining" | sed 's/^/     /' >&2
        echo "   Re-run 'tstack apply', or 'tstack apply --overwrite' to take ours." >&2
        exit 4
    fi
    exec "$CZ" apply $VERBOSE
}

mapfile -t CONFLICTS < <(ts_apply_conflicts)

if [ "${#CONFLICTS[@]}" -eq 0 ]; then
    [ "$CHECK" -eq 1 ] && { echo "$INFO no conflicts; 'chezmoi apply' would not ask anything."; exit 0; }
    ts_apply_finish
fi

if [ "$CHECK" -eq 1 ]; then
    echo "$WARN ${#CONFLICTS[@]} file(s) would make chezmoi stop and ask:"
    printf '     %s\n' "${CONFLICTS[@]}"
    echo "   Resolve with: tstack apply            (asks, backs up, explains)"
    echo "                 tstack apply --overwrite (takes ours, backs yours up)"
    exit 4
fi

if [ "$OVERWRITE" -eq 1 ]; then
    echo "$INFO taking terminal-stack's version of ${#CONFLICTS[@]} file(s); yours are backed up first."
    ts_apply_take_ours "${CONFLICTS[@]}"
    ts_apply_finish
fi

# No controlling terminal: chezmoi cannot ask and neither can we. Say what
# happened and what to do, and change NOTHING -- a half-applied home directory
# is worse than an unapplied one. Exit 4 so a caller can tell "there are
# decisions waiting" from "the apply broke".
#
# ts_is_interactive tests /dev/tty, not stdin, and that distinction is the whole
# point here: the installers all run `</dev/null` deliberately, and the user is
# still sitting at a terminal we can reach.
if ! ts_is_interactive; then
    echo "$WARN ${#CONFLICTS[@]} file(s) were changed after terminal-stack last wrote them:" >&2
    printf '     %s\n' "${CONFLICTS[@]}" >&2
    cat >&2 <<NOTTY

   Nothing was applied, and nothing was changed. This run has no terminal to
   ask on, so the choice is yours to make deliberately:

     see what differs      chezmoi diff
     take ours (backs up)  tstack apply --overwrite
     decide file by file   tstack apply
     keep yours for good   move your edits into ~/.zshrc.local, which the
                           stack never manages, then re-run the above

NOTTY
    exit 4
fi

ts_apply_explain "${#CONFLICTS[@]}"

TAKE=()
ALL=0
for target in "${CONFLICTS[@]}"; do
    if [ "$ALL" -eq 1 ]; then TAKE+=("$target"); continue; fi
    while true; do
        echo "  Conflict: $target"
        ans="$(ts_tty_prompt '  [o]verwrite  [a]ll  [d]iff  [m]erge  [q]uit: ')"
        case "$ans" in
            o|O|overwrite)      TAKE+=("$target"); break ;;
            a|A|all)            ALL=1; TAKE+=("$target"); break ;;
            d|D|diff)           "$CZ" diff --no-pager -- "$target" || true ;;
            m|M|merge)
                "$CZ" merge -- "$target" || {
                    echo "$WARN merge failed; nothing was overwritten." >&2; exit 1; }
                if ! ts_apply_conflicts | grep -Fxq -- "$target"; then break; fi
                echo "$WARN $target still differs after the merge; choose again." ;;
            q|Q|quit|'')
                echo "$INFO stopped. Nothing was applied and nothing was backed up." >&2
                echo "   Re-run 'tstack apply' when you have decided, or move your edits" >&2
                echo "   into ~/.zshrc.local so this stops coming up." >&2
                exit 4 ;;
            *) echo "   Answer o, a, d, m or q." ;;
        esac
    done
done

if [ "${#TAKE[@]}" -gt 0 ]; then
    echo
    echo "$INFO taking terminal-stack's version of ${#TAKE[@]} file(s):"
    ts_apply_take_ours "${TAKE[@]}"
fi

ts_apply_finish
