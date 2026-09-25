# WezTerm — pane management

Leader: **`Ctrl+\`** (configurable via `tstack config leader`) — tap, release, then
press the next key. It **waits** (no timeout): the cursor turns peach and a
`⌨ LEADER` badge shows; `Ctrl+\` `Esc` cancels. "`Ctrl+\` `h`" means
leader **then** `h`.

## Navigate-or-split — F1–F4 are directions
`F1`=left · `F2`=right · `F3`=down · `F4`=up (also `Ctrl+\` `1`–`4`). Press to
**focus** the pane in that direction — or, when no pane is there, **split** one into
existence (50/50) and focus it. Stateless: every press does something predictable
in any layout.

| Key | Action |
|---|---|
| `F1`–`F4` (or `Ctrl+\` `1`–`4`) | focus that direction, or split a new pane there |
| `Shift+F1`–`F4` | **always** split in that direction, into a fuzzy-picked domain (local, WSL, `SSH:*`…) |
| `F5` (or `Ctrl+\` `5`) | **jump** — PaneSelect overlay, every pane gets a label |
| `F6` (or `Ctrl+\` `6`) | **swap** — pick a pane to trade places with the active one |

## Split — local
| Key | Action |
|---|---|
| `Ctrl+\` `h` | split down (new pane below, stacked) |
| `Ctrl+\` `v` | split right (new pane to the side) |

## Split — into a domain
Shift = "remote": fuzzy-pick a domain (local, WSL, `SSH:*`…), then split it.

| Key | Action |
|---|---|
| `Ctrl+\` `H` | pick domain → split down |
| `Ctrl+\` `V` | pick domain → split right |

## Move / resize / rotate — repeatable modes
Arrows after the leader **enter a repeatable mode** (a coloured badge shows in the
status bar). Inside a mode, plain arrows **or** `j/k/i/m` keep going — no need to
re-press the leader. Every mode auto-exits on any non-mode key or a short idle;
`Esc`/`Enter` leave immediately.

| Enter | Mode | Repeat | Exit |
|---|---|---|---|
| `Ctrl+\` `←/→/↑/↓` | **move** focus between panes | arrows or `j/k/i/m` | any other key · ~1s idle · `Esc` |
| `Ctrl+\` `Shift+←/→/↑/↓` | **resize** (3 cells/press) | arrows (or `Shift+`) or `j/k/i/m` | any other key · ~1.5s idle · `Esc`/`Enter`/`q` |
| `Ctrl+\` `Ctrl+←/→` | **rotate** panes through their slots (`←` = counter-clockwise, `→` = clockwise) | `←/→` or `j/k` | any other key · ~1.5s idle · `Esc` |

e.g. `Ctrl+\ ← ← ←` moves focus left three panes; `Ctrl+\ Shift+→ → →`
grows the pane right 9 cells.

## Zoom, pop & close
| Key | Action |
|---|---|
| `Ctrl+\` `z` | toggle zoom (fill window; again to restore) |
| `Ctrl+\` `o` | pop pane into its own window |
| `Ctrl+Shift+O` | pop to window (no leader) |
| `Ctrl+\` `x` | close pane (confirms first) |

## Scrollback, quick select & links
| Key | Action |
|---|---|
| `Ctrl+Shift+↑` / `Ctrl+Shift+↓` | jump to the previous / next shell prompt in scrollback (OSC 133 semantic zones — zsh emits them via the sourced WezTerm shell integration; pwsh partially) |
| `Ctrl+Shift+Space` | QuickSelect — hint-label URLs/paths plus **git SHAs** and **`file:line`** refs in the viewport, press the label to copy |
| Ctrl-click | URLs open in the browser; a bare `owner/repo` opens on GitHub; `path/file.ext:123` opens in **Cursor** at that line |

## Literal keys
| Key | Action |
|---|---|
| `Shift+Enter` | send a literal newline (LF) — newline-without-submit in CLI REPLs like Claude Code, whose keybinding alone can't fire because terminals don't deliver a distinct Shift+Enter (`doc common/claude-code`) |
| `Ctrl+\` `Ctrl+\` | send a real `Ctrl+\` to the app — the escape hatch, since the leader eats the first press. It follows the leader: press whatever yours is, twice. Needed for nvim's `:terminal` exit (`Ctrl+\` `Ctrl+N`) and SIGQUIT |

## Do panes survive a GUI crash?
Only if the **multiplexer domain** is on. The installer asks and defaults to off,
so unless you said yes, panes are spawned by the GUI and a GUI crash takes them
with it. `tstack mux on` moves them into
`wezterm-mux-server`, where they (and everything running in them) survive; `tstack mux`
alone reports which mode you're in. Trade-offs and the kill/restart/reset verbs:
`tstack mux -h`, `doc common/stack`.

> macOS: free the F-row from the OS first (and `Ctrl+Space`, if that is your leader) — see `doc macos/wezterm`.
