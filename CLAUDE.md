# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A chezmoi source tree that deploys a Windows 11 + WSL2 Ubuntu + native Linux (Debian/Ubuntu) terminal stack (WezTerm, tmux, Starship, zsh, PowerShell `$PROFILE`, Claude Code hooks/settings, modern CLI tools) from one git repo to three targets with a single `chezmoi apply`. On native Linux the `run_after` Windows-sync hook self-no-ops (no `/mnt/c/` mount), so the same source tree is correct everywhere.

There is no build, no test suite, no lint. "Running" the project means applying configs to the host machine.

## The apply workflow (this repo's equivalent of build/test)

Always run chezmoi **from inside WSL** (not from Windows). The post-apply hook needs a POSIX shell and `/mnt/c/...` to exist.

```sh
~/.local/bin/chezmoi diff      # preview pending changes (WSL targets only — see caveat below)
~/.local/bin/chezmoi apply -v  # apply; runs run_after_90-sync-windows.sh at the end
```

To capture a hand-edit that was made directly to the target (not the source):

```sh
chezmoi re-add ~/.zshrc
chezmoi re-add ~/.claude/settings.json
```

There is no CI. Verification is manual: `docs/verifying-changes.md` is the pre-commit checklist (syntax gates, headless WezTerm config load test, the byte-identical menu diff, throwaway config stores), and `INSTALL.md` § Phase 9 is the post-install smoke test for a fresh machine.

## The architectural twist: one source repo, three targets

chezmoi natively only manages `$HOME` on the machine where it runs. We need Windows `C:\Users\<you>\`, WSL `/home/<you>/`, and native Linux `/home/<you>/` covered by the same source tree. The solution:

1. **WSL- and native-Linux-targeted files** use chezmoi's standard `dot_*` / `dot_config/` / `executable_*` naming at the repo root → applied to `$HOME` normally. The same files cover both: WSL-specific code paths (e.g., `wezterm cli set-tab-title`) are already guarded by `$WEZTERM_PANE` and no-op outside WezTerm, so they're harmless on native Linux servers reached via ssh/PuTTY.
2. **Windows-targeted files** live under `windows/` and are **excluded** from chezmoi's apply by `.chezmoiignore` (`windows/**`).
3. **`run_after_90-sync-windows.sh`** walks `windows/` after each apply and mirrors every file to `/mnt/c/Users/<you>/<same relative path>`, with `.bak.YYYYMMDD[.N]` backups for any overwrite. **On native Linux the hook exits cleanly when `/mnt/c/Users/` is missing** — same script, three platforms.

**Bootstrap split.** `bootstrap/wsl-bootstrap.sh` (WSL) and `bootstrap/linux-bootstrap.sh` (native Debian/Ubuntu) both source the shared `bootstrap/_common-debian.sh` helper for the install steps (apt, oh-my-zsh, chezmoi, Starship, Nerd Font). The wrappers diverge only on Windows-username handling and the default `SOURCE_DIR`.

**Per-machine overrides.** `dot_zshrc` sources `~/.zshrc.local` at the end if it exists; `$PROFILE` dot-sources `Documents\PowerShell\profile.local.ps1` the same way. Neither is tracked by chezmoi — use them for peer-sync helpers, server-role aliases, `WORKSPACE_DIR` overrides, anything that shouldn't propagate. See `dot_zshrc.local.example` / `windows/Documents/PowerShell/profile.local.ps1.example` for the documented patterns.

**Workspace navigation** (`ws`/`wsp`/`wspu`/`wsw`, both shells) resolves at call time: `$WORKSPACE_DIR` if set, else the first existing autodetect candidate (`/mnt/c/DATA/Workspace`, `~/Documents/Workspace`, `~/workspace`, `~/Workspace`; pwsh probes `C:\DATA\Workspace`, `~\workspace`, `~\Documents\Workspace`). Don't convert this to chezmoi templating — `docs/decisions.md` § "Why `$WORKSPACE_DIR` + call-time resolution" explains why it must stay an env var. `wsp`/`wspu`/`wsw` are suffix siblings of that root (`_Personal`/`-Personal`, `_Public`/`-Public`, `_Work`/`-Work`); `wsw` additionally honours `$WORK_WORKSPACE_DIR` and can write it via `wsw --set`.

**Workspace organizer (`wso`).** Keeps repos in `<workspace>/<tier>/github.com/<owner>/<repo>` — implemented twice, `bootstrap/_workspace.sh` + `bootstrap/wso.sh` (bash: WSL/Linux/macOS) and `bootstrap/_workspace.ps1` + `bootstrap/_workspace_cmd.ps1` (pwsh: Windows). The two are parallel implementations, not a wrapper and a shim: change one, change the other, and keep `-h` output byte-identical. Both are chezmoi-ignored (`bootstrap/**`) and run from the clone, so `ts-update` ships fixes without a profile re-sync.

The layout map is `bootstrap/workspace.conf` — **tracked**, so all machines agree — with an untracked per-machine override at `~/.config/terminal-stack/workspace.local.conf` (`%LOCALAPPDATA%\terminal-stack\workspace.local.conf` on Windows) read second, winning key by key. It is whitespace-delimited `<directive> <key> <value>`, deliberately **not JSON**: bash cannot parse JSON without `jq`, and this stays diffable. Don't move it into chezmoi `[data]` — that store is built for scalars, and adding a key there has a 7-step blast radius across `_wizard.sh`, `_config.sh`, `.chezmoi.toml.tmpl`, `_config.ps1`, `ts-config.sh` and both sync scripts.

Two invariants worth not breaking. A repo's destination is derived from its `origin` remote, never the folder name — that is what catches misfiled and double-cloned repos, and `docs/decisions.md` explains why `local/` exists rather than guessing an owner for a remote-less repo. And the tier-name skip in `ts_ws_scan_candidates` / `Get-TsWsScanCandidates` applies **only directly under the workspace root**: a legacy sibling root can legitimately hold a repo named `public` or `local`, and skipping it there would silently drop a real repo from the migration plan.

The jump shortcuts (`ws37`/`ws42`/`wsmb`/`wsmd`/`wsar`/`wsj`, and the repointed `wspu`) must stay shell functions in `dot_zshrc` and `$PROFILE` — a child process cannot change the parent shell's directory.

**Runtime clone location.** The runtime clone — the one `ts-update` pulls and chezmoi applies from — lives at a canonical path: `%LOCALAPPDATA%\terminal-stack\stack` shared by Windows + WSL (WSL sees `/mnt/c/Users/<you>/AppData/Local/terminal-stack/stack`), `~/.local/share/terminal-stack` on native Linux/macOS; pins (`TERMINAL_STACK_DIR`) are only for non-canonical locations. Dev clones at workspace tier paths (e.g. the `wsmb` checkout at `src/github.com/martybytes/terminal-stack`) are **invisible** to resolution, doctor, and doc probes unless pinned — `ts-update` never touches the dev tree. Relocating a legacy-path clone is `ts-doctor --repair`'s job (`ts-update` only prints a notice); rationale in `docs/decisions.md` § "Runtime clone location: canonical app-data paths, invisible dev clones".

Three invariants there earned the hard way, all with `docs/decisions.md` entries:

- **The installers refuse a workspace-root target by default.** `wso migrate` derives a repo's destination from its `origin`, so a clone under the workspace root gets relocated to a tier path and orphans the install. Dev-clone tier paths stay exempt.
- **A *persisted* pin is honoured only while a clone lives at it.** `profile.local.ps1` is dot-sourced by `$PROFILE`, so `irm … | iex` never sees a clean environment — `install.ps1` compares the value against the persisted line to tell a leftover from a deliberate one-shot override. Don't "simplify" that back to `if ($env:TERMINAL_STACK_DIR)`.
- **A dangling env pin degrades, it never dead-ends.** `Resolve-TsSourceDir` / `_ts_src` fall through to the candidate search; an explicit `-SourceDir` still hard-fails. The asymmetry is deliberate.

And `wso` blocks migration of **any** un-tiered terminal-stack clone, not merely the one that resolves as active — `Get-TsWsRuntimeClone` returning `$null` is exactly the broken state where the guard is needed, so it must not be the thing that arms it.

**WezTerm mux domain (`ts-mux`).** Whether panes are hosted by `wezterm-mux-server` instead of the GUI is the saved setting `weztermMux` (`on`|`off`, **default off**). `bootstrap/ts-mux.sh` (zsh wrapper in `dot_zshrc`) and `Invoke-TsMux` in `$PROFILE` are parallel implementations — change one, change the other, keep `-h` byte-identical. Subcommands: `status` (setting vs. *rendered* setting vs. live server), `on`/`off` (persist + re-render), `list`, `kill`, `restart`, `reset`. The install wizard asks the question (`ts_prompt_wezterm_mux` / `Read-TsWeztermMux`, `TS_WEZ_MUX=on|off` to skip, skipped on headless hosts) and the three bash bootstraps persist it with `ts_wez_mux_set` right after `ts_save_config`. Unlike the other config keys it is stored on its own (`ts_wez_mux_set` / `Save-TsConfig -WeztermMux`) rather than through `ts_save_config`, so flipping it doesn't have to re-state every other choice. On WSL the mux server is a **Windows** process: the bash script reaches it through interop (`tasklist.exe`/`taskkill.exe`/`wezterm.exe`), never `pgrep`. Rationale in `docs/decisions.md` § "Why the mux domain is opt-in, not the default".

**WezTerm startup restore (`weztermRestore`).** Whether launching WezTerm replays the last autosaved session is the saved setting `weztermRestore` (`on`|`off`, **default off**), gated in both GUI configs behind `local RESTORE_ENABLED`. The resurrect block deliberately **does not call `resurrect.setup()`** — that helper registers `wezterm.on("gui-startup", …)` unconditionally with no opt-out, which is the whole bug; we drive `event_driven_save` + `periodic_save` directly and register the handler ourselves under the gate. Don't "simplify" it back. Autosave runs either way, so `Leader+S`/`Leader+L` are unaffected and `current_state` keeps tracking the live workspace. Asked by the wizard (`ts_prompt_wezterm_restore` / `Read-TsWeztermRestore`, `TS_WEZ_RESTORE=on|off`, skipped headless), persisted by the bash bootstraps with `ts_wez_restore_set`, flipped later with `ts-config restore on|off`. Rationale in `docs/decisions.md` § "Why the startup session restore is opt-in".

**Update/rollback.** `ts-update` records the pre-pull HEAD to a state file (`~/.local/state/terminal-stack/rollback-sha` / `%LOCALAPPDATA%\terminal-stack\rollback-sha`) before pulling; `ts-rollback` resets the clone to it and re-applies. Both refuse on a dirty clone. The state file is only written when commits are actually incoming.

Source → destination mapping for the `windows/` subtree is **relative-path-preserving**: `windows/.wezterm.lua` → `/mnt/c/Users/<you>/.wezterm.lua`. To add a new Windows-side file, drop it at the mirror path under `windows/` — no script changes needed. Full mechanism in `docs/cross-side-chezmoi.md`.

**Username resolution.** No source file hard-codes a username:

- WSL-side templates (`*.tmpl` under the chezmoi source root, e.g. `dot_claude/settings.json.tmpl`) use chezmoi's native engine — `{{ .chezmoi.homeDir }}`, `{{ .chezmoi.username }}`.
- Windows-side templates (`*.tmpl` under `windows/`, e.g. `windows/.claude/settings.json.tmpl`) use a literal `__WIN_USER__` token that `run_after_90-sync-windows.sh` substitutes at sync time. The username is resolved from (1) `chezmoi data → windowsUsername` (written by the WSL bootstrap), falling back to (2) `cmd.exe /c echo %USERNAME%` via WSL interop. When you add a new Windows-side templated file, use `__WIN_USER__` — not Go-template syntax.

**User config tokens.** The sync hook (and `scripts/sync-windows.ps1`) substitute more than `__WIN_USER__` into Windows-side `.tmpl` files, sourced from the saved config: `__LEADER_KEY__`, `__LEADER_MODS__` (WezTerm leader), `__THEME_MODE__` (`dark`|`light`|`follow`), `__THEME_RESOLVED__` (baked palette `light`|`dark`), `__TMUX_PREFIX__`, `__WEZ_MUX__` (`on`|`off`, the WezTerm mux domain), `__WEZ_RESTORE__` (`on`|`off`, reopen the last session at startup). WSL/native chezmoi templates read the same values as `{{ .leaderKey }}` / `{{ .leaderMods }}` / `{{ .themeMode }}` / `{{ .resolvedTheme }}` / `{{ .tmuxPrefixResolved }}` / `{{ .weztermMux }}` / `{{ .weztermRestore }}` — always behind a `hasKey` guard with a default, so a clone predating the wizard renders today's look (Ctrl+Space, Mocha, mux off, no startup restore). The choices live in chezmoi `[data]` (mirrored to `%LOCALAPPDATA%\terminal-stack\config.json` for Windows-standalone); `.chezmoi.toml.tmpl` re-emits the raw choices and derives the bindings, `resolve_os_theme` (in `bootstrap/_config.{sh,ps1}`) computes `resolvedTheme`. Rendering the Windows-side `.tmpl`s in the WSL hook **requires python3** (the old sed fallback was removed — it couldn't render the multi-line `__CC_TTS_*__` tokens and broke on two-modifier leaders). Wizard = `bootstrap/_wizard.sh` + pwsh prompts in `_config.ps1`; change later via `bootstrap/ts-config.sh` (zsh `ts-config`) / pwsh `Set-TerminalStackConfig`. Every question goes through one menu helper — `Read-TsChoice` (pwsh) / `ts_prompt_choice` (bash), parallel implementations whose **rendered output must stay byte-identical** (diff the two menus; same rule as `wso`). They mark the default, accept an option's name as well as its number, and **re-prompt on invalid input** rather than falling into it — don't restore a `default:` catch-all. `TS_WIZ_ASKED` is tallied in `ts_wizard_ask`, never inside `ts_prompt_choice`: prompts run through `$(…)`, so a subshell increment is discarded. WezTerm is a wizard choice, **not** a required package (nightly's winget manifest goes stale; a failed nightly falls back to stable). Rationale in `docs/decisions.md` §§ "Why config lives in chezmoi `[data]` + a Windows JSON mirror" / "Why WezTerm follows the OS theme live, but Starship/tmux bake at apply time".

**WezTerm config.** The two GUI configs (`windows/.wezterm.lua.tmpl` for Windows, `dot_wezterm.lua.tmpl` for macOS) must stay visually in sync; the pane-nav module (`windows/.wezterm/pane_nav.lua` ↔ `dot_wezterm/pane_nav.lua`, kept in sync) drives the F1–F4 direction keys (focus the pane that way, or split one there), F5/F6 PaneSelect jump/swap, Shift+F1–F4 domain splits, and the Leader+1–6 mirrors. The status bar is **quiet by default**: `wezterm.GLOBAL.show_identity` starts `false`, so only the mode badge shows — Leader+s reveals the workspace (`status_workspace`) and the `user@host │ path` segment (`status_identity`), and both the tabline sections and the hand-rolled fallback go through those two functions so the toggle can never cover one and miss the other. The status bar (tabline.wez), Leader+p project picker (sessionizer.wezterm), and Leader+S/L session save/restore (resurrect.wezterm) are plugins loaded from **pinned forks under `github.com/martybytes`**, each `pcall`-guarded with a fallback — a failed clone degrades (tabline → hand-rolled status; the others lose their binding) instead of breaking the config. Windows renders with OpenGL (WebGpu crashed — see `docs/decisions.md`). The mux domain (`unix_domains` + `default_domain = 'main'`) is **opt-in and off by default**, gated in both configs behind `local MUX_ENABLED` (`__WEZ_MUX__` on the Windows mirror, `{{ .weztermMux }}` on macOS) and driven by `ts-mux` (see **WezTerm mux domain** above). `.wezterm/**` is darwin-gated in `.chezmoiignore`.

**Important caveat:** `chezmoi diff` only shows changes to WSL targets. It does NOT show what the `run_after` hook will sync to `/mnt/c/`. To preview Windows-side changes, compare source manually or just run apply and read the `created`/`updated` lines.

## File-management strategies (don't mix them up)

| File | Strategy | Why |
|---|---|---|
| `~/.zshrc` | whole-file | We own every line (oh-my-zsh template + our additions) |
| `~/.claude/settings.json` (both sides) | whole-file | We own it |
| `~/.tmux.conf`, `~/.config/starship.toml`, `~/.wezterm.lua` | whole-file **template** (`.tmpl`) | We own it; templated for leader/theme/prefix from chezmoi `[data]` (or `__TOKEN__`s on the Windows mirror). Edit the `.tmpl`, not the rendered file |
| `~/.config/git/terminal-stack.gitconfig` (both sides) | whole-file | We own it; hooked via `include.path`, user's `~/.gitconfig` stays untouched and wins |
| `$PROFILE` (Windows pwsh) | whole-file sync, **marker-block edited** | The sync copies the repo file over `$PROFILE` whole (with `.bak`); the `# ---- name-start ----` / `# ---- name-end ----` blocks organize the stack's regions. Personal content belongs in `profile.local.ps1`, never in `$PROFILE` itself |
| `~/.zshrc.local`, `profile.local.ps1`, `~/.doc.local/**` | **never managed** | Per-machine; `.zshrc.local`/`profile.local.ps1` ship `.example` twins; `~/.doc.local` is the personal `doc` layer |

**The `doc` knowledge base.** Command docs are plain `.md` files under `docs/kb/` in the clone (`common/`, `linux/`, `macos/`, `windows/`, `wezterm/`). On Windows, `scripts/sync-windows.ps1` (and the WSL `run_after` hook) also mirror `docs/kb/**` to `%LOCALAPPDATA%\terminal-stack\docs\kb\` so `doc`/`wzr` pick up updates after sync/apply; clone paths (`$TERMINAL_STACK_DIR`, workspace probes) still win for `doc edit`/`doc sync`. `docs/**` is chezmoi-ignored — canonical source stays in the clone. Per-machine/secret content lives in the untracked `~/.doc.local/` layer. `ref` and `wzr` are thin aliases into `doc`.

When modifying `$PROFILE`, edit the repo source (`windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1`) **inside an existing marker block** (`starship-stack-*`, `cli-tools-*`, `git-shortcuts-*`, …) or add a new marker block; keep `local-overrides` last. Anything a user hand-adds to the live `$PROFILE` outside the repo is replaced on the next sync (backed up, but gone from the live file) — per-machine content goes in `profile.local.ps1`. History in `docs/decisions.md` § "Why a whole-file `~/.zshrc` and a marker-block `$PROFILE`?".

## Gotchas worth remembering

These are written up at length in `docs/powershell-quirks.md`; the short version:

- **CRLF drift.** The repo's `.gitattributes` (`* text=auto eol=lf`) overrides Windows' `core.autocrlf=true` and forces LF in the working tree on every platform. Without it, every chezmoi-source file on a Windows clone gets CRLF on checkout, which breaks `~/.zshrc` under zsh (`^M` errors), `run_after_90-sync-windows.sh` (`#!/usr/bin/env bash\r` is not executable), and produces spurious `.bak` files on every apply. Don't remove `.gitattributes`. Rescue path for a single file that slipped through (e.g., an editor that ignored attributes): `sed -i 's/\r$//' <file>` from inside WSL.
- **JSON paths in Claude Code hooks must use forward slashes**, not backslashes. Two shell layers strip backslashes; forward slashes survive. See `windows/.claude/settings.json.tmpl` for examples (`C:/Users/__WIN_USER__/.claude/hooks/...`).
- **Tab title for `cc` wrappers uses `wezterm cli set-tab-title`, not OSC 0.** Claude Code's TUI overwrites `pane.title` (OSC) with its conversation slug; `tab.tab_title` is sticky and survives. The `format-tab-title` hook in both WezTerm configs checks `tab.tab_title` first, falling back to the active pane's cwd leaf.
- **Never auto-restart `wezterm-mux-server`.** When the mux is on, the server loads its own copy of `.wezterm.lua`, so a config change doesn't reach it — but restarting it kills every live pane. The sync scripts print a reminder instead (and only when `weztermMux` is `on`); `ts-mux restart` is the deliberate, confirmed path. Keep it that way.
- **`Enable-TransientPrompt` is guarded with `Get-Command`** because PSReadLine 2.4.5 doesn't export it. Don't remove the guard.
- **Never pipe `Where-Object` straight into `Set-Content`.** An empty pipeline gives `Set-Content` no value to write, so it leaves the file untouched — silently, with no error. Filtering a file down to nothing therefore *keeps* the line you meant to remove. Collect into an array and pass `-Value` (`@()` truncates as intended). A `-replace` pipeline is safe; it can't go empty.
- **`doc`'s alt-e edit binding can't hard-code fzf's `become(...)` action.** `become` (replace the fzf process with `$EDITOR`) only exists in fzf 0.42.0+; Debian/Ubuntu `apt` (what `_common-debian.sh` installs) ships older fzf (e.g. 0.29 on Ubuntu 22.04), where it's an unrecognized action and fzf refuses to start with `unknown action: become(...)`. `_doc_finder` in `dot_zshrc` resolves the bind through `_doc_edit_bind`, which checks the installed fzf version (zsh's `is-at-least`) and falls back to `execute(${EDITOR:-micro} {2})+abort` below 0.42.0 — the same fallback the pwsh side (`Invoke-DocFinder`) already used unconditionally. Don't revert to a bare `become(...)` bind.

## Backup convention

Any script in this repo that overwrites a user file must write a backup first as `<path>.bak.YYYYMMDD`. If that name already exists (same-day re-run), append `.1`, `.2`, etc. Never clobber a same-day backup. Reference implementation: `run_after_90-sync-windows.sh:28-34`. A Phase 7 incident where this discipline was missing motivated the hardening; see `docs/decisions.md` § "Why two backups".

## Where to look

- `README.md` — what the stack delivers, top-level layout
- `ARCHITECTURE.md` — the cross-side problem and our solution in 30s
- `INSTALL.md` — scripted (Phase 0 → 10) and manual install paths
- `CHANGELOG.md` — curated change history; `git log` is authoritative
- `docs/cross-side-chezmoi.md` — deep dive on the chezmoi + run_after mechanism
- `docs/developing-wezterm.md` — edit → sync/apply → reload loop for WezTerm config (Windows `sync-windows.ps1`, macOS chezmoi)
- `docs/powershell-quirks.md` — every weird Windows-side workaround with cause and fix
- `docs/verifying-changes.md` — how to check a change before committing (replaces the missing CI)
- `docs/decisions.md` — design choices that aren't obvious from the code

## Personal-path note

The source tree carries no hard-coded usernames. The WSL bootstrap prompts for the Windows username (default = interop-detected) and persists it under `[data].windowsUsername` in `~/.config/chezmoi/chezmoi.toml`; the sync hook substitutes it into `windows/**/*.tmpl` files at apply time, and WSL-side templates use chezmoi's native `{{ .chezmoi.homeDir }}`. If you ever see a literal username in a source file, that's a regression — replace it with `__WIN_USER__` (Windows side) or `{{ .chezmoi.homeDir }}` (WSL side, file needs `.tmpl` suffix). The `LICENSE` copyright is the one place a real name remains; update on fork if you care.
