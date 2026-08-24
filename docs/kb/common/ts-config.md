# ts-config — change any saved setting

Everything the install wizard asks, changeable afterwards. Every change persists
(chezmoi `[data]` on WSL/Linux/macOS, `config.json` on Windows) and re-applies.

Run it bare for an interactive menu; `ts-config show` just prints the state.

| Command | What it does |
|---|---|
| `ts-config` | interactive menu |
| `ts-config show` | the saved config + the derived bindings |
| `ts-config leader <chord>` | WezTerm leader, e.g. `ctrl-space`, `ctrl-a`, `alt-x` |
| `ts-config theme <dark\|light\|follow>` | palette; `follow` tracks the OS theme |
| `ts-config tmux <chord>` | tmux prefix — see `doc common/tmux` |
| `ts-config apps [recommended\|all\|none\|id,…]` | app catalog; no arg → picker. Installs, never uninstalls |
| `ts-config atuin <on\|off>` | atuin owns `Ctrl+R` — see `doc common/tools/atuin` |
| `ts-config ghostty [on\|off\|status\|diff]` | managed Ghostty config, macOS — see `doc common/tools/ghostty` |
| `ts-config tts …` | agent voice — see `doc common/tts` |
| `ts-config mux [on\|off\|…]` | hand-off to `ts-mux` (WezTerm multiplexer domain) |
| `ts-config restore <on\|off>` | reopen the last WezTerm session at startup (default off) |
| `ts-config wezterm` | your build + date, newest per channel, count of what changed since |
| `ts-config wezterm changes` | the full upstream changelog since your build, paged |
| `ts-config wezterm install <stable\|nightly>` | switch channel — removes the other package first |
| `ts-config wezterm upgrade` | refresh the channel you are on; never switches |
| `ts-config agents [show]` | saved Headroom / Caveman / AgentMemory state |
| `ts-config agents <tool> on\|off\|status\|repair\|uninstall` | one tool, user scope; never edits a project or Docker |
| `ts-config agents headroom cursor <mcp\|byok\|off>` | Cursor-only mode; `mcp` keeps subscription traffic direct |
| `ts-config wizard` | re-run **every** install question and persist the lot |

## `ts-config wizard`

The "start over as if installing" path — it re-asks leader, theme, terminal
emulator, apps, mux, session restore, atuin, voice and the agent tools, then
saves them all. `ts-config apps` re-asks only the apps question.

`TS_ASSUME_YES=1 ts-config wizard` takes every default without prompting, and
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
not merely the intentionally public health endpoints. If validation fails, the
saved state remains off and Claude/Codex launch directly. `off` is the emergency
revert: it saves off and removes Headroom MCP registrations without changing the
Docker service or its data. The separate MCP sidecar may be unavailable while
the model proxy is fully usable.

## Combined WSL + Windows

Run it from **WSL**. Its apply is the authoritative one: a pwsh save writes only
the `config.json` mirror, so the two stores silently diverge and the next
`chezmoi apply` from WSL renders the setting back. See `doc common/stack`.

See also `doc common/stack` (update/rollback/doctor), `doc common/tts`.
