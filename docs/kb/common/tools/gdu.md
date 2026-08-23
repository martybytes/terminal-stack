# gdu (fast disk usage TUI)

Same job as `ncdu`, written for speed — it parallelises the walk, so scanning a
large SSD finishes in seconds rather than minutes.

## The name collision

GNU coreutils already ships a `gdu` — its g-prefixed `du` — so **Homebrew installs
this one as `gdu-go`** when coreutils is present. On a Mac with coreutils, plain
`gdu` is GNU du, not this TUI. The stack resolves whichever is actually there
(`ts_app_bin gdu`) rather than reporting one as the other, and deliberately does
*not* symlink over coreutils' `gdu` the way it does for `batcat`/`fdfind` — that
name was coreutils' first. Type `gdu-go` (or alias it yourself) if you have both.
On Linux and Windows there is no collision and the binary is just `gdu`.

| Command | What it does |
|---|---|
| `gdu` | scan the current directory |
| `gdu /` | scan from root |
| `gdu -x /` | stay on one filesystem |
| `gdu -i /mnt` | ignore a path (repeatable) |
| `gdu -n /` | no UI — print the summary and exit |
| `gdu -o- / \| gzip > scan.gz` | export a scan; `gdu -f scan.gz` reads it back |
| `gdu --si` | powers of 1000 instead of 1024 |

Keys: `↑`/`↓` move, `Enter`/`→` descend, `←` up, `d` delete, `n`/`s`/`c` sort by
name/size/items, `r` rescan, `/` search, `q` quit.

Prefer `gdu` on big trees and `ncdu` where you want the older, quieter UI.
See `doc files-disk`.
