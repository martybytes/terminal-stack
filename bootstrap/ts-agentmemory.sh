#!/usr/bin/env bash
# ts-agentmemory.sh — wire Claude Code, Codex and Cursor to a local agentmemory
# server on macOS and Linux: tagged URLs, retrieval on by default, the deployment
# hook-script edits, and the duplicate-invocation guard. Previews by default.
#
# Usage: ts-agentmemory.sh [--apply] [--undo] [--check] [--host claude|codex|cursor]
#
# POSIX twin of ts-agentmemory.ps1. Runs from ts-agents.sh's agentmemory verb, so
# a plugin upgrade that reverts the hook-script edits is repaired on the next
# `ts-update`. docker-local/agentmemory/check-capture.sh probes for this exact
# path, which is why the name is not negotiable.
#
# Without this, macOS and Linux serve and search but never capture — silently,
# because every vendor hook does fetch(...).catch(() => {}) and exits 0.
#
# The HMAC secret is never read or written here. The plugin's own .mcp.json owns
# it; the hook edits only *re-read* a stale one from the 0600 cache on a 401.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_agentmemory.sh
. "$ROOT/_agentmemory.sh"
# shellcheck source=_merge_json_settings.sh
. "$ROOT/_merge_json_settings.sh"

APPLY=0; UNDO=0; CHECK=0; HOSTS=""
while [ $# -gt 0 ]; do
    case "$1" in
        --apply)  APPLY=1 ;;
        --undo)   UNDO=1 ;;
        --check)  CHECK=1 ;;
        --host)   shift; HOSTS="${HOSTS} ${1:-}" ;;
        -h|--help)
            sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *) echo "ts-agentmemory: unknown option '$1'" >&2; exit 2 ;;
    esac
    shift
done
[ -n "$HOSTS" ] || HOSTS="$AM_HOSTS"
for h in $HOSTS; do
    case "$h" in claude|codex|cursor) ;; *) echo "ts-agentmemory: unknown host '$h'" >&2; exit 2 ;; esac
done

EXECUTE=$APPLY
if [ "$CHECK" = 1 ]; then MODE=CHECK
elif [ "$UNDO" = 1 ] && [ "$APPLY" = 1 ]; then MODE=UNDO
elif [ "$APPLY" = 1 ]; then MODE=APPLY
else MODE=PREVIEW; fi

STAMP="$(date +%Y%m%d)"
PROBLEMS=0

_section() { printf '\n=== %s ===\n' "$1"; }
_step()    { if [ "$EXECUTE" = 1 ]; then printf '[DO]   %s\n' "$1"; else printf '[would] %s\n' "$1"; fi; }
_info()    { printf '       %s\n' "$1"; }
_warn()    { printf '  !    %s\n' "$1"; }
_pass()    { printf '  OK   %s\n' "$1"; }
_fail()    { PROBLEMS=$((PROBLEMS + 1)); _warn "$1"; }

if [ "$CHECK" != 1 ]; then
    printf 'ts-agentmemory  mode=%s\n' "$MODE"
    [ "$EXECUTE" = 1 ] || printf '(preview only - add --apply to write, or --undo --apply to remove)\n'
fi

# ---- shared helpers -----------------------------------------------------------

am_backup_file() {
    local p="$1" bak
    [ -f "$p" ] || return 0
    bak="$(ts_json_backup_path "$p" "$STAMP")"
    cp -p -- "$p" "$bak" && _info "backup $bak"
}

# Highest-versioned directory under a plugin cache root, or empty.
# Sorted with sort -V, not lexically: 0.9.29 must beat 0.9.9.
am_plugin_version_dir() {
    local root="$1" d
    [ -d "$root" ] || return 0
    d="$(ls -1 "$root" 2>/dev/null | sort -V | tail -1)"
    [ -n "$d" ] && [ -d "$root/$d" ] && printf '%s\n' "$root/$d"
}

# Resolve script paths inside the selected plugin version, refusing to escape it.
# Uses `cd … && pwd -P` rather than readlink -f / realpath, neither of which is
# portable to older macOS.
am_script_paths() {
    local vroot="$1" subdir="$2"; shift 2
    local real p n
    real="$(cd "$vroot" 2>/dev/null && pwd -P)" || return 0
    for n in "$@"; do
        p="$vroot/$subdir/$n"
        [ -f "$p" ] || continue
        local pdir
        pdir="$(cd "$(dirname "$p")" && pwd -P)"
        case "$pdir/" in
            "$real"/*) printf '%s\n' "$pdir/$(basename "$p")" ;;
            *) echo "Refusing to touch a script outside the plugin version: $p" >&2; return 1 ;;
        esac
    done
}

AM_CODEX_SCRIPTS="session-start.mjs prompt-submit.mjs pre-tool-use.mjs post-tool-use.mjs pre-compact.mjs stop.mjs"
AM_CURSOR_SCRIPTS="session-start.mjs prompt-submit.mjs pre-tool-use.mjs post-tool-use.mjs post-tool-failure.mjs stop.mjs session-end.mjs"
AM_BACKUP_SUFFIX=".agent007memory-original"

# POSIX hook command. The .ps1 emits a cmd.exe `set X=…&&` chain here; that
# written into a hooks file on a Mac fails SILENTLY, which is precisely the
# failure this wiring exists to prevent. Both variables are inlined rather than
# inherited: an exported variable only reaches processes started after it was
# set, so long-running shells and desktop apps launched hooks without it and
# every retrieval returned early.
am_hook_command() {
    printf 'AGENTMEMORY_URL=%s AGENTMEMORY_INJECT_CONTEXT=true node "%s"\n' \
        "$(am_agent_url "$1")" "$2"
}

am_owned_command() {
    case "$1" in *hooks/agentmemory/*) return 0 ;; *) return 1 ;; esac
}

# Render engine output through this script's own reporters.
am_run_engine() {
    local mode="$1"; shift
    local rc=0 line kind text
    while IFS=$'\t' read -r kind text; do
        case "$kind" in
            STEP) _step "$text" ;;
            INFO) _info "$text" ;;
            MISS) _fail "$text" ;;
            ERR)  _fail "$text" ;;
        esac
    done < <(am_engine "$mode" "$@" || echo "ERR	engine failed")
    return $rc
}

# Copy the vendor scripts to a stable location and apply the edits to the copy,
# so a plugin upgrade cannot silently revert deployed behaviour under a live agent.
am_sync_stable() {
    local src_dir="$1" dst_dir="$2" edits_file="$3"; shift 3
    local name
    if [ ! -d "$dst_dir" ]; then
        _step "create $dst_dir"
        [ "$EXECUTE" = 1 ] && mkdir -p "$dst_dir"
    fi
    for name in "$@"; do
        if [ ! -f "$src_dir/$name" ]; then _warn "vendor script missing: $name"; continue; fi
        if [ "$EXECUTE" != 1 ]; then _step "install $name"; continue; fi
        cp -p -- "$src_dir/$name" "$dst_dir/$name"
        am_run_engine apply "$edits_file" "$AM_BACKUP_SUFFIX" "$dst_dir/$name" >/dev/null
        rm -f -- "$dst_dir/$name$AM_BACKUP_SUFFIX"
        _step "install $name"
    done
}

# ---- Claude Code --------------------------------------------------------------

am_claude() {
    local root ver
    root="$HOME/.claude"
    ver="$(am_plugin_version_dir "$root/plugins/cache/agentmemory/agentmemory")"
    # Gated on the plugin cache, never on server reachability, so the wiring
    # survives the container being stopped.
    [ -n "$ver" ] || { _info 'Claude Code: agentmemory plugin not installed, skipped'; return 0; }

    _section 'Claude Code'
    _info "plugin $(basename "$ver")"

    # settings.json: only the two env keys. statusLine/hooks/theme belong to this
    # repo's own splice and everything else belongs to Claude Code, so this
    # splices the `env` value textually and leaves every other byte alone.
    local settings="$root/settings.json" envjson
    if [ ! -f "$settings" ]; then
        _warn "$settings does not exist yet; start Claude Code once, then re-run"
    else
        envjson="$(python3 - "$settings" "$(am_agent_url claude)" "$UNDO" <<'PY'
import json, sys
path, url, undo = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
try:
    text = open(path, encoding="utf-8").read()
    # tolerate JSONC the same way the splice does
    import re
    live = json.loads(re.sub(r"(?m)^\s*//.*$", "", text))
except Exception:
    print("PARSEFAIL"); raise SystemExit(0)
env = live.get("env") if isinstance(live.get("env"), dict) else {}
before = dict(env)
want = {"AGENTMEMORY_URL": url, "AGENTMEMORY_INJECT_CONTEXT": "true"}
for k, v in want.items():
    if undo: env.pop(k, None)
    else: env[k] = v
print("SAME" if env == before else "DIFF")
print(json.dumps(env, indent=2))
PY
)"
        local verdict; verdict="$(printf '%s\n' "$envjson" | head -1)"
        local body;    body="$(printf '%s\n' "$envjson" | tail -n +2)"
        if [ "$verdict" = PARSEFAIL ]; then
            _fail "could not parse $settings"
        elif [ "$verdict" = SAME ]; then
            if [ "$CHECK" = 1 ]; then _pass 'Claude settings env is correct'; else _info 'settings env already correct'; fi
        elif [ "$CHECK" = 1 ]; then
            _fail 'Claude settings env is missing AGENTMEMORY_URL / AGENTMEMORY_INJECT_CONTEXT'
        else
            _step "update env in $settings"
            if [ "$EXECUTE" = 1 ]; then
                am_backup_file "$settings"
                ts_merge_json_key "$settings" env "$body" ts-agentmemory >/dev/null \
                    || _fail "splice failed for $settings"
            fi
        fi
    fi

    local edits_file paths
    edits_file="$(mktemp)"; am_build_edits claude; am_write_edits "$edits_file"
    paths="$(am_script_paths "$ver" scripts session-start.mjs prompt-submit.mjs pre-tool-use.mjs)"
    [ -n "$paths" ] || { _warn 'Claude: no hook scripts found'; rm -f "$edits_file"; return 0; }

    if [ "$CHECK" = 1 ]; then
        local before=$PROBLEMS
        # shellcheck disable=SC2086
        am_run_engine check "$edits_file" "$AM_BACKUP_SUFFIX" $paths
        [ "$PROBLEMS" = "$before" ] && _pass 'Claude hook edits present'
    else
        local m=preview
        [ "$EXECUTE" = 1 ] && m=apply
        [ "$UNDO" = 1 ] && { m=undo-preview; [ "$EXECUTE" = 1 ] && m=undo-apply; }
        # shellcheck disable=SC2086
        am_run_engine "$m" "$edits_file" "$AM_BACKUP_SUFFIX" $paths
    fi
    rm -f "$edits_file"
}

# ---- Codex --------------------------------------------------------------------

am_codex() {
    local root ver edits_file plugin_paths stable_dir
    root="${CODEX_HOME:-$HOME/.codex}"
    ver="$(am_plugin_version_dir "$root/plugins/cache/agentmemory/agentmemory")"
    [ -n "$ver" ] || { _info 'Codex: agentmemory plugin not installed, skipped'; return 0; }

    _section 'Codex'
    _info "plugin $(basename "$ver")"
    edits_file="$(mktemp)"; am_build_edits codex; am_write_edits "$edits_file"

    # Two registrations are live: hooks.json (Desktop) and the plugin's own
    # hooks.codex.json (the CLI). Both are patched, and the duplicate invocation
    # is dropped by the guard the edits install. Codex exposes no hooks-only
    # toggle and silently ignores unknown plugin config keys, so removing one is
    # not an option without losing Desktop or CLI capture.
    # shellcheck disable=SC2086
    plugin_paths="$(am_script_paths "$ver" scripts $AM_CODEX_SCRIPTS)"
    stable_dir="$root/hooks/agentmemory/scripts"

    if [ "$CHECK" = 1 ]; then
        local before=$PROBLEMS stable_paths="" n
        for n in $AM_CODEX_SCRIPTS; do [ -f "$stable_dir/$n" ] && stable_paths="$stable_paths $stable_dir/$n"; done
        if [ -z "$plugin_paths" ]; then _warn 'Codex plugin cache (CLI): no scripts found'
        else
            before=$PROBLEMS
            # shellcheck disable=SC2086
            am_run_engine check "$edits_file" "$AM_BACKUP_SUFFIX" $plugin_paths
            [ "$PROBLEMS" = "$before" ] && _pass 'Codex plugin cache (CLI): edits present'
        fi
        if [ -z "$stable_paths" ]; then _warn 'Codex stable copies (Desktop): no scripts found'
        else
            before=$PROBLEMS
            # shellcheck disable=SC2086
            am_run_engine check "$edits_file" "$AM_BACKUP_SUFFIX" $stable_paths
            [ "$PROBLEMS" = "$before" ] && _pass 'Codex stable copies (Desktop): edits present'
        fi
        rm -f "$edits_file"; return 0
    fi

    local m=preview
    [ "$EXECUTE" = 1 ] && m=apply
    [ "$UNDO" = 1 ] && { m=undo-preview; [ "$EXECUTE" = 1 ] && m=undo-apply; }
    # shellcheck disable=SC2086
    [ -n "$plugin_paths" ] && am_run_engine "$m" "$edits_file" "$AM_BACKUP_SUFFIX" $plugin_paths

    if [ "$UNDO" = 1 ]; then
        if [ -d "$root/hooks/agentmemory" ]; then
            _step "remove $root/hooks/agentmemory"
            [ "$EXECUTE" = 1 ] && rm -rf -- "$root/hooks/agentmemory"
        fi
    else
        # shellcheck disable=SC2086
        am_sync_stable "$ver/scripts" "$stable_dir" "$edits_file" $AM_CODEX_SCRIPTS
    fi

    # hooks.json: own only our own entries, leave anyone else's alone. No
    # PreToolUse matcher — the script decides what it can serve, and the vendor
    # allow-list excluded the tool Codex emits most (Bash), so a matcher here
    # would only hide tools from it.
    am_write_hooks_json "$root/hooks.json" codex "$stable_dir"
    rm -f "$edits_file"
}

# ---- Cursor -------------------------------------------------------------------

am_cursor() {
    local cursor_home src_ver dest_dir edits_file
    cursor_home="$HOME/.cursor"
    [ -d "$cursor_home" ] || { _info 'Cursor: not installed, skipped'; return 0; }
    # Cursor ships no agentmemory package, so its scripts are copied from the
    # Claude plugin cache — that cache is the only source for them, and it is why
    # the URL edit needs its claude-tagged alternative forms.
    src_ver="$(am_plugin_version_dir "$HOME/.claude/plugins/cache/agentmemory/agentmemory")"
    [ -n "$src_ver" ] || { _info 'Cursor: no agentmemory plugin cache to copy scripts from, skipped'; return 0; }

    _section 'Cursor'
    edits_file="$(mktemp)"; am_build_edits cursor; am_write_edits "$edits_file"
    dest_dir="$cursor_home/hooks/agentmemory"

    if [ "$CHECK" = 1 ]; then
        local dest_paths="" n before
        for n in $AM_CURSOR_SCRIPTS; do [ -f "$dest_dir/$n" ] && dest_paths="$dest_paths $dest_dir/$n"; done
        if [ -z "$dest_paths" ]; then _fail 'Cursor agentmemory hook scripts are not installed'
        else
            before=$PROBLEMS
            # shellcheck disable=SC2086
            am_run_engine check "$edits_file" "$AM_BACKUP_SUFFIX" $dest_paths
            [ "$PROBLEMS" = "$before" ] && _pass 'Cursor hook edits present'
        fi
        rm -f "$edits_file"; return 0
    fi

    if [ "$UNDO" = 1 ]; then
        if [ -d "$dest_dir" ]; then
            _step "remove $dest_dir"
            [ "$EXECUTE" = 1 ] && rm -rf -- "$dest_dir"
        fi
    else
        # shellcheck disable=SC2086
        am_sync_stable "$src_ver/scripts" "$dest_dir" "$edits_file" $AM_CURSOR_SCRIPTS
    fi

    am_write_mcp_json "$cursor_home/mcp.json"
    am_write_hooks_json "$cursor_home/hooks.json" cursor "$dest_dir"
    rm -f "$edits_file"
}

# ---- hooks.json / mcp.json ----------------------------------------------------

# Per-ENTRY ownership, not per-key: other tools share these event arrays. This
# repo's own TTS hooks live in Cursor's `stop` and `postToolUse` too, so only
# entries whose command points at */hooks/agentmemory/* may ever be touched.
# terminal-stack's sync owns the TTS ones separately.
am_write_hooks_json() {
    local path="$1" agent="$2" script_dir="$3" out
    out="$(python3 - "$path" "$agent" "$script_dir" "$(am_agent_url "$agent")" "$UNDO" <<'PY'
import json, os, sys

path, agent, script_dir, url, undo = sys.argv[1:6]
undo = undo == "1"

CODEX = [
    ("SessionStart",     "session-start.mjs", "agentmemory: loading session context"),
    ("UserPromptSubmit", "prompt-submit.mjs", "agentmemory: recalling relevant memories"),
    ("PreToolUse",       "pre-tool-use.mjs",  None),
    ("PostToolUse",      "post-tool-use.mjs", None),
    ("PreCompact",       "pre-compact.mjs",   None),
    ("Stop",             "stop.mjs",          None),
]
CURSOR = [
    ("sessionStart",       "session-start.mjs"),
    ("beforeSubmitPrompt", "prompt-submit.mjs"),
    ("preToolUse",         "pre-tool-use.mjs"),
    ("postToolUse",        "post-tool-use.mjs"),
    ("postToolUseFailure", "post-tool-failure.mjs"),
    ("stop",               "stop.mjs"),
    ("sessionEnd",         "session-end.mjs"),
]

def command(script):
    # POSIX prefix, NOT a cmd.exe `set X=…&&` chain: that fails silently here.
    return 'AGENTMEMORY_URL=%s AGENTMEMORY_INJECT_CONTEXT=true node "%s"' % (
        url, os.path.join(script_dir, script))

def ours(cmd):
    return "hooks/agentmemory/" in str(cmd)

try:
    cfg = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
except Exception as exc:
    sys.stderr.write("refusing to overwrite malformed JSON %s: %s\n" % (path, exc))
    raise SystemExit(2)
if not isinstance(cfg, dict):
    cfg = {}
hooks = cfg.get("hooks")
if not isinstance(hooks, dict):
    hooks = {}
    cfg["hooks"] = hooks
if agent == "cursor":
    cfg.setdefault("version", 1)

changed = []
if agent == "codex":
    for event, script, status in CODEX:
        groups = hooks.get(event) or []
        foreign = [g for g in groups
                   if not any(ours(h.get("command")) for h in (g.get("hooks") or []))]
        if undo:
            if len(foreign) != len(groups):
                changed.append(event)
                if foreign: hooks[event] = foreign
                else: hooks.pop(event, None)
            continue
        hook = {"type": "command", "command": command(script)}
        if status:
            hook["statusMessage"] = status
        want = foreign + [{"hooks": [hook]}]
        if want != groups:
            changed.append(event)
            hooks[event] = want
else:
    for event, script in CURSOR:
        entries = hooks.get(event) or []
        foreign = [e for e in entries if not ours(e.get("command"))]
        if undo:
            if len(foreign) != len(entries):
                changed.append(event)
                if foreign: hooks[event] = foreign
                else: hooks.pop(event, None)
            continue
        entry = {"command": command(script)}
        if event == "preToolUse":
            entry["matcher"] = "Shell|Read|Write|Grep"
        # ours LAST, matching what the previous installer produced, so re-running
        # either tool converges instead of reordering the file every time.
        want = foreign + [entry]
        if want != entries:
            changed.append(event)
            hooks[event] = want

if not changed:
    print("SAME")
    raise SystemExit(0)
print("DIFF " + ", ".join(changed))
print(json.dumps(cfg, indent=2))
PY
)" || { _fail "hooks.json: refused to write $path"; return 0; }

    local verdict; verdict="$(printf '%s\n' "$out" | head -1)"
    if [ "$verdict" = SAME ]; then _info 'hooks.json already correct'; return 0; fi
    local what="${verdict#DIFF }"
    if [ "$UNDO" = 1 ]; then _step "remove hooks.json: $what"; else _step "update hooks.json: $what"; fi
    if [ "$EXECUTE" = 1 ]; then
        am_backup_file "$path"
        mkdir -p "$(dirname "$path")"
        printf '%s\n' "$out" | tail -n +2 > "$path"
        if [ "$agent" = codex ]; then _info 'restart Codex Desktop to load the change'
        else _info 'restart Cursor to load the change'; fi
    fi
}

# mcp.json: own only the agentmemory server entry.
am_write_mcp_json() {
    local path="$1" out
    out="$(python3 - "$path" "$(am_agent_url cursor)" "$UNDO" <<'PY'
import json, os, sys
path, url, undo = sys.argv[1], sys.argv[2], sys.argv[3] == "1"
try:
    cfg = json.load(open(path, encoding="utf-8")) if os.path.isfile(path) else {}
except Exception as exc:
    sys.stderr.write("refusing to overwrite malformed JSON %s: %s\n" % (path, exc))
    raise SystemExit(2)
if not isinstance(cfg, dict):
    cfg = {}
servers = cfg.get("mcpServers")
if not isinstance(servers, dict):
    servers = {}
    cfg["mcpServers"] = servers
want = {
    "command": "npx",
    "args": ["-y", "@agentmemory/mcp"],
    # The secret is never written here; the value is a reference the client expands.
    "env": {"AGENTMEMORY_URL": url, "AGENTMEMORY_SECRET": "${env:AGENTMEMORY_SECRET}"},
}
have = servers.get("agentmemory")
if undo:
    if have is None:
        print("SAME"); raise SystemExit(0)
    servers.pop("agentmemory", None)
    print("DIFF remove agentmemory")
else:
    if have == want:
        print("SAME"); raise SystemExit(0)
    servers["agentmemory"] = want
    print("DIFF " + ("update" if have else "add") + " agentmemory")
print(json.dumps(cfg, indent=2))
PY
)" || { _fail "mcp.json: refused to write $path"; return 0; }

    local verdict; verdict="$(printf '%s\n' "$out" | head -1)"
    if [ "$verdict" = SAME ]; then _info 'mcp.json already correct'; return 0; fi
    _step "${verdict#DIFF } in $path"
    if [ "$EXECUTE" = 1 ]; then
        am_backup_file "$path"
        mkdir -p "$(dirname "$path")"
        printf '%s\n' "$out" | tail -n +2 > "$path"
    fi
}

# ---- run ----------------------------------------------------------------------

for h in $HOSTS; do
    case "$h" in
        claude) am_claude ;;
        codex)  am_codex ;;
        cursor) am_cursor ;;
    esac
done

if [ "$CHECK" = 1 ]; then
    [ "$PROBLEMS" -gt 0 ] && exit 1
    exit 0
fi

echo
if [ "$PROBLEMS" -gt 0 ]; then
    # Exit non-zero on problems in EVERY mode, not just --check. The .ps1 reports
    # and still exits 0, so a caller cannot tell a clean apply from one where an
    # edit's anchor had moved — and ts-agents.sh needs to know.
    printf '%s problem(s) - see the ! lines above.\n' "$PROBLEMS"
    exit 1
elif [ "$EXECUTE" != 1 ]; then
    printf 'Nothing changed (preview). Add --apply to write.\n'
else
    printf 'Done (%s). Restart each agent: hooks and env are read at process start.\n' "$MODE"
fi
