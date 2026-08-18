# starship (prompt)

Cross-shell prompt; config at `~/.config/starship.toml` (stack-managed, whole-file).

**Agent/capture shells** (`TERM=dumb`, `CURSOR_AGENT=1`, `CI=1`): Starship is not
initialized — it errors on dumb terminals and adds stderr noise to agent output.
Interactive WezTerm and Cursor panel terminals are unaffected. See `doc windows/pwsh`
§ "Agent vs interactive terminals".

| Command | What |
|---|---|
| `starship explain` | explain what the current prompt is showing |
| `starship config` | open the config in `$EDITOR` |
| `starship module <name>` | render one module (e.g. `git_branch`, `directory`) |
| `starship preset <name>` | print a built-in preset |
| `starship preset --list` | list available presets |
| `starship timings` | per-module render timing (debug a slow prompt) |

An apply overwrites `starship.toml`; keep machine-specific tweaks out of it.
