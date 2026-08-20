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
#      (or $TERMINAL_STACK_DIR). git pull if already cloned.
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
DEFAULT_DIR="/mnt/c/Users/$WIN_USER/AppData/Local/terminal-stack/stack"
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
                if [ -f "$LEGACY/bootstrap/_doctor.sh" ]; then
                    set +e
                    # shellcheck source=/dev/null
                    . "$LEGACY/bootstrap/_doctor.sh"
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

if [ -d "$TARGET_DIR/.git" ]; then
    echo "$INFO Repo already at $TARGET_DIR; git pull"
    git -C "$TARGET_DIR" pull --ff-only
else
    echo "$INFO Cloning $REPO_URL -> $TARGET_DIR"
    mkdir -p "$(dirname -- "$TARGET_DIR")"
    git clone "$REPO_URL" "$TARGET_DIR"
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
bash "$BOOTSTRAP" </dev/null

# 5. chezmoi apply
echo "$INFO Running chezmoi apply -v"
"$HOME/.local/bin/chezmoi" apply -v </dev/null

# 6. Health check (non-fatal): sourceDir + zshrc + tools; flags leftover clones.
if [ -f "$TARGET_DIR/bootstrap/ts-doctor.sh" ]; then
    TERMINAL_STACK_DIR="$TARGET_DIR" bash "$TARGET_DIR/bootstrap/ts-doctor.sh" --quiet </dev/null \
        || echo "$INFO Run 'ts-doctor --repair' to resolve the items above."
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
