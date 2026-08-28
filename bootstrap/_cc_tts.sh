#!/usr/bin/env bash
# _cc_tts.sh — Claude Code local TTS config (Kokoro / Chatterbox / edge-tts).
# Sourced by bootstrap/_config.sh, ts-config.sh, and cc-speak hooks.
# Persists scalars in chezmoi [data]; chezmoi renders ~/.claude/tts/config.json from
# dot_claude/tts/config.json.tmpl. Do not execute directly.

# Default scalar values (Hermes-matching Kokoro am_adam).
ts_cc_tts_default() {
    case "$1" in
        ccTtsEnabled)              echo false ;;
        ccTtsEngine)               echo kokoro ;;
        ccTtsMessageMode)          echo template ;;
        ccTtsEvents)               echo waiting,error,question,permission ;;
        ccTtsPrefixClaude)         echo Claude ;;
        ccTtsPrefixCursor)         echo Cursor ;;
        ccTtsPrefixCodex)          echo Codex ;;
        ccTtsPrefixClaudeEnabled)  echo true ;;
        ccTtsPrefixCursorEnabled)  echo true ;;
        ccTtsPrefixCodexEnabled)   echo true ;;
        ccTtsIncludeProject)       echo true ;;
        ccTtsExcitement)           echo 0.25 ;;
        ccTtsKokoroUrl)            echo http://127.0.0.1:8880 ;;
        ccTtsKokoroVoice)          echo am_adam ;;
        ccTtsKokoroSpeed)          echo 1.0 ;;
        ccTtsKokoroFormat)         echo mp3 ;;
        ccTtsKokoroTimeout)        echo 15 ;;
        ccTtsChatterboxUrl)        echo http://127.0.0.1:8881 ;;
        ccTtsChatterboxVoice)      echo adam ;;
        ccTtsChatterboxEnergy)     echo 0.25 ;;
        ccTtsChatterboxCfgWeight)  echo 0.5 ;;
        ccTtsChatterboxTemperature) echo 0.6 ;;
        ccTtsChatterboxTimeout)    echo 60 ;;
        ccTtsSayVoice)             echo "" ;;
        ccTtsEdgeEnabled)          echo true ;;
        ccTtsEdgeVoice)            echo en-US-AndrewMultilingualNeural ;;
        ccTtsTemplateWaiting)      echo "Done in {project}. I'm waiting for you." ;;
        ccTtsTemplateError)        echo "Error in {project}. You may want to look." ;;
        ccTtsTemplateQuestion)     echo "I have a question for you." ;;
        ccTtsTemplatePermission)   echo "Permission needed in {project}." ;;
        ccTtsMaxChars)             echo 120 ;;
        ccTtsDebounceSec)          echo 5 ;;
        ccTtsPlayer)               echo auto ;;
        ccTtsDaemon)               echo off ;;
        ccTtsDaemonPort)           echo 8890 ;;
        ccTtsSummarizer)           echo template ;;
        ccTtsHaikuModel)           echo claude-haiku-4-5 ;;
        ccTtsOllamaUrl)            echo http://127.0.0.1:11434 ;;
        ccTtsOllamaModel)          echo llama3.2:3b ;;
        ccTtsMusicMode)            echo duck ;;
        ccTtsDuckPercent)          echo 30 ;;
        ccTtsVoicePool)            echo am_adam,am_michael,af_heart,bm_george ;;
        *) return 1 ;;
    esac
}

ts_cc_tts_keys() {
    printf '%s\n' \
        ccTtsEnabled ccTtsEngine ccTtsMessageMode ccTtsEvents \
        ccTtsPrefixClaude ccTtsPrefixCursor ccTtsPrefixCodex \
        ccTtsPrefixClaudeEnabled ccTtsPrefixCursorEnabled ccTtsPrefixCodexEnabled \
        ccTtsIncludeProject ccTtsExcitement \
        ccTtsKokoroUrl ccTtsKokoroVoice ccTtsKokoroSpeed ccTtsKokoroFormat ccTtsKokoroTimeout \
        ccTtsChatterboxUrl ccTtsChatterboxVoice ccTtsChatterboxEnergy \
        ccTtsChatterboxCfgWeight ccTtsChatterboxTemperature ccTtsChatterboxTimeout \
        ccTtsSayVoice ccTtsEdgeEnabled ccTtsEdgeVoice \
        ccTtsTemplateWaiting ccTtsTemplateError ccTtsTemplateQuestion ccTtsTemplatePermission \
        ccTtsMaxChars ccTtsDebounceSec ccTtsPlayer \
        ccTtsDaemon ccTtsDaemonPort ccTtsSummarizer ccTtsHaikuModel \
        ccTtsOllamaUrl ccTtsOllamaModel ccTtsMusicMode ccTtsDuckPercent ccTtsVoicePool
}

# Read one TTS scalar from chezmoi [data], else default.
ts_cc_tts_get() {
    local key="$1" v
    v="$(ts_data_get "$key" 2>/dev/null || true)"
    if [ -n "$v" ]; then echo "$v"; else ts_cc_tts_default "$key"; fi
}

# Write all TTS scalars to chezmoi [data] (values from args or current chezmoi state).
ts_cc_tts_persist_all() {
    local key val
    while IFS= read -r key; do
        val="$(ts_cc_tts_get "$key")"
        ts_data_set "$key" "$val"
    done <<EOF
$(ts_cc_tts_keys)
EOF
}

ts_cc_tts_set() {
    local key="$1" val="$2"
    ts_data_set "$key" "$val"
}

ts_cc_tts_reset_defaults() {
    local key
    while IFS= read -r key; do
        ts_data_set "$key" "$(ts_cc_tts_default "$key")"
    done <<EOF
$(ts_cc_tts_keys)
EOF
}

ts_cc_tts_chatterbox_exaggeration() {
    # Hermes: exaggeration = 0.25 + energy (energy 0–1).
    local energy
    energy="$(ts_cc_tts_get ccTtsChatterboxEnergy)"
    awk -v e="$energy" 'BEGIN { printf "%.2f", 0.25 + e + 0 }'
}

# Probe Kokoro / Chatterbox HTTP endpoints (best-effort).
ts_cc_tts_probe() {
    local _notice
    if _notice="$(ts_cc_tts_say_notice_recent)"; then
        echo "$WARN today: $_notice"
        echo "     engine: $(ts_cc_tts_get ccTtsEngine)   (tstack config tts voices lists what it can produce)"
    fi
    local kurl curl_ok=0
    kurl="$(ts_cc_tts_get ccTtsKokoroUrl)"
    if command -v curl >/dev/null 2>&1; then
        if curl -sf --max-time 2 "${kurl%/}/health" >/dev/null 2>&1 \
            || curl -sf --max-time 2 "${kurl%/}/v1/models" >/dev/null 2>&1 \
            || curl -sf --max-time 2 "${kurl%/}/docs" >/dev/null 2>&1; then
            echo "kokoro: up ($kurl)"
            curl_ok=1
        else
            echo "kokoro: down ($kurl)"
        fi
        local cburl
        cburl="$(ts_cc_tts_get ccTtsChatterboxUrl)"
        if curl -sf --max-time 2 "${cburl%/}/health" >/dev/null 2>&1 \
            || curl -sf --max-time 2 "${cburl%/}/docs" >/dev/null 2>&1; then
            echo "chatterbox: up ($cburl)"
        else
            echo "chatterbox: down ($cburl)"
        fi
    else
        echo "curl not found; skipping HTTP probes"
    fi
    if command -v edge-tts >/dev/null 2>&1; then
        echo "edge-tts: installed"
    elif [ "$(ts_cc_tts_get ccTtsEdgeEnabled)" = true ]; then
        echo "edge-tts: not installed (pip install edge-tts for fallback)"
    fi
    return 0
}

# Did an announcement quietly fall back to the system voice? The hooks cannot
# tell you: cc-tts-notify.sh detaches the worker with `>/dev/null 2>&1`, so the
# explanation went to a discarded stream. cc_tts_say_notice leaves it in a dated
# file instead, and this is what reads it back.
ts_cc_tts_say_notice_recent() {
    local dir stamp
    dir="${TMPDIR:-/tmp}"
    stamp="${dir%/}/cc-tts-say-notice.$(date +%Y%m%d)"
    [ -r "$stamp" ] || return 1
    printf '%s' "$(cat "$stamp" 2>/dev/null)"
}

ts_cc_tts_show() {
    local merged="${HOME}/.claude/tts/.merged.json"
    if [ -f "$merged" ] && command -v jq >/dev/null 2>&1; then
        echo "Claude Code TTS (effective config — config.json + local.json):"
        jq . "$merged" 2>/dev/null || cat "$merged"
        echo ""
        ts_cc_tts_probe
        return
    fi
    local key
    echo "Claude Code TTS (chezmoi [data]):"
    while IFS= read -r key; do
        printf '  %-28s %s\n' "$key:" "$(ts_cc_tts_get "$key")"
    done <<EOF
$(ts_cc_tts_keys)
EOF
    echo "  chatterbox exaggeration (derived): $(ts_cc_tts_chatterbox_exaggeration)"
    echo ""
    ts_cc_tts_probe
}

# Save TTS settings + refresh chezmoi init + mirror Windows config.json.
ts_cc_tts_finish() {
    local cz
    if cz="$(ts_chezmoi_bin)"; then "$cz" init >/dev/null 2>&1 || true; fi
    ts_mirror_windows_config
    ts_cc_tts_reload_daemon_config || true
}

ts_cc_tts_reload_daemon_config() {
    [ "$(ts_cc_tts_get ccTtsDaemon)" = on ] || return 0
    command -v curl >/dev/null 2>&1 || return 0
    local port hostline host token
    port="$(ts_cc_tts_get ccTtsDaemonPort)"
    if curl -sf --max-time 1 -X POST "http://127.0.0.1:${port}/v1/config/reload" >/dev/null 2>&1; then
        echo 'tts: running daemon reloaded the new configuration'
        return 0
    fi
    [ -f "${HOME}/.claude/hooks/cc-tts-lib.sh" ] || return 0
    # shellcheck source=/dev/null
    . "${HOME}/.claude/hooks/cc-tts-lib.sh"
    hostline="$(cc_tts_daemon_host "$port" 2>/dev/null)" || return 0
    host="${hostline%% *}"; token="${hostline#* }"
    if [ "$token" != "$hostline" ] && [ -n "$token" ]; then
        curl -sf --max-time 1 -X POST -H "X-TS-Token: $token" \
            "http://${host}:${port}/v1/config/reload" >/dev/null 2>&1 || return 0
    else
        curl -sf --max-time 1 -X POST \
            "http://${host}:${port}/v1/config/reload" >/dev/null 2>&1 || return 0
    fi
    echo 'tts: running daemon reloaded the new configuration'
}

# Emit ccTts JSON object for config.json mirror (single line, no external jq).
ts_cc_tts_json_for_mirror() {
    local en ev evjson="" e vp vpjson="" v
    en="$(ts_cc_tts_get ccTtsEnabled)"
    ev="$(ts_cc_tts_get ccTtsEvents)"
    IFS=',' read -ra _evparts <<< "$ev"
    for e in "${_evparts[@]}"; do
        e="${e#"${e%%[![:space:]]*}"}"
        e="${e%"${e##*[![:space:]]}"}"
        [ -n "$e" ] || continue
        evjson="${evjson}${evjson:+, }\"$e\""
    done
    vp="$(ts_cc_tts_get ccTtsVoicePool)"
    IFS=',' read -ra _vpparts <<< "$vp"
    for v in "${_vpparts[@]}"; do
        v="${v#"${v%%[![:space:]]*}"}"
        v="${v%"${v##*[![:space:]]}"}"
        [ -n "$v" ] || continue
        vpjson="${vpjson}${vpjson:+, }\"$v\""
    done
    cat <<EOF
  "ccTts": {
    "enabled": $([ "$en" = true ] && echo true || echo false),
    "engine": "$(ts_cc_tts_get ccTtsEngine)",
    "messageMode": "$(ts_cc_tts_get ccTtsMessageMode)",
    "events": [$evjson],
    "prefixClaude": "$(ts_cc_tts_get ccTtsPrefixClaude)",
    "prefixCursor": "$(ts_cc_tts_get ccTtsPrefixCursor)",
    "prefixCodex": "$(ts_cc_tts_get ccTtsPrefixCodex)",
    "prefixClaudeEnabled": $([ "$(ts_cc_tts_get ccTtsPrefixClaudeEnabled)" = true ] && echo true || echo false),
    "prefixCursorEnabled": $([ "$(ts_cc_tts_get ccTtsPrefixCursorEnabled)" = true ] && echo true || echo false),
    "prefixCodexEnabled": $([ "$(ts_cc_tts_get ccTtsPrefixCodexEnabled)" = true ] && echo true || echo false),
    "includeProject": $([ "$(ts_cc_tts_get ccTtsIncludeProject)" = true ] && echo true || echo false),
    "excitement": $(ts_cc_tts_get ccTtsExcitement),
    "kokoro": {
      "url": "$(ts_cc_tts_get ccTtsKokoroUrl)",
      "voice": "$(ts_cc_tts_get ccTtsKokoroVoice)",
      "speed": $(ts_cc_tts_get ccTtsKokoroSpeed),
      "format": "$(ts_cc_tts_get ccTtsKokoroFormat)",
      "timeoutSec": $(ts_cc_tts_get ccTtsKokoroTimeout)
    },
    "chatterbox": {
      "url": "$(ts_cc_tts_get ccTtsChatterboxUrl)",
      "voice": "$(ts_cc_tts_get ccTtsChatterboxVoice)",
      "energy": $(ts_cc_tts_get ccTtsChatterboxEnergy),
      "cfgWeight": $(ts_cc_tts_get ccTtsChatterboxCfgWeight),
      "temperature": $(ts_cc_tts_get ccTtsChatterboxTemperature),
      "timeoutSec": $(ts_cc_tts_get ccTtsChatterboxTimeout)
    },
    "say": {
      "voice": "$(ts_cc_tts_get ccTtsSayVoice)"
    },
    "edge": {
      "enabled": $([ "$(ts_cc_tts_get ccTtsEdgeEnabled)" = true ] && echo true || echo false),
      "voice": "$(ts_cc_tts_get ccTtsEdgeVoice)"
    },
    "templates": {
      "waiting": "$(ts_cc_tts_get ccTtsTemplateWaiting | sed 's/\\/\\\\/g; s/"/\\"/g')",
      "error": "$(ts_cc_tts_get ccTtsTemplateError | sed 's/\\/\\\\/g; s/"/\\"/g')",
      "question": "$(ts_cc_tts_get ccTtsTemplateQuestion | sed 's/\\/\\\\/g; s/"/\\"/g')",
      "permission": "$(ts_cc_tts_get ccTtsTemplatePermission | sed 's/\\/\\\\/g; s/"/\\"/g')"
    },
    "maxChars": $(ts_cc_tts_get ccTtsMaxChars),
    "debounceSec": $(ts_cc_tts_get ccTtsDebounceSec),
    "player": "$(ts_cc_tts_get ccTtsPlayer)",
    "daemon": {
      "enabled": $([ "$(ts_cc_tts_get ccTtsDaemon)" = on ] && echo true || echo false),
      "port": $(ts_cc_tts_get ccTtsDaemonPort)
    },
    "summarize": {
      "mode": "$(ts_cc_tts_get ccTtsSummarizer)",
      "haikuModel": "$(ts_cc_tts_get ccTtsHaikuModel)",
      "ollamaUrl": "$(ts_cc_tts_get ccTtsOllamaUrl)",
      "ollamaModel": "$(ts_cc_tts_get ccTtsOllamaModel)"
    },
    "music": {
      "mode": "$(ts_cc_tts_get ccTtsMusicMode)",
      "duckPercent": $(ts_cc_tts_get ccTtsDuckPercent)
    },
    "voicePool": [$vpjson]
  }
EOF
}

# ── ttsd daemon plumbing (Windows-only; WSL reaches it via interop) ────────────

ts_cc_tts_bootstrap_dir() {
    # Directory of this file — the clone's bootstrap/ (works because tstack config
    # and the bootstraps source _cc_tts.sh from the clone).
    printf '%s' "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
}

ts_cc_tts_daemon_supported() { [ -d /mnt/c/Users ]; }

ts_cc_tts_pwsh_exe() {
    local p
    for p in "/mnt/c/Program Files/PowerShell/7/pwsh.exe" \
             "/mnt/c/Program Files/PowerShell/7-preview/pwsh.exe"; do
        [ -x "$p" ] && { printf '%s' "$p"; return 0; }
    done
    return 1
}

ts_cc_tts_daemon_installer() {
    # Run bootstrap/install-tts-daemon.ps1 (Windows side) with the given args.
    local script pwsh_exe win
    script="$(ts_cc_tts_bootstrap_dir)/install-tts-daemon.ps1"
    [ -f "$script" ] || { echo "tts daemon: install-tts-daemon.ps1 not found beside _cc_tts.sh" >&2; return 1; }
    pwsh_exe="$(ts_cc_tts_pwsh_exe)" || { echo "tts daemon: pwsh.exe not found under /mnt/c" >&2; return 1; }
    win="$(wslpath -w "$script" 2>/dev/null || printf '%s' "$script")"
    "$pwsh_exe" -NoLogo -NonInteractive -ExecutionPolicy Bypass -File "$win" "$@"
}

ts_cc_tts_exe_path() {
    # The Windows-side daemon executable, as seen from WSL.
    local winuser
    [ -d /mnt/c/Users ] || return 1
    winuser="$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n')"
    [ -n "$winuser" ] || return 1
    printf '/mnt/c/Users/%s/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe' "$winuser"
}

ts_cc_tts_daemon_snapshot_path() {
    # The daemon's crash-safe pre-duck volume snapshot (Windows side, via /mnt/c).
    local winuser
    [ -d /mnt/c/Users ] || return 1
    winuser="$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n')"
    [ -n "$winuser" ] || return 1
    printf '/mnt/c/Users/%s/AppData/Local/terminal-stack/tts-daemon/state/duck-snapshot.json' "$winuser"
}

ts_cc_tts_daemon_status() {
    local port health sha
    port="$(ts_cc_tts_get ccTtsDaemonPort)"
    health="$(curl -sf --max-time 2 "http://127.0.0.1:${port}/healthz" 2>/dev/null || true)"
    if [ -z "$health" ] && [ -f "${HOME}/.claude/hooks/cc-tts-lib.sh" ]; then
        # NAT-mode WSL: reuse the hooks' host ladder + token.
        health="$(
            # shellcheck source=/dev/null
            . "${HOME}/.claude/hooks/cc-tts-lib.sh"
            hostline="$(cc_tts_daemon_host "$port" 2>/dev/null)" || exit 0
            host="${hostline%% *}"; token="${hostline#* }"
            [ "$token" = "$hostline" ] && token=""
            if [ -n "$token" ]; then
                curl -sf --max-time 2 -H "X-TS-Token: $token" "http://${host}:${port}/healthz" 2>/dev/null
            else
                curl -sf --max-time 2 "http://${host}:${port}/healthz" 2>/dev/null
            fi
        )"
    fi
    if [ -z "$health" ]; then
        echo "tts daemon: not reachable on port $port (hooks fall back to direct playback)"
        echo "  saved setting ccTtsDaemon=$(ts_cc_tts_get ccTtsDaemon)  —  start: tstack config tts daemon on"
        return 1
    fi
    echo "tts daemon: $health"
    sha="$(git -C "$(ts_cc_tts_bootstrap_dir)/.." rev-parse HEAD 2>/dev/null || true)"
    if [ -n "$sha" ] && ! printf '%s' "$health" | grep -q "$sha"; then
        echo "tts daemon: running an older build than this clone — tstack config tts daemon restart"
    fi
}

# ── `summarizer self` marker blocks for Claude and Codex ──────────────────────
# Marker-block edit, same discipline as \$PROFILE regions: install appends the
# block from bootstrap/tts-daemon/assets/speak-summary.md (which carries its own
# start/end markers); switching modes removes exactly that block. Backups follow
# the repo's .bak.YYYYMMDD[.N] convention.

TS_CC_TTS_SELF_START='<!-- terminal-stack-tts-start -->'
TS_CC_TTS_SELF_END='<!-- terminal-stack-tts-end -->'

ts_cc_tts_backup_file() {
    local f="$1" b n=1
    [ -f "$f" ] || return 0
    b="$f.bak.$(date +%Y%m%d)"
    while [ -e "$b" ]; do b="$f.bak.$(date +%Y%m%d).$n"; n=$((n + 1)); done
    cp -p "$f" "$b" 2>/dev/null || cp "$f" "$b"
}

ts_cc_tts_self_strip() {
    # Print $1 minus the marker block (no-op passthrough when absent).
    awk -v s="$TS_CC_TTS_SELF_START" -v e="$TS_CC_TTS_SELF_END" '
        index($0, s) { skip = 1 }
        !skip { print }
        skip && index($0, e) { skip = 0 }' "$1"
}

ts_cc_tts_codex_instruction_path() {
    local codex_home="$1"
    if [ -s "${codex_home}/AGENTS.override.md" ]; then
        printf '%s/AGENTS.override.md\n' "$codex_home"
    else
        printf '%s/AGENTS.md\n' "$codex_home"
    fi
}

ts_cc_tts_self_install_one() {
    local target="$1" agent="$2" asset
    asset="$(ts_cc_tts_bootstrap_dir)/tts-daemon/assets/speak-summary.md"
    [ -f "$asset" ] || { echo "tts: speak-summary.md asset not found (run tstack update?)" >&2; return 1; }
    mkdir -p "$(dirname "$target")" 2>/dev/null || true
    if [ -f "$target" ]; then
        ts_cc_tts_backup_file "$target"
        { ts_cc_tts_self_strip "$target"; echo; cat "$asset"; } > "$target.tmp" \
            && mv "$target.tmp" "$target"
    else
        cat "$asset" > "$target"
    fi
    echo "tts: spoken-summary instruction installed for $agent in $target"
}

ts_cc_tts_windows_home() {
    [ -d /mnt/c/Users ] || return 1
    local winuser
    winuser="$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n')"
    [ -n "$winuser" ] || return 1
    printf '/mnt/c/Users/%s\n' "$winuser"
}

ts_cc_tts_self_install() {
    local codex_home="${CODEX_HOME:-${HOME}/.codex}" win_home win_codex
    ts_cc_tts_self_install_one "${HOME}/.claude/CLAUDE.md" Claude || return 1
    ts_cc_tts_self_install_one "$(ts_cc_tts_codex_instruction_path "$codex_home")" Codex || return 1
    if win_home="$(ts_cc_tts_windows_home)"; then
        ts_cc_tts_self_install_one "${win_home}/.claude/CLAUDE.md" 'Claude (Windows)' || return 1
        win_codex="${win_home}/.codex"
        ts_cc_tts_self_install_one "$(ts_cc_tts_codex_instruction_path "$win_codex")" 'Codex (Windows)' || return 1
    fi
    echo 'tts: Cursor uses its final-response hook text when no GUI-managed User Rule marker is present'
}

ts_cc_tts_self_remove() {
    local target codex_home="${CODEX_HOME:-${HOME}/.codex}" win_home
    local -a targets=(
        "${HOME}/.claude/CLAUDE.md"
        "${codex_home}/AGENTS.md"
        "${codex_home}/AGENTS.override.md"
    )
    if win_home="$(ts_cc_tts_windows_home)"; then
        targets+=(
            "${win_home}/.claude/CLAUDE.md"
            "${win_home}/.codex/AGENTS.md"
            "${win_home}/.codex/AGENTS.override.md"
        )
    fi
    for target in "${targets[@]}"; do
        [ -f "$target" ] || continue
        grep -qF "$TS_CC_TTS_SELF_START" "$target" || continue
        ts_cc_tts_backup_file "$target"
        ts_cc_tts_self_strip "$target" > "$target.tmp" && mv "$target.tmp" "$target"
        echo "tts: spoken-summary instruction removed from $target"
    done
}

# Wizard: probe Kokoro; echo on|off|skip recommendation.
ts_cc_tts_wizard_probe() {
    if [ -n "${TS_CC_TTS:-}" ]; then echo "$TS_CC_TTS"; return 0; fi
    local kurl
    kurl="$(ts_cc_tts_default ccTtsKokoroUrl)"
    if command -v curl >/dev/null 2>&1; then
        if curl -sf --max-time 2 "${kurl%/}/health" >/dev/null 2>&1 \
            || curl -sf --max-time 2 "${kurl%/}/v1/models" >/dev/null 2>&1; then
            echo probe_ok
            return 0
        fi
    fi
    echo probe_fail
}

# Which engines could actually make a sound on this host. Echoes one line per
# engine; the wizard uses it to recommend something that will work rather than
# hardcoding kokoro and hoping.
ts_cc_tts_engine_report() {
    local url
    url="$(ts_data_get ccTtsKokoroUrl 2>/dev/null || true)"; url="${url:-http://127.0.0.1:8880}"
    if ts_probe_http "$url/health" 2 || ts_probe_http "$url/v1/models" 2; then
        printf '  kokoro:     reachable at %s\n' "$url"
    else
        printf '  kokoro:     NOT reachable at %s (needs the Docker container)\n' "$url"
    fi
    url="$(ts_data_get ccTtsChatterboxUrl 2>/dev/null || true)"; url="${url:-http://127.0.0.1:8881}"
    if ts_probe_http "$url/health" 2; then
        printf '  chatterbox: reachable at %s\n' "$url"
    else
        printf '  chatterbox: not reachable at %s\n' "$url"
    fi
    if command -v edge-tts >/dev/null 2>&1; then
        printf '  edge-tts:   installed (cloud voice, needs network)\n'
    else
        printf '  edge-tts:   not installed (pip install edge-tts)\n'
    fi
    if [ "$(uname -s 2>/dev/null)" = Darwin ] && command -v say >/dev/null 2>&1; then
        printf '  say:        always available — the offline floor, used if all else fails\n'
    fi
}

# Enable/disable. Rendered through ts_prompt_choice like every other question;
# it used to be hand-rolled with three options and only two outcomes, and its
# pwsh twin already used Read-TsChoice with two — a live break of the
# byte-identical menu rule.
ts_prompt_cc_tts() {
    if [ -n "${TS_CC_TTS:-}" ]; then
        case "$TS_CC_TTS" in
            on)  echo on; return ;;
            off|skip) echo off; return ;;
        esac
    fi
    local report def _mute_hint=""
    report="$(ts_cc_tts_engine_report 2>/dev/null || true)"
    # ccmute is the daemon's sentinel file, so only promise it where it exists.
    ts_cc_tts_daemon_supported && _mute_hint=' Silence it instantly with `ccmute`.'
    # Something can always speak on a Mac now that `say` is the floor.
    if [ "$(uname -s 2>/dev/null)" = Darwin ]; then def=on
    elif printf '%s' "$report" | grep -q 'reachable at'; then def=on
    else def=off; fi
    ts_prompt_choice "$def" 'Agent voice notifications?' \
"  RECOMMENDATION: ${def}. Claude, Cursor and Codex speak when they finish,
  hit an error, or need you — so you can leave a long run and be called back.
  What can speak here, probed just now:
${report}
  The first reachable engine wins, in that order. Nothing is installed for you.
  Turn it off any time with \`cctts off\`.${_mute_hint}" \
        'off|off|stay silent' \
        'on|on|speak on finish, error and questions'
}

# What gets said. This is the question users actually want and were never asked.
ts_prompt_cc_tts_message() {
    if [ -n "${TS_CC_TTS_MESSAGE:-}" ]; then
        case "$TS_CC_TTS_MESSAGE" in template|self|hook) echo "$TS_CC_TTS_MESSAGE"; return ;; esac
    fi
    ts_prompt_choice self 'What should it say when the agent finishes?' \
'  RECOMMENDATION: self. The agent writes its own one-line summary, so you hear
  what actually happened ("Migrated the parser and all tests pass") instead of
  the same sentence every time. No extra model call, no added latency.
  NOTE: self appends a short instruction block to ~/.claude/CLAUDE.md and
  ~/.codex/AGENTS.md, between markers, so the agent knows to write that line.
  tstack config tts summarizer template removes it again.
  template is the fixed wording. hook reads the last message out raw, which is
  blunt but needs no instruction block.' \
        'self|self|the agent writes its own line' \
        'template|template|same fixed sentence every time' \
        'hook|hook|read the last message out raw'
}

# Rendered via ts_prompt_choice — must stay byte-identical to Read-TsCcTtsDaemon
# (pwsh, Read-TsChoice) per the repo's menu-parity rule. Only the wizard calls
# this, so ts_prompt_choice (from _wizard.sh) is always in scope.
ts_prompt_cc_tts_daemon() {
    if [ -n "${TS_CC_TTS_DAEMON:-}" ]; then
        case "$TS_CC_TTS_DAEMON" in on) echo on; return ;; *) echo off; return ;; esac
    fi
    ts_prompt_choice off 'Route voice notifications through the tray daemon?' \
'  Queues/coalesces announcements, per-session voices, ducks music while speaking.
  Builds one console-free EXE under %LOCALAPPDATA%\terminal-stack. Python is build-time only.' \
        'off|Direct EXE playback' \
        'on|Tray daemon|installs now, autostarts at login'
}

ts_cc_tts_apply_wizard_choice() {
    local choice="$1" daemon="${2:-off}" message="${3:-}"
    # Seed the defaults ONLY on a host that has never been configured. This used
    # to call ts_cc_tts_reset_defaults unconditionally on both on and off, so
    # every `tstack config wizard` re-run silently discarded whatever the user had
    # tuned with `tstack config tts voice …`, `… engine …`, `… template …`.
    local configured
    configured="$(ts_data_get ccTtsEnabled 2>/dev/null || true)"
    case "$choice" in
        on)
            [ -n "$configured" ] || ts_cc_tts_reset_defaults
            ts_cc_tts_set ccTtsEnabled true
            ;;
        off|skip)
            [ -n "$configured" ] || ts_cc_tts_reset_defaults
            ts_cc_tts_set ccTtsEnabled false
            daemon=off
            ;;
    esac
    # What the wizard was told it should say. `self` also installs the marker
    # block into the agent instruction files, which is why it is applied through
    # ts_config_tts rather than a bare ts_cc_tts_set.
    if [ "$choice" = on ] && [ -n "$message" ]; then
        case "$message" in
            self)     ts_cc_tts_set ccTtsMessageMode template
                      ts_cc_tts_set ccTtsSummarizer self
                      ts_cc_tts_self_install || true ;;
            hook)     ts_cc_tts_set ccTtsMessageMode hook
                      ts_cc_tts_set ccTtsSummarizer template
                      ts_cc_tts_self_remove || true ;;
            template) ts_cc_tts_set ccTtsMessageMode template
                      ts_cc_tts_set ccTtsSummarizer template
                      ts_cc_tts_self_remove || true ;;
        esac
    fi

    if [ "$choice" = on ] && ts_cc_tts_daemon_supported; then
        if [ "$daemon" = on ]; then
            ts_cc_tts_daemon_installer || {
                echo "tts: executable build failed — disabling voice hooks" >&2
                ts_cc_tts_set ccTtsEnabled false
                ts_cc_tts_set ccTtsDaemon off
                return 1
            }
            ts_cc_tts_set ccTtsDaemon on
        else
            ts_cc_tts_daemon_installer -NoStart -NoAutostart || {
                echo "tts: executable build failed — disabling voice hooks" >&2
                ts_cc_tts_set ccTtsEnabled false
                return 1
            }
            ts_cc_tts_set ccTtsDaemon off
        fi
    else
        ts_cc_tts_set ccTtsDaemon off
    fi
}

# tstack config tts subcommands (requires $CZ and finish() from ts-config.sh caller).
# List the voices the ACTIVE engine can actually produce, from the engine
# itself. Nothing here is a hardcoded table: kokoro ships 68 and the set moves
# with the image, and a Mac has 184 with more downloadable from System Settings,
# so any list checked into this repo would be wrong on somebody's machine the
# week it was written.
#
# `tstack config tts voices <name>` speaks a sample in that voice. Hearing one is
# the only way to choose, and until now the only way to hear one was to set it
# and wait for an announcement.
ts_cc_tts_list_voices() {
    local want="${1:-}" engine url
    engine="$(ts_cc_tts_get ccTtsEngine)"

    if [ "$engine" = say ] || { [ "$engine" != chatterbox ] && [ "$(uname -s 2>/dev/null)" = Darwin ] && ! ts_cc_tts_kokoro_up; }; then
        command -v say >/dev/null 2>&1 || { echo "say is not available here." >&2; return 1; }
        if [ -n "$want" ]; then
            say -v '?' 2>/dev/null | awk '{print $1}' | grep -qxF "$want" || {
                echo "no installed voice named '$want'" >&2; return 1; }
            echo "==> $want"
            say -v "$want" "Hello, I am $want. This is how I sound."
            return 0
        fi
        echo "macOS system voices (say). English shown; $(say -v '?' 2>/dev/null | wc -l | tr -d ' ') installed in all languages."
        echo "More: System Settings -> Accessibility -> Spoken Content -> Manage Voices."
        say -v '?' 2>/dev/null | awk '$2 ~ /^en/ {printf "  %-16s %s\n", $1, $2}'
        echo
        echo "Hear one:  tstack config tts voices <name>"
        echo "Choose it: tstack config tts voice-say <name>"
        return 0
    fi

    url="$(ts_cc_tts_get ccTtsKokoroUrl)"
    command -v curl >/dev/null 2>&1 || { echo "curl is required to ask the engine." >&2; return 1; }
    local body
    body="$(curl -fsS --max-time 5 "${url%/}/v1/audio/voices" 2>/dev/null || true)"
    [ -n "$body" ] || {
        echo "$WARN kokoro is not answering at $url, so its voice list is unavailable." >&2
        echo "  start it with: tstack services up kokoro" >&2
        return 1; }
    if [ -n "$want" ]; then
        printf '%s' "$body" | grep -qF "\"$want\"" || {
            echo "no voice named '$want' on $url" >&2; return 1; }
        echo "==> $want"
        ts_cc_tts_say_sample_kokoro "$url" "$want"
        return 0
    fi
    echo "kokoro voices at $url. First letter is the language (a=American,"
    echo "b=British, e/f/h/i/j/p/z=other), second is f=female or m=male."
    printf '%s' "$body" | tr ',' '\n' | sed -n 's/.*"\([a-z][a-z]_[a-z0-9]*\)".*/  \1/p' | sort -u
    echo
    echo "Hear one:  tstack config tts voices <name>"
    echo "Choose it: tstack config tts voice <name>"
}

# Is kokoro answering? Used to pick which engine's list to show when the saved
# engine is kokoro but the container is down -- offering a list you cannot hear
# is worse than offering the one you can.
ts_cc_tts_kokoro_up() {
    command -v curl >/dev/null 2>&1 || return 1
    curl -fsS --max-time 2 -o /dev/null "$(ts_cc_tts_get ccTtsKokoroUrl | sed 's:/*$::')/v1/models" 2>/dev/null
}

# Synthesise one sample and play it through the same path an announcement uses.
ts_cc_tts_say_sample_kokoro() {
    local url="$1" voice="$2" tmp
    tmp="$(mktemp -t ts-voice).mp3"
    curl -fsS --max-time 20 -X POST "${url%/}/v1/audio/speech" \
        -H 'content-type: application/json' \
        -d "{\"model\":\"kokoro\",\"input\":\"Hello, I am $voice. This is how I sound.\",\"voice\":\"$voice\",\"response_format\":\"mp3\"}" \
        -o "$tmp" 2>/dev/null || { rm -f "$tmp"; echo "synthesis failed" >&2; return 1; }
    if command -v afplay >/dev/null 2>&1; then afplay "$tmp"
    elif command -v ffplay >/dev/null 2>&1; then ffplay -nodisp -autoexit -loglevel quiet "$tmp"
    else echo "no player available; wrote $tmp" >&2; return 0; fi
    rm -f "$tmp"
}

ts_config_tts() {
    local sub="${1:-}" arg="${2:-}" arg2="${3:-}"
    case "$sub" in
        # Bare `tstack config tts` shows status. Every sibling entrypoint does this
        # (tstack mux, tstack smb, tstack wezterm, tstack doctor, and `tts daemon` below); this
        # was the one verb in the stack that answered with an error instead.
        ''|show)
            ts_cc_tts_show
            ;;
        on)
            if ts_cc_tts_daemon_supported; then
                local exe
                exe="$(ts_cc_tts_exe_path)"
                [ -f "$exe" ] || ts_cc_tts_daemon_installer -NoStart -NoAutostart || return 1
            fi
            ts_cc_tts_set ccTtsEnabled true
            ts_cc_tts_finish
            finish
            ;;
        off)
            ts_cc_tts_set ccTtsEnabled false
            ts_cc_tts_finish
            finish
            ;;
        engine)
            [ -n "$arg" ] || { echo "usage: tstack config tts engine kokoro|chatterbox|say|auto" >&2; return 2; }
            case "$arg" in kokoro|chatterbox|say|auto) ;; *)
                echo "tstack config tts engine: expected kokoro, chatterbox, say, or auto" >&2; return 2 ;; esac
            # `say` is the macOS system voice. It has always been the FLOOR of
            # the ladder; choosing it here moves it to the front. Refuse it
            # elsewhere rather than saving a setting that can never take effect.
            if [ "$arg" = say ] && [ "$(uname -s 2>/dev/null)" != Darwin ]; then
                echo "tstack config tts engine: 'say' is macOS-only (Windows has SAPI, Linux has neither)" >&2
                return 2
            fi
            ts_cc_tts_set ccTtsEngine "$arg"
            ts_cc_tts_finish
            finish
            ;;
        message)
            [ -n "$arg" ] || { echo "usage: tstack config tts message template|hook" >&2; return 2; }
            case "$arg" in template|hook) ;; *)
                echo "tstack config tts message: expected template or hook" >&2; return 2 ;; esac
            ts_cc_tts_set ccTtsMessageMode "$arg"
            ts_cc_tts_finish
            finish
            ;;
        voice)
            [ -n "$arg" ] || { echo "usage: tstack config tts voice <kokoro-voice>" >&2; return 2; }
            ts_cc_tts_set ccTtsKokoroVoice "$arg"
            ts_cc_tts_finish
            finish
            ;;
        voice-say)
            [ -n "$arg" ] || { echo "usage: tstack config tts voice-say <name|system>" >&2; return 2; }
            # "system" clears it: `say -v ""` is an error rather than a synonym
            # for the default, so the empty value is what the lib checks for.
            case "$arg" in system|default) arg="" ;; esac
            if [ -n "$arg" ] && command -v say >/dev/null 2>&1 \
               && ! say -v '?' 2>/dev/null | awk '{print $1}' | grep -qxF "$arg"; then
                echo "tstack config tts voice-say: no installed voice named '$arg'" >&2
                echo "  list them with: tstack config tts voices" >&2
                return 2
            fi
            ts_cc_tts_set ccTtsSayVoice "$arg"
            ts_cc_tts_finish
            finish
            ;;
        voice-chatter)
            [ -n "$arg" ] || { echo "usage: tstack config tts voice-chatter <name>" >&2; return 2; }
            ts_cc_tts_set ccTtsChatterboxVoice "$arg"
            ts_cc_tts_finish
            finish
            ;;
        energy)
            [ -n "$arg" ] || { echo "usage: tstack config tts energy <0-1>" >&2; return 2; }
            ts_cc_tts_set ccTtsChatterboxEnergy "$arg"
            ts_cc_tts_finish
            finish
            ;;
        url)
            [ -n "$arg" ] && [ -n "$arg2" ] || { echo "usage: tstack config tts url kokoro|chatterbox <url>" >&2; return 2; }
            case "$arg" in
                kokoro)      ts_cc_tts_set ccTtsKokoroUrl "$arg2" ;;
                chatterbox)  ts_cc_tts_set ccTtsChatterboxUrl "$arg2" ;;
                *) echo "tstack config tts url: expected kokoro or chatterbox" >&2; return 2 ;;
            esac
            ts_cc_tts_finish
            finish
            ;;
        events)
            [ -n "$arg" ] || { echo "usage: tstack config tts events waiting,error,question,permission" >&2; return 2; }
            ts_cc_tts_set ccTtsEvents "$arg"
            ts_cc_tts_finish
            finish
            ;;
        prefix)
            [ -n "$arg" ] && [ -n "$arg2" ] || { echo "usage: tstack config tts prefix claude|cursor|codex on|off|<label>" >&2; return 2; }
            case "$arg" in
                claude)
                    case "$arg2" in
                        on)  ts_cc_tts_set ccTtsPrefixClaudeEnabled true ;;
                        off) ts_cc_tts_set ccTtsPrefixClaudeEnabled false ;;
                        *)   ts_cc_tts_set ccTtsPrefixClaude "$arg2"; ts_cc_tts_set ccTtsPrefixClaudeEnabled true ;;
                    esac ;;
                cursor)
                    case "$arg2" in
                        on)  ts_cc_tts_set ccTtsPrefixCursorEnabled true ;;
                        off) ts_cc_tts_set ccTtsPrefixCursorEnabled false ;;
                        *)   ts_cc_tts_set ccTtsPrefixCursor "$arg2"; ts_cc_tts_set ccTtsPrefixCursorEnabled true ;;
                    esac ;;
                codex)
                    case "$arg2" in
                        on)  ts_cc_tts_set ccTtsPrefixCodexEnabled true ;;
                        off) ts_cc_tts_set ccTtsPrefixCodexEnabled false ;;
                        *)   ts_cc_tts_set ccTtsPrefixCodex "$arg2"; ts_cc_tts_set ccTtsPrefixCodexEnabled true ;;
                    esac ;;
                *) echo "tstack config tts prefix: expected claude, cursor, or codex" >&2; return 2 ;;
            esac
            ts_cc_tts_finish
            finish
            ;;
        project)
            [ -n "$arg" ] || { echo "usage: tstack config tts project on|off" >&2; return 2; }
            case "$arg" in
                on)  ts_cc_tts_set ccTtsIncludeProject true ;;
                off) ts_cc_tts_set ccTtsIncludeProject false ;;
                *) echo "tstack config tts project: expected on or off" >&2; return 2 ;;
            esac
            ts_cc_tts_finish
            finish
            ;;
        excitement)
            [ -n "$arg" ] || { echo "usage: tstack config tts excitement <0-1>" >&2; return 2; }
            ts_cc_tts_set ccTtsExcitement "$arg"
            ts_cc_tts_set ccTtsChatterboxEnergy "$arg"
            ts_cc_tts_finish
            finish
            ;;
        template)
            [ -n "$arg" ] && [ -n "$arg2" ] || { echo "usage: tstack config tts template waiting|error|question|permission \"…\"" >&2; return 2; }
            case "$arg" in
                waiting)    ts_cc_tts_set ccTtsTemplateWaiting "$arg2" ;;
                error)      ts_cc_tts_set ccTtsTemplateError "$arg2" ;;
                question)   ts_cc_tts_set ccTtsTemplateQuestion "$arg2" ;;
                permission) ts_cc_tts_set ccTtsTemplatePermission "$arg2" ;;
                *) echo "tstack config tts template: unknown event '$arg'" >&2; return 2 ;;
            esac
            ts_cc_tts_finish
            finish
            ;;
        daemon)
            case "$arg" in
                on)
                    ts_cc_tts_daemon_supported || { echo "tts daemon: Windows-only; this host uses direct playback." >&2; return 1; }
                    ts_cc_tts_daemon_installer || return 1
                    ts_cc_tts_set ccTtsDaemon on
                    ts_cc_tts_finish
                    finish
                    ;;
                off)
                    ts_cc_tts_daemon_supported || { echo "tts daemon: Windows-only; this host uses direct playback." >&2; return 1; }
                    ts_cc_tts_daemon_installer -Uninstall || true
                    ts_cc_tts_set ccTtsDaemon off
                    ts_cc_tts_finish
                    finish
                    ;;
                install)
                    ts_cc_tts_daemon_supported || { echo "tts daemon: Windows-only; this host uses direct playback." >&2; return 1; }
                    ts_cc_tts_daemon_installer -NoStart
                    ;;
                restart)
                    ts_cc_tts_daemon_supported || { echo "tts daemon: Windows-only; this host uses direct playback." >&2; return 1; }
                    ts_cc_tts_daemon_installer -Uninstall || true
                    ts_cc_tts_daemon_installer
                    ;;
                ''|status)
                    ts_cc_tts_daemon_status
                    ;;
                *)
                    echo "usage: tstack config tts daemon on|off|status|restart|install" >&2; return 2 ;;
            esac
            ;;
        summarizer)
            [ -n "$arg" ] || { echo "usage: tstack config tts summarizer template|self|haiku|ollama" >&2; return 2; }
            case "$arg" in template|self|haiku|ollama) ;; *)
                echo "tstack config tts summarizer: expected template, self, haiku, or ollama" >&2; return 2 ;; esac
            # template and self run in the shell path on every platform. haiku
            # and ollama live in the daemon, so storing them on a host without
            # one is a setting nothing will ever read — say so instead.
            case "$arg" in
                haiku|ollama)
                    ts_cc_tts_daemon_supported || {
                        echo "tstack config tts summarizer: '$arg' needs the tray daemon (Windows)." >&2
                        echo "  On this host use: template (fixed lines) or self (the agent writes its own line)." >&2
                        return 1
                    } ;;
            esac
            ts_cc_tts_set ccTtsSummarizer "$arg"
            if [ "$arg" = self ]; then ts_cc_tts_self_install || true; else ts_cc_tts_self_remove || true; fi
            ts_cc_tts_finish
            finish
            ;;
        haiku-model)
            [ -n "$arg" ] || { echo "usage: tstack config tts haiku-model <model>" >&2; return 2; }
            ts_cc_tts_set ccTtsHaikuModel "$arg"
            ts_cc_tts_finish
            finish
            ;;
        ollama)
            [ -n "$arg" ] || { echo "usage: tstack config tts ollama <url> [<model>]" >&2; return 2; }
            ts_cc_tts_set ccTtsOllamaUrl "$arg"
            [ -n "$arg2" ] && ts_cc_tts_set ccTtsOllamaModel "$arg2"
            ts_cc_tts_finish
            finish
            ;;
        music)
            # Ducking is daemon-only AND built on pycaw/WinRT, so on any
            # other host this accepted and persisted a value with no reader.
            ts_cc_tts_daemon_supported || {
                echo "tstack config tts $sub: music ducking needs the tray daemon (Windows only)." >&2
                echo "  There is no CoreAudio equivalent here; the setting would do nothing." >&2
                return 1
            }
            [ -n "$arg" ] || { echo "usage: tstack config tts music duck|smart|pause|off" >&2; return 2; }
            case "$arg" in duck|smart|pause|off) ;; *)
                echo "tstack config tts music: expected duck, smart, pause, or off" >&2; return 2 ;; esac
            ts_cc_tts_set ccTtsMusicMode "$arg"
            ts_cc_tts_finish
            finish
            ;;
        duck-level)
            # Ducking is daemon-only AND built on pycaw/WinRT, so on any
            # other host this accepted and persisted a value with no reader.
            ts_cc_tts_daemon_supported || {
                echo "tstack config tts $sub: music ducking needs the tray daemon (Windows only)." >&2
                echo "  There is no CoreAudio equivalent here; the setting would do nothing." >&2
                return 1
            }
            case "$arg" in ''|*[!0-9]*) echo "usage: tstack config tts duck-level <0-100>" >&2; return 2 ;; esac
            [ "$arg" -le 100 ] || { echo "tstack config tts duck-level: expected 0-100" >&2; return 2; }
            ts_cc_tts_set ccTtsDuckPercent "$arg"
            ts_cc_tts_finish
            finish
            ;;
        voices)
            # `voices` now LISTS what you can pick, which is what the word means
            # to someone reading the help. It used to set the daemon's
            # per-session rotation pool -- a genuine collision: the two have
            # nothing to do with each other, and the pool is read only by the
            # Windows daemon. That is `voice-pool` now; `voices show|<csv>`
            # still works so an existing script does not break.
            # A voice name never contains a comma and the pool always does when
            # it means anything, so the two old forms stay distinguishable. The
            # CSV form is refused rather than silently honoured: it used to be
            # THIS verb, and a user who types it deserves to be pointed at the
            # new one instead of wondering why nothing was sampled.
            case "$arg" in
                show)
                    echo "voice pool: $(ts_cc_tts_get ccTtsVoicePool)"
                    echo "  (that is the daemon rotation pool; it moved to 'tstack config tts voice-pool')" >&2
                    ;;
                *,*)
                    echo "tstack config tts voices: this sets the daemon rotation pool now:" >&2
                    echo "  tstack config tts voice-pool $arg" >&2
                    echo "'voices' lists what you can pick, and 'voices <name>' plays a sample." >&2
                    return 2
                    ;;
                *)  ts_cc_tts_list_voices "$arg" ;;
            esac
            ;;
        voice-pool)
            if [ -z "$arg" ] || [ "$arg" = show ]; then
                echo "voice pool: $(ts_cc_tts_get ccTtsVoicePool)"
            else
                ts_cc_tts_set ccTtsVoicePool "$arg"
                ts_cc_tts_finish
                finish
            fi
            ;;
        port)
            case "$arg" in ''|*[!0-9]*) echo "usage: tstack config tts port <n>" >&2; return 2 ;; esac
            ts_cc_tts_set ccTtsDaemonPort "$arg"
            ts_cc_tts_finish
            finish
            ;;
        test)
            if [ -f "${HOME}/.claude/hooks/cc-tts-test.sh" ]; then
                if [ "$arg" = --source ] && [ -n "$arg2" ]; then
                    CC_TTS_VERBOSE=1 "${HOME}/.claude/hooks/cc-tts-test.sh" --source "$arg2"
                else
                    CC_TTS_VERBOSE=1 "${HOME}/.claude/hooks/cc-tts-test.sh"
                fi
            else
                echo "tstack config tts test: cc-tts-test.sh not found (run chezmoi apply)" >&2
                return 1
            fi
            ;;
        history)
            # Deliberately the executable, not the daemon API: the interesting cases are
            # the ones where the daemon is not answering.
            ts_cc_tts_daemon_supported || { echo "tts history: Windows-only; this host uses direct playback." >&2; return 1; }
            local hexe
            hexe="$(ts_cc_tts_exe_path)" || { echo "tts history: not a WSL host" >&2; return 1; }
            [ -f "$hexe" ] || { echo "tts history: terminal-stack-tts.exe not found (run tstack config tts daemon install)" >&2; return 1; }
            case "$arg" in
                --dupes|dupes)
                    if [ -n "$arg2" ]; then "$hexe" history --dupes --within "$arg2"; else "$hexe" history --dupes; fi ;;
                '') "$hexe" history ;;
                *) "$hexe" history --limit "$arg" ;;
            esac
            ;;
        reset)
            ts_cc_tts_reset_defaults
            ts_cc_tts_finish
            finish
            ;;
        -h|--help|help)
            cat <<'EOF'
tstack config tts — agent local TTS (Kokoro / Chatterbox / edge-tts)
  show | on | off | test [--source claude|cursor|codex|test] | reset
  engine kokoro|chatterbox|auto
  message template|hook
  voice <kokoro-voice> | voice-chatter <name>
  energy <0-1> | excitement <0-1>
  url kokoro|chatterbox <url>
  events waiting,error,question,permission
  prefix claude|cursor|codex on|off|<label>
  project on|off
  template waiting|error|question|permission "…"
  daemon on|off|status|restart|install    (Windows tray daemon: queue/coalesce/duck)
  summarizer template|self|haiku|ollama   (self also installs the CLAUDE.md block)
  haiku-model <model> | ollama <url> [<model>]
  music duck|smart|pause|off | duck-level <0-100>
  voices [<name>] | voice-say <name|system> | voice-pool show|<v1,v2,...> | port <n>
  history [<n>] | history --dupes [<sec>]  (what was said, and what was suppressed)
  (to go quiet right now use ccmute — instant, no apply; tray icon and hotkey share it)
EOF
            ;;
        *)
            echo "tstack config tts: unknown subcommand '$sub' (try: show, on, off, test; -h for all)" >&2
            return 2
            ;;
    esac
}

ts_config_tts_menu() {
    echo "  a) enable (on)   b) disable (off)   c) test   d) daemon status   e) back"
    local c; c="$(ts_tty_prompt 'Choose: ')"
    case "$c" in
        a|A) ts_config_tts on ;;
        b|B) ts_config_tts off ;;
        c|C) ts_config_tts test ;;
        d|D) ts_config_tts daemon status ;;
        *) ;;
    esac
}
