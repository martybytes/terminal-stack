# Zed (GUI editor)

Fast GPU-accelerated editor. **Optional** in the app catalog on every platform —
opt in via `tstack config apps` (WSL/Linux/macOS) or `Set-TerminalStackConfig`
(Windows; winget id `ZedIndustries.Zed`, brew cask `zed`). Install the `zed` CLI from
Zed's menu (Zed → Install CLI), then drive it from the terminal.

## Launch
| Command | What |
|---|---|
| `zed path...` | open file(s) or a directory |
| `zed .` | open the current directory as a project |
| `zed file:42` | open at line 42 |
| `zed file:42:10` | open at line 42, column 10 |
| `zed -n .` | new window |
| `zed -w file` | wait for the file to close (good as `$EDITOR` / for git) |
| `zed --add .` | add to the current workspace |
| `zed --help` | full options |

## Everyday shortcuts (`Cmd` on macOS, `Ctrl` elsewhere)
| Key | What |
|---|---|
| `Cmd/Ctrl-Shift-P` | command palette |
| `Cmd/Ctrl-P` | go to file |
| `Cmd/Ctrl-S` | save |
| `Cmd/Ctrl-Shift-F` | find in project |
| `Cmd/Ctrl-,` | settings |
| `Cmd/Ctrl-D` | add a cursor at the next occurrence |
| `Cmd/Ctrl-Shift-K` | delete line |
| `Cmd/Ctrl-/` | toggle comment |

Vim mode (enable in settings): `:w` `:q` `:qa` and the usual motions work.
