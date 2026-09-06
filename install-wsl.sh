#!/usr/bin/env bash
# install-wsl.sh — one-liner WSL installer for the terminal-stack.
# Usage (from a fresh WSL Ubuntu, after running install.ps1 on Windows):
#   curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-wsl.sh | bash
#
# Optional: override the clone location before piping.
#   TERMINAL_STACK_DIR=/mnt/c/dev/terminal-stack curl -fsSL ... | bash
#
# What it does:
#   1. Ensures git + curl are installed (apt).
#   2. Auto-detects Windows username via cmd.exe interop.
#   3. Clones github.com/martybytes/terminal-stack to /mnt/c/Users/<WIN_USER>/terminal-stack
#      (or $TERMINAL_STACK_DIR, unless that names a workspace root). git pull if
#      already cloned.
#   4. Runs bootstrap/wsl-bootstrap.sh non-interactively (WIN_USER from env).
#   5. Runs chezmoi apply -v.

set -euo pipefail

INFO=$'\033[1;34m==>\033[0m'
WARN=$'\033[1;33m!!\033[0m'

if [ "$(id -u)" -eq 0 ]; then
    echo "$WARN Don't run this as root. Run as your normal WSL user; sudo will prompt as needed."
    exit 1
fi

echo "$INFO terminal-stack WSL installer"
echo "    Detected: user $USER, home $HOME"

# 1. apt prereqs. `</dev/null` on each call so sudo / apt can't read from
# our script pipe (see the cmd.exe comment below).
if ! command -v git >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
    echo "$INFO Installing git + curl via apt"
    sudo apt-get update -qq </dev/null
    sudo apt-get install -y git curl </dev/null >/dev/null
fi

# 2. Windows username via cmd.exe interop.
# `</dev/null` is load-bearing under `curl | bash`: WSL's cmd.exe interop
# inherits the caller's stdin (our script pipe) and consumes it before exiting
# even though we only pass /c. Without this redirect, the rest of the script
# disappears into cmd.exe and bash exits 0 silently after the banner.
detect_win_user() {
    if [ -x /mnt/c/Windows/System32/cmd.exe ]; then
        /mnt/c/Windows/System32/cmd.exe /c 'echo %USERNAME%' </dev/null 2>/dev/null | tr -d '\r\n' || true
    fi
}
WIN_USER="${WIN_USER:-$(detect_win_user)}"
if [ -z "$WIN_USER" ]; then
    echo "$WARN Could not auto-detect Windows username. Set WIN_USER=<name> and re-run."
    exit 1
fi
export WIN_USER
echo "$INFO Windows username: $WIN_USER"

# 3. Choose clone location ($TERMINAL_STACK_DIR skips the prompt), then clone.
# Canonical default: the Windows app-data dir the stack already owns, shared by
# WSL and Windows (see docs/decisions.md § "Runtime clone location").
REPO_URL='https://github.com/martybytes/terminal-stack.git'
# The branch a runtime clone tracks, pinned rather than inherited. `git clone`
# with no --branch takes the repo's DEFAULT branch, so which tree an install got
# was decided on GitHub rather than here -- and for a while that silently meant
# the integration branch, while this very script was being fetched from main.
# Keep in step with tstack/paths.py RELEASE_BRANCH; tests/test_release_branch.py
# fails if any copy drifts.
RELEASE_BRANCH='main'
DEFAULT_DIR="/mnt/c/Users/$WIN_USER/AppData/Local/terminal-stack/stack"
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

# 3a. Existing clone at a legacy location: pull it first (that lands the move
# routine inside it), then offer to move it to the target instead of cloning
# fresh — preserves history, stashes, and dirty state. Minimal legacy scan;
# master list: bootstrap/_cleanup.sh ts_clone_candidates.
if [ ! -d "$TARGET_DIR/.git" ]; then
    LEGACY=""
    for c in "/mnt/c/Users/$WIN_USER/terminal-stack" \
             /mnt/c/DATA/Workspace/terminal-stack \
             "$HOME/code/terminal-stack" \
             "$HOME/terminal-stack"; do
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
                if [ -f "$LEGACY/bootstrap/_cleanup.sh" ]; then
                    set +e
                    # shellcheck source=/dev/null
                    . "$LEGACY/bootstrap/_cleanup.sh"
                    if command -v ts_relocate_clone >/dev/null 2>&1; then
                        ts_relocate_clone "$LEGACY" "$TARGET_DIR" \
                            || echo "$WARN Move failed; cloning fresh instead."
                    else
                        echo "$WARN This clone predates the move routine; cloning fresh (old clone offered for cleanup later)."
                    fi
                    set -e
                fi
                ;;
        esac
    fi
fi

# An existing clone carries whatever branch it was last left on, and
# ts_relocate_clone above preserves that across a move. Left alone, a clone
# parked on a merged-and-deleted feature branch fails the pull outright with
# git's "no such ref was fetched", which is how this function came to exist.
# Prune first: without it a deleted branch still looks alive through its stale
# remote-tracking ref.
ts_align_branch() {
    d="$1"
    git -C "$d" fetch --quiet --prune origin 2>/dev/null || true
    if [ -n "$(git -C "$d" status --porcelain 2>/dev/null)" ]; then
        echo "$WARN $d has uncommitted changes; leaving it on its current branch."
        return 0
    fi
    cur="$(git -C "$d" rev-parse --abbrev-ref HEAD 2>/dev/null || echo HEAD)"
    [ "$cur" = "$RELEASE_BRANCH" ] && return 0
    if git -C "$d" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
        # A live branch may be a deliberate test of unreleased work, so ask —
        # and when nobody is there to answer, keep it rather than undo a pin.
        ans=""
        if { true > /dev/tty; } 2>/dev/null; then
            IFS= read -r -p "  Clone is on '$cur', not $RELEASE_BRANCH. [S]witch / [K]eep? [S]: " ans < /dev/tty || ans=""
        else
            echo "$INFO Clone is on '$cur', not $RELEASE_BRANCH; keeping it (non-interactive)."
            return 0
        fi
        case "$ans" in k|K*) echo "$INFO Keeping '$cur'."; return 0 ;; esac
    else
        # No upstream: gone from the remote, or a detached HEAD. Nothing to ask.
        echo "$INFO '$cur' has no upstream on the remote; returning this clone to $RELEASE_BRANCH."
    fi
    git -C "$d" checkout "$RELEASE_BRANCH" 2>/dev/null \
        || git -C "$d" checkout -b "$RELEASE_BRANCH" "origin/$RELEASE_BRANCH" 2>/dev/null \
        || { echo "$WARN Could not switch $d to $RELEASE_BRANCH; continuing on '$cur'."; return 0; }
    echo "$INFO Switched $d to $RELEASE_BRANCH."
}

if [ -d "$TARGET_DIR/.git" ]; then
    echo "$INFO Repo already at $TARGET_DIR; git pull"
    ts_align_branch "$TARGET_DIR"
    git -C "$TARGET_DIR" pull --ff-only
else
    echo "$INFO Cloning $REPO_URL ($RELEASE_BRANCH) -> $TARGET_DIR"
    mkdir -p "$(dirname -- "$TARGET_DIR")"
    git clone --branch "$RELEASE_BRANCH" "$REPO_URL" "$TARGET_DIR"
fi

# 3b. Offer to clean up old clones + retired leftover files (pre-ticked
# checklist; confirms before removing). Non-fatal; runs before the bootstrap
# repoints chezmoi.toml at $TARGET_DIR.
if [ -f "$TARGET_DIR/bootstrap/_cleanup.sh" ]; then
    set +e
    # shellcheck source=/dev/null
    . "$TARGET_DIR/bootstrap/_cleanup.sh"
    ts_cleanup_menu "$TARGET_DIR"
    set -e
fi

# 4. Bootstrap (non-interactive thanks to the env WIN_USER guard in wsl-bootstrap.sh)
export SOURCE_DIR="$TARGET_DIR"
# The Python side resolves the clone from TERMINAL_STACK_DIR first. The
# questionnaire runs before chezmoi is configured, so without this a clone
# outside the built-in candidate list gave an EMPTY app catalog and offered
# no tools at all, silently.
export TERMINAL_STACK_DIR="$TARGET_DIR"
BOOTSTRAP="$TARGET_DIR/bootstrap/wsl-bootstrap.sh"
if [ ! -f "$BOOTSTRAP" ]; then
    echo "$WARN Expected bootstrap script not found at $BOOTSTRAP"
    exit 1
fi
echo "$INFO Running $BOOTSTRAP"
# `</dev/null` for the same reason as the cmd.exe call above — any child of
# this script under `curl | bash` could otherwise read from the script pipe
# and truncate our remaining source. The bootstrap is fully non-interactive
# (WIN_USER comes from env), so closing stdin is safe.
# rc 3 means the user quit at the wizard review. Anything else non-zero is a
# real failure and `set -e` should still take us down.
BOOT_RC=0
bash "$BOOTSTRAP" </dev/null || BOOT_RC=$?
if [ "$BOOT_RC" = 3 ]; then
    echo "$INFO Install cancelled at the questionnaire; nothing was changed."
    exit 0
elif [ "$BOOT_RC" != 0 ]; then
    echo "$WARN $BOOTSTRAP failed (exit $BOOT_RC)."
    exit "$BOOT_RC"
fi

# 5. chezmoi apply
echo "$INFO Running chezmoi apply -v"
APPLY_RC=0
bash "$TARGET_DIR/bootstrap/ts-apply.sh" -v </dev/null || APPLY_RC=$?
if [ "$APPLY_RC" = 4 ]; then
    # Conflicts, explained above, nothing written. Everything else installed.
    echo "$INFO Everything else is installed. Re-run the apply once you have decided."
    exit 0
elif [ "$APPLY_RC" != 0 ]; then
    echo "$WARN chezmoi apply failed (exit $APPLY_RC)."
    exit "$APPLY_RC"
fi

# 6. Health check (non-fatal): sourceDir + zshrc + tools; flags leftover clones.
if command -v python3 >/dev/null 2>&1 && [ -f "$TARGET_DIR/tstack/main.py" ]; then
    TERMINAL_STACK_DIR="$TARGET_DIR" python3 "$TARGET_DIR/tstack/main.py" doctor --quiet </dev/null \
        || echo "$INFO Run 'tstack doctor --repair' to resolve the items above."
fi

echo ""
echo "$INFO WSL install done."
echo "    Clone:  $TARGET_DIR"

# Verify the login shell actually flipped to zsh. chsh updates /etc/passwd but
# the *current* session stays in whatever shell launched this script.
LOGIN_SHELL="$(getent passwd "$USER" | cut -d: -f7)"
case "$LOGIN_SHELL" in
    /usr/bin/zsh|/bin/zsh)
        echo "    Shell:  login shell is $LOGIN_SHELL (chsh applied)."
        echo "    Next:   open a new WezTerm tab (auto-reload picks up .wezterm.lua),"
        echo "            or run 'exec zsh -l' here to start using zsh + Starship now."
        ;;
    *)
        echo "$WARN  Login shell is still $LOGIN_SHELL — chsh did not take effect."
        echo "    Run 'sudo chsh -s /usr/bin/zsh $USER' manually, then open a new WSL tab."
        ;;
esac
