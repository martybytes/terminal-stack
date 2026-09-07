# git

## Shell shortcuts (typed bare)
zsh aliases / pwsh functions. `gp`/`gl` are stack overrides — plain oh-my-zsh
makes `gp` *push* and `gl` *pull*; here they always mean pull / log.

| Shortcut | Full command | Note |
|---|---|---|
| `gst` | `git status` | it's `gst`, not `gs` (gs = Ghostscript) |
| `gp` | `git pull` | always PULL |
| `gl` | `git log --oneline --graph --decorate -10` | always LOG |
| `gco` | `git checkout` | |
| `gf` | `git fetch` | |
| `gd` | `git diff` | |
| `ga` | `git add` | |
| `gb` | `git branch` | |
| `gcm` | `git checkout <main branch>` | zsh; figures out main vs master |

## git-config aliases (`git <alias>`, from the stack's gitconfig include)
| Alias | Full command |
|---|---|
| `git st` | `git status` |
| `git lg` | `git log --oneline --graph --decorate -10` |
| `git lga` | `git log --oneline --graph --decorate --all` |
| `git br` | `git branch` |
| `git co` | `git checkout` |
| `git cm` | `git commit` |

`git diff` pages through **delta** (side-by-side, syntax-highlighted) — wired by
the same include at `~/.config/git/terminal-stack.gitconfig`.

## ssh on Windows

git is pinned to Windows' native OpenSSH (`core.sshCommand`) by the stack's
gitconfig. Without it git uses Git for Windows' bundled MSYS ssh, which cannot
reach the agent's named pipe and asks for the key passphrase on every command.
`tstack doctor` reports it as `git-ssh-command`; details in `doc ssh-config`.
