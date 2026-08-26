#!/usr/bin/env bash
# install-mac.sh — one-liner macOS installer for the terminal-stack.
# Targets macOS (Apple Silicon or Intel) via Homebrew. Idempotent: re-run safely.
# Usage (from a fresh Mac):
#   curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-mac.sh | bash
#
# Optional: override the clone location before piping.
#   TERMINAL_STACK_DIR=~/dotfiles/ts curl -fsSL ... | bash
#
# What it does:
#   1. Verifies Darwin.
#   2. Installs Homebrew if absent.
#   3. brew install git if absent.
#   4. Clones github.com/martybytes/terminal-stack to ~/code/terminal-stack
#      (or $TERMINAL_STACK_DIR, unless that names a workspace root). git pull if
#      already cloned.
#   5. Runs bootstrap/mac-bootstrap.sh.
#   6. Runs chezmoi apply -v. The post-apply hook self-no-ops without /mnt/c/Users/.

set -euo pipefail

INFO=$'\033[1;34m==>\033[0m'
WARN=$'\033[1;33m!!\033[0m'

if [ "$(uname -s)" != "Darwin" ]; then
    echo "$WARN This script is for macOS. Detected: $(uname -s). Aborting."
    exit 1
fi

echo "$INFO terminal-stack macOS installer"
echo "    Detected: user $USER, home $HOME, arch $(uname -m)"

# 1. Homebrew. NONINTERACTIVE=1 suppresses the installer's "Press RETURN to
# continue" prompt — required when this script is itself piped through bash,
# where /dev/tty may not be attached.
if ! command -v brew >/dev/null 2>&1; then
    echo "$INFO Installing Homebrew"
    NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/null
fi

# Make brew available for the rest of this script (path varies by Apple Silicon vs Intel).
if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi

# 2. Git
if ! command -v git >/dev/null 2>&1; then
    echo "$INFO brew install git"
    brew install git
fi

# 3. Choose clone location ($TERMINAL_STACK_DIR skips the prompt), then clone.
REPO_URL='https://github.com/martybytes/terminal-stack.git'
# Canonical default: the XDG data home (see docs/decisions.md).
DEFAULT_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/terminal-stack"
# Workspace roots, in probe order. Keep in sync with bootstrap/_workspace.sh
# ts_ws_root — this copy exists because the installer runs before any clone is
# on disk.
ts_in_workspace_root() {
    p="${1%/}"
    for r in "${WORKSPACE_DIR:-}" /mnt/c/DATA/Workspace "$HOME/Documents/Workspace" "$HOME/workspace" "$HOME/Workspace"; do
        [ -n "$r" ] || continue
        case "$p/" in "${r%/}"/*) return 0 ;; esac
    done
    return 1
}
# A dev clone at a wso tier path is a deliberate choice, not an accident.
# Twin of bootstrap/_cleanup.sh ts_is_dev_clone.
ts_is_dev_clone_path() {
    printf '%s' "$1" | grep -Eq '/(src|public|archive|local|scratch)/[^/]+\.[^/]+/[^/]+/[^/]+/?$'
}

# A pin at a path with no clone, while the canonical location HAS one, is a
# leftover from a relocated install. POSIX persists its pin as chezmoi's
# sourceDir rather than an env var, so an exported TERMINAL_STACK_DIR is
# honoured whenever it could plausibly be deliberate — i.e. every other case.
if [ -n "${TERMINAL_STACK_DIR:-}" ] && [ ! -d "$TERMINAL_STACK_DIR/.git" ] && [ -d "$DEFAULT_DIR/.git" ]; then
    echo "$INFO ignoring \$TERMINAL_STACK_DIR=$TERMINAL_STACK_DIR (no clone there); using $DEFAULT_DIR"
    TERMINAL_STACK_DIR=""
fi
if [ -n "${TERMINAL_STACK_DIR:-}" ]; then
    TARGET_DIR="$TERMINAL_STACK_DIR"
    echo "$INFO Clone location: $TARGET_DIR (from \$TERMINAL_STACK_DIR)"
else
    ans=""
    if { true > /dev/tty; } 2>/dev/null; then
        IFS= read -e -r -p "Where should the terminal-stack repo live? [$DEFAULT_DIR]: " ans < /dev/tty || ans=""
    fi
    TARGET_DIR="${ans:-$DEFAULT_DIR}"
    case "$TARGET_DIR" in
        "~")   TARGET_DIR="$HOME" ;;
        "~/"*) TARGET_DIR="$HOME/${TARGET_DIR#\~/}" ;;
    esac
fi

# The runtime clone must not live inside a workspace root: `wso migrate` derives
# a repo's destination from its origin and will relocate it to a tier path,
# orphaning the install. That has happened. Dev-clone tier paths are exempt —
# pinning one is deliberate (docs/decisions.md § "Runtime clone location").
if ts_in_workspace_root "$TARGET_DIR" && ! ts_is_dev_clone_path "$TARGET_DIR"; then
    echo ""
    echo "$WARN $TARGET_DIR is inside a workspace root."
    echo "    'wso migrate' can relocate it out from under the install."
    ws_ans=""
    if { true > /dev/tty; } 2>/dev/null; then
        IFS= read -r -p "  Use $DEFAULT_DIR instead? [Y/n]: " ws_ans < /dev/tty || ws_ans=""
    fi
    case "$ws_ans" in
        n|N|no|NO) echo "$INFO keeping $TARGET_DIR — re-run 'wso plan' after any workspace migration." ;;
        *)         TARGET_DIR="$DEFAULT_DIR"; echo "$INFO Clone location: $TARGET_DIR" ;;
    esac
    echo ""
fi


# 2a. Existing clone at a legacy location: pull it first (that lands the
# move routine inside it), then offer to move it to the target instead of
# cloning fresh — preserves history, stashes, and dirty state. Minimal legacy
# scan; master list: bootstrap/_cleanup.sh ts_clone_candidates.
if [ ! -d "$TARGET_DIR/.git" ]; then
    LEGACY=""
    for c in "$HOME/code/terminal-stack"              "$HOME/terminal-stack"              "$HOME/Workspace/terminal-stack"              "$HOME/Documents/Workspace/terminal-stack"; do
        [ -d "$c/.git" ] || continue
        git -C "$c" config --get remote.origin.url 2>/dev/null | grep -qi terminal-stack || continue
        LEGACY="$c"; break
    done
    if [ -n "$LEGACY" ]; then
        echo "$INFO Existing clone found at $LEGACY"
        mv_ans="m"
        if { true > /dev/tty; } 2>/dev/null; then
            IFS= read -r -p "  [M]ove it to $TARGET_DIR / [K]eep it there / [F]resh clone? [M]: " mv_ans < /dev/tty || mv_ans="m"
        fi
        case "$mv_ans" in
            k|K*) TARGET_DIR="$LEGACY"; echo "$INFO Keeping $LEGACY" ;;
            f|F*) : ;;
            *)
                git -C "$LEGACY" pull --ff-only >/dev/null 2>&1 || true
                if [ -f "$LEGACY/bootstrap/_doctor.sh" ]; then
                    set +e
                    # shellcheck source=/dev/null
                    . "$LEGACY/bootstrap/_doctor.sh"
                    if command -v ts_relocate_clone >/dev/null 2>&1; then
                        ts_relocate_clone "$LEGACY" "$TARGET_DIR"                             || echo "$WARN Move failed; cloning fresh instead."
                    else
                        echo "$WARN This clone predates the move routine; cloning fresh (old clone offered for cleanup later)."
                    fi
                    set -e
                fi
                ;;
        esac
    fi
fi

if [ -d "$TARGET_DIR/.git" ]; then
    echo "$INFO Repo already at $TARGET_DIR; git pull"
    git -C "$TARGET_DIR" pull --ff-only
else
    echo "$INFO Cloning $REPO_URL -> $TARGET_DIR"
    mkdir -p "$(dirname -- "$TARGET_DIR")"
    git clone "$REPO_URL" "$TARGET_DIR"
fi

# 3b. Offer to clean up old clones + retired leftover files (pre-ticked
# checklist; confirms before removing). Runs before the bootstrap repoints
# chezmoi.toml at $TARGET_DIR. Non-fatal.
if [ -f "$TARGET_DIR/bootstrap/_cleanup.sh" ]; then
    set +e
    # shellcheck source=/dev/null
    . "$TARGET_DIR/bootstrap/_cleanup.sh"
    ts_cleanup_menu "$TARGET_DIR"
    set -e
fi

# 4. Bootstrap
export SOURCE_DIR="$TARGET_DIR"
BOOTSTRAP="$TARGET_DIR/bootstrap/mac-bootstrap.sh"
if [ ! -f "$BOOTSTRAP" ]; then
    echo "$WARN Expected bootstrap script not found at $BOOTSTRAP"
    exit 1
fi
echo "$INFO Running $BOOTSTRAP"
# `</dev/null` defends against the curl|bash stdin-consumption pitfall — see
# the matching comment in install-wsl.sh. The bootstrap is non-interactive.
bash "$BOOTSTRAP" </dev/null

# 5. chezmoi apply
echo "$INFO Running chezmoi apply -v"
chezmoi apply -v </dev/null

# 6. Health check (non-fatal): sourceDir + zshrc + tools; flags leftover clones.
if [ -f "$TARGET_DIR/bootstrap/ts-doctor.sh" ]; then
    TERMINAL_STACK_DIR="$TARGET_DIR" bash "$TARGET_DIR/bootstrap/ts-doctor.sh" --quiet </dev/null \
        || echo "$INFO Run 'tstack doctor --repair' to resolve the items above."
fi

echo ""
echo "$INFO macOS install done."
echo "    Clone:  $TARGET_DIR"
echo "    Next:   quit and relaunch WezTerm so JetBrainsMono Nerd Font picks up; confirm Starship glyphs render."
