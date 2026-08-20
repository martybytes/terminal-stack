# macOS — Homebrew

The Mac package manager, and this stack's installer: `bootstrap/mac-bootstrap.sh`
installs Homebrew itself, then `brew install zsh git starship chezmoi`, your app
catalog picks (`delta` ships as the `git-delta` formula; Zed as a cask), and the
cask `font-jetbrains-mono-nerd-font` — plus WezTerm if you asked for it
(`wezterm@nightly` by default, `wezterm` for stable, or skipped; `TS_WEZTERM=`
sets it non-interactively, and a nightly that won't install falls back to stable). `ts-config apps`
reuses the same brew path later.

## Daily commands
| Command | What it does |
|---|---|
| `brew update` | refresh the package index |
| `brew outdated` | what has a newer version (`--cask` for GUI apps) |
| `brew upgrade` | upgrade everything installed |
| `brew upgrade --cask wezterm@nightly` | upgrade WezTerm (nightly is the default — the plain `wezterm` cask is stale, but supported) |
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
