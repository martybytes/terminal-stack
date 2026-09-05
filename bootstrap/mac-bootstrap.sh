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
# macOS installs GUI terminal emulators (WSL uses the host's; desktop Linux asks
# too, from linux-bootstrap.sh). A headless Mac has no window server, so it is
# never asked and never gets one.
ts_is_headless || TS_WIZ_ASK_TERMINALS=1
ts_wizard_collect || exit 0

# 2b. Required formulae first — these are prerequisites, not optional extras,
# and chezmoi in particular must exist before the next step: ts_save_config runs
# `chezmoi init` to regenerate the derived keys (leaderKey, leaderMods,
# tmuxPrefixResolved, resolvedTheme). Deliberately NOT guarded with
# ts_note_failure: if zsh/git/starship/chezmoi cannot be installed there is no
# stack to configure, and failing loudly here is correct.
echo "$INFO Installing required brew formulae (zsh, git, starship, chezmoi)"
brew install zsh git starship chezmoi

# 2c. Persist the answers BEFORE anything optional can fail.
#
# These used to run at the very end. An optional app install that aborted the
# script therefore threw away every answer the user had just typed — which is
# exactly what happened when a hand-installed Zed made `brew install --cask zed`
# collide and die under `set -e`: ten questions answered, a Review block shown,
# and not one setting saved. Installs are now non-fatal too (ts_note_failure),
# but ordering is the belt to that braces: nothing after this point can cost the
# user their answers.
#
# Safe to run this early because SOURCE_DIR is derived from this script's own
# path and needs no installed tool. Only chezmoi itself is required, and the
# path and needs no installed tool, and chezmoi itself is installed just above.
# 2d. chezmoi.toml — point sourceDir at this repo.
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

# 2e. The wizard's choices into chezmoi [data]. Settings only — the agent
# WIRING (ts_agents_apply_wizard) needs the agent CLIs and stays at §6.
if [ -f "$TOML" ]; then
    # shellcheck disable=SC2086
    ts_save_config "${TS_WIZ_LEADER:-ctrl-space}" "${TS_WIZ_THEME:-dark}" "${TS_WIZ_TMUX:-ctrl-b}" ${TS_WIZ_APPS:-}
    ts_agents_save_config "${TS_WIZ_HEADROOM:-off}" "${TS_WIZ_HEADROOM_CURSOR:-mcp}" "${TS_WIZ_CAVEMAN:-off}" "${TS_WIZ_AGENTMEMORY:-off}"
    # The memory answer itself. Stored through ts_memory_apply, not through
    # ts_agents_save_config, because that helper writes only independent toggles
    # and this one also DERIVES agentmemoryEnabled. Without this line the wizard
    # asked the question and threw the answer away.
    ts_memory_apply "${TS_WIZ_MEMORY_BACKEND:-agentmemory}"
    # Stored on its own, not through ts_save_config: the mux key is positional-
    # argument-free by design so tstack mux can flip it without re-stating the rest.
    ts_wez_mux_set "${TS_WIZ_WEZ_MUX:-off}"
    ts_wez_restore_set "${TS_WIZ_WEZ_RESTORE:-off}"
    ts_atuin_set "${TS_WIZ_ATUIN:-off}"
    ts_herdr_set "${TS_WIZ_HERDR:-off}"
    ts_starship_set "${TS_WIZ_STARSHIP:-terminal-stack}" || true
    ts_cc_tts_apply_wizard_choice "${TS_WIZ_CC_TTS:-off}" off "${TS_WIZ_CC_TTS_MESSAGE:-}"
    ts_cc_tts_finish
    echo "$INFO Saved terminal-stack config to $TOML [data]"
fi

ts_brew_install_apps "$TS_WIZ_APPS" || ts_note_failure "optional apps" "retry: tstack config apps"

# 3. Terminal emulators + Nerd Font (casks) — GUI only. Skip on a headless Mac
# (e.g. a CI runner or a Mac server reached over ssh): no window server to render
# either.
if ts_is_headless; then
    echo "$INFO Headless Mac — skipping terminal emulator + Nerd Font casks (no GUI here)."
else
    # Neither channel is installed automatically: TS_WIZ_TERMINALS is whatever
    # the wizard was told, and ts_wezterm_install removes the other channel first
    # (both casks own /Applications/WezTerm.app, so they cannot coexist).
    # docs/decisions.md § "Why the WezTerm channel is a question, and why it is
    # not a saved setting" covers why nightly is offered and pre-selected.
    ts_install_cask_latest() {
        local cask="$1" name="$2"
        if brew list --cask "$cask" >/dev/null 2>&1; then
            echo "$INFO $name: installed; checking for an upgrade"
            brew upgrade --cask "$cask" 2>/dev/null || echo "$INFO $name: already at the latest."
        else
            echo "$INFO $name: installing the latest"
            brew install --cask "$cask" || echo "$WARN $name install failed; install it by hand later."
        fi
    }

    if [ -z "${TS_WIZ_TERMINALS:-}" ]; then
        echo "$INFO Terminal emulator: none selected — skipped."
    else
        local_channel="$(ts_terminals_channel "$TS_WIZ_TERMINALS")"
        if [ -n "$local_channel" ]; then
            ts_wezterm_install "$local_channel"
        else
            echo "$INFO WezTerm: not selected — skipped."
        fi
        case " $TS_WIZ_TERMINALS " in
            *" ghostty "*) ts_install_cask_latest ghostty 'Ghostty' ;;
            *)             echo "$INFO Ghostty: not selected — skipped." ;;
        esac
    fi
    # JetBrainsMono Nerd Font cask (font casks moved into homebrew/cask in 2024).
    if ! brew list --cask font-jetbrains-mono-nerd-font >/dev/null 2>&1; then
        echo "$INFO Installing JetBrainsMono Nerd Font cask"
        brew install --cask font-jetbrains-mono-nerd-font \
            || ts_note_failure "JetBrainsMono Nerd Font" "retry: brew install --cask font-jetbrains-mono-nerd-font"
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

# 6. Agent wiring. The SETTINGS were already saved before any install ran (§2e);
# this is the half that shells out to `tstack agents`, which needs the claude/codex
# CLIs to exist — so it has to stay after the app install, unlike the settings.
if [ -f "$TOML" ]; then
    ts_agents_apply_wizard "$SOURCE_DIR"
fi

# 7. Git include — stack aliases + delta config (file lands via chezmoi apply;
# git silently skips missing include files, so ordering is safe).
GIT_INC="$HOME/.config/git/terminal-stack.gitconfig"
ts_install_git_hooks "$SOURCE_DIR"

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

ts_report_installed_apps "$TS_WIZ_APPS"
# Anything optional that failed is reported here rather than having aborted the
# run. Your config was saved before any of it ran, so a failure costs you a tool,
# never an answer.
ts_report_failures

echo ""
echo "$INFO macOS bootstrap done."
echo "    Next: chezmoi apply -v"
echo "    macOS skips the windows/** subtree automatically (no /mnt/c/Users/<user>)."
