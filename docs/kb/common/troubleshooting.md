# troubleshooting — start here

Keyed by symptom. Every row names a command, because the useful answer is nearly
always state you cannot see from the outside.

**The rule this page follows:** a symptom whose diagnosis needs state you cannot
read — a container's environment, a hook error that was swallowed, which process
owns a socket — is answered by a *command*. A symptom that is a concept or a
choice is answered by a *page*.

## First two commands

```sh
tstack doctor      # the install: clone, chezmoi, shells, hooks, config store
tstack services doctor # the services: engine, .env files, health, ports, toggle drift
```

Between them they cover everything below. If you only remember one thing,
remember these two.

## No voice

| check | what it means |
|---|---|
| `tstack config tts show` | is TTS on at all, and which engine is selected |
| `tstack services status` | is `kokoro` running (only matters when the engine is kokoro) |
| `tstack config tts test` | end to end, right now |

The usual causes, in order: TTS is off; the engine is `kokoro` and the container
is not running; the tray daemon is running an older build (`tstack config tts daemon
restart`); or the notification was suppressed as a duplicate. Concepts:
`doc tts`.

## Memories are not being captured

**Do not read logs for this — there are none.** Every vendor hook does
`fetch(...).catch(() => {})` and then `exit(0)`, so a machine wired to a server
that is refusing writes captures nothing and reports nothing.

```sh
tstack services test                              # writes a probe and reads it back
services/stacks/agentmemory/ts-verify.sh   # the same round trip, on its own
tstack agentmemory --check                     # is the host wiring still in place
```

A plugin upgrade replaces the vendor cache and silently reverts the wiring; both
sync paths repair it, and `tstack doctor` reports it. If the round trip returns 401,
the cached secret is stale — `tstack services doctor` compares the copies.

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

## The console says "UPSTREAM OFFLINE"

It means one thing: the console could not reach AgentMemory's
`/agentmemory/livez` within its 3-second budget. That is the console-to-server
hop *inside Docker*. It says nothing about your LLM provider, and nothing about
Headroom.

```sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3110/agentmemory/livez   # the server itself
docker exec ts-agent007memory sh -c 'wget -qO- "$UPSTREAM_HTTP/agentmemory/livez"'  # as the console sees it
```

If 3110 answers and the console cannot reach it, the two are not on the same
network. If neither answers, the server is down or still starting. A brief flap
during `tstack services restart` is expected.

## The LLM queue depth is large and the wait is minutes

Look at the trend, not the number. `Queue wait` is the age of the **oldest item
still waiting**, not how long new work waits, so it falls as a backlog clears.

```sh
curl -s http://127.0.0.1:3114/api/llm | python -c "import json,sys; print(json.load(sys.stdin)['queue'])"
```

`depth` falling over a minute or two is a backlog draining and needs nothing.
`depth` flat with `dlqDepth` climbing is the real failure — see the compression
section above. Throughput is bounded by the worker count times the provider's
latency, so a local 8B model at several seconds a call is a few jobs a minute
however deep the queue is.

## Claude is not compressing prompts

```sh
tstack config agents headroom status
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
`tstack services status` shows all of them. Concepts: `doc agentmemory-console`.

## `ssh` / `git push` says "Error connecting to agent" (Windows, WezTerm)

The give-away is that **the same command works in cmd.exe or Windows Terminal**
and fails in every WezTerm pane, however many times you restart the service.

| check | what it means |
|---|---|
| `$env:SSH_AUTH_SOCK` **from the failing pane** | must be `\\.\pipe\openssh-ssh-agent`. A `...\wezterm\agent.<pid>` path, or an empty value, is the bug |
| `[System.IO.Directory]::GetFiles('\\.\pipe\') -match 'openssh'` | the agent's pipe exists — if it does, the service is not your problem |
| `Get-Service ssh-agent` | Running is necessary, and tells you almost nothing on its own |
| `Get-Command ssh-add -All` | System32's OpenSSH should win over Git for Windows' `usr/bin` copy |

Windows OpenSSH reaches its agent over a **named pipe**, but honours
`SSH_AUTH_SOCK` ahead of it whenever that variable is set — so anything that sets
it to a filesystem path breaks every ssh in that shell while the agent stays
perfectly healthy. WezTerm did exactly that by default. The stack pins the
variable to the pipe in `~/.wezterm.lua`; if a pane disagrees, it is running an
older config — restart WezTerm (a new tab is not enough) after `tstack update`.

**Never fix this by setting `SSH_AUTH_SOCK` to a socket path or starting a Unix
`ssh-agent`** — neither can serve Windows OpenSSH. Concepts: `doc ssh-config`.

## A port is already in use

```sh
tstack services status          # names the conflicting listener when it can
```

On Linux/macOS `lsof -nP -iTCP:<port> -sTCP:LISTEN`; on Windows
`Get-NetTCPConnection -State Listen -LocalPort <port>`. Note `lsof` prints
nothing and exits 1 when there is no match, which looks exactly like a typo.
Ports are overridable per machine in each stack's `.env`.

## The container engine is down

```sh
tstack services doctor
```

It names which runtime it looked for and how to start it, per platform. It never
says "is Docker Desktop running?" when that is not the question.

## `docker` exists in WSL but every command fails

That is Docker Desktop's stub, left on `PATH` when WSL integration is switched
off for this distro. It exits 1 for everything and prints its complaint on
**stdout**, so `command -v docker` is true and useless. Two fixes, either works:

- Docker Desktop → Settings → Resources → WSL Integration → enable this distro
- run `tstack services` from Windows PowerShell instead

`tstack services` detects this and re-runs its Windows twin for you when it can.
Details: `doc docker-desktop`.

## A secret was rotated

```sh
tstack doctor        # compares the container's copy against the host's
```

The injected hook wrapper re-reads the authoritative value on a 401 and retries
once, so this normally self-heals. It did not always: a stale value once cost 56
consecutive captures with nothing in any log, which is why the recovery exists.

## Volumes still carry their old names

`tstack services up` refuses and names one command:

```sh
tstack services migrate-volumes    # copies, verifies the count, keeps the old volume
```

The refusal is the point — compose would otherwise create an empty replacement
and start the stack with no memories in it, reporting success.

## When a command says something this page does not explain

The stack READMEs are the long-form reference:
`services/stacks/<stack>/README.md`. `doc services` is the command surface,
`docs/decisions.md` is why any of it is shaped the way it is.
