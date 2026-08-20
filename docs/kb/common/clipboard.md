# Clipboard

| Command | What it does |
|---|---|
| `… \| clipcopy` | pipe anything to the system clipboard (both shells) |
| `catclip <file>` | copy a file's contents to the clipboard |

The zsh version picks the first tool present — `wl-copy` → `xclip` → `clip.exe`
(WSL) → `pbcopy` (macOS) — so the same command works on every box; pwsh uses
`Set-Clipboard`.

```bash
git log -1 --format=%H | clipcopy
catclip ~/.ssh/id_ed25519.pub
```

## Over SSH: OSC 52

The stack's tmux sets `set-clipboard on`, so a copy made **inside a remote tmux**
(copy-mode `y`, or a mouse selection) travels back through the terminal as an
OSC 52 sequence and lands on your **local** clipboard — no X forwarding, no
scp-a-temp-file detour. See `doc common/tmux`. `clipcopy` on a bare remote shell
still needs a local tool, so inside ssh prefer tmux copy-mode or QuickSelect.

## Grab from scrollback

`Ctrl+Shift+Space` — WezTerm QuickSelect hint-labels URLs, paths, git SHAs and
`file:line` refs in the viewport; press the label to copy. See `doc wezterm/panes`.
