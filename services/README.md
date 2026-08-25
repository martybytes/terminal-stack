# The local services

Three of terminal-stack's headline features are not shell configuration — they
are a client talking to a server on `127.0.0.1`. Those servers live here.

| stack | what you lose without it | ports |
|---|---|---|
| **`agentmemory`** | agents forget everything between sessions | 3111 proxy, 3110 server, 3112 events, 3113 viewer, 3114 console |
| **`headroom`** | no prompt compression, no usage dashboard | 8787 proxy, 8788 dashboard, 6333/6334 Qdrant, 7474/7687 Neo4j |
| **`kokoro`** | voice notifications go silent | 8880 |
| **`playwright`** | agents cannot drive a browser | 8931 |

Plus `console/` — the source of the agentmemory console, a transparent proxy and
UI in front of the memory server, built from this tree by the agentmemory stack.

**Everything binds `127.0.0.1` only.** None of these services authenticate, so
none of them is reachable from your network. That is deliberate and enforced:
`ts-stack test` audits every published port and never skips that check.

## What needs no configuration

The default install needs **no API key and no LLM host**. agentmemory embeds
on-device (`EMBEDDING_PROVIDER=local`), so capture, keyword search and vector
search all work offline. What an optional LLM adds is the *derived* layer:
change-aware summaries, incremental knowledge-graph extraction, and daily
consolidation. See `stacks/agentmemory/README.md` for how to point it at an
endpoint you host, or at the OpenAI API, if you want that.


## Two per-stack files, discovered by name

Neither is registered anywhere; a stack has them or it does not.

| file | what it does |
|---|---|
| `ts-after` | stack names this one starts after, and stops before. `agent007memory` sorts *before* `agentmemory` (`0` < `m`) while joining a network `agentmemory` creates, and an external network cannot be joined before it exists |
| `ts-envfiles` | extra `--env-file` paths, applied before this stack's own `.env`. Compose **interpolation** sources only -- they inject nothing into a container, which is what keeps `OPENAI_API_KEY` out of the console while it still displays the model AgentMemory is configured for |
| `ts-checks.<x>.conf` | health checks for the `docker-compose.<x>.yml` overlay of the same name, loaded only when that overlay is selected |

That last one exists because headroom's Qdrant and Neo4j checks used to live in
the base file, where they passed on every machine and proved nothing: the proxy
had never once contacted either datastore. See `doc headroom`.
## Quick start

```sh
ts-stack bootstrap     # seeds every .env, generates headroom's two secrets,
                       # creates the external volumes
ts-stack up            # start the stacks your settings enable
ts-stack test          # take it all down, bring it back up, prove it works
```

You need a container engine first: `doc docker-desktop` on Windows or macOS,
`doc docker` on Linux. `ts-stack doctor` tells you which one it found, whether it
is answering, and what to do when it is not.

## Day to day

```sh
ts-stack                       # one line per stack: state, health, ports
ts-stack up | down | restart   # optionally: ts-stack restart headroom
ts-stack logs headroom -n 100 -f
ts-stack config kokoro         # what compose actually resolves to here
ts-stack doctor                # engine, .env files, health, ports, toggle drift
ts-stack backup                # cold tar of every data volume, with a manifest
ts-stack --dry-run up          # the exact docker argv, without running it
```

Nothing here wraps or hides Docker. The compose files are ordinary files you can
run by hand from a stack directory; `ts-stack` exists so that the argv is
consistent, the env-file order is right, and `-v` can never reach a `down`.

## Which stacks run here

From the saved settings you already have — `agentmemoryEnabled`,
`headroomEnabled`, `playwrightEnabled`, and for kokoro the TTS switch plus
`ccTts.engine`. A stack whose setting is off is *skipped and reported as
skipped*, never as broken. One that is off but running gets a warning naming both
ways out, because intent and reality disagreeing is exactly what a doctor is for.

Naming a stack explicitly overrides its toggle: `ts-stack up headroom` works with
the setting off, because asking by name is consent.

## Per-machine differences

Everything machine-specific lives in a gitignored `.env` beside each stack's
tracked `.env.example`:

| stack | what varies |
|---|---|
| `agentmemory` | the optional LLM provider, prompt bounds |
| `agent007memory` | normally empty: it reads the agentmemory stack's `.env` for display values through `ts-envfiles` |
| `headroom` | the two generated secrets, ports, Neo4j heap and page cache |
| `kokoro` | the hardware profile: which image, and whether the GPU overlay merges |

A stack that ships a `.env.example` and has no `.env` is **mis**-configured, not
unconfigured: compose falls back to the base file alone, which for kokoro means
starting the GPU image with no GPU. `ts-stack doctor` reports it.

## Secrets

There are no secrets in this repository, and there never will be. headroom's
`HEADROOM_PROXY_TOKEN` and `NEO4J_PASSWORD` are generated on this machine by
`ts-stack bootstrap` and written only to the gitignored `.env`; agentmemory
generates its HMAC inside the container on first boot and every host reads it
from there. Neither is ever printed — only a fingerprint, because a value echoed
to a terminal lives in scrollback.

## Naming

Everything this tree creates is prefixed `ts-`, so it is obvious in `docker ps`
which containers belong to terminal-stack and which are your own work:

```
ts-agentmemory     ts-agentmemory-server
ts-agent007memory  ts-agent007memory
ts-headroom      ts-headroom-proxy, -dashboard, -qdrant, -neo4j
ts-kokoro        ts-kokoro-tts
ts-playwright    ts-playwright-mcp
```

Volumes follow the same rule. If yours still carry the older names, `ts-stack up`
will refuse to start and name the one command that fixes it — because compose
would otherwise create an empty replacement and start the stack with no memories
in it, reporting success.

## Adding a stack

Drop a directory under `stacks/` with a `docker-compose.yml`. There is nothing to
register: `ts-stack` finds it, and adding `ts-checks.conf` and `ts-verify.sh`
enrols it in `ts-stack test`. The rules and the checklist are in
`docs/service-conventions.md`.
