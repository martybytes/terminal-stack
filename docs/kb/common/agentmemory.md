# agentmemory — memory for Claude, Codex and Cursor

What gets captured, how each agent retrieves it, and what to run when it stops.
Long-form reference: `services/stacks/agentmemory/README.md`.

> Only one memory backend runs on a machine. `ts-config memory status` says which,
> and `ts-config memory headroom` swaps AgentMemory out for Headroom's own store.

## The shape

```
your agent  ->  127.0.0.1:3111/_agent/<host>   the console's transparent proxy
                        |
                        v
                127.0.0.1:3110                 the memory server itself
```

Every agent is pointed at **3111**, not 3110: the console proxies the traffic so
it can show you what happened. 3110 is the bypass, and it is the first thing to
check when 3111 is dead — see `doc agentmemory-console`.

The URL is tagged per host (`/_agent/claude`, `/_agent/codex`,
`/_agent/cursor`), which is how the console attributes a memory to the agent that
made it.

## Who wires what

| | |
|---|---|
| the server, its image, the compose file | `services/stacks/agentmemory/`, driven by `ts-stack` |
| which hooks each agent registers, what they run, the environment they carry | `bootstrap/ts-agentmemory.{sh,ps1}`, driven by `ts-update` and `chezmoi apply` |

Both halves ship in this repo, but the split is deliberate: the wiring edits
`~/.claude`, `~/.codex` and `~/.cursor`, which are host files, so it lives
outside `services/`.

## Turning it on

```sh
ts-config agents agentmemory on    # the saved setting, this machine only
ts-stack up agentmemory            # the server
ts-agentmemory --check             # is the host wiring in place
```

## Capture is invisible when it breaks

Every vendor hook does `fetch(...).catch(() => {})` and then `exit(0)`. That is
deliberate — a memory server being down must never break your agent — but it
means **a machine that captures nothing looks exactly like one that captures
everything**. There is no log to read.

So the only real check is a round trip:

```sh
ts-stack test                              # includes a write-then-read probe
services/stacks/agentmemory/ts-verify.sh   # just that probe
services/stacks/agentmemory/check-capture.sh --apply   # the deep diagnostic
```

Two failures worth knowing about, because both were silent:

- **A plugin upgrade reverts the wiring.** The hook scripts are vendor files in a
  plugin cache; an upgrade replaces the cache and every edit with it, turning
  retrieval off with nothing in any log. Both sync paths re-apply it, so
  `ts-update` and `chezmoi apply` repair it; `ts-doctor` reports it.
- **A stale secret 401s forever.** An exported variable only reaches processes
  started after it was set, so a long-lived shell keeps a pre-rotation secret and
  every request from that session fails — silently, because `/observe` swallows
  errors and retrieval discards non-2xx. That cost 56 consecutive captures once.
  The injected wrapper now re-reads the authoritative value on a 401 and retries.

## Retrieval

Every agent gets prompt-level retrieval (`/agentmemory/context` from
`prompt-submit`), not just Claude's `PreToolUse` enrichment. That matters more
than it sounds: `/enrich` fires only for a vendor allow-list, is excluded for
`Bash`, and drops a path-less `Grep` or `Glob` — so a shell-heavy session
retrieved almost nothing. Measured before the fix: 1041 captures against a single
`/context` call in 5.7 hours.

Set `AGENTMEMORY_INJECT_CONTEXT=false` in an agent's environment to turn
retrieval off deliberately.

## No LLM required

Embeddings run on-device (`EMBEDDING_PROVIDER=local`), so capture, keyword search
and vector search all work with no API key and no LLM host. An optional endpoint
adds the *derived* layer: summaries, knowledge-graph extraction, consolidation.
`services/stacks/agentmemory/README.md` covers pointing it at one.

## Where the data is

The volume `ts-agentmemory-data` is `external: true`, which means `docker compose
down -v` **cannot** remove it. That is on purpose: it is every memory you have
ever saved. Only `ts-stack reset --purge` removes it, and that wants a verified
backup and a typed phrase. `ts-stack backup` takes one on demand.

See also: `doc agentmemory-console` · `doc services` · `doc troubleshooting`
