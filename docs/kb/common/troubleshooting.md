# troubleshooting — start here

Keyed by symptom. Every row names a command, because the useful answer is nearly
always state you cannot see from the outside.

**The rule this page follows:** a symptom whose diagnosis needs state you cannot
read — a container's environment, a hook error that was swallowed, which process
owns a socket — is answered by a *command*. A symptom that is a concept or a
choice is answered by a *page*.

## First two commands

```sh
ts-doctor      # the install: clone, chezmoi, shells, hooks, config store
ts-stack doctor # the services: engine, .env files, health, ports, toggle drift
```

Between them they cover everything below. If you only remember one thing,
remember these two.

## No voice

| check | what it means |
|---|---|
| `ts-config tts status` | is TTS on at all, and which engine is selected |
| `ts-stack status` | is `kokoro` running (only matters when the engine is kokoro) |
| `ts-config tts test` | end to end, right now |

The usual causes, in order: TTS is off; the engine is `kokoro` and the container
is not running; the tray daemon is running an older build (`ts-config tts daemon
restart`); or the notification was suppressed as a duplicate. Concepts:
`doc tts`.

## Memories are not being captured

**Do not read logs for this — there are none.** Every vendor hook does
`fetch(...).catch(() => {})` and then `exit(0)`, so a machine wired to a server
that is refusing writes captures nothing and reports nothing.

```sh
ts-stack test                              # writes a probe and reads it back
services/stacks/agentmemory/ts-verify.sh   # the same round trip, on its own
ts-agentmemory --check                     # is the host wiring still in place
```

A plugin upgrade replaces the vendor cache and silently reverts the wiring; both
sync paths repair it, and `ts-doctor` reports it. If the round trip returns 401,
the cached secret is stale — `ts-stack doctor` compares the copies.

## Memories are captured but never summarised, and the dead-letter count climbs

The console's LLM Calls panel shows a large **dead letter** figure, "Observation
compression" glows coral, and the server log repeats

```
warn Failed to parse compression XML {"obsId":"…","retried":true}
```

next to `llm_call … "outcome":"success","providerLatencyMs":0`. Those two lines
together mean the job "succeeded" without any HTTP request happening: with no
usable chat provider AgentMemory produces an empty completion, the XML parse
fails, the job retries once and dead-letters. Storage, search and embeddings are
unaffected throughout, which is why nothing looks broken.

```sh
docker exec ts-agentmemory-server printenv OPENAI_BASE_URL OPENAI_API_KEY
services/stacks/agentmemory/ts-verify.sh    # asks the provider with the container's own credentials
```

Ask **inside** the container. The credential arrives through an optional
`env_file`, and compose says nothing at all when an optional `env_file` path
does not exist, so from outside a container with no key is indistinguishable
from one with a working key.

Two causes, in order: the key never reached the container (empty above), or the
provider refuses it (`401` from the verify). Provider choice and the no-provider
default: `doc agentmemory`.

Clearing a backlog that built up while the provider was broken:

```sh
services/stacks/agentmemory/reconcile-llm-queue.sh            # preview, changes nothing
services/stacks/agentmemory/reconcile-llm-queue.sh --apply    # cold backup, quarantine, one recovery pass
```

`--apply` stops the stack briefly. It never deletes: the old queue store is
moved aside to `/data/queue_store.quarantine-<stamp>` and a full volume backup
is written first.

## Claude is not compressing prompts

```sh
ts-config agents headroom status
```

That runs the authenticated probe and says *why* it failed. The one confusion
worth knowing: `{"error":"unauthorized"}` is headroom refusing your proxy token;
a body naming an API key means the request reached your provider, which is a
different problem. The proxy token is not your provider API key.

## The console is blank, or 3111 is dead

Four ports, and which one answers tells you what is broken:

| port | what it is |
|---|---|
| 3110 | the memory server itself (the bypass) |
| 3111 | the console's transparent proxy — **what every agent is configured to use** |
| 3113 | the stock viewer |
| 3114 | the console UI |

If 3110 answers and 3111 does not, the console is down, not agentmemory.
`ts-stack status` shows all of them. Concepts: `doc agentmemory-console`.

## A port is already in use

```sh
ts-stack status          # names the conflicting listener when it can
```

On Linux/macOS `lsof -nP -iTCP:<port> -sTCP:LISTEN`; on Windows
`Get-NetTCPConnection -State Listen -LocalPort <port>`. Note `lsof` prints
nothing and exits 1 when there is no match, which looks exactly like a typo.
Ports are overridable per machine in each stack's `.env`.

## The container engine is down

```sh
ts-stack doctor
```

It names which runtime it looked for and how to start it, per platform. It never
says "is Docker Desktop running?" when that is not the question.

## `docker` exists in WSL but every command fails

That is Docker Desktop's stub, left on `PATH` when WSL integration is switched
off for this distro. It exits 1 for everything and prints its complaint on
**stdout**, so `command -v docker` is true and useless. Two fixes, either works:

- Docker Desktop → Settings → Resources → WSL Integration → enable this distro
- run `ts-stack` from Windows PowerShell instead

`ts-stack` detects this and re-runs its Windows twin for you when it can.
Details: `doc docker-desktop`.

## A secret was rotated

```sh
ts-doctor        # compares the container's copy against the host's
```

The injected hook wrapper re-reads the authoritative value on a 401 and retries
once, so this normally self-heals. It did not always: a stale value once cost 56
consecutive captures with nothing in any log, which is why the recovery exists.

## Volumes still carry their old names

`ts-stack up` refuses and names one command:

```sh
ts-stack migrate-volumes    # copies, verifies the count, keeps the old volume
```

The refusal is the point — compose would otherwise create an empty replacement
and start the stack with no memories in it, reporting success.

## When a command says something this page does not explain

The stack READMEs are the long-form reference:
`services/stacks/<stack>/README.md`. `doc services` is the command surface,
`docs/decisions.md` is why any of it is shaped the way it is.
