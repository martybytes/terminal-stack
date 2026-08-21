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
…"). Tray icon menu: DND, mute 1 hour, music mode, summarizer mode, test
speak, unduck now.

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
| runtime knobs | `~/.claude/tts/config.json` + untracked `local.json` |
| autostart | HKCU `…\CurrentVersion\Run` → `"…\terminal-stack-tts.exe" daemon` |
| HTTP API | `http://127.0.0.1:8890` — `/healthz`, `/v1/status`, `/v1/dnd`, `/v1/duck/release` |

Music stuck quiet after a crash? `ts-doctor --repair` (or just start the
daemon — it restores the stale snapshot at startup). Emergency by hand:
NirSoft `svcl.exe /SetVolume Spotify.exe 100`.

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
