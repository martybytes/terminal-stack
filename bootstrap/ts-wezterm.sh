#!/usr/bin/env bash
# ts-wezterm.sh — which WezTerm build you have, what upstream has, what changed
# in between, and switching channel. Driven by `tstack config wezterm` and runnable
# standalone.
#
# WezTerm ships two channels and this stack installs NEITHER automatically. The
# wizard asks at install, tstack update offers when something newer exists, and this
# command changes it on demand. Upstream's newest stable is 20240203 (February
# 2024, no cut since), so nightly is the pre-selected answer — not the forced one.
#
# The channel is not a saved setting: it is read back from the package manager
# (brew cask / dpkg package), which cannot drift out of sync with what is
# actually installed. See docs/decisions.md § "Why the WezTerm channel is a
# question, and why it is not a saved setting".
set -euo pipefail

HELP='tstack wezterm — WezTerm build info, upstream comparison, and channel switching.

Usage:
  tstack wezterm [status]        installed build + date, latest per channel, what changed
  tstack wezterm changes         the full upstream changelog since your build (paged)
  tstack wezterm install <chan>  stable | nightly — switches channel, removing the other
  tstack wezterm upgrade         refresh the channel you are already on; never switches
  tstack wezterm -h              this help

Release names are <date>-<time>-<githash>, so your build date comes from
`wezterm --version` with no network call. Latest-stable comes from the GitHub
release; latest-nightly from the build date of the nightly asset for THIS
platform, because the nightly tag is a rolling one whose own date is meaningless
and whose assets are rebuilt per platform at different times.

"What changed" is sliced out of upstream'"'"'s own docs/changelog.md at the heading
matching your version — no summarising, just their notes and a count.

Nothing here runs on its own: installs and channel switches only happen when you
ask for them.'

# Help before anything else: `tstack wezterm -h` must work on a box where the clone
# or chezmoi is the very thing that is broken.
case "${1:-}" in -h|--help|help) printf '%s\n' "$HELP"; exit 0 ;; esac

CZ="${TERMINAL_STACK_CHEZMOI:-}"
if [ -z "$CZ" ]; then
    if [ -x "$HOME/.local/bin/chezmoi" ]; then CZ="$HOME/.local/bin/chezmoi"
    elif command -v chezmoi >/dev/null 2>&1; then CZ="$(command -v chezmoi)"
    else echo "tstack wezterm: chezmoi not found on PATH." >&2; exit 1; fi
fi
SRC="${TERMINAL_STACK_DIR:-$("$CZ" source-path 2>/dev/null || true)}"
if [ ! -d "$SRC/bootstrap" ]; then
    echo "tstack wezterm: cannot locate the terminal-stack clone (set TERMINAL_STACK_DIR)." >&2
    exit 1
fi
# shellcheck source=_wezterm.sh
. "$SRC/bootstrap/_wezterm.sh"

show_changes() {
    local inst ver text
    inst="$(ts_wezterm_installed 2>/dev/null || true)"
    ver="${inst%%|*}"
    if [ -z "$ver" ]; then
        echo "tstack wezterm: WezTerm is not installed, so there is no build to compare against." >&2
        return 1
    fi
    if ! text="$(ts_wez_changes_text "$ver")"; then
        echo "tstack wezterm: could not fetch upstream's changelog (offline?)." >&2
        return 1
    fi
    if [ -z "$text" ]; then
        echo "$INFO Nothing newer than $ver in upstream's changelog."
        return 0
    fi
    # Same reader the `doc` knowledge base uses, so long output behaves the same
    # way everywhere in the stack.
    if command -v glow >/dev/null 2>&1; then
        printf '# WezTerm changes since %s\n\n%s\n' "$ver" "$text" | glow -p - 2>/dev/null && return 0
    fi
    printf '# WezTerm changes since %s\n\n%s\n' "$ver" "$text" | ${PAGER:-less -RF}
}

case "${1:-}" in
    ""|status) ts_wezterm_status ;;
    changes)   show_changes ;;
    install)
        case "${2:-}" in
            stable|nightly) ts_wezterm_install "$2" ;;
            *) echo "usage: tstack wezterm install <stable|nightly>" >&2; exit 2 ;;
        esac ;;
    upgrade)   ts_wezterm_upgrade ;;
    *) echo "tstack wezterm: unknown command '$1' (try: status, changes, install, upgrade, -h)" >&2; exit 2 ;;
esac
