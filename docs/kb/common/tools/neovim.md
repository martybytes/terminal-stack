# Neovim (nvim)

Modal editor. In the app catalog as a **recommended** install — `tstack config apps`
(zsh) / `Set-TerminalStackConfig` (pwsh); winget id `Neovim.Neovim`. The stack's
`$EDITOR` stays `micro`, so run `nvim` explicitly — to make git, `doc edit` and
friends use it instead, set `EDITOR` in `~/.zshrc.local` / `profile.local.ps1`.
WezTerm tabs show a vim glyph while nvim is the pane's foreground process.

## Launch
| Command | What |
|---|---|
| `nvim file` | open file(s) |
| `nvim .` | open the current directory (file explorer) |
| `nvim +42 file` | open at line 42 |
| `nvim +/term file` | open and search for `term` |
| `nvim -u NONE file` | clean — no config |

## Everyday (Normal mode unless noted)
| Key | What |
|---|---|
| `i` / `Esc` | insert mode / back to Normal |
| `:w` `:q` `:wq` `:q!` `:qa!` | save / quit / save+quit / force-quit / quit-all |
| `dd` / `yy` / `p` | delete line / yank line / paste |
| `u` / `Ctrl-r` | undo / redo |

## Move & search
| Key | What |
|---|---|
| `h` `j` `k` `l` | left / down / up / right |
| `w` `b` `e` | word forward / back / end |
| `gg` / `G` | top / bottom of file |
| `Ctrl-u` / `Ctrl-d` | half-page up / down |
| `/text` `?text` `n` `N` | search forward / back / next / prev |
| `:%s/old/new/g` | replace all in the file (`/gc` to confirm each) |

## Windows & buffers
| Key | What |
|---|---|
| `:sp` / `:vsp` | horizontal / vertical split |
| `Ctrl-w h/j/k/l` | move between splits |
| `:ls` / `:b N` / `:bd` | list / switch to / delete a buffer |
