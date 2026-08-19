# Knowledge base (`doc`)

Personal command runbooks, rendered by **glow**. Browse with the `doc` command:

| Command | Does |
|---|---|
| `doc` | fuzzy-find a topic (live glow preview) → open in pager |
| `doc <topic>` | open a topic directly, e.g. `doc veracrypt`, `doc ssh-keys` |
| `doc -g <pattern>` | grep across every topic, jump to the match |
| `doc cmd [pattern]` | find a single command and drop it on your prompt to run |
| `doc tui` | glow's built-in tree browser |
| `doc edit <topic>` / `doc new <os>/<name>` | edit / scaffold a topic |
| `doc ls` | list topics for this OS + common |
| `doc sync` | commit your doc edits back to the repo (+ changelog, optional push) |

## Layout

- `common/` — cross-OS (git, ssh keys/config, tmux, copying files between servers, workspace navigation and the `wso` organizer, …)
- `common/tools/` — per-tool cheat-sheets (eza, fzf, bat, ripgrep, zoxide, delta, starship, chezmoi, micro, glow, neovim, zed) — `doc eza`, `doc nvim`, …
- `linux/` — apt, VeraCrypt, ssh permissions, systemd, docker
- `macos/` — Homebrew, macOS WezTerm toggles
- `windows/` — winget, PowerShell
- `wezterm/` — WezTerm keybindings + dev workflow (all OSes)

The viewer shows `common/` + `wezterm/` + your current OS by default; `doc --os <linux|macos|windows>` browses another.

## Personal layer

Anything with real hostnames, key filenames, or server addresses goes in `~/.doc.local/` (same folder layout, **never committed**). It's merged into every listing automatically. See `~/.doc.local/` on this machine for the personalized copies.
