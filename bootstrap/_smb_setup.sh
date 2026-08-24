#!/usr/bin/env bash
# Guided, verified, transactional setup for ts-smb. Sourced by ts-smb.sh.

ts_smb_setup_run() {
    need_rclone || return 1
    if ! ts_is_interactive; then
        echo "ts-smb setup: an interactive terminal is required; use 'ts-smb add' for scripted setup." >&2
        return 2
    fi
    cat >/dev/tty <<'EOF'

SMB connects to a shared folder published by a Windows PC or NAS.
First choose the computer, then sign in, then choose one of that computer's
shared folders. Nothing is saved until the connection is verified and you
approve a final review.
EOF

    local host="${OPT_HOSTARG:-}" short dns candidates="" tmp="" c
    if [ -z "$host" ] && command -v tailscale >/dev/null 2>&1 && command -v jq >/dev/null 2>&1; then
        echo "$INFO looking for online Tailscale computers accepting SMB on port 445..." >/dev/tty
        tmp="$(mktemp "${TMPDIR:-/tmp}/ts-smb-peers.XXXXXX")" || return 1
        while IFS=$'\t' read -r short dns; do
            [ -n "$dns" ] || continue
            (
                command -v nc >/dev/null 2>&1 || exit 0
                nc -z -w 2 "$dns" 445 >/dev/null 2>&1 || exit 0
                printf '%s\t%s\n' "$short" "$dns" >> "$tmp"
            ) &
        done <<EOF
$(tailscale status --json 2>/dev/null | jq -r '.Peer[]? | select(.Online) | [(.HostName // (.DNSName|split(".")[0])), (.DNSName|rtrimstr("."))] | @tsv' 2>/dev/null || true)
EOF
        wait
        candidates="$(sort -fu "$tmp" 2>/dev/null || true)"
        rm -f "$tmp"
        if [ -n "$candidates" ]; then
            local opts=() hosts=() i=0
            while IFS=$'\t' read -r short dns; do
                [ -n "$dns" ] || continue
                i=$((i + 1)); hosts[$i]="$dns"
                opts+=("$i|$short|$dns — online; SMB port 445 is open")
            done <<EOF
$candidates
EOF
            opts+=("manual|Enter another hostname or IP|use a LAN host or a peer not listed")
            c="$(ts_prompt_choice 1 'Which computer publishes the Windows/NAS shared folder?' \
                'The short name identifies the computer; the .ts.net name is its full Tailscale address.' "${opts[@]}")"
            [ "$c" = manual ] || host="${hosts[$c]}"
        else
            echo "$WARN no online Tailscale peers with SMB port 445 open were found." >/dev/tty
        fi
    fi
    [ -n "$host" ] || host="$(ts_tty_prompt 'Computer hostname, full Tailscale name, or IP address: ')"
    [ -n "$host" ] || { echo "ts-smb setup: a computer is required." >&2; return 2; }
    ts_smb_valid_token "$host" || { echo "ts-smb setup: '$host' is not a usable hostname." >&2; return 2; }

    local auth user domain="${OPT_DOMAIN:-}" plain="" blob="" cred
    auth="$(ts_prompt_choice account 'How do you sign in to this computer?' \
        'Use the Windows/NAS account allowed to view the shared folder. Guest works only when the server explicitly allows it.' \
        'account|Username and password|normal Windows or NAS account' \
        'guest|Guest access|no password; often disabled')"
    if [ "$auth" = guest ]; then
        user=guest; cred=none
    else
        user="${OPT_USER:-$(ts_tty_prompt 'SMB username (the account on the Windows PC or NAS): ')}"
        [ -n "$user" ] || { echo "ts-smb setup: a username is required." >&2; return 2; }
        ts_smb_valid_token "$user" || { echo "ts-smb setup: '$user' is not a usable username." >&2; return 2; }
        [ -n "$domain" ] || domain="$(ts_tty_prompt 'Windows domain (usually blank for a home PC or NAS): ')"
        if [ "$OPT_PASSWORD_STDIN" = 1 ]; then plain="$(cat)"; else plain="$(read_password_interactive)" || return 1; fi
        [ -n "$plain" ] || { echo "ts-smb setup: an empty password was not stored." >&2; return 1; }
        blob="$(printf '%s' "$plain" | ts_smb_obscure)"; plain=""
        [ -n "$blob" ] || { echo "ts-smb setup: rclone could not obscure the password." >&2; return 1; }
        cred="${OPT_CRED:-$(ts_prompt_choice "$(ts_smb_setting default_cred keychain)" \
            'Where should this password be kept after verification?' \
            'It is obscured before storage and never appears in a command line.' \
            'keychain|OS keychain|macOS Keychain or Linux secret-tool' \
            'file|Protected local file|0600 file; fallback when no keychain is available' \
            'prompt|Do not store it|ask again whenever needed')}"
    fi

    local root_remote shares="" errf
    root_remote="$(ts_smb_remote "$host" "$user" "$domain" "${OPT_PORT:-}")"
    errf="$(mktemp "${TMPDIR:-/tmp}/ts-smb-error.XXXXXX")" || return 1
    echo "$INFO signing in and asking $host for its shared-folder list..." >/dev/tty
    if [ -n "$blob" ]; then
        shares="$(RCLONE_SMB_PASS="$blob" ts_smb_timeout 20 rclone lsf "$root_remote" --dirs-only --smb-idle-timeout 5s 2>"$errf" || true)"
    else
        shares="$(ts_smb_timeout 20 rclone lsf "$root_remote" --dirs-only --smb-idle-timeout 5s 2>"$errf" || true)"
    fi
    shares="$(printf '%s\n' "$shares" | sed 's:/$::' | sed '/^$/d')"

    local path="${OPT_PATHARG:-}" manual=0
    if [ -z "$path" ] && [ -n "$shares" ]; then
        local share_opts=() share_vals=() share i=0
        while IFS= read -r share; do
            [ -n "$share" ] || continue
            i=$((i + 1)); share_vals[$i]="$share"; share_opts+=("$i|$share|shared folder on $host")
        done <<EOF
$shares
EOF
        share_opts+=("manual|Enter a different share name|use this if the server hides part of its share list")
        c="$(ts_prompt_choice 1 'Which shared folder do you want to use?' \
            'These are folders published by the selected computer, not folders on this Mac/Linux machine.' "${share_opts[@]}")"
        if [ "$c" = manual ]; then manual=1; else path="${share_vals[$c]}"; fi
    else
        manual=1
        [ -s "$errf" ] && echo "$WARN the server did not provide a share list; a known share can still be checked directly." >/dev/tty
    fi
    rm -f "$errf"
    if [ "$manual" = 1 ] && [ -z "$path" ]; then
        path="$(ts_tty_prompt 'Exact shared-folder name on that computer (example: Media): ')"
    fi
    [ -n "$path" ] || { echo "ts-smb setup: a shared-folder name is required." >&2; return 2; }
    case "$path" in *[[:space:]]*) echo "ts-smb setup: share names containing spaces are not supported by the local inventory format." >&2; return 2 ;; esac

    local share_remote="$root_remote$path/" verified=0
    echo "$INFO verifying that '$path' is readable with these credentials..." >/dev/tty
    if [ -n "$blob" ]; then
        RCLONE_SMB_PASS="$blob" ts_smb_timeout 20 rclone lsf "$share_remote" --max-depth 1 --smb-idle-timeout 5s >/dev/null 2>&1 && verified=1
    else
        ts_smb_timeout 20 rclone lsf "$share_remote" --max-depth 1 --smb-idle-timeout 5s >/dev/null 2>&1 && verified=1
    fi
    [ "$verified" = 1 ] || {
        echo "ts-smb setup: '$host/$path' could not be read. Nothing was saved." >&2
        echo "Check the username, password, share name, and Windows sharing permissions, then retry." >&2
        return 1
    }

    local name
    while :; do
        name="$(ts_smb_lower "$(ts_tty_prompt 'Short local alias used in commands (example: origin-media): ')")"
        case "$name" in
            '') echo "The local alias is required; it is not the computer name." >/dev/tty ;;
            *[!a-z0-9._-]*) echo "Use letters, numbers, dots, underscores, or dashes only." >/dev/tty ;;
            *) if ts_smb_has "$name"; then echo "Alias '$name' already exists; choose another." >/dev/tty; else break; fi ;;
        esac
    done

    cat >/dev/tty <<EOF

Review — nothing has been saved yet:
  local alias : $name        (used as: ts-smb ls $name)
  computer    : $host
  share       : $path
  account     : ${domain:+$domain\\}$user
  credential  : $cred
  mountpoint  : $(ts_smb_mountpoint "$name")
  mount mode  : read-only unless you explicitly pass --rw
EOF
    confirm "Save this verified share?" || { echo "$INFO cancelled; nothing was saved."; return 0; }

    local actual_cred="$cred" old_blob="" old_had=0 stored=0 rc=0
    if [ "$cred" = keychain ] || [ "$cred" = file ]; then
        old_blob="$(ts_smb_cred_get "$cred" "$user" "$host")"; [ -n "$old_blob" ] && old_had=1
        printf '%s' "$blob" | ts_smb_cred_set "$cred" "$user" "$host" || rc=$?
        if [ "$rc" = 2 ]; then
            actual_cred=file; rc=0
            old_blob="$(ts_smb_cred_get file "$user" "$host")"; old_had=0; [ -n "$old_blob" ] && old_had=1
            echo "$WARN no OS secret service is available; using a protected 0600 local file." >/dev/tty
            printf '%s' "$blob" | ts_smb_cred_set file "$user" "$host" || rc=$?
        fi
        [ "$rc" = 0 ] || { echo "ts-smb setup: could not store the credential; nothing was saved." >&2; return 1; }
        stored=1
    fi

    local f dir tmpconf
    f="$(ts_smb_local_conf)"; dir="$(dirname "$f")"
    mkdir -p "$dir" 2>/dev/null || rc=1
    tmpconf="$(mktemp "$dir/.shares.local.conf.XXXXXX" 2>/dev/null || true)"; [ -n "$tmpconf" ] || rc=1
    if [ "$rc" = 0 ]; then
        [ -f "$f" ] && cp "$f" "$tmpconf"
        {
            printf '\nshare %s\n' "$name"
            printf '  host %s\n  path %s\n  user %s\n' "$host" "$path" "$user"
            [ -n "$domain" ] && printf '  domain %s\n' "$domain"
            [ -n "${OPT_PORT:-}" ] && printf '  port %s\n' "$OPT_PORT"
            printf '  cred %s\n' "$actual_cred"
        } >> "$tmpconf" || rc=1
        chmod 600 "$tmpconf" 2>/dev/null || rc=1
        [ "$rc" = 0 ] && mv "$tmpconf" "$f" || rc=1
    fi
    if [ "$rc" != 0 ]; then
        [ -n "${tmpconf:-}" ] && rm -f "$tmpconf"
        if [ "$stored" = 1 ]; then
            if [ "$old_had" = 1 ]; then printf '%s' "$old_blob" | ts_smb_cred_set "$actual_cred" "$user" "$host" >/dev/null 2>&1 || true
            else ts_smb_cred_rm "$actual_cred" "$user" "$host"; fi
        fi
        echo "ts-smb setup: could not save the local inventory; the credential change was rolled back." >&2
        return 1
    fi

    TS_SMB_RELOAD=1 ts_smb_load_config; unset TS_SMB_RELOAD
    echo "$INFO saved '$name' locally in $f"
    echo "$INFO preview of $host/$path (up to 20 entries):"
    if [ -n "$blob" ]; then
        RCLONE_SMB_PASS="$blob" ts_smb_timeout 20 rclone lsf "$share_remote" --max-depth 1 --smb-idle-timeout 5s 2>/dev/null | head -20 || true
    else
        ts_smb_timeout 20 rclone lsf "$share_remote" --max-depth 1 --smb-idle-timeout 5s 2>/dev/null | head -20 || true
    fi
    echo "$INFO browse later: ts-smb ls $name"
    echo "$INFO mounting makes it appear at $(ts_smb_mountpoint "$name"); it remains read-only by default."
    c="$(ts_prompt_choice browse 'What next?' \
        'Browsing runs one command. Mounting starts a background filesystem until you unmount it.' \
        'browse|Finish without mounting|recommended; use ts-smb ls when needed' \
        'mount|Mount read-only now|unmount later with ts-smb umount')"
    [ "$c" = mount ] && cmd_mount "$name"
}
