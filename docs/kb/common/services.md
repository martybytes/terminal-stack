# services — the local Docker stacks

Three headline features of this stack are a client talking to a server on
`127.0.0.1`. `ts-stack` drives those servers. Long-form reference lives beside
each compose file in `services/stacks/<name>/README.md`.

## The four stacks

| stack | what you lose without it | ports |
|---|---|---|
| `agentmemory` | agents forget everything between sessions | 3111 proxy, 3110 server, 3113 viewer, 3114 console |
| `headroom` | no prompt compression, no usage dashboard | 8787, 8788, 6333/6334, 7474/7687 |
| `kokoro` | voice notifications go silent | 8880 |
| `playwright` | agents cannot drive a browser | 8931 |

Everything binds `127.0.0.1` only — none of these services authenticate.

## Commands

| | |
|---|---|
| `ts-stack` | one line per stack: state, health, published ports |
| `ts-stack bootstrap` | first run here: `.env` files, generated secrets, volumes |
| `ts-stack up [<stack>]` | start (only the stacks your settings enable) |
| `ts-stack down [<stack>]` | stop. Every volume is kept |
| `ts-stack restart [<stack>]` | down then up, so a changed `.env` is picked up |
| `ts-stack logs <stack> [-n N] [-f]` | tail one stack |
| `ts-stack config [<stack>]` | what compose actually resolves to on this machine |
| `ts-stack doctor` | engine, `.env` files, health, ports, toggle drift |
| `ts-stack test` | take it all down, bring it back up, prove the chain works |
| `ts-stack backup` | cold tar of every data volume, with a manifest |
| `ts-stack --dry-run <verb>` | print the exact docker argv and change nothing |

## Which stacks take part

From the settings you already have: `agentmemoryEnabled`, `headroomEnabled`,
`playwrightEnabled` (`ts-config agents`), and for kokoro the TTS switch plus
`ccTts.engine` (`ts-config tts`). A stack that is off is **skipped and reported
as skipped**, never as broken. One that is off but *running* gets a warning
naming both ways out.

Naming a stack overrides its toggle — `ts-stack up headroom` works with the
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

- **engine down** — `ts-stack doctor` names which runtime it looked for and how
  to start it. In WSL, `docker` may exist and be Docker Desktop's stub, which
  exits 1 for every command; doctor says so rather than guessing.
- **a stack will not start** — `ts-stack config <stack>` first. A missing
  required value fails there, by name.
- **it says "Up" but does not work** — that is what `ts-stack test` is for.
  "Up (healthy)" is not evidence: kokoro reports it while crash-looping on a CUDA
  build that does not match the card.

## What `ts-stack test` actually proves

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
