#!/usr/bin/env bash
# run_after_40-launchagents.sh — load the LaunchAgents chezmoi just wrote.
#
# A plist sitting in ~/Library/LaunchAgents does nothing. launchd only knows
# about it after a `bootstrap`, and it keeps running the OLD copy until the
# service is booted out -- so an apply that changes the plist and stops there
# leaves the previous definition live until the next logout. That is the kind of
# gap that reads as "the fix did not work".
#
# macOS only, and a no-op everywhere else: ~/Library/LaunchAgents is a Darwin
# path, and .chezmoiignore does not deploy the plist off Darwin anyway. The guard
# is here as well because a run_after runs on every target and finding out by
# `launchctl: command not found` is not a diagnosis.
#
# Never fails an apply. A login job that could not be reloaded is worth a line on
# stderr; it is not worth aborting the deployment of everything else, and the
# next login loads it regardless.
set -eu

[ "$(uname -s 2>/dev/null || true)" = Darwin ] || exit 0
command -v launchctl >/dev/null 2>&1 || exit 0

agents_dir="$HOME/Library/LaunchAgents"
[ -d "$agents_dir" ] || exit 0

domain="gui/$(id -u)"

for plist in "$agents_dir"/com.terminal-stack.*.plist; do
    [ -e "$plist" ] || continue
    label="$(basename "$plist" .plist)"

    # bootout first, unconditionally and ignoring failure: "not loaded" and
    # "loaded, now unloaded" are both the state we want, and distinguishing them
    # costs a second launchctl call to learn nothing.
    launchctl bootout "$domain/$label" >/dev/null 2>&1 || true

    if launchctl bootstrap "$domain" "$plist" >/dev/null 2>&1; then
        printf '==> loaded LaunchAgent %s\n' "$label"
    else
        printf 'terminal-stack: could not load %s; it will load at next login.\n' \
            "$label" >&2
    fi
done
