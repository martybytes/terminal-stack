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
| `starship` from the wrong place | `command -v starship` must be `/usr/bin/starship`, not `/usr/local/bin` |
