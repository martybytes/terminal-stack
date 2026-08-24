# Playwright MCP

An always-running, headless [Playwright MCP](https://github.com/microsoft/playwright-mcp) server for
Claude Code, Codex, and Cursor. It runs the official Microsoft image, exposes Streamable HTTP only
on `http://127.0.0.1:8931/mcp`, and gives each MCP client an isolated in-memory browser profile.

This is the shared browser *service*. The global Playwright CLI remains host-side because it is the
fastest, lowest-token option for ordinary browser checks. Durable end-to-end suites still belong in
each application repository as a pinned `@playwright/test` dependency.

## Pin

The image is pinned to Playwright MCP `v0.0.79` and its multi-platform manifest digest. The image's
entrypoint already selects headless Chromium and disables its sandbox, which is the upstream
container default. The server is not a security boundary: it can browse reachable sites and should
remain loopback-only.

To upgrade:

1. Review the [Playwright MCP releases](https://github.com/microsoft/playwright-mcp/releases).
2. Pull the exact release: `docker pull mcr.microsoft.com/playwright/mcp:vX.Y.Z`.
3. Copy its digest from `docker image inspect ... --format '{{index .RepoDigests 0}}'` into
   `docker-compose.yml`, keeping both the tag and digest.
4. Run `docker compose config`, bring the stack up, and run `check-playwright.ps1`.
5. Rerun `../setup-playwright-agents.sh --apply` (or `..\setup-playwright-agents.ps1 -Apply`) and verify all three agent clients.

Never change the image to `latest`.

## Start and automatic startup

From the repo root:

```powershell
.\stack.ps1 -Stack playwright -Up          # preview
.\stack.ps1 -Stack playwright -Up -Apply   # create/start it
```

The service uses `restart: unless-stopped`. After the first `up`, Docker starts it whenever the
Docker daemon starts. Docker Desktop itself must have **Start Docker Desktop when you log in**
enabled. A deliberate `docker compose stop` remains stopped until explicitly started again.

Outputs are capped at 256 MiB in the container's temporary filesystem. No host browser profile,
Docker data volume, or application worktree is mounted into the container.

## Verify

The healthcheck proves that the MCP endpoint is listening. The functional check goes further: it
negotiates two independent MCP sessions, lists tools, opens Chromium, visits Example Domain,
evaluates JavaScript, verifies browser storage isolation, and closes both sessions.

```sh
cd playwright
docker compose ps          # STATUS should read "Up (healthy)"
```

| | |
|---|---|
| macOS / Linux | `./check-playwright.sh` |
| Windows | `.\check-playwright.ps1` |

Then confirm the bind. Neutral first — the mapping must read `127.0.0.1:8931->`:

```sh
docker ps --format '{{.Names}}\t{{.Ports}}'
```

| | |
|---|---|
| macOS / Linux | `lsof -nP -iTCP:8931 -sTCP:LISTEN` |
| Windows | `Get-NetTCPConnection -State Listen -LocalPort 8931 \| Select-Object LocalAddress, LocalPort` |

The container should be healthy, both functional checks should report `PASS`, and the only host
listener should be `127.0.0.1:8931`.

Agent registrations are managed globally and idempotently from the repo root:

```sh
./setup-playwright-agents.sh --apply     # Windows: .\setup-playwright-agents.ps1 -Apply
codex mcp get playwright
claude mcp get playwright
cursor-agent mcp list-tools playwright
```

All three should point at `http://127.0.0.1:8931/mcp`. Restart an already-open agent session if it
cached the old STDIO registration.

## Gotchas

- This container is for isolated, headless automation. It does not attach to a personal signed-in
  Chrome or Edge profile.
- Container `localhost` is not host `localhost`. Tests for an application running directly on the
  host should use `http://host.docker.internal:<port>`; applications in another Compose project
  need a shared Docker network or a published host port. **`host.docker.internal` is provided by
  Docker Desktop on Windows and macOS, but not by native Linux Docker Engine** — there it needs
  `extra_hosts: ["host.docker.internal:host-gateway"]` on the service that resolves it. This
  stack's compose file deliberately does not set that yet: no Linux host is in the fleet, and the
  line would also touch the Windows resolution path.
- The server is intentionally unauthenticated. Never change the host port bind from `127.0.0.1`.
- The checkout at `<workspace>/public/github.com/playwright` is upstream development source, not
  the runtime. The official pinned image is the reproducible runtime used here. That pin is a
  manifest **list** covering `linux/amd64` and `linux/arm64`, so Apple Silicon runs it natively —
  verify with `docker image inspect … --format '{{.Architecture}}'` if a session feels slow.
