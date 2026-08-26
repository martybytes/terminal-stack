# Windows — winget

Windows' package manager, and how this stack installs its apps. The wizard and
`Set-TerminalStackConfig` (pwsh) / `tstack config apps` (from WSL) install the app
catalog via winget with the ids in `bootstrap/_config.ps1` — each install runs
`winget install --id <ID> --exact --silent` and may prompt for admin elevation.
Prerequisites (Nerd Font, Starship, chezmoi, Git) are always installed and aren't
in the catalog; tmux/tldr/nvtop/lazydocker are WSL/Linux-only.

**WezTerm is a wizard question, not a prerequisite** — tick `wez.wezterm.nightly`
or `wez.wezterm`, or leave both unticked and keep using Windows Terminal or an
existing install. Nightly is pre-selected on every machine, including one that already has stable,
because upstream's newest stable is `20240203`
(February 2024, no cut since). Switching channel uninstalls the other package
first — they install to the same place. `tstack config wezterm` shows your build and
its date, the newest on each channel, and what changed in between; nothing
upgrades on its own. Note nightly's manifest is republished more often than its
hash is refreshed, so `Installer hash does not match` is a routine outcome — the
failure is reported rather than hidden. Ghostty is offered here too — as
[noctty](https://github.com/amanthanvi/noctty), which still ships its release
assets under the former name winghostty (`AmanThanvi.winghostty`) — but like the
WezTerm channels it is asked, never installed for you, so it has no entry in the
terminal winget table. Every
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
| `gping` | `orf.gping` | optional |
| `claude` `codex` `cursor-agent` `grok` `gemini` `pi` | — | the **`ai` group** — pre-ticked but always asked, and not winget packages (see below) |

Also on Windows: `fnm` (`Schniz.fnm`), `node` (`OpenJS.NodeJS`), `python`
(`Python.Python.3.13`), `uv` (`astral-sh.uv`) and `ruff` (`astral-sh.ruff`) —
the `runtimes` group and the compiled half of `python`.

**The rest of the `python` group does not come from winget.** `pipx`, `poetry`,
`glances`, `ipython`, `httpie` and `pre-commit` have no winget manifest, so they
route through `Install-TsPyTool`: `uv tool install <name>` when uv is present
(it is in the recommended set, and its shims land on PATH), falling back to
`py -m pip install --user <name>`.

Three of them — `pypa.pipx`, `Python-Poetry.Poetry` and `nicolargo.glances` —
*were* in the winget table and none of the three ids exists. `pipx` is
recommended, so every Windows machine was offered it on every `tstack update` and
winget answered "No package found matching input criteria" every time. Check a
new id resolves (`winget show --id <id> --exact`) before adding it here.

**Not available on Windows** — `ncdu`, `bandwhich` and `tree` have no reliable
winget id (bandwhich has no Windows build at all), `atuin` has no winget
manifest *and* no PowerShell `atuin init` target, and `tmux`, `tldr`, `nvtop`
and `lazydocker` are WSL/Linux-only. They are absent from the winget table
rather than mapped to something that always fails, so `tstack update` never nags
about them here.

What `tstack update` offers is decided by `Test-TsAppInstallable`, which means *"can
this platform install it"*, not *"is it in winget"* — winget ids, the `ai` group
and the Python group all qualify. It used to be a bare winget lookup, so a
machine missing `grok`, `gemini`, `pi` or `cursor-agent` was never told.

**The `ai` group installs differently.** None of the five come from winget, so
they route through `Install-TsAiCli` instead: **claude** and **grok** via their
own official installers (`irm https://claude.ai/install.ps1 | iex` and
`irm https://x.ai/cli/install.ps1 | iex` — grok ships a standalone binary, so it
needs no Node), **codex** via npm `@openai/codex` (Node 16+) and **gemini** via
npm `@google/gemini-cli` (Node 20+). The npm ones are gated on the Node version
and say what to do rather than failing — install `fnm` from the `runtimes` group
and they work. There is deliberately no winget/brew fallback for gemini: that
formula is deprecated upstream. **cursor-agent** installs from the same URL as
POSIX with `?win32=true`, which serves a PowerShell script rather than a shell
one (`irm 'https://cursor.com/install?win32=true' | iex`) — it lands in
`%LOCALAPPDATA%\cursor-agent` and adds itself to the User PATH.

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

`tstack update` compares this catalog against what's on PATH after every pull and
offers to install anything the catalog gained — see `doc common/stack`.
PrettyMark is the one entry whose winget install doesn't land on `PATH`; its
presence check falls back to the fixed `C:\Program Files\PrettyMark\PrettyMark.exe`
path instead (same one the `pm` alias resolves).
