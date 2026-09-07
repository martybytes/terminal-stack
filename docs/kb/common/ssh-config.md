# SSH client config (`~/.ssh/config`)

Define per-host shortcuts so `ssh orion` just works.

```sshconfig
# Per-host block
Host orion
    HostName 192.168.1.50
    User marty
    Port 22
    IdentityFile ~/.ssh/id_orion
    IdentitiesOnly yes

# Wildcards + global defaults (most specific wins; put Host * LAST)
Host *
    ServerAliveInterval 60      # keepalive ping every 60s
    ServerAliveCountMax 3
    AddKeysToAgent yes
    IdentitiesOnly yes          # only offer the IdentityFile(s) named above
```

```bash
chmod 600 ~/.ssh/config
```

## Jump host (bastion)

```sshconfig
Host internal-box
    HostName 10.0.0.9
    User marty
    ProxyJump bastion.example.com
```

## Useful one-offs

```bash
ssh -v orion                    # verbose: see which key is offered
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_orion marty@host   # force one key, ignore agent
ssh-keygen -R orion             # drop a stale known_hosts entry after a rebuild
```

## The agent is missing inside a multiplexer, and only there

The give-away is the mirror of the Windows one below: `ssh` works in a plain
terminal and fails in every herdr (or tmux, or wezterm-mux) pane, while
`ssh-add -l` from that terminal lists your keys the whole time.

```bash
echo "$SSH_AUTH_SOCK"                    # empty, or a path that no longer exists
ls -l "${XDG_RUNTIME_DIR}/ssh-agent.socket"   # the real one, still there
systemctl --user status ssh-agent.socket
```

A multiplexer **server** captures its environment once, when it starts, and
hands that same copy to every pane it will ever spawn. `environment.d(5)` is read
by the systemd user manager before it starts anything, so it reaches services
started *after* that — and never reaches a server that was already running. Add
`SSH_AUTH_SOCK` there today and a server started yesterday still hands out
shells without it, indefinitely, with nothing to see.

The socket path is stable, so the shell rc recomputes it: `dot_zshrc` exports
`$XDG_RUNTIME_DIR/ssh-agent.socket` when `SSH_AUTH_SOCK` is unset **or points at
a socket that is gone**, and leaves any live value alone so a forwarded `ssh -A`
agent still wins. Because the fix is in the shell and not the server, **every new
pane is already correct** — no server restart, nothing to detach.

An already-open pane keeps the environment it started with. Fix that one in
place, or just open a new one:

```bash
export SSH_AUTH_SOCK="${XDG_RUNTIME_DIR}/ssh-agent.socket"
```

Interactive shells only, on purpose — `ssh host 'cmd'` runs a non-interactive
shell and still has no agent. Use `ssh host -t`.

## The agent on Windows is a pipe, not a socket

Windows OpenSSH reaches its agent over the named pipe `\\.\pipe\openssh-ssh-agent`,
served by the **OpenSSH Authentication Agent** service. There is no socket file
and no `ssh-agent -s` to eval.

```powershell
Get-Service ssh-agent                 # Automatic + Running is what you want
ssh-add -l                            # list loaded keys
ssh-add $HOME\.ssh\id_ed25519      # load one (AddKeysToAgent yes does this on first use)
```

`ssh` and `ssh-add` still honour **`SSH_AUTH_SOCK` ahead of that pipe** whenever
the variable is set, so anything that points it at a filesystem path — a terminal
emulator forwarding an agent, a leftover WSL/Git-Bash line, an empty value in the
registry — breaks every ssh in that shell while the service stays healthy. The
symptom and the fix: `doc troubleshooting`.

So on Windows: do not `eval $(ssh-agent -s)`, and do not set `SSH_AUTH_SOCK` to a
path. If something else insists on setting it, set it to the pipe above — Win32
OpenSSH accepts a pipe path there.

`IdentityAgent` in this file is the same trap wearing a different hat: it
overrides the pipe per-host. Leave it unset unless you are deliberately routing
through 1Password, KeeAgent or Pageant.
