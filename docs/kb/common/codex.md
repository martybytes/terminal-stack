# Codex CLI helpers

The stack supplies two enhanced yolo wrappers in zsh and PowerShell:

| Shortcut | Full command | What it does |
|---|---|---|
| `cy` | `codex --yolo` | Start a new unrestricted Codex session |
| `cyr` | `codex --yolo resume` | Open the unrestricted saved-session picker |

Arguments pass through: `cyr --last` resumes the newest session and
`cyr <session-id>` resumes a specific one. Both commands bypass approvals and
sandboxing; use ordinary `codex` / `codex resume` when you want those guards.

## Three-line dashboard

Inside WezTerm, `cy` and `cyr` create a three-row bottom split for the lifetime
of Codex. It is deliberately separate from Codex's native one-row footer:

| Line | Segments |
|---|---|
| 1 | cwd \| branch, dirty count, ahead/behind \| `owner/repo` |
| 2 | model/effort \| context 10-cell bar \| 5-hour and weekly usage bars + resets |
| 3 | `user@host` \| session tokens \| session patch `+N/-M` \| permissions/yolo \| Codex version |

Bars are green below 70%, yellow at 70–89%, and red at 90%+. Segments drop from
the right on narrow panes. Patch totals count successful Codex file changes in
the exact rollout, rather than comparing the whole branch. The sidecar is killed
when Codex exits. Outside WezTerm the wrappers still load the hook/TTS profile,
but skip the split. Plain `codex` is untouched and keeps the native footer.

The profile lives at `~/.codex/terminal-stack.config.toml`; its helper is
`~/.codex/hooks/terminal_stack.py`. Codex requires explicit trust for local
hooks: launch `cy`, run `/hooks`, review the two terminal-stack commands, and
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

## Native footer

Normal `codex` sessions can still use the fullest native adaptive row in
`~/.codex/config.toml`:

```toml
[tui]
status_line = ["model-with-reasoning", "project-name", "git-branch", "branch-changes", "pull-request-number", "context-used", "five-hour-limit", "weekly-limit", "used-tokens", "permissions", "fast-mode", "codex-version"]
status_line_use_colors = true
```

Run `/statusline` inside Codex to change that native row.
