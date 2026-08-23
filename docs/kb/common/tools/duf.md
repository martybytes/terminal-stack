# duf (modern df)

`df` with colour, alignment and sane units — mounted filesystems as a table you
can actually read at a glance.

| Command | What it does |
|---|---|
| `duf` | all mounts, grouped (local / network / special) |
| `duf --only local` | just real disks (`network`, `fuse`, `special` also work) |
| `duf --hide special` | drop tmpfs/devfs noise |
| `duf /` `duf ~` | only the filesystems backing these paths |
| `duf --sort size` | sort by size (`used`, `avail`, `usage`, `mountpoint`) |
| `duf --output mountpoint,size,used,avail,usage` | pick the columns |
| `duf --json` | machine-readable, for scripts |
| `duf --theme ansi` | plain ANSI colours when the truecolor theme looks wrong |

`duf` answers "which disk is full"; `dust`/`gdu`/`ncdu` answer "what filled it".
See `doc files-disk`.
