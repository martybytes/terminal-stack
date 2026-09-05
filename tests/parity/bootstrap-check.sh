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
[ -x "$HOME/.local/bin/chezmoi" ] || { echo "!! chezmoi was not installed"; fail=1; }

echo "==> chezmoi apply"
"$HOME/.local/bin/chezmoi" apply -v </dev/null >/dev/null
[ -f "$HOME/.zshrc" ] || { echo "!! chezmoi apply left no ~/.zshrc"; fail=1; }

# The doctor is the stack's own opinion of the install it just did.
python3 tstack/main.py doctor --quiet </dev/null \
    || echo "==> doctor reported items (non-fatal here)"

exit "$fail"
