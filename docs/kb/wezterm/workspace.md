# WezTerm — workspaces & launcher

Leader: **Ctrl+Space** — tap, release, then press the next key. It **waits** (no
timeout); `Ctrl+Space` `Esc` cancels.

## Launcher
| Key | Action |
|---|---|
| `Alt+L` | open launcher — fuzzy list of tabs, domains, workspaces, and commands (arrow keys to navigate) |

## Workspaces
Persistent named sessions; each has its own windows and tabs.

| Key | Action |
|---|---|
| `Ctrl+Space` `w` | switch — fuzzy picker of existing workspaces |
| `Ctrl+Space` `n` | new / switch — type a name to create or jump to one |
| `Ctrl+Space` `p` | **project picker** (sessionizer) — fuzzy-pick a repo from the `wso` workspace tree (and `*_Personal`/`*_Public`/`*_Work` siblings), switch to a workspace for it. Needs `fd` on PATH |

## Manage
| Key | Action |
|---|---|
| `Ctrl+Space` `R` | rename the current workspace |
| `Ctrl+Space` `X` | kill — close every pane in this workspace |

## Save / restore (resurrect)
Sessions autosave every 15 min, on window focus loss, and whenever you add or
close a pane or tab.

**Launching WezTerm starts clean by default** — it does not reopen what you had
last time. `ts-config restore on` changes that: every launch then replays the
last autosaved workspace, panes, layout, scrollback and all. Either way the
autosave keeps running, so `Ctrl+Space` `L` restores a session by hand whenever
you want one, and turning the setting on later gives you the session you had —
not a stale one from whenever you flipped it off.

| Key | Action |
|---|---|
| `Ctrl+Space` `S` | save the current workspace now |
| `Ctrl+Space` `L` | restore a saved state — fuzzy picker |

## Status bar
**Quiet by default.** The left side is empty until something is pending — then a
coloured badge names it (`⌨ LEADER`, or the active move/resize/rotate/tab/font
mode). There is no permanent badge in the normal state.

**Always on the right:** the **Claude fleet** — working/done/error counts across
every pane in every tab — the workspace name whenever it isn't the implicit
`default`. The title bar never shows a date or clock.

**`Ctrl+Space` `s`** adds `user@host │ path` for the **active pane** (the kind of
thing you usually already know; the tab titles carry the per-pane context). Press
it again to go quiet. The state survives config reloads but not a WezTerm
restart, so every launch starts clean.
