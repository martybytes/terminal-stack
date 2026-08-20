# terminal-stack

A reproducible Windows 11 + WSL2 Ubuntu + native Linux (Debian/Ubuntu) + macOS terminal-development stack: WezTerm + tmux + Starship + Claude Code/Codex wrappers + Nerd Font + modern CLI tools, with a single-source-of-truth chezmoi repo that manages config files across all targets.

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

Defaults: Windows and WSL share **one** clone at `%LOCALAPPDATA%\terminal-stack\stack` (visible from WSL as `/mnt/c/Users/<you>/AppData/Local/terminal-stack/stack`); Linux and macOS clone to `~/.local/share/terminal-stack`. Override with `$env:TERMINAL_STACK_DIR` (PowerShell) or `TERMINAL_STACK_DIR=…` (bash) — though the installer steers you off a location **inside a workspace root** (`wso migrate` would relocate the clone out from under the install), and pwsh ignores a pin left in `profile.local.ps1` when no clone lives at it any more. An existing clone at an old location is offered a move to the canonical path. Expects a clean home directory — if you already have a hand-edited `~/.zshrc` or `$PROFILE`, see `INSTALL.md` for the per-step path that preserves user content.

## Configuring (`ts-config`)

The install is a short **wizard** — pick your WezTerm **leader key** (`Ctrl+Space`/`Ctrl+A`/`Ctrl+B`/`Alt+Space`/custom), a **theme** (`dark` Catppuccin Mocha / `light` VS Code Light Modern / `follow` the OS light-dark setting), whether to install **WezTerm** itself (nightly / stable / skip — it is not forced on you, and a stale nightly package falls back to stable), whether panes should be hosted by the **WezTerm multiplexer** (off by default — see `ts-mux`), whether launching WezTerm should **reopen your last session** (off by default), and which **apps** to install (recommended set, everything, a comma-separated list, or none). Every menu marks its default and takes it on Enter, accepts an option's name as well as its number, and re-prompts rather than quietly defaulting when it cannot understand you; a final **review** lets you edit or quit before anything is installed. Choices are saved (chezmoi `[data]` on WSL/Linux/macOS, `%LOCALAPPDATA%\terminal-stack\config.json` on Windows) and survive `ts-update`.

Change them anytime with **`ts-config`** (both shells): run it bare for an interactive menu, or one-shot — `ts-config theme follow`, `ts-config leader ctrl-a`, `ts-config tmux ctrl-a`, `ts-config apps`, `ts-config restore on`, `ts-config show`. It re-applies and installs any newly-selected apps (it never uninstalls). In `follow` mode WezTerm switches light/dark live; the Starship/tmux palette is baked at apply and refreshed by `ts-update`/`ts-config`. In a combined Windows+WSL setup, run `ts-config` from WSL (its `chezmoi apply` is authoritative for the Windows files). Scripted installs skip the prompts with `TS_LEADER` / `TS_THEME` / `TS_WEZTERM` / `TS_WEZ_MUX` / `TS_WEZ_RESTORE` / `TS_APPS` / `TS_CC_TTS` / `TS_CC_TTS_DAEMON` / `TS_HEADLESS`, and `TS_ASSUME_YES=1` (bash) skips the review (see `INSTALL.md` § Install wizard).

**`ts-mux`** (both shells) owns the WezTerm **multiplexer domain** the wizard asks about: whether WezTerm hosts your panes in `wezterm-mux-server` instead of the GUI, so a GUI crash leaves every pane alive. It defaults to **off** — the mux server loads its own copy of `.wezterm.lua` (config changes need `ts-mux restart`, which kills every pane) and mux panes can't render the per-pane Claude tint. `ts-mux on`/`off` flip it and re-apply; `ts-mux` alone reports the setting, the *rendered* setting and the live server; `ts-mux kill`/`restart`/`reset` drive the server itself. From WSL it reaches the Windows-side server over interop, so it works from either shell.

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

**`ts-doctor`** diagnoses a broken install — a chezmoi `sourceDir` pointing at an old/moved clone (the classic "I updated but `doc` says command not found" symptom), a `~/.zshrc`/`$PROFILE` missing the stack block, leftover old clones, or tools off PATH. It's read-only by default; **`ts-doctor --repair`** (pwsh: `ts-doctor -Repair`) repoints `sourceDir`, moves a legacy-path clone to the canonical location (or, when that location is already occupied, switches to the clone there and offers the other for removal), re-applies, and offers to remove old clones and retired files (pre-ticked checklist, one confirmation, `TS_DRY_RUN=1` to preview). The installers run the same checks automatically and prompt for the clone location.

**Manual rollback** (state file missing, or rolling back further than one update):

```sh
git -C <clone> log --oneline -10          # pick the SHA or tag to return to
git -C <clone> reset --hard <sha>         # e.g. v1.0.x tags, or any commit
~/.local/bin/chezmoi apply                # Windows: <clone>\scripts\sync-windows.ps1
```

Two caveats: the clone may double as a dev checkout — commit or stash before any `reset --hard`. And rolling back the *source* doesn't delete files an update introduced (e.g. the git include at `~/.config/git/terminal-stack.gitconfig`); chezmoi simply stops managing them. For a full undo, also `git config --global --unset-all include.path <path>`.

## Developing WezTerm config

WezTerm loads from your home directory, not the clone. On Windows, run `scripts\sync-windows.ps1 -SourceDir <clone>` after editing `windows/.wezterm.lua.tmpl` or `windows/.wezterm/pane_nav.lua`, then reload (`Ctrl+Space` `r` for module changes; the sync prints a reminder when the mux server needs a restart too). On macOS, `chezmoi apply` deploys `dot_wezterm.lua.tmpl` and `dot_wezterm/pane_nav.lua`. See `docs/developing-wezterm.md` for the full loop, the plugin forks, `$env:TERMINAL_STACK_DIR`, and optional auto-sync.

## What you get

- **WezTerm** (nightly by default; stable or skip at install time) with a **taller, hand-drawn fancy tab bar**: the active tab is a solid accent block you can't miss; each tab shows an index, an icon (Claude robot / remote host / foreground process), and a deliberately short title — the bare project leaf for Claude panes, a ` host ·` chip + directory leaf for remote ones, never a full path. Claude tabs carry a coloured dot per pane and tint green when done / red on error (each Claude pane's background tints to match), and inactive tabs flag unseen output. The **hand-rolled status bar** stays quiet: a mode badge appears on the left only while the leader or a repeat mode is live (no permanent `NORMAL`), and the right side shows Claude fleet counts (working/done/error across every pane), the non-default workspace, and a clock — `Ctrl+Space s` adds `user@host │ path`. Integrated window buttons, JetBrainsMono Nerd Font at 11.5pt. **`F1`–`F4` are directions** (left/right/down/up): press to focus the pane that way, or split one into existence if none is there; `Shift+F1`–`F4` always split into a fuzzy-picked SSH/WSL domain, `F5` jumps via a labelled PaneSelect overlay, `F6` swaps panes, and `Ctrl+Space 1`–`6` mirror the F-keys. A **no-timeout leader** (`Ctrl+Space` by default — configurable via `ts-config leader`; peach-cursor "waiting" indicator) drives splits (`h`/`v` local; `H`/`V` into a chosen domain) and **arrow-key repeatable modes** — `Ctrl+Space`+arrows move focus, `+Shift` resizes, `+Ctrl` rotates panes, plus `t`/`f` for tab-switch / font-size — each shown by an on-screen mode badge, all auto-exiting after a short idle. **`Ctrl+Space p`** fuzzy-picks a project workspace (sessionizer over the `wso` tree; needs `fd`), and **`Ctrl+Space S`/`L`** save/restore sessions (resurrect; 15-min autosave — launching WezTerm starts clean unless you run `ts-config restore on`). QoL: QuickSelect patterns for git SHAs and `file:line` refs, hyperlink rules (`owner/repo` → GitHub; Ctrl-click a `file.ext:123` to open it in Cursor), `Ctrl+Shift+↑/↓` jump between shell prompts (OSC 133), `Alt+1…9` tab selection, `Ctrl+V` rebound for synthetic-paste (Wispr Flow, etc.), `Ctrl+Space o` to pop a pane into its own window, and workspace management (`Ctrl+Space R` rename, `Ctrl+Space X` close-all). Windows uses the OpenGL renderer. Panes can optionally be hosted in a **mux server** so a GUI crash doesn't kill your shells — off by default, `ts-mux on` to enable (`ts-mux -h` for status/kill/restart/reset and the trade-offs). The colour theme (Catppuccin **Mocha** dark / **VS Code Light Modern** light / **follow** the OS) is set by `ts-config theme` and switches live in follow mode. On macOS, two System Settings toggles free `Ctrl+Space` and the F-row first — see `INSTALL.md` § macOS.
- **PowerShell 7 `$PROFILE`** with Starship prompt, OSC 7 cwd hint, tilde-abbreviated tab title, UTF-8 console restore (heals Claude-Code `Γ¥»` mojibake), Claude wrappers that set per-tab project titles, and `cyr` for `codex --yolo resume`.
- **WSL zsh** with oh-my-zsh, theme cleared so Starship owns the prompt, a `precmd` that sets tab titles, `ccs` / `ssht` helpers for tmux-attached Claude Code and SSH sessions, and the same `cyr` Codex shortcut.
- **Codex CLI footer recipe** for model/reasoning, project/branch/patch, context and account usage, tokens, permissions, Fast mode, and version. Codex renders one adaptive row rather than Claude's custom three-line footer; see `doc codex`.
- **Claude Code hooks** that drive the WezTerm tab state — the per-pane dots, tab tint, and fleet counts via the `cc_state` user var — and pin the tab title to the project name while Claude runs, symmetric across Windows pwsh and WSL bash.
- **Voice notifications** (opt-in, `ts-config tts on`) — a spoken line when Claude Code or Cursor finishes, errors, or needs you, via local Kokoro TTS with edge-tts fallback. The optional **tray daemon** (`ts-config tts daemon on`) makes them session-aware: it names the project ("terminal-stack two finished"), coalesces simultaneous completions into one utterance, speaks questions immediately, ducks or pauses your music while talking, and can read a one-line summary the model writes itself. Hooks fall back to direct playback whenever the daemon is off or unreachable. See `doc windows/tts-daemon`.
- **Modern CLI tools**: eza, zoxide, fzf, bat, git-delta, ripgrep, `glow` (markdown renderer), the `micro` editor (a friendly nano alternative), and **Neovim** — installed on every target; **Zed** (GUI editor) is an opt-in pick in the app catalog on every platform. Delta is wired into `git diff` and the stack's `git st/lg/lga/br/co/cm` aliases via a managed gitconfig include.
- **tmux** configured for Claude Code passthrough, extended keys, and mouse mode.
- **`lsr` — top-level directories by most recent activity.** Ranks each directory by the newest mtime among its *immediate* children, so a project you edited files inside all day sorts first — unlike `ls -lt`/`eza -s modified`, which sort by the directory's own mtime and bury it. One level deep, never recursive. Both shells; `lsr -a` includes hidden dirs, and `lsrr` caps the list at the 20 most recent. See `doc common/files-disk`.

- **`ws`/`wsp`/`wspu`/`wsw` workspace navigation** that autodetects the workspace root per machine (`$WORKSPACE_DIR` in `~/.zshrc.local` / `profile.local.ps1` overrides it). `wsw` finds the `*_Work`/`*-Work` sibling, and `wsw --set` writes the override for you when work lives elsewhere.
- **`wso` — workspace organizer for many repos across many machines.** Keeps every clone in one derivable tree, `<workspace>/<tier>/github.com/<owner>/<repo>`, where the path is computed from the repo's `origin` remote rather than the folder someone typed once — which is what catches a repo misfiled under the wrong name, the same remote cloned twice under two spellings, or a clone still pointing at a renamed GitHub account. `wso status` is a read-only report of everything dirty, unpushed or detached; `wso plan`/`wso migrate` move an existing mess into the tree as atomic renames that preserve uncommitted work, stashes and untracked files, refusing anything whose destination already exists; `wso sync` is a fast-forward-only bulk update that can never destroy local work; `wso archive`/`wso unarchive` move cold repos to a parallel `archive/` tier behind an interactive checklist and a hard safety gate. `ws37`/`ws42`/`wsmb`/`wsmd`/`wspu`/`wsar` jump to an owner and `wsj` fuzzy-jumps to any repo, which is what makes the deep paths free. Both shells. See `doc common/workspace-org`.
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
├── bootstrap/            # deeper bootstraps + command backends, run from the clone
│   ├── windows-bootstrap.ps1
│   ├── wsl-bootstrap.sh
│   ├── linux-bootstrap.sh
│   ├── mac-bootstrap.sh
│   ├── _common-debian.sh    # shared Debian install helpers (sourced)
│   ├── _config.sh / _config.ps1   # config store, app catalog, prompt helper
│   ├── _wizard.sh           # install-wizard prompts (ts_prompt_choice)
│   ├── _cleanup.sh / _cleanup.ps1 # old-clone checklist; ts_backup_file lives here
│   ├── ts-config.sh         # backend for the `ts-config` shell command
│   ├── ts-doctor.sh         # backend for `ts-doctor`
│   ├── ts-mux.sh            # backend for `ts-mux` (WezTerm multiplexer domain)
│   ├── workspace.conf       # tracked layout map for `wso` (org → tier, renames)
│   ├── _workspace.sh + wso.sh              # `wso` — bash half (WSL/Linux/macOS)
│   └── _workspace.ps1 + _workspace_cmd.ps1 # `wso` — pwsh half (Windows)
├── scripts/
│   └── sync-windows.ps1  # Windows-native port of run_after sync (no WSL needed)
├── docs/                 # design-decision documentation
│   ├── cross-side-chezmoi.md
│   ├── developing-wezterm.md
│   ├── powershell-quirks.md
│   ├── decisions.md
│   └── kb/               # the `doc` knowledge base (common/, linux/, macos/, windows/, wezterm/)
├── dot_zshrc             # ↘ chezmoi-managed (WSL + native Linux + macOS home)
├── dot_zshrc.local.example  # template for per-machine overrides (~/.zshrc.local)
├── dot_tmux.conf.tmpl
├── dot_wezterm.lua.tmpl  # macOS WezTerm config (gated to darwin in .chezmoiignore)
├── dot_wezterm/          # WezTerm Lua modules (pane_nav.lua) — darwin-gated too
├── dot_config/
├── dot_claude/
├── .chezmoi.toml.tmpl    # OS-detection seam → [data].os = wsl|linux|darwin|windows
├── windows/              # ↘ NOT chezmoi-managed; synced by run_after hook (or sync-windows.ps1)
│   ├── .wezterm.lua.tmpl
│   ├── .wezterm/         # pane_nav.lua (Windows mirror)
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
