# yazi (terminal file manager)

Fast, async file manager with previews. In the catalog's `editors` group,
**optional** — it is a TUI app you open, not a shell primitive.

## How this stack wires it

- **`y`, not `yazi`.** Both shells define a `y` wrapper that runs yazi with
  `--cwd-file` and then `cd`s the *parent* shell to wherever you exited. A child
  process cannot change its parent's directory, so without the wrapper yazi is
  a viewer rather than a navigator. This is upstream's own recommended shim.
- **Installed from brew (macOS) or winget `sxyazi.yazi` (Windows).** Debian and
  Ubuntu carry no package, so Linux falls back to the GitHub release — note it
  ships a **`.zip`** and **two** binaries: `yazi` (the TUI) and `ya` (its CLI,
  needed for plugin management). Both are fetched.

## Keys worth knowing

| Key | Does |
|---|---|
| `q` | quit (and `cd` there, via `y`) |
| `Q` | quit **without** changing directory |
| `h` / `j` / `k` / `l` | navigate (vim-style) |
| `Space` | select; `v` enters visual select |
| `y` / `x` / `p` | yank / cut / paste |
| `d` | trash; `D` permanently delete |
| `a` | create file (`dir/` creates a directory) |
| `r` | rename; `.` toggles hidden files |
| `/` / `?` | search forward / back; `s` searches by content (needs `rg`) |
| `z` | jump with zoxide; `Z` jump with fzf |
| `Tab` | toggle the preview pane |

`z` and `Z` reuse zoxide and fzf, which the stack already installs.

See also `doc common/tools/zoxide`, `doc common/tools/fzf`.
