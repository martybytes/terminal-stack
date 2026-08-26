# CLAUDE.md — services/

Scoped guidance for the Docker service tree. The repo-level rules are in the root
`CLAUDE.md`; this file covers what is different inside `services/`.

## What this tree is

The containers three of terminal-stack's headline features run on. One directory
per stack under `stacks/`, each with its own compose file, `.env.example` and
README, plus `console/` — the source of the agentmemory console, which the
agentmemory stack builds.

| stack | what it is | ports |
|---|---|---|
| `agentmemory` | memory for Claude, Codex and Cursor, behind its console proxy | 3111 (proxy), 3110 (server bypass), 3112 (events), 3113 (stock viewer), 3114 (console UI) |
| `headroom` | prompt-compression proxy + Qdrant + Neo4j + a dashboard gateway | 8787, 8788, 6333/6334, 7474/7687 |
| `kokoro` | the TTS engine voice notifications use | 8880 |
| `playwright` | browser MCP server for agents | 8931 |

## The boundary

**`services/` is the service side**: anything that defines, builds, configures or
runs inside a container. **Everything outside it is the client side**: anything
that configures a program running on this host — `~/.claude`, `~/.codex`,
`~/.cursor`, the shells, the prompt.

The two meet in exactly two places: a published loopback port, and
`bootstrap/agent-tools.json`, the one file where a port, URL, image tag or
version pin is written down.

At the command level the same line is **`tstack services` versus `tstack agents`**:
`tstack services` is the only thing in this repo that starts, stops or builds a
container; `tstack agents` may only probe one. That is not a style preference —
`tests/test_agent_tools.py` asserts that `docker compose`, `docker rm` and
`restart: unless-stopped` appear nowhere in `tstack/commands/agents.py`, as a
case-insensitive match over the whole file, **so even a comment naming the
compose command fails it**. When a probe fails, `tstack agents` prints the verb
(`tstack services up playwright`), never the command.

Every docker argv in the repo is built in one place, `tstack/stacks.py`'s
`Compose.argv`, and a test asserts no second file builds one. That choke point is
what makes the data-safety rules testable rather than merely intended: `down`
never receives `-v`, and `--env-file .env` always precedes `--env-file
.billing.env`.

Three consequences. `bootstrap/ts-agentmemory.*` stays outside this tree although
its whole subject is agentmemory, because it edits `~/.claude`, `~/.codex` and
`~/.cursor`. `stacks/agentmemory/patch-agentmemory.mjs` stays inside, because it
patches the npm bundle in the image. And `stacks/*/ts-verify.sh` is the one
deliberate exception: proving capture works needs both halves, and only the
server-side record is evidence, because the hook always exits 0.

## Non-negotiables

- **Host ports bind `127.0.0.1` explicitly.** `"127.0.0.1:8880:8880"`, never
  `"8880:8880"`. None of these services authenticate; the bare form puts them on
  the LAN. `tstack services test` audits this and never skips it.
- **Never commit a `.env`.** `.env` is gitignored, `.env.example` is tracked and
  holds only non-sensitive defaults.
- **Tracked files are identical on every machine.** Anything machine-specific —
  GPU generation, ports, secrets — goes in `.env`. Editing tracked YAML to make
  one computer work is the bug.
- **Pin versions.** No `:latest`. Comment non-obvious pins.
- **Everything this tree creates is named `ts-`.** Projects (`name:` in the base
  compose file), containers, networks and locally built images. `docker ps` on a
  developer's machine also lists their work stacks; the prefix is what separates
  them.
- **A feature flag and the services it needs travel together.** headroom's
  memory overlay is the cautionary tale: the base file set `QDRANT_URL` and
  `NEO4J_URI` and started both datastores, while the proxy engaged memory only
  when passed `--memory` — which nothing passed, and for which there is no
  environment variable. Four containers healthy, two of them holding nothing, for
  months. If an overlay starts a service, it must also turn on the thing that
  uses it, and a test asserts that for this one.
- **Only one memory backend runs.** AgentMemory or headroom's own store, decided
  by the `memoryBackend` setting outside this tree. Nothing here may make both
  reachable at once.
- **Every script *in this tree* exists twice** (`foo.sh` + `foo.ps1`), flags
  mapping one to one. `tests/test_service_script_parity.py` fails otherwise, and
  deliberate differences go in the divergence register in
  `docs/service-conventions.md`, which that test reads.

  **The CLI that drives them no longer does.** `bootstrap/ts-stack.{sh,ps1}` were
  a 1,532-line pair kept in agreement by hand; they are now one Python program
  (`tstack/commands/services.py` + `tstack/stacks.py` + `tstack/engine.py`) and
  the pair is deleted. The rule survives here because these scripts run *inside*
  the service tree, are discovered by filename, and each is small enough that a
  twin is cheaper than an interpreter dependency in a container context.

## Working here

```sh
tstack services                     # status: one line per stack
tstack services bootstrap           # first run: .env files, generated secrets, volumes
tstack services up | down | restart
tstack services logs <stack>
tstack services test                # down, up, and prove the whole chain works
tstack services doctor
tstack services --dry-run <verb>    # the exact docker argv, without running it
```

A stack is any directory under `stacks/` holding a `docker-compose.yml` — there
is no registry, so adding one requires no edit anywhere. Which stacks take part
comes from the saved settings you already have (`agentmemoryEnabled`,
`headroomEnabled`, `playwrightEnabled`, and for kokoro the TTS switch plus
`ccTts.engine`); naming a stack explicitly overrides its toggle.

`kokoro`'s `.env` sets `COMPOSE_FILE`, so which files merge depends on the
machine profile. `tstack services config <stack>` shows what actually resolves.

## Verifying

**"Up" is not evidence.** `kokoro` crash-loops while reporting `Up` when the CUDA
build does not match the GPU. Each stack ships two things `tstack services test` finds
by filename:

- `ts-checks.conf` — declarative health and reachability, one check per line.
- `ts-verify.sh` / `.ps1` — the integration proof: that headroom's token is
  actually *enforced*, that a memory can be written and read back, that kokoro
  really synthesises audio.

Add a stack and it registers itself by having them.

## Gotchas that have already cost time

- **A `.env.example` with no `.env` is worse than nothing.** Compose falls back to
  the base file alone, which for kokoro means starting the GPU image with no GPU.
  `tstack services bootstrap` seeds them; `tstack services doctor` reports the gap.
- **headroom needs both secrets before it will start.** They are `:?`-required, so
  a missing one fails at `docker compose config` naming the variable rather than
  starting an open data plane. `tstack services bootstrap` generates them.
- **headroom's proxy token is not your provider API key.** The proxy forwards
  `Authorization` upstream, so sending the proxy token to `/v1/chat/completions`
  gets you past headroom and then a 401 from the provider. Tell them apart by the
  body: `{"error":"unauthorized"}` is headroom refusing you; anything naming an
  API key is upstream.
- **Host 3111 is the console proxy, not agentmemory.** If 3111 is dead, check the
  3110 bypass first — that is what separates "the console is down" from
  "agentmemory is down".
- **agentmemory can stop capturing while every read-path check passes.** Every
  vendor hook does `fetch(...).catch(() => {})` then `exit(0)`, so there is
  nothing to read. `tstack services test` writes a probe and reads it back, which is the
  only proof; `stacks/agentmemory/check-capture.sh` is the deeper diagnostic.
- **agentmemory's billing deploy needs both env files, stack `.env` first.** A
  lone `--env-file .billing.env` *replaces* `.env` as compose's interpolation
  source, so every `${OPENAI_*}`-derived `LLM_*` value the console displays
  resolves to `""` — blank panel, no error, everything healthy. `tstack services`
  assembles the list itself; hand-typed commands get it wrong.
- **agentmemory's volumes are `external: true`, headroom's are not.** That
  asymmetry is the safety property: `down -v` cannot touch an external volume,
  which is why every memory you have ever saved lives in one. `tstack services reset
  --purge` is the only path that removes them, and it needs a verified backup and
  a typed phrase.
- **agentmemory's consolidation reports success while failing.** A `reflect` run
  logging `newInsights: 0` is the signature of a prompt rejected for length, not
  a quiet day. Confirm with `promptChars` and a sub-100ms `providerLatencyMs` in
  `llm/telemetry`. Bounds live in `AGENTMEMORY_REFLECT_MAX_*` and
  `AGENTMEMORY_LLM_MAX_INPUT_CHARS`.
- **`entrypoint.sh` rewrites the container's `iii-config.yaml` on every start.**
  Editing it inside a running container does nothing — change the heredoc and
  rebuild.
- **The viewer must bind `0.0.0.0` *inside* the container.** True on every
  platform: a container-internal loopback bind is unreachable through a published
  port mapping. Safe, because the host side is loopback-only.
- **macOS/Linux: host reachability is not container reachability.** A container's
  DNS is Docker's embedded resolver, not the host's, so MagicDNS resolving on the
  host proves nothing. Test from a container before trusting an endpoint.
- **macOS/Linux: `/bin/bash` is 3.2 and always will be.** Every `.sh` here is
  bash-3.2 clean and the parity test enforces it. Two traps under
  `set -euo pipefail`: `cmd | head -c N` makes `cmd` take SIGPIPE and exit 141, a
  wordless death; and `cmd | grep -q` reports the pipeline as *failed* on a
  match. Capture first, match in the shell.
- **The console builds from `../../console`**, this repo's own tree. It used to be
  a pinned SHA of a separate repo, so a dirty working tree now builds a dirty
  image: `git status` before `tstack services up` is the whole discipline.
