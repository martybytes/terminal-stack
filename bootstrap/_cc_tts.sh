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
        ccTtsPrefixClaudeEnabled)  echo true ;;
        ccTtsPrefixCursorEnabled)  echo true ;;
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
        ccTtsPrefixClaude ccTtsPrefixCursor ccTtsPrefixClaudeEnabled ccTtsPrefixCursorEnabled \
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
    "prefixClaudeEnabled": $([ "$(ts_cc_tts_get ccTtsPrefixClaudeEnabled)" = true ] && echo true || echo false),
    "prefixCursorEnabled": $([ "$(ts_cc_tts_get ccTtsPrefixCursorEnabled)" = true ] && echo true || echo false),
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

ts_cc_tts_apply_wizard_choice() {
    local choice="$1"
    case "$choice" in
        on)
            ts_cc_tts_reset_defaults
            ts_cc_tts_set ccTtsEnabled true
            ;;
        off|skip)
            ts_cc_tts_reset_defaults
            ts_cc_tts_set ccTtsEnabled false
            ;;
    esac
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
            [ -n "$arg" ] && [ -n "$arg2" ] || { echo "usage: ts-config tts prefix claude|cursor on|off|<label>" >&2; return 2; }
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
                *) echo "ts-config tts prefix: expected claude or cursor" >&2; return 2 ;;
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
ts-config tts — Claude Code local TTS (Kokoro / Chatterbox / edge-tts)
  show | on | off | test [--source claude|cursor|test] | reset
  engine kokoro|chatterbox|auto
  message template|hook
  voice <kokoro-voice> | voice-chatter <name>
  energy <0-1> | excitement <0-1>
  url kokoro|chatterbox <url>
  events waiting,error,question,permission
  prefix claude|cursor on|off|<label>
  project on|off
  template waiting|error|question|permission "…"
EOF
            ;;
        *)
            echo "ts-config tts: unknown subcommand '$sub' (try: show, on, off, test)" >&2
            return 2
            ;;
    esac
}

ts_config_tts_menu() {
    echo "  a) enable (on)   b) disable (off)   c) test   d) back"
    local c; c="$(ts_tty_prompt 'Choose: ')"
    case "$c" in
        a|A) ts_config_tts on ;;
        b|B) ts_config_tts off ;;
        c|C) ts_config_tts test ;;
        *) ;;
    esac
}
