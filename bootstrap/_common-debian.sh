#!/usr/bin/env bash
# _common-debian.sh — shared installer steps for Debian/Ubuntu-family bootstraps.
# Sourced by wsl-bootstrap.sh (WSL Ubuntu) and linux-bootstrap.sh (native Debian/Ubuntu).
# Each function is idempotent; safe to re-source / re-run.
#
# This file is sourced, not executed. Do not `exit` here — return non-zero instead.

INFO=$'\033[1;34m==>\033[0m'
WARN=$'\033[1;33m!!\033[0m'

# Config store + wizard helpers (app catalog, chord/theme mapping, prompts) and
# environment detection (headless vs GUI).
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

common_apt_prereqs() {
    echo "$INFO Installing base apt packages (zsh, git, curl, unzip, JetBrains Mono regular font)"
    sudo apt-get update -qq
    # Hard prerequisites only — must be in apt on any supported Debian/Ubuntu.
    # The toggleable CLI tools (eza/fzf/bat/.../tmux) are installed per the user's
    # selection by common_install_selected_apps.
    sudo apt-get install -y \
        zsh git curl unzip \
        fonts-jetbrains-mono fontconfig \
        >/dev/null
}

# Install the user-selected toggleable apps (catalog ids). No-op when the list is
# empty — the wizard's "customize / decline all" path must not fall back to recommended.
# apt where it has them; the bespoke installers (glow/neovim/eza/delta/zed/…)
# otherwise. GPU/docker-gated ids no-op when the host lacks the hardware/tool.
common_install_selected_apps() {
    local apps="$*"
    if [ -z "$apps" ]; then
        echo "$INFO No optional apps selected; skipping app install"
        return 0
    fi
    if command -v apt-get >/dev/null 2>&1; then
        echo "$INFO Optional apps install via sudo apt — you may be prompted for your password"
    fi
    echo "$INFO Installing selected apps: $apps"
    local apt_pkgs="" id
    for id in $apps; do
        case "$id" in
            tmux)    apt_pkgs="$apt_pkgs tmux" ;;
            fzf)     apt_pkgs="$apt_pkgs fzf" ;;
            ripgrep) apt_pkgs="$apt_pkgs ripgrep" ;;
            zoxide)  apt_pkgs="$apt_pkgs zoxide" ;;
            micro)   apt_pkgs="$apt_pkgs micro" ;;
            bat)     apt_pkgs="$apt_pkgs bat" ;;
            eza)     apt_pkgs="$apt_pkgs eza" ;;        # may be absent pre-23.10; github fallback below
            delta)   apt_pkgs="$apt_pkgs git-delta" ;;
            tldr)    apt_pkgs="$apt_pkgs tldr" ;;
            gh)      apt_pkgs="$apt_pkgs gh" ;;          # universe on 24.04+; github fallback below
            fd)      apt_pkgs="$apt_pkgs fd-find" ;;      # ships the binary as `fdfind`; symlinked below
            tree)    apt_pkgs="$apt_pkgs tree" ;;
            duf)     apt_pkgs="$apt_pkgs duf" ;;
            ncdu)    apt_pkgs="$apt_pkgs ncdu" ;;
            btop)    apt_pkgs="$apt_pkgs btop" ;;         # 22.04+; github fallback below
            glances) apt_pkgs="$apt_pkgs glances" ;;
            rclone)  apt_pkgs="$apt_pkgs rclone" ;;      # apt lags upstream; fine for tstack smb
            nvtop)   command -v nvidia-smi >/dev/null 2>&1 && apt_pkgs="$apt_pkgs nvtop" ;;
        esac
    done
    if [ -n "$apt_pkgs" ]; then
        # shellcheck disable=SC2086
        if ! sudo apt-get install -y $apt_pkgs >/dev/null 2>&1; then
            for id in $apt_pkgs; do
                sudo apt-get install -y "$id" >/dev/null 2>&1 && continue
                case "$id" in
                    # eza/git-delta aren't in older Debian/Ubuntu repos by design —
                    # the GitHub-release fallback below installs them and reports
                    # the real outcome. Don't cry wolf here.
                    eza|git-delta|gh|btop|duf) : ;;
                    *) echo "$WARN apt install $id failed" ;;
                esac
            done
        fi
    fi
    case " $apps " in *" bat "*) common_bat_symlink ;; esac
    # eza/delta: prefer apt, else upstream release. Only warn if BOTH fail.
    case " $apps " in *" eza "*)
        command -v eza >/dev/null 2>&1 \
            || common_install_github_binary "eza-community/eza" "eza" "eza_$(common_arch_tag gnu)-unknown-linux-gnu\\.tar\\.gz$" \
            || echo "$WARN eza unavailable (not in apt and GitHub fallback failed)" ;;
    esac
    case " $apps " in *" delta "*)
        command -v delta >/dev/null 2>&1 \
            || common_install_github_binary "dandavison/delta" "delta" "delta-.*-$(common_arch_tag gnu)-unknown-linux-gnu\\.tar\\.gz$" \
            || echo "$WARN delta unavailable (not in apt and GitHub fallback failed)" ;;
    esac
    # gh / ghq / lazygit — the workspace-organizer toolchain. ghq and lazygit are
    # in no Debian/Ubuntu archive, and gh only from 24.04, so the upstream release
    # is the reliable path on all three. Arch-aware: unlike eza/delta above, these
    # are commonly wanted on arm64 boxes too.
    case " $apps " in *" gh "*)
        command -v gh >/dev/null 2>&1 \
            || common_install_github_binary "cli/cli" "gh" "gh_.*_linux_$(common_arch_tag deb)\\.tar\\.gz$" \
            || echo "$WARN gh unavailable (not in apt and GitHub fallback failed)" ;;
    esac
    case " $apps " in *" ghq "*)
        command -v ghq >/dev/null 2>&1 \
            || common_install_github_binary "x-motemen/ghq" "ghq" "ghq_linux_$(common_arch_tag deb)\\.zip$" \
            || echo "$WARN ghq unavailable (GitHub fallback failed)" ;;
    esac
    case " $apps " in *" lazygit "*)
        command -v lazygit >/dev/null 2>&1 \
            || common_install_github_binary "jesseduffield/lazygit" "lazygit" "lazygit_.*_Linux_$(common_arch_tag gnu)\\.tar\\.gz$" \
            || echo "$WARN lazygit unavailable (GitHub fallback failed)" ;;
    esac
    case " $apps " in *" glow "*)   common_install_glow ;; esac
    case " $apps " in *" neovim "*) common_install_neovim ;; esac
    case " $apps " in *" lazydocker "*)
        if command -v docker >/dev/null 2>&1; then
            common_install_github_binary "jesseduffield/lazydocker" "lazydocker" "lazydocker_.*_Linux_$(common_arch_tag gnu)\\.tar\\.gz$" || true
        else
            echo "$INFO lazydocker selected but docker not found; skipping"
        fi ;;
    esac
    case " $apps " in *" zed "*)
        if ! command -v zed >/dev/null 2>&1; then
            echo "$INFO Installing Zed via zed.dev install.sh"
            curl -f https://zed.dev/install.sh | sh >/dev/null 2>&1 || echo "$WARN Zed install failed (headless / network?)"
        fi ;;
    esac
    case " $apps " in *" fd "*) common_fd_symlink ;; esac
    # dust / gdu / bottom / bandwhich / gping are in no Debian or Ubuntu archive,
    # and btop/duf only in recent ones — upstream releases for all of them. Every
    # pattern is arch-aware via common_arch_tag: these are wanted on arm64 boxes
    # (Raspberry Pi, Ampere VMs) as much as on x86_64.
    case " $apps " in *" dust "*)
        command -v dust >/dev/null 2>&1 \
            || common_install_github_binary "bootandy/dust" "dust" "dust-.*-$(common_arch_tag gnu)-unknown-linux-gnu\\.tar\\.gz$" \
            || echo "$WARN dust unavailable (GitHub fallback failed)" ;;
    esac
    case " $apps " in *" gdu "*)
        command -v gdu >/dev/null 2>&1 \
            || common_install_github_binary "dundee/gdu" "gdu" "gdu_linux_$(common_arch_tag deb)\\.tgz$" \
            || echo "$WARN gdu unavailable (GitHub fallback failed)" ;;
    esac
    case " $apps " in *" bottom "*)
        command -v btm >/dev/null 2>&1 \
            || common_install_github_binary "ClementTsang/bottom" "btm" "bottom_$(common_arch_tag gnu)-unknown-linux-gnu\\.tar\\.gz$" \
            || echo "$WARN bottom unavailable (GitHub fallback failed)" ;;
    esac
    case " $apps " in *" bandwhich "*)
        command -v bandwhich >/dev/null 2>&1 \
            || common_install_github_binary "imsnif/bandwhich" "bandwhich" "bandwhich-.*-$(common_arch_tag gnu)-unknown-linux-(gnu|musl)\\.tar\\.gz$" \
            || echo "$WARN bandwhich unavailable (GitHub fallback failed)"
        # It reads raw sockets, so it needs CAP_NET_RAW or sudo to actually run.
        command -v bandwhich >/dev/null 2>&1 \
            && echo "$INFO bandwhich needs elevated rights: run it with sudo, or grant CAP_NET_RAW once" ;;
    esac
    case " $apps " in *" gping "*)
        command -v gping >/dev/null 2>&1 \
            || common_install_github_binary "orf/gping" "gping" "gping-$(common_arch_tag gnu)-unknown-linux-(gnu|musl)\\.tar\\.gz$" \
            || echo "$WARN gping unavailable (GitHub fallback failed)" ;;
    esac
    # atuin and yazi are cargo-dist projects: their ARM asset says `aarch64`,
    # not `arm64`, hence `common_arch_tag rust`. Neither is in any Debian or
    # Ubuntu archive, so there is no apt arm above to fall back from.
    case " $apps " in *" atuin "*)
        command -v atuin >/dev/null 2>&1 \
            || common_install_github_binary "atuinsh/atuin" "atuin" "atuin-$(common_arch_tag rust)-unknown-linux-gnu\\.tar\\.gz$" \
            || echo "$WARN atuin unavailable (GitHub fallback failed)" ;;
    esac
    # yazi ships a .zip, and two binaries: `yazi` (the TUI) and `ya` (its CLI,
    # needed by plugin management). Fetch both; the second is best-effort.
    case " $apps " in *" yazi "*)
        command -v yazi >/dev/null 2>&1 \
            || common_install_github_binary "sxyazi/yazi" "yazi" "yazi-$(common_arch_tag rust)-unknown-linux-gnu\\.zip$" \
            || echo "$WARN yazi unavailable (GitHub fallback failed)"
        command -v ya >/dev/null 2>&1 \
            || common_install_github_binary "sxyazi/yazi" "ya" "yazi-$(common_arch_tag rust)-unknown-linux-gnu\\.zip$" \
            || true ;;
    esac
    case " $apps " in *" btop "*)
        command -v btop >/dev/null 2>&1 \
            || common_install_github_binary "aristocratos/btop" "btop" "btop-$(common_arch_tag gnu)-linux-musl\\.tbz$" \
            || echo "$WARN btop unavailable (not in apt and GitHub fallback failed)" ;;
    esac
    case " $apps " in *" duf "*)
        command -v duf >/dev/null 2>&1 \
            || common_install_github_binary "muesli/duf" "duf" "duf_.*_linux_$(common_arch_tag deb)\\.tar\\.gz$" \
            || echo "$WARN duf unavailable (not in apt and GitHub fallback failed)" ;;
    esac
    # Not in apt on any release, and the upstream tarball is the only path. The
    # "rust" arch style is the one the release names use (x86_64/aarch64).
    case " $apps " in *" llmfit "*)
        command -v llmfit >/dev/null 2>&1 \
            || common_install_github_binary "AlexsJones/llmfit" "llmfit" "llmfit-.*-$(common_arch_tag rust)-unknown-linux-gnu\\.tar\\.gz$" \
            || echo "$WARN llmfit unavailable (GitHub fallback failed)" ;;
    esac
    ts_install_ai_clis "$apps"
}

# glow — Charm's terminal markdown renderer (`glow file.md`; `glow .` for the TUI browser).
# Not in the default Debian/Ubuntu apt repos, so add Charm's apt repository (keyring +
# source) and install from there. Idempotent: the keyring is written once (gpg --dearmor
# refuses to overwrite an existing file, so we guard on its presence), the source line is
# rewritten harmlessly, and the install no-ops once glow is on PATH. Non-fatal — a repo or
# network hiccup must not abort the whole bootstrap.
common_install_glow() {
    if command -v glow >/dev/null 2>&1; then
        echo "$INFO glow already on PATH ($(command -v glow))"
        return 0
    fi
    echo "$INFO Adding Charm apt repo and installing glow"
    command -v gpg >/dev/null 2>&1 || sudo apt-get install -y gnupg >/dev/null 2>&1 || true
    sudo mkdir -p /etc/apt/keyrings
    if [ ! -s /etc/apt/keyrings/charm.gpg ]; then
        curl -fsSL https://repo.charm.sh/apt/gpg.key \
            | sudo gpg --dearmor -o /etc/apt/keyrings/charm.gpg
    fi
    echo "deb [signed-by=/etc/apt/keyrings/charm.gpg] https://repo.charm.sh/apt/ * *" \
        | sudo tee /etc/apt/sources.list.d/charm.list >/dev/null
    sudo apt-get update -qq
    sudo apt-get install -y glow >/dev/null 2>&1 || echo "$WARN apt install glow failed (Charm repo)"
}

# GUI terminal emulators — native desktop Linux only. WSL never gets one (the
# GUI lives on the Windows host) and neither does a headless server; the caller
# gates the question, this gates the install as a second belt.
#
# Neither WezTerm channel is installed automatically. Upstream's own apt repo is
# used rather than an AppImage because it is the only method with an update path
# — `apt upgrade` keeps it current — and it carries BOTH channels, so switching
# is a package swap. The install itself lives in _wezterm.sh (ts_wezterm_install),
# shared with macOS and with `tstack config wezterm`.
_ts_is_wsl() { [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; }


common_install_terminals() {
    local selected=" ${1:-} " channel
    if ts_is_headless || _ts_is_wsl; then return 0; fi
    if [ -z "${1:-}" ]; then echo "$INFO Terminal emulator: none selected — skipped."; return 0; fi
    channel="$(ts_terminals_channel "${1:-}")"
    if [ -n "$channel" ]; then
        # A wezterm that no apt package owns was put there by hand; leave it be.
        if command -v wezterm >/dev/null 2>&1 \
           && ! dpkg -s wezterm >/dev/null 2>&1 \
           && ! dpkg -s wezterm-nightly >/dev/null 2>&1; then
            echo "$INFO WezTerm: already installed outside apt ($(command -v wezterm)); leaving it alone."
        else
            ts_wezterm_install "$channel"
        fi
    else
        echo "$INFO WezTerm: not selected — skipped."
    fi
    case "$selected" in
        *" ghostty "*)
            if command -v ghostty >/dev/null 2>&1; then
                echo "$INFO Ghostty: already installed ($(command -v ghostty))"
            else
                # Ghostty publishes no official Debian/Ubuntu repo, and this stack
                # does not ship a guessed third-party one. Point at the source
                # rather than run something that may not be what upstream means.
                echo "$INFO Ghostty: no official Debian/Ubuntu package to install from here."
                echo "      See https://ghostty.org/download for the current Linux options."
            fi ;;
        *) echo "$INFO Ghostty: not selected — skipped." ;;
    esac
}

# neovim — current release via the official PPA. apt's neovim is too old on older
# Ubuntu (0.6 on 22.04 jammy), so add ppa:neovim-ppa/unstable and install from there.
# Idempotent (skips if nvim is on PATH); non-fatal. On Debian (no PPAs) the
# add-apt-repository step warns and the install falls back to Debian's own neovim.
# A CLI editor, so safe on every Debian/Ubuntu target including headless servers.
common_install_neovim() {
    if command -v nvim >/dev/null 2>&1; then
        echo "$INFO neovim already on PATH ($(command -v nvim))"
        return 0
    fi
    echo "$INFO Adding neovim PPA and installing neovim"
    sudo apt-get install -y software-properties-common >/dev/null 2>&1 || true
    sudo add-apt-repository -y ppa:neovim-ppa/unstable >/dev/null 2>&1 \
        || echo "$WARN add-apt-repository ppa:neovim-ppa/unstable failed (non-Ubuntu?); using distro neovim"
    sudo apt-get update -qq
    sudo apt-get install -y neovim >/dev/null 2>&1 || echo "$WARN apt install neovim failed"
}

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

# Install eza and git-delta from upstream releases if apt didn't provide them.
common_install_optional_binaries() {
    # eza: tar.gz with a single 'eza' binary at the root.
    common_install_github_binary "eza-community/eza" "eza" "eza_$(common_arch_tag gnu)-unknown-linux-gnu\\.tar\\.gz$" || true
    # git-delta: ships as 'delta'. Asset name pattern: delta-<version>-x86_64-unknown-linux-gnu.tar.gz.
    common_install_github_binary "dandavison/delta" "delta" "delta-.*-$(common_arch_tag gnu)-unknown-linux-gnu\\.tar\\.gz$" || true
}

common_bat_symlink() {
    mkdir -p "$HOME/.local/bin"
    if [ ! -e "$HOME/.local/bin/bat" ]; then
        echo "$INFO Symlinking ~/.local/bin/bat -> /usr/bin/batcat"
        ln -sf /usr/bin/batcat "$HOME/.local/bin/bat"
    fi
}

# Debian/Ubuntu ship fd as the `fd-find` package with the binary named `fdfind`
# (a name clash with an unrelated `fd` package). Same treatment as batcat: the
# WezTerm sessionizer and everything else expect `fd` on PATH.
common_fd_symlink() {
    if [ -x /usr/bin/fdfind ] && [ ! -e "$HOME/.local/bin/fd" ]; then
        mkdir -p "$HOME/.local/bin"
        ln -sf /usr/bin/fdfind "$HOME/.local/bin/fd"
        echo "$INFO linked fdfind -> ~/.local/bin/fd"
    fi
}

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

common_login_shell_zsh() {
    local current_shell
    current_shell="$(getent passwd "$USER" | cut -d: -f7)"
    if [ "$current_shell" != "/usr/bin/zsh" ] && [ "$current_shell" != "/bin/zsh" ]; then
        echo "$INFO chsh login shell -> /usr/bin/zsh"
        sudo chsh -s /usr/bin/zsh "$USER"
    else
        echo "$INFO Login shell already zsh"
    fi
}

common_chezmoi() {
    if [ ! -x "$HOME/.local/bin/chezmoi" ]; then
        echo "$INFO Installing chezmoi to ~/.local/bin"
        sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin" >/dev/null
    else
        echo "$INFO chezmoi already present at ~/.local/bin/chezmoi"
    fi
}

common_starship() {
    if ! command -v starship >/dev/null 2>&1; then
        echo "$INFO Installing Starship to /usr/local/bin"
        sudo curl -sS https://starship.rs/install.sh | sudo sh -s -- -y -b /usr/local/bin
    else
        echo "$INFO Starship already on PATH"
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
    common_apt_prereqs
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
    common_oh_my_zsh
    common_login_shell_zsh
    common_starship
    common_nerd_font_jetbrains
    common_git_include
    common_workspace_config
    ts_report_installed_apps "$TS_WIZ_APPS"
    ts_report_failures
}
