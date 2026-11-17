# keymap: every keyboard shortcut on this PC

`tstack keys` (the script is `bootstrap/ts-keymap.ps1`) writes one CSV with every
keyboard shortcut it can find, and flags the ones that can never work because another
program has taken the key. It is the answer to "I press Ctrl+Shift+O and nothing
happens". The CSV is meant to be handed to Claude as is.

```powershell
tstack keys                                   # everything, to keymap-<PC>-<date>.csv
tstack keys -Chord ctrl+shift+o -Identify     # who holds Ctrl+Shift+O?
tstack keys -Identify -Force -OutFile k.csv   # everything, every owner named, no prompt
tstack keys -ConflictsOnly                    # only shortcuts that cannot work
tstack keys -Help                             # every option and collector
```

## What it reads

| Collector | Source |
|---|---|
| `probe` | every modifier + key combination, tried with `RegisterHotKey`: the ones that fail are held by another program |
| `windows` | the standard Windows 11 shortcuts (Win+V, Win+Shift+S, Alt+Tab, ...) |
| `shelllinks` | shortcut keys set on Start menu, Desktop and taskbar `.lnk` files |
| `powertoys` | every PowerToys module shortcut (marked when the module is off) and Keyboard Manager remaps |
| `wezterm` | `wezterm show-keys`: every key table and the leader |
| `windowsterminal` | Windows Terminal defaults and your `settings.json` |
| `editors` | your VS Code, Cursor, Windsurf, VSCodium and Zed keybindings (overrides only) |
| `herdr` | the herdr desktop app's `keys.json` and the TUI's `config.toml` |
| `claude` | `~/.claude/keybindings.json` |
| `psreadline` | the PowerShell line editor's handlers, with your profile loaded |
| `autohotkey` | hotkeys in any running AutoHotkey script |
| `wsl` | `tmux list-keys` and zsh `bindkey` inside WSL |
| `deepscan` | (`-DeepScan`) hotkey-like settings in any app's config under AppData |

Pick with `-Collect probe,herdr` or drop with `-Skip wsl`.

## Naming the program behind a global hotkey

Windows has no API that says who registered a hotkey. `RegisterHotKey` only fails with
error 1409, and `tstack doctor` uses exactly that to say "taken". `-Identify` goes
further: it installs a `WH_GETMESSAGE` hook (`bootstrap/hkspy`, a small Rust DLL built
once with `cargo` and cached in `%LOCALAPPDATA%\keymap`), presses each taken chord once,
and the hook records which process received the `WM_HOTKEY`. The hook also **swallows**
the message, so the owner does not act on the press.

Two kinds of owner are not intercepted, so their action runs and the row says
"not identified":

- a program running as administrator, when `tstack keys` is not elevated;
- a 32-bit program (the hook DLL is 64-bit).

Win+L, Ctrl+Alt+Delete, Ctrl+Shift+Esc and the graphics-reset chord are never pressed.

Without `-Identify`, a taken chord borrows its owner from a collector that declares it
(PowerToys, a `.lnk`, a Windows built-in) and says "inferred".

## Reading the CSV

Columns: `Chord, Scope, App, Context, Action, Owner, OwnerPid, Conflict, Source, Path, Notes`.

- **Chord** is canonical, `Ctrl+Alt+Shift+Win+Key`, so the same key from different apps
  lines up. A sequence is `Ctrl+B, C` (tmux prefix, VS Code chords).
- **Scope**: `Global hotkey` works everywhere, `App` only while that app has focus,
  `Shell`/`Terminal` inside PowerShell, zsh or tmux.
- **Conflict**:
  - `Never reaches <app>: held system-wide by <owner>`: the app's binding is dead,
    because Windows hands the key to the owner first.
  - On the global row: `swallows <app>: <action>` lists every binding it kills.
  - `bound twice here`: two actions on one key in the same app and context.

Found this way on 2026-11-17: AMD Software (`AMDRSServ.exe`) held Ctrl+Shift+O and
Ctrl+Shift+X, killing herdr's split and close-pane keys, and AltHMinimize held Alt+H,
killing herdr's `pane.go:left`.
