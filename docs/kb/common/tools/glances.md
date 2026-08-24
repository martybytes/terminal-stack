# glances (cross-platform monitor)

One monitor that runs everywhere Python does, and — unlike the others — can serve
its view over the network or a browser. Useful for headless boxes.

| Command | What it does |
|---|---|
| `glances` | start it |
| `glances -t 5` | 5-second refresh |
| `glances -1` | per-CPU-core view |
| `glances --disable-plugin docker,raid` | drop plugins you don't care about |
| `glances -w` | serve the web UI on `:61208` |
| `glances -s` | run as a server |
| `glances -c HOST` | connect to a `glances -s` server |
| `glances --export csv --export-csv-file out.csv` | log metrics to a file |
| `glances --stdout cpu.user,mem.used` | print selected metrics, for scripts |

Keys: `h` help, `1` per-core, `d` disk I/O, `n` network, `f` filesystems,
`c`/`m`/`i`/`t` sort by CPU/memory/IO/time, `q` quit.

Heavier than `btop`/`btm` (it is Python), so prefer those for a local terminal
and `glances -w`/`-s` for remote.

Being Python is also how it installs: brew on macOS, and on Windows through
`uv tool install glances` rather than winget, which has no glances package (the
`nicolargo.glances` id the stack used to carry does not exist). See
`doc node-python`.
