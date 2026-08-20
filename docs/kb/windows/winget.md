# Windows — winget

Windows' package manager, and how this stack installs its apps. The wizard and
`Set-TerminalStackConfig` (pwsh) / `ts-config apps` (from WSL) install the app
catalog via winget with the ids in `bootstrap/_config.ps1` — each install runs
`winget install --id <ID> --exact --silent` and may prompt for admin elevation.
Prerequisites (WezTerm, Nerd Font, Starship, chezmoi, Git) are always installed
and aren't in the catalog; tmux/tldr/nvtop/lazydocker are WSL/Linux-only.

## The catalog (winget ids)
| App | winget id | Set |
|---|---|---|
| `eza` | `eza-community.eza` | recommended |
| `fzf` | `junegunn.fzf` | recommended |
| `bat` | `sharkdp.bat` | recommended |
| `delta` | `dandavison.delta` | recommended |
| `ripgrep` | `BurntSushi.ripgrep.MSVC` | recommended |
| `zoxide` | `ajeetdsouza.zoxide` | recommended |
| `glow` | `charmbracelet.glow` | recommended |
| `micro` | `zyedidia.micro` | recommended |
| `neovim` | `Neovim.Neovim` | recommended |
| `gh` | `GitHub.cli` | recommended |
| `ghq` | `x-motemen.ghq` | recommended |
| `lazygit` | `JesseDuffield.lazygit` | recommended |
| `zed` | `Zed.Zed` | optional |
| `ffmpeg` | `Gyan.FFmpeg` | optional (ffplay for Claude TTS) |

## Daily commands
| Command | What it does |
|---|---|
| `winget search term` | find a package (`--source winget` skips the msstore noise) |
| `winget install --id Foo.Bar -e` | install by exact id (`-e` = `--exact`) |
| `winget list` | what's installed (any source) |
| `winget upgrade` | list available upgrades |
| `winget upgrade --all` | upgrade everything upgradable |
| `winget upgrade --id Foo.Bar` | upgrade just one |
| `winget pin add --id Foo.Bar` | hold a package out of `upgrade --all` |
| `winget uninstall --id Foo.Bar` | remove |

`ts-update` compares this catalog against what's on PATH after every pull and
offers to install anything the catalog gained — see `doc common/stack`.
