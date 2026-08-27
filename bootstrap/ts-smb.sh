#!/usr/bin/env bash
# ts-smb.sh — find, interrogate and mount SMB/CIFS shares, all through rclone.
# Driven by the `tstack smb` shell wrapper (zsh) and runnable standalone.
#
# THERE IS NO pwsh TWIN YET. Every other dual-shell command in this stack keeps
# a parallel PowerShell implementation with byte-identical -h output; this one
# is macOS/Linux only for now, deliberately and on the record (docs/decisions.md
# "Why tstack smb ships without a PowerShell twin"). HELP below is written as if it
# will be copied, because it will be. On Windows the engine layer is mostly moot
# anyway — Explorer and `net use` already do this natively.
#
# The library is bootstrap/_smb.sh; the store is bootstrap/shares.conf plus the
# untracked ~/.config/terminal-stack/shares.local.conf. No chezmoi [data] key is
# involved: the inventory is a record list, which that store is not built for,
# and every setting here is per-machine anyway.
#
# Two rules from _smb.sh are worth repeating because breaking them is silent:
# on darwin never run `rclone mount` without CGOFUSE_LIBFUSE_PATH set (a stale
# macFUSE wins cgofuse's dlopen order and the mount HANGS), and never stat or
# glob a mountpoint (a dead FUSE mount blocks forever and takes the shell).
set -euo pipefail

HELP='tstack smb — SMB/CIFS shares over rclone: find them, look inside, mount them.

Usage:
  tstack smb [list]      live mounts: name, state, engine, mountpoint
  tstack smb hosts       SMB servers on this LAN (mDNS; --sweep adds a port-445 scan)
  tstack smb shares HOST the shares HOST offers
  tstack smb probe HOST  auth + capability: which credentials work, and what they get
  tstack smb ls SPEC     one directory listing, no mount
  tstack smb tree SPEC   the tree, depth-limited (--depth N, default 2)
  tstack smb du SPEC     what it holds (rclone size)
  tstack smb get SRC DST copy out of a share without mounting it
  tstack smb setup       guided Windows/NAS share setup (Tailscale-aware)
  tstack smb mount NAME  mount it
  tstack smb umount NAME unmount it
  tstack smb add NAME    add a share to the store, asking for whatever you left out
  tstack smb config      edit shares.local.conf in $EDITOR; validated before it saves
  tstack smb creds NAME  set, show or forget the password for a share
  tstack smb engine      which mount engine auto picks here, and why the others lost
  tstack smb doctor      rclone, the FUSE engines, stale mounts, the store
  tstack smb -h          this help

  -y, --yes          skip confirmations
  -n, --dry-run      print the rclone command instead of running it
  --engine E         auto | fuse | nfs        (mount)
  --at DIR           mount somewhere other than the configured mountpoint
  --rw               mount read-write (turns on the VFS write cache)
  --all              every tstack smb mount        (list, umount)
  --force            unmount harder, and unmount before mounting over
  --depth N          how deep tree goes        (tree)
  --sweep            add a port-445 subnet scan to discovery   (hosts)
  --write            probe writability by creating a temp file (probe)
  --host H, --path S   answer "add" non-interactively
  --user U, --domain D, --port N, --guest
  --cred B           keychain | rclone | file | prompt | none
  -P, --password     prompt for the password; --password-stdin reads it instead

SPEC is a share name from your store, or HOST/SHARE[/PATH], or a bare HOST
meaning "list its shares". Interrogation uses on-the-fly rclone remotes, so a
host that was never configured works with no setup: rclone has no anonymous
mode, and user "guest" with an empty password is the documented substitute.

Passwords never appear in the command line — there is no --password VALUE flag,
because /proc/PID/cmdline is world-readable and a mount is long-lived. They are
obscured once by "tstack smb creds" and stored in the OS keychain; at runtime they
reach rclone through RCLONE_SMB_PASS.

Your shares live in ~/.config/terminal-stack/shares.local.conf, which is never
tracked and never synced anywhere. Defaults come from bootstrap/shares.conf in
the clone. Mounts default to read-only at ~/mnt/<name>; run "tstack smb doctor" if
one will not mount. Windows is not supported yet.'

# Help before anything else: `tstack smb -h` must work on a box where the clone or
# chezmoi is the very thing that is broken.
case "${1:-}" in -h|--help|help) printf '%s\n' "$HELP"; exit 0 ;; esac

CZ="${TERMINAL_STACK_CHEZMOI:-}"
if [ -z "$CZ" ]; then
    if [ -x "$HOME/.local/bin/chezmoi" ]; then CZ="$HOME/.local/bin/chezmoi"
    elif command -v chezmoi >/dev/null 2>&1; then CZ="$(command -v chezmoi)"
    else echo "tstack smb: chezmoi not found on PATH." >&2; exit 1; fi
fi
SRC="${TERMINAL_STACK_DIR:-$("$CZ" source-path 2>/dev/null || true)}"
if [ ! -d "$SRC/bootstrap" ]; then
    echo "tstack smb: cannot locate the terminal-stack clone (set TERMINAL_STACK_DIR)." >&2
    exit 1
fi
# shellcheck source=_config.sh
. "$SRC/bootstrap/_config.sh"
# shellcheck source=_wizard.sh
. "$SRC/bootstrap/_wizard.sh"
TS_SMB_LIB_DIR="$SRC/bootstrap"; export TS_SMB_LIB_DIR
# shellcheck source=_smb.sh
. "$SRC/bootstrap/_smb.sh"

ASSUME_YES=0; DRY_RUN=0
OPT_ENGINE=""; OPT_AT=""; OPT_RW=0; OPT_ALL=0; OPT_FORCE=0; OPT_NONEMPTY=0
OPT_DEPTH=2; OPT_SWEEP=0; OPT_WRITE=0; OPT_USER=""; OPT_DOMAIN=""; OPT_PORT=""
OPT_CRED=""; OPT_PASSWORD=0; OPT_PASSWORD_STDIN=0; OPT_GUEST=0; OPT_REVEAL=0
OPT_CANARY=0; OPT_REPAIR=0; OPT_CREDCHECK=0; OPT_VOLUME=0

confirm() {  # confirm <prompt>
    [ "$ASSUME_YES" = 1 ] && return 0
    if ! { true > /dev/tty; } 2>/dev/null; then
        echo "tstack smb: no terminal to confirm on — re-run with -y if you mean it." >&2
        return 1
    fi
    local a; a="$(ts_tty_prompt "$1 [y/N]: ")"
    case "$a" in y|Y|yes|YES) return 0 ;; *) echo "aborted."; return 1 ;; esac
}

need_rclone() {
    if ! ts_smb_have_rclone; then
        echo "tstack smb: rclone not found on PATH — install it with 'tstack config apps rclone'." >&2
        return 1
    fi
    return 0
}

# ── spec resolution ─────────────────────────────────────────────────────────────

# Sets R_NAME R_HOST R_PATH R_USER R_DOMAIN R_PORT R_CRED R_REMOTE from a SPEC:
# a store name, HOST/SHARE[/PATH], or a bare HOST.
R_NAME=""; R_HOST=""; R_PATH=""; R_USER=""; R_DOMAIN=""; R_PORT=""; R_CRED=""; R_REMOTE=""
resolve_spec() {
    local spec="$1"
    R_NAME=""; R_HOST=""; R_PATH=""; R_USER=""; R_DOMAIN=""; R_PORT=""; R_CRED=""; R_REMOTE=""
    if [ -z "$spec" ]; then echo "tstack smb: a share name or HOST/SHARE is required." >&2; return 2; fi

    local head="${spec%%/*}" tail=""
    case "$spec" in */*) tail="${spec#*/}" ;; esac

    if ts_smb_has "$head"; then
        R_NAME="$(ts_smb_lower "$head")"
        R_HOST="$(ts_smb_get "$R_NAME" host "")"
        R_PATH="$(ts_smb_get "$R_NAME" path "")"
        R_USER="$(ts_smb_get "$R_NAME" user guest)"
        R_DOMAIN="$(ts_smb_get "$R_NAME" domain "")"
        R_PORT="$(ts_smb_get "$R_NAME" port "")"
        R_CRED="$(ts_smb_get "$R_NAME" cred keychain)"
        R_REMOTE="$(ts_smb_get "$R_NAME" remote "")"
        [ -n "$tail" ] && R_PATH="${R_PATH:+$R_PATH/}$tail"
    else
        R_HOST="$head"
        R_PATH="$tail"
        R_USER="$(ts_smb_setting default_user guest)"
        R_DOMAIN="$(ts_smb_setting default_domain '')"
        R_CRED="$(ts_smb_setting default_cred keychain)"
    fi

    [ -n "$OPT_USER" ]   && { R_USER="$OPT_USER"; R_NAME=""; }
    [ "$OPT_GUEST" = 1 ] && { R_USER=guest; R_CRED=none; }
    [ -n "$OPT_DOMAIN" ] && R_DOMAIN="$OPT_DOMAIN"
    [ -n "$OPT_PORT" ]   && R_PORT="$OPT_PORT"
    [ -n "$OPT_CRED" ]   && R_CRED="$OPT_CRED"

    if ! ts_smb_valid_token "$R_HOST"; then
        echo "tstack smb: '$R_HOST' is not a usable host (no commas or colons)." >&2; return 2
    fi
    if [ -n "$R_USER" ] && ! ts_smb_valid_token "$R_USER"; then
        echo "tstack smb: '$R_USER' is not a usable user name (no commas or colons)." >&2; return 2
    fi
    return 0
}

# The rclone remote for the resolved spec: an explicit rclone.conf remote when
# the store names one, else an on-the-fly connection string.
spec_remote() {
    local sub="${1:-}"
    local base
    if [ -n "$R_REMOTE" ]; then
        base="$R_REMOTE:"
        [ -n "$R_PATH" ] && base="$base$R_PATH"
    else
        base="$(ts_smb_conn "$R_HOST" "$R_USER" "$R_DOMAIN" "$R_PORT")"
        [ -n "$R_PATH" ] && base="$base$R_PATH"
    fi
    [ -n "$sub" ] && base="${base%/}/$sub"
    printf '%s\n' "$base"
}

# Put the obscured password in RCLONE_SMB_PASS for the child only. It MUST be
# obscured — rclone rejects plaintext here with "input too short when revealing
# password". `tstack smb creds` obscures once at set time, so this is a plain read.
export_password() {
    RCLONE_SMB_PASS=""
    # An explicit flag always wins over the share's configured backend —
    # otherwise --password-stdin is swallowed by a `cred prompt` share, which is
    # exactly the combination a script needs.
    if [ "$OPT_PASSWORD_STDIN" = 1 ]; then
        if [ -z "${TS_STDIN_PASS+x}" ]; then TS_STDIN_PASS="$(cat | ts_smb_obscure)"; fi
        RCLONE_SMB_PASS="$TS_STDIN_PASS"
        export RCLONE_SMB_PASS; return 0
    fi
    if [ "$OPT_PASSWORD" = 1 ]; then
        local p
        p="$(read_password_interactive)" || return 1
        RCLONE_SMB_PASS="$(printf '%s' "$p" | ts_smb_obscure)"
        export RCLONE_SMB_PASS; return 0
    fi
    case "$R_CRED" in
        none|rclone) ;;
        prompt)
            local p2
            p2="$(read_password_interactive)" || return 1
            RCLONE_SMB_PASS="$(printf '%s' "$p2" | ts_smb_obscure)"
            ;;
        keychain|file)
            RCLONE_SMB_PASS="$(ts_smb_cred_get "$R_CRED" "$R_USER" "$R_HOST")"
            ;;
    esac
    export RCLONE_SMB_PASS
    return 0
}

read_password_interactive() {
    if ! { true > /dev/tty; } 2>/dev/null; then
        echo "tstack smb: no terminal to read a password from; use --password-stdin." >&2
        return 1
    fi
    local p=""
    printf 'Password for %s@%s: ' "$R_USER" "$R_HOST" > /dev/tty
    IFS= read -r -s p < /dev/tty || true
    printf '\n' > /dev/tty
    printf '%s' "$p"
}

# Run rclone, or print what would have run. The password is never in argv, so a
# dry-run line is safe to paste anywhere.
run_rclone() {
    if [ "$DRY_RUN" = 1 ]; then
        printf '%s' "rclone"
        local a
        for a in "$@"; do printf ' %q' "$a"; done
        if [ -n "${RCLONE_SMB_PASS:-}" ]; then printf '   # with RCLONE_SMB_PASS set in the environment'; fi
        printf '\n'
        return 0
    fi
    rclone "$@"
}

# ── subcommands: interrogation ──────────────────────────────────────────────────

cmd_shares() {
    need_rclone || return 1
    local spec="${1:-}"
    [ -n "$spec" ] || { echo "tstack smb shares: a host is required." >&2; return 2; }
    resolve_spec "$spec" || return $?
    R_PATH=""
    export_password || return 1
    echo "$INFO shares on $R_HOST (as ${R_USER:-guest})"
    run_rclone lsd "$(spec_remote)" --smb-idle-timeout 10s
}

cmd_ls() {
    need_rclone || return 1
    resolve_spec "${1:-}" || return $?
    export_password || return 1
    run_rclone lsf "$(spec_remote)" --smb-idle-timeout 10s
}

cmd_tree() {
    need_rclone || return 1
    resolve_spec "${1:-}" || return $?
    export_password || return 1
    run_rclone tree "$(spec_remote)" --level "$OPT_DEPTH" --smb-idle-timeout 10s
}

cmd_du() {
    need_rclone || return 1
    resolve_spec "${1:-}" || return $?
    export_password || return 1
    run_rclone size "$(spec_remote)" --smb-idle-timeout 10s
}

cmd_get() {
    need_rclone || return 1
    local src="${1:-}" dst="${2:-}"
    [ -n "$src" ] && [ -n "$dst" ] || { echo "tstack smb get: SRC and DST are required." >&2; return 2; }
    resolve_spec "$src" || return $?
    export_password || return 1
    run_rclone copy "$(spec_remote)" "$dst" --progress --smb-idle-timeout 10s
}

# Which credentials work, and what they get you. This is the "why will it not
# mount" command, so it reports per-candidate rather than failing on the first.
cmd_probe() {
    need_rclone || return 1
    local spec="${1:-}"
    [ -n "$spec" ] || { echo "tstack smb probe: a host or share is required." >&2; return 2; }
    resolve_spec "$spec" || return $?
    local want_path="$R_PATH"
    echo "$INFO probing $R_HOST${want_path:+/$want_path}"

    local cand user cred label out rc seen=" "
    for cand in "guest|none" "$R_USER|$R_CRED"; do
        user="${cand%%|*}"; cred="${cand#*|}"
        [ -n "$user" ] || continue
        case "$seen" in *" $user "*) continue ;; esac
        seen="$seen $user "
        if [ "$user" = guest ]; then cred=none; fi
        label="$user"
        [ "$cred" != none ] && label="$user (via $cred)"

        local saved_user="$R_USER" saved_cred="$R_CRED" saved_path="$R_PATH"
        R_USER="$user"; R_CRED="$cred"; R_PATH=""
        export_password || true
        rc=0
        out="$(ts_smb_timeout 20 rclone lsd "$(spec_remote)" --smb-idle-timeout 5s \
                --low-level-retries 1 --retries 1 --contimeout 5s --timeout 10s 2>&1)" || rc=$?
        R_USER="$saved_user"; R_CRED="$saved_cred"; R_PATH="$saved_path"

        if [ "$rc" = 0 ]; then
            local n; n="$(printf '%s\n' "$out" | grep -c . || true)"
            printf '  ok         %-28s %s share(s) visible\n' "$label" "$n"
        else
            case "$out" in
                *"NT_STATUS_LOGON_FAILURE"*|*"authenticate"*|*"credentials"*|*"password"*)
                    printf '  auth       %-28s bad credentials\n' "$label" ;;
                *"ACCESS_DENIED"*|*"permission denied"*)
                    printf '  denied     %-28s access denied\n' "$label" ;;
                ""|*"i/o timeout"*|*"timed out"*|*"no such host"*|*"connection refused"*|*"unreachable"*)
                    printf '  unreachable %-27s %s\n' "$label" "$(printf '%s' "$out" | tail -1 | cut -c1-60)" ;;
                *)
                    printf '  fail       %-28s %s\n' "$label" "$(printf '%s' "$out" | tail -1 | cut -c1-60)" ;;
            esac
        fi
    done

    if [ -n "$want_path" ]; then
        R_PATH="$want_path"
        export_password || true
        if ts_smb_timeout 20 rclone lsf "$(spec_remote)" --max-depth 1 --smb-idle-timeout 5s \
                --contimeout 5s --timeout 10s >/dev/null 2>&1; then
            echo "  ok         $want_path is readable"
        else
            echo "  fail       $want_path is not readable with those credentials"
        fi
        if [ "$OPT_WRITE" = 1 ]; then
            # The only honest test of writability is to write. Say so first:
            # some servers accept the create and then refuse the delete (seen on
            # Samba responding "The request is not supported"), which leaves a
            # file behind on someone else's share.
            local probe=".ts-smb-write-probe.$$"
            if confirm "tstack smb: create $probe on $R_HOST/$want_path to test writability? (it may not be removable again)"; then
                if printf 'tstack smb probe\n' | ts_smb_timeout 20 rclone rcat "$(spec_remote "$probe")" \
                        --smb-idle-timeout 5s --contimeout 5s --timeout 10s >/dev/null 2>&1; then
                    echo "  ok         $want_path is writable"
                    if ts_smb_timeout 20 rclone deletefile "$(spec_remote "$probe")" --smb-idle-timeout 5s >/dev/null 2>&1 ||
                       ts_smb_timeout 20 rclone delete     "$(spec_remote "$probe")" --smb-idle-timeout 5s >/dev/null 2>&1; then
                        :
                    else
                        echo "  $WARN the server refused to delete the probe file; remove it by hand:"
                        echo "             $R_HOST/$want_path/$probe"
                    fi
                else
                    echo "  ro         $want_path is not writable"
                fi
            else
                echo "  --         writability not tested"
            fi
        else
            echo "  --         writability not tested (pass --write to create a temp file)"
        fi
    fi
    return 0
}

# ── subcommands: discovery ──────────────────────────────────────────────────────

cmd_hosts() {
    echo "$INFO SMB hosts via mDNS"
    local found=0
    case "$(ts_smb_os)" in
        darwin)
            if command -v dns-sd >/dev/null 2>&1; then
                # dns-sd -B never exits; bound it. Instance names are not
                # hostnames, so each is resolved with -L to get the target.
                local names
                names="$(ts_smb_timeout 4 dns-sd -B _smb._tcp local. 2>/dev/null \
                    | awk '/Add/ { s=""; for (i=7; i<=NF; i++) s = s (i>7 ? " " : "") $i; if (s != "") print s }' \
                    | sort -u || true)"
                local nm host
                while IFS= read -r nm; do
                    [ -n "$nm" ] || continue
                    found=1
                    host="$(ts_smb_timeout 3 dns-sd -L "$nm" _smb._tcp local. 2>/dev/null \
                        | sed -n 's/.*can be reached at \([^ :]*\).*/\1/p' | head -1 || true)"
                    host="${host%.}"
                    printf '  %-28s %s\n' "$nm" "${host:-（unresolved）}"
                done <<EOF2
$names
EOF2
            else
                echo "  $WARN dns-sd not found; cannot browse mDNS on this machine"
            fi
            ;;
        linux)
            if command -v avahi-browse >/dev/null 2>&1; then
                local line
                while IFS=';' read -r kind _if _proto nm _svc _dom hostn addr port _rest; do
                    [ "$kind" = "=" ] || continue
                    found=1
                    printf '  %-28s %s %s\n' "$nm" "${hostn:-?}" "${addr:+($addr:$port)}"
                done <<EOF2
$(ts_smb_timeout 5 avahi-browse -rtp _smb._tcp 2>/dev/null || true)
EOF2
            else
                echo "  $WARN avahi-browse not found; install avahi-utils to browse mDNS"
            fi
            ;;
    esac
    [ "$found" = 0 ] && echo "  (nothing advertised _smb._tcp on this network)"

    if [ "$OPT_SWEEP" = 1 ]; then
        sweep_subnet
    else
        echo "  note: mDNS only. --sweep adds a port-445 scan of your subnet."
    fi
    return 0
}

# A port-445 scan of the local /24. Off by default and confirmed every time: on
# a managed network this looks like an attack, so it must be a deliberate act.
sweep_subnet() {
    if ! command -v nc >/dev/null 2>&1; then
        echo "  $WARN nc not found; cannot sweep"
        return 0
    fi
    local ip base
    case "$(ts_smb_os)" in
        darwin)
            local iface; iface="$(route -n get default 2>/dev/null | awk '/interface:/ {print $2}' | head -1)"
            [ -n "$iface" ] && ip="$(ipconfig getifaddr "$iface" 2>/dev/null || true)"
            ;;
        *)
            ip="$(ip route get 1.1.1.1 2>/dev/null | sed -n 's/.*src \([0-9.]*\).*/\1/p' | head -1 || true)"
            ;;
    esac
    if [ -z "${ip:-}" ]; then echo "  $WARN could not determine this machine's address; skipping sweep"; return 0; fi
    base="${ip%.*}"
    echo
    echo "$INFO sweep would scan $base.1-254 on port 445"
    confirm "tstack smb: port-scan $base.0/24?" || return 0
    local i pids=0
    for i in $(seq 1 254); do
        ( nc -z -w 1 "$base.$i" 445 >/dev/null 2>&1 && printf '  %s\n' "$base.$i" ) &
        pids=$((pids + 1))
        if [ "$pids" -ge 32 ]; then wait; pids=0; fi
    done
    wait
    return 0
}

# ── subcommands: mounts ─────────────────────────────────────────────────────────

cmd_list() {
    local names n state pid mp eng
    names="$(ts_smb_record_names)"
    if [ -z "$names" ]; then
        echo "tstack smb: no mounts recorded."
    else
        printf '%-14s %-8s %-6s %-8s %s\n' NAME STATE ENGINE PID MOUNTPOINT
        for n in $names; do
            state="$(ts_smb_mount_state "$n")"
            pid="$(ts_smb_record_get "$n" pid '-')"
            mp="$(ts_smb_record_get "$n" mountpoint '-')"
            eng="$(ts_smb_record_get "$n" engine '-')"
            printf '%-14s %-8s %-6s %-8s %s\n' "$n" "$state" "$eng" "$pid" "$mp"
            if [ "$state" = gone ]; then
                ts_smb_record_rm "$n"
            fi
        done
    fi

    # Strays: rclone mounts nobody here recorded. An invisible mount is worse
    # than an ugly one.
    local known="" fstype target
    for n in $names; do known="$known $(ts_smb_record_get "$n" mountpoint '')"; done
    local strays=""
    while read -r fstype target; do
        [ -n "$target" ] || continue
        case " $known " in *" $target "*) continue ;; esac
        # grep -F, not pgrep -f: the mountpoint is not ours to choose and a
        # regex metacharacter in it would silently hide the stray.
        ps -o args= -A 2>/dev/null | grep -F "$target" | grep -q rclone || continue
        strays="$strays$target ($fstype)
"
    done <<EOF2
$(ts_smb_rclone_mounts)
EOF2
    if [ -n "$strays" ]; then
        echo
        echo "$WARN rclone mounts not managed by tstack smb:"
        printf '%s' "$strays" | sed 's/^/  /'
    fi
    return 0
}

mount_preflight() {
    local mp="$1" name="$2"
    local other n
    for n in $(ts_smb_record_names); do
        [ "$n" = "$name" ] && continue
        other="$(ts_smb_record_get "$n" mountpoint '')"
        if [ "$other" = "$mp" ]; then
            echo "tstack smb: $mp is already claimed by '$n' — 'tstack smb umount $n' first." >&2
            return 1
        fi
    done
    if ts_smb_is_mounted "$mp"; then
        if [ "$OPT_FORCE" = 1 ]; then
            echo "$INFO $mp is mounted; unmounting first (--force)"
            do_unmount_path "$mp" "$(ts_smb_record_get "$name" engine fuse)" "$(ts_smb_record_get "$name" sudo 0)"
        else
            echo "tstack smb: $mp is already mounted — pass --force to unmount it first." >&2
            return 1
        fi
    fi
    # Safe now: the mount table says nothing is mounted here, so touching the
    # path cannot hit a wedged FUSE mount.
    if [ -L "$mp" ]; then
        echo "tstack smb: $mp is a symlink; refusing (rclone follows it and unmount gets confusing)." >&2
        return 1
    fi
    if [ ! -e "$mp" ]; then
        mkdir -p "$mp" || { echo "tstack smb: cannot create $mp" >&2; return 1; }
        return 0
    fi
    if [ ! -d "$mp" ]; then
        echo "tstack smb: $mp exists and is not a directory." >&2
        return 1
    fi
    local count
    count="$(ls -A "$mp" 2>/dev/null | grep -c . || true)"
    if [ "${count:-0}" -gt 0 ] && [ "$OPT_NONEMPTY" != 1 ]; then
        echo "tstack smb: $mp is not empty ($count entries); mounting over it would hide them." >&2
        ls -A "$mp" 2>/dev/null | head -3 | sed 's/^/    /' >&2
        echo "        pass --allow-nonempty if you really mean it (--force does not cover this)." >&2
        return 1
    fi
    return 0
}

cmd_mount() {
    need_rclone || return 1
    local name="${1:-}"
    [ -n "$name" ] || { echo "tstack smb mount: a share name is required." >&2; return 2; }
    resolve_spec "$name" || return $?
    [ -n "$R_PATH" ] || { echo "tstack smb: '$name' has no path (the SMB share name)." >&2; return 2; }

    local eline engine fuselib why
    eline="$(ts_smb_engine_resolve "${OPT_ENGINE:-$(ts_smb_get "$name" engine auto)}")"
    engine="$(printf '%s' "$eline" | cut -f1)"
    fuselib="$(printf '%s' "$eline" | cut -f2)"
    why="$(printf '%s' "$eline" | cut -f3)"

    local mp
    if [ -n "$OPT_AT" ]; then mp="$(ts_smb_expand_path "$OPT_AT")"
    elif [ "$OPT_VOLUME" = 1 ]; then mp="/Volumes/$(ts_smb_lower "$name")"
    else mp="$(ts_smb_mountpoint "$name")"; fi

    local vfs
    vfs="$(ts_smb_get "$name" vfs off)"
    if [ "$OPT_RW" = 1 ] && [ "$vfs" = off ]; then vfs=writes; fi
    if [ "$engine" = nfs ] && [ "$OPT_RW" = 1 ] && [ "$vfs" = off ]; then vfs=writes; fi
    if [ "$engine" = nfs ] && [ "$OPT_RW" = 1 ]; then
        echo "$INFO nfsmount needs a write cache to be writable — using --vfs-cache-mode $vfs"
    fi

    local sub="mount"; [ "$engine" = nfs ] && sub="nfsmount"
    local logf; logf="$(ts_smb_log_path "$name")"
    mkdir -p "$(ts_smb_state_dir)" 2>/dev/null || true

    set -- "$sub" "$(spec_remote)" "$mp" --daemon --daemon-wait 5s \
        --log-file "$logf" --log-format=pid --vfs-cache-mode "$vfs"
    [ "$OPT_RW" = 1 ] || set -- "$@" --read-only
    # NOTE: do NOT add "-o backend=fskit" here. fuse-t's FSKit backend looks
    # like the modern choice on macOS 26, but on 26.6.2 with fuse-t 1.2.6 it
    # fails outright ("fuse: mount failed with error: -1") while the default nfs
    # backend does not. Opt in per mount with: --engine fuse -- -o backend=fskit
    local extra; extra="$(ts_smb_flags "$name")"
    if [ -n "$extra" ]; then
        # rclone flags are shell tokens by construction; word-splitting is the
        # point. A flag VALUE containing a space is documented as unsupported.
        # shellcheck disable=SC2086
        set -- "$@" $extra
    fi

    if [ "$engine" = fuse ] && ! ts_smb_fuse_mount_capable; then
        echo "tstack smb: this rclone cannot mount (run 'tstack smb doctor')." >&2
        return 1
    fi
    export_password || return 1
    echo "$INFO engine: $engine — $why"
    [ -n "$fuselib" ] && echo "$INFO libfuse: $fuselib"
    local mode=read-only; [ "$OPT_RW" = 1 ] && mode=read-write
    echo "$INFO mounting $R_HOST/$R_PATH at $mp ($mode, vfs=$vfs)"

    if [ "$DRY_RUN" = 1 ]; then
        [ "$engine" = fuse ] && [ -n "$fuselib" ] && printf 'CGOFUSE_LIBFUSE_PATH=%q \\\n  ' "$fuselib"
        run_rclone "$@"
        return 0
    fi

    mount_preflight "$mp" "$(ts_smb_lower "$name")" || return 1
    : > "$logf" 2>/dev/null || true

    # Rule 1: on darwin the library is always pinned, never left to cgofuse's
    # dlopen order. A stale macFUSE would win it and the mount would HANG.
    if [ "$engine" = fuse ] && [ -n "$fuselib" ]; then
        CGOFUSE_LIBFUSE_PATH="$fuselib" rclone "$@" || {
            echo "tstack smb: mount failed; see $logf (and try 'tstack smb doctor')." >&2; return 1; }
    else
        rclone "$@" || {
            echo "tstack smb: mount failed; see $logf (and try 'tstack smb doctor')." >&2; return 1; }
    fi

    # --daemon makes the parent exit, so $! is the wrapper, not the mount.
    local pid; pid="$(capture_pid "$logf" "$mp")"

    # --daemon-wait is a constant sleep on macOS, so confirm readiness against
    # the mount table rather than trusting it.
    local i=0
    while [ "$i" -lt 75 ]; do
        if ts_smb_is_mounted "$mp"; then break; fi
        sleep 0.2; i=$((i + 1))
    done
    if ! ts_smb_is_mounted "$mp"; then
        echo "tstack smb: rclone started but $mp never appeared in the mount table; see $logf" >&2
        return 1
    fi

    ts_smb_record_write "$(ts_smb_lower "$name")" \
        name "$(ts_smb_lower "$name")" pid "${pid:-0}" engine "$engine" \
        fuselib "${fuselib:--}" host "$R_HOST" path "$R_PATH" \
        mountpoint "$mp" sudo 0 started "$(date +%s)" cachemode "$vfs"
    echo "$INFO mounted at $mp"
    [ "$vfs" != off ] && echo "$INFO vfs cache: ${XDG_CACHE_HOME:-$HOME/.cache}/rclone (macOS: ~/Library/Caches/rclone)"
    return 0
}

# rclone's own documented way to find a daemonised mount: --log-format=pid puts
# the pid on every line. The pgrep fallback matches the LOG PATH, which we chose
# and can keep regex-safe; the mountpoint cannot be.
capture_pid() {
    local logf="$1" mp="$2" pid=""
    local i=0
    while [ "$i" -lt 25 ]; do
        [ -s "$logf" ] && break
        sleep 0.2; i=$((i + 1))
    done
    pid="$(awk '{ for (i = 1; i <= NF; i++) if ($i ~ /^[0-9]+$/) { print $i; exit } }' "$logf" 2>/dev/null || true)"
    if [ -z "$pid" ]; then
        pid="$(pgrep -f -- "$logf" 2>/dev/null | head -1 || true)"
    fi
    printf '%s' "$pid"
}

do_unmount_path() {
    local mp="$1" engine="${2:-fuse}" usesudo="${3:-0}"
    local pre=""; [ "$usesudo" = 1 ] && pre="sudo"
    case "$(ts_smb_os)" in
        linux)
            if [ "$engine" = fuse ]; then
                command -v fusermount3 >/dev/null 2>&1 && fusermount3 -u "$mp" 2>/dev/null && return 0
                command -v fusermount  >/dev/null 2>&1 && fusermount  -u "$mp" 2>/dev/null && return 0
                if [ "$OPT_FORCE" = 1 ] && command -v fusermount3 >/dev/null 2>&1; then
                    fusermount3 -uz "$mp" 2>/dev/null && return 0
                fi
            fi
            $pre umount "$mp" 2>/dev/null && return 0
            [ "$OPT_FORCE" = 1 ] && $pre umount -f -l "$mp" 2>/dev/null && return 0
            ;;
        darwin)
            $pre umount "$mp" 2>/dev/null && return 0
            diskutil unmount "$mp" >/dev/null 2>&1 && return 0
            # The only thing that reliably clears a wedged macFUSE mount.
            [ "$OPT_FORCE" = 1 ] && diskutil unmount force "$mp" >/dev/null 2>&1 && return 0
            ;;
    esac
    return 1
}

cmd_umount() {
    local name="${1:-}"
    if [ "$OPT_ALL" = 1 ]; then
        local n rc=0
        for n in $(ts_smb_record_names); do umount_one "$n" || rc=1; done
        return "$rc"
    fi
    [ -n "$name" ] || { echo "tstack smb umount: a share name is required (or --all)." >&2; return 2; }
    umount_one "$(ts_smb_lower "$name")"
}

umount_one() {
    local name="$1" mp pid engine usesudo state
    mp="$(ts_smb_record_get "$name" mountpoint '')"
    if [ -z "$mp" ]; then
        echo "tstack smb: no mount recorded for '$name'." >&2
        return 1
    fi
    pid="$(ts_smb_record_get "$name" pid '')"
    engine="$(ts_smb_record_get "$name" engine fuse)"
    usesudo="$(ts_smb_record_get "$name" sudo 0)"
    state="$(ts_smb_mount_state "$name")"

    if [ "$state" = gone ]; then
        echo "$INFO $name: nothing mounted; clearing the record"
        ts_smb_record_rm "$name"; return 0
    fi

    if ts_smb_is_mounted "$mp"; then
        if ! do_unmount_path "$mp" "$engine" "$usesudo"; then
            echo "tstack smb: could not unmount $mp — try 'tstack smb umount $name --force'." >&2
            return 1
        fi
    fi

    # SIGTERM is rclone's documented daemon shutdown; escalate only if it sulks.
    if ts_smb_pid_alive "$pid"; then
        kill -TERM "$pid" 2>/dev/null || true
        local i
        for i in 1 2 3 4 5; do
            ts_smb_pid_alive "$pid" || break
            sleep 1
        done
        ts_smb_pid_alive "$pid" && kill -9 "$pid" 2>/dev/null || true
    fi

    # Never drop the record while the mountpoint is still mounted — that is how
    # you lose the ability to clean it up.
    if ts_smb_is_mounted "$mp"; then
        echo "tstack smb: $mp is still mounted; keeping the record so it can be retried." >&2
        return 1
    fi
    ts_smb_record_rm "$name"
    echo "$INFO $name: unmounted $mp"
    return 0
}

# ── subcommands: store + credentials ────────────────────────────────────────────

. "$SRC/bootstrap/_smb_setup.sh"
cmd_setup() { ts_smb_setup_run "$@"; }

cmd_add() {
    local name="${1:-}"
    [ -n "$name" ] || { echo "tstack smb add: a name is required." >&2; return 2; }
    name="$(ts_smb_lower "$name")"
    if ts_smb_has "$name"; then
        echo "tstack smb: '$name' already exists; edit it with 'tstack smb config'." >&2
        return 1
    fi
    local host path user cred
    host="${OPT_HOSTARG:-}"
    [ -n "$host" ] || host="$(ts_tty_prompt 'SMB host (name or IP): ')"
    [ -n "$host" ] || { echo "tstack smb: a host is required." >&2; return 2; }
    path="${OPT_PATHARG:-}"
    [ -n "$path" ] || path="$(ts_tty_prompt 'Share name on that host (the part after the host): ')"
    [ -n "$path" ] || { echo "tstack smb: a share name is required." >&2; return 2; }
    user="$OPT_USER"
    [ -n "$user" ] || user="$(ts_tty_prompt "SMB user [$(ts_smb_setting default_user guest)]: ")"
    [ -n "$user" ] || user="$(ts_smb_setting default_user guest)"
    if [ "$user" = guest ]; then
        cred=none
    else
        cred="${OPT_CRED:-$(ts_prompt_choice "$(ts_smb_setting default_cred keychain)" \
            'Where should the password live?' \
            '  The password is obscured once and stored; it never appears in a command line.' \
            'keychain|keychain|the OS keychain (macOS security / Linux secret-tool)' \
            'file|file|a 0600 file under ~/.config/terminal-stack/smb-creds' \
            'prompt|prompt|nowhere — ask every time' \
            'none|none|no password (guest)')}"
    fi

    local f; f="$(ts_smb_local_conf)"
    mkdir -p "$(dirname "$f")" 2>/dev/null || true
    {
        printf '\nshare %s\n' "$name"
        printf '  host       %s\n' "$host"
        printf '  path       %s\n' "$path"
        [ "$user" != "$(ts_smb_setting default_user guest)" ] && printf '  user       %s\n' "$user"
        [ -n "$OPT_PORT" ]   && printf '  port       %s\n' "$OPT_PORT"
        [ -n "$OPT_DOMAIN" ] && printf '  domain     %s\n' "$OPT_DOMAIN"
        printf '  cred       %s\n' "$cred"
    } >> "$f"
    echo "$INFO added '$name' to $f"
    TS_SMB_RELOAD=1 ts_smb_load_config
    unset TS_SMB_RELOAD
    case "$cred" in
        keychain|file) echo "$INFO set the password with: tstack smb creds $name set" ;;
    esac
    echo "$INFO check it with: tstack smb shares $host"
    return 0
}

cmd_config() {
    local f; f="$(ts_smb_local_conf)"
    mkdir -p "$(dirname "$f")" 2>/dev/null || true
    if [ ! -f "$f" ]; then
        cp "$SRC/bootstrap/shares.local.conf.example" "$f" 2>/dev/null || : > "$f"
        echo "$INFO seeded $f from the example"
    fi
    "${EDITOR:-micro}" "$f"
    TS_SMB_RELOAD=1 ts_smb_load_config; unset TS_SMB_RELOAD
    local problems; problems="$(ts_smb_validate || true)"
    if [ -n "$problems" ]; then
        echo "$WARN the store has problems:"
        printf '%s\n' "$problems" | sed 's/^/  /'
        return 1
    fi
    echo "$INFO $f is valid."
    return 0
}

cmd_creds() {
    local name="${1:-}" action="${2:-show}"
    [ -n "$name" ] || { echo "tstack smb creds: a share name is required." >&2; return 2; }
    resolve_spec "$name" || return $?
    local backend="$R_CRED"
    case "$backend" in
        none) echo "tstack smb: '$name' uses cred none (guest, no password)."; return 0 ;;
        rclone) echo "tstack smb: '$name' uses an rclone.conf remote; manage it with 'rclone config'."; return 0 ;;
    esac
    case "$action" in
        set)
            local p
            if [ "$OPT_PASSWORD_STDIN" = 1 ]; then p="$(cat)"
            else p="$(read_password_interactive)" || return 1; fi
            [ -n "$p" ] || { echo "tstack smb: empty password; nothing stored." >&2; return 1; }
            need_rclone || return 1
            local blob; blob="$(printf '%s' "$p" | ts_smb_obscure)"
            [ -n "$blob" ] || { echo "tstack smb: could not obscure the password." >&2; return 1; }
            local rc=0
            printf '%s' "$blob" | ts_smb_cred_set "$backend" "$R_USER" "$R_HOST" || rc=$?
            if [ "$rc" = 2 ]; then
                echo "$WARN secret-tool not found; falling back to a 0600 file (not a secret store, just not on the command line)"
                printf '%s' "$blob" | ts_smb_cred_set file "$R_USER" "$R_HOST" || {
                    echo "tstack smb: could not store the password." >&2; return 1; }
            elif [ "$rc" != 0 ]; then
                echo "tstack smb: could not store the password." >&2; return 1
            fi
            echo "$INFO stored the password for $R_USER@$R_HOST ($backend), obscured."
            ;;
        show)
            if ts_smb_cred_present "$backend" "$R_USER" "$R_HOST"; then
                echo "tstack smb: $R_USER@$R_HOST — a password is stored in $backend."
                if [ "$OPT_REVEAL" = 1 ]; then
                    need_rclone || return 1
                    # `rclone reveal` takes its argument on the command line only
                    # — unlike `obscure`, it has no "-" stdin form. That is a
                    # momentary argv exposure of the obscured (reversible) blob,
                    # accepted here because --reveal prints the password to the
                    # terminal anyway. The invariant that matters is unbroken:
                    # nothing secret is in the argv of a long-lived mount.
                    rclone reveal "$(ts_smb_cred_get "$backend" "$R_USER" "$R_HOST")"
                fi
            else
                echo "tstack smb: $R_USER@$R_HOST — no password stored ($backend). Set one with 'tstack smb creds $name set'."
            fi
            ;;
        rm|forget|delete)
            confirm "tstack smb: forget the password for $R_USER@$R_HOST?" || return 1
            ts_smb_cred_rm "$backend" "$R_USER" "$R_HOST"
            echo "$INFO forgotten."
            ;;
        *) echo "tstack smb creds: unknown action '$action' (set, show, rm)." >&2; return 2 ;;
    esac
    return 0
}

# ── subcommands: engine + doctor ────────────────────────────────────────────────

cmd_engine() {
    local eline engine fuselib why
    eline="$(ts_smb_engine_resolve "${OPT_ENGINE:-}")"
    engine="$(printf '%s' "$eline" | cut -f1)"
    fuselib="$(printf '%s' "$eline" | cut -f2)"
    why="$(printf '%s' "$eline" | cut -f3)"
    echo "tstack smb engine:"
    echo "  resolved : $engine"
    [ -n "$fuselib" ] && echo "  libfuse  : $fuselib"
    echo "  because  : $why"
    echo
    case "$(ts_smb_os)" in
        darwin)
            local st; st="$(ts_smb_macfuse_state)"
            if ts_smb_rclone_is_brew; then
                echo "  rclone   : Homebrew build ($(ts_smb_rclone_path)) — CANNOT mount"
                echo "             browsing, listing and copying are unaffected"
            else
                echo "  rclone   : $(ts_smb_rclone_path) — can mount"
            fi
            if ts_smb_fuset_present; then
                echo "  fuse-t   : $(ts_smb_fuset_version), backend $(ts_smb_fuset_backend)"
            else
                echo "  fuse-t   : not installed"
            fi
            case "$st" in
                absent)       echo "  macFUSE  : not installed" ;;
                orphan-dylib) echo "  macFUSE  : a stray libfuse.2.dylib with no macfuse.fs bundle" ;;
                loaded)       echo "  macFUSE  : $(ts_smb_macfuse_version), kext loaded" ;;
                stale)        echo "  macFUSE  : $(ts_smb_macfuse_version) (built for macOS $(ts_smb_macfuse_built_for)), kext NOT loaded" ;;
                plausible)    echo "  macFUSE  : $(ts_smb_macfuse_version), kext not loaded but it may still work" ;;
            esac
            echo
            echo "  On macOS rclone picks its FUSE library by dlopen order — macFUSE first,"
            echo "  fuse-t last — and there is no flag to change that, so tstack smb always pins"
            echo "  CGOFUSE_LIBFUSE_PATH. Without it a stale macFUSE wins and the mount hangs."
            ;;
        linux)
            echo "  fusermount : $(ts_smb_linux_fuse_state)"
            if ts_smb_linux_allow_other; then
                echo "  fuse.conf  : user_allow_other is set"
            else
                echo "  fuse.conf  : user_allow_other is NOT set (--allow-other would fail)"
            fi
            ;;
    esac
    return 0
}

cmd_doctor() {
    local issues=0
    _ok()  { echo "  ok  $1"; }
    _bad() { echo "  $WARN $1"; issues=$((issues + 1)); }
    echo "tstack smb doctor:"

    if ts_smb_have_rclone; then
        _ok "rclone $(rclone version 2>/dev/null | head -1 | awk '{print $2}') at $(command -v rclone)"
    else
        _bad "rclone not found; repair: tstack config apps rclone"
    fi

    local eline engine fuselib why
    eline="$(ts_smb_engine_resolve "")"
    engine="$(printf '%s' "$eline" | cut -f1)"
    fuselib="$(printf '%s' "$eline" | cut -f2)"
    why="$(printf '%s' "$eline" | cut -f3)"
    _ok "engine (auto): $engine — $why"
    [ -n "$fuselib" ] && _ok "libfuse pinned to $fuselib"

    case "$(ts_smb_os)" in
        darwin)
            if ts_smb_rclone_is_brew; then
                _bad "this rclone is the Homebrew build, which refuses to mount on macOS: it aborts with \"rclone mount is not supported on MacOS when rclone is installed via Homebrew\". Browsing, listing and copying are unaffected; only mounting is blocked, and no FUSE library or env var can get past it; repair: install the official binary from https://rclone.org/downloads/ (or brew install gromgit/fuse/rclone-mac)"
            fi
            local st; st="$(ts_smb_macfuse_state)"
            case "$st" in
                stale)
                    _bad "macFUSE $(ts_smb_macfuse_version) (built for macOS $(ts_smb_macfuse_built_for)) is stale for macOS $(ts_smb_macos_major), its kext is not loaded, and it wins rclone's dlopen order; tstack smb pins CGOFUSE_LIBFUSE_PATH so it cannot bite here; repair: run the macFUSE uninstaller to remove it entirely"
                    ;;
                orphan-dylib)
                    _bad "a stray /usr/local/lib/libfuse.2.dylib has no macfuse.fs bundle behind it; repair: rm /usr/local/lib/libfuse.2.dylib (and the libosxfuse* symlinks beside it)"
                    ;;
                plausible)
                    _ok "macFUSE $(ts_smb_macfuse_version) present, kext not loaded — auto will not pick it; force it with: tstack smb mount NAME --engine fuse"
                    ;;
                loaded) _ok "macFUSE $(ts_smb_macfuse_version), kext loaded" ;;
            esac
            if ts_smb_fuset_present; then
                _ok "fuse-t $(ts_smb_fuset_version), backend $(ts_smb_fuset_backend)"
                if [ "$(ts_smb_macos_major)" -ge 26 ] 2>/dev/null; then
                    echo "  note: fuse-t on macOS $(ts_smb_macos_major) can use FSKit, but it is NOT enabled by default — it failed on this platform in testing where the default nfs backend did not"
                fi
            elif [ "$engine" = nfs ]; then
                _bad "no FUSE library usable, so mounts fall back to rclone nfsmount (experimental, read-only without a write cache); repair: brew install --cask fuse-t"
            fi
            if [ -e /Library/Filesystems/osxfuse.fs ]; then
                echo "  note: leftover osxfuse.fs from a pre-macFUSE install; harmless, but it can be removed"
            fi
            ;;
        linux)
            local ls_; ls_="$(ts_smb_linux_fuse_state)"
            case "$ls_" in
                ok)     _ok "fusermount is usable" ;;
                denied) _bad "fusermount is blocked (AppArmor on Ubuntu 24.04+); repair: sudo apt install apparmor-utils && sudo aa-disable /usr/bin/fusermount3" ;;
                absent) _bad "fusermount not found, so mounts fall back to rclone nfsmount; repair: sudo apt install fuse3" ;;
            esac
            ts_smb_linux_allow_other || echo "  note: /etc/fuse.conf has no user_allow_other, so --allow-other is not offered"
            ;;
    esac

    local n state live=0 stale=0
    for n in $(ts_smb_record_names); do
        state="$(ts_smb_mount_state "$n")"
        case "$state" in
            live) live=$((live + 1)) ;;
            *)    stale=$((stale + 1)) ;;
        esac
    done
    if [ "$stale" -gt 0 ]; then
        _bad "$stale stale mount record(s); repair: tstack smb umount --all --force"
    else
        _ok "$live live mount(s), no stale records"
    fi

    local problems; problems="$(ts_smb_validate || true)"
    if [ -n "$problems" ]; then
        _bad "the share store has problems; repair: tstack smb config"
        printf '%s\n' "$problems" | sed 's/^/      /'
    else
        local count; count="$(ts_smb_names | wc -w | tr -d ' ')"
        _ok "$count share(s) configured, store parses clean"
    fi

    if [ "$OPT_CREDCHECK" = 1 ]; then
        for n in $(ts_smb_names); do
            resolve_spec "$n" >/dev/null 2>&1 || continue
            case "$R_CRED" in none|rclone|prompt) continue ;; esac
            if ts_smb_cred_present "$R_CRED" "$R_USER" "$R_HOST"; then
                _ok "$n: password stored in $R_CRED"
            else
                _bad "$n: no password stored; repair: tstack smb creds $n set"
            fi
        done
    else
        echo "  note: credentials not checked (pass --creds; on macOS that can pop a keychain dialog)"
    fi

    [ "$OPT_CANARY" = 1 ] && doctor_canary

    if [ "$OPT_REPAIR" = 1 ]; then doctor_repair; return $?; fi

    unset -f _ok _bad 2>/dev/null || true
    if [ "$issues" -eq 0 ]; then echo "$INFO no problems found."; return 0; fi
    echo "$WARN $issues problem(s) found."
    return 1
}

# A real mount, of the :memory: backend so no network is involved, under a
# watchdog. Deliberately NOT part of the auto probe: against a stale macFUSE it
# can wedge, which is the exact state the probe exists to avoid.
doctor_canary() {
    need_rclone || return 0
    local tmp; tmp="$(mktemp -d)"
    local eline engine fuselib
    eline="$(ts_smb_engine_resolve "")"
    engine="$(printf '%s' "$eline" | cut -f1)"
    fuselib="$(printf '%s' "$eline" | cut -f2)"
    local sub=mount; [ "$engine" = nfs ] && sub=nfsmount
    echo "  canary: $sub :memory: at $tmp"
    if [ -n "$fuselib" ]; then
        CGOFUSE_LIBFUSE_PATH="$fuselib" ts_smb_timeout 20 rclone "$sub" :memory: "$tmp" --daemon --daemon-wait 5s >/dev/null 2>&1 || true
    else
        ts_smb_timeout 20 rclone "$sub" :memory: "$tmp" --daemon --daemon-wait 5s >/dev/null 2>&1 || true
    fi
    if ts_smb_is_mounted "$tmp"; then
        echo "  ok  canary mounted with $engine"
        do_unmount_path "$tmp" "$engine" 0 || true
    else
        echo "  $WARN canary did NOT mount with $engine"
    fi
    rmdir "$tmp" 2>/dev/null || true
    return 0
}

doctor_repair() {
    echo
    echo "$INFO repair"
    local n state mp
    for n in $(ts_smb_record_names); do
        state="$(ts_smb_mount_state "$n")"
        [ "$state" = live ] && continue
        mp="$(ts_smb_record_get "$n" mountpoint '')"
        if confirm "tstack smb: clear the $state record for '$n' ($mp)?"; then
            OPT_FORCE=1 umount_one "$n" || ts_smb_record_rm "$n"
        fi
    done
    local f; f="$(ts_smb_local_conf)"
    if [ ! -f "$f" ] && confirm "tstack smb: seed $f from the example?"; then
        mkdir -p "$(dirname "$f")" 2>/dev/null || true
        cp "$SRC/bootstrap/shares.local.conf.example" "$f" && echo "$INFO seeded $f"
    fi
    if ! ts_smb_have_rclone; then
        if confirm "tstack smb: install rclone now?"; then
            if command -v brew >/dev/null 2>&1; then brew install rclone
            elif command -v apt-get >/dev/null 2>&1; then sudo apt-get install -y rclone
            else echo "$WARN no brew or apt here; install rclone by hand."; fi
        fi
    fi
    echo "$INFO repair does not install macFUSE or fuse-t, edit /etc/fuse.conf, or run aa-disable."
    echo "$INFO anything above that needs one of those is printed, not done."
    return 0
}

# ── flags ───────────────────────────────────────────────────────────────────────

OPT_HOSTARG=""; OPT_PATHARG=""
POS=()
while [ "$#" -gt 0 ]; do
    case "$1" in
        -y|--yes)          ASSUME_YES=1 ;;
        -n|--dry-run)      DRY_RUN=1 ;;
        --engine)          OPT_ENGINE="${2:-}"; shift ;;
        --at)              OPT_AT="${2:-}"; shift ;;
        --rw)              OPT_RW=1 ;;
        --read-only)       OPT_RW=0 ;;
        --all)             OPT_ALL=1 ;;
        --force)           OPT_FORCE=1 ;;
        --allow-nonempty)  OPT_NONEMPTY=1 ;;
        --volume)          OPT_VOLUME=1 ;;
        --depth)           OPT_DEPTH="${2:-2}"; shift ;;
        --sweep)           OPT_SWEEP=1 ;;
        --write)           OPT_WRITE=1 ;;
        --host)            OPT_HOSTARG="${2:-}"; shift ;;
        --path)            OPT_PATHARG="${2:-}"; shift ;;
        -u|--user)         OPT_USER="${2:-}"; shift ;;
        --domain)          OPT_DOMAIN="${2:-}"; shift ;;
        --port)            OPT_PORT="${2:-}"; shift ;;
        --guest)           OPT_GUEST=1 ;;
        --cred)            OPT_CRED="${2:-}"; shift ;;
        -P|--password)     OPT_PASSWORD=1 ;;
        --password-stdin)  OPT_PASSWORD_STDIN=1 ;;
        --reveal)          OPT_REVEAL=1 ;;
        --creds)           OPT_CREDCHECK=1 ;;
        --canary)          OPT_CANARY=1 ;;
        --repair)          OPT_REPAIR=1 ;;
        -h|--help|help)    printf '%s\n' "$HELP"; exit 0 ;;
        --) shift; while [ "$#" -gt 0 ]; do POS+=("$1"); shift; done; break ;;
        -*) echo "tstack smb: unknown flag '$1' (try: tstack smb -h)" >&2; exit 2 ;;
        *)  POS+=("$1") ;;
    esac
    shift
done
set -- ${POS+"${POS[@]}"}

CMD="${1:-}"; [ "$#" -gt 0 ] && shift

case "$CMD" in
    ""|list|status) cmd_list "$@" ;;
    hosts|discover) cmd_hosts "$@" ;;
    shares)         cmd_shares "$@" ;;
    probe)          cmd_probe "$@" ;;
    ls)             cmd_ls "$@" ;;
    tree)           cmd_tree "$@" ;;
    du|size)        cmd_du "$@" ;;
    get|copy)       cmd_get "$@" ;;
    setup)          cmd_setup "$@" ;;
    mount)          cmd_mount "$@" ;;
    umount|unmount) cmd_umount "$@" ;;
    add)            cmd_add "$@" ;;
    config|edit)    cmd_config "$@" ;;
    creds)          cmd_creds "$@" ;;
    engine)         cmd_engine "$@" ;;
    doctor)         cmd_doctor "$@" ;;
    *) echo "tstack smb: unknown command '$CMD' (list, hosts, shares, probe, ls, tree, du, get, setup, mount, umount, add, config, creds, engine, doctor)" >&2; exit 2 ;;
esac
