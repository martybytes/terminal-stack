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
footer. The terminal-stack profile disables that native metadata row so the
same facts do not appear twice:

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

## agentmemory

Wired by `bootstrap\ts-agentmemory.ps1` from every sync when
`ts-config agents agentmemory on` is saved for this computer.
Codex is the awkward host, for two reasons:

- **It retrieves on the prompt, not the tool call.** Codex emits `Bash` for most tool calls, and a
  shell command is not a safe source of file paths — guessing what `rg foo src/` will read means
  inspecting arbitrary command text. So shell tools are excluded from the path-based lookup and
  Codex asks once per prompt instead, which needs no paths at all.
- **Two hook registrations are live** — `~/.codex/hooks.json` (Desktop) and the plugin's
  `hooks.codex.json` (CLI) — so one event fires both. Codex offers no way to disable just one, so
  the duplicate is dropped inside the hook before any request. Without it, Codex received the same
  context block twice per prompt.

## Headroom and Caveman

With `ts-config agents headroom on`, enhanced interactive launches get a
session-local custom provider named `headroom`. The wrapper passes its base URL,
maps `HEADROOM_PROXY_TOKEN` to `X-Headroom-Proxy-Token`, and selects that provider
only for the child process; it never overrides Codex's reserved built-in `openai`
provider or writes provider state to `~/.codex/config.toml`. An unavailable or
unauthorized proxy fails open to the direct provider. `codex-stock` always
bypasses Headroom.

Recovery is explicit and reversible:

```text
ts-config agents headroom off     # direct mode; remove Headroom MCP registrations
ts-config agents headroom on      # authenticate first, then enable and register
ts-config agents headroom repair  # re-check and repair registrations
```

`on` and `repair` must receive a successful authenticated `/stats` response.
Public `/readyz` and `/health` responses are insufficient because Headroom keeps
them available even when data-plane authentication would reject every request.
The optional MCP sidecar on 8788 is reported separately and does not decide
whether model routing is usable. Reconciliation registers it only while it is
reachable; otherwise it removes stale client registrations so Codex does not
print an MCP startup failure on every launch. The authenticated 8787 model proxy
continues to work independently.

Caveman installs only the pinned global `caveman` skill and a marked block in the
active global `~/.codex/AGENTS.md`. The rest of Caveman's skill collection is not
installed, and existing global instructions are preserved with a dated backup.
Confirm both layers with `ts-config agents headroom status` and
`ts-config agents caveman status`. Only enhanced interactive Codex launches are
wrapped automatically; utility commands such as `codex exec` remain stock. In
Headroom's dashboard, routed Codex traffic is identified as OpenAI/Codex
WebSocket traffic, while a separate Claude smoke test is labeled
Claude/Anthropic.

## Voice notification

The profile's asynchronous Stop hook sends a `codex` event through the same
Kokoro/Chatterbox/edge and optional `ttsd` pipeline as Claude and Cursor. Existing
global Codex `notify` configuration is not replaced. With TTS enabled, test the
source explicitly:

```text
ts-config tts test --source codex
```

`ts-config tts summarizer self` installs the spoken-summary marker in Codex's
active global `$CODEX_HOME/AGENTS.md` (or `AGENTS.override.md`). Start a new
Codex session to load that instruction. Existing sessions still get a locally
derived sentence from their final-response hook text instead of repeating the
fixed waiting template.

Use `ts-config tts prefix codex on|off|<label>` to control the spoken `Codex.`
prefix. If the tray daemon predates this feature, run
`ts-config tts daemon restart` after updating.

The dashboard stays quiet when audio is healthy or TTS is disabled. It shows a
red speaker warning only when enabled Codex speech is misconfigured or its
configured daemon is unreachable.

## Native footer

The fullest native adaptive row remains configured in `~/.codex/config.toml` and
is what `codex-stock` uses. Enhanced interactive launches layer
`tui.status_line = []` over it because the lower dashboard supersedes it:

```toml
[tui]
status_line = ["model-with-reasoning", "project-name", "git-branch", "branch-changes", "pull-request-number", "context-used", "five-hour-limit", "weekly-limit", "used-tokens", "permissions", "fast-mode", "codex-version"]
status_line_use_colors = true
```

Run `/statusline` inside Codex to change that native row.
