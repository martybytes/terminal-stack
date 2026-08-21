# WezTerm — tabs

Tab selection uses **Alt** (no leader needed).

## Select by number
The number matches the tab.

| Key | Tab |
|---|---|
| `Alt+1` … `Alt+9` | tab 1 … 9 |

## Cycle
| Key | Action |
|---|---|
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | next / previous tab |
| `Ctrl+Space` `t` | **repeatable tab mode** — then `←`/`→` (or `j`/`k`, `n`/`p`) cycle tabs; `Esc` exits |

## Font size (repeatable)
`Ctrl+Space` `f` enters a font-size mode: `↑`/`↓` (or `k`/`j`) grow/shrink, `0` resets, `Esc` exits.

## Appearance
The bar is the taller **fancy** bar, fully hand-drawn. The **active tab is a solid
accent block** — that is the "which tab am I on" signal. Each tab shows
` <number>  <icon> [host ·] <title> `: the title is **`tab.tab_title`** when set
(the `cc` wrappers and Claude hooks set the **bare project name** via
`wezterm cli set-tab-title` — no `cc` prefix), else the active pane's **cwd leaf**,
never a full path; panes on another machine get a ` host ·` chip. The icon is a
robot for Claude panes, a remote-host glyph for ssh panes, else the foreground
process. Tabs with Claude panes add one coloured **dot per pane** (● working peach /
done green / error red, ○ idle) and inactive tabs tint by their most urgent pane;
other multi-pane tabs show a pane count, a zoomed pane adds an icon, and an inactive
tab with unseen output gets an accent dot.

## Status bar
Quiet by default: the left side is empty until the leader is pending or a repeat
mode is live (then a coloured badge names it). The right side always shows the
**Claude fleet** (working/done/error counts across every pane), the workspace name
when it isn't `default` — never a date or clock. **`Ctrl+Space` `s`** adds `user@host │ path`
for the active pane. See `doc wezterm/workspace`.
