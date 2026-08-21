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
        ccTtsEdgeEnabled ccTtsEdgeVoice \
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
    # Directory of this file — the clone's bootstrap/ (works because ts-config
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
        echo "  saved setting ccTtsDaemon=$(ts_cc_tts_get ccTtsDaemon)  —  start: ts-config tts daemon on"
        return 1
    fi
    echo "tts daemon: $health"
    sha="$(git -C "$(ts_cc_tts_bootstrap_dir)/.." rev-parse HEAD 2>/dev/null || true)"
    if [ -n "$sha" ] && ! printf '%s' "$health" | grep -q "$sha"; then
        echo "tts daemon: running an older build than this clone — ts-config tts daemon restart"
    fi
}

# ── `summarizer self` marker block in the user's ~/.claude/CLAUDE.md ───────────
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

ts_cc_tts_self_install() {
    local target="${HOME}/.claude/CLAUDE.md"
    local asset
    asset="$(ts_cc_tts_bootstrap_dir)/tts-daemon/assets/speak-summary.md"
    [ -f "$asset" ] || { echo "tts: speak-summary.md asset not found (run ts-update?)" >&2; return 1; }
    mkdir -p "${HOME}/.claude" 2>/dev/null || true
    if [ -f "$target" ]; then
        ts_cc_tts_backup_file "$target"
        { ts_cc_tts_self_strip "$target"; echo; cat "$asset"; } > "$target.tmp" \
            && mv "$target.tmp" "$target"
    else
        cat "$asset" > "$target"
    fi
    echo "tts: spoken-summary instruction installed in $target"
}

ts_cc_tts_self_remove() {
    local target="${HOME}/.claude/CLAUDE.md"
    [ -f "$target" ] || return 0
    grep -qF "$TS_CC_TTS_SELF_START" "$target" || return 0
    ts_cc_tts_backup_file "$target"
    ts_cc_tts_self_strip "$target" > "$target.tmp" && mv "$target.tmp" "$target"
    echo "tts: spoken-summary instruction removed from $target"
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

ts_prompt_cc_tts() {
    if [ -n "${TS_CC_TTS:-}" ]; then
        case "$TS_CC_TTS" in
            on)  echo on; return ;;
            off|skip) echo off; return ;;
        esac
    fi
    {
        printf '\nClaude Code voice notifications (local Kokoro TTS, am_adam)?\n'
        printf '  Requires Kokoro on http://127.0.0.1:8880 (Docker). Does not install containers.\n'
        if ts_cc_tts_wizard_probe | grep -q probe_ok; then
            printf '  Kokoro probe: OK\n'
            printf '  1) Enable (am_adam, waiting+error)  [recommended]\n'
        else
            printf '  Kokoro probe: not reachable\n'
            printf '  1) Enable (am_adam, waiting+error)\n'
        fi
        printf '  2) Enable anyway (start Kokoro later)\n'
        printf '  3) Skip\n'
    } > /dev/tty 2>/dev/null
    local ans; ans="$(ts_tty_prompt 'Choose [3]: ')"
    case "$ans" in
        1|2) echo on ;;
        *)   echo off ;;
    esac
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
  Installs a small Python venv under %LOCALAPPDATA%\terminal-stack. Needs Python 3.10+.' \
        'off|Classic direct playback' \
        'on|Tray daemon|installs now, autostarts at login'
}

ts_cc_tts_apply_wizard_choice() {
    local choice="$1" daemon="${2:-off}"
    case "$choice" in
        on)
            ts_cc_tts_reset_defaults
            ts_cc_tts_set ccTtsEnabled true
            ;;
        off|skip)
            ts_cc_tts_reset_defaults
            ts_cc_tts_set ccTtsEnabled false
            daemon=off
            ;;
    esac
    if [ "$daemon" = on ] && ts_cc_tts_daemon_supported; then
        if ts_cc_tts_daemon_installer; then
            ts_cc_tts_set ccTtsDaemon on
        else
            echo "tts daemon: install failed — keeping direct playback (retry: ts-config tts daemon on)" >&2
            ts_cc_tts_set ccTtsDaemon off
        fi
    else
        ts_cc_tts_set ccTtsDaemon off
    fi
}

# ts-config tts subcommands (requires $CZ and finish() from ts-config.sh caller).
ts_config_tts() {
    local sub="${1:-}" arg="${2:-}" arg2="${3:-}"
    case "$sub" in
        show)
            ts_cc_tts_show
            ;;
        on)
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
            [ -n "$arg" ] || { echo "usage: ts-config tts engine kokoro|chatterbox|auto" >&2; return 2; }
            case "$arg" in kokoro|chatterbox|auto) ;; *)
                echo "ts-config tts engine: expected kokoro, chatterbox, or auto" >&2; return 2 ;; esac
            ts_cc_tts_set ccTtsEngine "$arg"
            ts_cc_tts_finish
            finish
            ;;
        message)
            [ -n "$arg" ] || { echo "usage: ts-config tts message template|hook" >&2; return 2; }
            case "$arg" in template|hook) ;; *)
                echo "ts-config tts message: expected template or hook" >&2; return 2 ;; esac
            ts_cc_tts_set ccTtsMessageMode "$arg"
            ts_cc_tts_finish
            finish
            ;;
        voice)
            [ -n "$arg" ] || { echo "usage: ts-config tts voice <kokoro-voice>" >&2; return 2; }
            ts_cc_tts_set ccTtsKokoroVoice "$arg"
            ts_cc_tts_finish
            finish
            ;;
        voice-chatter)
            [ -n "$arg" ] || { echo "usage: ts-config tts voice-chatter <name>" >&2; return 2; }
            ts_cc_tts_set ccTtsChatterboxVoice "$arg"
            ts_cc_tts_finish
            finish
            ;;
        energy)
            [ -n "$arg" ] || { echo "usage: ts-config tts energy <0-1>" >&2; return 2; }
            ts_cc_tts_set ccTtsChatterboxEnergy "$arg"
            ts_cc_tts_finish
            finish
            ;;
        url)
            [ -n "$arg" ] && [ -n "$arg2" ] || { echo "usage: ts-config tts url kokoro|chatterbox <url>" >&2; return 2; }
            case "$arg" in
                kokoro)      ts_cc_tts_set ccTtsKokoroUrl "$arg2" ;;
                chatterbox)  ts_cc_tts_set ccTtsChatterboxUrl "$arg2" ;;
                *) echo "ts-config tts url: expected kokoro or chatterbox" >&2; return 2 ;;
            esac
            ts_cc_tts_finish
            finish
            ;;
        events)
            [ -n "$arg" ] || { echo "usage: ts-config tts events waiting,error,question,permission" >&2; return 2; }
            ts_cc_tts_set ccTtsEvents "$arg"
            ts_cc_tts_finish
            finish
            ;;
        prefix)
            [ -n "$arg" ] && [ -n "$arg2" ] || { echo "usage: ts-config tts prefix claude|cursor|codex on|off|<label>" >&2; return 2; }
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
                *) echo "ts-config tts prefix: expected claude, cursor, or codex" >&2; return 2 ;;
            esac
            ts_cc_tts_finish
            finish
            ;;
        project)
            [ -n "$arg" ] || { echo "usage: ts-config tts project on|off" >&2; return 2; }
            case "$arg" in
                on)  ts_cc_tts_set ccTtsIncludeProject true ;;
                off) ts_cc_tts_set ccTtsIncludeProject false ;;
                *) echo "ts-config tts project: expected on or off" >&2; return 2 ;;
            esac
            ts_cc_tts_finish
            finish
            ;;
        excitement)
            [ -n "$arg" ] || { echo "usage: ts-config tts excitement <0-1>" >&2; return 2; }
            ts_cc_tts_set ccTtsExcitement "$arg"
            ts_cc_tts_set ccTtsChatterboxEnergy "$arg"
            ts_cc_tts_finish
            finish
            ;;
        template)
            [ -n "$arg" ] && [ -n "$arg2" ] || { echo "usage: ts-config tts template waiting|error|question|permission \"…\"" >&2; return 2; }
            case "$arg" in
                waiting)    ts_cc_tts_set ccTtsTemplateWaiting "$arg2" ;;
                error)      ts_cc_tts_set ccTtsTemplateError "$arg2" ;;
                question)   ts_cc_tts_set ccTtsTemplateQuestion "$arg2" ;;
                permission) ts_cc_tts_set ccTtsTemplatePermission "$arg2" ;;
                *) echo "ts-config tts template: unknown event '$arg'" >&2; return 2 ;;
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
                    echo "usage: ts-config tts daemon on|off|status|restart|install" >&2; return 2 ;;
            esac
            ;;
        summarizer)
            [ -n "$arg" ] || { echo "usage: ts-config tts summarizer template|self|haiku|ollama" >&2; return 2; }
            case "$arg" in template|self|haiku|ollama) ;; *)
                echo "ts-config tts summarizer: expected template, self, haiku, or ollama" >&2; return 2 ;; esac
            ts_cc_tts_set ccTtsSummarizer "$arg"
            if [ "$arg" = self ]; then ts_cc_tts_self_install || true; else ts_cc_tts_self_remove || true; fi
            ts_cc_tts_finish
            finish
            ;;
        haiku-model)
            [ -n "$arg" ] || { echo "usage: ts-config tts haiku-model <model>" >&2; return 2; }
            ts_cc_tts_set ccTtsHaikuModel "$arg"
            ts_cc_tts_finish
            finish
            ;;
        ollama)
            [ -n "$arg" ] || { echo "usage: ts-config tts ollama <url> [<model>]" >&2; return 2; }
            ts_cc_tts_set ccTtsOllamaUrl "$arg"
            [ -n "$arg2" ] && ts_cc_tts_set ccTtsOllamaModel "$arg2"
            ts_cc_tts_finish
            finish
            ;;
        music)
            [ -n "$arg" ] || { echo "usage: ts-config tts music duck|smart|pause|off" >&2; return 2; }
            case "$arg" in duck|smart|pause|off) ;; *)
                echo "ts-config tts music: expected duck, smart, pause, or off" >&2; return 2 ;; esac
            ts_cc_tts_set ccTtsMusicMode "$arg"
            ts_cc_tts_finish
            finish
            ;;
        duck-level)
            case "$arg" in ''|*[!0-9]*) echo "usage: ts-config tts duck-level <0-100>" >&2; return 2 ;; esac
            [ "$arg" -le 100 ] || { echo "ts-config tts duck-level: expected 0-100" >&2; return 2; }
            ts_cc_tts_set ccTtsDuckPercent "$arg"
            ts_cc_tts_finish
            finish
            ;;
        voices)
            if [ -z "$arg" ] || [ "$arg" = show ]; then
                echo "voice pool: $(ts_cc_tts_get ccTtsVoicePool)"
            else
                ts_cc_tts_set ccTtsVoicePool "$arg"
                ts_cc_tts_finish
                finish
            fi
            ;;
        port)
            case "$arg" in ''|*[!0-9]*) echo "usage: ts-config tts port <n>" >&2; return 2 ;; esac
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
                echo "ts-config tts test: cc-tts-test.sh not found (run chezmoi apply)" >&2
                return 1
            fi
            ;;
        reset)
            ts_cc_tts_reset_defaults
            ts_cc_tts_finish
            finish
            ;;
        -h|--help|help)
            cat <<'EOF'
ts-config tts — agent local TTS (Kokoro / Chatterbox / edge-tts)
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
  voices show|<v1,v2,...> | port <n>
EOF
            ;;
        *)
            echo "ts-config tts: unknown subcommand '$sub' (try: show, on, off, test)" >&2
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
