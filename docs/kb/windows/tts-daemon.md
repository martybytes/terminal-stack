# Windows — TTS daemon (ttsd)

Console-free voice notifications for Claude Code, Cursor, and Codex. Enabling
TTS builds and installs one GUI-subsystem `terminal-stack-tts.exe`; Python is a
build-time dependency only. Hooks call that EXE directly. They do not launch
PowerShell, `cmd.exe`, Python, `ffplay`, or `ffprobe` while speaking.

`ts-config tts daemon on` adds session-aware queueing and the tray. When the
daemon is off or unreachable, the same EXE launches a detached direct worker —
never silence, and still no console window.

**Combined Windows+WSL setup: run the `ts-config tts …` verbs from WSL.**
pwsh `ts-config` saves only the Windows `config.json`, and the next WSL
`chezmoi apply` re-renders that file from chezmoi `[data]` — silently
reverting a pwsh-only change. From WSL the setting lands in `[data]` and both
sides render from it. (pwsh `daemon on` still installs/starts the daemon fine;
it prints a reminder about the WSL half.)

| Command | What it does |
|---|---|
| `ts-config tts on` | build/install the EXE if missing and enable voice hooks |
| `ts-config tts daemon on` | build/install the EXE, register direct EXE autostart, and start the tray daemon |
| `ts-config tts daemon off` | restore volumes, stop, remove autostart, back to direct playback |
| `ts-config tts daemon status` | health, queue, version-vs-clone staleness |
| `ts-config tts daemon restart` | the deliberate way to pick up a ts-update (never automatic) |
| `ts-config tts summarizer self\|haiku\|ollama\|template` | how the spoken line is written (see below) |
| `ts-config tts music duck\|smart\|pause\|off` | what happens to music while speaking (default duck) |
| `ts-config tts duck-level 30` | duck target as % of current volume |
| `ts-config tts voices show\|am_adam,af_heart,…` | per-session voice pool |
| `ts-config tts test --source claude` | synthetic event through the installed EXE |

What you hear: `"Claude. terminal-stack finished. Added the retry logic."` —
project name (with "two"/"three" when several sessions share one project),
what happened, and questions/permissions speak immediately while several
near-simultaneous "done"s coalesce into one line ("Three sessions finished:
…"). **Left-click the tray icon to mute** (it greys out with a slash); the menu also
has music mode, summarizer mode, test speak, unduck now.

## Summarizer modes

- `template` (default) — fixed lines enriched by the typed hook state
  (rate-limited vs billing error, which tool wants permission, …).
- `self` — the model itself ends each turn with `<!-- speak: one sentence -->`
  and the daemon reads only that (zero added latency). Installing this mode
  adds removable marker blocks to Claude's `~/.claude/CLAUDE.md` and Codex's
  active global `$CODEX_HOME/AGENTS.md` (or `AGENTS.override.md` when present).
  Cursor User Rules are GUI-managed, and an existing Codex session loads its
  instructions only once, so a missing marker derives a short sentence locally
  from the final-response hook text. Only an empty response falls back to the
  waiting template. Switching away removes every stack-owned marker block.
- `haiku` — Claude Haiku rewrites the final message into one spoken sentence
  (~1 s, needs `ANTHROPIC_API_KEY` in the daemon's environment).
- `ollama` — same against a local Ollama (`ts-config tts ollama <url> <model>`).

Every mode degrades rightward to `template` on any failure. `ts-config` also
reloads a reachable running daemon after saving, so changing modes does not
require `ts-config tts daemon restart`.

## Cursor

Cursor's completion hook uses `afterAgentResponse`, because Cursor's `stop`
payload contains status but no response text; `stop` remains installed for
errors. In `self` mode, the final response is locally shortened to one spoken
sentence when no explicit marker exists. For the best wording, optionally add
this **User Rule** in Cursor Settings → Rules:

> At the very end of your final message each turn, append an HTML comment
> `<!-- speak: <one spoken-style sentence, 15 words or fewer> -->` describing
> what you did or what you need. Plain words only — no code, no paths. Omit it
> for trivial turns.

Without the rule, Cursor still speaks the locally derived summary; it does not
repeat the fixed waiting template unless the hook supplied no response text.

## Where things live

| Thing | Path |
|---|---|
| source + PyInstaller spec | `<clone>\bootstrap\tts-daemon` (ships via ts-update) |
| installed runtime | `%LOCALAPPDATA%\terminal-stack\tts-daemon\terminal-stack-tts.exe` |
| log | `%LOCALAPPDATA%\terminal-stack\tts-daemon\logs\ttsd.log` |
| duck snapshot (crash safety) | `…\tts-daemon\state\duck-snapshot.json` |
| utterance history (SQLite) | `…\tts-daemon\state\history.db` |
| mute sentinel (existence = muted) | `…\tts-daemon\state\muted` |
| play lock (direct path only) | `…\tts-daemon\state\speak.lock` |
| runtime knobs | `~/.claude/tts/config.json` + untracked `local.json` |
| autostart | HKCU `…\CurrentVersion\Run` → `"…\terminal-stack-tts.exe" daemon` |
| HTTP API | `http://127.0.0.1:8890` — `/healthz`, `/v1/status`, `/v1/dnd`, `/v1/duck/release`, `/v1/history`, `/v1/mute` |

Music stuck quiet after a crash? `ts-doctor --repair` (or just start the
daemon — it restores the stale snapshot at startup). Emergency by hand:
NirSoft `svcl.exe /SetVolume Spotify.exe 100`.

## Did it actually speak?

`terminal-stack-tts.exe` is a GUI-subsystem binary: it writes nothing to the console and
**exits 0 whether or not anything was spoken**. The exit code is not evidence. The
authoritative signal is a line in the daemon log (`logs/ttsd.log`, path in the table above):

```
I ttsd.pipeline: spoke [kokoro]: Claude. Done in terminal-stack two. I'm waiting for you.
```

No `spoke` line means no audio, however healthy everything looked. A `ttsd.registry:
session … voice=…` line only proves the daemon *received* the event.

**`test` takes no text.** `terminal-stack-tts.exe test "say this"` silently ignores the
argument — `test_payload()` builds a fixed `stop`/`waiting` event with an empty message and
the positional argument is never read. It exercises the pipeline, not a phrase of your
choosing. To have the voice say something specific, use the `self` summarizer: end the
turn with a `<!-- speak: … -->` marker, which is what the Stop hook reads.

## Going quiet for a call

```powershell
ccmute            # toggle. Also: ccmute on | off | status
```

Four ways to the same switch, all instant and none of them touching config or running an
apply:

| | |
|---|---|
| `ccmute` | either shell; works with the daemon stopped |
| left-click the tray icon | it greys out with a slash while muted |
| `Ctrl+Alt+Shift+M` | anywhere, including with Teams focused |
| `Leader+m` | in WezTerm; the status bar shows a `MUTED` chip |

It is **sticky** — muted until you unmute — and **absolute**: questions, permission
prompts and errors are silenced too, which the old tray "Do not disturb" never did. Muting
also cuts off whatever is speaking at that moment. It survives a reboot and the daemon
dying, because it is a file (`state\muted`); `ccmute status`, the WezTerm chip and
`ts-doctor` all report it, so a mute you forgot about cannot masquerade as broken TTS.

**`ccmute` is not `cctts off`.** `cctts off` is the structural switch: it rewrites the
saved setting and removes the hooks on the next apply, taking 5–15 seconds and a wall of
output. `ccmute` writes one sentinel file. Use `ccmute` for a call and `cctts off` when you
want the feature gone.

If nothing speaks and `ccmute status` says *not muted*, check
`~/.claude/tts/local.json` for `"enabled": false` — that untracked override wins over the
rendered config, and it is the one thing that can silence everything while `cctts` still
reports ON. `ts-doctor` now flags it.

## It said the same thing twice (or two voices at once)

Ask it what happened — every decision is recorded, including the ones where it stayed quiet:

```powershell
ts-config tts history            # last 25 decisions, oldest first
ts-config tts history 60         # more of them
ts-config tts history --dupes    # anything that spoke twice inside 8s, last 24h
```

```
13:49:10  spoken       p0 question   direct kokoro   5.8s    Claude. alpha: I have a question…
13:49:10  deduped      p0 question   direct                  Claude. alpha: I have a question…
13:49:11  deduped      p0 question   direct                  Claude. alpha: I have a question…
```

That is the healthy shape. **One `AskUserQuestion` fires two hooks** — `Notification` and
the `AskUserQuestion` `PreToolUse` matcher — so seeing two rows per question is normal;
seeing two `spoken` rows is not. `--dupes` reporting nothing over a day of work is the
check that matters. (A third hook, `PermissionRequest`, was removed: it said "wants to run
AskUserQuestion. AskUserQuestion" and added nothing.)

If duplicates *are* showing up:

- **`ts-config tts daemon status` first.** While the daemon is down each hook speaks from
  its own detached process. They still take turns (a lock file serialises them) and still
  deduplicate through the shared history, but the daemon is the path that also coalesces —
  "Two sessions finished: …" — so its absence is worth knowing about. It now restarts
  itself on the next hook; `ts-doctor` says how long it has been silent.
- **The window is `debounceSec`** in `~/.claude/tts/config.json` (5 seconds). Raise it in
  the untracked `local.json` if two genuinely different announcements are landing on top of
  each other; set it to `0` to turn deduplication off entirely and hear everything.
- **A missing `history.db` is not an error.** Every read and write there fails open, so
  broken storage degrades to "might repeat itself", never to silence.

Overlapping *audio* specifically — two voices talking at once rather than one line said
twice — should be impossible now on both paths: the daemon speaks from a single dispatcher
thread, and direct workers hold `state\speak.lock` across synth and playback. If you hear
it anyway, get the timestamps from `ts-config tts history` and check whether the `pid`
column shows two different processes overlapping.

## Voice went silent after an apply

Almost always the two config stores disagreeing, not the daemon. A save from
pwsh writes only `%LOCALAPPDATA%\terminal-stack\config.json`; chezmoi `[data]`
in WSL is what a `chezmoi apply` reads. When they differ, each side renders a
valid `~/.claude/settings.json` from its own store and whichever applied last
wins — so TTS works, then quietly stops, then works again.

Check them against each other:

```sh
chezmoi execute-template '{{ .ccTtsEnabled }}'      # from WSL — authoritative
```

```powershell
(Get-Content "$env:LOCALAPPDATA\terminal-stack\config.json" | ConvertFrom-Json).ccTts.enabled
```

Disagree? Re-save **from WSL** — `ts-config tts on` — which is the only path
that writes both stores, then confirm `~/.claude/settings.json` has TTS entries
under `Stop`, `StopFailure`, `Notification` and the
`AskUserQuestion` `PreToolUse` matcher. Same rule for every `ts-config`
setting on a combined Windows+WSL machine, not just TTS.

## WSL reachability

WSL hooks invoke the installed Windows EXE through interop, so hook execution
does not need a WSL-to-Windows HTTP hop. The EXE itself uses loopback. The
daemon also retains a token-guarded WSL gateway listener for API/status tools;
its shared token is at `…\tts-daemon\state\token`. The installer tries to add an inbound
firewall rule for that listener and prints an elevated one-liner when it can't
— but check before bothering: on at least one machine the gateway path worked
with **no** rule (the `vEthernet (WSL)` interface profile already allowed it).
Verify with `ts-config tts daemon status` from WSL; if it reports unreachable
there while healthy on Windows, the firewall rule is the thing to add. Either
way, unreachable only affects WSL API/status probes; spoken hooks still use the EXE.
