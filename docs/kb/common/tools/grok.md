# grok (xAI Grok CLI)

xAI's coding agent in the terminal. Ships as a **standalone binary**, so unlike
`codex` and `gemini` it needs no Node at all.

## How this stack wires it

- **Installed from xAI's own installer** (`x.ai/cli/install.sh`), as part of the
  `ai` group in the install questionnaire. Every agent CLI is pre-ticked but
  still asked; untick it and nothing happens.
- **Routed to `~/.local/bin`.** The upstream installer defaults to `~/.grok/bin`
  and *appends a PATH line to `~/.zshrc`* — a file this stack owns whole-file, so
  the next `chezmoi apply` would silently delete it. `GROK_BIN_DIR` points the
  symlink at a directory already on PATH and sidesteps that; `dot_zshrc` carries
  the completions `fpath` itself.
- **`agent` is ambiguous.** Grok's installer also creates `~/.local/bin/agent` —
  and so does cursor-agent's, so whichever ran last owns that name. Use `grok`.

| Command | What it does |
|---|---|
| `grok` | interactive TUI in the current directory |
| `grok -p "explain this codebase"` | one-shot prompt, prints and exits |
| `grok --version` | build and commit |
| `grok completions zsh` | regenerate shell completions |
| `grok update` | self-update in place (preferred over re-running the installer) |
| `curl -fsSL https://x.ai/cli/install.sh \| bash` | reinstall (Windows: `irm https://x.ai/cli/install.ps1 \| iex`) |

First launch opens a browser to authenticate. For headless or CI use, put an API
key from `console.x.ai` in **`XAI_API_KEY`** instead. Config lives in
`~/.grok/config.toml`; the versioned binaries in `~/.grok/downloads`.

See also `doc claude-code`, `doc codex`, `doc gemini`, `doc cursor`.
