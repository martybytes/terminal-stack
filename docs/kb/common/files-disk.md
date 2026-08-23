# Files & disk

| Command | What it does |
|---|---|
| `ls` | aliased to **eza** — icons, git status, dirs first (`-l`/`-la` as usual) |
| `ls -T` / `lt` | eza tree view |
| `ll` / `la` | long / hidden+long (pwsh) |
| `lsr` | top-level dirs, most recently *worked in* first (see below) |
| `lsrr` | the same, capped at the 20 most recent |
| `lsr -a` / `lsrr -a` | same, including hidden/dotted directories |
| `lsr <dir>` | run it somewhere other than the current directory |
| `cat file` / `bat file` | **bat** — syntax highlighting, line numbers |
| `glow file.md` | render markdown in the terminal (`glow .` for a browser) |
| `fd pattern` | find files by name — regex, colour, honours `.gitignore` (`doc fd`) |
| `tree -L 2` | directory structure as text, for pasting (`doc tree`) |
| `duf` | free space per mount, readable (`doc duf`) — **which disk is full** |
| `dust` | biggest subdirectories, sorted tree, one shot (`doc dust`) — **what filled it** |
| `gdu` / `ncdu` | interactive disk-usage browsers you can delete from (`doc gdu`, `doc ncdu`) |
| `rmf <path…>` | force-delete recursively — **no confirmation, no undo** (see below) |
| `df -h` | disk free, human-readable |
| `du -sh *` | size of each item in the current dir |

## `rmf` — force delete

`rm -rf` in zsh; `Remove-Item -Recurse -Force -Confirm:$false` in pwsh. Both shells,
same behavior: never prompts, takes read-only and hidden items with it, and does
**not** use the Recycle Bin — there is no undo. Tab-complete the path and read it
back before pressing Enter.

`lt` is the tree view (`eza --tree`) in both shells — handy for checking what a
directory holds *before* an `rmf`.

## `lsr` — which project did I touch last?

`ls -lt` and `eza -s modified` sort directories by the directory's **own** mtime, which only
changes when entries are added or removed — not when a file inside is edited. A project you
worked in all afternoon can therefore sit at the bottom of the list.

`lsr` ranks each top-level directory by the newest mtime among its **immediate children**
(exactly one level deep — it never recurses, so it stays fast on big trees). Empty directories
show `(empty)` and sort last; the directory's own timestamp is never used, not even as a
fallback. Hidden *children* always count toward the ranking, even without `-a`.

```
$ lsr
fresh                         2026-08-15 11:00  new.txt
spaced dir                    2026-07-04 08:30  my report v2.txt
stale                         2020-01-01 10:00  old.txt
empty                         (empty)
```

`lsrr` is `lsr` truncated to the 20 most recent — the common case on a workspace with
dozens of checkouts. It takes the same flags and optional directory. For any other count,
pipe `lsr` yourself: `lsr | head -5`, or `lsr | Select-Object -First 5` in PowerShell.

Both shells agree on ordering. Two platform notes:

- `-a` means *dot-prefixed* on Linux/macOS/WSL but the *hidden attribute* on Windows, so the
  two can cover slightly different sets on the same folder.
- In PowerShell `lsr` emits objects, so it composes: `lsr | Where-Object Latest -gt (Get-Date).AddDays(-7)`,
  `lsr | Export-Csv recent.csv`. The zsh/bash version prints aligned text.

## Which disk tool

Four tools, four questions:

| Question | Tool |
|---|---|
| How much free space is left, per mount? | `duf` |
| What is taking up the space here? (one shot, pasteable) | `dust` |
| Let me browse it and delete things | `gdu` (fast) or `ncdu` (classic) |
| What is on a server I only have ssh to? | `gdu -o- / \| gzip > scan.gz`, copy it back, `gdu -f scan.gz` |

`ncdu -f`/`gdu -f` reading a saved scan is the trick worth remembering: do the
expensive walk on the server, browse it on your laptop.
