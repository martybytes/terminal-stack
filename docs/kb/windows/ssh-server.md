# SSH into this PC: PowerShell and Ubuntu

`tstack ssh setup` makes a Windows PC reachable over SSH with a key. It sets up two separate servers:

| Port (default) | Lands in | Server |
|---|---|---|
| `22` | PowerShell (`pwsh`) | Windows OpenSSH (`sshd` service) |
| `2222` | Ubuntu (WSL) | `openssh-server` inside the distro |

```sh
ssh -p 22   you@this-pc      # PowerShell
ssh -p 2222 you@this-pc      # Ubuntu
```

Both ports are yours to change, and the two must differ. The install wizard asks these questions on every Windows install. It recommends turning SSH on when you tick herdr, because a remote herdr session is reached over ssh.

```powershell
tstack ssh                 # status: what is set up, against what is saved
tstack ssh setup           # ask, pick keys, apply (one UAC prompt)
tstack ssh setup --dry-run # the plan, nothing changed
tstack ssh keys            # the keys that may log in
tstack ssh doctor          # key problems: modes, CRLF, agent, passphrases
tstack ssh doctor --fix    # repair them, asking first
```

## What it asks

- **Targets**: both, Windows only, or WSL only.
- **Ports**: 22 and 2222, or numbers you type.
- **Who may connect**:
  - `private`: networks Windows marks Private or Domain.
  - `tailnet`: only Tailscale addresses (100.64.0.0/10, fd7a:115c:a1e0::/48).
  - `lan-tailnet`: both of the above.
  - `any`: every network, including public Wi-Fi.
- **Passwords**: keys only (recommended) or passwords too. Passwords are switched off only **after a key login has been proven** on that port. If none of the keys you authorized is on this PC to test with, you are asked whether to switch them off anyway.
- **Agent sharing**: lets Ubuntu use the Windows ssh-agent, so a key unlocked once works in both. See [The shared agent](#the-shared-agent).
- **Keys**: tick any combination of these sources, and each one is then walked through:
  - **this PC's keys**: the `.pub` files in `~/.ssh`. A key with no passphrase is flagged.
  - **GitHub**: the keys published at `https://github.com/<user>.keys`.
  - **paste a key**: from the computer you will connect from.
  - **make a new pair**: an ed25519 key. ssh-keygen asks for the passphrase. Copy the private half to the other computer.

Keys are only ever added. Ones already authorized stay authorized.

## What it changes

Windows (the admin part, one UAC prompt; `bootstrap/ssh-server.ps1`):

- **OpenSSH Server**: installed if missing. `sshd` and `ssh-agent` are set to Automatic.
- **`C:\ProgramData\ssh\sshd_config`**:
  - A marked block goes at the **top** of the file. sshd keeps the first value it reads, so the block wins without your own lines being edited.
  - **Except `Port`**: every `Port` line is another listener, so your own `Port` lines are commented out, tagged `# terminal-stack disabled:`.
  - The file is backed up first (`.bak.YYYYMMDD`).
  - It is checked with `sshd -t`, and rolled back if that fails.
- **Keys**: written to the file sshd actually reads for you. That is `administrators_authorized_keys` (ACL: SYSTEM and Administrators only) when the stock `Match Group administrators` block is active, otherwise `~\.ssh\authorized_keys`.
- **Login shell**: `HKLM:\SOFTWARE\OpenSSH\DefaultShell` is set to pwsh. Without it you get `cmd.exe`.
- **Firewall**:
  - Rules named `terminal-stack sshd (...)` are created for the chosen scope.
  - Other enabled inbound rules for the same TCP port are **disabled, never deleted**. Otherwise they would widen the scope you picked. This includes the stock `OpenSSH-Server-In-TCP` rule.

WSL:

- **The server**:
  - `openssh-server` is installed in the default distro, as root, through `wsl.exe -u root`, so no sudo password is needed.
  - Its settings go in `/etc/ssh/sshd_config.d/10-terminal-stack.conf`.
  - On Ubuntu 24.04 the port is read by `ssh.socket` at `daemon-reload`, so the socket is restarted too.
  - Keys go to the distro user's `~/.ssh/authorized_keys`, with modes 700 and 600.
- **`networkingMode=mirrored`** in `%USERPROFILE%\.wslconfig`:
  - This puts Ubuntu's sshd on the PC's own address.
  - Only that one line is changed, and a backup is taken.
  - It takes effect after `wsl --shutdown`, which you are asked about because it closes every WSL shell.
- **A Hyper-V firewall rule** (`terminal-stack-sshd-wsl-*`) for the WSL port. Mirrored-mode traffic into WSL is filtered there, not by the ordinary host rules.
- **A logon task, `terminal-stack WSL sshd keep-alive`**: WSL stops a distro once nothing is attached, taking sshd with it. The task runs a hidden `wsl.exe --exec sleep infinity`.

## The shared agent

With agent sharing on (`sshAgentBridge`, the default), Ubuntu uses the **Windows** ssh-agent. The Windows agent keeps the keys you add across reboots, where a Linux agent forgets them at logout. So you type each passphrase once, ever, and the key works on both sides.

- **npiperelay** is installed on Windows (`winget install --id albertony.npiperelay`) and linked into WSL as `~/.local/bin/npiperelay.exe`.
- **socat** is installed in Ubuntu.
- **A systemd user unit, `wsl-ssh-agent-bridge.service`**, has socat listen on `$XDG_RUNTIME_DIR/wsl-ssh-agent.sock` and hand each connection to npiperelay. npiperelay talks to the agent's named pipe.
- **`~/.zshrc`** points `SSH_AUTH_SOCK` at that socket. It wins over Ubuntu's own agent, even when a herdr or tmux server handed the pane the old one. A forwarded `ssh -A` agent still wins over both.
- Ubuntu's own `ssh-agent` is left running, untouched.

Turning agent sharing off and re-running `tstack ssh setup` removes the unit and the link.

```sh
ssh-add -l                                          # in Ubuntu: the Windows agent's keys
systemctl --user status wsl-ssh-agent-bridge        # the relay
```

A shell opened before the bridge existed keeps its old value. Open a new one.

## Key doctor

`tstack ssh doctor` checks the things that make ssh refuse a key or ask for its passphrase again and again. From Windows it checks both Windows and Ubuntu; in WSL or on Linux it checks that machine.

| Check | `--fix` |
|---|---|
| Windows `ssh-agent` service not Running and Automatic | none: `tstack ssh setup` sets it (admin) |
| Windows `~\.ssh` readable by other users | makes it private (`icacls`, no admin) |
| A key named by `IdentityFile` is not in the Windows agent | `ssh-add` it: one passphrase, kept across reboots |
| `AddKeysToAgent` not set in `~/.ssh/config` | none: add `AddKeysToAgent yes` under `Host *` |
| The same `Host` pattern in two blocks (only the first block's values apply) | none: the stack never edits `~/.ssh/config` |
| A private key with no passphrase | `ssh-keygen -p` on it |
| Ubuntu: a private key other users can read, or a `~/.ssh`, `config` or `authorized_keys` others can write | `chmod 600` the keys, `go-w` the rest |
| Ubuntu: Windows line endings in `~/.ssh/config` | strips them, backup taken |
| Ubuntu: the shared agent missing or not answering | sets it up |

`--fix` asks before each repair. `--fix --yes` applies only the ones that ask nothing on the terminal: modes, line endings, permissions and the bridge. The exit code is 0 when nothing is left to warn about.

## The other computer

Point its `~/.ssh/config` at the new ports:

```
Host mypc
    HostName 10.0.0.12          # or this PC's Tailscale address
    User msampson
    Port 22
    IdentityFile ~/.ssh/id_ed25519_mykey

Host mypc-ubuntu
    HostName 10.0.0.12
    User msampson
    Port 2222
    IdentityFile ~/.ssh/id_ed25519_mykey
```

A computer that used another port before (the old 2222 for Windows, for example) needs its config updated.

## Troubleshooting

- **`Bad permissions. Try removing permissions for user: ...CodexSandboxUsers` / `UNPROTECTED PRIVATE KEY FILE`**:
  Windows OpenSSH skips any key that someone other than you, SYSTEM or Administrators
  can open, and the server then answers `Permission denied (publickey)`. Codex's sandbox
  adds a `CodexSandboxUsers` ACE to your profile root, and `~\.ssh` inherits it.
  `tstack doctor` reports it (`ssh-key-acl`) and `tstack doctor --repair` makes `~\.ssh`
  private: inheritance off, then you, SYSTEM and Administrators only. No admin needed. By hand:

  ```powershell
  icacls "$HOME\.ssh" /inheritance:r /grant:r "${env:USERNAME}:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F"
  icacls "$HOME\.ssh\*" /reset /T /C /Q
  ```

  A Codex sandbox session can no longer read your keys after this, which is the point.
- **`Permission denied (publickey)` on port 22, as an admin**: check which keys file is in force (`tstack ssh` shows it). The admin file is ignored unless its ACL is SYSTEM and Administrators only. Setup fixes that ACL.
- **WSL: `ssh.socket` fails with "Address already in use"**: under mirrored networking WSL shares the Windows port space. Something on Windows holds the WSL port, often an older Windows sshd still listening on it. Setup checks this first and names the process.
- **Port 2222 refuses from another computer but works locally**: WSL is not mirrored yet. Run `wsl --shutdown` and reconnect.
- **Port 2222 is dead after a while**: the keep-alive task is not running. Run `schtasks /Run /TN "terminal-stack WSL sshd keep-alive"`.
- **The UAC prompt was declined**: setup prints the exact command to run from an elevated PowerShell.
- **Ubuntu still asks for a passphrase**: run `tstack ssh doctor`. A key ssh refuses for its mode, a key not loaded in the Windows agent, and a shell opened before the bridge existed all look the same from the prompt.
- **`ssh-add -l` in Ubuntu says "Error connecting to agent"**: the Windows `ssh-agent` service is stopped, or the bridge unit is (`systemctl --user restart wsl-ssh-agent-bridge`).
- **Doing it over ssh**: setup warns you. The port can move under you, so the first run belongs on the PC's own console.
