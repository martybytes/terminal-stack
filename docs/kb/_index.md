# Knowledge base (`doc`)

Personal command runbooks, rendered by **glow**. Browse with the `doc` command:

**Something broken?** Start at `doc troubleshooting` — it is keyed by symptom, and
every row names the command that diagnoses it.

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

- `common/` — cross-OS (git, ssh, tmux, clipboard, the stack itself, workspace navigation and the `wso` organizer, SMB shares via `ts-smb`, troubleshooting, …)
- `common/services.md` + `common/{agentmemory,agentmemory-console,headroom,playwright}.md` — the local Docker services the memory, compression and voice features run on (`doc services`, `doc agentmemory`, …). Long-form reference lives beside each compose file in `services/stacks/<stack>/README.md`
- `common/tools/` — per-tool cheat-sheets (eza, fzf, bat, fd, tree, ripgrep, zoxide, atuin, yazi, delta, starship, chezmoi, micro, glow, neovim, zed, cursor, wezterm, ghostty, grok, gemini, pi, llmfit, node-python, tailscale, rclone, and disk/network monitors) — `doc eza`, `doc tailscale`, …
- `common/codex.md` / `common/claude-code.md` — AI coding-agent shortcuts and footer configuration (`doc codex`, `doc claude-code`); `common/tools/{grok,gemini}.md` cover the other two agents, and `common/tools/node-python.md` the runtimes they need
- `linux/` — apt, VeraCrypt, ssh permissions, systemd, docker (engine install + NVIDIA toolkit)
- `macos/` — Homebrew, macOS WezTerm toggles, Docker Desktop
- `windows/` — pwsh, winget, the TTS tray daemon, Docker Desktop
- `wezterm/` — WezTerm keybindings + dev workflow (all OSes)
- `_style/` — glamour style JSONs; dark/light follows your baked theme, `$DOC_STYLE` overrides

The viewer shows `common/` + `wezterm/` + your current OS by default; `doc --os`
browses another.

## Personal layer

Anything with real hostnames, key filenames, or server addresses goes in
`~/.doc.local/` (same folder layout, **never committed**). It's merged into every
listing automatically.
