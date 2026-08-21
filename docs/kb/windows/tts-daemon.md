# Windows — TTS daemon (ttsd)

Session-aware voice notifications for Claude Code and Cursor. Opt-in twice:
`ts-config tts on` (the classic TTS layer) + `ts-config tts daemon on` (this
daemon). When the daemon is off or dead, hooks fall back to classic direct
playback — never silence.

**Combined Windows+WSL setup: run the `ts-config tts …` verbs from WSL.**
pwsh `ts-config` saves only the Windows `config.json`, and the next WSL
`chezmoi apply` re-renders that file from chezmoi `[data]` — silently
reverting a pwsh-only change. From WSL the setting lands in `[data]` and both
sides render from it. (pwsh `daemon on` still installs/starts the daemon fine;
it prints a reminder about the WSL half.)

| Command | What it does |
|---|---|
| `ts-config tts daemon on` | install (venv + autostart), start, and route hooks through the daemon |
| `ts-config tts daemon off` | restore volumes, stop, remove autostart, back to direct playback |
| `ts-config tts daemon status` | health, queue, version-vs-clone staleness |
| `ts-config tts daemon restart` | the deliberate way to pick up a ts-update (never automatic) |
| `ts-config tts summarizer self\|haiku\|ollama\|template` | how the spoken line is written (see below) |
| `ts-config tts music duck\|smart\|pause\|off` | what happens to music while speaking (default duck) |
| `ts-config tts duck-level 30` | duck target as % of current volume |
| `ts-config tts voices show\|am_adam,af_heart,…` | per-session voice pool |
| `cc-tts-test.sh --daemon` / `-Daemon` | synthetic event through the daemon |
| `cc-tts-test.sh --daemon-fallback` / `-DaemonFallback` | prove direct playback survives a dead daemon |

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

Cursor's stop/question hooks already POST to the daemon (the daemon holds and
cools Cursor's per-turn stop storms). For `self`-mode summaries in Cursor, add
a **User Rule** by hand (Cursor Settings → Rules — the rules store is GUI-only,
the stack cannot manage it):

> At the very end of your final message each turn, append an HTML comment
> `<!-- speak: <one spoken-style sentence, 15 words or fewer> -->` describing
> what you did or what you need. Plain words only — no code, no paths. Omit it
> for trivial turns.

Without the rule, Cursor still speaks the locally derived summary; it does not
repeat the fixed waiting template unless the hook supplied no response text.

## Where things live

| Thing | Path |
|---|---|
| daemon source | `<clone>\bootstrap\tts-daemon\ttsd` (ships via ts-update) |
| venv (survives pulls) | `%LOCALAPPDATA%\terminal-stack\tts-daemon\venv` |
| log | `%LOCALAPPDATA%\terminal-stack\tts-daemon\logs\ttsd.log` |
| duck snapshot (crash safety) | `…\tts-daemon\state\duck-snapshot.json` |
| runtime knobs | `~/.claude/tts/config.json` + untracked `local.json` |
| autostart | HKCU `…\CurrentVersion\Run` → `terminal-stack-tts-daemon` |
| HTTP API | `http://127.0.0.1:8890` — `/healthz`, `/v1/status`, `/v1/dnd`, `/v1/duck/release` |

Music stuck quiet after a crash? `ts-doctor --repair` (or just start the
daemon — it restores the stale snapshot at startup). Emergency by hand:
NirSoft `svcl.exe /SetVolume Spotify.exe 100`.

## WSL reachability

NAT-mode WSL can't reach the daemon on `127.0.0.1`; the hook sender walks a
ladder (config `daemon.hostOverride` → loopback → default gateway → resolv.conf
nameserver) and authenticates against the gateway listener with the shared
token at `…\tts-daemon\state\token`. The installer tries to add an inbound
firewall rule for that listener and prints an elevated one-liner when it can't
— but check before bothering: on at least one machine the gateway path worked
with **no** rule (the `vEthernet (WSL)` interface profile already allowed it).
Verify with `ts-config tts daemon status` from WSL; if it reports unreachable
there while healthy on Windows, the firewall rule is the thing to add. Either
way, unreachable only ever means WSL hooks fall back to direct playback.
