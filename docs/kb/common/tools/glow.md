# glow (markdown renderer)

Terminal markdown renderer (charmbracelet's glamour engine). In this stack it
is mainly the engine behind `doc` — you rarely run it bare.

## How this stack wires it

- `doc <topic>` renders with `glow -s <style> -w <width> | less -RF`: an
  explicit width (terminal width − 2, capped at 100) and a pager that searches
  with `/` and prints short topics straight through. Picker previews render at
  the fzf pane's real width via `FZF_PREVIEW_COLUMNS`.
- **Shipped styles.** glow builds (and their bundled themes) differ per
  platform, so the repo ships glamour style JSONs at
  `docs/kb/_style/{dark,light}.json` — they ride the same mirror sync as the
  topics, and the same markdown renders identically everywhere. `doc` picks
  the one matching your saved `resolvedTheme`; override with
  `DOC_STYLE=dark|light|/path/to/style.json` (`$env:DOC_STYLE` in pwsh).
- `doc tui` / `doc tui local` open glow's tree browser over the tracked kb /
  `~/.doc.local`.

| Command | What it does |
|---|---|
| `glow file.md` | render a file |
| `glow -p file.md` | render in glow's own pager |
| `glow .` | TUI browser of markdown under cwd |
| `glow -s style.json file.md` | render with a specific glamour style |
| `glow -w 100 file.md` | wrap at 100 columns |
| `glow https://…/README.md` | render a remote markdown URL |

In the TUI: arrows / `j`/`k` scroll, `/` filter, `e` edit, `q` quit.
