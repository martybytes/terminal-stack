# Omarchy (Arch + Hyprland)

Omarchy is a fourth kind of target for this stack, and the first native-Linux
**desktop** one. Every earlier native-Linux host here was assumed headless
(ssh/PuTTY), and a good deal of the code says so out loud.

This page is the map: what Omarchy owns, what the stack owns, and where the two
used to collide. The reasoning behind each choice is in `docs/decisions.md`
§§ "Why Omarchy is a package-manager seam…" onward; this is the operational
view.

Verified against **Omarchy 4.0.1** (`/etc/os-release`: `ID=omarchy`,
`ID_LIKE=arch`), tmux 3.7c, chezmoi 2.72.0.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-linux.sh | bash
```

Same one-liner as Debian/Ubuntu. The installer detects the package manager and
routes to `bootstrap/_common-arch.sh` instead of `_common-debian.sh`.

Before this existed, that command failed on line one of the bootstrap with
`sudo: apt-get: command not found` — before the questionnaire, before chezmoi,
before anything was written.

## The division of labour

| Thing | Owner | Why |
|---|---|---|
| Packages | **Omarchy** (`omarchy pkg add` → pacman) | Every tool in the catalog but `llmfit` is in Arch `extra`, and ~20 are already in `omarchy-base.packages`. A `~/.local/bin` copy would shadow a pacman binary that `omarchy update` can never upgrade |
| Login shell | **Omarchy** (bash) | `~/.bashrc` → `$OMARCHY_PATH/default/bash/rc` is where its aliases, functions, mise/starship/zoxide/fzf init and completions live. The stack does **not** `chsh` here |
| `~/.config/tmux/tmux.conf` | **shared** — Omarchy's config sourced first, stack's settings on top | tmux prefers the XDG path; see below |
| `~/.config/ghostty/config` | **Omarchy** | It themes it per theme, seds the font family on `omarchy font set`, and restores it with `omarchy refresh config`. `tstack ghostty` correctly refuses off macOS |
| `starship` binary | **Omarchy** (pacman) | The curl installer writes `/usr/local/bin`, which precedes `/usr/bin` on PATH and shadows the packaged copy |
| `~/.config/starship.toml` | **stack** | The prompt is the part you chose; `tstack config prompt` still owns it |
| `chezmoi` binary | **Omarchy** (pacman, `extra/chezmoi`) | Debian has no package, which is the only reason the apt side curls it |
| Language runtimes | **Omarchy** (mise) | `omarchy install dev-env <lang>` is entirely `mise use --global`, and the shims are on PATH from `env-bootstrap`. `fnm`, `node` and `python` are vetoed from the catalog here |
| Nerd Font | **Omarchy** (`ttf-jetbrains-mono-nerd-basic`) | The stack's download step guards on `fc-list`, which that package already satisfies, so it self-skips |
| `~/.zshrc`, `~/.wezterm.lua`, `doc`/`ws`/`wso`/`tstack` | **stack** | The terminal is the stack's half of the machine |

## The tmux trap, and what the stack does about it

tmux reads `~/.tmux.conf` **or** `$XDG_CONFIG_HOME/tmux/tmux.conf`. On tmux
3.7c, **the XDG file wins when both exist.** Probed in a scratch `$HOME`:

```
both files present            -> prefix C-Space   (from the XDG file)
only ~/.config/tmux/tmux.conf -> prefix C-Space
only ~/.tmux.conf             -> prefix C-a
```

Omarchy ships its config at the XDG path. So the stack writing `~/.tmux.conf`
on Omarchy produced a file tmux never read: applied, visible in
`chezmoi diff`, and completely inert. The wizard's tmux-prefix answer had no
effect, with no error anywhere.

On Omarchy the stack therefore renders **`~/.config/tmux/tmux.conf`** instead,
and that file `source-file -q`s Omarchy's own config *first* before applying the
stack's prefix and behaviour. Later `set` wins in tmux, so the order is the
whole mechanism. That keeps Omarchy's Alt+Enter splits, Alt+1..9 window
switching and the Super+/ keybindings popup.

The stack's own status-bar theme is deliberately **not** applied on Omarchy: its
hexes are baked light/dark and would pin the bar to Catppuccin while every other
surface followed the active Omarchy theme (`omarchy-theme-set-tmux` re-tints on
every `omarchy theme set`). Plain Arch has no Omarchy theme to follow, so it
keeps the baked one.

`.chezmoiignore` gates the two paths against each other on `distroId`, so
exactly one is ever written. Both bodies come from `.chezmoitemplates/tmux-core`
and `tmux-theme`, so they cannot drift.

## zsh here

Omarchy is bash-first and the bootstrap leaves the login shell alone. zsh is
still installed and `~/.zshrc` is still applied, so:

```sh
zsh -l              # the stack's zsh, on demand
```

**Phase 1 uses oh-my-zsh, as on every other platform.** Omarchy ships an
official `omarchy-zsh` package (repo `omarchy`, deps `zsh eza mise zoxide
starship fzf fd bat zsh-syntax-highlighting`) which is the intended route — but
it generates its own `~/.zshrc`, and chezmoi owns that file whole. Making both
work means restructuring the stack's zsh content into a sourced fragment, which
is phase 2. Until then oh-my-zsh stays: it is self-contained in `~/.oh-my-zsh`
and trivially removed later.

Do **not** `chsh -s /usr/bin/zsh` on Omarchy. It takes away the entire
`default/bash/rc` chain with no warning.

## Detection

Two readers, one rule, both driven by `/etc/os-release`:

| | shell | Python |
|---|---|---|
| id | `ts_distro_id` | `plat.distro()` |
| family | `ts_is_arch` / `ts_is_debianish` | `plat.is_arch()` |
| Omarchy | `ts_is_omarchy` | `plat.is_omarchy()` |
| manager | `ts_pkg_manager` | — |
| which lib | `ts_common_lib` | — |

`TS_DISTRO_ID`, `TS_DISTRO_LIKE` and `TS_PKG_MANAGER` override all of it, which
is how the tests drive every branch on a machine that is only ever one distro.
An override that is **set but empty** means "this host has no ID" — testing for
non-empty instead made bash fall through to the live file and disagree with
Python.

`plat.kind()` stays four-valued (`windows`/`wsl`/`linux`/`macos`). Every switch
on it means "is this a POSIX box with no Windows side", and Arch answers `linux`
exactly as Debian does. The distro is a second axis, so it gets its own
functions rather than a fifth `kind()` value every existing caller would have to
learn.

## The installer contract

`bootstrap/_common-posix.sh` holds everything shared, including
`common_install_all` — the ordering, which encodes two separate incidents
(persistence before optional installs; chezmoi before persistence). Each distro
half supplies exactly six functions:

```
common_pkg_prereqs            common_login_shell_zsh
common_install_selected_apps  common_chezmoi
common_install_terminals      common_starship
```

`tests/test_distro.py` asserts both halves supply all six, that neither
redefines anything posix owns, and that neither reaches for the other's package
manager.

`_common-arch.sh` is much shorter than `_common-debian.sh`, and that is the
point: most of the Debian file is not apt, it is the *absence* of apt — a
GitHub-release fetch, a PPA or a third-party repo for each of eza, delta, gh,
ghq, lazygit, dust, gdu, bottom, bandwhich, gping, atuin, yazi, glow, neovim and
zed. All of them are in Arch `extra`. The `batcat`/`fdfind` symlink repairs go
the same way: Arch names both binaries correctly.

`ts_arch_pkg` maps catalog ids to package names. Only six diverge
(`delta`→`git-delta`, `gh`→`github-cli`, `tldr`→`tealdeer`, `node`→`nodejs`,
`pipx`→`python-pipx`, `poetry`→`python-poetry`); `llmfit` maps to empty and
takes the release-tarball path. An id with no case arm is **reported and
skipped**, never silently dropped, and a test asserts the mapping is total over
the catalog.

## WezTerm

`extra/wezterm` is the stable channel; nightly is AUR `wezterm-git`. The stack
installs the former and **prints** the command for the latter without running an
AUR helper — `wezterm-git` builds from source, unattended, inside what the user
thinks is a dotfiles install.

Note that Omarchy's own terminal machinery only knows `alacritty|foot|ghostty|
kitty`: `omarchy install terminal`, `omarchy default terminal`, `omarchy font
set` and the theme templates all enumerate those four. WezTerm gets no Omarchy
theming or font syncing today. Phase 2 adds a user template
(`~/.config/omarchy/themed/wezterm.lua.tpl`) and a `theme-set.d` hook to fix
that.

## Testing

```sh
tests/parity/run.sh arch omarchy          # the suite, on both (in the default set)
tests/parity/run.sh omarchy-bootstrap     # RUN the installer, end to end
tests/parity/run.sh arch-bootstrap        # the same, with no omarchy-* commands present
```

`arch` is plain `archlinux:latest` — the case `_common-arch.sh` must keep
working for and the one a developer on an Omarchy laptop never hits by accident.
`omarchy` adds Omarchy's `/etc/os-release`, its pacman repo, and the **real**
`omarchy-pkg-*` scripts extracted from the real package. They are extracted
rather than stubbed because a stub agrees with whatever we assumed, which is the
opposite of a test; the package itself is not installed because it depends on
hyprland, quickshell, sddm and uwsm — 115 MB of desktop that cannot run in a
container.

`run.sh` escalates to `sudo docker` when a plain `docker info` fails and a
passwordless `sudo docker info` works. Omarchy deliberately does not put you in
the `docker` group (`install/config/docker.sh`: group membership is equivalent
to passwordless root), so without that the parity run is unavailable on the very
platform it gates.

## Known gaps (phase 2)

- **`tstack services` / Docker.** `engine.py` sees permission-denied and advises
  `sudo usermod -aG docker "$USER"`, which is exactly the escalation Omarchy
  declined. It should point at `omarchy-setup-security-sudoless-docker`. `ufw`
  is active and `ufw-docker` is installed, so published ports need a
  localhost-binding story before the stacks are used here.
- **WezTerm config is still macOS-gated** in `.chezmoiignore`.
- **`~/.claude/settings.json`** — `omarchy-theme-set-claude --activate` writes
  `.theme` and its `mv` replaces a symlink; the stack's splice writes the same
  key. The stack should drop `theme` here and write through symlinks.
- **Alias collisions** — Omarchy's `c` (opencode), `cx` (claude, auto
  permissions) and `cy` (codex) versus the stack's, plus `EDITOR`.
- **`omarchy-zsh`** as the zsh base, with the stack's content as a fragment.
- **`post-update.d` hook** so `omarchy update` also refreshes the stack.
