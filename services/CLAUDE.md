# CLAUDE.md

## What this repo is

Docker stacks for local tooling on Windows, macOS and Linux with Docker Desktop. One directory per stack, each with its
own compose file and README. `agentmemory` (memory server: API 3111 via the console proxy, bypass
3110, stock viewer 3113, console UI 3114), `headroom` (LLM proxy 8787 + Qdrant 6333/6334 + Neo4j
7474/7687), `kokoro` (TTS, port 8880) and `playwright` (browser MCP, port 8931). It's a
documentation repo as much as a config repo — the READMEs are the deliverable, not an afterthought.

Read [`docs/conventions.md`](docs/conventions.md) before adding or changing a stack. It has the
full rules and an add-a-stack checklist.

## Non-negotiables

- **Host ports bind `127.0.0.1` explicitly.** `"127.0.0.1:8880:8880"`, never `"8880:8880"`. None of
  these services authenticate; the bare form puts them on the LAN.
- **Never commit a `.env`.** `.env` is gitignored, `.env.example` is tracked and holds only
  non-sensitive defaults. No secrets in this repo, ever.
- **Tracked files are identical on every machine.** Anything machine-specific — GPU generation,
  ports — goes in `.env`. If you find yourself editing tracked YAML to make one computer work, that's
  the bug.
- **Pin versions.** No `:latest`, no unpinned packages in a Dockerfile. Comment non-obvious pins.
- **Scripts preview by default.** `-Apply` / `--apply` to write; destructive modes still need it.
  Reuse the `Section` / `Step` / `Info` / `Warn` / `Have` helpers and `[would]` / `[DO]` output —
  from `_common.sh` on the `.sh` side, copied from `bootstrap.ps1` on the `.ps1` side.
- **Every script exists twice** (`foo.ps1` + `foo.sh`), flags mapping one-to-one. Changing one
  without the other is the bug — `tests/test_script_parity.py` fails on it. Deliberate differences
  go in the divergence register in `docs/conventions.md`, which the test reads.

## Working here

```sh
./bootstrap.sh [--apply]                                                  # macOS / Linux
./stack.sh [--list|--status|--up|--down|--logs] [--stack <name>] [--apply]
```

```powershell
.\bootstrap.ps1 [-Apply]                                                 # Windows
.\stack.ps1 [-List|-Status|-Up|-Down|-Logs] [-Stack <name>] [-Apply]
```

`stack.sh`/`stack.ps1` find stacks by looking for `docker-compose.yml` in top-level directories —
no registry to update. `kokoro`'s `.env` sets `COMPOSE_FILE`, so which files merge depends on the machine
profile; use `docker compose config` in the stack directory to see what actually resolves.

## Verifying

"Up" is not evidence a service works — `kokoro` crash-loops while reporting `Up` when the CUDA build
doesn't match the GPU. Always verify functionally: hit the endpoint, check the response. Each stack
README has a verification section; use those commands.

After any change touching ports:

```sh
docker ps --format '{{.Names}}\t{{.Ports}}'    # every mapping must read 127.0.0.1:<port>->
```

| | |
|---|---|
| macOS / Linux | `lsof -nP -iTCP:3110,3111,3112,3113,3114,6333,6334,7474,7687,8787,8788,8880,8931 -sTCP:LISTEN` |
| Windows | `Get-NetTCPConnection -State Listen -LocalPort 3110,3111,3112,3113,3114,6333,6334,7474,7687,8787,8788,8880,8931 \| Select-Object LocalAddress, LocalPort` |

Every listener must be `127.0.0.1`. Note `lsof` prints nothing and exits 1 on no match, which looks
exactly like a typo.

## Gotchas that have already cost time

- **macOS/Linux:** host reachability is not evidence a **container** can reach the same address.
  agentmemory dials vLLM over Tailscale from inside a container, whose egress is a separate path.
  Test it from a container (`docker run --rm curlimages/curl:8.14.1 -sS -o /dev/null -w '%{http_code}'
  --max-time 8 <url>`) before trusting an endpoint. Measured here: it works, and MagicDNS resolves
  from a container too — but the `.env` uses the `100.x` tailnet IP, which depends on neither.
- **macOS/Linux:** `/bin/bash` is 3.2 and always will be. Every `.sh` here is bash-3.2 clean, and
  the parity test enforces it. Two traps that bite silently under `set -euo pipefail`:
  `cmd | head -c N` makes `cmd` take SIGPIPE and exit 141, which `set -e` turns into a wordless
  death; and `cmd | grep -q` reports the pipeline as *failed* on a match for the same reason.
  Capture first, match in the shell.

- `headroom`'s proxy token is **not** your provider API key, and confusing them looks like a broken
  proxy. The proxy forwards the `Authorization` header upstream, so sending the proxy token to
  `/v1/chat/completions` gets you past headroom and then a 401 from your provider reading
  `Incorrect API key provided: ...`. Tell them apart by the body: `{"error":"unauthorized"}` is
  headroom refusing you; anything naming an API key is upstream. Detail in `headroom/README.md`.
- `headroom` needs **both** secrets in `headroom/.env` before it will start — unlike `agentmemory`,
  which generates its HMAC in-container on first boot. Compose interpolates them, so a missing one
  fails at `docker compose config` naming the variable rather than starting an open data plane.
- `headroom`'s Neo4j sizes its heap from host RAM unless bounded, which is wrong inside a Docker VM
  shared with `agentmemory` and `kokoro`. `NEO4J_HEAP` / `NEO4J_PAGECACHE` hold it to ~800 MB.
- `kokoro` on RTX 50-series (Blackwell) needs the `cu128` image. `:latest` is `cu126`, starts fine,
  then crash-loops on the first synthesis. Detail in `kokoro/README.md`.
- `agentmemory`'s volume is `external: true` — `bootstrap.sh`/`.ps1` creates it. `docker compose up`
  without that fails with `external volume ... not found`.
- `agentmemory`'s viewer must bind `0.0.0.0` *inside* the container. This is true on **every**
  platform, not just WSL2: a container-internal loopback bind is unreachable through any published
  port mapping, because the forwarder connects to the container's bridge address rather than its
  loopback. Safe here because the host side is loopback-only.
- `entrypoint.sh` rewrites the container's `iii-config.yaml` on every start. Editing it inside a
  running container does nothing — change the heredoc and rebuild.
- `kokoro/setup-kokoro-docker.ps1` is a deliberate copy of the same script in the `claude-local`
  repo (`tools/windows/system/`). Changes need porting both ways. Its `.sh` twin has no third copy.
- Host 3111 is the **console proxy** (agent007memory), not agentmemory itself. If 3111 is dead,
  check the bypass `3110` first to tell a console failure from an agentmemory failure. The console
  is deployed by SHA pin via `agentmemory/update-console.sh` (or `.ps1`), never by editing the context
  by hand.
- The console is a `.env`-selected profile, not baked into `agentmemory/docker-compose.yml` — that
  file is agentmemory alone; `docker-compose.console.yml` adds the console, chosen via `COMPOSE_FILE`
  in `agentmemory/.env` (same mechanism as `kokoro`'s GPU profile). Default is with-console. Without
  it, 3111/3114 don't exist and MCP clients use the bypass `3110` instead. See `agentmemory/README.md`.
- `agentmemory` now takes inference from **vLLM on lambda-dual** (`qwen3-8b-awq`, 16,384-token
  context), not the OpenAI API. Three things bite when moving between providers. `OPENAI_REASONING_EFFORT`
  is truthy-checked, so the OpenAI value `none` is *not* "off" — it puts `reasoning_effort: "none"`
  on every vLLM request; set it **empty**. `SUMMARIZE_CHUNK_SIZE` is the only real prompt bound
  (nothing truncates a single observation, and `AGENTMEMORY_SUMMARY_MAX_OBSERVATIONS` caps count, not
  size), so `250` — sized for a 65,536-token endpoint — overflows 16,384; it is `25` here, ~5.1k peak
  measured. And `VLLM_MAX_TOKENS=16384` is a *context* length: copying it into `MAX_TOKENS` would
  request the whole context as output. The provider credential must change in the **repo-root** `.env`,
  which loads second and therefore wins.
- `agentmemory`'s consolidation **reports success while failing**. The `reflect` stage built its
  prompt from every fact, lesson, and untruncated narrative in a concept cluster — no caps, and
  `SUMMARIZE_CHUNK_SIZE` does not apply to it — then swallowed the provider error in a bare
  `catch {}`. A 26k-token prompt against a 16,384 context logged
  `reflect: {"newInsights":0,"success":true}` and nothing else. **A consolidation run with
  `newInsights: 0` is the signature of a rejected prompt, not a quiet day**; confirm with
  `promptChars` and a sub-100ms `providerLatencyMs` in `llm/telemetry`. Now bounded by
  `AGENTMEMORY_REFLECT_MAX_*` (relevance-first) with `AGENTMEMORY_LLM_MAX_INPUT_CHARS` as a
  provider-wide ceiling, and the catch logs. Bound by relevance *before* truncation, or the ceiling
  discards the best facts. Note the concept list is its own cost: 673 concept names were 17.5k of a
  25.5k-char prompt even after facts were capped.
- `agentmemory`'s billing deploy needs **both** env files, stack `.env` first:
  `docker compose --env-file .env --env-file .billing.env -f docker-compose.yml -f docker-compose.console.yml -f docker-compose.billing.yml up -d`.
  A lone `--env-file .billing.env` *replaces* `.env` as compose's interpolation source, so every
  `${OPENAI_*}`-derived `LLM_*` mirror the console displays resolves to `""` — blank provider/model
  panel, no error, everything healthy. `update-console.ps1` handles this; hand-typed commands don't.
- `agentmemory` can stop **capturing** while every read-path check passes — healthy API, closed
  circuit breaker, MCP searches still returning hits. Verify with
  `agentmemory/check-capture.sh --apply` (or `.ps1 -Apply`), or check the newest
  `Observation captured` log line. The
  usual cause is the plugin's `plugin.json` pointing at `hooks/hooks.copilot.json` instead of
  `hooks/hooks.json`, which registers no hooks at all; a plugin update silently reverts the fix.
  Detail in `agentmemory/README.md`.
