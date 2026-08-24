# Conventions

The rules every stack in this repo follows. They exist so that a stack you haven't touched in six
months behaves the way you expect, and so that a fresh machine gets an identical setup from the same
tracked files.

## Layout

One top-level directory per stack, named after the service. Nothing registers a stack anywhere —
`stack.sh` / `stack.ps1` discover any directory containing a `docker-compose.yml`, so adding a
stack means adding a directory.

```
<stack>/
  docker-compose.yml        required — the base definition
  docker-compose.<x>.yml    optional overlays (e.g. gpu), merged via COMPOSE_FILE in .env
  .env.example              required IF anything varies by machine; tracked
  .env                      gitignored, seeded from .env.example by bootstrap.sh/.ps1
  README.md                 required
  Dockerfile / entrypoint   only if the stack builds locally
```

## Compose files

- **No top-level `version:` key.** It's obsolete in the Compose spec and Docker warns about it.
- **Bind host ports to `127.0.0.1` explicitly** — `"127.0.0.1:8880:8880"`, never `"8880:8880"`.
  These services have no authentication. The bare form binds every interface, which puts them on the
  LAN. This is the single easiest mistake to make here, and the one with the worst consequences.
- **Pin exact versions.** An image tag like `:latest`, or an unpinned package in a `Dockerfile`,
  means two machines built a week apart run different software. Prebuilt images get a full tag;
  locally built images get build args (see `agentmemory/docker-compose.yml`); services built from a
  git URL pin a **full commit SHA in the build context** (`...repo.git#<sha>`, see the `console`
  service in the same file — a branch name there is `:latest` by another spelling). If a pin is
  non-obvious — a CUDA build matched to a GPU generation, an SDK that must move with an engine —
  say why in a comment next to it.
- **Every service gets a healthcheck.** "Up" only means the process hasn't exited; `kokoro`'s
  crash-loop is the worked example of why that's not the same as working. Prefer something that
  exercises the actual service (an HTTP endpoint) over a port check.
- **Every service gets log rotation** — `json-file`, `max-size: 10m`, `max-file: 3`. Without it a
  chatty container will fill a disk eventually. It also bounds how long anything a container prints
  stays readable via `docker logs`, which matters when a container prints a secret on first boot.
- **`restart: unless-stopped`.** Survives reboots; respects a deliberate stop.
- **Name volumes, don't bind-mount host paths.** Host paths differ per machine, bring permission
  problems on Windows, and cost uid-mapping and virtiofs performance on Docker Desktop for Mac —
  which also only shares `$HOME`, `/tmp`, `/private` and `/Volumes` by default, so a bind mount
  from anywhere else fails at run time. Where a volume needs the same name everywhere, declare it
  `external: true` and add it to the required-volumes list in **both** `bootstrap.sh` and
  `bootstrap.ps1` so it gets created on a new machine whichever one is run.
- **Set `container_name:`** when Compose's default `<project>-<service>-<n>` would obscure what a
  container actually is — a multi-service stack (`headroom-proxy`, `headroom-qdrant`,
  `headroom-neo4j`), a container an external tool finds by literal name (`kokoro`, load-bearing for
  `claude-local`'s Windows GPU diagnostics), or a service whose image comes from a differently-named
  upstream repo (`agentmemory`'s `console` service is named `agent007memory`). This only sets the
  Docker-level display name — the Compose **service key** is unchanged, so `docker compose` commands
  still address the service by its original name.

## Per-machine variation

Anything that differs between computers goes in `.env`, never in a tracked file. Tracked files must
be byte-identical across machines.

Compose reads `.env` from the stack directory automatically, for both variable substitution and its
own settings (`COMPOSE_FILE`, `COMPOSE_PROFILES`, `COMPOSE_PROJECT_NAME`). Two ways to use it:

- **Substitution** for simple values — `image: ${KOKORO_IMAGE:-<sensible default>}`. Always give a
  default so the file is still valid without a `.env`.
- **Overlay selection** for structural differences, via `COMPOSE_FILE`. Compose merges additively, so
  build the base file as the *smallest* common case and have overlays *add* to it — an overlay
  cannot cleanly remove a block. `kokoro`'s base file is hardware-neutral and
  `docker-compose.gpu.yml` adds the NVIDIA reservation; the reverse would not work. `agentmemory`
  follows the same pattern for an optional whole *service*, not just a config block: the base file
  is kokoro's GPU selection — any script or overlay that explicitly lists `-f` files for a stack
  must include every overlay that stack's `COMPOSE_FILE` names
  before any overlay that patches the `console` service (billing, local-checkout), or Compose errors
  that the service isn't defined.

Set `COMPOSE_PATH_SEPARATOR=:` in any `.env` that sets `COMPOSE_FILE`. The separator otherwise
defaults to `;` on Windows and `:` elsewhere, which would make the file host-specific. On a Unix
host the pinning is a no-op — that is the point: one `.env` stays valid on any machine.

Write `.env.example` with every profile spelled out and commented, one uncommented. It's
documentation as much as configuration.

## Scripts

Every repo script exists **twice**, side by side, doing the same thing:

| | Language | Flags | Encoding |
|---|---|---|---|
| `foo.ps1` | Windows PowerShell | `-Apply`, `-Stack <name>` | UTF-8 **with** BOM |
| `foo.sh` | bash (macOS + Linux) | `--apply`, `--stack <name>` | UTF-8 **without** BOM |

**The flags map one-to-one.** `-Apply` ↔ `--apply`, `-Stack kokoro` ↔ `--stack kokoro`,
`-GpuTag` ↔ `--gpu-tag`, `-MaxPlannedTerraCalls` ↔ `--max-planned-terra-calls`. The `.sh` scripts
also accept the PowerShell spelling, normalised by one helper, so muscle memory from the other
platform still works. Breaking that parity costs more than it buys: it invalidates a sentence in
every other doc, and `tests/test_script_parity.py` fails on it.

Both **preview by default**. A script prints what it would do and changes nothing unless given
`-Apply` / `--apply`; a destructive mode (`-Undo`/`--undo`, `-Down`/`--down`) still requires it.
Use the shared `Section` / `Step` / `Info` / `Warn` / `Have` helpers and the `[would]` vs `[DO]`
output so every script in the repo reads the same. On the `.sh` side they live once in
`_common.sh`; the `.ps1` deliberately keep their own copies — copy them from `bootstrap.ps1`.

**Target bash 3.2.** macOS ships 3.2 and always will, and `bootstrap.sh`'s whole job is to report
what a machine is missing — it cannot require an unlisted `brew install bash` to say so. No
associative arrays, no `mapfile`/`readarray`, no `${x,,}`. Use `case`-based lookup functions and
space-separated strings instead. Shebang is `#!/usr/bin/env bash`, prologue is `set -euo pipefail`.

**The BOM rule is opposite for the two languages, and both directions are load-bearing.**

- **`.ps1` — UTF-8 WITH a BOM.** Windows PowerShell 5.1 reads BOM-less files as ANSI, so any
  non-ASCII character (the em-dashes these scripts print) becomes mojibake and the file fails to
  parse with a misleading `Missing closing '}'`. pwsh 7 is fine either way, so this only bites where
  someone runs the script with `powershell.exe`.
- **`.sh` — UTF-8 WITHOUT a BOM.** A BOM sits *before* the `#!`, so the kernel never sees a shebang
  and the script fails with `bad interpreter` or is handed to the wrong shell.

Line endings are pinned in `.gitattributes` for the same reason: `.ps1` is `eol=crlf`, `.sh` is
`eol=lf`. Never rely on a machine's `core.autocrlf`.

**Commit `.sh` files executable** — mode `100755`. Windows git ignores filesystem modes entirely,
so on a shared repo the index is the only place the bit can live; if it records `100644`, the next
macOS clone gets `permission denied`. Set it with `git update-index --chmod=+x <file>` before
committing. Sourced libraries (`_common.sh`) stay `100644` — they are sourced, not executed.

Every script opens with a header block. `.ps1` uses `.NAME`, `.SYNOPSIS`, `.PLATFORM`, `.USAGE`,
`.WHEN`, `.NOTE`; `.sh` uses a comment block whose second line is `name.sh — purpose.`, followed by
which `.ps1` it twins and `Usage:` / `When:` / `Note:`. `--help` prints that block back, so the
header *is* the usage text and there is no second copy to drift.

Scripts should be idempotent and should verify after acting rather than assuming success.

**Deliberately single-platform scripts.** Not everything needs a pair, as long as it is stated.
Nothing is single-platform today; if that changes, say so in the header and in the README section
that invokes it, and add it to the register below.

### Intentional divergences between a `.ps1` and its `.sh`

**`ts-verify.sh` runs without `set -e`.** Every other script here uses
`set -euo pipefail`. A verify script is a list of independent probes, and dying on
the first failure would report one problem and hide the rest — the opposite of
what a diagnostic is for. It uses `set -uo pipefail`, accumulates into `rc`, and
its header states the exit contract. `tests/test_service_script_parity.py`
enforces exactly this shape rather than allowing a bare opt-out.

The parity test only works if the *deliberate* differences are written down — otherwise it gets
weakened, or the differences get "corrected" back and forth forever. Anything here is expected;
anything not here is drift.

| Divergence | Where | Why |
|---|---|---|
| `[DO]   ` is three spaces, not two | `_common.sh` | Makes `[DO]   ` and `[would]` both 7 chars, so a message lands in the same column with or without `--apply`. The 2-space form was copied into seven `.ps1` and is the bug. |
| Missing Chrome warns in preview, refuses only under `--apply` | `setup-playwright-agents.sh` | Matches the MCP check six lines earlier. In the `.ps1` `$chromePath` is discovered, printed, and never used again — the MCP browser is headless Chromium *inside* the container. |
| Exits non-zero when problems were found | `check-capture.sh` | The `ts-doctor.sh` house rule, so it can be used in a pipeline or a hook. The `.ps1` always exits 0. |
| Probe sessions tracked and cleaned from an `EXIT` trap | `check-capture.sh` | Fixes a real bug: the `.ps1`'s `$probeSessions` is never initialised and section D's probe is never added to it. |
| Backup root defaults under `$HOME` XDG state | `reconcile-llm-queue.sh`, `migrate-durable-llm.sh` | There is no Unix `C:\DATA`, and Docker Desktop for Mac only bind-mounts from `$HOME`, `/tmp`, `/private`, `/Volumes`. |

| Refuses the GPU path on macOS instead of falling back to CPU | `setup-kokoro-docker.sh` | Docker Desktop for Mac has no passthrough of any kind. A silent switch is the failure mode `kokoro`'s Blackwell section exists to warn about. |
| CPU image pinned to `v0.8.0`, not `:latest` | `setup-kokoro-docker.sh` | A new file should not inherit the `.ps1`'s violation of the pin rule. Bring the `.ps1` into line the next time it is touched. |
| agentmemory image derived, not hardcoded | `migrate-durable-llm.sh` | `.ps1:56` hardcodes `agentmemory-agentmemory:latest`, correct only because the compose project name happens to match the directory name. |
| Secret resolution has a fallback chain and a 0600 mode check | `check-capture.sh`, `_common.sh` | `.ps1:79` reads the Windows User env var with *no* fallback, so that check fails on any machine where it is unset. There is no Unix equivalent of `HKCU\Environment`. |
| Upstream-source version check | `bootstrap.sh` | New capability; `bootstrap.ps1` gains it the next time it is touched. |
| No `wsl` probe | `bootstrap.sh` | No WSL on Unix; replaced by an OS-conditional engine check that stays quiet on native Linux. |
| `_common.sh` and `_json.mjs` have no `.ps1` twin | repo root | PowerShell has these built in — dot-sourcing helpers and `ConvertTo/FromJson`. |
| `.billing.env` written with LF | `configure-openai-billing.sh` | `[Environment]::NewLine` is CRLF on Windows. The file is gitignored, but a machine driven from both sets should not see it flip. |

## Cross-platform command idioms

Prefer a command that is **identical** on both platforms over a command shown twice. Most already
are — `docker`, `docker compose`, `git`, `npm`, `node` and the agent CLIs need no translation, and
neither does `curl` (pwsh 7 removed the `Invoke-WebRequest` alias) or `"$(some command)"` inside a
double-quoted string (PowerShell's `$()` behaves like POSIX command substitution). Showing both
spellings of an identical command teaches a difference that does not exist.

One global note covers every `curl` in this repo: **Windows PowerShell 5.1 only — write `curl.exe`;
`curl` is an alias for `Invoke-WebRequest` there.**

Reach for a two-row table only for the idioms below, which genuinely have no common spelling.

**Loopback port audit.** Start with the platform-independent check — every mapping must read
`127.0.0.1:<port>->`:

```sh
docker ps --format '{{.Names}}\t{{.Ports}}'
```

Then confirm at the OS level, which is the real proof — Docker's view is intent, not the socket:

| | |
|---|---|
| macOS / Linux | `lsof -nP -iTCP:<ports> -sTCP:LISTEN` |
| Windows | `Get-NetTCPConnection -State Listen -LocalPort <ports> \| Select-Object LocalAddress, LocalPort` |

On macOS the NAME column must read `127.0.0.1:<port>`; a `*:<port>` means all interfaces, which is
a bug because these services have no authentication. On Windows every `LocalAddress` must be
`127.0.0.1`. **`lsof` prints nothing and exits 1 when nothing matches**, which looks identical to a
typo — sanity-check it against a port you know is listening.

**HTTP health check.** Identical everywhere; `-f` turns a non-2xx into a non-zero exit, and `-w`
reproduces what `Select-Object StatusCode` was showing:

```sh
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3111/agentmemory/livez
```

**Capturing the agentmemory secret.** The one-call form is fully neutral:

```sh
curl -fsS -H "Authorization: Bearer $(docker compose exec -T agentmemory cat /data/.hmac)" \
  http://127.0.0.1:3111/agentmemory/health
```

For several calls, only the assignment differs:

| | |
|---|---|
| macOS / Linux | `sec="$(docker compose exec -T agentmemory cat /data/.hmac \| tr -d '\r')"` |
| Windows | `$sec = docker compose exec -T agentmemory cat /data/.hmac` |

The `tr -d '\r'` is cheap insurance: a stray CR inside an `Authorization` value makes curl fail
with an opaque header error, and `$()` only strips trailing newlines.

**Log grep.**

| | |
|---|---|
| macOS / Linux | `docker compose logs --timestamps agentmemory \| grep 'Observation captured' \| tail -1` |
| Windows | `docker compose logs --timestamps agentmemory \| Select-String 'Observation captured' \| Select-Object -Last 1` |

**Editing a `.env`.** Prefer prose — "open `.env` in your editor and replace the placeholder" — over
naming an editor. Where a literal command is wanted: `open -e .env` (macOS), `$EDITOR .env`
(Linux), `notepad .env` (Windows).

## Documentation

Every stack has a `README.md` that covers, at minimum:

- what the service is, and a link to its **upstream GitHub repository**
- what's reachable on which port, and what's deliberately not published
- what's pinned and how to bump it
- a quick start that can be copy-pasted
- **verification that proves the service works**, not just that the container is running
- the gotchas — the things that cost you an afternoon. These are the highest-value part of the file.
  `kokoro`'s Blackwell section is the model.

The root `README.md` carries the stack index table, including each stack's upstream repo. Update it
when adding a stack.

## Secrets

**No secrets in this repo.** `.env` is gitignored; `.env.example` is tracked and holds only
non-sensitive defaults or obvious placeholders. Generate service-owned credentials inside the
container when possible — `agentmemory` does this with its HMAC secret — and keep external provider
credentials in the narrowest applicable ignored `.env`.

Watch for a secret generated on first boot being *printed* on first boot: it then lives in
`docker logs` until log rotation ages it out. Document that where it applies, and give a rotation
procedure.

AgentMemory's LLM provider credential lives in repo-root `.env`, seeded from the tracked placeholder
in `.env.example`. It is read as `OPENAI_API_KEY` regardless of provider, because AgentMemory speaks
the OpenAI wire protocol — the variable is named for the protocol, not the vendor. Compose loads that
file *after* `agentmemory/.env`, so it is the only place the credential can win; switching providers
means editing the root file. The companion console receives display-only provider metadata and never
the key. Stack-local `agentmemory/.env` contains non-secret provider settings — endpoint, model, and
prompt bounds — plus a rollback-only <your-llm-host> Ollama placeholder.

A **masked fingerprint is not a secret, and a generated file is not a tracked one.** The console
displays which key is live via `LLM_API_KEY_HINT` / `LLM_ADMIN_KEY_HINT` — the key's `sk-<role>-`
prefix, six characters, an ellipsis, and the last four, generated into the ignored
`agentmemory/.billing.env` by `configure-openai-billing.ps1`. Ten of ~164 characters cannot
authenticate, and being able to see *which* key is running is what makes a rotation verifiable
instead of hopeful. Two rules keep that from drifting into a real leak: derive the fingerprint from
the key at generation time rather than storing a second copy of it anywhere, and keep the example
fingerprints in tracked docs illustrative rather than pasting the live one in. SOPS was not adopted because no
credential is committed; that judgement changes the day a secret must live in the repository.

If a stack ever genuinely needs a credential in version control, the approach to use is **SOPS with
an age key**: SOPS encrypts values but not keys, so diffs and review stay readable, and
`sops exec-env` injects them into `docker compose` without plaintext touching disk. The age private
key lives outside the repo. This is deliberately *not* set up today — nothing here needs it, and it
would be maintenance for no benefit. Set it up when there's a real secret, not before.

## Adding a stack — checklist

1. `mkdir <stack>` and write `docker-compose.yml`: pinned version, loopback bind, healthcheck on
   **every** service, log rotation, `restart: unless-stopped`.
2. Machine-dependent? Add `.env.example` with commented profiles, and overlay files if the
   difference is structural. **Check the image's architectures before pinning** —
   `docker manifest inspect <image> | grep architecture` must list `amd64` *and* `arm64`, or the
   stack is single-platform and the `.env.example` has to say which profile each machine takes.
   An image with no matching manifest does not fail loudly: Docker emulates it, very slowly.
   Never pin `:latest`, even when it happens to be the digest you want today.
3. Needs an `external` volume? Add it to the required-volumes list in **both** `bootstrap.sh` and
   `bootstrap.ps1` — a volume created by only one of them is a new-machine failure on the other
   platform. Plain named volumes need no registration; prefer them unless the name must be stable
   across machines (see `agentmemory`, which adopted a volume an earlier setup had created).
4. Write `README.md` per the list above. Show one command where the two platforms agree, and a
   two-row table only where they genuinely differ — see "Cross-platform command idioms".
5. Add a row to the root `README.md` stack table, naming the upstream GitHub repo. If the stack
   does not run everywhere, say so in the table.
6. Bootstrap, bring it up, and verify **functionally**:

   | | |
   |---|---|
   | macOS / Linux | `./bootstrap.sh --apply && ./stack.sh --up --apply` |
   | Windows | `.\bootstrap.ps1 -Apply` then `.\stack.ps1 -Up -Apply` |

   "Up" is not evidence. Hit the endpoint and check the response body, not just the status.
7. Confirm the port is loopback-only, both ways — see "Cross-platform command idioms". Every
   mapping `127.0.0.1:<port>->`, every listener `127.0.0.1`.
8. Run the parity test if you touched a script: `python3 -m pytest -q tests/`.
