# docker-local

The Docker stacks that back local tooling on my machines — one directory per stack, each with its
own compose file and README. Clone it on a new computer, run `bootstrap.sh` (or `bootstrap.ps1` on
Windows), and you get the same services on the same ports as everywhere else.

Everything here is a **local, single-host** setup on Docker Desktop, and runs on **Windows, macOS
and Linux** — every script exists as both a `.ps1` and a `.sh`, and every image is multi-arch, so
Apple Silicon runs all of them natively. Every service binds **loopback only** (`127.0.0.1`) — none
of them have authentication, and none are meant to be reachable from the LAN.

---

## Stacks

| Stack | What it is | Upstream | Pinned to | Local URL | GPU |
|---|---|---|---|---|---|
| [`agentmemory/`](agentmemory/) | Persistent memory server for AI coding agents, plus its web viewer. Backs the `agentmemory` MCP server. | [rohitg00/agentmemory](https://github.com/rohitg00/agentmemory) · engine [iii-hq/iii](https://github.com/iii-hq/iii) | npm `@agentmemory/agentmemory@0.9.29`, `iiidev/iii:0.11.2` | API [`:3110`](http://127.0.0.1:3110) bypass, or [`:3111`](http://127.0.0.1:3111) via console proxy (default profile) · viewer [`:3113`](http://127.0.0.1:3113) | no |
| ↳ `console` (same stack, default-on profile) | agent007memory — companion console: live request feed with project/agent attribution, real-time dashboard, sortable timeline. Proxies host 3111. Selectable via `COMPOSE_FILE` in `agentmemory/.env` — see `agentmemory/README.md`. | [martybytes/agent007memory](https://github.com/martybytes/agent007memory) | git SHA in `agentmemory/docker-compose.console.yml` (bump via `update-console.ps1`) | console [`:3114`](http://127.0.0.1:3114) | no |
| [`headroom/`](headroom/) | Local Headroom proxy — an OpenAI-compatible endpoint that compresses what goes to your LLM provider, plus the Qdrant vector store and Neo4j graph its semantic memory needs. | [headroomlabs-ai/headroom](https://github.com/headroomlabs-ai/headroom) · [qdrant/qdrant](https://github.com/qdrant/qdrant) · [neo4j/neo4j](https://github.com/neo4j/neo4j) | `ghcr.io/headroomlabs-ai/headroom:0.36.5`, `qdrant/qdrant:v1.17.1`, `neo4j:5.26` | proxy [`:8787`](http://127.0.0.1:8787) · dashboard [`:8787/dashboard`](http://127.0.0.1:8787/dashboard) · qdrant [`:6333`](http://127.0.0.1:6333) · neo4j [`:7474`](http://127.0.0.1:7474) | no |
| [`kokoro/`](kokoro/) | Kokoro-FastAPI text-to-speech — an OpenAI-compatible `/v1/audio/speech` endpoint plus Swagger UI. | [remsky/Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) | `ghcr.io/remsky/kokoro-fastapi-gpu:v0.8.0-cu128` | [`:8880`](http://127.0.0.1:8880) | NVIDIA (optional — CPU profile available) |
| [`playwright/`](playwright/) | Always-running, isolated headless browser automation for Claude, Codex, and Cursor over MCP. | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) | image `v0.0.79` + manifest digest | MCP [`:8931/mcp`](http://127.0.0.1:8931/mcp) | no |

`agentmemory` builds locally from its `Dockerfile`; `headroom`, `kokoro` and `playwright` pull prebuilt images.
All pin exact versions — see [`docs/conventions.md`](docs/conventions.md) for why, and each stack's
README for how to bump them.

## Browser testing for agents

The [Playwright MCP](https://github.com/microsoft/playwright-mcp) server is an always-running Docker
stack at `http://127.0.0.1:8931/mcp`. Claude Code, Codex, and Cursor share the server process but get
separate isolated, in-memory browser contexts. The token-efficient
[Playwright CLI](https://playwright.dev/docs/getting-started-cli) stays host-side for ordinary browser
work.

The setup covers Claude Code, Codex, and Cursor globally:

| | preview | install/configure and verify |
|---|---|---|
| macOS / Linux | `./setup-playwright-agents.sh` | `./setup-playwright-agents.sh --apply` |
| Windows | `.\setup-playwright-agents.ps1` | `.\setup-playwright-agents.ps1 -Apply` |

It pins `@playwright/cli@0.1.18`, installs the official `playwright-cli` skill plus this repo's
`frontend-testing` policy, and registers the Docker HTTP MCP server as `playwright` in all three
clients. CLI artifacts go under `%LOCALAPPDATA%\playwright-agents` on Windows and
`~/Library/Application Support/playwright-agents` on macOS (`$XDG_DATA_HOME` on Linux); container
artifacts are bounded and temporary. Restart open agent sessions after applying.

**Upstream checkouts are reference material, never the runtime.** The convention is
`<workspace>/public/github.com/<repo>` — `playwright` and `agentmemory` both live there. The stacks
run pinned published images or a pinned local build; nothing loads from those paths. An
`agentmemory` checkout additionally has to sit at the version this repo pins, or it answers
patch-maintenance questions with the wrong code shape; `bootstrap` warns when the two disagree.
Durable end-to-end tests still belong in each application
repository as a pinned `@playwright/test` dependency. Use Playwright's matching Docker image in CI
when Linux/browser parity is needed; do not replace committed tests with ad-hoc agent clicks.

Quick verification after restarting the clients:

```powershell
playwright\check-playwright.ps1
playwright-cli --help
codex mcp get playwright
claude mcp get playwright
cursor-agent mcp list-tools playwright
```

To upgrade the CLI, change its version constant in `setup-playwright-agents.ps1`. To upgrade the MCP
image, follow [`playwright/README.md`](playwright/README.md). Review upstream release notes and never
change either pin to `latest`.

`agentmemory` has one **optional** external dependency: its enabled LLM features call a remote
chat-completions endpoint. AgentMemory speaks the OpenAI wire protocol, so which provider serves that
endpoint is a configuration choice, not a code path:

- **vLLM on lambda-dual** — the current provider. `qwen3-8b-awq` over the LAN, one model for
  change-aware summaries, incremental knowledge-graph extraction, and daily-bounded consolidation.
  No cost, but a **16,384-token context**, which is what every prompt bound in that stack is sized
  against — every prompt is bounded by its family's limit and by a provider-wide input ceiling.
  Per-observation compression is on and costs nothing.
- **OpenAI API** — a documented one-file rollback, with `gpt-5.6-luna` for compression and
  `gpt-5.6-terra` for everything else, plus project-scoped cost reconciliation.

Semantic search calls neither — embeddings run on-device inside the container — so the stack still
starts and searches offline while durable LLM jobs wait for the endpoint. The provider gate admits at
most three calls concurrently. Endpoint setup, the three traps that bite when switching providers,
key rotation, billing, queue recovery, rollback, and measured costs are all documented in
[`agentmemory/README.md`](agentmemory/README.md).

## New machine

Full runbook: **[`docs/new-machine.md`](docs/new-machine.md)**, which starts by sending you to your
platform's prerequisites — [Windows](docs/new-machine-windows.md) (Docker Desktop + WSL 2, NVIDIA)
or [macOS](docs/new-machine-macos.md) (Docker Desktop, VM resources, the container→tailnet check).

The short version, once the prerequisites are done:

```sh
git clone git@github.com:martybytes/docker-local.git
cd docker-local
```

| | preview | apply |
|---|---|---|
| macOS / Linux | `./bootstrap.sh` | `./bootstrap.sh --apply` |
| Windows | `.\bootstrap.ps1` | `.\bootstrap.ps1 -Apply` |

Then edit three gitignored files in your editor: repo-root `.env` for the LLM provider key (vLLM,
or an API-billed OpenAI key), `headroom/.env` for its two generated secrets, and `kokoro/.env` for
the hardware profile bootstrap named.

| | |
|---|---|
| macOS / Linux | `./stack.sh --up --apply` then `./setup-playwright-agents.sh --apply` then `./stack.sh --status` |
| Windows | `.\stack.ps1 -Up -Apply` then `.\setup-playwright-agents.ps1 -Apply` then `.\stack.ps1 -Status` |

## Day to day

`stack.sh` / `stack.ps1` drive every stack from the repo root. Read-only actions run immediately;
`--up` and `--down` preview unless you add `--apply`. The flags map one-to-one between the two, so
the `.ps1` form is the same commands with `-Up`, `-Apply`, `-Stack` and so on.

```sh
./stack.sh                                   # list: state + which compose files each stack merges
./stack.sh --status                          # docker compose ps for each stack
./stack.sh --up --apply                      # start everything
./stack.sh --down --apply                    # stop everything (volumes and images are kept)
./stack.sh --stack kokoro --logs --follow    # tail one stack
```

Or work inside a single stack directory with plain `docker compose up -d` / `down` / `logs -f` —
nothing here wraps or hides Docker, and the compose files are ordinary files you can run by hand.

## How per-machine differences are handled

The point of this repo is that **tracked files are identical on every computer**. Anything that
varies by machine lives in a gitignored `.env`, seeded from a committed `.env.example`:

- **`kokoro`** needs a CUDA build matched to your GPU generation, and won't start at all on a
  machine with no NVIDIA runtime. Its `.env` selects one of three profiles — Blackwell (RTX
  50-series), pre-Blackwell, or CPU-only — by setting `KOKORO_IMAGE` and choosing whether
  `docker-compose.gpu.yml` is merged in. Bootstrap detects your card and tells you which to pick —
  on a Mac the answer is always Profile C, because Docker Desktop for Mac has no GPU passthrough of
  any kind. See [`kokoro/README.md`](kokoro/README.md).
- **`agentmemory`** reads its LLM provider credential from repo-root `.env` — which loads *second*,
  so it is the only place that credential can win — and non-secret stack settings, including the
  endpoint and model, from `agentmemory/.env`. Its data volume is declared `external: true`, so the
  name is stable; bootstrap creates it when needed. Codex OAuth is not used by this background
  service.
  Optional console billing adds a third, generated file, `agentmemory/.billing.env` — project
  identifiers, the Admin key's host path, and masked key fingerprints, never key material.
- **`headroom`** needs two secrets in `headroom/.env` before it will start at all, because Compose
  interpolates them before anything runs — it cannot generate them in-container the way
  `agentmemory` generates its HMAC. Its host ports are all `${VAR:-default}`, since 6333, 7474 and
  7687 are popular defaults likely to collide. See [`headroom/README.md`](headroom/README.md).
- **Scripts, not stacks.** Every script ships twice — `foo.ps1` and `foo.sh` — with flags mapping
  one-to-one. That is itself a per-machine difference handled in tracked files rather than in
  `.env`, and `tests/test_script_parity.py` keeps the two sets honest.

## Conventions

Every stack in this repo follows the same rules — loopback-only binds, a healthcheck, rotated logs,
pinned versions, a README naming its upstream. The full checklist for adding a new stack is in
[`docs/conventions.md`](docs/conventions.md).

**No secrets are stored in this repo**, and none should be. `.env` files are gitignored;
`.env.example` files are tracked and contain placeholders only. AgentMemory's provider key lives
in repo-root `.env`; its HMAC secret is generated inside the container and persists on the Docker
volume. Headroom's two secrets are generated by you into `headroom/.env`. If a credential ever needs to live in version control, `docs/conventions.md` records the
approach to use.

## Related repos

- **[`claude-local`](https://github.com/martybytes/claude-local)** — Windows tooling and runbooks for
  the Claude Code setup that consumes these services. Notably
  `tools/windows/diagnostics/gpu-tts-diagnose.ps1` and `gpu-tts-quiet.ps1`, which diagnose and
  mitigate GPU contention between `kokoro` and the desktop compositor, and
  `docs/windows/cursor-stall-gpu-tts-runbook.md`. Those tools find the container by the literal name
  `kokoro`, which is why `container_name` is pinned in the compose file.
  `tools/windows/system/setup-kokoro-docker.ps1` there is the same script as `kokoro/setup-kokoro-docker.ps1`
  here — a deliberate copy; changes need porting both ways. All of that is Windows-and-NVIDIA
  material; `kokoro/setup-kokoro-docker.sh` has no third copy.
- **[`terminal-stack`](https://github.com/martybytes/terminal-stack)** — owns the *client* side of
  agentmemory: which hooks each agent registers, what they run, and the environment they carry
  (`bootstrap/ts-agentmemory.ps1`). That wiring deliberately does not live here. It is
  **PowerShell-only today**, so on macOS and Linux this repo's agentmemory stack serves and searches
  but never captures — `agentmemory/check-capture.sh` reports exactly that and exits non-zero.
