# SMB shares (`ts-smb`)

Find, interrogate and mount SMB/CIFS shares through rclone, with the same
commands on macOS and Linux. Replaces knowing `smbutil`/`mount_smbfs` on one box
and `smbclient`/`mount.cifs` on another.

| Command | What it does |
|---|---|
| `ts-smb hosts` | SMB servers advertising on this LAN (mDNS) |
| `ts-smb hosts --sweep` | also port-scan your /24 — asks first, and it is noisy |
| `ts-smb shares HOST` | the shares a host offers |
| `ts-smb probe HOST/SHARE` | which credentials work, and what they get you |
| `ts-smb probe HOST/SHARE --write` | also test writability (creates a file; asks first) |
| `ts-smb ls NAME` | one listing, no mount |
| `ts-smb tree NAME --depth 3` | depth-limited tree |
| `ts-smb du NAME` | object count and total size |
| `ts-smb get NAME/file.txt .` | copy out without mounting |
| `ts-smb add NAME --host H --path SHARE --user U` | add it to your store |
| `ts-smb creds NAME set` | store the password (obscured) in the OS keychain |
| `ts-smb mount NAME` / `ts-smb umount NAME` | mount read-only / unmount |
| `ts-smb mount NAME --rw` | mount read-write (turns on the VFS write cache) |
| `ts-smb list` | live mounts, with stale ones flagged |
| `ts-smb engine` | which mount engine is used here, and why the others lost |
| `ts-smb doctor` | rclone, FUSE, stale mounts, the store |

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

The SMB share name is `path`, not `share` — `share` opens a stanza. `ts-smb
doctor` says so if you get it wrong.

Passwords are obscured once by `ts-smb creds` and kept in the OS keychain; they
reach rclone through the environment and never appear in a command line. There is
no `--password VALUE` flag on purpose; use `-P` or `--password-stdin`.

rclone has no anonymous mode — user `guest` with an empty password is the
substitute, and it is the default.

Windows is not supported yet; use Explorer or `net use` there. See `doc rclone`.
