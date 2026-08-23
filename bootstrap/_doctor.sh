#!/usr/bin/env bash
# _doctor.sh — diagnose + repair the terminal-stack install. Sourced by the bash
# entry ts-doctor.sh, by the installers (post-apply health check), and by ts-update.
# Depends on _config.sh (sourceDir helpers) and _cleanup.sh (clone discovery).
#
# This file is sourced, not executed. Do not `exit`; return non-zero instead.

if ! command -v ts_chezmoi_bin >/dev/null 2>&1; then
    _ts_doctor_dir="$(dirname -- "${BASH_SOURCE[0]}")"
    # shellcheck source=_config.sh
    [ -f "$_ts_doctor_dir/_config.sh" ] && . "$_ts_doctor_dir/_config.sh"
fi
if ! command -v ts_find_old_clones >/dev/null 2>&1; then
    _ts_doctor_dir="$(dirname -- "${BASH_SOURCE[0]}")"
    # shellcheck source=_cleanup.sh
    [ -f "$_ts_doctor_dir/_cleanup.sh" ] && . "$_ts_doctor_dir/_cleanup.sh"
fi
: "${INFO:=$'\033[1;34m==>\033[0m'}"
: "${WARN:=$'\033[1;33m!!\033[0m'}"

TS_CANONICAL_REMOTE="https://github.com/martybytes/terminal-stack.git"

# Move the runtime clone to a new location, git state (incl. dirty worktree,
# stashes, reflog) intact, then repoint chezmoi and fix stale pins.
# Same-volume moves are instant renames; a cross-device move (ext4 -> /mnt/c)
# copies, verifies HEAD, then removes the source.
ts_relocate_clone() {
    local src="$1" dst="$2" cz head ans
    ts_is_stack_clone "$src" || { echo "$WARN relocate: '$src' is not a terminal-stack clone."; return 1; }
    [ -e "$dst" ] && { echo "$WARN relocate: destination '$dst' already exists."; return 1; }
    case "$dst/" in "$src"/*) echo "$WARN relocate: destination is inside the source."; return 1 ;; esac
    if [ -n "$(git -C "$src" status --porcelain 2>/dev/null)" ]; then
        echo "$INFO relocate: clone has uncommitted changes — they move with it."
    fi
    head="$(git -C "$src" rev-parse HEAD 2>/dev/null)"
    mkdir -p -- "$(dirname -- "$dst")" || return 1
    echo "$INFO moving $src -> $dst"
    mv -- "$src" "$dst" || { echo "$WARN relocate: move failed; nothing changed."; return 1; }
    if [ "$(git -C "$dst" rev-parse HEAD 2>/dev/null)" != "$head" ]; then
        echo "$WARN relocate: HEAD mismatch after move — inspect $dst before continuing."; return 1
    fi
    # ext4 -> drvfs: silence mode-bit churn on the Windows filesystem.
    case "$dst" in /mnt/c/*) git -C "$dst" config core.filemode false 2>/dev/null || true ;; esac

    # Repoint chezmoi at the new location and re-apply.
    if cz="$(ts_chezmoi_bin)"; then
        ts_ensure_source_dir "$dst"
        echo "$INFO re-applying from $dst…"
        "$cz" apply || echo "$WARN chezmoi apply failed — run it manually after fixing the issue."
    fi

    # Normalize an origin URL left over from the renamed account.
    local origin
    origin="$(git -C "$dst" config --get remote.origin.url 2>/dev/null || true)"
    if [ -n "$origin" ] && [ "$origin" != "$TS_CANONICAL_REMOTE" ] \
       && printf '%s' "$origin" | grep -qiE 'martsamp77|terminal-stack'; then
        case "$origin" in
            git@github.com:martybytes/terminal-stack*) : ;;  # SSH form of the canonical remote — leave it
            *)
                ans="$(ts_tty_prompt "Origin is '$origin' — set it to $TS_CANONICAL_REMOTE? [Y/n]: ")"
                case "$ans" in n|N|no|NO) : ;; *) git -C "$dst" remote set-url origin "$TS_CANONICAL_REMOTE" \
                    && echo "$INFO origin -> $TS_CANONICAL_REMOTE" ;; esac ;;
        esac
    fi

    # WSL cross-fix: a Windows-side TERMINAL_STACK_DIR pin at the OLD path is now
    # stale. Canonical needs no pin, so remove the line (backed up first).
    if [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
        local winsrc plps fixed=0
        winsrc="$(printf '%s' "$src" | sed -E 's|^/mnt/c/|C:/|' | tr '/' '\\')"
        for plps in /mnt/c/Users/*/Documents/PowerShell/profile.local.ps1 \
                    /mnt/c/Users/*/OneDrive*/Documents/PowerShell/profile.local.ps1; do
            [ -f "$plps" ] || continue
            if grep -iq 'TERMINAL_STACK_DIR' "$plps" 2>/dev/null \
               && grep -iqF "$winsrc" "$plps" 2>/dev/null; then
                ts_backup_file "$plps"
                sed -i '/TERMINAL_STACK_DIR/d' "$plps"
                echo "$INFO removed the stale \$env:TERMINAL_STACK_DIR pin from $plps"
                fixed=1
            fi
        done
        if [ "$fixed" -eq 0 ]; then
            echo "$INFO if pwsh pins TERMINAL_STACK_DIR at the old path, remove that line from profile.local.ps1 (canonical needs no pin)."
        fi
    fi

    echo "$INFO clone relocated. If your shell's cwd was inside it: cd $dst"
}

# Diagnose. Prints a checklist; returns 0 when healthy, 1 when issues are found.
# Set TS_DOCTOR_QUIET=1 to suppress the per-check "ok" lines (warnings still show).
# Read one dotted path out of the Windows config mirror. Prints __missing__ when the key
# is absent, so a mirror written by an older version does not read as a disagreement.
ts_doctor_mirror_value() {
    python3 - "$1" "$2" <<'PY' 2>/dev/null || printf '__missing__'
import json, sys
try:
    node = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    print("__missing__", end=""); raise SystemExit
for part in sys.argv[2].split("."):
    if not isinstance(node, dict) or part not in node:
        print("__missing__", end=""); raise SystemExit
    node = node[part]
if isinstance(node, bool):
    print("true" if node else "false", end="")
else:
    print(node, end="")
PY
}

# The two stores spell the same answer differently: chezmoi [data] holds "true"/"false" and
# on/off strings, the mirror holds real JSON booleans. Compare meaning, not spelling.
ts_doctor_norm() {
    case "$1" in
        on|On|ON|true|True|TRUE|yes|1) printf 'true' ;;
        off|Off|OFF|false|False|FALSE|no|0|'') printf 'false' ;;
        *) printf '%s' "$1" ;;
    esac
}

ts_doctor() {
    local issues=0 cz src others t
    local quiet="${TS_DOCTOR_QUIET:-}"
    _ok()  { [ "$quiet" = "1" ] || echo "  ok  $1"; }
    _bad() { echo "  $WARN $1"; issues=$((issues + 1)); }

    [ "$quiet" = "1" ] || echo "$INFO terminal-stack doctor"

    if ! cz="$(ts_chezmoi_bin)"; then
        _bad "chezmoi binary not found (~/.local/bin/chezmoi or PATH)"
        echo "$WARN $issues issue(s) found."; return 1
    fi
    _ok "chezmoi: $cz"

    src="$("$cz" source-path 2>/dev/null || true)"
    if [ -z "$src" ]; then
        _bad "chezmoi has no source dir (chezmoi.toml missing sourceDir)"
    elif [ ! -d "$src/.git" ]; then
        _bad "sourceDir '$src' is not a git clone"
    elif ! ts_is_stack_clone "$src"; then
        _bad "sourceDir '$src' is a git repo but not a terminal-stack clone"
    else
        _ok "sourceDir: $src"
    fi

    if [ -f "$HOME/.zshrc" ]; then
        if grep -q 'terminal-stack-zsh-start' "$HOME/.zshrc" 2>/dev/null; then
            _ok "~/.zshrc has the terminal-stack block"
        else
            _bad "~/.zshrc missing the terminal-stack block (stale or not applied)"
        fi
        if grep -q 'doc-start' "$HOME/.zshrc" 2>/dev/null; then
            _ok "~/.zshrc has the 'doc' command"
        else
            _bad "~/.zshrc has no 'doc' command (source may predate the doc feature)"
        fi
    else
        _bad "~/.zshrc not found (chezmoi apply not run yet?)"
    fi

    for t in zsh starship; do
        if command -v "$t" >/dev/null 2>&1; then _ok "$t on PATH"; else _bad "$t not on PATH"; fi
    done

    # Config-store divergence, and whether any TTS hook exists at all. Both live OUTSIDE
    # the ccTtsEnabled gate below, deliberately: the failure being checked for is one store
    # saying "off" while the other says "on", so gating on either store blinds the check
    # exactly when it matters. On 2026-08-21 the mirror said false, chezmoi [data] said
    # true, the pwsh sync had deleted every TTS hook, and the doctor reported "tts daemon
    # healthy".
    #
    # Report only, never repair: a disagreement can be a deliberate pwsh-side change, and
    # overwriting it would be the same silent loss this check exists to expose.
    if [ -d /mnt/c/Users ] && command -v ts_data_prefetch >/dev/null 2>&1 \
        && command -v python3 >/dev/null 2>&1; then
        local _dv_user _dv_mirror _dv_pair _dv_key _dv_path _dv_mine _dv_theirs _dv_found=0
        _dv_user="$(ts_win_user 2>/dev/null || true)"
        _dv_mirror="/mnt/c/Users/$_dv_user/AppData/Local/terminal-stack/config.json"
        if [ -n "$_dv_user" ] && [ -f "$_dv_mirror" ]; then
            # One render for every key, because a per-key chezmoi spawn costs seconds here.
            # shellcheck disable=SC2086
            ts_data_prefetch $TS_MIRROR_DATA_KEYS
            # chezmoi [data] key : dotted path in the Windows mirror. Only the keys whose
            # disagreement changes what gets rendered are worth reporting.
            for _dv_pair in ccTtsEnabled:ccTts.enabled \
                            ccTtsDaemon:ccTts.daemon.enabled \
                            ccTtsEngine:ccTts.engine \
                            ccTtsSummarizer:ccTts.summarize.mode \
                            leaderChord:leaderChord \
                            themeMode:themeMode \
                            tmuxPrefix:tmuxPrefix \
                            weztermMux:weztermMux \
                            weztermRestore:weztermRestore \
                            headroomEnabled:headroomEnabled \
                            headroomCursorMode:headroomCursorMode \
                            cavemanEnabled:cavemanEnabled \
                            agentmemoryEnabled:agentmemoryEnabled; do
                _dv_key="${_dv_pair%%:*}"
                _dv_path="${_dv_pair#*:}"
                _dv_mine="$(ts_data_get "$_dv_key" 2>/dev/null || true)"
                _dv_theirs="$(ts_doctor_mirror_value "$_dv_mirror" "$_dv_path")"
                [ "$_dv_theirs" = "__missing__" ] && continue
                if [ "$(ts_doctor_norm "$_dv_mine")" != "$(ts_doctor_norm "$_dv_theirs")" ]; then
                    _dv_found=1
                    _bad "config stores disagree on $_dv_key: chezmoi [data]='$_dv_mine' but the Windows mirror='$_dv_theirs'"
                    echo "      [data] wins for 'chezmoi apply' from WSL; the mirror wins for a pwsh sync."
                fi
            done
            [ "$_dv_found" = 0 ] && _ok "config stores agree"
        fi
    fi

    # A hook that does not exist cannot be degraded, slow, or muted - it is simply absent,
    # and every other TTS check will still look healthy. This is the one-line version of
    # the outage above.
    if [ -d /mnt/c/Users ]; then
        local _hk_user _hk_settings
        _hk_user="$(ts_win_user 2>/dev/null || true)"
        _hk_settings="/mnt/c/Users/$_hk_user/.claude/settings.json"
        if [ -n "$_hk_user" ] && [ -f "$_hk_settings" ]; then
            if grep -q 'terminal-stack-tts.exe hook' "$_hk_settings" 2>/dev/null; then
                _ok "Claude TTS hooks installed"
            elif [ "$(ts_cc_tts_get ccTtsEnabled 2>/dev/null)" = true ]; then
                _bad "TTS is enabled but ~/.claude/settings.json has no terminal-stack-tts hooks - nothing will ever call the daemon; repair: ts-config tts on (from WSL)"
            fi
        fi
    fi

    # Claude TTS (only when the feature is on). Kokoro down is a note (edge-tts
    # covers it); an enabled-but-dead daemon is a failure — the hooks are
    # silently degraded to direct playback and the user chose otherwise.
    if command -v ts_cc_tts_get >/dev/null 2>&1 && [ "$(ts_cc_tts_get ccTtsEnabled 2>/dev/null)" = true ]; then
        if ts_cc_tts_probe 2>/dev/null | grep -q '^kokoro: up'; then
            _ok "kokoro TTS engine reachable"
        else
            echo "  note: kokoro TTS engine not reachable (edge-tts fallback will be used)"
        fi
        # One line of forensics from the utterance history. Both numbers below are
        # invisible otherwise: every hook exits 0 whether it spoke once, three times, or
        # fell back to the direct path for fifteen hours.
        local _hexe _hchk _hage _hdup _mute
        _hexe="$(ts_cc_tts_exe_path 2>/dev/null || true)"
        if [ -n "$_hexe" ] && [ -f "$_hexe" ]; then
            _hchk="$("$_hexe" history --check 2>/dev/null | tr -d "\015")"
            case "$_hchk" in
                *daemon_silent_for=*)
                    _hage="${_hchk##*daemon_silent_for=}"; _hage="${_hage%% *}"
                    _hdup="${_hchk##*dupes=}"; _hdup="${_hdup%% *}" ;;
            esac
        fi
        # A mute is a note, never a failure -- but an unreported one is indistinguishable
        # from broken TTS, which is exactly how an afternoon got lost to a stale override.
        if [ -n "$_hexe" ] && [ -f "$_hexe" ]; then
            _mute="$("$_hexe" mute status 2>/dev/null | tr -d "\015")"
            case "$_mute" in
                *MUTED*) echo "  note: ${_mute#tts: } - unmute with ccmute, or the tray icon" ;;
            esac
        fi
        # The untracked local override wins over the rendered config, so `cctts on` can
        # report success while every hook stays silent.
        # The Windows-side file on a combined host: that is the one the EXE merges. Reading
        # $HOME here meant the WSL home, so this check could never have fired on the very
        # machine it was written for.
        local _lj="$HOME/.claude/tts/local.json" _lj_user
        if [ -d /mnt/c/Users ]; then
            _lj_user="$(ts_win_user 2>/dev/null || true)"
            [ -n "$_lj_user" ] && _lj="/mnt/c/Users/$_lj_user/.claude/tts/local.json"
        fi
        if [ -f "$_lj" ] \
            && grep -q '"enabled"[[:space:]]*:[[:space:]]*false' "$_lj" 2>/dev/null; then
            _bad "tts: $_lj forces enabled=false, which overrides the saved setting - remove that key (ccmute is the way to go quiet)"
        fi
        if [ -n "${_hdup:-}" ] && [ "$_hdup" != 0 ]; then
            echo "  note: $_hdup session(s) spoke twice within 8s in the last day - inspect: ts-config tts history --dupes"
        fi
        if [ "$(ts_cc_tts_get ccTtsDaemon 2>/dev/null)" = on ]; then
            local _dout _snap
            if _dout="$(ts_cc_tts_daemon_status 2>/dev/null)"; then
                _ok "tts daemon healthy"
                printf '%s\n' "$_dout" | grep 'older build' | sed 's/^/  note: /' || true
            else
                _bad "tts daemon enabled (ccTtsDaemon=on) but not reachable — hooks fall back to direct playback; start: ts-config tts daemon on"
                if [ -n "${_hage:-}" ] && [ "$_hage" != - ] && [ "$_hage" -gt 900 ] 2>/dev/null; then
                    echo "  note: nothing has spoken through the daemon for $((_hage / 60)) minutes - that long on the direct path is how overlapping voices go unnoticed"
                fi
                _snap="$(ts_cc_tts_daemon_snapshot_path 2>/dev/null || true)"
                if [ -n "$_snap" ] && [ -f "$_snap" ]; then
                    echo "  note: stale duck snapshot present — music may be stuck quiet; the daemon's next start restores it (ts-config tts daemon on)"
                fi
            fi
        fi
    fi

    # agentmemory hook wiring (only when agentmemory is actually installed). The hook
    # scripts live in vendor plugin caches, so a plugin upgrade reverts every edit and
    # retrieval silently stops - the one failure worth a check, because nothing else
    # reports it. The sync repairs it automatically; this is for when you want to know.
    if [ "$(ts_agent_get agentmemoryEnabled 2>/dev/null || echo off)" = on ] && [ -n "${src:-}" ]; then
        # On WSL the agents and their configuration live on Windows, so the check
        # goes through the .ps1 as before. Everywhere else — macOS, native Linux —
        # the bash twin runs it directly. The [ -d /mnt/c/Users ] gate used to be
        # unconditional, which is why macOS and Linux never checked (and never
        # wired) anything at all.
        local _am_pwsh _am_win _am_done=0
        if [ -d /mnt/c/Users ] && [ -f "$src/bootstrap/ts-agentmemory.ps1" ]; then
            _am_pwsh=""
            for _p in "/mnt/c/Program Files/PowerShell/7/pwsh.exe" \
                      "/mnt/c/Program Files/PowerShell/7-preview/pwsh.exe"; do
                [ -x "$_p" ] && { _am_pwsh="$_p"; break; }
            done
            if [ -n "$_am_pwsh" ]; then
                _am_win="$(wslpath -w "$src/bootstrap/ts-agentmemory.ps1" 2>/dev/null || printf '%s' "$src/bootstrap/ts-agentmemory.ps1")"
                if "$_am_pwsh" -NoLogo -NonInteractive -ExecutionPolicy Bypass -File "$_am_win" -Check >/dev/null 2>&1; then
                    _ok "agentmemory hook wiring intact"
                else
                    _bad "agentmemory hook wiring is incomplete (a plugin upgrade reverts it) — repair: ts-update, or bootstrap/ts-agentmemory.ps1 -Apply"
                fi
                _am_done=1
            fi
        fi
        if [ "$_am_done" = 0 ] && [ -f "$src/bootstrap/ts-agentmemory.sh" ]; then
            if bash "$src/bootstrap/ts-agentmemory.sh" --check >/dev/null 2>&1; then
                _ok "agentmemory hook wiring intact"
            else
                _bad "agentmemory hook wiring is incomplete (a plugin upgrade reverts it) — repair: ts-config agents agentmemory repair"
            fi
        fi
        # The secret, which is a different failure. The hooks now recover a stale *process*
        # copy by re-reading it from the user environment on a 401, but nothing can recover
        # when the user environment is itself the stale one: every request 401s and both
        # capture and retrieval swallow it, so a whole session's observations vanish with
        # nothing in any log. Compare the two stores when Docker is reachable; skip quietly
        # when it is not, since the container is not this repo's concern.
        local _am_cid _am_csec _am_usec
        if command -v docker >/dev/null 2>&1; then
            _am_cid="$(timeout 5 docker ps --filter name=agentmemory --format '{{.Names}}' 2>/dev/null \
                | grep -v console | head -1)"
            if [ -n "$_am_cid" ]; then
                _am_csec="$(timeout 5 docker exec "$_am_cid" cat /data/.hmac 2>/dev/null | tr -d '\r\n')"
                # A freshly spawned cmd.exe reads the current user environment, which is the
                # value a hook would recover to -- not this shell's possibly stale copy.
                _am_usec="$(timeout 5 cmd.exe /c 'echo %AGENTMEMORY_SECRET%' 2>/dev/null | tr -d '\r\n')"
                case "$_am_usec" in *'%AGENTMEMORY_SECRET%'*) _am_usec="" ;; esac
                if [ -n "$_am_csec" ] && [ -n "$_am_usec" ] && [ "$_am_csec" != "$_am_usec" ]; then
                    _bad "agentmemory secret mismatch: the container's differs from AGENTMEMORY_SECRET in your user environment — every request 401s and is swallowed; refresh it with the plugin's setup"
                fi
            fi
        fi
    fi

    # ── ts-smb (SMB shares over rclone) ───────────────────────────────────────
    # Gated: ts_doctor is already long, so this runs only once you actually use
    # ts-smb. `ts-smb doctor` is the full report; these are the three lines that
    # matter to a general health check.
    local smb_conf="${XDG_CONFIG_HOME:-$HOME/.config}/terminal-stack/shares.local.conf"
    local smb_state="${XDG_STATE_HOME:-$HOME/.local/state}/terminal-stack/smb"
    if [ -f "$smb_conf" ] || [ -n "$(ls -A "$smb_state" 2>/dev/null || true)" ]; then
        if command -v rclone >/dev/null 2>&1; then
            _ok "ts-smb: rclone present"
        else
            _bad "ts-smb: shares are configured but rclone is missing; repair: ts-config apps rclone"
        fi
        # The Homebrew macOS build refuses to mount, and nothing at runtime can
        # get past it — worth saying out loud, because browsing still works and
        # only mounting breaks.
        if [ "$(uname -s 2>/dev/null)" = Darwin ] && command -v rclone >/dev/null 2>&1; then
            local rcp; rcp="$(command -v rclone)"
            rcp="$(realpath "$rcp" 2>/dev/null || printf '%s' "$rcp")"
            case "$rcp" in
                */Cellar/*|/opt/homebrew/*|/usr/local/Homebrew/*)
                    _bad "ts-smb: this rclone is the Homebrew build, which cannot mount on macOS (browsing is unaffected); repair: install the official binary from https://rclone.org/downloads/"
                    ;;
            esac
        fi
        local smb_stale=0 f pid mp
        for f in "$smb_state"/*.mnt; do
            [ -f "$f" ] || continue
            pid="$(awk '$1 == "pid" { print $2 }' "$f" 2>/dev/null | tail -1)"
            case "$pid" in ''|*[!0-9]*) smb_stale=$((smb_stale + 1)); continue ;; esac
            kill -0 "$pid" 2>/dev/null || smb_stale=$((smb_stale + 1))
        done
        if [ "$smb_stale" -gt 0 ]; then
            _bad "ts-smb: $smb_stale stale mount record(s); repair: ts-smb umount --all --force"
        fi
    fi

    # Location advisories (not health failures): a legacy-path runtime clone can
    # be moved to the canonical location; a dev-clone pin is deliberate.
    local canon=""
    command -v ts_canonical_clone_dir >/dev/null 2>&1 && canon="$(ts_canonical_clone_dir 2>/dev/null || true)"
    if [ -n "$src" ] && [ -n "$canon" ] && [ "$(_ts_realpath "$src")" != "$(_ts_realpath "$canon")" ]; then
        if command -v ts_is_dev_clone >/dev/null 2>&1 && ts_is_dev_clone "$src"; then
            echo "  note: sourceDir points at a dev clone (workspace tier path) — deliberate pin, leaving it alone."
        else
            echo "  note: clone is at a legacy location; 'ts-doctor --repair' can move it to $canon"
        fi
    fi

    # Leftover clones are advisory, not a health failure — note them without
    # counting an issue, so a working install still reports "all checks passed".
    others="$(ts_find_old_clones "${src:-$HOME/code/terminal-stack}" 2>/dev/null)"
    if [ -n "$others" ]; then
        echo "  note: other terminal-stack clones present (ts-doctor --repair can clean them up):"
        echo "$others" | sed 's/^/        /'
    fi

    unset -f _ok _bad 2>/dev/null || true
    if [ "$issues" -eq 0 ]; then [ "$quiet" = "1" ] || echo "$INFO all checks passed."; return 0; fi
    echo "$WARN $issues issue(s) found — run 'ts-doctor --repair' to fix."
    return 1
}

# Repair. <desired-clone> (optional) is the clone that should be canonical; when
# omitted we keep the current valid sourceDir, else auto-pick the only clone found.
# Confirms before repointing/applying and before any cleanup.
ts_repair() {
    local desired="${1:-}" cz src ans
    cz="$(ts_chezmoi_bin)" || { echo "$WARN chezmoi not found; cannot repair."; return 1; }
    src="$("$cz" source-path 2>/dev/null || true)"

    if [ -z "$desired" ]; then
        if [ -n "$src" ] && ts_is_stack_clone "$src"; then
            desired="$src"
        else
            local found="" cnt=0 c
            while IFS= read -r c; do found="$c"; cnt=$((cnt + 1)); done < <(ts_find_old_clones "/nonexistent" 2>/dev/null)
            if [ "$cnt" -eq 1 ]; then desired="$found"
            elif [ "$cnt" -gt 1 ]; then
                echo "$WARN multiple clones found and none is active. Re-run the installer or set TERMINAL_STACK_DIR, then retry."
                ts_find_old_clones "/nonexistent" 2>/dev/null | sed 's/^/        /'
                return 1
            else
                echo "$WARN no terminal-stack clone found. Re-run the install one-liner."
                return 1
            fi
        fi
    fi

    # Offer the canonical-location move first (relocation repoints + applies itself).
    local canon=""
    command -v ts_canonical_clone_dir >/dev/null 2>&1 && canon="$(ts_canonical_clone_dir 2>/dev/null || true)"
    if [ -n "$canon" ] && [ "$(_ts_realpath "$desired")" != "$(_ts_realpath "$canon")" ] \
       && ! ts_is_dev_clone "$desired"; then
        if [ -e "$canon" ]; then
            echo "$WARN canonical location $canon already exists — not moving '$desired'; resolve via the cleanup menu."
        else
            ans="$(ts_tty_prompt "Move '$desired' to the canonical location '$canon'? [Y/n]: ")"
            case "$ans" in
                n|N|no|NO) echo "$INFO left the clone where it is." ;;
                *) if ts_relocate_clone "$desired" "$canon"; then
                       desired="$canon"
                       src="$("$cz" source-path 2>/dev/null || true)"
                   fi ;;
            esac
        fi
    fi

    if [ "$src" != "$desired" ]; then
        ans="$(ts_tty_prompt "Repoint chezmoi sourceDir from '${src:-<unset>}' to '$desired'? [Y/n]: ")"
        case "$ans" in
            n|N|no|NO) echo "$INFO left sourceDir unchanged." ;;
            *) ts_ensure_source_dir "$desired"
               echo "$INFO re-applying from $desired…"
               "$cz" apply && echo "$INFO chezmoi apply done — run 'exec zsh -l' to reload your shell." ;;
        esac
    else
        echo "$INFO sourceDir already correct ($desired)."
    fi

    ts_cleanup_menu "$desired"

    # Final quiet verify pass so the user sees the end state.
    TS_DOCTOR_QUIET=1 ts_doctor || true
}
