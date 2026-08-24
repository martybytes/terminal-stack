# headroom — prompt compression and the usage dashboard

The proxy your agents' API traffic goes through, plus the vector store and graph
it uses. Long-form reference: `services/stacks/headroom/README.md`.

## The shape

| port | what |
|---|---|
| 8787 | the proxy. Agents point their base URL here |
| 8788 | the dashboard gateway (nginx), which injects the token server-side |
| 6333 / 6334 | Qdrant — the vectors. **Only when `memoryBackend` is `headroom`** |
| 7474 / 7687 | Neo4j — the knowledge graph. Same condition |

The last two are not part of the base stack: they arrive with
`docker-compose.memory.yml`, which `ts-config memory headroom` selects. A
machine using AgentMemory for memory never pulls those images.

`headroom mcp serve` is a **separate process** the compose file does not start
(8788 here is the dashboard gateway, not MCP). Memory does not need it — the
`--memory` flag injects the memory tools into requests directly — so it only
matters for CCR retrieval on subscription plans.

## Turning it on

```sh
ts-stack up headroom
ts-config agents headroom on      # registers the MCP clients, saves the setting
ts-config agents headroom status  # the authenticated probe, with a reason
```

`headroom on` refuses to persist `on` until the authenticated proxy answers,
deliberately: a machine claiming a working proxy it does not have is worse than
one that says so.

## The token is not your API key

The single most expensive confusion here. `HEADROOM_PROXY_TOKEN` authenticates
**you to headroom**; your provider key authenticates **headroom to the provider**.
The proxy forwards `Authorization` upstream, so sending the proxy token to
`/v1/chat/completions` gets you past headroom and then a 401 from the provider.

Tell them apart by the body:

| body | meaning |
|---|---|
| `{"error":"unauthorized"}` | headroom refusing you — wrong or missing proxy token |
| anything naming an API key | you got through headroom; your provider refused it |

The token is generated on this machine by `ts-stack bootstrap` and written only
to the gitignored `services/stacks/headroom/.env`.

## Both secrets are required to start

`HEADROOM_PROXY_TOKEN` and `NEO4J_PASSWORD` are `:?`-required in the compose
file, so a missing one fails at `docker compose config` naming the variable
rather than starting an open data plane. `ts-stack bootstrap` generates both;
`ts-stack config headroom` is what to run if it will not start.

## Resource notes

With memory off — the default — this stack is two small containers. With
`memoryBackend=headroom` it also runs Neo4j, which sizes its heap from host RAM
unless bounded (wrong inside a Docker VM shared with the other stacks);
`NEO4J_HEAP` and `NEO4J_PAGECACHE` in `.env` hold it to about 800 MB. That makes
headroom-with-memory the heaviest of the stacks by a wide margin, which is the
main reason the memory backend is a deliberate choice rather than a default.

## Data

`ts-headroom-workspace`, `ts-headroom-qdrant` and `ts-headroom-neo4j` are plain
named volumes, so `docker compose down -v` **can** remove them — that is the
difference from agentmemory's, which are external precisely so it cannot.
`ts-stack reset --destroy-data` is the deliberate path, and it takes a verified
backup and a typed phrase first.

## What Headroom does, and does not, use a model for

**Compression calls no model.** It is structural: tool-schema trimming,
code-aware compression, and CCR. On a working machine the schema trimming is
almost all of it — 629,013 tokens saved against 0.5% average message
compression, in one measured 15-minute window. Nothing in the compression path
has an LLM endpoint, and there is no setting that would give it one.

The only model Headroom talks to is the one it **relays your traffic to**
(`backend`, default `anthropic`). So "point Headroom at the same model as
AgentMemory" would not improve compression — it would change which model your
agents are talking to. Three different things could be meant, and none of them
is a shared side-model:

| what you might change | what it actually does |
|---|---|
| `openai_base_url` / `anthropic_base_url` / `backend` | changes the upstream your agents' requests go to. Setting it to a local 8B model replaces the model you are coding with |
| the embedding model | not settable. Embeddings run on-device inside the container (`onnxruntime`, `transformers`). AgentMemory is `EMBEDDING_PROVIDER=local` too, so both are already local |
| a summarisation model | there isn't one. Headroom's memory stores and retrieves; it does not summarise through an LLM |

## Memory: only one backend runs

AgentMemory and Headroom both do semantic memory, and this stack runs exactly
one of them. `ts-config memory` is the switch:

```sh
ts-config memory status        # which one, and whether the derived state agrees
ts-config memory agentmemory   # AgentMemory remembers, Headroom compresses (the default)
ts-config memory headroom      # Headroom does both; AgentMemory is not installed
ts-config memory none          # no memory; Headroom still compresses
```

Choosing `headroom` merges `docker-compose.memory.yml`, which starts Qdrant and
Neo4j **and passes `--memory` to the proxy**. That flag is the whole feature:
setting `QDRANT_URL` and `NEO4J_URI` is not enough and never was. Before this
was a setting, the compose file did exactly that — both databases up, memory
never engaged — and every machine ran a 900 MB Neo4j holding zero nodes while
reporting healthy. There is no environment variable for `--memory`, so the flag
lives in the overlay's `command:` and a test asserts it stays there.

`ts-stack doctor` reports the backend, refuses to let the derived
`agentmemoryEnabled` drift from it, and says so if the proxy is running without
`--memory` while `headroom` is selected.

## `headroom doctor` inside the container always says "not routed"

Running `docker exec ts-headroom-proxy headroom doctor` reports
`claude: not routed` and `codex: not routed`. Both are artifacts of where it
ran: it looks for `~/.claude/settings.json` and `~/.codex/config.toml`, and
neither exists inside the container — nor should it. Your routing is fine if
`/stats` attributes requests to `claude-code`. Ask the host instead:

```sh
ts-config agents headroom status
```

See also: `doc services` · `doc troubleshooting` · `doc claude-code`
