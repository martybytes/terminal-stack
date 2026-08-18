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
| `df -h` | disk free, human-readable |
| `du -sh *` | size of each item in the current dir |

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
