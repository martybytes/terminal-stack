# eza (modern ls)

Maintained `ls` replacement: colors, Nerd Font icons, a git-status column,
tree view, saner defaults.

## How this stack wires it

- `ls` = `eza --icons=always --git --group-directories-first` in both shells
  (pwsh removes the built-in `Get-ChildItem` alias first).
- `lt` = the same with `--tree` (both shells). pwsh also defines `ll` (long)
  and `la` (long + hidden); in zsh use `ls -l` / `ls -la`.
- `EZA_COLORS='di=1;34:…'` bolds directories blue in both shells, matching
  WezTerm's ANSI blue in both themes — listings look identical across panes
  and domains.
- `lsr` / `lsrr` are **not** eza — they rank directories by real recent
  activity (newest child mtime); see `doc common/files-disk`.

| Command | What it does |
|---|---|
| `eza -l` | long view |
| `eza -la` | long + hidden |
| `eza -T` / `eza -TL 2` | tree / tree capped at depth 2 |
| `eza -l -s size` / `-s modified` | sort by size / mtime |
| `eza -l -r -s modified` | newest last (reverse any sort) |
| `eza -T --git-ignore` | tree, skipping whatever `.gitignore` skips |
| `eza -lD` | directories only |
| `eza -l --no-permissions --no-user` | trim long-view columns |
| `eza -l --total-size` | recursive dir sizes in the size column (slow) |
