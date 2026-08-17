# terminal-stack

A reproducible Windows 11 + WSL2 Ubuntu + native Linux (Debian/Ubuntu) + macOS terminal-development stack: WezTerm + tmux + Starship + Claude Code wrappers + Nerd Font + modern CLI tools, with a single-source-of-truth chezmoi repo that manages config files across all targets.

## Quick install

One command per environment. GitHub renders a copy button on each code block (top-right corner on hover). Each installer is idempotent and ends with `chezmoi apply` — a fresh box becomes a working stack in one shot.

**Windows 11** (PowerShell 7+, from an elevated or normal pwsh window):

```powershell
irm https://raw.githubusercontent.com/martybytes/terminal-stack/main/install.ps1 | iex
```

**WSL Ubuntu** (run *after* the Windows step above):

```sh
curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-wsl.sh | bash
```

**Native Debian/Ubuntu**:

```sh
curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-linux.sh | bash
```

**macOS** (Apple Silicon or Intel):

```sh
curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-mac.sh | bash
```

Defaults: the Windows installer clones to `%USERPROFILE%\terminal-stack` (visible from WSL as `/mnt/c/Users/<you>/terminal-stack`); Linux and macOS clone to `~/code/terminal-stack`. Override with `$env:TERMINAL_STACK_DIR` (PowerShell) or `TERMINAL_STACK_DIR=…` (bash). Expects a clean home directory — if you already have a hand-edited `~/.zshrc` or `$PROFILE`, see `INSTALL.md` for the per-step path that preserves user content.

## Configuring (`ts-config`)

The install is a short **wizard** — pick your WezTerm **leader key** (`Ctrl+Space`/`Ctrl+A`/`Ctrl+B`/custom), a **theme** (`dark` Catppuccin Mocha / `light` Latte / `follow` the OS light-dark setting), and which **apps** to install (recommended set or a per-app picker). Choices are saved (chezmoi `[data]` on WSL/Linux/macOS, `%LOCALAPPDATA%\terminal-stack\config.json` on Windows) and survive `ts-update`.

Change them anytime with **`ts-config`** (both shells): run it bare for an interactive menu, or one-shot — `ts-config theme follow`, `ts-config leader ctrl-a`, `ts-config tmux ctrl-a`, `ts-config apps`, `ts-config show`. It re-applies and installs any newly-selected apps (it never uninstalls). In `follow` mode WezTerm switches light/dark live; the Starship/tmux palette is baked at apply and refreshed by `ts-update`/`ts-config`. In a combined Windows+WSL setup, run `ts-config` from WSL (its `chezmoi apply` is authoritative for the Windows files). Scripted installs skip the prompts with `TS_LEADER` / `TS_THEME` / `TS_APPS` (see `INSTALL.md` § Install wizard).

## Updating & rollback

After install, `ts-update` is available in both pwsh and zsh. It fetches, shows the incoming commits, records a rollback point, then pulls and re-applies (honoring your saved `ts-config` choices):

```text
$ ts-update
==> incoming changes:
  a1b2c3d feat: workspace autodetect
==> recorded rollback point: e452f67 (ts-rollback to undo)
```

(PowerShell re-applies via `scripts\sync-windows.ps1` — Windows-side only, no WSL needed. zsh re-applies via `chezmoi apply`.)

Re-running the original install one-liner from § Quick install does the same thing (the installers are idempotent and `git pull` if the clone exists).

**`ts-rollback`** undoes the last `ts-update`: it resets the clone to the recorded SHA (refusing if the clone has uncommitted changes) and re-applies. Run `ts-update` again to return to latest. The rollback point lives at `~/.local/state/terminal-stack/rollback-sha` (zsh) / `%LOCALAPPDATA%\terminal-stack\rollback-sha` (pwsh).

**`ts-doctor`** diagnoses a broken install — a chezmoi `sourceDir` pointing at an old/moved clone (the classic "I updated but `doc` says command not found" symptom), a `~/.zshrc`/`$PROFILE` missing the stack block, leftover old clones, or tools off PATH. It's read-only by default; **`ts-doctor --repair`** (pwsh: `ts-doctor -Repair`) repoints `sourceDir`, re-applies, and offers to remove old clones and retired files (pre-ticked checklist, one confirmation, `TS_DRY_RUN=1` to preview). The installers run the same checks automatically and prompt for the clone location.

**Manual rollback** (state file missing, or rolling back further than one update):

```sh
git -C <clone> log --oneline -10          # pick the SHA or tag to return to
git -C <clone> reset --hard <sha>         # e.g. v1.0.x tags, or any commit
~/.local/bin/chezmoi apply                # Windows: <clone>\scripts\sync-windows.ps1
```

Two caveats: the clone may double as a dev checkout — commit or stash before any `reset --hard`. And rolling back the *source* doesn't delete files an update introduced (e.g. the git include at `~/.config/git/terminal-stack.gitconfig`); chezmoi simply stops managing them. For a full undo, also `git config --global --unset-all include.path <path>`.

## Developing WezTerm config

WezTerm loads from your home directory, not the clone. On Windows, run `scripts\sync-windows.ps1 -SourceDir <clone>` after editing `windows/.wezterm.lua.tmpl` or `windows/.wezterm/pane_grid.lua`, then reload (`Ctrl+Space` `r` for module changes). On macOS, `chezmoi apply` deploys `dot_wezterm.lua.tmpl` and `dot_wezterm/pane_grid.lua`. See `docs/developing-wezterm.md` for the full loop, `$env:TERMINAL_STACK_DIR`, and optional auto-sync.

## What you get

- **WezTerm nightly** with a flat tab bar (each tab labelled `N: <dir>`, tinted green when Claude finishes / red on error; each Claude pane's background tints to match), integrated window buttons, JetBrainsMono Nerd Font at 11.5pt, and a right-status showing `user@host` · workspace · cwd. A **no-timeout leader** (`Ctrl+Space` by default — configurable via `ts-config leader`; peach-cursor "waiting" indicator) drives splits (`h`/`v` local; `H`/`V` into a chosen SSH/WSL domain) and **arrow-key repeatable modes** — `Ctrl+Space`+arrows move focus, `+Shift` resizes, `+Ctrl` rotates panes, plus `t`/`f` for tab-switch / font-size — each shown by an on-screen mode badge. Also `Alt+1…9` tab selection, `Ctrl+V` rebound for synthetic-paste (Wispr Flow, etc.), `Ctrl+Space o` to pop a pane into its own window, the `F1`–`F6` 3×2 grid, and workspace management (`Ctrl+Space R` rename, `Ctrl+Space X` close-all). The colour theme (Catppuccin **Mocha** dark / **Latte** light / **follow** the OS) is set by `ts-config theme` and switches live in follow mode. On macOS, two System Settings toggles free `Ctrl+Space` and the F-row first — see `INSTALL.md` § macOS.
- **PowerShell 7 `$PROFILE`** with Starship prompt, OSC 7 cwd hint, tilde-abbreviated tab title, UTF-8 console restore (heals Claude-Code `Γ¥»` mojibake), and `cc`/`ccc`/`ccd`/`ccdc`/`cca` wrappers that set per-tab project titles.
- **WSL zsh** with oh-my-zsh, theme cleared so Starship owns the prompt, a `precmd` that sets tab titles, and `ccs` / `ssht` helpers for tmux-attached Claude Code and SSH sessions.
- **Claude Code hooks** that flip the WezTerm tab title to `cc ⏳ <project>` while Claude is thinking and `cc ✓ <project>` when it's waiting for your input — symmetric across Windows pwsh and WSL bash.
- **Modern CLI tools**: eza, zoxide, fzf, bat, git-delta, ripgrep, `glow` (markdown renderer), the `micro` editor (a friendly nano alternative), and **Neovim** — installed on every target; **Zed** (GUI editor) on macOS/Windows and opt-in on Linux. Delta is wired into `git diff` and the stack's `git st/lg/lga/br/co/cm` aliases via a managed gitconfig include.
- **tmux** configured for Claude Code passthrough, extended keys, and mouse mode.
- **`ws`/`wsp`/`wspu` workspace navigation** that autodetects the workspace root per machine (`$WORKSPACE_DIR` in `~/.zshrc.local` / `profile.local.ps1` overrides it).
- **`doc` knowledge base** — a tree of markdown command runbooks under `docs/kb/` in the clone (`common/` + per-OS `linux/`/`macos/`/`windows/` + `wezterm/`), rendered by `glow`. `doc` fuzzy-finds a topic, `doc <topic>` opens it, `doc -g` greps, `doc cmd` drops a command straight onto your prompt, and `doc sync` commits your edits back (with a changelog bullet). Personal/secret runbooks live in an untracked `~/.doc.local/` layer. `ref` and `wzr` are thin aliases into it.

## Architecture in 30 seconds

This is a chezmoi repo with a twist: chezmoi natively manages Linux/WSL home (`~/.zshrc`, `~/.tmux.conf`, `~/.config/starship.toml`, `~/.claude/*`), but Windows-side files live in a `windows/` subdirectory excluded from chezmoi's normal apply via `.chezmoiignore`. A `run_after_90-sync-windows.sh` hook then mirrors `windows/` to `/mnt/c/Users/<user>/` and `docs/kb/` to `%LOCALAPPDATA%\terminal-stack\docs\kb\` on every `chezmoi apply` (or `scripts\sync-windows.ps1` on Windows-only), with same-day `.bak.YYYYMMDD[.N]` backups for any file it overwrites. On native Linux and macOS the hook self-no-ops (no `/mnt/c/` mount), so the same source tree drives WSL, native Linux, macOS, and Windows from one apply.

Single source of truth, single `chezmoi apply`, three targets updated. See `ARCHITECTURE.md` for the long version.

## Install (longer paths)

The § Quick install one-liners above are the recommended path. For people who want to read each step before running it, `INSTALL.md` documents two alternatives:

- **Scripted bootstrap** — run each `bootstrap/*` script by hand, then `chezmoi apply`. See `INSTALL.md` § Scripted.
- **Step-by-step walkthrough** — every install step documented with its "why". Slower, but each command is annotated. See `INSTALL.md` § Manual.

For an existing machine with chezmoi already pointed elsewhere, just clone this repo and write `~/.config/chezmoi/chezmoi.toml` with `sourceDir = "<absolute path to your clone>"`.

## Layout

```
terminal-stack/
├── README.md             # this file
├── ARCHITECTURE.md       # cross-side chezmoi, run_after hook, sync semantics
├── CHANGELOG.md          # curated change history
├── INSTALL.md            # scripted + step-by-step install paths
├── LICENSE               # MIT
├── install.ps1           # one-liner Windows installer (irm | iex)
├── install-wsl.sh        # one-liner WSL installer (curl | bash)
├── install-linux.sh      # one-liner native-Linux installer
├── install-mac.sh        # one-liner macOS installer
├── bootstrap/            # deeper bootstraps invoked by the installers
│   ├── windows-bootstrap.ps1
│   ├── wsl-bootstrap.sh
│   ├── linux-bootstrap.sh
│   ├── _common-debian.sh    # shared Debian install helpers (sourced)
│   └── mac-bootstrap.sh
├── scripts/
│   └── sync-windows.ps1  # Windows-native port of run_after sync (no WSL needed)
├── docs/                 # design-decision documentation
│   ├── cross-side-chezmoi.md
│   ├── developing-wezterm.md
│   ├── powershell-quirks.md
│   └── decisions.md
├── dot_zshrc             # ↘ chezmoi-managed (WSL + native Linux + macOS home)
├── dot_zshrc.local.example  # template for per-machine overrides (~/.zshrc.local)
├── dot_tmux.conf
├── dot_wezterm.lua       # macOS WezTerm config (gated to darwin in .chezmoiignore)
├── dot_config/
├── dot_claude/
├── .chezmoi.toml.tmpl    # OS-detection seam → [data].os = wsl|linux|darwin|windows
├── windows/              # ↘ NOT chezmoi-managed; synced by run_after hook (or sync-windows.ps1)
│   ├── .wezterm.lua
│   ├── .config/
│   ├── Documents/
│   └── .claude/
└── run_after_90-sync-windows.sh
```

## Portability

The repo carries no hard-coded usernames. The WSL bootstrap detects your Windows username (via `cmd.exe` interop) and persists it under `[data].windowsUsername` in `~/.config/chezmoi/chezmoi.toml`. The sync hook substitutes that value into `windows/**/*.tmpl` files (e.g., `windows/.claude/settings.json.tmpl`) at apply time, and WSL-side templates use chezmoi's native `{{ .chezmoi.homeDir }}`. See `ARCHITECTURE.md` § "Username resolution" for the resolution order.

Tested on Windows 11 + WSL2 Ubuntu, native Debian/Ubuntu, and macOS (Apple Silicon + Intel).

## License

MIT. See `LICENSE`.
