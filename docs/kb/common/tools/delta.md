# delta (git diff pager)

Syntax-highlighted, word-level diff pager. You never call it — git does.

## How this stack wires it

The stack's gitconfig include (`~/.config/git/terminal-stack.gitconfig`, pulled
in from your `~/.gitconfig` via `include.path`) sets `core.pager` to a
**guarded** one-liner — `sh -c 'if command -v delta …; then delta; else
less -R; fi'` — so a machine without delta falls back to `less` instead of
erroring on every `git diff`. `interactive.diffFilter` gets the same guard
(falling back to `cat`) for `git add -p`. `[delta] navigate = true` turns on
`n`/`N` file jumping in the pager.

| Command | What it does |
|---|---|
| `git diff` / `git show` / `git log -p` | paged through delta automatically |
| `n` / `N` (in the pager) | jump to next / previous file |
| `git add -p` | hunk staging, delta-highlighted |
| `git -c delta.side-by-side=true diff` | side-by-side for one command |
| `git diff \| delta --side-by-side` | ditto, explicit |
| `git diff \| delta --line-numbers` | add line-number columns |
| `delta a.txt b.txt` | diff two arbitrary files |

To make side-by-side permanent, put `side-by-side = true` under `[delta]` in
your own `~/.gitconfig` — includes resolve first, so your file wins.
