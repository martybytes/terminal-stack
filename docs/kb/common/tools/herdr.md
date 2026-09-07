# herdr (terminal multiplexer for coding agents)

One Rust binary that runs a background server and owns the terminals your coding
agents live in. Panes survive detach, network loss and reboot; every pane is
marked working, blocked or idle, so the stuck agent is the one you can see. It
does not wrap or replace Claude Code, Codex, Cursor or Grok — it hosts them.

Apache-2.0, from [herdr.dev](https://herdr.dev). Docs: <https://herdr.dev/docs/>.

## How this stack wires it

- **Opt-in twice, deliberately.** The app picker offers `herdr` and never
  pre-ticks it (`classes none` in `bootstrap/apps.conf`). The *config* is a
  separate setting, `herdrConfig`, default **off**. Running herdr with a config
  the stack has never touched is a supported answer, not an oversight.
- **Installed from herdr.dev's own script**, on every platform, never from a
  package manager. `curl -fsSL https://herdr.dev/install.sh | sh` on POSIX;
  `irm https://herdr.dev/install.ps1 | iex` on Windows.
- **Not winget.** There is no stable `Herdr.Herdr` manifest. `Herdr.Herdr.Preview`
  is Herdr, Inc.'s but pins the preview channel, and `hdosys.herdr-win`,
  `khanhtd36.herdr-khanhtd36` and `hdosys.herdr-sandbox` are third-party
  republishes. Check with `winget show --id Herdr.Herdr --exact` before that
  changes.
- **Not brew on macOS either.** `herdr channel set` works on direct installs
  only, and this stack reads the channel back rather than storing it — a
  brew-managed herdr would report a channel nothing could change.
- **It sits beside tmux**, it does not replace it. tmux stays the `ssht`
  persistence story on servers, and nothing starts herdr for you.

## The managed config

`tstack herdr` is the one implementation; both shells hand off to it.

| Command | What it does |
|---|---|
| `tstack herdr` / `tstack herdr status` | the setting, the config file, the binary, the channel, the servers |
| `tstack herdr on` | splice our key in, backing the file up first |
| `tstack herdr off` | restore the backup, or remove just our line |
| `tstack herdr update` | say whether a newer herdr exists; never installs it |

`tstack config herdr on|off` is the same thing by another door.

**It is a key splice, not a whole-file render.** herdr writes this file itself
(`herdr config reset-keys` rewrites it, the global menu edits it) and so do you.
The first machine this shipped to already had a hand-written config carrying
`onboarding = false` and `[terminal] default_shell = "pwsh"`. A whole-file mirror
would have deleted both, silently, with nothing in any diff — the same failure as
whole-file-copying `~/.claude/settings.json`. So ownership is per **key**:

```toml
[theme]
name = "terminal"  # managed by terminal-stack

[terminal]
default_shell = "/usr/bin/zsh"  # managed by terminal-stack
```

That is the entire set — two lines, each carrying the marker. Every other byte of
the file, comments and formatting included, survives a write untouched. The
second line is conditional and explained under "Which shell your panes run":
`auto` defers to a `default_shell` you wrote yourself, which is what keeps the
`"pwsh"` machine above intact.

**Why `terminal`.** herdr ships eleven built-in themes (`catppuccin`, `terminal`,
`tokyo-night`, `dracula`, `nord`, `gruvbox`, `one-dark`, `solarized`, `kanagawa`,
`rose-pine`, `vesper`) plus an `auto_switch` light/dark pair. Naming one would
make the stack a second theme owner and would have to be re-derived every time
`themeMode` changed. `terminal` uses the host terminal's ANSI palette — which
this stack already themes — so one value is correct in **dark, light and follow**
alike, and stays correct when the OS appearance flips underneath.

**`off` never deletes the file.** It restores the `.bak.YYYYMMDD` taken before
the first write, or, when the stack created the file itself, removes only the
marked line. It is deliberately not a `.chezmoiremove` rule and not a sync-side
delete: both of those run on every machine and would reach a box that never opted
in.

## Which shell your panes run

herdr spawns your **login shell** by default. On Omarchy that is bash and always
will be — the fleet never runs `chsh`, because Omarchy's own desktop is
bash-first — while the shell this stack actually configures, with the prompt, the
tools and the agent wrappers, is zsh. So the default gives you a pane that is not
the machine the rest of the stack set up. That is what `herdrShell` fixes.

| Command | What it does |
|---|---|
| `tstack config herdr shell auto` | the shell this stack configures here (the default) |
| `tstack config herdr shell zsh` | name one explicitly — also `bash`, `pwsh` |
| `tstack config herdr shell login` | herdr's own behaviour; the stack owns no shell key |

`auto` is OS-aware, and the map is four platforms and two answers:

| Platform | `auto` resolves to | Login shell there |
|---|---|---|
| Windows | `pwsh` | whatever `$PROFILE`'s host is |
| macOS | `zsh` | usually zsh already |
| Ubuntu / Debian | `zsh` | usually zsh already |
| Omarchy | `zsh` | **bash**, deliberately |

Omarchy is the row that makes it a setting rather than a guess.

Three things worth knowing:

**It writes an absolute path**, resolved on the machine, never a bare name. The
herdr *server* is long-lived and keeps the environment it started with, so its
`PATH` is not your shell's — the same property that cost this stack an ssh agent
in every pane (`doc ssh-config`). What is **stored** is the choice, not the path:
a path would be wrong on the other side of a combined Windows+WSL machine, and a
Windows one carries backslashes, which the settings store cannot hold.

**A shell that is not installed is never written.** A `default_shell` pointing at
something absent breaks every new pane; leaving herdr on the login shell it was
already using is strictly better, and `tstack herdr status` says which happened.

**`auto` defers to a `default_shell` you wrote yourself.** An unmarked line in
this file is yours — that is the rule the whole section above is built on, and
the first machine this shipped to had a hand-written `default_shell = "pwsh"`.
Naming a shell explicitly is how you hand the key over; the file is backed up
before the first write either way.

```bash
tstack herdr status            # the setting, what it resolved to, and why
herdr server reload-config     # apply it; open panes keep the shell they have
```

`shell_mode` (`login` / `non_login`) stays yours — the stack owns
`[terminal] default_shell` and nothing else in that table.

One cosmetic thing worth knowing: a key the stack re-adds after `login` removed it
is inserted at the **top of its table**, not back where it was. Nothing is lost —
your lines and comments all survive — but a comment you wrote directly above the
old position now sits above whatever followed it. Keep such a comment with the
line if the position matters to you.

One implementation on all four platforms: `tstack/commands.conf` gives `herdr` a
`python` column for POSIX *and* Windows, so there is no bash writer and no pwsh
twin. Saving the setting and re-splicing the file have to happen together, and
splitting that across three implementations is how a store and a file come to
disagree.

## Where the config lives

| Platform | Path |
|---|---|
| Linux, macOS, WSL | `~/.config/herdr/config.toml` (or `$XDG_CONFIG_HOME`) |
| Windows | `%APPDATA%\herdr\config.toml` |

`HERDR_CONFIG_PATH` overrides it, and this stack honours that override. Run
`herdr --help` to see the path herdr itself resolved.

Reload after an edit without restarting: `herdr server reload-config`.
Startup-only settings still need a restart.

## The prefix collision

herdr's prefix is **`ctrl+b`**, which is also this stack's default `tmuxPrefix`.
The stack stores no prefix key of its own for herdr, so the two match out of the
box — and because herdr sits beside tmux rather than replacing it, nesting one
inside the other is reachable. Nested, the inner one never sees the chord.

`tstack doctor` reports this as a **note**, never a failure, and never rewrites
either side: which of the two to move is your call.

- move tmux's: `tstack config tmux ctrl-a`
- move herdr's: `[keys] prefix = "ctrl+a"` in `config.toml`

The note is gated on tmux actually being installed. A warning you can never
satisfy is a nag, and this stack has been bitten by that before.

## Two machines, two servers

On a combined Windows + WSL box the Windows herdr and the WSL herdr are
**independent**: separate binaries, separate sockets, separate configs. Neither
side's config resolves to a `/mnt/c` path, and neither sets `HERDR_SOCKET_PATH`
for the other. `tstack herdr status` reports both, labelled, rather than pretending
one is authoritative — the Windows one is reached through interop (`herdr.exe`),
never `pgrep`, which finds nothing inside WSL while a healthy Windows server runs
on the same machine.

## Updates

herdr self-updates with `herdr update`, and checks for new versions in the
background on its own (`[update] version_check`). `tstack update` prints that a
newer one exists and stops there: updating a live multiplexer is the same class
of hazard as restarting the WezTerm mux server, which this stack deliberately
never automates. Run it yourself when no session is mid-flight.

## Useful commands

```sh
herdr                       # launch or attach to the default session
herdr --session <name>      # attach to a named one
herdr --remote <host>       # attach over ssh, with local keybindings
herdr status                # client, server, update
herdr session list          # every session
herdr --default-config      # print every setting, commented, with its default
herdr channel show          # stable | preview
herdr completion zsh        # completions (also bash, fish, powershell, elvish)
```

Agents drive it too: `herdr agent start`, `agent prompt`, `agent wait`,
`agent read`, `agent send-keys`. Inside a pane, herdr exports `HERDR_PANE_ID`,
`HERDR_TAB_ID`, `HERDR_WORKSPACE_ID`, `HERDR_SESSION` and `HERDR_SOCKET_PATH`.

## Known gaps

Two things this stack does not do yet, both tracked in `docs/herdr-rollout.md`:

- **No shell completions are installed.** `herdr completion <shell>` works, but
  wiring it into `~/.zshrc` or `$PROFILE` costs a subprocess on every shell
  start, so it needs caching before it ships.
- **Tab titles are not herdr-aware.** `_ts_tab_title` / `Set-TsTabTitle` call
  `wezterm cli set-tab-title`, which does nothing inside a herdr pane. herdr has
  a `--label` on its pane commands and exports `HERDR_PANE_ID`, so the branch is
  detectable — it just is not written.

## See also

- `doc common/tmux` — the multiplexer herdr sits beside
- `doc common/tools/wezterm` — and the one it usually runs inside
- `doc common/tstack` — every `tstack` subcommand
