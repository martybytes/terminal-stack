#!/usr/bin/env bash
# _smb.sh — SMB/CIFS share library for `ts-smb`. Everything goes through rclone:
# one binary, one flag vocabulary, on macOS and Linux alike. Listing the root of
# an SMB host enumerates its shares, so `rclone lsd` is both the discovery
# primitive and the browse primitive.
#
# This file is sourced, not executed. Do not `exit`; return non-zero instead.
# Stays bash-3.2 clean (macOS ships 3.2): no associative arrays, no ${x,,}.
#
# There is no pwsh twin yet — see the header of ts-smb.sh. When one is written,
# note that the store's `flags` directive carries a free-form tail: a pwsh
# `-split '\s+'` would destroy it, so that parser must split with a limit of 3.
#
# Two rules in here are load-bearing and easy to undo by accident:
#
#   1. On darwin, NEVER run `rclone mount` without CGOFUSE_LIBFUSE_PATH set.
#      cgofuse's dlopen order is fixed — $CGOFUSE_LIBFUSE_PATH, then macFUSE's
#      libfuse.2.dylib, then libosxfuse.2.dylib, then libfuse-t.dylib — so a
#      stale macFUSE wins over a working FUSE-T and the mount HANGS rather than
#      failing. There is no --fuse-lib flag; the env var is the only lever.
#
#   2. NEVER stat/ls/test -d/glob a mountpoint. On a dead FUSE mount those block
#      forever and take the calling shell with them. Liveness is read from the
#      kernel mount table only, which never touches the filesystem.

: "${INFO:=$'\033[1;34m==>\033[0m'}"
: "${WARN:=$'\033[1;33m!!\033[0m'}"

TS_SMB_FIELDS="host path mountpoint user domain port cred engine vfs remote flags"
TS_SMB_CRED_SERVICE="terminal-stack-smb"

# Lowercase without bash 4's ${x,,} — macOS bash 3.2 has to work too.
ts_smb_lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }

ts_smb_os() {
    case "$(uname -s 2>/dev/null || echo unknown)" in
        Darwin) echo darwin ;;
        Linux)  echo linux ;;
        *)      echo unknown ;;
    esac
}

# macOS has no timeout(1); brew coreutils supplies gtimeout, and neither is
# guaranteed. Fall back to a background watchdog so callers can always bound a
# command that might never return (dns-sd, a wedged mount probe).
# usage: ts_smb_timeout <seconds> <cmd> [args...]
ts_smb_timeout() {
    local secs="$1"; shift
    if command -v timeout >/dev/null 2>&1; then
        timeout "$secs" "$@"
        return $?
    fi
    if command -v gtimeout >/dev/null 2>&1; then
        gtimeout "$secs" "$@"
        return $?
    fi
    "$@" &
    local pid=$! rc=0
    ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null || true ) 2>/dev/null &
    local watchdog=$!
    wait "$pid" 2>/dev/null || rc=$?
    kill -TERM "$watchdog" 2>/dev/null || true
    wait "$watchdog" 2>/dev/null || true
    return "$rc"
}

# ---------------------------------------------------------------- config ----

# The tracked defaults, then the untracked per-machine store. Order matters:
# later files win, so the local file can redefine any setting or any one field
# of a stanza. The tracked file NEVER holds a real host.
ts_smb_conf_files() {
    local dir="${TS_SMB_LIB_DIR:-}"
    [ -n "$dir" ] || dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    [ -f "$dir/shares.conf" ] && printf '%s\n' "$dir/shares.conf"
    local loc; loc="$(ts_smb_local_conf)"
    [ -f "$loc" ] && printf '%s\n' "$loc"
    return 0
}

ts_smb_local_conf() {
    printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/terminal-stack/shares.local.conf"
}

# Populate TS_SMB_SETTINGS / TS_SMB_RECORDS as space-delimited key=value strings
# (records keyed "<name>.<field>", which keeps ts_smb_lookup's last-match-wins
# behaviour for free) and TS_SMB_FLAGS as newline-delimited "<name><TAB><value>",
# because the space-delimited form cannot hold a value containing a space.
#
# Grammar is stanza form, so the workspace.conf tokenizer is unchanged:
#     set   <key>   <value>
#     share <name>            opens a stanza; fields bind to it until the next
#       <field> <value>       `share` or `set`
ts_smb_load_config() {
    [ -n "${TS_SMB_LOADED:-}" ] && [ -z "${TS_SMB_RELOAD:-}" ] && return 0
    TS_SMB_SETTINGS=""; TS_SMB_RECORDS=""; TS_SMB_FLAGS=""; TS_SMB_NAMES=""
    TS_SMB_CONF_ERRORS=""
    local f kind a rest cur="" value
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        while read -r kind a rest || [ -n "$kind" ]; do
            case "$kind" in ''|\#*) continue ;; esac
            case "$kind" in
                set)
                    [ -n "$a" ] || continue
                    cur=""
                    TS_SMB_SETTINGS="$TS_SMB_SETTINGS $a=$(ts_smb_first_token "$rest")"
                    ;;
                share)
                    if [ -z "$a" ]; then
                        TS_SMB_CONF_ERRORS="$TS_SMB_CONF_ERRORS${TS_SMB_CONF_ERRORS:+;}$f: 'share' with no name"
                        continue
                    fi
                    cur="$(ts_smb_lower "$a")"
                    case " $TS_SMB_NAMES " in
                        *" $cur "*) ;;
                        *) TS_SMB_NAMES="$TS_SMB_NAMES $cur" ;;
                    esac
                    ;;
                *)
                    case " $TS_SMB_FIELDS " in
                        *" $kind "*) ;;
                        *)
                            TS_SMB_CONF_ERRORS="$TS_SMB_CONF_ERRORS${TS_SMB_CONF_ERRORS:+;}$f: unknown directive '$kind'"
                            continue
                            ;;
                    esac
                    if [ -z "$cur" ]; then
                        TS_SMB_CONF_ERRORS="$TS_SMB_CONF_ERRORS${TS_SMB_CONF_ERRORS:+;}$f: '$kind' outside any share stanza"
                        continue
                    fi
                    if [ "$kind" = flags ]; then
                        # The one free-form tail. Recombine and strip an inline
                        # comment; a flag VALUE containing a space is not
                        # supported (use a dedicated directive).
                        value="$a${rest:+ $rest}"
                        case "$value" in *" #"*) value="${value%% #*}" ;; esac

                        value="${value%"${value##*[![:space:]]}"}"
                        TS_SMB_FLAGS="$TS_SMB_FLAGS$cur	$value
"
                    else
                        [ -n "$a" ] || continue
                        TS_SMB_RECORDS="$TS_SMB_RECORDS $cur.$kind=$a"
                    fi
                    ;;
            esac
        done < "$f"
    done < <(ts_smb_conf_files)
    TS_SMB_LOADED=1
    export TS_SMB_SETTINGS TS_SMB_RECORDS TS_SMB_FLAGS TS_SMB_NAMES TS_SMB_LOADED
}

# First whitespace-delimited token of a string, so an inline comment after a
# `set` value is dropped the same way `read -r kind a b` drops it elsewhere.
ts_smb_first_token() {
    local t="$1"
    set -- $t
    printf '%s' "${1:-}"
}

# ts_smb_lookup "<a=1 b=2>" <key> <default> — last match wins, so the local file
# appended second beats the tracked default without having to dedupe.
ts_smb_lookup() {
    local list="$1" key="$2" def="$3" pair found=""
    for pair in $list; do
        case "$pair" in "$key="*) found="${pair#*=}" ;; esac
    done
    if [ -n "$found" ]; then printf '%s\n' "$found"; else printf '%s\n' "$def"; fi
}

ts_smb_setting() { ts_smb_load_config; ts_smb_lookup "$TS_SMB_SETTINGS" "$1" "$2"; }

# ts_smb_get <name> <field> <default> — a share's field, falling back to the
# matching `set default_<field>` and then to the caller's default.
ts_smb_get() {
    ts_smb_load_config
    local name field def v
    name="$(ts_smb_lower "$1")"; field="$2"; def="${3:-}"
    v="$(ts_smb_lookup "$TS_SMB_RECORDS" "$name.$field" "")"
    [ -n "$v" ] || v="$(ts_smb_lookup "$TS_SMB_SETTINGS" "default_$field" "")"
    [ -n "$v" ] || v="$def"
    printf '%s\n' "$v"
}

ts_smb_flags() {
    ts_smb_load_config
    local name line out=""
    name="$(ts_smb_lower "$1")"
    while IFS='	' read -r n v; do
        [ "$n" = "$name" ] && out="$v"
    done <<EOF
$TS_SMB_FLAGS
EOF
    printf '%s\n' "$out"
}

ts_smb_names() { ts_smb_load_config; printf '%s\n' "${TS_SMB_NAMES# }"; }

ts_smb_has() {
    ts_smb_load_config
    local name; name="$(ts_smb_lower "$1")"
    case " $TS_SMB_NAMES " in *" $name "*) return 0 ;; *) return 1 ;; esac
}

ts_smb_conf_errors() { ts_smb_load_config; printf '%s\n' "${TS_SMB_CONF_ERRORS:-}"; }

# ~ in a stored mountpoint is expanded here rather than by the shell, because the
# value came out of a config file and was never subject to tilde expansion.
ts_smb_expand_path() {
    local p="$1"
    case "$p" in
        "~") printf '%s\n' "$HOME" ;;
        "~/"*) printf '%s\n' "$HOME/${p#\~/}" ;;
        *) printf '%s\n' "$p" ;;
    esac
}

# The mountpoint a share resolves to: its own directive, else <mount_root>/<name>.
ts_smb_mountpoint() {
    local name="$1" mp
    mp="$(ts_smb_get "$name" mountpoint "")"
    [ -n "$mp" ] || mp="$(ts_smb_setting mount_root '~/mnt')/$(ts_smb_lower "$name")"
    ts_smb_expand_path "$mp"
}

# ----------------------------------------------------------------- state ----

ts_smb_state_dir() {
    printf '%s\n' "${XDG_STATE_HOME:-$HOME/.local/state}/terminal-stack/smb"
}

ts_smb_record_path() { printf '%s\n' "$(ts_smb_state_dir)/$(ts_smb_lower "$1").mnt"; }
ts_smb_log_path()    { printf '%s\n' "$(ts_smb_state_dir)/$(ts_smb_lower "$1").log"; }

# ts_smb_record_write <name> <key> <value> [<key> <value> ...]
# Same whitespace `key value` grammar as the store, so one reader serves both.
ts_smb_record_write() {
    local name="$1"; shift
    local dir; dir="$(ts_smb_state_dir)"
    mkdir -p "$dir" 2>/dev/null || return 1
    local f; f="$(ts_smb_record_path "$name")"
    : > "$f" || return 1
    while [ "$#" -ge 2 ]; do
        printf '%s %s\n' "$1" "$2" >> "$f"
        shift 2
    done
    return 0
}

ts_smb_record_get() {
    local f k v key def
    f="$(ts_smb_record_path "$1")"; key="$2"; def="${3:-}"
    [ -f "$f" ] || { printf '%s\n' "$def"; return 0; }
    local found=""
    while read -r k v || [ -n "$k" ]; do
        [ "$k" = "$key" ] && found="$v"
    done < "$f"
    if [ -n "$found" ]; then printf '%s\n' "$found"; else printf '%s\n' "$def"; fi
}

ts_smb_record_rm() {
    rm -f "$(ts_smb_record_path "$1")" 2>/dev/null || true
    return 0
}

ts_smb_record_names() {
    local dir f n out=""
    dir="$(ts_smb_state_dir)"
    [ -d "$dir" ] || { printf '\n'; return 0; }
    for f in "$dir"/*.mnt; do
        [ -f "$f" ] || continue
        n="${f##*/}"; n="${n%.mnt}"
        out="$out $n"
    done
    printf '%s\n' "${out# }"
}

# ------------------------------------------------------------ mount table ----

# Is this path mounted? Reads the kernel mount table ONLY — never touches the
# path, so a dead FUSE mount cannot hang the caller. See rule 2 in the header.
ts_smb_is_mounted() {
    local mp="$1"
    [ -n "$mp" ] || return 1
    case "$(ts_smb_os)" in
        darwin)
            # `mount` prints "<src> on <path> (<type>, ...)"; the " on " and " ("
            # anchors survive spaces in the path.
            mount 2>/dev/null | grep -qF " on $mp (" && return 0
            return 1
            ;;
        *)
            if [ -r /proc/self/mounts ]; then
                awk -v t="$mp" '{ gsub(/\\040/, " ", $2); if ($2 == t) f=1 } END { exit f?0:1 }' \
                    /proc/self/mounts && return 0
                return 1
            fi
            mount 2>/dev/null | grep -qF " on $mp " && return 0
            return 1
            ;;
    esac
}

# Every mount that looks like an rclone mount, one "<fstype> <target>" per line.
# Best-effort: used only to report strays, never to decide anything.
ts_smb_rclone_mounts() {
    case "$(ts_smb_os)" in
        darwin)
            mount 2>/dev/null | awk '
                /\(macfuse/ || /\(nfs/ {
                    line = $0
                    i = index(line, " on ")
                    if (i == 0) next
                    rest = substr(line, i + 4)
                    j = index(rest, " (")
                    if (j == 0) next
                    target = substr(rest, 1, j - 1)
                    type = substr(rest, j + 2)
                    k = index(type, ",")
                    if (k > 0) type = substr(type, 1, k - 1)
                    k = index(type, ")")
                    if (k > 0) type = substr(type, 1, k - 1)
                    print type " " target
                }'
            ;;
        *)
            if [ -r /proc/self/mounts ]; then
                awk '$3 ~ /^(fuse\.rclone|fuse|nfs4?)$/ {
                        gsub(/\\040/, " ", $2); print $3 " " $2
                     }' /proc/self/mounts
            fi
            ;;
    esac
    return 0
}

ts_smb_pid_alive() {
    local pid="$1"
    case "$pid" in ''|*[!0-9]*) return 1 ;; esac
    kill -0 "$pid" 2>/dev/null && return 0
    return 1
}

# live | zombie | orphan | gone — derived, never stored.
ts_smb_mount_state() {
    local name="$1" pid mp alive=1 mounted=1
    pid="$(ts_smb_record_get "$name" pid "")"
    mp="$(ts_smb_record_get "$name" mountpoint "")"
    ts_smb_pid_alive "$pid" && alive=0
    ts_smb_is_mounted "$mp" && mounted=0
    if [ "$alive" = 0 ] && [ "$mounted" = 0 ]; then echo live
    elif [ "$alive" = 0 ]; then echo zombie
    elif [ "$mounted" = 0 ]; then echo orphan
    else echo gone
    fi
}

# ---------------------------------------------------------------- engine ----

ts_smb_macos_major() { sw_vers -productVersion 2>/dev/null | cut -d. -f1; }

TS_SMB_FUSET_LIB="/usr/local/lib/libfuse-t.dylib"
TS_SMB_MACFUSE_LIB="/usr/local/lib/libfuse.2.dylib"
TS_SMB_MACFUSE_FS="/Library/Filesystems/macfuse.fs"

ts_smb_fuset_present() { [ -e "$TS_SMB_FUSET_LIB" ]; }

ts_smb_rclone_path() {
    local p; p="$(command -v rclone 2>/dev/null || true)"
    [ -n "$p" ] || return 1
    if command -v realpath >/dev/null 2>&1; then realpath "$p" 2>/dev/null || printf '%s\n' "$p"
    else
        # readlink -f is GNU-only; macOS needs the manual walk.
        local t
        while [ -L "$p" ]; do t="$(readlink "$p")"; case "$t" in /*) p="$t" ;; *) p="$(dirname "$p")/$t" ;; esac; done
        printf '%s\n' "$p"
    fi
}

# Homebrew's macOS rclone refuses to mount at all: it aborts with "rclone mount
# is not supported on MacOS when rclone is installed via Homebrew". That is a
# build-time guard, so no FUSE library and no env var can get past it — which
# means a brew rclone can browse, list and copy perfectly but can never `mount`.
# Detected the way rclone itself detects it, from the resolved binary path.
ts_smb_rclone_is_brew() {
    [ "$(ts_smb_os)" = darwin ] || return 1
    local p; p="$(ts_smb_rclone_path)" || return 1
    case "$p" in */Cellar/*) return 0 ;; esac
    local pre
    for pre in /opt/homebrew /usr/local/Homebrew /home/linuxbrew/.linuxbrew; do
        case "$p" in "$pre"/*) return 0 ;; esac
    done
    return 1
}

# Can `rclone mount` (the FUSE path) work with this binary at all?
ts_smb_fuse_mount_capable() {
    ts_smb_have_rclone || return 1
    ts_smb_rclone_is_brew && return 1
    return 0
}

# absent | orphan-dylib | loaded | stale | plausible
#
# `loaded` is the only verdict `auto` will act on, and it is definitive: an
# unloadable kext makes rclone HANG, whereas nfsmount at worst gives a slow
# mount, so a merely `plausible` macFUSE deliberately ranks below nfs.
ts_smb_macfuse_state() {
    [ -e "$TS_SMB_MACFUSE_LIB" ] || { echo absent; return 0; }
    [ -d "$TS_SMB_MACFUSE_FS" ] || { echo orphan-dylib; return 0; }
    # Unprivileged and ~0.2s. Proof beats inference.
    if kmutil showloaded --list-only 2>/dev/null | grep -qi fuse; then
        echo loaded; return 0
    fi
    local built os_major mf_major
    built="$(defaults read "$TS_SMB_MACFUSE_FS/Contents/Info.plist" DTPlatformVersion 2>/dev/null || echo '')"
    mf_major="$(ts_smb_macfuse_version | cut -d. -f1)"
    os_major="$(ts_smb_macos_major)"
    case "$built" in
        ''|*[!0-9.]*) built="" ;;
    esac
    if [ -n "$built" ] && [ -n "$os_major" ]; then
        local b; b="${built%%.*}"
        if [ "$b" -lt $((os_major - 2)) ] 2>/dev/null; then echo stale; return 0; fi
    fi
    if [ -n "$mf_major" ] && [ -n "$os_major" ]; then
        if [ "$mf_major" -lt 5 ] 2>/dev/null && [ "$os_major" -ge 14 ] 2>/dev/null; then
            echo stale; return 0
        fi
    fi
    echo plausible
}

ts_smb_macfuse_version() {
    defaults read "$TS_SMB_MACFUSE_FS/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || echo ''
}

ts_smb_macfuse_built_for() {
    defaults read "$TS_SMB_MACFUSE_FS/Contents/Info.plist" DTPlatformVersion 2>/dev/null || echo ''
}

# fuse-t's effective backend. Its shipped .ini is entirely commented out, so an
# absent/commented `backend` means the default, nfs.
ts_smb_fuset_backend() {
    local ini="/Library/Application Support/fuse-t/cfg/fuse-t.ini" v=""
    if [ -f "$ini" ]; then
        v="$(grep -E '^[[:space:]]*backend[[:space:]]*=' "$ini" 2>/dev/null | tail -1 | sed 's/.*=[[:space:]]*//' || true)"
    fi
    [ -n "$v" ] || v="nfs (default)"
    printf '%s\n' "$v"
}

ts_smb_fuset_version() {
    local t
    t="$(readlink "$TS_SMB_FUSET_LIB" 2>/dev/null || echo '')"
    case "$t" in
        libfuse-t-*.dylib) t="${t#libfuse-t-}"; printf '%s\n' "${t%.dylib}" ;;
        *) printf '\n' ;;
    esac
}

# ok | denied | absent — AppArmor detection by proof, not by sniffing
# /etc/os-release. Costs nothing and needs no root.
ts_smb_linux_fuse_state() {
    local bin out rc=0
    bin="$(command -v fusermount3 2>/dev/null || command -v fusermount 2>/dev/null || true)"
    [ -n "$bin" ] || { echo absent; return 0; }
    out="$("$bin" -u /nonexistent-ts-smb-probe 2>&1)" || rc=$?
    case "$out" in
        *"ermission denied"*|*"peration not permitted"*) echo denied; return 0 ;;
    esac
    case "$rc" in 126|127) echo denied; return 0 ;; esac
    echo ok
}

ts_smb_linux_allow_other() {
    grep -qs '^[[:space:]]*user_allow_other' /etc/fuse.conf 2>/dev/null
}

# Resolve the mount engine. Prints three TAB-separated fields:
#     <engine>	<fuselib-or-empty>	<why>
# usage: ts_smb_engine_resolve [auto|fuse|nfs]
ts_smb_engine_resolve() {
    local want="${1:-}"
    [ -n "$want" ] || want="$(ts_smb_setting default_engine auto)"
    local os; os="$(ts_smb_os)"

    if [ "$os" = darwin ]; then
        local mstate; mstate="$(ts_smb_macfuse_state)"
        # The Homebrew guard outranks every FUSE consideration: that build cannot
        # mount no matter which library is present or pinned.
        if ts_smb_rclone_is_brew; then
            case "$want" in
                fuse) printf 'nfs\t\t%s\n' "fuse requested, but this rclone is the Homebrew build and refuses to mount" ;;
                *)    printf 'nfs\t\t%s\n' "this rclone is the Homebrew build, which refuses to mount (install the official binary for FUSE)" ;;
            esac
            return 0
        fi
        case "$want" in
            nfs) printf 'nfs\t\t%s\n' "requested explicitly"; return 0 ;;
            fuse)
                if ts_smb_fuset_present; then
                    printf 'fuse\t%s\t%s\n' "$TS_SMB_FUSET_LIB" "fuse-t $(ts_smb_fuset_version), pinned"
                    return 0
                fi
                if [ "$mstate" = loaded ]; then
                    printf 'fuse\t%s\t%s\n' "$TS_SMB_MACFUSE_LIB" "macFUSE $(ts_smb_macfuse_version), kext loaded"
                    return 0
                fi
                printf 'nfs\t\t%s\n' "fuse requested but no usable FUSE library (macFUSE: $mstate)"
                return 0
                ;;
        esac
        # auto
        if ts_smb_fuset_present; then
            printf 'fuse\t%s\t%s\n' "$TS_SMB_FUSET_LIB" \
                "fuse-t $(ts_smb_fuset_version) (userspace, no kext); macFUSE: $mstate"
            return 0
        fi
        if [ "$mstate" = loaded ]; then
            printf 'fuse\t%s\t%s\n' "$TS_SMB_MACFUSE_LIB" "macFUSE $(ts_smb_macfuse_version), kext loaded; no fuse-t"
            return 0
        fi
        printf 'nfs\t\t%s\n' "no fuse-t, and macFUSE is $mstate (auto never picks an unproven kext)"
        return 0
    fi

    local lstate; lstate="$(ts_smb_linux_fuse_state)"
    case "$want" in
        nfs) printf 'nfs\t\t%s\n' "requested explicitly"; return 0 ;;
        fuse)
            if [ "$lstate" = ok ]; then printf 'fuse\t\t%s\n' "fusermount usable"; return 0; fi
            printf 'nfs\t\t%s\n' "fuse requested but fusermount is $lstate"
            return 0
            ;;
    esac
    if [ "$lstate" = ok ]; then printf 'fuse\t\t%s\n' "fusermount usable"; return 0; fi
    printf 'nfs\t\t%s\n' "fusermount is $lstate"
    return 0
}

ts_smb_engine_field() {
    local n="$1" line
    line="$(ts_smb_engine_resolve "${2:-}")"
    printf '%s\n' "$line" | cut -f"$n"
}

# ----------------------------------------------------------- credentials ----

ts_smb_cred_account() { printf '%s\n' "$1@$2"; }

# Obscure plaintext read from stdin. rclone obscure reads stdin with "-", so the
# plaintext never appears in argv.
ts_smb_obscure() { rclone obscure - 2>/dev/null; }

# Store the ALREADY-OBSCURED blob (read from stdin). Obscuring at set time means
# the runtime path never has to shell out to `rclone obscure`, and no plaintext
# exists anywhere after setup.
ts_smb_cred_set() {
    local backend="$1" user="$2" host="$3" blob acct
    acct="$(ts_smb_cred_account "$user" "$host")"
    blob="$(cat)"
    [ -n "$blob" ] || return 1
    case "$backend" in
        keychain)
            if [ "$(ts_smb_os)" = darwin ]; then
                security add-generic-password -U -a "$acct" -s "$TS_SMB_CRED_SERVICE" \
                    -w "$blob" >/dev/null 2>&1 || return 1
                return 0
            fi
            if command -v secret-tool >/dev/null 2>&1; then
                printf '%s' "$blob" | secret-tool store --label="terminal-stack SMB $acct" \
                    service "$TS_SMB_CRED_SERVICE" account "$acct" >/dev/null 2>&1 || return 1
                return 0
            fi
            return 2   # caller falls back to `file`
            ;;
        file)
            local dir="${XDG_CONFIG_HOME:-$HOME/.config}/terminal-stack/smb-creds"
            ( umask 077; mkdir -p "$dir" ) 2>/dev/null || return 1
            ( umask 077; printf '%s\n' "$blob" > "$dir/$(ts_smb_cred_file_name "$user" "$host")" ) || return 1
            return 0
            ;;
        *) return 1 ;;
    esac
}

ts_smb_cred_file_name() {
    printf '%s\n' "$(printf '%s@%s' "$1" "$2" | tr -c 'A-Za-z0-9._@-' '_')"
}

# Print the obscured blob, or nothing. Never prompts, never pops a dialog for
# `file`; `keychain` on macOS may prompt the user once for access.
ts_smb_cred_get() {
    local backend="$1" user="$2" host="$3" acct
    acct="$(ts_smb_cred_account "$user" "$host")"
    case "$backend" in
        keychain)
            if [ "$(ts_smb_os)" = darwin ]; then
                security find-generic-password -a "$acct" -s "$TS_SMB_CRED_SERVICE" -w 2>/dev/null || true
                return 0
            fi
            if command -v secret-tool >/dev/null 2>&1; then
                secret-tool lookup service "$TS_SMB_CRED_SERVICE" account "$acct" 2>/dev/null || true
                return 0
            fi
            ts_smb_cred_get file "$user" "$host"
            return 0
            ;;
        file)
            local f="${XDG_CONFIG_HOME:-$HOME/.config}/terminal-stack/smb-creds/$(ts_smb_cred_file_name "$user" "$host")"
            [ -f "$f" ] && cat "$f" 2>/dev/null || true
            return 0
            ;;
        *) return 0 ;;
    esac
}

ts_smb_cred_rm() {
    local backend="$1" user="$2" host="$3" acct
    acct="$(ts_smb_cred_account "$user" "$host")"
    case "$backend" in
        keychain)
            if [ "$(ts_smb_os)" = darwin ]; then
                security delete-generic-password -a "$acct" -s "$TS_SMB_CRED_SERVICE" >/dev/null 2>&1 || true
            elif command -v secret-tool >/dev/null 2>&1; then
                secret-tool clear service "$TS_SMB_CRED_SERVICE" account "$acct" >/dev/null 2>&1 || true
            fi
            ;;
    esac
    rm -f "${XDG_CONFIG_HOME:-$HOME/.config}/terminal-stack/smb-creds/$(ts_smb_cred_file_name "$user" "$host")" 2>/dev/null || true
    return 0
}

ts_smb_cred_present() {
    local blob; blob="$(ts_smb_cred_get "$1" "$2" "$3")"
    [ -n "$blob" ]
}

# ---------------------------------------------------------------- rclone ----

ts_smb_have_rclone() { command -v rclone >/dev/null 2>&1; }

# An on-the-fly remote, so interrogation works against a host that was never
# configured. The password is NOT in here — it goes in RCLONE_SMB_PASS, because
# argv is world-readable via /proc/PID/cmdline and a mount is long-lived.
# usage: ts_smb_conn <host> <user> [<domain>] [<port>]
ts_smb_conn() {
    local host="$1" user="$2" domain="${3:-}" port="${4:-}" s
    s=":smb,host=$host"
    [ -n "$user" ] && s="$s,user=$user"
    [ -n "$domain" ] && s="$s,domain=$domain"
    [ -n "$port" ] && s="$s,port=$port"
    printf '%s:\n' "$s"
}

# A host or user containing a comma or a colon would silently corrupt the
# connection string, so refuse it rather than produce a confusing rclone error.
ts_smb_valid_token() {
    case "$1" in
        *,*|*:*|'') return 1 ;;
        *) return 0 ;;
    esac
}

# ------------------------------------------------------------- validation ----

# Report anything wrong with the store, one finding per line. Used by
# `ts-smb config` before it saves and by `ts-smb doctor`. Note that `share` is
# the stanza OPENER, so a stray `share Media` meant as the SMB share name
# silently opens a second stanza — a stanza with no `host` is usually that
# mistake, which is why it is called out by name.
ts_smb_validate() {
    ts_smb_load_config
    local e n v out=0
    if [ -n "${TS_SMB_CONF_ERRORS:-}" ]; then
        printf '%s\n' "$TS_SMB_CONF_ERRORS" | tr ';' '\n' | while IFS= read -r e; do
            [ -n "$e" ] && printf '%s\n' "$e"
        done
        out=1
    fi
    for n in $TS_SMB_NAMES; do
        v="$(ts_smb_lookup "$TS_SMB_RECORDS" "$n.host" "")"
        if [ -z "$v" ]; then
            printf "share '%s' has no host (did you mean 'path' for the SMB share name? 'share' opens a new stanza)\n" "$n"
            out=1
        fi
        v="$(ts_smb_lookup "$TS_SMB_RECORDS" "$n.path" "")"
        if [ -z "$v" ]; then
            printf "share '%s' has no path (the SMB share name on the host) — if you wrote 'share X' for it, note that 'share' opens a stanza; the field is 'path'\n" "$n"
            out=1
        fi
        v="$(ts_smb_get "$n" engine auto)"
        case "$v" in auto|fuse|nfs) ;; *) printf "share '%s': engine '%s' is not auto|fuse|nfs\n" "$n" "$v"; out=1 ;; esac
        v="$(ts_smb_get "$n" vfs off)"
        case "$v" in off|minimal|writes|full) ;; *) printf "share '%s': vfs '%s' is not off|minimal|writes|full\n" "$n" "$v"; out=1 ;; esac
        v="$(ts_smb_get "$n" cred keychain)"
        case "$v" in keychain|rclone|file|prompt|none) ;; *) printf "share '%s': cred '%s' is not keychain|rclone|file|prompt|none\n" "$n" "$v"; out=1 ;; esac
    done
    return "$out"
}
