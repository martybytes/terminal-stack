#!/usr/bin/env bash
# _common.sh — shared helpers for every .sh script in this repo: preview/apply
# output, prerequisite checks, security assertions, HTTP, JSON, secrets, paths
# and compose wrappers. Sourced by bootstrap.sh, stack.sh and each stack's
# scripts. macOS/Linux side only; the .ps1 scripts keep their own copies of
# these helpers by design (see docs/conventions.md, "Scripts").
#
# This file is sourced, not executed. Do not `exit`; return non-zero instead.
# The one exception is `die`, whose whole job is to end the calling script.
#
# Stays bash-3.2 clean (macOS ships 3.2): no associative arrays, no ${x,,},
# no mapfile/readarray, no ;;& in case. Lookup tables are `case` functions.

# ── Repo root ────────────────────────────────────────────────────────────────
# Resolved from this file, not from $0, so a script in a stack sub-directory
# never has to guess at "..". Symlink-safe without readlink -f / realpath:
# BSD readlink had no -f for years and realpath is not on older macOS.
_dl_resolve_dir() {                       # <path> -> absolute dir, symlinks resolved
    local p="$1" d
    while [ -L "$p" ]; do
        d="$(cd -- "$(dirname -- "$p")" && pwd)"
        p="$(readlink "$p")"
        case "$p" in /*) ;; *) p="$d/$p" ;; esac
    done
    cd -- "$(dirname -- "$p")" 2>/dev/null && pwd -P
}
DL_ROOT="${DL_ROOT:-$(_dl_resolve_dir "${BASH_SOURCE[0]}")}"

# ── Mode globals ─────────────────────────────────────────────────────────────
# One DL_APPLY that `step` reads. The .ps1 copies close over either $execute or
# $Apply depending on the script, which is identical only by accident; here the
# two spellings cannot coexist.
: "${DL_APPLY:=0}"
: "${DL_UNDO:=0}"
: "${DL_CHECK:=0}"
: "${DL_PROBLEMS:=0}"
: "${DL_FLAG_CONSUMED:=0}"
DL_MODE=""
# Declared so `set -u` is safe before the first HTTP call. See http_status.
: "${DL_HTTP_STATUS:=}"
: "${DL_HTTP_TIME_MS:=}"

dl_mode() {
    if [ "$DL_CHECK" = 1 ]; then DL_MODE=CHECK
    elif [ "$DL_UNDO" = 1 ] && [ "$DL_APPLY" = 1 ]; then DL_MODE=UNDO
    elif [ "$DL_APPLY" = 1 ]; then DL_MODE=APPLY
    else DL_MODE=PREVIEW
    fi
    printf '%s' "$DL_MODE"
}

# ── Colour ───────────────────────────────────────────────────────────────────
# Honours NO_COLOR, a non-tty stdout (piping to a file or a pager), TERM=dumb,
# and DL_COLOR=always|never|auto for forcing either way.
dl_use_colour() {
    [ -n "${NO_COLOR:-}" ] && return 1
    case "${DL_COLOR:-auto}" in
        always) return 0 ;;
        never)  return 1 ;;
    esac
    [ -t 1 ] || return 1
    [ -n "${TERM:-}" ] && [ "$TERM" != dumb ]
}

if dl_use_colour; then
    : "${C_CYAN:=$'\033[36m'}"  ; : "${C_GREEN:=$'\033[32m'}"
    : "${C_YELLOW:=$'\033[33m'}"; : "${C_DIM:=$'\033[90m'}"
    : "${C_WHITE:=$'\033[97m'}" ; : "${C_RESET:=$'\033[0m'}"
else
    C_CYAN='' ; C_GREEN='' ; C_YELLOW='' ; C_DIM='' ; C_WHITE='' ; C_RESET=''
fi

# ── Output helpers ───────────────────────────────────────────────────────────
# Bare names on purpose: it keeps the .ps1 <-> .sh mapping 1:1 greppable, and
# these files are executed, never sourced into an interactive shell.
#
# The [DO] tag is THREE spaces, not the two used by seven of the .ps1 copies.
# '[DO]   ' and '[would]' are then both 7 characters, so a message lands in the
# same column whether or not you passed --apply — which is the entire point of
# the tag. See the divergence register in docs/conventions.md.
section() { printf '\n%s=== %s ===%s\n' "$C_CYAN" "$1" "$C_RESET"; }
step() {
    if [ "$DL_APPLY" = 1 ]; then printf '%s[DO]    %s%s\n' "$C_GREEN" "$1" "$C_RESET"
    else printf '%s[would] %s%s\n' "$C_YELLOW" "$1" "$C_RESET"; fi
}
info() { printf '%s       %s%s\n' "$C_DIM" "$1" "$C_RESET"; }
warn() { printf '%s  !    %s%s\n' "$C_YELLOW" "$1" "$C_RESET"; }
pass() { printf '%s  OK   %s%s\n' "$C_GREEN" "$1" "$C_RESET"; }
fail() { DL_PROBLEMS=$((DL_PROBLEMS + 1)); printf '%s  X    %s%s\n' "$C_YELLOW" "$1" "$C_RESET"; }
die()  { printf '%s\n' "$1" >&2; exit "${2:-1}"; }

dl_banner() {                             # <script-name>
    dl_mode >/dev/null
    printf '%s%s  mode=%s  repo=%s%s\n' "$C_WHITE" "$1" "$DL_MODE" "$DL_ROOT" "$C_RESET"
    [ "$DL_APPLY" = 1 ] || printf '%s(preview only — re-run with --apply to perform)%s\n' "$C_DIM" "$C_RESET"
}

dl_summary() {
    printf '\n'
    if [ "$DL_APPLY" = 1 ]; then printf '%sDone (%s).%s\n' "$C_GREEN" "$DL_MODE" "$C_RESET"
    else printf '%sNothing changed (preview). Add --apply to perform.%s\n' "$C_WHITE" "$C_RESET"; fi
}

# ── Flags ────────────────────────────────────────────────────────────────────
# -Apply -> --apply, -GpuTag -> --gpu-tag, -MaxPlannedTerraCalls ->
# --max-planned-terra-calls. Lets the PowerShell spelling work from muscle
# memory without every script listing both. Short flags like -h are untouched
# because the pattern requires an uppercase first letter.
dl_normalise_flag() {
    case "$1" in
        --*) printf '%s' "$1" ;;
        -[[:upper:]]*) printf '%s' "$1" | LC_ALL=C sed 's/^-//; s/\([a-z0-9]\)\([A-Z]\)/\1-\2/g' \
                 | LC_ALL=C tr '[:upper:]' '[:lower:]' | sed 's/^/--/' ;;
        *) printf '%s' "$1" ;;
    esac
}

# Handles the flags every script shares. Sets DL_FLAG_CONSUMED to how many
# arguments to shift and returns 0; returns 1 when the flag is not ours.
dl_parse_common_flag() {                  # <normalised-arg> [next-arg]
    DL_FLAG_CONSUMED=1
    case "$1" in
        --apply)     DL_APPLY=1 ;;
        --undo)      DL_UNDO=1 ;;
        --check)     DL_CHECK=1 ;;
        --no-color|--no-colour)
                     C_CYAN='' ; C_GREEN='' ; C_YELLOW='' ; C_DIM='' ; C_WHITE='' ; C_RESET='' ;;
        -h|--help)   dl_usage; exit 0 ;;
        *)           DL_FLAG_CONSUMED=0; return 1 ;;
    esac
    return 0
}

# The header comment IS the usage text — no second copy to drift. Stops at the
# first non-comment line rather than a fixed range, so a header can grow or
# shrink without anyone remembering to retune a line number.
dl_usage() {
    awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"
}

# PowerShell gets [ValidateRange] free; bash gets nothing free. These bound
# scripts that spend money and quarantine a queue, so they are not optional.
dl_require_int() {                        # <name> <value> <min> <max>
    case "$2" in
        ''|*[!0-9-]*) die "$1: '$2' is not an integer" ;;
    esac
    [ "$2" -ge "$3" ] 2>/dev/null && [ "$2" -le "$4" ] 2>/dev/null \
        || die "$1: $2 is outside the allowed range $3..$4"
}

dl_require_num() {                        # <name> <value> <min> <max>
    awk -v v="$2" -v lo="$3" -v hi="$4" 'BEGIN{
        if (v+0 != v && v !~ /^-?[0-9]*\.?[0-9]+$/) exit 2
        exit (v+0 >= lo+0 && v+0 <= hi+0) ? 0 : 1
    }' </dev/null || die "$1: $2 is not a number in the range $3..$4"
}

# ── Platform and prerequisites ───────────────────────────────────────────────
# PREDICATES. Everything in this section that returns non-zero does so as a
# VALUE, so only ever call them in a condition context (`if have docker; then`)
# or with `|| true`. Under `set -e` a bare call will end the script.
dl_os() {
    case "$(uname -s | tr '[:upper:]' '[:lower:]')" in
        darwin) printf 'darwin' ;;
        linux)  printf 'linux' ;;
        *)      printf 'other' ;;
    esac
}

have() { command -v "$1" >/dev/null 2>&1; }
need() { have "$1" || die "${2:-$1 not found on PATH.}"; }

require_docker() {
    have docker || die 'docker CLI not found on PATH — install and launch Docker Desktop first. See docs/new-machine.md.'
    docker info >/dev/null 2>&1 || die 'Docker daemon not responding — is Docker Desktop running?'
}

# Sets DL_GPU_PROFILE (A|B|C) and DL_GPU_REASON. Returns 0 always.
#
# On macOS the answer is C unconditionally and nvidia-smi is never probed:
# Docker Desktop for Mac has no GPU passthrough of any kind — not CUDA, and not
# Metal/MPS — so a Linux container cannot reach the Apple GPU under any
# configuration. The reason string says that rather than the .ps1's generic
# "no NVIDIA GPU detected", which reads like something you could go and fix.
dl_gpu_profile() {
    DL_GPU_PROFILE=C
    DL_GPU_REASON=''
    case "$(dl_os)" in
        darwin)
            DL_GPU_REASON='Docker Desktop for Mac has no NVIDIA passthrough (and no Metal/MPS passthrough either) — C is the only profile that can run here'
            return 0 ;;
    esac
    if ! have nvidia-smi; then
        DL_GPU_REASON='nvidia-smi not on PATH — treating this as a CPU-only machine'
        return 0
    fi
    local name
    # `|| true`: head exits after the first line on a multi-GPU box, tr/nvidia-smi
    # take SIGPIPE, and pipefail would surface that as a fatal 141.
    name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 || true)"
    if [ -z "$name" ]; then
        DL_GPU_REASON='nvidia-smi present but reported no GPU — treating this as a CPU-only machine'
        return 0
    fi
    # Blackwell consumer cards (RTX 50-series, sm_120) need the CUDA 12.8 build;
    # the cu126 build starts fine then crash-loops on the first synthesis.
    if printf '%s' "$name" | grep -Eq 'RTX[[:space:]]*50[0-9]{2}'; then
        DL_GPU_PROFILE=A; DL_GPU_REASON="$name is Blackwell (RTX 50-series) — Profile A (cu128)"
    else
        DL_GPU_PROFILE=B; DL_GPU_REASON="$name is pre-Blackwell — Profile B (cu126) is the narrower match"
    fi
    # On native Linux the NVIDIA Container Toolkit is a SEPARATE install, so a
    # working host nvidia-smi proves nothing about the container runtime. This
    # is where docs/new-machine.md's "you don't need the toolkit" differs: that
    # is true only because WSL 2 handles passthrough for Docker Desktop.
    # Captured first, then matched in the shell. `... | grep -q` would be wrong
    # here, not merely fragile: grep -q exits at the first match, docker takes
    # SIGPIPE, and pipefail then reports the pipeline as FAILED on a match.
    runtimes="$(docker info --format '{{.Runtimes}}' 2>/dev/null || true)"
    case "$runtimes" in *nvidia*) : ;; *)
        DL_GPU_REASON="$DL_GPU_REASON; NOTE the nvidia container runtime is not registered with this docker — install the NVIDIA Container Toolkit or the GPU overlay will fail to start" ;;
    esac
    return 0
}

# PREDICATE. 0 = image publishes that arch, 1 = it does not, 2 = could not tell
# (no network, private registry, old CLI). Callers must distinguish 1 from 2.
dl_image_has_arch() {                     # <image> <arch>
    local out
    out="$(docker manifest inspect "$1" 2>/dev/null)" || return 2
    [ -n "$out" ] || return 2
    case "$out" in *"\"architecture\": \"$2\""*) return 0 ;; *) return 1 ;; esac
}

# ── Paths and files ──────────────────────────────────────────────────────────
dl_realpath() {                           # <path> -> absolute, symlinks resolved
    if [ -d "$1" ]; then (cd -- "$1" 2>/dev/null && pwd -P)
    else
        local d b
        d="$(dirname -- "$1")"; b="$(basename -- "$1")"
        [ -d "$d" ] || return 1
        printf '%s/%s' "$(cd -- "$d" 2>/dev/null && pwd -P)" "$b"
    fi
}

# PREDICATE. Assert <path> is inside <root> after both are fully resolved.
#
# This is a safety guard, not a convenience: the resolved path is bind-mounted
# into a container that writes a tar archive into it, so a symlinked or
# ..-bearing root would have the container write somewhere unintended.
# The trailing slash is load-bearing — it stops root /a/backups matching
# /a/backups-evil, exactly what .TrimEnd('\') + '\' does on the Windows side.
# Deliberately case-SENSITIVE: the .ps1 uses OrdinalIgnoreCase because NTFS is,
# but pwd -P returns on-disk casing, so plain matching is correct on Linux and
# strictly safer on a case-insensitive APFS volume.
dl_assert_within() {                      # <root> <path>
    local rroot rpath
    rroot="$(dl_realpath "$1")" || return 1
    rpath="$(dl_realpath "$2")" || return 1
    case "$rpath/" in "$rroot"/*) return 0 ;; *) return 1 ;; esac
}

# There is no Unix C:\DATA. XDG state under $HOME is the equivalent, and it is
# also the only place Docker Desktop for Mac shares by default — a backup root
# outside $HOME fails to bind-mount.
dl_backup_root() {
    printf '%s' "${DOCKER_LOCAL_BACKUP_ROOT:-${XDG_STATE_HOME:-$HOME/.local/state}/docker-local/backups}"
}

# PREDICATE. Reject a backup root that is far too broad. The .ps1 only rejects
# the drive root; the Unix analogue of that (/) is a very weak floor, so also
# reject $HOME itself and anything outside $HOME or /Volumes.
dl_backup_root_sane() {                   # <resolved-root>
    [ -n "${DOCKER_LOCAL_ALLOW_ANY_BACKUP_ROOT:-}" ] && return 0
    local r="$1" home
    home="$(dl_realpath "$HOME")" || return 1
    [ "$r" = / ] && return 1
    [ "$r" = "$home" ] && return 1
    case "$r/" in "$home"/*|/Volumes/*) return 0 ;; *) return 1 ;; esac
}

# PREDICATE. Docker Desktop for Mac only shares $HOME, /tmp, /private and
# /Volumes by default; a bind mount from anywhere else fails at run time. Must
# be checked BEFORE a script stops the stack, or the stack is already down when
# the mount fails.
dl_assert_docker_shareable() {            # <absolute-path>
    case "$(dl_os)" in linux) return 0 ;; esac
    local p home
    p="$(dl_realpath "$1")" || return 1
    home="$(dl_realpath "$HOME")" || return 1
    case "$p/" in "$home"/*|/tmp/*|/private/*|/Volumes/*) return 0 ;; *) return 1 ;; esac
}

# stat -c is GNU-only and stat -f is BSD-only; wc -c is neither.
file_size() { wc -c < "$1" | tr -d ' '; }

stamp() { date -u +%Y%m%d-%H%M%S; }

# Note the argv offset: with `node -e`, the first real argument is argv[1]
# (there is no script path in argv). With `node -` it is argv[2], because "-"
# itself occupies argv[1]. Getting this wrong yields `undefined`, which
# JSON.stringify silently DROPS from an object rather than erroring.
#
# NOT `tr -dc ... < /dev/urandom | head -c N`: head exits as soon as it has
# enough bytes, tr takes SIGPIPE, and under `set -o pipefail` that surfaces as
# exit 141 which `set -e` turns into a silent death of the calling script.
# node is already a hard prerequisite and has no such race.
dl_rand_hex() {
    node -e 'const n=Number(process.argv[1])||12;process.stdout.write(require("node:crypto").randomBytes(n).toString("hex").slice(0,n))' "${1:-12}"
}

# Byte-exact whole-file regex replace, matching what the .ps1 twins do with
# `(Get-Content -Raw) -replace ... | Set-Content -NoNewline`.
#
# NOT sed: `sed -i` needs -i '' on BSD and rejects it on GNU, and more
# importantly sed is line-oriented and appends a trailing newline to a file that
# lacked one. These helpers rewrite TRACKED files that the .ps1 also rewrites,
# so a one-byte difference would have the two script sets fight over the file
# forever. node is already a hard prerequisite and gives exact string semantics.
# The program comes in on stdin so no shell quoting can mangle it.
#
# Returns 0 on a change, 3 when the pattern matched nothing (the caller decides
# whether that is an error), 4 if the result would be empty.
dl_replace_in_file() {                    # <file> <js-regex> <replacement>
    node - "$1" "$2" "$3" <<'DL_NODE_EOF'
const fs = require("node:fs");
// `node -` keeps "-" as argv[1], so the real arguments start at 2.
const [f, re, rep] = process.argv.slice(2);
const before = fs.readFileSync(f, "utf8");
const after = before.replace(new RegExp(re, "g"), rep);
if (after === before) process.exit(3);
if (!after.length) process.exit(4);
const tmp = f + ".tmp" + process.pid;
fs.writeFileSync(tmp, after);
fs.renameSync(tmp, f);
DL_NODE_EOF
}

# ── Listening sockets ────────────────────────────────────────────────────────
# Prints one bare address per line (no :port) for whatever is listening on
# <port>. Returns 2 when no tool is available to tell — callers MUST treat 2
# differently from "nothing listening", which is an empty result with status 0.
_dl_listen_addrs() {                      # <port>
    local port="$1" line
    if have lsof; then
        lsof -nP -iTCP:"$port" -sTCP:LISTEN -Fn 2>/dev/null | sed -n 's/^n//p' \
        | while IFS= read -r line; do printf '%s\n' "${line%[:.]$port}"; done
        return 0
    fi
    if have ss; then
        ss -ltnH 2>/dev/null | awk '{print $4}' | grep -E "[:.]$port\$" \
        | while IFS= read -r line; do printf '%s\n' "${line%[:.]$port}"; done
        return 0
    fi
    if have netstat; then
        netstat -an 2>/dev/null | awk '/^tcp/ && /LISTEN/ {print $4}' | grep -E "[:.]$port\$" \
        | while IFS= read -r line; do printf '%s\n' "${line%[:.]$port}"; done
        return 0
    fi
    return 2
}

_dl_addr_is_loopback() {
    case "$1" in
        127.*|::1|'[::1]'|localhost) return 0 ;;
        *) return 1 ;;
    esac
}

# PREDICATE, READINESS ONLY — "is anything listening yet". This is deliberately
# NOT assert_loopback_only: conflating the two would either make a polling loop
# fail closed on a non-loopback bind, or make the security assertion pass just
# because nothing has started yet.
port_listening() {                        # <port>
    local addrs
    addrs="$(_dl_listen_addrs "$1")" || return 1
    [ -n "$addrs" ]
}

# THE security check. docs/conventions.md calls a non-loopback bind here "the
# single easiest mistake to make, and the one with the worst consequences" —
# none of these services authenticate, so a 0.0.0.0 bind puts them on the LAN.
#
# Returns non-zero if any port is exposed OR if it could not be determined.
# A check that cannot run is reported loudly, never skipped silently.
assert_loopback_only() {                  # <port>...
    local port addrs addr rc bad=0
    for port in "$@"; do
        addrs="$(_dl_listen_addrs "$port")"; rc=$?
        if [ "$rc" = 2 ]; then
            fail "cannot verify port $port is loopback-only — no lsof, ss or netstat on PATH"
            bad=1; continue
        fi
        if [ -z "$addrs" ]; then
            # Not a failure: the assertion is "not exposed", not "is up". But say
            # so, or a stopped stack quietly renders as a clean bill of health.
            info "port $port: nothing listening — not exposed, but nothing proven either"
            continue
        fi
        while IFS= read -r addr; do
            [ -n "$addr" ] || continue
            if _dl_addr_is_loopback "$addr"; then
                pass "port $port bound to $addr"
            else
                fail "port $port is listening on $addr — reachable beyond this machine. These services have no authentication; the bind must be 127.0.0.1."
                bad=1
            fi
        done <<EOF
$addrs
EOF
    done
    [ "$bad" = 0 ]
}

# Second, independent signal. On Docker Desktop for Mac the host socket belongs
# to com.docker.backend, so lsof proves the host binding but says nothing about
# the publish SPEC — and the spec is what a bad compose edit gets wrong. This
# catches it even before the container is reachable.
dl_assert_publish_loopback() {
    local out line bad=0
    out="$(docker ps --format '{{.Names}}|{{.Ports}}' 2>/dev/null)" || return 0
    while IFS= read -r line; do
        [ -n "$line" ] || continue
        case "${line#*|}" in
            *'0.0.0.0:'*|*'[::]:'*)
                fail "container ${line%%|*} publishes on all interfaces: ${line#*|}"
                bad=1 ;;
        esac
    done <<EOF
$out
EOF
    [ "$bad" = 0 ]
}

# ── HTTP ─────────────────────────────────────────────────────────────────────
# DL_HTTP_STATUS and DL_HTTP_TIME_MS are set by http_status. curl's
# %{time_total} replaces [Diagnostics.Stopwatch]: $SECONDS is whole-second only
# and `date +%s%3N` does not exist on macOS.
#
# CAVEAT: those globals only survive when http_status is called directly --
#   http_status "$url" 8 >/dev/null; echo "$DL_HTTP_TIME_MS"
# Calling it as `s=$(http_status "$url")` runs it in a subshell, so you get the
# printed status but the timing globals keep their previous values.
http_status() {                           # <url> [timeout] -> prints status code
    # No pipeline here on purpose: a `... | read` puts the read in a subshell,
    # so DL_HTTP_STATUS would never reach the caller.
    local out t
    out="$(curl -sS -o /dev/null -w '%{http_code} %{time_total}' --max-time "${2:-20}" "$1" 2>/dev/null)" || out='000 0'
    DL_HTTP_STATUS="${out%% *}"
    t="${out#* }"
    DL_HTTP_TIME_MS="$(awk -v t="${t:-0}" 'BEGIN{printf "%.0f", t*1000}')"
    printf '%s' "$DL_HTTP_STATUS"
}

http_get() {                              # <url> [timeout] -> body on stdout
    curl -fsS --max-time "${2:-20}" "$1"
}

# Bearer tokens must never reach argv. `curl -H "Authorization: Bearer $s"` is
# visible in `ps aux` to every local user for the life of the request — an
# exposure the PowerShell twins do not have, because they pass headers
# in-process. A curl config file on stdin keeps the secret off the process list.
http_get_auth() {                         # <url> <secret> [timeout]
    printf 'header = "Authorization: Bearer %s"\n' "$2" \
        | curl -fsS -K - --max-time "${3:-20}" "$1"
}

http_post_json() {                        # <url> <json-body> [timeout]
    curl -fsS --max-time "${3:-20}" -H 'content-type: application/json' -d "$2" "$1"
}

# Authenticated variants. Same rule as http_get_auth: the bearer goes in via a
# curl config file on stdin so it never appears in `ps aux`.
http_post_json_auth() {                   # <url> <secret> <json-body> [timeout]
    printf 'header = "Authorization: Bearer %s"\n' "$2" \
        | curl -fsS -K - --max-time "${4:-20}" -H 'content-type: application/json' -d "$3" "$1"
}

http_delete_json_auth() {                 # <url> <secret> <json-body> [timeout]
    printf 'header = "Authorization: Bearer %s"\n' "$2" \
        | curl -fsS -K - --max-time "${4:-20}" -X DELETE -H 'content-type: application/json' -d "$3" "$1"
}

wait_http_200() {                         # <url> <timeout-seconds>
    local url="$1" deadline now
    deadline=$(( $(date +%s) + ${2:-60} ))
    while :; do
        [ "$(http_status "$url" 5)" = 200 ] && return 0
        now="$(date +%s)"
        [ "$now" -ge "$deadline" ] && return 1
        sleep 2
    done
}

# ── JSON ─────────────────────────────────────────────────────────────────────
# node, not jq: node is already a hard prerequisite of this repo (the playwright
# setup, check-playwright.mjs, the capture probe) and the repo already ships
# .mjs helpers, whereas jq is required by nothing today. The hard cases here are
# round-trip edits of a user's agent config, where a safe read-modify-write plus
# atomic replace is less code in node than in jq.
json_get() { node "$DL_ROOT/_json.mjs" get "$1" "$2"; }
json_set() { node "$DL_ROOT/_json.mjs" set "$1" "$2" "$3"; }
json_eq()  { node "$DL_ROOT/_json.mjs" eq  "$1" "$2" "$3"; }
json_str() { node "$DL_ROOT/_json.mjs" str "$1"; }

# GNU `date -d` is not on macOS and BSD `date -j -f` is not on Linux, so a
# per-OS split here would mean two incompatible dialects to maintain.
dl_iso_age_minutes() {                    # <iso8601> -> whole minutes, or empty
    node -e 'const t=Date.parse(process.argv[1]); if(!isNaN(t)) console.log(Math.floor((Date.now()-t)/60000))' "$1" 2>/dev/null
}

# ── .env reading ─────────────────────────────────────────────────────────────
dl_env_value() {                          # <env-file> <key> -> value, or non-zero
    local f="$1" k="$2" line v
    [ -f "$f" ] || return 1
    while IFS= read -r line || [ -n "$line" ]; do
        line="${line%$'\r'}"
        line="${line#"${line%%[![:space:]]*}"}"
        case "$line" in
            "$k"=*)
                v="${line#*=}"
                v="${v#"${v%%[![:space:]]*}"}"
                v="${v%"${v##*[![:space:]]}"}"
                printf '%s' "$v"; return 0 ;;
        esac
    done < "$f"
    return 1
}

# ── Secrets ──────────────────────────────────────────────────────────────────
_dl_file_mode() { stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1" 2>/dev/null; }

dl_secret_cache_path() {
    printf '%s' "${XDG_CONFIG_HOME:-$HOME/.config}/docker-local/agentmemory.secret"
}

# Windows keeps this in HKCU\Environment, which every newly launched process
# inherits. Unix has no equivalent with those semantics: a keychain does not put
# anything in a GUI app's environment, and a shell profile misses GUI-launched
# apps entirely (and belongs to terminal-stack, not here). So:
#
#   container = source of truth   file = cache   environment = override
#
# The 0600 check has no Windows analogue and is the reason the file is safe to
# use at all. Refuse a group- or world-readable cache rather than trusting it.
agentmemory_secret() {                    # [stack-dir]
    local cache mode dir out
    if [ -n "${AGENTMEMORY_SECRET:-}" ]; then printf '%s' "$AGENTMEMORY_SECRET"; return 0; fi
    cache="$(dl_secret_cache_path)"
    if [ -f "$cache" ]; then
        mode="$(_dl_file_mode "$cache")"
        if [ "$mode" = 600 ]; then
            tr -d '\r\n' < "$cache"; return 0
        fi
        warn "$cache is mode ${mode:-unknown}, not 600 — refusing to use it. chmod 600 it, or delete it."
    fi
    dir="${1:-$DL_ROOT/agentmemory}"
    out="$( cd "$dir" 2>/dev/null && docker compose exec -T agentmemory cat /data/.hmac 2>/dev/null )" || return 1
    [ -n "$out" ] || return 1
    printf '%s' "$out" | tr -d '\r\n'
}

# Read a raw credential file, refusing anything that looks wrong. The mode check
# is Unix-only and deliberate: these files hold provider admin keys.
dl_read_raw_secret() {                    # <path> <label>
    local p="$1" label="$2" mode v
    [ -f "$p" ] || { printf '%s not found: %s\n' "$label" "$p" >&2; return 1; }
    mode="$(_dl_file_mode "$p")"
    case "$mode" in
        600|400) ;;
        *) printf '%s is mode %s — chmod 600 %s before using it.\n' "$label" "${mode:-unknown}" "$p" >&2; return 1 ;;
    esac
    # Reject anything that is not exactly one raw key. The .ps1's Read-RawSecret
    # does the same: a file holding `OPENAI_API_KEY=sk-...`, a quoted value, or
    # two lines would otherwise be bind-mounted into the container as-is and
    # authenticate as garbage.
    if [ "$(grep -c . "$p" || true)" -gt 1 ]; then
        printf '%s file must contain exactly one raw key: %s\n' "$label" "$p" >&2; return 1
    fi
    v="$(tr -d '\r\n' < "$p")"
    [ -n "$v" ] || { printf '%s is empty: %s\n' "$label" "$p" >&2; return 1; }
    case "$v" in
        \"*|\'*|*\"|*\')
            printf '%s file must contain only the raw key, without quotes: %s\n' "$label" "$p" >&2; return 1 ;;
    esac
    if printf '%s' "$v" | grep -qE '^(export[[:space:]]+)?[A-Za-z_][A-Za-z0-9_]*[[:space:]]*='; then
        printf '%s file must contain only the raw key, without OPENAI_API_KEY= or export: %s\n' "$label" "$p" >&2; return 1
    fi
    printf '%s' "$v"
}

# ── Compose ──────────────────────────────────────────────────────────────────
# Callers cd into their stack directory first (or run these in a subshell), so
# these stay thin wrappers with one place to add behaviour later.
compose()         { docker compose "$@"; }
compose_capture() { docker compose "$@" 2>&1; }

# Which compose files a stack will actually merge, per its .env. `docker compose
# ls` reports the files a project was *created* with, which goes stale the
# moment you add an overlay — so read the current intent instead.
dl_compose_files() {                      # <stack-dir> -> one file per line
    local dir="$1" sep spec
    sep="$(dl_env_value "$dir/.env" COMPOSE_PATH_SEPARATOR 2>/dev/null)" || sep=':'
    [ -n "$sep" ] || sep=':'
    spec="$(dl_env_value "$dir/.env" COMPOSE_FILE 2>/dev/null)" || spec=''
    if [ -z "$spec" ]; then printf 'docker-compose.yml\n'; return 0; fi
    printf '%s\n' "$spec" | tr "$sep" '\n' | sed '/^[[:space:]]*$/d; s/^[[:space:]]*//; s/[[:space:]]*$//'
}

# PREDICATE. A stack shipping a .env.example with no .env is misconfigured:
# compose silently falls back to the base file only, which for kokoro means
# starting the GPU image with no GPU access.
dl_env_seeded() {                         # <stack-dir>
    [ -f "$1/.env.example" ] || return 0
    [ -f "$1/.env" ]
}

# Derive a service's image rather than hardcoding it. migrate-durable-llm.ps1:56
# hardcodes `agentmemory-agentmemory:latest`, which is right only because the
# compose project name happens to derive from the directory name.
dl_compose_image() {                      # <stack-dir> <service>
    local cfg img proj
    cfg="$( cd "$1" && docker compose config --format json 2>/dev/null )" || return 1
    img="$(printf '%s' "$cfg" | node "$DL_ROOT/_json.mjs" get - "services.$2.image" 2>/dev/null)"
    if [ -n "$img" ] && [ "$img" != null ]; then printf '%s' "$img"; return 0; fi
    proj="$(printf '%s' "$cfg" | node "$DL_ROOT/_json.mjs" get - name 2>/dev/null)"
    [ -n "$proj" ] && [ "$proj" != null ] || proj="$(basename "$1")"
    printf '%s-%s' "$proj" "$2"
}

# ── Upstream agentmemory source checkout ─────────────────────────────────────
# Reference material for repairing patch-agentmemory.mjs when a version bump
# breaks one of its ~43 exact-match replacements, and for answering "what env
# var does the runtime actually read". NEVER a runtime: the stack builds from
# npm at the pinned version and nothing loads from this path.
#
# The derived location is a hint of LAST resort — it is a four-level layout
# assumption, and this repo deliberately refuses that kind of guess in tracked
# files. Absent is not an error; this is optional tooling.
dl_agentmemory_source() {
    local p
    if [ -n "${AGENTMEMORY_SOURCE_PATH:-}" ]; then p="$AGENTMEMORY_SOURCE_PATH"
    else
        p="$(dl_env_value "$DL_ROOT/agentmemory/.env" AGENTMEMORY_SOURCE_PATH 2>/dev/null)" || p=''
        [ -n "$p" ] || p="$DL_ROOT/../../../../public/github.com/agentmemory"
    fi
    [ -f "$p/package.json" ] || return 1
    dl_realpath "$p"
}

# The pinned version this repo builds, from the compose build args.
dl_agentmemory_pinned_version() {
    sed -n 's/^[[:space:]]*AGENTMEMORY_VERSION:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' \
        "$DL_ROOT/agentmemory/docker-compose.yml" 2>/dev/null | head -n 1 || true
}
