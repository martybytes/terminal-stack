# kokoro

Local [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) text-to-speech container —
an OpenAI-compatible TTS API (`/v1/audio/speech`) plus a Swagger UI, reachable at
**`http://127.0.0.1:8880`**.

Two ways to manage it:

- **`docker-compose.yml`** — **canonical**. `docker compose up -d` / `down`. Matches the convention
  used by the other stacks in this repo (see `../agentmemory`), and is what `../stack.sh` /
  `../stack.ps1` drive.
- **`setup-kokoro-docker.sh` / `.ps1`** — the escape hatch, with a preview mode that
  shows the exact `docker pull` / `docker run` it's about to execute before executing it, and can
  idempotently create/start/verify/remove the container in one command. Useful when you want to see
  the raw Docker commands, or to stand up the container without a compose project. It is a
  deliberate copy of the same script in the `claude-local` repo's `tools/windows/system/` — changes
  need porting both ways. The `.sh` twin has no third copy. On macOS the script **refuses** the GPU
  path rather than quietly substituting the CPU image; see "On a Mac" below.

Both create/manage a container literally named `kokoro`, so don't run both at once against the same
container unless you're okay with either one adopting what the other created. Both bind
`127.0.0.1:8880` only.

---

## Picking your machine profile

This is the only stack in the repo with a hardware dependency, so it's the only one with a `.env`.
Copy the example and uncomment one profile:

| | |
|---|---|
| macOS / Linux | `../bootstrap.sh --apply` |
| Windows | `..\bootstrap.ps1 -Apply` |

That seeds `.env` and tells you which profile this machine needs. Then open `.env` in your editor
and uncomment that one.

| Profile | Hardware | Image | Compose files |
|---|---|---|---|
| **A** (default) | Blackwell — RTX 50-series, sm_120 | `...-gpu:v0.8.0-cu128` | base + `docker-compose.gpu.yml` |
| **B** | GTX 900 through RTX 40-series | `...-gpu:v0.8.0-cu126` | base + `docker-compose.gpu.yml` |
| **C** | **any Mac**; or no NVIDIA GPU; or you don't want TTS competing with the display GPU | `...-cpu:v0.8.0` | base only |

`v0.8.0` is the same upstream release as Profiles A and B, so one version number governs all three,
and its manifest is multi-arch — Apple Silicon gets a native `linux/arm64` image with no separate
tag.

## On a Mac

**Profile C is mandatory, not a preference.** Docker Desktop for Mac has no GPU passthrough of any
kind — not CUDA, and not Metal/MPS. A Linux container on macOS cannot reach the Apple GPU under any
configuration.

Selecting Profile A or B on a Mac fails at `docker compose up` with
`could not select device driver "nvidia" with capabilities: [[gpu]]`. That loud failure is the
intended behaviour. `bootstrap.sh` picks C for you and says why.

Expect CPU-rate synthesis — which for this service is fine: measured on Apple Silicon, a short
utterance returns `audio/mpeg` in well under a second. Allow for a one-off model warm-up on the very
first request before calling a slow response a failure.

Everything in "The one thing that will bite you" below is NVIDIA-only and cannot happen to you.

`.env` sets two things: `KOKORO_IMAGE`, and `COMPOSE_FILE` — which selects whether the NVIDIA device
reservation in `docker-compose.gpu.yml` gets merged in. Profile C must omit that overlay; the
reservation prevents the container from starting on a host with no NVIDIA runtime.

`.env` also pins `COMPOSE_PATH_SEPARATOR=:`, because `COMPOSE_FILE`'s separator otherwise defaults to
`;` on Windows and `:` everywhere else. On a Unix host the pinning is a no-op — that is the point:
one `.env.example` stays valid on any host.

**If `.env` is missing entirely**, Compose falls back to the base file alone and starts the GPU image
with no GPU access — it works, but silently on the CPU. `../stack.sh` and `../stack.ps1` both warn
when a stack has a `.env.example` and no `.env`; check the resolved config directly with:

```sh
docker compose config   # confirm the image tag, and whether the nvidia deploy: block is present
```

---

## The one thing that will bite you: GPU image tag

*Applies to NVIDIA hosts only — Profiles A and B. On a Mac there is no GPU passthrough at all, so
Profile C is the only option and none of this can happen to you.*


Kokoro-FastAPI's GPU image `:latest` tag ships a PyTorch build compiled for **CUDA 12.6**, whose
bundled kernels only cover GTX 900-series through RTX 40-series (compute capability ≤ 9.0).

On an **RTX 50-series (Blackwell, sm_120)** card, that image:

1. Pulls fine.
2. Starts fine — `docker ps` shows it `Up`.
3. Then dies on the *first inference request* with:
   ```
   RuntimeError: Warmup failed: Failed to load model: Failed to load Kokoro model:
   CUDA error: no kernel image is available for execution on the device
   ```
4. Because the container has `--restart unless-stopped`, it then **crash-loops** — Docker keeps
   restarting it, it keeps dying at warmup, forever. `docker ps` will keep showing it "Up N
   seconds" even though it has never once successfully served a request.

**Fix:** use the `v0.8.0-cu128` tag instead (CUDA 12.8, includes sm_120 kernels). That's Profile A,
the default in `.env.example`, and the default `KOKORO_IMAGE` value in `docker-compose.yml` and in
both setup scripts.

If you're running this on an *older* card (pre-Blackwell), `v0.8.0-cu128` should still work, but
`v0.8.0-cu126` is the narrower/lighter match for that hardware — that's Profile B, or pass
`--gpu-tag v0.8.0-cu126` / `-GpuTag v0.8.0-cu126` to the script.

Found via: [Kokoro-FastAPI GHCR package tags](https://github.com/remsky/Kokoro-FastAPI/pkgs/container/kokoro-fastapi-gpu)
and general Blackwell/PyTorch reports (this is a widespread early-Blackwell issue, not
Kokoro-specific — see e.g. [pytorch/pytorch#159207](https://github.com/pytorch/pytorch/issues/159207)).

---

## Quick start — compose

```sh
docker compose config          # check which image + overlay your .env selects
docker compose up -d           # pull + create + start
docker compose ps              # confirm "Up (healthy)" and 127.0.0.1:8880->8880/tcp
docker compose logs -f kokoro  # watch it come up / debug a crash loop
docker compose down            # stop + remove the container (image stays cached)
```

Compose reads `.env` from this directory automatically — you don't pass `-f` or `--env-file`
yourself. From the repo root, `../stack.sh --stack kokoro --up --apply` (or
`..\stack.ps1 -Stack kokoro -Up -Apply`) does the same thing.

## Quick start — script

```sh
./setup-kokoro-docker.sh                       # preview — shows the docker pull/run it would use
./setup-kokoro-docker.sh --apply               # pull + create/start (GPU, v0.8.0-cu128)
./setup-kokoro-docker.sh --cpu --apply         # CPU image — and the only mode that works on a Mac
./setup-kokoro-docker.sh --gpu-tag v0.8.0-cu126 --apply   # pin to the pre-Blackwell CUDA build
./setup-kokoro-docker.sh --undo --apply        # remove the container (image stays cached)
```

```powershell
.\setup-kokoro-docker.ps1 -Apply              # the same, on Windows
.\setup-kokoro-docker.ps1 -Cpu -Apply
.\setup-kokoro-docker.ps1 -GpuTag v0.8.0-cu126 -Apply
.\setup-kokoro-docker.ps1 -Undo -Apply
```

On macOS, running it **without** `--cpu` is refused outright rather than quietly falling back —
something that starts fine and is silently the wrong image is exactly the failure mode the Blackwell
section above exists to warn about.

Idempotent: re-running with apply against an already-running container just reports it's up;
against a stopped one it `docker start`s rather than recreating. Without apply it only prints what
it would do — nothing is changed. **The script ignores `.env`** — it takes its image from
`--cpu` / `--gpu-tag` instead, so keep the two in step if you use both.

| Parameter | Default | Notes |
|---|---|---|
| `-Cpu` / `--cpu` | off | Use the CPU image instead of the GPU one. **The two script sets differ here:** the `.ps1` pulls `...-cpu:latest`, the `.sh` pulls the pinned `...-cpu:v0.8.0` that Profile C uses. A new file should not inherit a violation of this repo's pin rule; bring the `.ps1` into line the next time it is touched. Registered in `../docs/conventions.md`. |
| `-GpuTag` / `--gpu-tag` | `v0.8.0-cu128` | GPU image tag. `v0.8.0-cu126` for GTX 900–RTX 40-series cards. Ignored with `-Cpu`. |
| `-Port` | `8880` | Host port, bound to `127.0.0.1` only. |
| `-ContainerName` | `kokoro` | |
| `-Apply` | off | Without it the script previews and changes nothing. |
| `-Undo` | off | Removes the container (`docker rm -f`). Still requires `-Apply` to write. |

---

## Verify it's actually serving audio

`docker ps` showing "Up" is not enough (see the crash-loop gotcha above) — confirm the API itself
responds and can synthesize:

Swagger UI / liveness — identical everywhere (Windows PowerShell 5.1 only: `curl.exe`):

```sh
curl -fsS -o /dev/null -w '/docs: %{http_code}\n' http://127.0.0.1:8880/docs
```

The real synthesis request is the check that matters, and **a non-zero file size is not the
assertion** — a JSON error body has one too. The content type is:

| | |
|---|---|
| macOS / Linux | <pre>curl -fsS http://127.0.0.1:8880/v1/audio/speech \\<br>  -H 'content-type: application/json' \\<br>  -d '{"model":"kokoro","input":"Hello from Kokoro.","voice":"af_heart"}' \\<br>  -o out.mp3 -w '%{content_type} %{size_download} bytes\n'</pre> |
| Windows | <pre>$body = @{ model='kokoro'; input='Hello from Kokoro.'; voice='af_heart' } \| ConvertTo-Json<br>Invoke-WebRequest -Uri http://127.0.0.1:8880/v1/audio/speech -Method Post `<br>  -ContentType 'application/json' -Body $body -OutFile out.mp3<br>Get-Item out.mp3 \| Select-Object Length</pre> |

Expect `audio/mpeg` and a non-zero size. `application/json` means an error body — read it. To
actually hear it: `afplay out.mp3` (macOS), `start out.mp3` (Windows).

If synthesis fails, or the container's state flips between `running` and `restarting`
(`docker inspect kokoro --format '{{.State.Status}}'`), check `docker logs kokoro` for the CUDA
kernel error above before assuming anything else is wrong. On a Mac that error cannot occur; check
instead that the image really is `arm64` and not being emulated:

```sh
docker inspect kokoro --format '{{.Config.Image}}'
docker image inspect ghcr.io/remsky/kokoro-fastapi-cpu:v0.8.0 --format '{{.Architecture}}'
```

(`out.mp3` is gitignored.)

---

## Notes

- **Restart policy is `unless-stopped`.** It survives Docker Desktop / machine restarts, but
  won't restart just because you explicitly stopped it.
- **`container_name: kokoro` is load-bearing on Windows.** The `claude-local` diagnostics
  (`tools/windows/diagnostics/`) find this container by that literal name. They are Windows- and
  NVIDIA-only, but the name stays stable everywhere so the stacks match. Don't rename it, and don't run a second copy of this stack under a different
  project name.
- **Removing the container doesn't remove the image.** `docker compose down` / `-Undo -Apply`
  only removes the container; run `docker rmi ghcr.io/remsky/kokoro-fastapi-gpu:v0.8.0-cu128`
  yourself to reclaim that disk space.
- **GPU contention with the display.** If this GPU also drives your monitors, every synthesis
  call competes with the desktop compositor for VRAM/GPU time and can cause cursor/desktop
  stutter. The [`claude-local`](https://github.com/martybytes/claude-local) repo
  (`tools/windows/diagnostics/gpu-tts-diagnose.ps1` and `gpu-tts-quiet.ps1`, plus
  `docs/windows/cursor-stall-gpu-tts-runbook.md`) has read-only diagnosis and a reversible "quiet it
  down" remediation for exactly that scenario — those tools work against this container regardless of
  whether it was created here or there, since they just look for a container named `kokoro`. Switch
  to Profile C here instead if you'd rather avoid the risk entirely.
