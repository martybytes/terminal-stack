# Windows — winget

Windows' package manager, and how this stack installs its apps. The wizard and
`Set-TerminalStackConfig` (pwsh) / `ts-config apps` (from WSL) install the app
catalog via winget with the ids in `bootstrap/_config.ps1` — each install runs
`winget install --id <ID> --exact --silent` and may prompt for admin elevation.
Prerequisites (Nerd Font, Starship, chezmoi, Git) are always installed and aren't
in the catalog; tmux/tldr/nvtop/lazydocker are WSL/Linux-only.

**WezTerm is a wizard question, not a prerequisite** — tick `wez.wezterm.nightly`
or `wez.wezterm`, or leave both unticked and keep using Windows Terminal or an
existing install. Nightly is pre-selected on every machine, including one that already has stable,
because upstream's newest stable is `20240203`
(February 2024, no cut since). Switching channel uninstalls the other package
first — they install to the same place. `ts-config wezterm` shows your build and
its date, the newest on each channel, and what changed in between; nothing
upgrades on its own. Note nightly's manifest is republished more often than its
hash is refreshed, so `Installer hash does not match` is a routine outcome — the
failure is reported rather than hidden. Ghostty has no Windows build, so it is
offered on macOS/Linux only. Every
package that failed is reprinted at the end of the run with the command to retry
it, so a failure can't scroll past unnoticed.

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
| `prettymark` | `Eagle1.PrettyMark` | recommended (markdown viewer, `pm` alias) |
| `fd` | `sharkdp.fd` | recommended (the WezTerm project picker needs it) |
| `duf` | `muesli.duf` | recommended (disk free) |
| `dust` | `bootandy.dust` | recommended (disk usage) |
| `btop` | `aristocratos.btop4win` | recommended (resource monitor) |
| `zed` | `ZedIndustries.Zed` | optional |
| `gdu` | `dundee.gdu` | optional (fast disk-usage TUI) |
| `bottom` | `Clement.bottom` | optional (binary is `btm`) |
| `glances` | `nicolargo.glances` | optional |
| `gping` | `orf.gping` | optional |
| `claude` `codex` `cursor-agent` `grok` `gemini` | — | the **`ai` group** — pre-ticked but always asked, and not winget packages (see below) |

Also on Windows: `fnm` (`Schniz.fnm`), `node` (`OpenJS.NodeJS`), `python`
(`Python.Python.3.13`), `uv`, `pipx`, `ruff` and `poetry` — the `runtimes` and
`python` groups.

**Not available on Windows** — `ncdu`, `bandwhich` and `tree` have no reliable
winget id (bandwhich has no Windows build at all), and `tmux`, `tldr`, `nvtop`
and `lazydocker` are WSL/Linux-only. They are absent from the winget table
rather than mapped to something that always fails, so `ts-update` never nags
about them here.

**The `ai` group installs differently.** None of the five come from winget, so
they route through `Install-TsAiCli` instead: **claude** and **grok** via their
own official installers (`irm https://claude.ai/install.ps1 | iex` and
`irm https://x.ai/cli/install.ps1 | iex` — grok ships a standalone binary, so it
needs no Node), **codex** via npm `@openai/codex` (Node 16+) and **gemini** via
npm `@google/gemini-cli` (Node 20+). The npm ones are gated on the Node version
and say what to do rather than failing — install `fnm` from the `runtimes` group
and they work. There is deliberately no winget/brew fallback for gemini: that
formula is deprecated upstream. **cursor-agent** has no Windows installer this
stack can call; install it inside WSL.

The group is pre-ticked (default to all) but always asked, and every CLI in it
stays individually untickable.

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
PrettyMark is the one entry whose winget install doesn't land on `PATH`; its
presence check falls back to the fixed `C:\Program Files\PrettyMark\PrettyMark.exe`
path instead (same one the `pm` alias resolves).
