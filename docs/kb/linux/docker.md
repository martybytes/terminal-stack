# Linux — Docker

Server-admin runbook. If your user is in the `docker` group none of these need
sudo (`sudo usermod -aG docker $USER`, then log back in).

## Containers
| Command | What it does |
|---|---|
| `docker ps` | running containers (`-a` for stopped too) |
| `docker logs -f name` | follow logs (`--tail 100` to start near the end) |
| `docker exec -it name bash` | shell into a running container (`sh` on alpine) |
| `docker stop\|start\|restart name` | lifecycle |
| `docker stats` | live CPU/mem per container |
| `docker inspect name \| jq '.[0].State'` | config/state as JSON — pick any subtree |
| `docker cp name:/path/file .` | copy a file out (reverse the args to copy in) |
| `docker update --restart unless-stopped name` | make it survive reboots |

## Compose stacks
| Command | What it does |
|---|---|
| `docker compose up -d` | start the stack, detached |
| `docker compose down` | stop and remove containers (named volumes survive) |
| `docker compose pull && docker compose up -d` | update images, recreate what changed |
| `docker compose logs -f svc` | follow one service |
| `docker compose ps` | stack status |

## Disk hygiene
| Command | What it does |
|---|---|
| `docker system df` | what images/containers/volumes cost on disk |
| `docker image prune` | dangling images only (`-a` = all unused — aggressive) |
| `docker system prune` | dangling everything (add `--volumes` with care) |

Restart policies: `no` (default), `on-failure`, `always`, `unless-stopped` —
set at run time (`--restart`) or per-service in compose (`restart:`).

## Install the engine

Docker's own repository, not the distro's `docker.io` package — the latter lags
and its compose plugin is often missing:

```sh
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
```

**The group change does not affect the shell that ran it.** Log out and back in
(or `newgrp docker` for one shell). Until then every docker command fails with
`permission denied while trying to connect`, which is not a stopped daemon and
`ts-stack doctor` says so.

```sh
systemctl is-active docker         # rootful
systemctl --user is-active docker  # rootless
```

## NVIDIA Container Toolkit

Only needed for kokoro's GPU profile. A working `nvidia-smi` on the host proves
nothing about containers — what matters is whether the runtime is registered:

```sh
docker info --format '{{.Runtimes}}'       # must list nvidia
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

Install per NVIDIA's instructions for your distro, then
`sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker`.

See also: `doc services` · `doc troubleshooting`
