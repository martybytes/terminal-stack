#!/usr/bin/env bash
# _common-posix.sh — the installer steps that are the same on every Linux, and
# the orchestration that sequences them.
#
# Sourced by _common-debian.sh (apt: WSL Ubuntu + native Debian/Ubuntu) and
# _common-arch.sh (pacman: Arch and Omarchy). Those two files supply ONLY the
# parts that genuinely differ, as a fixed contract:
#
#   common_pkg_prereqs            base packages the rest of the bootstrap needs
#   common_install_selected_apps  the catalog ids the user ticked
#   common_install_terminals      the GUI terminal emulator, if any
#   common_zsh_base               the zsh framework ~/.zshrc expects to find
#   common_login_shell_zsh        whether/how the login shell changes
#   common_chezmoi                install chezmoi
#   common_starship               install the starship binary
#
# Everything else lives here, once. This split exists because the Arch support
# was written by copying the Debian file, and a copy of `common_install_all` is
# a copy of the ORDERING — which encodes two separate incidents (persistence
# before optional installs; chezmoi before persistence) and would have drifted
# the first time either was touched on one side only.
#
# This file is sourced, not executed. Do not `exit` here — return non-zero instead.

INFO=$'\033[1;34m==>\033[0m'
WARN=$'\033[1;33m!!\033[0m'

# Config store + wizard helpers (app catalog, chord/theme mapping, prompts) and
# environment detection (headless vs GUI, and which distro this is).
# shellcheck source=_config.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/_config.sh"
# shellcheck source=_wizard.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/_wizard.sh"
# shellcheck source=_detect.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/_detect.sh"

common_require_non_root() {
    if [ "$(id -u)" -eq 0 ]; then
        echo "$WARN Don't run this as root. Run as your normal user; sudo will prompt as needed."
        return 1
    fi
}

_ts_is_wsl() { [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; }

# The oh-my-zsh install itself, shared because both distro halves reach for it --
# Omarchy is the only host that uses something else. Called through
# common_zsh_base rather than directly, so which base a platform gets is a
# contract decision and not a shared default anybody can quietly diverge from.
common_oh_my_zsh() {
    if [ ! -d "$HOME/.oh-my-zsh" ]; then
        echo "$INFO Installing oh-my-zsh"
        RUNZSH=no CHSH=no KEEP_ZSHRC=no sh -c \
            "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" \
            >/dev/null
    else
        echo "$INFO oh-my-zsh already present at ~/.oh-my-zsh"
    fi
}

common_nerd_font_jetbrains() {
    if ts_is_headless; then
        echo "$INFO Headless server — skipping Nerd Font download (no GUI terminal renders it here)."
        return 0
    fi
    if ! fc-list 2>/dev/null | grep -q "JetBrainsMono Nerd Font"; then
        echo "$INFO Downloading JetBrainsMono Nerd Font zip"
        mkdir -p "$HOME/.local/share/fonts/JetBrainsMonoNerdFont"
        local tmp_zip
        tmp_zip=$(mktemp /tmp/jbm-nf.XXXXXX.zip)
        curl -fL --silent --show-error \
            -o "$tmp_zip" \
            https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.zip
        # `-o` overwrites without prompting. Without it, a re-run where the
        # files already exist on disk (e.g. fontconfig lost them but the .ttf
        # files survived) prompts "replace ...? [y]es..." on stdin, which is
        # /dev/null under the curl|bash installer flow and aborts the unzip.
        unzip -qo "$tmp_zip" -d "$HOME/.local/share/fonts/JetBrainsMonoNerdFont/"
        rm -f "$tmp_zip"
        fc-cache -f "$HOME/.local/share/fonts" >/dev/null
    else
        # The guard is fontconfig, not a package name, and that is what makes
        # this a no-op on Omarchy: ttf-jetbrains-mono-nerd-basic already
        # satisfies it, so no second copy of the family lands in ~/.local/share.
        echo "$INFO JetBrainsMono Nerd Font already in fontconfig"
    fi
}

# Prompt helper for curl|bash flows: stdin is the script pipe, so read from
# /dev/tty instead. Falls back to the default (prints nothing) when there is
# no controlling terminal (CI, true non-interactive).
# Usage: common_tty_prompt "Question [default]: " → echoes the answer or "".
common_tty_prompt() {
    local answer=""
    # Read with readline (-e) so Backspace/arrow keys edit the line instead of
    # inserting raw control codes; -p shows the prompt. Skip when no tty.
    if { true > /dev/tty; } 2>/dev/null; then
        IFS= read -e -r -p "$1" answer < /dev/tty || answer=""
    fi
    echo "$answer"
}

# Workspace directory for the ws/wsp/wspu shell functions.
# $WORKSPACE_DIR env → use without prompting (scripted installs). Otherwise
# prompt on /dev/tty with the autodetected candidate as default. The answer is
# persisted to ~/.zshrc.local ONLY when it differs from the autodetect — the
# shell-side _ts_workspace() covers the detected case on its own.
common_workspace_config() {
    local detected="" d choice
    for d in /mnt/c/DATA/Workspace "$HOME/Documents/Workspace" \
             "$HOME/workspace" "$HOME/Workspace"; do
        [ -d "$d" ] && { detected="$d"; break; }
    done

    choice="${WORKSPACE_DIR:-}"
    if [ -n "$choice" ]; then
        echo "$INFO WORKSPACE_DIR=$choice (from env; skipping prompt)"
    else
        choice="$(common_tty_prompt "Workspace directory [${detected:-none}]: ")"
        choice="${choice:-$detected}"
        # Expand a leading ~ — it's read as a literal here, so it would land in
        # ~/.zshrc.local as export WORKSPACE_DIR="~/foo" (unexpanded) and break ws.
        case "$choice" in "~") choice="$HOME" ;; "~/"*) choice="$HOME/${choice#\~/}" ;; esac
    fi

    if [ -z "$choice" ]; then
        echo "$WARN No workspace directory found or chosen."
        echo "    Set one later: export WORKSPACE_DIR=... in ~/.zshrc.local"
        return 0
    fi
    [ -d "$choice" ] || echo "$WARN $choice does not exist (yet) — ws will warn until it does."

    if [ "$choice" = "$detected" ]; then
        echo "$INFO Workspace: $choice (autodetected; no override needed)"
        return 0
    fi

    local rc="$HOME/.zshrc.local"
    if [ -f "$rc" ] && grep -q '^export WORKSPACE_DIR=' "$rc"; then
        sed -i "s|^export WORKSPACE_DIR=.*|export WORKSPACE_DIR=\"$choice\"|" "$rc"
        echo "$INFO Updated WORKSPACE_DIR in $rc"
    else
        printf 'export WORKSPACE_DIR="%s"\n' "$choice" >> "$rc"
        echo "$INFO Wrote WORKSPACE_DIR=$choice to $rc"
    fi
}

# Hook the stack's git aliases + delta config into the global gitconfig.
# The included file lands via chezmoi apply (which runs after bootstrap);
# git silently skips missing include files, so ordering is safe.
#
# Additive on purpose, and that is what makes it safe on a machine where
# ~/.config/git/config is somebody else's symlink (Omarchy fleets stow it):
# nothing here writes that file. The include lands in ~/.gitconfig.
common_git_include() {
    local inc="$HOME/.config/git/terminal-stack.gitconfig"
    if git config --global --get-all include.path 2>/dev/null | grep -qF "terminal-stack.gitconfig"; then
        echo "$INFO git include.path already set"
    else
        echo "$INFO Adding git include.path -> $inc"
        git config --global --add include.path "$inc"
    fi
}

# Run all standard install steps. The wizard runs early (collects leader/theme/
# app choices into TS_WIZ_*); the selected apps are then installed. Persisting the
# choices into chezmoi [data] happens in the wrapper AFTER chezmoi.toml is written
# (ts_save_config) — chezmoi.toml may not exist yet at this point.
common_install_all() {
    common_pkg_prereqs
    ts_confirm_headless
    # Desktop Linux is asked which GUI terminal emulator it wants. WSL is not —
    # the GUI lives on the Windows host — and neither is a headless server.
    if ! ts_is_headless && ! _ts_is_wsl; then TS_WIZ_ASK_TERMINALS=1; fi
    # rc 3 is "quit at the review": stop, but it is not a failure. Returning 1
    # for it made install-linux.sh print "a step failed silently" at someone who
    # simply typed q.
    ts_wizard_collect; _wiz_rc=$?
    case "$_wiz_rc" in
        0) ;;
        3) echo "$INFO wizard cancelled - nothing was installed or changed."; return 3 ;;
        *) return "$_wiz_rc" ;;
    esac
    # chezmoi FIRST, then persist, then everything optional.
    #
    # These used to run in the other order, so an optional install that aborted
    # the script threw away every answer the user had just typed. That is not
    # hypothetical: a hand-installed app made a cask collide and die under
    # `set -e`, and ten answered questions were silently lost. Persistence needs
    # chezmoi (ts_save_config runs `chezmoi init` to regenerate the derived
    # keys), which is the only reason it was late in the first place — so
    # chezmoi moves up rather than persistence moving down.
    #
    # TS_PERSIST_HOOK is the wrapper's persistence function; each wrapper owns
    # its own because native Linux and WSL differ (windowsUsername).
    common_chezmoi
    if [ -n "${TS_PERSIST_HOOK:-}" ] && command -v "$TS_PERSIST_HOOK" >/dev/null 2>&1; then
        "$TS_PERSIST_HOOK"
    fi
    common_install_selected_apps "$TS_WIZ_APPS" || ts_note_failure "optional apps" "retry: tstack config apps"
    common_install_terminals "${TS_WIZ_TERMINALS:-}" || ts_note_failure "terminal emulator" "retry: tstack config wezterm install <channel>"
    common_zsh_base
    common_login_shell_zsh
    common_starship
    common_nerd_font_jetbrains
    common_git_include
    common_workspace_config
    ts_report_installed_apps "$TS_WIZ_APPS"
    ts_report_failures
}

# ── Upstream release binaries ─────────────────────────────────────────────────
# Shared because "no distro packages this, fetch the release tarball" is not an
# apt problem. Arch needs it far less -- every tool in the catalog but llmfit is
# in `extra` -- but it needs it for exactly that one, and a second copy of this
# would be a second place for the ARM asset-name trap below to be got wrong.
#
# NOTE the name: `common_arch_tag` predates Arch Linux support and means CPU
# architecture, not the distro. Renaming it would churn every call site and the
# test that pins the aarch64/arm64 split, for no behaviour.

# uname -m -> the token upstream release assets actually use. Three spellings
# are common and projects disagree, so callers say which they need:
#   deb  -> amd64 / arm64     (gh, ghq, and most Go projects)
#   gnu  -> x86_64 / arm64    (lazygit, eza, delta)
#   rust -> x86_64 / aarch64  (atuin, yazi — anything shipped by cargo-dist)
# The rust/gnu split is only the ARM spelling, and getting it wrong fails
# *silently on ARM only*: the asset regex simply matches nothing, x86_64 boxes
# keep working, and the tool is quietly missing on every Pi/ARM server.
# Unknown machines fall back to the 64-bit Intel asset, which is what the older
# call sites hardcoded anyway.
common_arch_tag() {
    local style="${1:-deb}" m
    m="$(uname -m 2>/dev/null || echo x86_64)"
    case "$m" in
        aarch64|arm64) if [ "$style" = rust ]; then echo aarch64; else echo arm64; fi ;;
        *) if [ "$style" = deb ]; then echo amd64; else echo x86_64; fi ;;
    esac
}

# Fetch the latest release tarball from a GitHub repo for the current arch and
# extract the named binary into ~/.local/bin. Skips if the binary is already on PATH.
# Usage: common_install_github_binary <repo> <binary-name> <asset-grep-pattern>
common_install_github_binary() {
    local repo="$1" bin_name="$2" asset_pattern="$3"
    if command -v "$bin_name" >/dev/null 2>&1; then
        echo "$INFO $bin_name already on PATH ($(command -v "$bin_name"))"
        return 0
    fi
    echo "$INFO Installing $bin_name from $repo (apt didn't have it)"
    mkdir -p "$HOME/.local/bin"
    local tmp_dir asset_url
    tmp_dir="$(mktemp -d)"
    asset_url=$(curl -fsSL "https://api.github.com/repos/$repo/releases/latest" \
        | grep -oE '"browser_download_url":[[:space:]]*"[^"]+"' \
        | cut -d'"' -f4 \
        | grep -E "$asset_pattern" \
        | head -n1)
    if [ -z "$asset_url" ]; then
        echo "$WARN Could not find asset matching '$asset_pattern' in latest $repo release."
        rm -rf "$tmp_dir"
        return 1
    fi
    local archive="$tmp_dir/$(basename "$asset_url")"
    curl -fL --silent --show-error -o "$archive" "$asset_url"
    case "$archive" in
        *.tar.gz|*.tgz) tar -xzf "$archive" -C "$tmp_dir" ;;
        *.zip)          unzip -q "$archive" -d "$tmp_dir" ;;
        *)              echo "$WARN Unsupported archive format: $archive"; rm -rf "$tmp_dir"; return 1 ;;
    esac
    local found
    found=$(find "$tmp_dir" -type f -name "$bin_name" -executable | head -n1)
    if [ -z "$found" ]; then
        # Some archives ship the binary not marked +x; try a non-executable match.
        found=$(find "$tmp_dir" -type f -name "$bin_name" | head -n1)
    fi
    if [ -z "$found" ]; then
        echo "$WARN Could not locate '$bin_name' inside extracted archive."
        rm -rf "$tmp_dir"
        return 1
    fi
    install -m 0755 "$found" "$HOME/.local/bin/$bin_name"
    rm -rf "$tmp_dir"
    echo "$INFO Installed ~/.local/bin/$bin_name"
}
