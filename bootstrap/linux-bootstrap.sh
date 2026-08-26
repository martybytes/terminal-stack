#!/usr/bin/env bash
# linux-bootstrap.sh — install native-Linux prerequisites for the terminal-stack.
# Targets Debian/Ubuntu-family distros. Idempotent: re-run safely.
# See ../INSTALL.md § Linux for context.
#
# Difference vs wsl-bootstrap.sh: no Windows-username prompt, default SOURCE_DIR
# points at ~/code/terminal-stack instead of /mnt/c/DATA/Workspace/terminal-stack.
# The post-apply hook (run_after_90-sync-windows.sh) self-no-ops when /mnt/c/Users/
# is absent, so no extra gating is required here.

set -euo pipefail

# shellcheck source=_common-debian.sh
. "$(dirname -- "$0")/_common-debian.sh"

common_require_non_root

echo "$INFO Terminal stack Linux bootstrap"
echo "    Detected: user $USER, home $HOME"

# Persist the wizard's answers. Called by common_install_all BEFORE anything
# optional runs, via TS_PERSIST_HOOK — an install that fails must never be able
# to discard answers the user already typed.
_ts_persist_wizard() {

    # chezmoi.toml — point sourceDir at this repo. No windowsUsername on native Linux.
    # ts_ensure_source_dir (from _config.sh, sourced via _common-debian.sh) creates
    # the toml or repoints a stale sourceDir, preserving any [data] block.
    # Default: the clone this script lives in (self-relative, like mac-bootstrap).
    _TS_BOOTSTRAP_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
    SOURCE_DIR="${SOURCE_DIR:-$(cd -- "$_TS_BOOTSTRAP_DIR/.." && pwd)}"
    TOML="$HOME/.config/chezmoi/chezmoi.toml"
    if [ -d "$SOURCE_DIR" ]; then
        ts_ensure_source_dir "$SOURCE_DIR"
        ts_install_git_hooks "$SOURCE_DIR"
    else
        echo "$WARN $SOURCE_DIR not found; skipping chezmoi.toml. Set SOURCE_DIR env var and re-run, or edit manually."
    fi

    # Persist the wizard's config choices into chezmoi [data] (regenerates the derived
    # leaderKey/leaderMods/resolvedTheme via `chezmoi init`). Requires chezmoi.toml.
    if [ -f "$TOML" ]; then
        # shellcheck disable=SC2086
        ts_save_config "${TS_WIZ_LEADER:-ctrl-space}" "${TS_WIZ_THEME:-dark}" "${TS_WIZ_TMUX:-ctrl-b}" ${TS_WIZ_APPS:-}
        ts_agents_save_config "${TS_WIZ_HEADROOM:-off}" "${TS_WIZ_HEADROOM_CURSOR:-mcp}" "${TS_WIZ_CAVEMAN:-off}" "${TS_WIZ_AGENTMEMORY:-off}"
        # Stored on its own, not through ts_save_config: the mux key is positional-
        # argument-free by design so tstack mux can flip it without re-stating the rest.
        ts_wez_mux_set "${TS_WIZ_WEZ_MUX:-off}"
        ts_wez_restore_set "${TS_WIZ_WEZ_RESTORE:-off}"
        ts_atuin_set "${TS_WIZ_ATUIN:-off}"
        ts_cc_tts_apply_wizard_choice "${TS_WIZ_CC_TTS:-off}" off "${TS_WIZ_CC_TTS_MESSAGE:-}"
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
echo "$INFO Linux bootstrap done."
echo "    Next: ~/.local/bin/chezmoi apply -v"
echo "    See INSTALL.md § Linux for the full sequence."
