#!/usr/bin/env bash
# _workspace.sh — workspace layout library for `wso`. Derives every repo's home
# from its `origin` remote rather than from the folder it happens to sit in, so
# a misfiled clone is a computed fact rather than something you have to notice.
#
# Layout: <root>/<tier>/<host>/<owner>/<repo>
#   src/      owners listed in workspace.conf   (yours; must never be lost)
#   public/   everyone else                     (third-party; disposable cache)
#   archive/  cold repos, mirrors src/ exactly  (per-machine, never synced)
#   local/    no remote yet                     (holding pen — nothing to derive)
#   scratch/  not a git repo at all
#
# This file is sourced, not executed. Do not `exit`; return non-zero instead.
# Stays bash-3.2 clean (macOS ships 3.2): no associative arrays, no ${x,,}.

: "${INFO:=$'\033[1;34m==>\033[0m'}"
: "${WARN:=$'\033[1;33m!!\033[0m'}"

TS_WS_TIERS="src public archive local scratch"

# ---------------------------------------------------------------- config ----

# Lowercase without bash 4's ${x,,} — macOS bash 3.2 has to work too.
ts_ws_lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

# The tracked map, then the untracked per-machine override. Order matters:
# later files win, so the local file can redefine any org/rename/set.
ts_ws_conf_files() {
    local dir="${TS_WS_LIB_DIR:-}"
    [ -n "$dir" ] || dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    [ -f "$dir/workspace.conf" ] && printf '%s\n' "$dir/workspace.conf"
    local loc="${XDG_CONFIG_HOME:-$HOME/.config}/terminal-stack/workspace.local.conf"
    [ -f "$loc" ] && printf '%s\n' "$loc"
    return 0
}

# Populate TS_WS_ORGS / TS_WS_RENAMES / TS_WS_SETTINGS as space-delimited
# key=value strings. Same shape as TS_APPS_* in _config.sh, and it avoids
# associative arrays entirely.
ts_ws_load_config() {
    [ -n "${TS_WS_LOADED:-}" ] && [ -z "${TS_WS_RELOAD:-}" ] && return 0
    TS_WS_ORGS=""; TS_WS_RENAMES=""; TS_WS_SETTINGS=""
    local f kind a b
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        while read -r kind a b || [ -n "$kind" ]; do
            case "$kind" in ''|\#*) continue ;; esac
            [ -n "$a" ] || continue
            case "$kind" in
                org)    TS_WS_ORGS="$TS_WS_ORGS $(ts_ws_lower "$a")=$b" ;;
                rename) TS_WS_RENAMES="$TS_WS_RENAMES $(ts_ws_lower "$a")=$b" ;;
                set)    TS_WS_SETTINGS="$TS_WS_SETTINGS $a=$b" ;;
                *)      echo "$WARN workspace.conf: unknown directive '$kind' in $f" >&2 ;;
            esac
        done < "$f"
    done < <(ts_ws_conf_files)
    TS_WS_LOADED=1
    export TS_WS_ORGS TS_WS_RENAMES TS_WS_SETTINGS TS_WS_LOADED
}

# ts_ws_lookup "<a=1 b=2>" <key> <default> — last match wins, so an override
# file appended later beats the tracked default without having to dedupe.
ts_ws_lookup() {
    local list="$1" key="$2" def="$3" pair found=""
    for pair in $list; do
        case "$pair" in "$key="*) found="${pair#*=}" ;; esac
    done
    [ -n "$found" ] && printf '%s\n' "$found" || printf '%s\n' "$def"
}

ts_ws_setting() { ts_ws_load_config; ts_ws_lookup "$TS_WS_SETTINGS" "$1" "$2"; }

# Owner -> canonical owner, applying the rename map (martsamp77 -> martybytes).
ts_ws_canon_owner() {
    ts_ws_load_config
    ts_ws_lookup "$TS_WS_RENAMES" "$(ts_ws_lower "$1")" "$1"
}

# Owner -> tier. Checks the canonical name, so a renamed owner still resolves
# to src/ rather than falling through to public/.
ts_ws_tier_for_owner() {
    ts_ws_load_config
    local owner
    owner="$(ts_ws_lower "$(ts_ws_canon_owner "$1")")"
    ts_ws_lookup "$TS_WS_ORGS" "$owner" "$(ts_ws_setting default_tier public)"
}

ts_ws_is_own_owner() {
    [ "$(ts_ws_tier_for_owner "$1")" = "src" ]
}

# Every owner mapped to src/, space separated — used by status/sync/orphans.
ts_ws_own_owners() {
    ts_ws_load_config
    local pair out=""
    for pair in $TS_WS_ORGS; do
        case "$pair" in *=src) out="$out ${pair%%=*}" ;; esac
    done
    printf '%s\n' "${out# }"
}

# ------------------------------------------------------------- workspace ----

# The workspace root. Mirrors _ts_workspace in dot_zshrc deliberately — this
# library also runs from bash, where that zsh function does not exist.
ts_ws_root() {
    [ -n "${WORKSPACE_DIR:-}" ] && { printf '%s\n' "$WORKSPACE_DIR"; return 0; }
    local d
    for d in /mnt/c/DATA/Workspace "$HOME/Documents/Workspace" \
             "$HOME/workspace" "$HOME/Workspace"; do
        if [ -d "$d" ]; then { printf '%s\n' "$d"; return 0; }; fi
    done
    return 1
}

ts_ws_state_dir() {
    printf '%s\n' "${XDG_STATE_HOME:-$HOME/.local/state}/terminal-stack"
}

# The ACTIVE terminal-stack runtime clone (the one ts-update updates), realpathed.
# wso must never migrate it: relocating the runtime clone breaks the install
# (that's ts-doctor's job). Resolution: $TERMINAL_STACK_DIR → chezmoi.toml
# sourceDir (inline read — this library stays standalone). Empty when unknown.
ts_ws_runtime_clone() {
    local src="${TERMINAL_STACK_DIR:-}" toml="$HOME/.config/chezmoi/chezmoi.toml"
    if [ -z "$src" ] && [ -f "$toml" ]; then
        src="$(grep -E '^[[:space:]]*sourceDir[[:space:]]*=' "$toml" | head -n1 \
            | sed -E 's/^[[:space:]]*sourceDir[[:space:]]*=[[:space:]]*"?([^"]*)"?.*/\1/')"
    fi
    # Third step so a standalone `bash bootstrap/wso.sh` (Git Bash, no
    # chezmoi.toml) isn't left guard-less — an empty result switches the
    # "never migrate the runtime clone" check off entirely.
    if [ -z "$src" ] && command -v ts_canonical_clone_dir >/dev/null 2>&1; then
        src="$(ts_canonical_clone_dir 2>/dev/null || true)"
        [ -d "$src/.git" ] || src=""
    fi
    [ -n "$src" ] || return 1
    ( cd "$src" 2>/dev/null && pwd -P ) || printf '%s\n' "$src"
}

# --------------------------------------------------------- remote parsing ----

# ts_ws_parse_remote <url> -> "host<TAB>owner<TAB>repo", or return 1.
# Handles every form git actually emits:
#   git@host:owner/repo.git            (scp-like)
#   ssh://git@host:22/owner/repo.git
#   https://user@host/owner/repo
#   git://host/owner/repo.git
# Nested GitLab groups collapse into the owner, so group/subgroup/repo keeps its
# full path and cannot collide with a different group's same-named repo.
ts_ws_parse_remote() {
    local url="$1" host="" path="" rest=""
    url="${url%%[[:space:]]*}"
    [ -n "$url" ] || return 1
    # Strip a trailing .git and any trailing slashes.
    url="${url%/}"; url="${url%.git}"; url="${url%/}"
    case "$url" in
        *://*)
            rest="${url#*://}"
            rest="${rest#*@}"                 # drop user[:pass]@
            host="${rest%%/*}"; host="${host%%:*}"
            path="${rest#*/}"
            [ "$path" = "$rest" ] && return 1
            ;;
        *:*)
            rest="${url#*@}"                  # drop user@ if present
            host="${rest%%:*}"
            path="${rest#*:}"
            ;;
        *) return 1 ;;
    esac
    host="$(ts_ws_lower "$host")"
    path="${path#/}"; path="${path%/}"
    [ -n "$host" ] && [ -n "$path" ] || return 1
    case "$path" in */*) ;; *) return 1 ;; esac
    local repo="${path##*/}" owner="${path%/*}"
    [ -n "$repo" ] && [ -n "$owner" ] || return 1
    printf '%s\t%s\t%s\n' "$host" "$owner" "$repo"
}

# Rebuild a remote URL in the requested scheme, preserving host/owner/repo.
# scheme: ssh | https | preserve (returns the original untouched).
ts_ws_build_remote() {
    local scheme="$1" host="$2" owner="$3" repo="$4" orig="${5:-}"
    case "$scheme" in
        ssh)   printf 'git@%s:%s/%s.git\n' "$host" "$owner" "$repo" ;;
        https) printf 'https://%s/%s/%s.git\n' "$host" "$owner" "$repo" ;;
        *)     printf '%s\n' "$orig" ;;
    esac
}

ts_ws_origin() {
    git -C "$1" config --get remote.origin.url 2>/dev/null | head -n1
}

# ------------------------------------------------------------ destination ----

# ts_ws_dest_for <dir> -> "tier<TAB>relpath<TAB>note", relative to the root.
# This is the single place a repo's home is decided; everything else consumes it.
ts_ws_dest_for() {
    local dir="$1" name
    name="$(basename -- "$dir")"
    if [ ! -e "$dir/.git" ]; then
        printf 'scratch\tscratch/%s\t%s\n' "$name" "not a git repo"
        return 0
    fi
    local origin
    origin="$(ts_ws_origin "$dir")"
    if [ -z "$origin" ]; then
        printf 'local\tlocal/%s\tNO REMOTE - push before this becomes a real path\n' "$name"
        return 0
    fi
    local parsed
    if ! parsed="$(ts_ws_parse_remote "$origin")"; then
        printf 'local\t\tunparseable remote: %s\n' "$origin"
        return 0
    fi
    local host owner repo
    host="$(printf '%s' "$parsed" | cut -f1)"
    owner="$(printf '%s' "$parsed" | cut -f2)"
    repo="$(printf '%s' "$parsed" | cut -f3)"
    local canon tier note=""
    canon="$(ts_ws_canon_owner "$owner")"
    tier="$(ts_ws_tier_for_owner "$canon")"
    [ "$canon" != "$owner" ] && note="owner renamed $owner -> $canon"
    if [ "$name" != "$repo" ]; then
        [ -n "$note" ] && note="$note; "
        note="${note}folder '$name' renamed to match remote"
    fi
    printf '%s\t%s/%s/%s/%s\t%s\n' "$tier" "$tier" "$host" "$canon" "$repo" "$note"
}

# ------------------------------------------------------------- git state ----

# ts_ws_git_state <dir> -> "dirty<TAB>unpushed<TAB>stashes<TAB>head"
# head is the branch name, or the literal DETACHED.
ts_ws_git_state() {
    local dir="$1" dirty=0 unpushed=0 stashes=0 head="DETACHED" b
    dirty="$(git -C "$dir" status --porcelain 2>/dev/null | grep -c . || true)"
    # Commits on ANY local branch that no remote has. This is the gate that
    # matters for archiving: a repo can be clean and still hold the only copy
    # of work, on a branch you are not currently standing on.
    unpushed="$(git -C "$dir" rev-list --count --branches --not --remotes 2>/dev/null || echo 0)"
    stashes="$(git -C "$dir" rev-list --walk-reflogs --count refs/stash 2>/dev/null || echo 0)"
    if b="$(git -C "$dir" symbolic-ref --quiet --short HEAD 2>/dev/null)"; then head="$b"; fi
    printf '%s\t%s\t%s\t%s\n' "${dirty:-0}" "${unpushed:-0}" "${stashes:-0}" "$head"
}

# True when a repo is safe to move away. Sets TS_WS_UNSAFE_WHY on refusal.
ts_ws_is_safe_to_archive() {
    local dir="$1" st dirty unpushed stashes head
    st="$(ts_ws_git_state "$dir")"
    dirty="$(printf '%s' "$st" | cut -f1)"
    unpushed="$(printf '%s' "$st" | cut -f2)"
    stashes="$(printf '%s' "$st" | cut -f3)"
    head="$(printf '%s' "$st" | cut -f4)"
    TS_WS_UNSAFE_WHY=""
    [ "$dirty" -gt 0 ]    && TS_WS_UNSAFE_WHY="$TS_WS_UNSAFE_WHY ${dirty} uncommitted"
    [ "$unpushed" -gt 0 ] && TS_WS_UNSAFE_WHY="$TS_WS_UNSAFE_WHY ${unpushed} unpushed"
    [ "$stashes" -gt 0 ]  && TS_WS_UNSAFE_WHY="$TS_WS_UNSAFE_WHY ${stashes} stashed"
    [ "$head" = "DETACHED" ] && TS_WS_UNSAFE_WHY="$TS_WS_UNSAFE_WHY detached-HEAD"
    [ -z "$(ts_ws_origin "$dir")" ] && TS_WS_UNSAFE_WHY="$TS_WS_UNSAFE_WHY no-remote"
    TS_WS_UNSAFE_WHY="${TS_WS_UNSAFE_WHY# }"
    [ -z "$TS_WS_UNSAFE_WHY" ]
}

# ------------------------------------------------------------- staleness ----

# GNU vs BSD stat, probed rather than branched on uname — a Mac with Homebrew
# coreutils on PATH has GNU stat. Same reasoning as _ts_stat_flavor in dot_zshrc.
ts_ws_stat_flavor() {
    if [ -z "${TS_WS_STAT_FLAVOR:-}" ]; then
        if stat -c %Y . >/dev/null 2>&1; then TS_WS_STAT_FLAVOR=gnu
        else TS_WS_STAT_FLAVOR=bsd; fi
    fi
    printf '%s\n' "$TS_WS_STAT_FLAVOR"
}

# Newest mtime among a repo's immediate children, EXCLUDING .git.
#
# Two things are load-bearing here. -mindepth 1 stops find returning the repo
# itself, whose own mtime only moves when entries are added or removed — the
# exact trap `lsr` exists to avoid. And excluding .git matters even more for a
# repo than for a plain directory: git fetch, gc and even status add and remove
# files under .git, so including it would make every repo look touched today.
ts_ws_newest_child() {
    local dir="$1"
    if [ "$(ts_ws_stat_flavor)" = gnu ]; then
        find "$dir" -mindepth 1 -maxdepth 1 -name .git -prune -o -exec stat -c '%Y' {} + 2>/dev/null
    else
        find "$dir" -mindepth 1 -maxdepth 1 -name .git -prune -o -exec stat -f '%m' {} + 2>/dev/null
    fi | sort -rn | head -n1
}

# Last real activity: the later of the last commit and the newest working file.
# A repo cloned last week but never committed to is not stale, and neither is
# one you have been editing all afternoon without committing.
ts_ws_last_activity() {
    local dir="$1" commit=0 child=0
    commit="$(git -C "$dir" log -1 --format=%ct 2>/dev/null || echo 0)"
    child="$(ts_ws_newest_child "$dir")"
    [ -n "$commit" ] || commit=0
    [ -n "$child" ] || child=0
    if [ "$commit" -ge "$child" ]; then printf '%s\n' "$commit"; else printf '%s\n' "$child"; fi
}

ts_ws_days_since() {
    local when="$1" now
    now="$(date +%s)"
    [ "${when:-0}" -gt 0 ] || { printf '99999\n'; return 0; }
    printf '%s\n' $(( (now - when) / 86400 ))
}

ts_ws_fmt_date() {
    local e="$1"
    [ "${e:-0}" -gt 0 ] || { printf 'never\n'; return 0; }
    if [ "$(ts_ws_stat_flavor)" = gnu ]; then date -d "@$e" '+%Y-%m-%d'
    else date -r "$e" '+%Y-%m-%d'; fi
}

# ------------------------------------------------------------------ moves ----

# Same filesystem? A move within one is an atomic rename that preserves dirty
# files, stashes, reflog and untracked scratch. Across filesystems it silently
# degrades to copy+delete, which is slow and can half-finish — we refuse instead.
ts_ws_same_volume() {
    local a="$1" b="$2" da db
    while [ -n "$b" ] && [ "$b" != "/" ] && [ ! -d "$b" ]; do b="$(dirname -- "$b")"; done
    da="$(df -P -- "$a" 2>/dev/null | awk 'NR==2{print $1}')"
    db="$(df -P -- "$b" 2>/dev/null | awk 'NR==2{print $1}')"
    [ -n "$da" ] && [ "$da" = "$db" ]
}

# Move with retry. On Windows-backed paths (/mnt/c) a handle held by an editor,
# terminal, language server or indexer makes the rename fail transiently.
ts_ws_move() {
    local src="$1" dst="$2" n=0 max="${TS_WS_MOVE_RETRIES:-5}"
    [ -e "$dst" ] && { echo "$WARN destination exists, refusing: $dst" >&2; return 1; }
    mkdir -p -- "$(dirname -- "$dst")" || return 1
    if ! ts_ws_same_volume "$src" "$dst"; then
        echo "$WARN $src and $dst are on different filesystems; a move there is a copy, not a rename." >&2
        echo "$WARN Move it by hand, or point the workspace root at the same volume." >&2
        return 1
    fi
    while [ "$n" -lt "$max" ]; do
        if mv -- "$src" "$dst" 2>/dev/null; then return 0; fi
        n=$((n + 1)); sleep 1
    done
    echo "$WARN could not move $src (something is holding it open — editor, terminal, language server, indexer)" >&2
    return 1
}

# ------------------------------------------------------------------- logs ----

# Run logs live inside the workspace, not in per-OS state. They describe the
# workspace, not the machine — and on a combined Windows+WSL setup both sides
# drive the same tree, so a `--undo-last` from zsh must see an archive run done
# from PowerShell. Splitting them by OS state dir would silently hide it.
# The leading dot keeps the directory out of ts_ws_scan_candidates.
ts_ws_run_log_dir() { printf '%s/.terminal-stack/workspace-runs\n' "$(ts_ws_root)"; }

# Run logs store paths RELATIVE to the workspace root, with forward slashes.
# Absolute paths would be unreadable from the other side of a combined
# Windows+WSL setup: pwsh writes "C:\...\archive\x", which zsh cannot resolve.
# These two helpers are the only places that format matters.
ts_ws_log_rel() {
    local p="$1" root="${2:-$(ts_ws_root)}"
    p="${p#"$root"/}"
    printf '%s\n' "$p" | tr '\\' '/'
}
ts_ws_log_abs() {
    local rel="$1" root="${2:-$(ts_ws_root)}"
    rel="$(printf '%s' "$rel" | tr '\\' '/')"
    printf '%s/%s\n' "$root" "$rel"
}

ts_ws_new_run_log() {
    local kind="$1" dir f
    dir="$(ts_ws_run_log_dir)"
    mkdir -p -- "$dir" || return 1
    f="$dir/$(date +%Y%m%d-%H%M%S)-$kind.tsv"
    printf 'action\tsource\tdestination\n' > "$f" || return 1
    printf '%s\n' "$f"
}

ts_ws_latest_run_log() {
    local kind="$1" dir
    dir="$(ts_ws_run_log_dir)"
    [ -d "$dir" ] || return 1
    ls -1 "$dir"/*-"$kind".tsv 2>/dev/null | sort | tail -n1
}

# --------------------------------------------------------------- scanning ----

# Scan roots: the workspace itself plus its legacy siblings (Workspace_Public,
# Workspace-md, ...), plus anything in $TS_WS_EXTRA_ROOTS.
#
# The sibling list comes from enumerating the parent directory rather than from
# guessing suffixes. That matters on Windows and macOS, whose filesystems are
# case-insensitive: probing both "${root}-md" and "${root}-MD" finds the same
# directory twice and every repo inside it gets planned twice. Listing the
# parent yields each real entry exactly once, under its true on-disk name.
ts_ws_scan_roots() {
    local root parent base d name lbase lname extra
    root="$(ts_ws_root)" || return 1
    parent="$(dirname -- "$root")"
    base="$(basename -- "$root")"
    lbase="$(ts_ws_lower "$base")"
    {
        printf '%s
' "$root"
        for d in "$parent"/*; do
            [ -d "$d" ] || continue
            name="$(basename -- "$d")"
            lname="$(ts_ws_lower "$name")"
            case "$lname" in
                "$lbase"[-_]*) printf '%s
' "$d" ;;
            esac
        done
        for extra in ${TS_WS_EXTRA_ROOTS:-}; do
            [ -d "$extra" ] && printf '%s
' "$extra"
        done
    } | awk 'NF && !seen[tolower($0)]++'
    return 0
}

ts_ws_is_tier_dir() {
    local name="$1" t
    for t in $TS_WS_TIERS; do [ "$name" = "$t" ] && return 0; done
    return 1
}

# Candidate directories to organise: immediate children of each scan root,
# minus tier dirs and dotfiles. Tier dirs are skipped so a re-run after
# migration does not try to migrate the organised tree into itself.
ts_ws_scan_candidates() {
    local r d name root
    root="$(ts_ws_root)" || return 1
    while IFS= read -r r; do
        [ -n "$r" ] || continue
        for d in "$r"/*; do
            [ -d "$d" ] || continue
            name="$(basename -- "$d")"
            case "$name" in .*) continue ;; esac
            # Skip tier directories, but ONLY directly under the workspace root.
            # Legacy sibling roots can legitimately contain a repo named "public"
            # or "local"; treating those as tiers would silently drop a real repo
            # from the migration plan, which is the one thing this must never do.
            if [ "$r" = "$root" ] && ts_ws_is_tier_dir "$name"; then continue; fi
            printf '%s\n' "$d"
        done
    done < <(ts_ws_scan_roots)
    return 0
}

# Every git repo already living in the organised tree, one path per line.
ts_ws_managed_repos() {
    local root tier
    root="$(ts_ws_root)" || return 1
    for tier in ${1:-src public archive local}; do
        [ -d "$root/$tier" ] || continue
        find "$root/$tier" -maxdepth 5 -name .git -prune -print 2>/dev/null \
            | sed 's|/\.git$||'
    done
    return 0
}
