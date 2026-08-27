# SMB shares (`tstack smb`)

Find, interrogate and mount SMB/CIFS shares through rclone, with the same
commands on macOS and Linux. Replaces knowing `smbutil`/`mount_smbfs` on one box
and `smbclient`/`mount.cifs` on another.

| Command | What it does |
|---|---|
| `tstack smb setup` | guided Tailscale-aware setup; verifies access before saving |
| `tstack smb hosts` | SMB servers advertising on this LAN (mDNS) |
| `tstack smb hosts --sweep` | also port-scan your /24 — asks first, and it is noisy |
| `tstack smb shares HOST` | the shares a host offers |
| `tstack smb probe HOST/SHARE` | which credentials work, and what they get you |
| `tstack smb probe HOST/SHARE --write` | also test writability (creates a file; asks first) |
| `tstack smb ls NAME` | one listing, no mount |
| `tstack smb tree NAME --depth 3` | depth-limited tree |
| `tstack smb du NAME` | object count and total size |
| `tstack smb get NAME/file.txt .` | copy out without mounting |
| `tstack smb add NAME --host H --path SHARE --user U` | add it to your store |
| `tstack smb creds NAME set` | store the password (obscured) in the OS keychain |
| `tstack smb mount NAME` / `tstack smb umount NAME` | mount read-only / unmount |
| `tstack smb mount NAME --rw` | mount read-write (turns on the VFS write cache) |
| `tstack smb list` | live mounts, with stale ones flagged |
| `tstack smb engine` | which mount engine is used here, and why the others lost |
| `tstack smb doctor` | rclone, FUSE, stale mounts, the store |

`NAME` is a share from your store; `HOST/SHARE[/PATH]` works too, and a bare host
means "list its shares". Nothing has to be configured to interrogate a host.

Your shares live in `~/.config/terminal-stack/shares.local.conf` — untracked and
never synced anywhere. Defaults are in `bootstrap/shares.conf`. A stanza is:

```
share media
  host nas.lan
  path Media
  user marty
  cred keychain
```

The SMB share name is `path`, not `share` — `share` opens a stanza. `tstack smb
doctor` says so if you get it wrong.

Passwords are obscured once by `tstack smb creds` and kept in the OS keychain; they
reach rclone through the environment and never appear in a command line. There is
no `--password VALUE` flag on purpose; use `-P` or `--password-stdin`.

Start a new connection with `tstack smb setup`. It explains every choice, finds
online Tailscale computers with SMB open, signs in before listing their actual
shared folders, verifies the selected folder, and reviews everything before
writing the machine-local inventory. It then previews the folder and optionally
offers a read-only mount. `tstack smb add` remains the lower-level manual route.

rclone has no anonymous mode — user `guest` with an empty password is the
substitute, and it is the default.

Windows is not supported yet; use Explorer or `net use` there. See `doc rclone`.
