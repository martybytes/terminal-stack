#!/usr/bin/env bash
# _config.sh — terminal-stack configuration store (POSIX/Debian/macOS side).
# Sourced by the bootstraps, the wizard, and (indirectly) ts-config.
#
# Source of truth on this side is chezmoi [data] in ~/.config/chezmoi/chezmoi.toml.
# We store the RAW choices (leaderChord, themeMode, tmuxPrefix, resolvedTheme,
# weztermMux, weztermRestore, apps) and let .chezmoi.toml.tmpl derive the
# concrete bindings (leaderKey/leaderMods/tmuxPrefixResolved) on `chezmoi init`.
# resolvedTheme needs live OS detection, so it is computed here and stored.
#
# This file is sourced, not executed. Do not `exit`; return non-zero instead.

# Log colors — the bootstraps define these before sourcing us, but ts-config and
# the doctor source this file standalone, so provide a fallback.
: "${INFO:=$'\033[1;34m==>\033[0m'}"
: "${WARN:=$'\033[1;33m!!\033[0m'}"

# shellcheck source=_cc_tts.sh
. "$(dirname -- "${BASH_SOURCE[0]}")/_cc_tts.sh"

# ── App catalog ────────────────────────────────────────────────────────────────
# Toggleable apps the wizard/picker offers. Required prerequisites (zsh, git,
# curl, unzip, fontconfig, the Nerd Font, Starship, chezmoi) are always installed
# by the common_* steps and are NOT listed here.
#   TS_APPS_RECOMMENDED — pre-checked in the picker / installed by "recommended".
#   TS_APPS_OPTIONAL    — unchecked by default (GUI editor, GPU/docker tools).
TS_APPS_RECOMMENDED="tmux eza fzf bat delta ripgrep zoxide glow micro neovim gh ghq lazygit"
TS_APPS_OPTIONAL="zed tldr nvtop lazydocker"
TS_APPS_ALL="$TS_APPS_RECOMMENDED $TS_APPS_OPTIONAL"

# Human-readable one-liners for the picker.
ts_app_desc() {
    case "$1" in
        tmux)       echo "terminal multiplexer (ssht, persistent sessions)";;
        eza)        echo "modern ls (icons, git status)";;
        fzf)        echo "fuzzy finder (Ctrl+R, Ctrl+T)";;
        bat)        echo "cat with syntax highlighting";;
        delta)      echo "git diff pager";;
        ripgrep)    echo "fast recursive grep (rg)";;
        zoxide)     echo "smarter cd (z)";;
        glow)       echo "terminal markdown renderer";;
        micro)      echo "nano-like terminal editor";;
        neovim)     echo "neovim editor (nvim)";;
        gh)         echo "GitHub CLI (org enumeration for wso)";;
        ghq)        echo "clone into the derived workspace path";;
        lazygit)    echo "git TUI (the wso status hand-off)";;
        zed)        echo "Zed GUI editor";;
        tldr)       echo "concise command examples";;
        nvtop)      echo "GPU process monitor (NVIDIA hosts)";;
        lazydocker) echo "docker TUI (docker hosts)";;
        *)          echo "";;
    esac
}

# The binary an app id actually puts on PATH. Mostly identity; a few differ.
ts_app_bin() {
    case "$1" in
        ripgrep) echo rg ;;
        neovim)  echo nvim ;;
        *)       echo "$1" ;;
    esac
}

# Apps this machine is expected to have but doesn't. Two sources, deliberately:
# the user's saved selection (an install that failed or a tool later removed),
# AND anything since added to TS_APPS_RECOMMENDED. The second half is the point —
# a machine configured before a tool joined the catalog would otherwise never
# get it however many times ts-update ran, which is exactly how gh/ghq/lazygit
# would have missed every existing install.
ts_apps_pending() {
    local saved id seen="" out=""
    saved="$(ts_data_get_apps 2>/dev/null || true)"
    for id in $saved $TS_APPS_RECOMMENDED; do
        case " $seen " in *" $id "*) continue ;; esac
        seen="$seen $id"
        command -v "$(ts_app_bin "$id")" >/dev/null 2>&1 && continue
        out="$out $id"
    done
    echo "${out# }"
}

# Shown in the apps wizard when optional installs may need elevation.
ts_apps_install_note() {
    if command -v apt-get >/dev/null 2>&1; then
        printf '  Optional apps install via sudo apt (and may add PPAs). Your user must be able to run sudo.\n\n'
    elif [ "$(uname -s 2>/dev/null)" = "Darwin" ]; then
        printf '  Optional apps install via Homebrew (user-space; no sudo for formulae).\n\n'
    fi
}

# Install the selected toggleable apps via Homebrew (macOS). Idempotent: brew
# skips already-installed formulae. Debian/WSL uses common_install_selected_apps
# in _common-debian.sh instead (it needs the bespoke glow/neovim/… installers).
ts_brew_install_apps() {
    command -v brew >/dev/null 2>&1 || { echo "ts: brew not found; cannot install apps"; return 1; }
    local apps="$*"
    if [ -z "$apps" ]; then
        echo "==> No optional apps selected; skipping app install"
        return 0
    fi
    echo "==> Installing selected apps: $apps"
    local formulae="" id
    for id in $apps; do
        case "$id" in
            tmux)       formulae="$formulae tmux" ;;
            eza)        formulae="$formulae eza" ;;
            zoxide)     formulae="$formulae zoxide" ;;
            fzf)        formulae="$formulae fzf" ;;
            bat)        formulae="$formulae bat" ;;
            delta)      formulae="$formulae git-delta" ;;
            ripgrep)    formulae="$formulae ripgrep" ;;
            micro)      formulae="$formulae micro" ;;
            glow)       formulae="$formulae glow" ;;
            neovim)     formulae="$formulae neovim" ;;
            gh)         formulae="$formulae gh" ;;
            ghq)        formulae="$formulae ghq" ;;
            lazygit)    formulae="$formulae lazygit" ;;
            tldr)       formulae="$formulae tldr" ;;
            lazydocker) formulae="$formulae lazydocker" ;;
            nvtop)      echo "==> nvtop is Linux-only; skipping on macOS" ;;
        esac
    done
    # shellcheck disable=SC2086
    [ -n "$formulae" ] && brew install $formulae
    case " $apps " in *" zed "*)
        brew list --cask zed >/dev/null 2>&1 || brew install --cask zed ;;
    esac
}

# ── chezmoi helpers ─────────────────────────────────────────────────────────────
ts_chezmoi_bin() {
    if [ -n "${TERMINAL_STACK_CHEZMOI:-}" ]; then echo "$TERMINAL_STACK_CHEZMOI"
    elif [ -x "$HOME/.local/bin/chezmoi" ]; then echo "$HOME/.local/bin/chezmoi"
    elif command -v chezmoi >/dev/null 2>&1; then command -v chezmoi
    elif [ -x /usr/local/bin/chezmoi ]; then echo /usr/local/bin/chezmoi
    else return 1
    fi
}

ts_toml() { echo "${HOME}/.config/chezmoi/chezmoi.toml"; }

# The canonical runtime clone location (see docs/decisions.md § "Runtime clone
# location"). WSL shares ONE clone with Windows inside the app-data dir the
# stack already owns; native Linux/macOS use the XDG data home. Pins
# The Windows username for /mnt/c paths: chezmoi [data] first, then cmd.exe interop.
# The interop half is not optional. A clone installed before the bootstrap started
# recording windowsUsername has only that answer, and ts_mirror_windows_config used to
# resolve from [data] alone and `return 0` when it came back empty -- writing no mirror
# while reporting success. That is how the two config stores silently diverged: every
# WSL-side save updated chezmoi [data] and skipped the mirror, so the next pwsh sync
# rendered Windows-side files from stale values and, for ccTtsEnabled=false, removed every
# TTS hook. Same order as run_after_90-sync-windows.sh resolve_win_user and ts-mux.sh
# win_user.
ts_win_user() {
    local wu; wu="$(ts_data_get windowsUsername 2>/dev/null || true)"
    [ -n "$wu" ] && { printf '%s' "$wu"; return 0; }
    if [ -x /mnt/c/Windows/System32/cmd.exe ]; then
        wu="$(/mnt/c/Windows/System32/cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n' || true)"
        [ -n "$wu" ] && { printf '%s' "$wu"; return 0; }
    fi
    return 1
}

# (TERMINAL_STACK_DIR) are only for NON-canonical locations. Twins:
# dot_zshrc _ts_canonical_clone, profile/_cleanup.ps1 Get-TsCanonicalCloneDir.
ts_canonical_clone_dir() {
    if [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
        local wu=""
        wu="$(ts_win_user 2>/dev/null || true)"
        if [ -n "$wu" ]; then
            echo "/mnt/c/Users/$wu/AppData/Local/terminal-stack/stack"
            return 0
        fi
        # Last resort: a single existing match wins.
        local m matches=0 hit=""
        for m in /mnt/c/Users/*/AppData/Local/terminal-stack/stack; do
            [ -d "$m" ] || continue
            matches=$((matches + 1)); hit="$m"
        done
        [ "$matches" -eq 1 ] && { echo "$hit"; return 0; }
        return 1
    fi
    echo "${XDG_DATA_HOME:-$HOME/.local/share}/terminal-stack"
}

# Read the sourceDir currently recorded in chezmoi.toml (empty if unset/absent).
ts_source_dir_recorded() {
    local toml; toml="$(ts_toml)"
    [ -f "$toml" ] || return 0
    grep -E '^[[:space:]]*sourceDir[[:space:]]*=' "$toml" | head -n1 \
        | sed -E 's/^[[:space:]]*sourceDir[[:space:]]*=[[:space:]]*"?([^"]*)"?.*/\1/'
}

# Write/replace the sourceDir line in chezmoi.toml, preserving everything else
# (the [data] block, windowsUsername, …). Creates the file if missing.
ts_set_source_dir() {
    local dir="$1" toml tmp; toml="$(ts_toml)"
    mkdir -p "$(dirname "$toml")"
    if [ ! -f "$toml" ]; then printf 'sourceDir = "%s"\n' "$dir" > "$toml"; return 0; fi
    tmp="$(mktemp)"
    if grep -qE '^[[:space:]]*sourceDir[[:space:]]*=' "$toml"; then
        awk -v d="$dir" '/^[[:space:]]*sourceDir[[:space:]]*=/ {print "sourceDir = \"" d "\""; next} {print}' \
            "$toml" > "$tmp" && mv "$tmp" "$toml"
    else
        { printf 'sourceDir = "%s"\n' "$dir"; cat "$toml"; } > "$tmp" && mv "$tmp" "$toml"
    fi
    rm -f "$tmp" 2>/dev/null || true
}

# Ensure chezmoi.toml's sourceDir points at <dir>. Creates the file if missing,
# repoints (preserving [data]) when it differs, no-ops when already correct.
# This is the fix for the "stale sourceDir on re-run" bug: a fresh clone at a new
# path was previously ignored because the bootstrap refused to touch an existing
# chezmoi.toml, so `chezmoi apply` kept deploying from the old clone.
ts_ensure_source_dir() {
    local dir="$1" cur; cur="$(ts_source_dir_recorded)"
    if [ -z "$cur" ]; then
        ts_set_source_dir "$dir"
        echo "$INFO chezmoi sourceDir set to $dir"
    elif [ "$cur" = "$dir" ]; then
        echo "$INFO chezmoi sourceDir already = $dir"
    else
        echo "$WARN chezmoi sourceDir was '$cur' — repointing to '$dir'"
        ts_set_source_dir "$dir"
    fi
}

# Set a scalar string key under [data], updating in place or appending.
# Uses awk + temp file (portable across GNU and BSD/macOS; no `sed -i`).
ts_data_set() {
    local key="$1" val="$2" toml tmp; toml="$(ts_toml)"
    [ -f "$toml" ] || { mkdir -p "$(dirname "$toml")"; printf '[data]\n' > "$toml"; }
    tmp="$(mktemp)"
    if grep -q "^$key = " "$toml"; then
        awk -v k="$key" -v v="$val" '$0 ~ "^"k" = " {print k" = \"" v "\""; next} {print}' "$toml" > "$tmp" && mv "$tmp" "$toml"
    elif grep -q '^\[data\]' "$toml"; then
        awk -v k="$key" -v v="$val" '{print} /^\[data\]/ && !ins {print k" = \"" v "\""; ins=1}' "$toml" > "$tmp" && mv "$tmp" "$toml"
    else
        printf '\n[data]\n%s = "%s"\n' "$key" "$val" >> "$toml"
    fi
    rm -f "$tmp" 2>/dev/null || true
}

# Set the apps array under [data].
ts_data_set_apps() {
    local toml tmp arr="" a; toml="$(ts_toml)"
    for a in "$@"; do arr="$arr${arr:+, }\"$a\""; done
    local line="apps = [$arr]"
    [ -f "$toml" ] || { mkdir -p "$(dirname "$toml")"; printf '[data]\n' > "$toml"; }
    tmp="$(mktemp)"
    if grep -q '^apps = ' "$toml"; then
        awk -v line="$line" '/^apps = / {print line; next} {print}' "$toml" > "$tmp" && mv "$tmp" "$toml"
    elif grep -q '^\[data\]' "$toml"; then
        awk -v line="$line" '{print} /^\[data\]/ && !ins {print line; ins=1}' "$toml" > "$tmp" && mv "$tmp" "$toml"
    else
        printf '\n[data]\n%s\n' "$line" >> "$toml"
    fi
    rm -f "$tmp" 2>/dev/null || true
}

# Read a derived/raw value through chezmoi (authoritative; reflects the template).
# Batched [data] read: one `chezmoi execute-template` for every key the Windows mirror
# needs. Writing that mirror made 49 separate spawns, which measured **229 seconds** on a
# combined host, because chezmoi re-reads its source state per invocation and the source
# dir lives on /mnt/c. Nobody noticed until the mirror actually started being written: the
# writer used to bail out early, so the cost was hidden behind a silent no-op.
#
# Values are framed as key=<<value>> so a value containing "=" survives. A key that is not
# prefetched still resolves, because ts_data_get falls back to its own spawn -- a missing
# entry here is only slow, never wrong. Values containing a newline are the one shape this
# cannot carry; every key below is a scalar.
TS_MIRROR_DATA_KEYS="
    ccTtsChatterboxCfgWeight ccTtsChatterboxEnergy ccTtsChatterboxTemperature 
    ccTtsChatterboxTimeout ccTtsChatterboxUrl ccTtsChatterboxVoice ccTtsDaemon 
    ccTtsDaemonPort ccTtsDebounceSec ccTtsDuckPercent ccTtsEdgeEnabled ccTtsEdgeVoice 
    ccTtsEnabled ccTtsEngine ccTtsEvents ccTtsExcitement ccTtsHaikuModel 
    ccTtsIncludeProject ccTtsKokoroFormat ccTtsKokoroSpeed ccTtsKokoroTimeout 
    ccTtsKokoroUrl ccTtsKokoroVoice ccTtsMaxChars ccTtsMessageMode ccTtsMusicMode 
    ccTtsOllamaModel ccTtsOllamaUrl ccTtsPlayer ccTtsPrefixClaude ccTtsPrefixClaudeEnabled 
    ccTtsPrefixCodex ccTtsPrefixCodexEnabled ccTtsPrefixCursor ccTtsPrefixCursorEnabled 
    ccTtsSummarizer ccTtsTemplateError ccTtsTemplatePermission ccTtsTemplateQuestion 
    ccTtsTemplateWaiting ccTtsVoicePool leaderChord tmuxPrefix windowsUsername
    weztermMux weztermRestore headroomEnabled headroomCursorMode cavemanEnabled
    agentmemoryEnabled
"

ts_data_prefetch() {
    local cz tmpl="" k v line out
    cz="$(ts_chezmoi_bin)" || return 0
    for k in "$@"; do
        tmpl="${tmpl}${k}=<<{{ if hasKey . \"${k}\" }}{{ index . \"${k}\" }}{{ end }}>>
"
    done
    [ -n "$tmpl" ] || return 0
    out="$("$cz" execute-template "$tmpl" 2>/dev/null)" || return 0
    while IFS= read -r line; do
        case "$line" in *"=<<"*">>") ;; *) continue ;; esac
        k="${line%%=<<*}"
        case "$k" in ''|*[!A-Za-z0-9_]*) continue ;; esac
        v="${line#*=<<}"; v="${v%>>}"
        eval "TS_DATA_CACHE_${k}=\$v"
        eval "TS_DATA_CACHE_SET_${k}=1"
    done <<EOF
$out
EOF
}

ts_data_get() {
    # Prefetched value if there is one; the marker variable distinguishes "cached empty"
    # from "never fetched", which matters because plenty of these keys are legitimately "".
    local _hit=""
    eval "_hit=\${TS_DATA_CACHE_SET_${1}:-}"
    if [ -n "$_hit" ]; then
        eval "printf '%s' \"\$TS_DATA_CACHE_${1}\""
        return 0
    fi
    local cz; cz="$(ts_chezmoi_bin)" || return 1
    "$cz" execute-template "{{ if hasKey . \"$1\" }}{{ index . \"$1\" }}{{ end }}" 2>/dev/null
}

# Read the apps array as a space-separated list.
ts_data_get_apps() {
    local cz; cz="$(ts_chezmoi_bin)" || return 1
    "$cz" execute-template '{{ if hasKey . "apps" }}{{ range $i,$a := .apps }}{{ if $i }} {{ end }}{{ $a }}{{ end }}{{ end }}' 2>/dev/null
}

# Per-machine, user-global coding-agent integrations. Fresh machines default to
# off. AgentMemory alone migrates to on when its pre-toggle plugin wiring already
# exists, so an upgrade does not silently disable an established installation.
ts_agent_get() {
    local key="$1" env_name="" v=""
    case "$key" in
        headroomEnabled) env_name=TS_HEADROOM ;;
        headroomCursorMode) env_name=TS_HEADROOM_CURSOR ;;
        cavemanEnabled) env_name=TS_CAVEMAN ;;
        agentmemoryEnabled) env_name=TS_AGENTMEMORY ;;
        *) echo "ts_agent_get: unknown key '$key'" >&2; return 2 ;;
    esac
    eval "v=\${$env_name:-}"
    [ -n "$v" ] || v="$(ts_data_get "$key" 2>/dev/null || true)"
    if [ -z "$v" ] && [ "$key" = headroomCursorMode ]; then v=mcp; fi
    if [ -z "$v" ] && [ "$key" = agentmemoryEnabled ]; then
        if [ -d "$HOME/.claude/plugins/cache/agentmemory/agentmemory" ] \
            || [ -d "$HOME/.codex/plugins/cache/agentmemory/agentmemory" ]; then v=on; fi
        if [ -z "$v" ] && [ -d /mnt/c/Users ]; then
            local winuser=""; winuser="$(ts_win_user 2>/dev/null || true)"
            if [ -n "$winuser" ] && { [ -d "/mnt/c/Users/$winuser/.claude/plugins/cache/agentmemory/agentmemory" ] \
                || [ -d "/mnt/c/Users/$winuser/.codex/plugins/cache/agentmemory/agentmemory" ]; }; then v=on; fi
        fi
    fi
    [ -n "$v" ] || v=off
    printf '%s\n' "$(printf '%s' "$v" | tr 'A-Z' 'a-z')"
}

ts_agent_set() {
    local key="$1" value="$2"
    case "$key:$value" in
        headroomEnabled:on|headroomEnabled:off|cavemanEnabled:on|cavemanEnabled:off|agentmemoryEnabled:on|agentmemoryEnabled:off|headroomCursorMode:mcp|headroomCursorMode:byok|headroomCursorMode:off) ;;
        *) echo "ts_agent_set: invalid $key=$value" >&2; return 2 ;;
    esac
    ts_data_set "$key" "$value"
    ts_mirror_windows_config
}

ts_agents_save_config() {
    local headroom="${1:-off}" cursor="${2:-mcp}" caveman="${3:-off}" agentmemory="${4:-off}"
    ts_data_set headroomEnabled "$headroom"
    ts_data_set headroomCursorMode "$cursor"
    ts_data_set cavemanEnabled "$caveman"
    ts_data_set agentmemoryEnabled "$agentmemory"
    ts_mirror_windows_config
}

ts_agents_apply_wizard() {
    local script="${1:-}"
    [ -f "$script" ] || return 0
    [ "${TS_WIZ_HEADROOM:-off}" = on ] && bash "$script" headroom on "${TS_WIZ_HEADROOM_CURSOR:-mcp}" || [ "${TS_WIZ_HEADROOM:-off}" != on ] || echo "$WARN Headroom client setup failed; retry: ts-config agents headroom repair" >&2
    [ "${TS_WIZ_CAVEMAN:-off}" = on ] && bash "$script" caveman on || [ "${TS_WIZ_CAVEMAN:-off}" != on ] || echo "$WARN Caveman setup failed; retry: ts-config agents caveman repair" >&2
    [ "${TS_WIZ_AGENTMEMORY:-off}" = on ] && bash "$script" agentmemory on || [ "${TS_WIZ_AGENTMEMORY:-off}" != on ] || echo "$WARN AgentMemory setup failed; retry: ts-config agents agentmemory repair" >&2
}

# ── WezTerm multiplexer domain ──────────────────────────────────────────────────
# "on"  → .wezterm.lua sets unix_domains = {{ name = 'main' }} + default_domain,
#         so panes live in wezterm-mux-server and survive a GUI crash.
# "off" → panes are spawned locally by the GUI (the default; see ts-mux -h for the
#         trade-offs). Stored on its own, not through ts_save_config, so the
#         ts-mux command can flip it without re-stating every other choice.
ts_wez_mux_get() {
    local v; v="$(ts_data_get weztermMux 2>/dev/null || true)"
    case "$v" in on|off) echo "$v" ;; *) echo off ;; esac
}

# ts_wez_mux_set <on|off> — persist, regenerate derived keys, mirror to Windows.
ts_wez_mux_set() {
    case "$1" in on|off) ;; *) echo "ts_wez_mux_set: expected on|off" >&2; return 2 ;; esac
    ts_data_set weztermMux "$1"
    local cz; if cz="$(ts_chezmoi_bin)"; then "$cz" init >/dev/null 2>&1 || true; fi
    ts_mirror_windows_config
}

# ── WezTerm session restore ─────────────────────────────────────────────────────
# "on"  -> .wezterm.lua registers resurrect's gui-startup handler, so WezTerm
#          reopens the last session (tabs, panes, scrollback) at launch.
# "off" -> starts clean (the default). The autosave still runs either way, so
#          Leader+L can restore on demand. Stored on its own like weztermMux.
ts_wez_restore_get() {
    local v; v="$(ts_data_get weztermRestore 2>/dev/null || true)"
    case "$v" in on|off) echo "$v" ;; *) echo off ;; esac
}

# ts_wez_restore_set <on|off> — persist, regenerate derived keys, mirror to Windows.
ts_wez_restore_set() {
    case "$1" in on|off) ;; *) echo "ts_wez_restore_set: expected on|off" >&2; return 2 ;; esac
    ts_data_set weztermRestore "$1"
    local cz; if cz="$(ts_chezmoi_bin)"; then "$cz" init >/dev/null 2>&1 || true; fi
    ts_mirror_windows_config
}

# ── OS appearance detection ─────────────────────────────────────────────────────
# Echoes the baked palette (light|dark) for a theme mode. follow → detect; on any
# failure default to dark (the stack's historical look).
resolve_os_theme() {
    local mode="${1:-dark}"
    case "$mode" in
        light) echo light; return 0;;
        dark)  echo dark;  return 0;;
    esac
    if [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
        local v
        v="$(/mnt/c/Windows/System32/reg.exe query \
             'HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Themes\Personalize' \
             /v AppsUseLightTheme 2>/dev/null | tr -d '\r')"
        case "$v" in *0x1*) echo light; return 0;; *0x0*) echo dark; return 0;; esac
        echo dark; return 0
    fi
    case "$(uname -s 2>/dev/null)" in
        Darwin)
            if defaults read -g AppleInterfaceStyle 2>/dev/null | grep -qi dark
            then echo dark; else echo light; fi
            return 0;;
        *)
            local cs; cs="$(gsettings get org.gnome.desktop.interface color-scheme 2>/dev/null)"
            case "$cs" in
                *dark*) echo dark; return 0;;
                *light*|*default*) echo light; return 0;;
            esac
            local th; th="$(gsettings get org.gnome.desktop.interface gtk-theme 2>/dev/null)"
            case "$th" in *-dark*|*Dark*|*-Dark*) echo dark; return 0;; esac
            echo dark; return 0;;
    esac
}

# ── Save + propagate ─────────────────────────────────────────────────────────────
# ts_save_config <leaderChord> <themeMode> <tmuxPrefix> [appId ...]
# Writes the raw choices, computes resolvedTheme, regenerates derived keys via
# `chezmoi init`, and mirrors the Windows config.json when /mnt/c is present.
ts_save_config() {
    local leader="$1" theme="$2" tprefix="$3"; shift 3 || true
    ts_data_set leaderChord "$leader"
    ts_data_set themeMode "$theme"
    ts_data_set tmuxPrefix "$tprefix"
    ts_data_set resolvedTheme "$(resolve_os_theme "$theme")"
    ts_data_set_apps "$@"
    local cz; if cz="$(ts_chezmoi_bin)"; then "$cz" init >/dev/null 2>&1 || true; fi
    ts_mirror_windows_config
}

# Refresh only resolvedTheme from the live OS (used by ts-update for follow mode).
ts_refresh_resolved_theme() {
    local mode; mode="$(ts_data_get themeMode)"; [ -n "$mode" ] || mode="dark"
    ts_data_set resolvedTheme "$(resolve_os_theme "$mode")"
    local cz; if cz="$(ts_chezmoi_bin)"; then "$cz" init >/dev/null 2>&1 || true; fi
}

# Mirror the derived config to the Windows side so sync-windows.ps1 / a
# Windows-standalone ts-config agree with the WSL source of truth.
ts_mirror_windows_config() {
    [ -d /mnt/c/Users ] || return 0
    # One render up front, so the ~49 reads below cost one chezmoi spawn between them.
    # shellcheck disable=SC2086
    ts_data_prefetch $TS_MIRROR_DATA_KEYS
    local cz; cz="$(ts_chezmoi_bin)" || return 0
    local winuser; winuser="$(ts_win_user 2>/dev/null || true)"
    if [ -z "$winuser" ] || [ ! -d "/mnt/c/Users/$winuser" ]; then
        # Loud on purpose. A silent skip leaves the Windows mirror stale while the save
        # reports success, and the next pwsh sync renders from those old values.
        echo "warning: could not resolve the Windows username - the Windows config mirror was NOT updated." >&2
        echo "  Windows-side settings keep their previous values; ts-doctor reports the divergence." >&2
        return 0
    fi
    local dst="/mnt/c/Users/$winuser/AppData/Local/terminal-stack"
    mkdir -p "$dst" 2>/dev/null || return 0
    local lk="" lm="" tm="" rt="" tr="" appscsv="" jsonapps=""
    # These six are derived expressions rather than plain [data] keys, so they cannot go
    # through ts_data_prefetch's hasKey form -- but they can still share one spawn. Six
    # separate renders cost about thirty seconds of the mirror write on a combined host.
    local _derived _dline _dk _dv
    _derived="$("$cz" execute-template 'lk=<<{{ .leaderKey }}>>
lm=<<{{ .leaderMods }}>>
tm=<<{{ .themeMode }}>>
rt=<<{{ .resolvedTheme }}>>
tr=<<{{ .tmuxPrefixResolved }}>>
appscsv=<<{{ if hasKey . "apps" }}{{ range $i,$a := .apps }}{{ if $i }},{{ end }}{{ $a }}{{ end }}{{ end }}>>' 2>/dev/null)"
    while IFS= read -r _dline; do
        case "$_dline" in *"=<<"*">>") ;; *) continue ;; esac
        _dk="${_dline%%=<<*}"
        _dv="${_dline#*=<<}"; _dv="${_dv%>>}"
        case "$_dk" in
            lk) lk="$_dv" ;;
            lm) lm="$_dv" ;;
            tm) tm="$_dv" ;;
            rt) rt="$_dv" ;;
            tr) tr="$_dv" ;;
            appscsv) appscsv="$_dv" ;;
        esac
    done <<EOF
$_derived
EOF
    local a IFS=,
    for a in $appscsv; do [ -n "$a" ] && jsonapps="$jsonapps${jsonapps:+, }\"$a\""; done
    unset IFS
    cat > "$dst/config.json" <<EOF
{
  "leaderKey": "$lk",
  "leaderMods": "$lm",
  "leaderChord": "$(ts_data_get leaderChord)",
  "themeMode": "$tm",
  "resolvedTheme": "$rt",
  "tmuxPrefix": "$(ts_data_get tmuxPrefix)",
  "tmuxPrefixResolved": "$tr",
  "weztermMux": "$(ts_wez_mux_get)",
  "weztermRestore": "$(ts_wez_restore_get)",
  "headroomEnabled": "$(ts_agent_get headroomEnabled)",
  "headroomCursorMode": "$(ts_agent_get headroomCursorMode)",
  "cavemanEnabled": "$(ts_agent_get cavemanEnabled)",
  "agentmemoryEnabled": "$(ts_agent_get agentmemoryEnabled)",
  "apps": [$jsonapps],
$(ts_cc_tts_json_for_mirror)
}
EOF
}
