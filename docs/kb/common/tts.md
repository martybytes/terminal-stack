# Agent voice notifications

Claude Code, Cursor and Codex speak when they finish, hit an error, or need you.
Turn it on with `tstack config tts on`, off with `cctts off`.

## What works where

The feature is split: a **direct path** that every platform has, and a **tray
daemon** that only Windows has. Most of the "smart" options live in the daemon.

| | macOS / native Linux | Windows (+ WSL) |
|---|---|---|
| speak on finish / error / question / permission | ✅ | ✅ |
| Kokoro, Chatterbox, edge-tts engines | ✅ | ✅ |
| offline floor when none are reachable | ✅ `say` (macOS) | ✅ SAPI |
| `template` and `self` summaries | ✅ | ✅ |
| `haiku` / `ollama` summaries | ❌ daemon-only — refused, not silently stored | ✅ |
| music ducking (`music`, `duck-level`) | ❌ daemon-only, pycaw/WinRT — refused | ✅ |
| `ccmute`, global hotkey, tray icon | ❌ | ✅ |
| `tstack config tts history`, `/ui` dashboard | ❌ | ✅ |
| per-session voices (`voices`) | ❌ | ✅ |

Anything marked ❌ now **refuses with a reason** rather than accepting a value
nothing will read. That was not always true: `tstack config tts music duck` used to
save happily on a Mac and do nothing.

## Commands

`tstack config tts` on its own prints the effective config.

| Command | What it does |
|---|---|
| `tstack config tts` / `show` | effective config (config.json + local.json) |
| `cctts` / `cctts on` / `cctts off` | quick status and toggle |
| `tstack config tts test [--source claude\|cursor\|codex]` | speak a fixed line. **Ignores any text you pass** |
| `tstack config tts engine kokoro\|chatterbox\|say\|auto` | which synthesiser to try first (`say` is macOS-only) |
| `tstack config tts voices` | list what the active engine can produce |
| `tstack config tts voices <name>` | play a sample in that voice |
| `tstack config tts voice-say <name\|system>` | the macOS system voice |
| `tstack config tts voice-pool <v1,v2,…>` | the daemon's per-session rotation (Windows) |
| `tstack config tts voice <name>` / `voice-chatter <name>` | per-engine voice |
| `tstack config tts excitement <0-1>` | speaking rate |
| `tstack config tts events waiting,error,question,permission` | when it speaks |
| `tstack config tts message template\|hook` | fixed line, or read the last message raw |
| `tstack config tts summarizer template\|self` | what a "finished" announcement says |
| `tstack config tts template waiting\|error\|… "…"` | reword one announcement |
| `tstack config tts prefix claude\|cursor\|codex on\|off\|<label>` | who is speaking |
| `tstack config tts project on\|off` | include the project name |
| `tstack config tts reset` | back to defaults |

## What it says when the agent finishes

- **`template`** — the same sentence every time: *"Done in myproject. I'm
  waiting for you."* Needs nothing.
- **`self`** — the agent writes its own one-liner, so you hear *"Migrated the
  parser and all tests pass."* **No extra model call and no added latency**: the
  agent appends a hidden `<!-- speak: … -->` marker to its final message and the
  hook reads it. If there is no marker, the first prose sentence is used instead,
  capped at 15 words.
- **`hook`** — reads the agent's last message out raw, truncated to `maxChars`.
  Blunt, but needs no instruction block.

`self` **edits your instruction files.** `tstack config tts summarizer self` appends
a marker-delimited block to `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` so the
agent knows to write that line; `tstack config tts summarizer template` removes it
again. The block is bounded by `<!-- terminal-stack-tts-start -->` markers and
the file is backed up first.

The direct POSIX hook prefers `jq` when reading the final agent message and falls
back to Python when `jq` is absent. Codex's top-level `last_assistant_message` and
Claude-style transcript payloads produce the same self summary, including on a
minimal host without `jq`.

Applied to the **finish** event only. A question or a permission prompt keeps its
template, because a line written for "I'm done" is the wrong thing to say when
the agent is waiting on you.

`haiku` and `ollama` send the final message to a model for a one-sentence
summary. Both need the daemon; `haiku` also needs an API key, `ollama` a local
server. On a host without a daemon they are refused.

## Choosing a voice

```sh
tstack config tts voices              # what the active engine can produce
tstack config tts voices af_heart     # hear it
tstack config tts voice af_heart      # kokoro
tstack config tts voice-say Samantha  # macOS system voice
```

Nothing is hardcoded: kokoro is asked over `GET /v1/audio/voices` (68 in the
v0.8.0 image, and the set moves with the image) and macOS is asked with
`say -v '?'` (184 installed here, more from System Settings → Accessibility →
Spoken Content → Manage Voices). If the saved engine is kokoro but the container
is down, the macOS list is shown instead — offering a list you cannot hear is
worse than offering the one you can.

`voices` used to set the daemon's rotation pool. That is `voice-pool` now; the
old comma-separated form redirects rather than silently doing the wrong thing.

## Which engine actually speaks

Tried in order, first one that works wins:

1. **Kokoro** — `http://127.0.0.1:8880`, a Docker container **you** run. Nothing
   here installs it.
2. **Chatterbox** — `http://127.0.0.1:8881`, same deal.
3. **edge-tts** — `pip install edge-tts`. A cloud voice; needs network.
4. **the offline floor** — `say` on macOS, SAPI on Windows. Neither needs a
   running service; SAPI also needs no player, which matters because the
   Windows playback path requires `ffplay`. Linux has no floor: if every
   engine is down there, it is silent.

The wizard probes all of these and tells you which are reachable before you
choose. If you hear the system voice instead of your usual one, the floor caught
a fallback — Kokoro is probably down. A once-a-day notice says so.

## It went quiet

- **`~/.claude/tts/local.json` with `"enabled": false`** overrides everything and
  is the most common silent killer. `tstack config tts` shows the effective value.
- **A Windows-standalone install reporting a setting you never chose.** The two
  stores spell the TTS block differently: chezmoi `[data]` is flat
  (`ccTtsKokoroVoice`), the mirror nests (`ccTts.kokoro.voice`) because the daemon
  reads that file too. Until 08/28/2026 the reader derived the nested name wrongly
  for every key below the top level, missed, and served the default instead — so a
  voice, URL, template or timeout set on Windows read back as the shipped default
  with nothing reporting a problem. `tstack config show` now names the layer each
  value came from, which is what makes this visible rather than merely fixed.

- **A `chezmoi apply` from the wrong side.** On combined WSL+Windows, run
  `tstack config tts …` from **WSL** — a pwsh save writes only the `config.json`
  mirror, so the next WSL apply renders the setting back off. This removed all
  five Claude TTS hooks once, with no error.
- **`ccTtsEnabled` off** removes the hooks entirely on the next apply, which is
  different from `ccmute` (instant, no apply, Windows only).

Windows extras — the tray, the dashboard, mute, duplicate suppression, the WSL
firewall path — are in `doc windows/tts-daemon`.

See also `doc common/claude-code`, `doc tstack config`.
