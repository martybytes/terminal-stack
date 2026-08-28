#!/usr/bin/env bash
# wsl-bootstrap.sh — install WSL/Linux-side prerequisites for the terminal-stack.
# Idempotent: re-run safely.
# See ../INSTALL.md § Scripted for context.

set -euo pipefail

# shellcheck source=_common-debian.sh
. "$(dirname -- "$0")/_common-debian.sh"

common_require_non_root

echo "$INFO Terminal stack WSL bootstrap"
echo "    Detected: user $USER, home $HOME"

# Persist the wizard's answers. Called by common_install_all BEFORE anything
# optional runs, via TS_PERSIST_HOOK — an install that fails must never be able
# to discard answers the user already typed.
_ts_persist_wizard() {

    # Resolve the Windows username (used by run_after_90-sync-windows.sh to target
    # /mnt/c/Users/<user>/). Try WSL interop first, then prompt for confirmation.
    detect_win_user() {
        if [ -x /mnt/c/Windows/System32/cmd.exe ]; then
            /mnt/c/Windows/System32/cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n' || true
        fi
    }

    DETECTED_WIN_USER="$(detect_win_user)"
    echo ""
    # Honor WIN_USER from env (set by install-wsl.sh wrapper for non-interactive curl|bash flow);
    # only prompt when running interactively from a clone.
    if [ -z "${WIN_USER:-}" ]; then
        if [ -n "$DETECTED_WIN_USER" ]; then
            printf "Windows username for /mnt/c/Users/<user>/ [%s]: " "$DETECTED_WIN_USER"
        else
            printf "Windows username for /mnt/c/Users/<user>/: "
        fi
        read -r WIN_USER
        WIN_USER="${WIN_USER:-$DETECTED_WIN_USER}"
    else
        echo "$INFO WIN_USER=$WIN_USER (from env; skipping prompt)"
    fi

    if [ -z "$WIN_USER" ]; then
        echo "$WARN No Windows username provided. The sync hook will retry detection at apply time."
    fi

    # chezmoi.toml — point sourceDir at this repo and persist windowsUsername under
    # [data]. ts_ensure_source_dir creates the toml or repoints a stale sourceDir
    # (preserving [data]); ts_data_set adds/updates windowsUsername idempotently.
    # Default: the clone this script lives in (self-relative, like mac-bootstrap) —
    # the bootstrap is always run from inside the clone it should point at.
    _TS_BOOTSTRAP_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
    SOURCE_DIR="${SOURCE_DIR:-$(cd -- "$_TS_BOOTSTRAP_DIR/.." && pwd)}"
    TOML="$HOME/.config/chezmoi/chezmoi.toml"
    if [ -d "$SOURCE_DIR" ]; then
        ts_ensure_source_dir "$SOURCE_DIR"
        ts_install_git_hooks "$SOURCE_DIR"
        if [ -n "$WIN_USER" ]; then
            ts_data_set windowsUsername "$WIN_USER"
            echo "$INFO chezmoi [data].windowsUsername = $WIN_USER"
        fi
    else
        echo "$WARN $SOURCE_DIR not found; skipping chezmoi.toml. Set SOURCE_DIR env var and re-run, or edit manually."
    fi

    # Persist the wizard's config choices into chezmoi [data] (regenerates the derived
    # leaderKey/leaderMods/resolvedTheme via `chezmoi init`) and mirror to the Windows
    # side. Requires chezmoi.toml to exist (written just above).
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
        # Same shape as the three above: its own writer, so choosing a prompt
        # does not have to re-state every other answer.
        ts_starship_set "${TS_WIZ_STARSHIP:-terminal-stack}" || true
        ts_cc_tts_apply_wizard_choice "${TS_WIZ_CC_TTS:-off}" "${TS_WIZ_CC_TTS_DAEMON:-off}" "${TS_WIZ_CC_TTS_MESSAGE:-}"
        ts_cc_tts_finish
        echo "$INFO Saved terminal-stack config to $TOML [data]"
    fi
}
TS_PERSIST_HOOK=_ts_persist_wizard

common_install_all

# The agent WIRING half: needs the claude/codex CLIs, so unlike the settings it
# has to wait until after the app install.
if [ -f "${TOML:-}" ]; then
    ts_agents_apply_wizard "$SOURCE_DIR"
fi

echo ""
echo "$INFO WSL bootstrap done."
echo "    Next: ~/.local/bin/chezmoi apply -v"
echo "    See INSTALL.md § Scripted for the full sequence."
