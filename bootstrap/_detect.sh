#!/usr/bin/env bash
# _detect.sh — environment detection for the POSIX bootstraps (headless vs GUI).
# Sourced by _common-debian.sh (WSL/Linux) and mac-bootstrap.sh after _config.sh
# and _wizard.sh (it uses ts_tty_prompt for the confirm prompt).
#
# A "headless" host is a server with no graphical session — typically reached
# over ssh/PuTTY. On such hosts the stack should NOT download the Nerd Font (no
# GUI terminal renders it) and should NOT ask the WezTerm leader-key question
# (WezTerm is a GUI app that isn't installed there). tmux/starship/zsh/CLI tools
# are still installed — those are the genuinely useful headless pieces.
#
# This file is sourced, not executed. Do not `exit`; return non-zero instead.

: "${INFO:=$'\033[1;34m==>\033[0m'}"
: "${WARN:=$'\033[1;33m!!\033[0m'}"

# Best-effort auto-detection. Returns 0 (headless) / 1 (graphical desktop).
_ts_headless_autodetect() {
    # WSL is never headless: it renders in a Windows GUI terminal (WezTerm /
    # Windows Terminal) on the Windows side, which needs the font there.
    if [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
        return 1
    fi
    # An X or Wayland display means a local graphical session.
    if [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; then
        return 1
    fi
    # macOS desktop always has a window server (Aqua); only headless when SSH'd
    # into a Mac with no console session — fall through to the SSH check.
    # An SSH session with no display is the canonical headless case.
    if [ -n "${SSH_CONNECTION:-}" ] || [ -n "${SSH_TTY:-}" ] || [ -n "${SSH_CLIENT:-}" ]; then
        return 0
    fi
    # systemd default target: multi-user → server, graphical → desktop.
    if command -v systemctl >/dev/null 2>&1; then
        case "$(systemctl get-default 2>/dev/null)" in
            multi-user.target|multi-user) return 0 ;;
            graphical.target|graphical)   return 1 ;;
        esac
    fi
    # macOS with a console but no SSH: treat as graphical.
    if [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
        return 1
    fi
    # No display, no SSH hint, no systemd answer: assume headless (server-class).
    return 0
}

# Resolve TS_HEADLESS_RESOLVED to 1 (headless) or 0 (graphical). Honors an
# explicit TS_HEADLESS env override; otherwise auto-detects.
ts_detect_headless() {
    case "${TS_HEADLESS:-}" in
        1|y|Y|yes|YES|true|TRUE)  TS_HEADLESS_RESOLVED=1; return 0 ;;
        0|n|N|no|NO|false|FALSE)  TS_HEADLESS_RESOLVED=0; return 0 ;;
    esac
    if _ts_headless_autodetect; then TS_HEADLESS_RESOLVED=1; else TS_HEADLESS_RESOLVED=0; fi
}

# True when the resolved environment is headless (detects lazily on first use).
ts_is_headless() {
    [ -n "${TS_HEADLESS_RESOLVED:-}" ] || ts_detect_headless
    [ "${TS_HEADLESS_RESOLVED:-0}" = "1" ]
}

# Print the detection and, unless forced via TS_HEADLESS, let the user flip it on
# the controlling terminal. Sets TS_HEADLESS_RESOLVED. Safe under curl|bash.
# Call this once, early in the bootstrap, before the font/wizard steps.
ts_confirm_headless() {
    ts_detect_headless
    local forced=0
    case "${TS_HEADLESS:-}" in ?*) forced=1 ;; esac

    if ts_is_headless; then
        echo "$INFO Environment: headless server (no graphical session detected)"
    else
        echo "$INFO Environment: graphical desktop"
    fi

    if [ "$forced" = "1" ]; then
        echo "$INFO (forced via TS_HEADLESS=$TS_HEADLESS)"
        return 0
    fi

    local ans
    if ts_is_headless; then
        echo "    Headless mode skips the Nerd Font download and the WezTerm leader-key prompt."
        ans="$(ts_tty_prompt 'Treat this as a headless server? [Y/n]: ')"
        case "$ans" in n|N|no|NO) TS_HEADLESS_RESOLVED=0; echo "$INFO Treating as a graphical desktop." ;; esac
    else
        ans="$(ts_tty_prompt 'Treat this as a headless server (skip font + WezTerm prompts)? [y/N]: ')"
        case "$ans" in y|Y|yes|YES) TS_HEADLESS_RESOLVED=1; echo "$INFO Treating as a headless server." ;; esac
    fi
}

# ── Distro detection (Linux) ───────────────────────────────────────────────────
# `ID` / `ID_LIKE` from /etc/os-release, lowercased, with TS_DISTRO_ID /
# TS_DISTRO_LIKE / TS_PKG_MANAGER overrides so the parity containers and the unit
# tests can drive every branch without a matching machine underneath them.
#
# Omarchy answers ID=omarchy, ID_LIKE=arch (verified on 4.0.1). Arch-ness and
# Omarchy-ness are asked SEPARATELY on purpose: ts_is_arch gates the PACKAGE
# MANAGER, ts_is_omarchy gates the OPINIONS (who owns tmux, the login shell, the
# theme). A plain Arch box wants the first and none of the second.
#
# Pure bash, no awk/sed: this is sourced before anything is installed, and
# /etc/os-release is a tiny KEY=value file. Values may be quoted, and ID_LIKE is
# space-separated ("ubuntu debian"), which is why the membership test below pads
# with spaces rather than comparing whole strings.

ts_os_release_field() {
    local key="$1" line val
    [ -r /etc/os-release ] || return 1
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in "$key"=*) ;; *) continue ;; esac
        val="${line#*=}"
        val="${val%\"}"; val="${val#\"}"
        val="${val%\'}"; val="${val#\'}"
        printf '%s' "$val" | tr '[:upper:]' '[:lower:]'
        return 0
    done < /etc/os-release
    return 1
}

# `${VAR+set}`, not `-n "$VAR"`: an override that is SET BUT EMPTY has to mean
# "this host has no ID", which is a real case (a minimal /etc/os-release) and the
# one the Python twin already expressed, since os.environ.get returns "" there.
# Testing for non-empty instead made bash fall through to the live /etc/os-release
# and answer `omarchy` where Python answered "" -- two readers, one rule,
# disagreeing exactly the way the platform column once did.
ts_distro_id() {
    if [ -n "${TS_DISTRO_ID+set}" ]; then printf '%s' "$TS_DISTRO_ID"; return 0; fi
    ts_os_release_field ID || printf 'unknown'
}

ts_distro_like() {
    if [ -n "${TS_DISTRO_LIKE+set}" ]; then printf '%s' "$TS_DISTRO_LIKE"; return 0; fi
    ts_os_release_field ID_LIKE || printf ''
}

# Omarchy specifically — the distro whose own commands and owned configs the
# stack defers to. Never widened to "arch": deferring to `omarchy pkg add` on a
# box with no omarchy is a command-not-found, not a policy.
ts_is_omarchy() { [ "$(ts_distro_id)" = "omarchy" ]; }

ts_is_arch() {
    case "$(ts_distro_id)" in
        arch|archarm|omarchy|endeavouros|cachyos|manjaro|garuda|artix) return 0 ;;
    esac
    case " $(ts_distro_like) " in *" arch "*) return 0 ;; esac
    return 1
}

ts_is_debianish() {
    case "$(ts_distro_id)" in debian|ubuntu|linuxmint|pop|raspbian|elementary) return 0 ;; esac
    case " $(ts_distro_like) " in *" debian "*|*" ubuntu "*) return 0 ;; esac
    return 1
}

# apt | pacman | brew | none. os-release decides FIRST and the binary only
# confirms it: a box can carry a stray package manager it does not run on (the
# Windows-side `apt` shim inside WSL was exactly that), and picking by
# `command -v` alone is how the wrong installer gets chosen on a box that has
# both. Falls back to whichever binary exists when os-release says nothing
# useful, because "unknown distro with pacman on it" is still pacman.
ts_pkg_manager() {
    if [ -n "${TS_PKG_MANAGER+set}" ]; then printf '%s' "$TS_PKG_MANAGER"; return 0; fi
    if ts_is_arch      && command -v pacman  >/dev/null 2>&1; then printf 'pacman'; return 0; fi
    if ts_is_debianish && command -v apt-get >/dev/null 2>&1; then printf 'apt';    return 0; fi
    if command -v pacman  >/dev/null 2>&1; then printf 'pacman'; return 0; fi
    if command -v apt-get >/dev/null 2>&1; then printf 'apt';    return 0; fi
    if command -v brew    >/dev/null 2>&1; then printf 'brew';   return 0; fi
    printf 'none'
}

# The distro-specific installer file for this host, as a bare filename. The
# bootstraps source it; nothing else should need to know the mapping.
ts_common_lib() {
    case "$(ts_pkg_manager)" in
        pacman) printf '_common-arch.sh' ;;
        *)      printf '_common-debian.sh' ;;
    esac
}
