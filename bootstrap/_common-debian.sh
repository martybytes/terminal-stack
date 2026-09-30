#!/usr/bin/env bash
# _common-debian.sh — the APT half of the installer contract (see _common-posix.sh).
# Sourced by wsl-bootstrap.sh (WSL Ubuntu) and, on a Debian/Ubuntu-family host,
# by linux-bootstrap.sh. The pacman twin is _common-arch.sh; ts_common_lib in
# _detect.sh is what picks between them.
# Each function is idempotent; safe to re-source / re-run.
#
# This file is sourced, not executed. Do not `exit` here — return non-zero instead.

# Everything shared with the pacman side -- INFO/WARN, the config/wizard/detect
# sources, the distro-agnostic steps and the ORDERING in common_install_all --
# lives in _common-posix.sh. This file supplies only the apt half of the
# contract documented there.
# shellcheck source=_common-posix.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/_common-posix.sh"


common_pkg_prereqs() {
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

# Catalog id -> apt package(s). Empty means "not from apt": the id has its own
# route further down common_install_selected_apps (an upstream release, a vendor
# repo, uv). Non-zero means NO case arm at all -- a catalog row nobody taught this
# file about -- and the installer REPORTS it rather than dropping it. That silent
# drop is how fnm, node, python, uv, pipx, ruff, ipython, httpie, poetry and
# pre-commit went uninstalled on every Debian/Ubuntu/WSL box with no message.
# tests/test_distro.py asserts the mapping is total, same as ts_arch_pkg.
ts_debian_pkg() {
    case "$1" in
        delta)   echo git-delta ;;              # github fallback below
        fd)      echo fd-find ;;                # ships `fdfind`; symlinked below
        python)  echo "python3 python3-venv python3-pip" ;;
        # apt, under their own name. eza/gh/btop/duf may be absent on older
        # releases; each has a GitHub fallback below.
        tmux|fzf|ripgrep|zoxide|micro|bat|eza|tldr|gh|tree|duf|ncdu|btop|\
        glances|rclone|nvtop|pipx)
            echo "$1" ;;
        # Not apt: routed below.
        ghq|lazygit|glow|neovim|lazydocker|zed|dust|gdu|bottom|bandwhich|gping|\
        atuin|yazi|llmfit|fnm|node|uv|ruff|ipython|httpie|poetry|pre-commit)
            echo "" ;;
        *)       return 1 ;;
    esac
}

# One Python CLI in its own environment: `uv tool install`, else pipx. The twin
# of Install-TsPyTool in _config.ps1, and apt is deliberately not a route --
# Debian's python3-* packages are system libraries, and since PEP 668 a bare
# `pip install --user` refuses outright.
ts_debian_py_tool() {
    local id="$1" pkg="${2:-$1}"
    if command -v "$id" >/dev/null 2>&1; then
        echo "$INFO $id already on PATH ($(command -v "$id"))"
        return 0
    fi
    if command -v uv >/dev/null 2>&1; then
        echo "$INFO $id: uv tool install $pkg"
        uv tool install "$pkg" >/dev/null 2>&1 && return 0
        echo "$WARN $id: uv tool install failed; trying pipx"
    fi
    if command -v pipx >/dev/null 2>&1; then
        pipx install "$pkg" >/dev/null 2>&1 && return 0
    fi
    echo "$WARN $id unavailable; tick uv (or pipx), then: uv tool install $pkg"
    return 1
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
    local apt_pkgs="" id pkg
    for id in $apps; do
        # The AI CLIs, herdr and docker are install ROUTES, handled below.
        ts_app_is_ai "$id" && continue
        ts_app_is_herdr "$id" && continue
        ts_app_is_docker "$id" && continue
        case "$id" in
            nvtop) command -v nvidia-smi >/dev/null 2>&1 || continue ;;
        esac
        if ! pkg="$(ts_debian_pkg "$id")"; then
            echo "$WARN no Debian install route for catalog id '$id' — skipped (add it to ts_debian_pkg)"
            continue
        fi
        [ -n "$pkg" ] && apt_pkgs="$apt_pkgs $pkg"
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
            || common_install_github_binary "jesseduffield/lazygit" "lazygit" "lazygit_.*_[Ll]inux_$(common_arch_tag gnu)\\.tar\\.gz$" \
            || echo "$WARN lazygit unavailable (GitHub fallback failed)" ;;
    esac
    case " $apps " in *" glow "*)   common_install_glow ;; esac
    case " $apps " in *" neovim "*) common_install_neovim ;; esac
    case " $apps " in *" lazydocker "*)
        if command -v docker >/dev/null 2>&1; then
            common_install_github_binary "jesseduffield/lazydocker" "lazydocker" "lazydocker_.*_[Ll]inux_$(common_arch_tag gnu)\\.tar\\.gz$" || true
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
    # Runtimes and the Python group. None of these is in apt under a usable
    # name (Debian's `fnm` does not exist, its `ruff` lags a year, and its
    # python3-* tools are libraries), so each takes its upstream release or uv.
    # uv first: the Python tools below install THROUGH it. Both it and
    # `uv tool install` land in ~/.local/bin, which a fresh login may not have
    # on PATH yet -- and then "installed" would be followed by "unavailable".
    case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) PATH="$HOME/.local/bin:$PATH" ;; esac
    case " $apps " in *" uv "*)
        command -v uv >/dev/null 2>&1 \
            || common_install_github_binary "astral-sh/uv" "uv" "uv-$(common_arch_tag rust)-unknown-linux-gnu\\.tar\\.gz$" \
            || echo "$WARN uv unavailable (GitHub fallback failed)"
        command -v uvx >/dev/null 2>&1 \
            || common_install_github_binary "astral-sh/uv" "uvx" "uv-$(common_arch_tag rust)-unknown-linux-gnu\\.tar\\.gz$" \
            || true ;;
    esac
    case " $apps " in *" ruff "*)
        command -v ruff >/dev/null 2>&1 \
            || common_install_github_binary "astral-sh/ruff" "ruff" "ruff-$(common_arch_tag rust)-unknown-linux-gnu\\.tar\\.gz$" \
            || echo "$WARN ruff unavailable (GitHub fallback failed)" ;;
    esac
    # fnm names its x86_64 asset `fnm-linux.zip` and its ARM one `fnm-arm64.zip`.
    case " $apps " in *" fnm "*)
        local fnm_asset="fnm-linux\\.zip$"
        [ "$(common_arch_tag deb)" = arm64 ] && fnm_asset="fnm-arm64\\.zip$"
        command -v fnm >/dev/null 2>&1 \
            || common_install_github_binary "Schniz/fnm" "fnm" "$fnm_asset" \
            || echo "$WARN fnm unavailable (GitHub fallback failed)" ;;
    esac
    # `node` without fnm has nothing to install it with: say so rather than
    # reach for apt's nodejs, which is too old for gemini and competes with fnm.
    case " $apps " in *" node "*)
        case " $apps " in *" fnm "*) ;; *)
            command -v node >/dev/null 2>&1 \
                || echo "$WARN node needs fnm to install it: tstack config apps fnm" ;;
        esac ;;
    esac
    ts_install_node_lts "$apps" || true
    for id in ipython httpie poetry pre-commit; do
        case " $apps " in *" $id "*) ts_debian_py_tool "$id" || true ;; esac
    done
    ts_install_ai_clis "$apps"
    # herdr comes from herdr.dev's own installer rather than a GitHub-release
    # fallback: that script picks the right asset per architecture and wires up
    # the path `herdr update` and `herdr channel set` use. Shared with the macOS
    # pass, so there is one herdr install route on POSIX.
    ts_install_herdrs "$apps"
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


# oh-my-zsh, as it has always been here. dot_zshrc sources it when present.
common_zsh_base() { common_oh_my_zsh; }

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





