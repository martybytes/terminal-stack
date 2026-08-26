# tstack — the stack's one command

`tstack` is the single entry point for the whole stack. There are no `ts-*`
commands any more, and no aliases for them.

| Command | What it does |
|---|---|
| `tstack config` | view and change saved settings (the table below) |
| `tstack doctor` | diagnose the install; `--repair` fixes what it can |
| `tstack update` | pull the latest stack and re-apply |
| `tstack rollback` | undo the last update |
| `tstack services` | the Docker service stacks - see `doc services` |
| `tstack mux` | the WezTerm multiplexer domain |
| `tstack wezterm` | WezTerm channel and updates (POSIX only) |
| `tstack smb` | SMB shares over rclone (POSIX only) - see `doc smb-shares` |
| `tstack agents` | agent CLI wiring - see `doc agentmemory`, `doc headroom` |
| `tstack agentmemory` | the agentmemory hook harness; `--check` reports reverted edits |
| `tstack doc` | this knowledge base (the bare `doc` command is the same thing) |
| `tstack --help` | every subcommand, with platform gaps marked |
| `tstack --version` | clone path, branch, commit, and whether it is dirty |

A subcommand reported as "not available on <platform>" is deliberate, not a
broken install: `smb` and `wezterm` have no PowerShell implementation.

## Configuration

Everything the install wizard asks, changeable afterwards. Every change persists
(chezmoi `[data]` on WSL/Linux/macOS, `config.json` on Windows) and re-applies.

Run it bare for an interactive menu; `tstack config show` just prints the state.

| Command | What it does |
|---|---|
| `tstack config` | interactive menu |
| `tstack config show` | the saved config + the derived bindings |
| `tstack config leader <chord>` | WezTerm leader, e.g. `ctrl-space`, `ctrl-a`, `alt-x` |
| `tstack config theme <dark\|light\|follow>` | palette; `follow` tracks the OS theme |
| `tstack config tmux <chord>` | tmux prefix — see `doc common/tmux` |
| `tstack config apps [recommended\|all\|none\|id,…]` | app catalog; no arg → picker. Installs, never uninstalls |
| `tstack config atuin <on\|off>` | atuin owns `Ctrl+R` — see `doc common/tools/atuin` |
| `tstack config ghostty [on\|off\|status\|diff]` | managed Ghostty config, macOS — see `doc common/tools/ghostty` |
| `tstack config tts …` | agent voice — see `doc common/tts` |
| `tstack config mux [on\|off\|…]` | hand-off to `tstack mux` (WezTerm multiplexer domain) |
| `tstack config restore <on\|off>` | reopen the last WezTerm session at startup (default off) |
| `tstack config wezterm` | your build + date, newest per channel, count of what changed since |
| `tstack config wezterm changes` | the full upstream changelog since your build, paged |
| `tstack config wezterm install <stable\|nightly>` | switch channel — removes the other package first |
| `tstack config wezterm upgrade` | refresh the channel you are on; never switches |
| `tstack config memory [status]` | which memory backend runs, and whether the derived state agrees |
| `tstack config memory <agentmemory\|headroom\|none>` | switch it; restarts headroom so the setting and the running state cannot disagree |
| `tstack config agents [show]` | saved Headroom / Caveman / AgentMemory state |
| `tstack config agents <tool> on\|off\|status\|repair\|uninstall` | one tool, user scope; never edits a project or Docker |
| `tstack config agents headroom cursor <mcp\|byok\|off>` | Cursor-only mode; `mcp` keeps subscription traffic direct |
| `tstack config wizard` | re-run **every** install question and persist the lot |

## `tstack config wizard`

The "start over as if installing" path — it re-asks leader, theme, terminal
emulator, apps, mux, session restore, atuin, voice and the agent tools, then
saves them all. `tstack config apps` re-asks only the apps question.

`TS_ASSUME_YES=1 tstack config wizard` takes every default without prompting, and
the per-question `TS_*` env vars still skip individual prompts
(`TS_LEADER`, `TS_THEME`, `TS_ATUIN`, `TS_TERMINALS`, `TS_CC_TTS`, …).

Answers are saved **before** anything is installed, so a package that fails to
install can no longer cost you the answers you just gave. Anything optional that
fails is collected and reported at the end instead of aborting the run.

Questions that can be got wrong open with a `RECOMMENDATION:` line saying which
way to go *and what it costs*. The agent toggles go further and **probe** first —
Headroom and AgentMemory are contacted before being offered, and the default
follows what answered, because wiring an agent to a service that is not running
fails later and silently.

Headroom's `on` and `repair` actions require an authenticated `/stats` response,
not merely the intentionally public health endpoints. If validation fails, saved
state remains off and Claude/Codex launch directly. `off` is the emergency revert:
it saves off and removes Headroom MCP registrations without changing service data.
MCP uses Docker stdio, not an HTTP sidecar: repair/status also require a real
JSON-RPC initialize handshake before registering the command.

## Combined WSL + Windows

Run it from **WSL**. Its apply is the authoritative one: a pwsh save writes only
the `config.json` mirror, so the two stores silently diverge and the next
`chezmoi apply` from WSL renders the setting back. See `doc common/stack`.

See also `doc common/stack` (update/rollback/doctor), `doc common/tts`.
