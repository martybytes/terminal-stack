# Workspace navigation

| Command | What it does |
|---|---|
| `ws` | cd to the workspace — `$WORKSPACE_DIR` (zsh `~/.zshrc.local` / pwsh `profile.local.ps1`) if set, else autodetected |
| `wsp` | cd to the `*_Personal` / `*-Personal` sibling |
| `wspu` | cd to `public/github.com` in the organised tree, else the `*_Public` / `*-Public` sibling |
| `ws37` `ws42` `wsmb` `wsmd` | cd to `src/github.com/<owner>` for 37metrics / dimension42ai / martybytes / moleculardesigns |
| `wsar` | cd to `archive/github.com` |
| `wsj [query]` | fuzzy-jump to any repo in the tree (fzf; falls back to a filtered menu) |
| `wsw` | cd to the work workspace — `$WORK_WORKSPACE_DIR` if set, else the `*_Work` / `*-Work` sibling |
| `wsw --set [dir]` | write `WORK_WORKSPACE_DIR` into `~/.zshrc.local` / `profile.local.ps1` (default: current dir) |
| `wsw --show` | print the resolved work workspace without changing directory |
| `db` / `dbx` | cd to Dropbox — `$DROPBOX_DIR` if set, else Dropbox's own `info.json`, else the platform candidates |
| `z dirname` | zoxide — jump to any directory you've visited, from anywhere |
| `zi` | zoxide interactive picker when there are multiple matches |
| `zoxide-prune` | drop dead paths from zoxide's database (pwsh) |

Autodetect probes (first existing wins): `/mnt/c/DATA/Workspace`, `~/Documents/Workspace`, `~/workspace`, `~/Workspace` (pwsh also `C:\DATA\Workspace`).

`wsp`/`wspu`/`wsw` derive from that root by suffix, underscore first then dash — so
`Workspace_Work` and `Workspace-Work` both resolve. When the work tree lives somewhere
unrelated to the main workspace, `wsw --set /path/to/work` records it in the per-machine
override file (backing the file up first) and takes effect immediately.

`db` resolves in the same call-time, override-first style. It reads Dropbox's own
`info.json` (`~/.dropbox/`, `~/.config/dropbox/`, `%LOCALAPPDATA%\Dropbox\`) before guessing
at paths, because that file is the only thing that gets a relocated folder, a Business
account, or two linked accounts right; a `personal` root wins over a `business` one. The
fallbacks are `~/Library/CloudStorage/Dropbox` (macOS Ventura and later), `~/Dropbox`
(Linux, older macOS, Windows), then the `(Personal)` / `(Business)` variants. Under WSL it
looks at the Windows side via `/mnt/c/Users/<you>/`, since that is where the real store is.
Set `DROPBOX_DIR` in `~/.zshrc.local` / `profile.local.ps1` to override.

`ws37`/`ws42`/`wsmb`/`wsmd`/`wsar`/`wsj` address the organised tree that `wso` builds —
see `doc common/workspace-org`. They fall back to the archive tier when an owner has no
live `src/` directory, so they keep working as repos move between tiers. `wspu` prefers
the new `public/` tier and only falls back to the old `*_Public` sibling root, so it
behaves correctly before, during and after a migration.
