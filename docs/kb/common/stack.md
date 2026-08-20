# Stack management

| Command | What it does |
|---|---|
| `doc` / `ref` | this knowledge base (`doc -h` for subcommands) |
| `wzr [topic]` | WezTerm key reference (`doc wezterm/...`) |
| `ts-update` | pull the latest stack and re-apply — see below |
| `ts-rollback` | undo the last `ts-update` — see below |
| `ts-doctor [--repair]` | health-check / fix the install — see below |
| `ts-config` | change leader, theme, tmux prefix, apps, TTS — see below |
| `ts-mux` | WezTerm multiplexer domain: on/off, status, kill/restart/reset — see below |
| `plain` | vanilla shell, no rc/profile (no oh-my-zsh/starship/aliases) — `exit` to return |
| `chezmoi diff` / `chezmoi apply -v` | preview / apply configs (run from inside WSL on Windows) |
| `chezmoi re-add ~/.zshrc` | capture a hand-edit of a managed file back into the repo |
| `scripts\sync-windows.ps1 -SourceDir <clone>` | Windows-side deploy — see `doc wezterm/dev-config` |

pwsh function names: `Update-TerminalStack`, `Restore-TerminalStack`,
`Set-TerminalStackConfig`, `Invoke-TsDoctor`, `Invoke-TsMux` — all aliased to the
same `ts-*` names.

## Clone locations

| Path | Role |
|---|---|
| `%LOCALAPPDATA%\terminal-stack\stack` (WSL: `/mnt/c/Users/<you>/AppData/Local/terminal-stack/stack`) | canonical runtime clone — Windows + WSL share this **one** clone |
| `~/.local/share/terminal-stack` | canonical runtime clone — native Linux/macOS |
| `<workspace>/<tier>/github.com/<owner>/terminal-stack` | dev clone — **invisible** to resolution/doctor/`doc` unless pinned |

The canonical path resolves without a pin — set `TERMINAL_STACK_DIR`
(`$env:TERMINAL_STACK_DIR`) only for a **non-canonical** location, e.g. a dev clone
you deliberately work against; that pin is how `ts-update` can update it, since dev
clones are otherwise skipped. At a legacy path `ts-update` prints a one-line notice
and `ts-doctor --repair` offers to move the clone to the canonical location (git
state intact).

**A pin that points at nothing does not break anything.** If the clone moved or was
deleted, the resolvers warn once and fall through to the usual candidate search
rather than failing — a stale line in `profile.local.ps1` would otherwise take
`ts-update`, `wso` and `doc` down together. An explicit `sync-windows.ps1 -SourceDir`
still fails loudly: that one is typed per call, so a bad value is a mistake worth
stopping for. `install.ps1` goes further and ignores a *persisted* pin with no clone
behind it, removing the dead line once the clone lands at the canonical path.

**The runtime clone never goes inside a workspace root.** The installers warn and
offer the canonical path instead, and `wso` refuses to migrate any un-tiered
terminal-stack clone it finds there — see `doc common/workspace-org`. `%LOCALAPPDATA%\terminal-stack` also holds `config.json`,
`rollback-sha`, and the `docs\kb` mirror alongside `stack\`. Rationale:
`docs/decisions.md` § "Runtime clone location".

## `ts-update`
Resolves the **runtime** clone — the pin (`$TERMINAL_STACK_DIR`) first, else the
canonical location, else legacy defaults; a pin with no clone behind it is warned
about and skipped rather than obeyed. Dev clones at workspace tier paths are
never picked up unless pinned, so `ts-update` can't mutate the tree you develop
in. Then: prints a one-line notice if the clone sits at a legacy path (`ts-doctor
--repair` moves it); warns about any **other** clones on
the machine — only the resolved one is updated, and a forgotten old clone would
silently re-deploy an old profile (pwsh offers to pin the choice); fetches and lists
the incoming commits; records the pre-pull HEAD as the rollback point; pulls
`--ff-only`; re-bakes the resolved theme (matters in `follow` mode); re-applies
(`chezmoi apply` / `sync-windows.ps1`); and finally offers to install any catalog
apps missing from this machine — never behind your back. The rollback SHA is written
only when commits are actually incoming, so a no-op re-run can't clobber the last
real rollback point. State file: `~/.local/state/terminal-stack/rollback-sha`
(WSL/Linux), `%LOCALAPPDATA%\terminal-stack\rollback-sha` (Windows).

## `ts-rollback`
Resets the clone to the recorded SHA and re-applies. It **refuses on a dirty
clone** — the clone may double as a dev checkout, so commit or stash first. "No
recorded rollback point" means no `ts-update` has pulled commits since the state
file was written; recover manually with `git -C <clone> reset --hard <sha>` then
`chezmoi apply` (Windows: `scripts\sync-windows.ps1`). One level deep: the next
`ts-update` that pulls overwrites the recorded point.

## `ts-doctor`
Read-only health check; exits 0 when healthy. Checks that chezmoi exists, that its
sourceDir is a real terminal-stack clone (a git repo whose `origin` names the
project — a folder name is not proof), that `~/.zshrc` carries the stack block and
the `doc` command, and that `zsh`/`starship` are on PATH. Leftover clones are noted
but don't fail the check. `--quiet` hides the per-check ok lines.

`ts-doctor --repair` fixes what it finds, confirming each step: offers to **move**
a legacy-path clone to the canonical location (git state intact) — or, when that
location is **already occupied**, switches to the clone living there and offers the
other one for removal, since the move itself refuses an existing destination and the
cleanup checklist never lists the canonical path. It also repoints chezmoi's
sourceDir at the real clone, fixes stale pins, can normalize an old-account origin
URL, re-applies, then offers an interactive checklist to
remove old clones and leftover files (per-machine files — `profile.local.ps1`,
`~/.doc.local`, rollback state — are never listed). On Windows the same pair is
`Test-TerminalStack` / `Repair-TerminalStack`: checks the clone,
`%LOCALAPPDATA%\terminal-stack\config.json`, and the `$PROFILE` marker block;
repair offers the same canonical move and re-syncs (a pin is written to
`profile.local.ps1` only when the clone stays at a non-canonical path).

## `ts-config`
| Command | What it does |
|---|---|
| `ts-config` | interactive menu (leader / theme / tmux / apps / re-apply / TTS) |
| — | WezTerm itself is an **install-time** choice, not a `ts-config` entry; change it with `winget install wez.wezterm` / `brew install --cask wezterm@nightly` |
| `ts-config show` | print the saved config + the derived bindings |
| `ts-config leader <chord>` | WezTerm leader, e.g. `ctrl-space`, `ctrl-a`, `alt-x` |
| `ts-config theme <dark\|light\|follow>` | palette; `follow` tracks the OS theme |
| `ts-config tmux <chord>` | tmux prefix, e.g. `ctrl-a` — see `doc common/tmux` |
| `ts-config apps [recommended\|all\|none\|id,…]` | app catalog; no arg → picker; installs, never uninstalls |
| `ts-config tts <show\|on\|off\|test\|…>` | Claude/Cursor voice — see `doc common/claude-code` |
| `ts-config mux [on\|off\|…]` | hand-off to `ts-mux` (WezTerm multiplexer domain) |
| `ts-config restore <on\|off>` | reopen the last WezTerm session at startup (default off) |

Every change persists (chezmoi `[data]` on WSL/Linux, `config.json` on Windows) and
re-applies. In a combined WSL+Windows setup run it from **WSL** — its apply is
authoritative for the Windows-side files too.

## `ts-mux`
The WezTerm **multiplexer domain**: with it on, your shells run inside
`wezterm-mux-server` instead of the GUI, so a GUI crash leaves every pane alive and
relaunching WezTerm reattaches. **Off by default** — see the trade-offs below.

| Command | What it does |
|---|---|
| `ts-mux` / `ts-mux status` | the setting, the *rendered* setting, the server pid, the pane count |
| `ts-mux on` / `ts-mux off` | flip it and re-render `.wezterm.lua` |
| `ts-mux list` | `wezterm cli list` — every pane the mux knows about |
| `ts-mux kill` | stop `wezterm-mux-server` — **kills every pane it hosts** |
| `ts-mux restart` | stop it, start a fresh one, so it re-reads the config |
| `ts-mux reset` | back to the default: off + re-apply + kill + clear stale sockets |
| `-y` / `--yes` | skip the confirmation on kill / restart / reset |

Why it is off by default: the mux server loads its **own** copy of `.wezterm.lua`,
so a config change needs `ts-mux restart` (which kills every pane) and not just a
GUI reload; and the Claude per-pane tint rides `pane:inject_output`, which mux panes
don't have (tab dots and title tints still work).

`on`/`off` take effect for newly spawned tabs; relaunch WezTerm for a clean switch.
Panes already hosted by the mux stay there until you close them or `ts-mux kill`.
`status` prints the *rendered* value next to the saved one, so a setting you changed
but never applied — or a `.wezterm.lua` older than the toggle, reported as
`on (pre-toggle)` — shows up as stale instead of silently disagreeing.

The install wizard asks (defaulting to off); `TS_WEZ_MUX=on|off` skips the prompt
for a scripted install. The setting is saved with the rest of the config
(`ts-config show` prints it as `wezmux`; `ts-config mux …` is the same command).
On WSL the mux server is a **Windows** process — `ts-mux` reaches it over interop,
so it works from either side.

## SSH (stack shortcut)
`ssht host [session]` — SSH and attach-or-create a remote tmux session in one shot
(default session `main`); also names the WezTerm tab `ssh-host:session`. **zsh
only** — no pwsh counterpart. See `doc common/ssh-config`, `doc common/tmux`.
