# rclone (sync and mount 70+ storage backends)

One binary that speaks S3, SFTP, WebDAV, Google Drive, SMB and about seventy
other things with the same flags everywhere. In this stack it is the engine
behind `tstack smb`; see `doc smb-shares` for the wrapper.

| Command | What it does |
|---|---|
| `rclone config` | guided setup with SMB first and provider categories explained |
| `rclone-stock config` | original advanced wizard (writes `~/.config/rclone/rclone.conf`) |
| `rclone listremotes` | what you have configured |
| `rclone lsd remote:` | list directories — against an SMB root, this lists the **shares** |
| `rclone lsf remote:path` | flat listing, one name per line (script-friendly) |
| `rclone tree remote:path --level 2` | depth-limited tree |
| `rclone size remote:path` | object count and total bytes |
| `rclone copy SRC DST --progress` | copy, skipping files already identical |
| `rclone sync SRC DST --dry-run` | make DST match SRC — **always dry-run first** |
| `rclone check SRC DST` | compare without transferring |
| `rclone mount remote: ~/mnt/x --vfs-cache-mode writes` | FUSE mount (needs a FUSE library) |
| `rclone nfsmount remote: ~/mnt/x` | mount without FUSE, via a local NFS server |
| `rclone obscure -` | obscure a password read from stdin (never pass it as an argument) |
| `rclone reveal OBSCURED` | turn an obscured value back into plaintext |

Connection strings make a remote on the fly, so nothing has to be configured
first: `rclone lsd ":smb,host=nas.lan,user=guest:"`. Pass the password as the
`RCLONE_SMB_PASS` environment variable and **obscure it first** — rclone rejects
plaintext there.

The guided setup explains that rclone's **Storage** question means the kind of
server or service—not a folder and not where its configuration file lives. It
preselects common providers, progressively searches uncommon ones, and uses
`tstack smb setup` for Windows/NAS shared folders. `rclone-stock config` is the raw
escape hatch for upstream instructions.

rclone's Tier is backend support/maturity: Tier 1 is production-grade, Tier 2
is stable with minor gaps, Tier 3 has known caveats, Tier 4 is experimental,
and Tier 5 is deprecated. It is not price, capacity, or storage location.

Two macOS traps. Homebrew's rclone **cannot mount at all** (it aborts with
"rclone mount is not supported on MacOS when rclone is installed via Homebrew");
browsing and copying are unaffected, but for mounting you need the official
binary from <https://rclone.org/downloads/>. And when both macFUSE and FUSE-T are
installed, rclone always picks macFUSE — set `CGOFUSE_LIBFUSE_PATH` to choose.

`rclone` moves and mounts remote data; `rsync`/`scp` do the same for one SSH
host. See `doc scp-rsync`, `doc smb-shares`.
