# Cursor (AI editor)

VS Code fork with a built-in coding agent; the `cursor` CLI takes the same
flags as `code`. The stack wires around Cursor but does not install it — get it
yourself and enable its shell command.

## How this stack wires it

- `c [path]` in both shells = `cursor <path> --classic` (classic UI), defaulting
  to `.`; extra args pass through. Like `npp`, but for Cursor.
- Ctrl-click a `path/file.ext:123` in WezTerm and it opens in Cursor at that
  exact line via `cursor --goto` — see `doc wezterm/panes` § "Scrollback, quick
  select & links".
- Cursor agent shells set `CURSOR_AGENT=1` / `TERM=dumb`; both rcs detect that
  and skip Starship and OSC title chrome so captured output stays clean — see
  `doc windows/pwsh` § "Agent vs interactive terminals".
- The Windows sync merges stack-owned terminal keys into
  `%APPDATA%\Cursor\User\settings.json` via `bootstrap/_merge_cursor_settings.ps1`
  — a textual splice, one key at a time, backup first, so your own comments and
  formatting survive.
- Cursor Agent TTS hooks (`~/.cursor/hooks`, synced by the stack) can announce
  stop/error/question events — see `doc common/claude-code` § "Local TTS".
- `~/.cursor/hooks.json` is **part-owned**: the sync splices in only the stack's own
  hook entries (`bootstrap/_merge_cursor_hooks.ps1`) and leaves anyone else's alone,
  so tools that register their own hooks — agentmemory shares the `stop` and
  `postToolUse` arrays with ours — survive an apply. Add your own hooks straight to
  the file; the stack will not remove them. Never let anything copy that file whole.

| Command | What it does |
|---|---|
| `c` / `c path` | open cwd / path in Cursor, classic UI |
| `cursor .` | open the current directory |
| `cursor --goto file:42` | open a file at line 42 |
| `cursor --diff a b` | diff two files in the editor |
| `cursor -n .` | force a new window |
| `cursor -r file` | reuse the current window |
| `cursor --add dir` | add a folder to the open workspace |
