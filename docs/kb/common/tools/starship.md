# starship (prompt)

Cross-shell prompt for both zsh and pwsh. The rendered config is
`~/.config/starship.toml`, but it's baked from `dot_config/starship.toml.tmpl`
in the repo — edit the `.tmpl` and apply; hand-edits to the rendered file are
overwritten. Two-line rainbow layout: OS icon, directory, git branch + status,
`took Ns` (any command over 500 ms), a dotted fill, then `user@host` and a
clock on the right.

## Theme

The `palette` line is baked at apply time from the saved `resolvedTheme` —
Catppuccin Mocha (dark) or VS Code Light Modern (light). Change it with
`ts-config theme <dark|light|follow>`, never by editing the rendered file.

## Agent shells

Both rcs skip `starship init` when `_ts_agent_shell` (zsh) /
`Test-TsAgentShell` (pwsh) detects a non-interactive host: `CURSOR_AGENT=1`,
`TERM=dumb`, or `CI=1`/`true`. Starship errors on dumb terminals and its
escape sequences pollute captured agent output. Interactive WezTerm and Cursor
panel terminals are unaffected. See `doc windows/pwsh` § "Agent vs interactive
terminals".

## Daily commands
| Command | What |
|---|---|
| `starship explain` | explain what the current prompt is showing |
| `starship module git_branch` | render one module (`directory`, `time`, …) |
| `starship timings` | per-module render timing (debug a slow prompt) |
| `starship preset --list` | list built-in presets |
| `starship config` | open the config in `$EDITOR` — mind the `.tmpl` caveat above |
