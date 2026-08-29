# ghostty (GPU-accelerated terminal)

Fast, GPU-accelerated terminal emulator with platform-native UI — a real macOS
window on macOS, GTK on Linux. Configured by this stack on macOS only.

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
| `tstack config ghostty status` | managed or not, version, and a live `+validate-config` |
| `tstack config ghostty diff` | what an apply would change |
| `tstack config ghostty off` | **revert**: restore your backup (or remove ours) and stop managing |
| `tstack config ghostty on` | manage it again |

**`off` is a real revert, not just "stop managing".** A config that was already
there when the stack first applied is preserved as `config.bak.YYYYMMDD[.N]` by
a `run_before` hook — `chezmoi apply` overwrites `$HOME` files with no backup on
POSIX, so without that hook a hand-written config would vanish silently. `off`
restores the newest backup; if there never was one, it removes ours and Ghostty
falls back to its own defaults.

### ssh, and why backspace breaks without this

Ghostty announces `TERM=xterm-ghostty`. `ssh` forwards `TERM` to the remote, and
a host whose terminfo database has no `xterm-ghostty` entry cannot resolve
`kbs` or `kdch1` — so **backspace inserts junk instead of erasing and Delete
does nothing**. Local panes are unaffected, which is what makes it puzzling.

The managed config fixes it with two shell-integration features:

    shell-integration-features = no-cursor,sudo,title,ssh-env,ssh-terminfo

`ssh-terminfo` uploads the real entry to each host on first connect (it needs
`tic` there) and keeps Ghostty's full capability set; `ssh-env` is the fallback
that sets `TERM=xterm-256color` where the upload cannot happen — a minimal
container, a read-only home, a jump host. Both are listed on purpose: either one
alone leaves a class of hosts broken.

Two things worth knowing:

- **`tstack config ghostty off` does not test this.** Stock Ghostty defaults to
  the same `TERM`, so turning the managed config off changes nothing and looks
  like the config is innocent.
- **Naming any value for `shell-integration-features` replaces the default set**,
  so both features have to be spelled out or they are off.

Useful commands:

| Command | What it does |
|---|---|
| `ghostty +ssh-cache` | list hosts whose terminfo is already installed |
| `ghostty +ssh-cache --clear` | forget them all (a reinstalled host needs this) |
| `infocmp -x xterm-ghostty \| ssh HOST -- tic -x -` | do it by hand, once, for one host |

If a remote still misbehaves, check `echo $TERM` there. `xterm-ghostty` means
the upload landed; `xterm-256color` means the fallback did. Either is fine —
`xterm-ghostty` *with* broken keys means the upload silently failed.

### Not on Windows

This stack configures Ghostty on **macOS only**. `tstack ghostty` says so on any
other platform rather than guessing at a path, and its native-Linux hosts are
headless anyway. There was briefly a Windows target, through the third-party
noctty build; it was removed. See `docs/decisions.md` § "Why the Windows Ghostty
target was dropped" — including the note that removing the code that wrote
`%LOCALAPPDATA%\ghostty\` does not delete files an earlier apply already put
there.

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
