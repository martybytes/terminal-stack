# micro (terminal editor)

Nano's spiritual successor: GUI-style Ctrl bindings, full mouse support
(click to place the cursor, drag to select, wheel to scroll), no modes.

## How this stack wires it

- Default `$EDITOR` in both shells when installed — zsh falls back to `nano`,
  pwsh leaves `$env:EDITOR` unset without it. git, `chezmoi edit` and friends
  follow `$EDITOR`.
- `doc edit <topic>` and the doc picker's `alt-e` open topics in it
  (`$EDITOR` first, micro preferred, `vi`/`notepad` as the last resort).

| Key | What it does |
|---|---|
| `Ctrl-S` / `Ctrl-Q` | save / quit |
| `Ctrl-O` | open a file |
| `Ctrl-C` / `Ctrl-X` / `Ctrl-V` | copy / cut / paste (system clipboard) |
| `Ctrl-Z` / `Ctrl-Y` | undo / redo |
| `Ctrl-F` / `Ctrl-N` | find / find next |
| `Ctrl-D` | duplicate line |
| `Alt-N` / `Alt-P` | add a cursor at the next match / remove it (multicursor) |
| `Ctrl-E` | command bar — `> goto 42`, `> replace a b`, `> set …` |
| `Ctrl-B` | run a shell command |
| `Alt-,` / `Alt-.` | previous / next tab |
| `Ctrl-G` | help |

Useful `> set` options: `set tabsize 2`, `set softwrap on`, `set ruler off`.
Settings persist to `~/.config/micro/settings.json`; plugins install with
`micro -plugin install <name>`.
