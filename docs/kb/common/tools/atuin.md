# atuin (shell history)

Shell history in SQLite instead of a flat file: full-text search, no 100k-line
ceiling, and every shell shares one database. Replaces `Ctrl+R`.

## How this stack wires it

- **Opt-in, and asked.** The install questionnaire asks; `ts-config atuin on|off`
  changes it later. Default **off**.
- **It is a saved setting, not a presence check.** The atuin binary is often
  already installed and completely dormant — pulled in as a Homebrew dependency,
  or installed manually and never configured. A `command -v atuin` guard in
  `~/.zshrc` would therefore hijack `Ctrl+R` on the next `chezmoi apply` without
  anyone choosing it. The setting is `atuinEnabled` in chezmoi `[data]`.
- **The switch is a rendered fragment**, `~/.config/terminal-stack/atuin.zsh`,
  which `~/.zshrc` sources. When the setting is off that file is *empty*.
  `~/.zshrc` stays a non-template so `chezmoi re-add ~/.zshrc` keeps working.
- **zsh only.** `atuin init` supports zsh, bash, fish, nu and xonsh — there is
  **no PowerShell target**, and no winget package. On a Windows machine atuin
  lives in WSL. It is deliberately absent from the winget table rather than
  present and always failing.

## Keys

| Key | With atuin off | With atuin on |
|---|---|---|
| `Ctrl+R` | fzf history widget | **atuin search** |
| `Ctrl+T` | fzf file widget | unchanged |
| `Alt+C` | fzf cd widget | unchanged |
| `Up` | prefix search (oh-my-zsh) | unchanged — `--disable-up-arrow` |

Up-arrow is deliberately left alone: `up-line-or-beginning-search` is long-standing
muscle memory, and atuin taking it is the most-complained-about default.

## Secrets

`~/.zshrc` defines `zshaddhistory()`, which **discards** any command matching a
secret pattern so it never reaches `~/.zsh_history`. atuin does not use that
hook — it records through its own `preexec` — so without a matching filter every
secret the stack refuses to write to the history file would still land in
atuin's database.

`~/.config/atuin/config.toml` therefore carries a `history_filter` mirroring the
same regexes, plus atuin's own `secrets_filter`. **The two lists must say the
same thing**; if you change one, change the other. Verified: a command
containing `ANTHROPIC_API_KEY=sk-…`, a `Bearer` token or `--token=` is recorded
by neither store.

## Sync

Not configured. `auto_sync = false` and `update_check = false` — there is no
atuin account here, and updates come from brew / the GitHub-release fallback.
Everything stays on this machine.

| Command | What it does |
|---|---|
| `atuin search <text>` | search history from the command line |
| `atuin stats` | most-used commands |
| `atuin history list` | dump what is stored |
| `ts-config atuin on` / `off` | enable/disable the `Ctrl+R` integration |

See also `doc common/search-history`, `doc common/tools/fzf`.
