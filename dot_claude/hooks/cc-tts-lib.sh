#!/usr/bin/env bash
# cc-tts-lib.sh — shared helpers for Claude Code / Cursor TTS hooks (sourced, not executed).
CC_TTS_CONFIG_DIR="${CC_TTS_CONFIG_DIR:-${HOME}/.claude/tts}"
CC_TTS_CONFIG_BASE="${CC_TTS_CONFIG_DIR}/config.json"
CC_TTS_CONFIG_LOCAL="${CC_TTS_CONFIG_DIR}/local.json"
CC_TTS_LEGACY="${HOME}/.claude/tts.json"
CONFIG="${CC_TTS_CONFIG:-}"

cc_tts_log() {
    [ -n "${CC_TTS_VERBOSE:-}" ] && echo "cc-tts: $*" >&2
}

# WSL hooks use the same console-free Windows executable as native Windows.
# Resolve it with shell globbing so a hook never launches cmd.exe/PowerShell
# merely to discover the Windows username.
cc_tts_windows_exe() {
    local candidate
    [ -d /mnt/c/Users ] || return 1
    for candidate in /mnt/c/Users/*/AppData/Local/terminal-stack/tts-daemon/terminal-stack-tts.exe; do
        [ -f "$candidate" ] || continue
        printf '%s' "$candidate"
        return 0
    done
    return 1
}

cc_tts_windows_hook() {
    # cc_tts_windows_hook <source> <event> <state> <raw-json>
    local source="$1" event="$2" state="$3" input="$4" exe
    exe="$(cc_tts_windows_exe)" || return 1
    printf '%s' "$input" | "$exe" hook --source "$source" --event "$event" \
        --state "$state"
}

# The absolute mute, as the tray icon / hotkey / ccmute write it. The sentinel lives in
# the Windows daemon's state dir, because on a combined host that is the process that does
# the talking; a native Linux host, which has no ttsd, keeps its own next to the config.
cc_tts_mute_path() {
    local winuser
    if [ -d /mnt/c/Users ]; then
        winuser="$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n')"
        if [ -n "$winuser" ]; then
            printf '/mnt/c/Users/%s/AppData/Local/terminal-stack/tts-daemon/state/muted' "$winuser"
            return 0
        fi
    fi
    printf '%s/.claude/tts/muted' "$HOME"
}

cc_tts_muted() {
    [ -f "$(cc_tts_mute_path)" ]
}

cc_tts_init_config() {
    [ -n "$CONFIG" ] && [ -f "$CONFIG" ] && return 0

    local merged="${CC_TTS_CONFIG_DIR}/.merged.json"
    mkdir -p "$CC_TTS_CONFIG_DIR" 2>/dev/null || true

    if [ ! -f "$CC_TTS_CONFIG_BASE" ] && [ -f "$CC_TTS_LEGACY" ]; then
        cc_tts_log "migrating $CC_TTS_LEGACY -> $CC_TTS_CONFIG_BASE"
        cp -p "$CC_TTS_LEGACY" "$CC_TTS_CONFIG_BASE" 2>/dev/null || cp "$CC_TTS_LEGACY" "$CC_TTS_CONFIG_BASE"
    fi

    if [ ! -f "$CC_TTS_CONFIG_BASE" ]; then
        CONFIG="$CC_TTS_LEGACY"
        return 0
    fi

    if command -v python3 >/dev/null 2>&1; then
        python3 - "$CC_TTS_CONFIG_BASE" "$CC_TTS_CONFIG_LOCAL" "$merged" <<'PY' 2>/dev/null || cp "$CC_TTS_CONFIG_BASE" "$merged"
import json, sys
base_p, local_p, out_p = sys.argv[1], sys.argv[2], sys.argv[3]
def deep_merge(a, b):
    if not isinstance(a, dict) or not isinstance(b, dict):
        return b
    out = dict(a)
    for k, v in b.items():
        if k.startswith('_'):
            continue
        out[k] = deep_merge(out.get(k), v) if k in out else v
    return out
with open(base_p, encoding='utf-8') as f:
    cfg = json.load(f)
if __import__('os').path.isfile(local_p):
    with open(local_p, encoding='utf-8') as f:
        loc = json.load(f)
    cfg = deep_merge(cfg, loc)
# Legacy flat templates -> announce.templates
if 'templates' in cfg and 'announce' not in cfg:
    cfg['announce'] = {'messageMode': cfg.pop('messageMode', 'template'),
                       'includeProject': True,
                       'templates': cfg.pop('templates')}
if 'messageMode' in cfg and isinstance(cfg.get('announce'), dict):
    cfg['announce'].setdefault('messageMode', cfg.pop('messageMode'))
with open(out_p, 'w', encoding='utf-8') as f:
    json.dump(cfg, f, indent=2)
PY
        CONFIG="$merged"
    else
        CONFIG="$CC_TTS_CONFIG_BASE"
    fi
}

cc_tts_json() {
    cc_tts_init_config
    local key="$1" default="${2:-}"
    if [ ! -f "$CONFIG" ]; then
        echo "$default"
        return
    fi
    if command -v jq >/dev/null 2>&1; then
        jq -r "$key // empty" "$CONFIG" 2>/dev/null || echo "$default"
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$CONFIG" "$key" "$default" <<'PY' 2>/dev/null || echo "$default"
import json, sys
path, key, default = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path, encoding='utf-8') as f:
        d = json.load(f)
    for part in key.strip('.').split('.'):
        if isinstance(d, dict):
            d = d.get(part)
        else:
            d = None
            break
    if d is None:
        print(default)
    elif isinstance(d, bool):
        print('true' if d else 'false')
    else:
        print(d)
except Exception:
    print(default)
PY
        return
    fi
    case "$key" in
        .enabled) grep -q '"enabled"[[:space:]]*:[[:space:]]*true' "$CONFIG" && echo true || echo false ;;
        *) echo "$default" ;;
    esac
}

cc_tts_assistant_text() {
    # Extract the last assistant message from hook JSON. jq is preferred, but
    # Git Bash and minimal POSIX hosts may have Python without jq.
    local input="${1:-}" mode="${2:-transcript}" py
    [ -n "$input" ] || return 0

    if command -v jq >/dev/null 2>&1; then
        if [ "$mode" = direct ]; then
            if printf '%s' "$input" | jq -r '
                (.last_assistant_message // .text // empty) as $direct
                | if ($direct | type) == "string" and ($direct | length) > 0 then $direct else
                [.. | objects
                 | select(.role? == "assistant" or .type? == "assistant")
                 | (.content // .message // empty)
                 | if type == "array" then
                     [ .[] | select(.type? == "text") | .text ] | join(" ")
                   elif type == "string" then .
                   else empty end
                ] | last // empty end' 2>/dev/null; then
                return 0
            fi
        elif printf '%s' "$input" | jq -r '
            [.. | objects
             | select(.role? == "assistant" or .type? == "assistant")
             | (.content // .message // empty)
             | if type == "array" then
                 [ .[] | select(.type? == "text") | .text ] | join(" ")
               elif type == "string" then .
               else empty end
            ] | last // empty' 2>/dev/null; then
            return 0
        fi
    fi

    if command -v python3 >/dev/null 2>&1; then
        py="$(command -v python3)"
    elif command -v python >/dev/null 2>&1; then
        py="$(command -v python)"
    else
        return 0
    fi

    printf '%s' "$input" | "$py" -c '
import json
import sys


def objects(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def assistant_text(value):
    if not isinstance(value, dict):
        return ""
    if value.get("role") != "assistant" and value.get("type") != "assistant":
        return ""
    content = value.get("content")
    if content is None:
        content = value.get("message")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            item.get("text", "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
    return ""


try:
    payload = json.load(sys.stdin)
except Exception:
    raise SystemExit(0)

if sys.argv[1] == "direct" and isinstance(payload, dict):
    direct = payload.get("last_assistant_message") or payload.get("text")
    if isinstance(direct, str) and direct:
        print(direct, end="")
        raise SystemExit(0)

messages = [text for item in objects(payload) if (text := assistant_text(item))]
if messages:
    print(messages[-1], end="")
' "$mode" 2>/dev/null || true
}

cc_tts_event_enabled() {
    local ev="$1"
    if command -v jq >/dev/null 2>&1 && [ -f "$CONFIG" ]; then
        jq -e --arg e "$ev" '.events | index($e) != null' "$CONFIG" >/dev/null 2>&1
        return $?
    fi
    grep -q "\"$ev\"" "$CONFIG" 2>/dev/null
}

cc_tts_effective_excitement() {
    cc_tts_json .excitement ''
}

cc_tts_effective_kokoro_speed() {
    local exc base
    exc="$(cc_tts_effective_excitement)"
    if [ -n "$exc" ]; then
        awk -v e="$exc" 'BEGIN { printf "%.2f", 0.8 + e * 0.4 }'
        return
    fi
    cc_tts_json .kokoro.speed 1.0
}

cc_tts_effective_chatterbox_energy() {
    local exc
    exc="$(cc_tts_effective_excitement)"
    if [ -n "$exc" ]; then
        echo "$exc"
        return
    fi
    cc_tts_json .chatterbox.energy 0.25
}

# ── `self` summarizer, shell side ──────────────────────────────────────────────
# Port of ttsd/summarize.py's _extract_marker/_self_summary. That Python runs
# only inside the Windows EXE, so on macOS and native Linux `self` used to be
# accepted, persisted, and never read — while STILL appending the marker block
# to ~/.claude/CLAUDE.md, so the agent emitted <!-- speak: … --> comments that
# nothing consumed. These two helpers give the direct path the same behaviour.
#
# Keep in step with ttsd/summarize.py:136-169; a test drives both on the same
# fixtures and compares.

# Strip a fenced code block, markdown emphasis, links and bare URLs, and
# collapse whitespace — the shell twin of summarize.py's _speakable().
cc_tts_speakable() {
    printf '%s' "$1" | sed -E \
        -e 's/`[^`]*`/ /g' \
        -e 's/!?\[([^]]*)\]\([^)]*\)/\1/g' \
        -e 's#https?://[^[:space:]]*# #g' \
        -e 's/[*_~>#]+/ /g' \
        -e 's/[[:space:]]+/ /g' \
        -e 's/^ //; s/ $//'
}

# Last <!-- speak: … --> in the text, or empty. Last wins, matching
# _extract_marker's matches[-1].
cc_tts_speak_marker() {
    local one
    one="$(printf '%s' "$1" | tr '\n' ' ')"
    printf '%s' "$one" | sed -n 's/.*<!--[[:space:]]*speak:[[:space:]]*\(.*\)[[:space:]]*-->.*/\1/p' \
        | sed -E 's/[[:space:]]+$//'
}

# Remove every marker comment, so it can never be spoken verbatim in hook mode.
cc_tts_strip_markers() {
    printf '%s' "$1" | sed -E 's/<!--[[:space:]]*speak:[^>]*-->/ /g'
}

# One prose sentence from the agent's final message: drop fenced code, drop the
# markers, skip blanks and headings, strip list bullets, first sentence, ≤15
# words. Mirrors _self_summary's fallback branch.
cc_tts_self_summary() {
    local text="$1" marked clean line spoken sentence
    marked="$(cc_tts_speak_marker "$text")"
    if [ -n "$marked" ]; then
        cc_tts_speakable "$marked"
        return 0
    fi
    clean="$(printf '%s' "$text" | sed -E '/^[[:space:]]*```/,/^[[:space:]]*```/d')"
    clean="$(cc_tts_strip_markers "$clean")"
    printf '%s\n' "$clean" | while IFS= read -r line; do
        line="${line#"${line%%[![:space:]]*}"}"
        [ -z "$line" ] && continue
        case "$line" in \#*) continue ;; esac
        line="$(printf '%s' "$line" | sed -E 's/^([-*+][[:space:]]+|[0-9]+[.)][[:space:]]+)//')"
        spoken="$(cc_tts_speakable "$line")"
        [ -z "$spoken" ] && continue
        sentence="$(printf '%s' "$spoken" | sed -E 's/([.!?])[[:space:]].*/\1/')"
        printf '%s' "$sentence" | awk '{
            if (NF > 15) { out=""; for (i=1;i<=15;i++) out=out (i>1?" ":"") $i;
                           sub(/[,;:-]+$/, "", out); printf "%s.", out }
            else printf "%s", $0 }'
        break
    done
}

cc_tts_build_speech() {
    # cc_tts_build_speech <source> <state> <project> [override_text]
    local source="$1" state="$2" project="$3" override_text="${4:-}"
    local text tpl max_chars prefix prefix_enabled include_project message_mode hook_json

    cc_tts_init_config
    max_chars="$(cc_tts_json .maxChars 120)"
    include_project="$(cc_tts_json .announce.includeProject true)"
    message_mode="$(cc_tts_json .announce.messageMode template)"
    # Only consult the legacy top-level .messageMode when announce.messageMode
    # is unset/default — a configured 'hook' must survive. (The old condition
    # was inverted and silently reset 'hook' back to 'template'.)
    [ "$message_mode" != template ] || message_mode="$(cc_tts_json .messageMode template)"

    if [ "$include_project" != true ]; then
        project=""
    fi

    prefix_enabled="$(cc_tts_json ".sources.${source}.prefixEnabled" true)"
    prefix="$(cc_tts_json ".sources.${source}.prefix" "$source")"

    if [ -n "$override_text" ]; then
        text="$override_text"
    elif [ "$message_mode" = hook ] && [ -n "${CC_TTS_HOOK_JSON:-}" ]; then
        hook_json="${CC_TTS_HOOK_JSON}"
        text="$(cc_tts_assistant_text "$hook_json" transcript)"
        [ -z "${text:-}" ] && message_mode=template
    fi

    # `self`: the agent writes its own announcement. Applied ONLY to the "done"
    # event, exactly as ttsd/summarize.py:84-99 does — question/permission/error
    # keep their templates, because a marker written for "I finished" is the
    # wrong thing to say when the agent is asking you something.
    #
    # The mode is read from .summarize.mode, which config.json.tmpl already
    # renders on every platform, so this needs no new key.
    if [ -z "$override_text" ] && [ "$state" = waiting ] \
       && [ "$(cc_tts_json .summarize.mode template)" = self ] \
       && [ -n "${CC_TTS_HOOK_JSON:-}" ]; then
        local final_text self_line
        final_text="$(cc_tts_assistant_text "${CC_TTS_HOOK_JSON}" direct)"
        if [ -n "$final_text" ]; then
            self_line="$(cc_tts_self_summary "$final_text")"
            if [ -n "$self_line" ]; then
                text="${project:+$project} finished. $self_line"
                text="${text# }"
                message_mode=self
            fi
        fi
    fi

    if [ "$message_mode" = template ] || [ -z "${text:-}" ]; then
        tpl="$(cc_tts_json ".announce.templates.$state" "")"
        [ -z "$tpl" ] && tpl="$(cc_tts_json ".templates.$state" "")"
        text="${tpl//\{project\}/$project}"
    fi

    # Never speak the marker itself. In hook mode the raw final message is the
    # speech text, so a <!-- speak: … --> comment would otherwise be read out.
    case "$text" in *'<!--'*) text="$(cc_tts_strip_markers "$text")" ;; esac

    text="${text//$'\n'/ }"
    text="${text//$'\r'/ }"
    text="${text#"${text%%[![:space:]]*}"}"
    text="${text%"${text##*[![:space:]]}"}"

    if [ "$source" != test ] && [ "$prefix_enabled" = true ] && [ -n "$prefix" ]; then
        case "$text" in
            "$prefix."*|"$prefix "*) ;;
            *) text="$prefix. $text" ;;
        esac
    fi

    [ "${#text}" -gt "$max_chars" ] && text="${text:0:max_chars}"
    printf '%s' "$text"
}

cc_tts_parse_input_state() {
    # Parse hook stdin JSON -> state + optional override text. Sets CC_TTS_PARSED_STATE / CC_TTS_PARSED_OVERRIDE.
    local input="${1:-}" event="${2:-}"
    CC_TTS_PARSED_STATE=""
    CC_TTS_PARSED_OVERRIDE=""

    case "$event" in
        question)
            CC_TTS_PARSED_STATE=question
            if command -v jq >/dev/null 2>&1 && [ -n "$input" ]; then
                CC_TTS_PARSED_OVERRIDE="$(printf '%s' "$input" | jq -r '
                    .message // empty,
                    (.tool_input.questions[0].question // empty),
                    (.tool_input.questions[0].header // empty),
                    (.tool_input.prompt // empty)
                ' 2>/dev/null | head -1)"
                [ "$CC_TTS_PARSED_OVERRIDE" = null ] && CC_TTS_PARSED_OVERRIDE=""
            fi
            ;;
        permission)
            CC_TTS_PARSED_STATE=permission
            if command -v jq >/dev/null 2>&1 && [ -n "$input" ]; then
                CC_TTS_PARSED_OVERRIDE="$(printf '%s' "$input" | jq -r '
                    .tool_name // empty,
                    .message // empty
                ' 2>/dev/null | head -1)"
                [ "$CC_TTS_PARSED_OVERRIDE" = null ] && CC_TTS_PARSED_OVERRIDE=""
            fi
            ;;
        notification)
            CC_TTS_PARSED_STATE=question
            if command -v jq >/dev/null 2>&1 && [ -n "$input" ]; then
                CC_TTS_PARSED_OVERRIDE="$(printf '%s' "$input" | jq -r '.message // empty' 2>/dev/null)"
                [ "$CC_TTS_PARSED_OVERRIDE" = null ] && CC_TTS_PARSED_OVERRIDE=""
            fi
            ;;
        cursor_question)
            CC_TTS_PARSED_STATE=question
            if command -v jq >/dev/null 2>&1 && [ -n "$input" ]; then
                CC_TTS_PARSED_OVERRIDE="$(printf '%s' "$input" | jq -r '
                    (.tool_input.questions[0].prompt // empty),
                    (.tool_input.questions[0].question // empty),
                    (.tool_input.questions[0].header // empty)
                ' 2>/dev/null | head -1)"
                [ "$CC_TTS_PARSED_OVERRIDE" = null ] && CC_TTS_PARSED_OVERRIDE=""
            fi
            ;;
    esac
}

cc_tts_wsl_win_path() {
    local p="$1"
    if command -v wslpath >/dev/null 2>&1; then
        wslpath -w "$p" 2>/dev/null || printf '%s' "$p"
    else
        printf '%s' "$p"
    fi
}

cc_tts_temp_media() {
    local ext="${1:-mp3}"
    if [ -d /mnt/c/Users ] && command -v cmd.exe >/dev/null 2>&1; then
        local winuser
        winuser="$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n')"
        if [ -n "$winuser" ] && [ -d "/mnt/c/Users/$winuser/AppData/Local/Temp" ]; then
            printf '/mnt/c/Users/%s/AppData/Local/Temp/cc-tts-%s.%s' "$winuser" "$$" "$ext"
            return
        fi
    fi
    mktemp "${TMPDIR:-/tmp}/cc-tts.XXXXXX.${ext}" 2>/dev/null || echo "/tmp/cc-tts-$$.${ext}"
}

cc_tts_synth_kokoro() {
    local text="$1" out="$2"
    local url model voice speed fmt timeout payload
    url="$(cc_tts_json .kokoro.url 'http://127.0.0.1:8880')"
    # The docker image answers to the literal "kokoro"; mlx-audio -- the same
    # model running natively on Apple Silicon, same wire protocol -- wants the
    # HuggingFace repo id and 400s on anything else. Being configurable is the
    # whole difference between the two, so it must not be a literal here.
    model="$(cc_tts_json .kokoro.model kokoro)"
    voice="$(cc_tts_json .kokoro.voice am_adam)"
    speed="$(cc_tts_effective_kokoro_speed)"
    fmt="$(cc_tts_json .kokoro.format mp3)"
    timeout="$(cc_tts_json .kokoro.timeoutSec 15)"
    if command -v jq >/dev/null 2>&1; then
        payload="$(jq -n --arg t "$text" --arg m "$model" --arg v "$voice" --arg f "$fmt" --argjson s "$speed" \
            '{model:$m,input:$t,voice:$v,response_format:$f,speed:$s}')"
    else
        payload="$(python3 - "$text" "$voice" "$fmt" "$speed" "$model" <<'PY'
import json, sys
print(json.dumps({"model":sys.argv[5],"input":sys.argv[1],"voice":sys.argv[2],
                  "response_format":sys.argv[3],"speed":float(sys.argv[4])}))
PY
)"
    fi
    curl -sf --max-time "$timeout" \
        -H 'Content-Type: application/json' \
        -d "$payload" \
        "${url%/}/v1/audio/speech" -o "$out"
}

cc_tts_synth_chatterbox() {
    local text="$1" out="$2"
    local url voice energy cfg temp timeout exag payload
    url="$(cc_tts_json .chatterbox.url 'http://127.0.0.1:8881')"
    voice="$(cc_tts_json .chatterbox.voice adam)"
    energy="$(cc_tts_effective_chatterbox_energy)"
    cfg="$(cc_tts_json .chatterbox.cfgWeight 0.5)"
    temp="$(cc_tts_json .chatterbox.temperature 0.6)"
    timeout="$(cc_tts_json .chatterbox.timeoutSec 60)"
    exag="$(awk -v e="$energy" 'BEGIN { printf "%.2f", 0.25 + e + 0 }')"
    if command -v jq >/dev/null 2>&1; then
        payload="$(jq -n --arg t "$text" --arg v "$voice" \
            --argjson ex "$exag" --argjson cw "$cfg" --argjson tp "$temp" \
            '{input:$t,voice:$v,exaggeration:$ex,cfg_weight:$cw,temperature:$tp}')"
    else
        payload="$(python3 - "$text" "$voice" "$exag" "$cfg" "$temp" <<'PY'
import json, sys
print(json.dumps({"input":sys.argv[1],"voice":sys.argv[2],
                  "exaggeration":float(sys.argv[3]),"cfg_weight":float(sys.argv[4]),
                  "temperature":float(sys.argv[5])}))
PY
)"
    fi
    curl -sf --max-time "$timeout" \
        -H 'Content-Type: application/json' \
        -d "$payload" \
        "${url%/}/v1/audio/speech" -o "$out"
}

cc_tts_synth_edge() {
    local text="$1" out="$2" voice
    [ "$(cc_tts_json .edge.enabled true)" = true ] || return 1
    voice="$(cc_tts_json .edge.voice en-US-AndrewMultilingualNeural)"
    command -v edge-tts >/dev/null 2>&1 || return 1
    edge-tts --voice "$voice" --text "$text" --write-media "$out" >/dev/null 2>&1
}

# The macOS floor, mirroring Windows' SAPI rung (ttsd/synth.py). Without it the
# ladder ended in SILENCE: a Mac with Kokoro stopped and no edge-tts turns
# "voice notifications: on" into a switch that does nothing, and the worker runs
# detached with output discarded, so nothing anywhere says why.
#
# TRAP: `say -o out.mp3` exits 0 and writes a 16-byte junk file. say picks its
# format from the EXTENSION and only really writes AIFF, so synthesise to a
# .aiff and move it into place — afplay sniffs content, not the name.
cc_tts_synth_say() {
    # $3 is "chosen" when `say` is the configured engine rather than the floor.
    # It changes two things and neither is cosmetic: the daily notice explains an
    # UNEXPECTED fallback, so firing it for a deliberate choice is a nag about a
    # decision already made; and the log line should say which of the two
    # happened, because "why is it using say" is the question this rung creates.
    local text="$1" out="$2" chosen="${3:-}" tmp voice
    [ "$(uname -s 2>/dev/null)" = Darwin ] || return 1
    command -v say >/dev/null 2>&1 || return 1
    tmp="${out%.*}.say.aiff"

    # An unset voice means the SYSTEM voice, which is what the floor has always
    # used and what a user who never chose one expects. `say -v ""` is an error,
    # not a synonym, so the flag is omitted rather than passed empty.
    voice="$(cc_tts_json .say.voice "")"
    if [ -n "$voice" ]; then
        say -v "$voice" -o "$tmp" -- "$text" >/dev/null 2>&1 || { rm -f "$tmp"; return 1; }
    else
        say -o "$tmp" -- "$text" >/dev/null 2>&1 || { rm -f "$tmp"; return 1; }
    fi

    # Guard the junk-file case explicitly rather than trusting the exit code.
    [ -s "$tmp" ] && [ "$(wc -c < "$tmp" 2>/dev/null || echo 0)" -gt 1024 ] || {
        rm -f "$tmp"; return 1; }
    mv -f "$tmp" "$out" || { rm -f "$tmp"; return 1; }
    if [ "$chosen" = chosen ]; then
        cc_tts_log "synth say (engine: say${voice:+, voice $voice})"
    else
        cc_tts_log "synth say (fallback: no Kokoro/Chatterbox/edge-tts)"
        cc_tts_say_notice
    fi
    return 0
}

# Tell the user ONCE A DAY that the system voice is standing in, so a changed
# voice reads as "Kokoro is down", not "my config broke". Never fatal.
cc_tts_say_notice() {
    # The REASON goes in the file, not just a mark that it happened.
    #
    # This printed to stderr and nothing else, and cc-tts-notify.sh runs the
    # worker as `( _worker ) >/dev/null 2>&1 &` -- so the one line that explains
    # why the voice changed was written to a discarded stream, every time. The
    # symptom that produces is "my TTS is speaking in a different voice and I
    # cannot find out why", which is exactly the question the notice answers.
    #
    # `tstack config tts` reads this back. Still once a day: the point is to
    # explain a change, not to narrate every announcement.
    local stamp dir
    dir="${TMPDIR:-/tmp}"
    stamp="${dir%/}/cc-tts-say-notice.$(date +%Y%m%d)"
    [ -e "$stamp" ] && return 0
    printf 'used the macOS system voice at %s: Kokoro/Chatterbox/edge-tts were all unavailable.\n' \
        "$(date '+%H:%M')" > "$stamp" 2>/dev/null || return 0
    printf 'cc-tts: using the macOS system voice - Kokoro/Chatterbox/edge-tts were unavailable.\n' >&2
    return 0
}

cc_tts_synth() {
    local text="$1" out="$2" engine ok=1
    engine="$(cc_tts_json .engine kokoro)"
    case "$engine" in
        kokoro)     cc_tts_synth_kokoro "$text" "$out" && ok=0 ;;
        chatterbox) cc_tts_synth_chatterbox "$text" "$out" && ok=0 ;;
        # Chosen, so tried FIRST -- and it still falls through to edge and to
        # itself-as-floor below if `say` is somehow unavailable, which keeps the
        # "on never means silence" property that the floor exists for.
        say)        cc_tts_synth_say "$text" "$out" chosen && ok=0 ;;
        auto)
            cc_tts_synth_kokoro "$text" "$out" && ok=0
            [ "$ok" -ne 0 ] && cc_tts_synth_chatterbox "$text" "$out" && ok=0
            ;;
    esac
    [ "$ok" -ne 0 ] && cc_tts_synth_edge "$text" "$out" && ok=0
    # Last rung. Offline, always present on macOS, and the reason "on" can no
    # longer mean silence.
    [ "$ok" -ne 0 ] && cc_tts_synth_say "$text" "$out" && ok=0
    return "$ok"
}

cc_tts_win_play_ps1() {
    local winuser=""
    if command -v cmd.exe >/dev/null 2>&1; then
        winuser="$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n')"
    fi
    if [ -n "$winuser" ] && [ -f "/mnt/c/Users/$winuser/.claude/hooks/cc-tts-play.ps1" ]; then
        echo "/mnt/c/Users/$winuser/.claude/hooks/cc-tts-play.ps1"
    elif [ -f "${HOME}/.claude/hooks/cc-tts-play.ps1" ]; then
        echo "${HOME}/.claude/hooks/cc-tts-play.ps1"
    elif [ -n "$winuser" ] && [ -f "/mnt/c/Users/$winuser/.claude/hooks/cc-speak-play.ps1" ]; then
        echo "/mnt/c/Users/$winuser/.claude/hooks/cc-speak-play.ps1"
    fi
}

cc_tts_find_ffplay_win() {
    if command -v cmd.exe >/dev/null 2>&1; then
        cmd.exe /c 'where ffplay 2>nul' 2>/dev/null | tr -d '\r' | head -1
    fi
}

cc_tts_play_ffplay_windows() {
    local path="$1" media_win ffplay_win ffplay_bin
    media_win="$(cc_tts_wsl_win_path "$path")"
    ffplay_win="$(cc_tts_find_ffplay_win)"
    [ -n "$ffplay_win" ] || return 1

    if command -v wslpath >/dev/null 2>&1; then
        ffplay_bin="$(wslpath "$ffplay_win" 2>/dev/null || true)"
    fi
    if [ -n "$ffplay_bin" ] && [ -x "$ffplay_bin" ]; then
        cc_tts_log "play $ffplay_bin (media $path)"
        "$ffplay_bin" -nodisp -autoexit -hide_banner -loglevel error "$media_win" && return 0
        cc_tts_log "play retry with WSL path"
        "$ffplay_bin" -nodisp -autoexit -hide_banner -loglevel error "$path" && return 0
    fi

    local winuser tmp_win
    winuser="$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n')"
    tmp_win="C:\\Users\\${winuser}\\AppData\\Local\\Temp"
    cc_tts_log "play cmd cd $tmp_win"
    cmd.exe /c "cd /d $tmp_win && \"$ffplay_win\" -nodisp -autoexit -hide_banner -loglevel error \"$media_win\""
}

cc_tts_play() {
    local path="$1" player
    [ -f "$path" ] && [ -s "$path" ] || return 1
    player="$(cc_tts_json .player auto)"

    if [ "$player" = windows ] || { [ "$player" = auto ] && [ -d /mnt/c/Users ]; }; then
        if cc_tts_play_ffplay_windows "$path"; then
            return 0
        fi
        if command -v ffplay.exe >/dev/null 2>&1; then
            cc_tts_log "play ffplay.exe $(cc_tts_wsl_win_path "$path")"
            ffplay.exe -nodisp -autoexit -hide_banner -loglevel quiet "$(cc_tts_wsl_win_path "$path")" && return 0
        fi
        local play_ps1
        play_ps1="$(cc_tts_win_play_ps1)"
        if [ -n "$play_ps1" ] && command -v pwsh.exe >/dev/null 2>&1; then
            cc_tts_log "play pwsh $(cc_tts_wsl_win_path "$play_ps1")"
            pwsh.exe -NoLogo -NonInteractive -ExecutionPolicy Bypass \
                -File "$(cc_tts_wsl_win_path "$play_ps1")" \
                -MediaPath "$(cc_tts_wsl_win_path "$path")" && return 0
        fi
        if [ "$player" = auto ] && [ -d /mnt/c/Users ]; then
            cc_tts_log "WSL: install Windows ffplay (winget install Gyan.FFmpeg)"
        fi
    fi

    if [ "$(uname -s 2>/dev/null)" = Darwin ] && command -v afplay >/dev/null 2>&1; then
        cc_tts_log "play afplay $path"
        afplay "$path" && return 0
    fi
    if command -v ffplay >/dev/null 2>&1; then
        cc_tts_log "play ffplay $path"
        ffplay -nodisp -autoexit -hide_banner -loglevel quiet "$path" && return 0
    fi
    return 1
}

# ── ttsd daemon senders ─────────────────────────────────────────────────────────
# The daemon is a native Windows tray process (bootstrap/tts-daemon), so only
# WSL (with /mnt/c) can reach it from the POSIX side; native Linux/macOS always
# keep the direct cc-tts-notify path. Callers must fall back to that path when
# cc_tts_daemon_send fails — daemon dead means "speak the old way", never silence.

CC_TTS_DAEMON_CACHE="${HOME}/.cache/terminal-stack/cc-tts.daemonhost"

cc_tts_daemon_ready() {
    [ -d /mnt/c/Users ] || return 1
    [ "$(cc_tts_json .daemon.enabled false)" = true ] || return 1
    command -v curl >/dev/null 2>&1 || return 1
    command -v jq >/dev/null 2>&1 || command -v python3 >/dev/null 2>&1 || return 1
}

cc_tts_daemon_token() {
    # Shared secret required by the daemon's non-loopback (WSL-facing) listener.
    local winuser
    winuser="$(cmd.exe /c 'echo %USERNAME%' 2>/dev/null | tr -d '\r\n')"
    [ -n "$winuser" ] || return 1
    cat "/mnt/c/Users/${winuser}/AppData/Local/terminal-stack/tts-daemon/state/token" 2>/dev/null
}

cc_tts_daemon_probe() {
    local host="$1" port="$2" token="$3"
    if [ -n "$token" ]; then
        curl -sf --connect-timeout 0.25 --max-time 1 -H "X-TS-Token: $token" \
            "http://${host}:${port}/healthz" >/dev/null 2>&1
    else
        curl -sf --connect-timeout 0.25 --max-time 1 \
            "http://${host}:${port}/healthz" >/dev/null 2>&1
    fi
}

cc_tts_daemon_host() {
    # Prints "host token" (token empty on loopback). Ladder: hostOverride →
    # 127.0.0.1 (mirrored networking) → default gateway (NAT) → resolv.conf
    # nameserver. The winner is cached 60s; send failures clear the cache.
    local port="$1" host token="" cached age
    mkdir -p "$(dirname "$CC_TTS_DAEMON_CACHE")" 2>/dev/null || true
    if [ -f "$CC_TTS_DAEMON_CACHE" ]; then
        age=$(( $(date +%s) - $(stat -c %Y "$CC_TTS_DAEMON_CACHE" 2>/dev/null || echo 0) ))
        if [ "$age" -ge 0 ] && [ "$age" -lt 60 ]; then
            cat "$CC_TTS_DAEMON_CACHE"
            return 0
        fi
    fi
    local candidates="" override gw ns
    override="$(cc_tts_json .daemon.hostOverride '')"
    [ -n "$override" ] && candidates="$override"
    candidates="$candidates 127.0.0.1"
    gw="$(ip route show default 2>/dev/null | awk '{print $3; exit}')"
    [ -n "$gw" ] && candidates="$candidates $gw"
    ns="$(awk '/^nameserver/ {print $2; exit}' /etc/resolv.conf 2>/dev/null)"
    [ -n "$ns" ] && [ "$ns" != "$gw" ] && candidates="$candidates $ns"
    for host in $candidates; do
        token=""
        [ "$host" != 127.0.0.1 ] && token="$(cc_tts_daemon_token || true)"
        if cc_tts_daemon_probe "$host" "$port" "$token"; then
            printf '%s %s' "$host" "$token" > "$CC_TTS_DAEMON_CACHE" 2>/dev/null || true
            printf '%s %s' "$host" "$token"
            return 0
        fi
    done
    return 1
}

cc_tts_daemon_send() {
    # cc_tts_daemon_send <source> <event> <state> <hook-json> [override]
    # Returns 0 only when the daemon accepted the event.
    local source="$1" event="$2" state="$3" input="$4" override="${5:-}"
    local port hostline host token payload
    # CC_TTS_DAEMON_PORT_OVERRIDE: test hook (cc-tts-test --daemon-fallback)
    # forces an unreachable port to prove the direct-speak fallback fires.
    port="${CC_TTS_DAEMON_PORT_OVERRIDE:-$(cc_tts_json .daemon.port 8890)}"
    hostline="$(cc_tts_daemon_host "$port")" || return 1
    host="${hostline%% *}"
    token="${hostline#* }"
    [ "$token" = "$hostline" ] && token=""
    local pdir="${CLAUDE_PROJECT_DIR:-${CURSOR_PROJECT_DIR:-$PWD}}"
    local fid="pid$PPID"
    if command -v jq >/dev/null 2>&1; then
        payload="$(jq -cn \
            --arg source "$source" --arg event "$event" --arg state "$state" \
            --arg pdir "$pdir" --arg cwd "$PWD" --arg pane "${WEZTERM_PANE:-}" \
            --arg override "$override" --arg fid "$fid" --arg input "$input" '
            ($input | (try fromjson catch {})) as $h |
            {v: 1, source: $source, host: "wsl", event: $event, state: $state,
             session_key: ($source + ":" + (($h.session_id // $h.conversation_id // $fid) | tostring)),
             project: {dir: $pdir, name: ($pdir | split("/") | last)},
             cwd: $cwd,
             transcript_path: ($h.transcript_path // ""),
             override: $override,
             message: {
               text: ($h.last_assistant_message // $h.text // ""),
               error_type: ($h.error_type // ""),
               notification_type: ($h.notification_type // ""),
               tool_name: ($h.tool_name // ""),
               stop_status: ($h.status // "")},
             wezterm: {pane: $pane},
             ts: now}' 2>/dev/null)"
    else
        payload="$(CC_TTS_DAEMON_INPUT="$input" python3 - "$source" "$event" "$state" \
            "$pdir" "$PWD" "${WEZTERM_PANE:-}" "$override" "$fid" <<'PY' 2>/dev/null
import json, os, sys, time
source, event, state, pdir, cwd, pane, override, fid = sys.argv[1:9]
try:
    h = json.loads(os.environ.get("CC_TTS_DAEMON_INPUT") or "{}")
    if not isinstance(h, dict):
        h = {}
except ValueError:
    h = {}
sid = h.get("session_id") or h.get("conversation_id") or fid
print(json.dumps({
    "v": 1, "source": source, "host": "wsl", "event": event, "state": state,
    "session_key": f"{source}:{sid}",
    "project": {"dir": pdir, "name": pdir.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]},
    "cwd": cwd,
    "transcript_path": h.get("transcript_path") or "",
    "override": override,
    "message": {
        "text": h.get("last_assistant_message") or h.get("text") or "",
        "error_type": h.get("error_type") or "",
        "notification_type": h.get("notification_type") or "",
        "tool_name": h.get("tool_name") or "",
        "stop_status": h.get("status") or ""},
    "wezterm": {"pane": pane},
    "ts": time.time()}))
PY
)"
    fi
    [ -n "$payload" ] || return 1
    local rc=0
    if [ -n "$token" ]; then
        curl -sf --connect-timeout 0.25 --max-time 2 -H "X-TS-Token: $token" \
            -H 'Content-Type: application/json' -d "$payload" \
            "http://${host}:${port}/v1/event" >/dev/null 2>&1 || rc=1
    else
        curl -sf --connect-timeout 0.25 --max-time 2 \
            -H 'Content-Type: application/json' -d "$payload" \
            "http://${host}:${port}/v1/event" >/dev/null 2>&1 || rc=1
    fi
    [ "$rc" -ne 0 ] && rm -f "$CC_TTS_DAEMON_CACHE" 2>/dev/null
    return "$rc"
}
