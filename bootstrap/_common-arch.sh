#!/usr/bin/env bash
# _common-arch.sh — the PACMAN half of the installer contract (see _common-posix.sh).
# Sourced by linux-bootstrap.sh on an Arch-family host; `ts_common_lib` in
# _detect.sh is what picks between this and _common-debian.sh. The apt twin is
# _common-debian.sh, and the two share everything in _common-posix.sh.
#
# Each function is idempotent; safe to re-source / re-run.
# This file is sourced, not executed. Do not `exit` here — return non-zero instead.
#
# WHY THIS IS SO MUCH SHORTER THAN THE APT TWIN.
#
# Most of _common-debian.sh is not apt — it is the absence of apt. eza, delta,
# gh, ghq, lazygit, dust, gdu, bottom, bandwhich, gping, atuin, yazi, glow,
# neovim and zed each needed a GitHub-release fetch, a PPA or a third-party apt
# repo because no Debian or Ubuntu archive carries them. Every one of them is in
# Arch's `extra`. So the whole fallback apparatus collapses into one package
# list, and only `llmfit` still needs the release tarball.
#
# The two binary-name symlinks go the same way: Debian ships bat as `batcat` and
# fd as `fdfind` (name clashes with unrelated packages), so the apt side has to
# repair PATH afterwards. Arch names both correctly. Nothing to do here.
#
# ARCH vs OMARCHY. This file is for the Arch FAMILY: it must work on plain Arch,
# where none of the `omarchy-*` commands exist. Omarchy-specific behaviour is
# gated on `ts_is_omarchy` at each site, never assumed, and each such gate says
# what Omarchy owns that we are declining to fight over.

# shellcheck source=_common-posix.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/_common-posix.sh"

# The one install verb. On Omarchy this is `omarchy-pkg-add`, which wraps
# `pacman -S --noconfirm --needed` AND verifies afterwards that each package is
# actually registered — pacman does not always report its own failure. On plain
# Arch it is that pacman call directly.
#
# `--needed` is what makes every caller idempotent, and it is why nothing here
# probes with `command -v` first: pacman already knows what is installed, and a
# binary on PATH is not evidence a package owns it.
ts_pacman_add() {
    [ "$#" -gt 0 ] || return 0
    if ts_is_omarchy && command -v omarchy-pkg-add >/dev/null 2>&1; then
        omarchy-pkg-add "$@"
    else
        sudo pacman -S --noconfirm --needed "$@"
    fi
}

common_pkg_prereqs() {
    echo "$INFO Installing base pacman packages (zsh, git, curl, unzip, JetBrains Mono, fontconfig)"
    # -Sy, not -Syu: a partial upgrade is unsupported on Arch, but refusing to
    # refresh the databases at all is worse — pacman then installs from a stale
    # index and fails on a moved version. The full upgrade is `omarchy update`'s
    # job (or the user's), never an installer's: pulling a new kernel out from
    # under a running session is not something this script gets to decide.
    sudo pacman -Sy --noconfirm >/dev/null
    ts_pacman_add zsh git curl unzip ttf-jetbrains-mono fontconfig >/dev/null \
        || echo "$WARN base package install failed; continuing"
}

# Catalog id -> Arch package name. Only the divergences carry a mapping; every
# other id IS the package name, which is the common case and stays a no-op line
# in the case below.
#
# `-` means "same as the id". An id that reaches here with no case arm is a
# catalog row nobody taught this file about, and it is REPORTED rather than
# silently dropped — a quietly missing tool is the failure this repo keeps
# being bitten by. tests/test_apps_catalog.py asserts the mapping is total.
ts_arch_pkg() {
    case "$1" in
        delta)   echo git-delta ;;
        gh)      echo github-cli ;;
        tldr)    echo tealdeer ;;
        node)    echo nodejs ;;
        pipx)    echo python-pipx ;;
        poetry)  echo python-poetry ;;
        # Runtimes: see common_install_selected_apps. Named here so the mapping
        # stays total, even where Omarchy declines to install them.
        fnm|python) echo "$1" ;;
        # In `extra` under their own name.
        tmux|eza|bat|tree|zoxide|fzf|atuin|ripgrep|fd|duf|ncdu|dust|gdu|btop|\
        bottom|glances|nvtop|lazydocker|bandwhich|gping|rclone|ghq|lazygit|\
        micro|neovim|glow|zed|yazi|uv|ruff|ipython|httpie|pre-commit)
            echo "$1" ;;
        # No Arch package. Handled out of band or skipped.
        llmfit)  echo "" ;;
        *)       return 1 ;;
    esac
}

common_install_selected_apps() {
    local apps="$*"
    if [ -z "$apps" ]; then
        echo "$INFO No optional apps selected; skipping app install"
        return 0
    fi
    echo "$INFO Optional apps install via pacman — you may be prompted for your password"
    echo "$INFO Installing selected apps: $apps"

    local pkgs="" id pkg
    for id in $apps; do
        # The AI CLIs are an install ROUTE, not a package: ts_install_ai_clis
        # below handles them and no package manager has any of them.
        ts_app_is_ai "$id" && continue

        # Runtime managers. Omarchy standardises on mise (mise-bin is in its
        # base package set, `omarchy install dev-env <lang>` is entirely
        # `mise use --global`, and env-bootstrap puts the shims on PATH), so a
        # second version manager here would compete for the same binaries and
        # the winner would be decided by PATH order. uv/pipx/ruff/ipython stay:
        # they are TOOLS, not version managers, and Omarchy's own
        # `dev-env python` installs uv too.
        case "$id" in
            fnm|node|python)
                if ts_is_omarchy; then
                    echo "$INFO $id: skipped — Omarchy manages runtimes with mise (\`mise use --global $id\`)"
                    continue
                fi ;;
        esac

        # Hardware/tooling gates, same as the apt side.
        case "$id" in
            nvtop)      command -v nvidia-smi >/dev/null 2>&1 || { echo "$INFO nvtop selected but no nvidia-smi; skipping"; continue; } ;;
            lazydocker) command -v docker     >/dev/null 2>&1 || { echo "$INFO lazydocker selected but docker not found; skipping"; continue; } ;;
        esac

        if ! pkg="$(ts_arch_pkg "$id")"; then
            echo "$WARN no Arch package mapping for catalog id '$id' — skipped (add it to ts_arch_pkg)"
            continue
        fi
        [ -n "$pkg" ] && pkgs="$pkgs $pkg"
    done

    if [ -n "$pkgs" ]; then
        # One transaction. On failure, retry singly so one bad name cannot cost
        # the user every other tool they ticked — the same shape the apt side
        # arrived at for the same reason.
        # shellcheck disable=SC2086
        if ! ts_pacman_add $pkgs >/dev/null 2>&1; then
            for pkg in $pkgs; do
                ts_pacman_add "$pkg" >/dev/null 2>&1 || echo "$WARN pacman install $pkg failed"
            done
        fi
    fi

    # The one catalog entry Arch does not package. Arch-aware asset name; see
    # common_arch_tag in _common-posix.sh (CPU architecture, not the distro).
    case " $apps " in *" llmfit "*)
        command -v llmfit >/dev/null 2>&1 \
            || common_install_github_binary "AlexsJones/llmfit" "llmfit" "llmfit-.*-$(common_arch_tag rust)-unknown-linux-gnu\\.tar\\.gz$" \
            || echo "$WARN llmfit unavailable (GitHub fallback failed)" ;;
    esac

    ts_install_ai_clis "$apps"
}

common_install_terminals() {
    local selected=" ${1:-} " channel
    if ts_is_headless || _ts_is_wsl; then return 0; fi
    if [ -z "${1:-}" ]; then echo "$INFO Terminal emulator: none selected — skipped."; return 0; fi

    channel="$(ts_terminals_channel "${1:-}")"
    if [ -n "$channel" ]; then
        # A wezterm no pacman package owns was put there by hand; leave it be.
        # Same rule as the apt side, asked of the package database rather than
        # of dpkg.
        if command -v wezterm >/dev/null 2>&1 && ! pacman -Qo "$(command -v wezterm)" >/dev/null 2>&1; then
            echo "$INFO WezTerm: already installed outside pacman ($(command -v wezterm)); leaving it alone."
        else
            ts_wezterm_install "$channel"
        fi
    else
        echo "$INFO WezTerm: not selected — skipped."
    fi

    case "$selected" in
        *" ghostty "*)
            # Ghostty IS packaged on Arch (extra/ghostty), unlike Debian where
            # upstream publishes no repo. Installing the package is all this
            # does: on Omarchy the CONFIG is Omarchy's — it themes
            # ~/.config/ghostty/config from the active theme, seds the font
            # family on `omarchy font set`, and restores it with
            # `omarchy refresh config`. `tstack ghostty` correctly refuses off
            # macOS and that stays true here.
            ts_pacman_add ghostty >/dev/null 2>&1 \
                && echo "$INFO Ghostty: installed ($(command -v ghostty 2>/dev/null || echo 'see pacman'))" \
                || echo "$WARN Ghostty: pacman install failed"
            if ts_is_omarchy; then
                echo "$INFO Ghostty config on Omarchy is Omarchy's (theme + font + refresh); the stack does not manage it."
                command -v omarchy-default-terminal >/dev/null 2>&1 \
                    && echo "      Make it the Super+Return terminal with: omarchy default terminal ghostty"
            fi ;;
        *) echo "$INFO Ghostty: not selected — skipped." ;;
    esac
}

# The zsh base.
#
# On Omarchy that is `omarchy-zsh`, the distro's own official package, and not
# oh-my-zsh: it is the zsh half of the same aliases, functions and environment
# the desktop's bash rc provides, so `zsh -l` stops being a different machine
# from the one Super+Return opens. dot_zshrc sources it when the files are there.
#
# `omarchy-setup-zsh` -- which the package prints as the next step -- is
# deliberately NOT run. It generates its own ~/.zshrc, and chezmoi owns that file
# whole-file. The generated file is only two source lines, and dot_zshrc takes
# those two directly, so nothing is lost by leaving the generator alone.
#
# Plain Arch gets oh-my-zsh like everywhere else: omarchy-zsh is in Omarchy's
# own pacman repo and is not there to install.
common_zsh_base() {
    if ts_is_omarchy; then
        echo "$INFO zsh base: omarchy-zsh (the distro's own; not oh-my-zsh)"
        if ts_pacman_add omarchy-zsh >/dev/null 2>&1; then
            echo "$INFO      installed. Do NOT run omarchy-setup-zsh: it would overwrite the"
            echo "      ~/.zshrc chezmoi owns. The stack sources its files directly."
        else
            echo "$WARN omarchy-zsh install failed; falling back to oh-my-zsh"
            common_oh_my_zsh
        fi
        return 0
    fi
    common_oh_my_zsh
}

# The login shell.
#
# On plain Arch this is the ordinary chsh the apt side does. On OMARCHY it is
# deliberately NOT: Omarchy is bash-first by construction. ~/.bashrc sources
# $OMARCHY_PATH/default/bash/rc, which is where its aliases, functions, mise /
# starship / zoxide / fzf init and completions come from, and `omarchy` ships an
# official `omarchy-zsh` package rather than expecting anyone to chsh by hand.
# Changing the login shell here would take all of that away silently, and the
# stack has no business making that call during an install.
#
# So: zsh is installed and usable, the login shell is left alone, and the user
# is told exactly how to get the stack's zsh when they want it.
common_login_shell_zsh() {
    local current_shell
    current_shell="$(getent passwd "$USER" | cut -d: -f7)"

    if ts_is_omarchy; then
        case "$current_shell" in
            */zsh) echo "$INFO Login shell is already $current_shell (left as you set it)." ;;
            *)
                echo "$INFO Login shell: leaving $current_shell alone — Omarchy is bash-first."
                echo "      Its aliases, functions and shell init live in \$OMARCHY_PATH/default/bash/rc,"
                echo "      and chsh would silently take all of that away."
                echo "      To use the stack's zsh here: run 'zsh -l', or point your terminal at it."
                ;;
        esac
        return 0
    fi

    if [ "$current_shell" != "/usr/bin/zsh" ] && [ "$current_shell" != "/bin/zsh" ]; then
        echo "$INFO chsh login shell -> /usr/bin/zsh"
        sudo chsh -s /usr/bin/zsh "$USER"
    else
        echo "$INFO Login shell already zsh"
    fi
}

# chezmoi and starship are both in Arch's `extra`, so neither gets the curl
# installer the apt side needs.
#
# starship matters more than it looks: the apt path installs to
# /usr/local/bin, which PRECEDES /usr/bin on PATH — so on a box that already has
# the packaged starship it would shadow it with an unmanaged copy that
# `pacman -Syu` (and `omarchy update`) can never upgrade. Every resolver in this
# repo (ts_chezmoi_bin, _ts_chezmoi, find_chezmoi) already falls through to
# PATH, so a /usr/bin/chezmoi is found without anything else changing.
common_chezmoi() {
    if command -v chezmoi >/dev/null 2>&1; then
        echo "$INFO chezmoi already on PATH ($(command -v chezmoi))"
        return 0
    fi
    echo "$INFO Installing chezmoi via pacman"
    ts_pacman_add chezmoi >/dev/null || echo "$WARN pacman install chezmoi failed"
}

common_starship() {
    if command -v starship >/dev/null 2>&1; then
        echo "$INFO Starship already on PATH ($(command -v starship))"
        return 0
    fi
    echo "$INFO Installing Starship via pacman"
    ts_pacman_add starship >/dev/null || echo "$WARN pacman install starship failed"
}
