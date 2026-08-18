# Workspace navigation

| Command | What it does |
|---|---|
| `ws` | cd to the workspace — `$WORKSPACE_DIR` (zsh `~/.zshrc.local` / pwsh `profile.local.ps1`) if set, else autodetected |
| `wsp` | cd to the `*_Personal` / `*-Personal` sibling |
| `wspu` | cd to the `*_Public` / `*-Public` sibling |
| `wsw` | cd to the work workspace — `$WORK_WORKSPACE_DIR` if set, else the `*_Work` / `*-Work` sibling |
| `wsw --set [dir]` | write `WORK_WORKSPACE_DIR` into `~/.zshrc.local` / `profile.local.ps1` (default: current dir) |
| `wsw --show` | print the resolved work workspace without changing directory |
| `z dirname` | zoxide — jump to any directory you've visited, from anywhere |
| `zi` | zoxide interactive picker when there are multiple matches |
| `zoxide-prune` | drop dead paths from zoxide's database (pwsh) |

Autodetect probes (first existing wins): `/mnt/c/DATA/Workspace`, `~/Documents/Workspace`, `~/workspace`, `~/Workspace` (pwsh also `C:\DATA\Workspace`).

`wsp`/`wspu`/`wsw` derive from that root by suffix, underscore first then dash — so
`Workspace_Work` and `Workspace-Work` both resolve. When the work tree lives somewhere
unrelated to the main workspace, `wsw --set /path/to/work` records it in the per-machine
override file (backing the file up first) and takes effect immediately.
