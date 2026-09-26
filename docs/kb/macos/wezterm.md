# macOS — free the WezTerm keys first

macOS grabs the bare `F1`–`F6` keys before WezTerm sees them, and `Ctrl+Space`
too, so the directional pane keys (see `doc wezterm/panes`) look dead until you
flip the first toggle, and a `Ctrl+Space` leader until you flip the second. The
default leader, `Ctrl+\`, is not claimed by macOS and needs neither:

1. **F-row → real function keys.** System Settings → Keyboard → enable
   **"Use F1, F2, etc. keys as standard function keys"** (or hold **Fn** when pressing F1–F6).
2. **Free `Ctrl+Space`** (only if that is your leader). System Settings → Keyboard → Keyboard Shortcuts →
   **Input Sources** → uncheck **"Select the previous input source"** (that's the system's `Ctrl+Space`).

With a `Ctrl+Space` leader, until it is freed the leader `1`–`6` fallback for the
F-keys won't work either.

Keybindings themselves are identical across Windows/macOS/Linux — see
`doc wezterm/panes`, `doc wezterm/tabs`, `doc wezterm/workspace`.

Developing config: edit `dot_wezterm.lua.tmpl` / `dot_wezterm/pane_nav.lua`, then
`chezmoi apply -v` — see `doc wezterm/dev-config`.
