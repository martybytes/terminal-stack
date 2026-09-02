# Omarchy — the stack on Arch + Hyprland

`doc omarchy`. Design rationale lives in `docs/omarchy.md` and
`docs/decisions.md`; this is the day-to-day command sheet.

## Install / update

```bash
curl -fsSL https://raw.githubusercontent.com/martybytes/terminal-stack/main/install-linux.sh | bash
tstack update                   # pull + re-apply the runtime clone
tstack doctor                   # what the stack thinks of this box
```

The installer reads `/etc/os-release` and routes to the pacman half on its own.

```bash
cat /etc/os-release | head -4   # ID=omarchy, ID_LIKE=arch
tstack doctor --repair          # relocate a legacy clone, fix hooks
```

## Theme integration

```bash
tstack omarchy                  # what is installed, and whether it is current
tstack omarchy sync             # install or refresh (every apply does this too)
tstack omarchy off              # remove it, on this machine, and remember
omarchy theme set tokyo-night   # renders the WezTerm colours as a side effect
```

Three files in Omarchy's own extension points, all additive:

| File | Does |
|---|---|
| `~/.config/omarchy/themed/wezterm.lua.tpl` | Omarchy renders it per theme; WezTerm reads the result |
| `~/.config/omarchy/hooks/theme-set.d/terminal-stack` | re-bakes light/dark on a mode flip, nudges WezTerm to reload |
| `~/.config/omarchy/hooks/post-update.d/terminal-stack` | reports pending stack commits during `omarchy update` |

```bash
cat ~/.local/state/omarchy/current/theme/wezterm.lua   # what WezTerm reads
bash ~/.config/omarchy/hooks/theme-set.d/terminal-stack tokyo-night   # run it by hand
```

If WezTerm's colours look stale: touch `~/.wezterm.lua` (it watches its own
config, not the generated theme beside it).

## Who owns what

```bash
pacman -Qo /usr/bin/starship        # Omarchy's, not ours
pacman -Qo "$(command -v wezterm)"  # extra/wezterm
omarchy theme current               # the theme everything else follows
omarchy default terminal            # what Super+Return opens
```

The stack owns `~/.zshrc`, `~/.config/starship.toml`, the WezTerm config and the
`doc`/`ws`/`wso`/`tstack` commands. Omarchy owns the packages, the login shell,
`~/.config/ghostty/config`, the theme, and the language runtimes (mise).

## The shell

**The login shell stays bash here, on purpose.** Omarchy's aliases, functions,
completions and its mise/starship/zoxide/fzf init all hang off `~/.bashrc` →
`$OMARCHY_PATH/default/bash/rc`. `chsh` would take all of that away silently.

```bash
zsh -l                          # the stack's zsh, on demand
getent passwd "$USER" | cut -d: -f7   # confirm it is still bash
```

Do **not** run `sudo chsh -s /usr/bin/zsh`.

The zsh base here is **omarchy-zsh**, not oh-my-zsh -- Omarchy's own package, so
`zsh -l` has the same aliases and functions as the bash the desktop opens. The
stack sources its files directly; do **not** run `omarchy-setup-zsh`, which would
generate a `~/.zshrc` over the one chezmoi owns.

```bash
pacman -Q omarchy-zsh                 # the base
zsh -ic 'print $_TS_OMARCHY_ZSH'      # non-empty when it is loaded
zsh -ic 'whence -w c cy ws doc'       # c/cy are Omarchy's aliases; the rest ours
```

`c` and `cy` are Omarchy's here and not the stack's, deliberately: zsh expands
aliases at parse time, and a function of the same name is a parse error that
abandons the rest of the rc. If `ws`, `doc` or `tstack` ever go missing in zsh,
that is the shape to look for -- run `zsh -ic true` and read the first error.

## tmux

The config is at the XDG path here, not `~/.tmux.conf` — tmux 3.7c prefers
`$XDG_CONFIG_HOME/tmux/tmux.conf` when both exist, so a `~/.tmux.conf` would be
applied and then silently ignored.

```bash
head -3 ~/.config/tmux/tmux.conf     # sources Omarchy's config first
ls ~/.tmux.conf                      # should NOT exist on Omarchy
tmux show-options -g prefix          # what actually took effect
tstack config tmux ctrl-a            # change it, then restart the server
```

Omarchy's own bindings survive: `Alt+Enter` / `Alt+Shift+Enter` split,
`Alt+1..9` switch windows, `Super+/` shows the keybinding popup.

## Packages

Everything comes from pacman. `omarchy pkg add` is the wrapper the stack uses —
it is `pacman -S --needed` plus a check that the package really registered.

```bash
tstack config apps                  # re-pick the CLI tool set
omarchy pkg add <pkg>               # add one by hand
pacman -Q | grep -c .               # what is installed
omarchy update                      # system packages + migrations
```

Six catalog ids are not their own package name: `delta`→`git-delta`,
`gh`→`github-cli`, `tldr`→`tealdeer`, `node`→`nodejs`, `pipx`→`python-pipx`,
`poetry`→`python-poetry`.

## Runtimes: mise, not fnm

`fnm`, `node` and `python` are not offered by the stack here — Omarchy handles
them, and two version managers would fight over PATH order.

```bash
omarchy install dev-env node        # mise use --global node
mise use --global python@latest
mise ls                             # what is pinned
mup                                 # Omarchy alias: MISE_MINIMUM_RELEASE_AGE=0 mise up
```

`uv`, `pipx`, `ruff` and `ipython` are still the stack's to install — they are
tools, not version managers.

## Docker

Omarchy deliberately does **not** put you in the `docker` group: membership is
equivalent to passwordless root. The daemon is socket-activated and reachable
through `sudo`.

```bash
sudo docker info                            # the normal path here
omarchy-setup-security-sudoless-docker      # opt in, behind its warning
systemctl is-active docker.socket
sudo ufw status                             # ufw-docker is installed
```

## Claude Code settings

`~/.claude/settings.json` is a symlink into omarchy-dots here, and three things
write it. The stack splices `statusLine` and `hooks`, cedes `theme` to
`omarchy-theme-set-claude`, and writes through the link rather than replacing it.

```bash
ls -la ~/.claude/settings.json            # should still be a symlink after an apply
jq -r .theme ~/.claude/settings.json      # custom:omarchy, Omarchy's
jq -r .statusLine.command ~/.claude/settings.json   # ours
git -C ~/Workspace/src/github.com/martybytes/omarchy-dots status --short
```

That last one should show the tracked file changing when the stack's hooks
change -- that is the write going through, not around, the link.

## Troubleshooting

```bash
tstack doctor --quiet                       # first stop
chezmoi data | grep -i distro               # distroId should be "omarchy"
chezmoi diff                                # what an apply would change
tstack apply                                # re-render everything
```

| Symptom | Check |
|---|---|
| tmux prefix has no effect | `ls ~/.tmux.conf` — if it exists, it is shadowing the XDG file |
| Omarchy's tmux bindings gone | `grep source-file ~/.config/tmux/tmux.conf` |
| prompt looks wrong after `omarchy theme set` | `tstack config theme follow`, then `tstack apply` |
| a tool "NOT FOUND on PATH" | `pacman -Q <pkg>`; then `tstack config apps` |
| WezTerm ignores `omarchy theme set` | `tstack omarchy status` — is the template `current`? |
| `tstack omarchy sync` says "not ours" | a file of that name exists that the stack did not write; move it aside |
| `docker` permission denied | expected: `sudo docker`, or `omarchy-setup-security-sudoless-docker` |
| `~/.claude/settings.json` is no longer a symlink | the restore hook failed; `tstack apply` again and read its stderr |
| Claude Code theme flapping | the stack should not write `theme` on Omarchy; check `chezmoi data \| grep distroId` |
| `starship` from the wrong place | `command -v starship` must be `/usr/bin/starship`, not `/usr/local/bin` |
