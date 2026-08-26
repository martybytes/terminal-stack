# Windows — TTS daemon (ttsd)

Console-free voice notifications for Claude Code, Cursor, and Codex. Enabling
TTS builds and installs one GUI-subsystem `terminal-stack-tts.exe`; Python is a
build-time dependency only. Hooks call that EXE directly. They do not launch
PowerShell, `cmd.exe`, Python, `ffplay`, or `ffprobe` while speaking.

`tstack config tts daemon on` adds session-aware queueing and the tray. When the
daemon is off or unreachable, the same EXE launches a detached direct worker —
never silence, and still no console window.

**Combined Windows+WSL setup: run the `tstack config tts …` verbs from WSL.**
pwsh `tstack config` saves only the Windows `config.json`, and the next WSL
`chezmoi apply` re-renders that file from chezmoi `[data]` — silently
reverting a pwsh-only change. From WSL the setting lands in `[data]` and both
sides render from it. (pwsh `daemon on` still installs/starts the daemon fine;
it prints a reminder about the WSL half.)

| Command | What it does |
|---|---|
| `tstack config tts on` | build/install the EXE if missing and enable voice hooks |
| `tstack config tts daemon on` | build/install the EXE, register direct EXE autostart, and start the tray daemon |
| `tstack config tts daemon off` | restore volumes, stop, remove autostart, back to direct playback |
| `tstack config tts daemon status` | health, queue, version-vs-clone staleness |
| `tstack config tts daemon restart` | the deliberate way to pick up a tstack update (never automatic) |
| `tstack config tts summarizer self\|haiku\|ollama\|template` | how the spoken line is written (see below) |
| `tstack config tts music duck\|smart\|pause\|off` | what happens to music while speaking (default duck) |
| `tstack config tts duck-level 30` | duck target as % of current volume |
| `tstack config tts voices show\|am_adam,af_heart,…` | per-session voice pool |
| `tstack config tts test --source claude` | synthetic event through the installed EXE |

What you hear: `"Claude. terminal-stack finished. Added the retry logic."` —
project name (with "two"/"three" when several sessions share one project),
what happened, and questions/permissions speak immediately while several
near-simultaneous "done"s coalesce into one line ("Three sessions finished:
…"). **Left-click the tray icon to mute** (it greys out with a slash; a hollow ring
means the feature is switched off entirely and no hooks are installed). The menu also
has music mode, summarizer mode, **Open dashboard**, test speak, unduck now.

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
- `ollama` — same against a local Ollama (`tstack config tts ollama <url> <model>`).

Every mode degrades rightward to `template` on any failure. `tstack config` also
reloads a reachable running daemon after saving, so changing modes does not
require `tstack config tts daemon restart`.

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
| source + PyInstaller spec | `<clone>\bootstrap\tts-daemon` (ships via tstack update) |
| installed runtime | `%LOCALAPPDATA%\terminal-stack\tts-daemon\terminal-stack-tts.exe` |
| log | `%LOCALAPPDATA%\terminal-stack\tts-daemon\logs\ttsd.log` |
| duck snapshot (crash safety) | `…\tts-daemon\state\duck-snapshot.json` |
| utterance history (SQLite) | `…\tts-daemon\state\history.db` |
| mute sentinel (existence = muted) | `…\tts-daemon\state\muted` |
| secrets (the haiku API key) | `…\tts-daemon\state\secrets.json` |
| play lock (direct path only) | `…\tts-daemon\state\speak.lock` |
| runtime knobs | `~/.claude/tts/config.json` + untracked `local.json` |
| autostart | HKCU `…\CurrentVersion\Run` → `"…\terminal-stack-tts.exe" daemon` |
| HTTP API | `http://127.0.0.1:8890` — `/healthz`, `/v1/status`, `/v1/dnd`, `/v1/duck/release`, `/v1/history`, `/v1/history/summary`, `/v1/mute`, `/ui`, `/v1/logs/stream` |

Music stuck quiet after a crash? `tstack doctor --repair` (or just start the
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

## The dashboard

Tray icon, **Open dashboard**, or `http://127.0.0.1:8890/ui`. Three tabs:

| Tab | Answers |
|---|---|
| Status | is it up, is it muted, which summarizer, how long since the daemon last spoke, and whether the summarizer has been quietly falling back to template |
| Timeline | what it decided and why, from the history database: `spoken`, `deduped`, `muted`, `suppressed_dnd`, `synth_failed`, with engine and play time |
| Log | the raw `ttsd.log`, streamed live, coloured by level, with a filter and a pause button |
| Settings | every setting the daemon reads, plus the API key and a summarizer test |

Both streams are **newest first** by default, new rows arrive at the top, and each has a
sort toggle if you would rather read oldest first.

Loopback only, and it will refuse a request whose `Host` header is not one it recognises, so
a web page you happen to be visiting cannot read your history.

### Settings

Changes are written to `~/.claude/tts/local.json`: **machine-local overrides** that win over
the saved settings and survive every apply, but do not travel to your other machines. For a
setting that should propagate, use `tstack config tts …` from WSL. Every field shows which layer
it came from, and says so when an override is beating the saved value.

Three groups are called out because they are not what they look like:

- **Needs a restart** holds the eleven settings the daemon reads once at startup. A config
  reload returns success without applying them, so the page marks them and offers the
  restart rather than pretending.
- **Shell fallback only** holds four settings the daemon never reads. They are live on the
  WSL and PowerShell fallback path, which is what speaks when the daemon is down.
- **Secrets** holds the Anthropic key for `haiku`, stored in the daemon's state directory,
  never in either config store and never in git. An environment variable still works, but
  the daemon starts at logon and cannot see one you export afterwards.

**Test the current mode** is the button worth knowing about. A missing API key makes `haiku`
behave exactly like `template`, with nothing in any log, so the test reports which mode
actually ran, where the key came from, the latency, and whether it fell back and why.

Two things it deliberately does not claim:

- **An empty timeline is not "all quiet".** Every history function fails open and returns
  nothing when its database is unusable, so the page says so rather than implying silence.
- **Non-template summarizer modes only apply to `waiting` announcements.** Questions,
  permission prompts and errors are always the template line, and a coalesced
  multi-session line bypasses every mode. That is by construction, not a fault.

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
`tstack doctor` all report it, so a mute you forgot about cannot masquerade as broken TTS.

**`ccmute` is not `cctts off`.** `cctts off` is the structural switch: it rewrites the
saved setting and removes the hooks on the next apply, taking 5–15 seconds and a wall of
output. `ccmute` writes one sentinel file. Use `ccmute` for a call and `cctts off` when you
want the feature gone.

If nothing speaks and `ccmute status` says *not muted*, check
`~/.claude/tts/local.json` for `"enabled": false` — that untracked override wins over the
rendered config, and it is the one thing that can silence everything while `cctts` still
reports ON. `tstack doctor` now flags it.

## It said the same thing twice (or two voices at once)

Ask it what happened — every decision is recorded, including the ones where it stayed quiet:

```powershell
tstack config tts history            # last 25 decisions, oldest first
tstack config tts history 60         # more of them
tstack config tts history --dupes    # anything that spoke twice inside 8s, last 24h
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

- **`tstack config tts daemon status` first.** While the daemon is down each hook speaks from
  its own detached process. They still take turns (a lock file serialises them) and still
  deduplicate through the shared history, but the daemon is the path that also coalesces —
  "Two sessions finished: …" — so its absence is worth knowing about. It now restarts
  itself on the next hook; `tstack doctor` says how long it has been silent.
- **The window is `debounceSec`** in `~/.claude/tts/config.json` (5 seconds). Raise it in
  the untracked `local.json` if two genuinely different announcements are landing on top of
  each other; set it to `0` to turn deduplication off entirely and hear everything.
- **A missing `history.db` is not an error.** Every read and write there fails open, so
  broken storage degrades to "might repeat itself", never to silence.

Overlapping *audio* specifically — two voices talking at once rather than one line said
twice — should be impossible now on both paths: the daemon speaks from a single dispatcher
thread, and direct workers hold `state\speak.lock` across synth and playback. If you hear
it anyway, get the timestamps from `tstack config tts history` and check whether the `pid`
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

Disagree? Re-save **from WSL** — `tstack config tts on` — which is the only path
that writes both stores, then confirm `~/.claude/settings.json` has TTS entries
under `Stop`, `StopFailure`, `Notification` and the
`AskUserQuestion` `PreToolUse` matcher. Same rule for every `tstack config`
setting on a combined Windows+WSL machine, not just TTS.

## WSL reachability

WSL hooks invoke the installed Windows EXE through interop, so hook execution
does not need a WSL-to-Windows HTTP hop. The EXE itself uses loopback. The
daemon also retains a token-guarded WSL gateway listener for API/status tools;
its shared token is at `…\tts-daemon\state\token`. The installer tries to add an inbound
firewall rule for that listener and prints an elevated one-liner when it can't
— but check before bothering: on at least one machine the gateway path worked
with **no** rule (the `vEthernet (WSL)` interface profile already allowed it).
Verify with `tstack config tts daemon status` from WSL; if it reports unreachable
there while healthy on Windows, the firewall rule is the thing to add. Either
way, unreachable only affects WSL API/status probes; spoken hooks still use the EXE.
