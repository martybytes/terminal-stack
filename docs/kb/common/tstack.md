# tstack — the stack's one command

`tstack` is the single entry point for the whole stack. There are no `ts-*`
commands any more, and no aliases for them.

| Command | What it does |
|---|---|
| `tstack config` | view and change saved settings (the table below) |
| `tstack ui` | every setting in one screen; needs Textual |
| `tstack doctor` | diagnose the install; `--quiet`, `--json`, `--repair` (see below) |
| `tstack update` | pull the latest stack and re-apply |
| `tstack rollback` | undo the last update |
| `tstack apply` | re-apply the dotfiles, explaining any conflict first (POSIX) |
| `tstack services` | the Docker service stacks - see `doc services` |
| `tstack mux` | the WezTerm multiplexer domain |
| `tstack wezterm` | WezTerm channel and updates |
| `tstack ghostty` | the managed Ghostty config; `status`, `diff`, `on`, `off` |
| `tstack wizard` | ask the install questions and print the answers — it saves nothing |
| `tstack smb` | SMB shares over rclone (POSIX only) - see `doc smb-shares` |
| `tstack agents` | agent CLI wiring - see `doc agentmemory`, `doc headroom` |
| `tstack agentmemory` | the agentmemory hook harness; `--check` reports reverted edits |
| `tstack doc` | this knowledge base (the bare `doc` command is the same thing) |
| `tstack --help` | every subcommand, with platform gaps marked |
| `tstack --version` | clone path, branch, commit, and whether it is dirty |

A subcommand reported as "not available on <platform>" is deliberate, not a
broken install: `smb` has no PowerShell implementation.

`doctor`, `services`, `mux`, `wezterm`, `agents`, `ghostty`, `wizard`, `ui` and (on POSIX) `config` are one Python program
that runs identically on Windows, WSL, Linux and macOS. `update`, `rollback`,
`smb` and `agentmemory` are still shell, as is `config` on **Windows** -- that
row's two columns differ deliberately until it can be exercised there. `tstack`
routes to whichever the registry (`tstack/commands.conf`) says, so the command
you type never changes as each one is ported.

On POSIX, `tstack config apps`, `tts` and `reconfigure` hand back to
`bootstrap/ts-config.sh`: they end in a package-manager install or the
bootstrap's own save sequence, which the port deliberately never covers.


## "… has changed since chezmoi last wrote it?"

You edited a file the stack owns -- `~/.zshrc`, `~/.tmux.conf`,
`~/.config/starship.toml` -- or something else did, and now an update wants to
replace it. Left to itself chezmoi asks

```
.zshrc has changed since chezmoi last wrote it?
> diff/overwrite/all-overwrite/skip/quit
```

and says nothing about what you would lose. `tstack apply` asks the same
question with the answer spelled out, and **backs your version up before
overwriting it** -- chezmoi does not, on POSIX.

```sh
tstack apply              # explain, then decide file by file
tstack apply --overwrite  # take the stack's version everywhere, backing yours up
tstack apply --check      # list what would be asked about; change nothing
```

| answer | what happens |
|---|---|
| `overwrite` | your file is copied to `<file>.bak.YYYYMMDD`, then the stack's version is installed |
| `all` | the same, for every remaining file. Usually what you want |
| `diff` | show exactly what would change |
| `merge` | open chezmoi's merge tool. It edits the **source clone**, which `tstack update` then refuses to run from until you commit or discard that change |
| `quit` | stop. Nothing is applied and nothing is backed up |

**Overwriting is the right answer more often than it sounds**, because these
files are not where your settings belong. The stack owns them outright and
rewrites them on every update, so an edit made directly to `~/.zshrc` is
temporary by construction. Put your own configuration in:

- `~/.zshrc.local` — sourced at the end of `~/.zshrc` (see `dot_zshrc.local.example`)
- `Documents\PowerShell\profile.local.ps1` — dot-sourced by `$PROFILE`

Neither is ever managed or overwritten, so anything you move there survives the
question permanently.

To recover a file you overwrote:

```sh
ls ~/.zshrc.bak.*            # newest wins; .1, .2 are same-day re-runs
cp ~/.zshrc.bak.20260829 ~/.zshrc
```

### It stopped without asking

A run with no terminal to ask on — CI, a piped script, some `curl | bash`
setups — cannot make the choice for you, so it makes none: it lists the files,
prints these same options and exits 4 having changed nothing. Re-run
`tstack apply` from a terminal, or `tstack apply --overwrite` if you already
know you want the stack's versions.

## `tstack ui`

Every saved setting in one screen: what it is now, what the default is, and
**which layer the value came from** - chezmoi `[data]`, the Windows mirror, or
nothing at all. Those three look identical once a value is printed, and on
2026-08-21 they disagreed while every report looked healthy.

```sh
tstack ui
```

| Key | What |
|---|---|
| `/` | filter by key, label, group, value **or note** - the keys are camelCase internals, so "ollama" or "leader" is what you actually type |
| `Enter` | edit the selected setting |
| `Space` | next value, for a choice setting; saves straight away |
| `d` | back to the default |
| `r` | reload from the store |
| `q` | quit |

A `*` before a value means it differs from the default. A setting chezmoi
*derives* from your other choices (`resolvedTheme`, `leaderKey`, …) is listed but
refused - writing one produces a value that survives until the next save.

Writes go through the same setter the command line uses, so there is no second
writer and no second set of validation rules. Nothing here starts a container or
installs anything; it edits settings.

Textual is the one third-party library this program uses and only this command
needs it, which is why it is not installed for you:

```sh
uv tool install textual     # or pipx install textual, or pip install --user textual
```

## `tstack doctor`

The health check. Read-only by default; exit status is the answer, so it is safe
in a script: **0 healthy, 1 issues found**.

| | |
|---|---|
| `tstack doctor` | every check, with an `ok` line each |
| `tstack doctor --quiet` | drops the `ok` lines. Problems and `note:` advisories still print |
| `tstack doctor --json` | one record per check: `check`, `status`, `message`, optional `hint` |
| `tstack doctor --repair` | fix what is fixable, confirming each step |

It also reports a **chosen Starship preset that is not the prompt you are
running**: the template falls back to this stack's own prompt when starship is
missing, so the setting and the deployed file can disagree with nothing else
saying so.

Three severities. `ok` is the only one `--quiet` drops. `!!` is a problem and counts
toward the exit status. `note:` is worth telling you and never counts - a leftover
clone, a legacy clone location, a dev-clone pin - and it survives `--quiet`,
because an advisory you only see in verbose output is one you never see. Folding
notes into failures would instead train you to ignore the exit code.

`--json` is a read model, not the prose reformatted: `check` is a stable id safe
to match on, while the message wording is free to improve. That is what the
dashboard will consume.

```sh
tstack doctor --json | python3 -c 'import json,sys
for c in json.load(sys.stdin)["checks"]:
    if c["status"] != "ok": print(c["check"], "-", c["message"])'
```

One implementation runs on every platform. Before this was ported, the bash side
ran about twenty checks and the PowerShell side about eight, so Windows never
checked config-store divergence, the memory-backend derivation, SMB mount records
or the agentmemory hook wiring at all.

What it looks at: the chezmoi binary and where it applies from (POSIX only - on
Windows the apply path is `sync-windows.ps1`), the clone and whether other clones
exist, `~/.zshrc` or `$PROFILE` carrying the stack block, `zsh` and `starship` on
PATH, the two config stores agreeing, `memoryBackend` matching its derived
`agentmemoryEnabled`, the TTS engine and daemon when TTS is on, a `local.json`
override silently forcing it off, the agentmemory hook wiring a plugin upgrade
reverts, SMB mount records, and - in a dev clone - whether the commit gate is
actually installed.

## Configuration

Everything the install wizard asks, changeable afterwards. Every change persists
(chezmoi `[data]` on WSL/Linux/macOS, `config.json` on Windows) and re-applies.

Run it bare for an interactive menu; `tstack config show` just prints the state.

| Command | What it does |
|---|---|
| `tstack config` | interactive menu |
| `tstack config show` | the saved config + the derived bindings |
| `tstack config leader <chord>` | WezTerm leader, e.g. `ctrl-space`, `ctrl-a`, `alt-x`, `ctrl-backslash` (keys with no printable spelling are named) |
| `tstack config theme <dark\|light\|follow>` | palette; `follow` tracks the OS theme |
| `tstack config tmux <chord>` | tmux prefix — see `doc common/tmux` |
| `tstack config apps [recommended\|all\|none\|id,…]` | app catalog (`bootstrap/apps.conf`); no arg → picker. Installs, never uninstalls |
| `tstack config prompt [status\|list\|<name>]` | which Starship prompt. `list` renders every option so you can see them |
| `tstack config atuin <on\|off>` | atuin owns `Ctrl+R` — see `doc common/tools/atuin` |
| `tstack config ghostty [on\|off\|status\|diff]` | hand-off to `tstack ghostty` — see `doc common/tools/ghostty` |
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
| `tstack config wizard` | ask them **and** save and install — see below |

## `tstack config wizard`

The "start over as if installing" path — it re-asks the profile question,
then leader, theme, terminal emulator, apps, prompt preset, mux, session
restore, atuin, voice and the agent tools, saves them all, and installs what
they imply. `tstack config apps` re-asks only the apps question.

**`tstack wizard` is a different command.** It runs the same questionnaire and
then *prints* or emits the answers; it writes no setting and installs nothing.
The split is deliberate — the four bootstraps each need the answers before
there is a config file to save them into, and each owns its own save order. So
`tstack wizard` is the questionnaire and `tstack config wizard` is the
questionnaire plus the consequences; `-h` on either one says which you have.

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
