# docker-desktop (Windows) — the container engine

The four local services need a container engine. On Windows that is Docker
Desktop with the WSL 2 backend.

## Install

```powershell
winget install --id Docker.DockerDesktop --exact
```

> The stack can install it for you: `docker` is a row in the app catalog (`tstack config apps`), offered but never pre-ticked, because an engine install means a reboot and licence terms.

Then start it once from the Start menu and let it finish initialising. The stack
never starts it without asking: launching a multi-gigabyte GUI application because you
typed `tstack services status` is not acceptable. `tstack services up --start-engine` does it
when you ask, on Windows and from WSL alike, and `tstack agents headroom on` (what
the installer runs when you pick Headroom) asks first and waits up to two minutes
for it. Neither ever installs Docker Desktop.

## WSL integration — the setting that causes "docker is broken in WSL"

**Settings → Resources → WSL Integration → enable your distro.**

With it off, `docker` still exists inside WSL — as Docker Desktop's stub. It
exits 1 for every command and prints

```
The command 'docker' could not be found in this WSL 2 distro.
```

on **stdout**, so `command -v docker` succeeds and tells you nothing. Anything
that treats that as "the engine is down" is giving you the wrong answer: the
engine may be perfectly healthy on the Windows side.

`tstack services` detects this specifically. For anything that changes state it re-runs
its Windows twin over interop rather than proxying `docker.exe`, because compose
resolves `-f`, build contexts and bind mounts as *Windows* paths, and a
`\wsl.localhost` share is not reliably bind-mountable — a failure that would
land after your stack was already stopped.

### After a Docker Desktop upgrade: "waiting 1m0s for the backend socket"

```
WSL integration with distro 'Ubuntu' unexpectedly stopped. Do you want to restart it?
running wsl distro proxy in Ubuntu distro: waiting 1m0s for the backend socket
... test -s /mnt/wsl/docker-desktop/shared-sockets/host-services/backend.sock: exit status 1
```

`docker` on Windows works and containers run; inside WSL docker is gone. The
shared directory under `/mnt/wsl` belongs to the **WSL utility VM**, not to Docker
Desktop. The upgrade restarts Docker's backend but the VM keeps running, so the
new backend never republishes `backend.sock` into the old VM. **The dialog's
Restart button only re-runs the one-minute wait and fails the same way**, and so
does `docker desktop restart`. The fix is a fresh VM:

```powershell
tstack services repair            # from PowerShell, never from WSL
tstack services repair --update   # before updating: pauses while you click "Update version"
```

It snapshots the running containers, then `docker desktop stop` →
`wsl --shutdown` → `docker desktop start`, waits for the engine, checks `docker`
**inside** each integrated distro, recycles once more if that failed, runs
`hello-world`, and starts any container that was running before and did not come
back. It asks first (`-y` skips that): `wsl --shutdown` closes every WSL terminal.
Afterwards, close a leftover dialog with its X, and reconnect agents' container
MCP servers (`/mcp` in Claude Code).

`tstack doctor` fails `docker-integration` while this is happening, and when the
installer starts Docker for you it checks for it and offers the repair
(default no). Both only ask a distro that is already running: with every
integrated distro stopped the shared directory is empty by design, and that is
not reported.

The repair also checks the one other post-upgrade fault: the elevated installer
can recreate the Docker WSL disk owned by `Administrators` (common when
`%LOCALAPPDATA%\Docker\wsl` is a junction to another drive), and the engine then
never starts (`MountDisk/HCS/E_ACCESSDENIED`, shown as a misleading
"vpnkit-bridge ... bad magic string"). It prints the two `icacls` lines to run
from an **elevated** PowerShell and waits; it never elevates itself.

**Never** reset to factory defaults or `wsl --unregister docker-desktop` for
this: both destroy every image and volume, and neither fixes it.

Then check that the stacks came back from the right clone. On a combined
Windows + WSL machine only one clone holds the AgentMemory LLM settings;
`tstack services up` refuses to recreate a stack another clone started, and
names the one to run it from.

## Resources

Settings → Resources. The whole set of stacks is comfortable in 8 GB; headroom's
Neo4j alone will take what you give it unless bounded, and it is bounded in
`services/stacks/headroom/.env` (`NEO4J_HEAP`, `NEO4J_PAGECACHE`).

Docker Desktop's WSL backend grows its VM disk on demand and does not shrink it.
`%LOCALAPPDATA%\Docker\wsl` is where that lives.

## GPU (optional, kokoro only)

Docker Desktop passes NVIDIA GPUs through the WSL 2 backend with a current
driver; nothing extra to install on Windows. Verify:

```powershell
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

On an RTX 50-series (Blackwell) card kokoro needs the `cu128` image. `:latest` is
`cu126`, which starts happily and then crash-loops on the first synthesis —
`tstack services test` catches that by checking the restart count, not just health.

## Autostart

Docker Desktop can start with Windows (Settings → General). If you leave it off,
`tstack services status` will tell you the engine is unreachable rather than looking
broken.

See also: `doc services` · `doc troubleshooting`
