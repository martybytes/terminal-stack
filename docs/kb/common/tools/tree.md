# tree (directory structure)

Prints a directory as an indented tree. The stack's `lt` alias uses
`eza --tree` for day-to-day listing, but plain `tree` is still the one for
pasting a layout into a README or an issue.

| Command | What it does |
|---|---|
| `tree` | the tree from here down |
| `tree -L 2` | limit the depth |
| `tree -d` | directories only |
| `tree -a` | include hidden entries |
| `tree -I 'node_modules\|.git'` | ignore a pattern (`\|`-separated) |
| `tree --gitignore` | honour `.gitignore` (tree 2.x) |
| `tree -h --du` | sizes, with directory totals |
| `tree -F` | classify: `/` dirs, `*` executables, `@` symlinks |
| `tree -C \| less -R` | keep the colours through a pager |
| `tree -J` / `-X` | JSON / XML output |

`lt` (= `eza --tree --icons --git`) is the nicer interactive view; `tree -L 2 -I
'node_modules\|.git'` is the one worth memorising for documentation.
