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

Two guards on that choice, both there because the alternative bit us:

- **Not inside a workspace root.** If the target sits under a detected workspace (`C:\DATA\Workspace`, `~/workspace`, …), the installer warns and offers the canonical path instead — `wso migrate` derives destinations from a repo's `origin` and will otherwise relocate the runtime clone to a tier path, orphaning the install. Answer `n` to override; a dev clone already at a tier path is exempt.
- **A stale pin is ignored, not obeyed.** `profile.local.ps1` is dot-sourced by `$PROFILE`, so a `TERMINAL_STACK_DIR` written by an earlier install is set in *every* pwsh session — `irm … | iex` never starts clean. If that persisted pin points at a path with no clone, the installer says so, falls back to the canonical default, and removes the dead line (backed up first). A pin you export for one run is not in that file and is always honoured.

**Cleaning up old installs.** After cloning, the installer scans for **old terminal-stack clones at other paths** and **retired leftover files** (`command-reference.{md,txt,html}`, `~/.local/bin/wzr`, `~/.wezterm-ref`) and offers a checklist — safe items pre-ticked, one confirmation before anything is removed, your per-machine files (`~/.zshrc.local`/`profile.local.ps1`, `~/.doc.local`, `*.local.md`) never touched. Preview without deleting via `TS_DRY_RUN=1`. This is also what prevents the "I re-installed but `doc` still isn't found" trap: a stale `chezmoi sourceDir` pointing at an old clone is repointed automatically.

**Install wizard.** The bootstraps run a short wizard, each prompt skippable via an env var (so scripted installs stay non-interactive — the bash prompts read `/dev/tty` directly and degrade to their defaults when no terminal is attached). Your answers are **saved** (chezmoi `[data]` on WSL/Linux/macOS; `%LOCALAPPDATA%\terminal-stack\config.json` on Windows) so `ts-update` keeps honoring them and `ts-config` can change them later.

Every question works the same way: the default is **marked with `>` and captioned "press Enter"**, an option's **name works wherever its number does** (`dark`, `stable`, `none`), and anything it doesn't recognise **asks again** rather than quietly taking the default — after three tries it gives up and takes the default, so an automated caller can't hang.

- **Leader key** (WezTerm) — `Ctrl+Space` (default), `Ctrl+A`, `Ctrl+B`, `Alt+Space`, or a custom `mod-key` chord (e.g. `ctrl-x`). Skip with `TS_LEADER=ctrl-a`.
- **Theme** — `dark` (Catppuccin Mocha, default), `light` (VS Code Light Modern), or `follow` (track the OS light/dark setting; WezTerm switches live, the Starship/tmux palette is baked at apply and refreshed by `ts-update`/`ts-config`). Skip with `TS_THEME=dark|light|follow`.
- **Terminal emulator** (Windows, macOS and desktop Linux — WSL and headless hosts never install one) — a tick-list, so each is individually opt-in and `[n]one` is one keystroke away. **WezTerm nightly**, **WezTerm stable** and (macOS/Linux) **Ghostty** are separate ticks. Whatever is installed starts ticked on its detected channel; on a fresh machine **nightly is pre-selected**, because upstream's newest stable is `20240203` — February 2024, with no cut since — and this stack's Lua config targets current builds.

  The prompt shows the facts rather than just a default: your installed build and its date, the newest build on each channel, and a count of what changed in between.

  ```
  Terminal emulator:
    Installed: WezTerm 20240203-110809-5046fc22 (stable, 2024-02-03)
    Latest:    nightly built 2026-08-23  | stable 20240203-110809-5046fc22 (2024-02-03)
    Since your build: Changed 20  New 32  Fixed 74  Updated 9
    [ ]  1) WezTerm nightly  (current builds; what this stack configures)
    [x]  2) WezTerm stable  (20240203 — upstream has not cut one since)
    [x]  3) Ghostty  (GPU-accelerated, platform-native UI)
  Toggle a number, [a]ll, [n]one, Enter to continue, [s]kip:
  ```

  **Nothing is automatic.** Nothing installs unless you tick it, and neither channel ever upgrades on its own — `ts-update` reports and offers, `ts-config wezterm` changes it on demand. Ticking both WezTerm rows installs nightly and says so: the two packages install to the same place, so they cannot coexist, and switching channel removes the other first.

  Skip the prompt with `TS_TERMINALS=wezterm-nightly,ghostty` / `TS_TERMINALS=wezterm-stable` / `TS_TERMINALS=none`; `TS_WEZTERM=nightly|stable|skip` still maps across. Change it later with **`ts-config wezterm install <stable|nightly>`**, which removes the other channel for you; `ts-config wezterm` (or `ts-wezterm`) shows your build, both channels' newest, and what changed in between. Rationale in `docs/decisions.md` § "Why the WezTerm channel is a question, and why it is not a saved setting".
- **WezTerm multiplexer** — whether panes are hosted by `wezterm-mux-server` instead of the GUI, so a GUI crash leaves every pane alive and relaunching WezTerm reattaches. Defaults to **off**: the mux server loads its own copy of `.wezterm.lua`, so config changes then need `ts-mux restart` (which kills every pane), and mux panes can't render the per-pane Claude tint. Skipped on headless servers (no GUI to host). Change it any time with `ts-mux on|off`. Skip with `TS_WEZ_MUX=on|off`.
- **Restore last session** — whether launching WezTerm reopens the workspace you last had (panes, layout and scrollback) or starts clean. Defaults to **off**; the autosave runs either way, so `Ctrl+Space` `L` still restores by hand and `ts-config restore on` flips it later. Skipped on headless servers. Skip with `TS_WEZ_RESTORE=on|off`.
- **Apps** — five ways to answer: the **recommended set**, **everything**, **whole groups**, **individual tools**, or **none**. The Nerd Font, Starship, chezmoi, git and zsh are always installed regardless. Skip the question with `TS_APPS=recommended|all|none|id,id,…`.

  The catalog is grouped so you can take a category without reading 30 lines:

  | Group | Tools |
  |---|---|
  | `shell` | tmux, eza, bat, tree, zoxide, fzf, atuin |
  | `search` | ripgrep, fd |
  | `disk` | duf, ncdu, dust, gdu |
  | `system` | btop, bottom, glances, nvtop, lazydocker |
  | `network` | bandwhich, gping, rclone |
  | `git` | delta, gh, ghq, lazygit |
  | `editors` | micro, neovim, glow, zed, tldr, yazi (+ prettymark on Windows) |
  | `runtimes` | fnm (Node version manager), node |
  | `python` | python, uv, pipx, ruff, ipython, httpie, poetry, pre-commit |
  | `ai` | claude, codex, cursor-agent, grok, gemini, pi |

  **choose whole groups** ticks groups — *all* of them start ticked, `ai` included; **choose individual tools** walks the groups one tick-list at a time, or takes a comma-separated list if you already know what you want. Anything in the recommended set starts ticked, so pressing Enter through the walk lands exactly on the recommended set.

  **The `ai` group defaults to all five and is still a question** — every agent CLI starts ticked, and every one stays individually untickable. None of them come from a package manager:

  | CLI | How it installs | Needs Node? |
  |---|---|---|
  | `claude` | official installer (`claude.ai/install.sh`) | no |
  | `grok` | official installer (`x.ai/cli/install.sh`) — a standalone binary | no |
  | `cursor-agent` | official installer (`cursor.com/install`) | no |
  | `codex` | npm `@openai/codex` | **16+** |
  | `gemini` | npm `@google/gemini-cli` | **20+** |

  The two npm ones are gated on the Node version and say what to do rather than failing — install `fnm` from the `runtimes` group and they work. There is deliberately no brew fallback for `gemini`: the `gemini-cli` formula is deprecated upstream and scheduled for removal, so it would hand you a dead end.

  **`python` and `runtimes`** are ordinary groups asked the same way. `fnm` is chosen over nvm because nvm costs 200-500ms of shell startup and fnm about 10ms, and it reads `.nvmrc`/`.node-version` so per-project pins keep working; picking it also installs the current Node LTS, since the manager alone gives you no runtime.

  Groups are a picker concern only; the saved selection stays a flat list, so no new config key is involved.

  After installing, the wizard prints what each tool actually resolved to and its version — an installer that failed quietly shows up as `NOT FOUND on PATH` rather than being assumed to have worked.

- **Changed your mind later?** `ts-config apps` re-asks just the apps question; **`ts-config wizard`** replays the *entire* questionnaire — leader, theme, terminal emulator, apps, mux, restore, TTS, agent tools — and persists all of it. `TS_ASSUME_YES=1 ts-config wizard` takes the defaults without prompting.
- **Claude Code voice notifications** — off unless a local Kokoro TTS server answers on `http://127.0.0.1:8880`, in which case enabling is the default. Skip with `TS_CC_TTS=on|off`.
- **TTS tray daemon** (asked only when voice notifications were enabled, on Windows/WSL, never headless) — route announcements through a small native daemon that names the session ("terminal-stack finished — added the retry logic"), queues and coalesces simultaneous completions, and ducks (or pauses) your music while speaking. Defaults to **direct EXE playback**; enabling voice builds one console-free `terminal-stack-tts.exe` using a temporary Python venv, while choosing the daemon also adds autostart and the tray/session features. Python 3.10+ is a build dependency only — no persistent venv or Python runtime remains under `%LOCALAPPDATA%\terminal-stack\tts-daemon`. Change later with `ts-config tts daemon on|off`; hooks launch a detached direct worker in the same EXE whenever the daemon is unreachable. Skip with `TS_CC_TTS_DAEMON=on|off`. The daemon also hosts the dashboard (tray: Open dashboard, or `http://127.0.0.1:8890/ui`) for live activity, the log, and settings. Details: `doc windows/tts-daemon`.
- **Workspace directory** — pre-filled with the autodetected candidate (`C:\DATA\Workspace` / `~/Documents/Workspace` / `~/workspace` / `~/Workspace`). Press Enter to accept. Persisted to `~/.zshrc.local` (zsh) or `Documents\PowerShell\profile.local.ps1` (pwsh) *only* when it differs from the autodetect. Skip with `WORKSPACE_DIR=/path` / `$env:WORKSPACE_DIR`.

Then a **review** — every answer listed, with `[P]roceed / [e]dit / [q]uit`. Nothing has been installed or written at that point, so `e` re-asks the questions and `q` leaves the machine untouched. The review is skipped when there is nothing to review (every answer came from an env var) or with `TS_ASSUME_YES=1` (bash).

**Headless servers.** On a host with no graphical session (a server reached over ssh/PuTTY), the bootstrap auto-detects "headless", tells you so, and lets you confirm or flip it; force it with `TS_HEADLESS=1` (or `=0` for a desktop). Headless mode **skips the Nerd Font download and the WezTerm leader-key prompt** — there's no GUI terminal to use them — while still installing tmux, Starship, zsh, and the CLI tools. (WSL is treated as a desktop: it renders in a Windows GUI terminal.)

Change any of these later with **`ts-config`** (interactive menu) or one-shot — `ts-config theme follow`, `ts-config leader ctrl-a`, `ts-config apps`, `ts-config restore on`, `ts-config show`. In a combined Windows+WSL setup, run `ts-config` from WSL (its `chezmoi apply` is authoritative for the Windows-side files).

**If something looks wrong** — `doc: command not found` after an update, a clone you moved, leftover old clones — run **`ts-doctor`** (read-only health check) and **`ts-doctor --repair`** (pwsh: `ts-doctor -Repair`) to repoint chezmoi's `sourceDir`, move a legacy-path clone to the canonical location, re-apply, and clean up. If the canonical location is *already* occupied, `--repair` switches to the clone that lives there and offers the other one for removal — a case that used to have no way forward. The installers run the same check automatically at the end.

If you want to walk through each step instead (recommended for first-time inspection, or when chezmoi would clobber an existing hand-edited dotfile), keep reading.

### Step-by-step (same end result, with intermediate stops)

For a fresh Windows 11 + WSL2 machine, follow sections 1 → 4 below. For a native Linux box (Debian/Ubuntu), skip sections 1–2 and follow section 2L (Linux) → 3 → 4. For a macOS host, skip sections 1–2 and follow section 2M (macOS) → 3 → 4. The WSL bootstrap will prompt for your Windows username (it pre-fills the value reported by `cmd.exe` via interop, so usually you can just press Enter); the Linux and macOS bootstraps have no Windows-side prompts.

### 1. Windows side

Open PowerShell 7 (`pwsh`) and run (adjust the path if you cloned elsewhere — the default for the one-liner installer is `$env:LOCALAPPDATA\terminal-stack\stack`):

```powershell
cd $env:LOCALAPPDATA\terminal-stack\stack
.\bootstrap\windows-bootstrap.ps1
```

It runs the wizard (leader key / theme / terminal emulator / mux / apps / TTS + optional tray daemon / workspace — see **Install wizard** above; set `$env:TS_LEADER`/`TS_THEME`/`TS_TERMINALS`/`TS_WEZ_MUX`/`TS_WEZ_RESTORE`/`TS_APPS`/`TS_CC_TTS`/`TS_CC_TTS_DAEMON` to skip prompts), shows the review, and only then installs:
- **Always:** JetBrainsMono Nerd Font (`DEVCOM.JetBrainsMonoNerdFont`), Starship (`Starship.Starship`), chezmoi (`twpayne.chezmoi`)
- **WezTerm, if you ticked it:** `wez.wezterm.nightly` or `wez.wezterm`, whichever channel you picked. Switching channel uninstalls the other package first — they install to the same place. Ghostty is offered here too, but never installed for you: on Windows it is [noctty](https://github.com/amanthanvi/noctty), whose releases still carry the former name winghostty (`winget install AmanThanvi.winghostty`). Tick it and the managed config is written either way
- **Selected apps** (recommended set by default): eza, fzf, bat, delta, ripgrep, zoxide, glow, micro, neovim, gh, ghq, lazygit, prettymark; optionally `zed` (one winget install)

It saves your choices to `%LOCALAPPDATA%\terminal-stack\config.json`. Any package that failed is **listed again at the end with the command to retry it**, so a failure can't scroll past unnoticed. Pass `-WhatIf` to preview without installing. UAC prompts on machine-scope installs; approve each.

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
- JetBrainsMono Nerd Font (`--cask font-jetbrains-mono-nerd-font`)
- Terminal emulators, if you ticked them: `--cask wezterm@nightly` or `--cask wezterm` (your pick) and/or `--cask ghostty`

Both WezTerm casks are offered and **nightly is pre-selected** — upstream's newest stable is `20240203-110809`, February 2024. Switching channel uninstalls the other cask first, since both ship `/Applications/WezTerm.app`. Each emulator is a separate tick (`TS_TERMINALS=wezterm-nightly,ghostty|none`); an already-installed one is upgraded rather than reinstalled, and never without being asked. `ts-config wezterm` shows your build, both channels' newest, and what changed. Headless Macs skip the emulator and font casks entirely — there is no window server to render them.

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

### Phase 1 — WezTerm (Windows)

```powershell
winget install --id wez.wezterm.nightly --exact --silent   # or wez.wezterm for stable
wezterm.exe --version
```

Optional — the rest of the stack works without it, under Windows Terminal or an
existing WezTerm. Either channel is fine; the stack asks rather than choosing for
you, and `ts-config wezterm` compares what you have against both channels.

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

Lands via `chezmoi apply`: zsh `ccs` / `ssht`, enhanced interactive `codex`,
`resume`, and `fork` launches, plus `cy` (`codex --yolo`) and `cyr`
(`codex --yolo resume`) in both shells. Utility commands stay stock and
`codex-stock` bypasses the enhancement. In WezTerm interactive Codex adds a
three-line dashboard and Stop TTS. See `doc codex` for the dashboard, one-time
hook trust, and the security trade-off of `--yolo`.

### Phase 6b — Per-computer coding-agent tools

The wizard optionally enables Headroom, Caveman, and AgentMemory at user scope.
Fresh machines default off; the same account can therefore use a Docker-backed
desktop setup on one computer and no local services on another. Scripted answers:

```text
TS_HEADROOM=on|off
TS_HEADROOM_CURSOR=mcp|byok|off
TS_CAVEMAN=on|off
TS_AGENTMEMORY=on|off
```

Terminal-stack never manages the containers. Headroom expects the docker-local
proxy/dashboard on `127.0.0.1:8787` and its HTTP MCP sidecar on `8788`; AgentMemory
expects its REST service on `3111` and viewer on `3113`. Cursor `mcp` keeps
subscription-model traffic direct. `byok` requires a provider API key, separate
provider billing, and a one-time global Cursor provider base URL. Change anything
later with `ts-config agents`; `off` removes active client wiring while preserving
service data, and `uninstall` also removes terminal-stack-owned client packages.

Headroom enable/repair validates the authenticated data plane at `/stats` before
saving `on`; `/readyz` and `/health` alone do not prove agent requests will work.
If the proxy or token breaks, restore direct launches immediately with
`ts-config agents headroom off`. Re-enable with `ts-config agents headroom on`
only after its preflight succeeds. `claude-stock` and `codex-stock` are always
direct one-launch escape hatches.

Verify the client seam after the Docker services are running:

```powershell
ts-config agents headroom status
ts-config agents caveman status
ts-config agents agentmemory status
ts-config agents headroom dashboard
```

Headroom's dashboard labels traffic by the client/provider that made it. A
`claude -p ...` smoke test therefore appears as Claude/Anthropic; a routed Codex
session appears as OpenAI and records Codex WebSocket frames. Start a new agent
session after changing these settings because an already-running process keeps
the environment and instructions it started with.

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
# PrettyMark (GUI markdown viewer, `pm` alias — see Windows PowerShell extras):
winget install --id Eagle1.PrettyMark --exact --silent
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

Open WezTerm, confirm the active tab renders as a solid accent block and the clock shows on the right of the bar (`Ctrl+Space` `s` adds `user@host │ path`). Open a zsh pane, confirm Starship prompt with the branch glyph renders. Open a pwsh pane, run `cc` from a project dir, confirm the tab shows the Claude icon and the bare project name (a coloured state dot appears once Claude starts working).

If you enabled the TTS daemon: `ts-config tts daemon status` should report healthy with the clone's git SHA, and `~/.claude/hooks/cc-tts-test.sh --daemon` (pwsh: `cc-tts-test.ps1 -Daemon`) should speak "Daemon test…". Then prove the never-silence fallback once: `cc-tts-test.sh --daemon-fallback` must still speak through the classic direct path.

Two more, both quick. `ccmute` should report `MUTED`, silence the next announcement, and cut off anything speaking at that moment; `ccmute off` restores it. And the tray's **Open dashboard** should load, with the Status tab reporting the daemon up and the Log tab streaming lines as they happen.

If you use SMB shares: `ts-smb doctor` should report rclone present and name the mount engine it picked, and `ts-smb hosts` should list any SMB server advertising on your network. On macOS, note that a Homebrew-installed rclone **cannot mount** — doctor says so and points at the official binary; browsing and copying work either way.

### Phase 10 — Done

`git log --oneline` shows the prior history. Any subsequent changes you make should land as new commits with marker blocks where they belong.
