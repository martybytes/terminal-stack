# docker-desktop (macOS) — the container engine

The four local services need a container engine. Two reasonable choices.

## Docker Desktop

```sh
brew install --cask docker
open -a Docker
```

## Colima (lighter, no GUI)

```sh
brew install colima docker docker-compose
colima start --cpu 4 --memory 8
```

`ts-stack doctor` resolves which runtime you are on from `docker context ls`
rather than guessing, and tells you the right command to start it — including
OrbStack and Rancher Desktop if that is what you use.

## VM resources

Everything runs inside a Linux VM, so its allocation is the real limit. 4 CPUs
and 8 GB is comfortable for all four stacks; the memory server's first build is
the heaviest moment. Docker Desktop: Settings → Resources. Colima: the flags
above, or `colima stop && colima start --memory 8`.

## There is no GPU step

Docker Desktop for Mac has **no GPU passthrough at all** — not CUDA, not
Metal/MPS. kokoro runs its CPU profile, which is the only correct choice here and
what the setup script selects. It is slower, not broken.

## Bind mounts

Docker Desktop for Mac shares `$HOME`, `/tmp`, `/private` and `/Volumes` by
default. Anything outside those cannot be bind-mounted, which matters for
backups: `ts-stack backup` writes under `$XDG_STATE_HOME` (inside `$HOME`) for
exactly this reason. Override with `TS_STACK_BACKUP_ROOT`, but keep it under
`$HOME` or the tar container cannot see it.

## Can a container reach your LLM host?

Only relevant if you configured an optional LLM endpoint for agentmemory. Host
reachability is **not** container reachability: a container resolves DNS through
Docker's embedded resolver, not your host's, so a name that resolves in your
shell may not resolve in a container.

```sh
docker run --rm curlimages/curl:8.14.1 -sS -o /dev/null -w '%{http_code}' \
  --max-time 8 http://<your-llm-host>:8000/v1/models
```

If the name fails but an IP works, use the IP.

See also: `doc services` · `doc troubleshooting` · `doc brew`
