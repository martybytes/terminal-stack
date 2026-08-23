# ncdu (interactive disk usage)

The classic TUI disk-usage analyser: scan a tree once, then browse it sorted by
size and delete from inside the viewer.

| Command | What it does |
|---|---|
| `ncdu` | scan the current directory |
| `ncdu /` | scan from root (slow; add `-x`) |
| `ncdu -x /` | stay on one filesystem — skips `/proc`, network mounts, other disks |
| `ncdu --exclude .git ~/src` | skip a pattern while scanning |
| `ncdu -o scan.json /` | write the scan to a file (fast, no UI) |
| `ncdu -f scan.json` | browse a saved scan — the way to analyse a server from your laptop |

Keys: `↑`/`↓` move, `→`/`Enter` descend, `←` up, `d` delete, `n`/`s`/`C` sort by
name/size/items, `g` toggle percentage/graph, `i` file info, `q` quit.

`gdu` is a much faster alternative with the same idea; `dust` is the
non-interactive one. See `doc files-disk`.
