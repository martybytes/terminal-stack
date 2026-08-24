#!/usr/bin/env bash
# A small, contextual front door for rclone's very large configuration wizard.
# The zsh wrapper calls this only for the exact interactive `rclone config`.
set -u

SRC="${TERMINAL_STACK_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
RCLONE_BIN="${TERMINAL_STACK_RCLONE_BIN:-}"
[ -n "$RCLONE_BIN" ] || RCLONE_BIN="$(command -v rclone 2>/dev/null || true)"
if [ -z "$RCLONE_BIN" ]; then
    echo "rclone config: rclone is not installed. Run: ts-config apps rclone" >&2
    exit 127
fi

# shellcheck source=_config.sh
. "$SRC/bootstrap/_config.sh"
# shellcheck source=_wizard.sh
. "$SRC/bootstrap/_wizard.sh"

if ! ts_is_interactive; then
    cat >&2 <<'EOF'
rclone config: terminal-stack's guided setup needs an interactive terminal.
Run it in a terminal, or use `rclone-stock config` for rclone's raw interface.
Scripted commands such as `rclone config create ...` are never intercepted.
EOF
    exit 2
fi

say_context() {
    cat >/dev/tty <<'EOF'

rclone saves connections to other computers and storage services.
You are choosing what kind of server or service to connect to.
This does NOT choose a folder, and it does NOT choose where configuration is stored.

A "saved connection" is a reusable set of connection settings. Its local nickname
is only how you refer to it in commands, for example `photos:` or `backup:`.
EOF
}

remote_name() {
    local type="$1" name existing
    while :; do
        name="$(ts_tty_prompt "Local nickname for this $type connection (example: backup): ")"
        case "$name" in
            '') echo "A nickname is required; it is not the server or folder name." >/dev/tty ;;
            *[!A-Za-z0-9._-]*) echo "Use letters, numbers, dots, underscores, or dashes only." >/dev/tty ;;
            *)
                existing="$($RCLONE_BIN listremotes 2>/dev/null | sed 's/:$//' | grep -Fx "$name" || true)"
                if [ -n "$existing" ]; then
                    echo "A saved connection named '$name' already exists. Choose another nickname." >/dev/tty
                else
                    printf '%s\n' "$name"
                    return 0
                fi
                ;;
        esac
    done
}

create_remote() {
    local type="$1" label="$2" name
    cat >/dev/tty <<EOF

Next you will configure $label. The storage type is already selected, so rclone
will not show its enormous provider list. rclone may still ask provider-specific
questions or open a browser for sign-in.
EOF
    name="$(remote_name "$label")" || return 1
    "$RCLONE_BIN" config create "$name" "$type"
}

server_menu() {
    local c
    c="$(ts_prompt_choice sftp 'What protocol does the server use?' \
        'This selects how rclone connects; it does not select a folder.' \
        'sftp|SFTP / SSH|recommended for Linux and Unix servers' \
        'webdav|WebDAV|common for hosted file services and NAS devices' \
        'ftp|FTP|older and normally unencrypted unless separately protected' \
        'back|Back|return to the main menu')"
    case "$c" in
        sftp) create_remote sftp 'an SFTP server' ;;
        webdav) create_remote webdav 'a WebDAV server' ;;
        ftp) create_remote ftp 'an FTP server' ;;
    esac
}

cloud_menu() {
    local c
    c="$(ts_prompt_choice drive 'Which personal cloud service?' \
        'The provider is selected here; its own sign-in follows afterward.' \
        'drive|Google Drive' 'onedrive|Microsoft OneDrive' 'dropbox|Dropbox' \
        'box|Box' 'iclouddrive|iCloud Drive' 'protondrive|Proton Drive' \
        'mega|Mega' 'pcloud|pCloud' 'back|Back')"
    [ "$c" = back ] || create_remote "$c" "$c"
}

object_menu() {
    local c label
    c="$(ts_prompt_choice s3 'Which object-storage service?' \
        'Object storage is normally used for backups or applications, not a Windows shared folder.' \
        's3|Amazon S3 or S3-compatible|AWS, Cloudflare R2, MinIO, Wasabi, and many others' \
        'b2|Backblaze B2' 'azureblob|Microsoft Azure Blob Storage' \
        'google cloud storage|Google Cloud Storage|not Google Drive' 'back|Back')"
    [ "$c" = back ] && return 0
    label="$c"; [ "$c" = 'google cloud storage' ] && label='Google Cloud Storage'
    create_remote "$c" "$label"
}

tier_help() {
    cat >/dev/tty <<'EOF'

rclone's Tier is its backend support/maturity classification, not price, storage
capacity, or location:
  Tier 1  production-grade, first-class
  Tier 2  well-supported, with minor gaps
  Tier 3  works for many uses, with known caveats
  Tier 4  experimental; expect gaps or changes
  Tier 5  deprecated; no longer maintained or supported
EOF
}

provider_search() {
    if ! command -v jq >/dev/null 2>&1; then
        echo "Provider search needs jq. Run: ts-config apps jq" >/dev/tty
        echo "You can still use Advanced raw rclone wizard from the main menu." >/dev/tty
        return 1
    fi
    local data query count row key name desc tier c
    data="$($RCLONE_BIN config providers 2>/dev/null)" || {
        echo "rclone could not provide its provider catalog." >/dev/tty; return 1; }
    tier_help
    while :; do
        query="$(ts_tty_prompt "Search provider name or description (example: proton; 'all' shows everything; blank goes back): ")"
        [ -n "$query" ] || return 0
        if [ "$query" = all ]; then
            c="$(ts_prompt_choice no 'Show the complete provider catalog?' \
                'It is long. Searching by a word is usually faster.' \
                'no|No|return to search' 'yes|Yes|show every backend')"
            [ "$c" = yes ] || continue
            query=''
        fi
        rows="$(printf '%s' "$data" | jq -r --arg q "$query" '
          map(select($q == "" or (((.Name // "") + " " + (.Description // "")) | ascii_downcase | contains($q|ascii_downcase))))
          | .[] | [(.Name // ""), (.Description // .Name // ""), (.Overview.Tier // "Unrated")] | @tsv')"
        count="$(printf '%s\n' "$rows" | sed '/^$/d' | wc -l | tr -d ' ')"
        if [ "$count" -eq 0 ]; then echo "No providers matched '$query'. Try another word." >/dev/tty; continue; fi
        if [ "$count" -gt 12 ] && [ -n "$query" ]; then
            echo "$count providers matched. Add another word to narrow the result." >/dev/tty
            printf '%s\n' "$rows" | head -12 | awk -F '\t' '{printf "  %-22s %s (%s)\n",$1,$2,$3}' >/dev/tty
            continue
        fi
        local opts=()
        while IFS=$'\t' read -r name desc tier; do
            [ -n "$name" ] || continue
            opts+=("$name|$desc|$tier")
        done <<EOF
$rows
EOF
        opts+=("back|Back|return to provider search")
        c="$(ts_prompt_choice back 'Which provider do you mean?' \
            'This selects the connection technology, not a folder or config location.' "${opts[@]}")"
        [ "$c" = back ] || { create_remote "$c" "$c"; return; }
    done
}

say_context
while :; do
    choice="$(ts_prompt_choice smb 'What kind of server or service do you want to connect to?' \
        'Windows shared folders use SMB. Choose another category only when you know the service uses it.' \
        'smb|Windows / NAS shared folder|SMB — recommended for Windows shares over Tailscale' \
        'server|Another computer or server|SFTP, FTP, or WebDAV' \
        'cloud|Personal cloud drive|Google Drive, OneDrive, Dropbox, and similar' \
        'object|Object storage or backups|S3, B2, Azure Blob, or Google Cloud Storage' \
        'other|Search for another provider|progressively search rclone’s complete catalog' \
        'manage|Manage saved connections|rename, reconnect, edit, or delete existing remotes' \
        'raw|Advanced raw rclone wizard|the original rclone interface' \
        'quit|Quit|make no changes')"
    case "$choice" in
        smb)
            echo >/dev/tty
            echo "SMB setup selects a specific shared folder on a Windows PC or NAS." >/dev/tty
            TERMINAL_STACK_DIR="$SRC" TERMINAL_STACK_RCLONE_BIN="$RCLONE_BIN" \
                bash "$SRC/bootstrap/ts-smb.sh" setup
            ;;
        server) server_menu ;;
        cloud) cloud_menu ;;
        object) object_menu ;;
        other) provider_search ;;
        manage)
            echo "Opening rclone's connection-management screen. You are managing saved connection settings." >/dev/tty
            "$RCLONE_BIN" config
            ;;
        raw)
            echo "Opening rclone's original advanced wizard. Its 'Storage' question means connection/provider type." >/dev/tty
            "$RCLONE_BIN" config
            ;;
        quit) exit 0 ;;
    esac
done
