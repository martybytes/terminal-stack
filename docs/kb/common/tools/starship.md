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
`tstack config theme <dark|light|follow>`, never by editing the rendered file.

## Compact past prompts (transient) and the blank line

Once you press Enter, the finished line is redrawn with a short prompt, so
scrollback copies cleanly and only the live prompt is the full two lines:

```
❯ cd C
❯ ls
 ts-agentmemory-data.tgz
╭─    terminal-stack/C   main ........................ marty@Nova  2:55:20 PM ─╮
╰─❯
```

On by default, in the `bare` style, with no blank line between commands. All
three are saved settings and hold for every prompt, presets included:

| Command | What |
|---|---|
| `tstack config prompt transient` | show the setting and what each style looks like |
| `tstack config prompt transient on\|off` | collapse finished prompts, or keep them full |
| `tstack config prompt transient bare` | `❯ ls` — just the arrow (default) |
| `tstack config prompt transient dir` | `terminal-stack ❯ ls` — the folder it ran in |
| `tstack config prompt transient time` | `3:24:06 PM ❯ ls` — when it ran |
| `tstack config prompt transient dir-time` | `terminal-stack 3:24:06 PM ❯ ls` |
| `tstack config prompt newline on\|off` | blank line before each prompt (default off) |

A style also turns transient on. Changes show in a **new** shell or tab
(`exec zsh` in the current one). For one shell only, export
`TS_PROMPT_TRANSIENT=off` or `TS_PROMPT_TRANSIENT_STYLE=dir` before it starts.
The `tstack config` menu has the same choices under `p) prompt`.

How it works: zsh has no Starship transience, so `dot_zshrc` installs a
`zle-line-init` widget (chained onto oh-my-zsh's) that redraws the line on Enter
and on Ctrl+C. PowerShell uses Starship's own `Enable-TransientPrompt` with an
`Invoke-Starship-TransientFunction`; there a line abandoned with **Ctrl+C** keeps
its full prompt, because Starship only hooks Enter. The blank line is Starship's
`add_newline`, written into `starship.toml` on both sides.

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
