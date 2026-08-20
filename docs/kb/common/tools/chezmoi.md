# chezmoi (dotfile manager)

Keeps dotfiles in a git "source tree" and renders them into `$HOME`. This repo
**is** a chezmoi source tree — "running" the stack means `chezmoi apply`.

## How this stack wires it

- **Always apply from inside WSL** (or native Linux/macOS), never from Windows:
  the `run_after_90-sync-windows.sh` hook needs a POSIX shell and `/mnt/c/`.
- **`chezmoi diff` only shows WSL-side targets.** Windows files live under
  `windows/**` (chezmoi-ignored) and are mirrored by the run_after hook, so the
  diff never shows them — compare manually, or apply and read the
  `created`/`updated` lines.
- `sourceDir` points at the **canonical runtime clone**:
  `%LOCALAPPDATA%\terminal-stack\stack` on Windows + WSL (WSL path
  `/mnt/c/Users/<you>/AppData/Local/terminal-stack/stack`),
  `~/.local/share/terminal-stack` on native Linux/macOS. Dev clones at workspace
  tier paths are invisible unless pinned — see `doc common/stack`.
- Wizard choices (leader, theme, tmux prefix, Windows username) live under
  `[data]` in `~/.config/chezmoi/chezmoi.toml`, mirrored to
  `%LOCALAPPDATA%\terminal-stack\config.json` for Windows-standalone.
- Edit the `.tmpl` source, not the rendered file — the next apply overwrites it.

| Command | What it does |
|---|---|
| `chezmoi diff` | preview pending WSL-side changes |
| `chezmoi apply -v` | apply; runs the Windows-sync hook at the end |
| `chezmoi re-add ~/.zshrc` | capture a hand-edit of a managed target back to source |
| `chezmoi source-path` | print the clone path |
| `chezmoi managed` | list every managed target |
| `chezmoi edit <target>` | edit a target's source (`.tmpl`-aware) |
| `chezmoi cd` | shell into the source dir |
| `chezmoi init` | re-render the config after `.chezmoi.toml.tmpl` changes |

Day to day you rarely call it directly: `ts-update` (pull + re-apply) and
`ts-rollback` (undo the last update) wrap it — see `doc common/stack`.

WezTerm dev on macOS: `chezmoi apply -v ~/.wezterm.lua ~/.wezterm/pane_nav.lua`
— see `doc wezterm/dev-config`.
