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
- **Agent sharing**: lets Ubuntu use the Windows ssh-agent, so a key unlocked once works in both.
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

- **`Permission denied (publickey)` on port 22, as an admin**: check which keys file is in force (`tstack ssh` shows it). The admin file is ignored unless its ACL is SYSTEM and Administrators only. Setup fixes that ACL.
- **WSL: `ssh.socket` fails with "Address already in use"**: under mirrored networking WSL shares the Windows port space. Something on Windows holds the WSL port, often an older Windows sshd still listening on it. Setup checks this first and names the process.
- **Port 2222 refuses from another computer but works locally**: WSL is not mirrored yet. Run `wsl --shutdown` and reconnect.
- **Port 2222 is dead after a while**: the keep-alive task is not running. Run `schtasks /Run /TN "terminal-stack WSL sshd keep-alive"`.
- **The UAC prompt was declined**: setup prints the exact command to run from an elevated PowerShell.
- **Doing it over ssh**: setup warns you. The port can move under you, so the first run belongs on the PC's own console.
