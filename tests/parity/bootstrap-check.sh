#!/usr/bin/env bash
# What the `bootstrap` parity target runs INSIDE the container.
#
# A file rather than a `bash -c '...'` string, because the sibling arms in
# run.sh already have to spell an apostrophe as a backtick to avoid closing
# their own quoting -- and this script needs prose.
#
# Preconditions the container provides: /repo is the repo, read-only; the user
# is non-root with passwordless sudo; every answer is already in the
# environment, so nothing here can block on a prompt.
set -euo pipefail

# A clean checkout at a path that is deliberately NOT on the built-in candidate
# list. That is the whole point: a clone anywhere else is what exposes the
# resolution bugs, and every default location hides them.
CLONE="$HOME/somewhere/odd/stack"
mkdir -p "$(dirname "$CLONE")"
cp -a /repo/. "$CLONE/"
cd "$CLONE"
git config --global --add safe.directory "$CLONE"
# Drop what git ignores, so the container sees what a clean checkout sees, not
# the developer's untracked files. Uncommitted TRACKED changes stay -- running
# against the working tree is the point.
git ls-files --others --ignored --exclude-standard -z | xargs -0 -r rm -f --

fail=0

# ── the regression no static check can see ──────────────────────────────────
# Assert on the ANSWER, never on the wizard's console output: the questionnaire
# writes its menus to the terminal, so a "catalog is empty" warning never
# reaches stdout and a grep for it silently always passes. That mistake made an
# earlier version of this check unable to fail.
#
# Invoked without TERMINAL_STACK_DIR, a clone at a path off the candidate list
# resolves to nothing -- chezmoi is not configured YET at this point in the
# bootstrap -- so apps.catalog() is empty and the recommended set comes back
# empty. A whole install with no CLI tools, reported as success.
echo "==> probing the questionnaire from $CLONE"
(
    set +u
    # shellcheck disable=SC1091
    . bootstrap/_config.sh >/dev/null 2>&1 || true
    # shellcheck disable=SC1091
    . bootstrap/_wizard.sh
    TS_APPS=recommended ts_wizard_collect >/dev/null 2>&1 || true
    if [ -z "${TS_WIZ_APPS:-}" ]; then
        echo "!! the wizard offered NO TOOLS from a clone at $CLONE"
        exit 1
    fi
    # shellcheck disable=SC2086
    set -- $TS_WIZ_APPS
    echo "==> recommended set resolved: $# tools"
) || fail=1

# ── and now the installer, for real ─────────────────────────────────────────
# SOURCE_DIR only, NOT TERMINAL_STACK_DIR. install-linux.sh exports both, but
# running the bootstrap directly is a documented path too, and it is the one
# where the wizard has to pin the clone for itself. Exporting it here would test
# the installer and quietly stop testing bootstrap/_wizard.sh.
export SOURCE_DIR="$CLONE"
echo "==> running bootstrap/linux-bootstrap.sh"
bash bootstrap/linux-bootstrap.sh </dev/null

# ── what it is supposed to have left behind ─────────────────────────────────
TOML="$HOME/.config/chezmoi/chezmoi.toml"
[ -f "$TOML" ] || { echo "!! $TOML was never written"; fail=1; }
grep -q "$CLONE" "$TOML" 2>/dev/null || { echo "!! chezmoi.toml does not point at $CLONE"; fail=1; }
# WHERE chezmoi lands is the package manager's business, not this check's. The
# apt bootstraps curl it into ~/.local/bin because Debian does not package it;
# Arch has `extra/chezmoi`, so it arrives at /usr/bin. Asserting the path rather
# than the BINARY made this check fail on every Arch host for a chezmoi that was
# installed correctly -- and every resolver in the repo (ts_chezmoi_bin,
# _ts_chezmoi, find_chezmoi) already falls through to PATH.
CZ=""
for c in "$HOME/.local/bin/chezmoi" "$(command -v chezmoi 2>/dev/null || true)"; do
    [ -n "$c" ] && [ -x "$c" ] && { CZ="$c"; break; }
done
[ -n "$CZ" ] || { echo "!! chezmoi was not installed (not in ~/.local/bin, not on PATH)"; fail=1; }

if [ -n "$CZ" ]; then
    echo "==> chezmoi apply ($CZ)"
    "$CZ" apply -v </dev/null >/dev/null
    [ -f "$HOME/.zshrc" ] || { echo "!! chezmoi apply left no ~/.zshrc"; fail=1; }

    # tmux lands at exactly ONE path, and which one depends on the distro.
    # Omarchy owns ~/.config/tmux/tmux.conf and tmux 3.7c prefers it over
    # ~/.tmux.conf, so writing the latter there produced a config tmux never
    # read: applied, diffed, and inert. Assert the file that this host's tmux
    # would actually load, and assert the other one is ABSENT -- "both present"
    # is the silently-wrong state, not an error anything else would report.
    if [ -r /etc/os-release ] && grep -qi '^ID=omarchy' /etc/os-release; then
        [ -f "$HOME/.config/tmux/tmux.conf" ] \
            || { echo "!! no ~/.config/tmux/tmux.conf on Omarchy"; fail=1; }
        [ -e "$HOME/.tmux.conf" ] \
            && { echo "!! ~/.tmux.conf exists on Omarchy; tmux would ignore it"; fail=1; }
        grep -q 'source-file -q /usr/share/omarchy/config/tmux/tmux.conf' \
            "$HOME/.config/tmux/tmux.conf" 2>/dev/null \
            || { echo "!! the Omarchy tmux config is not sourced; its bindings are gone"; fail=1; }
    else
        [ -f "$HOME/.tmux.conf" ] || { echo "!! chezmoi apply left no ~/.tmux.conf"; fail=1; }
        [ -e "$HOME/.config/tmux/tmux.conf" ] \
            && { echo "!! ~/.config/tmux/tmux.conf exists off Omarchy; it would shadow ~/.tmux.conf"; fail=1; }
    fi

    # ~/.claude, which `.chezmoiignore` blocked outright until 2026-09-06. The
    # rule was meant to stop the repo's own project-scoped .claude/commands
    # deploying; because .chezmoiignore matches the TARGET, it took dot_claude/**
    # with it and nothing under ~/.claude had ever landed on POSIX.
    [ -f "$HOME/.claude/statusline-command.sh" ] \
        || { echo "!! ~/.claude/statusline-command.sh did not deploy"; fail=1; }
    [ -f "$HOME/.claude/settings.json" ] \
        || { echo "!! the ~/.claude/settings.json splice did not run"; fail=1; }
    grep -q statusLine "$HOME/.claude/settings.json" 2>/dev/null \
        || { echo "!! ~/.claude/settings.json has no statusLine; the splice wrote nothing"; fail=1; }

    # And the stray fixture that used to ride along with it.
    [ -e "$HOME/C" ] && { echo "!! ~/C was created; the C/ fixture is deploying again"; fail=1; }

    # The login shell. On Omarchy the bootstrap must NOT have chsh'd: the distro
    # is bash-first and its whole shell environment hangs off ~/.bashrc.
    if [ -r /etc/os-release ] && grep -qi '^ID=omarchy' /etc/os-release; then
        # ${USER:-$(id -un)}, not $USER: `docker run` sets no USER, and under
        # `set -u` a bare $USER is an unbound-variable abort. This repo has been
        # bitten by exactly that before -- it is why the bootstrap parity target
        # exists -- and this check reproduced it on its first run.
        case "$(getent passwd "${USER:-$(id -un)}" | cut -d: -f7)" in
            */zsh) echo "!! the bootstrap chsh'd to zsh on Omarchy"; fail=1 ;;
        esac
    fi
fi

# The doctor is the stack's own opinion of the install it just did.
python3 tstack/main.py doctor --quiet </dev/null \
    || echo "==> doctor reported items (non-fatal here)"

exit "$fail"
