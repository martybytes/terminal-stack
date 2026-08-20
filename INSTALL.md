# Install

Two paths. Pick the one matching how much trust you have in the scripts.

## Scripted (fastest)

### Quick install (one-liner per environment)

The fastest path: a single command per environment, runnable from a fresh box. Installs prereqs, clones the repo, runs the bootstrap, and ends with `chezmoi apply`. Idempotent.

```powershell
# Windows 11 — PowerShell 7+
irm https://raw.githubusercontent.com/martybytes/terminal-stack/main/install.ps1 | iex
```

```sh
# WSL Ubuntu — run after the Windows one-liner
curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-wsl.sh | bash

# Native Debian/Ubuntu
curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-linux.sh | bash

# macOS
curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-mac.sh | bash
```

**Clone location.** Each installer **prompts** for where to put the repo, pre-filled with the per-platform canonical default (Windows and WSL share **one** clone at `%LOCALAPPDATA%\terminal-stack\stack`, which WSL sees as `/mnt/c/Users/<you>/AppData/Local/terminal-stack/stack`; Linux/macOS `~/.local/share/terminal-stack`). Press Enter to accept, or set `$env:TERMINAL_STACK_DIR` (PowerShell) / `TERMINAL_STACK_DIR=…` (bash) to skip the prompt. If an existing clone sits at an old location, the installer offers to move it to the canonical path (git state intact). The WSL installer auto-detects your Windows username via `cmd.exe` interop, so it runs without prompts under `curl | bash`.

**Cleaning up old installs.** After cloning, the installer scans for **old terminal-stack clones at other paths** and **retired leftover files** (`command-reference.{md,txt,html}`, `~/.local/bin/wzr`, `~/.wezterm-ref`) and offers a checklist — safe items pre-ticked, one confirmation before anything is removed, your per-machine files (`~/.zshrc.local`/`profile.local.ps1`, `~/.doc.local`, `*.local.md`) never touched. Preview without deleting via `TS_DRY_RUN=1`. This is also what prevents the "I re-installed but `doc` still isn't found" trap: a stale `chezmoi sourceDir` pointing at an old clone is repointed automatically.

**Install wizard.** The bootstraps run a short wizard, each prompt skippable via an env var (so scripted installs stay non-interactive — the bash prompts read `/dev/tty` directly and degrade to their defaults when no terminal is attached). Your answers are **saved** (chezmoi `[data]` on WSL/Linux/macOS; `%LOCALAPPDATA%\terminal-stack\config.json` on Windows) so `ts-update` keeps honoring them and `ts-config` can change them later.

- **Leader key** (WezTerm) — `Ctrl+Space` (recommended), `Ctrl+A`, `Ctrl+B`, or a custom `mod-key` chord (e.g. `alt-space`). Skip with `TS_LEADER=ctrl-a`.
- **Theme** — `dark` (Catppuccin Mocha, recommended), `light` (VS Code Light Modern), or `follow` (track the OS light/dark setting; WezTerm switches live, the Starship/tmux palette is baked at apply and refreshed by `ts-update`/`ts-config`). Skip with `TS_THEME=dark|light|follow`.
- **Apps** — accept the recommended set (`eza fzf bat delta ripgrep zoxide glow micro neovim gh ghq lazygit`, plus `tmux` off-Windows) or customize per-app (also offers `zed`, `tldr`, `nvtop`, `lazydocker`). Required tools (WezTerm, the Nerd Font, Starship, chezmoi, git, zsh) are always installed. Skip with `TS_APPS=recommended|all|none|id,id,…`.
- **Workspace directory** — pre-filled with the autodetected candidate (`C:\DATA\Workspace` / `~/Documents/Workspace` / `~/workspace` / `~/Workspace`). Press Enter to accept. Persisted to `~/.zshrc.local` (zsh) or `Documents\PowerShell\profile.local.ps1` (pwsh) *only* when it differs from the autodetect. Skip with `WORKSPACE_DIR=/path` / `$env:WORKSPACE_DIR`.

**Headless servers.** On a host with no graphical session (a server reached over ssh/PuTTY), the bootstrap auto-detects "headless", tells you so, and lets you confirm or flip it; force it with `TS_HEADLESS=1` (or `=0` for a desktop). Headless mode **skips the Nerd Font download and the WezTerm leader-key prompt** — there's no GUI terminal to use them — while still installing tmux, Starship, zsh, and the CLI tools. (WSL is treated as a desktop: it renders in a Windows GUI terminal.)

Change any of these later with **`ts-config`** (interactive menu) or one-shot — `ts-config theme follow`, `ts-config leader ctrl-a`, `ts-config apps`, `ts-config show`. In a combined Windows+WSL setup, run `ts-config` from WSL (its `chezmoi apply` is authoritative for the Windows-side files).

One setting the wizard deliberately doesn't ask about is the WezTerm **multiplexer domain** — whether panes are hosted by `wezterm-mux-server` (so a GUI crash leaves them alive) instead of the GUI. It installs **off**; turn it on with `ts-mux on` once you've read the trade-offs in `ts-mux -h` (config changes then need `ts-mux restart`, which kills every pane, and mux panes can't render the per-pane Claude tint).

**If something looks wrong** — `doc: command not found` after an update, a clone you moved, leftover old clones — run **`ts-doctor`** (read-only health check) and **`ts-doctor --repair`** (pwsh: `ts-doctor -Repair`) to repoint chezmoi's `sourceDir`, re-apply, and clean up. The installers run the same check automatically at the end.

If you want to walk through each step instead (recommended for first-time inspection, or when chezmoi would clobber an existing hand-edited dotfile), keep reading.

### Step-by-step (same end result, with intermediate stops)

For a fresh Windows 11 + WSL2 machine, follow sections 1 → 4 below. For a native Linux box (Debian/Ubuntu), skip sections 1–2 and follow section 2L (Linux) → 3 → 4. For a macOS host, skip sections 1–2 and follow section 2M (macOS) → 3 → 4. The WSL bootstrap will prompt for your Windows username (it pre-fills the value reported by `cmd.exe` via interop, so usually you can just press Enter); the Linux and macOS bootstraps have no Windows-side prompts.

### 1. Windows side

Open PowerShell 7 (`pwsh`) and run (adjust the path if you cloned elsewhere — the default for the one-liner installer is `$env:LOCALAPPDATA\terminal-stack\stack`):

```powershell
cd $env:LOCALAPPDATA\terminal-stack\stack
.\bootstrap\windows-bootstrap.ps1
```

It runs the wizard (leader key / theme / apps — see **Install wizard** above; set `$env:TS_LEADER`/`TS_THEME`/`TS_APPS` to skip prompts), then installs:
- **Always:** WezTerm nightly (`wez.wezterm.nightly`), JetBrainsMono Nerd Font (`DEVCOM.JetBrainsMonoNerdFont`), Starship (`Starship.Starship`), chezmoi (`twpayne.chezmoi`)
- **Selected apps** (recommended set by default): eza, fzf, bat, delta, ripgrep, zoxide, glow, micro, neovim; optional `zed` (one winget each)

It saves your choices to `%LOCALAPPDATA%\terminal-stack\config.json`. Pass `-WhatIf` to preview without installing. UAC prompts on machine-scope installs; approve each.

### 2. WSL side

Open WSL Ubuntu (substitute your Windows username for `<you>`):

```sh
wsl -d Ubuntu
cd /mnt/c/Users/<you>/AppData/Local/terminal-stack/stack
bash ./bootstrap/wsl-bootstrap.sh
```

This installs:
- zsh + git + curl + unzip
- oh-my-zsh (unattended)
- Sets login shell to zsh for current user
- chezmoi (curl installer to `~/.local/bin/`)
- Starship (curl installer to `/usr/local/bin/`)
- `fonts-jetbrains-mono` (regular variant) + Nerd Font variant zip
- eza, zoxide, fzf, bat (with `batcat` → `bat` symlink), git-delta, ripgrep
- tmux

Re-run as needed; the script is idempotent.

### 2L. Linux side (native Debian/Ubuntu, instead of WSL)

For any native Debian/Ubuntu host:

```sh
git clone <repo-url> ~/.local/share/terminal-stack    # or your chosen path
cd ~/.local/share/terminal-stack
bash ./bootstrap/linux-bootstrap.sh
```

Installs the same toolchain as the WSL bootstrap (zsh, oh-my-zsh, chezmoi, Starship, Nerd Font, modern CLI tools), writes `~/.config/chezmoi/chezmoi.toml` with `sourceDir` pointing at the clone, and skips all Windows-side handling. The post-apply sync hook self-no-ops when `/mnt/c/Users/` is absent, so `chezmoi apply` Just Works.

Override the source path via env var if you cloned elsewhere:

```sh
SOURCE_DIR=/srv/dotfiles/terminal-stack bash ./bootstrap/linux-bootstrap.sh
```

Re-run as needed; the script is idempotent.

### 2M. macOS side (instead of WSL/Linux)

For a MacBook or any macOS host:

```sh
git clone <repo-url> ~/.local/share/terminal-stack    # or your chosen path
cd ~/.local/share/terminal-stack
bash ./bootstrap/mac-bootstrap.sh
```

Installs via Homebrew (installing Homebrew itself first if absent):
- zsh, git, tmux
- oh-my-zsh (unattended)
- chezmoi, Starship
- eza, zoxide, fzf, bat, git-delta, ripgrep
- WezTerm nightly (`--cask wezterm@nightly`) and JetBrainsMono Nerd Font (`--cask font-jetbrains-mono-nerd-font`)

The plain `wezterm` cask is pinned to the stale `20240203` stable; the stack uses the `wezterm@nightly` cask so macOS matches the WezTerm nightly installed on the Windows side.

It also writes `~/.config/chezmoi/chezmoi.toml` with `sourceDir` pointing at the
clone (auto-detected from the script's own location). macOS keeps the system
`/bin/zsh` as the login shell; the Windows-side `windows/**` subtree is skipped
automatically because `/mnt/c/Users/` doesn't exist.

Override the source path via env var if you cloned elsewhere:

```sh
SOURCE_DIR=~/dotfiles/terminal-stack bash ./bootstrap/mac-bootstrap.sh
```

Re-run as needed; the script is idempotent.

### 3. Apply chezmoi

The WSL bootstrap already wrote `~/.config/chezmoi/chezmoi.toml` with `sourceDir` and `[data].windowsUsername`. Just apply:

```sh
# Inside WSL
~/.local/bin/chezmoi apply -v
```

The Linux and macOS bootstraps likewise write `~/.config/chezmoi/chezmoi.toml`
(no `windowsUsername` — there's no Windows side). If you skipped the bootstrap,
write it by hand — chezmoi expands a leading `~` but **not** `$HOME`, so use a
tilde or an absolute path:

```sh
mkdir -p ~/.config/chezmoi
echo 'sourceDir = "~/.local/share/terminal-stack"' > ~/.config/chezmoi/chezmoi.toml  # adjust path
chezmoi apply -v
```

(macOS and native Linux skip the Windows side automatically: the `run_after` hook's `/mnt/c/Users/<user>/` existence check noops when the path doesn't exist.)

For per-machine overrides (peer-sync helpers, server-role aliases, anything that shouldn't propagate via the shared repo), copy `~/.zshrc.local.example` to `~/.zshrc.local` and edit. `dot_zshrc` sources it at the end if present.

### 4. Reopen WezTerm

Open a new WezTerm tab — auto-reload picks up the new `.wezterm.lua`. Open a pwsh tab and a `Alt-L → WSL zsh` tab to confirm starship renders correctly with the Nerd Font.

On macOS, quit and relaunch WezTerm so it sets JetBrainsMono Nerd Font from the freshly-applied `~/.wezterm.lua`, then open a new tab and confirm the Starship two-line prompt renders with glyphs. WezTerm itself must be set to a Nerd Font for the launch-window prompt; the config does that automatically.

**macOS — free the keybinding keys.** macOS intercepts the WezTerm leader and the directional pane F-keys before they reach the terminal, so out of the box `Ctrl+Space …` and `F1`–`F6` look dead. Two System Settings toggles fix it:

- **F-keys** → System Settings → Keyboard → enable **"Use F1, F2, etc. keys as standard function keys"** (or hold **Fn** + F1…F6). The bare F-row is otherwise hardware media keys (brightness, Mission Control, …).
- **`Ctrl+Space`** → System Settings → Keyboard → Keyboard Shortcuts → **Input Sources** → uncheck **"Select the previous input source"**. That system shortcut swallows `Ctrl+Space` system-wide, which also disables the `Ctrl+Space 1`–`6` F-key fallback.

Then `Ctrl+Space r` in WezTerm to reload, and the bindings in the command reference work.

### Developing WezTerm config

WezTerm reads `%USERPROFILE%\.wezterm.lua` and `%USERPROFILE%\.wezterm\pane_nav.lua`, **not** the git clone. After editing `windows/.wezterm.lua.tmpl` or `windows/.wezterm/pane_nav.lua` in your dev checkout, deploy and reload:

```powershell
& C:\path\to\terminal-stack\scripts\sync-windows.ps1 -SourceDir C:\path\to\terminal-stack
```

The canonical install (`%LOCALAPPDATA%\terminal-stack\stack`) resolves without any pin — set `$env:TERMINAL_STACK_DIR` in `profile.local.ps1` only when working against a **non-canonical** location, e.g. a dev clone at a workspace tier path (which is otherwise invisible to `ts-update` and the resolvers). Changes to `.wezterm.lua` usually auto-reload; press **`Ctrl+Space` `r`** after `pane_nav.lua` edits. Full loop, optional file-watcher, macOS path, and symlink trick: `docs/developing-wezterm.md`.

## Manual

For when you want to understand each step. Every command is annotated; numbered headings just keep the steps ordered.

### Phase 0 — Detect environment

Confirm versions and existing state:

```powershell
$PSVersionTable.PSVersion                # expect 7.6+
wsl -l -v                                # confirm Ubuntu present
winget --version                         # confirm winget available
```

```sh
# Inside WSL
cat /etc/os-release | grep PRETTY_NAME   # confirm Ubuntu 26.04 or similar
```

### Phase 0.5 — WSL prereqs

```sh
sudo apt-get update
sudo apt-get install -y zsh git curl unzip
sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
chsh -s /usr/bin/zsh
sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin"
```

Log out and back in (or close/reopen the WSL terminal) so the new login shell takes effect.

### Phase 1 — WezTerm nightly (Windows)

```powershell
winget install --id wez.wezterm.nightly --exact --silent
wezterm.exe --version    # expect 2025+ build, not 20240203
```

### Phase 2 — `.wezterm.lua`

Will land via `chezmoi apply` in step "Apply chezmoi" at the bottom of this manual path.

### Phase 3 — JetBrainsMono Nerd Font

```powershell
winget install --id DEVCOM.JetBrainsMonoNerdFont --exact --silent
```

```sh
# WSL — both apt regular and the Nerd Font zip from upstream
sudo apt-get install -y fonts-jetbrains-mono
mkdir -p ~/.local/share/fonts/JetBrainsMonoNerdFont
curl -fL -o /tmp/jbm-nf.zip https://github.com/ryanoasis/nerd-fonts/releases/latest/download/JetBrainsMono.zip
unzip -q /tmp/jbm-nf.zip -d ~/.local/share/fonts/JetBrainsMonoNerdFont/
rm /tmp/jbm-nf.zip
fc-cache -f
```

### Phase 4 — tmux

Will land via `chezmoi apply`. Install the binary first:

```sh
sudo apt-get install -y tmux
```

### Phase 5 — Starship + shell hookups

```powershell
winget install --id Starship.Starship --exact --silent
```

```sh
sudo curl -sS https://starship.rs/install.sh | sh -s -- -y -b /usr/local/bin
```

`.zshrc` (full file) and `$PROFILE` (marker-block injection) will be handled by `chezmoi apply`.

### Phase 6 — Shell helpers

Lands via `chezmoi apply` (zsh `ccs` / `ssht`).

### Phase 7 — Modern CLI tools

```powershell
winget install --id eza-community.eza --exact --silent
winget install --id junegunn.fzf --exact --silent
winget install --id sharkdp.bat --exact --silent
winget install --id dandavison.delta --exact --silent
winget install --id BurntSushi.ripgrep.MSVC --exact --silent
# zoxide if not already from Chocolatey:
# winget install --id ajeetdsouza.zoxide --exact --silent
# workspace-organizer toolchain (wso):
winget install --id GitHub.cli --exact --silent
winget install --id x-motemen.ghq --exact --silent
winget install --id JesseDuffield.lazygit --exact --silent
```

```sh
sudo apt-get install -y eza zoxide fzf bat git-delta ripgrep
mkdir -p ~/.local/bin
ln -sf /usr/bin/batcat ~/.local/bin/bat
```

`gh`, `ghq` and `lazygit` back the `wso` workspace organizer. Only `gh` is packaged
on Debian/Ubuntu, and only from 24.04, so the bootstrap installs all three from their
upstream GitHub releases into `~/.local/bin` when apt cannot supply them (arch-aware —
amd64 and arm64 both work). On macOS all three are Homebrew formulae:

```sh
brew install gh ghq lazygit
```

Authenticate `gh` once per machine — `wso synceverything` and `wso orphans --push`
need it, and `wso doctor` checks for it:

```sh
gh auth login
```

### Phase 8 — Apply chezmoi

```sh
# Detect your Windows username (or hard-code it below)
WIN_USER=$(/mnt/c/Windows/System32/cmd.exe /c 'echo %USERNAME%' | tr -d '\r\n')
mkdir -p ~/.config/chezmoi
cat > ~/.config/chezmoi/chezmoi.toml <<EOF
sourceDir = "/mnt/c/Users/${WIN_USER}/terminal-stack"

[data]
windowsUsername = "$WIN_USER"
EOF
~/.local/bin/chezmoi diff      # preview what will change (WSL targets only)
~/.local/bin/chezmoi apply -v
```

You'll see one creation summary plus a `sync-windows: user=<you>, …` line confirming the run_after hook ran.

If you skip the `[data].windowsUsername` line, the sync hook will fall back to `cmd.exe /c echo %USERNAME%` via interop and use that — explicitly setting it just makes the value stable across machine renames.

### Phase 9 — Verify

```powershell
wezterm.exe --version
starship --version
pwsh -c '$PSVersionTable.PSVersion'
```

```sh
zsh --version
tmux -V
eza --version | head -1
zoxide --version
fzf --version
bat --version
delta --version
rg --version | head -1
chezmoi doctor | head -5
```

Open WezTerm, confirm tab status bar shows workspace · cwd. Open a zsh pane, confirm Starship prompt with the branch glyph renders. Open a pwsh pane, run `cc` from a project dir, confirm tab title flips to `cc • <project>`.

### Phase 10 — Done

`git log --oneline` shows the prior history. Any subsequent changes you make should land as new commits with marker blocks where they belong.
