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
