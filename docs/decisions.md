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

Project-leaf-based titles win for human navigation. When you have five CC sessions across five projects, `netsuite-customizations` / `frontend-app` / `slide-decks` is instantly scannable. Conversation titles like `distinguish-claude-code-tabs-pwsh` look meaningful in isolation but are visually similar across tabs.

The thinking/waiting indicator (`⏳` / `✓`) layered on top via CC hooks gives you state without losing the project signal.

**Amended with the 2026-08 tab-bar redesign:** the `cc • ` prefix (and the state glyph in the title) turned out to waste tab width for zero information — the tab bar's Claude icon and per-pane state dots already say "Claude" and its state. The wrappers and hooks now set the **bare project leaf** as the title; the project-leaf-over-conversation-slug reasoning above is unchanged. `strip_cc_prefix` in both configs keeps titles from not-yet-updated machines rendering clean.

## Why forward slashes in JSON paths?

See `powershell-quirks.md` § "Backslashes in JSON paths get stripped twice". The short version: it's the simplest fix that doesn't depend on knowing which shell layer is eating which characters. Forward slashes are inert in JSON, in POSIX shells, in PowerShell. Backslashes are special in all three.

## Why `wezterm cli set-tab-title` and not OSC 0?

Setting tab titles via OSC 0/2 (the standard terminal way) writes to `pane.title`. Claude Code also writes to `pane.title` (with its conversation slug). Last writer wins. We can't synchronize.

`wezterm cli set-tab-title` writes to `tab.tab_title` (a different WezTerm-internal field). Our `format-tab-title` Lua hook checks `tab.tab_title` first and only falls back when it is empty — to the active pane's cwd leaf, then `pane.title`. So once we set `tab.tab_title`, no OSC stream can dislodge it.

The tradeoff: `tab.tab_title` is sticky. It doesn't automatically reset when CC exits. We handle that in the `cc` pwsh wrapper's `try/finally`, which clears `tab.tab_title` (`Set-WezTabTitle ""`) on CC exit, allowing the formatter to fall through to the pane's cwd leaf.

## Why two backups (`bak.20260519` and `bak.20260519.original`) for `$PROFILE`?

The `.bak.20260519` backup is the state of `$PROFILE` immediately *before* the most recent overwrite. The `.bak.20260519.original` backup is the original-original pre-deployment state, recovered manually after a Phase 7 incident clobbered the first-day backup.

Going forward, the run_after script's hardened backup logic (see `cross-side-chezmoi.md` § "Backup hardening") prevents this from happening again. New same-day overwrites get `.bak.YYYYMMDD.1`, `.2`, etc.

If you want to clean up the doubled backup name in `$PROFILE`'s directory, delete `.bak.20260519` (the post-Phase-7 state, which is also captured in git history) and leave `.bak.20260519.original` (which is unique).

## Why is `tab_max_width = 120` and not bigger?

Tested at 80 (too tight for tilde-paths in subprojects), 120 (current — fits most paths comfortably), and "infinite via 999" (rejected because it makes WezTerm shrink all tabs proportionally when many are open, defeating readability).

120 cells gives ~14ch margin over the longest expected title (`ap-bill-automation-standalone`) and leaves room for project name to be the dominant visual signal.

**Retro-bar only since the 2026-08 fancy-bar redesign:** the fancy bar ignores `tab_max_width` and sizes tabs to content (labels are hard-truncated to 28 chars in `format-tab-title` instead). The value stays for the retro fallback.

## Why `window_background_opacity = 1.0` (no transparency)?

Originally `0.97` (slight transparency). User rejected after seeing it — the slight bleed-through from background apps hurt readability of code/output. Switched to fully opaque.

If you want transparency back, change to `0.95` or so. Don't go below `0.85` — JetBrainsMono Nerd Font glyphs start to look fuzzy on real-world backgrounds.

## Why `INTEGRATED_BUTTONS|RESIZE` for `window_decorations`?

The original value was `'RESIZE'`, which draws only a resizable border — no OS title bar, and therefore *no* minimize/maximize/close buttons anywhere. That's a clean look but leaves no obvious way to close the window with the mouse. `'INTEGRATED_BUTTONS|RESIZE'` keeps the title-bar-less look but folds the standard window controls into the right edge of the tab bar. (This originally rode on the fancy tab bar; the tabline.wez era ran the retro bar, and the 2026-08 hand-rolled redesign returned both configs to the fancy bar — the integrated buttons render in either.) The buttons (`integrated_title_buttons` defaults to `{ 'Hide', 'Maximize', 'Close' }`, right-aligned) render natively per platform — Windows-style on Windows, the native traffic-lights on macOS — so we set no `integrated_title_button_*` overrides. Applied to both `windows/.wezterm.lua` and `dot_wezterm.lua`.

## Why `LEADER o` to detach a tab instead of dragging it out?

WezTerm has no native mouse "tear-off": you cannot drag a tab off the bar to spawn a new window (long-standing limitation — see GH discussion #4080 and issue #549). The supported equivalent is the Lua `pane:move_to_new_window()`, which we bind to `LEADER o` (the leader — default `Ctrl+Space`, configurable via `ts-config leader` — then `o`) via `wezterm.action_callback`, plus `Ctrl+Shift+O` for access without the leader. `o` was the obvious free letter among the leader bindings at the time and is mnemonic for "out". For ad-hoc use without a keybinding, the CLI does the same thing: `wezterm cli move-pane-to-new-tab --new-window`. Bound in both WezTerm configs.

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

## Why front_end is OpenGL on Windows (and WebGpu on macOS)

`WebGpu` is WezTerm's modern default backend and the fastest; both GUI configs used it until August 2026. On Windows it is gone for a reason worth keeping: wgpu 25.0.2 (DX12 backend) panics at `wgpu_core.rs:3626:38` ("!?") when it reconfigures the swapchain surface after a display/session state change — monitor sleep, RDP/session disconnect. Four identical crashes (08/15–08/18/2026), each aborting the GUI and killing every pane in the window (three live Claude Code sessions in one case). `windows/.wezterm.lua.tmpl` now sets `config.front_end = 'OpenGL'`, which does not use wgpu at all and cannot reach that code path. A commented-out block beside the setting records how to re-test WebGpu once upstream wgpu is fixed — including pinning `webgpu_preferred_adapter`, since the machine that hit this carries both an AMD iGPU and an RTX 5070 and wgpu was free to pick either. macOS (`dot_wezterm.lua.tmpl`) intentionally stays on WebGpu: it is Metal-backed there and does not have this defect.

An older, different WebGpu incident is kept for history. On some Intel iGPU drivers (an earlier Windows 11 setup, May 2026) WebGpu had an output-buffer queueing behavior where rapid post-redirect output from a child process (Claude Code starting up, a large `cat` of a colored log) didn't trigger an immediate redraw — the buffer flushed only on the next input event, so "type `ccd`, hit Enter, nothing happens; hit space and Claude Code's whole intro screen appears at once." We switched to `OpenGL` for a while (commit `7922da8`); a later WezTerm-nightly / driver update cleared it and the configs returned to WebGpu — until the crash above retired it on Windows for good.

## Why the mux domain is opt-in, not the default (`ts-mux`)

The same WebGpu crash motivated a structural fix beyond the renderer swap: with panes local to the GUI process, *any* GUI abort — renderer panic, driver update, misclick on a "close window" prompt — kills every shell and everything running in them. Hosting panes in a `wezterm-mux-server` process outside the GUI (`config.unix_domains = { { name = 'main' } }` + `config.default_domain = 'main'`) fixes that: a GUI crash leaves every pane alive and relaunching WezTerm reattaches.

It shipped unconditionally in August 2026 and that was the mistake. The mux is a real change in how the terminal behaves, and it arrived through a routine `ts-update` — panes started coming up in a domain the user never asked for, with two visible side effects:

- **Per-pane background tints may not render under the mux domain.** The Claude cc-state tint is driven by `pane:inject_output` (see the ConPTY entry in `powershell-quirks.md`), which is local-pane-only; mux panes fall back to the hook's raw OSC 11, which ConPTY eats on Windows. Failures log once per pane to the debug overlay (`Ctrl+Shift+L`). Tab dots and title tints are unaffected (they ride the user var, not the byte stream).
- **The mux server loads its own copy of `.wezterm.lua`.** A GUI reload does not change how the mux spawns panes, so every config change needs a mux restart — which kills every live pane. Nothing in the stack restarts it automatically for exactly that reason; the sync scripts print a reminder instead.

So the domain is now a **saved setting** (`weztermMux`, `on`|`off`) that defaults to **off** — the pre-August behaviour — and both GUI configs gate it:

```lua
local MUX_ENABLED = '<on|off>' == 'on'   -- __WEZ_MUX__ / {{ .weztermMux }}
if MUX_ENABLED then
  config.unix_domains = { { name = 'main' } }
  config.default_domain = 'main'
end
```

Defaulting to *off* rather than preserving the shipped-on behaviour is deliberate: crash resilience is worth having, but it is worth **choosing**, and a machine that silently gained a mux is better served by landing back where it started and opting back in with one command. For the same reason the **install wizard asks** — `ts_prompt_wezterm_mux` / `Read-TsWeztermMux`, defaulting to off, `TS_WEZ_MUX=on|off` for scripted installs, and skipped on headless hosts where there is no GUI to host anything. A question at install is how a default becomes a decision; leaving it to a command nobody knows exists is how it stays a surprise.

`ts-mux` is that command, and it also owns the live server, because the manual path (`taskkill /IM wezterm-mux-server.exe /F`) is both easy to get wrong and impossible from WSL without knowing the interop trick:

| Command | Does |
|---|---|
| `ts-mux` / `ts-mux status` | the setting, the *rendered* setting (catches an un-applied change), the server pid, the pane count |
| `ts-mux on` / `off` | flip `weztermMux`, re-render, and say what takes effect when |
| `ts-mux list` | `wezterm cli list` |
| `ts-mux kill` / `restart` | stop / cycle `wezterm-mux-server` (confirmed — it kills every pane it hosts) |
| `ts-mux reset` | back to the default: off + re-apply + kill + clear stale sockets |

Two implementations, as everywhere else in this repo: `bootstrap/ts-mux.sh` (zsh wrapper in `dot_zshrc`) and `Invoke-TsMux` in `$PROFILE`. On WSL the GUI, the mux server and the rendered config are all Windows-side, so the bash script drives them over interop (`tasklist.exe` / `taskkill.exe` / `wezterm.exe`) rather than the Linux process table.

`status` deliberately reports the **rendered** value separately from the saved one. A config written before this toggle existed has no `MUX_ENABLED` line at all, so it reads the unconditional `config.default_domain = 'main'` and reports `on (pre-toggle)` — which is exactly the state a machine is in between pulling this change and applying it.

## Why the startup session restore is opt-in (and why we don't call `resurrect.setup()`)

WezTerm reopened the previous session at every launch — the same tabs and panes, with
their old scrollback replayed back into them — on every machine the stack was installed
on. Nobody asked for it and no document in this repo described it. The GUI log named
the culprit:

```
lua: resurrect: restoring workspace 'default' on gui-startup
```

`resurrect.setup()` registers the restore itself, unconditionally, with no option to
decline:

```lua
-- plugin/init.lua, in setup()
wezterm.on("gui-startup", pub.state_manager.resurrect_on_gui_startup)
```

The handler reads `current_state` from the plugin's state dir and, if it names a
workspace, replays it with `restore_text = true`. Every autosave rewrites that file, so
the behaviour re-arms itself forever — killing the mux, clearing sockets and restarting
the GUI all leave it perfectly intact, which is what made it look like a mux problem.

**The fix is to stop calling `setup()`.** With `keybindings = false` and
`status_bar = false` — which we already passed — `setup()` reduces to exactly three
things: `event_driven_save`, `periodic_save`, and that one `wezterm.on` line. So the
config now calls the two save engines directly and registers the `gui-startup` handler
itself, only when the setting says so:

```lua
local RESTORE_ENABLED = '<on|off>' == 'on'   -- __WEZ_RESTORE__ / {{ .weztermRestore }}
...
if RESTORE_ENABLED then
  wezterm.on('gui-startup', resurrect.state_manager.resurrect_on_gui_startup)
end
```

Forking around it was the alternative and was rejected: the fork is already pinned, and
adding a `restore_on_startup` option there would mean a plugin-cache refresh on every
machine before the fix took effect — while the config-side version ships with one
`ts-update`. Skipping `setup()` costs us nothing today and the comment in both configs
says loudly why it must not be "simplified" back.

Default **off**, for the same reason the mux domain is: a terminal that silently
reopens last week's shells is a surprise, not a feature you chose. `ts-config restore
on` turns it back on, and that is a plain boolean with no live process behind it — which
is why it lives in `ts-config` rather than earning its own `ts-*` command the way
`ts-mux` did.

Two deliberate consequences:

- **The autosave keeps running when the setting is off.** `Leader+S` / `Leader+L` are
  unaffected, and `current_state` keeps tracking your live workspace — so flipping the
  setting on restores *the session you had*, not a stale one from whenever you turned it
  off.
- **No saved state is deleted.** Turning the feature off is not a reason to throw away
  the user's sessions.

A `ts-mux status`-style saved-vs-rendered drift line would be cheap here (the gate is a
column-0 `local RESTORE_ENABLED = '<on|off>'`, greppable exactly like `MUX_ENABLED`) but
is deliberately skipped: every `ts-config` mutation ends in an apply, so the drift the
mux has to worry about — a live server disagreeing with both — has no analogue here.

## Why the status bar starts quiet

The tabline status bar shipped showing the mode badge, the workspace name, and `user@host │ path` for the active pane. Two of those three are permanent noise: on a single-user laptop `user@host` never changes, the workspace is `default` until you deliberately make another one, and the path is already in the Starship prompt two lines below and in the tab title above. That left a status bar whose steady state was three facts you already knew, and whose one genuinely useful element — the mode badge that tells you a repeatable key table is armed — was competing with them.

So `wezterm.GLOBAL.show_identity` now starts `false`. The badge still renders (it is transient and load-bearing); **Leader+s** reveals the rest when you actually want it — "which host is this pane on again?" — and hides it again. `wezterm.GLOBAL` survives a config reload but not a GUI restart, which is the right lifetime: a deliberate reveal lasts the session, and every launch starts clean.

The toggle covers the workspace name too, which it previously did not. Both the tabline sections and the hand-rolled fallback status now route through `status_workspace` / `status_identity`, so there is exactly one place the toggle is honoured and no way for the two renderers to disagree — the fallback had its own `ws ~= 'default'` test, which would have kept showing a named workspace after Leader+s hid everything else.

This is a runtime toggle with a default, not a saved config key. It costs one keystroke to change, needs no re-apply, and adding it to chezmoi `[data]` would mean the seven-file blast radius described above for something you flip while looking at it.

**Amended with the 2026-08 hand-rolled redesign:** "quiet" got quieter and the split moved. tabline's mode component printed a permanent `NORMAL` badge in the corner — a fact with zero information, and exactly the kind of steady-state noise this entry argues against — so with tabline gone the left side now renders *nothing* in the normal state; a coloured badge appears only while the leader is pending or a repeat mode is live. The workspace name moved **out** from behind the toggle: unlike `user@host`, a non-default workspace only exists because you deliberately created one, so it's signal, not noise (and it's `''` for `default`, i.e. invisible most of the time). Leader+s now gates only `user@host │ path`. Claude fleet counts remain always-on; the date and clock were later removed permanently because they duplicated the OS clock and consumed scarce title-bar width. There is one renderer now, so the two-renderers-disagreeing hazard above is gone by construction.

## Why the tab bar is fancy and fully hand-rolled (tabline.wez dropped)

The 2026-08-20 redesign came from concrete daily frustrations: the active tab (surface-grey on mantle-grey) was nearly indistinguishable from its neighbours; a permanent `NORMAL` badge occupied the corner saying nothing; Claude tabs burned width on a `cc • ` prefix that duplicated what the icon and dots already showed; non-Claude tabs could carry a full remote path; and the one-cell retro bar was cramped with no way to grow it.

Three decisions fell out:

1. **Fancy bar, not retro.** The retro bar's height is hard-locked to one terminal cell, and WezTerm has no multi-line tab bar at all (open feature request, wezterm/wezterm#3789). The fancy bar's height follows `window_frame.font_size` — the *only* sanctioned way to make the bar taller. The fancy bar still honours `colors.tab_bar` and `format-tab-title`, so nothing about the hand-drawn content is style-specific: flipping `use_fancy_tab_bar` back to `false` renders the same tabs and status in the retro bar (the escape hatch if the fancy bar misbehaves).
2. **tabline.wez dropped, not themed harder.** tabline requires the retro bar, so it blocked (1) outright. And its remaining value had already shrunk to nothing: `tabs_enabled = false` since day one (its components can't express per-pane cc dots), the identity segments moved behind Leader+s, and its mode component is what printed the permanent `NORMAL`. Meanwhile the config carried a complete hand-rolled fallback status for when the plugin failed to clone — two renderers for one bar. The fallback was promoted to the only renderer and extended; one fewer plugin fork to maintain, and the badge/segment behaviour is now plain code in the config.
3. **Contrast by role.** The active tab is a solid accent block (`#89b4fa` dark / `#005fb8` light) with dark bold text — findable in peripheral vision, which is the active tab's entire job. The cc-state wash now applies to *inactive* tabs only, where "a background Claude run finished" is the thing worth shouting; on the active tab the dots carry the state and the accent block is never diluted.

The status right side also gained the **Claude fleet** segment — `cc_state` counts across every pane in the mux (`N●` per state, coloured) — because "is anything done or broken somewhere?" was otherwise answered by scanning tab dots one by one. The `wezterm.mux` walk runs on the status cadence (100 ms) but is pure in-process table iteration, the same cost class as the pane-tint resync that already rode that cadence.

## Why not just use a single GUI tool like Microsoft Terminal?

Microsoft Terminal is fine, but:
- WezTerm has better Lua-based programmability.
- WezTerm's tab bar with custom format hooks beats MT's tab UI.
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

Aliases can't run code around the wrapped command. Setting and clearing the WezTerm tab title requires a pre-step and a post-step around the `claude` invocation. Either we (a) leave zsh as plain aliases and accept that only the PowerShell side gets the per-project tab title, or (b) promote zsh to functions matching the PowerShell try/finally pattern. We chose (b) for the same reason the PowerShell side does it: when you have four or five Claude panes open in WezTerm under WSL, the tab title is what tells you which project each pane is for. Without it the tabs are all just `pwsh` / `zsh` and you have to click each one to remember. The cost is a one-line helper (`_wez_tab_title`) and a small amount of bookkeeping (`local rc=$?; ... return $rc`) since zsh has no `try/finally` — that bookkeeping matters because without it the function would always exit 0 and mask Claude's exit code from scripts that wrap it.

The title text and the per-prompt clearing behavior are covered separately under "Why per-tab `cc • <project>` instead of one big tab name?" (amended: bare project leaf now) and "Why `wezterm cli set-tab-title` and not OSC 0?" — this entry is just about *why functions, not aliases*.

## Why Claude Code TTS is opt-in chezmoi data (not a sentinel file)

Like tab tinting, TTS is stack infrastructure — but unlike `ccnotify` (a sentinel file users toggle without re-apply), **enabling TTS adds hooks to the managed whole-file `settings.json`**. Conditional chezmoi template blocks keyed on `ccTtsEnabled` mean `ts-config tts off` + apply truly removes the hooks; no orphan processes or stale sentinel files. Runtime knobs live in **`~/.claude/tts/config.json`** (chezmoi-rendered) with optional untracked **`local.json`** merged at hook time — not in the template files themselves. **Async-only:** hooks spawn background workers and return immediately. **WSL playback goes through Windows interop** because Docker forwards `:8880` but audio devices do not.

**Hooks vs MCP:** lifecycle alerts (stop, AskQuestion, permission) must stay **hooks** — IDEs fire those events; an MCP server would not hear them unless the model voluntarily called it. A future **terminal-stack-tts MCP** can share the same `cc-tts-lib` for on-demand `speak` from Claude Desktop / Co-work; it complements hooks rather than replacing them.

*(Amended: the daemon upgrade below layers session-aware announcements on top of this design without changing any of it — the direct path described here is now the fallback, and everything in this entry still holds when the daemon is off or unreachable.)*

## Why the TTS daemon is a native tray process, not a Docker container

The session-aware announcement layer (`ccTtsDaemon`, `bootstrap/tts-daemon/ttsd`) needs two things a container can never have on Windows: an audio path to the host (Docker Desktop's utility VM has no sound device — there is no `/dev/snd` to pass through) and access to the host's per-app audio sessions (`ISimpleAudioVolume` enumerates only the caller's logon session, so a container cannot see or duck `Spotify.exe`'s mixer entry). Kokoro stays in Docker because synthesis is stateless HTTP — the daemon calls the same `:8880` endpoint the direct path always used. Everything that must touch host audio — playback, ducking, media pause/resume — lives in the one native process; anything else can reach it over `127.0.0.1:8890`.

## Why every Windows hook calls one GUI-subsystem EXE

The previous Windows path looked backgrounded but still started console-subsystem children: hook → PowerShell → Python → `ffprobe.exe` / `ffplay.exe`. Windows could allocate or flash a command window at any of those boundaries. Hiding only the first process was insufficient. `terminal-stack-tts.exe` therefore owns hook normalization, daemon posting, synthesis fallback, WinRT playback, SAPI, and duration probing in-process. PyInstaller's windowed bootloader marks it as GUI subsystem, and redirected hook JSON is read through inherited Win32 standard handles because `sys.stdin` is intentionally absent in a windowed build. Claude, Cursor, Codex, and WSL interop all call that EXE directly.

The **never-silence** rule remains, but the fallback is now another mode of the same binary: if the daemon is disabled or unreachable, the short-lived hook process starts a detached `_direct` worker with `CREATE_NO_WINDOW`. No PowerShell, `cmd`, Python runtime, FFmpeg tool, or console host belongs on a successful spoken path. Any unavoidable auxiliary child (currently only optional WezTerm CLI inspection) goes through the centralized hidden-process helper.

## Why the TTS source and PyInstaller spec live in `bootstrap/tts-daemon/`

The source, tests, build script, and spec ship with `ts-update`, while the built runtime lives at `%LOCALAPPDATA%\terminal-stack\tts-daemon\terminal-stack-tts.exe`. The installer creates a temporary build venv, freezes one EXE, validates it, atomically swaps it into place, and removes the legacy persistent venv/launcher only after validation. HKCU Run points directly at `"terminal-stack-tts.exe" daemon`, so clone relocation cannot strand autostart. The build embeds the clone Git SHA for `/healthz`; updates nudge rather than auto-restart because the daemon may be speaking or holding a duck.

## Why ducking snapshots pre-duck volumes to disk before touching anything

Windows persists per-app mixer volume indefinitely. A daemon that dies between ramp-down and restore leaves the music at 30% until the user finds the Volume Mixer — so the duck engine writes `state\duck-snapshot.json` *before* the first volume change, restores any stale snapshot at next startup, runs a 15 s watchdog while holding, and exposes `POST /v1/duck/release` plus a `--restore-volumes` oneshot that `ts-doctor --repair` invokes. Pause mode uses the Windows media-session API (`TryPauseAsync` only on sessions that were Playing, resume exactly those) and never simulates the media key, which is a blind toggle other apps can hijack.

## Why the `self` summarizer instruction uses agent-owned marker blocks

`summarizer self` needs the model to end each turn with a `<!-- speak: … -->` one-liner, which requires an instruction visible to every session. The repo deliberately does **not** manage Claude's `~/.claude/CLAUDE.md` or Codex's active global `$CODEX_HOME/AGENTS.md` whole-file (they are user-owned agent instructions) and does not force an output style outside this opt-in feature. Instead `ts-config tts summarizer self` edits a `<!-- terminal-stack-tts-start/end -->` marker block into both files, with `.bak.YYYYMMDD` backups, and switching to any other mode removes exactly those blocks. Codex sessions load instructions at startup, so already-running sessions may not emit the marker; the final-response hook text is locally shortened in that case.

Cursor's global User Rules live in a GUI-only settings store, so its optional rule ships as copy-paste text in `docs/kb/windows/tts-daemon.md`. Cursor's `afterAgentResponse` hook supplies the actual final response, which is locally shortened when no marker exists; its separate `stop` hook carries only status and speaks only failures. This asymmetry is deliberate — don't try to manage Cursor's rules database from a dotfiles repo.

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

## Why `lsr` ignores a directory's own mtime, and probes for GNU vs BSD

A directory's mtime changes only when an entry is added, removed, or renamed — not when a file
inside it is edited. That makes `ls -lt` and `eza -l -s modified` actively misleading for the
question people actually ask a listing ("which project did I touch last?"): a repo you edited
all afternoon shows an untouched mtime, while one where a build tool dropped and deleted a temp
file jumps to the top. `lsr` therefore ranks by the newest mtime among a directory's *immediate*
children and never falls back to the directory's own timestamp, not even for an empty directory
— an empty one has no activity to report, so it prints `(empty)` and sorts last. Staying exactly
one level deep is what keeps it usable: full recursion would be correct too, but on a workspace
of git checkouts it means walking every object in every `.git`.

The one-level rule has a sharp edge worth remembering: `find <dir> -maxdepth 1` includes `<dir>`
itself, so the obvious implementation silently reintroduces the directory's own mtime and makes
"is this empty?" impossible to detect. `-mindepth 1` is load-bearing, not tidiness.

`stat` and `date` are the portability problem. GNU wants `stat -c '%Y %n'` and `date -d @N`;
BSD/macOS wants `stat -f '%m %N'` and `date -r N`, and each errors on the other's flags. Since
one `dot_zshrc` serves WSL, native Linux, **and** macOS, the split has to be resolved at runtime
inside the function. We probe (`stat -c %Y .` succeeds?) rather than branch on
`uname -s = Darwin`, which is the idiom elsewhere in this repo: a Mac with Homebrew coreutils on
`PATH` has GNU `stat`, and the probe gets that right where a `uname` test would pick the wrong
flags. The result is cached in `$_TS_STAT_FLAVOR` so it costs one process per shell, not one per
call. The implementation stays POSIX (no zsh-only globbing such as `*(om)`, no `print -r --`) so
the same function body works if it is ever sourced from bash.

## Why Cursor IDE settings use merge, not whole-file

`%APPDATA%\Cursor\User\settings.json` holds personal choices — theme, fonts, editor prefs — alongside stack infrastructure. Whole-file management (the pattern used for `~/.claude/settings.json` infra keys) would clobber those on every sync.

The stack ships a **fragment** at `windows/AppData/Roaming/Cursor/User/terminal-stack.terminal.json` containing only stack-owned terminal keys (`terminal.integrated.automationProfile.windows`). `bootstrap/_merge_cursor_settings.ps1` shallow-merges those keys into the live settings file, backing up before write. This complements the profile guard: `automationProfile` covers VS Code/Cursor task automation (`pwsh -NoProfile`); agent shells still load `$PROFILE` but skip Starship via `Test-TsAgentShell`.

The merge edits the live file **textually**, splicing one top-level key at a time, rather than parsing to an object and re-serialising it. Parse-and-rewrite is the obvious implementation and it is wrong here for two reasons. First, `ConvertTo-Json` cannot represent comments, so every `// …` a user wrote in `settings.json` — a normal thing to have in a VS Code/Cursor config — would be silently deleted on the first sync. Second, round-tripping the *whole* file puts every unrelated setting at risk of a converter bug; an early version of this script turned the accelerator `[pscustomobject]` (which resolves to `PSObject`, matching every pipeline-wrapped value) against array elements and rewrote `["javascript"]` as `[{"Length":10}]`, destroying arrays it had no business touching. Textual splicing means the blast radius of a bug is the keys we own, and everything else is copied byte-for-byte. A post-merge check re-parses the result and refuses to write if any fragment key came out wrong or any pre-existing key changed.

The fragment carries `__PWSH_EXE__` / `__GIT_CMD_DIR__` placeholders rather than literal paths, resolved at merge time via `Get-Command` with per-user fallbacks. pwsh is not reliably at `C:\Program Files\PowerShell\7` — winget and Store installs land in `%LOCALAPPDATA%\Microsoft\WindowsApps` — and a hard-coded path yields an automation profile that fails with "file not found" on those machines. These are deliberately *not* sync-hook tokens like `__WIN_USER__`: the value depends on the machine running the merge, not on the config the user chose at install time.

## Why a separate `dot_wezterm.lua` for macOS

WezTerm reads `~/.wezterm.lua` from the home directory of whatever machine the GUI runs on. On Windows that's `C:\Users\<you>\.wezterm.lua`, deployed from `windows/.wezterm.lua` by the sync hook. On WSL the GUI is still the *Windows* WezTerm, so WSL's Linux home gets no WezTerm config at all — correct, because nothing there would read it. On macOS, WezTerm runs natively and reads the macOS home directory, so the Mac genuinely needs its own `~/.wezterm.lua`.

Three ways to produce it:

1. **Sync `windows/.wezterm.lua` to the Mac too.** Rejected — that file hardcodes `default_prog = { 'pwsh.exe' }` and a `launch_menu` with `wsl.exe`. Neither exists on macOS; WezTerm would error or spawn nothing.
2. **One `.tmpl` that forks on `.chezmoi.os`.** Workable, but the Windows file isn't chezmoi-managed at all (it lives under `windows/` and ships via the sync hook), so there's no single file to template — the Windows and non-Windows copies travel different roads by design.
3. **A standalone `dot_wezterm.lua`** at the chezmoi root, applied only on macOS.

We chose (3). The new file mirrors `windows/.wezterm.lua`'s visual settings (font stack, Catppuccin Mocha, flat tab bar, leader key, pane keys, `format-tab-title` / `update-right-status`, `front_end`) and intentionally diverges in exactly two places: it omits `default_prog`/`launch_menu` (macOS defaults to the login shell), and its final font fallback is `Menlo` instead of `Cascadia Code` because Menlo ships with macOS and Cascadia does not.

Native-Linux hosts in this stack are headless (reached over ssh/PuTTY) and run no WezTerm GUI, so applying `~/.wezterm.lua` there would just litter the home directory with a dead file. To prevent that, `.chezmoiignore` — which chezmoi evaluates as a template — gained a `{{ if ne .chezmoi.os "darwin" }} .wezterm.lua / .wezterm/** {{ end }}` block (the second pattern covers the Lua modules, i.e. `pane_nav.lua`). The files are therefore applied on macOS only. The gate keys off the built-in `.chezmoi.os`, not `[data].os`, so it works even when the bootstrap-written `chezmoi.toml` omits the `[data]` section.

Trade-off: like the single-sourced `starship.toml`, nothing automatic keeps `dot_wezterm.lua` and `windows/.wezterm.lua` visually in sync — a shared change has to be made in both. `dot_wezterm.lua`'s header comment says so.

One macOS-only caveat lives *outside* the config. macOS reserves both the `Ctrl+Space` leader (the system *Input Sources → "Select the previous input source"* shortcut) and the bare `F1`–`F6` pane keys (hardware media keys), intercepting them before WezTerm sees the keystroke — so out of the box every `Ctrl+Space …` binding and the F-key pane bindings look dead, and the `Ctrl+Space 1`–`6` fallback (which routes through the same leader) dies with them. We keep the bindings byte-identical to the Windows side rather than picking Mac-specific keys — cross-platform muscle memory wins — and push the resolution to two System Settings toggles (enable standard function keys; free the `Ctrl+Space` input-source shortcut), documented in `INSTALL.md` § macOS and the darwin block of the command reference.

## Why `doc` replaced the command-reference render pipeline

The command reference began as a single per-OS-gated markdown (`command-reference.md.tmpl` + a standalone Windows twin) that a bash renderer (`render-command-reference.sh`, bash + POSIX awk) expanded into committed `.txt`/`.html` twins **and** per-OS previews under `docs/command-reference/`, kept honest by two warn-only staleness checks (`run_after_10-*` on POSIX apply, a hash-check in `sync-windows.ps1`). It worked, and it bought three viewing formats (console/browser/Obsidian) that never drifted. But every content edit meant re-running the renderer and committing four-plus generated files, and the previews required the renderer to *shadow* chezmoi's `{{ if eq/ne .chezmoi.os }}` resolution with an embedded awk resolver — a deliberate but real maintenance tax, and a frequent source of "twins are stale" warnings.

`doc` retires all of it. Command docs are now plain `.md` topic files under `docs/kb/` (`common/` + per-OS `linux/`/`macos/`/`windows/` + `wezterm/`), read **in place** from the clone by the `doc` command — `docs/**` is already chezmoi-ignored, so there is no deploy step, no `.txt`/`.html` generation, no previews, and no staleness check. Per-OS selection moved from apply-time template gates to **runtime** (`doc` shows `common/` + the current OS; `--os` browses another); the dual-format twins became unnecessary because `glow` renders the `.md` directly and `doc -g` / `doc cmd` cover search and command-reuse. Editing a doc is just editing a file; `doc sync` stages it with an auto `### Docs` CHANGELOG bullet and an optional push. Per-machine/secret content moved from the untracked `command-reference.local.md` to a `~/.doc.local/` tree the viewer merges in. `ref` and `wzr` became thin aliases into `doc`. The render script, the `.md`/`.txt`/`.html` sources/twins, the previews, and both check hooks were deleted.

Trade-off: the browser/Obsidian `.html` export is gone. It was the weakest-justified part of the old pipeline (browsability only, no structural need), and in-terminal `glow` covers the day-to-day; an on-demand `doc export <topic>` could bring HTML back if it's ever missed.

## Why "kill workspace" shells out to `wezterm cli` (and rename doesn't)

`Ctrl+Space X` ("delete this workspace" = close all its panes) can't be done in pure Lua: `CloseCurrentTab`/`CloseCurrentPane` act only on the GUI's *active* pane, and the mux API exposes no tab/workspace close (wezterm/wezterm discussion #5907). The binding therefore collects every pane id in the target workspace from the mux, switches the GUI to another workspace first (so closing the last window doesn't quit WezTerm), then kills the collected panes with `wezterm cli kill-pane --pane-id <id>` via `wezterm.run_child_process`. The binary name is held in a `WEZTERM_CLI` local in both configs — currently `'wezterm'` on both sides (the GUI process resolves it from its own PATH, so no `.exe` suffix is needed on Windows). It refuses to run when the current workspace is the only one. `rename`, by contrast, is a clean one-liner (`wezterm.mux.rename_workspace`).

## Why config lives in chezmoi `[data]` + a Windows JSON mirror

The wizard/`ts-config` choices (leader chord, theme mode, tmux prefix, app selection, and the `ts-mux` domain toggle) need to survive every `ts-update` and be readable by *all* the apply paths. The stack already had exactly the right bridge: chezmoi `[data]` in `~/.config/chezmoi/chezmoi.toml` — the same place `windowsUsername` is stored and consumed by the WSL `run_after` hook to render Windows-side files. So the choices live there too. `.chezmoi.toml.tmpl` re-emits them (so a bare `chezmoi init` doesn't drop them) and *derives* the concrete bindings — `leaderChord "ctrl-space"` → `leaderKey "phys:Space"` + `leaderMods "CTRL"`, `tmuxPrefix "ctrl-b"` → `tmuxPrefixResolved "C-b"` — in one Go-template mapping. WSL/native chezmoi templates read them directly (`{{ .leaderKey }}`); the WSL hook reads them via `chezmoi execute-template` and substitutes `__LEADER_*__`/`__THEME_*__`/`__TMUX_PREFIX__`/`__WEZ_MUX__` tokens into the Windows `.tmpl` files (same mechanism as `__WIN_USER__`).

The wrinkle: a **Windows-standalone** install (no WSL) never runs chezmoi, so it can't read chezmoi `[data]`. That path gets a JSON mirror at `%LOCALAPPDATA%\terminal-stack\config.json` (next to the existing `rollback-sha`), written by `windows-bootstrap.ps1` / the pwsh `ts-config` and read by `scripts/sync-windows.ps1`. To keep the two stores from drifting in a **combined** Windows+WSL setup, the WSL side is authoritative: `ts_save_config` (bash) also writes the Windows `config.json` mirror when `/mnt/c/Users/<user>` exists, and the docs tell you to run `ts-config` from WSL. Defaults are baked into every consumer (`hasKey` guards in the templates, `cfg <key> <default>` in the hook, fallbacks in `sync-windows.ps1`), so a clone that predates the wizard renders today's behaviour (Ctrl+Space, Mocha, mux off) until you run it.

A single dedicated config file (one TOML/JSON on every platform) was the alternative. Rejected: it would duplicate the cross-side plumbing that chezmoi `[data]` + the sync hook already provide for `windowsUsername`, and chezmoi templates can't cleanly read an arbitrary external file on every apply. Reusing the existing bridge keeps the mapping in one Go template and the I/O in `bootstrap/_config.{sh,ps1}`.

## Why WezTerm follows the OS theme live, but Starship/tmux bake at apply time

`follow` mode means "track the OS light/dark setting." WezTerm can do this *live*: `wezterm.gui.get_appearance()` returns `Dark`/`Light`, and WezTerm re-evaluates the config when the OS appearance changes — so `.wezterm.lua` carries both palettes (Catppuccin Mocha dark + VS Code Light Modern light) and a `pick_palette(mode)` that flips the whole UI (scheme, tab bar, status line, Claude tints) with no re-apply. Only the *mode* (`themeMode`) is injected.

Starship and tmux can't: their configs are static files with no runtime OS-theme hook (Starship picks one `palette` at load; tmux reads a fixed status style). Querying the OS theme on every shell start was rejected — it adds startup latency to every prompt and OS detection from inside WSL is unreliable. So for those two the palette is **baked**: a `resolvedTheme` (`light`|`dark`) is computed once at apply time (`resolve_os_theme` reads the Windows registry / `defaults` / `gsettings`; `follow` resolves to the current OS theme, fixed modes resolve to themselves) and written into the store. `ts-update` and `ts-config` re-run that resolution (`ts_refresh_resolved_theme` / `Update-TsResolvedTheme`) and re-apply, so a `follow` user who toggles the OS theme picks up the new shell palette on the next update — while WezTerm has already switched live. The asymmetry is intrinsic to what each tool exposes, not a shortcut. (One palette wrinkle: WezTerm and Starship use VS Code Light Modern for `light`, while `dot_tmux.conf.tmpl` deliberately keeps Catppuccin-Latte-derived hexes for its light status colours.)

## Why a re-run repoints `sourceDir` (and why `ts-doctor` exists)

The original bootstraps refused to touch an existing `~/.config/chezmoi/chezmoi.toml` ("already exists; not overwriting sourceDir"). That looked conservative but caused a silent, confusing failure: install once to `~/terminal-stack`, later re-run the installer (which now clones to `~/code/terminal-stack`), and chezmoi keeps applying from the *old* clone. A clone that predates a feature (e.g. `doc`) therefore never delivers it, and `chezmoi apply` prints no changes because the old source already matches the target — the user sees "I updated, why is `doc` not found?".

The fix is to treat `sourceDir` as something the installer **owns and corrects**, not something it tiptoes around: `ts_ensure_source_dir` rewrites only the `sourceDir` line (preserving the `[data]` block — leader/theme/apps/`windowsUsername`) when it differs. This lives in `_config.sh` and is shared by all three POSIX bootstraps, so the three near-identical toml-writing blocks collapsed to one. `ts-doctor` is the standing version of the same check for an existing install: it verifies `sourceDir` resolves to a real terminal-stack clone (and the *intended* one), that `~/.zshrc`/`$PROFILE` actually carry the stack, and that tools are present — then `--repair` repoints and re-applies. Windows has no `chezmoi.toml`, so its analogue persists `$env:TERMINAL_STACK_DIR` to `profile.local.ps1` instead.

## Why re-clone fresh (not adopt-in-place) when an old clone is found

When the installer finds an old clone at a different path, it clones fresh to the chosen location and *offers to delete* the old one, rather than adopting the old clone where it sits. Adopt-in-place is less disruptive but inherits whatever state the old clone carried — a detached HEAD, a half-finished rebase, a wrong branch, local edits — and silently makes that the source of truth. A fresh clone is guaranteed to be `main` at a known-good commit, which is what an *installer* (as opposed to `ts-update`) should guarantee. Deletion is never automatic: the cleanup checklist shows each old clone's last commit, pre-ticks it, and removes nothing without an explicit confirmation; the keep-list (`~/.zshrc.local`/`profile.local.ps1`, `~/.doc.local`, rollback state, `*.local.md`) is never offered.

## Why headless is auto-detected (and what it changes)

Native Linux already skips the WezTerm *program* (only macOS/Windows install it), but the bootstrap still downloaded a ~30 MB Nerd Font and ran `fc-cache` on every server, and the wizard still asked for a WezTerm leader key — neither of which means anything on a box with no GUI terminal. We auto-detect headless (no `$DISPLAY`/`$WAYLAND_DISPLAY` and either an SSH session or a non-graphical systemd target; WSL is explicitly *not* headless because it renders in a Windows GUI terminal) rather than adding a flag, because the common case — `curl … | bash` on a fresh server over ssh — has no one around to pass a flag. Detection is **confirmed, not silent**: the bootstrap prints what it concluded and lets the user flip it on `/dev/tty`, and `TS_HEADLESS=1|0` forces it for unattended runs. Headless mode skips only the GUI-only steps (font + leader prompt); tmux, Starship, zsh, and the CLI tools — the things that make a server pleasant over ssh — still install.

## Why `wso` derives repo paths from the remote instead of the folder name

The folder a clone sits in is a guess someone typed once; the `origin` remote is the
only thing that says what a repo actually is. Deriving `<tier>/<host>/<owner>/<repo>`
from the remote is what makes the layout machine-generatable — a new machine is one
command rather than an afternoon — but the reason it earned its place is the failure
modes it catches for free. On the machine this was built against, the first plan found a
folder named `flipoff` in the third-party root whose origin was `37metrics/rotari`;
`sheet-sense` and `sheet_sense` in two different roots turned out to be one repo with
two local spellings; and a clone still pointing at a GitHub account renamed years ago
filed itself under the new name because a `rename` line in `workspace.conf` said to.
None of those are visible by looking at the folder, and all three are structurally
impossible once the path is computed rather than typed.

The `github.com/` level looks like pointless nesting when everything lives on one host,
and it is never typed — `wsj` fuzzy-jumps. It buys three things: two owners on different
hosts can share a repo name without colliding, the tree stays compatible with `ghq`, and
the day something lands on a self-hosted Gitea or a client's GitLab, nothing about the
scheme changes.

Trade-off: a repo whose remote is wrong gets filed wrong, and a repo with no remote
cannot be placed at all. The second case is why the `local/` tier exists rather than
guessing an owner — a path under `src/github.com/<owner>/` is a claim about where the
repo lives upstream, and for a repo that has never been pushed that claim would be false.

## Why the archive tier is a parallel tree and not `#archive` inside each org

A folder nested in each org directory was the first instinct and is wrong twice over.
It breaks the path-equals-remote invariant that everything else depends on, and
punctuation prefixes do not sort the way people assume: under the default
`en_US.UTF-8` collation glibc ignores punctuation entirely, so `_archive` interleaves
with the `a` repos and only sorts first under `LC_COLLATE=C`. A naming scheme whose
behaviour depends on a locale setting will behave differently on different machines,
which is disqualifying for a stack that exists to be identical across a fleet.

A parallel `archive/` mirroring the shape of `src/` makes archiving a path-preserving
move and restoring the same move reversed, keeps derivation working in both tiers, and
leaves `ls` inside an org directory showing only live work — which was the actual goal.

Archive state is deliberately per-machine and never written back to this repo. A repo
being cold on the laptop and hot on the desktop is correct; it is local cache state, not
a fact about the repo. Syncing that decision would archive a repo out from under you on
the next machine.

## Why `wso` owns its own path derivation when it also requires `ghq`

`ghq` is a hard requirement — it is installed by every bootstrap and `wso doctor`
verifies it — and `wso identity` writes the per-URL `ghq.root` config so `ghq get` and
`ghq list` land in the same tree. But the layout logic is ours, not delegated.

Two reasons. `ghq` has no concept of the `archive/`, `local/` or `scratch/` tiers, which
is most of what the organizer decides; delegating would mean owning the tiering anyway
and then reconciling it with a second source of truth. And `ghq`'s multi-root
configuration resolves with last-value-wins precedence, which has silently broken
people's setups across upgrades — a per-machine debugging cost multiplied by the number
of machines this deploys to.

Trade-off: more code here, and the two must be kept in agreement. The agreement is
one-directional and mechanical (`wso identity` generates the `ghq` config from
`workspace.conf`), so there is one source of truth even though there are two consumers.

## Why the staleness scan excludes `.git`, and re-checks safety twice

`wso archive` ranks by the later of the last commit and the newest mtime among a repo's
immediate children, reusing the reasoning behind `lsr` — a directory's own mtime only
moves when entries are added or removed, so a repo edited all afternoon looks untouched.

Excluding `.git` from that child scan matters more for a repo than the `-mindepth 1`
rule does for a plain directory. `git fetch` writes `FETCH_HEAD`, `git gc` rewrites
packs, and even `git status` can churn the index lock — all of which add and remove
entries directly under `.git`. Including it would make every repo that has ever been
fetched look like it was touched today, and the archiver would correctly conclude that
nothing is ever cold.

The safety gate runs twice: once when the candidate list is built, and again immediately
before each move. The checklist is interactive and can sit open for minutes while the
user reads it, which is more than enough time for a background editor save or a running
build to dirty a repo that was clean when it was listed. Re-checking is cheap; moving a
repo with uncommitted work is not.

## Why the migration moves rather than re-clones, and refuses across volumes

Within one filesystem a move is a rename: instant, atomic, and it preserves everything
inside the directory — uncommitted changes, stashes, the reflog, untracked scratch
files, `.env` files that were never going to be in git. Any approach based on
re-cloning silently discards exactly the work that is hardest to recover, and on a
machine where several repos carry hundreds of uncommitted changes that is a data-loss
event rather than a tidy-up.

Across filesystems the same call degrades into copy-then-delete, which is slow and can
half-finish. `wso` detects that and refuses rather than doing it, because a partially
copied repo with the original already unlinked is the worst possible outcome.

The Windows path needs retry logic that the POSIX path does not: directory handles are
released asynchronously, so an editor, terminal, language server or indexer that has
merely *looked* at a repo can make the rename fail for a second or two. The retry loop
reports the likely culprit by name rather than a raw sharing-violation message.

Nothing is ever deleted. The old roots are left in place after a migration for the user
to remove by hand once they have verified — the same discipline as the `.bak` convention
elsewhere in this repo.

## Runtime clone location: canonical app-data paths, invisible dev clones

The runtime clone — the one `ts-update` pulls and chezmoi applies from — lives at a
**canonical location** per platform:

- Windows + WSL (shared, ONE clone for both worlds): `%LOCALAPPDATA%\terminal-stack\stack`,
  which WSL reaches as `/mnt/c/Users/<you>/AppData/Local/terminal-stack/stack`.
- Native Linux / macOS: `${XDG_DATA_HOME:-~/.local/share}/terminal-stack`.

Why there: the stack already owns `%LOCALAPPDATA%\terminal-stack` (config.json,
rollback-sha, the docs/kb mirror, workspace state), chezmoi itself uses the same
convention (`%LOCALAPPDATA%\chezmoi` / `~/.local/share/chezmoi`), and — decisively —
app-data is **outside every workspace root**, so `wso migrate` can never relocate the
runtime clone out from under the install. That happened in practice: a clone at
`<workspace>/terminal-stack` planned cleanly into `src/github.com/<owner>/terminal-stack`,
a path no resolver knew, orphaning the machinery. Note the state-dir nesting: the mirror
at `…\terminal-stack\docs\kb` and the clone's kb at `…\terminal-stack\stack\docs\kb`
are distinct trees; the mirror stays last in every doc-root probe.

**The candidate list** (master copy: `bootstrap/_cleanup.sh ts_clone_candidates`;
replicas with sync headers: `dot_zshrc _ts_clone_candidates`, profile
`Get-TsCloneCandidates`, `bootstrap/_cleanup.ps1 Get-TsCleanupCloneCandidates` —
parse-time isolation forces the copies). Priority order IS resolution order:

1. the pin (`TERMINAL_STACK_DIR` / `-SourceDir`; POSIX also honours chezmoi `sourceDir`)
2. the canonical location
3. legacy defaults (`~/terminal-stack`, `C:\DATA\Workspace\terminal-stack`,
   `~/code/terminal-stack`, Workspace variants, `~/.local/share/chezmoi`,
   WSL `/mnt/c` probes)

The old pwsh newest-commit ranking is gone: it would prefer a **dev clone** the moment
you commit to it, making `ts-update` mutate the tree you are developing in.

**Dev clones are invisible unless pinned.** A clone at a wso tier path
(`<tier>/<host-with-dot>/<owner>/<repo>` — `ts_is_dev_clone` / `Test-TsDevClone`) is
skipped by every resolver, doctor probe, doc root, and cleanup menu. Setting
`TERMINAL_STACK_DIR` at it still works — pins are deliberate. This is what lets the
same repo be simultaneously the runtime install (canonical path) and a working
checkout (`wsmb` → `src/github.com/martybytes/terminal-stack`) without `ts-update`
ever touching the latter. `wso` plan/migrate additionally mark the *active* runtime
clone as `runtime … not migrated` if it is ever scanned.

**Pins are only for non-canonical locations.** The canonical path resolves on its own;
a pin there would shadow future relocations, so the installer and `Move-TsClone`/
`ts_relocate_clone` strip a stale pin (backed up) instead of rewriting it.

**A persisted pin is honoured only while a clone lives at it.** `profile.local.ps1` is
dot-sourced by `$PROFILE`, so a pin written by an earlier install is set in *every*
pwsh session — `irm … | iex` never sees a clean environment, and `install.ps1` cannot
tell "the user prefixed the one-liner" from "this machine was pinned in 2024" by
looking at the variable alone. It compares against the persisted line instead: a value
that matches `profile.local.ps1` **and** has no clone behind it is a leftover, so the
installer says so and falls back to the canonical default (the pin line is then removed
by the existing `Clear-TsSourceDirPin` branch, backed up first). A pin exported for one
run is not in that file and is always obeyed. POSIX persists its pin as chezmoi's
`sourceDir` rather than an env var, so there `TERMINAL_STACK_DIR` is only overridden
when it is dangling *and* the canonical location holds a real clone.

**A dangling pin degrades; it never dead-ends.** `Resolve-TsSourceDir` / `_ts_src` warn
and fall through to the candidate search when `$TERMINAL_STACK_DIR` names a path with no
clone. The two pin sources are deliberately not equivalent: an explicit `-SourceDir` is
typed per call, so a bad one still fails loudly, while the env pin arrives unbidden in
every session and a stale line would otherwise brick `ts-update` / `wso` / `doc`
machine-wide with no way out short of hand-editing `profile.local.ps1`. That is exactly
what happened.

**The runtime clone never goes inside a workspace root.** All four installers warn and
default to the canonical path when the chosen target sits under a detected workspace
root, because `wso migrate` derives a repo's destination from its `origin` and will
relocate it to `<tier>/github.com/<owner>/terminal-stack` — a path no resolver knows.
Dev-clone tier paths stay exempt: pinning one is deliberate.

**wso will not migrate an un-tiered terminal-stack clone, active or not.** The original
guard compared each candidate against the *resolved* runtime clone, which meant a `$null`
from `Get-TsWsRuntimeClone` switched the guard off — in precisely the broken states where
it matters (dangling pin, clone at a legacy path). It is layered now: the guard delegates
to `Resolve-TsSourceDir`, the pwsh `wso` shim exports what it resolved (the zsh twin
already did), and any scan candidate whose `origin` names the project is blocked outright.
A genuine dev clone already lives at a tier path and is therefore never a scan candidate,
so nothing legitimate is caught.

**Migration is ts-doctor's job.** `ts-doctor --repair` (pwsh `-Repair`) offers to move
a legacy-path clone to the canonical location: a plain directory move (same-volume
rename; cross-volume copy + HEAD-verify), then repoints chezmoi `sourceDir` (POSIX) or
clears the stale pin (Windows), offers to normalize a renamed-account origin URL, and
re-applies. `ts-update` only prints a one-line notice — an update must never move
directories as a side effect. Installers default to the canonical paths and offer the
same move when they find an existing legacy clone (pulling it first so the move
routine is present inside it).

When the canonical location is *already occupied*, `Move-TsClone` refuses (it will not
overwrite a destination) and the cleanup menu cannot help — `Find-TsClones` never offers
the canonical path, by design. That combination used to be a dead end, so `-Repair`
resolves it directly: if the occupant is a real stack clone it becomes the one in use and
the cleanup menu offers the other; if it is merely a directory in the way, it says so and
names the fix.

## Why the wizard re-prompts instead of defaulting on bad input

Every wizard question used to be a `switch (Read-Host 'Choose [1]') { … default { … } }`
(pwsh) or `case "$ans" in … *) … ;; esac` (bash). Both are total functions: `9`, `y`, a
stray paste, or a mis-hit key all fell into the default branch and the install continued
as if option 1 had been chosen deliberately. The defaults are good, which is exactly why
this was hard to notice — you got a working stack that was not the one you asked for.

A default should be what you get when you *decline to choose*, not what you get when the
program cannot understand you. So `Read-TsChoice` / `ts_prompt_choice` treat an empty
answer as consent to the default and anything unrecognised as a question worth asking
again (three times, then the default, so an automated caller can never spin). While the
two implementations were being written anyway, they also gained what the old ones lacked:
the default is marked and captioned "press Enter" rather than encoded in a `[1]` nobody
reads, and an option's name works wherever its number does (`dark`, `stable`, `none`).

They are two implementations, not a wrapper and a shim — the same rule `wso` follows, for
the same reason (bash cannot source a `.ps1` and pwsh cannot source a `.sh`). Keep the
rendered output byte-identical; a diff of the two menus is the test.

**Why the review step.** The wizard's answers used to be applied as they were given, and
the Windows workspace question was asked *after* every winget install — so a mis-answer
was only discoverable once the machine had already changed, and the fix was a full re-run.
Collecting first and showing a `[P]roceed / [e]dit / [q]uit` summary makes a wrong answer
cost a keystroke. `q` is meaningful precisely because nothing has happened yet.

`TS_WIZ_ASKED` counts the questions a human was actually shown, and it is tallied in
`ts_wizard_ask` rather than inside `ts_prompt_choice`: every prompt is called through
`$(…)`, so an increment in the subshell would be discarded. It exists because "is there a
`/dev/tty`" and "is there a person" are different questions — a run whose every answer
came from `TS_*` env vars has nothing to review, and prompting anyway would block forever
in CI, where the tty exists and nobody is watching it.

## Why WezTerm is a choice, and why a failed nightly falls back to stable

WezTerm sat in the always-installed set next to the Nerd Font, Starship, and chezmoi.
Those three are load-bearing — the configs this repo deploys are meaningless without them.
WezTerm is not in the same category: the stack is useful under Windows Terminal, over ssh,
or on a machine that already has WezTerm from somewhere else, and the `.wezterm.lua` we
deploy is inert when the binary is absent.

It was also the least reliable install in the set. `wez.wezterm.nightly`'s winget manifest
is republished more often than its hash is refreshed, so `Installer hash does not match`
is a routine outcome rather than an exotic one — and the bootstrap's response was a
`Write-Warning` that scrolled past behind a dozen more package installs, leaving an
install that looked clean and had no terminal. Nightly is still the default (the config
targets current builds), but a nightly that will not install now falls back to stable
rather than to nothing, and every package that failed is reprinted at the end with the
command to retry it.

## Why `~/.claude/settings.json` is spliced, not copied

Every other file under `windows/**` is a whole-file mirror: the stack owns it, so the sync
renders it and copies it over the top. `~/.claude/settings.json` looks like one of those and
is not, because **Claude Code writes the same file**. `/model` persists `model` there.
`/plugin` writes `enabledPlugins` and `extraKnownMarketplaces`. MCP tool allowances land in
`permissions`. Environment a plugin's hooks and MCP server need — `AGENTMEMORY_URL`, keys
like it — lives in `env`. None of that is ours, none of it is in the template, and a
whole-file copy deletes all of it.

That is not hypothetical. On 2026-08-20 a sync overwrote the file at 19:58 and took
`enabledPlugins` with it, which disabled the agentmemory plugin: its twelve lifecycle hooks
and its MCP server stopped loading, and nothing said so. Claude Code just stopped recording
anything, while Codex — whose config lives in `~/.codex/`, which this repo does not
whole-file-manage — kept working, so the two agents disagreed about whether memory existed.
The backup chain (`settings.json.bak.20260820.12` has the keys, `.13` does not) is the only
evidence the sync was responsible.

So the file is now **part-owned**. The sync splices in exactly the top-level keys the
template renders — `statusLine`, `hooks`, `theme` — and leaves every other byte where it
was. `bootstrap/_merge_claude_settings.ps1` drives it; the textual splice engine underneath
is `bootstrap/_merge_json_settings.ps1`, extracted from `_merge_cursor_settings.ps1` (Cursor
learned this lesson first, for `// comments` rather than app-owned state) and now shared by
both. Both sync paths route the file through it: `scripts/sync-windows.ps1` dot-sources the
helper, and `run_after_90-sync-windows.sh` stages the rendered fragment on the Windows side
and shells to `pwsh.exe`, the same way it already did for Cursor.

Three properties are deliberate:

- **A key the template stops rendering stops being ours.** Ownership is derived from the
  rendered fragment, not a hard-coded list, so removing a hook from the template removes it
  from the live file.
- **The splice refuses rather than guesses.** If the result does not re-parse, or would
  disturb any key the fragment does not own, nothing is written. A backup still precedes
  every write that does happen.
- **No pwsh, no clobber.** If `pwsh.exe` cannot be found from WSL the hook leaves an existing
  file completely alone and says so; it only falls back to a plain copy when there is no live
  file yet and therefore nothing to lose.

The tempting shortcut — put `enabledPlugins` and `env.AGENTMEMORY_URL` in the template and
keep the whole-file copy — is wrong twice over. AgentMemory's client wiring is deliberately
outside version control (`docker-local/agentmemory/README.md`: user-scoped, global, one
machine at a time), and it would not save `model` or anything else Claude Code writes next.

The WSL-side `dot_claude/settings.json.tmpl` is still a whole-file chezmoi target. That is
correct only as long as WSL-side Claude Code has no plugins and no per-machine keys; the day
it does, it needs a `modify_` script doing the same splice.
