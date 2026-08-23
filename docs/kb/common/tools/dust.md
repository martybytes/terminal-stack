# dust (du with a tree)

`du` that prints a sorted, indented tree with bars, and needs no flags to be
useful. Non-interactive — good for "what is big here" in one shot, and for
pasting into a ticket.

| Command | What it does |
|---|---|
| `dust` | biggest subdirectories of the current directory |
| `dust ~/src` | somewhere else |
| `dust -d 2` | limit depth |
| `dust -n 40` | show 40 entries instead of the default |
| `dust -r` | reverse — biggest last |
| `dust -f` | count files rather than bytes |
| `dust -X .git` | exclude a directory (repeatable) |
| `dust -s` | follow symlinks |
| `dust -p` | full paths instead of the tree indent |

`ncdu`/`gdu` when you want to browse and delete; `duf` for free space per mount.
See `doc files-disk`.
