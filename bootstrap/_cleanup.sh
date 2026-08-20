#!/usr/bin/env bash
# _cleanup.sh — find and (with confirmation) remove old terminal-stack clones and
# retired leftover files. Sourced by the installers (after the fresh clone exists)
# and available standalone. Drives an interactive pre-ticked checklist; never
# touches the keep-list (per-machine overrides, the personal doc layer, rollback
# state). Honors TS_DRY_RUN=1 (preview only).
#
# This file is sourced, not executed. Do not `exit`; return non-zero instead.

# Pull in INFO/WARN + ts_tty_prompt when sourced standalone (installer context).
if ! command -v ts_tty_prompt >/dev/null 2>&1; then
    _ts_cleanup_dir="$(dirname -- "${BASH_SOURCE[0]}")"
    # shellcheck source=_config.sh
    [ -f "$_ts_cleanup_dir/_config.sh" ] && . "$_ts_cleanup_dir/_config.sh"
    # shellcheck source=_wizard.sh
    [ -f "$_ts_cleanup_dir/_wizard.sh" ] && . "$_ts_cleanup_dir/_wizard.sh"
fi
: "${INFO:=$'\033[1;34m==>\033[0m'}"
: "${WARN:=$'\033[1;33m!!\033[0m'}"

# CANONICAL CLONE CANDIDATE LIST (bash master) — canonical location first, then
# legacy defaults. Keep in sync with docs/decisions.md § "Runtime clone location"
# and the sibling replicas: dot_zshrc _ts_clone_candidates, profile
# Get-TsCloneCandidates, bootstrap/_cleanup.ps1 Get-TsCleanupCloneCandidates.
# Globs expand later in ts_find_old_clones; non-existent paths are filtered there.
ts_clone_candidates() {
    local canon=""
    command -v ts_canonical_clone_dir >/dev/null 2>&1 && canon="$(ts_canonical_clone_dir 2>/dev/null || true)"
    [ -n "$canon" ] && printf '%s\n' "$canon"
    printf '%s\n' \
        "$HOME/code/terminal-stack" \
        "$HOME/terminal-stack" \
        "$HOME/Workspace/terminal-stack" \
        "$HOME/workspace/terminal-stack" \
        "$HOME/Documents/Workspace/terminal-stack" \
        "$HOME/.local/share/chezmoi"
    if [ -r /proc/version ] && grep -qi microsoft /proc/version 2>/dev/null; then
        printf '%s\n' \
            "/mnt/c/Users/*/terminal-stack" \
            "/mnt/c/DATA/Workspace/terminal-stack"
    fi
}

# True when <dir> is a git clone of terminal-stack (remote URL mentions it).
ts_is_stack_clone() {
    local d="$1"
    [ -d "$d/.git" ] || return 1
    git -C "$d" config --get remote.origin.url 2>/dev/null | grep -qi 'terminal-stack'
}

# True when <path> is a DEV clone: it sits at a wso workspace tier path
# (<tier>/<host>/<owner>/<repo>, host must contain a dot). Dev clones are
# invisible to auto-resolution, move offers and cleanup — the user works there;
# only an explicit TERMINAL_STACK_DIR pin selects one. Master copy — twins:
# dot_zshrc _ts_is_dev_clone, profile/_cleanup.ps1 Test-TsDevClone.
# Safe by construction: ~/.local/share/... ('.local' breaks the /local/ bound)
# and .../AppData/Local/terminal-stack/stack (host segment has no dot) never match.
ts_is_dev_clone() {
    [[ "$1" =~ /(src|public|archive|local|scratch)/[^/]+\.[^/]+/[^/]+/[^/]+/?$ ]]
}

# Canonicalize a path (resolve symlinks/.. when it exists; echo as-is otherwise).
_ts_realpath() { ( cd "$1" 2>/dev/null && pwd -P ) || echo "$1"; }

# Echo stack clones other than <current> (the one we just installed/kept).
ts_find_old_clones() {
    local current="$1" d rp seen=" "
    current="$(_ts_realpath "$current")"
    # Word-split + glob-expand the candidate list intentionally.
    # shellcheck disable=SC2046
    set -- $(ts_clone_candidates)
    for d in "$@"; do
        [ -e "$d" ] || continue
        ts_is_stack_clone "$d" || continue
        ts_is_dev_clone "$d" && continue   # dev checkouts are never "old clones"
        rp="$(_ts_realpath "$d")"
        [ "$rp" = "$current" ] && continue
        case "$seen" in *" $rp "*) continue ;; esac
        seen="$seen$rp "
        echo "$d"
    done
}

# Echo retired/leftover home-dir files as TAB-separated "tick<TAB>path<TAB>label".
# tick=1 → pre-selected (known retired artifact); tick=0 → listed but off by default.
ts_find_stray() {
    local f
    for f in \
        "$HOME/command-reference.md" \
        "$HOME/command-reference.txt" \
        "$HOME/command-reference.html" \
        "$HOME/.local/bin/wzr" \
        "$HOME/.wezterm-ref"; do
        [ -e "$f" ] && printf '1\t%s\tretired terminal-stack artifact\n' "$f"
    done
    # Heuristic: loose top-level *.sh in $HOME that reference the stack. Off by
    # default — provenance is uncertain, so the user opts in per file.
    for f in "$HOME"/*.sh; do
        [ -e "$f" ] || continue
        if grep -qiE 'terminal-stack|sync-windows|chezmoi' "$f" 2>/dev/null; then
            printf '0\t%s\tloose script mentioning terminal-stack (verify first)\n' "$f"
        fi
    done
}

# Back up a file as <path>.bak.YYYYMMDD[.N] before removal (repo convention).
ts_backup_file() {
    local f="$1" stamp base bak n
    [ -e "$f" ] || return 0
    stamp="$(date +%Y%m%d)"
    base="$f.bak.$stamp"; bak="$base"; n=1
    while [ -e "$bak" ]; do bak="$base.$n"; n=$((n+1)); done
    cp -a -- "$f" "$bak" 2>/dev/null && echo "$INFO backed up $f -> $bak"
}

# Interactive cleanup checklist. <current> is the clone to KEEP (never offered).
# Old clones are pre-ticked; retired files pre-ticked; loose scripts unticked.
# Renders the list, lets the user toggle, then confirms before removing anything.
ts_cleanup_menu() {
    local current="${1:-}"
    local -a paths=() labels=() ticks=() kinds=()
    local d tk pth lbl

    local canon=""
    command -v ts_canonical_clone_dir >/dev/null 2>&1 && canon="$(ts_canonical_clone_dir 2>/dev/null || true)"
    while IFS= read -r d; do
        [ -n "$d" ] || continue
        # The canonical runtime location is never offered for deletion.
        [ -n "$canon" ] && [ "$(_ts_realpath "$d")" = "$(_ts_realpath "$canon")" ] && continue
        paths+=("$d")
        case "$d" in
            /mnt/c/*)
                # A clone under /mnt/c is on the Windows side — quite possibly the
                # user's active Windows install or a dev checkout. List it but DON'T
                # pre-tick it: deleting it from WSL would nuke the Windows-side repo.
                labels+=("old clone (Windows-side — verify it isn't your active install) $(git -C "$d" log -1 --format='%h %s' 2>/dev/null | cut -c1-34)")
                ticks+=(0) ;;
            *)
                labels+=("old clone — $(git -C "$d" log -1 --format='%h %s' 2>/dev/null | cut -c1-56)")
                ticks+=(1) ;;
        esac
        kinds+=(clone)
    done < <(ts_find_old_clones "$current")

    while IFS=$'\t' read -r tk pth lbl; do
        [ -n "$pth" ] || continue
        paths+=("$pth"); labels+=("$lbl"); ticks+=("$tk"); kinds+=(file)
    done < <(ts_find_stray)

    local n=${#paths[@]}
    if [ "$n" -eq 0 ]; then
        echo "$INFO Cleanup: no old clones or leftover files found."
        return 0
    fi

    local i idx ans
    while true; do
        echo
        echo "$INFO Old terminal-stack instances / leftover files found:"
        for i in $(seq 0 $((n - 1))); do
            local mark=" "; [ "${ticks[$i]}" = "1" ] && mark="x"
            printf '  [%s] %2d) %s\n         %s\n' "$mark" "$((i + 1))" "${paths[$i]}" "${labels[$i]}"
        done
        echo "      Keep-list files (.zshrc.local, .doc.local, rollback state, command-reference.local.md) are never shown."
        ans="$(ts_tty_prompt 'Toggle a number, [a]ll, [n]one, Enter to continue, [s]kip cleanup: ')"
        case "$ans" in
            "")        break ;;
            s|S)       echo "$INFO Cleanup skipped."; return 0 ;;
            a|A)       for i in $(seq 0 $((n - 1))); do ticks[$i]=1; done ;;
            no|NO|n|N) for i in $(seq 0 $((n - 1))); do ticks[$i]=0; done ;;
            *[!0-9]*)  echo "  ? enter a number, a, n, s, or Enter" ;;
            *)         idx=$((ans - 1))
                       if [ "$idx" -ge 0 ] && [ "$idx" -lt "$n" ]; then
                           [ "${ticks[$idx]}" = "1" ] && ticks[$idx]=0 || ticks[$idx]=1
                       fi ;;
        esac
    done

    local selected=0
    for i in $(seq 0 $((n - 1))); do [ "${ticks[$i]}" = "1" ] && selected=$((selected + 1)); done
    if [ "$selected" -eq 0 ]; then echo "$INFO Nothing selected; cleanup skipped."; return 0; fi

    if [ "${TS_DRY_RUN:-}" = "1" ]; then
        echo "$INFO [dry-run] would remove $selected item(s):"
        for i in $(seq 0 $((n - 1))); do [ "${ticks[$i]}" = "1" ] && echo "    ${paths[$i]}"; done
        return 0
    fi

    ans="$(ts_tty_prompt "Remove $selected selected item(s)? This cannot be undone for clones. [y/N]: ")"
    case "$ans" in y|Y|yes|YES) ;; *) echo "$INFO Cleanup cancelled; nothing removed."; return 0 ;; esac

    local removed=0
    for i in $(seq 0 $((n - 1))); do
        [ "${ticks[$i]}" = "1" ] || continue
        d="${paths[$i]}"
        [ "${kinds[$i]}" = "file" ] && ts_backup_file "$d"
        if rm -rf -- "$d"; then echo "$INFO removed $d"; removed=$((removed + 1))
        else echo "$WARN failed to remove $d"; fi
    done
    echo "$INFO Cleanup: removed $removed item(s)."
}
