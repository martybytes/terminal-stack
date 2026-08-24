# headroom

Local [Headroom](https://github.com/headroomlabs-ai/headroom) proxy — an
OpenAI-compatible endpoint that sits between your agent and your LLM provider and
compresses what goes over the wire, plus the two datastores its semantic-memory
features need, plus a small gateway that makes the dashboard usable in a plain
browser tab. Things reachable on the host:

| | URL | Notes |
|---|---|---|
| Proxy | **`http://127.0.0.1:8787`** | OpenAI-compatible `/v1/*`. Point a client's base URL here. Readiness at `/readyz`. |
| Dashboard (direct) | **`http://127.0.0.1:8787/dashboard`** | Savings, history and session stats. Needs the proxy token — see the gotcha below on when. |
| Dashboard (browser-friendly) | **`http://127.0.0.1:8788/dashboard`** | Same dashboard; `dashboard-gateway` attaches the token server-side, so it loads in a plain browser tab with nothing to paste. |
| Qdrant | **`http://127.0.0.1:6333`** | Vector store (REST; gRPC on 6334). Holds embeddings derived from your prompts. |
| Neo4j | **`http://127.0.0.1:7474`** | Graph browser (Bolt on 7687). |

Unlike `../kokoro`, this stack pulls prebuilt images — all four are multi-arch,
so Apple Silicon runs them natively. Unlike `../agentmemory`, it needs **two
secrets to exist before it will start at all**; see the gotcha below.

## Quick start

Bootstrap seeds `headroom/.env` from `.env.example`, then you fill in the two
secrets and start the stack.

| | |
|---|---|
| macOS / Linux | `../bootstrap.sh --apply` |
| Windows | `..\bootstrap.ps1 -Apply` |

Generate the two secrets and put them in `headroom/.env` (identical on both
platforms if you have OpenSSL; otherwise use any 32-byte hex string):

```sh
openssl rand -hex 32     # -> HEADROOM_PROXY_TOKEN
openssl rand -hex 32     # -> NEO4J_PASSWORD
```

Then bring it up:

| | |
|---|---|
| macOS / Linux | `../stack.sh --stack headroom --up --apply` |
| Windows | `..\stack.ps1 -Stack headroom -Up -Apply` |

First start pulls roughly 2 GB across the three images and Neo4j takes ~45
seconds to accept connections; the healthchecks account for that.

## What's pinned, and how to bump it

| Pin | Where | Notes |
|---|---|---|
| `ghcr.io/headroomlabs-ai/headroom:0.36.5` | `HEADROOM_IMAGE` in `.env`, default in `docker-compose.yml` | multi-arch (amd64 + arm64) |
| `qdrant/qdrant:v1.17.1` | `docker-compose.yml` | multi-arch |
| `neo4j:5.26` | `docker-compose.yml` | multi-arch |
| `nginx:1.27.4-alpine` | `docker-compose.yml` (`dashboard-gateway`) | multi-arch; ships both `curl` and `wget`, verified before pinning |

Bumping any of them: confirm the new tag publishes **both** architectures before
you pin it, or the stack silently starts emulating on one of your machines.

The proxy is a thin local image layered on that pin. Its Dockerfile makes the
dedicated `X-Headroom-Proxy-Token` take precedence over the provider's OAuth
`Authorization` bearer; remove the patch once the pinned upstream image includes
that behavior.

```sh
docker manifest inspect ghcr.io/headroomlabs-ai/headroom:<new> | grep architecture
```

Upstream ships its own `docker-compose.yml` that **builds from a local
checkout**. This stack deliberately does not: a build context is a machine
specific path in a tracked file, and two machines building a week apart would
run different bytes (`../docs/conventions.md`, "Pin exact versions"). The
checkout at `Workspace/src/github.com/martybytes/headroom` is upstream reference
source, not the runtime.

## Verify it's actually working

"Up" is not evidence. These are the checks that prove it.

```sh
docker compose ps      # all four STATUS should read "Up (healthy)"
```

Proxy, gateway and datastores — identical on every platform (Windows
PowerShell 5.1 only: write `curl.exe`; pwsh 7 removed the
`Invoke-WebRequest` alias):

```sh
curl -fsS -o /dev/null -w 'proxy   /readyz: %{http_code}\n' http://127.0.0.1:8787/readyz
curl -fsS -o /dev/null -w 'dashboard-gateway: %{http_code}\n' http://127.0.0.1:8788/dashboard
curl -fsS -o /dev/null -w 'qdrant:          %{http_code}\n' http://127.0.0.1:6333/
curl -fsS -o /dev/null -w 'neo4j browser:   %{http_code}\n' http://127.0.0.1:7474/
curl -fsS http://127.0.0.1:6333/collections
```

The `dashboard-gateway` check should return `200` with zero headers set — no
token, no bearer, nothing pasted — because the gateway attached it
server-side. Then open `http://127.0.0.1:8788/dashboard` in an actual
browser tab with no extensions and confirm it fully renders, including the
Settings tab and unmasked stats (that proves
`HEADROOM_PROXY_TRUSTED_DASHBOARD_CLIENT_CIDRS` is working, not just the
token injection on the base dashboard route).

**The check that matters most is that the proxy token is enforced**, because it
is the only thing standing between a local process and a relay to your provider:

| | |
|---|---|
| macOS / Linux | `tok="$(grep '^HEADROOM_PROXY_TOKEN=' .env \| cut -d= -f2-)"` |
| Windows | `$tok = (Select-String '^HEADROOM_PROXY_TOKEN=' .env).Line -replace '^[^=]+='` |

```sh
# no token -> {"error":"unauthorized"}
curl -sS -X POST http://127.0.0.1:8787/v1/chat/completions \
  -H 'content-type: application/json' -d '{"model":"x","messages":[]}'

# with the token -> 200 on the dashboard
curl -sS -o /dev/null -w '%{http_code}\n' -H "Authorization: Bearer $tok" \
  http://127.0.0.1:8787/dashboard
```

Then confirm nothing is exposed. Neutral first — every mapping must read
`127.0.0.1:<port>->`:

```sh
docker ps --format '{{.Names}}\t{{.Ports}}'
```

| | |
|---|---|
| macOS / Linux | `lsof -nP -iTCP:8787,8788,6333,6334,7474,7687 -sTCP:LISTEN` |
| Windows | `Get-NetTCPConnection -State Listen -LocalPort 8787,8788,6333,6334,7474,7687 \| Select-Object LocalAddress, LocalPort` |

On macOS the NAME column must read `127.0.0.1:<port>`; a `*:<port>` is a bug.
`lsof` prints nothing and exits 1 when nothing matches, which looks identical to
a typo — sanity-check it against a port you know is listening.

## Gotchas

**The proxy token is not your provider API key, and confusing them looks like a
broken proxy.** Headroom forwards the `Authorization` header upstream. Send the
proxy token as a bearer to `/v1/chat/completions` and the *proxy* accepts you,
then your provider rejects it with something like `Incorrect API key provided:
4bb2c6c8****1c52` — a 401 that reads like the proxy refusing you when it is
actually the provider. Tell the two apart by the body: `{"error":"unauthorized"}`
is the proxy; anything mentioning an API key is upstream. Configure the real
provider credential separately.

**A bare `http://127.0.0.1:8787/dashboard` in a browser may or may not need the
token, depending on your platform — that's Docker, not this repo.** Headroom
exempts loopback callers from the token, but "loopback" means the literal peer
IP the app sees, and that differs by how each platform's Docker networking
forwards a host-published port into the container. On Windows (Docker
Desktop/WSL2) that identity is preserved, so the bare URL can just work. On
macOS and native Linux, the connection is NATed through the Docker bridge, so
the container sees the bridge gateway instead of `127.0.0.1` and the token is
required — confirmed here by comparing `/health`'s response (it includes an
extra `config` block only for requests the app recognizes as loopback) curled
from the host versus curled from inside the container.

`dashboard-gateway` (`http://127.0.0.1:8788`) makes this identical on every
platform instead of relying on that Docker networking detail: it's a small
loopback-bound nginx container that attaches `X-Headroom-Proxy-Token` to a
request server-side before forwarding it to `headroom-proxy`, so a plain
browser tab always works and the token never touches the browser. It doesn't
widen anything the token protects — it proxies only read-only dashboard/status
routes (`/dashboard`, `/stats*`, `/settings*`, `/health`, `/metrics`; see
`dashboard-gateway/templates/default.conf.template`) and has no route for
`/v1/*` at all, so the actual LLM-relay data plane still requires the real
token from every caller, gateway or not. The Settings tab and unmasked stats
additionally need `HEADROOM_PROXY_TRUSTED_DASHBOARD_CLIENT_CIDRS`
(`docker-compose.yml`, scoped to this stack's own explicit subnet) — an
upstream-supported knob built for exactly this "dashboard behind a
reverse-proxy" case, not a patch.

**8788 works identically on Windows, macOS and Linux; 8787's bare-URL
behavior does not.** The platform split above is specifically about a
*host*-originated connection through a published port losing its loopback
identity on macOS/Linux Docker. `dashboard-gateway`'s request to
`headroom-proxy` is *container-to-container*, over the explicit bridge
subnet above — ordinary Docker bridge networking, not the host NAT hop that
differs by platform, so it behaves the same everywhere regardless of which
machine the stack runs on. No script in this repo (`stack.sh`/`stack.ps1`,
`bootstrap.sh`/`bootstrap.ps1`) references headroom's ports or service
names — they discover stacks by finding `docker-compose.yml`, generically —
so none needed a platform-specific change for this.

**Both secrets must exist before the first start.** `agentmemory` generates its
HMAC inside the container on first boot; headroom cannot, because compose
interpolates both values before anything runs. They are declared required, so a
missing one fails at `docker compose config` with a message naming the variable,
rather than starting a proxy whose data plane accepts anyone. That is deliberate.

**Neo4j sizes its heap from host RAM, which is wrong inside a shared VM.** Left
alone it will claim a fraction of the whole machine while sharing 8 GB with
`agentmemory` and `kokoro`. `NEO4J_HEAP` / `NEO4J_PAGECACHE` in `.env` bound it
to 512m/256m; measured steady state is ~800 MB resident. Raise them if the graph
grows and queries slow down.

**6333, 7474 and 7687 are popular defaults.** If something else on the machine
already listens there, change the host side in `.env` — every port is
`${VAR:-default}` in the compose file, and the container side never moves.

**`docker compose down -v` destroys the graph and the vectors.** Plain
`down` keeps all three named volumes. There is no external-volume protection
here, unlike `agentmemory`, because nothing pre-existed these.

**The Qdrant image ships no `curl` or `wget`,** so its healthcheck opens a TCP
connection with bash's `/dev/tcp` instead. If you rewrite that check, note that
zsh has no `/dev/tcp` at all — test it inside the container, not from your shell.

**Client wiring is not this repo's job.** Which agents point at the proxy, and
the MCP registration, belong to `terminal-stack` alongside the other harness
wiring — the same boundary `agentmemory` observes.

## Notes

- `restart: unless-stopped` on all three, so the stack survives a reboot once
  Docker Desktop is set to start at login.
- The proxy binds `0.0.0.0` **inside** the container. That is required on every
  platform: a container-internal loopback bind is unreachable through any
  published port mapping, because the forwarder connects to the container's
  bridge address. The host side stays loopback-only via `ports:`.
- To point the proxy at the fleet's own vLLM rather than a hosted provider, set
  `OPENAI_TARGET_API_URL` in `.env` to the tailnet endpoint used by
  `../agentmemory` (see `../.env.example` for why it is the `100.x` address and
  not the MagicDNS name).
