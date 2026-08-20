# Knowledge base (`doc`)

Personal command runbooks, rendered by **glow**. Browse with the `doc` command:

| Command | Does |
|---|---|
| `doc` | fuzzy-find a topic (live glow preview) → open in the reader |
| `doc <topic>` | open a topic directly, e.g. `doc veracrypt`, `doc ssh-keys` |
| `doc -g <pattern>` | grep across every topic (paged) |
| `doc cmd [pattern]` | find a single command and drop it on your prompt to run |
| `doc tui [local]` | glow's tree browser (`local` = `~/.doc.local`) |
| `doc edit <topic>` / `doc new <os>/<name>` | edit / scaffold a topic |
| `doc ls` / `doc --os <linux\|macos\|windows>` | list topics / browse another OS |
| `doc sync` | commit your doc edits back to the repo (+ changelog, optional push) |

Picker keys: `ctrl-u`/`ctrl-d` scroll the preview, `ctrl-/` toggles it, `alt-e`
edits the highlighted topic. The reader is `less`: `/pattern` searches, `q` quits.

## Layout

- `common/` — cross-OS (git, ssh, tmux, clipboard, the stack itself, workspace navigation and the `wso` organizer, …)
- `common/tools/` — per-tool cheat-sheets (eza, fzf, bat, ripgrep, zoxide, delta, starship, chezmoi, micro, glow, neovim, zed, cursor) — `doc eza`, `doc nvim`, …
- `linux/` — apt, VeraCrypt, ssh permissions, systemd, docker
- `macos/` — Homebrew, macOS WezTerm toggles
- `windows/` — pwsh, winget
- `wezterm/` — WezTerm keybindings + dev workflow (all OSes)
- `_style/` — glamour style JSONs; dark/light follows your baked theme, `$DOC_STYLE` overrides

The viewer shows `common/` + `wezterm/` + your current OS by default; `doc --os`
browses another.

## Personal layer

Anything with real hostnames, key filenames, or server addresses goes in
`~/.doc.local/` (same folder layout, **never committed**). It's merged into every
listing automatically.
