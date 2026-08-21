# Codex CLI dashboard and helpers

The stack enhances every interactive Codex launch in zsh and PowerShell:

| Shortcut | Full command | What it does |
|---|---|---|
| `codex` | `codex` | Start a guarded interactive session with the dashboard |
| `codex resume` | `codex resume` | Open the guarded saved-session picker with the dashboard |
| `codex fork` | `codex fork` | Fork a session with the dashboard |
| `cy` | `codex --yolo` | Start a new unrestricted Codex session |
| `cyr` | `codex --yolo resume` | Open the unrestricted saved-session picker |
| `codex-stock` | external `codex` | Bypass terminal-stack completely |

Arguments pass through: `cyr --last` resumes the newest session and
`cyr <session-id>` resumes a specific one. Both commands bypass approvals and
sandboxing; ordinary `codex` / `codex resume` keep those guards. Noninteractive
and administrative commands such as `codex exec`, `codex review`, `codex mcp`,
`codex login`, completions, help, and version output remain stock automatically.

## Three-line dashboard

Inside WezTerm, an interactive launch creates a three-row bottom split for the
lifetime of Codex. It is deliberately separate from Codex's native one-row
footer:

| Line | Segments |
|---|---|
| 1 — location | smart repo-relative path \| `owner/repo` \| branch → upstream \| linked-worktree badge |
| 2 — changes | staged/modified/deleted/untracked/conflict counts \| ahead/behind \| stashes \| exact Codex patch `+N/-M` \| last-commit age \| PR review, CI, and merge health |
| 3 — Codex | state + current action + turn/session timers \| model/effort \| context \| 5-hour + weekly limits \| token breakdown \| permissions \| version \| relevant account, tool-failure, and TTS warnings |

Bars are green below 70%, yellow at 70–89%, and red at 90%+. Segments drop from
low-priority fields after abbreviating on narrow panes; each row stays on one
physical line. `THINK`, `TOOL`, `WAIT`, `DONE`, and `ERROR` make current activity
visible. A live turn turns yellow after two minutes and orange after five—it
never becomes an error just because it is long. Patch totals count successful
Codex file changes in the exact rollout rather than comparing the whole branch.

The screen redraws every 750 ms. Local Git refreshes every two seconds, TTS
health every 30 seconds, and GitHub PR state every 45 seconds through `gh`; PR
details disappear quietly when `gh` is missing, offline, or not authenticated.
The sidecar is killed when Codex exits. Outside WezTerm, the named hook/TTS
profile still loads but the split is skipped.

The profile lives at `~/.codex/terminal-stack.config.toml`; its helper is
`~/.codex/hooks/terminal_stack.py`. Codex requires explicit trust for local
hooks: launch an interactive session, run `/hooks`, review the two terminal-stack commands, and
trust them once. Until then, the dashboard uses recent-rollout discovery, but
the exact pane mapping and Stop TTS wait for hook trust.

## Voice notification

The profile's asynchronous Stop hook sends a `codex` event through the same
Kokoro/Chatterbox/edge and optional `ttsd` pipeline as Claude and Cursor. Existing
global Codex `notify` configuration is not replaced. With TTS enabled, test the
source explicitly:

```text
ts-config tts test --source codex
```

Use `ts-config tts prefix codex on|off|<label>` to control the spoken `Codex.`
prefix. If the tray daemon predates this feature, run
`ts-config tts daemon restart` after updating.

The dashboard stays quiet when audio is healthy or TTS is disabled. It shows a
red speaker warning only when enabled Codex speech is misconfigured or its
configured daemon is unreachable.

## Native footer

The fullest native adaptive row remains configured in `~/.codex/config.toml` and
is also what `codex-stock` uses:

```toml
[tui]
status_line = ["model-with-reasoning", "project-name", "git-branch", "branch-changes", "pull-request-number", "context-used", "five-hour-limit", "weekly-limit", "used-tokens", "permissions", "fast-mode", "codex-version"]
status_line_use_colors = true
```

Run `/statusline` inside Codex to change that native row.
