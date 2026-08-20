# WezTerm — pane management

Leader: **Ctrl+Space** (configurable via `ts-config leader`) — tap, release, then
press the next key. It **waits** (no timeout): the cursor turns peach and a
`⌨ LEADER` badge shows; `Ctrl+Space` `Esc` cancels. "`Ctrl+Space` `h`" means
leader **then** `h`.

## Navigate-or-split — F1–F4 are directions
`F1`=left · `F2`=right · `F3`=down · `F4`=up (also `Ctrl+Space` `1`–`4`). Press to
**focus** the pane in that direction — or, when no pane is there, **split** one into
existence (50/50) and focus it. Stateless: every press does something predictable
in any layout.

| Key | Action |
|---|---|
| `F1`–`F4` (or `Ctrl+Space` `1`–`4`) | focus that direction, or split a new pane there |
| `Shift+F1`–`F4` | **always** split in that direction, into a fuzzy-picked domain (local, WSL, `SSH:*`…) |
| `F5` (or `Ctrl+Space` `5`) | **jump** — PaneSelect overlay, every pane gets a label |
| `F6` (or `Ctrl+Space` `6`) | **swap** — pick a pane to trade places with the active one |

## Split — local
| Key | Action |
|---|---|
| `Ctrl+Space` `h` | split down (new pane below, stacked) |
| `Ctrl+Space` `v` | split right (new pane to the side) |

## Split — into a domain
Shift = "remote": fuzzy-pick a domain (local, WSL, `SSH:*`…), then split it.

| Key | Action |
|---|---|
| `Ctrl+Space` `H` | pick domain → split down |
| `Ctrl+Space` `V` | pick domain → split right |

## Move / resize / rotate — repeatable modes
Arrows after the leader **enter a repeatable mode** (a coloured badge shows in the
status bar). Inside a mode, plain arrows **or** `j/k/i/m` keep going — no need to
re-press the leader. Every mode auto-exits on any non-mode key or a short idle;
`Esc`/`Enter` leave immediately.

| Enter | Mode | Repeat | Exit |
|---|---|---|---|
| `Ctrl+Space` `←/→/↑/↓` | **move** focus between panes | arrows or `j/k/i/m` | any other key · ~1s idle · `Esc` |
| `Ctrl+Space` `Shift+←/→/↑/↓` | **resize** (3 cells/press) | arrows (or `Shift+`) or `j/k/i/m` | any other key · ~1.5s idle · `Esc`/`Enter`/`q` |
| `Ctrl+Space` `Ctrl+←/→` | **rotate** panes through their slots (`←` = counter-clockwise, `→` = clockwise) | `←/→` or `j/k` | any other key · ~1.5s idle · `Esc` |

e.g. `Ctrl+Space ← ← ←` moves focus left three panes; `Ctrl+Space Shift+→ → →`
grows the pane right 9 cells.

## Zoom, pop & close
| Key | Action |
|---|---|
| `Ctrl+Space` `z` | toggle zoom (fill window; again to restore) |
| `Ctrl+Space` `o` | pop pane into its own window |
| `Ctrl+Shift+O` | pop to window (no leader) |
| `Ctrl+Space` `x` | close pane (confirms first) |

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
| `Ctrl+Space` `Ctrl+Space` | send a real `Ctrl+Space` to the app — the escape hatch, since the leader eats the first press (leader, then `Ctrl+Space`, whatever your leader is) |

## Do panes survive a GUI crash?
Only if the **multiplexer domain** is on, and it is **off by default** — panes are
spawned by the GUI, so a GUI crash takes them with it. `ts-mux on` moves them into
`wezterm-mux-server`, where they (and everything running in them) survive; `ts-mux`
alone reports which mode you're in. Trade-offs and the kill/restart/reset verbs:
`ts-mux -h`, `doc common/stack`.

> macOS: free `Ctrl+Space` and the F-row from the OS first — see `doc macos/wezterm`.
