# agentmemory

Local [agentmemory](https://github.com/rohitg00/agentmemory) server — persistent memory for AI
coding agents, backing the `agentmemory` MCP server.

**The agent007memory console is a selectable profile, not always-on.** `docker-compose.yml` is
agentmemory alone. The agent007memory console that used to merge in here as an overlay is now
its own stack and its own compose project, `services/stacks/agent007memory/` — it joins this
stack's network (`ts-agentmemory-net`) and mounts this stack's data volume read-only for the
HMAC secret. (The overlay mechanism itself is unchanged and still used by kokoro, same as
`../kokoro`'s hardware profile). **With console** (default, in `.env.example`) is what most setups
want. **Without console**: agentmemory is still fully usable, just without the proxy/UI — see the
table below for exactly what moves. No local clone of `agent007memory` is needed either way; Docker
pulls it directly from the pinned GitHub SHA in the console service's build context.

| | URL | Notes |
|---|---|---|
| HTTP API | **`http://127.0.0.1:3111`** *(with-console only)* | Liveness at `/agentmemory/livez`. This is what MCP clients talk to when the console is deployed. Port 3111 is published by the `console` service, an **agent-aware proxy** in front of agentmemory — same API responses, plus project/agent attribution and a live request feed. |
| Console | **`http://127.0.0.1:3114`** *(with-console only)* | [agent007memory](https://github.com/martybytes/agent007memory) — compact watch overview, live project/LLM/cost activity, guarded operations, detailed help, one-year aggregate reports, live requests, timeline, memories, and system health. Runs as the `console` service, container-named `agent007memory` (not the Compose default `agentmemory-console-1`) — look for that name in `docker ps`. |
| API bypass | **`http://127.0.0.1:3110`** *(always)* | agentmemory's API **directly**. With the console deployed, this is the first diagnostic when 3111 misbehaves: if 3110 answers and 3111 doesn't, the console is the problem, not agentmemory. Without the console, this is the **only** way in — point MCP clients here instead of 3111. |
| Viewer | **`http://127.0.0.1:3113`** *(always)* | Stock web UI for browsing what's stored (kept alongside the console, when present). |
| Streams | **`ws://127.0.0.1:3112`** *(always)* | `iii-stream`. The viewer's live WebSocket. **Required** — see below. The console, when deployed, subscribes to the same stream server-side over the compose network. |

Without the console: no console UI, no per-host `/_agent/<name>` MCP-client attribution, and no
OpenAI billing sync (all console-only features, described further down). Nothing about agentmemory
itself changes — same healthcheck, same data volume, same environment.

**3112 is not optional.** The viewer opens a live WebSocket to `ws://localhost:3112`; if that port
isn't published the UI never finishes loading — it sits on **"Connecting" and reloads every few
seconds** — even though the REST API on 3111 answers perfectly and the container reports healthy.
The failure looks like a broken backend and isn't. If you need to change it, change the `ports:`
mapping, not the port inside `entrypoint.sh`.

Unlike `../kokoro`, this stack **builds locally** from the `Dockerfile` here rather than pulling a
prebuilt image. Bootstrap seeds `agentmemory/.env` for non-secret settings and repo-root `.env` for
the LLM provider credential.

## Quick start

```powershell
docker compose up -d --build   # first run: builds the image, then starts
docker compose ps              # confirm "Up (healthy)"
docker compose logs -f         # watch startup / debug
docker compose down            # stop + remove the container (volume and image stay)
```

`../bootstrap.sh --apply` (or `..\bootstrap.ps1 -Apply`) must have run at least once on this machine first — see
[the volume section](#the-data-volumes-are-external-on-purpose) below.

---

## What's pinned, and how to bump it

Three build args in `docker-compose.yml` pin the agentmemory service, and the `console` service
is pinned by a git commit SHA in its build context. Nothing floats on `:latest`:

| Pin | Current | What it pins |
|---|---|---|
| `AGENTMEMORY_VERSION` | `0.9.29` | the npm package `@agentmemory/agentmemory` |
| `III_VERSION` | `0.11.2` | the `iiidev/iii` image the `iii` engine binary is copied out of |
| `III_SDK_VERSION` | `0.11.2` | the `iii-sdk` npm package |
| console image | `services/stacks/agent007memory/` | the console is its own stack now, built from `services/console/` in this repo. `tstack services up agent007memory --build` rebuilds it. |

The `iii-sdk` pin is the non-obvious one. `Dockerfile:18` writes a `package.json` at build time
containing an npm `overrides` block, purely to force `iii-sdk` to `III_SDK_VERSION` — otherwise npm
resolves whatever the agentmemory package's own range allows, and the SDK can drift out of step with
the `iii` engine binary copied from the `iiidev/iii` image. **`III_VERSION` and `III_SDK_VERSION`
should move together.**

To bump:

```powershell
# see what's available
npm view @agentmemory/agentmemory version
npm view iii-sdk versions --json

# edit the three args in docker-compose.yml, then
docker compose build --no-cache
docker compose up -d
```

Then run the [verification checks](#verify-its-actually-working) — a mismatch between the engine and
the SDK typically shows up as the container starting and then failing its healthcheck, not as a
build error.

---

## The data volumes are `external` on purpose

`docker-compose.yml` declares:

```yaml
volumes:
  ts-agentmemory-data:
    external: true
  ts-agentmemory-console-history:
    external: true
```

`external: true` means Compose will **use** the volumes but never **create** them. The upside: their
names are stable on every machine, with no project-name prefix and no per-machine edit. The cost:
something has to create them first — `..\bootstrap.ps1` creates both. `update-console.sh --apply`
also creates `ts-agentmemory-console-history` when deploying to an existing machine.

Skip bootstrap on a new machine and `docker compose up` fails immediately with an external-volume
error. That's the intended failure: loud, not silent.

The volume holds everything that matters — `state_store.db` (the memories themselves),
`stream_store`, and `.hmac`. Back it up before anything destructive:

```powershell
# tar the volume into the current directory
docker run --rm -v ts-agentmemory-data:/data -v ${PWD}:/backup alpine tar czf /backup/agentmemory-data.tgz -C /data .

# restore into a fresh volume
docker volume create ts-agentmemory-data
docker run --rm -v ts-agentmemory-data:/data -v ${PWD}:/backup alpine tar xzf /backup/agentmemory-data.tgz -C /data
```

`docker compose down` never touches it. `docker volume rm ts-agentmemory-data` does, and there is
no undo.

`ts-agentmemory-console-history` is separate and contains only the console's SQLite database and WAL files.
It retains one year of aggregate request/project/agent, observation, LLM provider/model/family token
and estimated-cost counters, authoritative daily provider costs, and process counts for
the Reports page. It contains no prompts, responses, request bodies, paths, memory content,
session IDs, or individual activity rows. Back it up with the console stopped so the files form a
consistent snapshot:

```powershell
docker compose stop console
docker run --rm -v ts-agentmemory-console-history:/data:ro -v ${PWD}:/backup alpine tar czf /backup/agent007memory-history.tgz -C /data .
docker compose start console
```

Restore only while `console` is stopped and only into an empty history volume. Like the main data
volume, it survives rebuilds, recreates, and `docker compose down -v`; explicit removal has no undo.

---

## The HMAC secret

`entrypoint.sh` generates `AGENTMEMORY_SECRET` on first boot only — `openssl rand -hex 32` written
to `/data/.hmac` with mode 600, then read back and exported into the CLI's environment on every
subsequent start. It lives on the volume, never in this repo.

Two things worth knowing about it:

1. **It is printed to stdout exactly once**, on the boot that generates it, inside a banner saying
   "Copy this value now. It will not be printed again." True of the banner, not of the secret — it's
   still in `/data/.hmac` and you can read it back at any time:

   ```powershell
   docker compose exec agentmemory cat /data/.hmac
   ```

2. **That one-time print lands in the container's logs.** This stack uses the `json-file` driver
   with `max-size: 10m` / `max-file: 3`, so the secret stays recoverable via `docker logs` until
   enough output accumulates to rotate it out — on a quiet container, potentially a long time. If
   that matters, rotate after first boot.

**To rotate:** delete the file on the volume and restart. A new secret is generated and printed.

```powershell
docker compose exec agentmemory rm /data/.hmac
docker compose restart
docker compose logs --tail 20   # the new secret is in the banner
```

Anything holding the old secret needs updating. The **console is not on that list**: it mounts the
data volume read-only (`/upstream-data/.hmac`) for its own API calls and re-reads the file whenever
it gets a 401, so rotation self-heals — no secret in any tracked file or `.env`. Proxy traffic is
unaffected either way; the console passes each caller's own bearer through untouched.

---

## Connecting an MCP client

Every MCP client needs the HMAC secret above as a bearer token and its own tagged base URL through
the console proxy. It also needs **`AGENTMEMORY_INJECT_CONTEXT=true` in its own environment** — set
it once as a **User** environment variable, alongside `AGENTMEMORY_SECRET`, and every agent inherits
it:

```powershell
[Environment]::SetEnvironmentVariable('AGENTMEMORY_INJECT_CONTEXT','true','User')
```

That flag is read in two independent places — the server (`dist/index.mjs`) and, separately, each
agent's own hook process (`session-start.mjs` and `pre-tool-use.mjs` both test
`process.env["AGENTMEMORY_INJECT_CONTEXT"] === "true"`). Setting it only in `.env` configures the
server and leaves every client write-only: capture keeps working, retrieval never fires, and the
only symptom is that agents never seem to look anything up. Nothing is logged, and
`check-capture.sh` section A reports the hooks as correctly wired, because they are — they just
return early. Section E now checks the read path for exactly this reason.

Env vars reach a process only at launch, so restart Claude Code, Codex and Cursor afterwards.

| Host | `AGENTMEMORY_URL` | Configuration |
|---|---|---|
| Claude Code | `http://localhost:3111/_agent/claude` | terminal-stack `bootstrap/ts-agentmemory.ps1` |
| Codex | `http://localhost:3111/_agent/codex` | same, plus the MCP env in `~/.codex/config.toml` |
| Cursor | `http://localhost:3111/_agent/cursor` | same |

All three are wired by **terminal-stack**, from every `tstack update` / `chezmoi apply`. See
"Client wiring is terminal-stack's" below.

The console strips `/_agent/<host>` before forwarding, displays the host in Live Requests, and
adds AgentMemory's existing `agentId` metadata to session-start and explicit-memory writes.
Observations inherit the session's agent, so Sessions, Timeline, and Memories retain provenance
after the console restarts. Existing or direct/untagged traffic remains valid and appears as
`Unknown`. Global endpoints such as liveness, MCP tool discovery, and unscoped search have no
project/session metadata and appear under project `Global` rather than as an empty cell. Port 3110
is a diagnostic bypass and must not be used for tagged client configuration.

All three hosts use the same bridge, [`@agentmemory/mcp`](https://www.npmjs.com/package/@agentmemory/mcp)
— a stdio process launched via `npx` that translates MCP tool calls into HTTP calls against the
REST API. Client wiring is **user-scoped, global config on the machine**, deliberately outside
version control, so the same setup applies to every project without per-repo configuration.

### Claude Code

Handled entirely by the `agentmemory@agentmemory` Claude Code plugin (installed via Claude Code's
plugin manager, cached at `~/.claude/plugins/cache/agentmemory/agentmemory/<version>/`). It ships
the MCP server registration *and* a full set of lifecycle hooks (session start/end, every tool use,
prompt submission, ...) that capture memories automatically. Nothing to configure here beyond
installing the plugin and making sure `AGENTMEMORY_SECRET` is set as a **User** environment variable
— the plugin's `.mcp.json` reads it via `${AGENTMEMORY_SECRET:-}`. Also merge this top-level entry
into `~/.claude/settings.json`:

```json
{
  "env": {
    "AGENTMEMORY_URL": "http://localhost:3111/_agent/claude"
  }
}
```

Or don't do it by hand at all: **terminal-stack owns the client wiring now.**
`bootstrap/ts-agentmemory.ps1` in that repo sets this env block, patches the hook scripts,
and registers the hooks for all three hosts — and it runs from every `tstack update` /
`chezmoi apply`, which matters because a plugin upgrade replaces the vendor caches and
silently reverts the hook-script edits. `tstack doctor` reports that condition; the sync fixes
it. Nothing here needs doing per host.

That split is deliberate: which hooks exist, what they run, and what environment they carry
is a terminal-stack concern, because that repo already manages `~/.claude/settings.json`,
`~/.cursor/hooks.json` and `~/.codex/**`. This repo is the server.

Restart Claude Code (or reload MCP) after changing it.

### Codex

Codex forwards the AgentMemory MCP table's environment to the stdio bridge, but plugin lifecycle
hooks do not inherit `shell_environment_policy.set`. Merge the tagged URL into the MCP environment
in `~/.codex/config.toml`:

```toml
[mcp_servers.agentmemory.env]
AGENTMEMORY_URL = "http://localhost:3111/_agent/codex"
```

The hook side — patching the six scripts the plugin references, and registering the same six for
Codex Desktop in `~/.codex/hooks.json` — is terminal-stack's `bootstrap/ts-agentmemory.ps1`. It
never edits `hooks.codex.json`, so Codex's existing hook trust hashes stay valid.

The plugin cache is versioned, so an AgentMemory plugin upgrade reverts those edits — that is
why the wiring re-applies from every sync instead of being a command you remember to run. Existing
Codex sessions invoke the scripts afresh for each hook and pick up the change on their next event;
restart Codex only when the MCP configuration itself changed. `shell_environment_policy.set` can
still carry the same URL into Codex shell commands, but it is not the hook configuration path.
Codex Desktop reads `~/.codex/hooks.json`; the second script merges stable copies of the six plugin
hooks there without replacing unrelated user hooks. Rerun it after a plugin upgrade and restart the
desktop app.

### Cursor

Cursor has no equivalent plugin package for agentmemory, so the same two pieces — MCP registration
and capture hooks — have to be wired into Cursor's own global config by hand:
`~/.cursor/mcp.json` (MCP servers) and `~/.cursor/hooks.json` (hooks), both of which apply across
every Cursor project on the machine, matching how the Claude Code plugin is user-scoped rather than
per-repo.

terminal-stack's `bootstrap/ts-agentmemory.ps1` does this — the MCP server entry, the hook
scripts, and the seven hook registrations — from every sync.

It requires the Claude Code `agentmemory` plugin to already be installed, since that plugin's cache
is the only place the hook scripts exist — agentmemory ships no separate Cursor package to pull them
from. The script copies the 7 scripts Cursor actually needs (session start/end, prompt submit,
pre/post tool use, tool failure, stop) into a Cursor-owned `~/.cursor/hooks/agentmemory/`, rather
than pointing at the Claude plugin's *versioned* cache path directly — that path moves on every
plugin update, which would otherwise silently break the hooks the next time `agentmemory` updates.

Two syntax differences from the Claude Code side, both handled by the script:

- Cursor's env-var interpolation in `mcp.json` is `${env:VAR}`, not Claude Code's `${VAR:-default}`
  shell-style syntax — no fallback-default support, so an unset `AGENTMEMORY_TOOLS` is left out of
  the config entirely rather than interpolated to an empty string.
- The hook scripts read `AGENTMEMORY_SECRET` straight from `process.env`, so as long as it's set as
  a **User** environment variable (the script sets it for you if it isn't, by reading it back from
  the running container's `/data/.hmac`), both the MCP server and the hooks pick it up the same way.
- Cursor does not expose the MCP server's `env` block to hook subprocesses. The script therefore
  sets the Cursor-tagged `AGENTMEMORY_URL` in each owned hook command as well as in `mcp.json`.

The script is idempotent and merges rather than overwrites — re-running it, or running it on a
machine that already has other MCP servers or hooks configured, only ever touches the `agentmemory`
entries. `-Undo -Apply` removes exactly those entries and nothing else. After `-Apply`, restart
Cursor, then check **Settings → MCP** (`agentmemory` shows connected) and **Settings → Hooks** (7
hooks loaded).

---

## Client wiring is terminal-stack's

Everything about *which hooks exist, what they run, and what environment they carry* lives in
**terminal-stack** (`bootstrap/ts-agentmemory.ps1` over `bootstrap/_agentmemory.ps1`), not here.
That repo already manages `~/.claude/settings.json`, `~/.cursor/hooks.json` and `~/.codex/**`, and
carries the merge helpers that stop agentmemory's hook entries being clobbered by its own sync. It
used to live here purely because the compose file was next door.

What that buys: the wiring re-applies from every `tstack update` / `chezmoi apply`, so a plugin upgrade
— which replaces the vendor caches and silently reverts every hook-script edit — repairs itself
instead of needing a command nobody remembers. `tstack doctor` reports the condition, and
`tstack agentmemory -Check` is the detailed version.

This repo keeps the server: image, compose, `.env`, the in-container bundle patches
(`patch-agentmemory.mjs`), the data migrations, and the console pin. `check-capture.sh` checks
that half.

### On macOS and Linux, client wiring has no owner yet

`bootstrap/ts-agentmemory.ps1` is PowerShell and Windows-only, and the hook commands it generates
use cmd.exe's `set X=…&&` prefix, which no Unix shell understands. Until terminal-stack grows a
macOS/Linux path, **this stack will serve and search but never capture** on those platforms: the
server is healthy, MCP tools resolve, searches return hits, and no observation is ever written.

That is exactly the silent failure documented in "None of the above proves memories are being
*captured*" below — so expect it here rather than diagnosing it. `check-capture.sh` detects the
missing entry point, reports it as a failure rather than a skip, and exits non-zero.

The fix belongs in terminal-stack, not here. It needs:

- a `.sh` twin of `bootstrap/ts-agentmemory.ps1` (and of `_agentmemory.ps1` and
  `_merge_json_settings.ps1`, which it sources);
- POSIX `VAR=value node …` prefixes in the generated hook commands instead of the cmd.exe chain;
- the secret and `AGENTMEMORY_INJECT_CONTEXT` exported from **`~/.zshenv`**, not `~/.zshrc` — hook
  subprocesses are non-interactive, so `~/.zshrc` is never sourced for them and a variable set
  there reaches nothing and logs nothing;
- `launchctl setenv` plus a `~/Library/LaunchAgents/` plist for GUI-launched Cursor and Codex
  Desktop, which inherit from `launchd` and read neither shell file;
- the stale-secret recovery edit re-pointed: its Windows form re-reads the authoritative value with
  `reg query "HKCU\Environment"`, which on Unix throws, is caught, and leaves the recovery a
  permanent no-op.

Note also that `tstack agents` already handles the *plugin install* half in bash — it is only the
hook wiring that is missing.

## Retrieval: how each host asks

Capture and retrieval are separate paths and fail separately. For a long time every host
captured perfectly and none of them ever asked, which looks identical to an empty store —
`check-capture.sh` sections A–D all passed throughout.

| Host | Route it uses | Trigger |
|---|---|---|
| Claude Code | `POST /agentmemory/enrich` | `pre-tool-use.mjs`, on a tool carrying a structured file path |
| Codex | `POST /agentmemory/context` | `prompt-submit.mjs`, once per prompt — see below |
| Cursor | `POST /agentmemory/session/start` | `session-start.mjs`, plus `enrich` on file tools |

`GET /agentmemory/memories` is also captured, but **GET volume is not a retrieval-health
metric**: the hooks retrieve over POST. Judge retrieval by the routes above.

### Why Codex retrieves on the prompt, not the tool call

Codex emits `Bash` for most tool calls. The vendor `pre-tool-use.mjs` allow-lists
`edit/write/create/read/view/grep/glob` and additionally returns early unless it can pull a
structured path out of the tool input — so for Codex it fired essentially never, and widening
the hook's matcher alone changes nothing.

A shell command is not a safe source of file paths. Parsing `rg foo src/` or a piped
one-liner to guess what will be read means inspecting and potentially storing arbitrary
command text, and getting it wrong either way. So `Bash` and its siblings are **deliberately
excluded** from the path-based route, and Codex retrieves at the prompt instead:
`/agentmemory/context` needs only `{ sessionId, project }`, no paths at all. The prompt is
input the user actually wrote, it is already being captured, and one lookup per turn is the
right granularity anyway.

The tool filter is inverted rather than extended: instead of enumerating tool names Codex
might emit, `pre-tool-use.mjs` now denies a fixed shell family
(`bash`, `shell`, `sh`, `cmd`, `powershell`, `pwsh`, `exec`, `local_shell`, `run_command`,
`terminal`) and lets everything else through to the existing "no structured path, no request"
rule. A tool name nobody predicted costs nothing, and no command string is ever read.

### Retrieval is on unless you turn it off

`AGENTMEMORY_INJECT_CONTEXT` is read by each hook **in its own process**, and a User
environment variable only reaches processes started after it was set. Long-running shells and
desktop apps therefore kept launching hooks without it, and every one returned early — with
nothing logged, because that is the hook's designed no-op.

Two things fix that, and the setup scripts do both:

- The gate now reads `!== "false"`, so retrieval defaults on. Set
  `AGENTMEMORY_INJECT_CONTEXT=false` to disable it deliberately.
- Generated hook commands inline the value rather than inheriting it. Codex Desktop's
  `~/.codex/hooks.json` and Cursor's `~/.cursor/hooks.json` commands both carry
  `set AGENTMEMORY_URL=…&& set AGENTMEMORY_INJECT_CONTEXT=true&& node …`; Claude Code gets the
  same pair in `~/.claude/settings.json`'s `env`, which it injects into hook processes.

The edits live in one place — terminal-stack's `bootstrap/_agentmemory.ps1` — because the same
six scripts exist twice for Codex (plugin cache for the CLI, `~/.codex/hooks/agentmemory` for
Desktop) and again for Claude. **A plugin upgrade replaces those caches and silently reverts
every edit**, which turns retrieval back off with nothing in any log. That is why the wiring
re-applies from every sync; `tstack doctor` reports the same condition.

### Duplicate capture

Codex loads `~/.codex/hooks.json` *and* the plugin's own `hooks.codex.json`, so one event was
captured twice — 172 `/observe` requests contained 80 near-identical pairs 1–4 ms apart, while
Claude (one registration) had none. Codex has no hooks-only plugin toggle, silently ignores
unknown plugin config keys (so inventing one looks like it worked and does nothing), and
dropping either registration costs Desktop or CLI capture.

So the duplicate is suppressed server-side instead: `/agentmemory/observe` keys on
`sessionId + hookType + cwd + hash(data)` and drops a repeat inside
`AGENTMEMORY_OBSERVE_DEDUPE_MS` (default `750`, `0` disables), answering `200 {"deduped":true}`
rather than storing it. The key **excludes the timestamp** — each hook process stamps its own,
so the two registrations differ there and nowhere else. Equal request byte counts prove only
equal length. This is host-agnostic and survives plugin upgrades.

### Project on memories

`project` is optional on `memory_save`, and agents mostly omit it. It was never dropped by the
server — REST validates it, `mem::remember` persists it — but three things around it were
broken and are now patched:

- `GET /agentmemory/memories` read no `project` parameter at all, so `?project=anything`
  returned the same unfiltered page. It now filters, and `&includeUnprojected=true` opts
  untagged records back in.
- `memoryToObservation` (and the lesson equivalent) dropped `project`, so a memory saved *with*
  a project came back out of search without one. Search's compact projection now carries it.
- `pre-tool-use.mjs` sent no project with `/enrich`, so that retrieval was recorded against a
  blank project while the other routes were attributed correctly.

For records already saved untagged, **`migrate-memory-projects.sh`** is a dry run by default.
It uses AgentMemory's own `infer-memory-projects` step, which derives a project from the
sessions a memory is linked to and refuses anything ambiguous. Memories from `memory_save`
arrive with `sessionIds: []`, so that step can never infer them — the script lists them with
whatever evidence exists (agent, files, origin, title) so they can be tagged by hand. It does
not guess.

## Why `AGENTMEMORY_VIEWER_HOST=0.0.0.0`

The viewer defaults to binding `127.0.0.1` *inside the container's own network namespace*. A
container-internal loopback bind is unreachable through **any** published port mapping, on every
platform: the port forwarder connects to the container's address on its bridge network, which is
not the container's loopback. So the viewer has to bind `0.0.0.0` to be reachable at all.

(This was previously described here as a Docker Desktop / WSL 2 behaviour. It is not — it is
equally true on Docker Desktop for Mac and on native Linux Docker. The setting was always right;
the explanation was wrong, and it had propagated into `CLAUDE.md` and the new-machine runbook.) `entrypoint.sh` does the same for
the `iii-http` and `iii-stream` workers in the config it writes.

**This does not expose the viewer beyond this machine.** The host-side binding is
`127.0.0.1:3113:3113`, not `0.0.0.0:3113:3113`. `0.0.0.0` inside the container means "all interfaces
of the container's namespace", and the only route into that namespace is the loopback port mapping.
`VIEWER_ALLOWED_HOSTS` then has to match the `Host` header the browser actually sends, hence
`localhost:3113,127.0.0.1:3113`.

The `iii-http` worker additionally restricts CORS to the four `localhost` / `127.0.0.1` origins on
3111 and 3113 — see the config heredoc in `entrypoint.sh`.

---

## Verify it's actually working

`docker compose ps` showing "Up" is weaker evidence than the healthcheck passing, and the
healthchecks only cover the two APIs — check the UIs separately:

```powershell
# API liveness THROUGH the console proxy (what MCP clients actually traverse)
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3111/agentmemory/livez

# API liveness DIRECT (the bypass) — if this works and 3111 doesn't, blame the console
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3110/agentmemory/livez

# Console is up (200 even when agentmemory is down — it reports upstream state as data)
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3114/healthz

# Stock viewer serves its page
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3113

# Health as Docker sees it
docker compose ps      # STATUS should read "Up (healthy)" for both services

# Data volume is attached and non-empty
docker compose exec agentmemory ls -la /data
```

The last one is the meaningful check after a rebuild or a move to a new machine: if `/data` is empty
when it shouldn't be, you're pointed at a freshly created volume rather than your real one.

`./update-console.sh --apply` runs the port/liveness checks above automatically after every deploy,
including the loopback-bind audit over 3110–3114 (`lsof` on macOS/Linux, `Get-NetTCPConnection` on Windows).

### None of the above proves memories are being *captured*

Every check so far exercises the **read** path. Reads and writes fail independently, and on
2026-08-20 the write path was dead for over two hours while the API stayed `healthy`, the circuit
breaker stayed closed, and MCP searches kept returning results. Nothing surfaced it.

```powershell
.\check-capture.ps1          # hook wiring, secret consistency, capture recency
.\check-capture.ps1 -Apply   # + run a real hook end to end, then forget the probe
```

The one-line triage, if you only want the headline:

```powershell
docker compose logs --timestamps agentmemory | Select-String 'Observation captured' | Select-Object -Last 1
```

If that timestamp is old but you have been working since, capture is broken. Two causes, both silent
by construction:

1. **The plugin ships pointing at the Copilot hook config.** `plugin.json` in
   `~\.claude\plugins\cache\agentmemory\agentmemory\<ver>\` sets
   `"hooks": "hooks/hooks.copilot.json"` and `"mcpServers": ".mcp.copilot.json"`. That file uses
   camelCase events (`postToolUse`) and `${COPILOT_PLUGIN_ROOT}`; Claude Code emits PascalCase and
   expands `${CLAUDE_PLUGIN_ROOT}`, so it registers **nothing** — the correct `hooks/hooks.json`
   sits unused right beside it. Repoint both values. **A plugin update reverts this**, and it lives
   in the plugin cache, so this repo cannot pin it — re-run `check-capture.sh` after every bump.
2. **A missing or stale `AGENTMEMORY_SECRET` looks identical to success.** The hook scripts read it
   from `process.env`, then do `fetch(...).catch(() => {})` followed by `process.exit(0)`. A 401 is
   swallowed and the hook reports success. Keep the User environment variable as the only copy
   (see [The HMAC secret](#the-hmac-secret)) — a hardcoded copy in `settings.json` or `mcp.json`
   survives until the next rotation and then fails this same silent way.

One trap when testing a hook by hand: it parses stdin inside a bare `try`/`catch { return }`, so a
payload whose Windows path turns `\D` into an invalid JSON escape makes the hook exit **0** having
done nothing. Build the JSON with `ConvertTo-Json`, and treat only the server-side record as
evidence — never the exit code.

---

## Features, local embeddings, and the remote LLM

Embeddings remain local. Change-aware session summarization, bounded incremental graph extraction,
and consolidation run against a remote chat-completions endpoint. AgentMemory speaks the OpenAI wire
protocol, so the provider is a configuration choice rather than a code path: today that endpoint is
**vLLM on <your-llm-host>**, and the OpenAI API remains a supported one-file rollback.

| | Runs on | Needs network? |
|---|---|---|
| **Embeddings** (semantic search) | in this container, on CPU | no |
| **LLM features** (graph, consolidation, summaries) | remote endpoint | yes — LAN for vLLM, internet for OpenAI |

That split is deliberate. Embeddings run on *every* write, so search remains available offline and
the persisted 384-dimension index does not change. LLM features are durable background work and
resume after connectivity returns.

### vLLM on <your-llm-host> (current provider)

| | |
|---|---|
| Endpoint | `http://<tailnet-ip>:8000/v1` — over **Tailscale**, `VLLM_BASE_URL` in the repo-root `.env`. Find it with `tailscale ip -4 <your-llm-host>`. |
| Model | `qwen3-8b-awq` (`Qwen/Qwen3-8B-AWQ`, AWQ-quantized, tensor-parallel across two A4000s) |
| Context | **16,384 tokens** — every prompt bound in this stack is sized against this, not against cost |
| Served by | vLLM 0.15.0, native `vllm.service` under systemd, `Restart=always`, enabled at boot |
| Auth | enforced; the key is `VLLM_API_KEY`, mirrored into `OPENAI_API_KEY` (see below) |
| Cost | none — this is local hardware |

There is no cheap/expensive model split any more: one model serves summaries, graph extraction, and
consolidation. `AGENTMEMORY_COMPRESSION_MODEL` is left unset so the provider falls back to
`OPENAI_MODEL` rather than carrying a stale cloud model name.

**The credential must be set in the repo-root `.env`, not here.** Compose loads `agentmemory/.env`
first and `../.env` second, so the root file is the only place an `OPENAI_API_KEY` can win. The vLLM
key goes in under that name — the variable is named for the wire protocol, not the vendor.

Managing vLLM and its models is out of scope for this repo; it lives on <your-llm-host>. The documented
reversal there is `sudo systemctl stop vllm && sudo systemctl enable --now ollama` (Ollama's config
and models are preserved but its service is stopped and disabled).

#### Three things that bite when switching providers

**1. `OPENAI_REASONING_EFFORT` is truthy-checked, so `none` is not "off".** The deployment patch
emits `if (this.reasoningEffort) body.reasoning_effort = this.reasoningEffort`. The string `none` is
non-empty and therefore truthy, so leaving the OpenAI value in place sends
`reasoning_effort: "none"` to vLLM on every request. **Set it to empty**, which omits the field. The
neighbouring completion-token branch is already provider-aware: `max_completion_tokens` is sent only
when the model name starts with `gpt-5.6`, so `qwen3-8b-awq` correctly receives plain `max_tokens`.

**2. `SUMMARIZE_CHUNK_SIZE` must come down with the context.** `250` was sized for a
65,536-token endpoint. Nothing truncates an individual observation anywhere in the summary path, and
`AGENTMEMORY_SUMMARY_MAX_OBSERVATIONS` caps the observation *count*, not their size — so the chunk
size is the only real bound. At `25`, measured map/reduce prompts on this deployment peak at
**5,147 prompt tokens** (~206 per observation) against a 16,384 context, leaving ~11k of headroom
after the 2,048-token output reserve. Raise it only against observed
`[agentmemory] llm_usage` `promptTokens`, never by guessing.

**3. `VLLM_MAX_TOKENS=16384` is a context length, not an output cap.** Copying it into AgentMemory's
`MAX_TOKENS` would request the entire context as completion tokens and leave no room for the prompt.
`MAX_TOKENS` stays at `2048`; `VLLM_MAX_TOKENS` is used only to *derive* the bound above.

#### The failure that reports success: consolidation's reflect stage

This one is worth knowing because *nothing* surfaces it. The consolidation pipeline runs
`semantic -> reflect -> procedural -> decay`. The `reflect` stage built its prompt from **every**
fact, lesson, and untruncated crystal narrative matching a concept cluster, with no caps anywhere —
`AGENTMEMORY_SUMMARY_MAX_OBSERVATIONS` and `SUMMARIZE_CHUNK_SIZE` do not apply to it. With the
semantic store past 1,400 facts, one cluster reached **105,926 chars / ~26,482 tokens** and was
rejected instantly by the 16,384-token endpoint.

The stage then swallowed the error in a bare `catch { continue; }`, so the pipeline logged:

```
reflect: {"clustersProcessed":1,"clustersSkipped":0,"newInsights":0,"success":true,"usedFallback":false}
```

`success: true`, zero insights, no error anywhere. **A consolidation pipeline reporting success with
`newInsights: 0` is the signature of a rejected prompt, not of a quiet day.** Confirm it in
`llm/telemetry` by looking at `promptChars` and a `providerLatencyMs` under ~100 ms — an instant
rejection, not a real call.

The deployment patch fixes this in three layers:

| Layer | What it does |
|---|---|
| `AGENTMEMORY_REFLECT_MAX_*` | Bounds the reflect prompt *by relevance* — facts and lessons sorted by confidence, narratives truncated, concept list capped — then trims further until it fits `AGENTMEMORY_REFLECT_MAX_PROMPT_CHARS`, logging `Reflect bounded cluster input` with source-vs-used counts. |
| `AGENTMEMORY_LLM_MAX_INPUT_CHARS` | A ceiling inside the provider itself, applied to **every** family. Nothing can overflow the context regardless of which code path built the prompt, including `provider.compress` callers this stack does not individually bound (graph extraction, temporal extraction, query expansion). A clamp logs `llm_input_clamped`. |
| logged `catch` | The reflect loop still continues past a bad cluster — one cluster must not abort the pipeline — but now logs `Reflect cluster failed` with the cluster shape and the error. |

Result on this deployment: the same cluster went from a 26,482-token rejection producing **0
insights** to a bounded prompt producing **5**.

Two lessons generalise beyond this stage. **Bound by relevance before bounding by truncation** — the
provider ceiling alone would cut mid-prompt and throw away the strongest facts, so the semantic caps
run first and the ceiling is only insurance. And **the concept list is its own cost**: after capping
facts to 40, a cluster naming ~700 concepts still spent ~17.5k of a 25.5k-char prompt just listing
them, which is why `AGENTMEMORY_REFLECT_MAX_CONCEPTS` exists. That was only visible because the bound
logs what it dropped.

A fifth thing to watch is model-side rather than config-side: Qwen3 is a hybrid-reasoning model, and
if the served chat template defaults to thinking mode, replies arrive wrapped in `<think>…</think>`,
which burns the output budget and can break the XML-shaped summary and graph parsing. That is a vLLM
flag on <your-llm-host>, not a setting here. Verified clean on this deployment — summaries come back as
well-formed title/narrative/decisions/files with no reasoning tags.

#### Per-observation compression

`AGENTMEMORY_AUTO_COMPRESS=true`. It costs nothing on local hardware and it makes every *downstream*
prompt smaller — summaries and graph batches consume compressed observations rather than raw
captures, which is real headroom on a 16k context. Measured on this deployment: ~600-830 prompt
tokens and ~200-300 completion tokens per observation, `qualityScore` 90, and no format retries.

The capture log states which path ran, and is the fastest way to confirm the flag took effect:

```powershell
docker logs agentmemory-agentmemory-1 --since 5m | Select-String 'Observation captured'
```

`compress:"llm"` is the LLM path; `compress:"synthetic"` is the non-LLM fallback used when the flag
is off. Turning it off does **not** stop capture or break search — embeddings are local either way —
so `false` is a safe way to shed provider load without losing memories.

Note the runtime retries a compression once when the model returns invalid XML
(`compressWithRetry`), so a malformed response costs two calls. Watch `"retried":true` in the
`Observation compressed` lines if throughput matters.

#### Switching back to the OpenAI API

Uncomment the cloud `OPENAI_API_KEY` line in the repo-root `.env` and comment the vLLM one, then in
`agentmemory/.env` restore `OPENAI_BASE_URL`/`OPENAI_MODEL`, set `OPENAI_REASONING_EFFORT=none`,
restore `SUMMARIZE_CHUNK_SIZE=250` and `AGENTMEMORY_COMPRESSION_MODEL=gpt-5.6-luna`, set
`AGENTMEMORY_AUTO_COMPRESS=true`, and drop the two `LLM_*_LABEL` lines. Recreate with the command in
[Authoritative cost reconciliation](#authoritative-cost-reconciliation). No tracked file needs
reverting — the console label defaults already fall back to the OpenAI wording.

### API authentication, billing, and models

Everything in this section applies to the **OpenAI API provider** — the rollback path, not the
current deployment. It is kept intact because the billing, cost-sync, and key-rotation machinery is
still wired up and still works; skip it while vLLM is serving.

AgentMemory is an unattended server process, so it uses a standard [OpenAI API key](https://platform.openai.com/api-keys).
Codex OAuth authenticates the interactive Codex client and is not exported as a reusable credential
for this container. [API billing](https://platform.openai.com/settings/organization/billing/overview)
must be enabled for the key's project or organization; a ChatGPT or Codex subscription does not fund
API usage.

From the repository root, create the untracked key file if bootstrap has not already done so:

```powershell
Copy-Item .env.example .env
$EDITOR .env        # Windows: notepad .env
```

Replace the placeholder with `OPENAI_API_KEY=sk-proj-...`, then rebuild or recreate AgentMemory.
To swap a key that is already in service, follow [Rotating either key](#rotating-either-key)
instead — it covers the project-scoping requirement and the masked fingerprint the console shows.
The environment file uses `KEY=value` syntax; this differs from the raw `.key` files described
below. Never put the key in `agentmemory/.env` or either tracked `.env.example`. In OpenAI mode the
split is `gpt-5.6-luna` for high-volume compression and `gpt-5.6-terra` for summaries, graph
extraction, and consolidation; vLLM serves every family from one model instead.
Organization limits vary; check the OpenAI platform [Limits page](https://platform.openai.com/settings/organization/limits)
rather than copying a historical limit snapshot. This stack admits at most three provider calls
concurrently and has only two queue consumers.

The 2026-08-21 state-aware migration used 14 Terra calls and 2 Luna calls for an estimated `$0.33`.
The code-only redeploy used no Terra calls and 7 Luna calls, adding less than one cent. These are
workload measurements, not a monthly forecast. `reconcile-llm-queue.sh` previews planned calls and
estimated cost before writing; review its pricing constants whenever OpenAI pricing changes.

#### Authoritative cost reconciliation

Agent007Memory estimates every observed paid call immediately from exact token categories and a
versioned price catalog. It can also synchronize authoritative OpenAI organization Costs API
buckets filtered to one dedicated project. These values stay separate in the UI and history:
estimates can be broken down by AgentMemory family, while billed daily totals cannot.

Create an OpenAI project named **Agentmemory** from the OpenAI platform
[Projects page](https://platform.openai.com/settings/organization/projects). Copy its `proj_...` ID from
the table, create the inference key inside that project, allow the deployment's Luna and Terra
models, and configure project rate limits, a spend limit, and spend alerts. The Monthly Spend
column provides an independent provider-side comparison to Agent007Memory.

For the restricted inference key, set only **Model capabilities → Chat completions
(`/v1/chat/completions`) → Request**. Leave List models, every other model capability, and every
other API permission at None. The dashboard term is **Request**, not Write.

The Costs API requires a separate organization Admin key. Give it **Usage API Scope → Read**.
Temporarily give it **Organization Administration → Read** while the helper retrieves and validates
the project; return that permission to None after `-Apply`. Audit Logs Scope and Fine-tuning
Checkpoints remain None. Never reuse the inference key or put the Admin key in an environment
variable.

Create the Admin key file (`~/.config/openai-admin.key`, or `C:\Temp\openai-admin.key` on Windows) with only the raw `sk-admin-...` secret on one line. Do not include
`OPENAI_API_KEY=`, `export`, quotes, or another line. The helper rejects those formats without
printing the secret. If an inference key is staged in its own `.key` file during rotation, that file
uses the same raw-only format; the services-root `.env` (`services/.env`) still uses `OPENAI_API_KEY=...`. Validate
the active project and Costs access, then write the non-secret settings:

```powershell
cd agentmemory
.\configure-openai-billing.ps1 `
  -AdminKeyFile C:\path\openai-admin.key `
  -ProjectId proj_...              # preview
.\configure-openai-billing.ps1 `
  -AdminKeyFile C:\path\openai-admin.key `
  -ProjectId proj_... -Apply

tstack services up agent007memory
```

**Billing configuration moved with the console**, to
`services/stacks/agent007memory/` — `configure-openai-billing.sh` / `.ps1`, `.billing.env` and
`docker-compose.billing.yml` are all there, and `tstack services` assembles the env-file list for you. The
rule below is why that assembly exists, and it has not changed.

**Pass both env files, stack `.env` first.** These are compose's *interpolation* source, which is a
different mechanism from the `env_file:` keys inside the service definitions. A lone
`--env-file .billing.env` replaces `.env` rather than adding to it, so every `${OPENAI_*}`-derived
`LLM_*` display mirror in the console's `environment:` block silently resolves to `""` — the LLM
Calls page loses its provider, model, and concurrency row while everything stays healthy and no
error appears anywhere. This is exactly what happened between the first billing rollout and
2026-08-21. `update-console.sh --apply` now passes both files for you.

Future `update-console.sh --apply` runs automatically keep this billing overlay enabled whenever
`.billing.env` exists, so a console upgrade does not silently remove project billing.

`.billing.env` is ignored and contains only the project ID/name, the host file path, the fixed
in-container path, and the two masked key fingerprints below—never key material.
`docker-compose.billing.yml` bind mounts the Admin key file read-only. The console backfills the retention window once, then refreshes month-to-date plus the
trailing seven completed UTC days. Automatic and manual refreshes share a persisted two-hour
minimum. A rate-limit response stops the run and doubles `Retry-After` or the request-reset window
when that is longer. Without this optional setup, local estimates continue working and the UI says
Billing setup required.

The Costs API uses daily buckets, so a new project can correctly show `$0.00` until a complete UTC
day and provider billing processing exist. **Estimated today** remains real-time token telemetry;
**Billed month-to-date** is provider-recorded history. Do not add the two values together.

#### Masked key fingerprints in the console

The console can display *which* key each side is using without ever receiving a key. `.billing.env`
carries two display-only fingerprints, generated by `configure-openai-billing.sh` / `.ps1`:

| Variable | Fingerprints | Example |
|---|---|---|
| `LLM_API_KEY_HINT` | the inference key from the repo-root `.env` | `sk-proj-Ab1Cd2…Wx9Z` |
| `LLM_ADMIN_KEY_HINT` | the Admin key at `OPENAI_ADMIN_KEY_FILE_HOST` | `sk-admin-Ef3Gh4…Yz8Q` |

The format is the key's own `sk-<role>-` prefix, six identifying characters, `…`, and the last four —
10 of ~164 characters, the head-and-tail shape provider dashboards use. It is enough to confirm at a
glance which key is live and to tell an old key from a new one mid-rotation, and it cannot
authenticate. A value shorter than expected degrades to prefix-plus-ellipsis rather than exposing
most of itself.

They reach the console through `.billing.env` as an `env_file:`, deliberately **not** through the
`environment:` block: an `environment:` entry would interpolate to `""` and override the real value
on any deploy that omits `--env-file`. The inference key itself still never enters the console.

#### Rotating either key

Rotation is two independent moves. Neither one needs the other, and neither needs the Admin key's
**Organization Administration** permission — `-RefreshHints` makes no API call at all.

**Inference key** — replace `OPENAI_API_KEY=` in the repo-root `.env` (back the old file up as
`.env.bak.YYYYMMDD` first), then recreate. Create the new key *inside the billing project*, or its
usage will not appear in project-scoped cost sync at all; the old `agentmemory-origin-key` sat
outside the `Agentmemory` project for exactly this reason and was replaced on 2026-08-21 by
`agentmemory-origin-inference`. Confirm the fingerprint in `.billing.env` matches the key you meant
to install, since a stale hint is the only visible symptom of a half-finished rotation.

**Admin key** — overwrite the raw `.key` file named by `OPENAI_ADMIN_KEY_FILE_HOST` in place. The
bind mount is live, so the running console reads the new secret without a compose change; recreate
only to refresh the fingerprint.

```powershell
cd agentmemory
.\configure-openai-billing.ps1 -RefreshHints            # preview both fingerprints
.\configure-openai-billing.ps1 -RefreshHints -Apply
tstack services up agent007memory
```

Verify the new inference key actually authenticates in-process, rather than trusting `Up`:

```powershell
docker logs agentmemory-agentmemory-1 --since 5m | Select-String llm_call | Select-Object -Last 5
```

Every recent `llm_call` line should read `"outcome":"success"` and `circuitBreaker.state` should stay
`closed`. A rejected key shows up as failing `llm_call` lines and a queue that grows without
draining, not as an unhealthy container. Note that recreating AgentMemory runs startup recovery,
which re-queues summary and graph jobs for eligible sessions — real provider spend, bounded by
`AGENTMEMORY_LLM_CONCURRENCY`. To skip it on a restart that changes nothing but configuration:

```powershell
docker compose exec agentmemory sh -c 'touch /data/.skip-next-llm-recovery'
```

### Why it was BM25-only (it was never about API keys)

The viewer suggested setting `OPENAI_API_KEY`, which was misleading. The real cause was
`Dockerfile:19` installing with **`--omit=optional`**: `@huggingface/transformers` is an
*optionalDependency* of agentmemory and is the on-device embedding backend, so that one flag left
`node_modules/@huggingface/` an empty directory and silently disabled vector search.

The Dockerfile now installs optional dependencies and **bakes the model into the image** at build
time. agentmemory never sets transformers.js's `cacheDir`, so it defaults to a `.cache/` folder next
to the package — *not* the `/data` volume. Without baking, the ~23MB `Xenova/all-MiniLM-L6-v2`
re-downloads on every container recreate and can't start at all with no internet.

### The one configuration trap

**`EMBEDDING_PROVIDER=local` is mandatory, not cosmetic.** Embedding-provider detection runs
`GEMINI → OPENAI → VOYAGE → COHERE → OPENROUTER`. Because `OPENAI_API_KEY` and `OPENAI_BASE_URL` are
both set for the *chat* LLM, detection would otherwise pick the **openai** embedding provider. On the
OpenAI API that silently changed the vector model and persisted dimension. Against the current vLLM
endpoint it is worse and louder: <your-llm-host> serves one **chat** model and no embedding model, so
every embedding request would 404 and writes would stop being searchable. Pin it explicitly.

The provider credential has one untracked source: repo-root `.env`. Compose loads `agentmemory/.env`
first and `../.env` second, so the root `OPENAI_API_KEY` wins — which is why switching providers
means editing that file, not the stack one. The console receives display-only provider metadata and
masked key fingerprints, never the key itself.

### Embedding dimension is a one-way door

Local is **384-dim**. If you ever switch providers, agentmemory **refuses to boot**:

> `Refusing to start: persisted vector index has N of M vectors with the wrong dimension.`

The only escape is `AGENTMEMORY_DROP_STALE_INDEX=true`, which discards the vectors and rebuilds from
live observations. Decide before you accumulate memories, not after.

### Local-provider rollback baseline

Before the OpenAI migration, an idle <your-llm-host> running
`qwen3:30b-a3b-instruct-2507-q4_K_M` measured:

- **2.2s** for an 83-token compression prompt and 189-token response
- **3.8s** for a near-maximum 8KB observation (1,581 input + 335 output tokens)
- **97.6/100** all-time compression quality

The already-installed `gemma3:12b` is not a faster replacement on this host: the same 8KB prompt
took **27.8s cold / 8.5s warm**. The 70–135s production latency was queue wait, not raw Qwen speed.
AgentMemory 0.9.29 launched every observation compression immediately, while summaries, graph
extraction, and consolidation shared the same Ollama runner. The deployment patch now stores raw
observations first, enqueues only their IDs in the file-backed `agentmemory-llm` iii queue, retries
failed jobs three times with 30-second backoff. The OpenAI rollout canaries at one provider call,
then admits at most three (`AGENTMEMORY_LLM_CONCURRENCY=3`); summary map work is independently
bounded at two chunks. Two queue consumers keep job preparation moving while the provider gate
remains the final concurrency authority.

Check all of it at a glance:

```powershell
sec="$(docker compose exec -T agentmemory cat /data/.hmac | tr -d '\r')"   # Windows: $sec = docker compose exec -T agentmemory cat /data/.hmac
curl -s -H "Authorization: Bearer $sec" http://127.0.0.1:3111/agentmemory/health
curl -s -H "Authorization: Bearer $sec" http://127.0.0.1:3111/agentmemory/config/flags
curl -s -H "Authorization: Bearer $sec" "http://127.0.0.1:3111/agentmemory/llm/telemetry?limit=20"
```

`functionMetrics` is **cumulative for the life of the volume**, so old failures from before this
configuration stay in the totals — `mem::summarize` shows 15 stale failures at ~2ms each from the
pre-LLM era. Judge health by whether counters are *still incrementing*, not by the totals, and by
`circuitBreaker.state`.

The Agent007Memory console presents the same information at
`http://127.0.0.1:3114/#/llm`. It shows durable queue depth, active jobs, workers, DLQ depth, recent
average durable wait, provider-gate wait, and job runtime, plus exact safe rows for compression,
summarization, graph extraction, and consolidation: family, status, model, prompt size,
exact input/cached/cache-write/output/reasoning tokens, project/session scope, estimated cost, the
two separate waits, latency, and outcome. It keeps the cumulative
metrics as a fallback. Prompt/response bodies, secrets, and raw error strings never enter the
telemetry endpoint or console.

For an operations-only view, `http://127.0.0.1:3114/#/overview` combines the six latest compact
project cards with nine completion/latency/queue/cost cards and the two tracked LLM call families. It
omits provider/server configuration and is sized to fit a 1920×1000 browser viewport without
scrolling. Its project reorder dropdown uses the same persistent cadence as the full Projects page,
and its persisted collapsible sidebar can recover an additional 160px of horizontal workspace.

`http://127.0.0.1:3114/#/reports` retains one year of privacy-safe minute aggregates in the separate
`ts-agentmemory-console-history` volume. Its default Overview tab follows the live watch view with global
totals, the six busiest projects, LLM completion/cost health, and historical activity charts. Queue depth
and wait remain live-only because they are not persisted in the reporting database.

The console's `#/operations` page exposes project-scoped, preview-first Full memory maintenance and
recovery, forced session summaries, local graph-snapshot repair, and manual billing sync. Full
maintenance queues both `mem::consolidate` and the all-tier consolidation pipeline. Recovery preview
does not update session counts or enqueue work. Confirmation tokens expire, duplicate runs are
suppressed, and destructive forget/delete/reset/restore actions are intentionally not exposed.
`#/help` renders the console's canonical detailed architecture and operations guide.

### Bounded prompts and provider limits

**The binding constraint is now context, not cost.** vLLM serves `qwen3-8b-awq` with a
16,384-token context — a quarter of the 65,536-token endpoint these bounds were first written for,
and far less than GPT-5.6. Nothing truncates an individual observation in the summary path, so the
chunk size is the real bound. Measured peak on this deployment is 5,147 prompt tokens per map chunk:

| Setting | Default | Here | Why |
|---|---|---|---|
| `MAX_TOKENS` | 4096 | `2048` | Dense summary chunks reached the 1,024 cap exactly; 2,048 avoids truncation while remaining bounded. |
| `AGENTMEMORY_COMPRESSION_MAX_TOKENS` | n/a | `512` | Independent cap for per-observation compression. |
| `SUMMARIZE_CHUNK_SIZE` | 400 | `25` | Sized for the 16,384-token context: ~206 tokens per observation measured, so 25 peaks near 5.1k and leaves ~11k of headroom after the output reserve. `250` was sized for 65,536 and overflows this endpoint. Raise only against observed `llm_usage` `promptTokens`. |
| `SUMMARIZE_CHUNK_CONCURRENCY` | 6 | `2` | Allows modest parallel map work without a provider burst. |
| `AGENTMEMORY_SUMMARY_MAX_OBSERVATIONS` | n/a | `500` | Oversized imports use a deterministic chronological sample instead of an unbounded map/reduce job. |
| `AGENTMEMORY_LLM_TIMEOUT_MS` | 60000 | `120000` | Headroom for a cold or contended local endpoint. Warm latency measured 0.05s and 8 parallel requests finished in 0.8s, so this is a failure bound, not an expected wait. |
| `AGENTMEMORY_LLM_MAX_INPUT_CHARS` | n/a | `48000` | Provider-wide input ceiling (~12k tokens), applied to every family as a backstop. Logs `llm_input_clamped` when it engages; frequent hits mean a family bound below is too loose. |
| `AGENTMEMORY_REFLECT_MAX_CONCEPTS` | n/a | `60` | Consolidation's concept list is its own cost — 673 names was 17.5k chars of prompt. |
| `AGENTMEMORY_REFLECT_MAX_FACTS` / `_LESSONS` / `_CRYSTALS` | n/a | `40` / `20` / `5` | Reflect cluster input, sorted by confidence so the strongest material survives the cut. |
| `AGENTMEMORY_REFLECT_MAX_PROMPT_CHARS` | n/a | `40000` | Final pre-flight on the reflect prompt (~10k tokens); measured 10,619 after the caps. |
| `AGENTMEMORY_LLM_QUEUE` | n/a | `agentmemory-llm` | Native iii queue persisted at `/data/queue_store`. |
| `AGENTMEMORY_LLM_RECOVERY_BATCH_SIZE` | n/a | `10` | Replays old raw observations in paced waves instead of flooding the paid provider. |
| provider concurrency / queue consumers | n/a | `3` / `2` | Keeps request admission bounded well below the account RPM and TPM limits. |
| `AGENTMEMORY_MAX_OBSERVATIONS_PER_SESSION` | 500 | `0` | Removes the hard rejection; Compose also maps this to 0.9.29's legacy `MAX_OBS_PER_SESSION` runtime name. LLM inputs remain independently bounded. |
| `AGENTMEMORY_AUTO_SUMMARY_MIN_NEW_OBSERVATIONS` | n/a | `25` | Duplicate stop hooks do not repeatedly summarize unchanged sessions. |
| `AGENTMEMORY_AUTO_GRAPH_MAX_OBSERVATIONS_PER_RUN` | n/a | `10` | Each stop schedules at most one bounded incremental graph batch. |

The original local-provider symptom is useful rollback context:

```
request (75897 tokens) exceeds the available context size (65536 tokens)
OpenAI API request timed out after 60000ms
```

The raw observation remains durable and the queue retries it. It becomes searchable after a
successful LLM compression; no synthetic replacement silently hides an exhausted LLM job. Startup
recovery queues at most 10 old observations at a time and places the next recovery scan behind that
wave, so multi-thousand-observation projects cannot monopolize queue admission. Summaries are queued
after the raw backlog reaches zero.

### Reconciling a stale queue or historical DLQ

Do not bulk-redrive an old DLQ just to make the console counters reach zero. Durable queue records
can outlive the state change they originally requested, while compression, summary, and incremental
graph handlers use current memory state as their source of truth. Preview the state-aware repair:

```powershell
.\reconcile-llm-queue.ps1
```

The preview reports current queue families, raw observations, due summaries and graph sessions,
projected Terra calls, and estimated cost without writing anything. `-Apply` stops the stack, writes
a cold full-volume backup below `%LOCALAPPDATA%\terminal-stack\stack-backups`, moves the exact `/data/queue_store`
directory to a timestamped quarantine directory, starts with a clean queue, and lets the existing
startup reconciliation enqueue only work that durable state still needs. It never deletes the old
queue and never invokes iii's bulk DLQ redrive. The default safety guards refuse more than 25 planned
Terra calls or an estimated recovery cost above one dollar. Recovery also requires the fresh queue
to remain empty and healthy for 105 seconds, covering the queue's full retry window before success is
reported. Malformed or unreadable session records are logged and excluded from follow-up summary and
graph jobs instead of becoming poison DLQ messages.

For a code-only container replacement immediately after a completed reconciliation, an empty regular
file at `/data/.skip-next-llm-recovery` suppresses one startup pass. The entrypoint consumes the marker
before launch, so later restarts recover normally; do not use it to bypass a needed state repair.

### Historical local timings

Two concurrent manual summaries now serialize: the first used 0ms queue wait and 2.46s provider
time; the second reported 2.46s queue wait and 1.88s provider time. Before the patch both would have
entered Ollama concurrently, and hundreds of observation calls could accumulate behind them.

The observation dedup check also used to run outside the per-session lock, so two identical hook
posts arriving together both passed it. The deployment patch repeats the check inside the lock. A
concurrent probe now returns one `observationId` and one `deduplicated: true`, halving the duplicated
hook volume seen from current clients.

Post-deployment verification on the live corpus:

| Path | Result |
|---|---|
| New observation compression | 2.26–3.66s provider time, 90–100 quality, successful calls serialized during overlap |
| `doc_soc2` summary (2,674 observations) | Deterministic 500-observation sample, 2 map calls + 1 reduce call, 125.29s under concurrent summary load, quality 100 |
| `doc_soc2` graph batch | 25 observations in 6.6s, 7 new concept nodes, durable cursor advanced only after success |
| Project profile | 10 summary concepts surfaced in Top Concepts without re-compressing 2,674 historical observations |
| Final health | AgentMemory and console healthy; circuit closed with 0 current failures |

The 125.29s oversized-session result includes queue time behind a second legitimate session
summary. Normal observation calls remained a few seconds and Ollama admitted only one request at a
time. The stored `doc_soc2` summary still records the full 2,674-observation source count; the cap
controls LLM input volume, not provenance.

`mem::auto-forget` is not a useful load lever in 0.9.29: observation rules are hard-coded to older
than 180 days and importance 2 or lower, and there is no scheduled auto-forget trigger in this
stack. A live dry run returned zero candidates. The effective controls are deduplication, the
durable provider queue, change-aware summaries, the 500-observation summary-input cap, and
incremental graph batches.

### Semantic search and vector persistence

Worth understanding before you judge whether search is "working", because the symptoms are
confusing.

**It works.** Verified with a deliberately lexically-disjoint probe — storing *"The crimson
automobile traverses the thoroughfare at daybreak while pedestrians slumber"* and querying *"a red
car drives down the street early in the morning while people sleep"* returns it as the top hit at
0.6. No content word is shared, so BM25 cannot produce that match.

Current 0.9.29 state has active persisted manifests for both indexes: ~8.9M serialized BM25
characters and ~2.65M vector characters. A restart restored both. The earlier empty-vector behavior
is no longer representative of this volume.

### State-store sizing and the SQLite decision

Before graph v2 migration, the live `/data` volume was ~670MB. `state_store.db` is a directory, not
a SQLite file, and accounted for ~664MB. Only ~12.4MB was the active BM25/vector generation. Failed
generation rollbacks left **254 orphan index-shard files (~489.7MB)**. Legacy graph
edge/node/snapshot blobs added ~176.9MB. The legacy graph scopes remain after migration for rollback,
so the first deployment intentionally grows the volume; reclaim them only after a separate,
backup-protected retention decision.

Do **not** run the 0.9.29 README command `iii worker add iii-database`. The registry URL now returns
404. Its replacement, `database`, is a generic SQLite/Postgres/MySQL query worker; it does not
replace `state::get/set/list/update`. On the pinned iii 0.11.2 state surface, the supported adapters
are KV, Redis, and bridge—not SQLite or Postgres. Installing `database` beside AgentMemory would add
SQL functions while all existing memory state continued using the file KV.

Therefore SQLite is not a safe configuration-only migration today. Keep the pinned file KV, clean
orphan index generations only after a volume backup, and fix upstream generation garbage
collection. Revisit SQLite when iii ships a real state adapter with import/export semantics. Redis
is the only supported scale-out state adapter now, but it conflicts with this deployment's
local-first/zero-ops goal.

The fix for the current graph bottleneck is therefore not SQL: graph nodes, edges, name/edge
indexes, and degree records are deterministically split across 64 KV scopes. Reads fan out eight at
a time, while the compact v2 snapshot retains only the last 32 provenance IDs plus the full source
count. Full provenance stays on each sharded node/edge. This removes the monolithic `state::set`
payloads that previously timed out after 180 seconds and reconnected the worker.

### First graph-v2 deployment, migration, and rollback

Preview the complete cold-backup/deploy/migrate/verify workflow, then apply it:

```powershell
.\migrate-durable-llm.ps1
.\migrate-durable-llm.ps1 -Apply
```

The script stops both stack services, writes a timestamped volume archive under
`%LOCALAPPDATA%\terminal-stack\stack-backups`, rebuilds, waits up to ten minutes for the authenticated migration
status, requeues raw observations, reconciles session counts, checks the DLQ, and verifies ports
3110, 3111, and 3114. Migration copies indexed and orphan graph records, rebuilds lookup indexes,
validates node/edge counts, writes a compact snapshot, and only then switches the running worker to
v2. Legacy scopes are never deleted.

Software rollback is `git revert` of the durable-queue deployment (or redeploy commit `5da03f3`),
with `AGENTMEMORY_MAX_OBSERVATIONS_PER_SESSION=0` retained so capture does not start rejecting long
sessions. Prefer leaving graph writes disabled on legacy software while diagnosing. The v2 shards
and original legacy graph remain on the volume. Restore the cold archive only for actual corruption:
it necessarily discards observations captured after the backup.

### The two silent failure modes to know about

Both would leave you with no semantic search and **no log line saying so**:

1. `vectorIndexAddGuarded()` opens with `if (!vi || !ep) return false` — no warning, no metric. If
   the embedding provider is null, embedding simply never happens, silently.
2. Embedding-provider detection is `EMBEDDING_PROVIDER` override, then `GEMINI → OPENAI → VOYAGE →
   COHERE → OPENROUTER`, then **null**. `local` is *not* in the auto-detect chain — it is only ever
   selected by the explicit override. That is the second reason `EMBEDDING_PROVIDER=local` is
   mandatory here, beyond the `OPENAI_API_KEY` collision.

The one reliable positive confirmation is this startup line, which only appears with
`AGENTMEMORY_VERBOSE=true`:

```
[agentmemory] Embedding provider: local (384 dims)
```

If that line is absent, embeddings are off regardless of what `doctor` or the viewer claims.

### Running `agentmemory doctor` in this container

`doctor` queries the server over HTTP and needs the bearer token, but `docker exec` does **not**
inherit `AGENTMEMORY_SECRET` - the entrypoint exports it into the server process only. Run it
without the token and it reports a misleading `1/5 passing` with "Running BM25-only" and "set
ANTHROPIC_API_KEY", because it is inferring from an unauthorized health response rather than from
the actual configuration. Pass the secret in:

```powershell
sec="$(docker compose exec -T agentmemory cat /data/.hmac | tr -d '\r')"   # Windows: $sec = docker compose exec -T agentmemory cat /data/.hmac
docker exec -e AGENTMEMORY_SECRET=$sec agentmemory-agentmemory-1 agentmemory doctor
```

Ignore the `~/.agentmemory/.env is missing` warning. That file is agentmemory's own config location
for a normal install; here configuration arrives through Compose `env_file` entries as container
environment, which takes precedence over it. Creating it would duplicate configuration.

### Steady-state LLM policy

Automatic session summaries and graph extraction are enabled, queued durably, and change-aware. A summary
starts at 10 observations and is regenerated only after 25 new observations, or after one hour if
there is any new material. Duplicate stop hooks are serialized. Graph extraction keeps a durable
per-session cursor and submits no more than 10 previously unprocessed observations per stop. The
cursor advances only after a successful graph write, so a provider or state failure is retryable.
Project profiles merge concepts from these session summaries, so large imported sessions populate
the dashboard's Top Concepts without re-compressing every historical observation in one burst.

Per-observation LLM compression is **enabled** (`AGENTMEMORY_AUTO_COMPRESS=true`) and, like every
other family, goes through the durable file-backed queue to the single model vLLM serves. Hook bursts
persist locally, while no more than three provider calls are admitted at once. Every prompt is
bounded twice: by its family's own limit, and by the provider-wide
`AGENTMEMORY_LLM_MAX_INPUT_CHARS` ceiling. To verify the bounded policy:

```powershell
# graph counts should increase after successful incremental batches
curl -s -H "Authorization: Bearer $sec" "http://127.0.0.1:3111/agentmemory/graph/stats"
# queue depth should trend down, with active <= 3 provider calls and no new DLQ growth
curl -s -H "Authorization: Bearer $sec" "http://127.0.0.1:3111/agentmemory/llm/telemetry?limit=20"
# migration must remain complete after restart
curl -s -H "Authorization: Bearer $sec" "http://127.0.0.1:3111/agentmemory/admin/graph-migration"
```

An unchanged repeated stop should produce a skipped summary job and no new provider call.

---

## Notes

- **Restart policy is `unless-stopped`** — survives Docker Desktop and machine restarts, but won't
  come back if you explicitly stopped it.
- **The container runs as `node`, not root.** `entrypoint.sh` starts as root only to write the
  config, `chown /data`, and handle `.hmac`, then drops privileges via `gosu`. `tini` is PID 1.
- **`entrypoint.sh` overwrites the npm-bundled `iii-config.yaml` on every start.** Editing that file
  inside the container has no lasting effect — change the heredoc in `entrypoint.sh` and rebuild.
- **Rebuilding does not touch your data.** The image and the volume are independent, so `--no-cache`
  rebuilds are safe.
