# terminal-stack revamp: `tstack` as one Python program

Roadmap for replacing the two-copy bash/PowerShell management layer with a single
Python program named `tstack`, plus a Textual dashboard. Written outside the repo so
it does not disturb the working tree.

Baseline: `terminal-stack` @ `f67ed5f` (main, clean).

---

## 1. Why

The original proposal was a short `tstack` command fronting the `ts-*` scripts plus a
Ratatui TUI. Investigation changed the shape of both.

The real problem is not the command names. **Every piece of management logic exists
twice**, once in bash and once in PowerShell, kept in agreement by a human remembering
to edit both and by a manual pty diff.

### Traced: what `ts-config theme dark` does today

**On Mac / Linux / WSL:**

```
zsh function ts-config()                 dot_zshrc:869
  -> bash bootstrap/ts-config.sh theme dark
       -> sources bootstrap/_config.sh            1,109 lines
       -> ts_data_set themeMode dark              awk-edits chezmoi.toml
       -> chezmoi init                            regenerates derived keys
       -> ts_mirror_windows_config                writes config.json
```

**On Windows:**

```
alias ts-config -> Set-TerminalStackConfig        $PROFILE:1075
  -> dot-sources bootstrap/_config.ps1            2,050 lines
  -> Save-TsConfig -ThemeMode dark
  -> writes %LOCALAPPDATA%\terminal-stack\config.json
```

Neither calls the other. They share zero code. They are two hand-written
implementations of one feature.

### Measured duplication

| | bash | pwsh |
|---|---|---|
| `_config` | 1,109 | 2,050 |
| `wso` / `_workspace_cmd` | 820 | 745 |
| `ts-stack` | 635 | 897 |
| `ts-agentmemory` | 609 | 490 |
| `ts-agents` | 359 | 431 |
| `_workspace` | 468 | 431 |
| `_agentmemory` | 323 | 355 |
| `_merge_json_settings` | 236 | 274 |
| `_cleanup` | 212 | 278 |
| **twin subtotal** | **4,771** | **5,951** |
| `dot_zshrc` / `$PROFILE` (partial twins) | 1,870 | 2,351 |
| **repo total** | **16,006** | **9,701** |

### What that duplication has actually cost

- `ts-stack` has been broken on Windows since commit `54da056`: a literal TAB byte at
  `$PROFILE:1705` in `Join-Path $src 'bootstrap<TAB>s-stack.ps1'`. Unnoticed because
  the Linux copy is fine.
- A `$foo` vs `$Foo` case collision coerced a scriptblock into a `[string[]]` of its own
  source text and killed **every `Read-TsMulti` call**, i.e. the entire Windows install
  wizard. Parses cleanly; invisible to `ParseFile`.
- Two config stores diverging silently removed **all five** Claude TTS hooks in one day,
  and emptied `~/.cursor/hooks.json` of agentmemory's seven Cursor hooks.
- Recorded and still true: pwsh-side `ts-config tts` saves do not survive a WSL apply.
  Each side writes its own store; last one to run wins.

The rule holding the two halves together is "their rendered output must be
byte-identical", verified by a **manual pty diff**. Only **one** of those pairs
(`ts-stack.sh` / `ts-stack.ps1`) is actually enforced by a test. CLAUDE.md states the
`ts-mux` pair is pinned too. It is not.

---

## 2. Why Python

Python is not a new dependency. It is already mandatory and already load-bearing:

- **Both sync paths hard-fail without it.** `run_after_90-sync-windows.sh:350` ("python3
  ships with WSL Ubuntu — require it"), `scripts/sync-windows.ps1:253` (`throw
  "sync-windows: Python 3 required to merge $dst"`).
- **11,506 lines already tracked**: `bootstrap/tts-daemon/ttsd/` is a 5,244-line Python
  application with 1,929 lines of its own pytest suite, plus 3,262 lines of repo tests.
- **The only commit gate is pytest** (`.githooks/pre-commit`).
- **Every shell script already shells out to Python for structured work**, via embedded
  heredocs: `ts-agentmemory.sh` (4 sites), `ts-agents.sh` (5), `ts-stack.sh`,
  `_agentmemory.sh`, `_doctor.sh`, `_merge_json_settings.sh`, `_wezterm.sh`.
- `python` is in `TS_APPS_RECOMMENDED` on both sides: winget `Python.Python.3.13`
  (`_config.ps1:39`), brew `python@3.14` (`_config.sh:404`).

The repo already decided Python is mandatory. It never admitted it architecturally.

### After

```
tstack config theme dark
  -> python tstack/commands/config.py theme dark
```

One file. Every platform. Fix a bug once.

### Why not a compiled core

Rust and Go both give a single fast binary with no runtime dependency, and both are
disqualified by the same thing: **this stack's entire update mechanism is `git pull` +
`chezmoi apply` on text files.** A compiled core turns every one-line fix into a build
and a distribution event, in a repo with no CI. Rust stays where it belongs, as an
optional extra that can be absent without breaking anything.

---

## 3. End state

```
install-*.sh / install.ps1     shell    ~1,500 lines   bootstrap only
dot_zshrc / $PROFILE           shell    ~800 each      integration + tstack shim
tstack/                        python   ~5-6k          ALL management logic
bootstrap/tts-daemon/          python   5,244          unchanged
tstack/ui/                     python   Textual dashboard
```

Shell and PowerShell drop from ~25.7k lines to ~4k. Python rises to ~17k. Net less
code, one implementation, and tests that check behaviour rather than scanning shell
source text.

**What stays shell, permanently:**

- **Bootstrap.** A bare machine has `bash` or `pwsh` and nothing else. Chicken-and-egg.
- **Shell integration.** PATH, prompt, key bindings, and anything that changes the
  parent shell's working directory or restarts it. A subprocess cannot do that.

`update` and `rollback` still move to Python: the Python side does the work and exits
with a code the thin shim acts on (restart zsh, or `cd` to a path). Zoxide uses exactly
this pattern.

### Package layout

Top level `tstack/`, not `bootstrap/tstack/`. `bootstrap/` means "runs once at install";
this is the daily driver, and `bootstrap/` shrinks as the port proceeds. Requires a
`tstack/**` line in `.chezmoiignore`, which is allow-by-default: without it every source
file is written into `$HOME` on apply, the trap already documented there for `tests/**`
and `services/**`.

```
tstack/
  main.py           entry; puts its parent on sys.path, then imports the package
  cli.py            dispatcher, help, --version, --json plumbing
  registry.py       subcommand table: name, summary, impl (python | shell)
  paths.py          clone resolution
  platform.py       OS / WSL detection, wslpath, python discovery
  store.py          the ONE config writer
  schema.py         settings schema
  commands/
  ui/               Textual dashboard
```

Three pieces have existing models to reuse rather than reinvent:

- `paths.py` ports clone resolution currently written **three times**:
  `bootstrap/_cleanup.sh` `ts_clone_candidates` (the documented master),
  `dot_zshrc:560-622`, and `$PROFILE:782-871`. Both documented asymmetries must survive:
  an explicit `--source-dir` hard-fails, a dangling `TERMINAL_STACK_DIR` degrades to the
  candidate search.
- `store.py` is the single writer of chezmoi `[data]` **and** the Windows
  `config.json` mirror. It must keep calling `chezmoi init` after a save (that is what
  regenerates the derived `leaderKey`, `leaderMods`, `tmuxPrefixResolved`,
  `resolvedTheme`) and must keep the carry-forward behaviour that `Save-TsConfig`'s
  `$PSBoundParameters.ContainsKey` guards provide: omitting a key must not reset it.
  One writer is what fixes the two-store drift.
- `schema.py` copies the shape of `bootstrap/tts-daemon/ttsd/settings_schema.py`
  (`key, label, kind, options, group, note, flags`, plus which layer won per field).

---

## 4. The transition mechanism

`registry.py` marks each subcommand `python` or `shell`. **The shell shims do the
routing**, because a not-yet-ported Windows subcommand lives inside `$PROFILE` as a
function and cannot be invoked from a child process.

```
tstack <sub>  ->  shim reads registry
                    impl = python  ->  run tstack/main.py <sub> ...
                    impl = shell   ->  call the existing native implementation
```

This is what lets **every `ts-*` name be deleted in Phase 0**, before any logic moves.
The user only ever sees `tstack`. Each later port flips one registry entry from `shell`
to `python` and deletes two files.

Command surface:

```
tstack config       tstack services      tstack agents
tstack doctor       tstack smb           tstack agentmemory
tstack update       tstack wezterm       tstack doc
tstack rollback     tstack mux           tstack ui
tstack --version    tstack --help
```

No `ts-*` name survives, and no alias is provided anywhere, tracked or untracked.
`wso` and `doc` stay standalone; `tstack doc` is an extra entry point, not a
replacement. `wso` must stay a shell function regardless, since it changes the parent
shell's directory.

---

## 5. Phases

Each is its own branch, `merge --no-ff` into `main`, with docs and a `CHANGELOG.md
[Unreleased]` entry shipping with the change. Each later phase ends by flipping one
`registry.py` entry to `python` and deleting the shell twin pair.

**Phase 0 — foundation.** The `tstack/` package with the dispatcher, `--help`,
`--version` and the routing. Shims in `dot_zshrc` and `$PROFILE`. Every `ts-*` name
deleted. `$PROFILE:1705` TAB bug fixed. Completions from the registry (the first in the
repo). Path-existence test. Characterization harness. Docs sweep.

| # | Subsystem | Replaces | Why this order |
|---|---|---|---|
| 1 | `doctor` | `ts-doctor.sh` + `_doctor.sh` (510) vs `$PROFILE:1746-1823` + `_cleanup.ps1` | pure read and report; easiest to characterize; `--json` immediately |
| 2 | `config show` + schema | read half of `_config.sh` (1,109) / `_config.ps1` (2,050) | `settings_schema.py` is already the model |
| 3 | `services` | `ts-stack.sh` (635) / `ts-stack.ps1` (897) | near-perfect duplicate, best-tested subsystem already |
| 4 | `config` writes + wizard | rest of `_config.*`, `_wizard.sh` (767) | highest duplication and highest risk: chezmoi, the mirror, derived keys |
| 5 | `mux`, `wezterm`, `agents`, `agentmemory`, `smb` | `ts-mux.sh` (301), `_wezterm.sh` (446), `ts-agents.*`, `ts-agentmemory.*`, `ts-smb.sh` (1,150) + `_smb.sh` (702) | |
| 6 | `wso` / workspace | `wso.sh` (820) / `_workspace_cmd.ps1` (745) + `_workspace.*` | |
| 7 | `update` / `rollback` | `dot_zshrc:711-861`, `$PROFILE:886-1073` | last; exits with a code the shim acts on |
| 8 | `tstack ui` | new | Textual, importing the core directly |

**Never ported:** the four installer entry points, `_common-debian.sh`, the chezmoi
templates, and everything in `dot_zshrc` / `$PROFILE` that must run in-process (PATH,
prompt, key bindings, `ws*` directory jumps).

---

## 6. Traps found during investigation

**Path strings appear in three spellings.** `bootstrap/ts-x.ps1` (forward slash,
deliberate in `sync-windows.ps1`), `bootstrap\ts-x.ps1` (backslash, in `$PROFILE` and
three kb docs), and **bare `ts-x.ps1` via `$PSScriptRoot`/`$ROOT`** in
`ts-agents.ps1:381,387,405`, `ts-agents.sh:314,315,324` and `windows-bootstrap.ps1:184`.
A grep for `bootstrap/ts-` misses the third group entirely. Hence the path-existence
test, which is the permanent guard.

**`check-capture.sh:76` probes for a command named `ts-agentmemory` on `PATH`.** Update
it with the rest (`:77-79, 89, 93, 431`, and `check-capture.ps1:38-41, 383`).

**Bootstrap sequencing.** `ts_wizard_collect` runs **before** package installs,
deliberately: the documented invariant is that answers are saved before anything that
can fail (`docs/verifying-changes.md` §4e). Once the wizard is Python, Python must exist
first. So `_common-debian.sh`, `mac-bootstrap.sh` and `windows-bootstrap.ps1` ensure
Python 3.10+ as **step 0**. Debian/Ubuntu already ship it; macOS ships 3.9 and needs
`brew install python@3.14`; Windows needs `winget install Python.Python.3.13`. Reuse the
`Find-Python` probe already in `bootstrap/tts-daemon/build.ps1:12-27`. This changes the
failure mode from "answers lost on a later abort" to "abort before any question", which
is strictly better.

**Four scripts print `-h` by `sed -n 'N,Mp' "$0"` over their own header comment**:
`ts-config.sh:583` (2,21), `ts-doctor.sh:41` (2,13, zero slack), `ts-agentmemory.sh:34`
(2,16), `wso.sh:818` (2,19, with a hand-maintained marker at `:21-22`). Two tests parse
the range out of the source and assert a specific line falls inside it
(`test_agent_tools.py:724-728`, `:889-893`). Python argparse removes the class.

**Tests that slice `dot_zshrc` on literal function names** must be rewritten:
`test_agent_tools.py:79` (`ts-rollback() {`), `:705` (`ts-update() {`), `:1060`
(`\nts-smb() {`), `:1076` (the `# ts-smb` comment marker). Also the `bash -n` entrypoint
list at `:312-324` and `test_stack.py:389` (literal `"ts-stack bootstrap"` in
`INSTALL.md`).

---

## 7. Must NOT be renamed

Heavily test-pinned, and not part of the command surface:

- **The Docker `ts-` prefix** on every project, container, image, volume and network.
  Pinned by `test_stack.py:240-241, 244, 250, 260-271, 282-288, 507-509`, plus the
  literal refusal string `pre-ts- names` at `:298`. Renaming means a data migration.
- **`services/stacks/*/ts-{after,envfiles,checks.conf,verify.sh,verify.ps1}`** — 18
  files, discovered by exact filename with no registry. Pinned by `test_stack.py:466-469,
  476, 481, 489, 496, 580, 587, 594, 599-600, 605-606` and
  `test_service_script_parity.py:138, 147`.

---

## 8. Verification

Characterization tests are the safety mechanism. Before porting a subsystem, run the
existing shell implementation in a throwaway `HOME`, capture stdout, exit code and
resulting file contents, and pin them. Port to Python. Require the same fixtures pass.
Then delete the shell twins. That is what makes a 14,000-line port survivable in a repo
with no CI, against a failure mode that is characteristically silent.

```sh
python -m pytest tests/ -q                  # the existing commit gate
python -m pytest tests/characterize -q      # shell-vs-python equivalence
python tstack/main.py --help
bash -n <changed>.sh ; zsh -n dot_zshrc     # remaining shell only
```

```powershell
$e = $null
[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $f), [ref]$null, [ref]$e); $e
python -m pytest tests/test_agent_tools.py -k shadows -q   # while any .ps1 remains
```

Config-store changes use a throwaway store, never the real one: POSIX temp `HOME` with
its own `chezmoi.toml` (omit `windowsUsername` and the Windows mirror no-ops); Windows
overrides `$env:LOCALAPPDATA` in a child pwsh. Recipes at `docs/verifying-changes.md` §4.

**A dev clone cannot verify end to end.** `chezmoi source-path` points at the runtime
clone and dev clones at workspace tier paths are deliberately invisible, so `chezmoi
apply` from a dev tree deploys the old code and proves nothing. Verify with the gates
above, commit, then `tstack update` on the target machine and check there.

Run the suite on Windows **and** under WSL before each merge: the two halves of
`store.py` only both execute across that boundary.

---

## 9. Non-goals

- Do not rename the project or the repository.
- Do not keep any `ts-*` alias, tracked or untracked.
- Do not rename the Docker `ts-` prefix or the per-stack `ts-*` convention files.
- Do not let the dashboard write config directly; it calls the same core functions the
  CLI does, and the core remains the only writer.
- Do not port the bootstraps or the in-process shell integration.
- Do not add Rust to the app catalog.
