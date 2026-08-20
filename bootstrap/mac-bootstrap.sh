#!/usr/bin/env bash
# mac-bootstrap.sh — install macOS-side prerequisites for the terminal-stack.
# Targets macOS (Apple Silicon or Intel) via Homebrew. Idempotent: re-run safely.
# See ../INSTALL.md § macOS for the full sequence.
#
# macOS skips the windows/** subtree automatically (no /mnt/c/Users/<user>): the
# post-apply hook (run_after_90-sync-windows.sh) self-no-ops when that path is absent.

set -euo pipefail

INFO=$'\033[1;34m==>\033[0m'
WARN=$'\033[1;33m!!\033[0m'

if [ "$(uname -s)" != "Darwin" ]; then
    echo "$WARN This script is for macOS. Detected: $(uname -s). Aborting."
    exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck source=_config.sh
. "$SCRIPT_DIR/_config.sh"
# shellcheck source=_wizard.sh
. "$SCRIPT_DIR/_wizard.sh"
# shellcheck source=_detect.sh
. "$SCRIPT_DIR/_detect.sh"

echo "$INFO Terminal stack macOS bootstrap"
echo "    Detected: user $USER, home $HOME, arch $(uname -m)"

# 1. Homebrew
if ! command -v brew >/dev/null 2>&1; then
    echo "$INFO Installing Homebrew"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
    echo "$INFO Homebrew already installed"
fi

# Make brew available for the rest of the script (path varies by Apple Silicon vs Intel)
if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi

# 2. Wizard — collect leader/theme/app choices (env vars skip prompts), then
# install the required formulae plus the selected toggleable apps.
ts_confirm_headless
# macOS is the only POSIX target that installs WezTerm (WSL/Linux use the
# host's GUI), so it is the only one that asks.
ts_is_headless || TS_WIZ_ASK_WEZTERM=1
ts_wizard_collect || exit 0
echo "$INFO Installing required brew formulae (zsh, git, starship, chezmoi)"
brew install zsh git starship chezmoi
ts_brew_install_apps "$TS_WIZ_APPS"

# 3. WezTerm + Nerd Font (casks) — GUI only. Skip on a headless Mac (e.g. a CI
# runner or a Mac server reached over ssh): no window server to render either.
if ts_is_headless; then
    echo "$INFO Headless Mac — skipping WezTerm + Nerd Font casks (no GUI here)."
else
    # WezTerm, matching the Windows side. The plain `wezterm` cask is pinned to
    # the stale 20240203 stable; this stack expects a current build, so nightly
    # is the default — but it is a choice (see ts_prompt_wezterm), and a nightly
    # that won't install falls back to stable rather than failing the bootstrap.
    case "${TS_WIZ_WEZTERM:-nightly}" in
        skip)
            echo "$INFO WezTerm: skipped"
            ;;
        stable)
            if ! brew list --cask wezterm >/dev/null 2>&1; then
                echo "$INFO Installing WezTerm stable cask"
                brew install --cask wezterm || echo "$WARN WezTerm cask install failed; install it by hand later."
            else
                echo "$INFO WezTerm cask already installed"
            fi
            ;;
        *)
            if ! brew list --cask wezterm@nightly >/dev/null 2>&1; then
                echo "$INFO Installing WezTerm nightly cask"
                if ! brew install --cask wezterm@nightly; then
                    echo "$WARN nightly unavailable; falling back to WezTerm stable"
                    brew install --cask wezterm || echo "$WARN WezTerm cask install failed; install it by hand later."
                fi
            else
                echo "$INFO WezTerm nightly cask already installed"
            fi
            ;;
    esac
    # JetBrainsMono Nerd Font cask (font casks moved into homebrew/cask in 2024).
    if ! brew list --cask font-jetbrains-mono-nerd-font >/dev/null 2>&1; then
        echo "$INFO Installing JetBrainsMono Nerd Font cask"
        brew install --cask font-jetbrains-mono-nerd-font
    else
        echo "$INFO JetBrainsMono Nerd Font cask already installed"
    fi
fi

# 4. oh-my-zsh (unattended) — same as WSL path
if [ ! -d "$HOME/.oh-my-zsh" ]; then
    echo "$INFO Installing oh-my-zsh"
    RUNZSH=no CHSH=no KEEP_ZSHRC=no sh -c \
        "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" \
        >/dev/null
else
    echo "$INFO oh-my-zsh already present"
fi

# 5. Login shell -> zsh (macOS ships with zsh by default since Catalina, but check anyway)
current_shell="$(dscl . -read "/Users/$USER" UserShell | awk '{print $2}')"
brew_zsh="$(brew --prefix)/bin/zsh"
if [ "$current_shell" != "$brew_zsh" ] && [ "$current_shell" != "/bin/zsh" ]; then
    echo "$INFO chsh login shell -> $brew_zsh"
    # Add brew zsh to /etc/shells if not present
    if ! grep -qFx "$brew_zsh" /etc/shells; then
        echo "$brew_zsh" | sudo tee -a /etc/shells >/dev/null
    fi
    chsh -s "$brew_zsh"
else
    echo "$INFO Login shell already zsh"
fi

# 6. chezmoi.toml — point sourceDir at this repo.
# Default: the repo this script lives in (bootstrap/ is one level below the root).
# Override by exporting SOURCE_DIR before running. ts_ensure_source_dir creates
# the toml or repoints a stale sourceDir (preserving [data]).
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
SOURCE_DIR="${SOURCE_DIR:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
TOML="$HOME/.config/chezmoi/chezmoi.toml"
if [ -d "$SOURCE_DIR" ]; then
    ts_ensure_source_dir "$SOURCE_DIR"
else
    echo "$WARN $SOURCE_DIR not found; set SOURCE_DIR and re-run, or edit $TOML manually."
fi

# 6b. Persist the wizard's config choices into chezmoi [data] (regenerates the
# derived leaderKey/leaderMods/resolvedTheme via `chezmoi init`).
if [ -f "$TOML" ]; then
    # shellcheck disable=SC2086
    ts_save_config "${TS_WIZ_LEADER:-ctrl-space}" "${TS_WIZ_THEME:-dark}" "${TS_WIZ_TMUX:-ctrl-b}" ${TS_WIZ_APPS:-}
    # Stored on its own, not through ts_save_config: the mux key is positional-
    # argument-free by design so ts-mux can flip it without re-stating the rest.
    ts_wez_mux_set "${TS_WIZ_WEZ_MUX:-off}"
    ts_wez_restore_set "${TS_WIZ_WEZ_RESTORE:-off}"
    ts_cc_tts_apply_wizard_choice "${TS_WIZ_CC_TTS:-off}"
    ts_cc_tts_finish
    echo "$INFO Saved terminal-stack config to $TOML [data]"
fi

# 7. Git include — stack aliases + delta config (file lands via chezmoi apply;
# git silently skips missing include files, so ordering is safe).
GIT_INC="$HOME/.config/git/terminal-stack.gitconfig"
if git config --global --get-all include.path 2>/dev/null | grep -qF "terminal-stack.gitconfig"; then
    echo "$INFO git include.path already set"
else
    echo "$INFO Adding git include.path -> $GIT_INC"
    git config --global --add include.path "$GIT_INC"
fi

# 8. Workspace directory for ws/wsp/wspu. Same contract as the Debian-family
# bootstraps: $WORKSPACE_DIR env skips the prompt; the /dev/tty read survives
# curl|bash; the answer persists to ~/.zshrc.local only when it differs from
# the autodetect (the shell-side _ts_workspace() covers the detected case).
WS_DETECTED=""
for d in "$HOME/Documents/Workspace" "$HOME/workspace" "$HOME/Workspace"; do
    [ -d "$d" ] && { WS_DETECTED="$d"; break; }
done
WS_CHOICE="${WORKSPACE_DIR:-}"
if [ -n "$WS_CHOICE" ]; then
    echo "$INFO WORKSPACE_DIR=$WS_CHOICE (from env; skipping prompt)"
else
    if { true > /dev/tty; } 2>/dev/null; then
        IFS= read -e -r -p "Workspace directory [${WS_DETECTED:-none}]: " WS_CHOICE < /dev/tty || WS_CHOICE=""
    else WS_CHOICE=""; fi
    WS_CHOICE="${WS_CHOICE:-$WS_DETECTED}"
    case "$WS_CHOICE" in "~") WS_CHOICE="$HOME" ;; "~/"*) WS_CHOICE="$HOME/${WS_CHOICE#\~/}" ;; esac
fi
if [ -z "$WS_CHOICE" ]; then
    echo "$WARN No workspace directory found or chosen."
    echo "    Set one later: export WORKSPACE_DIR=... in ~/.zshrc.local"
elif [ "$WS_CHOICE" = "$WS_DETECTED" ]; then
    echo "$INFO Workspace: $WS_CHOICE (autodetected; no override needed)"
else
    [ -d "$WS_CHOICE" ] || echo "$WARN $WS_CHOICE does not exist (yet) — ws will warn until it does."
    RC="$HOME/.zshrc.local"
    if [ -f "$RC" ] && grep -q '^export WORKSPACE_DIR=' "$RC"; then
        # BSD sed needs the empty '' backup arg.
        sed -i '' "s|^export WORKSPACE_DIR=.*|export WORKSPACE_DIR=\"$WS_CHOICE\"|" "$RC"
        echo "$INFO Updated WORKSPACE_DIR in $RC"
    else
        printf 'export WORKSPACE_DIR="%s"\n' "$WS_CHOICE" >> "$RC"
        echo "$INFO Wrote WORKSPACE_DIR=$WS_CHOICE to $RC"
    fi
fi

echo ""
echo "$INFO macOS bootstrap done."
echo "    Next: chezmoi apply -v"
echo "    macOS skips the windows/** subtree automatically (no /mnt/c/Users/<user>)."
