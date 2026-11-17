# Desktop agent apps (Herdr app, Orca, T3 Code)

GUI workspaces for running coding agents side by side. All three are optional,
never pre-ticked, and offered on macOS, Windows and desktop Linux — never on WSL
(a GUI app belongs on the Windows side) and never on a headless machine.

| id | What it is | Site |
|---|---|---|
| `herdr-app` | Herdr's native desktop app: terminals and agents in one window. Separate from the `herdr` TUI, and installs the `herdr-core` runtime it needs | <https://herdr.dev/download/> |
| `orca` | Orca by Stably: runs Claude Code, Codex, OpenCode and Pi in parallel, one git worktree each | <https://orca.dev> |
| `t3code` | T3 Code: a desktop GUI over the Codex and Claude Code CLIs | <https://github.com/pingdotgg/t3code> |

## Install / remove

Pick them in the wizard's **Desktop agent apps** step, or later:

```sh
tstack config apps            # tick them in the picker
```

How each one arrives:

| | macOS | Windows | Ubuntu / Debian | Arch / Omarchy |
|---|---|---|---|---|
| Herdr app | cask `herdr-app` (Apple Silicon only) | herdr.dev's `install.ps1` | herdr.dev's `install.sh` | herdr.dev's `install.sh` |
| Orca | cask `stablyai/orca/orca` (Stably's tap) | winget `StablyAI.Orca` | `.deb` from the latest GitHub release | AppImage + launcher entry |
| T3 Code | cask `t3-code` | winget `T3Tools.T3Code` | `.deb` from the latest GitHub release | AppImage + launcher entry |

- **A copy you installed yourself is left alone.** On macOS any `Herdr.app`,
  `Orca.app` or `T3 Code*.app` in `/Applications` or `~/Applications` counts;
  on Linux a launcher (`.desktop`) entry does. Nothing is ever reinstalled over.
- **Arch / Omarchy: no AUR helper is run.** All three are AUR-only there
  (`herdr-app`, `stably-orca-bin`, `t3code-bin`), and the stack never drives
  `yay`. You can still use those yourself instead; the stack will then see the
  launcher entry and leave it alone.
- **AppImages** live in `~/.local/share/terminal-stack/apps/<id>.AppImage`, with
  a launcher in `~/.local/share/applications/<id>.desktop`. Re-running
  `tstack config apps` replaces the image with the latest release, which is the
  update path. They need FUSE 2 (`sudo pacman -S fuse2`); without it, run the
  image with `--appimage-extract-and-run`.
- **Updates.** Orca and T3 Code update themselves; `brew upgrade --cask` and
  `winget upgrade` also work where they were installed that way.
- **Remove** with the tool that installed it: `brew uninstall --cask <cask>`,
  `winget uninstall --id <id>`, `sudo apt remove orca-ide` / `t3-code`, or
  delete the AppImage and its `.desktop` file.

## Gotchas

- `/usr/bin/orca` on most GNOME desktops is the **Orca screen reader**, not this
  app. The stack never treats it as the app being installed.
- The bare Homebrew cask `orca` is Plotly's unrelated image tool; the app is
  `stablyai/orca/orca`.
- The Herdr app has no Intel macOS build and no winget package (`Herdr.Herdr` is
  the TUI, `Herdr.HerdrCore` the runtime).
