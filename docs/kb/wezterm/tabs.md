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
Each tab shows ` <number>  <icon> <title> `: the title is **`tab.tab_title`** when set
(the `cc` wrappers and Claude hooks set it via `wezterm cli set-tab-title`), else the
active pane's **cwd leaf**. The icon tracks the foreground process (a robot while
Claude runs). Tabs with Claude panes add one coloured **dot per pane** (● working
peach / done green / error red, ○ idle) and the whole tab tints by its most urgent
pane; other multi-pane tabs show a pane count, and a zoomed pane adds an icon. The
status bar shows mode/workspace on the left and `user@host │ path` on the right —
see `doc wezterm/workspace`.
