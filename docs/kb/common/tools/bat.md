# bat (cat with wings)

`cat` with syntax highlighting, line numbers, git-change markers and automatic
paging. Reads files or stdin; drops decorations by itself when piped.

## How this stack wires it

- `ccat` = `bat --paging=never` in both shells — a highlighted `cat` that never
  opens a pager. It deliberately does **not** shadow `cat`/`Get-Content`: real
  `cat` stays predictable for scripts and pipes. The pwsh version warns instead
  of erroring when bat is missing.
- `doc` falls back to bat when glow is absent, and the `doc cmd` picker's
  preview is `bat --highlight-line` on the source topic.

| Command | What it does |
|---|---|
| `bat file` | view with syntax highlight + line numbers |
| `ccat file` | same, never paged |
| `bat -p file` | plain — no decorations, good for piping |
| `bat -r 10:20 file` | only lines 10–20 |
| `bat -A file` | reveal whitespace / non-printables |
| `bat -l yaml file` | force a language |
| `bat --diff file` | highlight only the lines changed vs git |
| `bat --style=numbers,changes file` | pick decorations à la carte |
| `cmd \| bat -l json` | highlight piped output |

In the pager: `j`/`k` or arrows scroll, `/` search, `q` quit.
