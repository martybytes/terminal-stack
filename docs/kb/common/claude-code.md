# Claude Code helpers

zsh aliases / pwsh functions. Each `cc*` sets the WezTerm tab title while Claude runs.

| Shortcut | Full command | What it does |
|---|---|---|
| `cc` | `claude` | launch Claude Code |
| `ccc` | `claude --continue` | continue last conversation |
| `ccd` | `claude --dangerously-skip-permissions` | no permission prompts |
| `ccdc` | `claude --dangerously-skip-permissions --continue` | both |
| `ccr` | `claude --resume` | pick a past session to resume |
| `ccdr` | `claude --dangerously-skip-permissions --resume` | both |
| `cca` | `claude agents` | agents view |
| `ccs name` | tmux session `cc-name` running `claude --name name` | zsh only — Claude in tmux, survives disconnects; defaults to current dir name |

`ccnotify on` / `off` toggles the done/error toast (zsh + pwsh).

**Agent shells:** Cursor Agent and hook subprocesses often run with `TERM=dumb`.
The stack skips Starship and OSC title sequences in those shells while keeping
git shortcuts, zoxide, and `cc*` wrappers. See `doc windows/pwsh` § "Agent vs
interactive terminals".

## Who owns `~/.claude/settings.json`

Shared file. The stack renders `statusLine`, `hooks` and `theme`; **Claude Code owns
everything else** — `model` (from `/model`), `enabledPlugins` and
`extraKnownMarketplaces` (from `/plugin`), `permissions`, `env`.

On Windows the sync splices its three keys in and leaves the rest byte-for-byte
(`bootstrap/_merge_cursor_hooks.ps1` does the same for `~/.cursor/hooks.json`, per hook
entry). So installing a plugin, switching model, or allowing an MCP tool survives an
apply — and per-machine wiring an app needs (an MCP server URL in `env`, say) belongs
in that file rather than in the repo.

Two things follow:

- **Don't `chezmoi re-add` it.** That captures Claude Code's private state into the
  tracked template and pushes it to every machine on the next apply.
- **A plugin that silently stops working is worth checking here first.** If
  `enabledPlugins` loses an entry, the plugin's hooks and MCP server just stop
  loading — no error, nothing in `chezmoi diff`. The `.bak.yyyyMMdd[.N]` chain beside
  the file shows what a write removed.

## agentmemory

If a local agentmemory server is running, `bootstrap\ts-agentmemory.ps1` wires this agent to it:
the tagged URL and `AGENTMEMORY_INJECT_CONTEXT` in `~/.claude/settings.json`'s `env`, plus edits
to the plugin's own hook scripts. It runs from every sync, so nothing needs doing by hand.

Two things worth knowing:

- **A plugin upgrade reverts the hook-script edits** and retrieval silently stops (capture keeps
  working, so nothing looks broken). The next `ts-update` repairs it; `ts-doctor` reports it.
- **Retrieval is on by default.** Set `AGENTMEMORY_INJECT_CONTEXT=false` to turn it off
  deliberately. Nothing is wired at all when the plugin is not installed.

Not retrieving? Check `ts-doctor` first, then that the agent was started *after* any environment
change — hooks read their environment at process start.

## Statusline

The three-line footer under the prompt is `~/.claude/statusline-command.sh`
(chezmoi-managed; needs `python3` — any segment whose data is missing simply
drops out):

| Line | Segments |
|---|---|
| 1 | cwd \| branch + status \| `owner/repo` |
| 2 | model \| `ctx` % + bar \| `5h` budget % + bar + reset \| `7d` budget % + bar + reset |
| 3 | `user@host` \| tokens (`205k/1M tok`) \| `cost: $X.XX` \| `+N/-M lines` |

Branch status is `✓` when clean, else the non-zero counts as
`+staged ~modified -deleted ?untracked !conflicts`, plus `↑ahead ↓behind` of
upstream. The 10-segment bars are green below 70%, yellow at 70-89%, red at 90%+.
`5h`/`7d` are the rate-limit budgets; the grey suffix is the reset as one coarse
unit (`14m`, `2h`, `2d`).

## Enter vs Shift+Enter

`~/.claude/keybindings.json` binds `Enter` = submit, `Shift+Enter` = newline. Most
terminals never deliver a distinct Shift+Enter to the app, so that binding alone
can't fire — WezTerm closes the gap by sending a literal LF (`Ctrl+J`, the default
newline binding) for `Shift+Enter`; see `doc wezterm/panes` § "Literal keys".
Inside tmux it survives thanks to `extended-keys`/`allow-passthrough` — see
`doc common/tmux`.

## Local TTS (Kokoro / Chatterbox / edge)

Optional voice when an agent **finishes**, **errors**, **asks a question**, or **needs permission**. Shared config under `~/.claude/tts/`. **Off by default.**

| Command | What it does |
|---|---|
| `cctts on` / `off` | Enable/disable TTS (re-applies; adds/removes hooks in Claude + Cursor) |
| `cctts test` | Generic end-to-end synth + play test |
| `ts-config tts test --source claude` | Test with Claude prefix + template |
| `ts-config tts test --source cursor` | Test with Cursor prefix + template |
| `ts-config tts test --source codex` | Test with Codex prefix + template |
| `ts-config tts …` | Full control (prefix, project, excitement, templates, events) |
| `ts-config tts daemon on` | Windows: session-aware announcements via the ttsd tray daemon (names the project, coalesces, ducks music) — `doc windows/tts-daemon` |
| `/test-voice` | Slash command in Claude Code or Cursor (user home) |
| `ts-config tts history [--dupes]` | Windows: what was spoken and what was suppressed — the answer to "why did it say that twice" (`doc windows/tts-daemon`) |
| `ccmute` | Silence it instantly for a call — sticky, absolute, works with the daemon stopped. Also the tray icon, `Ctrl+Alt+Shift+M`, or `Leader+m` |

### Config layout

| Path | Managed? | Purpose |
|---|---|---|
| `~/.claude/tts/config.json` | yes (chezmoi) | Engine, voices, templates, prefixes, events |
| `~/.claude/tts/local.json` | **no** | Per-machine overrides (copy from `local.json.example`) |
| Legacy `~/.claude/tts.json` | migrated once | Auto-copied to `tts/config.json` on first hook run |

`ts-config tts show` prints chezmoi `[data]`; after apply, hooks read **merged** `config.json` + `local.json`.

Key knobs: `sources.claude|cursor|codex.prefix`, `announce.includeProject`, `announce.templates.{waiting,error,question,permission}`, `excitement` (0–1, drives Kokoro speed / Chatterbox energy).

### Hook wiring

| App | Event | When it speaks |
|---|---|---|
| Claude Code | `Stop` / `StopFailure` | Agent finished / failed |
| Claude Code | `Notification` / `PreToolUse` (`AskUserQuestion`) | Needs attention or permission / clarifying question |

One `AskUserQuestion` trips **both** of those Claude hooks, ~2.5s apart. You hear it once: the daemon and every fallback worker check a shared utterance history before speaking, so the second is recorded as `deduped` rather than said. `ts-config tts history` shows both. (A third hook, `PermissionRequest`, was dropped — it echoed the tool name twice and `Notification` already covers permission prompts.)
| Cursor Agent | `afterAgentResponse` | Agent final response completed |
| Cursor Agent | `stop` | Agent loop failed (`completed` / `aborted` are silent) |
| Cursor Agent | `postToolUse` (`AskQuestion`) | Plan-mode / clarifying question UI |
| Codex (`cy` / `cyr`) | `Stop` | Agent turn ended |

On Windows and WSL, every hook calls the console-free **`terminal-stack-tts.exe`** directly. It uses Kokoro/Chatterbox/edge synthesis and WinRT playback in-process; prefixes **`Claude.`** / **`Cursor.`** / **`Codex.`** are configurable per source. Native Linux/macOS retain the shell `cc-tts-notify` path.

### Prerequisites

- **Kokoro** (primary): `http://127.0.0.1:8880` — e.g. `remsky/kokoro-fastapi-gpu` in Docker.
- **Chatterbox** (optional): `http://127.0.0.1:8881`.
- **edge-tts** (fallback): bundled into the Windows EXE; install separately only on native Linux/macOS.

The stack does **not** install Docker containers — only hooks and config.

### WSL audio

WSL invokes the Windows GUI-subsystem EXE, whose WinRT MediaPlayer uses the same Windows audio device as Hermes. No FFmpeg player or shell host is started.

### Verification

1. `ts-config tts on && chezmoi apply -v`
2. `ts-config tts test` — generic phrase
3. `/test-voice` in Claude Code or Cursor
4. `/test-voice-question` in Cursor — question template
5. Trigger AskQuestion in Cursor plan mode — hear **Cursor. I have a question for you.**
6. Claude permission or AskUserQuestion — hear **Claude.** + template

**Cursor:** confirm `~/.cursor/hooks.json` has `afterAgentResponse`, `stop`, and `postToolUse` entries. `afterAgentResponse` carries the spoken completion text; `stop` is retained for failures. Other tools' entries sit in the same arrays and are expected — look for the one whose command is `terminal-stack-tts.exe`, not for a one-entry array. Restart Cursor after first deploy. Check **Settings → Hooks** if silent.

Skip at bootstrap: `TS_CC_TTS=off`. Enable: `TS_CC_TTS=on`.
