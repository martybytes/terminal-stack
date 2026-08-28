# agentmemory — memory for Claude, Codex and Cursor

What gets captured, how each agent retrieves it, and what to run when it stops.
Long-form reference: `services/stacks/agentmemory/README.md`.

> Only one memory backend runs on a machine. `tstack config memory status` says which,
> and `tstack config memory headroom` swaps AgentMemory out for Headroom's own store.

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
| the server, its image, the compose file | `services/stacks/agentmemory/`, driven by `tstack services` |
| which hooks each agent registers, what they run, the environment they carry | `bootstrap/ts-agentmemory.{sh,ps1}`, driven by `tstack update` and `chezmoi apply` |

Both halves ship in this repo, but the split is deliberate: the wiring edits
`~/.claude`, `~/.codex` and `~/.cursor`, which are host files, so it lives
outside `services/`.

## Turning it on

```sh
tstack config agents agentmemory on    # the saved setting, this machine only
tstack services up agentmemory            # the server
tstack agentmemory --check             # is the host wiring in place
```

## Capture is invisible when it breaks

Every vendor hook does `fetch(...).catch(() => {})` and then `exit(0)`. That is
deliberate — a memory server being down must never break your agent — but it
means **a machine that captures nothing looks exactly like one that captures
everything**. There is no log to read.

So the only real check is a round trip:

```sh
tstack services test                              # includes a write-then-read probe
services/stacks/agentmemory/ts-verify.sh   # just that probe
services/stacks/agentmemory/check-capture.sh --apply   # the deep diagnostic
```

Two failures worth knowing about, because both were silent:

- **A plugin upgrade reverts the wiring.** The hook scripts are vendor files in a
  plugin cache; an upgrade replaces the cache and every edit with it, turning
  retrieval off with nothing in any log. Both sync paths re-apply it, so
  `tstack update` and `chezmoi apply` repair it; `tstack doctor` reports it.
- **A stale secret 401s forever.** An exported variable only reaches processes
  started after it was set, so a long-lived shell keeps a pre-rotation secret and
  every request from that session fails — silently, because `/observe` swallows
  errors and retrieval discards non-2xx. That cost 56 consecutive captures once.
  The injected wrapper now re-reads the authoritative value on a 401 and retries.

## Where the secret comes from

`AGENTMEMORY_SECRET` is the container's `/data/.hmac`. Nothing in this stack
writes it; the plugin's own setup owns that. What the stack does is get it to the
three kinds of process that need it, which reach differently:

| Consumer | Reads |
|---|---|
| terminal-launched agents | `~/.zshenv` |
| agent **hook subprocesses** | `~/.zshenv` — they are non-interactive, so zsh never sources `~/.zshrc` for them |
| GUI Cursor / Codex Desktop | the launchd environment — they read no shell file at all |

So there are two carriers. `chezmoi apply` splices a block into `~/.zshenv`
(part-owned: everything you or rustup or nvm put there is kept), and on macOS it
installs `~/Library/LaunchAgents/com.terminal-stack.agentmemory-secret.plist`,
which runs at login and does `launchctl setenv`. Both **read the 0600 cache at
`~/.config/terminal-stack/agentmemory.secret`** rather than carrying the value:
the secret rotates whenever the container regenerates `/data/.hmac`, and a
hardcoded copy works until it does not and then 401s on every request with the
error swallowed.

Both disappear when `agentmemoryEnabled` is off, so turning the feature off
actually stops exporting the secret.

`tstack services` writes the cache; `check-capture.sh` verifies no config file
holds a literal copy — including both carriers.

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
and vector search all work with no API key and no LLM host. A fresh clone ships
with **no chat provider configured**, and that is a supported state rather than
a half-finished install.

```sh
tstack agents llm      # what a chat model is switched on, and what runs without one
```

A chat model adds exactly four things:

| feature | what it does |
|---|---|
| `compression` | long observations condensed before they are stored |
| `summary` | session summaries |
| `graph` | entity and relation extraction into the knowledge graph |
| `consolidation` | the periodic reflect pass that turns observations into insights |

Everything else — storage, semantic search, embeddings — is unaffected either
way.

### Configured-but-unreachable is worse than absent

Unset is a clean skip that every check reports. An endpoint that is set and does
not answer fails **silently**: the calls return empty, fail XML parsing, retry,
and still log `outcome:"success"`. That asymmetry is why nothing ships
uncommented, and why the probe to trust is the one that dials from *inside* the
container:

```sh
tstack services test agentmemory
```

`tstack agents llm` probes from the host as well, and says so — a container's DNS
is Docker's embedded resolver and its egress a separate path, so reaching an
endpoint from your shell proves nothing about the server.

### Pointing it at a provider

Set the endpoint in `services/stacks/agentmemory/.env` and the credential in
`services/.env` (they load in that order, so the root file wins), then
`tstack services restart agentmemory`. The example file spells out three shapes:
any OpenAI-compatible server (vLLM, LM Studio, llama.cpp), Ollama on
`http://host.docker.internal:11434/v1`, or the OpenAI API itself.

Not sure what your machine can run? `llmfit recommend --use-case coding` sizes
candidates against this computer's RAM and GPU and prints an ollama name — it is
in the app catalog under **local model sizing** (`tstack config apps llmfit`),
and `doc llmfit` has the rest.

Remember to update `LLM_PROVIDER_LABEL` / `LLM_ENDPOINT_LABEL` in the same file,
or the console keeps reporting the machine as unconfigured.

## Where the data is

The volume `ts-agentmemory-data` is `external: true`, which means `docker compose
down -v` **cannot** remove it. That is on purpose: it is every memory you have
ever saved. Only `tstack services reset --purge` removes it, and that wants a verified
backup and a typed phrase. `tstack services backup` takes one on demand.

See also: `doc agentmemory-console` · `doc services` · `doc troubleshooting`
