# ghostty (GPU-accelerated terminal)

Fast, GPU-accelerated terminal emulator with platform-native UI — a real macOS
window on macOS, GTK on Linux. No Windows build.

## How this stack wires it

- **Offered at install, never forced.** The wizard's terminal-emulator tick-list
  offers WezTerm and Ghostty separately; anything already installed starts
  ticked, so a re-run upgrades rather than reinstalls. `TS_TERMINALS=ghostty`
  picks it non-interactively, `TS_TERMINALS=none` takes neither.
- **macOS:** installed and upgraded as the `ghostty` cask.
- **Linux:** upstream publishes no official Debian/Ubuntu repo, so the bootstrap
  points at <https://ghostty.org/download> rather than guessing at a
  third-party package.
- **No stack config.** Theme, leader chord and the tab bar are baked into
  `.wezterm.lua` by chezmoi and have no Ghostty equivalent here — under Ghostty
  you get the shell tooling (Starship, the `cc*`/`ws*`/`doc` commands, tmux)
  but not the stack's terminal theming. Configure it yourself in
  `~/.config/ghostty/config`.
- The `cc*` wrappers' tab titles use `wezterm cli set-tab-title`, which no-ops
  outside WezTerm — harmless here, but the Claude tab colouring is WezTerm-only.

| Command | What it does |
|---|---|
| `ghostty --version` | print the installed version |
| `brew upgrade --cask ghostty` | upgrade (macOS) |
| `ghostty +show-config` | dump the effective configuration |
| `ghostty +list-fonts` | fonts Ghostty can see (check JetBrainsMono Nerd Font is there) |
| `ghostty +list-themes` | built-in themes |
| `ghostty +list-keybinds` | current keybindings |

Config lives at `~/.config/ghostty/config` (macOS also reads
`~/Library/Application Support/com.mitchellh.ghostty/config`). It is **not**
managed by this stack — edit it freely, nothing here will overwrite it.
