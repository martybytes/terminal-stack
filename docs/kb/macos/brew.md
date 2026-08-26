# macOS — Homebrew

The Mac package manager, and this stack's installer: `bootstrap/mac-bootstrap.sh`
installs Homebrew itself, then `brew install zsh git starship chezmoi`, your app
catalog picks (`delta` ships as the `git-delta` formula; Zed as a cask), and the
cask `font-jetbrains-mono-nerd-font` — plus WezTerm if you asked for it
(`--cask wezterm@nightly` or `--cask wezterm`, your pick) and Ghostty (`--cask ghostty`)
if you ticked them; `TS_TERMINALS=wezterm-nightly,ghostty|none` sets it non-interactively. `tstack config apps`
reuses the same brew path later.

## Daily commands
| Command | What it does |
|---|---|
| `brew update` | refresh the package index |
| `brew outdated` | what has a newer version (`--cask` for GUI apps) |
| `brew upgrade` | upgrade everything installed |
| `tstack config wezterm` | installed build + date, newest on each channel, what changed since — **use this instead of guessing** |
| `tstack config wezterm upgrade` | refresh the channel you are on (never switches) |
| `tstack config wezterm install nightly` | switch channel; removes the other cask first (they share `/Applications/WezTerm.app`) |
| `brew upgrade --cask ghostty` | upgrade Ghostty |
| `brew install formula` | install (`--cask` for GUI apps) |
| `brew uninstall formula` | remove |
| `brew cleanup` | remove old versions and stale downloads |
| `brew list` | what's installed (`--cask` for GUI apps) |
| `brew info formula` | version, deps, install status |
| `brew pin formula` | hold a formula out of `brew upgrade` |
| `brew doctor` | diagnose a broken brew setup |

## Services (launchd wrappers)
| Command | What it does |
|---|---|
| `brew services list` | what brew is running under launchd |
| `brew services start\|stop\|restart svc` | control a service (postgres, redis, …) |

## Bundles

`brew bundle dump` writes a `Brewfile` of everything installed; `brew bundle`
in a directory holding one installs the lot — the quickest way to mirror one
Mac's toolset onto another.
