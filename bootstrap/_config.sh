#!/usr/bin/env bash
# _config.sh — terminal-stack configuration store (POSIX/Debian/macOS side).
# Sourced by the bootstraps, the wizard, and (indirectly) ts-config.
#
# Source of truth on this side is chezmoi [data] in ~/.config/chezmoi/chezmoi.toml.
# We store the RAW choices (leaderChord, themeMode, tmuxPrefix, resolvedTheme, apps)
# and let .chezmoi.toml.tmpl derive the concrete bindings (leaderKey/leaderMods/
# tmuxPrefixResolved) on `chezmoi init`. resolvedTheme needs live OS detection, so
# it is computed here (resolve_os_theme) and stored.
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
ts_data_get() {
    local cz; cz="$(ts_chezmoi_bin)" || return 1
    "$cz" execute-template "{{ if hasKey . \"$1\" }}{{ index . \"$1\" }}{{ end }}" 2>/dev/null
}

# Read the apps array as a space-separated list.
ts_data_get_apps() {
    local cz; cz="$(ts_chezmoi_bin)" || return 1
    "$cz" execute-template '{{ if hasKey . "apps" }}{{ range $i,$a := .apps }}{{ if $i }} {{ end }}{{ $a }}{{ end }}{{ end }}' 2>/dev/null
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
    local cz; cz="$(ts_chezmoi_bin)" || return 0
    local winuser; winuser="$("$cz" execute-template '{{ if hasKey . "windowsUsername" }}{{ .windowsUsername }}{{ end }}' 2>/dev/null)"
    [ -n "$winuser" ] && [ -d "/mnt/c/Users/$winuser" ] || return 0
    local dst="/mnt/c/Users/$winuser/AppData/Local/terminal-stack"
    mkdir -p "$dst" 2>/dev/null || return 0
    local lk lm tm rt tr appscsv jsonapps=""
    lk="$("$cz" execute-template '{{ .leaderKey }}' 2>/dev/null)"
    lm="$("$cz" execute-template '{{ .leaderMods }}' 2>/dev/null)"
    tm="$("$cz" execute-template '{{ .themeMode }}' 2>/dev/null)"
    rt="$("$cz" execute-template '{{ .resolvedTheme }}' 2>/dev/null)"
    tr="$("$cz" execute-template '{{ .tmuxPrefixResolved }}' 2>/dev/null)"
    appscsv="$("$cz" execute-template '{{ if hasKey . "apps" }}{{ range $i,$a := .apps }}{{ if $i }},{{ end }}{{ $a }}{{ end }}{{ end }}' 2>/dev/null)"
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
  "apps": [$jsonapps],
$(ts_cc_tts_json_for_mirror)
}
EOF
}
