# docker-desktop (Windows) — the container engine

The four local services need a container engine. On Windows that is Docker
Desktop with the WSL 2 backend.

## Install

```powershell
winget install --id Docker.DockerDesktop --exact
```

Then start it once from the Start menu and let it finish initialising. The stack
never starts it for you: launching a multi-gigabyte GUI application because you
typed `tstack services status` is not acceptable. `tstack services up --start-engine` does it
when you ask.

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
