# A dashboard for terminal-stack - design

Status: **design only.** Nothing here is built. It is the last phase of the port
described in `REVAMP-PLAN.md`, and it depends on every phase before it.

## What changed since the first draft

The original design assumed the management layer would stay bash + PowerShell
twins, so a TUI had to be a separate program talking to them over a `--json`
contract, and Ratatui was the natural choice. That assumption is gone: `tstack`
is becoming one Python program.

| first draft | now | why |
|---|---|---|
| Ratatui (Rust) | **Textual (Python)** | it ships with `git pull` like everything else; a compiled binary does not |
| command `ts-tui` | **`tstack ui`** | one entry point, one namespace |
| prebuilt binaries via cargo-dist | nothing to distribute | there is no artifact |
| a `--json` contract between two programs | direct function calls | same process, same objects |
| version skew between binary and clone | impossible | the dashboard *is* the clone |

The skew problem was the largest single risk in the first design, and it
disappeared rather than being solved: `tstack update` is `git pull` +
`chezmoi apply`, and a Python dashboard participates in that automatically.
`tstack rollback` takes the dashboard back with it.

`--json` read models are still worth building - they make the stack scriptable
and they are what external probes want - but they are no longer load-bearing for
the dashboard.

## The rule that did not change

**The dashboard never writes config itself.** It calls the same core functions
the CLI calls. Not because Python could not write the file, but because two
writers is exactly how this repo lost all five Claude TTS hooks in a single day
and emptied `~/.cursor/hooks.json` of agentmemory's seven Cursor hooks: the
chezmoi `[data]` store and the Windows `config.json` mirror disagreed, each side
rendered a valid file from its own copy, and the setting flipped depending on
which applied last.

One writer, reached the same way from the CLI and the dashboard. A test enforces
it: nothing under `tstack/ui/` may import a writer or touch a config path
directly.

## What it shows

Ordered by what is worth opening it for.

1. **Home** - health summary, clone SHA and branch, mux state, service counts,
   last update, anything `doctor` flagged.
2. **Doctor** - checks by severity, `r` to run a repair. This is the screen people
   open when something is wrong, so it has to be the one that reads best.
3. **Services** - per-stack state, health and published ports; start, stop,
   restart, logs.
4. **Config** - every key with its value, its default, and **which layer won**.
   That last column is the point; it is what `ttsd/webui.py` already does for the
   TTS settings and the reason that dashboard can be trusted.
5. **Doc browser** - the `docs/kb/` tree with preview. Worth building first: it
   needs no config access at all, so it exercises the widget layer while risking
   nothing.

Deliberately absent:

- **The 41 `ccTts*` keys.** The daemon already has a full web dashboard for them
  (`ttsd/webui.py`), including override display and restart-required labels.
  Link to it rather than rebuilding it.
- **`update` and `rollback` as in-app actions.** Both are interactive multi-stage
  flows that can re-exec the shell. The dashboard suspends, hands the terminal
  over, and re-enters.
- **`wso` and `smb` mutations.** Read-only until they are ported and proven.

## Testing it

Textual is testable in a way a terminal UI usually is not, and that is a large
part of why it wins here:

- `pytest-textual-snapshot` over the rendered output of every screen.
- The `Pilot` API for keyboard interaction: focus order, key bindings, and what a
  screen does when the backend raises.
- `textual serve` puts the same app in a browser, so the Playwright setup this
  repo already uses covers keyboard navigation, focus order, resize and visual
  regression - without driving a native terminal, which Playwright cannot do and
  should not be asked to.

## Two runtime rules carried forward

- **Never `stat`, `ls` or glob an SMB mountpoint.** A dead FUSE mount blocks
  forever and takes the calling process with it. In a CLI that is an annoying
  hang; in a dashboard it is a frozen render loop with no way out. Liveness comes
  from the kernel mount table, which is why `smb` derives it rather than storing
  it.
- **Never auto-restart `wezterm-mux-server`.** It loads its own copy of the
  config, so a config change does not reach it - but restarting kills every live
  pane. Print the reminder; the restart stays deliberate.

## Where it sits in the port

Last, as phase 8 in `REVAMP-PLAN.md`, after `doctor`, `config`, `services` and the
rest are Python. A dashboard built over shell-outs would be the screen-scraping
design this whole port exists to avoid.
