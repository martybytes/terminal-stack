#!/usr/bin/env bash
# Claude Code statusLine command — three-line, cross-platform (bash + python3).
# Receives session JSON on stdin. Writes three coloured lines to stdout.
#
# Line 1: <cwd> | <branch> <✓|●> [↑N][↓N] | <owner/repo>
# Line 2: <model> | ctx <pct>% <bar> | 5h <pct>% <bar> <reset> | 7d <pct>% <bar> <reset>
# Line 3: <user@host> | <used_k>/<total_M> tok | cost: $X.XX | +N/-M lines

raw=$(cat)

# ── Python detection ─────────────────────────────────────────────────────────
# python3 on Linux/Mac; python on Windows (where python3 may be the App Store stub).
_py=""
if python3 -c "import sys" >/dev/null 2>&1; then _py=python3
elif python  -c "import sys" >/dev/null 2>&1; then _py=python
fi

# json_get <dot.path> — portable, no jq required.
json_get() {
    [ -z "$_py" ] && { printf ''; return; }
    printf '%s' "$raw" | "$_py" -c "
import json,sys
try:
    v=json.load(sys.stdin)
    for k in '$1'.split('.'):
        v=v.get(k) if isinstance(v,dict) else None
        if v is None: break
    print('' if v is None else v)
except: print('')
" 2>/dev/null
}

# ── Extract JSON fields ───────────────────────────────────────────────────────
cwd=$(json_get cwd)
[ -z "$cwd" ] && cwd=$(json_get workspace.current_dir)
[ -z "$cwd" ] && cwd="$PWD"

model=$(json_get model.display_name)

ctx_window=$(json_get context_window.context_window_size)
ctx_used_pct=$(json_get context_window.used_percentage)
ctx_total_tok=$(json_get context_window.total_input_tokens)

cost_usd=$(json_get cost.total_cost_usd)
lines_added=$(json_get cost.total_lines_added)
lines_removed=$(json_get cost.total_lines_removed)

five_hr_pct=$(json_get rate_limits.five_hour.used_percentage)
five_hr_reset=$(json_get rate_limits.five_hour.resets_at)
seven_day_pct=$(json_get rate_limits.seven_day.used_percentage)
seven_day_reset=$(json_get rate_limits.seven_day.resets_at)

repo_owner=$(json_get workspace.repo.owner)
repo_name=$(json_get workspace.repo.name)

# ── Git: branch + dirty + ahead/behind ───────────────────────────────────────
branch=""; git_status=""
if command -v git &>/dev/null && [ -n "$cwd" ]; then
    branch=$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null || true)
    if [ -n "$branch" ]; then
        porcelain=$(git -C "$cwd" status --porcelain=v2 --branch 2>/dev/null || true)
        # Porcelain v2: "1/2 XY …" (X=staged, Y=worktree), "u …" (unmerged), "? …" (untracked).
        # Clean → "✓"; dirty → "+staged ~modified -deleted ?untracked !conflicts" (non-zero only).
        staged=$(   printf '%s\n' "$porcelain" | grep -cE '^[12] [MTADRC]\.')
        modified=$( printf '%s\n' "$porcelain" | grep -cE '^[12] [.MTADRC][MTADRC]')
        deleted=$(  printf '%s\n' "$porcelain" | grep -cE '^[12] .D')
        untracked=$(printf '%s\n' "$porcelain" | grep -cE '^\?')
        conflicts=$(printf '%s\n' "$porcelain" | grep -cE '^u ')
        parts=""
        [ "$staged"    -gt 0 ] 2>/dev/null && parts="${parts} +${staged}"
        [ "$modified"  -gt 0 ] 2>/dev/null && parts="${parts} ~${modified}"
        [ "$deleted"   -gt 0 ] 2>/dev/null && parts="${parts} -${deleted}"
        [ "$untracked" -gt 0 ] 2>/dev/null && parts="${parts} ?${untracked}"
        [ "$conflicts" -gt 0 ] 2>/dev/null && parts="${parts} !${conflicts}"
        if [ -n "$parts" ]; then git_status="${parts# }"; else git_status="✓"; fi
        # Parse "# branch.ab +N -M" — portable (no grep -P)
        ab=$(printf '%s\n' "$porcelain" | grep '^# branch.ab' | head -1)
        if [ -n "$ab" ]; then
            set -- $ab           # split on whitespace: $3=+N $4=-M
            ahead=${3#+}; behind=${4#-}
            [ "${ahead:-0}"  -gt 0 ] 2>/dev/null && git_status="${git_status} ↑${ahead}"
            [ "${behind:-0}" -gt 0 ] 2>/dev/null && git_status="${git_status} ↓${behind}"
        fi
    fi
fi

# ── Bar renderer (shared by ctx + rate limits) ───────────────────────────────
R=$'\033[0m'
GREY=$'\033[90m'
# make_bar <pct> → "<pct>% <colour><10-seg █/░ bar><reset>"  (green<70 / yellow<90 / red)
make_bar() {
    local pct=$1 filled empty bar="" i c
    pct=${pct%%.*}                                      # floats → int part (0.41 → 0)
    case "$pct" in ''|*[!0-9]*) printf '?'; return;; esac
    [ "$pct" -gt 100 ] && pct=100
    filled=$(( pct * 10 / 100 )); [ "$filled" -gt 10 ] && filled=10
    empty=$(( 10 - filled ))
    i=0; while [ $i -lt "$filled" ]; do bar="${bar}█"; i=$(( i+1 )); done
    i=0; while [ $i -lt "$empty"  ]; do bar="${bar}░"; i=$(( i+1 )); done
    if   [ "$pct" -ge 90 ]; then c=$'\033[1;31m'
    elif [ "$pct" -ge 70 ]; then c=$'\033[1;33m'
    else                          c=$'\033[1;32m'
    fi
    printf '%s%% %s%s%s' "$pct" "$c" "$bar" "$R"
}

ctx_str="?"
# The percentage can arrive as a float ("41.5"); strip the fraction first —
# POSIX [ -ge ] and $(( )) are integer-only and would silently fail to a "?".
ctx_int="${ctx_used_pct%%.*}"
[ -n "$ctx_int" ] && [ "$ctx_int" -ge 0 ] 2>/dev/null && ctx_str=$(make_bar "$ctx_int")

# ── Token display (e.g. 205k/1M tok) ─────────────────────────────────────────
token_str=""
if [ -n "$ctx_total_tok" ] && [ -n "$ctx_window" ] && [ "$ctx_window" -gt 0 ] 2>/dev/null; then
    used_k=$(( ctx_total_tok / 1000 ))
    if [ "$ctx_window" -ge 1000000 ] 2>/dev/null; then
        total_m=$(( ctx_window / 1000000 ))
        token_str="${used_k}k/${total_m}M tok"
    else
        total_k=$(( ctx_window / 1000 ))
        token_str="${used_k}k/${total_k}k tok"
    fi
fi

# ── Cost ──────────────────────────────────────────────────────────────────────
cost_str=""
if [ -n "$cost_usd" ] && [ -n "$_py" ]; then
    cost_str=$(printf '%s' "$cost_usd" | "$_py" -c "
import sys
try: print('\$%.2f' % float(sys.stdin.read().strip()))
except: print('')
" 2>/dev/null)
fi

# ── Lines delta ───────────────────────────────────────────────────────────────
lines_str=""
if [ -n "$lines_added" ] || [ -n "$lines_removed" ]; then
    lines_str="+${lines_added:-0}/-${lines_removed:-0} lines"
fi

# ── Rate limits: ctx-style bars + compact reset countdown ────────────────────
# fmt_reset <unix-ts> → a single coarse unit (e.g. "14m", "2h", "2d"); "" on error.
fmt_reset() {
    local ts="$1"
    [ -z "$ts" ] || [ -z "$_py" ] && { printf ''; return; }
    printf '%s' "$ts" | "$_py" -c "
import sys, time
try:
    r = int(sys.stdin.read().strip()) - int(time.time())
    if r <= 0: print('soon')
    elif r < 3600: print(f'{round(r/60)}m')
    elif r < 86400: print(f'{round(r/3600)}h')
    else: print(f'{round(r/86400)}d')
except: print('')
" 2>/dev/null
}

five_str=""; seven_str=""
if [ -n "$five_hr_pct" ]; then
    five_str="5h $(make_bar "$five_hr_pct")"
    fr=$(fmt_reset "$five_hr_reset"); [ -n "$fr" ] && five_str="${five_str} ${GREY}${fr}${R}"
fi
if [ -n "$seven_day_pct" ]; then
    seven_str="7d $(make_bar "$seven_day_pct")"
    sr=$(fmt_reset "$seven_day_reset"); [ -n "$sr" ] && seven_str="${seven_str} ${GREY}${sr}${R}"
fi

# ── Identity ──────────────────────────────────────────────────────────────────
host=$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo "?")
user=$(whoami 2>/dev/null || id -un 2>/dev/null || echo "?")

# ── Assemble ──────────────────────────────────────────────────────────────────
SEP=" | "

line1="$cwd"
if [ -n "$branch" ]; then
    line1="${line1}${SEP}${branch} ${git_status}"
fi
[ -n "$repo_owner" ] && [ -n "$repo_name" ] && line1="${line1}${SEP}${repo_owner}/${repo_name}"

line2="${model:-?}${SEP}ctx ${ctx_str}"
[ -n "$five_str"  ] && line2="${line2}${SEP}${five_str}"
[ -n "$seven_str" ] && line2="${line2}${SEP}${seven_str}"

line3="${user}@${host}"
[ -n "$token_str" ] && line3="${line3}${SEP}${token_str}"
[ -n "$cost_str"  ] && line3="${line3}${SEP}cost: ${cost_str}"
[ -n "$lines_str" ] && line3="${line3}${SEP}${lines_str}"

printf '%s\n%s\n%s\n' "$line1" "$line2" "$line3"
