# Windows — PowerShell extras

Most shortcuts are shared — see `doc common/git`, `doc common/claude-code`,
`doc common/workspace-nav`, `doc common/files-disk`, `doc common/search-history`.
Windows-specific bits:

| Command | What it does |
|---|---|
| `npp file` | open file(s) in Notepad++ (GUI; `npp` alone opens it empty) |
| `glow file.md` | render markdown (`glow .` for a browser) |
| `zoxide-prune` | drop dead paths from zoxide's database |
| `ll` / `la` / `lt` | eza long / hidden+long / tree |
| `Ctrl+R` | PSReadLine reverse history search (native — the profile wires no fzf keys; see `doc common/tools/fzf`) |
| `Ctrl+V` | paste (rebound so synthetic paste — Wispr Flow etc. — reaches Claude Code) |

## Agent vs interactive terminals

Cursor Agent, Claude Code hooks, and other **capture shells** run with
`TERM=dumb` and often `CURSOR_AGENT=1`. They are not your WezTerm session — they
exist so the IDE can parse plain command output.

The stack detects those shells (`Test-TsAgentShell` in pwsh; `_ts_agent_shell` in
zsh) and **skips prompt chrome** there:

- Starship init + transient prompt
- OSC 7 / OSC 0 title sequences (pwsh `Invoke-Starship-PreCommand`; zsh precmd hooks)

Everything else still loads: UTF-8 codepage, zoxide, git shortcuts, `ws`/`doc`, etc.

| Shell | Signals | Starship |
|---|---|---|
| WezTerm pwsh / zsh tab | normal `TERM` | on |
| Cursor bottom terminal | normal `TERM` | on |
| Cursor Agent command runner | `TERM=dumb`, `CURSOR_AGENT=1` | off |
| CI / automation | `CI=1` | off |

**Escape hatch:** `plain` — nested `pwsh -NoLogo -NoProfile` (no profile at all);
`exit` returns to the customized shell. WezTerm launch menu has a matching entry.

**Cursor IDE automation** (VS Code tasks, not agent shells): `ts-update` / sync
merges `terminal.integrated.automationProfile.windows` from
`windows/AppData/Roaming/Cursor/User/terminal-stack.terminal.json` into
`%APPDATA%\Cursor\User\settings.json` — a bare `pwsh -NoProfile` with Git on PATH.
See `doc wezterm/dev-config` for the sync table.

After profile changes, start a **new** Cursor agent chat (existing agent shells keep
the old profile until restarted).

## Recommended WezTerm model (one OS window)
Use WezTerm **workspaces** (`Ctrl+Space w` picker, `Ctrl+Space n` to create) as the
unit of "what I'm working on". Inside a workspace use **panes** (`F1`–`F4` /
`Ctrl+Space 1`–`4` focus-or-split by direction, `F5`/`F6` jump/swap via PaneSelect,
`Ctrl+Space h`/`v` to split, leader+arrows for move/resize modes, `z` zoom) for
things you watch simultaneously. Need a remote shell
beside your work? `Ctrl+Space H`/`V` opens a domain picker (SSH/WSL) and splits it in.
Tabs are cheap full-screen flips within a workspace — `Alt+1`…`9` to jump. This
replaces needing multiple top-level WezTerm windows. Full keys: `doc wezterm/panes`,
`doc wezterm/tabs`, `doc wezterm/workspace`.

## Developing WezTerm config

WezTerm loads from `%USERPROFILE%`, not the clone. After editing `windows/.wezterm.lua.tmpl`
or `windows/.wezterm/pane_nav.lua`, run `scripts\sync-windows.ps1 -SourceDir <clone>`,
then **`Ctrl+Space` `r`** for `pane_nav.lua` changes. Full loop: `doc wezterm/dev-config`.
