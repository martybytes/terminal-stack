# fd (friendly find)

`find` with defaults you would have chosen anyway: regex by default, colour,
parallel walking, and `.gitignore` respected.

## How this stack wires it

- **The WezTerm project picker needs it.** `Leader+p` (sessionizer) shells out to
  `fd` to list repos; without it the picker comes up empty.
- **Debian/Ubuntu name it `fdfind`** — the `fd` name was already taken by an
  unrelated package. The bootstrap installs `fd-find` and symlinks
  `~/.local/bin/fd -> /usr/bin/fdfind`, the same treatment `bat`/`batcat` gets.
  On macOS and Windows the binary is just `fd`.

| Command | What it does |
|---|---|
| `fd pattern` | regex search over names, from here down |
| `fd -g '*.log'` | glob instead of regex |
| `fd -e md -e txt` | filter by extension (repeatable) |
| `fd -t f` / `-t d` / `-t l` | files / directories / symlinks only |
| `fd -H` / `-I` | include hidden / ignore `.gitignore` |
| `fd -d 2 pattern` | cap the depth |
| `fd pattern ~/src` | search somewhere else |
| `fd -x rm {}` / `-X rm` | run a command per result / once with all results |
| `fd --changed-within 2d` | modified in the last two days |
| `fd -0 pattern \| xargs -0 ...` | NUL-separated, safe for odd filenames |

`rg --files -g pattern` does something similar; `fd` is the one to reach for when
you want paths rather than content. See `doc ripgrep`.
