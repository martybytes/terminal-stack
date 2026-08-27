#!/usr/bin/env bash
# _stack.sh — shared helpers for every .sh script under services/: preview/apply
# output, prerequisite checks, security assertions, HTTP, JSON, secrets, paths
# and compose wrappers. Sourced by bootstrap/ts-stack.sh and each stack's own
# scripts. macOS/Linux side only; the .ps1 scripts keep their own copies of
# these helpers by design (see docs/service-conventions.md, "Scripts").
#
# Deliberately NOT merged into bootstrap/_config.sh. That file is sourced on
# shell-startup paths and will never need Docker, GPU or loopback helpers; and
# this one owns bare `die`/`have`/`warn`/`info`/`pass`/`fail`/`step`/`compose`,
# which would sit next to _config.sh's $WARN/$INFO variables — legal in bash and
# a review hazard. See docs/decisions.md.
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
_tss_resolve_dir() {                       # <path> -> absolute dir, symlinks resolved
    local p="$1" d
    while [ -L "$p" ]; do
        d="$(cd -- "$(dirname -- "$p")" && pwd)"
        p="$(readlink "$p")"
        case "$p" in /*) ;; *) p="$d/$p" ;; esac
    done
    cd -- "$(dirname -- "$p")" 2>/dev/null && pwd -P
}
TSS_ROOT="${TSS_ROOT:-$(_tss_resolve_dir "${BASH_SOURCE[0]}")}"
# Where the compose stacks live. A stack is any directory under here holding a
# docker-compose.yml — there is no registry, so adding one requires no edit
# anywhere (that property is why services/** is a single .chezmoiignore line).
# TS_STACK_ROOT overrides it for the pytest fixture tree.
TSS_STACKS="${TS_STACK_ROOT:-$TSS_ROOT/stacks}"

# ── Mode globals ─────────────────────────────────────────────────────────────
# One TSS_APPLY that `step` reads. The .ps1 copies close over either $execute or
# $Apply depending on the script, which is identical only by accident; here the
# two spellings cannot coexist.
: "${TSS_APPLY:=0}"
: "${TSS_UNDO:=0}"
: "${TSS_CHECK:=0}"
: "${TSS_PROBLEMS:=0}"
: "${TSS_FLAG_CONSUMED:=0}"
TSS_MODE=""
# Declared so `set -u` is safe before the first HTTP call. See http_status.
: "${TSS_HTTP_STATUS:=}"
: "${TSS_HTTP_TIME_MS:=}"

tss_mode() {
    if [ "$TSS_CHECK" = 1 ]; then TSS_MODE=CHECK
    elif [ "$TSS_UNDO" = 1 ] && [ "$TSS_APPLY" = 1 ]; then TSS_MODE=UNDO
    elif [ "$TSS_APPLY" = 1 ]; then TSS_MODE=APPLY
    else TSS_MODE=PREVIEW
    fi
    printf '%s' "$TSS_MODE"
}

# ── Colour ───────────────────────────────────────────────────────────────────
# Honours NO_COLOR, a non-tty stdout (piping to a file or a pager), TERM=dumb,
# and TSS_COLOR=always|never|auto for forcing either way.
tss_use_colour() {
    [ -n "${NO_COLOR:-}" ] && return 1
    case "${TSS_COLOR:-auto}" in
        always) return 0 ;;
        never)  return 1 ;;
    esac
    [ -t 1 ] || return 1
    [ -n "${TERM:-}" ] && [ "$TERM" != dumb ]
}

if tss_use_colour; then
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
    if [ "$TSS_APPLY" = 1 ]; then printf '%s[DO]    %s%s\n' "$C_GREEN" "$1" "$C_RESET"
    else printf '%s[would] %s%s\n' "$C_YELLOW" "$1" "$C_RESET"; fi
}
info() { printf '%s       %s%s\n' "$C_DIM" "$1" "$C_RESET"; }
warn() { printf '%s  !    %s%s\n' "$C_YELLOW" "$1" "$C_RESET"; }
pass() { printf '%s  OK   %s%s\n' "$C_GREEN" "$1" "$C_RESET"; }
fail() { TSS_PROBLEMS=$((TSS_PROBLEMS + 1)); printf '%s  X    %s%s\n' "$C_YELLOW" "$1" "$C_RESET"; }
die()  { printf '%s\n' "$1" >&2; exit "${2:-1}"; }

tss_banner() {                             # <script-name>
    tss_mode >/dev/null
    printf '%s%s  mode=%s  repo=%s%s\n' "$C_WHITE" "$1" "$TSS_MODE" "$TSS_ROOT" "$C_RESET"
    [ "$TSS_APPLY" = 1 ] || printf '%s(preview only — re-run with --apply to perform)%s\n' "$C_DIM" "$C_RESET"
}

tss_summary() {
    printf '\n'
    if [ "$TSS_APPLY" = 1 ]; then printf '%sDone (%s).%s\n' "$C_GREEN" "$TSS_MODE" "$C_RESET"
    else printf '%sNothing changed (preview). Add --apply to perform.%s\n' "$C_WHITE" "$C_RESET"; fi
}

# ── Flags ────────────────────────────────────────────────────────────────────
# -Apply -> --apply, -GpuTag -> --gpu-tag, -MaxPlannedTerraCalls ->
# --max-planned-terra-calls. Lets the PowerShell spelling work from muscle
# memory without every script listing both. Short flags like -h are untouched
# because the pattern requires an uppercase first letter.
tss_normalise_flag() {
    case "$1" in
        --*) printf '%s' "$1" ;;
        -[[:upper:]]*) printf '%s' "$1" | LC_ALL=C sed 's/^-//; s/\([a-z0-9]\)\([A-Z]\)/\1-\2/g' \
                 | LC_ALL=C tr '[:upper:]' '[:lower:]' | sed 's/^/--/' ;;
        *) printf '%s' "$1" ;;
    esac
}

# Handles the flags every script shares. Sets TSS_FLAG_CONSUMED to how many
# arguments to shift and returns 0; returns 1 when the flag is not ours.
tss_parse_common_flag() {                  # <normalised-arg> [next-arg]
    TSS_FLAG_CONSUMED=1
    case "$1" in
        --apply)     TSS_APPLY=1 ;;
        --undo)      TSS_UNDO=1 ;;
        --check)     TSS_CHECK=1 ;;
        --no-color|--no-colour)
                     C_CYAN='' ; C_GREEN='' ; C_YELLOW='' ; C_DIM='' ; C_WHITE='' ; C_RESET='' ;;
        -h|--help)   tss_usage; exit 0 ;;
        *)           TSS_FLAG_CONSUMED=0; return 1 ;;
    esac
    return 0
}

# The header comment IS the usage text — no second copy to drift. Stops at the
# first non-comment line rather than a fixed range, so a header can grow or
# shrink without anyone remembering to retune a line number.
tss_usage() {
    awk 'NR==1 {next} /^#/ {sub(/^# ?/, ""); print; next} {exit}' "$0"
}

# PowerShell gets [ValidateRange] free; bash gets nothing free. These bound
# scripts that spend money and quarantine a queue, so they are not optional.
tss_require_int() {                        # <name> <value> <min> <max>
    case "$2" in
        ''|*[!0-9-]*) die "$1: '$2' is not an integer" ;;
    esac
    [ "$2" -ge "$3" ] 2>/dev/null && [ "$2" -le "$4" ] 2>/dev/null \
        || die "$1: $2 is outside the allowed range $3..$4"
}

tss_require_num() {                        # <name> <value> <min> <max>
    awk -v v="$2" -v lo="$3" -v hi="$4" 'BEGIN{
        if (v+0 != v && v !~ /^-?[0-9]*\.?[0-9]+$/) exit 2
        exit (v+0 >= lo+0 && v+0 <= hi+0) ? 0 : 1
    }' </dev/null || die "$1: $2 is not a number in the range $3..$4"
}

# ── Platform and prerequisites ───────────────────────────────────────────────
# PREDICATES. Everything in this section that returns non-zero does so as a
# VALUE, so only ever call them in a condition context (`if have docker; then`)
# or with `|| true`. Under `set -e` a bare call will end the script.
tss_os() {
    case "$(uname -s | tr '[:upper:]' '[:lower:]')" in
        darwin)                printf 'darwin' ;;
        linux)                 printf 'linux' ;;
        # Git Bash / MSYS2 / Cygwin. Not 'other': this shell drives a WINDOWS
        # Docker Desktop, which cannot bind-mount an MSYS path, and whose state
        # directory convention is %LOCALAPPDATA%, not ~/.local/state.
        mingw*|msys*|cygwin*)  printf 'windows' ;;
        *)                     printf 'other' ;;
    esac
}

# A host path in the form the DOCKER ENGINE understands. Identical everywhere
# except under Git Bash, where the engine is a Windows process: it cannot mount
# /c/Users/... and the failure surfaces INSIDE the container as tar saying
# "Cannot open: No such file or directory" -- which reads as a broken archive
# rather than a broken mount, after the stack has already been stopped.
tss_docker_path() {                        # <path>
    if [ "$(tss_os)" = windows ] && command -v cygpath >/dev/null 2>&1; then
        cygpath -w "$1"
    else
        printf '%s' "$1"
    fi
}

have() { command -v "$1" >/dev/null 2>&1; }
need() { have "$1" || die "${2:-$1 not found on PATH.}"; }

require_docker() {
    have docker || die 'docker CLI not found on PATH — install and launch Docker Desktop first. See docs/new-machine.md.'
    docker info >/dev/null 2>&1 || die 'Docker daemon not responding — is Docker Desktop running?'
}

# Sets TSS_GPU_PROFILE (A|B|C) and TSS_GPU_REASON. Returns 0 always.
#
# On macOS the answer is C unconditionally and nvidia-smi is never probed:
# Docker Desktop for Mac has no GPU passthrough of any kind — not CUDA, and not
# Metal/MPS — so a Linux container cannot reach the Apple GPU under any
# configuration. The reason string says that rather than the .ps1's generic
# "no NVIDIA GPU detected", which reads like something you could go and fix.
tss_gpu_profile() {
    TSS_GPU_PROFILE=C
    TSS_GPU_REASON=''
    case "$(tss_os)" in
        darwin)
            TSS_GPU_REASON='Docker Desktop for Mac has no NVIDIA passthrough (and no Metal/MPS passthrough either) — C is the only profile that can run here'
            return 0 ;;
    esac
    if ! have nvidia-smi; then
        TSS_GPU_REASON='nvidia-smi not on PATH — treating this as a CPU-only machine'
        return 0
    fi
    local name
    # `|| true`: head exits after the first line on a multi-GPU box, tr/nvidia-smi
    # take SIGPIPE, and pipefail would surface that as a fatal 141.
    name="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 || true)"
    if [ -z "$name" ]; then
        TSS_GPU_REASON='nvidia-smi present but reported no GPU — treating this as a CPU-only machine'
        return 0
    fi
    # Blackwell consumer cards (RTX 50-series, sm_120) need the CUDA 12.8 build;
    # the cu126 build starts fine then crash-loops on the first synthesis.
    if printf '%s' "$name" | grep -Eq 'RTX[[:space:]]*50[0-9]{2}'; then
        TSS_GPU_PROFILE=A; TSS_GPU_REASON="$name is Blackwell (RTX 50-series) — Profile A (cu128)"
    else
        TSS_GPU_PROFILE=B; TSS_GPU_REASON="$name is pre-Blackwell — Profile B (cu126) is the narrower match"
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
        TSS_GPU_REASON="$TSS_GPU_REASON; NOTE the nvidia container runtime is not registered with this docker — install the NVIDIA Container Toolkit or the GPU overlay will fail to start" ;;
    esac
    return 0
}

# PREDICATE. 0 = image publishes that arch, 1 = it does not, 2 = could not tell
# (no network, private registry, old CLI). Callers must distinguish 1 from 2.
tss_image_has_arch() {                     # <image> <arch>
    local out
    out="$(docker manifest inspect "$1" 2>/dev/null)" || return 2
    [ -n "$out" ] || return 2
    case "$out" in *"\"architecture\": \"$2\""*) return 0 ;; *) return 1 ;; esac
}

# ── Paths and files ──────────────────────────────────────────────────────────
tss_realpath() {                           # <path> -> absolute, symlinks resolved
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
tss_assert_within() {                      # <root> <path>
    local rroot rpath
    rroot="$(tss_realpath "$1")" || return 1
    rpath="$(tss_realpath "$2")" || return 1
    case "$rpath/" in "$rroot"/*) return 0 ;; *) return 1 ;; esac
}

# There is no Unix C:\DATA. XDG state under $HOME is the equivalent, and it is
# also the only place Docker Desktop for Mac shares by default — a backup root
# outside $HOME fails to bind-mount.
# DOCKER_LOCAL_BACKUP_ROOT is honoured as a deprecated alias: someone may have
# exported it before the repos merged, and silently ignoring it would write the
# backup somewhere they are not looking.
tss_backup_root() {
    if [ -n "${TS_STACK_BACKUP_ROOT:-${DOCKER_LOCAL_BACKUP_ROOT:-}}" ]; then
        printf '%s' "${TS_STACK_BACKUP_ROOT:-$DOCKER_LOCAL_BACKUP_ROOT}"
        return 0
    fi
    # Under Git Bash this has to agree with the pwsh twin, which writes to
    # %LOCALAPPDATA%/terminal-stack/stack-backups. Two conventions on one machine
    # means a restore looks in the wrong place.
    if [ "$(tss_os)" = windows ] && [ -n "${LOCALAPPDATA:-}" ]; then
        printf '%s' "$(cygpath -u "$LOCALAPPDATA" 2>/dev/null || printf '%s' "$LOCALAPPDATA")/terminal-stack/stack-backups"
        return 0
    fi
    printf '%s' "${XDG_STATE_HOME:-$HOME/.local/state}/terminal-stack/stack-backups"
}

# PREDICATE. Reject a backup root that is far too broad. The .ps1 only rejects
# the drive root; the Unix analogue of that (/) is a very weak floor, so also
# reject $HOME itself and anything outside $HOME or /Volumes.
tss_backup_root_sane() {                   # <resolved-root>
    [ -n "${TS_STACK_ALLOW_ANY_BACKUP_ROOT:-${DOCKER_LOCAL_ALLOW_ANY_BACKUP_ROOT:-}}" ] && return 0
    local r="$1" home
    home="$(tss_realpath "$HOME")" || return 1
    [ "$r" = / ] && return 1
    [ "$r" = "$home" ] && return 1
    case "$r/" in "$home"/*|/Volumes/*) return 0 ;; *) return 1 ;; esac
}

# PREDICATE. Docker Desktop for Mac only shares $HOME, /tmp, /private and
# /Volumes by default; a bind mount from anywhere else fails at run time. Must
# be checked BEFORE a script stops the stack, or the stack is already down when
# the mount fails.
tss_assert_docker_shareable() {            # <absolute-path>
    # Windows shares whole drives rather than a fixed list of trees, and the
    # path is translated by tss_docker_path before it reaches the engine.
    case "$(tss_os)" in linux|windows) return 0 ;; esac
    local p home
    p="$(tss_realpath "$1")" || return 1
    home="$(tss_realpath "$HOME")" || return 1
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
tss_rand_hex() {
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
tss_replace_in_file() {                    # <file> <js-regex> <replacement>
    node - "$1" "$2" "$3" <<'TSS_NODE_EOF'
const fs = require("node:fs");
// `node -` keeps "-" as argv[1], so the real arguments start at 2.
const [f, re, rep] = process.argv.slice(2);
const before = fs.readFileSync(f, "utf8");
// "m" as well as "g": callers anchor line-oriented patterns with ^ and $, and
// without it ^ only ever matches the start of the file.
const after = before.replace(new RegExp(re, "gm"), rep);
if (after === before) process.exit(3);
if (!after.length) process.exit(4);
const tmp = f + ".tmp" + process.pid;
fs.writeFileSync(tmp, after);
fs.renameSync(tmp, f);
TSS_NODE_EOF
}

# ── Listening sockets ────────────────────────────────────────────────────────
# Prints one bare address per line (no :port) for whatever is listening on
# <port>. Returns 2 when no tool is available to tell — callers MUST treat 2
# differently from "nothing listening", which is an empty result with status 0.
_tss_listen_addrs() {                      # <port>
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

_tss_addr_is_loopback() {
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
    addrs="$(_tss_listen_addrs "$1")" || return 1
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
        addrs="$(_tss_listen_addrs "$port")"; rc=$?
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
            if _tss_addr_is_loopback "$addr"; then
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
tss_assert_publish_loopback() {
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
# TSS_HTTP_STATUS and TSS_HTTP_TIME_MS are set by http_status. curl's
# %{time_total} replaces [Diagnostics.Stopwatch]: $SECONDS is whole-second only
# and `date +%s%3N` does not exist on macOS.
#
# CAVEAT: those globals only survive when http_status is called directly --
#   http_status "$url" 8 >/dev/null; echo "$TSS_HTTP_TIME_MS"
# Calling it as `s=$(http_status "$url")` runs it in a subshell, so you get the
# printed status but the timing globals keep their previous values.
http_status() {                           # <url> [timeout] -> prints status code
    # No pipeline here on purpose: a `... | read` puts the read in a subshell,
    # so TSS_HTTP_STATUS would never reach the caller.
    local out t
    out="$(curl -sS -o /dev/null -w '%{http_code} %{time_total}' --max-time "${2:-20}" "$1" 2>/dev/null)" || out='000 0'
    TSS_HTTP_STATUS="${out%% *}"
    t="${out#* }"
    TSS_HTTP_TIME_MS="$(awk -v t="${t:-0}" 'BEGIN{printf "%.0f", t*1000}')"
    printf '%s' "$TSS_HTTP_STATUS"
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
json_get() { node "$TSS_ROOT/_json.mjs" get "$1" "$2"; }
json_set() { node "$TSS_ROOT/_json.mjs" set "$1" "$2" "$3"; }
json_eq()  { node "$TSS_ROOT/_json.mjs" eq  "$1" "$2" "$3"; }
json_str() { node "$TSS_ROOT/_json.mjs" str "$1"; }

# GNU `date -d` is not on macOS and BSD `date -j -f` is not on Linux, so a
# per-OS split here would mean two incompatible dialects to maintain.
tss_iso_age_minutes() {                    # <iso8601> -> whole minutes, or empty
    node -e 'const t=Date.parse(process.argv[1]); if(!isNaN(t)) console.log(Math.floor((Date.now()-t)/60000))' "$1" 2>/dev/null
}

# ── .env reading ─────────────────────────────────────────────────────────────
tss_env_value() {                          # <env-file> <key> -> value, or non-zero
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
_tss_file_mode() { stat -f '%Lp' "$1" 2>/dev/null || stat -c '%a' "$1" 2>/dev/null; }

tss_secret_cache_path() {
    printf '%s' "${XDG_CONFIG_HOME:-$HOME/.config}/terminal-stack/agentmemory.secret"
}

# The pre-merge location. Still WRITTEN, not just read: the reader is JavaScript
# injected into vendor hook files on live machines, and those are only rewritten
# when `ts-agentmemory --apply` runs -- so a machine can be carrying the old
# reader for a while after this clone updates. Dropping the old path silently
# turns 401-recovery back into a permanent no-op, which is the exact failure that
# cost 56 consecutive captures on 2026-08-21 with nothing in any log.
tss_secret_cache_path_legacy() {
    printf '%s' "${XDG_CONFIG_HOME:-$HOME/.config}/docker-local/agentmemory.secret"
}

# Write the cache to both paths, 0600, creating the directories. Callers that
# refresh the secret must use this rather than writing the new path alone.
tss_secret_cache_write() {                 # <secret>
    local secret="$1" path
    [ -n "$secret" ] || return 1
    for path in "$(tss_secret_cache_path)" "$(tss_secret_cache_path_legacy)"; do
        mkdir -p "$(dirname "$path")" 2>/dev/null || continue
        # Create private, then fill: a world-readable window is still a window,
        # and agentmemory_secret refuses a cache that is not mode 600 anyway.
        ( umask 077; printf '%s' "$secret" > "$path" ) || continue
        chmod 600 "$path" 2>/dev/null || true
    done
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
    local cache mode dir out legacy
    if [ -n "${AGENTMEMORY_SECRET:-}" ]; then printf '%s' "$AGENTMEMORY_SECRET"; return 0; fi
    # New path first, then the pre-merge one, so a machine that has not re-applied
    # its hook edits yet still finds its cache.
    for cache in "$(tss_secret_cache_path)" "$(tss_secret_cache_path_legacy)"; do
        [ -f "$cache" ] || continue
        mode="$(_tss_file_mode "$cache")"
        if [ "$mode" = 600 ]; then
            tr -d '\r\n' < "$cache"; return 0
        fi
        warn "$cache is mode ${mode:-unknown}, not 600 — refusing to use it. chmod 600 it, or delete it."
    done
    dir="${1:-$TSS_STACKS/agentmemory}"
    out="$( cd "$dir" 2>/dev/null && docker compose exec -T agentmemory cat /data/.hmac 2>/dev/null )" || return 1
    [ -n "$out" ] || return 1
    out="$(printf '%s' "$out" | tr -d '\r\n')"
    # Refresh both cache paths while we have the authoritative value in hand.
    tss_secret_cache_write "$out" 2>/dev/null || true
    printf '%s' "$out"
}

# Read a raw credential file, refusing anything that looks wrong. The mode check
# is Unix-only and deliberate: these files hold provider admin keys.
tss_read_raw_secret() {                    # <path> <label>
    local p="$1" label="$2" mode v
    [ -f "$p" ] || { printf '%s not found: %s\n' "$label" "$p" >&2; return 1; }
    mode="$(_tss_file_mode "$p")"
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
tss_compose_files() {                      # <stack-dir> -> one file per line
    local dir="$1" sep spec
    sep="$(tss_env_value "$dir/.env" COMPOSE_PATH_SEPARATOR 2>/dev/null)" || sep=':'
    [ -n "$sep" ] || sep=':'
    spec="$(tss_env_value "$dir/.env" COMPOSE_FILE 2>/dev/null)" || spec=''
    if [ -z "$spec" ]; then printf 'docker-compose.yml\n'; return 0; fi
    printf '%s\n' "$spec" | tr "$sep" '\n' | sed '/^[[:space:]]*$/d; s/^[[:space:]]*//; s/[[:space:]]*$//'
}

# PREDICATE. A stack shipping a .env.example with no .env is misconfigured:
# compose silently falls back to the base file only, which for kokoro means
# starting the GPU image with no GPU access.
tss_env_seeded() {                         # <stack-dir>
    [ -f "$1/.env.example" ] || return 0
    [ -f "$1/.env" ]
}

# Derive a service's image rather than hardcoding it. migrate-durable-llm.ps1:56
# hardcodes `agentmemory-agentmemory:latest`, which is right only because the
# compose project name happens to derive from the directory name.
tss_compose_image() {                      # <stack-dir> <service>
    local cfg img proj
    cfg="$( cd "$1" && docker compose config --format json 2>/dev/null )" || return 1
    img="$(printf '%s' "$cfg" | node "$TSS_ROOT/_json.mjs" get - "services.$2.image" 2>/dev/null)"
    if [ -n "$img" ] && [ "$img" != null ]; then printf '%s' "$img"; return 0; fi
    proj="$(printf '%s' "$cfg" | node "$TSS_ROOT/_json.mjs" get - name 2>/dev/null)"
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
tss_agentmemory_source() {
    local p
    if [ -n "${AGENTMEMORY_SOURCE_PATH:-}" ]; then p="$AGENTMEMORY_SOURCE_PATH"
    else
        p="$(tss_env_value "$TSS_STACKS/agentmemory/.env" AGENTMEMORY_SOURCE_PATH 2>/dev/null)" || p=''
        [ -n "$p" ] || p="$TSS_ROOT/../../../../../public/github.com/agentmemory"
    fi
    [ -f "$p/package.json" ] || return 1
    tss_realpath "$p"
}

# The pinned version this repo builds, from the compose build args.
tss_agentmemory_pinned_version() {
    sed -n 's/^[[:space:]]*AGENTMEMORY_VERSION:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' \
        "$TSS_STACKS/agentmemory/docker-compose.yml" 2>/dev/null | head -n 1 || true
}

# ── ts-stack: discovery, toggles, engine, compose ────────────────────────────
# Everything below is used by bootstrap/ts-stack.sh. Its pwsh twin carries the
# same logic inline (bootstrap/ts-stack.ps1) — change one, change the other.

# Every stack, one per line, lexically sorted. A stack is a directory holding a
# docker-compose.yml; there is no registry.
tss_stack_list() {
    local d
    for d in "$TSS_STACKS"/*/; do
        [ -f "$d/docker-compose.yml" ] || continue
        basename "$d"
    done | tss_stack_order
}

# Start order. Lexical order is wrong the moment one stack joins another's
# network: agent007memory sorts BEFORE agentmemory ('0' < 'm'), and an external
# network cannot be joined before it exists. A stack declares what it must
# follow in an optional `ts-after` file, one stack name per line -- discovered
# like everything else here, never registered.
#
# Repeated passes rather than a real topological sort: the input is a handful of
# stacks, and a cycle degrades to "leave the order alone" instead of hanging.
tss_stack_order() {
    local names line moved pass name after
    names="$(cat)"
    for pass in 1 2 3 4 5; do
        moved=0
        for name in $names; do
            [ -f "$TSS_STACKS/$name/ts-after" ] || continue
            while IFS= read -r after; do
                case "$after" in ''|'#'*) continue ;; esac
                # Already later than its dependency? Nothing to do.
                case "
$names
" in *"
$after
"*) ;; *) continue ;; esac
                if [ "$(printf '%s
' "$names" | grep -n -x -- "$after" | cut -d: -f1)"                      -gt "$(printf '%s
' "$names" | grep -n -x -- "$name" | cut -d: -f1)" ]; then
                    names="$(printf '%s
' "$names" | grep -v -x -- "$name")"
                    names="$(printf '%s
' "$names" | awk -v a="$after" -v n="$name"                         '{print} $0==a{print n}')"
                    moved=1
                fi
            done < "$TSS_STACKS/$name/ts-after"
        done
        [ "$moved" = 0 ] && break
    done
    printf '%s
' "$names"
}

tss_stack_dir() { printf '%s' "$TSS_STACKS/$1"; }

# PURE. Which saved terminal-stack setting gates this stack, or "" for none.
# `kokoro` is special: it is gated on the TTS engine as well as the switch, so
# the caller checks both — this only names the primary key.
tss_toggle_for() {
    case "$1" in
        agentmemory) printf 'agentmemoryEnabled' ;;
        # The console is part of the agentmemory feature, not a separate choice:
        # a machine that wants memories wants the proxy every client is pointed
        # at. Separate PROJECT, same switch.
        agent007memory) printf 'agentmemoryEnabled' ;;
        headroom)    printf 'headroomEnabled' ;;
        playwright)  printf 'playwrightEnabled' ;;
        kokoro)      printf 'ccTts' ;;
        *)           printf '' ;;
    esac
}

# ── engine ───────────────────────────────────────────────────────────────────
# `docker` on PATH is not evidence. Inside WSL with Docker Desktop's integration
# switched off, PATH still holds Desktop's stub, which exits 1 for every command
# and prints "could not be found in this WSL 2 distro" ON STDOUT. `have docker`
# is therefore true and useless, and the old require_docker diagnosed it as "is
# Docker Desktop running?" — the wrong answer when the engine is perfectly
# healthy on the Windows side.
#
# Returns exactly one of: native | wsl-shim | absent | denied
# TS_STACK_DOCKER_PROBE overrides the whole probe for tests.
tss_docker_kind() {
    [ -n "${TS_STACK_DOCKER_PROBE:-}" ] && { printf '%s' "$TS_STACK_DOCKER_PROBE"; return 0; }

    local bin out
    bin="$(command -v docker 2>/dev/null)" || { printf 'absent'; return 0; }

    # The shim lives under a Windows mount and there is no Linux docker beside it.
    case "$bin" in
        /mnt/[a-z]/*)
            [ -x /usr/bin/docker ] || { printf 'wsl-shim'; return 0; } ;;
    esac
    # Belt and braces: the stub prints to STDOUT, so 2>&1 is not enough on its own.
    out="$(docker version 2>&1 || true)"
    case "$out" in
        *"could not be found in this WSL"*) printf 'wsl-shim'; return 0 ;;
    esac

    if docker info >/dev/null 2>&1; then printf 'native'; return 0; fi
    out="$(docker info 2>&1 || true)"
    case "$out" in
        *"permission denied while trying to connect"*) printf 'denied'; return 0 ;;
    esac
    printf 'native'   # CLI present, engine down — the caller reports that
}

tss_engine_up() { [ "$(tss_docker_kind)" = native ] && docker info >/dev/null 2>&1; }

# PURE. <os> <kind> -> the advice line(s). Split out so it is unit-testable with
# no Docker anywhere: the string IS the deliverable of a failed probe.
tss_engine_advice() {                       # <os> <kind>
    case "$2" in
        wsl-shim)
            printf '%s\n' \
                'the `docker` on PATH is Docker Desktop'"'"'s stub — it exits 1 for every' \
                'command and says nothing about whether the engine is healthy.' \
                '  fix either way:' \
                '    Docker Desktop -> Settings -> Resources -> WSL Integration -> enable this distro' \
                '    or run the Windows twin:  ts-stack <command>   (from PowerShell)' ;;
        denied)
            printf '%s\n' \
                'the engine is there but this user may not talk to it.' \
                '  fix:  sudo usermod -aG docker "$USER"   then LOG OUT and back in' \
                '        (a new shell in the same session does not pick the group up)' ;;
        absent)
            case "$1" in
                darwin) printf '%s\n' 'no container engine found.' \
                    '  fix:  brew install --cask docker      (Docker Desktop)' \
                    '        brew install colima && colima start   (lighter, no GUI)' ;;
                linux)  printf '%s\n' 'no container engine found.' \
                    '  fix:  see `doc docker` for the docker-ce install for your distro' ;;
                *)      printf '%s\n' 'no container engine found.' \
                    '  fix:  winget install --id Docker.DockerDesktop --exact' ;;
            esac ;;
        *)
            case "$1" in
                darwin) printf '%s\n' 'the engine is not answering.' \
                    '  fix:  open -a Docker      (or: colima start)' ;;
                linux)  printf '%s\n' 'the engine is not answering.' \
                    '  fix:  sudo systemctl start docker    (rootless: systemctl --user start docker)' ;;
                *)      printf '%s\n' 'the engine is not answering.' \
                    '  fix:  start Docker Desktop, or re-run with --start-engine' ;;
            esac ;;
    esac
}

# ── the compose choke point ──────────────────────────────────────────────────
# EVERY docker invocation goes through here, which is what makes three
# invariants testable rather than merely intended:
#   * `down` never receives -v (the two paths that do are explicit and gated)
#   * the billing overlay always gets --env-file .env BEFORE --env-file
#     .billing.env — a lone --env-file REPLACES the interpolation source, so
#     every ${OPENAI_*}-derived LLM_* display value silently resolves to ""
#   * TS_STACK_DRY_RUN=1 prints the exact argv and runs nothing
# The --env-file list for a stack, in order, one per line. Compose reads these
# as INTERPOLATION sources; nothing here is injected into a container.
#
# Order is the whole point. `--env-file .billing.env` alone REPLACES .env as the
# interpolation source, so every ${...} default resolves to empty -- which is how
# the console's provider panel went blank while everything reported healthy.
# Extras from `ts-envfiles` come first so the stack's own .env always wins.
tss_env_file_list() {                       # <stack-dir>
    local dir="$1" line
    if [ -f "$dir/ts-envfiles" ]; then
        while IFS= read -r line; do
            case "$line" in ''|'#'*) continue ;; esac
            [ -f "$dir/$line" ] || continue
            printf '%s
' "$line"
        done < "$dir/ts-envfiles"
    fi
    [ -f "$dir/.env" ] && printf '%s
' .env
    [ -f "$dir/.billing.env" ] && printf '%s
' .billing.env
    return 0
}

tss_compose() {                             # <stack> <compose args...>
    local stack="$1"; shift
    local dir; dir="$(tss_stack_dir "$stack")"
    local -a pre; pre=()
    local f
    # Only pass --env-file at all when there is something beyond the default
    # .env: compose already reads .env on its own, and naming it explicitly for
    # every stack would be noise in the dry-run argv this is all inspected by.
    if [ -f "$dir/ts-envfiles" ] || [ -f "$dir/.billing.env" ]; then
        while IFS= read -r f; do
            [ -n "$f" ] && pre=(${pre[@]+"${pre[@]}"} --env-file "$f")
        done <<EOF
$(tss_env_file_list "$dir")
EOF
    fi
    if [ "${TS_STACK_DRY_RUN:-0}" = 1 ]; then
        printf '(%s) docker compose %s%s\n' "$stack" \
            "$([ ${#pre[@]} -gt 0 ] && printf '%s ' "${pre[@]}")" "$*"
        return 0
    fi
    ( cd "$dir" && docker compose ${pre[@]+"${pre[@]}"} "$@" )
}

# ── the pre-ts- volume names ─────────────────────────────────────────────────
# Renaming a volume is the only part of the naming sweep that touches data.
# `docker compose up` would create an empty replacement and start the stack with
# no memories in it, reporting success, so `ts-stack up` refuses while a legacy
# volume exists and its new name does not.
#
# One "old new" pair per line. The headroom three carry their old project
# prefix because they were plain named volumes under a project called headroom;
# the two agentmemory volumes are external, so they never had one.
tss_volume_renames() {
    cat <<'EOF'
agentmemory_iii-data ts-agentmemory-data
agent007memory_history ts-agentmemory-console-history
headroom_headroom_workspace ts-headroom-workspace
headroom_qdrant_data ts-headroom-qdrant
headroom_neo4j_data ts-headroom-neo4j
EOF
}

tss_volume_exists() { docker volume inspect "$1" >/dev/null 2>&1; }

# Pairs still needing migration, one "old new" per line. Empty output = nothing
# to do, which is also the answer on a machine that never had the old names.
tss_volumes_pending() {
    local old new
    tss_volume_renames | while read -r old new; do
        [ -n "$old" ] || continue
        if tss_volume_exists "$old" && ! tss_volume_exists "$new"; then
            printf '%s %s\n' "$old" "$new"
        fi
    done
}

# Copy one volume's contents into a new volume, in a container, and verify the
# file count came across. The old volume is left ALONE: it is the rollback.
tss_volume_copy() {                        # <old> <new>
    local old="$1" new="$2" before after
    before="$(docker run --rm -v "$old:/from:ro" alpine sh -c 'find /from -type f | wc -l' 2>/dev/null | tr -d ' \r')"
    [ -n "$before" ] || { warn "$old: could not be read"; return 1; }
    docker volume create "$new" >/dev/null || return 1
    # -a preserves modes and times; /data/.hmac is 0600 and must stay that way.
    docker run --rm -v "$old:/from:ro" -v "$new:/to" alpine \
        sh -c 'cp -a /from/. /to/ 2>/dev/null || cp -R /from/. /to/' || return 1
    after="$(docker run --rm -v "$new:/to:ro" alpine sh -c 'find /to -type f | wc -l' 2>/dev/null | tr -d ' \r')"
    if [ "$before" != "$after" ]; then
        warn "$old -> $new: $before files in, $after out — NOT removing anything, and the new volume is suspect"
        return 1
    fi
    pass "$old -> $new ($after files)"
}

# ── first-run setup ──────────────────────────────────────────────────────────
# Seed <stack>/.env from its .env.example. A stack with a .env.example and no
# .env is not "unconfigured", it is MIS-configured: compose falls back to the
# base file only, which for kokoro means starting the GPU image with no GPU.
tss_seed_env() {                           # <stack-dir>
    local ex="$1/.env.example" env="$1/.env"
    [ -f "$ex" ] || return 0
    if [ -f "$env" ]; then
        info "$(basename "$1")/.env already exists — left untouched"
        return 0
    fi
    step "copy $(basename "$1")/.env.example -> .env"
    [ "$TSS_APPLY" = 1 ] || return 0
    cp "$ex" "$env" || return 1
    info 'seeded with the default profile — review it before starting the stack'
    # kokoro is the one stack whose default profile is WRONG on most machines:
    # its .env.example ships Profile A (Blackwell, CUDA 12.8) uncommented, which
    # a blind copy then hands to a Mac. `ts-stack up kokoro` merges the NVIDIA
    # device reservation and fails on "could not select device driver", after
    # pulling several GB of amd64 CUDA image. setup-kokoro-docker.sh already
    # refuses GPU on darwin; this is the same knowledge, applied to the file that
    # compose actually reads.
    case "$(basename "$1")" in kokoro) tss_seed_kokoro_profile "$env" || return 1 ;; esac
}

# Rewrite a freshly seeded kokoro .env for THIS machine's hardware. Only ever
# called on a file this run just created, so it cannot overwrite a profile
# somebody chose. Profiles are the three in kokoro/.env.example; tss_gpu_profile
# already encodes which one a machine needs and why.
tss_seed_kokoro_profile() {                # <env-file>
    local env="$1" spec image
    tss_gpu_profile
    case "$TSS_GPU_PROFILE" in
        A) spec='docker-compose.yml:docker-compose.gpu.yml'
           image='ghcr.io/remsky/kokoro-fastapi-gpu:v0.8.0-cu128' ;;
        B) spec='docker-compose.yml:docker-compose.gpu.yml'
           image='ghcr.io/remsky/kokoro-fastapi-gpu:v0.8.0-cu126' ;;
        *) spec='docker-compose.yml'
           image='ghcr.io/remsky/kokoro-fastapi-cpu:v0.8.0' ;;
    esac
    info "kokoro profile $TSS_GPU_PROFILE — $TSS_GPU_REASON"
    # Status 3 means the pattern matched nothing, which for a file we just copied
    # from the tracked example means the example changed shape. Say so; a silent
    # no-op here is how the GPU default gets shipped to a Mac all over again.
    tss_replace_in_file "$env" '^COMPOSE_FILE=.*$' "COMPOSE_FILE=$spec" \
        || { warn "$env: no COMPOSE_FILE line to set — check it by hand"; return 1; }
    tss_replace_in_file "$env" '^KOKORO_IMAGE=.*$' "KOKORO_IMAGE=$image" \
        || { warn "$env: no KOKORO_IMAGE line to set — check it by hand"; return 1; }
    return 0
}

# Replace a still-placeholder value with real random bytes. Never rotates a value
# somebody set: that is what makes a re-run idempotent, and what stops a second
# bootstrap silently invalidating a live proxy token.
tss_fill_secret() {                        # <env-file> <key> <placeholder> <bytes>
    local file="$1" key="$2" placeholder="$3" bytes="${4:-32}" current secret
    [ -f "$file" ] || return 0
    current="$(tss_env_value "$file" "$key" 2>/dev/null || true)"
    if [ -n "$current" ] && [ "$current" != "$placeholder" ]; then
        info "$key already set — left untouched"
        return 0
    fi
    step "generate $key ($bytes random bytes)"
    [ "$TSS_APPLY" = 1 ] || return 0
    secret="$(tss_rand_hex "$bytes")" || { warn "could not generate $key"; return 1; }
    # tss_replace_in_file, not sed: `sed -i` needs -i '' on BSD and rejects it on
    # GNU, and sed appends a trailing newline to a file that lacked one. Its
    # pattern is a JS regex, so anchor to the start of a line and match the rest
    # of it rather than trusting the current value to be regex-safe.
    tss_replace_in_file "$file" "^$key=.*$" "$key=$secret" || return 1
    # A fingerprint, never the value: a secret echoed to a terminal lives in
    # scrollback, and this one is also in `docker logs` until rotation.
    info "$key set (${secret%"${secret#??????}"}...${secret#"${secret%????}"})"
}

# ── declarative checks ───────────────────────────────────────────────────────
# Each stack ships ts-checks.conf; a new stack registers itself by having one.
# Fields: kind id expect secs target

# Every check file in effect for a stack: ts-checks.conf, plus one per compose
# OVERLAY this machine has selected. `docker-compose.<x>.yml` pairs with
# `ts-checks.<x>.conf` by name — no registry, same rule as everything else here.
#
# Without this an overlay's services either go unchecked, or their checks sit in
# the base file and fail on every machine that has not enabled the overlay.
# headroom is the case that forced it: its Qdrant and Neo4j checks were asserted
# everywhere, and passed everywhere, while nothing had ever written to either.
tss_check_files() {                        # <stack> -> one path per line
    local stack="$1" dir f name
    dir="$(tss_stack_dir "$stack")"
    [ -f "$dir/ts-checks.conf" ] && printf '%s\n' "$dir/ts-checks.conf"
    while IFS= read -r f; do
        case "$f" in
            docker-compose.yml|'') continue ;;
            docker-compose.*.yml) name="${f#docker-compose.}"; name="${name%.yml}" ;;
            *) continue ;;
        esac
        [ -f "$dir/ts-checks.$name.conf" ] && printf '%s\n' "$dir/ts-checks.$name.conf"
    done <<EOF
$(tss_compose_files "$dir")
EOF
    return 0
}

tss_run_checks() {                         # <stack>   -> 0 all passed
    local stack="$1" conf kind id expect secs target rc=0 deadline confs
    confs="$(tss_check_files "$stack")"
    [ -n "$confs" ] || { info "$stack: no ts-checks.conf"; return 0; }
    for conf in $confs; do
    while read -r kind id expect secs target; do
        case "${kind:-}" in ''|'#'*) continue ;; esac
        case "$kind" in
            health)
                if tss_wait_healthy "$id" "$secs"; then pass "$stack/$id healthy"
                else fail "$stack/$id not healthy within ${secs}s"; rc=1
                     docker logs --tail 40 "$id" 2>&1 | sed 's/^/        /' | tail -40
                fi ;;
            http)
                # Any response means something is listening. A 404 or a 401 is
                # not "down" -- that distinction is why there are two kinds here.
                if tss_wait_http "$target" "$secs" any; then pass "$stack/$id answering"
                else fail "$stack/$id no response from $target in ${secs}s"; rc=1; fi ;;
            http-ok)
                if tss_wait_http "$target" "$secs" 2xx; then pass "$stack/$id 2xx"
                else fail "$stack/$id not 2xx from $target in ${secs}s"; rc=1; fi ;;
            port)
                tss_port_publication "$target"; case $? in
                    0) pass "$stack/$id published on 127.0.0.1:$target" ;;
                    1) fail "$stack/$id port $target is published BEYOND loopback"; rc=1 ;;
                    2) fail "$stack/$id port $target is not published at all"; rc=1 ;;
                esac ;;
            *) warn "$stack: unknown check kind '$kind'" ;;
        esac
    done < "$conf"
    done
    return $rc
}

# A container is healthy when compose says so; a container with NO healthcheck
# only has to be running (docs/service-conventions.md says every service should
# declare one, so this is the fallback, not the norm).
tss_wait_healthy() {                       # <container> <seconds>
    local name="$1" secs="${2:-60}" waited=0 state health
    while [ "$waited" -lt "$secs" ]; do
        state="$(docker inspect -f '{{.State.Status}}' "$name" 2>/dev/null || true)"
        health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$name" 2>/dev/null || true)"
        case "$health" in
            healthy) return 0 ;;
            unhealthy) : ;;
            '') [ "$state" = running ] && return 0 ;;
        esac
        sleep 2; waited=$((waited + 2))
    done
    return 1
}

# <url> <seconds> <any|2xx>
tss_wait_http() {
    local url="$1" secs="${2:-10}" mode="${3:-any}" waited=0 code
    while :; do
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null)" || code=000
        case "$mode:$code" in
            any:000) : ;;
            any:*)   return 0 ;;
            2xx:2??) return 0 ;;
        esac
        [ "$waited" -ge "$secs" ] && return 1
        sleep 2; waited=$((waited + 2))
    done
}

# Published AND loopback-only. Never skipped by a toggle: a service here that is
# reachable off-box is a security incident, not an outage, and none of them
# authenticate.
#
# Returns 0 loopback-only, 1 published beyond loopback, 2 NOT PUBLISHED AT ALL.
# Three outcomes, not two, because a check that cannot tell "absent" from "bad"
# reports the wrong one -- which is exactly what happened here.
#
# Docker collapses contiguous ports into a range, so 3113 appears as
# `127.0.0.1:3112-3113->3112-3113/tcp` and a literal `:3113->` finds nothing.
tss_port_publication() {                   # <port> -> 0 loopback | 1 exposed | 2 absent
    local port="$1" line addr lo hi found=0
    while IFS= read -r line; do
        case "$line" in *"->"*) ;; *) continue ;; esac
        addr="${line%%:*}"; addr="${addr# }"
        lo="${line#*:}"; lo="${lo%%->*}"
        hi="$lo"
        case "$lo" in *-*) hi="${lo#*-}"; lo="${lo%%-*}" ;; esac
        case "$lo$hi" in *[!0-9]*) continue ;; esac
        [ "$port" -ge "$lo" ] && [ "$port" -le "$hi" ] || continue
        found=1
        [ "$addr" = "127.0.0.1" ] || return 1
    done <<EOF
$(docker ps --format '{{.Ports}}' 2>/dev/null | tr ',' '\n')
EOF
    [ "$found" = 1 ] || return 2
    return 0
}

tss_assert_loopback_port() {               # <port>
    tss_port_publication "$1"
}

# Every published port of every container THIS STACK owns. Runs even when
# everything else failed.
#
# Scoped to ts- containers on purpose: a developer's own projects legitimately
# publish on 0.0.0.0, and failing this check on them is noise -- which is how the
# one check that must never be skipped ends up ignored.
tss_audit_loopback() {
    local bad
    bad="$(docker ps --filter 'name=ts-' --format '{{.Names}} {{.Ports}}' 2>/dev/null \
           | tr ',' '\n' | grep -E '[0-9]+->' | grep -v '127\.0\.0\.1:' || true)"
    [ -z "$bad" ] || { printf '%s\n' "$bad"; return 1; }
    return 0
}

# ── backup ───────────────────────────────────────────────────────────────────
# Every volume this stack owns, whether external or not, INCLUDING any that still
# carries its pre-ts- name. Listing only the new names made `backup` a no-op on
# exactly the machine that needed it most: the one about to migrate.
#
# The two memory volumes come first because they are the ones you would miss.
tss_data_volumes() {
    local new old
    for new in ts-agentmemory-data ts-agentmemory-console-history \
               ts-headroom-workspace ts-headroom-qdrant ts-headroom-neo4j; do
        tss_volume_exists "$new" && printf '%s\n' "$new"
    done
    tss_volume_renames | while read -r old new; do
        [ -n "$old" ] || continue
        tss_volume_exists "$old" && printf '%s\n' "$old"
    done
    return 0
}

# Where backups go. NOT C:\DATA: that is one person's path. On macOS $HOME is
# also the only tree Docker Desktop shares by default, so a backup root outside
# it cannot be bind-mounted at all.
tss_backup_dir() {
    local root
    if [ -n "${TS_STACK_BACKUP_ROOT:-}" ]; then root="$TS_STACK_BACKUP_ROOT"
    elif [ -n "${LOCALAPPDATA:-}" ]; then root="$LOCALAPPDATA/terminal-stack/stack-backups"
    else root="${XDG_STATE_HOME:-$HOME/.local/state}/terminal-stack/stack-backups"; fi
    printf '%s/%s' "$root" "$(stamp)"
}

# tar one volume into <dir>, then VERIFY the archive before anything is torn
# down. A backup that is only checked after the teardown is not a backup.
tss_backup_volume() {                      # <volume> <dir>
    local vol="$1" dir="$2" out="$2/$1.tgz" bytes
    docker volume inspect "$vol" >/dev/null 2>&1 || { info "$vol does not exist — skipped"; return 0; }
    step "backup $vol"
    [ "$TSS_APPLY" = 1 ] || return 0
    local mnt; mnt="$(tss_docker_path "$dir")"
    docker run --rm -v "$vol:/from:ro" -v "$mnt:/to" alpine \
        sh -c "tar -C /from -czf /to/$vol.tgz ." || { warn "$vol: tar failed"; return 1; }
    docker run --rm -v "$mnt:/to:ro" alpine sh -c "tar -tzf /to/$vol.tgz >/dev/null" \
        || { warn "$vol: the archive does not read back"; return 1; }
    bytes="$(file_size "$out" 2>/dev/null || echo 0)"
    [ "$bytes" -gt 100 ] || { warn "$vol: archive is suspiciously small ($bytes bytes)"; return 1; }
    printf '%s %s %s\n' "$vol" "$bytes" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$dir/manifest.txt"
    pass "$vol -> $out ($bytes bytes)"
}

tss_backup_all() {
    local dir rc=0 v
    dir="$(tss_backup_dir)"
    step "mkdir -p $dir"
    if [ "$TSS_APPLY" = 1 ]; then
        mkdir -p "$dir" || return 1
        tss_assert_docker_shareable "$dir" \
            || { warn "$dir cannot be bind-mounted by this engine — set TS_STACK_BACKUP_ROOT under \$HOME"; return 1; }
        : > "$dir/manifest.txt"
    fi
    for v in $(tss_data_volumes); do
        tss_backup_volume "$v" "$dir" || rc=1
    done
    [ "$rc" = 0 ] && info "restore with: ts-stack restore $(basename "$dir")"
    return $rc
}
