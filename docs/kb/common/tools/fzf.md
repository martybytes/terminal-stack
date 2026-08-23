# fzf (fuzzy finder)

General-purpose fuzzy filter: feed it lines, type a few characters, pick one.
Every interactive picker in this stack is fzf underneath.

## How this stack wires it

- **zsh**: the rc sources `fzf --zsh` (fzf ≥ 0.48; older builds silently
  no-op), which binds `Ctrl-R` fuzzy history, `Ctrl-T` insert-a-file, and
  `Alt-C` cd-to-subdirectory.
- **pwsh**: no key bindings — `Ctrl+R` there is PSReadLine's own history
  search. fzf is used programmatically by the pickers instead.
- Pickers built on it (both shells): `doc` (topic finder), `doc cmd` (command
  finder), `wsj` (repo jump), `wso unarchive`, zoxide's `zi`.
- The `doc`/`doc cmd` pickers bind `ctrl-u`/`ctrl-d` (scroll the preview),
  `ctrl-/` (toggle the preview), and `alt-e` (open the topic in `$EDITOR`).

## The `Ctrl-T` workflow

`Ctrl-T` inserts a **path** into the command line rather than launching
anything, so it composes with whatever you have already typed:

```
v <Ctrl-T>            # then fuzzy-type "volks cal", Enter
→ v 'notes/cars/Volkswagen California.md'
```

`v` is the stack's alias for `nvim`. The same works for any command —
`cat`, `less`, `cp`, `rm`, `nvim`. Paths containing spaces come back
shell-quoted, so they survive as a single argument.

## Query syntax (works in every picker)

| Pattern | Matches |
|---|---|
| `term` | fuzzy — letters in order, anywhere |
| `'term` | exact substring |
| `^term` / `term$` | prefix / suffix (e.g. `.md$`) |
| `!term` | negate |
| `a b` | space = AND — `'src .go$ !test` |

| Usage | What it does |
|---|---|
| `cmd \| fzf` | pick a line from any output |
| `fzf -m` | multi-select — Tab marks, Enter takes all |
| `fzf -q 'foo'` | start pre-filtered |
| `fzf --preview 'bat --color=always {}'` | preview pane |
| `nvim $(fzf)` | open a fuzzy-picked file |

Inside: type to filter, arrows or `Ctrl-J`/`Ctrl-K` move, Enter select,
Esc cancel.
