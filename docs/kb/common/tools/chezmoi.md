# chezmoi (dotfile manager)

Applies this repo to `$HOME`. On Windows, run it from **inside WSL**.

| Command | What |
|---|---|
| `chezmoi diff` | preview pending changes |
| `chezmoi apply -v` | apply (runs the windows-sync hook at the end) |
| `chezmoi re-add ~/.zshrc` | capture a hand-edit of a managed file back to source |
| `chezmoi source-path` | print the clone path |
| `chezmoi managed` | list every managed target |
| `chezmoi edit <target>` | edit a target's source |
| `chezmoi cd` | shell into the source dir |
| `chezmoi init` | regenerate config after the template changes |

Stack wrappers: `ts-update` (pull + apply), `ts-rollback` (undo) — see `doc common/stack`.

WezTerm dev (macOS): `chezmoi apply -v ~/.wezterm.lua ~/.wezterm/pane_nav.lua` — see `doc wezterm/dev-config`.
