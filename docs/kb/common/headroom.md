# headroom — prompt compression and the usage dashboard

The proxy your agents' API traffic goes through, plus the vector store and graph
it uses. Long-form reference: `services/stacks/headroom/README.md`.

## The shape

| port | what |
|---|---|
| 8787 | the proxy. Agents point their base URL here |
| 8788 | the dashboard gateway (nginx), which injects the token server-side |
| 6333 / 6334 | Qdrant — the vectors |
| 7474 / 7687 | Neo4j — the knowledge graph |

The MCP sidecar on 8788 is a **separate process** (`headroom mcp serve`); the
compose file does not start it. The proxy being up says nothing about MCP.

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

Neo4j sizes its heap from host RAM unless bounded, which is wrong inside a Docker
VM shared with the other stacks. `NEO4J_HEAP` and `NEO4J_PAGECACHE` in `.env`
hold it to about 800 MB. This is the heaviest of the four stacks, which is why it
is offered but off by default.

## Data

`ts-headroom-workspace`, `ts-headroom-qdrant` and `ts-headroom-neo4j` are plain
named volumes, so `docker compose down -v` **can** remove them — that is the
difference from agentmemory's, which are external precisely so it cannot.
`ts-stack reset --destroy-data` is the deliberate path, and it takes a verified
backup and a typed phrase first.

See also: `doc services` · `doc troubleshooting` · `doc claude-code`
