<img src="public/assets/agent007memory-mark.png" alt="Agent007Memory aperture and memory-node mark" width="96" />

# Agent007Memory

Agent007Memory is a spy-inspired companion console for
[agentmemory](https://github.com/rohitg00/agentmemory) — a real-time
dashboard the stock viewer doesn't have, with **zero changes to agentmemory itself**. Upstream
updates never need merging into this repo; it talks to agentmemory purely over its public REST
API and `mem-live` WebSocket stream.

The original aperture-and-memory-node identity and the dashboard's encrypted-network empty-state
art were generated with fal.ai, then adapted to the console's navy, turquoise, and periwinkle
palette. Production derivatives live in `public/assets`.

One Node process, two listeners:

| Port | What | Why |
|---|---|---|
| `3111` | Agent-aware reverse proxy → agentmemory's REST API | Every MCP/hook call is captured as **metadata only** (HTTP method, semantic intent, memory-lifecycle stage, safe result/context counts, path, bounded MCP operation name, project/session/agent attribution, status, duration, sizes — never bodies) in a 5,000-entry ring buffer. Tagged session and explicit-memory writes also receive AgentMemory's existing `agentId` metadata. |
| `3114` | Console UI + `/api/*` + `/ws` + `/healthz` | React SPA with a compact operations overview, live dashboard, per-project and LLM activity, one-year aggregate reports, live requests, timeline, memories browser, and system health. |

The backend also subscribes to agentmemory's `mem-live` stream (port 3112) server-side and
rebroadcasts a single consolidated WebSocket to the browser. Live events arrive through that
socket; bounded dashboard and project snapshots are periodically reconciled over the console API.

## Brand assets

| Asset | fal.ai model | Seed | Production output |
|---|---|---:|---|
| Aperture and memory-node mark | `fal-ai/ideogram/v3/generate-transparent` (`QUALITY`) | `278601774` | `agent007memory-mark.png`, favicon PNGs, `favicon.ico`, Apple touch icon |
| Encrypted-network empty state | `fal-ai/flux-2` | `953604386` | `agent007memory-empty-state.webp` |

The source prompts request an original cyber-espionage identity and explicitly exclude weapons,
official 007 lettering, gun-barrel imagery, copied franchise artwork, generated UI, and generated
typography. The exact `Agent007Memory` product name remains HTML text so it is accessible and
renders reliably at every size.

`scripts/prepare_brand_assets.py` performs deterministic cleanup, recoloring, and resizing; it
does not call fal.ai or read an API key. With Python 3 and Pillow installed, rebuild the production
derivatives from downloaded source generations with:

```bash
python3 scripts/prepare_brand_assets.py \
  --logo-source /path/to/logo-source.png \
  --background-source /path/to/empty-state-source.png \
  --output public/assets
```

```powershell
python scripts/prepare_brand_assets.py `
  --logo-source C:\path\to\logo-source.png `
  --background-source C:\path\to\empty-state-source.png `
  --output public\assets
```

## Overview page

Overview is the single-screen operational watch view at `#/overview`; its default layout is designed
to fit without scrolling in a 1920×1000 browser viewport. It shows the six most recently active
projects beneath the global memory/session/observation/request/latency/uptime row. Compact project
cards lead with confirmed stores, automatic recall, modeled context avoided, agent attribution,
and a mirrored 15-minute memory-value graph.

A compact Memory Value row plots saves above zero and automatic/manual retrieval below zero. It
separates hook-driven context from explicit search, shows session-start assistance, closeouts,
semantic/source coverage, budgets, truncation, scope warnings, and a conservative avoided-context
range derived from exact capture bytes. “Returned” means delivered, not proof of model attention.

Overview shares the Projects page's persisted reorder cadence (15 seconds, 30 seconds, 60 seconds,
5 minutes, or manual) and exposes the same dropdown plus the manual **Reorder now** action. Live card
values and glow continue updating between position refreshes. Beneath Projects, Overview shows the
compact LLM cards for completions, success, provider latency, effective output tokens/second, durable depth/wait, job runtime, and
dead-letter pressure, followed by fallback cards for
`mem::compress` and `mem::summarize`. Provider endpoint, exact-call table, model, timeout, and other
server configuration remain on the dedicated LLM Calls page. API-cost cards appear only when the
active provider may charge an API fee; a private-network vLLM deployment omits them.

The left navigation collapses to an icon rail for additional working space. Its state is saved in
browser local storage and survives reloads and container rebuilds on the same origin; icon tooltips
and accessible labels retain every destination and the live/offline status while collapsed.

Every route also has a **Customize** control at the bottom of the sidebar. Its live-preview drawer
can hide or show page sections and individual cards or columns, set row/project limits, pin or hide
project cards, choose comfortable or compact density, set 80–125% page scale, and constrain the
canvas to Fluid, Wide (1600 px), or Focused (1280 px). Section order is draggable on the primary
Overview and Projects views. **Default** restores the shipped page, while **Focused** applies a
curated reduced view. Dark, Light, and System themes are global; page presentation is independent.
All presentation preferences use the versioned `agent007memory.preferences.v1` local-storage key.
Search terms, active filters, selected rows, expansion state, and pagination are deliberately not
persisted.

## Projects page

Projects combines durable AgentMemory session projects with the console's rolling 15-minute
memory activity. Each card shows confirmed observation and explicit-memory stores, all recall
attempts split into delivered/empty/failed/unknown outcomes, returned context, durable long-term
memory count, agent attribution, requests/min, errors, p95 latency, and last activity. HTTP
verbs describe transport: AgentMemory search, recall, context, enrichment, and many MCP reads use
POST, so verb totals remain a small diagnostic footer instead of the main graph. The border pulses
turquoise for completed storage activity and violet for retrieval activity; concurrent activity
layers both colors and increases the glow strength.

The lifecycle strip is the primary memory signal: confirmed recall hits/attempts, context tokens
returned, observations captured, explicit long-term saves, and scope warnings. The older semantic
intent remains available as a coarser transport classification.

Card values update from the live request stream, but their newest-first positions change only on
the selected cadence (15 seconds, 30 seconds, 60 seconds, 5 minutes, or manual). The selection is
stored in the browser's local storage, so it survives reloads and container rebuilds on the same
origin. Clicking a card opens Live Requests with an exact project filter. Activity counts reset
when the console process restarts; project cards remain discoverable from AgentMemory sessions.

## Live Requests

The full request table shows project and agent attribution alongside HTTP method, semantic intent,
and the concrete memory-lifecycle stage. Lookup, write, health, admin, and unclassified intent filters make read behavior visible
without treating every POST as a write. The compact Dashboard request feed also shows project and
intent. For generic MCP calls the proxy may retain the bounded tool name needed for classification;
arguments and bodies are never stored. Calls with no project or session scope remain `Global`.
Agent capability-discovery polls such as `/agentmemory/mcp/tools` are intentionally classified as
administrative and global rather than as project memory lookups.

Expanding a row shows whether a retrieval returned results or context, returned nothing, failed,
or could not be observed; result count, top score, context size, and project-integrity counts are
safe numeric metadata. The response stream is forwarded unchanged. At most 512 KiB is inspected
transiently for selected JSON retrieval/save responses, and all content is discarded immediately.

## LLM Calls page

LLM Calls combines AgentMemory's authenticated `/agentmemory/health`,
`/agentmemory/config/flags`, and `/agentmemory/llm/telemetry` responses with safe, explicitly
forwarded deployment metadata. It shows the configured provider endpoint and model,
timeout/output/concurrency settings, local embedding mode, circuit-breaker state, durable queue
depth, worker count, average durable wait, provider-gate wait, job runtime, dead-letter depth, and exact calls for compression, summarization, graph
extraction, and consolidation.

The console polls every three seconds. Exact rows include family, lifecycle state, outcome, model,
project/session attribution, prompt character count, prompt/cached/cache-write/completion/reasoning
token categories, effective output tokens/second, separate durable/provider-gate wait, provider latency, and estimated cost. Output rate uses exact successful completion tokens divided by provider latency, including time-to-first-token, and is retained in reports.
The Exact Provider Calls ledger is the final page section and uses its own 360-pixel scroll window
plus persisted pagination, so large call histories do not make the whole page excessively tall.
Today and 15-minute estimates use a versioned model-price catalog. Unknown remote models are marked
Unpriced and local models are explicitly zero; neither is silently blended into paid estimates.
Hosted provider identity takes precedence over network location, then private/loopback endpoints are
treated as local. Public self-hosted endpoints remain Unknown rather than being assumed free.
AgentMemory's cumulative `mem::compress` and `mem::summarize` metrics remain
visible as a compatibility fallback and historical total. The first cumulative sample is still a
baseline, so old totals never masquerade as new live activity.

Optional authoritative OpenAI reconciliation uses the organization Costs API with complete UTC-day
buckets filtered to one dedicated OpenAI project. Billed month-to-date is displayed separately
from estimates on Overview, LLM Calls, and Reports when paid or unknown-fee traffic is relevant. The required Admin API key is file-mounted
read-only, never sent to the browser, logged, or stored in history. Automatic and manual refreshes
share a persistent two-hour cooldown; `Retry-After` and request-reset windows are doubled when they
require a longer delay.

When a hosted provider is active, the page can show short masked OpenAI key hints, such as
`sk-proj-123456…wxyz`, for the active inference and billing-admin credentials. Local inference hides
both OpenAI hints because those credentials are not in the active call path, even if old deployment
variables remain mounted. The browser and history database never receive a complete key. The
inference hint is supplied as an already-masked deployment value; the Admin-key hint is derived
server-side from its read-only file.

The page never receives complete provider API keys, prompt or response bodies, or raw provider errors. Safe
configuration values are opt-in environment mirrors; invalid URLs are suppressed and
credentials/query strings are stripped before display.

## Historical reports

Reports at `#/reports` retain one year of privacy-safe minute aggregates in a console-owned SQLite
database. The default Overview tab follows the live Overview hierarchy with global totals, the six
busiest projects, memory retrieval effectiveness, LLM completion health, and activity charts. Summary, Projects, Memory, LLM, and System
tabs provide preset or custom date ranges, optional preceding-period comparisons, automatic chart
downsampling, filters, and CSV export. The default view is the last 24 hours and refreshes every
15 seconds while visible.

The database stores counts and gauges only: project and agent dimensions, method/status groups,
observation kinds/types, LLM completion families, exact provider/model/family token totals,
estimated costs, local/priced/unpriced call classification, authoritative daily provider costs,
process samples, and a fixed request-latency
histogram used to estimate historical p95. It never stores paths, bodies, prompts, responses,
memory content, excerpts, raw session IDs, request IDs, or individual activity records. A salted
session hash supports lifecycle correlation without exposing the identifier. Live pages
remain memory-backed and real time; Reports survives console restarts and rebuilds.

Memory history separates automatic and manual retrieval; stores capture bytes, budgets,
truncation, relevance, latency, session coverage, and the modeled avoided-context bounds; and keeps
storage outcomes, project-integrity warnings, observation captures, saves, and consolidation by
minute, project, and agent. CSV exports expose the same privacy-safe aggregates.

History begins when this version is deployed. Current memory/session totals seed the first gauge
sample, but earlier request, observation, latency, project, and LLM timelines cannot be
reconstructed. Reported availability is sampled upstream availability; time when the console
itself was stopped is not counted as uptime.

## Operations and Help

Operations at `#/operations` exposes only guarded, non-destructive actions. Full memory maintenance
requires selecting one project or explicitly choosing all projects, then performs a no-write
preview before queuing both basic memory consolidation and the full consolidation pipeline.
Recovery is also preview-first and queues one bounded durable wave. A selected session can receive
a forced summary, the graph snapshot can be rebuilt locally, and configured OpenAI billing can be
synchronized on demand when non-local inference is active. Local operation previews omit projected
API cost and pause billing synchronization. Preview confirmations expire, duplicate submissions are suppressed, and
forget/delete/reset/restore actions are intentionally absent.

Help at `#/help` renders the canonical [detailed guide](docs/HELP.md). The same guide powers
plain-language contextual explanations: ambiguous labels receive accessible hover/focus tooltips,
while question-mark controls open detailed dialogs. Adaptive, Minimal, and Off help density is
saved with existing browser display preferences. The guide documents every formula, caveat,
workflow, privacy boundary, operation, and troubleshooting path.

## Agent attribution

Configure each host to use its tagged proxy base URL:

| Host | `AGENTMEMORY_URL` |
|---|---|
| Claude Code | `http://localhost:3111/_agent/claude` |
| Codex | `http://localhost:3111/_agent/codex` |
| Cursor | `http://localhost:3111/_agent/cursor` |

Set the Claude URL in `env.AGENTMEMORY_URL` in `~/.claude/settings.json`. Codex needs the tagged
value in its AgentMemory MCP environment, while its plugin hook scripts need their own tagged
fallback because Codex does not forward `shell_environment_policy.set` into plugin hook commands.
Restart or reload each host after changing its MCP configuration. Re-run the client setup after
upgrading the AgentMemory plugin because plugin caches are versioned.
Set `AGENTMEMORY_INJECT_CONTEXT=true` in the host agent environment as well as the server: the
container flag does not propagate into host hook processes, and Codex/Cursor lookup hooks must be
explicit or capture becomes write-only when context injection was intended.

> **Client wiring lives in `terminal-stack`, and is Windows-only today.**
> The `setup-codex-agent-tagging.ps1` / `setup-cursor-integration.ps1` helpers that used to live in
> the deployment stack were moved out; the current automation is
> `terminal-stack/bootstrap/ts-agentmemory.ps1` (over `bootstrap/_agentmemory.ps1`). There is **no
> bash twin yet**, so on macOS and Linux the tagged proxy URLs, the Codex plugin-hook fallback, and
> `AGENTMEMORY_INJECT_CONTEXT` must be set by hand using the table above. Everything else in this
> repo — the proxy, the console, and the Docker deployment — is fully cross-platform.

The proxy strips `/_agent/<name>` before forwarding. For
`POST /agentmemory/session/start` and `POST /agentmemory/remember`, it adds only the known
client name as `agentId` with a streaming transform. AgentMemory 0.9.29 already persists that
field on sessions and memories, and observations inherit it from their session. Existing and
untagged records remain valid and appear as `Unknown`. Requests such as liveness, tool discovery,
and unscoped search that carry no project or session metadata appear under the `Global` project.

## Dev

Requires Node >= 24 (`node:sqlite` is used unflagged). Builds and runs identically on macOS,
Linux, and Windows; there are no native modules to compile.

```bash
npm install
npm run dev        # backend on 3114 (dev proxy listener on 3121) + vite on 5173
```

Dev expects a running agentmemory publishing `3111`/`3112` (override with `UPSTREAM_HTTP` /
`UPSTREAM_WS`). The console's own API calls need the agentmemory bearer, or point `SECRET_FILE`
at a file containing it:

```bash
AGENTMEMORY_SECRET=<secret> npm run dev
```

```powershell
$env:AGENTMEMORY_SECRET = '<secret>'; npm run dev
```

```bash
npm run typecheck
npm test
npm run build      # dist/web (SPA) + dist/server (backend)
npm start          # serve the built app
```

## Environment

| Var | Default | Notes |
|---|---|---|
| `HOST` | `127.0.0.1` (container: `0.0.0.0`) | bind address for both listeners |
| `PROXY_PORT` / `UI_PORT` | `3111` / `3114` | `npm run dev` moves the proxy to `3121` |
| `UPSTREAM_HTTP` / `UPSTREAM_WS` | `http://127.0.0.1:3111` / `ws://127.0.0.1:3112` | agentmemory endpoints |
| `SECRET_FILE` / `AGENTMEMORY_SECRET` | — | bearer for the console's own API calls (file wins; re-read on 401). Proxy traffic passes the caller's auth through untouched. |
| `CAPTURE_BODIES` | `false` | ships off — request contents are never recorded; the proxy only inspects bounded JSON metadata for project/session attribution and streams agent tagging without buffering content |
| `LLM_POLL_MS` | `3000` | cadence for local upstream LLM health/config telemetry; minimum 1000 ms |
| `LLM_PROVIDER` / `LLM_ENDPOINT_LABEL` | `configured LLM` / — | safe display names, such as `OpenAI-compatible` and `<your-llm-host>` |
| `LLM_MODEL` / `LLM_BASE_URL` | — | safe model and endpoint mirrors; never put credentials in the URL |
| `LLM_TIMEOUT_MS` / `LLM_MAX_TOKENS` | — | display-only request ceiling and maximum output-token settings |
| `LLM_SUMMARIZE_CONCURRENCY` / `LLM_GRAPH_BATCH_SIZE` | — | display-only summary worker and graph batch settings |
| `LLM_CONCURRENCY` / `LLM_RECOVERY_BATCH_SIZE` | — | display-only provider-gate slots and paced startup-recovery wave size |
| `LLM_EMBEDDING_PROVIDER` | — | display-only embedding mode, kept separate from the remote LLM provider |
| `HISTORY_DB_PATH` | `.agent007memory/history.sqlite` (container: `/data/agent007memory.sqlite`) | console-owned aggregate SQLite database; never point this at AgentMemory's volume |
| `HISTORY_RETENTION_DAYS` | `365` | rolling minute-aggregate retention window |
| `OPENAI_ADMIN_KEY_FILE` | — | optional in-container read-only Admin API key file used only for billing synchronization; environment key values are deliberately unsupported |
| `OPENAI_INFERENCE_KEY_FILE` | — | optional read-only inference-key file used only to derive a 12-character masked display hint; prefer a safe hint when the upstream alone owns the key |
| `LLM_API_KEY_HINT` | — | preferred producer/consumer contract for the safe inference-key hint: family prefix + six identifier characters + ellipsis + final four, such as `sk-proj-123456…wxyz`; exposed only while non-local inference is active |
| `LLM_ADMIN_KEY_HINT` | — | matching safe contract for the billing Admin-key hint; falls back to deriving the same shape from `OPENAI_ADMIN_KEY_FILE` and is hidden while billing is inactive for local inference |
| `OPENAI_INFERENCE_KEY_HINT` | — | deprecated compatibility alias for `LLM_API_KEY_HINT`; a complete value is masked again before any API response |
| `OPENAI_BILLING_PROJECT_ID` | — | dedicated OpenAI project used as the authoritative billing boundary |
| `OPENAI_BILLING_PROJECT_NAME` | — | safe display label generated from the selected project |
| `OPENAI_BILLING_SYNC_MS` | `7200000` | billing reconciliation cadence and shared manual-refresh cooldown; minimum two hours |

## Docker

`Dockerfile` is a two-stage Node 24 build pinned by the lockfile (`npm ci`). Deployment lives in
this repo, at `services/stacks/agent007memory/` — its own compose project, whose build context is
this directory:

```sh
tstack services up agent007memory              # rebuild and deploy from this checkout
tstack services logs agent007memory -n 50      # what it did
```

`update-console.sh` / `.ps1` are gone. They existed to push this repo, re-pin a commit SHA in
the compose file, rebuild and verify -- a loop that only made sense while the console was a
separate repository built from a pin. The build context is now the in-tree `services/console/`,
so what runs is what you have checked out, and the whole cycle is one `tstack services up`.

There is no hot reload: the deployed console is an immutable compiled image, so re-run
`tstack services up agent007memory` after each change. It mounts AgentMemory's volume read-only
for the HMAC secret and a separate external `ts-agentmemory-console-history` volume read/write at `/data`
for aggregate reporting.

When OpenAI inference is active, enable authoritative costs by creating a dedicated **Agentmemory** project, putting its inference
key in the services-root `.env` (`services/.env`), and running this stack's own
`services/stacks/agent007memory/configure-openai-billing.sh` (or `.ps1` on Windows) to validate the project and Costs
API permissions. The helper writes the project ID/name, Admin-key mount paths, and the two safe
masked key hints to ignored `.billing.env`; raw key material never enters it. The shared hint
contract is `LLM_API_KEY_HINT` for inference and `LLM_ADMIN_KEY_HINT` for billing administration.
Deploy with the read-only billing overlay described in that stack's README. Without it, exact local
estimates continue working and the UI explicitly shows
**Billing setup required**.

The stack publishes both hints automatically. Agent007Memory ignores those
OpenAI hints while the active provider is local, so stale safe metadata does not imply key use. The optional
`docker-compose.key-hints.yml` overlay is retained for older stacks and manual deployments; it
forwards only already-masked values. Generate a compatibility hint in memory without printing or
persisting the full key, then include the overlay:

```powershell
$rawInferenceKey = (Get-Content -LiteralPath C:\temp\openai-inference.key -Raw).Trim()
if (-not $rawInferenceKey.StartsWith('sk-')) { throw 'Expected one raw OpenAI key' }
$family = if ($rawInferenceKey.StartsWith('sk-proj-')) { 'sk-proj-' } else { 'sk-' }
$identifier = $rawInferenceKey.Substring($family.Length)
$env:LLM_API_KEY_HINT = $family + $identifier.Substring(0, 6) + '…' + $identifier.Substring($identifier.Length - 4)
$rawInferenceKey = $null
docker compose --env-file .billing.env -f docker-compose.yml -f docker-compose.billing.yml -f C:\DATA\Workspace\src\github.com\martybytes\agent007memory\docker-compose.key-hints.yml up -d
Remove-Item Env:LLM_API_KEY_HINT
```

The masked hint is safe display metadata, but it still identifies a credential family; do not
commit machine-specific hints. The complete inference key remains only in AgentMemory's environment.

For a consistent backup, stop only the console, archive its history volume, then start it again:

```bash
docker compose stop console
docker run --rm -v ts-agentmemory-console-history:/data:ro -v "$PWD":/backup alpine tar czf /backup/agent007memory-history.tgz -C /data .
docker compose start console
```

```powershell
docker compose stop console
docker run --rm -v ts-agentmemory-console-history:/data:ro -v ${PWD}:/backup alpine tar czf /backup/agent007memory-history.tgz -C /data .
docker compose start console
```

Restore only into an empty volume while the console is stopped. The volume is external, so
`docker compose down -v` does not remove it; only an explicit
`docker volume rm ts-agentmemory-console-history` does.

### Platform notes

The image is built from `node:24-alpine`, which is a multi-arch manifest with no `--platform` pin,
so Apple Silicon and arm64 Linux build natively rather than under emulation. The lockfile carries
the complete optional-dependency matrix (including the `linux-*-musl` variants of rollup,
lightningcss, and `@tailwindcss/oxide`), so `npm ci` resolves inside Alpine on both arm64 and x64.

Three things to be aware of when moving between machines:

- **`HISTORY_DB_PATH`'s dev default is relative to the working directory**
  (`.agent007memory/history.sqlite`). Running `npm start` from a different directory silently
  creates a second, empty database rather than reusing the first.
- **Keep `/data` a named volume.** SQLite runs in WAL mode, which needs `-shm` shared memory and
  POSIX advisory locks. A named volume is fine everywhere; a Docker Desktop bind mount on macOS
  (virtiofs) or an NFS share can misbehave.
- **On native Linux, a bind-mounted `/data` will fail.** The container runs as `USER node`
  (uid 1000) and Linux does not remap host uids the way Docker Desktop does, so the history worker
  gets `EACCES`. Named volumes avoid this entirely.
