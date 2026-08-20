# macOS — free the WezTerm keys first

macOS grabs both `Ctrl+Space` and the bare `F1`–`F6` keys before WezTerm sees
them, so the leader and the directional pane keys (see `doc wezterm/panes`) look
dead until you flip two toggles:

1. **F-row → real function keys.** System Settings → Keyboard → enable
   **"Use F1, F2, etc. keys as standard function keys"** (or hold **Fn** when pressing F1–F6).
2. **Free `Ctrl+Space`.** System Settings → Keyboard → Keyboard Shortcuts →
   **Input Sources** → uncheck **"Select the previous input source"** (that's the system's `Ctrl+Space`).

Until `Ctrl+Space` is freed, the `Ctrl+Space 1`–`6` fallback for the F-keys won't work either.

Keybindings themselves are identical across Windows/macOS/Linux — see
`doc wezterm/panes`, `doc wezterm/tabs`, `doc wezterm/workspace`.

Developing config: edit `dot_wezterm.lua.tmpl` / `dot_wezterm/pane_nav.lua`, then
`chezmoi apply -v` — see `doc wezterm/dev-config`.
