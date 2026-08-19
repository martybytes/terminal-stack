#!/usr/bin/env bash
# wso - workspace organizer. Keeps many repos across several GitHub owners in one
# derivable tree, and makes bulk operations over them safe.
#
# Usage:
#   wso status [--dirty] [--org X]  what is dirty / unpushed / detached (read-only)
#   wso plan                        preview the migration; never writes
#   wso migrate [--fix-remotes]     execute it (moves only; asks first)
#   wso sync [--org X]              fast-forward-only update of what is here
#   wso synceverything              sync, then clone every missing org repo
#   wso archive [--days N]          interactive: threshold, checklist, confirm
#   wso unarchive [name|--org X|--all|--undo-last] [--update]
#   wso get <url|owner/repo>        clone to the derived path
#   wso orphans [--push]            repos with no remote (they exist on one disk)
#   wso identity                    write this machine's git identity rules
#   wso doctor                      tools, config and tree health
#
# Layout is <root>/<tier>/<host>/<owner>/<repo>; see bootstrap/workspace.conf.
# Honors TS_DRY_RUN=1 (preview only) everywhere that writes.
#
# --- end of --help text (lines 2-19; keep Show-TsWsHelp in _workspace_cmd.ps1
# --- byte-identical to it) -----------------------------------------------------
# This is the bash half, driven by the `wso` wrapper in dot_zshrc and runnable
# standalone. bootstrap/_workspace.ps1 + _workspace_cmd.ps1 are the Windows twin.
set -euo pipefail

DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
TS_WS_LIB_DIR="$DIR"
export TS_WS_LIB_DIR
# shellcheck source=_workspace.sh
. "$DIR/_workspace.sh"
# ts_tty_prompt lives in _wizard.sh; _config.sh brings INFO/WARN with it.
# shellcheck source=_config.sh
[ -f "$DIR/_config.sh" ] && . "$DIR/_config.sh"
# shellcheck source=_wizard.sh
[ -f "$DIR/_wizard.sh" ] && . "$DIR/_wizard.sh"
# ts_backup_file lives here — the repo's canonical .bak.YYYYMMDD[.N] writer.
# shellcheck source=_cleanup.sh
[ -f "$DIR/_cleanup.sh" ] && . "$DIR/_cleanup.sh"

ROOT=""
if ! ROOT="$(ts_ws_root)"; then
    echo "wso: no workspace found — export WORKSPACE_DIR in ~/.zshrc.local" >&2
    exit 1
fi

# Migrating C: paths from inside WSL works but crawls: every stat crosses the
# 9p filesystem boundary. Warn once; the Windows-native pwsh side is the fast
# path. Same reasoning as the /mnt/c guard in _cleanup.sh.
ts_ws_warn_if_drvfs() {
    case "$ROOT" in
        /mnt/[a-z]/*)
            echo "$WARN $ROOT is a Windows drive seen from WSL. This works, but it is slow and" >&2
            echo "$WARN metadata-heavy. Prefer running 'wso $1' from PowerShell on Windows." >&2
            ;;
    esac
}

ts_ws_confirm() {
    local prompt="$1" ans
    [ "${TS_WS_YES:-}" = "1" ] && return 0
    ans="$(ts_tty_prompt "$prompt")"
    case "$ans" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

# ------------------------------------------------------------------ status ----

cmd_status() {
    local only_dirty=0 org_filter="" d st dirty unpushed stashes head origin
    local n=0 nd=0 nu=0 ndet=0 nnr=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --dirty) only_dirty=1; shift ;;
            --org)   org_filter="${2:-}"; shift 2 ;;
            *) echo "wso status: unknown option: $1" >&2; return 2 ;;
        esac
    done
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        case "$d" in */.git) continue ;; esac
        [ -n "$org_filter" ] && case "$d" in *"/$org_filter/"*) ;; *) continue ;; esac
        n=$((n + 1))
        st="$(ts_ws_git_state "$d")"
        dirty="$(printf '%s' "$st" | cut -f1)"
        unpushed="$(printf '%s' "$st" | cut -f2)"
        stashes="$(printf '%s' "$st" | cut -f3)"
        head="$(printf '%s' "$st" | cut -f4)"
        origin="$(ts_ws_origin "$d")"
        [ "$dirty" -gt 0 ] && nd=$((nd + 1))
        [ "$unpushed" -gt 0 ] && nu=$((nu + 1))
        [ "$head" = "DETACHED" ] && ndet=$((ndet + 1))
        [ -z "$origin" ] && nnr=$((nnr + 1))
        local flags=""
        [ "$dirty" -gt 0 ]    && flags="$flags ${dirty} dirty"
        [ "$unpushed" -gt 0 ] && flags="$flags ${unpushed} unpushed"
        [ "$stashes" -gt 0 ]  && flags="$flags ${stashes} stash"
        [ "$head" = "DETACHED" ] && flags="$flags DETACHED"
        [ -z "$origin" ] && flags="$flags no-remote"
        if [ -n "$flags" ]; then
            printf '%-58s %s\n' "${d#"$ROOT"/}" "${flags# }"
        elif [ "$only_dirty" -eq 0 ] && [ "${TS_WS_VERBOSE:-}" = "1" ]; then
            printf '%-58s ok\n' "${d#"$ROOT"/}"
        fi
    done < <(ts_ws_all_repos)
    echo "--"
    printf '%d repos   %d dirty   %d unpushed   %d detached   %d no-remote\n' \
        "$n" "$nd" "$nu" "$ndet" "$nnr"
}

# Repos in the organised tree, plus anything still sitting in a legacy root.
ts_ws_all_repos() {
    ts_ws_managed_repos "src public archive local"
    local d
    while IFS= read -r d; do
        if [ -e "$d/.git" ]; then printf '%s\n' "$d"; fi
    done < <(ts_ws_scan_candidates)
    return 0
}

# -------------------------------------------------------------------- plan ----

# Emit the full migration plan as TSV: status<TAB>src<TAB>dest<TAB>note.
# status is one of: move, skip-exists, conflict, blocked.
ts_ws_build_plan() {
    local d out tier rel note dest
    local -a seen_dest=() seen_src=()
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        out="$(ts_ws_dest_for "$d")"
        tier="$(printf '%s' "$out" | cut -f1)"
        rel="$(printf '%s' "$out" | cut -f2)"
        note="$(printf '%s' "$out" | cut -f3)"
        if [ -z "$rel" ]; then
            printf 'blocked\t%s\t\t%s\n' "$d" "$note"
            continue
        fi
        dest="$ROOT/$rel"
        if [ "$d" = "$dest" ]; then
            printf 'inplace\t%s\t%s\t%s\n' "$d" "$dest" "already correct"
            continue
        fi
        if [ -e "$dest" ]; then
            printf 'conflict\t%s\t%s\t%s\n' "$d" "$dest" "destination already exists${note:+; $note}"
            continue
        fi
        printf 'move\t%s\t%s\t%s\n' "$d" "$dest" "$note"
    done < <(ts_ws_scan_candidates)
    return 0
}

# Two different sources wanting one destination is the diverged-duplicate case.
# Mark every member so neither is moved and the pair is obvious.
ts_ws_mark_dupes() {
    awk -F'\t' 'BEGIN{OFS="\t"}
        { line[NR]=$0; st[NR]=$1; dst[NR]=$3; if ($1=="move") c[$3]++ }
        END{ for (i=1;i<=NR;i++) {
                if (st[i]=="move" && c[dst[i]]>1) { split(line[i],f,"\t");
                    print "conflict", f[2], f[3], "two sources claim this path — resolve by hand" }
                else print line[i] } }'
}

cmd_plan() {
    local plan movec=0 conflictc=0 blockedc=0 inplacec=0
    plan="$(ts_ws_build_plan | ts_ws_mark_dupes)"
    echo
    echo "=============================================================================="
    echo " Workspace migration plan"
    echo " Root: $ROOT"
    echo " Mode: ${1:-DRY RUN — nothing is moved}"
    echo "=============================================================================="
    local tier
    for tier in src public local scratch; do
        local block
        # Anchor on the full destination prefix rather than a bare "/src"
        # substring: an owner or repo name containing a tier word would
        # otherwise be reported under the wrong heading.
        block="$(printf '%s\n' "$plan" | awk -F'\t' -v pfx="$ROOT/$tier/" \
            '$1=="move" && substr($3, 1, length(pfx))==pfx')"
        [ -n "$block" ] || continue
        echo
        echo "-- $tier --------------------------------------------------------------"
        printf '%s\n' "$block" | while IFS=$'\t' read -r _ s dd nn; do
            printf '   %-46s <- %s\n' "${dd#"$ROOT"/}" "$s"
            if [ -n "$nn" ]; then printf '      note: %s\n' "$nn"; fi
        done
    done
    local conflicts
    conflicts="$(printf '%s\n' "$plan" | awk -F'\t' '$1=="conflict" || $1=="blocked"')"
    if [ -n "$conflicts" ]; then
        echo
        echo "-- BLOCKED ------------------------------------------------------------"
        printf '%s\n' "$conflicts" | while IFS=$'\t' read -r _ s dd nn; do
            printf '   %-46s %s\n' "$(basename -- "$s")" "$nn"
            printf '      at: %s\n' "$s"
        done
        echo
        echo "   Resolve these by hand, then re-run. Nothing above was moved."
    fi
    movec="$(printf '%s\n' "$plan" | awk -F'\t' '$1=="move"' | grep -c . || true)"
    conflictc="$(printf '%s\n' "$plan" | awk -F'\t' '$1=="conflict"' | grep -c . || true)"
    blockedc="$(printf '%s\n' "$plan" | awk -F'\t' '$1=="blocked"' | grep -c . || true)"
    inplacec="$(printf '%s\n' "$plan" | awk -F'\t' '$1=="inplace"' | grep -c . || true)"
    echo
    printf '%s ready, %s conflicted, %s blocked, %s already correct\n' \
        "$movec" "$conflictc" "$blockedc" "$inplacec"
    echo
    TS_WS_PLAN="$plan"
}

# ----------------------------------------------------------------- migrate ----

cmd_migrate() {
    local fix_remotes=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --fix-remotes) fix_remotes=1; shift ;;
            *) echo "wso migrate: unknown option: $1" >&2; return 2 ;;
        esac
    done
    ts_ws_warn_if_drvfs migrate
    cmd_plan "EXECUTE"
    local plan="$TS_WS_PLAN" movec
    movec="$(printf '%s\n' "$plan" | awk -F'\t' '$1=="move"' | grep -c . || true)"
    if [ "$movec" -eq 0 ]; then echo "$INFO Nothing to move."; return 0; fi
    if [ "${TS_DRY_RUN:-}" = "1" ]; then
        echo "$INFO [dry-run] would move $movec repo(s); nothing changed."
        return 0
    fi
    ts_ws_confirm "Move $movec repo(s)? Working trees, stashes and untracked files are preserved. [y/N]: " \
        || { echo "$INFO Migration cancelled; nothing moved."; return 0; }

    local log moved=0 failed=0 s dd
    log="$(ts_ws_new_run_log migrate)"
    while IFS=$'\t' read -r st s dd _; do
        [ "$st" = "move" ] || continue
        if ts_ws_move "$s" "$dd"; then
            echo "$INFO moved $(basename -- "$s") -> ${dd#"$ROOT"/}"
            printf 'moved\t%s\t%s\n' "$(ts_ws_log_rel "$s" "$ROOT")" "$(ts_ws_log_rel "$dd" "$ROOT")" >> "$log"
            moved=$((moved + 1))
            [ "$fix_remotes" -eq 1 ] && ts_ws_fix_remote "$dd"
        else
            printf 'failed\t%s\t%s\n' "$(ts_ws_log_rel "$s" "$ROOT")" "$(ts_ws_log_rel "$dd" "$ROOT")" >> "$log"
            failed=$((failed + 1))
        fi
    done < <(printf '%s\n' "$plan")
    echo
    printf '%s %d moved, %d failed. Log: %s\n' "$INFO" "$moved" "$failed" "$log"
    echo "$INFO Source roots were NOT deleted. Verify, then remove the empty ones by hand."
}

# Rewrite origin to the configured scheme and canonical owner. Only ever
# touches repos whose owner you control; public/ clones are left alone because
# you have no push access there and the scheme is the upstream's business.
ts_ws_fix_remote() {
    local dir="$1" origin parsed host owner repo canon tier scheme want
    origin="$(ts_ws_origin "$dir")"
    [ -n "$origin" ] || return 0
    parsed="$(ts_ws_parse_remote "$origin")" || return 0
    host="$(printf '%s' "$parsed" | cut -f1)"
    owner="$(printf '%s' "$parsed" | cut -f2)"
    repo="$(printf '%s' "$parsed" | cut -f3)"
    canon="$(ts_ws_canon_owner "$owner")"
    tier="$(ts_ws_tier_for_owner "$canon")"
    if [ "$tier" = "src" ]; then scheme="$(ts_ws_setting scheme_own ssh)"
    else scheme="$(ts_ws_setting scheme_public preserve)"; fi
    want="$(ts_ws_build_remote "$scheme" "$host" "$canon" "$repo" "$origin")"
    [ "$want" = "$origin" ] && return 0
    if [ "${TS_DRY_RUN:-}" = "1" ]; then
        echo "$INFO [dry-run] remote $origin -> $want"
        return 0
    fi
    git -C "$dir" remote set-url origin "$want" \
        && echo "$INFO   remote: $origin -> $want"
    # Reported, never fatal: one failed set-url must not abort a migration that
    # has already moved repos successfully.
    return 0
}

# -------------------------------------------------------------------- sync ----

# Fast-forward only, and never on a dirty tree. A ff-only pull cannot destroy
# uncommitted work — it just refuses — so the failures are the output that
# matters: they are the short list of repos that need a human.
ts_ws_sync_one() {
    local d st dirty head
    d="$1"
    st="$(ts_ws_git_state "$d")"
    dirty="$(printf '%s' "$st" | cut -f1)"
    head="$(printf '%s' "$st" | cut -f4)"
    local rel="${d#"$ROOT"/}"
    if [ -z "$(ts_ws_origin "$d")" ]; then
        printf '%-58s %s\n' "$rel" "skipped (no remote)"; return 0
    fi
    if [ "$head" = "DETACHED" ]; then
        printf '%-58s %s\n' "$rel" "skipped (detached HEAD)"; return 0
    fi
    if [ "$dirty" -gt 0 ]; then
        printf '%-58s %s\n' "$rel" "skipped ($dirty uncommitted)"; return 0
    fi
    if ! git -C "$d" fetch --quiet --prune 2>/dev/null; then
        printf '%-58s %s\n' "$rel" "FETCH FAILED"; return 0
    fi
    local before after
    before="$(git -C "$d" rev-parse HEAD 2>/dev/null || echo x)"
    if git -C "$d" merge --ff-only --quiet '@{u}' 2>/dev/null; then
        after="$(git -C "$d" rev-parse HEAD 2>/dev/null || echo x)"
        if [ "$before" = "$after" ]; then
            [ "${TS_WS_VERBOSE:-}" = "1" ] && printf '%-58s %s\n' "$rel" "up to date"
        else
            printf '%-58s %s\n' "$rel" "fast-forwarded"
        fi
    else
        if git -C "$d" rev-parse '@{u}' >/dev/null 2>&1; then
            printf '%-58s %s\n' "$rel" "SKIPPED (diverged — needs you)"
        else
            printf '%-58s %s\n' "$rel" "skipped (no upstream)"
        fi
    fi
    return 0
}

cmd_sync() {
    local org_filter="" d
    while [ $# -gt 0 ]; do
        case "$1" in
            --org) org_filter="${2:-}"; shift 2 ;;
            *) echo "wso sync: unknown option: $1" >&2; return 2 ;;
        esac
    done
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        [ -n "$org_filter" ] && case "$d" in *"/$org_filter/"*) ;; *) continue ;; esac
        ts_ws_sync_one "$d"
    done < <(ts_ws_managed_repos "src public local")
    ts_ws_report_missing
}

# What exists in your orgs but not on this machine. Reported, never cloned —
# putting 100 repos on a laptop is a decision, not a default.
ts_ws_report_missing() {
    command -v gh >/dev/null 2>&1 || return 0
    local owner missing=0 line repo host
    host="$(ts_ws_setting host_default github.com)"
    for owner in $(ts_ws_own_owners); do
        while IFS= read -r repo; do
            [ -n "$repo" ] || continue
            [ -d "$ROOT/src/$host/$owner/$repo" ] && continue
            [ -d "$ROOT/archive/$host/$owner/$repo" ] && continue
            missing=$((missing + 1))
            if [ "$missing" -le 20 ]; then printf '   missing: %s/%s\n' "$owner" "$repo"; fi
        done < <(gh repo list "$owner" --limit 500 --json name -q '.[].name' 2>/dev/null)
    done
    if [ "$missing" -gt 0 ]; then
        echo "--"
        printf '%d repo(s) in your orgs are not on this machine. `wso synceverything` clones them.\n' "$missing"
    fi
    return 0
}

cmd_synceverything() {
    command -v gh >/dev/null 2>&1 || {
        echo "wso: gh not found — needed to enumerate your orgs. Install it (wso doctor lists how)." >&2
        return 1
    }
    cmd_sync
    local owner repo host cloned=0
    host="$(ts_ws_setting host_default github.com)"
    for owner in $(ts_ws_own_owners); do
        while IFS= read -r repo; do
            [ -n "$repo" ] || continue
            local dest="$ROOT/src/$host/$owner/$repo"
            [ -d "$dest" ] && continue
            [ -d "$ROOT/archive/$host/$owner/$repo" ] && continue
            if [ "${TS_DRY_RUN:-}" = "1" ]; then
                echo "$INFO [dry-run] would clone $owner/$repo"; continue
            fi
            mkdir -p -- "$(dirname -- "$dest")"
            local url
            url="$(ts_ws_build_remote "$(ts_ws_setting scheme_own ssh)" "$host" "$owner" "$repo" "")"
            if git clone --quiet "$url" "$dest"; then
                echo "$INFO cloned $owner/$repo"; cloned=$((cloned + 1))
            else
                echo "$WARN failed to clone $owner/$repo" >&2
            fi
        done < <(gh repo list "$owner" --limit 500 --json name -q '.[].name' 2>/dev/null)
    done
    printf '%s %d cloned.\n' "$INFO" "$cloned"
}

# --------------------------------------------------------------------- get ----

cmd_get() {
    local spec="${1:-}"
    [ -n "$spec" ] || { echo "usage: wso get <url|owner/repo>" >&2; return 2; }
    local host owner repo parsed
    if parsed="$(ts_ws_parse_remote "$spec")"; then
        host="$(printf '%s' "$parsed" | cut -f1)"
        owner="$(printf '%s' "$parsed" | cut -f2)"
        repo="$(printf '%s' "$parsed" | cut -f3)"
    else
        case "$spec" in
            */*) host="$(ts_ws_setting host_default github.com)"
                 owner="${spec%/*}"; repo="${spec##*/}" ;;
            *) echo "wso get: cannot parse '$spec' (expected a URL or owner/repo)" >&2; return 2 ;;
        esac
    fi
    local canon tier dest scheme url
    canon="$(ts_ws_canon_owner "$owner")"
    tier="$(ts_ws_tier_for_owner "$canon")"
    dest="$ROOT/$tier/$host/$canon/$repo"
    [ -d "$dest" ] && { echo "$INFO already here: $dest"; printf '%s\n' "$dest"; return 0; }
    if [ "$tier" = "src" ]; then scheme="$(ts_ws_setting scheme_own ssh)"
    else scheme="$(ts_ws_setting scheme_public preserve)"; fi
    url="$(ts_ws_build_remote "$scheme" "$host" "$canon" "$repo" "$spec")"
    [ -n "$url" ] || url="$spec"
    if [ "${TS_DRY_RUN:-}" = "1" ]; then
        echo "$INFO [dry-run] would clone $url -> $dest"; return 0
    fi
    mkdir -p -- "$(dirname -- "$dest")"
    git clone "$url" "$dest" && printf '%s\n' "$dest"
}

# ----------------------------------------------------------------- orphans ----

cmd_orphans() {
    local do_push=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --push) do_push=1; shift ;;
            *) echo "wso orphans: unknown option: $1" >&2; return 2 ;;
        esac
    done
    local d found=0
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        [ -e "$d/.git" ] || continue
        [ -z "$(ts_ws_origin "$d")" ] || continue
        found=$((found + 1))
        local commits branches
        commits="$(git -C "$d" rev-list --all --count 2>/dev/null || echo 0)"
        branches="$(git -C "$d" for-each-ref --format='%(refname:short)' refs/heads 2>/dev/null | tr '\n' ' ')"
        printf '%-44s %6s commits   %s\n' "${d#"$ROOT"/}" "$commits" "${branches% }"
        if [ "$do_push" -eq 1 ]; then ts_ws_push_orphan "$d"; fi
    done < <(ts_ws_all_repos)
    if [ "$found" -eq 0 ]; then
        echo "$INFO No repos without a remote. Nothing here exists on only one disk."
    else
        echo "--"
        printf '%d repo(s) exist on this disk only. `wso orphans --push` creates a private remote for each.\n' "$found"
    fi
}

# Creating a GitHub repo is outward-facing and not trivially undone, so this
# confirms per repo and shows the authorship first — a big history with no
# remote is usually a clone whose origin was stripped, and that should not be
# pushed into a company org without a look.
ts_ws_push_orphan() {
    local d="$1" name owner
    name="$(basename -- "$d")"
    command -v gh >/dev/null 2>&1 || { echo "$WARN gh not found; cannot create remotes." >&2; return 1; }
    echo
    echo "$INFO $d"
    echo "     authors: $(git -C "$d" log --format='%ae' 2>/dev/null | sort -u | head -5 | tr '\n' ' ')"
    owner="$(ts_tty_prompt "     owner for this repo (blank = skip): ")"
    [ -n "$owner" ] || { echo "     skipped."; return 0; }
    if [ "${TS_DRY_RUN:-}" = "1" ]; then
        echo "$INFO [dry-run] would run: gh repo create $owner/$name --private --source $d --push"
        return 0
    fi
    ts_ws_confirm "     create PRIVATE $owner/$name and push all branches? [y/N]: " || {
        echo "     skipped."; return 0; }
    ( cd "$d" && gh repo create "$owner/$name" --private --source . --push && git push --all ) \
        && echo "$INFO pushed $owner/$name"
    # One repo failing to publish must not abort the walk over the others.
    return 0
}

# ----------------------------------------------------------------- archive ----

cmd_archive() {
    local days=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --days) days="${2:-}"; shift 2 ;;
            *) echo "wso archive: unknown option: $1" >&2; return 2 ;;
        esac
    done
    local default_days
    default_days="$(ts_ws_setting archive_days 90)"
    if [ -z "$days" ]; then
        days="${TS_WS_DAYS:-}"
        [ -n "$days" ] || days="$(ts_tty_prompt "Archive repos untouched for how many days? [$default_days]: ")"
        [ -n "$days" ] || days="$default_days"
    fi
    case "$days" in ''|*[!0-9]*) echo "wso archive: --days needs a number, got '$days'" >&2; return 2 ;; esac

    echo "$INFO Scanning src/ for repos untouched for $days+ days…"
    local -a paths=() labels=() ticks=() whys=()
    local d act age why
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        act="$(ts_ws_last_activity "$d")"
        age="$(ts_ws_days_since "$act")"
        [ "$age" -ge "$days" ] || continue
        paths+=("$d")
        if ts_ws_is_safe_to_archive "$d"; then
            why=""
            ticks+=(1)
            labels+=("last activity $(ts_ws_fmt_date "$act")  (${age}d ago)")
        else
            why="$TS_WS_UNSAFE_WHY"
            ticks+=(0)
            labels+=("last activity $(ts_ws_fmt_date "$act")  (${age}d ago)  — HELD: $why")
        fi
        whys+=("$why")
    done < <(ts_ws_managed_repos src)

    local n=${#paths[@]}
    if [ "$n" -eq 0 ]; then
        echo "$INFO Nothing in src/ is older than $days days. That is the correct outcome most months."
        return 0
    fi

    local i idx ans mark
    while true; do
        echo
        echo "$INFO Cold repos (${days}+ days). Ticked ones will move to archive/:"
        for i in $(seq 0 $((n - 1))); do
            mark=" "; [ "${ticks[$i]}" = "1" ] && mark="x"
            printf '  [%s] %2d) %s\n         %s\n' "$mark" "$((i + 1))" "${paths[$i]#"$ROOT"/}" "${labels[$i]}"
        done
        echo "      HELD repos have uncommitted, unpushed or stashed work and cannot be ticked."
        ans="$(ts_tty_prompt 'Toggle a number, [a]ll safe, [n]one, Enter to continue, [s]kip: ')"
        case "$ans" in
            "")        break ;;
            s|S)       echo "$INFO Archive skipped."; return 0 ;;
            a|A)       for i in $(seq 0 $((n - 1))); do [ -z "${whys[$i]}" ] && ticks[$i]=1; done ;;
            no|NO|n|N) for i in $(seq 0 $((n - 1))); do ticks[$i]=0; done ;;
            *[!0-9]*)  echo "  ? enter a number, a, n, s, or Enter" ;;
            *)         idx=$((ans - 1))
                       if [ "$idx" -ge 0 ] && [ "$idx" -lt "$n" ]; then
                           if [ -n "${whys[$idx]}" ]; then
                               echo "  ! ${paths[$idx]##*/} is held: ${whys[$idx]}. Commit or push it first."
                           else
                               [ "${ticks[$idx]}" = "1" ] && ticks[$idx]=0 || ticks[$idx]=1
                           fi
                       fi ;;
        esac
    done

    local selected=0
    for i in $(seq 0 $((n - 1))); do [ "${ticks[$i]}" = "1" ] && selected=$((selected + 1)); done
    [ "$selected" -eq 0 ] && { echo "$INFO Nothing selected; nothing archived."; return 0; }

    if [ "${TS_DRY_RUN:-}" = "1" ]; then
        echo "$INFO [dry-run] would archive $selected repo(s):"
        for i in $(seq 0 $((n - 1))); do [ "${ticks[$i]}" = "1" ] && echo "    ${paths[$i]#"$ROOT"/}"; done
        return 0
    fi
    ts_ws_confirm "Archive $selected repo(s)? They move to archive/ and can be restored with 'wso unarchive'. [y/N]: " \
        || { echo "$INFO Cancelled; nothing archived."; return 0; }

    local log dest rel done_n=0
    log="$(ts_ws_new_run_log archive)"
    for i in $(seq 0 $((n - 1))); do
        [ "${ticks[$i]}" = "1" ] || continue
        d="${paths[$i]}"
        # Re-check immediately before moving: the checklist may have been open a
        # while, and a repo can become dirty between the scan and the confirm.
        if ! ts_ws_is_safe_to_archive "$d"; then
            echo "$WARN ${d##*/} became unsafe ($TS_WS_UNSAFE_WHY); skipped."; continue
        fi
        rel="${d#"$ROOT"/src/}"
        dest="$ROOT/archive/$rel"
        if ts_ws_move "$d" "$dest"; then
            echo "$INFO archived ${d#"$ROOT"/} -> archive/$rel"
            printf 'archived\t%s\t%s\n' "$(ts_ws_log_rel "$d" "$ROOT")" "$(ts_ws_log_rel "$dest" "$ROOT")" >> "$log"
            done_n=$((done_n + 1))
        fi
    done
    printf '%s %d archived. Log: %s\n' "$INFO" "$done_n" "$log"
}

# --------------------------------------------------------------- unarchive ----

cmd_unarchive() {
    local mode="pick" name="" org="" update=0
    while [ $# -gt 0 ]; do
        case "$1" in
            --all)       mode="all"; shift ;;
            --undo-last) mode="undo"; shift ;;
            --org)       mode="org"; org="${2:-}"; shift 2 ;;
            --update)    update=1; shift ;;
            -*) echo "wso unarchive: unknown option: $1" >&2; return 2 ;;
            *)  mode="name"; name="$1"; shift ;;
        esac
    done
    [ -d "$ROOT/archive" ] || { echo "$INFO Nothing archived on this machine."; return 0; }

    local -a picks=()
    case "$mode" in
        undo)
            local log
            log="$(ts_ws_latest_run_log archive)" || { echo "$INFO No archive run to undo."; return 0; }
            echo "$INFO Reversing $log"
            local s dd
            while IFS=$'\t' read -r st s dd; do
                [ "$st" = "archived" ] || continue
                # Logged relative and forward-slashed, so a run written by the
                # PowerShell side on the same tree resolves here too.
                dd="$(ts_ws_log_abs "$dd" "$ROOT")"
                if [ -d "$dd" ]; then picks+=("$dd"); fi
            done < "$log"
            ;;
        all)  while IFS= read -r d; do picks+=("$d"); done < <(ts_ws_managed_repos archive) ;;
        org)  while IFS= read -r d; do
                  case "$d" in */"$org"/*) picks+=("$d") ;; esac
              done < <(ts_ws_managed_repos archive) ;;
        name) while IFS= read -r d; do
                  case "$(basename -- "$d")" in *"$name"*) picks+=("$d") ;; esac
              done < <(ts_ws_managed_repos archive) ;;
        pick)
            command -v fzf >/dev/null 2>&1 || {
                echo "wso unarchive: fzf not installed — use 'wso unarchive <name>' or --org/--all." >&2
                return 1; }
            local sel
            sel="$(ts_ws_managed_repos archive | sed "s|^$ROOT/archive/||" \
                   | fzf --multi --height 60% --reverse --prompt 'unarchive> ' \
                         --header 'TAB=select multiple, enter=restore')" || return 0
            [ -n "$sel" ] || return 0
            while IFS= read -r d; do
                if [ -n "$d" ]; then picks+=("$ROOT/archive/$d"); fi
            done <<< "$sel"
            ;;
    esac

    local n=${#picks[@]}
    [ "$n" -eq 0 ] && { echo "$INFO Nothing matched."; return 0; }
    echo "$INFO Restoring $n repo(s) to src/:"
    local d rel dest restored=0
    for d in "${picks[@]}"; do printf '    %s\n' "${d#"$ROOT"/}"; done
    if [ "${TS_DRY_RUN:-}" = "1" ]; then echo "$INFO [dry-run] nothing moved."; return 0; fi
    ts_ws_confirm "Restore $n repo(s)? [y/N]: " || { echo "$INFO Cancelled."; return 0; }

    for d in "${picks[@]}"; do
        rel="${d#"$ROOT"/archive/}"
        dest="$ROOT/src/$rel"
        if ts_ws_move "$d" "$dest"; then
            echo "$INFO restored src/$rel"
            restored=$((restored + 1))
            if [ "$update" -eq 1 ]; then ts_ws_sync_one "$dest"; fi
        fi
    done
    printf '%s %d restored.\n' "$INFO" "$restored"
}

# ---------------------------------------------------------------- identity ----

# Writes the per-machine git rules. These cannot be tracked: the paths are
# machine-specific and the emails are personal, and CLAUDE.md forbids either in
# the source tree.
cmd_identity() {
    local gitdir="${XDG_CONFIG_HOME:-$HOME/.config}/git"
    local out="$gitdir/terminal-stack-workspace.gitconfig"
    local host owner root_fwd
    host="$(ts_ws_setting host_default github.com)"
    root_fwd="$(printf '%s' "$ROOT" | sed 's|\\|/|g')"
    mkdir -p -- "$gitdir"

    local tmp
    tmp="$(mktemp)"
    {
        echo "# Generated by 'wso identity'. Per-machine — do not commit."
        echo "# Regenerate any time; your ~/.gitconfig is not touched beyond one include.path."
        echo
        echo "[ghq]"
        echo "  root = $root_fwd/public"
        for owner in $(ts_ws_own_owners); do
            echo "[ghq \"https://$host/$owner\"]"
            echo "  root = $root_fwd/src"
        done
    } > "$tmp"

    for owner in $(ts_ws_own_owners); do
        local idf="$gitdir/identity-$owner" name email key cur_name cur_email
        if [ -f "$idf" ]; then
            cur_name="$(git config -f "$idf" user.name 2>/dev/null || true)"
            cur_email="$(git config -f "$idf" user.email 2>/dev/null || true)"
        else
            cur_name="$(git config --global user.name 2>/dev/null || true)"
            cur_email=""
        fi
        echo
        echo "$INFO Identity for $owner"
        name="$(ts_tty_prompt "  name  [$cur_name]: ")";  [ -n "$name" ] || name="$cur_name"
        email="$(ts_tty_prompt "  email [$cur_email]: ")"; [ -n "$email" ] || email="$cur_email"
        key="$(ts_tty_prompt "  signing key (blank = none): ")"
        if [ -n "$email" ]; then
            [ -f "$idf" ] && ts_backup_file "$idf"
            {
                echo "# Generated by 'wso identity' — per-machine, do not commit."
                echo "[user]"
                echo "  name = $name"
                echo "  email = $email"
                [ -n "$key" ] && echo "  signingkey = $key"
            } > "$idf"
            echo "$INFO wrote $idf"
            {
                echo
                echo "[includeIf \"gitdir:$root_fwd/src/$host/$owner/\"]"
                echo "  path = $idf"
                echo "[includeIf \"gitdir:$root_fwd/archive/$host/$owner/\"]"
                echo "  path = $idf"
            } >> "$tmp"
        else
            echo "$WARN no email given for $owner; skipped."
        fi
    done

    [ -f "$out" ] && ts_backup_file "$out"
    mv "$tmp" "$out"
    echo "$INFO wrote $out"
    if git config --global --get-all include.path 2>/dev/null | grep -qF "terminal-stack-workspace.gitconfig"; then
        echo "$INFO git include.path already set"
    else
        git config --global --add include.path "$out"
        echo "$INFO added git include.path -> $out"
    fi
}

# ------------------------------------------------------------------ doctor ----

cmd_doctor() {
    local issues=0 t p
    echo "$INFO Workspace"
    printf '  root            %s\n' "$ROOT"
    for t in src public archive local scratch; do
        if [ -d "$ROOT/$t" ]; then
            printf '  %-15s %s repo(s)\n' "$t/" "$(ts_ws_managed_repos "$t" 2>/dev/null | grep -c . || echo 0)"
        else
            printf '  %-15s (not created yet)\n' "$t/"
        fi
    done
    echo
    echo "$INFO Config"
    ts_ws_conf_files | sed 's/^/  /'
    printf '  orgs            %s\n' "$(ts_ws_own_owners)"
    printf '  renames         %s\n' "${TS_WS_RENAMES# }"
    printf '  archive_days    %s\n' "$(ts_ws_setting archive_days 90)"
    printf '  scheme_own      %s\n' "$(ts_ws_setting scheme_own ssh)"
    echo
    echo "$INFO Tools"
    for t in git gh ghq fzf lazygit; do
        if p="$(command -v "$t" 2>/dev/null)"; then
            printf '  %-8s ok    %s\n' "$t" "$p"
        else
            printf '  %-8s MISSING — install it: ts-config apps\n' "$t"
            issues=$((issues + 1))
        fi
    done
    if command -v gh >/dev/null 2>&1; then
        if gh auth status >/dev/null 2>&1; then echo "  gh auth  ok"
        else echo "  gh auth  NOT LOGGED IN — run: gh auth login"; issues=$((issues + 1)); fi
    fi
    echo
    echo "$INFO Git"
    if git config --global --get-all include.path 2>/dev/null | grep -qF "terminal-stack-workspace.gitconfig"; then
        echo "  identity rules  ok"
    else
        echo "  identity rules  not installed — run: wso identity"
        issues=$((issues + 1))
    fi
    printf '  pull.ff         %s\n' "$(git config --get pull.ff 2>/dev/null || echo '(unset — expected "only")')"
    echo
    if [ "$issues" -eq 0 ]; then echo "$INFO All good."; else
        printf '%s %d issue(s) found.\n' "$WARN" "$issues"; return 1
    fi
}

# ---------------------------------------------------------------- dispatch ----

case "${1:-}" in
    ""|status)      shift || true; cmd_status "$@" ;;
    plan)           shift; cmd_plan ;;
    migrate)        shift; cmd_migrate "$@" ;;
    sync)           shift; cmd_sync "$@" ;;
    synceverything) shift; cmd_synceverything "$@" ;;
    archive)        shift; cmd_archive "$@" ;;
    unarchive)      shift; cmd_unarchive "$@" ;;
    get)            shift; cmd_get "$@" ;;
    orphans)        shift; cmd_orphans "$@" ;;
    identity)       shift; cmd_identity ;;
    doctor)         shift; cmd_doctor ;;
    -h|--help|help) sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) echo "wso: unknown command '$1' (try: status, plan, migrate, sync, archive, unarchive, get, orphans, identity, doctor, --help)" >&2; exit 2 ;;
esac
