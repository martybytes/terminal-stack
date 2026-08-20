# Codex CLI helpers

The stack supplies the same shortcut in zsh and PowerShell:

| Shortcut | Full command | What it does |
|---|---|---|
| `cyr` | `codex --yolo resume` | Open Codex's saved-session picker with approvals and sandboxing bypassed |

Arguments pass through, so `cyr --last` resumes the most recent session and
`cyr <session-id>` resumes a specific one. `--yolo` gives Codex unrestricted
local access; use plain `codex resume` when you want approval and sandbox guards.

## Footer status line

Codex's native footer is one adaptive row. It cannot run a custom multi-line
status command like the Claude Code footer, but current Codex versions expose
most of the useful fields through `tui.status_line` in `~/.codex/config.toml`:

```toml
[tui]
status_line = ["model-with-reasoning", "project-name", "git-branch", "branch-changes", "pull-request-number", "context-used", "five-hour-limit", "weekly-limit", "used-tokens", "permissions", "fast-mode", "codex-version"]
status_line_use_colors = true
```

The order is the priority order. Codex drops fields whose data is unavailable
and truncates the row to the terminal width. The configured fields cover:

- model + reasoning level, project, Git branch, pull request, and committed
  branch changes against the default branch;
- context consumption, 5-hour and weekly allowance, and session token usage;
- active permission/sandbox profile, Fast mode, and the Codex version.

`branch-changes` is the closest native equivalent to Claude's patch summary; it
is branch-relative, not an exact per-turn `+N/-M lines` counter. Codex also does
not currently expose Claude-style session cost in the footer.

Run `/statusline` inside Codex to toggle fields, change their order, or turn
theme colors on and off without editing TOML by hand. Footer changes apply to
new Codex sessions.
