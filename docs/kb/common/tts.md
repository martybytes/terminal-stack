# Agent voice notifications

Claude Code, Cursor and Codex speak when they finish, hit an error, or need you.
Turn it on with `ts-config tts on`, off with `cctts off`.

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
| `ts-config tts history`, `/ui` dashboard | ❌ | ✅ |
| per-session voices (`voices`) | ❌ | ✅ |

Anything marked ❌ now **refuses with a reason** rather than accepting a value
nothing will read. That was not always true: `ts-config tts music duck` used to
save happily on a Mac and do nothing.

## Commands

`ts-config tts` on its own prints the effective config.

| Command | What it does |
|---|---|
| `ts-config tts` / `show` | effective config (config.json + local.json) |
| `cctts` / `cctts on` / `cctts off` | quick status and toggle |
| `ts-config tts test [--source claude\|cursor\|codex]` | speak a fixed line. **Ignores any text you pass** |
| `ts-config tts engine kokoro\|chatterbox\|auto` | which synthesiser to try first |
| `ts-config tts voice <name>` / `voice-chatter <name>` | per-engine voice |
| `ts-config tts excitement <0-1>` | speaking rate |
| `ts-config tts events waiting,error,question,permission` | when it speaks |
| `ts-config tts message template\|hook` | fixed line, or read the last message raw |
| `ts-config tts summarizer template\|self` | what a "finished" announcement says |
| `ts-config tts template waiting\|error\|… "…"` | reword one announcement |
| `ts-config tts prefix claude\|cursor\|codex on\|off\|<label>` | who is speaking |
| `ts-config tts project on\|off` | include the project name |
| `ts-config tts reset` | back to defaults |

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

`self` **edits your instruction files.** `ts-config tts summarizer self` appends
a marker-delimited block to `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` so the
agent knows to write that line; `ts-config tts summarizer template` removes it
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

## Which engine actually speaks

Tried in order, first one that works wins:

1. **Kokoro** — `http://127.0.0.1:8880`, a Docker container **you** run. Nothing
   here installs it.
2. **Chatterbox** — `http://127.0.0.1:8881`, same deal.
3. **edge-tts** — `pip install edge-tts`. A cloud voice; needs network.
4. **the offline floor** — `say` on macOS, SAPI on Windows.

The wizard probes all of these and tells you which are reachable before you
choose. If you hear the system voice instead of your usual one, the floor caught
a fallback — Kokoro is probably down. A once-a-day notice says so.

## It went quiet

- **`~/.claude/tts/local.json` with `"enabled": false`** overrides everything and
  is the most common silent killer. `ts-config tts` shows the effective value.
- **A `chezmoi apply` from the wrong side.** On combined WSL+Windows, run
  `ts-config tts …` from **WSL** — a pwsh save writes only the `config.json`
  mirror, so the next WSL apply renders the setting back off. This removed all
  five Claude TTS hooks once, with no error.
- **`ccTtsEnabled` off** removes the hooks entirely on the next apply, which is
  different from `ccmute` (instant, no apply, Windows only).

Windows extras — the tray, the dashboard, mute, duplicate suppression, the WSL
firewall path — are in `doc windows/tts-daemon`.

See also `doc common/claude-code`, `doc ts-config`.
