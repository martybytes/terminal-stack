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

## Why duplicate speech is collapsed by a history table

Three hooks described one `AskUserQuestion` — `Notification`, `PermissionRequest`, and the `AskUserQuestion` `PreToolUse` matcher (the middle one has since been pruned; see below) — and the obvious fix, "make the scheduler smarter", does not work. The scheduler already keys pending events on `(session_key, priority class)`, but all three are `P0_INTERACTIVE` and `collect_due` drains `P0` **immediately**: the first is spoken and gone ~2.5s before the second arrives, so the slot never holds two at once. There is nothing in memory left to compare against. Worse, when the daemon is down each hook spawns its own detached `_direct` worker, so the state has to be shared between *processes*, not threads.

Hence a durable record instead of a queue tweak. `state\history.db` stores one row per **decision** — `spoken`, `deduped`, `suppressed_dnd`, `synth_failed`, `failed` — and both paths check `recently_spoken(session, priority, debounceSec)` before speaking. The direct path checks it a second time *inside* the play lock, which is the check that actually collapses the burst: the first look raced with its siblings. Recording the rejections is the point; the dispatcher's in-memory `spoken`/`suppressed` counters die with the process, and the original investigation needed hand-parsing of `ttsd.log` to establish that anything had spoken twice at all. `ts-config tts history --dupes` is now that query.

`debounceSec` already existed in `config.py` with **no reader anywhere** — a config key nothing read is exactly why this looked fine on inspection — so it was wired up rather than replaced by a new key. A new chezmoi `[data]` key has a 7-step blast radius and a second store to diverge with; a runtime knob in `~/.claude/tts/config.json` (settable in the untracked `local.json`, `0` to disable dedupe entirely) has neither.

Two constraints shaped the mechanism:

- **The lock orders speech, it never drops it.** A waiter polls, then speaks anyway once `wait_sec` is up, and a lock older than `stale_sec` is reclaimed rather than trusted. Silencing a permission prompt is worse than hearing it twice, so dropping duplicates is `recently_spoken`'s job and the lock's only job is preventing overlap. The mutex is an atomic exclusive create, not a read-then-write test — two workers a millisecond apart would both pass a "is it locked?" read, which is the race being closed.
- **Fail open, everywhere.** A missing, locked, read-only or corrupt database returns "nothing known" and writes nothing; the first failure logs once and the module goes quiet so a bad disk cannot flood the log. Verified by pointing `LOCALAPPDATA` at a regular file: history, lock and log all unusable, and it still spoke. That drill found two pre-existing crashes on the way to speech — `_setup_logging` and `_spawn_direct` both ran `mkdir` outside any guard, and the second sat outside the `try` whose `False` return is what makes `submit_hook` fall back to speaking in-process.

The availability half is smaller but mattered more in practice: autostart is logon-only with no watchdog, so a daemon that died at 22:17 was still dead at 13:30 the next day, with no error and nothing in the log. Every hook in between took the unserialized direct path and exited 0, which is how genuinely overlapping voices went unnoticed for fifteen hours. A hook that cannot reach an enabled daemon now starts it and retries once. That is safe to race: two hooks both spawning means the loser fails to bind the port and exits 0 (`_already_running`), so the check only ever asks whether the port answers, never which process won it. `ts-doctor` reports how long the daemon has been silent and flags any session that spoke twice, because neither is visible otherwise — every hook exits 0 either way.

## Why the dashboard writes only local.json, and needs a token to do it

The daemon is a Windows process and chezmoi `[data]` lives in WSL, so the page physically
cannot write the authoritative store. Rather than shell across the boundary from a form
submit, it writes `local.json`, which is the mechanism built for exactly this: untracked,
deep-merged over the rendered config, wins, and survives every apply. The tray already
wrote it for music and summarizer mode, so this is one mechanism rather than a new one.

The cost is real and is stated on the page itself: these are machine-local overrides that do
not travel to other machines. **Every field shows which layer won**, and says so explicitly
when an override is beating the saved value. Without that, changing a setting somewhere else
and seeing no effect would be unexplainable, which is the confusion this whole feature
exists to end.

**Writes need the token even on loopback.** Loopback needed no token because it cannot be
reached from another machine, and that reasoning does not survive a browser: any page you
visit can POST to 127.0.0.1. The Host allowlist does not help here, because a cross-site
form POST carries the *target* Host. Before this, a random page could mute your machine
(`/v1/mute` mutated on an empty body), and a config endpoint would have raised that to
writing arbitrary dotted keys, including `kokoro.url` and the ollama URL, which are
exfiltration shaped. So the new routes plus `/v1/mute` and `/v1/speak` require
`X-TS-Token`, which the page carries because it is served same-origin and no route sends
CORS headers.

Three routes stayed open, deliberately, and it is worth knowing which: `/v1/event`, because
every hook posts it and none of them has a token to hand; `/v1/config/reload`, because
`ts-config` from pwsh has no token either; and `/v1/duck/release` with `/v1/shutdown`,
because the installer calls them and both are nuisances rather than compromises now that a
dead daemon restarts itself on the next hook.

**Validation lives in a schema, not in the UI.** The enums existed only in `tray.py`'s
tuples, `_cc_tts.sh`'s case arms and `_config.ps1`'s switch, and `write_local` accepted any
path with any value. `ttsd/settings_schema.py` is now the single list the server validates
against and the page renders from, so the two cannot drift, and two tests check that its
`restart` and `shell` flags still match what the code does: a restart-flagged key must
appear in `_build`, and a shell-only key must appear nowhere the daemon reads config. A
stale flag would be a lie the UI repeats.

The haiku model became a closed list rather than free text, because `max_tokens` is 60 and
that interacts badly with a model that thinks by default.

## Why the summarizer test reports rather than just speaks

A missing API key makes `haiku` produce exactly the template line, with no exception and
nothing in the log. A test button that only played audio could not tell that apart from
success, so the test returns what actually ran: the mode requested, the mode that produced
the line, where the key came from, the latency, whether it fell back and why, and the line
itself. It also carries the structural caveat, because a correctly configured haiku *still*
sounds like the template for a question: non-template modes only apply to `waiting`
announcements, and a coalesced multi-session line bypasses every mode.

It runs on a throwaway `Summarizer` so a test never disturbs the daemon's own counters.

## Why the dashboard is a page served by the daemon

The daemon already runs an HTTP server on loopback, so a browser page costs no new bundled
dependency, no console window, and no second GUI toolkit. The alternative worth taking
seriously was a native always-on-top window, and it loses on a specific mechanical point:
pystray owns the main thread for the life of the process, so Tk would have to run its own
loop on a worker thread, which is unsupported and prone to hanging, and it would add roughly
10MB plus DLLs to a binary this repo is deliberately careful about.

**The page is a Python string literal, not a bundled asset.** The spec's only `datas` entry
is a 41-byte build artifact, and the repo's one real source asset is clone-resident by
design, which cannot work for a frozen EXE in `%LOCALAPPDATA%` with no reliable path back to
the clone. The `_MEIPASS` lookup that would be required degrades silently to a default on
`OSError`, and the same silent degrade here would serve a blank page from a healthy daemon.
A literal cannot be forgotten in a spec edit.

**Two panels, because they answer different questions.** The raw log says what the daemon is
doing, including engine errors that never reach a decision. The decision timeline, from the
history database, says what it chose and why: `spoken`, `deduped`, `muted`, `suppressed_dnd`,
`synth_failed`. The log cannot answer "why was it silent" cleanly, and that has been the
recurring question. The timeline also survives log rotation and daemon restarts.

The streaming is hand-rolled inside `BaseHTTPRequestHandler`, and three details are
load-bearing. `protocol_version = "HTTP/1.1"` means a response without a `Content-Length`
would leave the browser waiting forever, so the connection is explicitly closed rather than
kept alive. Every write can raise once the tab closes, which is a normal end of stream and
not worth logging. And the loop polls `app.stopping`, because `listener.shutdown()` stops the
accept loop but says nothing to a response already in progress.

Following the log never holds the file open. `RotatingFileHandler` renames `ttsd.log` on
rotation, and on Windows a reader with the handle open can make that rename *fail inside the
handler*, which would break the daemon's own logging in order to display it. So: stat, open,
read, close, every poll; detect rotation by the file shrinking; decode with
`errors="replace"` because a byte offset can land mid-codepoint in a line containing smart
quotes; hold back anything after the last newline so no half record is rendered; and treat a
line that fails the timestamp pattern as a continuation rather than dropping it, since a
future `log.exception` would emit those.

**A Host allowlist, before any write endpoint exists.** Loopback needs no token, which is
safe against other machines and not at all safe against a browser: any page can reach
127.0.0.1. With no `Host` validation, DNS rebinding would let a remote page read this
daemon's history and status. The bound address is always accepted, so the WSL-facing listener
keeps working for hooks that address it by gateway IP, and a missing `Host` is allowed because
only local scripts omit it while every browser sends one.

## Why a summarizer that cannot work says so

Selecting `haiku` with no API key produced *no* observable difference from `template`. The
lookup returned `""`, there was no exception, no log line and no counter, and `/v1/status`
went on reporting `summarizerMode: haiku`. `Summarizer.degraded` was incremented in exactly
one place and read nowhere; `__init__` accepted a `degraded_counter` and discarded it. That
is the most misleading state the daemon had: the feature was off, every indicator said it
was on, and the only way to find out was to read the source.

Every fall-back-to-template now goes through one `_degrade(reason, detail)` that counts it,
records the reason, and warns **once per reason per process** (a broken key would otherwise
write a line on every announcement). `/v1/status` carries `summarizerDegraded` and
`summarizerLastDegrade`, so "why does it sound like template mode" is answerable without a
log dive. The reason strings name the thing that failed, including the exception class for a
request failure, because a timeout, a 401 and a rate limit are otherwise indistinguishable
at that layer.

Two structural facts came out of the same investigation and are worth writing down, because
both look like bugs and are not:

- **Non-template modes only apply to `waiting` events.** `_line_for_one` returns before the
  mode dispatch unless the event is `P2_DONE`, so questions, permission prompts and errors
  are always the template, whatever mode is selected.
- **A coalesced batch bypasses every mode**, since the multi-session line is assembled
  locally.

Both are pinned by tests now, so nobody "fixes" them by accident, and any UI that offers a
mode has to say so rather than implying the mode applies everywhere.

`self` has a third surprise: without a `<!-- speak: -->` marker it does not fall back to the
template, it speaks the first sentence of the answer. That is what every Cursor session and
every pre-install Codex session gets.

## Why the API key lives in the daemon state dir, not in config

An environment variable cannot do this job. The daemon is autostarted from
`HKCU\...\CurrentVersion\Run`, so it inherits the logon environment and nothing after it.
A key exported in a shell, or `setx` without a logoff, never reaches the running process.
That is the same shape as the stale `AGENTMEMORY_SECRET` that silently destroyed 56 captures
the same day: it worked in a new shell and not in the process that mattered.

Neither config store is an acceptable home either. `config.json` is rendered from chezmoi
`[data]`, which is tracked in git. `local.json` is untracked, but it is part of the config
merge, it sits beside the rendered file, and it is what people paste into a bug report. A
secret that appears in an effective-config dump is a leaked secret.

So `state/secrets.json`, alongside `token` and `history.db`, following the pattern
`load_or_create_token` already set for the WSL listener's shared secret: machine-local, never
merged into `Config`, read at use time. `ttsd/keystore.py` (named to avoid any confusion with
the standard library `secrets` module) writes atomically, refuses any name outside a fixed
allow-list so a settings endpoint cannot become "write anything anywhere", and **never
rewrites a file it cannot parse** so a hand-edited typo stays fixable by hand. `describe()`
returns whether a key is set and where it came from, plus the last four characters, and never
the value. The environment variable remains a fallback, so nothing that worked before stops.

## Why `local.json` writes are atomic, locked, and refuse to destroy

`write_local` was a read-modify-write with three faults that a settings form turns from
theoretical into likely. It wrote in place, so a crash mid-write left truncated JSON, which
`Config.reload` then discards wholesale, presenting as every local setting reverting at
once. It took no lock, so a tray toggle and another writer interleaving lost one of them.
And `except ValueError: data = {}` meant a single bad byte caused the next write to replace
**every other override** with a one-key document.

Now: one temp file plus `os.replace`, an exclusive-create lock with a stale reclaim (the same
idiom and reasoning as `speaklock.py`, including proceeding after the wait rather than
refusing, because a save that silently does nothing is worse than an interleaved one), and an
unparseable overlay is moved to `local.json.bad.YYYYMMDD` under the repo's usual dated-backup
rule instead of being overwritten. `write_local_many` exists so an N-field form is one
read-modify-write rather than N, which is precisely the workload that hit the old bug.

## Why the Windows mirror is written from a resolved username, loudly

`ts_mirror_windows_config` resolved the Windows username from chezmoi `[data].windowsUsername`
alone and did `return 0` when it came back empty. On a machine whose clone predates the
bootstrap recording that key, the mirror was therefore **never written by any WSL-side save**,
and every save reported success. The two config stores drifted apart for as long as the
machine had been running.

The consequence is not cosmetic. `scripts/sync-windows.ps1` gates the TTS hook tokens on the
mirror's `ccTts.enabled`, so a stale `false` there makes the next pwsh sync delete every TTS
hook entry from `~/.claude/settings.json`, while `ccTtsDaemon` is a separate key and keeps the
tray daemon running. The result is a healthy, unmuted tray icon attached to nothing, which is
exactly how it presented.

Three copies of the correct resolution order already existed (`resolve_win_user` in the sync
hook, `win_user` in `ts-mux.sh`, and inline in `ts_canonical_clone_dir`): chezmoi `[data]`
first, then `cmd.exe /c echo %USERNAME%` over interop. The mirror writer was the one place
that lacked the interop half. It now shares `ts_win_user`, and when the username genuinely
cannot be resolved it **warns instead of returning success**, because a silent skip is what
made this survive so long.

Fixing it exposed the cost that the no-op had been hiding: writing the mirror makes 49 reads
of chezmoi `[data]`, and each `chezmoi execute-template` re-reads the source state, which on a
combined host lives on `/mnt/c`. The first honest run took **229 seconds**. Two batching
passes brought it to **14**, with byte-identical output: `ts_data_prefetch` renders every
plain key in one call and caches the values (a marker variable distinguishes "cached empty"
from "never fetched", since several keys are legitimately empty), and the six derived
expressions, which cannot use the `hasKey` form, share a second call. `ts_data_get` still
falls back to its own spawn for anything not prefetched, so a key missing from the list is
only slow, never wrong.

## Why every agent gets prompt-level retrieval

The wiring originally gave `/agentmemory/context` at prompt-submit time to Codex and Cursor only, on the reasoning that Claude "already retrieves on file tools and at session start". Measured against the console feed over 5.7 hours, that assumption failed badly: Claude made **1041** captures, **250** `/enrich` calls and exactly **one** `/context` — and that one was a compaction, since `pre-compact.mjs` is Claude's only `/context` caller. Codex, with the edit, retrieved on essentially every prompt.

The gap is in what `/enrich` can see. It fires only for the vendor allow-list (`edit/write/create/read/view/glob/grep`), `Bash` is excluded both by the `hooks.json` matcher and by that list, and a `Grep`/`Glob` carrying no `path` argument is dropped. A session that is mostly shell work — which is most real work — therefore retrieves nothing at all between session start and the first file edit. `/agentmemory/context` needs only `{ sessionId, project }`, so it is the one channel that does not depend on what tools a turn happens to use.

Two things made this cheap to fix rather than a redesign: the edit already existed and was merely withheld, and the vendor `prompt-submit.mjs` is byte-identical across hosts, so the same anchors applied to Claude untouched. The only real change was adding `prompt-submit.mjs` to Claude's patch set — the installer had never opened that file, which is why the edit could not have landed even if the guard had allowed it.

What stays host-specific is the shell denylist (edit 5). Claude's `PreToolUse` uses the vendor allow-list plus a `hooks.json` matcher; inverting the list there would widen a mechanism that already works rather than fix one that does not.

Cost, accepted deliberately: one request and a context block on every prompt. `AGENTMEMORY_INJECT_CONTEXT=false` turns it off without unpatching anything, which is what the gate edit exists for.

## Why a 401 refreshes the secret from the user environment

`AGENTMEMORY_SECRET` reaches a hook through the process environment, and a User environment variable only reaches processes started *after* it was set. Rotate the secret and every long-lived shell keeps the old one — so every request from any session launched by that shell fails with 401. On 2026-08-21 that ran for thirteen minutes and cost **56 consecutive requests**: `session/start`, `observe`, `enrich`, `session/end`, all rejected, with **nothing in any log**. Capture swallows errors in `.catch(() => {})` and retrieval discards non-2xx behind `if (res.ok)`, which is correct behaviour for a hook that must never block a turn, and exactly what made this invisible.

The recovery re-reads the value from the user environment on a 401 and retries once, caching it for the process. Three choices worth keeping:

- **It wraps `fetch` once per script** instead of each call site. There are six scripts with one or two fetches each; wrapping the global keeps this to a single edit with a single anchor (`function authHeaders() {`, which exists exactly once in all six) rather than a dozen fragile ones.
- **It reads the user environment, not the container.** The container is the Docker stack's concern, and a hook has no business running `docker exec`. The user environment is where the authoritative value already lives and is what the plugin's own `.mcp.json` reads.
- **It fails open in every direction.** A non-Windows host, a missing value, an unreadable registry, or a retry that also 401s all return the original response. The recovery can only ever turn a silent failure into a success, never a success into a failure.

It also covers the case where the secret is missing from the process entirely, since "no `Authorization` header" and "wrong `Authorization` header" produce the same 401.

What it cannot fix is a user environment that is *itself* stale relative to the container — nothing local can recover from that, so `ts-doctor` reports it instead, comparing the two when Docker is reachable and staying quiet when it is not.

## Why the mute is a sentinel file, not the tray's DND

The tray already had `Do not disturb` and `Mute for 1 hour`, and neither silenced the things worth silencing. Both routed to `Dispatcher.set_dnd`, and the single enforcement point exempted `P0_INTERACTIVE` and `P1_ERROR` whenever `quietHours.allowInteractive` was true — the default. So DND muted "done" announcements and spoke every question, permission prompt and error: exactly backwards for someone who just answered a phone call. The flag's name gave no hint that it governed the DND toggle at all.

Two more problems made it unusable rather than merely wrong. It was **one float on the dispatcher**, so it died with the process — a tray Quit, a crash or a reboot silently un-muted. And the **direct path never consulted it**: `dnd_active` lived only on `Dispatcher`, which a detached worker never constructs, so with `daemon.enabled` false (the shipped default) the mute had no effect whatsoever and the only UI for it was not even running.

`state/muted` fixes all three by being a file. Existence is the check, so the hot paths never parse it and WezTerm can decide with a `glob`; the JSON body (`since`, `by`) is metadata for reporting. It is read at the two hook gates, in the dispatcher, and by the native-WSL playback path, which is what makes it hold with the daemon dead. It is **absolute** — no priority escape — because the exemption was the bug. Quiet hours keep their own `allowInteractive`, since a schedule and a panic button are different things.

Three details worth not undoing:

- **It fails open toward speech**, the opposite of `history.py`. If the state directory is unusable, "not muted" is the answer. A mute that cannot be lifted is indistinguishable from the feature being broken, whereas one that fails audibly is something you can hear and act on. An existence check gives that default for free.
- **Muting cuts off the sentence already playing.** Nothing could interrupt speech before: `Playback.play` built the WinRT `MediaPlayer` as a local and blocked until the audio finished. It now publishes the player so `stop()` can pause it and release the waiter, wrapped so a failed cross-thread COM call merely lets the sentence finish.
- **Three surfaces report it.** The tray icon greys out with a slash, WezTerm shows a `MUTED` chip, and `ts-doctor` names it — plus the `local.json` `enabled:false` mask that hid a mute for an afternoon while `cctts` cheerfully reported ON. An unreported mute *is* a bug report waiting to happen.

The tray and the global hotkey are conveniences on top of the file, not the mechanism, because both exist only while the daemon runs — and it has died silently more than once. `ccmute` writes the sentinel itself and works regardless; it also best-effort POSTs `/v1/mute` purely to get the barge-in, since only the process that owns the audio can stop it.

Why not `local.json` `{"enabled": false}`, which every path already honoured? It conflates "quiet for this call" with "feature off", `Config.write_local` is a non-atomic read-modify-write that a tray toggle and a shell command can clobber, and it is exactly the switch that masked a saved setting for hours. Why not a chezmoi `[data]` key: writing config stores from the wrong shell is what silently removed all five Claude TTS hooks on 2026-08-21. The sentinel touches neither store.

## Why `PermissionRequest` was dropped from the Claude TTS hooks

It never contributed text the others lacked. `build_payload` sets its `override` to `tool_name`, and `summarize.py` already renders that tool name into the permission template before appending the same string again — "Claude. alpha wants to run AskUserQuestion. AskUserQuestion". `Notification` announces the same prompts in Claude's own words ("Claude needs your permission to use Bash"), and the actual question text comes from the `AskUserQuestion` `PreToolUse` hook, the only place `_first_question` runs.

Dedupe made the redundancy worse rather than harmless: `recently_spoken` is **first-wins, not best-wins**, so which of the three sentences you heard depended on which hook Claude happened to fire first. Deleting the weakest one is a smaller change than teaching the dispatcher to rank candidates, and it removes a class of announcement nobody was choosing.

Accepted cost: the `permission` state becomes unreachable from Claude (Cursor still sends it), so permission prompts can no longer be muted separately from questions via the `events` list, and `announce.templates.permission` is now only exercised by Cursor and `ts-config tts test`. The absolute mute covers the "silence everything" case that granularity was standing in for.

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

**The failure mode that asymmetry buys, and what it looks like.** The bridge is one-way: a
bash save writes chezmoi `[data]` *and* mirrors to `config.json`, but a **pwsh save writes only
the mirror**. On a combined machine that is a silent divergence — the two stores disagree about a
key and nothing says so, because each apply path reads only its own store and renders a perfectly
valid file from it. Whichever path runs last wins, so the setting appears to work until the *other*
side applies and takes it away.

Observed 2026-08-21: `ccTtsEnabled` was `false` in chezmoi `[data]` and `true` in the mirror. Every
`ts-update` from pwsh rendered the five Claude TTS hooks; the next `chezmoi apply` from WSL rendered
none and removed them. Nothing failed, nothing warned, the diff looked intentional, and the only
symptom was that voice notifications quietly stopped. It had presumably been flip-flopping for some
time.

Two things follow. `ts-config` from WSL is not a style preference — it is the only path that writes
both stores, which is why CLAUDE.md states it as a rule. And when a setting mysteriously reverts
after an apply, compare the stores before debugging the templates:

```sh
chezmoi execute-template '{{ .ccTtsEnabled }}'                     # WSL, authoritative
python -c "import json;print(json.load(open('/mnt/c/Users/<you>/AppData/Local/terminal-stack/config.json'))['ccTts']['enabled'])"
```

They must agree. Repair by re-saving from WSL (`ts-config tts on`), which writes both. Nothing
currently *detects* the divergence — `ts-doctor` would be the natural home for a check that walks
the shared keys and reports any that disagree.

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

## Why the WezTerm channel is a question, and why it is not a saved setting

WezTerm sat in the always-installed set next to the Nerd Font, Starship, and chezmoi.
Those three are load-bearing — the configs this repo deploys are meaningless without them.
WezTerm is not in the same category: the stack is useful under Windows Terminal, over ssh,
under Ghostty, or on a machine that already has WezTerm from somewhere else, and the
`.wezterm.lua` we deploy is inert when the binary is absent. So it stays a question, and the
question is a tick-list: WezTerm nightly, WezTerm stable and Ghostty are separate ticks,
whatever is installed starts ticked on its detected channel, and `[n]one` is one keystroke.

**Both channels are offered, and nightly is pre-selected — on every machine.**
Upstream's newest *stable* is `20240203-110809-5046fc22` — February 2024, with no cut since.
Nightly is what @wez uses as a daily driver and what this stack's Lua config targets, so
defaulting a *fresh* machine to stable would put it on a two-and-a-half-year-old build. This
briefly *was* stable-only, and that was the wrong call for exactly this reason.

This briefly pre-ticked **whatever was installed** instead, on the theory that a re-run should
offer to upgrade what you have rather than switch your channel behind you. That was wrong, and
it was reported as a bug within a day: a stable box saw nightly unticked, and pressing Enter —
the thing everyone does — silently kept the February 2024 build while row 1 read "what this
stack configures". A default that quietly preserves a two-and-a-half-year-old build is not a
conservative default, it is the wrong one. Nightly is pre-ticked regardless of what is
installed; the channel is still only ever *offered*, never switched without a keystroke.

The one exception is a WezTerm installed **outside a package manager**
(`ts_wezterm_channel` → `unknown`): neither channel is ticked and Enter leaves it alone,
the same "not ours to replace" rule `ts_wezterm_install` applies at install time.

The two channels are **mutually exclusive in the tick-list itself**: both casks own
`/Applications/WezTerm.app` and both apt packages own `/usr/bin/wezterm`, so ticking one
unticks the other on screen. That used to be resolved only *after* Enter, which meant the
list happily displayed `[x] [x]` for a combination the code would silently refuse.

**But nothing is automatic.** Nightly moving daily is precisely why it must not upgrade
behind your back: the wizard asks at install, `ts-update` reports and offers when something
newer exists on the channel you are already on, and `ts-config wezterm` changes it on demand.
No path installs, upgrades or switches without a yes. Non-interactive runs print the command
instead of running it.

**The prompt shows facts, not just a default.** A choice between "stable" and "nightly" is
meaningless without knowing that stable is from 2024 and nightly was rebuilt this morning, so
the intro carries the installed build and its date, the newest build on each channel, and a
count of what changed in between. All of it is derivable without an LLM:

- The build date is **in the release name** — `<YYYYMMDD>-<HHMMSS>-<githash>` — so
  `wezterm --version` alone dates the installed build with no network call.
- Latest stable is the `releases/latest` tag and its `published_at`.
- Latest nightly is **not** the nightly release's own `published_at` (that is stuck in 2019,
  because the tag is a rolling one). It is the `updated_at` of the nightly asset *for this
  platform*, which matters: the Debian10 nightly last built over a year ago while Debian12's
  built today, and quoting a release-level date would be wrong on both counts.
- "What changed" is sliced out of upstream's own `docs/changelog.md`, whose release headings
  are exactly the strings `wezterm --version` prints — so the slice is an exact match rather
  than a guess. The tally counts bullets per `#### Changed / New / Fixed / Updated`; the full
  text is `ts-config wezterm changes`, paged through the same reader `doc` uses. For a
  nightly there is no heading to anchor on, so the honest answer there is the commit count
  from `compare/<hash>...main`.

**The channel is not stored.** It is read back from the package manager — `brew list --cask
wezterm@nightly` vs `wezterm`, `winget list --id wez.wezterm.nightly` vs `wez.wezterm`,
`dpkg -s wezterm-nightly` vs `wezterm`. That cannot drift out of sync with what is actually
installed the way a saved value can, it is self-healing after a manual `brew install`, and it
keeps the seven-file blast radius of a new chezmoi `[data]` key out of this entirely — the
same reasoning as the agentmemory wiring, which is auto-detected with no saved setting. A
WezTerm that no package manager here owns reports channel `unknown`: its version and date are
still shown, and install/upgrade leave it alone rather than fighting over it.

**Switching removes the other channel first, in both directions.** On macOS both casks own
`/Applications/WezTerm.app` and on Debian both packages own `/usr/bin/wezterm`, so the second
install simply refuses. The removal is conditional on actually switching — a machine that
declines WezTerm entirely keeps whatever it already had, which the earlier stable-only
version got wrong by purging nightly unconditionally.

Every network call fails **open and silent**, with a hard timeout: a report that degrades to
"installed version and date" is fine, one that blocks an install or errors a shell is not.
`gh api` is preferred where it exists (5000 requests/hour, authenticated) over the bare REST
endpoint (60/hour per IP).

**Ghostty is offered where it exists.** macOS gets the `ghostty` cask. Windows has no Ghostty
build, so it is absent from `$script:TsTerminalCandidates` there. On Debian/Ubuntu upstream
publishes no official repo, and the bootstrap points at `ghostty.org/download` rather than
running a guessed third-party `.deb` or snap — a wrong guess here installs something the user
did not choose from a source they did not vet. **This originally said the stack ships no Ghostty config; that was reversed on
2026-08-23** — see "Why Ghostty gets a managed config after all" below.

## Why Ghostty gets a managed config after all

The original position was that theme, leader chord and font are baked into `.wezterm.lua`
and "have no Ghostty equivalent", so a Ghostty user got the tooling but not the theming.
That was true of the *tab bar* and turned out to be false of everything else: Ghostty has a
theme system, a font stack, padding and key bindings, and configuring none
of them meant Ghostty looked nothing like the rest of the stack on the same machine.

Four things decided the shape of it.

**Global shortcuts must preserve macOS conventions.** An early version bound
`global:cmd+grave_accent=toggle_quick_terminal`. That intercepted Command-Backtick,
the standard “cycle windows in the active application” shortcut, system-wide.
The stack intentionally ships no quick-terminal configuration now.

**Theme is live, not baked.** Every other consumer of the theme setting reads `resolvedTheme`,
the palette resolved at apply time, because Starship, tmux and Claude cannot re-evaluate at
runtime. WezTerm is the exception — it re-executes its Lua when the OS appearance changes, so
it reads the raw `themeMode`. Ghostty turns out to be in WezTerm's class, not Starship's: its
`theme = dark:X,light:Y` syntax follows the OS by itself. So the template reads `themeMode`,
and `follow` genuinely switches live. Reading `resolvedTheme` would have looked correct and
silently frozen `follow` until the next apply.

`Catppuccin Mocha` is a Ghostty builtin, so dark needs nothing. **VS Code Light Modern is
not**, so the stack ships `themes/vs-code-light-modern`, generated from the same hexes as
`dot_wezterm.lua.tmpl`'s `PALETTES.light.scheme_def`. A test compares the two, because two
hand-maintained copies of a 16-colour palette drift the moment anyone touches either.

**`off` had to be a real revert, and `.chezmoiremove` could not provide it.** The obvious
implementation — list `.config/ghostty/**` in `.chezmoiremove` behind the same gate — is
wrong, because `.chezmoiremove` is evaluated on *every* machine. A user who never opted in,
on a Linux box with a hand-written Ghostty config, would have it deleted by an apply. So the
gate in `.chezmoiignore` only stops re-rendering, and `ts-config ghostty off` does the
removal explicitly, for the machine you actually run it on.

**Nothing on the POSIX side backs up before an overwrite.** The `.bak.YYYYMMDD[.N]`
convention fires in the Windows sync hook and the merge helpers, but a plain `chezmoi apply`
replaces a `$HOME` file with no backup at all — so the first managed apply would have
destroyed a hand-written `~/.config/ghostty/config` silently, with nothing in the diff to
show it. `run_before_20-backup-ghostty.sh` takes the backup, skipping any file that already
carries our marker so a managed config does not spawn a new `.bak` on every apply. That
backup is also what makes `off` a restore rather than a delete.

**No PowerShell twin**, for the same reason `ts-smb` has none: Ghostty ships no Windows
build, so there is nothing there to configure. Stated in `-h` so the absence reads as a
decision rather than drift.

What is still WezTerm-only: the tab bar (Claude pane tints, fleet counters, status line) is
`.wezterm.lua` Lua with no Ghostty equivalent.

**The per-tab project name turned out to be a tmux question, not a Ghostty one.** Ghostty does
have the right primitive — `set_tab_title`, distinct from `set_surface_title`, the same split
that makes the WezTerm approach work — and a title set that way genuinely survives Claude Code
overwriting the OSC title. It is simply unreachable from a script: there is no CLI to drive a
running instance (`ghostty +new-window` reports "not supported on this platform"), and no
escape sequence maps to it. ConEmu's `OSC 9;3` is present in the binary and looks like the
answer, but it sets the *surface* title, which Claude then overwrites — tested, not assumed.

tmux handles the `ccs` case, and terminal-agnostically: while a session is attached tmux
**owns** the outer terminal's title, intercepting the inner program's `OSC 2` completely —
Claude's conversation slug never reaches the terminal at all — and substituting
`set-titles-string`. Setting that to `#{s/^cc-//:session_name}` puts the bare project leaf in
the tab, in Ghostty and WezTerm alike.

The wrappers that do *not* use tmux (`ccd`, `ccdc`, `ccr`, `ccdr`) were initially written off
as unfixable under Ghostty. That was wrong, and the fix is the other half of the problem
rather than the same half again: **stop Claude writing a title at all.** Claude Code honours
`CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1` — verified by probing it in a pty, where the default
run writes `OSC 0 ✳ Claude Code` and the disabled run writes nothing whatsoever. So the
wrapper emits `OSC 2` with the project leaf, Claude leaves it alone, and the tab keeps it.

Both halves are load-bearing and neither is obvious from the other's code, which is why a
test pins them together: the wrapper's `OSC 2` without the env var is overwritten within
seconds, and the env var without the `OSC 2` just leaves whatever the shell last set. The
before/after is exact — `terminal-stack` then `✳ Claude Code`, versus `terminal-stack` alone.

`claude --name <name>` is the documented alternative and produces `✳ <name>`; `ccs` uses it
because a tmux session needs a name regardless. The `cc*` wrappers prefer the env var because
it leaves the title entirely to the stack, so the tab reads `terminal-stack` rather than
`✳ terminal-stack`, matching the existing rule that a tab shows the bare project leaf.

One trap: inside `#{...}` tmux wants the variable *name*. `#{s/^cc-//:#S}` is accepted and
silently renders an **empty** string — a blank tab title, which is worse than the noisy one it
replaced. A test pins the working form.

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

The POSIX side used to be a whole-file chezmoi target, "correct only as long as WSL-side
Claude Code has no plugins and no per-machine keys; the day it does, it needs a `modify_`
script doing the same splice". That day arrived on macOS: Claude Code wrote
`agentPushNotifEnabled` into `~/.claude/settings.json`, and `chezmoi apply` wanted to delete
it — the same silent, diff-less clobber as the Windows incident, one platform over.

`dot_claude/modify_settings.json.tmpl` is that script. chezmoi hands a `modify_` script the
current target on stdin and takes stdout as the new contents, so the splice is native rather
than bolted onto a sync hook. It keeps the three properties that matter, matching the pwsh
helper: ownership comes from the **rendered fragment**, not a hard-coded key list, so
removing a hook from the template removes it from the live file; every other top-level key
and the live file's key order survive byte for byte; and it **refuses rather than guesses** —
a live file that will not parse is echoed straight back, because an unrecoverable hand-edit
is worse than a skipped apply.

Two smaller traps were closed at the same time. `tests/**` was missing from `.chezmoiignore`,
so chezmoi had been deploying the pytest suite into `~/tests/` — the same trap the installer
entry points fell into, and the reason those are listed there. And a `.chezmoiremove` entry
cannot clean that up: chezmoi skips ignored paths entirely, so the stale copies are retired
through `ts_find_stray` in `bootstrap/_cleanup.sh` instead.

## Why `~/.cursor/hooks.json` needs per-entry ownership

Same 19:58 sync, same cause, one level deeper. `~/.cursor/hooks.json` was a whole-file
mirror of `windows/.cursor/hooks.json.tmpl`, and the copy took agentmemory's seven Cursor
capture hooks with it — `hooks.json.bak.20260820.5` (1910 bytes) has them,
`.bak.20260820.6` (578 bytes) is what the sync left.

The key splice that fixed `~/.claude/settings.json` does not work here. That file divides
cleanly: we own whole top-level keys, Claude Code owns the others. This one has a single
top-level `hooks` key holding one array per event, and two of the events we write —
`stop` and `postToolUse` — are events **agentmemory also writes**. Splicing the `hooks`
value wholesale would delete its entries just as effectively as copying the file did.

So ownership is per entry. `bootstrap/_merge_cursor_hooks.ps1` rebuilds each event array
as *our rendered entries, then every foreign entry that was already there*, and hands the
result to the shared splice engine as a synthetic fragment — so only the `hooks` value is
re-serialised and any other top-level key survives byte-for-byte.

An entry is ours if its command references `terminal-stack` (the TTS EXE) or `cursor-tts`
(the legacy per-hook scripts, Windows `.ps1` and WSL `.sh`), or is the `cat > /dev/null`
`afterFileEdit` no-op. The marker list matters more than it looks:

- **Legacy markers are why an upgrade replaces rather than duplicates.** The machine that
  motivated this had `pwsh … cursor-tts.ps1` entries from before the EXE existed; without
  that marker the merge would have kept them *and* added the EXE, double-speaking every
  event.
- **`cat > /dev/null` has to be a marker, not just an exact match against the render.**
  With TTS off we render no hooks at all, so there is nothing to match it against — and it
  still has to go. Turning TTS off must remove our entries and leave everyone else's, which
  the whole-file copy achieved by brute force and a merge has to do deliberately.

Ordering is ours-then-theirs, which is also what `setup-cursor-integration.ps1` produces
(it appends itself after everything it does not own). Both tools therefore converge on the
same array order instead of rewriting the file on each other's account every run — verified
by an on → off → on round trip that returns to exactly four stack entries and seven
agentmemory ones, with a second identical run reporting no change at all.

The WSL-side `dot_cursor/hooks.json.tmpl` is still a whole-file chezmoi target, for the same
reason as its Claude counterpart: nothing else writes the WSL copy today. The day Cursor is
wired to agentmemory inside WSL, it needs a `modify_` script.


## Why the agentmemory harness wiring lives here

It used to live in `docker-local/agentmemory/`, next to the compose file, because that is where
the server's scripts already were. That was proximity, not design, and it put four installers
that rewrite `~/.claude/settings.json`, `~/.codex/hooks.json` and `~/.cursor/hooks.json` in a
repo whose subject is a Docker stack.

This repo already owned that surface. It manages those exact files, ships the TTS hooks for all
three agents, and `bootstrap/_merge_claude_settings.ps1` and `bootstrap/_merge_cursor_hooks.ps1`
exist **specifically** to stop agentmemory's hook entries being clobbered by a sync.

### The boundary is now a directory, not a repository

The seam used to be a repository boundary, which enforced itself: you could not accidentally put a
hook installer in the Docker repo, because it was a different clone. Absorbing that repo removes the
enforcement, so the rule has to be written down and tested rather than merely observed.

**`services/` is the service side.** Anything that defines, builds, configures or runs inside a
container lives there. **Everything outside `services/` is the client side** — anything that
configures a program running on this host. The two meet at exactly two places: a published loopback
port, and `bootstrap/agent-tools.json`, the one file where a port, URL, image tag or version pin is
written down. Neither side reaches into the other by path.

At the command level the same line is `ts-stack` versus `ts-agents`. **`ts-stack` is the only thing
in this repo that starts, stops or builds a container; `ts-agents` may only probe one.** That is not
a style preference — `test_no_project_scope_or_docker_mutation_in_lifecycle_adapters` asserts the
strings `docker compose`, `docker rm` and `restart: unless-stopped` appear nowhere in
`bootstrap/ts-agents.{sh,ps1}`, as case-insensitive matches over the whole file, **so even a comment
naming the compose command fails it**. When a probe fails, `ts-agents` prints the *verb*
(`ts-stack up playwright`), never the command. Having an in-repo verb to point at is what makes that
guardrail easy to keep: before the merge there was no such command, which is precisely why inlining
`docker compose` was tempting.

Three consequences. `bootstrap/ts-agentmemory.*` stays outside `services/` although its whole
subject is agentmemory, because it edits `~/.claude`, `~/.codex` and `~/.cursor`.
`services/stacks/agentmemory/patch-agentmemory.mjs` stays inside, because it patches the npm bundle
in the image. And `services/stacks/*/ts-verify.sh` is the **one deliberate exception**: proving
capture works needs both halves, and only the server-side record is evidence, because the hook
always exits 0.

Three consequences worth writing down.

**The sync applies it, so a plugin upgrade repairs itself.** The hook scripts are vendor files
inside plugin caches. An upgrade replaces the cache and reverts every edit, which silently turns
retrieval off — no error, nothing in any log, and capture keeps working so nothing looks wrong.
Previously the fix was re-running an installer nobody remembered. Now both sync paths run
`ts-agentmemory.ps1 -Check` and only `-Apply` when something is missing, so `ts-update` and
`chezmoi apply` restore it. `ts-doctor` reports the same condition for when you want to know
rather than have it fixed.

**The duplicate is suppressed client-side, before the request.** Codex loads two hook
registrations — `~/.codex/hooks.json` for Desktop and the plugin's own `hooks.codex.json` for the
CLI — so one event fired both. Every observation was stored twice and, worse, every retrieval was
*requested* twice: Codex received the same ~5.7 KB context block twice per prompt. There is no
registration-level fix. `codex plugin` has no enable/disable subcommand, the binary contains no
hooks-toggle key, and Codex **silently accepts unknown plugin config keys** — a deliberately
bogus field was ignored without error, so inventing `plugins."x".hooks.enabled = false` would
look like it worked and do nothing. Dropping either registration costs Desktop or CLI capture.

So the guard sits in the hook scripts. Two details are load-bearing:

- **The mutex is `fs.openSync(marker, "wx")`** — an atomic exclusive create. A read-then-write
  check would let two processes 1 ms apart both pass, which is precisely the race being fixed.
  The observed duplicates were 1–4 ms apart.
- **The key excludes every timestamp.** Each hook process stamps its own, and that is the only
  field that differs between the two registrations. Equal request byte counts prove equal
  *length*, not equal content.

It fails open: any error proceeds with the request, so a broken guard degrades to
duplicate-but-working rather than silently dropping capture. An earlier version of this lived
server-side in `docker-local`'s bundle patch; it only ever covered `/observe`, and absorbed the
duplicate instead of preventing it.

**Originally auto-detected; now explicitly machine-local.** The first harness version avoided a
saved key because the plugin cache was an unambiguous signal and another mirrored value enlarged
the config-store blast radius. Once Headroom and Caveman joined the same lifecycle, that stopped
being a sufficient model: service availability and desired behavior differ by computer. The
explicit `agentmemoryEnabled` key now travels through every config/mirror test, while a missing key
migrates to on when an existing plugin cache proves the pre-toggle machine was already wired.
Runtime wiring remains gated on the plugin cache rather than server reachability, so stopping the
container does not unwire anything.

## Why agent tools are user-global but machine-local

Headroom, Caveman, and AgentMemory should affect every project without adding a
file to every repository, but they cannot be one roaming yes/no choice. Headroom
and AgentMemory depend on loopback Docker services that intentionally do not exist
on every computer, and Cursor's subscription traffic cannot be treated like a
provider API key. The four settings therefore live in terminal-stack's existing
per-machine stores: chezmoi `[data]` on Unix/WSL and its Windows
`%LOCALAPPDATA%\terminal-stack\config.json` mirror. WSL remains authoritative on a
combined machine. Fresh values are off; an existing AgentMemory plugin is the one
migration signal, so introducing the toggle cannot silently disable working hooks.

Docker-local owns service lifecycle, images, secrets, feature flags, volumes, and
data. Terminal-stack owns only the client seam: user-scope plugins/skills/MCP,
shell wrappers, and merge-safe hook entries. That boundary is why `off` and
`uninstall` never issue a Docker command.

Headroom model routing stays out of permanent Claude/Codex provider config. The
shell wrapper probes authenticated `/stats`, injects the base URL and dedicated
proxy token into only the child process, restores the previous environment in
`finally`/function scope, and goes direct when the proxy is down or unauthorized.
Claude keeps provider OAuth in `Authorization` and sends the proxy credential as
`X-Headroom-Proxy-Token`. Codex uses a session-local custom `headroom` provider;
the built-in `openai` provider is reserved and cannot be extended with proxy
headers. No provider is persisted. This preserves provider identity/history and
avoids turning a Docker or credential outage into an agent outage. Cursor has no supported
equivalent launch override, so its choice is explicit: MCP-only (subscription
models direct), BYOK (manual global provider URL and separate billing), or off.

The lifecycle command is also the recovery boundary. `headroom off` saves direct
mode and removes terminal-stack-owned MCP registrations without touching Docker
or data. `on` and `repair` validate authenticated model-proxy access before they
change registrations or save on. Health endpoints cannot serve as that preflight:
Headroom intentionally exempts them from authentication. The independently-run
MCP sidecar is diagnostic only and does not make a working model proxy fail.

Pins live together in `bootstrap/agent-tools.json`; upgrades change there through
review rather than following `latest` service images. `ts-update` checks only tools
enabled on the current machine and repairs their user-global client wiring. JSON
files shared with the agents are edited by named entry, with a backup, so unrelated
MCP servers and hooks survive.

## Why `ts-smb` pins the macOS FUSE library instead of letting rclone choose

`rclone mount` uses cgofuse, which on darwin loads the first FUSE library it
finds in a fixed order: `$CGOFUSE_LIBFUSE_PATH`, then macFUSE's
`/usr/local/lib/libfuse.2.dylib`, then `libosxfuse.2.dylib`, then FUSE-T's
`libfuse-t.dylib`. There is no `--fuse-lib` flag — `--fuse-flag` only forwards
arguments *to* libfuse — so the environment variable is the only lever.

That order is actively harmful on a machine that has both. The development Mac
carried macFUSE 4.2.4 built for macOS 12.1 (December 2021) alongside FUSE-T 1.2.6
(May 2026). macFUSE wins the order, its kext does not load on macOS 26, and the
resulting failure is a **hang, not an error** — and a hung FUSE mount takes any
shell that touches the mountpoint with it. Nothing in the error surface points at
the library that was actually chosen.

So `ts-smb` never invokes `rclone mount` on darwin without setting
`CGOFUSE_LIBFUSE_PATH` explicitly, and `auto` prefers FUSE-T: it is userspace, it
is unaffected by Apple deprecating kexts, and unlike a kext its viability is
decidable from the filesystem alone. macFUSE is used only when
`kmutil showloaded --list-only` proves its kext is actually loaded — a check that
is unprivileged and takes about 0.2s. A merely *plausible* macFUSE ranks **below**
`rclone nfsmount`, because an unloadable kext hangs while nfsmount at worst gives
a slow mount. Prefer degraded-but-working over possibly-wedged.

Two related findings are baked into the code as comments, because both cost real
time to rediscover. Homebrew's macOS rclone refuses to mount at all, aborting
with "rclone mount is not supported on MacOS when rclone is installed via
Homebrew" — a build-time guard no library or variable can get past, so a brew
rclone browses and copies perfectly but can never mount; `ts-smb doctor` reports
it and names the official binary. And FUSE-T's FSKit backend, which looks like
the modern choice on macOS 26, fails outright there (`fuse: mount failed with
error: -1`) where the default NFS backend does not, so `-o backend=fskit` is
**not** passed automatically.

## Why `ts-smb` tracks mounts in a state dir rather than through `rclone rc`

rclone can expose a control API with `--rc`, including `mount/listmounts` and
`mount/unmount`. It is the wrong tool here for three reasons.

The rc server is **per process**. Running `--rc` on N daemonised mounts means N
ports, and knowing which port belongs to which share requires a local record
anyway — so it buys nothing that the state dir does not already provide. The
alternative shape, one long-lived `rclone rcd` that owns every mount, is a second
daemon to supervise, autostart and health-check; the TTS daemon section of
`CLAUDE.md` is a monument to what that costs. And `--rc-no-auth` on loopback is an
unauthenticated channel that can mount arbitrary remotes, which is a lesson this
repo has already paid for once (hence the Host-header checks and `X-TS-Token` on
the TTS dashboard).

So identity and intent live in
`${XDG_STATE_HOME:-~/.local/state}/terminal-stack/smb/<name>.mnt`, in the same
whitespace `key value` grammar as the share store so one parser serves both, and
**liveness is derived, never stored**: pid alive × mountpoint present gives
live/zombie/orphan/gone. The state dir alone cannot tell whether a mount is real;
the mount table alone cannot tell whether a mount is *ours*, which is what makes
`ts-smb umount --all` safe.

The hard constraint underneath is that nothing may `stat`, `ls`, `test -d` or glob
a mountpoint to answer "is this mounted": on a dead FUSE mount those block forever.
Liveness is read from `mount(8)` on macOS and `/proc/self/mounts` on Linux, both of
which answer without touching the path. `findmnt --target` is specifically avoided
because it resolves the path, which touches it.

## Why the SMB share inventory is local-only and never synced

The obvious wish is to keep one share list across machines, and the obvious
vehicle is a GitHub gist. Both halves are wrong.

Gists are owned by user accounts, never by organisations, so "shares grouped by
org" does not map onto them at all. "Secret" gists are not private — anyone with
the URL can read one, and since November 2025 GitHub scans unlisted gists and
reports findings to secret-scanning partners. NAS hostnames, share names and
usernames are exactly the sort of quiet inventory leak that is invisible until it
matters. A private repository is the primitive that actually has org ownership
and access control.

The deeper objection is architectural: a network round-trip must not sit in the
path of `ts-smb mount`. A mount tool has to work when the network is flaky, which
is precisely when someone is using it. Any sync design therefore has to be
local-first with explicit push/pull anyway — at which point the sync is a separate
concern that can be added later without changing anything here.

So `~/.config/terminal-stack/shares.local.conf` is untracked, machine-local, and
the only source of truth. `bootstrap/shares.conf` is tracked but holds **defaults
only and never a host**, so the repository never learns where anyone's NAS is.
No chezmoi `[data]` key is involved either: the inventory is a list of records,
which that store is explicitly not built for, and every field here is per-machine.

## Why `ts-smb` ships without a PowerShell twin

Every other dual-shell command in this stack keeps a parallel pwsh implementation
whose `-h` output stays byte-identical. `ts-smb` does not, as of 2026-08-23, and
that is a decision rather than drift — recorded here, stated in the `-h` prose,
and noted in `CLAUDE.md` so nobody "fixes" the asymmetry without reading this.

Most of what `ts-smb` exists to do is moot on Windows: Explorer and `net use`
already browse and map SMB shares natively, with credentials in Credential
Manager, and the entire FUSE engine layer has no Windows analogue beyond WinFsp.
The interrogation half would still be useful, so a twin may be worth writing —
but it is a separate piece of work, and pretending otherwise by shipping an
untested pwsh file would be worse than the honest gap.

Two notes for whoever writes it. The store's `flags` directive carries a
free-form tail, so a pwsh `-split '\s+'` destroys it — split with a limit of 3
and parse the remainder. And the credential layer maps to Credential Manager, not
to `security`/`secret-tool`.

## Why a PowerShell local may never share a parameter's name

PowerShell variable names are case-insensitive. A local `$foo` inside a function
that takes a parameter `$Foo` is not a shadowing local — it *is* that parameter.
And a parameter keeps the type converter that its declaration attached, for the
life of the variable. So this, in `Read-TsMulti`:

```powershell
param([string[]]$Exclusive = @())
$exclusive = { param($keep) ... }     # assigns to $Exclusive
& $exclusive -1                        # runs a STRING as a command name
```

silently coerced the scriptblock into a one-element `[string[]]` holding its own
source text, and the call then tried to run that text as a command. The error it
produced — `The term ' param($keep) ... ' is not recognized as a name of a
cmdlet` — names the whole function body, which is why it reads as gibberish.

It parses cleanly, so `ParseFile` (our pwsh equivalent of `bash -n`) cannot see
it, and there is no `set -u` for PowerShell to catch the aliasing. It killed
every `Read-TsMulti` call — the terminal question, the tool-group pickers, and so
`install.ps1`, `windows-bootstrap.ps1` and `ts-config apps` — while every test
and the whole POSIX side stayed green, because bash keeps functions and variables
in separate namespaces and cannot have this bug at all.

The rule is therefore blunt: **no local may match a parameter name, whatever the
casing**. `test_no_pwsh_local_shadows_a_typed_parameter` walks the AST of every
`.ps1`/`.psm1` in the repo and fails on any assignment whose target matches a
*typed* parameter case-insensitively but not case-sensitively. It found one other
instance (`Test-TsWsSameVolume`'s `$b` against `[string]$B`) which was harmless —
both sides were strings — and was renamed anyway, because "harmless today"
depends entirely on what type is assigned tomorrow.

Untyped parameters are excluded deliberately: with no converter attached the
aliasing is still confusing but not silently destructive, and including them
turns a precise gate into noise.

## Why the exclusive collapse only fires for a member of the group

`ts_prompt_multi` / `Read-TsMulti` take a set of mutually exclusive keys — today
only `wezterm-nightly` / `wezterm-stable`, because both casks own
`/Applications/WezTerm.app`. Ticking one visibly unticks the other, so the screen
can never show a combination the caller will refuse.

The collapse is driven by the index of whatever was just ticked, passed as
`$keep`: every ticked group member that is not `$keep` gets cleared. That is
correct only when `$keep` is *itself* in the group. When it is not, no member can
equal it, so all of them fail the test and the entire group is cleared.

The terminal question is the only exclusive prompt in the stack, and Ghostty is
its only non-member — so on macOS, ticking Ghostty returned Ghostty **alone**.
WezTerm dropped out of the selection with nothing on screen to say so, and the
install simply did not install it. Both twins had it. The Windows half was
unreachable behind the `Read-TsMulti` crash above, which is the only reason this
surfaced now: fixing the crash made the toggle loop runnable for the first time.

Both implementations now return early when `$keep` is outside the group. The
guard lives inside the helper rather than at the call sites so the `-1`
normalisation path (which has no winner and must still collapse a both-ticked
pre-selection) keeps working unchanged.

A six-case matrix pins the two implementations to identical answers —
`test_exclusive_group_survives_a_non_member_tick_bash` / `_pwsh`. Driving the
loop needs a fake TTY on both sides, and the bash half has a trap worth keeping:
`ts_prompt_multi` reads its answer inside a nested `$( )`, so a shell-variable
answer cursor resets on every call and the test loops forever. The cursor has to
live on disk.

## Why the Python CLI tools bypass winget

`$TsWingetIds` is the catalog's claim about what winget can install, and three of
its entries were not real: `pypa.pipx`, `Python-Poetry.Poetry` and
`nicolargo.glances` all answer *"No package found matching input criteria"*.
`pipx` is in the recommended set, so every Windows machine was offered it on
every `ts-update`, accepted, and watched the install fail — permanently, because
a failed install leaves the tool missing and therefore still pending.

The existing rule for this (`ncdu`, `bandwhich`, `tree`, `atuin`) is that an id
which always fails is worse than an honest "not available on this platform". But
that rule assumes the tool genuinely cannot be installed here, and these can: they
are PyPI packages. Declaring them unavailable would have been an accurate
statement about winget and a false one about Windows.

So they route through `Install-TsPyTool`, the Python sibling of the existing
`Install-TsAiCli` — `uv tool install <name>` first, `py -m pip install --user`
as the fallback. uv is already in the recommended set, needs no ambient Python,
and puts real shims on PATH. This also picks up `ipython`, `httpie` and
`pre-commit`, which had no winget id at all and were being skipped in silence.

Ordering is load-bearing: the Python pass runs **after** the winget pass, because
`python` and `uv` are themselves winget entries, and **before** the agent CLIs.
Both Windows install paths need it — `Install-TsApps` and the separate loop in
`windows-bootstrap.ps1`, which deliberately uses `Install-WingetPackage` so
failures land in the end-of-run report. Skip either and the tools it owns are
silently never installed.

## Why the pending gate asks "can we install it", not "is it in winget"

`Get-TsAppsPending` decides what `ts-update` offers. It gated on
`$TsWingetIds.ContainsKey($id)` under a comment reading *"Only offer what this
platform can actually install"* — which those two things stopped meaning the same
day the agent CLIs arrived. `claude`, `codex`, `cursor-agent`, `grok`, `gemini`
and `pi` are all recommended and all installable through `Install-TsAiCli`, and
none of them is in `$TsWingetIds`. A Windows machine missing four of them was
never told, on any run.

The POSIX twin `ts_app_installable` had it right and its comment even cites the
Windows behaviour as the model it was copying — the Windows side had drifted out
from under the comment. `Test-TsAppInstallable` restores the intended meaning:
true for a winget id, an agent CLI, or a Python tool.

The visible consequence is that Windows users are now offered agent CLIs they are
missing. That is the point, and it matches macOS and Linux — but it does mean the
first `ts-update` after this change has more to say than the last one did.

## Why `Update-TsSessionPath` exists

An installer that ran seconds ago edited the persisted `Path`, but the current
process was started before that, so `Get-Command` cannot see what was just
installed. `Show-TsInstalledApps` therefore reported a tool as `NOT FOUND on
PATH` immediately after installing it successfully — alarming, and wrong.

`Update-TsSessionPath` rebuilds `$env:PATH` from the Machine and User values,
prepending the live process PATH so anything a session set by hand (fnm's
per-shell entry, a manual prepend) survives. It is the pwsh counterpart of
`ts_load_node_env`'s role in `ts_apps_pending`, and it is wrapped in a `try` that
swallows everything: a stale PATH costs an inaccurate report, never an install.

## Why Ghostty is managed on Windows too

`ts-config ghostty` used to refuse anywhere but macOS, and `.chezmoiignore` said
"Ghostty has no Windows build". That was true when it was written and is not any
more: [noctty](https://github.com/amanthanvi/noctty) is Ghostty's terminal core
wrapped in a native Win32 app — tabs, splits, session restore, an OpenGL
renderer, and most of Ghostty's config surface. It was renamed from **WingHostty**
in main on 2026-08-20 after a trademark request from the Ghostty team, but that
landed *after* the v1.3.123 tag, so every release asset published so far is still
named `winghostty-…`. Installing "winghostty" from the noctty releases page is
therefore current, not stale — a distinction worth stating, because the repo, the
release title and the downloaded file disagree with each other by design.

**The config goes to `%LOCALAPPDATA%\ghostty\config`, not the app-named dir.**
This is the whole reason the integration is cheap. Verified against 1.3.123: the
app reads *two* locations, its own `%LOCALAPPDATA%\<appname>\config.ghostty` and
the upstream-compatible `%LOCALAPPDATA%\ghostty\config`, with the latter loaded
first and the former winning on conflict. `<appname>` is `winghostty` today and
`noctty` the day the rename ships, so writing to the app-named path would
silently stop being read on upgrade day, with no error and nothing in any log.
The upstream path is read by both, needs no migration, and — because it is
`ghostty/config` plus `ghostty/themes/` — is the *same relative layout* as macOS
`~/.config/ghostty/`. The generated `vs-code-light-modern` theme file ports
byte-for-byte; a test pins the two copies together, and the existing test pinning
the macOS copy to WezTerm's `PALETTES.light` then covers Windows transitively.

**It is a `windows/` mirror file, not a chezmoi target.** chezmoi only manages
`$HOME` on the machine it runs on, so the Windows copy rides the same
relative-path-preserving sync as `$PROFILE` and `.wezterm.lua`:
`windows/AppData/Local/ghostty/…` → `C:\Users\<you>\AppData\Local\ghostty\…`.
That also means the `ghosttyConfig=off` switch needed a second implementation —
a path skip in both sync paths — rather than the `.chezmoiignore` gate the macOS
side uses. Both skip; neither deletes. Deleting stays `ts-config`'s job for the
same reason it does on macOS: a sync-side removal runs on *every* machine and
would wipe a hand-written config on a box that never opted in.

**The theme is resolved in the sync, not branched in the template.** Ghostty's
config format has no conditionals, and Windows mirror files get plain token
substitution with no template engine — so `{{ if }}` would be copied through
literally. `themeMode` therefore maps to two computed tokens,
`__GHOSTTY_THEME__` and `__GHOSTTY_WINDOW_THEME__`, exactly as
`tmuxPrefixResolved` is derived. The mapping now exists three times (bash sync,
pwsh sync, `ts-config ghostty diff`) and a test pins them together, because a
drift between them shows up as `diff` reporting a phantom change forever.

`follow` cannot be expressed by pinning `window-theme`, and an explicit mode
cannot be expressed by a split theme: a `dark:…,light:…` theme *always* tracks
the OS. That is why the two values move together rather than one deriving from
the other.

**Windows drops four macOS directives and gains one.** `font-thicken` and
`window-colorspace = display-p3` are macOS rendering niceties; the three `cmd+…`
readline chords have no Cmd key to hang off (`Home`/`End`/`Ctrl+U` are the
natives); and `macos-option-as-alt` is absent from the Windows option set
entirely. That last one is worth stating precisely: it is *silently ignored*, not
diagnosed, so shipping it would have cost nothing — it is dropped because a
config that pretends to set something it cannot is a lie to the next reader.
Windows gains `window-theme`, which drives the DWM title bar.

**There is no honest syntax gate on Windows.** On macOS `ghostty
+validate-config` exits 1 on error and `ts-config ghostty status` runs it as a
real check. Neither Windows equivalent works on 1.3.123: `+validate-config` fails
with `FileTooBig` even for a 14-byte config, and `+show-config` reports *nothing*
for an unknown key or for a bad value on a real key — it silently drops both.
Every "accepted" result from probing options that way is therefore meaningless,
which is a trap worth remembering the next time someone reaches for
`+show-config` as a validator. `status` prints `validate: unavailable on this
build` rather than a check it did not run.

**Offered, never installed.** The terminal question now lists Ghostty on Windows
and pre-ticks it when the executable is present, the same shape as the WezTerm
channels — and like them it is deliberately absent from `$TsTerminalWingetIds`,
so ticking it prints the install command instead of running it. winget does carry
`AmanThanvi.winghostty`, currently the same 1.3.123 the releases page ships, so
either source is fine; the managed config lands the same way regardless, and
lands whether or not the app is installed at all.

One PowerShell trap this uncovered, unrelated to Ghostty but caught by it: a
`switch` unrolls a one-element array to a **scalar**, so `$preticked += 'ghostty'`
concatenated strings instead of appending and produced the single nonsense key
`wezterm-nightlyghostty` — leaving the entire question unticked. The `@( )` around
the switch is load-bearing, and a test pins it.

**The Windows config pins pwsh and goes opaque, and both are deliberate.**
`command = pwsh.exe -NoLogo` mirrors WezTerm's `default_prog`, because noctty's
picker will happily hand you "Windows PowerShell" — PowerShell **5.1**, which
this stack configures not at all (the managed profile is
`Documents\PowerShell\Microsoft.PowerShell_profile.ps1`, pwsh 7 only). Worse,
5.1 carries its own execution policy, tracked separately from pwsh 7's, and
defaults to Restricted on client Windows, so it refuses to dot-source *any*
profile — ours, or the unrelated `Documents\WindowsPowerShell\profile.ps1` that
other installers drop there. The result is a wall of `SecurityError` on every
launch that looks like a terminal fault and is not one. Pinning the shell avoids
it; raising the policy is a machine decision and stays the user's.

Opacity is the second divergence: the macOS twin's `background-opacity = 0.97`
plus `background-blur = 20` reads well on a Mac, but on Windows
`shouldUseSystemBackdrop` turns exactly that pair into a DWM tabbed backdrop, and
the backdrop is painted under the **Win32 chrome** as well as the terminal
surface — washing out the overlay surfaces, most visibly the `Ctrl+Shift+P`
command palette. The Windows config therefore sets `background-opacity = 1` and
leaves `background-blur` unset, which fails both halves of that condition. It
also matches WezTerm on Windows, which is fully opaque already. A test pins the
pair *and* asserts macOS is still translucent, so the divergence stays visible
rather than quietly converging.

## Why the pwsh profile caches tool init instead of running it

`starship`, `zoxide` and `fnm` all print shell code that the profile evaluates.
Running them is the obvious implementation and it was costing a WezTerm pane most
of a second before it drew a prompt. Measured on a machine with a third-party
antivirus (Datto AV) scanning every exec:

| step | cold | warm |
|---|---|---|
| `starship init powershell` | 1,835ms | ~50ms |
| `zoxide init powershell` | 869ms | ~90ms |
| `fnm env --use-on-cd` | 764ms | ~40ms |
| `Add-Type` for the console-codepage P/Invoke | 339ms | 339ms (never cached) |

Two of those numbers deserve a note. `starship init powershell` emits a
*bootstrap* that re-runs starship with `--print-full-init`, so the old line paid
**two** starship spawns; asking for `--print-full-init` directly pays one, and
none once cached. And `Add-Type` runs the C# compiler every session — PowerShell
keeps nothing between sessions — so that 339ms was per pane, forever.

So the generated text is cached under `%LOCALAPPDATA%\terminal-stack\cache\`,
keyed on the producing binary's path, mtime and size, and the codepage helper is
compiled once to an assembly there and loaded with `Add-Type -Path` (~25ms).
Profile cost on that machine went from a 1,110ms median to 697ms, and from a
1,062ms floor to 355ms.

Three details are load-bearing:

- **`Get-TsToolInit` returns a file to dot-source, not a string to
  `Invoke-Expression`.** Same 10KB of starship init: 427ms dot-sourced against
  612ms through `Invoke-Expression`. The cache's key line is a `#` comment
  precisely so the file stays a plain dot-sourceable script.
- **The caller dot-sources it, never the helper.** `$PROFILE` is dot-sourced into
  the global scope; a function body is not. starship's `New-Module` and zoxide's
  `function global:` definitions would land somewhere the prompt never sees.
- **`fnm env` is not cached.** Its output embeds a per-shell
  `FNM_MULTISHELL_PATH` containing the PID and a timestamp; a cached copy would
  point every shell at one other shell's directory.

The remaining floor is starship's init itself: ~430ms to parse 10KB, which is not
a spawn and not ours to trim. Nothing here changes what the prompt looks like, so
a wrong cache shows up as a stale prompt rather than a broken shell — and the
stamp mismatch that follows any starship upgrade regenerates it.

## Why fnm does not resolve `package.json` engines

fnm resolves `engines.node` from `package.json` when no `.nvmrc` or
`.node-version` is present, and that is on by default (`FNM_RESOLVE_ENGINES`).
Two consequences, both bad on a Windows box:

1. `package.json` is in nearly every JS repo, so fnm's `use-on-cd` hook fires on
   nearly every `cd` — a 738ms measured spawn here, on a directory change.
2. An `engines` range that no fnm-**installed** version satisfies turns `cd` into
   an interactive prompt: `Can't find an installed Node version matching
   >=24.0.0. Do you want to install it? answer [y/N]:`. fnm only considers
   versions *it* installed, so this fires even when the active `node` already
   satisfies the range — a system Node 26 against `>=24` still gets asked.

Both shells therefore pass `--resolve-engines=false`. An explicit
`.nvmrc`/`.node-version` pin is still honoured: that file is somebody's decision,
an `engines` range is metadata. With the flag off, fnm's own generated hook stops
testing for `package.json` at all, so `cd` into a JS repo costs 2ms instead of
740ms.

Keep the fallback in both shells. fnm before 1.36 has no `--resolve-engines` and
exits non-zero, and `eval`/`Invoke-Expression` of the resulting empty string
would leave fnm unwired with nothing printed.

## Why the service stacks moved into this repo

Three headline features — agentmemory capture and retrieval, Headroom compression, Kokoro voice
notifications — do not work unless a Docker service is running. Those services lived in a separate
private repo, and one of them (the agentmemory console) lived in a *third* repo that the second
built from a pinned commit SHA. Shipping a change across that boundary meant three clones, two
remotes, and a push, re-pin, rebuild loop.

The seam had real costs beyond inconvenience. `check-capture.sh` carried an entire section that
existed only because the two repos could not call each other. Both absorbed repos still told macOS
and Linux users that the bash hook wiring did not exist, which had stopped being true when
`bootstrap/ts-agentmemory.sh` shipped. And a version pinned in `bootstrap/agent-tools.json` and the
same version pinned in a compose file could only be reconciled by hand — now a test does it, which
is a check that was not *possible* before.

What did not move: the upstream projects themselves. `@agentmemory/agentmemory`, the `iii` runtime,
Headroom, Kokoro, Qdrant, Neo4j and the Playwright MCP image are third-party, pinned, and patched at
build time. This repo owns the compose glue, the patches and the lifecycle, not the software.

## Why the console builds from the working tree, not a pinned SHA

The console's compose build context was a pinned `github.com/...#<sha>`, which is the right answer
when the source is in another repository: a locally built image from a git context gets an immutable
ref rather than a branch. With the source in `services/console/`, the same pin costs a push, a
re-pin and a rebuild for every change — the loop `update-console.*` existed to automate.

The context is now `../../console`, so what runs is what you have checked out. The trade is real and
worth stating: a dirty working tree builds a dirty image. `git status` before `ts-stack up` is the
whole discipline, and `ts-stack --dry-run up` shows exactly what would be built.

Dropping `update-console.*` also dropped two behaviours that had to be inherited rather than lost:
the double `--env-file` billing deploy in the correct order, and the post-rebuild `/healthz` verify.
Both live in `ts-stack` now. A lone `--env-file .billing.env` *replaces* `.env` as compose's
interpolation source, so every `${OPENAI_*}`-derived value the console displays resolves to empty —
a blank provider panel, no error, everything healthy.

## Why everything is named `ts-`, and why the volumes needed a migration

`docker ps` on a working machine also lists that person's own projects. Before, this stack's
containers were indistinguishable from them: projects were the directory name, containers mixed
three conventions (a bare `kokoro`, a hyphenated `headroom-proxy`, and nothing at all for the memory
server — Docker called it `agentmemory-agentmemory-1`), and volumes were split between prefixed and
bare.

Projects are now pinned with compose's `name:` key rather than `COMPOSE_PROJECT_NAME` in five `.env`
files: tracked, so every machine agrees, and unaffected by which directory you run from.

Volumes are the one part that touches data, and two details only a live `docker volume ls` shows.
Headroom's three were project-prefixed on disk (`headroom_headroom_workspace`, and so on) because
they are plain named volumes, while agentmemory's two are `external: true` and so never had a
prefix. And renaming the compose *key* alone would have produced
`ts-headroom_ts-headroom-workspace`, so the three pin `name:` explicitly.

They stay non-external deliberately: **the asymmetry is the safety property**. `down -v` cannot
touch an external volume, which is why every memory ever saved lives in one, while headroom's graph
and vectors are removable by design behind `--destroy-data`.

`ts-stack up` refuses to start while a legacy volume exists and its replacement does not, because
compose would otherwise create an empty one and start the stack with no memories in it, reporting
success. `ts-stack migrate-volumes` copies in a container, verifies the file count came across, and
leaves the old volume as the rollback. The same trap caught `ts-stack bootstrap`, which happily
created the empty replacement until it learned the same rule.

## Why the agentmemory secret cache kept a fallback when it moved

The cache moved from `$XDG_CONFIG_HOME/docker-local/agentmemory.secret` to
`$XDG_CONFIG_HOME/terminal-stack/agentmemory.secret`, which sounds like a rename and is not. The
*reader* is JavaScript already injected into vendor hook files on live machines, and those files are
only rewritten when `ts-agentmemory --apply` runs. Moving the writer alone turns 401-recovery into a
permanent no-op — the exact failure that cost 56 consecutive captures on 2026-08-21 with nothing in
any log, because `/observe` swallows errors and retrieval discards non-2xx.

So the writer writes both paths and the injected reader tries both. The dangerous part was the edit
MARKER: it defaults to the full replacement text, so changing that text makes an already-patched file
look unpatched — and the injected block *ends with* `function authHeaders() {`, which is the edit's
own anchor, so a re-apply would have injected a second copy of the whole recovery block into every
hook script on every wired machine. Both twins now pass an explicit marker,
`let amFreshSecret = null;`, that every form of the block shares.

## Why an optional `env_file` is a trap, and how the merge fell into it

`services/stacks/agentmemory/docker-compose.yml` loads two env files: its own
`.env`, and a shared one holding the single `OPENAI_API_KEY` that wins over the
per-provider rollback settings. Both are `required: false`, because a fresh
clone must start in degraded no-LLM mode rather than refusing to boot.

In docker-local the stacks sat one level under the repo root, so the shared file
was `../.env`. Absorbing the tree added a level (`services/stacks/<stack>/`) and
that path silently became `services/stacks/.env` -- a file that has never
existed. `required: false` means compose reports **nothing**: no warning, no
non-zero exit, no line in `docker compose config`. The container started
healthy, every check passed, and `OPENAI_API_KEY` was simply absent.

What that looked like from the outside is the part worth remembering. With no
usable provider AgentMemory returns an empty completion instead of raising, so
the log line reads `"outcome":"success"` with `providerLatencyMs: 0`; the empty
body then fails XML parsing, retries once, and dead-letters. 52,570 compression
jobs accumulated that way. Capture, search and local embeddings kept working
perfectly the whole time, which is exactly why nobody looked.

Three things now guard it:

- The path is `../../.env`, with the level spelled out in a comment.
- `test_every_optional_env_file_points_at_a_documented_location` asserts every
  `env_file` path resolves next to a **tracked** `.env.example`. That is true of
  `services/.env` and of each stack's own `.env`, and false of any directory a
  wrong number of `..` lands on. It needs no real `.env`, so it runs anywhere.
- `ts-verify.sh` asks the provider **from inside the container**, using the
  container's own `OPENAI_BASE_URL` and `OPENAI_API_KEY`. An unset base URL is a
  skip (no chat provider is a supported configuration); a configured provider
  that refuses is a failure. Asking from outside would have proved nothing --
  the key is on the host either way.

The same merge broke seven maintenance scripts the same way: they source
`"$SCRIPT_DIR/../_common.sh"`, and the helper both moved a level and was renamed
to `_stack.sh`. The rename sweep rewrote every `dl_` call *inside* those files
and missed the source line, so each one died on its first executable statement.
Nothing caught it because these are the scripts you reach for only when
something is already wrong. `test_every_sourced_helper_path_resolves` now checks
that every `. "$SCRIPT_DIR/…"` target exists.


## Why agent007memory is its own compose project

The console started as an overlay: `docker-compose.console.yml`, merged into the
agentmemory project through `COMPOSE_FILE`. That was the right shape while it
was a separate repository pinned by commit SHA, because the overlay was the only
place the two met.

It is the wrong shape now. The console is a 104-file TypeScript application with
its own lifecycle — you rebuild the UI while the memory server keeps running —
and as an overlay it appeared in `docker ps`, in Docker Desktop and in
`ts-stack status` as a second row under someone else's name. Splitting it makes
"3110 answers, 3111 does not" read as *one stack down and the other fine*
instead of a mystery inside a single stack, which is exactly the verdict the
check ordering has always been trying to produce.

Three things had to be built to make a cross-project stack work, and all three
are discovered rather than registered — the property that adding a stack takes
no edit anywhere:

- **`ts-after`**, one stack name per line: this stack starts after those, and
  stops before them. Needed immediately, because stacks are listed lexically and
  `agent007memory` sorts *before* `agentmemory` (`0` < `m`) while joining a
  network `agentmemory` creates. An external network cannot be joined before it
  exists, so a fresh `up` failed with "network not found" on a stack that was
  perfectly configured. `down` and `restart` walk the reverse order, and
  `restart` takes everything down before bringing anything up: restarting
  agentmemory while the console still held its network left the console pointed
  at a container that no longer existed, recovering only on its own timer.

- **`ts-envfiles`**, extra `--env-file` interpolation sources applied before the
  stack's own `.env`. The console displays which model and endpoint AgentMemory
  is configured for, and the authority on that is the agentmemory stack's
  `.env`. The alternative was a second copy of those values that silently went
  stale.

  The distinction it rests on is load-bearing and easy to lose: `--env-file` is
  compose's *interpolation* source and injects nothing into a container, while
  an `env_file:` key hands the container every variable in the file — including
  `OPENAI_API_KEY`, which the console is deliberately never given. A test
  asserts no path appears in both.

- **A pinned network name.** `ts-agentmemory-net`, not the project-derived
  `ts-agentmemory_default`. Anything that reaches across projects has to be
  pinned, or it changes under the other side the day that project is renamed.
  For the same reason the console addresses `ts-agentmemory-server` by container
  name rather than the `agentmemory` service alias.

`depends_on` does not survive the split — compose ignores it across projects,
silently — so it is gone rather than left behind reading as ordering that is not
happening. The console tolerates an upstream that is not answering yet; that is
what `restart: unless-stopped` is for.

What did **not** change: the history volume keeps its agentmemory-era name
(`ts-agentmemory-console-history`). Renaming it would mean migrating a year of
reporting history to buy nothing. The billing helpers did move, because they
only ever configured the console.

## Why only one memory backend runs

AgentMemory and Headroom both do semantic memory. The install asked about them
as two independent yes/no questions, so every combination was reachable,
including the one nobody wants: two stores, each holding half the story, with no
way to know which one has the answer you are looking for.

It is now one question with one slot — `memoryBackend`, `agentmemory` |
`headroom` | `none`. A single slot cannot hold two values, so the bad
combination is unrepresentable rather than merely discouraged. `headroomEnabled`
stays independent because compression is genuinely orthogonal; only the memory
half is exclusive.

`agentmemoryEnabled` is derived from it, and `ts_memory_apply` /
`Set-TsMemoryBackend` is the only thing that writes either key.
`ts-config agents agentmemory on` refuses when the backend is something else and
names `ts-config memory agentmemory`, rather than silently reconciling —
quietly undoing what someone asked for is worse than telling them the two
disagree. `ts-doctor` reports drift for the case where something wrote the key
anyway.

The default is `agentmemory`, and that is not a preference: it is what every
machine has effectively been running (see below), so upgrading into this key
changes nothing about how any existing install behaves.

## Why Headroom's memory is a compose overlay, not a flag inside the proxy

The thing that made this a bug rather than a tidy-up: **Headroom's memory has
never run.** The proxy's command is `headroom proxy --host 0.0.0.0`, and memory
engages only when it is passed `--memory`. The compose file set `QDRANT_URL` and
`NEO4J_URI` and started both databases, so everything looked wired — and the
proxy never contacted either. Measured on a machine that had been running it for
months:

```
headroom memory stats   0 memories      qdrant   0 collections
/stats mcp              0 retrievals    neo4j    0 nodes
                                        ts-headroom-neo4j  899 MB RSS
```

Four containers reporting healthy, two of them holding nothing, and no check
anywhere that would have said so. Note also that `--memory-qdrant-url` reads
`HEADROOM_QDRANT_URL`, not the un-prefixed `QDRANT_URL` the datastores
themselves were wired with — so even the variable that was set was the wrong
name. Both are set now, and the flag is passed explicitly on the command line as
well.

So the split is `docker-compose.memory.yml`, selected through the stack's
`COMPOSE_FILE`, and it carries three things that must travel together: the two
services, the proxy's connection settings, and `--memory`. Putting only the
services behind the overlay would have preserved the original bug in a tidier
shape.

Why an overlay rather than a profile: a profile can gate services but not the
`command:` of a service that is in the base file, and `--memory` has no
environment variable to gate instead. The overlay also means Qdrant and Neo4j
are never *referenced* on a machine that does not want them, so they are never
pulled — which is most of the point on a laptop.

`ts-config memory` restarts headroom rather than printing the command. The
setting and the running state disagreeing is exactly the failure mode above, and
a restart of a compression proxy costs an in-flight request, not a pane full of
work (contrast `ts-mux restart`, which is deliberate for that reason).

## `ts-after` and `ts-envfiles`

Two small per-stack files, both discovered by name rather than registered, both
added because the console split needed them:

- **`ts-after`** — stack names this one must start after, and stop before.
  Stacks are listed lexically, and `agent007memory` sorts before `agentmemory`
  (`0` < `m`) while joining a network `agentmemory` creates. An external network
  cannot be joined before it exists, so without this a fresh `up` failed with
  "network not found" on a stack that was perfectly configured.

- **`ts-envfiles`** — extra `--env-file` paths, applied before the stack's own
  `.env` so its values win. These are compose *interpolation* sources and inject
  nothing into a container. The distinction is load-bearing: an `env_file:` key
  hands the container every variable in the file, and the console reads the
  agentmemory stack's `.env` for display values — a file that contains
  `OPENAI_API_KEY`. A test asserts no path appears in both.

`ts-checks.<x>.conf` follows the same naming rule as the overlay it belongs to.
Without it an overlay's services either go unchecked, or their checks sit in the
base file and fail on every machine that has not enabled the overlay — which is
precisely what the Qdrant and Neo4j health checks were doing: passing
everywhere, proving nothing.

## Why Headroom MCP uses Docker stdio instead of port 8788

Port `8788` belongs to nginx and serves the Headroom dashboard. It never exposed
MCP, so registering `http://127.0.0.1:8788/mcp` made Codex fail every startup
at `initialize` with nginx `404`; Claude's quieter reporting made the same broken
registration look healthy.

Publishing another unauthenticated MCP listener would add network surface and a
second lifecycle to manage. The proxy container already contains the matching
Headroom CLI, so clients now launch its MCP server on demand with `docker exec -i`
and stdio. Repair/status sends a real JSON-RPC initialize request, then checks
server identity and tool capability before writing Claude, Codex, or Cursor
registration. Model routing stays independently gated by authenticated `/stats`.

Trade-off: Docker and `ts-headroom-proxy` must be available when an MCP client
starts. That dependency already exists for Headroom, and failed reconciliation
removes stale registrations so Codex starts cleanly in direct mode.
