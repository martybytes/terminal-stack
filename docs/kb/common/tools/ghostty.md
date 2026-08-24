# ghostty (GPU-accelerated terminal)

Fast, GPU-accelerated terminal emulator with platform-native UI — a real macOS
window on macOS, GTK on Linux. No Windows build.

## How this stack wires it

- **Offered at install, never forced.** The wizard's terminal-emulator tick-list
  offers WezTerm and Ghostty separately; anything already installed starts
  ticked, so a re-run upgrades rather than reinstalls. `TS_TERMINALS=ghostty`
  picks it non-interactively, `TS_TERMINALS=none` takes neither.
- **macOS:** installed and upgraded as the `ghostty` cask. The managed config
  sets `auto-update = off` so Homebrew stays the only updater — two updaters
  fighting over `/Applications` is how you get a half-replaced app bundle.
- **Linux:** upstream publishes no official Debian/Ubuntu repo, so the bootstrap
  points at <https://ghostty.org/download> rather than guessing at a
  third-party package. The config is **macOS-only** (Linux hosts here are
  headless), gated in `.chezmoiignore` alongside `.wezterm.lua`.

## The managed config

`~/.config/ghostty/config` **is** managed now, and so is
`~/.config/ghostty/themes/vs-code-light-modern`. Edit the source in the clone
(`dot_config/ghostty/config.tmpl`), not the deployed file — `chezmoi apply`
overwrites it.

| Command | What it does |
|---|---|
| `ts-config ghostty status` | managed or not, version, and a live `+validate-config` |
| `ts-config ghostty diff` | what an apply would change |
| `ts-config ghostty off` | **revert**: restore your backup (or remove ours) and stop managing |
| `ts-config ghostty on` | manage it again |

**`off` is a real revert, not just "stop managing".** A config that was already
there when the stack first applied is preserved as `config.bak.YYYYMMDD[.N]` by
a `run_before` hook — `chezmoi apply` overwrites `$HOME` files with no backup on
POSIX, so without that hook a hand-written config would vanish silently. `off`
restores the newest backup; if there never was one, it removes ours and Ghostty
falls back to its own defaults.

### Windows: noctty (still shipping as winghostty)

There *is* a Ghostty for Windows — not from upstream, but
[noctty](https://github.com/amanthanvi/noctty): Ghostty's terminal core wrapped
in a native Win32 app, with tabs, splits, session restore and a command palette.
The project was renamed from **WingHostty** in main on 2026-08-20 after a
trademark request, but that landed *after* the v1.3.123 tag, so the release
assets are still `winghostty-<ver>-windows-x64-setup.exe`. Install it with
`winget install AmanThanvi.winghostty` or from the releases page — the stack
offers it in the terminal question but never installs it, exactly like the
WezTerm channels.

The managed config lands at **`%LOCALAPPDATA%\ghostty\config`**, with the custom
light theme beside it in `themes\`. That is the *upstream* path, and the choice
is deliberate: noctty reads both that and its own
`%LOCALAPPDATA%\<appname>\config.ghostty`, and `<appname>` is `winghostty`
today and `noctty` the day the rename ships — so the app-named path would
silently stop being read on upgrade day.

`ts-config ghostty` works on Windows and from WSL (where it drives the
Windows-side copy over `/mnt/c/`). Two differences from macOS worth knowing:

- **There is no working syntax gate.** `+validate-config` fails with
  `FileTooBig` on 1.3.123 even for a 14-byte config, and `+show-config` reports
  *nothing* for an unknown key or a bad value. `status` says
  `validate: unavailable on this build` rather than claiming a check it did not
  run.
- **A few macOS directives are dropped**, not carried: `macos-option-as-alt`
  (absent from the Windows option set — silently ignored, not diagnosed),
  `font-thicken` and `window-colorspace` (macOS rendering), and the `cmd+…`
  readline chords (no Cmd key; `Home`/`End`/`Ctrl+U` are the natives). Windows
  gains `window-theme`, which drives the DWM title bar.

### What it sets

- **Theme** tracks the stack's `themeMode`. Ghostty's `dark:…,light:…` syntax
  follows the OS *itself*, so `follow` switches live with no re-apply — the same
  class as WezTerm, unlike Starship and tmux which bake a palette at apply time.
  Catppuccin Mocha is a Ghostty builtin; VS Code Light Modern is not, so the
  stack ships it, generated from the same hexes as WezTerm's `PALETTES.light`
  (a test pins them together).
- **Font**: JetBrainsMono Nerd Font at 11.5, matching WezTerm exactly.
- **Keys**: `macos-option-as-alt` (the important one — without it Alt never
  reaches tmux, vim or readline), plus Cmd+←/→/Backspace readline motions.
  `cmd+t`/`w`/`d` are deliberately left on Ghostty's own tab and split actions:
  this stack multiplexes *inside* the terminal with WezTerm and tmux, so there
  is no host multiplexer to forward them to.
- **No global quick-terminal key**: `Cmd+\`` remains the standard macOS
  “cycle windows in the active application” shortcut. A global Ghostty binding
  would intercept that system convention even while another app is active.
- **Behaviour**: copy-on-select, paste protection, and a 10000-line scrollback
  matching WezTerm's.

### Tab titles, and the one thing Ghostty still can't do

- **No stack tab bar.** The Claude pane tints, the fleet counters and the status
  line are `.wezterm.lua` Lua, and Ghostty has no equivalent.
- **The tab shows the project name.** The `cc*` wrappers set it, and Claude
  Code is told not to overwrite it (`CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1`) —
  without that pair Claude replaces it with `✳ Claude Code` and then its
  conversation slug, which is what used to happen here. `ccs` goes through tmux
  instead, where tmux owns the title and substitutes the session name.

  Worth knowing if you ever change this: Ghostty *does* have a sticky per-tab
  title (`set_tab_title`, distinct from `set_surface_title`) and a title set
  that way genuinely survives Claude. It is just unreachable from a script —
  there is no CLI to drive a running instance (`ghostty +new-window` reports
  *"not supported on this platform"*) and no escape sequence maps to it;
  ConEmu's `OSC 9;3` sets the *surface* title, tested. So the stack uses plain
  `OSC 2` and removes the thing that was overwriting it, rather than fighting
  for a sticky title it cannot reach. WezTerm still uses
  `wezterm cli set-tab-title`, which is a real override.

| Command | What it does |
|---|---|
| `ghostty --version` | print the installed version |
| `brew upgrade --cask ghostty` | upgrade (macOS) |
| `ghostty +show-config` | dump the effective configuration |
| `ghostty +validate-config` | check a config; **exits 1** on error, unlike WezTerm's `show-keys` |
| `ghostty +list-fonts` | fonts Ghostty can see |
| `ghostty +list-themes` | built-in themes |
| `ghostty +list-keybinds` | current keybindings |
| `Cmd+Shift+,` | reload the config in place |

Ghostty's config syntax has **no inline comments** — a `#` after a value becomes
part of the value. macOS also reads
`~/Library/Application Support/com.mitchellh.ghostty/config`, but the XDG path
above wins and is the one this stack manages.
