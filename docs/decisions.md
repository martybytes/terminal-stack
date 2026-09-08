# Design decisions

Notes on choices made during the original deployment that aren't obvious from reading the code. Order is roughly chronological.

## The claims audit

`CLAUDE.md`, `ARCHITECTURE.md` and `README.md` accumulated assertions of the form
"X is pinned by a test" and "never do Z because W". On 2026-08-25 every checkable
one was verified against `tests/`. Most held. These did not, and each is now
either enforced or corrected:

| claim | was | now |
|---|---|---|
| "There is no build, no test suite, no lint" (`CLAUDE.md` line 9) | false in three ways, and contradicted 19 lines later | replaced with the actual gate list |
| `tstack mux` `-h` kept byte-identical between the twins | nothing compared them; only the `tstack services` pair had a test | `test_ts_mux_help_is_byte_identical_between_the_twins` |
| `wso` `-h` byte-identical (`wso.sh:21-22` marker) | a comment, unenforced | `test_wso_help_is_byte_identical_between_the_twins` |
| `ts_app_installable` gate | bash half pinned twice, pwsh twin **zero** times, so it could drift silently | `test_app_installable_is_pinned_on_both_sides_not_just_bash` |
| "Never pipe `Where-Object` into `Set-Content`" | prose only | `test_no_where_object_piped_straight_into_set_content` |
| backup convention "reference: `run_after_90-sync-windows.sh:28-34`" | stale; the `.bak` block starts at 27 | line number replaced with a description |
| `check-capture.sh` probes `command -v ts-agentmemory` | there was never an executable by that name; it matched nothing on every host | probe removed, clone paths lead |
| `.githooks/pre-commit`: "installed by `bootstrap.sh --apply` / `bootstrap.ps1 -Apply`" | **neither file has ever existed in this repo**; nothing set `core.hooksPath`; it was unset in every clone | `ts_install_git_hooks` / `Install-TsGitHooks`, called by all three bash bootstraps, pinned by `test_the_git_hooks_are_actually_installed_by_something` |

The last one is the reason the others survived: the repo's only automated gate had
never executed anywhere. That is how a literal TAB byte in `$PROFILE:1705` broke
`tstack services` on Windows from `54da056` onward with nobody noticing, and how the
`services/console` suite stayed red after being merged.

**The lesson is structural, not clerical.** An unenforced invariant written as
settled fact is worse than no invariant: it is read, believed, and quietly
violated. Two guards now exist for the class -
`test_the_hooks_never_claim_a_file_that_does_not_exist`, and `repo_file()` in
`tests/test_agent_tools.py`, which makes any "string X must appear in file Y" test
fail loudly when Y is deleted instead of passing vacuously forever.


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

- **Per-machine content lives in `profile.local.ps1`** (dot-sourced at the end of `$PROFILE`, never synced — the Windows counterpart of `~/.zshrc.local`, since v1.1.0). Anything personal that goes into `$PROFILE` itself *will* be replaced on the next `tstack update`/apply — recoverable from the `.bak`, but gone from the live file.
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

WezTerm has no native mouse "tear-off": you cannot drag a tab off the bar to spawn a new window (long-standing limitation — see GH discussion #4080 and issue #549). The supported equivalent is the Lua `pane:move_to_new_window()`, which we bind to `LEADER o` (the leader — default `Ctrl+Space`, configurable via `tstack config leader` — then `o`) via `wezterm.action_callback`, plus `Ctrl+Shift+O` for access without the leader. `o` was the obvious free letter among the leader bindings at the time and is mnemonic for "out". For ad-hoc use without a keybinding, the CLI does the same thing: `wezterm cli move-pane-to-new-tab --new-window`. Bound in both WezTerm configs.

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

## Why the mux domain is opt-in, not the default (`tstack mux`)

The same WebGpu crash motivated a structural fix beyond the renderer swap: with panes local to the GUI process, *any* GUI abort — renderer panic, driver update, misclick on a "close window" prompt — kills every shell and everything running in them. Hosting panes in a `wezterm-mux-server` process outside the GUI (`config.unix_domains = { { name = 'main' } }` + `config.default_domain = 'main'`) fixes that: a GUI crash leaves every pane alive and relaunching WezTerm reattaches.

It shipped unconditionally in August 2026 and that was the mistake. The mux is a real change in how the terminal behaves, and it arrived through a routine `tstack update` — panes started coming up in a domain the user never asked for, with two visible side effects:

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

`tstack mux` is that command, and it also owns the live server, because the manual path (`taskkill /IM wezterm-mux-server.exe /F`) is both easy to get wrong and impossible from WSL without knowing the interop trick:

| Command | Does |
|---|---|
| `tstack mux` / `tstack mux status` | the setting, the *rendered* setting (catches an un-applied change), the server pid, the pane count |
| `tstack mux on` / `off` | flip `weztermMux`, re-render, and say what takes effect when |
| `tstack mux list` | `wezterm cli list` |
| `tstack mux kill` / `restart` | stop / cycle `wezterm-mux-server` (confirmed — it kills every pane it hosts) |
| `tstack mux reset` | back to the default: off + re-apply + kill + clear stale sockets |

One implementation, `tstack/commands/mux.py`. It was two - `bootstrap/ts-mux.sh` and `Invoke-TsMux` in `$PROFILE` - kept in agreement by hand. On WSL the GUI, the mux server and the rendered config are all Windows-side, so the bash script drives them over interop (`tasklist.exe` / `taskkill.exe` / `wezterm.exe`) rather than the Linux process table.

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
`tstack update`. Skipping `setup()` costs us nothing today and the comment in both configs
says loudly why it must not be "simplified" back.

Default **off**, for the same reason the mux domain is: a terminal that silently
reopens last week's shells is a surprise, not a feature you chose. `tstack config restore
on` turns it back on, and that is a plain boolean with no live process behind it — which
is why it lives in `tstack config` rather than earning its own `ts-*` command the way
`tstack mux` did.

Two deliberate consequences:

- **The autosave keeps running when the setting is off.** `Leader+S` / `Leader+L` are
  unaffected, and `current_state` keeps tracking your live workspace — so flipping the
  setting on restores *the session you had*, not a stale one from whenever you turned it
  off.
- **No saved state is deleted.** Turning the feature off is not a reason to throw away
  the user's sessions.

A `tstack mux status`-style saved-vs-rendered drift line would be cheap here (the gate is a
column-0 `local RESTORE_ENABLED = '<on|off>'`, greppable exactly like `MUX_ENABLED`) but
is deliberately skipped: every `tstack config` mutation ends in an apply, so the drift the
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

What that Lua draws, moved here out of `CLAUDE.md`'s 40 KB budget: the active tab is a
solid accent block and inactive tabs with Claude panes wash with their `cc_state` tint; a
Claude pane's label is the bare project leaf, a remote pane's is a ` host ·` chip plus the
directory leaf, never a full path. The status bar's left side renders *nothing* in the normal
state -- a coloured badge appears only while the leader is pending or a repeat mode is live --
and its right side carries the Claude fleet counts (`cc_state` across every mux pane), the
workspace when it is not the default, and a clock. Leader+s
(`wezterm.GLOBAL.show_identity`) toggles the `user@host | path` detail, nothing else.

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

*(Amended: the root is now changeable after install, by `ws --set <dir>` or `tstack workspace set <path>`, and it is still not a chezmoi key. A fourth reason arrived with the command: `store.set` writes `key = "<value>"` into TOML unescaped, so `schema.Setting.validate` refuses any text value containing a backslash — a Windows workspace path could not be a `[data]` key even if the other three objections were answered. The writer moved to `tstack/workspace.py`, which emits the same `export WORKSPACE_DIR="<path>"` line the installer does and matches on `^\s*export\s+WORKSPACE_DIR=`, so the four writers that exist can each find and replace the others' output. `ws --set` stays a shell function purely because a child process cannot export into its parent: it runs the command and exports the path the command prints on stdout, which is why that command prints the path and nothing else there.)*

## Why does `tstack rollback` use a recorded SHA file instead of `git reflog`?

`tstack update` writes the pre-pull HEAD to `~/.local/state/terminal-stack/rollback-sha` before pulling, and `tstack rollback` resets to exactly that. The alternative — `git reset --hard HEAD@{1}` — is shorter but wrong in practice: the reflog entry one back is whatever git did last, which after a few manual operations in the clone (branch switches, amends on a dev machine where the clone doubles as a checkout) is not "the state before the last tstack update". An explicit file is unambiguous, human-inspectable (`cat` it to see where rollback would land), and survives `git gc`. The file is only written when an update actually has incoming commits, so a no-op `tstack update` can't clobber a real rollback point. Both commands refuse to run over a dirty working tree for the same dev-checkout reason.

## Why convert zsh `cc*` from aliases to functions just for the tab title?

Aliases can't run code around the wrapped command. Setting and clearing the WezTerm tab title requires a pre-step and a post-step around the `claude` invocation. Either we (a) leave zsh as plain aliases and accept that only the PowerShell side gets the per-project tab title, or (b) promote zsh to functions matching the PowerShell try/finally pattern. We chose (b) for the same reason the PowerShell side does it: when you have four or five Claude panes open in WezTerm under WSL, the tab title is what tells you which project each pane is for. Without it the tabs are all just `pwsh` / `zsh` and you have to click each one to remember. The cost is a one-line helper (`_wez_tab_title`) and a small amount of bookkeeping (`local rc=$?; ... return $rc`) since zsh has no `try/finally` — that bookkeeping matters because without it the function would always exit 0 and mask Claude's exit code from scripts that wrap it.

The title text and the per-prompt clearing behavior are covered separately under "Why per-tab `cc • <project>` instead of one big tab name?" (amended: bare project leaf now) and "Why `wezterm cli set-tab-title` and not OSC 0?" — this entry is just about *why functions, not aliases*.

## Why Claude Code TTS is opt-in chezmoi data (not a sentinel file)

Like tab tinting, TTS is stack infrastructure — but unlike `ccnotify` (a sentinel file users toggle without re-apply), **enabling TTS adds hooks to the managed whole-file `settings.json`**. Conditional chezmoi template blocks keyed on `ccTtsEnabled` mean `tstack config tts off` + apply truly removes the hooks; no orphan processes or stale sentinel files. Runtime knobs live in **`~/.claude/tts/config.json`** (chezmoi-rendered) with optional untracked **`local.json`** merged at hook time — not in the template files themselves. **Async-only:** hooks spawn background workers and return immediately. **WSL playback goes through Windows interop** because Docker forwards `:8880` but audio devices do not.

**Hooks vs MCP:** lifecycle alerts (stop, AskQuestion, permission) must stay **hooks** — IDEs fire those events; an MCP server would not hear them unless the model voluntarily called it. A future **terminal-stack-tts MCP** can share the same `cc-tts-lib` for on-demand `speak` from Claude Desktop / Co-work; it complements hooks rather than replacing them.

*(Amended: the daemon upgrade below layers session-aware announcements on top of this design without changing any of it — the direct path described here is now the fallback, and everything in this entry still holds when the daemon is off or unreachable.)*

## Why the TTS daemon is a native tray process, not a Docker container

The session-aware announcement layer (`ccTtsDaemon`, `bootstrap/tts-daemon/ttsd`) needs two things a container can never have on Windows: an audio path to the host (Docker Desktop's utility VM has no sound device — there is no `/dev/snd` to pass through) and access to the host's per-app audio sessions (`ISimpleAudioVolume` enumerates only the caller's logon session, so a container cannot see or duck `Spotify.exe`'s mixer entry). Kokoro stays in Docker because synthesis is stateless HTTP — the daemon calls the same `:8880` endpoint the direct path always used. Everything that must touch host audio — playback, ducking, media pause/resume — lives in the one native process; anything else can reach it over `127.0.0.1:8890`.

## Why every Windows hook calls one GUI-subsystem EXE

The previous Windows path looked backgrounded but still started console-subsystem children: hook → PowerShell → Python → `ffprobe.exe` / `ffplay.exe`. Windows could allocate or flash a command window at any of those boundaries. Hiding only the first process was insufficient. `terminal-stack-tts.exe` therefore owns hook normalization, daemon posting, synthesis fallback, WinRT playback, SAPI, and duration probing in-process. PyInstaller's windowed bootloader marks it as GUI subsystem, and redirected hook JSON is read through inherited Win32 standard handles because `sys.stdin` is intentionally absent in a windowed build. Claude, Cursor, Codex, and WSL interop all call that EXE directly.

The **never-silence** rule remains, but the fallback is now another mode of the same binary: if the daemon is disabled or unreachable, the short-lived hook process starts a detached `_direct` worker with `CREATE_NO_WINDOW`. No PowerShell, `cmd`, Python runtime, FFmpeg tool, or console host belongs on a successful spoken path. Any unavoidable auxiliary child (currently only optional WezTerm CLI inspection) goes through the centralized hidden-process helper.

## Why the TTS source and PyInstaller spec live in `bootstrap/tts-daemon/`

The source, tests, build script, and spec ship with `tstack update`, while the built runtime lives at `%LOCALAPPDATA%\terminal-stack\tts-daemon\terminal-stack-tts.exe`. The installer creates a temporary build venv, freezes one EXE, validates it, atomically swaps it into place, and removes the legacy persistent venv/launcher only after validation. HKCU Run points directly at `"terminal-stack-tts.exe" daemon`, so clone relocation cannot strand autostart. The build embeds the clone Git SHA for `/healthz`; updates nudge rather than auto-restart because the daemon may be speaking or holding a duck.

## Why duplicate speech is collapsed by a history table

Three hooks described one `AskUserQuestion` — `Notification`, `PermissionRequest`, and the `AskUserQuestion` `PreToolUse` matcher (the middle one has since been pruned; see below) — and the obvious fix, "make the scheduler smarter", does not work. The scheduler already keys pending events on `(session_key, priority class)`, but all three are `P0_INTERACTIVE` and `collect_due` drains `P0` **immediately**: the first is spoken and gone ~2.5s before the second arrives, so the slot never holds two at once. There is nothing in memory left to compare against. Worse, when the daemon is down each hook spawns its own detached `_direct` worker, so the state has to be shared between *processes*, not threads.

Hence a durable record instead of a queue tweak. `state\history.db` stores one row per **decision** — `spoken`, `deduped`, `suppressed_dnd`, `synth_failed`, `failed` — and both paths check `recently_spoken(session, priority, debounceSec)` before speaking. The direct path checks it a second time *inside* the play lock, which is the check that actually collapses the burst: the first look raced with its siblings. Recording the rejections is the point; the dispatcher's in-memory `spoken`/`suppressed` counters die with the process, and the original investigation needed hand-parsing of `ttsd.log` to establish that anything had spoken twice at all. `tstack config tts history --dupes` is now that query.

`debounceSec` already existed in `config.py` with **no reader anywhere** — a config key nothing read is exactly why this looked fine on inspection — so it was wired up rather than replaced by a new key. A new chezmoi `[data]` key has a 7-step blast radius and a second store to diverge with; a runtime knob in `~/.claude/tts/config.json` (settable in the untracked `local.json`, `0` to disable dedupe entirely) has neither.

Two constraints shaped the mechanism:

- **The lock orders speech, it never drops it.** A waiter polls, then speaks anyway once `wait_sec` is up, and a lock older than `stale_sec` is reclaimed rather than trusted. Silencing a permission prompt is worse than hearing it twice, so dropping duplicates is `recently_spoken`'s job and the lock's only job is preventing overlap. The mutex is an atomic exclusive create, not a read-then-write test — two workers a millisecond apart would both pass a "is it locked?" read, which is the race being closed.
- **Fail open, everywhere.** A missing, locked, read-only or corrupt database returns "nothing known" and writes nothing; the first failure logs once and the module goes quiet so a bad disk cannot flood the log. Verified by pointing `LOCALAPPDATA` at a regular file: history, lock and log all unusable, and it still spoke. That drill found two pre-existing crashes on the way to speech — `_setup_logging` and `_spawn_direct` both ran `mkdir` outside any guard, and the second sat outside the `try` whose `False` return is what makes `submit_hook` fall back to speaking in-process.

The availability half is smaller but mattered more in practice: autostart is logon-only with no watchdog, so a daemon that died at 22:17 was still dead at 13:30 the next day, with no error and nothing in the log. Every hook in between took the unserialized direct path and exited 0, which is how genuinely overlapping voices went unnoticed for fifteen hours. A hook that cannot reach an enabled daemon now starts it and retries once. That is safe to race: two hooks both spawning means the loser fails to bind the port and exits 0 (`_already_running`), so the check only ever asks whether the port answers, never which process won it. `tstack doctor` reports how long the daemon has been silent and flags any session that spoke twice, because neither is visible otherwise — every hook exits 0 either way.

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
`tstack config` from pwsh has no token either; and `/v1/duck/release` with `/v1/shutdown`,
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

What it cannot fix is a user environment that is *itself* stale relative to the container — nothing local can recover from that, so `tstack doctor` reports it instead, comparing the two when Docker is reachable and staying quiet when it is not.

## Why the mute is a sentinel file, not the tray's DND

The tray already had `Do not disturb` and `Mute for 1 hour`, and neither silenced the things worth silencing. Both routed to `Dispatcher.set_dnd`, and the single enforcement point exempted `P0_INTERACTIVE` and `P1_ERROR` whenever `quietHours.allowInteractive` was true — the default. So DND muted "done" announcements and spoke every question, permission prompt and error: exactly backwards for someone who just answered a phone call. The flag's name gave no hint that it governed the DND toggle at all.

Two more problems made it unusable rather than merely wrong. It was **one float on the dispatcher**, so it died with the process — a tray Quit, a crash or a reboot silently un-muted. And the **direct path never consulted it**: `dnd_active` lived only on `Dispatcher`, which a detached worker never constructs, so with `daemon.enabled` false (the shipped default) the mute had no effect whatsoever and the only UI for it was not even running.

`state/muted` fixes all three by being a file. Existence is the check, so the hot paths never parse it and WezTerm can decide with a `glob`; the JSON body (`since`, `by`) is metadata for reporting. It is read at the two hook gates, in the dispatcher, and by the native-WSL playback path, which is what makes it hold with the daemon dead. It is **absolute** — no priority escape — because the exemption was the bug. Quiet hours keep their own `allowInteractive`, since a schedule and a panic button are different things.

Three details worth not undoing:

- **It fails open toward speech**, the opposite of `history.py`. If the state directory is unusable, "not muted" is the answer. A mute that cannot be lifted is indistinguishable from the feature being broken, whereas one that fails audibly is something you can hear and act on. An existence check gives that default for free.
- **Muting cuts off the sentence already playing.** Nothing could interrupt speech before: `Playback.play` built the WinRT `MediaPlayer` as a local and blocked until the audio finished. It now publishes the player so `stop()` can pause it and release the waiter, wrapped so a failed cross-thread COM call merely lets the sentence finish.
- **Three surfaces report it.** The tray icon greys out with a slash, WezTerm shows a `MUTED` chip, and `tstack doctor` names it — plus the `local.json` `enabled:false` mask that hid a mute for an afternoon while `cctts` cheerfully reported ON. An unreported mute *is* a bug report waiting to happen.

The tray and the global hotkey are conveniences on top of the file, not the mechanism, because both exist only while the daemon runs — and it has died silently more than once. `ccmute` writes the sentinel itself and works regardless; it also best-effort POSTs `/v1/mute` purely to get the barge-in, since only the process that owns the audio can stop it.

Why not `local.json` `{"enabled": false}`, which every path already honoured? It conflates "quiet for this call" with "feature off", `Config.write_local` is a non-atomic read-modify-write that a tray toggle and a shell command can clobber, and it is exactly the switch that masked a saved setting for hours. Why not a chezmoi `[data]` key: writing config stores from the wrong shell is what silently removed all five Claude TTS hooks on 2026-08-21. The sentinel touches neither store.

## Why `PermissionRequest` was dropped from the Claude TTS hooks

It never contributed text the others lacked. `build_payload` sets its `override` to `tool_name`, and `summarize.py` already renders that tool name into the permission template before appending the same string again — "Claude. alpha wants to run AskUserQuestion. AskUserQuestion". `Notification` announces the same prompts in Claude's own words ("Claude needs your permission to use Bash"), and the actual question text comes from the `AskUserQuestion` `PreToolUse` hook, the only place `_first_question` runs.

Dedupe made the redundancy worse rather than harmless: `recently_spoken` is **first-wins, not best-wins**, so which of the three sentences you heard depended on which hook Claude happened to fire first. Deleting the weakest one is a smaller change than teaching the dispatcher to rank candidates, and it removes a class of announcement nobody was choosing.

Accepted cost: the `permission` state becomes unreachable from Claude (Cursor still sends it), so permission prompts can no longer be muted separately from questions via the `events` list, and `announce.templates.permission` is now only exercised by Cursor and `tstack config tts test`. The absolute mute covers the "silence everything" case that granularity was standing in for.

## Why ducking snapshots pre-duck volumes to disk before touching anything

Windows persists per-app mixer volume indefinitely. A daemon that dies between ramp-down and restore leaves the music at 30% until the user finds the Volume Mixer — so the duck engine writes `state\duck-snapshot.json` *before* the first volume change, restores any stale snapshot at next startup, runs a 15 s watchdog while holding, and exposes `POST /v1/duck/release` plus a `--restore-volumes` oneshot that `tstack doctor --repair` invokes. Pause mode uses the Windows media-session API (`TryPauseAsync` only on sessions that were Playing, resume exactly those) and never simulates the media key, which is a blind toggle other apps can hijack.

## Why the `self` summarizer instruction uses agent-owned marker blocks

`summarizer self` needs the model to end each turn with a `<!-- speak: … -->` one-liner, which requires an instruction visible to every session. The repo deliberately does **not** manage Claude's `~/.claude/CLAUDE.md` or Codex's active global `$CODEX_HOME/AGENTS.md` whole-file (they are user-owned agent instructions) and does not force an output style outside this opt-in feature. Instead `tstack config tts summarizer self` edits a `<!-- terminal-stack-tts-start/end -->` marker block into both files, with `.bak.YYYYMMDD` backups, and switching to any other mode removes exactly those blocks. Codex sessions load instructions at startup, so already-running sessions may not emit the marker; the final-response hook text is locally shortened in that case.

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

The wizard/`tstack config` choices (leader chord, theme mode, tmux prefix, app selection, and the `tstack mux` domain toggle) need to survive every `tstack update` and be readable by *all* the apply paths. The stack already had exactly the right bridge: chezmoi `[data]` in `~/.config/chezmoi/chezmoi.toml` — the same place `windowsUsername` is stored and consumed by the WSL `run_after` hook to render Windows-side files. So the choices live there too. `.chezmoi.toml.tmpl` re-emits them (so a bare `chezmoi init` doesn't drop them) and *derives* the concrete bindings — `leaderChord "ctrl-space"` → `leaderKey "phys:Space"` + `leaderMods "CTRL"`, `tmuxPrefix "ctrl-b"` → `tmuxPrefixResolved "C-b"` — in one Go-template mapping. WSL/native chezmoi templates read them directly (`{{ .leaderKey }}`); the WSL hook reads them via `chezmoi execute-template` and substitutes `__LEADER_*__`/`__THEME_*__`/`__TMUX_PREFIX__`/`__WEZ_MUX__` tokens into the Windows `.tmpl` files (same mechanism as `__WIN_USER__`).

The wrinkle: a **Windows-standalone** install (no WSL) never runs chezmoi, so it can't read chezmoi `[data]`. That path gets a JSON mirror at `%LOCALAPPDATA%\terminal-stack\config.json` (next to the existing `rollback-sha`), written by `windows-bootstrap.ps1` / the pwsh `tstack config` and read by `scripts/sync-windows.ps1`. To keep the two stores from drifting in a **combined** Windows+WSL setup, the WSL side is authoritative: `ts_save_config` (bash) also writes the Windows `config.json` mirror when `/mnt/c/Users/<user>` exists, and the docs tell you to run `tstack config` from WSL. Defaults are baked into every consumer (`hasKey` guards in the templates, `cfg <key> <default>` in the hook, fallbacks in `sync-windows.ps1`), so a clone that predates the wizard renders today's behaviour (Ctrl+Space, Mocha, mux off) until you run it.

A single dedicated config file (one TOML/JSON on every platform) was the alternative. Rejected: it would duplicate the cross-side plumbing that chezmoi `[data]` + the sync hook already provide for `windowsUsername`, and chezmoi templates can't cleanly read an arbitrary external file on every apply. Reusing the existing bridge keeps the mapping in one Go template and the I/O in `bootstrap/_config.{sh,ps1}`.

**The failure mode that asymmetry buys, and what it looks like.** The bridge is one-way: a
bash save writes chezmoi `[data]` *and* mirrors to `config.json`, but a **pwsh save writes only
the mirror**. On a combined machine that is a silent divergence — the two stores disagree about a
key and nothing says so, because each apply path reads only its own store and renders a perfectly
valid file from it. Whichever path runs last wins, so the setting appears to work until the *other*
side applies and takes it away.

Observed 2026-08-21: `ccTtsEnabled` was `false` in chezmoi `[data]` and `true` in the mirror. Every
`tstack update` from pwsh rendered the five Claude TTS hooks; the next `chezmoi apply` from WSL rendered
none and removed them. Nothing failed, nothing warned, the diff looked intentional, and the only
symptom was that voice notifications quietly stopped. It had presumably been flip-flopping for some
time.

Two things follow. `tstack config` from WSL is not a style preference — it is the only path that writes
both stores, which is why CLAUDE.md states it as a rule. And when a setting mysteriously reverts
after an apply, compare the stores before debugging the templates:

```sh
chezmoi execute-template '{{ .ccTtsEnabled }}'                     # WSL, authoritative
python -c "import json;print(json.load(open('/mnt/c/Users/<you>/AppData/Local/terminal-stack/config.json'))['ccTts']['enabled'])"
```

They must agree. Repair by re-saving from WSL (`tstack config tts on`), which writes both. Nothing
currently *detects* the divergence — `tstack doctor` would be the natural home for a check that walks
the shared keys and reports any that disagree.

## Why WezTerm follows the OS theme live, but Starship/tmux bake at apply time

`follow` mode means "track the OS light/dark setting." WezTerm can do this *live*: `wezterm.gui.get_appearance()` returns `Dark`/`Light`, and WezTerm re-evaluates the config when the OS appearance changes — so `.wezterm.lua` carries both palettes (Catppuccin Mocha dark + VS Code Light Modern light) and a `pick_palette(mode)` that flips the whole UI (scheme, tab bar, status line, Claude tints) with no re-apply. Only the *mode* (`themeMode`) is injected.

Starship and tmux can't: their configs are static files with no runtime OS-theme hook (Starship picks one `palette` at load; tmux reads a fixed status style). Querying the OS theme on every shell start was rejected — it adds startup latency to every prompt and OS detection from inside WSL is unreliable. So for those two the palette is **baked**: a `resolvedTheme` (`light`|`dark`) is computed once at apply time (`resolve_os_theme` reads the Windows registry / `defaults` / `gsettings`; `follow` resolves to the current OS theme, fixed modes resolve to themselves) and written into the store. `tstack update` and `tstack config` re-run that resolution (`ts_refresh_resolved_theme` / `Update-TsResolvedTheme`) and re-apply, so a `follow` user who toggles the OS theme picks up the new shell palette on the next update — while WezTerm has already switched live. The asymmetry is intrinsic to what each tool exposes, not a shortcut. (One palette wrinkle: WezTerm and Starship use VS Code Light Modern for `light`, while `dot_tmux.conf.tmpl` deliberately keeps Catppuccin-Latte-derived hexes for its light status colours.)

## Why a re-run repoints `sourceDir` (and why `tstack doctor` exists)

The original bootstraps refused to touch an existing `~/.config/chezmoi/chezmoi.toml` ("already exists; not overwriting sourceDir"). That looked conservative but caused a silent, confusing failure: install once to `~/terminal-stack`, later re-run the installer (which now clones to `~/code/terminal-stack`), and chezmoi keeps applying from the *old* clone. A clone that predates a feature (e.g. `doc`) therefore never delivers it, and `chezmoi apply` prints no changes because the old source already matches the target — the user sees "I updated, why is `doc` not found?".

The fix is to treat `sourceDir` as something the installer **owns and corrects**, not something it tiptoes around: `ts_ensure_source_dir` rewrites only the `sourceDir` line (preserving the `[data]` block — leader/theme/apps/`windowsUsername`) when it differs. This lives in `_config.sh` and is shared by all three POSIX bootstraps, so the three near-identical toml-writing blocks collapsed to one. `tstack doctor` is the standing version of the same check for an existing install: it verifies `sourceDir` resolves to a real terminal-stack clone (and the *intended* one), that `~/.zshrc`/`$PROFILE` actually carry the stack, and that tools are present — then `--repair` repoints and re-applies. Windows has no `chezmoi.toml`, so its analogue persists `$env:TERMINAL_STACK_DIR` to `profile.local.ps1` instead.

## Why re-clone fresh (not adopt-in-place) when an old clone is found

When the installer finds an old clone at a different path, it clones fresh to the chosen location and *offers to delete* the old one, rather than adopting the old clone where it sits. Adopt-in-place is less disruptive but inherits whatever state the old clone carried — a detached HEAD, a half-finished rebase, a wrong branch, local edits — and silently makes that the source of truth. A fresh clone is guaranteed to be the release branch at a known-good commit, which is what an *installer* (as opposed to `tstack update`) should guarantee. That sentence was false for nine days — `git clone` took no `--branch`, so it landed whatever GitHub's default branch was — and the section below is what made it true again. Deletion is never automatic: the cleanup checklist shows each old clone's last commit, pre-ticks it, and removes nothing without an explicit confirmation; the keep-list (`~/.zshrc.local`/`profile.local.ps1`, `~/.doc.local`, rollback state, `*.local.md`) is never offered.

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

## Why the workspace root moves across volumes when `wso migrate` refuses to

The entry above says `wso` refuses a cross-volume move, and it should keep refusing. This
one is the exception, and the difference is what is being moved.

`wso migrate` relocates individual repos *within* a tree, one at a time, dozens of times,
non-interactively. Crossing a volume there turns a rename into a copy-then-delete for
each of them, and a partly copied repo whose original is already unlinked is the worst
outcome available — from an operation the user was not thinking hard about because it
usually moves nothing.

Moving the ROOT is the opposite case in every respect. It happens once, deliberately,
because a workspace has outgrown its disk, and crossing a volume is the entire point:
"move my workspace to the big drive" is not a request that can be satisfied by a rename.
Refusing would mean the command cannot do the only thing anyone would run it for.

So the safety is bought a different way rather than by refusing:

1. **Preflight refuses for a reason it can name** — destination exists and is not empty,
   parent missing, not writable, less than 110% of the tree's size free, the calling
   shell standing inside the source, the tree being moved into itself, or the
   terminal-stack runtime clone sitting inside it. "Refused" with no reason just moves
   the problem to whatever the user guesses next.
2. **The copy preserves hardlinks** (`rsync -aHAX`). Git object stores and worktrees
   hardlink; losing that silently inflates the copy and breaks `git worktree`. `cp -a` is
   the fallback when rsync is absent, and it says so, because it cannot.
3. **Verification is a separate pass**, not a return code. A second rsync in dry-run mode
   reports anything it would still transfer, which is exactly "what is not identical
   yet". Directory-attribute-only rows are excluded: destination directory mtimes settle
   after their contents are written, so they always differ and never mean anything.
4. **Nothing is unlinked until after that passes**, and then only behind a confirm.

The ordering is the argument. An interruption at any point before step 4 leaves the
original complete, so the failure mode `wso migrate` refuses to risk cannot occur here —
not because copying got safer, but because the delete moved to the far side of a
verification. A failed verification exits non-zero, leaves both trees, and does **not**
repoint the root: pointing the workspace at a copy that did not verify would be a worse
outcome than doing nothing, and it is the one the naive "copy, then save" ordering
produces.

`--keep-source` declines the removal outright, and `TS_WS_YES=1` skips the prompt for
scripts. The prompt defaults to no, and to no when stdin is not a terminal.

## Why the local workspace root is a second root, not a fourth candidate

The workspace root resolves to one directory: `$WORKSPACE_DIR`, else the first existing
autodetect probe. Adding `~/LocalWorkspace` to that probe list would have been the
one-line change, and it would have been wrong in both directions — on a machine with a
real workspace it never fires, and on a machine without one it silently redefines *the*
workspace as the local disk.

The two roots are not alternatives. They answer different questions:

- The main root is where project work lives, and it is expected to be large. Putting it
  on a mounted data volume is normal and is what `--move` exists to do.
- The local root is where repos live that **cannot** be on that volume. A dotfiles repo
  stowed into `$HOME` is the case that forces it: if the mount is ever missing —
  `nofail` in fstab makes that silent — the mountpoint still exists, the tree under it is
  empty, and every stowed link dangles. Nothing says so until the next login, when the
  bar, the window manager's config and `~/.ssh/config` are all simply gone.

`doc common/workspace-nav` had already written that warning down for `ws --move`. The
local root is the durable answer to it rather than a warning about it.

So: `$LOCAL_WORKSPACE_DIR`, else `~/LocalWorkspace` when it exists, resolved at call time
like everything else here, and **returning nothing on a machine that has neither**. Most
machines have one root, and every consumer had to keep working unchanged on those.

Three consequences worth stating, because each is a place this could have gone wrong.

**The jumps search roots in order, main first.** `wsj` and `ws37`/`ws42`/`wsmb`/`wsmd`
take the first hit, so a single-root machine behaves exactly as before and a two-root
machine only ever gains destinations. `wsar` is left alone: `archive/` is a tier `wso`
builds, and `wso` does not build one there.

**`wsj`'s rows had to become self-describing.** The picker showed root-RELATIVE paths,
which is what keeps them readable, and a relative row is ambiguous the moment there are
two roots — `src/github.com/o/x` could be either. Rows from the main root stay relative;
rows from any other root are absolute with `$HOME` collapsed to `~`. The row's first
character now says which root it came from and the selection maps back to exactly one
directory, with no rule about which root wins a collision — because there are no
collisions.

**`wso` must never see it.** This is the one that could do damage. `wso migrate` derives
a destination from a repo's `origin` and moves it into the organised main tree,
non-interactively, dozens at a time. Doing that to a stowed dotfiles repo puts it back on
the volume it was moved off, re-creating the exact silent breakage the local root exists
to prevent — from a command the user was not thinking hard about, because it usually
moves nothing. `ts_ws_scan_roots` / `Get-TsWsScanRoots` therefore drop that root and
everything under it, and drop it **even when `TS_WS_EXTRA_ROOTS` names it**: that
variable means "legacy root, empty this into the tree", which is the precise opposite.
The guard stands down when the workspace *is* the local root, or it would leave `wso`
with no roots at all and a plan that silently contains nothing.

## Why `--org` matches the owner segment rather than the path

`--org` existed on `status`, `sync` and `unarchive` as `case "$d" in *"/$org"/*)`, and
that substring test was wrong in three ways that all returned a wrong answer silently
rather than erroring:

- `--org github.com` matched every repo in the tree. The host is a path segment too.
- A *repo* named like an owner matched, so `--org martybytes` also selected
  `someone/martybytes`.
- `--org martsamp77` matched nothing after a migration. The tree carries the canonical
  owner and the flag carried what the user typed, and nothing said so.

One helper (`ts_ws_org_match` / `Test-TsWsOrgMatch`) now matches the owner segment of
`<tier>/<host>/<owner>/<repo>` with the rename map applied to both sides, and the three
existing call sites were retrofitted onto it rather than left as a fourth spelling.

Two verbs are deliberately different. `plan` and `migrate` filter the **destination**,
because a misfiled repo's whole point is that its current folder does not say who owns
it — filtering on the source path would hide exactly the repos the plan exists to find.
Rows with no destination (blocked, unparseable origin) survive every filter: they need a
human, and hiding them behind a flag is how they get forgotten. And `orphans` has no
owner to match at all — a repo with no remote is a repo nothing derives an owner for —
so its empty result names the filter instead of reading as "you have none".

Adding the filter to `plan` forced a smaller fix worth recording. `cmd_plan`'s first
positional was its *mode* string, so the dispatcher had to call it with no arguments,
which meant `wso plan --org x` silently discarded the flag and printed an unfiltered
plan. Mode became `--mode`, and the dispatcher now forwards `"$@"` to every verb, with
`identity` and `doctor` rejecting anything they are given. A flag that is ignored without
comment is worse than one that errors.

## Runtime clone location: Windows app-data, POSIX XDG, invisible dev clones

The runtime clone — the one `tstack update` pulls and chezmoi applies from — lives at a
**canonical location** per platform:

- Windows: `%LOCALAPPDATA%\terminal-stack\stack`.
- Every POSIX target, **WSL included**: `${XDG_DATA_HOME:-~/.local/share}/terminal-stack`.

**WSL used to share the Windows clone** through `/mnt/c`, and that was wrong. drvfs is
not a small tax, it is a different order of magnitude -- measured on one machine, two
real clones of this repo:

| operation | `/mnt/c` (drvfs) | `~` (ext4) |
|---|---|---|
| `git status`, avg of 3 | **1634 ms** | **3 ms** |
| `find -type f` over the tree | 306 ms | 47 ms |

~540x on the operation every git command, prompt and hook performs. The cost was already
on the record from the other side: the comment at `bootstrap/_config.sh` notes 229 seconds
for 49 chezmoi spawns *"because the source dir lives on /mnt/c"*. And the old default was
actively harmful on a machine that had done the right thing by hand -- the installer
offered to *relocate* an existing Linux-side clone onto the mount.

So a WSL install is now self-contained on the Linux filesystem, and the Windows install
owns the Windows side. `state_dir()` already sent WSL to XDG; this is the same split,
applied to the clone.

**The two original arguments survive intact.** App-data is outside every workspace root,
so `wso migrate` can never relocate the runtime clone out from under the install -- and
`~/.local/share` is not a workspace root either, so XDG satisfies that equally.
`tests/test_tstack_core.py` already pinned `~/.local/share/terminal-stack` as *not* a dev
clone (the leading dot in `.local` breaks the `/local/` bound), so the new default was
proven safe against that regex before it became the default.

**The old location stays a legacy candidate** in all three POSIX lists, or every machine
installed before the move stops resolving its own clone. `install-wsl.sh` scans it first
and offers the move, which is how an existing install migrates.

One sharp edge the move creates, and it is worth knowing: on the docker **wsl-shim** path
(Docker Desktop with this distro's WSL integration OFF) the engine is a Windows process
that cannot bind-mount an ext4 path. `require_windows_visible` was effectively unreachable
while the canonical clone lived on `/mnt/c`; it is reachable now. `tstack doctor` reports
it as `wsl-docker-shim`, a note, and the fix is to turn that integration on -- which is
also what gives WSL a native Linux docker.

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
you commit to it, making `tstack update` mutate the tree you are developing in.

**Dev clones are invisible unless pinned.** A clone at a wso tier path
(`<tier>/<host-with-dot>/<owner>/<repo>` — `ts_is_dev_clone` / `Test-TsDevClone`) is
skipped by every resolver, doctor probe, doc root, and cleanup menu. Setting
`TERMINAL_STACK_DIR` at it still works — pins are deliberate. This is what lets the
same repo be simultaneously the runtime install (canonical path) and a working
checkout (`wsmb` → `src/github.com/martybytes/terminal-stack`) without `tstack update`
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
every session and a stale line would otherwise brick `tstack update` / `wso` / `doc`
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

**Migration is tstack doctor's job.** `tstack doctor --repair` (pwsh `-Repair`) offers to move
a legacy-path clone to the canonical location: a plain directory move (same-volume
rename; cross-volume copy + HEAD-verify), then repoints chezmoi `sourceDir` (POSIX) or
clears the stale pin (Windows), offers to normalize a renamed-account origin URL, and
re-applies. `tstack update` only prints a one-line notice — an update must never move
directories as a side effect. Installers default to the canonical paths and offer the
same move when they find an existing legacy clone (pulling it first so the move
routine is present inside it).

When the canonical location is *already occupied*, `Move-TsClone` refuses (it will not
overwrite a destination) and the cleanup menu cannot help — `Find-TsClones` never offers
the canonical path, by design. That combination used to be a dead end, so `-Repair`
resolves it directly: if the occupant is a real stack clone it becomes the one in use and
the cleanup menu offers the other; if it is merely a directory in the way, it says so and
names the fix.

## One branch, because two of them broke the installer

`curl … /main/install-mac.sh | bash` died on a machine that had been running the
stack for months:

```
Your configuration specifies to merge with the ref 'refs/heads/feat/local-bin-bootstrap'
from the remote, but no such ref was fetched.
```

The runtime clone was sitting on a feature branch that had been merged and
deleted upstream. That is the visible half. The invisible half is why it was on
one at all, and why nothing had noticed.

**The installer and the installed tree came from different branches.** Every
documented one-liner — `README.md`, `INSTALL.md`, `install.ps1`'s own printed
hints — fetches `install-*.sh` from `main`. That script then ran `git clone
"$REPO_URL" "$TARGET_DIR"` with no `--branch`, which takes the repo's **default**
branch. On 08/28/2026 the default became `develop`. From that day, the script you
ran came from the release branch and the tree it installed came from the
integration branch, and no test, doc or check anywhere named a branch, so nothing
could see it. `ts_relocate_clone` preserves the current branch across a move, so
machines installed before that date stayed on `main` and machines installed after
landed on `develop`, with nothing reconciling the two.

**`tstack update` read the broken state as a healthy one.** It decided whether
anything was incoming from the output of `git log --oneline 'HEAD..@{u}'` with
stderr discarded. Empty output means "nothing to pull" — and it is also what that
command produces when it **fails**, which it does in all three of: no tracking
branch, a detached HEAD, and a tracking branch whose remote ref is gone. So a
clone on a deleted branch printed `==> already up to date`, exited 0, applied the
stale tree, and did that forever. The `git pull --ff-only` that would have
surfaced the error only runs inside the `if incoming` arm, so it was never
reached. Worse than the installer's loud crash, because nothing ever said so.

Three changes, and one deletion of a distinction:

1.  **`RELEASE_BRANCH` is a constant, carried six times.** `tstack/paths.py` holds
    it; the four installers and the two shells repeat the literal because they
    cannot import Python, and the installers run before any clone exists.
    `tests/test_release_branch.py` reads all seven and fails on drift — the same
    shape as `tests/test_apps_catalog.py`, and for the same reason.
2.  **The installers pin it and realign an existing clone.** `git clone --branch`,
    plus `ts_align_branch` / `Set-TsCloneBranch` before the pull that the
    misalignment breaks. A clone with no upstream is returned to the release
    branch without asking, because that state is broken rather than chosen; a
    clone on a *live* other branch is asked about, defaulting to switching, and
    left alone when nobody is there to answer, because that one may be a
    deliberate test of unreleased work. Neither ever touches a dirty tree —
    switching branches under uncommitted work either fails or carries it across,
    and both are things to do to someone's work only with their say-so.
3.  **Both update twins ask for the upstream by name** (`rev-parse --abbrev-ref
    --symbolic-full-name '@{u}'`) instead of inferring it from an empty diff, and
    fetch with `--prune` — without which a deleted branch still looks alive
    through its stale remote-tracking ref, which is the version of this bug that
    survives a `git fetch`. No upstream now stops the update and names the
    repair; it never applies. `tstack doctor`'s `check_clone_branch` is the
    standing version, and `--repair` performs the switch.

The distinction deleted is `develop` itself. Having the default branch and the
release branch be different branches bought nothing here — this is a
single-maintainer repo where every phase branch is already gated by protection
and full CI on the way in — and it cost an install, silently, for nine days.
`main` is now the default, the integration branch and the release branch, and
`AGENTS.md` § Branches is the authority. The pin in the installers stays anyway:
it is what stops a future settings change on GitHub from deciding what an install
gets.

**Dev clones are exempt from all of it.** A checkout at a workspace tier path is
where branches are supposed to be, and `check_clone_branch` returns early there —
same reasoning as `check_clone_location`'s dev-clone arm. A check that nags where
the behaviour is correct trains the reader to ignore it.

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
behind your back: the wizard asks at install, `tstack update` reports and offers when something
newer exists on the channel you are already on, and `tstack config wezterm` changes it on demand.
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
  text is `tstack config wezterm changes`, paged through the same reader `doc` uses. For a
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
gate in `.chezmoiignore` only stops re-rendering, and `tstack config ghostty off` does the
removal explicitly, for the machine you actually run it on.

**Nothing on the POSIX side backs up before an overwrite.** The `.bak.YYYYMMDD[.N]`
convention fires in the Windows sync hook and the merge helpers, but a plain `chezmoi apply`
replaces a `$HOME` file with no backup at all — so the first managed apply would have
destroyed a hand-written `~/.config/ghostty/config` silently, with nothing in the diff to
show it. `run_before_20-backup-ghostty.sh` takes the backup, skipping any file that already
carries our marker so a managed config does not spawn a new `.bak` on every apply. That
backup is also what makes `off` a restore rather than a delete.

**macOS only**, for the same reason `tstack smb` is POSIX only: there is no Ghostty on the
other targets that this stack configures. `tstack/commands.conf` says `-` in the Windows
column so the shim reports "not supported on this platform" rather than a missing command,
and `-h` says it too, so the absence reads as a decision rather than drift. This was briefly
untrue — see § "Why the Windows Ghostty target was dropped".

## Why the Ghostty config opts into the ssh integration

Symptom: ssh into any Linux host from Ghostty and backspace inserts junk or walks the
cursor forward instead of erasing, and Delete does nothing at all. Nothing else is wrong;
local panes are fine.

The chain is short and entirely outside this repo. Ghostty announces `TERM=xterm-ghostty`.
`ssh` forwards `TERM` to the remote. The remote's terminfo database has no `xterm-ghostty`
entry, so ncurses cannot resolve `kbs=\177` or `kdch1=\E[3~`, and readline falls back to
something that gets both keys wrong.

**`tstack config ghostty off` is not a diagnostic for this**, which is what made it
confusing: stock Ghostty with no config from us defaults to the same `TERM`, so turning the
managed config off changes nothing and looks like an acquittal. WezTerm never had the
problem for an unrelated reason — neither `.wezterm.lua` sets `config.term`, so it reports
`xterm-256color`, a name every host already knows.

The fix is `shell-integration-features = …,ssh-env,ssh-terminfo`. Two things about that
line are easy to get wrong:

- **Naming any value replaces Ghostty's default set.** The features are not additive to a
  default; `no-cursor,sudo,title` was already an explicit set, and neither ssh feature is
  in Ghostty's defaults anyway. They have to be spelled out or they are simply off.
- **Both, not one.** `ssh-terminfo` uploads the real entry per host and keeps Ghostty's full
  capability set there, but it needs `tic` on the remote and a writable home. `ssh-env` is
  the fallback that sets `TERM=xterm-256color` where that cannot happen. Terminfo alone
  leaves minimal containers and jump hosts broken; env alone gives up Ghostty's own
  capabilities on every remote.

The blunt alternative, `term = xterm-256color`, was rejected: it fixes ssh by lying about
`TERM` in **local** panes too, giving up Ghostty's terminfo everywhere to fix it somewhere.
A test pins both features present and pins the absence of a global `term` line.

`ghostty +ssh-cache` lists and clears the per-host cache — useful when a host is reinstalled
and the cached "already done" is stale. The manual equivalent, for a host reached some other
way, is `infocmp -x xterm-ghostty | ssh <host> -- tic -x -`.

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

At the command level the same line is `tstack services` versus `tstack agents`. **`tstack services` is the only thing
in this repo that starts, stops or builds a container; `tstack agents` may only probe one.** That is not
a style preference — `test_no_project_scope_or_docker_mutation_in_lifecycle_adapters` asserts the
strings `docker compose`, `docker rm` and `restart: unless-stopped` appear nowhere in
`tstack/commands/agents.py`, as case-insensitive matches over the whole file, **so even a comment
naming the compose command fails it**. When a probe fails, `tstack agents` prints the *verb*
(`tstack services up playwright`), never the command. Having an in-repo verb to point at is what makes that
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
`ts-agentmemory.ps1 -Check` and only `-Apply` when something is missing, so `tstack update` and
`chezmoi apply` restore it. `tstack doctor` reports the same condition for when you want to know
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
review rather than following `latest` service images. `tstack update` checks only tools
enabled on the current machine and repairs their user-global client wiring. JSON
files shared with the agents are edited by named entry, with a backup, so unrelated
MCP servers and hooks survive.

## Why `tstack smb` pins the macOS FUSE library instead of letting rclone choose

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

So `tstack smb` never invokes `rclone mount` on darwin without setting
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
rclone browses and copies perfectly but can never mount; `tstack smb doctor` reports
it and names the official binary. And FUSE-T's FSKit backend, which looks like
the modern choice on macOS 26, fails outright there (`fuse: mount failed with
error: -1`) where the default NFS backend does not, so `-o backend=fskit` is
**not** passed automatically.

## Why `tstack smb` tracks mounts in a state dir rather than through `rclone rc`

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
`tstack smb umount --all` safe.

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
path of `tstack smb mount`. A mount tool has to work when the network is flaky, which
is precisely when someone is using it. Any sync design therefore has to be
local-first with explicit push/pull anyway — at which point the sync is a separate
concern that can be added later without changing anything here.

So `~/.config/terminal-stack/shares.local.conf` is untracked, machine-local, and
the only source of truth. `bootstrap/shares.conf` is tracked but holds **defaults
only and never a host**, so the repository never learns where anyone's NAS is.
No chezmoi `[data]` key is involved either: the inventory is a list of records,
which that store is explicitly not built for, and every field here is per-machine.

## Why `tstack smb` ships without a PowerShell twin

Every other dual-shell command in this stack keeps a parallel pwsh implementation
whose `-h` output stays byte-identical. `tstack smb` does not, as of 2026-08-23, and
that is a decision rather than drift — recorded here, stated in the `-h` prose,
and noted in `CLAUDE.md` so nobody "fixes" the asymmetry without reading this.

Most of what `tstack smb` exists to do is moot on Windows: Explorer and `net use`
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
`install.ps1`, `windows-bootstrap.ps1` and `tstack config apps` — while every test
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
every `tstack update`, accepted, and watched the install fail — permanently, because
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

`Get-TsAppsPending` decides what `tstack update` offers. It gated on
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
first `tstack update` after this change has more to say than the last one did.

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

## Why the Windows Ghostty target was dropped

It existed for four days and is worth one paragraph so nobody rebuilds it by
accident. [noctty](https://github.com/amanthanvi/noctty) — Ghostty's terminal
core in a native Win32 app, renamed from **WingHostty** in main on 2026-08-20 but
still shipping release assets under the old name — was a real Ghostty for
Windows, and the stack mirrored a config to `%LOCALAPPDATA%\ghostty\` for it.
The owner of this stack does not use it, so the whole target is gone rather than
left to rot: the mirror file and its generated theme, the `__GHOSTTY_THEME__` /
`__GHOSTTY_WINDOW_THEME__` substitution in **both** sync scripts, the
subtree-skip that implemented `ghosttyConfig=off` on that side, the interop
binary probe, the pwsh terminal-picker row and the `Set-TerminalStackConfig`
branch.

Three things that removal bought, none of which is only about Ghostty:

- **The themeMode → theme mapping is gone entirely**, not merely deduplicated. It
  existed once per renderer because Ghostty's config format has no conditionals
  and Windows mirror files get token substitution rather than Go templates; a
  test had to pin the copies against each other, because a drift between them
  showed up as `tstack config ghostty diff` reporting a phantom change forever.
- **`target()` returning None is a refusal now, not a branch.** WSL used to
  resolve to the Windows install, which was correct then and is a silent bug
  now — writing to a `/mnt/c` path that nothing on the machine reads, and
  reporting success. A parametrised test pins the refusal on Linux, WSL and
  Windows alike, and asserts the message mentions neither `/mnt/c` nor
  `LOCALAPPDATA`.
- **There is one syntax gate again.** macOS has a real one (`ghostty
  +validate-config` exits 1 on error). The Windows build had none: on 1.3.123
  `+validate-config` failed with `FileTooBig` even for a 14-byte config, and
  `+show-config` reported *nothing* for an unknown key or a bad value on a real
  key. That trap outlives the removal — never treat `+show-config` as a
  validator, on any build; every "accepted" it returns is meaningless.

**Removal is not deletion on the machines that had it.** The code that *wrote*
`%LOCALAPPDATA%\ghostty\` is gone; the files an earlier apply already put there
stay, unmanaged. Deleting them from a sync would run that deletion on every
machine — the same reason `off` was never a `.chezmoiremove` rule. Anyone who
wants them gone removes that directory by hand, once.

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
worth stating: a dirty working tree builds a dirty image. `git status` before `tstack services up` is the
whole discipline, and `tstack services --dry-run up` shows exactly what would be built.

Dropping `update-console.*` also dropped two behaviours that had to be inherited rather than lost:
the double `--env-file` billing deploy in the correct order, and the post-rebuild `/healthz` verify.
Both live in `tstack services` now. A lone `--env-file .billing.env` *replaces* `.env` as compose's
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

`tstack services up` refuses to start while a legacy volume exists and its replacement does not, because
compose would otherwise create an empty one and start the stack with no memories in it, reporting
success. `tstack services migrate-volumes` copies in a container, verifies the file count came across, and
leaves the old volume as the rollback. The same trap caught `tstack services bootstrap`, which happily
created the empty replacement until it learned the same rule.

## Why the agentmemory secret cache kept a fallback when it moved

The cache moved from `$XDG_CONFIG_HOME/docker-local/agentmemory.secret` to
`$XDG_CONFIG_HOME/terminal-stack/agentmemory.secret`, which sounds like a rename and is not. The
*reader* is JavaScript already injected into vendor hook files on live machines, and those files are
only rewritten when `tstack agentmemory --apply` runs. Moving the writer alone turns 401-recovery into a
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
`tstack services status` as a second row under someone else's name. Splitting it makes
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
`tstack config agents agentmemory on` refuses when the backend is something else and
names `tstack config memory agentmemory`, rather than silently reconciling —
quietly undoing what someone asked for is worse than telling them the two
disagree. `tstack doctor` reports drift for the case where something wrote the key
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

`tstack config memory` restarts headroom rather than printing the command. The
setting and the running state disagreeing is exactly the failure mode above, and
a restart of a compression proxy costs an in-flight request, not a pane full of
work (contrast `tstack mux restart`, which is deliberate for that reason).

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

## Why Codex questions use `PreToolUse`, not transcript watching

Codex writes `request_user_input` calls to rollout JSONL, but question pauses do
not emit `Stop`. Completion-only TTS therefore cannot see them. A dashboard
tailer could detect records, but would couple correctness to enhanced-pane
lifetime, rollout discovery, offsets, restart recovery, and custom dedupe.

Official Codex hook coverage includes local function tools under `PreToolUse`.
The existing AgentMemory `PreToolUse` hook also generated context for a live
`request_user_input` call, proving this Codex version uses that path. The profile
therefore registers an exact `^request_user_input$` matcher and runs it
asynchronously. The bridge emits existing `question/question` protocol, so first
question extraction, session naming, priority, mute, filtering, history, and
fallback behavior remain one TTS implementation. `PermissionRequest` stays out:
approval speech is separate product behavior and previously produced weak,
duplicated tool-name announcements.

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


## Why `tstack services` stopped handing WSL work to PowerShell

Inside WSL with Docker Desktop's integration switched off, `docker` on PATH is
Desktop's stub: it exits 1 for every command and prints its complaint on STDOUT,
so `command -v docker` is true and useless. `bootstrap/ts-stack.sh` handled that
by re-exec'ing `bootstrap/ts-stack.ps1` through interop for `up`, `down`,
`restart`, `logs` and `config`, on the reasoning that compose resolves `-f`, build
contexts and bind mounts as *Windows* paths and a `\\wsl.localhost` 9p share is
not reliably bind-mountable - a failure that would land after the stack was
already down.

The reasoning about paths was right. The handoff was a consequence of the logic
existing twice, and it had two costs that were never written down:

- **It gave up entirely with no pwsh 7**, printing "no Linux Docker CLI in this
  WSL distro, and no pwsh 7 to hand off to" and exiting 1. Nothing was wrong with
  the engine; the wrong process was being asked to talk to it.
- **It covered five verbs of twelve.** `bootstrap`, `test`, `backup`, `reset`,
  `migrate-volumes`, `doctor` and `status` never handed off, so on exactly the
  machine that needed the handoff they ran against the stub and failed.

There is one implementation now, so there is nothing to hand off *to*. The Python
port runs `docker.exe` through interop from the same process
(`tstack/engine.py:binary_for`), which reaches the identical engine, works with no
pwsh installed, and covers every verb.

The path constraint is still real and is now stated rather than side-stepped:
`require_windows_visible` refuses a stack tree that a Windows engine cannot
bind-mount, **before** anything is torn down, and names the fix. A clone under
`/mnt/<drive>` is fine, which the canonical
`%LOCALAPPDATA%\terminal-stack\stack` always is; a clone inside the WSL
filesystem is not.

That check is pure string work on a POSIX path and must stay that way.
`Path.resolve()` on Windows - where this suite also runs - turns `/mnt/c/x` into a
drive-relative path and inverts the answer.

## Why kokoro was never reported as off (and how a twin hid it)

`bootstrap/ts-stack.sh` gated the kokoro stack with:

```sh
on="$(ts_cc_tts_get enabled 2>/dev/null || echo true)"
engine="$(ts_cc_tts_get engine 2>/dev/null || echo kokoro)"
```

The keys are `ccTtsEnabled` and `ccTtsEngine`. `ts_cc_tts_get enabled` therefore
looked up a `[data]` key that does not exist, got nothing, fell through to
`ts_cc_tts_default`, whose `*)` branch is the bare word `1` - a command, not a
value, so the function exited 127. The `|| echo true` guard then turned that
failure into "TTS is on", and the second line turned it into "engine is kokoro".

**kokoro was reported as enabled on every macOS and Linux machine, whatever the
settings said**, including machines with voice notifications off entirely. The
pwsh twin read the real values through `Get-CcTtsConfig` and behaved correctly, so
the two disagreed on every such machine and nothing compared them: the parity test
for this subsystem checked that both files *contained the string* `ccTts`, which
both did.

That is the shape of the failure this whole port exists to remove - not a missing
test, but a test that could only ever check the two files looked alike. There is
one implementation now (`tstack/stacks.py:stack_state`) and the test drives it
with real values instead.

## Why the compose choke point is a class, not a helper

Every docker argv is built in `tstack/stacks.py`'s `Compose.argv`, and
`tests/test_stack.py` asserts that no other file under `tstack/` builds one. Three
invariants ride on that being literally true:

- `down` never receives `-v`. Volumes are destroyed only by explicitly gated
  paths, and the two that do are `test --destroy-data` and `reset --destroy-data`.
- `--env-file .env` always precedes `--env-file .billing.env`. A lone
  `--env-file .billing.env` *replaces* `.env` as compose's interpolation source,
  so every `${OPENAI_*}`-derived `LLM_*` display value resolves to empty: a blank
  provider panel in the console, no error, everything healthy.
- `--dry-run` prints the exact argv and runs nothing, naming the real binary
  (`docker.exe` on the interop path) rather than a plausible-looking `docker`.

A second builder would be a second set of rules that nothing checks, which is how
the ordering bug happened the first time.

## Why a fresh clone ships no chat provider at all

`services/stacks/agentmemory/.env.example` had `OPENAI_BASE_URL` and
`OPENAI_MODEL` **active**, pointing at a Tailscale host on one person's network,
and `tstack services bootstrap` copies that file verbatim. Every clone but the
author's booted into the state below.

There are three states, and they are not symmetric:

| state | `ts-verify` | what actually happens |
|---|---|---|
| unset | `skip -` | compression, summary, graph and consolidation are skipped; storage, search and embeddings are unaffected |
| set and reachable | pass | all four run |
| set and unreachable | `000`, fail | every call returns empty, fails XML parsing, retries, and dead-letters — while the log line still reads `outcome:"success"` |

52,570 jobs accumulated in the third state before anyone noticed, because nothing
about it looks like a failure from the outside. Shipping an address that resolves
on nobody else's network put every fresh install straight into it, so the example
now ships with everything commented and names three provider shapes anyone can
copy instead.

**`OPENAI_API_KEY` in `services/.env.example` matters more than it looks**, and
is commented out for a reason that is easy to miss: with a key set and no base
URL, the client falls back to its own default endpoint (`api.openai.com`) and
sends the placeholder there. `ts-verify` would still report `skip`, because it
reads the container's `OPENAI_BASE_URL` and that is empty — so the machine looks
cleanly unconfigured while quietly 401ing against a service nobody chose.

The compose **default** for `LLM_PROVIDER_LABEL` stays `OpenAI`, deliberately.
An unlabelled provider is then assessed as paid, and over-reporting cost is the
safe direction to be wrong in. It is the wrong answer for a machine with no
provider at all, which is what the two explicit `none` lines in the example
correct.

## Why `tstack agents llm` reads the env file rather than the container

It has to be right while the stack is **down** — that is when someone is most
likely to be asking why nothing is being summarised. The stack's own `.env` is
compose's authoritative interpolation source (`agent007memory/ts-envfiles` says
the same thing from the console's side), so reading it needs no engine and keeps
one copy of the truth.

Two things it will not do:

- **It never reports a host probe as container reachability.** A container's DNS
  is Docker's embedded resolver, not the host's, and its egress is a separate
  path — so an endpoint your shell reaches may be unreachable from the server.
  The success line says so and names `tstack services test agentmemory`, which
  dials from inside.
- **An endpoint with an empty `OPENAI_MODEL` is called out, not ticked.**
  `inferenceActive` in the console's `shared/llmEndpoint.ts` is driven by the
  *model*, not the URL, so that configuration reads as done everywhere while
  every family stays off.

## Why the container gets `host.docker.internal` mapped explicitly

A chat model running on the host — Ollama, LM Studio, llama.cpp — is the most
likely provider anyone here will have, and from inside a container `localhost` is
the container. So `tstack agents llm` offers `http://host.docker.internal:11434/v1`
rather than the URL you would copy out of a browser.

That name is free on Docker Desktop and **does not exist on native Linux** unless
it is mapped, which is how the same `OPENAI_BASE_URL` that worked on a Mac
silently `000`d on a server. `extra_hosts: host.docker.internal:host-gateway` on
the agentmemory service makes one printed URL correct on all three platforms; it
is accepted and redundant on Desktop (verified against Docker Desktop on macOS,
which resolves the name and returns a connection error rather than a DNS one).

## Why `llmfit` is in `models`, not `ai`

`ts_app_is_ai` reads the `ai` group as the install **route**, not as a category:
every member is handed to `ts_install_ai_cli`, which has a branch per agent CLI
and a `*)` that prints "no agent-CLI installer defined". A packaged binary put in
that group would therefore be silently skipped on macOS and Linux and reported as
an error on the way past.

`llmfit` comes from brew on macOS and from a release tarball on Debian/WSL, so it
needs the ordinary package-manager path. A one-member `models` group is cheaper
than teaching `ts_app_is_ai` an exception list, and it is where someone looks for
"which model fits this machine" anyway.

It is **absent from the Windows catalog**. It ships a windows-msvc binary but is
in no winget manifest (checked: neither `manifests/a/AlexsJones/llmfit` nor
`manifests/l/llmfit` exists), and that table takes verified ids only — the rule is
"can this platform install it", never "is it in winget".

## Why the kokoro model id had to become a setting

mlx-audio runs the same Kokoro model natively on Apple Silicon and speaks the
same OpenAI protocol: `/v1/audio/speech` with `model`, `voice`, `speed` and
`response_format`, plus `/v1/audio/voices` and `/v1/models`. Every field this
stack sends matched **except one** — the docker image answers to the literal
string `kokoro`, and mlx-audio wants the HuggingFace repo id and rejects anything
else.

So a hard-coded `model` was the single thing standing between this stack and a
native Apple Silicon engine, and `ccTtsKokoroModel` is the whole port. Nothing
else changed: voice lists, samples, speed, the pool and the fallback ladder all
work unaltered.

Two details that are not obvious:

- **The pwsh side defaults it at the call site**, not from the config.
  `Get-CcTtsConfig` fills missing *top-level* keys only, so a config stored before
  this key existed has no nested `model` member at all and would send an empty
  string.
- **`?model=` is sent to `/v1/audio/voices` only when a model is configured.**
  mlx-audio 400s without it (it resolves the voice packs out of that HuggingFace
  snapshot); the docker image has no such parameter. Sending it unconditionally
  would change the one request that is known to work.

## Why the macOS engine advice is derived, not written down

There are three ways to get a voice on a Mac and which one is right depends on
the machine, so `tstack config tts engines` measures it — architecture, cores,
memory, installed system voices, and whether Docker, kokoro and mlx-audio are
actually present — and branches on `uname -m`.

The deciding fact it exists to state: **Docker Desktop gives the container no GPU
on Apple Silicon**, so the shipped kokoro image runs on the CPU a model the
machine could run on its GPU. That does not make the container wrong — one voice
across a Mac, a Linux box and a Windows machine is a real reason to keep it — but
it is not the fast option, and mlx-audio is the same model without the penalty.

Two claims were wrong in the first draft and are pinned against by a test: MLX
runs on the **GPU through Metal**, not the Neural Engine, and Docker on Apple
Silicon runs the model on the CPU rather than emulating an x86 GPU.

## Why `tstack ui` does not write the store

A dashboard is exactly the kind of thing that grows its own writer — it already
has the key, the value and the file path — and a second writer is how this repo
lost five TTS hooks in a day. So every save routes through
`tstack.commands.config.set_value`, the same function the command line uses.

That also gets the schema's validation and the `DERIVED` refusal for free: a key
regenerated by `chezmoi init` cannot be edited from the dashboard any more than
from a shell, and the message is the same one either way. It needed no part of
the phase-4 flip — that module is already built, just not yet wired to the
`config` name.

Three structural choices behind it:

- **Textual is optional and isolated in `tstack/ui/`.** Everything else in
  `tstack` runs on the standard library, which is what lets a fresh machine run
  `tstack doctor` before anything is installed. `tstack ui` catches the
  `ImportError` and prints how to install Textual.
- **`ui/app.py` is excluded from coverage MEASUREMENT, not from testing.**
  `tests/test_ui_app.py` drives it headless through Textual's own `run_test()`.
  Measuring it would make the floor depend on whether the machine running the
  suite happens to have Textual installed — present, the number goes up; absent,
  every line reads as uncovered and the gate fails for a reason unrelated to the
  change. A floor that moves with the environment is not a floor.
- **The Textual tests live in their own module.** `pytest.importorskip` skips the
  module it is *in*; at the top of `tests/test_ui.py` it silently took the
  fourteen stdlib-only model tests with it, and the suite still reported green.

Two UI details worth keeping: the `source` column is a fixed width because
auto-sizing pushed it off the right edge at 110 columns, and `source` is the
entire reason the screen exists. And `e` is the advertised edit key rather than
Enter — a focused `DataTable` claims `enter` for its own select action, so the
App-level binding never fires there and never appears in the footer. Enter still
works, through `on_data_table_row_selected`.

## Why the install profile is not a saved setting

The wizard opened with the WezTerm leader key, then the mux, then session
restore, then voice notifications, then a memory backend — fourteen questions
aimed at someone who may only have wanted the prompt. The honest answer to "can I
just have the prompt" has to be yes, so that is now question one, and it opens by
rendering the prompt you would get.

The answer (`prompt` / `shell` / `full`) is **not stored**. It decides what the
rest of the wizard asks and what those answers default to, and every one of those
*is* saved on its own — so a stored `profile` would be a second copy of state that
can disagree with the settings it produced. Re-running the wizard asks again,
which is correct: the answer is about what you want now, not about what this
machine is.

On `prompt`, every remaining answer is pinned to its off/default value rather
than asked, and the review screen lists them. A review that silently omits what
it decided for you is how "I didn't choose that" happens.

## Why the app class is inferred rather than saved

The second question — "will you write code on this machine?" — picks between two
recommended sets. The split is "does this only make sense if you write code
here", not taste: git tooling stays in **both**, because delta, gh and lazygit
earn their place on a server you deploy from, while ghq, the runtimes, the Python
tooling, the agent CLIs and llmfit are development-only. The monitors and network
tools that are merely optional on a laptop become default kit on a server, so
neither set is a subset of the other — they are two different defaults.

`ts_apps_pending` had to learn about this or the class would have become a
permanent nag. It offers the saved selection **plus anything since added to the
recommended set**, which is the point — a machine configured before a tool joined
the catalog would otherwise never get it. With two classes, a box set up as a
server would be told on every `tstack update` that it is missing fnm, poetry and
six agent CLIs it deliberately declined: the same nag `ts_app_installable` was
added to end, in a new place.

So the class is derived from a predicate that cannot drift — *does the saved
selection contain anything outside the sysadmin set?* — rather than from a stored
copy that can. A server that later installs `claude` flips to developer, which is
the right answer. A machine that has never been configured reports `developer`,
keeping the previous behaviour rather than guessing.

## Why the Starship presets are not vendored

`starshipPreset` is a saved setting: `terminal-stack` (the default) is this
repo's own two-line prompt, and any other value is one of Starship's twelve
built-in presets. `tstack config prompt list` renders **every** option live,
because a preset name tells you nothing and this is a decision about what you
look at all day.

Copying twelve TOML files into this repo would freeze them at whatever upstream
shipped the day they were taken, and the whole point of a preset is that it is
Starship's rather than ours. `dot_config/starship.toml.tmpl` therefore runs
`starship preset <name>` at apply time.

**`lookPath` is the load-bearing half.** During a bootstrap that template can be
rendered *before* starship is installed, and chezmoi's `output` on a missing
binary aborts the entire apply — not just that file. Falling back to this stack's
own prompt keeps a half-installed machine with a working prompt, and the next
apply picks up the preset.

Three traps found while building it:

- **`starship preset -o <file>` refuses to overwrite an existing file**, and
  `mktemp` has already created one. The command fails, the temp file stays empty,
  and the preview silently renders nothing. Redirect stdout instead.
- **`STARSHIP_SHELL` must be empty, not unset.** With a shell name starship emits
  that shell's escaping (zsh's `%{…%}`), which a preview prints as literal
  punctuation rather than as colour.
- **An unknown preset name renders an empty config**, so it is checked against
  `starship preset --list` before it is saved — a working prompt replaced by no
  prompt, with nothing in the diff to explain it, is worse than a refusal.

Both sync paths render it on the Windows side too. A combined machine showing
tokyo-night in WSL and this stack's prompt in PowerShell is exactly the
split-brain the config mirror exists to prevent.

## Why `Save-TsConfig` needed two more parameters

It rebuilds `config.json` from a fixed set of properties, so a key missing from
that set is **deleted** on any Windows-side save — the same failure its own
`ccTts` comment warns about, one level up. `atuinEnabled` had this hole from the
day it was added and has no pwsh consumer, so nothing ever showed;
`starshipPreset` decides which prompt `sync-windows.ps1` deploys, so losing it
would visibly revert the prompt on the next Windows save.

Both are now parameters, carried forward when the caller does not pass them.
`StarshipPreset` deliberately has **no `ValidateSet`**: `starship preset --list`
is the authority and it grows, so a hardcoded set here would reject a preset the
installed starship has.

## What the bash agentmemory twin may not copy from the `.ps1`

`bootstrap/_agentmemory.sh` keeps the `.ps1`'s `@T`/`@N` encoding on purpose, so
the two files' edit text diffs directly. Exactly **two** things differ, and both
are mandatory:

- **Stale-secret recovery reads the 0600 cache**
  (`${XDG_CONFIG_HOME:-~/.config}/docker-local/agentmemory.secret`) rather than
  `reg query HKCU\Environment`, which on Unix throws, is caught, and leaves the
  recovery a permanent no-op.
- **Hook commands are a POSIX `VAR=value node "<path>"` prefix**, not a cmd.exe
  `set X=…&&` chain. That chain written into a hooks file on a Mac fails
  **silently**.

Three implementation constraints that are not obvious from the code:

- **The literal multi-line replace runs in python3, not bash.** `${x//a/b}`
  treats the needle as a glob, and `sed` is line-oriented and appends a trailing
  newline to a file that lacked one.
- **The FILE's line endings decide what gets inserted, not the matched form's.**
  A single-line anchor is byte-identical in LF and CRLF, so deciding from the
  match injects LF blocks into a CRLF file.
- **Python must read with `newline=""`**, or universal-newline translation
  silently rewrites every CRLF vendor file to LF.

And unlike the `.ps1`, which reports problems and still exits 0, the bash twin
**exits non-zero in every mode**, so `tstack agents` can tell a clean apply from
one where an edit's anchor had moved.

## Why every agent gets prompt-level retrieval

`/agentmemory/context` from `prompt-submit.mjs`, gated by
`AGENTMEMORY_INJECT_CONTEXT`, was Codex/Cursor-only on the theory that Claude
already retrieved through `/enrich` at `PreToolUse` and `/session/start`.

`/enrich` fires only for the vendor allow-list, is excluded for `Bash`, and drops
a path-less `Grep`/`Glob` — so a shell-heavy Claude session retrieved almost
nothing. Measured: **1041 captures against one `/context` call in 5.7 hours.**
Claude's patch set therefore includes `prompt-submit.mjs`, and adding a script to
an agent's list is the whole change.

`AGENTMEMORY_INJECT_CONTEXT` is **inlined into every generated hook command**
rather than inherited. A User environment variable only reaches processes started
after it was set, so inheriting it left long-running shells and desktop apps
retrieving nothing.

## Why `doc`'s edit binding cannot hard-code fzf's `become(...)`

`become` — replace the fzf process with `$EDITOR` — only exists in fzf 0.42.0+.
Debian/Ubuntu `apt`, which is what `_common-debian.sh` installs, ships older fzf
(0.29 on Ubuntu 22.04), where it is an unrecognized action and **fzf refuses to
start at all**: `unknown action: become(...)`. That takes out the whole finder,
not just the edit key.

`_doc_finder` in `dot_zshrc` resolves the bind through `_doc_edit_bind`, which
checks the installed version with zsh's `is-at-least` and falls back to
`execute(${EDITOR:-micro} {2})+abort` below 0.42.0 — the same fallback the pwsh
side (`Invoke-DocFinder`) has always used unconditionally.

## Why `~/.claude/settings.json` and `~/.cursor/hooks.json` are never copied

`~/.claude/settings.json` holds Claude Code's own state — `model`,
`enabledPlugins`, `permissions`, `env` — next to this stack's `statusLine`,
`hooks` and `theme`. A whole-file mirror deletes all of it with **no error and
nothing in the diff**. That is how the agentmemory plugin got silently disabled:
`enabledPlugins` vanished mid-session, so its hooks and MCP server stopped
loading. The same sync emptied `~/.cursor/hooks.json` of agentmemory's seven
Cursor hooks.

Both now route through a merge helper on both sync paths
(`bootstrap/_merge_claude_settings.ps1`, `bootstrap/_merge_cursor_hooks.ps1`).
If you add another such file, splice it rather than copying it — and work out
whether ownership is per **key** or, as with Cursor's shared event arrays, per
**entry**.

## Why every wizard question carries a recommendation, and what each one costs

A default with no reasoning is a default people override at random. Each
behaviour question therefore opens with a `RECOMMENDATION:` line that says which
way to go **and what it costs**:

- **mux off** — config changes then need `tstack mux restart`, which kills every
  pane, and mux panes cannot render the per-pane Claude tint.
- **session restore off** — panes come back without their processes, and the
  autosave runs either way, so `Leader+L` still restores on demand.
- **atuin on** — its *wizard* default is `on`, while the stored `[data]` default
  stays `off` so a machine that never answered is not flipped silently.

**The agent toggles are probed, not guessed.** `ts_probe_headroom` and
`ts_probe_agentmemory` run before the question, print what they found, and set
the default. This matters because the agentmemory hooks `fetch(...).catch(() => {})`
then `exit(0)`: a machine wired to a service that is not running captures nothing
and reports nothing.

**"Answering" is the test, never a 2xx.** AgentMemory returns 404 on `/` and 401
on `/agentmemory/health`, so `curl -fsS` — which `tstack agents agentmemory
status` used — reported the service *down* while it was up and serving.
`ts_probe_http` accepts any HTTP status and counts only a refused connection as
down; `ts_probe_http_ok` is the strict variant, for genuine readiness endpoints
like Headroom's `/readyz`. When a probe fails, `ts_docker_ports` reports what
docker *is* publishing, so the warning names the real port rather than repeating
the expected one.

## Why the app catalog became a data file

There were two catalogs -- `bootstrap/_config.sh` and `bootstrap/_config.ps1` --
carrying the same ids, group membership, descriptions and two default sets each.
They had already drifted in a way that mattered: the pwsh side kept a **second id
list** to express "Windows cannot install this", doing by omission what
`Test-TsAppInstallable` was supposed to do by rule. That is the exact drift
CLAUDE.md warns about, in the file it warns about it in.

A third reader forced the issue. The settings dashboard, the wizard port and
`tstack config apps` all need the catalog, and only one of those is bash.

`bootstrap/apps.conf` is whitespace-delimited for the same reason
`workspace.conf` and `commands.conf` are: bash cannot parse JSON without `jq`,
and this stays diffable. Two columns replace four lists:

- **`classes`** -- `both | dev | sys | none`. The recommended and sysadmin sets
  are DERIVED from it, so they cannot drift apart. Neither is a subset of the
  other: a server's default kit includes the monitors that are merely optional on
  a laptop, and drops the runtimes and agents entirely.
- **`platforms`** -- `all | posix | linux | windows`. "Can this platform install
  it", never "is it in winget", and it is what replaced the second id list.

Verified by construction rather than by eye: every derived set was dumped from
bash and pwsh before the change and reproduced exactly after, and
`tests/test_apps_catalog.py` now runs all three readers and compares them.

Two fixes fell out. macOS no longer offers `nvtop` in the picker at all, rather
than offering it and then refusing to install it. And the catalog is ASCII,
because Python prints these descriptions now and a Windows console on codepage
437 renders an em dash as mojibake.

## Why the wizard's answers travel in a file

The questionnaire is one Python implementation, and the four bootstraps that call
it are shell. The answers reach them by writing a file the caller sources, never
by printing to stdout.

That removes a whole class of failure by construction. The bash wizard routed
every prompt to `/dev/tty` precisely because it was called inside `$( )`, and a
single `printf` that forgot the redirect would have been captured as part of an
answer. With a file there is no capture boundary to corrupt: menus go to the
terminal, answers go to the path the caller passed, and the two cannot mix.

Three details are load-bearing under `set -euo pipefail`:

- **Every variable is emitted unconditionally**, empty where there is no value.
  The callers read several of them unguarded, and `set -u` aborts on a missing
  one.
- **`export`, not assignment.** `ts_agents_apply_wizard` reads `TS_WIZ_HEADROOM`
  and friends from the ENVIRONMENT of a child `tstack agents` process; a bare
  assignment would silently turn the agent wiring off.
- **Written whole, then renamed.** A crashed wizard cannot leave half a file for
  the caller to source -- and it is never reached anyway, because the exit code
  is non-zero and the call is the condition of an `if`.

Windows gets the same answers as JSON, keyed by the PascalCase names the old
PowerShell hashtable already used, so every `$w.X` call site downstream is
unchanged.

**Exit 3 means the user quit at the review**, which each caller already handled
as cancelled and which has to stay distinguishable from a failure.

## Why `tstack config` flipped only its POSIX column

`tstack/commands.conf` has two implementation columns per row, and `config` is
the row that uses them differently on purpose.

POSIX runs the ported Python. Windows stays on `Set-TerminalStackConfig` until it
can be exercised on a Windows machine: `tstack config` is the most-used command
in the stack, the delegation there would have to reach a function that lives
inside `$PROFILE`, and flipping it blind is how you find out on someone else's
morning.

Three verbs are **delegated**, not unported. `apps` ends in a package-manager
install, `tts` is twenty-five sub-verbs over the daemon, and `reconfigure` is the
bootstrap's own save sequence -- and `REVAMP-PLAN.md` lists the installer entry
points as never ported. They are unportable by the plan's own rule, so Python
routes them to `bootstrap/ts-config.sh`, which survives as the delegate target
rather than as the entry point. "Delete ts-config.sh" was never achievable and
the checklist that said so was wrong.

`mux`, `wezterm`, `ghostty` and `wizard` are handed to their ported commands
**in-process**: they are in the same program, and spawning a second interpreter
to reach one would double the startup cost for nothing.

Two divergences from the shell are recorded in the characterization harness
rather than papered over: an unknown verb and a missing argument are exit 2 now,
on every platform, where `ts-config.sh` returned 1. A caller that keys off the
exit code should see one answer for one kind of mistake.

## How each kind of tool actually gets installed

The catalog says *what*; these are the *hows*, and each exists because the
obvious route failed.

**Agent CLIs never come from a package manager.** `ts_install_ai_cli` /
`Install-TsAiCli` handle them instead of brew/apt/winget: claude, grok and
cursor-agent ship native installers that need no Node, while codex (npm, Node
16+) and gemini (npm, Node 20+) are gated on the Node version and *say what to
do* rather than failing. There is **no brew fallback for gemini** -- that formula
is deprecated upstream, so installing from it would hand you a dead end.

**grok's installer appends a PATH line to `~/.zshrc`**, which this stack owns
whole-file, so the next apply would wipe it. `GROK_BIN_DIR="$HOME/.local/bin"`
routes the symlink onto the already-managed PATH instead, and `dot_zshrc` carries
its completions `fpath` itself.

**Node is fnm, not nvm** -- roughly 10ms of shell startup against 200-500ms --
wired into both shells with `--use-on-cd`. Because fnm's PATH entry is created
per-shell, `ts_apps_pending` and `ts_report_installed_apps` call
`ts_load_node_env` first, or they nag about npm-installed CLIs forever.

**The Python group is the same shape as the agent one.** `pipx`, `poetry`,
`glances`, `ipython`, `httpie` and `pre-commit` have no winget package (three
were carried as ids that do not resolve), so Windows routes them through
`Install-TsPyTool` -- `uv tool install`, else `py -m pip install --user` -- after
the winget pass and before the agent CLIs, in **both** `Install-TsApps` and
`windows-bootstrap.ps1`'s own loop.

**Binary names can differ from the id** (`btop` becomes `btop4win` on Windows),
and a new winget id is verified with `winget show --id <id> --exact` before it is
written down. An id that always fails is worse than an honest "not available on
this platform".

## Why leader keys with no printable spelling are stored by name

`tstack config leader ctrl-\` looked like it should work and could not, for two
independent reasons that both stayed silent until the next chezmoi command. The
store (`store.set` and `ts_data_set`) writes `key = "<value>"` with no escaping,
so a backslash or a double quote leaves `~/.config/chezmoi/chezmoi.toml`
unparseable and every later `chezmoi` invocation dead. And had the value got
through, all three renderers (the WSL hook's Python substitution, `sync-windows.ps1`
and `dot_wezterm.lua.tmpl`) would have written `key = '\'` into Lua, where the
backslash escapes the closing quote.

The fix chosen is the pattern the stack already had for the one other such key:
`space` is spelled by name and `.chezmoi.toml.tmpl` / `ConvertTo-TsLeader` map it
to WezTerm's `phys:Space`. `backslash` joins it as `phys:Backslash`. That keeps
every renderer a plain token substitution (no Lua escaping in three places to keep
aligned), and the schema validator turns the two forbidden characters into a
refusal that names the spelling. The alternative, escaping at render time, was
rejected because it fixes the Lua and not the TOML, and the TOML failure is the
one that bricks the machine.

Two consequences. The mapping table now lives in two places (Go template and
pwsh) and `test_named_leader_keys_map_identically_in_both_chord_mappers` fails if
a name is added to one and not the other. And `phys:` names a physical position
on the US ANSI layout, so on another layout `ctrl-backslash` is whichever key sits
where `\` does on a US board; `space` has always had the same property.

## Why the WSL sync walk reads its file list from fd 3

`run_after_90-sync-windows.sh` walks `windows/` with `while read -d '' ... done < <(find ...)`.
Two entries in that tree are part-owned and go through `pwsh.exe` (the
`.claude/settings.json` and `.cursor/hooks.json` merges). pwsh drains whatever
stdin it inherits, and with the file list on stdin the first merge consumed the
rest of it. In `find` order that was everything after `.claude/settings.json.tmpl`:
`.config/**`, `.cursor/**`, `.wezterm/pane_nav.lua`, `.wezterm.lua.tmpl`,
`AppData/**` and `Documents/PowerShell/**`. None of it was visited, nothing was
printed, and the summary line counted the visited files as unchanged.

It was found on 2026-09-02 when `tstack config leader ctrl-backslash` saved,
`chezmoi init` derived `phys:Backslash`, the hook's own `cfg leaderKey` returned
`phys:Backslash`, and the rendered `~/.wezterm.lua` on the Windows side still said
`phys:Space`. `bash -x` showed the walk ending eleven files in. How long it had
been that way is not knowable from the logs, because the failure mode is an
absence: every pwsh-side `sync-windows.ps1` run kept the Windows files current
enough that nobody noticed the WSL apply had stopped touching them.

The fix is `read -u 3` with `3< <(find ...)`, so the body can run anything it
likes on stdin. `< /dev/null` on the pwsh call alone was rejected: it fixes the
one consumer we know about and leaves the trap armed for the next one.

The same investigation exposed a second gap. The Python `tstack config` saved to
chezmoi `[data]` and stopped; the shell save it replaced had always ended in
`ts_mirror_windows_config`. Since `scripts/sync-windows.ps1` renders from that
mirror, a setting changed from WSL was rendered back to its old value by the next
pwsh-side sync. `_apply` now calls the bash writer after `chezmoi init` on WSL,
keeping one implementation of the mirror.
## Why a gate has to RUN the installer, and what a parse gate cannot see

A refactor that ported the wizard, the apps catalog, ghostty, mux and config to
Python was done on macOS and merged. The first Windows install after it died on
its third line:

```
windows-bootstrap.ps1: Cannot bind argument to parameter 'Path' because it is null.
```

`Join-Path $SourceDir 'tstack\main.py'`, with nothing assigning `$SourceDir`.
Four separate things had to be true for that to reach `main`, and each is worth
keeping in mind separately.

**1. The bug was a duplicate, not a typo.** `_config.ps1` already had
`Invoke-TsWizard`, and its own comment says *"ONE copy, because there are two
callers -- the bootstrap and `tstack config wizard` in $PROFILE -- and the last
time each had its own, $PROFILE was still calling a `Read-TsWizard` that no
longer existed."* The bootstrap had re-inlined a third copy anyway. The comment
was right about the failure mode and the code drifted back into it regardless.

**2. The guard test named two callers and checked one.**
`test_the_windows_wizard_runner_has_exactly_one_implementation` existed, for
exactly this, and asserted only against `$PROFILE`. A test whose docstring
describes an invariant it does not check is worse than no test: it is a claim
that the thing is covered. (See also § "The claims audit".)

**3. A parse gate would not have helped.** Every `.ps1` in the repo parses
cleanly -- verified. PowerShell has no `bash -n` equivalent for undefined names,
and CI had **no PowerShell job at all**: `bash -n` ran over every shell script on
Linux, macOS, WSL and three distro containers, while `.ps1` was checked nowhere,
with the Windows runner's syntax step explicitly `if: runner.os != 'Windows'`.

What finds it is a scope-aware AST walk, and the one detail that decides whether
it works: for a dot-sourced dependency it must count **script-level assignments
only**. Counting that file's *function parameters* is precisely what made
`$SourceDir` look defined -- `Invoke-TsWizard` has a parameter by that name. The
first version of the scan did exactly that and reported nothing. Within the file
under test, scriptblock `param()` blocks DO count, or `$mk = { param($ms) ... }`
is a false positive.

**4. Nothing in the repo ran an installer.** `tests/parity/run.sh` and the CI
`parity` job both stop at `bash -n` plus pytest. That is a structural blind spot,
not an oversight about one bug: `bash -n` cannot see an unset variable, and a
static name resolver cannot see an empty catalog. The bash twin of the Windows
bug was sitting in the tree at the same time -- `_wizard.sh` ran the questionnaire
without pinning `TERMINAL_STACK_DIR`, and it runs *before* chezmoi is configured,
so a clone at any path off the built-in candidate list produced an empty
`apps.catalog()` and an install that finished successfully with no CLI tools.

Hence `tests/parity/run.sh bootstrap`. Three things about it are load-bearing:

- **A non-root user with passwordless sudo.** `common_require_non_root` refuses
  uid 0, and the bootstrap shells out to `sudo` for apt and `chsh`.
- **The clone goes at a path deliberately off the candidate list**
  (`~/somewhere/odd/stack`). Every default location hides the resolution bugs.
- **It asserts on the wizard's ANSWER, never on its console output.** The
  questionnaire writes its menus to the terminal, so a "the app catalog is empty"
  warning never reaches stdout. The first version grepped the log for that string
  and therefore could not fail -- it passed with the bug deliberately reinstated.
  It checks `TS_WIZ_APPS` instead, which is the thing the caller actually
  consumes.

It earned its place on the first run, with a bug none of the static gates could
express: all three bootstraps printed `Detected: user $USER` under `set -u`, and
`$USER` is set by **login** shells and nothing else. `docker run ... bash -c`,
`su - -c`, cron and systemd units all aborted on line one. `_config.sh` derives
it from `id -un` now.

It is opt-in -- it installs packages and wants the network -- so a bare
`tests/parity/run.sh` does not include it. Name it to run it.

One more thing the containers caught, which is the older argument for them
restated: the fix for `ts_app_desc`'s whitespace handling used an awk interval
expression, `{4}`. Debian ships gawk and passed. **Ubuntu's default awk is mawk,
which has no interval expressions**, so the substitution silently matched nothing
and returned the whole row. Explicit repetition instead. Testing on "Linux"
means testing on the distro's own tools, not on one distro that happens to have
the permissive ones.

## Why the conflict question is asked by us, not by chezmoi

chezmoi already asks. That is the problem:

```
.zshrc has changed since chezmoi last wrote it?
> diff/overwrite/all-overwrite/skip/quit
```

There is no indication of which edit is at stake, no statement that `overwrite`
is permanent, and no hint that the recurrence has a fix. `all-overwrite` is
nearly always correct here — these files are stack-owned and rewritten every
update, so an edit made directly to `~/.zshrc` was never going to survive — and
a user with only that line to go on cannot know it.

**Resolve first, then apply**, rather than `chezmoi apply --interactive` with
better wording around it. `--interactive` prompts for *every* change, not just
the contentious ones, and its wording is not ours to change. Instead
`bootstrap/ts-apply.sh` reads `chezmoi status`, settles each conflict with
`chezmoi apply --force -- <file>`, and only then runs the general apply — by
which point chezmoi has nothing to ask. A residual-conflict guard refuses to run
that final apply if anything is somehow left, because in an installer a
re-prompt is the dead end described below.

**Back up before overwriting.** A POSIX `chezmoi apply` writes no backup at all;
the `.bak.YYYYMMDD[.N]` convention only ever fired in the Windows sync hook, the
merge helpers, and `run_before_20-backup-ghostty.sh` — which exists precisely
because of this gap. Taking one turns "overwrite" from a lossy answer into a
recoverable one, which is what makes recommending "all" honest. The convention
is now one helper, `ts_backup_file` in `_config.sh`, instead of the two
open-coded copies it had grown.

**`/dev/tty`, not stdin.** Every installer runs the apply with `</dev/null` on
purpose — the `curl | bash` stdin-consumption defence, where a child reading the
script pipe truncates the script still being read. That makes stdin a useless
test for "can I ask a question", and it is the reason chezmoi failed here at all:

```
chezmoi: .zshrc: could not open a new TTY: open /dev/tty: no such device or address
```

A re-install over any hand-edited file hit that under `set -e` and aborted. The
repo already had the right primitive — `ts_is_interactive`, which probes
`/dev/tty` — and using it means the question still gets asked in a real terminal
even though stdin is closed.

**Exit 4 for "a decision is waiting".** Distinct from 0 and from a real failure,
so a caller can tell the two apart: `tstack update` reports that the pull
succeeded and the apply is pending, and the installers say everything else is
installed and exit 0. A conflict is not a broken install, and a half-applied home
directory is worse than an unapplied one — so nothing is written in that case.

**The conflict predicate is column 1 alone.** `chezmoi status` prints two
columns; the earlier zsh implementation required both to be non-space. Verified
against chezmoi 2.72, the prompt fires on **column 1** — the destination
differing from what chezmoi last wrote — whether or not the source changed:

| case | status | chezmoi |
|---|---|---|
| user edited, source unchanged | `MM` | asks |
| source changed, user did not touch it | ` M` | applies silently |
| both changed | `MM` | asks |

Both filters agree on these, so the old one was not producing wrong answers —
it was describing the wrong rule, which is the kind of thing that stops being
harmless the moment a fourth case shows up.

**One implementation, four callers.** This lived in `dot_zshrc`, in zsh, so only
`tstack update` had it. The three installers — where a conflict is *most* likely,
because a re-install runs over whatever the previous one left behind — got the
bare `chezmoi apply` instead. That asymmetry is the same shape as the
`Invoke-TsWizard` duplication that killed the Windows install, and it is worth
noticing that both were "the good version exists, and the path that needed it
most could not reach it".

## Why Omarchy is a package-manager seam, not a fifth platform kind

`install-linux.sh` on any Arch host died with `sudo: apt-get: command not
found`. Not at the end, not after a warning: `common_install_all`'s **first**
call is `common_pkg_prereqs` (then `common_apt_prereqs`), `linux-bootstrap.sh`
runs under `set -euo pipefail`, and that was the whole install — before the
questionnaire, before chezmoi, before a byte was written. A `grep -rln "Arch
Linux|pacman|Omarchy"` across every `.md`, `.sh`, `.py` and `.conf` in the repo
returned **nothing**. The platform was not unsupported; it was unimagined.

The obvious fix — make `plat.kind()` return `arch` — is the wrong one. Every
switch on `kind()` in this repo (`engine.py`, the sync hook, `paths.py`,
`state_dir`) is asking "is this a POSIX box with no Windows side", and an Arch
box answers `linux` to that exactly as Debian does. A fifth value would have
made every one of those callers learn a distinction none of them cares about,
and the ones that were not updated would have silently taken the `else` branch.

What actually differs is two things, and they are a second axis: **which package
manager**, and **who owns which config**. So `plat.distro()` / `is_arch()` /
`is_omarchy()` sit beside `kind()` rather than inside it, with shell twins
(`ts_distro_id`, `ts_is_arch`, `ts_is_omarchy`) reading the same
`/etc/os-release`. Omarchy 4.0.1 answers `ID=omarchy`, `ID_LIKE=arch`.

Arch-ness and Omarchy-ness are asked **separately**, and that is load-bearing:
`ts_is_arch` gates the package manager, `ts_is_omarchy` gates the opinions
(bash-first, mise owns runtimes, Omarchy owns tmux and Ghostty). Widening the
second to "arch" would run `omarchy pkg add` on a box with no omarchy, which is
a command-not-found, not a policy. `tests/parity/run.sh arch` exists precisely
to keep the plain-Arch path honest, because nobody developing this on an Omarchy
laptop will ever exercise it by accident.

One trap, found by the test that compares the two readers: the `TS_DISTRO_ID`
override has to distinguish **unset** from **set-but-empty**. `[ -n "$VAR" ]`
treats them alike, so bash fell through to the live `/etc/os-release` and
answered `omarchy` where Python — whose `os.environ.get` returns `""` — answered
`""`. `${VAR+set}` is the test that matches. Two readers of one rule disagreeing
is the same failure the `platforms` column was introduced to end, arriving one
axis over.

## Why the installer contract was split into `_common-posix.sh`

`_common-arch.sh` was going to be written by copying `_common-debian.sh`. That
would have copied `common_install_all`, and `common_install_all` is not a list
of steps — it is an **ordering**, and the ordering encodes two separate
incidents. Persistence runs before any optional install, because an install that
died under `set -e` once threw away ten answers the user had just typed. chezmoi
runs before persistence, because `ts_save_config` shells out to `chezmoi init`.
A second copy of that is a second place for either to be undone by someone
fixing the other.

So the shared half moved to `_common-posix.sh` — the orchestration plus
`common_require_non_root`, `common_oh_my_zsh`, `common_nerd_font_jetbrains`,
`common_tty_prompt`, `common_workspace_config`, `common_git_include`, and the
release-binary helpers — and each distro half supplies exactly six functions:
`common_pkg_prereqs`, `common_install_selected_apps`, `common_install_terminals`,
`common_login_shell_zsh`, `common_chezmoi`, `common_starship`.
`tests/test_distro.py` asserts both halves supply all six, that neither
redefines anything posix owns, and that neither reaches for the other's package
manager (comments stripped first — both files talk about the other at length,
and that prose is the useful part).

The pacman half came out roughly a third the size of the apt one, which is the
measurement worth keeping: **most of `_common-debian.sh` is not apt, it is the
absence of apt.** eza, delta, gh, ghq, lazygit, dust, gdu, bottom, bandwhich,
gping, atuin, yazi, glow, neovim and zed each needed a GitHub-release fetch, a
PPA or a third-party apt repo because no Debian or Ubuntu archive carries them.
Every one is in Arch `extra`; only `llmfit` still needs the tarball. The
`batcat`/`fdfind` symlink repairs disappear the same way — Debian renames both
binaries to dodge package name clashes, Arch does not.

`ts_arch_pkg` carries the six ids whose package name differs (`delta`→
`git-delta`, `gh`→`github-cli`, `tldr`→`tealdeer`, `node`→`nodejs`, `pipx`→
`python-pipx`, `poetry`→`python-poetry`). An id with no case arm is **reported
and skipped**, never silently dropped, and a test asserts the mapping is total
over every catalog row a Linux box could install — because a quietly missing
tool is this repo's recurring failure, and "add a row to apps.conf" must not
cost Arch users the tool.

## Why the tmux config moved to the XDG path on Omarchy

The stack wrote `~/.tmux.conf`. Omarchy ships its own config at
`~/.config/tmux/tmux.conf`. tmux reads one **or** the other, and which one wins
is not obvious from the man page, which says only "looks for a user
configuration file at `~/.tmux.conf` or `$XDG_CONFIG_HOME/tmux/tmux.conf`" and
lists all three paths together under FILES.

Probed directly, on tmux 3.7c, in a scratch `$HOME`:

```
both files present            -> prefix C-Space   (the XDG file)
only ~/.config/tmux/tmux.conf -> prefix C-Space
only ~/.tmux.conf             -> prefix C-a
```

**The XDG path wins.** So on Omarchy the stack was applying a file tmux never
read. The wizard asked for a tmux prefix, saved it, rendered it, showed it in
`chezmoi diff` — and it did nothing. No error, nothing missing, nothing to
notice. That is worse than shipping no tmux config at all.

Writing the XDG path instead is necessary but not sufficient: taking it outright
would delete Omarchy's Alt+Enter splits, Alt+1..9 window switching and the
Super+/ keybindings popup, and would leave `omarchy-theme-set-tmux` re-tinting a
bar we had overwritten. So the rendered file `source-file -q`s Omarchy's config
**first**, then applies the stack's settings. Later `set` wins in tmux; the
order is the entire mechanism. `-q` is load-bearing — the same template renders
on plain Arch, where that file does not exist.

The stack's own status bar is deliberately **not** applied on Omarchy. Its
colours are baked light/dark at render time, so it would pin the bar to
Catppuccin while every other surface on the desktop followed the active Omarchy
theme. Plain Arch has nothing to follow and keeps the baked one.

Two files, one body: both paths include `.chezmoitemplates/tmux-core`, and
`.chezmoiignore` gates them against each other on `distroId` so exactly one is
ever written. Both present is the silently-wrong state, so the bootstrap parity
check asserts the *other* one is absent, not merely that the right one exists.

## Why the bootstrap does not `chsh` on Omarchy

`common_login_shell_zsh` runs `sudo chsh -s /usr/bin/zsh`. On Omarchy that is
the wrong thing to do during a dotfiles install, and it fails silently in the
worst way: everything appears to work and the desktop's entire shell
environment is simply gone.

Omarchy is bash-first by construction. `~/.bashrc` sources
`$OMARCHY_PATH/default/bash/rc`, which pulls in `envs`, `shell`, `aliases`,
`functions`, `init` and `completions` — its `EDITOR`/`BROWSER` wiring, the
zoxide `cd` wrapper, mise/starship/zoxide/fzf init, and the aliases the
keybindings and menus assume. None of that is in `~/.zshrc`. And Omarchy ships
an official `omarchy-zsh` package (repo `omarchy`, deps `zsh eza mise zoxide
starship fzf fd bat zsh-syntax-highlighting`) rather than expecting anyone to
`chsh` by hand — which is the strongest available statement of intent.

So on Omarchy the login shell is left alone, zsh is installed and `~/.zshrc` is
still applied, and the bootstrap prints what to run (`zsh -l`) and why it did
not switch. On **plain Arch** the `chsh` still happens: that is ordinary Arch
behaviour and there is no bash-first contract to break. The test drives both
branches behaviourally, with `chsh` stubbed, rather than grepping for a string.

Phase 1 keeps oh-my-zsh here rather than adopting `omarchy-zsh`, deliberately:
`omarchy-zsh` generates its own `~/.zshrc` and chezmoi owns that file whole, so
making both work means restructuring the stack's zsh content into a sourced
fragment. Until that lands, oh-my-zsh is self-contained in `~/.oh-my-zsh` and
removable in one step.

The related veto: **Omarchy owns language runtimes, via mise.** `mise-bin` is in
its base package set, `omarchy install dev-env <lang>` is entirely
`mise use --global`, and `env-bootstrap` puts `~/.local/share/mise/shims` on
PATH. A second version manager competes for the same binaries with PATH order
deciding the winner, so `fnm`, `node` and `python` are removed from the catalog
on Omarchy — in `ts_apps_load` and `App.installable`, not merely skipped at
install time. An id that is offered, ticked and then skipped is one
`ts_apps_pending` reports as missing on every `tstack update`, forever, which is
the exact nag `ts_app_installable` was added to end. `uv`, `pipx`, `ruff` and
`ipython` stay: they are tools, not version managers, and Omarchy's own
`dev-env python` installs `uv` too.

## Why the Omarchy integration installs into Omarchy's extension points

Omarchy themes the terminal it knows about -- alacritty, foot, ghostty, kitty --
from the active theme's `colors.toml`, and it knows about exactly those four.
`omarchy install terminal`, `omarchy default terminal`, `omarchy font set` and
`default/themed/*.tpl` all enumerate the same list. WezTerm is not on it, so on
an Omarchy desktop the stack's flagship terminal sat in Catppuccin while every
other surface turned Tokyo Night.

The tempting fix is to read `colors.toml` from the WezTerm config and be done.
The better one is to use the seams Omarchy publishes, because they are what make
the result survive: `~/.config/omarchy/themed/<name>.tpl` is globbed by
`omarchy-theme-set-templates` and rendered into
`~/.local/state/omarchy/current/theme/<name>` on every theme change, and
`~/.config/omarchy/hooks/<event>.d/` is documented in Omarchy's own agent skill.
Using them means the stack never parses a format it does not own, never edits a
file Omarchy will overwrite, and gets re-rendered by Omarchy's machinery rather
than by ours.

Three files, and three rules that fell out of building them.

**Additive only.** Each has a name of its own -- `wezterm.lua.tpl`,
`hooks/*/terminal-stack` -- so nothing Omarchy or a stow tree owns is edited.
That is the same bargain `~/.config/git/terminal-stack.gitconfig` strikes on a
fleet where `~/.config/git/config` is somebody else's symlink, and stow links
per file, so a new sibling is undisturbed.

**Ownership is a marker, and the marker has to be on one line.** A file at one
of those paths without it is somebody's own and is left alone, said out loud.
The WezTerm template shipped with the marker WRAPPED across two lines, and
`_is_ours` greps line-wise: every sync then politely skipped its own template
while reporting "up to date", so an upgrade could never reach it. Caught by
`tstack omarchy status` on the first live run, which is the argument for having
a status verb at all.

**`off` is a machine-local sentinel, not a chezmoi `[data]` key.** Adding a key
to that store has a documented seven-step blast radius, and this decision is per
machine by nature: the artefacts only exist where Omarchy does. The sentinel is
also what stops `run_after_50-omarchy-integration.sh` reinstating on the next
apply what someone deliberately removed -- the same shape as the TTS mute
sentinel, and the same reason `tstack ghostty off` acts on one machine.

Two deliberate limits.

The theme hook does **not** re-render on every theme change. Flicking through
the theme picker fires it per keystroke, and only a light<->dark FLIP changes
anything the stack bakes -- so it compares first, using the `mode` key Omarchy's
`colors.toml` states outright. That is also strictly better than the gsettings
probe `resolve_os_theme` falls back to, which reads a value Omarchy wrote.
It does always touch the WezTerm config, because WezTerm watches its OWN config
file and not the generated theme beside it, so nothing reaches a running
instance otherwise.

The post-update hook **reports and does not pull**, which is not what was
originally wanted. `tstack update` is a zsh function (`commands.conf`:
`update  @_tstack_update`) carrying the dirty-clone refusal, the rollback point
and the duplicate-clone warning; a bash hook can neither call it nor honestly
reimplement it, and a second copy of that logic is exactly what
`_common-posix.sh` exists to prevent one file over. Making the hook pull needs
`tstack update` ported to Python first. Until then the hook does the half it can
do correctly -- fetch, and say what is waiting, after Omarchy's own migrations
have run.

## Why the docker advice asks Omarchy's permission first

`engine_advice` told a user whose engine refused them to run
`sudo usermod -aG docker "$USER"`. On Omarchy that is advice to undo a decision
the distro made on purpose: `install/config/docker.sh` declines the group and
writes down why -- membership is equivalent to passwordless root, because
anything in it can `docker run -v /:/host` -- and ships
`omarchy-setup-security-sudoless-docker` as the opt-in, behind a warning.

The stack has no business quietly talking someone out of that. On Omarchy the
DENIED branch now names `sudo docker` (per command, no escalation) and Omarchy's
own opt-in, and nowhere mentions `usermod`. Every other Linux keeps the advice
it had: the group is the ordinary answer there, and the point is not that the
group is wrong, it is that this distro already considered it.

Same shape one level up, in the parity runner: `tests/parity/run.sh` escalates
to `sudo docker` on its own when a plain `docker info` fails and a passwordless
`sudo docker info` works. Without that, the gate for the Arch platform could not
run on the Arch platform -- and the fix must not be "join the docker group",
because that is the thing being respected.

## Why Omarchy's zsh base is sourced, and why two names are escaped

Omarchy ships `omarchy-zsh`, an official package that is the zsh half of the
aliases, functions and environment its bash rc provides. Adopting it is obviously
right on an Omarchy box -- `zsh -l` should not be a different machine from the
one Super+Return opens -- and obviously impossible as packaged: `omarchy-setup-zsh`
generates its own `~/.zshrc`, and chezmoi owns that file whole-file. Two owners,
one file.

The way out was to read what the generator actually writes. It is two lines:

    source /usr/share/omarchy-zsh/shell/zoptions
    source /usr/share/omarchy-zsh/shell/all

So `dot_zshrc` sources those files directly and the generator is never run.
Nothing is lost and ownership is never contested -- the same move the tmux config
makes on Omarchy, and for the same reason. `inits` is skipped out of that
aggregate because it initialises starship, zoxide, mise and fzf, all of which
this rc already does, and the prompt is a saved setting: two inits means two
precmd hooks for one prompt.

THE PART THAT WAS NOT OBVIOUS

zsh expands aliases at PARSE time. Omarchy defines `c` and `cy` as aliases; this
stack defines both as functions; and defining a function whose name is a live
alias is a parse error. A parse error in an rc does not stop at its line -- it
abandons the rest of the file. With omarchy-zsh installed:

    /root/.zshrc:470: defining function based on alias `cy'
    /root/.zshrc:470: parse error near `()'
    ws=none  doc=none  tstack=none        <- everything after line 470

`ws`, `doc`, `tstack`, the `cc*` wrappers: all silently absent, on one distro
only, from a line 470 lines earlier. This was found by RUNNING the rc in the
omarchy parity container, not by reading it, and it would not have been found any
other way.

The first fix attempted was the obvious one -- wrap the definitions in
`if [[ -z "$_TS_OMARCHY_ZSH" ]]; then ... fi`. It does not work, and the reason
is worth keeping: zsh parses the whole `if` block before it evaluates the
condition, so the alias is expanded regardless of which branch would run. What
works is escaping the name, `\cy()`, which suppresses expansion at parse time;
the guard then decides only whether the function is DEFINED.

Exactly two names collide, and that was computed rather than assumed: every
alias omarchy-zsh defines, intersected with every function `dot_zshrc` defines.
`tests/test_omarchy_zsh.py` carries the alias set and fails on any unescaped
collision, so a future stack function called `d`, `t` or `g` is caught by a test
rather than by somebody's shell going quiet.

Both collisions are deferred to Omarchy, which is what the machine's owner
chose: `c` is opencode there and Cursor here, genuinely different programs, and
`cy` is codex on both sides. The deferral is not merely a preference for `cy` --
it is also the shape that avoids the parse error without an escape hatch nobody
would remember.

The repo has met this exact failure before. It is why `dot_zshrc` does not load
oh-my-zsh's `z` plugin: "(eval):...: defining function based on alias `z'".
## Why herdr's pane shell is a setting, and why `auto` means the stack's shell

The entry below says the stack owns `[theme] name` "and nothing else", and names
`[terminal] default_shell = "pwsh"` as the hand-written value a whole-file render would
have destroyed. Owning that exact key afterwards deserves an explanation.

The case that forced it is Omarchy. herdr spawns the **login shell**, which there is
bash and always will be: Omarchy's desktop is bash-first and the fleet never runs `chsh`
(`docs/omarchy.md`). The shell this stack actually configures — the prompt, the tools,
the agent wrappers, `dot_zshrc` — is zsh. So on the one platform where the two differ,
herdr's default hands you a pane that is not the machine the rest of the stack set up.
No amount of theme splicing fixes that, and telling each machine to hand-write the key
is how a fleet setting comes to be forgotten on the third box.

`auto` therefore means **the shell this stack configures**, not the login shell: `pwsh`
on Windows, `zsh` on macOS, Ubuntu and Omarchy. Two answers across four platforms, and
neither is read from `/etc/passwd`.

Four constraints shaped the rest, and each one is a test.

**The choice is stored; the path is resolved.** `[data]` holds `auto`/`zsh`/`bash`/
`pwsh`/`login`. It could not hold a path even if that were desirable: a Windows path
carries backslashes and `schema.Setting.validate` refuses those for this store, because
`store.set` writes `key = "<value>"` into chezmoi.toml unescaped. A stored path would
also be wrong on the other side of a combined Windows+WSL machine, which shares one
store and runs two independent herdr servers.

**What is written is absolute.** The herdr server is long-lived and keeps the
environment it started with, so its `PATH` is not the shell's — the same property that
had already cost this repo an ssh agent in every pane. A bare `zsh` would be resolved
against an environment nobody has looked at.

**A missing shell is never written.** A `default_shell` pointing at something absent
breaks every new pane. Leaving herdr on the login shell it was already using is strictly
better, so the key is omitted and `status` says why.

**`auto` defers to a hand-written value.** This is the one that keeps faith with the
module's premise: a line without the marker is yours. The `"pwsh"` machine in that
docstring must not have its shell changed by a *default*, and it does not — `auto` sees
an unmarked `default_shell` and stands down. Naming a shell explicitly takes the key
over, because that is a decision rather than a default, and the file is backed up before
the first write either way. `login` removes the line the stack wrote: a splice that
leaves its last value behind after being turned off is not a splice.

`shell_mode` stays unowned. The stack owns one key in `[terminal]`, not the table.

## Why herdr is opt-in, spliced rather than rendered, and keeps its own prefix

herdr is a terminal multiplexer that hosts coding agents: one Rust binary running
a background server, panes that survive detach and reboot, and every pane marked
working, blocked or idle. It overlaps this stack in three places at once — tmux,
the WezTerm mux domain, and the `cc*` wrappers' tab titles — so adding it was
mostly a set of decisions about what NOT to do.

**It sits beside tmux; it does not replace it.** tmux stays the `ssht` persistence
story on servers, and nothing in the stack starts herdr for you. The cost accepted
is that a machine can have three multiplexers available at once. The alternative,
making `herdrConfig on` mean "tmux drops out", would have reached `ssht`, the
wrappers and half the docs for a change nobody had asked for yet.

**It keeps herdr's own `ctrl+b` prefix, and there is no `herdrPrefix` setting.**
Matching upstream means every herdr tutorial applies unmodified and the store
carries one fewer key. The known cost is that `ctrl+b` is also this stack's
`tmuxPrefix` default, so tmux nested inside a herdr pane never sees the chord —
and decision one makes that nesting reachable rather than impossible.

The mitigation is a `tstack doctor` **note**, not a setting and not a rewrite:
which of the two chords to move is the user's call, and a doctor that edited
either would be making it for them. The note is **gated on tmux actually being
installed**, which is the difference between a warning and a nag. herdr keeps
`ctrl+b` by decision, so a machine reporting a collision it has decided to live
with, on every single `tstack doctor` run, forever, is a report nobody reads.
That is the same failure `ts_app_installable` was added to end when a macOS box
was told about `nvtop` on every update.

**The config is a key SPLICE, not a whole-file render.** This is the one place
`tstack/herdr.py` diverges from `tstack/ghostty.py`, which it is otherwise
modelled on, and the divergence came from looking at a real machine rather than
reasoning about one. herdr writes `config.toml` itself — `herdr config reset-keys`
backs it up and rewrites it, and the global menu edits it — and so does the user.
The first box this shipped to already carried a hand-written `onboarding = false`
and `[terminal] default_shell = "pwsh"`. A whole-file mirror would have deleted
both, silently, with nothing in any diff: exactly the hazard that once disabled
the agentmemory plugin by whole-file-copying `~/.claude/settings.json`, on a
format with no cheap key splice. So the splice is written out by hand, line
oriented, and it preserves comments, formatting and the file's own line endings.

Ownership is therefore per **key**, and the set is one: `[theme] name`.

**`theme.name = "terminal"`, not a theme name and not `auto_switch`.** herdr ships
eleven built-in themes plus a light/dark `auto_switch` pair. Naming one would make
the stack a second theme owner and would have to be re-derived every time
`themeMode` changed. Worse, deriving it from `resolvedTheme` is precisely the trap
the Ghostty config documents: the value looks right and silently freezes `follow`.
`terminal` tells herdr to use the host terminal's ANSI palette, which this stack
already themes, so one value is correct in dark, light AND follow, and stays
correct when the OS appearance flips underneath. No re-render, no second owner.

**`off` restores, and never unlinks.** Ghostty's `off` deletes what it deployed,
because it deployed the whole file. Here the file is mostly someone else's, so
`off` restores the `.bak.YYYYMMDD` taken before the first write, and failing that
removes only the marked line. As with Ghostty it is deliberately not a
`.chezmoiremove` rule and not a sync-side delete: both of those run on every
machine and would wipe a hand-written config on a box that never opted in.

**Installed by herdr.dev's own script on every platform.** Not winget: there is no
stable `Herdr.Herdr` manifest, only `Herdr.Herdr.Preview` (which is Herdr, Inc.'s
but pins the preview channel) and three third-party republishes. Not brew on
macOS either, which is the less obvious half — `herdr channel set` is documented
as working on direct installs only, and this stack **detects** the channel rather
than storing it, matching the WezTerm channel precedent. A brew-managed herdr
would report a channel nothing could change.

**Routed by an id list, not by its group.** `herdr` belongs in `shell` next to
tmux, because that is what it is. Putting it in `ai` to get a non-package install
would hand it to `ts_install_ai_cli`, which has no branch for it and would print
"no agent-CLI installer defined" — the same coupling that put `llmfit` in
`models`. So `ts_app_is_herdr` / `Test-TsAppIsHerdr` is an explicit id list, the
shape `$TsPyTools` already uses on the Windows side.

**`tstack update` reports a newer herdr and installs nothing.** herdr already
checks in the background on its own. Updating a live multiplexer is the same class
of hazard as restarting the WezTerm mux server, which this stack deliberately
never automates.

**On a combined Windows plus WSL machine, both sides run their own server.** Two
installs, two sockets, two configs, and no stack opinion about which one you
attach to. The consequence built for: `tstack herdr status` reports both, labelled,
rather than assuming one is authoritative, and it reaches the Windows one through
interop (`herdr.exe`) — never `pgrep`, which finds nothing inside WSL while a
healthy Windows-side server runs on the same machine, the trap `tstack mux`
already documents. Neither side resolves its config to a `/mnt/c` path, and
neither sets `HERDR_SOCKET_PATH` for the other.

**The wizard question is probed, not always asked.** It only appears when there is
a herdr to configure: already on PATH, or ticked in the app picker moments ago.
It is asked even when headless, unlike the WezTerm toggles — a multiplexer is
exactly what earns its keep on a server reached over ssh. And it is a different
question from "install herdr", which the picker already asked: running herdr with
its own untouched config is a supported answer rather than an oversight.


## Why the starship preview subprocess names its encoding

`tstack wizard` opens by rendering the prompt live, which shells out to starship.
On Windows that call died, and took the entire questionnaire with it:

```
AttributeError: 'NoneType' object has no attribute 'strip'
  tstack/choices.py, _preset_config
```

The cause is two failures compounding. `subprocess.run(..., text=True)` with no
`encoding` decodes with the locale codec, which on a Windows console is cp1252 —
and starship's own preset output carries bytes cp1252 has no mapping for. The
`UnicodeDecodeError` is then raised inside subprocess's reader THREAD, not in the
caller. So the call returns normally, with `returncode == 0` and `stdout` set to
`None`. Every guard in this file tested `got is None or got.returncode != 0`, all
of which passed, and the next `.strip()` died a long way from the cause.

(Since generalised: `tstack/proc.py` is now the one capture helper, and
`choices.py` delegates to it rather than naming the encoding itself. The reasoning
below is why that module exists.)

Two changes, because either alone leaves the trap armed. The encoding is now
named (`encoding="utf-8", errors="replace"`) on both subprocess calls in the file,
and `_run` treats `stdout is None` as failure — another decoder can still fail on
some other input, and a caller reading `None` is the failure mode this exists to
end.

It had been failing on every Windows machine for as long as the preview has
existed, and it took eleven tests in `tests/test_wizard.py` with it. They were red
locally and read as a Python 3.14 quirk. They were not.

## Why the Windows gitconfig pins `core.sshCommand`

After a `tstack update`, every git command over ssh asked for the key
passphrase — in PowerShell and in a brand-new WezTerm alike — while `ssh-add -l`
in the same pane listed both keys. The agent was healthy throughout.

Unset, `core.sshCommand` leaves git running **Git for Windows' bundled MSYS**
ssh (`C:\Program Files\Git\usr\bin\ssh.exe`), which cannot speak the named pipe
`\\.\pipe\openssh-ssh-agent` that the Windows agent listens on. One pane, one environment,
both binaries:

| ssh binary | `-T git@github.com` |
|---|---|
| `C:/Windows/System32/OpenSSH/ssh.exe` | `Hi martybytes! You've successfully authenticated` |
| `C:/Program Files/Git/usr/bin/ssh.exe` | `Permission denied (publickey)` |

Non-interactively that is a denial; interactively ssh falls back to prompting,
which is what a human sees. Pointing git at native OpenSSH fixes it — verified
with `GIT_SSH_COMMAND` set and `git ls-remote origin HEAD` returning a SHA with
no prompt.

**This was never a regression from the `SSH_AUTH_SOCK` pipe fix.** MSYS ssh could
never use the Windows agent; that fix repaired native `ssh` and left `git`
untouched, which is why the symptom only became visible once `ssh` itself
started working. Before this change a repo-wide grep for `sshCommand`, `GIT_SSH`,
`GIT_SSH_COMMAND`, `System32/OpenSSH` and `usr/bin/ssh` returned **zero hits**:
which ssh binary git runs had never been pinned anywhere.

### Why the mirror diverges, when it never had before

`dot_config/git/terminal-stack.gitconfig` and its Windows copy were byte-identical
by convention, stated in their shared header. The fix cannot honour that: the
value is an **absolute Windows path**, and the canonical copy is applied to WSL,
macOS and native Linux, where `core.sshCommand = C:/…` breaks git outright.

Three options were weighed. A portable `sh -c` guard in the shared file (the
idiom `core.pager` already uses there) would have kept the mirror intact, but
hides a platform decision inside a shell one-liner that every POSIX machine then
evaluates on every remote operation. Having the bootstrap write
`git config --global core.sshCommand` alongside the `include.path` line it
already adds would avoid touching either file, but only fixes machines that
re-run the bootstrap and puts stack policy in the user's own `~/.gitconfig`.
The mirror diverges instead: one line, in the file that already carries every
other git setting, visible in a diff.

So the header now states the real rule — identical **except** `core.sshCommand`,
canonical must never gain it — and `tests/test_gitconfig.py` pins that shape in
both directions. There was no gitconfig test of any kind before; a mirror that
silently loses the line puts the passphrase prompts back, and a canonical file
that silently gains it breaks every POSIX target, so both directions had to fail
loudly rather than quietly.

`tstack doctor` reports it as `git-ssh-command`. A value pointing at some other
ssh is a **note, not a failure** — routing through 1Password or a custom agent is
a legitimate choice, and failing an install over it would train people to ignore
the exit code.

## Why the agent probe names two sockets

Found while investigating why WSL had no agent at all. `dot_zshrc` recovered
`$XDG_RUNTIME_DIR/ssh-agent.socket` — the **Arch** name, which is what
omarchy-dots' bash half uses. Debian and Ubuntu's `/usr/lib/openssh/agent-launch`
creates **`$XDG_RUNTIME_DIR/openssh_agent`** instead. The probe could therefore
never fire on WSL or a Debian server: two of the three targets this stack ships
to, silently, since the block was written.

Arch stays **first**. `tests/test_ssh_auth_sock.py` pins that path as the contract
with omarchy-dots, which owns the bash half in a repo we do not control — if the
two halves ever chose different sockets, a machine would end up talking to two
agents. Adding the Debian name as a *fallback* keeps that contract exactly.

Verified in real zsh: the Debian socket is found, the Arch one wins when both
exist, a forwarded `ssh -A` value survives, a stale path is replaced, and a
machine with no socket is left alone.

**What this does not do is start an agent.** On Ubuntu 24.04 `ssh-agent.service`
is `static` (no `[Install]` section) and ordered `Before=graphical-session-pre.target`,
so with no graphical session in WSL nothing pulls it in and no socket is ever
created — its `ConditionPathExists=/etc/X11/Xsession.options` and `use-ssh-agent`
gates both pass; only the session is missing. Shipping a unit that spawns an agent
on headless hosts is a behaviour change, and the Omarchy audit put it on the record
that the stack contains no ssh-agent code. That decision deserves its own change,
not a rider on a git fix — it was made on 09/07/2026, below.

## Why a WSL install stopped writing to the Windows side

Moving the WSL clone to ext4 (above) settled where files live. It left a second question:
should a WSL apply still *provision Windows*? It used to -- `run_after_90-sync-windows.sh`
mirrored `windows/**`, `dot_codex/**` and `docs/kb/**` into `/mnt/c/Users/<you>/`, rendered
the Windows starship config and TTS config, and installed a Windows TTS EXE.

It no longer does, on WSL. The reason is that once WSL and Windows each have their own
clone, **both sides write the same destinations**, and `scripts/sync-windows.ps1` is a full
parallel implementation of the same mirror, not a stub. Two writers, two clones, possibly
two commits:

- Each renders `$PROFILE`, `.wezterm.lua` and `settings.json` from its own tree. They
  differ by a byte, so each backs the other's version up and overwrites it -- you collect
  `.bak.YYYYMMDD.1`, `.2`, `.3` on every alternating apply.
- They read *different config stores*: the bash hook renders from chezmoi `[data]`, the
  pwsh script from `config.json`. `doctor`'s `config-divergence` check exists precisely
  because those drift, and the 2026-08-21 incident it records is exactly this shape -- the
  mirror said false, `[data]` said true, and a pwsh sync deleted every TTS hook while
  doctor reported "tts daemon healthy".

Nothing detected or refused a second writer; the only mitigation was a byte-comparison
before write, which makes *identical* clones idempotent and does nothing for the real case.

So: the hook no-ops on WSL and says so rather than skipping silently, because somebody who
used to get their Windows profile provisioned from WSL needs to know it moved. Windows is
delivered by `scripts/sync-windows.ps1` (`tstack update` in PowerShell), which was already
a complete standalone path. The config mirror stopped too, in both twins
(`ts_mirror_windows_config`, `_refresh_windows_mirror`) -- a WSL save must not reach into
a store another install owns.

**What deliberately stays**, because the thing genuinely lives on the Windows side and no
Linux equivalent exists. This is a READ list, not a write list, and it is the difference
between "self-contained" and "isolated":

- **mux interop** (`tasklist.exe`, `taskkill.exe`, `wezterm.exe`): with a Windows-hosted
  WezTerm the mux server really is a Windows process, invisible to `pgrep` inside WSL.
- **TTS playback**: WSL2 has no reliable audio device; the daemon is a Windows EXE.
- **Theme `follow`**: the light/dark setting only exists in the Windows registry.
- **GUI agent config**: Cursor and Codex run as Windows processes and keep their settings
  in the Windows profile.
- **`windowsUsername`**: still needed to find any of the above.
- **`.chezmoiignore`'s WezTerm gate**: WSL correctly gets no `.wezterm.lua`, because the
  Windows install owns it. Do not "fix" this by adding a WSL branch unless someone is
  actually running a Linux WezTerm inside WSL.

Three doctor checks were narrowed from `is_windows_side()` (Windows **or** WSL) to Windows
only, because they measured files a WSL install no longer owns: `config-divergence`, the
Claude TTS hook check, and `git-ssh-command` -- that last one was measuring *WSL's own*
git and demanding a `C:/` path that would be wrong there if it were set.

## Why the bootstrap starts an agent, and why it does not disable anyone else's

The change the section above deferred, made 09/07/2026 on a fresh WSL Ubuntu
24.04 install where every `ssh` and every `git push` asked for a passphrase and
`ssh-add -l` answered `Could not open a connection to your authentication agent`.

Two independent things were wrong, and fixing either alone changes nothing:

1. **Nothing pulled the unit in.** `ssh-agent.service` is `static` on Ubuntu —
   no `[Install]` section, so `systemctl --user enable` has nothing to write —
   and is ordered `Before=graphical-session-pre.target`, which a login with no
   desktop never reaches. `systemctl --user add-wants default.target
   ssh-agent.service` writes the `.wants` symlink the unit cannot write for
   itself, at a target that *is* reached.
2. **Starting it by hand also did nothing, and said it had worked.** Debian and
   Ubuntu run the agent through `/usr/lib/openssh/agent-launch`, whose first act
   is `[ -z "$SSH_AUTH_SOCK" ]`. `gpg-agent-ssh.socket` is enabled by default and
   sets exactly that variable in the user manager's environment, so the script
   exits 0 without executing `ssh-agent`. `systemctl --user status` reports
   `Started`, `Main PID … (code=exited, status=0/SUCCESS)`, and no socket exists.
   Nothing anywhere says why.

The obvious fix for (2) is `systemctl --user disable gpg-agent-ssh.socket`. It
works, and it is **not ours to do**: a machine that genuinely keeps its ssh keys
in gpg would lose them from every session, and an installer that silently
switches which agent a person's keys live in has overstepped. Instead the
bootstrap drops a user-scope override that runs `ssh-agent` directly, leaving
`agent-launch`'s guard nothing to guard:

```ini
[Service]
ExecStart=
ExecStartPre=-/bin/rm -f %t/openssh_agent
ExecStart=/usr/bin/ssh-agent -D -a %t/openssh_agent
```

Both agents then exist and neither is taken away, because `dot_zshrc` never
overwrites a **live** `SSH_AUTH_SOCK` (§ "Why the agent probe names two
sockets") — whichever socket a session actually inherits still wins. The
override is written **only** when a start produced no socket, so Arch, which
socket-activates the unit at its own `ssh-agent.socket` path, never gets one.

Three further constraints, each pinned by `tests/test_ssh_agent_bootstrap.py`:

- **A live agent is never restarted.** A restart drops every key already loaded,
  which puts the person back to typing passphrases — the exact thing this step
  removes. Re-running the bootstrap must be free.
- **The two halves must name the same sockets.** The bootstrap creates one of
  exactly the names `dot_zshrc` probes, in the same order. An agent bound
  anywhere else is an agent no shell will ever find, and the failure is silent.
- **No systemd user manager is a no-op, not an error.** A container has none, and
  so does a WSL distro without `systemd=true` in `/etc/wsl.conf`; the parity
  bootstrap container runs this code. WSL gets a one-line pointer at
  `doc ssh-config` because a person is watching there; a container gets silence.

It is an **install** step and not an apply step. It starts a process and edits
the user manager's units, neither of which is what `chezmoi apply` is for, and
`.chezmoiignore` keeps the whole of `bootstrap/**` out of the apply anyway. The
statement in the Omarchy audit — that the stack ships no ssh-agent code — is
therefore still true of everything an apply touches.

Filling the agent is deliberately left to `~/.zshrc.local`, where
`dot_zshrc.local.example` documents a keychain-style `sshkeys` helper. Which keys
a machine should hold, and whether a passphrase prompt at first login is welcome
at all, is exactly the kind of per-machine answer that must not propagate through
a shared repo.

## Why a container on a WSL2 host still says WSL

A container shares the host **kernel**. On a WSL2 host that kernel is
Microsoft's, so `/proc/version` carries `microsoft` *inside* every container, and
all three probes in this repo that read that file report `wsl` there:
`_ts_is_wsl` in `bootstrap/_common-posix.sh`, the `_plat` case in
`bootstrap/_config.sh`, and `is_wsl()` in `tstack/platform.py`.

They agree with each other, and that is the property that matters -- the three
were deliberately written to match, and `_config.sh` says so in a comment. None
of them is changed here. Reporting `linux` inside a container would be *more*
accurate and is tempting, but it is a change to platform identity in three
places at once, and the failure it would prevent is better prevented at the two
sites that actually got it wrong.

Because it got it wrong twice, in opposite directions, on the same day
(09/07/2026).

**Once by conditioning a distro rule on the machine axis.** `tstack/apps.py`
vetoes `fnm`/`node`/`python` on Omarchy, because Omarchy owns those binaries
through mise. The awk twin in `ts_apps_load` keys that on the distro alone; the
Python side also required `machine == plat.LINUX`. A real Omarchy box answers
`linux`, so the two agreed everywhere it could be observed -- except in an
Omarchy parity container on a WSL host, where both readers say `wsl`, bash still
vetoed and Python did not. `tests/parity/run.sh omarchy` was therefore **red on
every WSL dev box and green in CI**, whose runners are native Linux, so no gate
anywhere could report it. The veto is distro-only now, matching its twin
exactly, and `test_the_mise_veto_agrees_between_bash_and_python` -- named for two
readers and, until now, reading only one of them -- drives both across every
`kind()`.

**Once by addressing a person in a place with no person in it.**
`common_ssh_agent` prints a pointer at `doc ssh-config` when there is no systemd
user manager to enable the agent in, and gated that on `_ts_is_wsl` so it would
not fire in a container. `tests/parity/run.sh bootstrap` runs that file for real,
in a container, on this host -- and the hint duly printed into the build log. The
gate is `_ts_in_container` now, which checks `/.dockerenv` and
`/run/.containerenv` rather than asking what kernel it is standing on. Its marker
list is a variable so both branches are testable without being in a container,
and the test is confirmed in a real one.

The rule the two share: **`kind()` answers "what sort of machine is this", and it
is the wrong question for "which distro owns this binary" and for "is there a
human reading this".** Reach for the distro or for the container markers instead.
