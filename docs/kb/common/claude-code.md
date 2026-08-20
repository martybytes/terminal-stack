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
| `ts-config tts …` | Full control (prefix, project, excitement, templates, events) |
| `/test-voice` | Slash command in Claude Code or Cursor (user home) |

### Config layout

| Path | Managed? | Purpose |
|---|---|---|
| `~/.claude/tts/config.json` | yes (chezmoi) | Engine, voices, templates, prefixes, events |
| `~/.claude/tts/local.json` | **no** | Per-machine overrides (copy from `local.json.example`) |
| Legacy `~/.claude/tts.json` | migrated once | Auto-copied to `tts/config.json` on first hook run |

`ts-config tts show` prints chezmoi `[data]`; after apply, hooks read **merged** `config.json` + `local.json`.

Key knobs: `sources.claude|cursor.prefix`, `announce.includeProject`, `announce.templates.{waiting,error,question,permission}`, `excitement` (0–1, drives Kokoro speed / Chatterbox energy).

### Hook wiring

| App | Event | When it speaks |
|---|---|---|
| Claude Code | `Stop` / `StopFailure` | Agent finished / failed |
| Claude Code | `Notification` / `PermissionRequest` / `PreToolUse` (`AskUserQuestion`) | Needs attention / permission / clarifying question |
| Cursor Agent | `stop` | Agent loop ended |
| Cursor Agent | `postToolUse` (`AskQuestion`) | Plan-mode / clarifying question UI |

All paths call **`cc-tts-notify`** → Kokoro → **`cc-tts-play`** (WSL uses Windows `ffplay`). Prefixes **`Claude.`** / **`Cursor.`** are configurable per source.

### Prerequisites

- **Kokoro** (primary): `http://127.0.0.1:8880` — e.g. `remsky/kokoro-fastapi-gpu` in Docker.
- **Chatterbox** (optional): `http://127.0.0.1:8881`.
- **edge-tts** (fallback): `pip install edge-tts`.

The stack does **not** install Docker containers — only hooks and config.

### WSL audio

Playback routes through **Windows** (`ffplay`) so you hear the same headphones as Hermes.

### Verification

1. `ts-config tts on && chezmoi apply -v`
2. `ts-config tts test` — generic phrase
3. `/test-voice` in Claude Code or Cursor
4. `/test-voice-question` in Cursor — question template
5. Trigger AskQuestion in Cursor plan mode — hear **Cursor. I have a question for you.**
6. Claude permission or AskUserQuestion — hear **Claude.** + template

**Cursor:** confirm `~/.cursor/hooks.json` has `stop` and `postToolUse` entries. Restart Cursor after first deploy. Check **Settings → Hooks** if silent.

Skip at bootstrap: `TS_CC_TTS=off`. Enable: `TS_CC_TTS=on`.
