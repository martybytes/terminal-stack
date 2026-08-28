# services — the local Docker stacks

Three headline features of this stack are a client talking to a server on
`127.0.0.1`. `tstack services` drives those servers. Long-form reference lives beside
each compose file in `services/stacks/<name>/README.md`.

> AgentMemory and Headroom both do semantic memory, and exactly one of them runs:
> `tstack config memory agentmemory|headroom|none`. The default is AgentMemory for
> memory and Headroom for compression.

## The stacks

| stack | what you lose without it | ports |
|---|---|---|
| `agentmemory` | agents forget everything between sessions | 3110 server, 3112/3113 viewer |
| `agent007memory` | no console UI, and MCP clients lose the 3111 proxy they are pointed at | 3111 proxy, 3114 console |
| `headroom` | no prompt compression, no usage dashboard | 8787, 8788 (+ 6333/6334, 7474/7687 only with `memoryBackend=headroom`) |
| `kokoro` | voice notifications go silent | 8880 |
| `playwright` | agents cannot drive a browser | 8931 |

`agent007memory` starts after `agentmemory` and joins its network — `tstack services`
orders them, and reversing them by hand fails with "network not found".

Everything binds `127.0.0.1` only — none of these services authenticate.

## Commands

| | |
|---|---|
| `tstack services` | one line per stack: state, health, published ports |
| `tstack services bootstrap` | first run here: `.env` files, generated secrets, volumes |
| `tstack services up [<stack>]` | start (only the stacks your settings enable) |
| `tstack services up <stack> --build` | …rebuilding its image first — for the two stacks built from this repo's own source |
| `tstack services down [<stack>]` | stop. Every volume is kept |
| `tstack services restart [<stack>]` | down then up, so a changed `.env` is picked up |
| `tstack services logs <stack> [-n N] [-f]` | tail one stack |
| `tstack services config [<stack>]` | what compose actually resolves to on this machine |
| `tstack services doctor` | engine, `.env` files, health, ports, toggle drift |
| `tstack services test` | take it all down, bring it back up, prove the chain works |
| `tstack services backup` | cold tar of every data volume, with a manifest |
| `tstack services --dry-run <verb>` | print the exact docker argv and change nothing |

## Which stacks take part

From the settings you already have: `agentmemoryEnabled`, `headroomEnabled`,
`playwrightEnabled` (`tstack config agents`), and for kokoro the TTS switch plus
`ccTts.engine` (`tstack config tts`). A stack that is off is **skipped and reported
as skipped**, never as broken. One that is off but *running* gets a warning
naming both ways out.

Naming a stack overrides its toggle — `tstack services up headroom` works with the
setting off, because asking by name is consent.

## Reading the status line

```
  ok  agentmemory  running (2/2)  3110 3111 3113 3114
  --  headroom     headroomEnabled=off
  !!  kokoro       running, but ccTts.engine=edge
```

`ok` participating and healthy · `--` deliberately not running here · `!!` needs
attention. The third line is intent and reality disagreeing, which is a warning
rather than a failure.

## When something is wrong

`doc troubleshooting` is keyed by symptom. The short version:

- **engine down** — `tstack services doctor` names which runtime it looked for and how
  to start it. In WSL, `docker` may exist and be Docker Desktop's stub, which
  exits 1 for every command; doctor says so rather than guessing, and every verb
  reaches the Windows engine through `docker.exe` instead of failing.

  One case is refused rather than attempted: a clone **inside** the WSL
  filesystem. A Windows engine cannot bind-mount `\\wsl.localhost`, and the
  failure would land after the stack was already down. Keep the clone under a
  Windows drive (the canonical `%LOCALAPPDATA%\terminal-stack\stack` is), or
  enable this distro under Docker Desktop → Settings → Resources → WSL
  Integration.
- **exit codes** — `0` healthy, `1` something is wrong, `2` the command line was
  wrong (unknown verb, unknown stack, `logs` with no stack).
- **a stack will not start** — `tstack services config <stack>` first. A missing
  required value fails there, by name.
- **it says "Up" but does not work** — that is what `tstack services test` is for.
  "Up (healthy)" is not evidence: kokoro reports it while crash-looping on a CUDA
  build that does not match the card.

## What `tstack services test` actually proves

Not just that containers started:

- headroom's token is **enforced** — an unauthenticated `/v1` request is refused
  by the proxy, checked on the response body rather than its status, because a
  refused connection is also non-2xx.
- a memory can be **written and read back** through the console proxy. Every
  vendor hook swallows its errors and exits 0, so a round trip is the only proof
  that capture works.
- kokoro **synthesises audio** and has not restarted.
- every published port still binds `127.0.0.1`. That check never gets skipped.

## Safety

`down`, `restart`, `test` and `reset` destroy no volume. `--destroy-data` takes
headroom's three (the knowledge graph and every vector) after a verified backup
and a typed phrase. `--purge` also takes the two memory volumes — every memory
you have ever saved — which are `external: true` precisely so an ordinary
`down -v` cannot touch them.

See also: `doc agentmemory` · `doc headroom` · `doc troubleshooting` ·
`doc docker-desktop` (Windows/macOS) · `doc docker` (Linux)
