# Stack management

| Command | What it does |
|---|---|
| `doc` / `ref` | this knowledge base (`doc -h` for subcommands) |
| `wzr [topic]` | WezTerm key reference (`doc wezterm/...`) |
| `ts-update` | pull the latest stack and re-apply — see below |
| `ts-rollback` | undo the last `ts-update` — see below |
| `ts-doctor [--repair]` | health-check / fix the install — see below |
| `ts-config` | change leader, theme, tmux prefix, apps, TTS, agent tools, WezTerm mux/restore — see below |
| `ts-config wizard` | re-run the whole install questionnaire from scratch — see below |
| `ts-mux` | WezTerm multiplexer domain: on/off, status, kill/restart/reset — see below |
| `ts-smb` | SMB/CIFS shares over rclone: discover, interrogate, mount — `doc smb-shares` (macOS/Linux) |
| `ts-wezterm` | WezTerm build info, upstream comparison, channel switching — see below |
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
| `ts-config` | interactive menu (leader / theme / tmux / apps / TTS / coding agents / WezTerm mux / restore) |
| `ts-config wezterm` | WezTerm build info and channel — see below |
| `ts-config show` | print the saved config + the derived bindings |
| `ts-config leader <chord>` | WezTerm leader, e.g. `ctrl-space`, `ctrl-a`, `alt-x` |
| `ts-config theme <dark\|light\|follow>` | palette; `follow` tracks the OS theme |
| `ts-config tmux <chord>` | tmux prefix, e.g. `ctrl-a` — see `doc common/tmux` |
| `ts-config apps [recommended\|all\|none\|id,…]` | app catalog; no arg → picker; installs, never uninstalls |
| `ts-config wizard` | re-run **every** install question (leader, theme, terminal emulator, apps, mux, restore, TTS, agent tools) and persist the lot. `ts-config apps` re-asks only the apps question; this is the "start over as if installing" path. `TS_ASSUME_YES=1 ts-config wizard` takes the defaults without prompting, and the per-question `TS_*` env vars still skip individual prompts |
| `ts-config tts <show\|on\|off\|test\|…>` | Claude/Cursor voice — see `doc common/claude-code` |
| `ccmute` | silence the voice instantly, until you unmute. Also the tray icon, `Ctrl+Alt+Shift+M`, `Leader+m` |
| (tray) | the tray's **Open dashboard** gives live activity, the daemon log and a settings editor: see `doc windows/tts-daemon` |
| `ts-config mux [on\|off\|…]` | hand-off to `ts-mux` (WezTerm multiplexer domain) |
| `ts-config restore <on\|off>` | reopen the last WezTerm session at startup (default off) |
| `ts-config wezterm` | your build + date, newest on each channel, and a count of what changed since |
| `ts-config wezterm changes` | the full upstream changelog since your build, paged |
| `ts-config wezterm install <stable\|nightly>` | switch channel — removes the other package first |
| `ts-config wezterm upgrade` | refresh the channel you are on; never switches |
| `ts-config agents [show]` | saved Headroom, Caveman, AgentMemory state for this computer |
| `ts-config agents <tool> on\|off\|status\|repair\|uninstall` | manage one tool at user scope; never edits a project or Docker |
| `ts-config agents headroom dashboard` | open the Headroom GUI monitor |
| `ts-config agents headroom cursor <mcp\|byok\|off>` | Cursor-only mode; `mcp` keeps subscription traffic direct |

Every change persists (chezmoi `[data]` on WSL/Linux, `config.json` on Windows) and
re-applies. In a combined WSL+Windows setup run it from **WSL** — its apply is
authoritative for the Windows-side files too.

Agent-tool pins live in `bootstrap/agent-tools.json`. `ts-update` reconciles only
tools enabled on this machine. Headroom routing is process-local to the Claude and
enhanced Codex wrappers, restored on exit, and bypassed with a warning when the
proxy is unavailable; `claude-stock` and `codex-stock` always go direct. Docker
Compose, API secrets, AgentMemory feature flags, containers, volumes, and service
data remain owned by docker-local.

For a live check, run the three `ts-config agents <tool> status` commands and
open the Headroom dashboard. Dashboard attribution follows the originating
client: Claude requests appear as Claude/Anthropic; Codex requests appear as
OpenAI and increment Codex WebSocket counters. Setting changes apply to newly
started agent sessions, not a process that was already running.

## `ts-wezterm`

Also reachable as `ts-config wezterm …`, and `t` in the `ts-config` menu.

| Command | What it does |
|---|---|
| `ts-wezterm` / `status` | your build + date, newest on each channel, a count of what changed since |
| `ts-wezterm changes` | the full upstream changelog since your build, paged through glow |
| `ts-wezterm install <stable\|nightly>` | switch channel — removes the other package first |
| `ts-wezterm upgrade` | refresh the channel you are on; never switches |
| `ts-wezterm -h` | help (works even when the clone or chezmoi is broken) |

Nothing here runs on its own: the wizard asks at install, `ts-update` offers when
something newer exists on the channel you are already on, and this changes it on
demand. The channel is read back from the package manager rather than stored, so
it cannot drift from what is installed. Details and the "where do those numbers
come from" explanation: `doc wezterm`.

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

## `ts-smb`
Find, interrogate and mount **SMB/CIFS shares** through rclone, with one flag
vocabulary on macOS and Linux instead of `smbutil`/`mount_smbfs` on one box and
`smbclient`/`mount.cifs` on another. **Windows is not covered yet** — Explorer and
`net use` already do this there.

| Command | What it does |
|---|---|
| `ts-smb` / `ts-smb list` | live mounts: name, state, engine, mountpoint (strays flagged) |
| `ts-smb hosts` | SMB servers advertising on this LAN over mDNS |
| `ts-smb hosts --sweep` | also port-scan your /24 — asks first, and it is noisy |
| `ts-smb shares HOST` | the shares a host offers |
| `ts-smb probe HOST/SHARE` | which credentials work, and what they get you |
| `ts-smb probe … --write` | also test writability (creates a file; asks first) |
| `ts-smb ls` / `tree` / `du` | look inside without mounting (`--depth N` for tree) |
| `ts-smb get SRC DST` | copy out without mounting |
| `ts-smb add NAME` | add a share (`--host`/`--path`/`--user` to skip the prompts) |
| `ts-smb creds NAME set` | store the password, obscured, in the OS keychain |
| `ts-smb mount NAME` | mount read-only (`--rw`, `--at DIR`, `--engine auto\|fuse\|nfs`) |
| `ts-smb umount NAME` | unmount (`--all`, `--force`) |
| `ts-smb engine` | which mount engine is used here, and why the others lost |
| `ts-smb doctor` | rclone, the FUSE engines, stale mounts, the store |
| `-n` / `--dry-run` | print the rclone command instead of running it |

Nothing has to be configured to interrogate a host: `ts-smb shares nas.lan` builds
an rclone connection string on the fly. rclone has no anonymous mode — user
`guest` with an empty password is the substitute, and it is the default.

Your shares live in `~/.config/terminal-stack/shares.local.conf`, which is
**untracked and never synced anywhere**; defaults come from `bootstrap/shares.conf`
in the clone. A stanza looks like:

```
share media
  host nas.lan
  path Media
  user marty
  cred keychain
```

The SMB share name is **`path`**, not `share` — `share` opens a stanza. Get that
wrong and `ts-smb doctor` says so by name.

Passwords are obscured once by `ts-smb creds` and kept in the OS keychain (macOS
`security`, Linux `secret-tool`, with a 0600 file fallback); they reach rclone
through the environment and never appear in a command line. There is deliberately
no `--password VALUE` flag — use `-P` to be prompted or `--password-stdin` in a
script.

If a mount will not work, `ts-smb doctor` is the command. On macOS it knows the
three things that break mounting silently: **Homebrew's rclone cannot mount at
all** (a build-time guard; browsing still works, so install the official binary
from <https://rclone.org/downloads/> if you need mounts), rclone picks its FUSE
library by a fixed order that a stale **macFUSE** wins over a working **FUSE-T**
(`ts-smb` pins it, so this cannot bite), and FUSE-T's **FSKit** backend is not
enabled by default because it fails where the default NFS backend does not. On
Linux it detects the AppArmor block on `fusermount3` that Ubuntu 24.04+ ships.

See `doc smb-shares` for the topic page and `doc rclone` for the tool itself.

## SSH (stack shortcut)
`ssht host [session]` — SSH and attach-or-create a remote tmux session in one shot
(default session `main`); also names the WezTerm tab `ssh-host:session`. **zsh
only** — no pwsh counterpart. See `doc common/ssh-config`, `doc common/tmux`.
