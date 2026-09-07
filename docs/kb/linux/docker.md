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
`tstack services doctor` says so.

```sh
systemctl is-active docker         # rootful
systemctl --user is-active docker  # rootless
```

## Reaching the daemon without the docker group (Omarchy)

Omarchy leaves the install user **out of** the `docker` group on purpose:
membership is root-equivalent, because a container can bind-mount `/` and rewrite
the host as root. So a bare `docker` is `permission denied`, and Omarchy reaches
the daemon through a **pkexec prompt** instead (`omarchy-launch-docker-tui` asks
`omarchy-sudo-docker` which way to go). There is no passwordless polkit rule.

That leaves three ways in, and only the third needs no elevation at all:

| | Cost |
|---|---|
| `omarchy-setup-security-sudoless-docker` | the group, i.e. root-equivalent |
| `sudo docker` | a password, every 15 minutes |
| **rootless Docker** | a second daemon, and a second set of images and volumes |

**Rootless** gives this user their own daemon on a socket they own, and leaves the
system one running for Lazydocker and anything else that wants it. On Arch the
`docker` package ships no rootless files — they are AUR:

```sh
yay -S docker-rootless-extras                 # pulls rootlesskit from extra
sudo pacman -S slirp4netns fuse-overlayfs     # the recommended optional deps
systemctl --user enable --now docker.socket   # socket at $XDG_RUNTIME_DIR/docker.sock
sudo loginctl enable-linger "$USER"           # survives logout
docker context create rootless --docker "host=unix://$XDG_RUNTIME_DIR/docker.sock"
docker context use rootless
```

The Arch package ships the systemd **user** units itself, so
`dockerd-rootless-setuptool.sh` is neither present nor needed — nothing has to be
`--force`d past the running system socket. `/etc/subuid` and `/etc/subgid` are
usually already populated; check with `grep "^$USER:" /etc/subuid /etc/subgid`.

**Use the context, not `DOCKER_HOST`.** The context lives in
`~/.docker/config.json`, so every shell and every non-interactive agent run picks
it up with no shell or `environment.d` config at all. Exporting `DOCKER_HOST` for
the whole session instead would drag Omarchy's Lazydocker onto the rootless
daemon, where it would see none of the rootful containers.

```sh
docker info | grep -i rootless        # "rootless" in the security options
docker context ls                     # rootless is current
systemctl is-active docker.socket     # the SYSTEM one, still running
id -nG                                # still no docker group
docker context use default            # the way back
```

**Two engines means two sets of images and volumes.** Anything already built or
stored under `/var/lib/docker` is invisible from the rootless daemon
(`~/.local/share/docker`) and vice versa. Move a named volume across with:

```sh
docker volume create <name>
sudo docker run --rm -v <name>:/from alpine tar cf - -C /from . \
  | docker run --rm -i -v <name>:/to alpine tar xf - -C /to
```

Rootless limits worth knowing: no true `--privileged`, `--net=host` is the
namespace's host and not the machine's, binding ports below 1024 needs
`net.ipv4.ip_unprivileged_port_start`, and bind-mounted files are UID-remapped.
`tests/parity/run.sh` needs none of those, which is why it works rootless
unchanged.

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
