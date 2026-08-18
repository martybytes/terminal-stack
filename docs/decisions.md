# Design decisions

Notes on choices made during the original deployment that aren't obvious from reading the code. Order is roughly chronological.

## Why oh-my-zsh with `ZSH_THEME=""`?

oh-my-zsh provides plugin loading (`plugins=(git ...)`), aliases, and a theme. Themes set `PROMPT` directly. Starship sets `PROMPT` to its own callback. The two would compete.

We disable oh-my-zsh's theme by setting `ZSH_THEME=""`, which makes omz a no-op for the prompt. omz still handles plugins (currently just `git`, providing git-aware completions and aliases). Starship owns the prompt.

Alternative considered: drop oh-my-zsh entirely and use raw zsh + zinit/zplug. Rejected because oh-my-zsh is a well-known known-quantity in this codebase, and we're not pushing zsh performance limits.

## Why chezmoi over a plain git dotfiles repo with symlinks?

Plain dotfiles repos with `stow` or symlinks have a problem: they assume your target is `$HOME`. They don't help with the cross-side Windows/WSL issue — you'd need two dotfiles repos or weird symlink chains across `/mnt/c`.

chezmoi gives us:
- Templates (we don't use them yet, but they're available for OS-conditional content).
- Encrypted source files (we don't use, but useful for secrets).
- A `run_after_` script slot that's perfect for our cross-side mirror hook.
- A canonical `chezmoi diff` view of pending changes.
- Built-in `executable_` prefix that handles +x bits without separate scripts.

The cost is one extra concept (`source` vs `target`) but the benefits more than pay for it.

## Why a whole-file `~/.zshrc` and a marker-block `$PROFILE`?

Both files started with user content. `~/.zshrc` is created from scratch by oh-my-zsh during our deployment — we own every line, so whole-file management was always correct: we have the canonical template, re-running loses nothing, `chezmoi diff` shows the full intended state.

`$PROFILE` predated the terminal stack with user-personal content (workspace navigation funcs, zoxide init, `cc` aliases that evolved over time). It was originally managed by marker-block injection so re-running deployment touched only the bracketed regions. That content has since been absorbed into the repo copy (`windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1`), and **the sync mechanism is whole-file**: both sync scripts copy the rendered source over `$PROFILE`, with a `.bak.YYYYMMDD[.N]` backup on every overwrite. Two things keep that safe:

- **Per-machine content lives in `profile.local.ps1`** (dot-sourced at the end of `$PROFILE`, never synced — the Windows counterpart of `~/.zshrc.local`, since v1.1.0). Anything personal that goes into `$PROFILE` itself *will* be replaced on the next `ts-update`/apply — recoverable from the `.bak`, but gone from the live file.
- **The marker blocks remain as editing discipline**, not merge mechanics: they delimit the stack's functional regions (`starship-stack-*`, `cli-tools-*`, `git-shortcuts-*`, …) so an agent or human editing the source knows where each concern lives and adds new ones as new blocks.

If a fresh machine has a pre-existing `$PROFILE`, the first sync backs it up and replaces it — migrate anything worth keeping into `profile.local.ps1`.

## Why per-tab `cc • <project>` instead of one big tab name?

Initial implementation set the tab title to the conversation slug (whatever Claude Code emits via OSC 2). Found this in practice: all CC tabs end up with conversation-slug titles that are hard to map back to "which project is this".

Project-leaf-based titles win for human navigation. When you have five CC sessions across five projects, `cc • netsuite-customizations` / `cc • frontend-app` / `cc • slide-decks` is instantly scannable. Conversation titles like `distinguish-claude-code-tabs-pwsh` look meaningful in isolation but are visually similar across tabs.

The thinking/waiting indicator (`⏳` / `✓`) layered on top via CC hooks gives you state without losing the project signal.

## Why forward slashes in JSON paths?

See `powershell-quirks.md` § "Backslashes in JSON paths get stripped twice". The short version: it's the simplest fix that doesn't depend on knowing which shell layer is eating which characters. Forward slashes are inert in JSON, in POSIX shells, in PowerShell. Backslashes are special in all three.

## Why `wezterm cli set-tab-title` and not OSC 0?

Setting tab titles via OSC 0/2 (the standard terminal way) writes to `pane.title`. Claude Code also writes to `pane.title` (with its conversation slug). Last writer wins. We can't synchronize.

`wezterm cli set-tab-title` writes to `tab.tab_title` (a different WezTerm-internal field). Our `format-tab-title` Lua hook checks `tab.tab_title` first and only falls back to `pane.title` if `tab.tab_title` is empty. So once we set `tab.tab_title`, no OSC stream can dislodge it.

The tradeoff: `tab.tab_title` is sticky. It doesn't automatically reset when CC exits. We handle that in the `cc` pwsh wrapper's `try/finally`, which clears `tab.tab_title` (`Set-WezTabTitle ""`) on CC exit, allowing the formatter to fall through to `pane.title` (which by then is `pwsh • <leaf>` from the next prompt cycle).

## Why two backups (`bak.20260519` and `bak.20260519.original`) for `$PROFILE`?

The `.bak.20260519` backup is the state of `$PROFILE` immediately *before* the most recent overwrite. The `.bak.20260519.original` backup is the original-original pre-deployment state, recovered manually after a Phase 7 incident clobbered the first-day backup.

Going forward, the run_after script's hardened backup logic (see `cross-side-chezmoi.md` § "Backup hardening") prevents this from happening again. New same-day overwrites get `.bak.YYYYMMDD.1`, `.2`, etc.

If you want to clean up the doubled backup name in `$PROFILE`'s directory, delete `.bak.20260519` (the post-Phase-7 state, which is also captured in git history) and leave `.bak.20260519.original` (which is unique).

## Why is `tab_max_width = 120` and not bigger?

Tested at 80 (too tight for tilde-paths in subprojects), 120 (current — fits most paths comfortably), and "infinite via 999" (rejected because it makes WezTerm shrink all tabs proportionally when many are open, defeating readability).

120 cells gives ~14ch margin over the longest expected title (`cc ⏳ ap-bill-automation-standalone`) and leaves room for project name to be the dominant visual signal.

## Why `window_background_opacity = 1.0` (no transparency)?

Originally `0.97` (slight transparency). User rejected after seeing it — the slight bleed-through from background apps hurt readability of code/output. Switched to fully opaque.

If you want transparency back, change to `0.95` or so. Don't go below `0.85` — JetBrainsMono Nerd Font glyphs start to look fuzzy on real-world backgrounds.

## Why `INTEGRATED_BUTTONS|RESIZE` for `window_decorations`?

The original value was `'RESIZE'`, which draws only a resizable border — no OS title bar, and therefore *no* minimize/maximize/close buttons anywhere. That's a clean look but leaves no obvious way to close the window with the mouse. `'INTEGRATED_BUTTONS|RESIZE'` keeps the title-bar-less look but folds the standard window controls into the right edge of the **fancy** tab bar (so `use_fancy_tab_bar = true` is a hard requirement). The buttons (`integrated_title_buttons` defaults to `{ 'Hide', 'Maximize', 'Close' }`, right-aligned) render natively per platform — Windows-style on Windows, the native traffic-lights on macOS — so we set no `integrated_title_button_*` overrides. Applied to both `windows/.wezterm.lua` and `dot_wezterm.lua`.

## Why `LEADER o` to detach a tab instead of dragging it out?

WezTerm has no native mouse "tear-off": you cannot drag a tab off the bar to spawn a new window (long-standing limitation — see GH discussion #4080 and issue #549). The supported equivalent is the Lua `pane:move_to_new_window()`, which we bind to `LEADER o` (`Ctrl+A` then `o`) via `wezterm.action_callback`. `o` was the obvious free letter among the existing leader bindings (`w n \ - h l k j`) and mnemonic for "out". For ad-hoc use without a keybinding, the CLI does the same thing: `wezterm cli move-pane-to-new-tab --new-window`. Bound in both WezTerm configs.

## Why local-only chezmoi git (no remote yet)?

Originally pushed to nowhere. User chose local-first during the repo-promotion step. Adding a private GitHub remote is a follow-up: `git remote add origin git@github.com:<you>/terminal-stack.git && git push -u origin main`.

The Mac sync mentioned at project kickoff is enabled once a remote exists. Until then, manual file copies or local clones over the network.

## Why MIT license?

Standard, permissive, well-understood. The stack contains nothing proprietary. If you fork it for personal use, the source carries no hard-coded usernames (the sync hook resolves the Windows user at apply time — see `cross-side-chezmoi.md` § "Username resolution"). You may want to update the copyright line in `LICENSE`.

## Why `.gitattributes` with `eol=lf` instead of trusting developer git config?

Windows installers typically enable `core.autocrlf=true` at the system level. Without a `.gitattributes`, every git checkout on Windows rewrites every text file in the working tree as CRLF, which then propagates through chezmoi to the WSL home directory. Symptoms on first apply: `zsh ~/.zshrc:N: command not found: ^M` errors on every line, `run_after_90-sync-windows.sh` failing because `#!/usr/bin/env bash\r` is not an executable name, spurious `.bak` files on every subsequent apply because the source and destination differ on phantom line endings.

`* text=auto eol=lf` in `.gitattributes` overrides `core.autocrlf` at the repo level, so cloning is correct regardless of the developer's global config. Binary markers (`*.jpg binary`, etc.) protect non-text files from being touched.

Trade-off: PowerShell `*.ps1` files end up LF too. pwsh accepts both encodings natively, so this is fine. The only consumers that care about CRLF specifically are some legacy `cmd.exe` batch parsers, which we don't ship.

## Why single-source the starship config across Windows and WSL?

Originally there were two divergent `starship.toml` files — `dot_config/starship.toml` had the rounded-frame two-line prompt, `windows/.config/starship.toml` had a stripped-down single-line variant. Maintaining both meant any glyph or layout change had to be made twice and stayed out of sync until someone noticed.

The two sides have always wanted the same prompt structure — only the OS glyph differs at render time (starship auto-detects). So we collapsed to one canonical config at `dot_config/starship.toml` and a byte-identical mirror at `windows/.config/starship.toml`. Both deploy through their respective paths (chezmoi for WSL, `run_after_90-sync-windows.sh` for Windows). Edit `dot_config/starship.toml`, `cp` to the windows mirror, apply.

Trade-off: nothing automatic enforces the mirror — a CI check or pre-commit hook could, but for a single-maintainer repo this hasn't been worth wiring up yet.

## Why P/Invoke for the UTF-8 console codepage, not `[Console]::OutputEncoding`?

The .NET `[Console]::OutputEncoding` property is a cached value. When you set it, .NET calls `SetConsoleOutputCP()` under the hood. When you read it, .NET returns the cached value — it does NOT re-query Win32 to see whether something else (e.g., a native child process like Claude Code) changed the underlying codepage out from under it.

Native console TUIs routinely call `SetConsoleOutputCP()` directly to change the OS-level codepage during runtime, and don't always restore it on exit. After such a child process exits, .NET's cached `OutputEncoding` says "UTF-8" while the OS console is actually at CP437 — and any conditional fix that checks the .NET cache short-circuits as "already UTF-8", skipping the reset, leaving the user staring at `Γ¥»` mojibake.

The P/Invoke version (`Native.ConsoleCP::GetConsoleOutputCP()`) asks the OS directly. It runs once per prompt, costs a few microseconds, and is the authoritative source.

## Why WebGpu front_end (with OpenGL as the documented fallback)?

`WebGpu` is WezTerm's modern default backend and the fastest; both GUI configs (`windows/.wezterm.lua` and `dot_wezterm.lua`) set it explicitly.

One known failure mode is kept here because it bit us once. On some Intel iGPU drivers (reproduced on an earlier Windows 11 setup, May 2026) WebGpu had an output-buffer queueing behavior where rapid post-redirect output from a child process (Claude Code starting up, a large `cat` of a colored log) didn't trigger an immediate redraw — the buffer flushed only on the next input event, so "type `ccd`, hit Enter, nothing happens; hit space and Claude Code's whole intro screen appears at once." We switched to `OpenGL` for a while (commit `7922da8`); a later WezTerm-nightly / driver update cleared it and the configs returned to WebGpu.

If that startup stall ever reappears, the fix is a one-liner — set `config.front_end = 'OpenGL'` in the affected platform's `.wezterm.lua` (the comment beside the setting points here). OpenGL trades slightly less polished scrolling under load for immunity to the stall; macOS (Metal-backed WebGpu) never had the issue.

## Why not just use a single GUI tool like Microsoft Terminal?

Microsoft Terminal is fine, but:
- WezTerm has better Lua-based programmability.
- WezTerm's fancy tab bar with custom format hooks beats MT's tab UI.
- WezTerm has better support for WSL launching with shell-specific args (the `launch_menu` entries).
- WezTerm renders better on high-DPI displays (subjective).

If MT is what you actually want, this repo's chezmoi side will still mostly work — you'd just skip the `.wezterm.lua` deployment and accept that MT's config (in `settings.json` under `%LOCALAPPDATA%\Packages\Microsoft.WindowsTerminal_...`) is a separate concern.

## Why guard `ws*` on `/mnt/c` existence rather than `$WSL_INTEROP`?

The five zsh workspace-nav functions (`ws`, `wsp`, `wspu`, `wscalibra`, `wsnetsuite`) only make sense on WSL where the Windows-side workspace tree is mounted at `/mnt/c/DATA/Workspace*`. The same `dot_zshrc` ships unchanged to native Debian/Ubuntu servers via `bootstrap/linux-bootstrap.sh`, where `/mnt/c` doesn't exist. Three plausible guards:

1. `grep -qi microsoft /proc/version` — detects WSL kernel.
2. `[[ -n "$WSL_INTEROP" ]]` — detects WSL with Windows interop enabled.
3. `[[ -d /mnt/c/DATA/Workspace ]]` — detects the actual path the functions would `cd` into.

We use (3). It's the loosest filter on platform identity but the tightest on *what could go wrong*: if WSL is present yet the workspace tree happens to live elsewhere (fresh clone of the dotfiles onto a new WSL distro before the workspace is laid down, or a coworker forking the repo whose layout differs), (1) and (2) would still define functions that error on call. (3) only defines them when calling them will actually work.

The cost is one stat at shell startup. On WSL with `/mnt/c` cached it's microseconds; on native Linux it's a quick negative result. Cheap enough that the same pattern should be the default for any future Windows-path shortcut we port to zsh — guard on the specific path, not on platform.

**Superseded in v1.1.0:** the `ws*` functions are now always defined and resolve the workspace at *call* time via `_ts_workspace()` (env override → candidate probe). The guard-on-path philosophy survives inside the resolver — it still only `cd`s into directories that exist — but the functions themselves no longer disappear on machines where the startup-time probe failed. See "Why `$WORKSPACE_DIR` + call-time resolution instead of chezmoi templating?" below.

## Why `$WORKSPACE_DIR` + call-time resolution instead of chezmoi templating?

Workspace location varies per machine (`C:\DATA\Workspace` on the PC, `~/Documents/Workspace` on the Mac, `~/workspace` on Linux servers). Two ways to make `ws` work everywhere:

1. chezmoi `[data].workspaceDir` + `dot_zshrc.tmpl` — bake the path in at apply time.
2. `$WORKSPACE_DIR` env var checked at call time, autodetect candidate list as fallback.

We use (2). Templating fails three ways that the env var doesn't: it requires `chezmoi apply` to change the path (the env var is live on the next prompt); it does nothing for machines that get the `.zshrc` *without* chezmoi (the lambda-dual ↔ internal `dot-push` rsync flow ships the rendered file); and `~/.zshrc.local` — where the override belongs, per the existing per-machine-overrides convention — is sourced at the *end* of `.zshrc`, so any startup-time resolution would run before the override exists. Call-time resolution costs a few stats per `ws` invocation, which is noise for an interactive cd.

The installer only persists `WORKSPACE_DIR` to `~/.zshrc.local` when the user's answer differs from what autodetect would find — a machine whose workspace is in a standard location carries zero local config.

## Why does `ts-rollback` use a recorded SHA file instead of `git reflog`?

`ts-update` writes the pre-pull HEAD to `~/.local/state/terminal-stack/rollback-sha` before pulling, and `ts-rollback` resets to exactly that. The alternative — `git reset --hard HEAD@{1}` — is shorter but wrong in practice: the reflog entry one back is whatever git did last, which after a few manual operations in the clone (branch switches, amends on a dev machine where the clone doubles as a checkout) is not "the state before the last ts-update". An explicit file is unambiguous, human-inspectable (`cat` it to see where rollback would land), and survives `git gc`. The file is only written when an update actually has incoming commits, so a no-op `ts-update` can't clobber a real rollback point. Both commands refuse to run over a dirty working tree for the same dev-checkout reason.

## Why convert zsh `cc*` from aliases to functions just for the tab title?

Aliases can't run code around the wrapped command. Setting and clearing the WezTerm tab title requires a pre-step and a post-step around the `claude` invocation. Either we (a) leave zsh as plain aliases and accept that only the PowerShell side gets the `cc • <leaf>` tab title, or (b) promote zsh to functions matching the PowerShell try/finally pattern. We chose (b) for the same reason the PowerShell side does it: when you have four or five Claude panes open in WezTerm under WSL, the tab title is what tells you which project each pane is for. Without it the tabs are all just `pwsh` / `zsh` and you have to click each one to remember. The cost is a one-line helper (`_wez_tab_title`) and a small amount of bookkeeping (`local rc=$?; ... return $rc`) since zsh has no `try/finally` — that bookkeeping matters because without it the function would always exit 0 and mask Claude's exit code from scripts that wrap it.

The `cc • <leaf>` text and the per-prompt clearing behavior are covered separately under "Why per-tab `cc • <project>` instead of one big tab name?" and "Why `wezterm cli set-tab-title` and not OSC 0?" — this entry is just about *why functions, not aliases*.

## Why Claude Code TTS is opt-in chezmoi data (not a sentinel file)

Like tab tinting, TTS is stack infrastructure — but unlike `ccnotify` (a sentinel file users toggle without re-apply), **enabling TTS adds hooks to the managed whole-file `settings.json`**. Conditional chezmoi template blocks keyed on `ccTtsEnabled` mean `ts-config tts off` + apply truly removes the hooks; no orphan processes or stale sentinel files. Runtime knobs live in **`~/.claude/tts/config.json`** (chezmoi-rendered) with optional untracked **`local.json`** merged at hook time — not in the template files themselves. **Async-only:** hooks spawn background workers and return immediately. **WSL playback goes through Windows interop** because Docker forwards `:8880` but audio devices do not.

**Hooks vs MCP:** lifecycle alerts (stop, AskQuestion, permission) must stay **hooks** — IDEs fire those events; an MCP server would not hear them unless the model voluntarily called it. A future **terminal-stack-tts MCP** can share the same `cc-tts-lib` for on-demand `speak` from Claude Desktop / Co-work; it complements hooks rather than replacing them.

## Why `settings.json` ships only shared infra — no model, prefs, permissions, or plugins

`~/.claude/settings.json` is managed whole-file (see "Why a whole-file `~/.zshrc` and a marker-block `$PROFILE`?"), so on every `chezmoi apply` the live file is replaced by the tracked template. That makes the template a poor place for anything you'd want to *choose per machine or per session* — the apply silently reverts it. So the tracked templates carry **only** the things that are genuinely part of this terminal stack: the `statusLine` command, the `wez-tab-status` hooks, and (when `ccTtsEnabled`) the `cc-speak` TTS hooks. Everything that is a personal choice is deliberately kept out:

- **Model, `effortLevel`, `theme`, `tui`, `autoUpdatesChannel`, voice** — per-user preferences set through the Claude UI (`/model`, `/config`). Baking them in meant every apply clobbered whatever you'd picked.
- **Permission posture** (`permissions.defaultMode`, `skipDangerousModePermissionPrompt`, `skipAutoPermissionPrompt`) — left at Claude Code's safe defaults. A shared dotfiles repo shouldn't silently auto-approve tool calls or strip the dangerous-mode guard on every machine it lands on.
- **Plugins** (`enabledPlugins` + `extraKnownMarketplaces`, e.g. `claude-obsidian`, `gitkraken-hooks`) — enablement is a live, per-machine choice made via the `/plugin` UI, and the claude-obsidian marketplace pointed at a machine-specific local path (`C:/DATA/Workspace_Public/claude-obsidian`) that wouldn't resolve on a fork. Whole-file management can't merge live plugin writes, so the clean answer is to not track them and let your live file own them.

An earlier version of this entry argued the opposite — that the template should *track* the plugin blocks so an apply wouldn't disable them. That traded one surprise (apply disables your plugins) for a worse one (apply re-imposes a model, a permission mode, and third-party integrations you didn't pick on this machine). The rule now: **the repo owns infrastructure; you own preferences.** If you re-enable a plugin or set a model, it lives in your live `~/.claude/settings.json` and the repo leaves it alone.

The companion machine-state notes for the GitKraken integration (the AI-hook log flood, the 0-byte `gk.exe` symlink) remain in `powershell-quirks.md` § "GitKraken `gk ai hook` plugin" for anyone who opts back in.

## Why Starship and prompt chrome are skipped in agent shells

Cursor Agent (and similar capture runners) intentionally set `TERM=dumb` and `CURSOR_AGENT=1`. The shell is not interactive — it exists so the IDE can run commands and parse plain-text stdout. Starship detects `TERM=dumb`, refuses to render, and logs `[ERROR] - (starship::print): Under a 'dumb' terminal` to stderr on every invocation. That noise pollutes agent transcripts without helping the model.

The fix is **not** to force `TERM=xterm-256color` in agent shells (Cursor sets `dumb` by design; fighting it breaks output parsing) and **not** to drop the full profile (agents still benefit from git shortcuts, zoxide, UTF-8 setup, workspace nav). Instead, `Test-TsAgentShell` / `_ts_agent_shell` guard only the prompt layer: Starship init, transient prompt, and OSC 7/0 title sequences. Interactive WezTerm and the Cursor bottom-panel terminal are unchanged.

The existing `plain` escape hatch (`pwsh -NoProfile` / `zsh -df`) remains for humans who want a completely vanilla shell; agent detection is automatic and lighter-weight.

## Why Cursor IDE settings use merge, not whole-file

`%APPDATA%\Cursor\User\settings.json` holds personal choices — theme, fonts, editor prefs — alongside stack infrastructure. Whole-file management (the pattern used for `~/.claude/settings.json` infra keys) would clobber those on every sync.

The stack ships a **fragment** at `windows/AppData/Roaming/Cursor/User/terminal-stack.terminal.json` containing only stack-owned terminal keys (`terminal.integrated.automationProfile.windows`). `bootstrap/_merge_cursor_settings.ps1` shallow-merges those keys into the live settings file, backing up before write. This complements the profile guard: `automationProfile` covers VS Code/Cursor task automation (`pwsh -NoProfile`); agent shells still load `$PROFILE` but skip Starship via `Test-TsAgentShell`.

## Why a separate `dot_wezterm.lua` for macOS

WezTerm reads `~/.wezterm.lua` from the home directory of whatever machine the GUI runs on. On Windows that's `C:\Users\<you>\.wezterm.lua`, deployed from `windows/.wezterm.lua` by the sync hook. On WSL the GUI is still the *Windows* WezTerm, so WSL's Linux home gets no WezTerm config at all — correct, because nothing there would read it. On macOS, WezTerm runs natively and reads the macOS home directory, so the Mac genuinely needs its own `~/.wezterm.lua`.

Three ways to produce it:

1. **Sync `windows/.wezterm.lua` to the Mac too.** Rejected — that file hardcodes `default_prog = { 'pwsh.exe' }` and a `launch_menu` with `wsl.exe`. Neither exists on macOS; WezTerm would error or spawn nothing.
2. **One `.tmpl` that forks on `.chezmoi.os`.** Workable, but the Windows file isn't chezmoi-managed at all (it lives under `windows/` and ships via the sync hook), so there's no single file to template — the Windows and non-Windows copies travel different roads by design.
3. **A standalone `dot_wezterm.lua`** at the chezmoi root, applied only on macOS.

We chose (3). The new file mirrors `windows/.wezterm.lua`'s visual settings (font stack, Catppuccin Mocha, flat tab bar, leader key, pane keys, `format-tab-title` / `update-right-status`, `front_end`) and intentionally diverges in exactly two places: it omits `default_prog`/`launch_menu` (macOS defaults to the login shell), and its final font fallback is `Menlo` instead of `Cascadia Code` because Menlo ships with macOS and Cascadia does not.

Native-Linux hosts in this stack are headless (reached over ssh/PuTTY) and run no WezTerm GUI, so applying `~/.wezterm.lua` there would just litter the home directory with a dead file. To prevent that, `.chezmoiignore` — which chezmoi evaluates as a template — gained a `{{ if ne .chezmoi.os "darwin" }} .wezterm.lua {{ end }}` block. The file is therefore applied on macOS only. The gate keys off the built-in `.chezmoi.os`, not `[data].os`, so it works even when the bootstrap-written `chezmoi.toml` omits the `[data]` section.

Trade-off: like the single-sourced `starship.toml`, nothing automatic keeps `dot_wezterm.lua` and `windows/.wezterm.lua` visually in sync — a shared change has to be made in both. `dot_wezterm.lua`'s header comment says so.

One macOS-only caveat lives *outside* the config. macOS reserves both the `Ctrl+Space` leader (the system *Input Sources → "Select the previous input source"* shortcut) and the bare `F1`–`F6` pane-grid keys (hardware media keys), intercepting them before WezTerm sees the keystroke — so out of the box every `Ctrl+Space …` binding and the F-key grid look dead, and the `Ctrl+Space 1`–`6` F-key fallback (which routes through the same leader) dies with them. We keep the bindings byte-identical to the Windows side rather than picking Mac-specific keys — cross-platform muscle memory wins — and push the resolution to two System Settings toggles (enable standard function keys; free the `Ctrl+Space` input-source shortcut), documented in `INSTALL.md` § macOS and the darwin block of the command reference.

## Why `doc` replaced the command-reference render pipeline

The command reference began as a single per-OS-gated markdown (`command-reference.md.tmpl` + a standalone Windows twin) that a bash renderer (`render-command-reference.sh`, bash + POSIX awk) expanded into committed `.txt`/`.html` twins **and** per-OS previews under `docs/command-reference/`, kept honest by two warn-only staleness checks (`run_after_10-*` on POSIX apply, a hash-check in `sync-windows.ps1`). It worked, and it bought three viewing formats (console/browser/Obsidian) that never drifted. But every content edit meant re-running the renderer and committing four-plus generated files, and the previews required the renderer to *shadow* chezmoi's `{{ if eq/ne .chezmoi.os }}` resolution with an embedded awk resolver — a deliberate but real maintenance tax, and a frequent source of "twins are stale" warnings.

`doc` retires all of it. Command docs are now plain `.md` topic files under `docs/kb/` (`common/` + per-OS `linux/`/`macos/`/`windows/` + `wezterm/`), read **in place** from the clone by the `doc` command — `docs/**` is already chezmoi-ignored, so there is no deploy step, no `.txt`/`.html` generation, no previews, and no staleness check. Per-OS selection moved from apply-time template gates to **runtime** (`doc` shows `common/` + the current OS; `--os` browses another); the dual-format twins became unnecessary because `glow` renders the `.md` directly and `doc -g` / `doc cmd` cover search and command-reuse. Editing a doc is just editing a file; `doc sync` stages it with an auto `### Docs` CHANGELOG bullet and an optional push. Per-machine/secret content moved from the untracked `command-reference.local.md` to a `~/.doc.local/` tree the viewer merges in. `ref` and `wzr` became thin aliases into `doc`. The render script, the `.md`/`.txt`/`.html` sources/twins, the previews, and both check hooks were deleted.

Trade-off: the browser/Obsidian `.html` export is gone. It was the weakest-justified part of the old pipeline (browsability only, no structural need), and in-terminal `glow` covers the day-to-day; an on-demand `doc export <topic>` could bring HTML back if it's ever missed.

## Why "kill workspace" shells out to `wezterm cli` (and rename doesn't)

`Ctrl+Space X` ("delete this workspace" = close all its panes) can't be done in pure Lua: `CloseCurrentTab`/`CloseCurrentPane` act only on the GUI's *active* pane, and the mux API exposes no tab/workspace close (wezterm/wezterm discussion #5907). The binding therefore collects every pane id in the target workspace from the mux, switches the GUI to another workspace first (so closing the last window doesn't quit WezTerm), then kills the collected panes with `wezterm cli kill-pane --pane-id <id>` via `wezterm.run_child_process`. The only per-file difference between the two configs is the binary name — `wezterm` (macOS) vs `wezterm.exe` (Windows) — held in a `WEZTERM_CLI` local. It refuses to run when the current workspace is the only one. `rename`, by contrast, is a clean one-liner (`wezterm.mux.rename_workspace`).

## Why config lives in chezmoi `[data]` + a Windows JSON mirror

The wizard/`ts-config` choices (leader chord, theme mode, tmux prefix, app selection) need to survive every `ts-update` and be readable by *all* the apply paths. The stack already had exactly the right bridge: chezmoi `[data]` in `~/.config/chezmoi/chezmoi.toml` — the same place `windowsUsername` is stored and consumed by the WSL `run_after` hook to render Windows-side files. So the choices live there too. `.chezmoi.toml.tmpl` re-emits them (so a bare `chezmoi init` doesn't drop them) and *derives* the concrete bindings — `leaderChord "ctrl-space"` → `leaderKey "phys:Space"` + `leaderMods "CTRL"`, `tmuxPrefix "ctrl-b"` → `tmuxPrefixResolved "C-b"` — in one Go-template mapping. WSL/native chezmoi templates read them directly (`{{ .leaderKey }}`); the WSL hook reads them via `chezmoi execute-template` and substitutes `__LEADER_*__`/`__THEME_*__`/`__TMUX_PREFIX__` tokens into the Windows `.tmpl` files (same mechanism as `__WIN_USER__`).

The wrinkle: a **Windows-standalone** install (no WSL) never runs chezmoi, so it can't read chezmoi `[data]`. That path gets a JSON mirror at `%LOCALAPPDATA%\terminal-stack\config.json` (next to the existing `rollback-sha`), written by `windows-bootstrap.ps1` / the pwsh `ts-config` and read by `scripts/sync-windows.ps1`. To keep the two stores from drifting in a **combined** Windows+WSL setup, the WSL side is authoritative: `ts_save_config` (bash) also writes the Windows `config.json` mirror when `/mnt/c/Users/<user>` exists, and the docs tell you to run `ts-config` from WSL. Defaults are baked into every consumer (`hasKey` guards in the templates, `cfg <key> <default>` in the hook, fallbacks in `sync-windows.ps1`), so a clone that predates the wizard renders today's behaviour (Ctrl+Space, Mocha) until you run it.

A single dedicated config file (one TOML/JSON on every platform) was the alternative. Rejected: it would duplicate the cross-side plumbing that chezmoi `[data]` + the sync hook already provide for `windowsUsername`, and chezmoi templates can't cleanly read an arbitrary external file on every apply. Reusing the existing bridge keeps the mapping in one Go template and the I/O in `bootstrap/_config.{sh,ps1}`.

## Why WezTerm follows the OS theme live, but Starship/tmux bake at apply time

`follow` mode means "track the OS light/dark setting." WezTerm can do this *live*: `wezterm.gui.get_appearance()` returns `Dark`/`Light`, and WezTerm re-evaluates the config when the OS appearance changes — so `.wezterm.lua` carries both palettes (Catppuccin Mocha + Latte) and a `pick_palette(mode)` that flips the whole UI (scheme, tab bar, status line, Claude tints) with no re-apply. Only the *mode* (`themeMode`) is injected.

Starship and tmux can't: their configs are static files with no runtime OS-theme hook (Starship picks one `palette` at load; tmux reads a fixed status style). Querying the OS theme on every shell start was rejected — it adds startup latency to every prompt and OS detection from inside WSL is unreliable. So for those two the palette is **baked**: a `resolvedTheme` (`light`|`dark`) is computed once at apply time (`resolve_os_theme` reads the Windows registry / `defaults` / `gsettings`; `follow` resolves to the current OS theme, fixed modes resolve to themselves) and written into the store. `ts-update` and `ts-config` re-run that resolution (`ts_refresh_resolved_theme` / `Update-TsResolvedTheme`) and re-apply, so a `follow` user who toggles the OS theme picks up the new shell palette on the next update — while WezTerm has already switched live. The asymmetry is intrinsic to what each tool exposes, not a shortcut.

## Why a re-run repoints `sourceDir` (and why `ts-doctor` exists)

The original bootstraps refused to touch an existing `~/.config/chezmoi/chezmoi.toml` ("already exists; not overwriting sourceDir"). That looked conservative but caused a silent, confusing failure: install once to `~/terminal-stack`, later re-run the installer (which now clones to `~/code/terminal-stack`), and chezmoi keeps applying from the *old* clone. A clone that predates a feature (e.g. `doc`) therefore never delivers it, and `chezmoi apply` prints no changes because the old source already matches the target — the user sees "I updated, why is `doc` not found?".

The fix is to treat `sourceDir` as something the installer **owns and corrects**, not something it tiptoes around: `ts_ensure_source_dir` rewrites only the `sourceDir` line (preserving the `[data]` block — leader/theme/apps/`windowsUsername`) when it differs. This lives in `_config.sh` and is shared by all three POSIX bootstraps, so the three near-identical toml-writing blocks collapsed to one. `ts-doctor` is the standing version of the same check for an existing install: it verifies `sourceDir` resolves to a real terminal-stack clone (and the *intended* one), that `~/.zshrc`/`$PROFILE` actually carry the stack, and that tools are present — then `--repair` repoints and re-applies. Windows has no `chezmoi.toml`, so its analogue persists `$env:TERMINAL_STACK_DIR` to `profile.local.ps1` instead.

## Why re-clone fresh (not adopt-in-place) when an old clone is found

When the installer finds an old clone at a different path, it clones fresh to the chosen location and *offers to delete* the old one, rather than adopting the old clone where it sits. Adopt-in-place is less disruptive but inherits whatever state the old clone carried — a detached HEAD, a half-finished rebase, a wrong branch, local edits — and silently makes that the source of truth. A fresh clone is guaranteed to be `main` at a known-good commit, which is what an *installer* (as opposed to `ts-update`) should guarantee. Deletion is never automatic: the cleanup checklist shows each old clone's last commit, pre-ticks it, and removes nothing without an explicit confirmation; the keep-list (`~/.zshrc.local`/`profile.local.ps1`, `~/.doc.local`, rollback state, `*.local.md`) is never offered.

## Why headless is auto-detected (and what it changes)

Native Linux already skips the WezTerm *program* (only macOS/Windows install it), but the bootstrap still downloaded a ~30 MB Nerd Font and ran `fc-cache` on every server, and the wizard still asked for a WezTerm leader key — neither of which means anything on a box with no GUI terminal. We auto-detect headless (no `$DISPLAY`/`$WAYLAND_DISPLAY` and either an SSH session or a non-graphical systemd target; WSL is explicitly *not* headless because it renders in a Windows GUI terminal) rather than adding a flag, because the common case — `curl … | bash` on a fresh server over ssh — has no one around to pass a flag. Detection is **confirmed, not silent**: the bootstrap prints what it concluded and lets the user flip it on `/dev/tty`, and `TS_HEADLESS=1|0` forces it for unattended runs. Headless mode skips only the GUI-only steps (font + leader prompt); tmux, Starship, zsh, and the CLI tools — the things that make a server pleasant over ssh — still install.
