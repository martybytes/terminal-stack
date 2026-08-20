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
Sessions autosave every 15 min and on window focus loss.

| Key | Action |
|---|---|
| `Ctrl+Space` `S` | save the current workspace now |
| `Ctrl+Space` `L` | restore a saved state — fuzzy picker |

## Status bar
Left shows the active mode badge (or `⌨ LEADER`) and the workspace; right shows
`user@host │ path` for the **active pane**. **`Ctrl+Space` `s`** toggles the
identity+path segment on/off (survives config reloads).
