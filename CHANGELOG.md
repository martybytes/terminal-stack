# Changelog

All notable changes captured here. Format loosely follows [Keep a Changelog](https://keepachangelog.com/). Dates are MM/DD/YYYY for display, `git log` is authoritative.

## [Unreleased]

### Added

- **herdr, the terminal multiplexer that hosts coding agents (09/04/2026).**
  Offered by the app picker on every platform and never pre-ticked, installed
  from herdr.dev's own script rather than a package manager, and configured by a
  new `tstack herdr` (`status`, `on`, `off`, `update`). The saved setting is
  `herdrConfig`, default **off**.

  Not winget: there is no stable `Herdr.Herdr` manifest, only
  `Herdr.Herdr.Preview` and three third-party republishes. Not brew on macOS
  either — `herdr channel set` works on direct installs only, and this stack
  reads the channel back rather than storing it, matching WezTerm.

  The managed config is a **key splice, not a whole-file render**. herdr rewrites
  `config.toml` itself and so does the user; the first machine this shipped to
  already carried a hand-written `onboarding = false` and `default_shell =
  "pwsh"`, both of which a whole-file mirror would have deleted silently. The
  stack owns exactly one key, `[theme] name = "terminal"`, which follows the
  terminal's own palette and is therefore right in dark, light *and* follow. `off`
  restores the backup taken before the first write, or removes just that line —
  it never unlinks the file, and is never a `.chezmoiremove`.

  herdr keeps its own `ctrl+b` prefix, which collides with this stack's
  `tmuxPrefix` default. `tstack doctor` reports that as a note, gated on tmux
  actually being installed, and never rewrites either side. On a combined
  Windows + WSL machine the two servers are independent, and
  `tstack herdr status` reports both. Rationale in `docs/decisions.md`; the
  runbook is `doc herdr`.

### Fixed

- **The pre-commit hook can pass again (09/04/2026).** `.githooks/pre-commit`
  runs mypy under `set -e`, and mypy had five errors in `tstack/ui/app.py` on a
  clean tree, so the hook rejected every commit in the clone. Newer Textual types
  `BINDINGS` as a list of `Binding` *or* the two tuple shorthands, and `list` is
  invariant, so the narrower `ClassVar[list[Binding]]` is an error however
  correct its contents; and `DOMNode.action_toggle` now takes an argument, which
  our no-argument picker override collided with. The annotations match the base
  exactly and the picker's action is `toggle_row`, which is its own name rather
  than a signature it never wanted.
- **`tstack wizard` runs on Windows again (09/04/2026).** The prompt preview
  shells out to starship, and `subprocess.run(..., text=True)` with no `encoding`
  decodes with the locale codec — cp1252 on a Windows console, which cannot
  decode what starship emits. The `UnicodeDecodeError` is raised inside
  subprocess's reader *thread*, so the call returned with `returncode == 0` and
  `stdout == None`, every `returncode != 0` guard passed, and the next `.strip()`
  died with an `AttributeError` a long way from the cause. That killed the whole
  questionnaire on the first question. Both calls in `tstack/choices.py` now name
  `encoding="utf-8", errors="replace"`, and `_run` treats a `None` stdout as
  failure. It had also been failing eleven tests in `tests/test_wizard.py`, which
  read as a Python 3.14 quirk and were not.

- **A WSL apply now reaches every Windows-side file again (09/02/2026).** The
  `run_after` sync walked `windows/` with the file list on the loop's stdin,
  and the part-owned merge for `.claude/settings.json` runs `pwsh.exe`, which
  drains inherited stdin. Everything after that entry in `find` order was
  silently skipped: `.config/**`, `.cursor/**`, `.wezterm/**`, `.wezterm.lua`
  and `$PROFILE` were never re-rendered from WSL, and the summary counted them
  as unchanged. The list now arrives on fd 3. Found because a saved leader
  change never reached the rendered `.wezterm.lua`.
- **`tstack config` on WSL refreshes the Windows `config.json` mirror (09/02/2026).**
  The Python port saved to chezmoi `[data]` and stopped there, while the shell
  save had always ended in `ts_mirror_windows_config`. `sync-windows.ps1` and a
  pwsh-side `tstack update` render from the mirror, so any setting changed from
  WSL was rendered back to its previous value by the next Windows-side sync.
  The apply step now calls the same bash writer after `chezmoi init`.
- **`Ctrl+\` can be the WezTerm leader (09/02/2026).** The leader chord is
  stored as `mod-key` text, and the only key with a spelled-out name was
  `space`. A literal `ctrl-\` had two failure modes, both silent until the
  next chezmoi command: the store writes `key = "<value>"` with no escaping,
  so the backslash left `chezmoi.toml` unparseable, and had it got through,
  every renderer would have produced `key = '\'` in Lua. `backslash` now joins
  `space` as a named key (`ctrl-backslash`, mapped to `phys:Backslash`) in
  both chord mappers, and the `leaderChord`/`tmuxPrefix` validator refuses a
  backslash or double quote with the spelling that works. Pinned by a
  two-mapper parity test and a pwsh run of `ConvertTo-TsLeader`.

- **Ghostty: backspace and Delete work over ssh again (08/28/2026).** ssh into
  any Linux host from Ghostty and backspace inserted junk instead of erasing,
  while Delete did nothing. Ghostty announces `TERM=xterm-ghostty` and `ssh`
  forwards it; a host with no `xterm-ghostty` terminfo entry cannot resolve
  `kbs` or `kdch1`, and readline gets both keys wrong. Nothing in the managed
  config caused it — stock Ghostty defaults to the same `TERM`, which is why
  `tstack config ghostty off` was not a diagnostic and looked like an acquittal.

  The config now sets
  `shell-integration-features = no-cursor,sudo,title,ssh-env,ssh-terminfo`.
  `ssh-terminfo` uploads the real entry per host on first connect (it needs
  `tic` there) and keeps Ghostty's full capability set; `ssh-env` is the
  fallback that sets `TERM=xterm-256color` where the upload cannot happen. Both,
  because either alone leaves a class of hosts broken — and note that naming any
  value for that key **replaces** Ghostty's defaults rather than adding to them.
  `ghostty +ssh-cache` lists and clears the per-host cache. Rejected the blunt
  `term = xterm-256color`, which fixes ssh by giving up Ghostty's terminfo in
  local panes too. Tests pin both features present and the absence of a global
  `term` line. WezTerm was never affected: it reports `xterm-256color` already.

### Removed

- **The Windows Ghostty target, and everything that fed it (08/28/2026).** The
  noctty integration added on 08/24 is gone: the `windows/AppData/Local/ghostty/`
  mirror and its generated theme, the `__GHOSTTY_THEME__` /
  `__GHOSTTY_WINDOW_THEME__` substitution in **both** sync scripts, the
  subtree-skip that implemented `ghosttyConfig=off` on that side, the interop
  binary probe, the pwsh terminal-picker row and `Get-TsGhosttyExe`, and the
  `Set-TerminalStackConfig ghostty` branch. `tstack/commands.conf` now says `-`
  in the Windows column, so the shim reports "not supported on this platform"
  rather than a missing command.

  Three things this simplified beyond Ghostty itself. The themeMode → theme
  mapping is **gone**, not merely deduplicated — it existed once per renderer and
  needed a test pinning the copies together, because drift between them showed up
  as `tstack config ghostty diff` reporting a phantom change forever.
  `ghostty.target()` returning None is now a **refusal** rather than a branch,
  which matters most on WSL: it used to resolve to the Windows install, and would
  otherwise now write to a `/mnt/c` path nothing on the machine reads while
  reporting success. And `status` runs a real syntax gate unconditionally, since
  the build with no working `+validate-config` is no longer a target.
  `tstack/ghostty.py` lost 30% of its lines; 11 tests went with the target.

  **This does not delete files on a machine that already had them.** The code
  that wrote `%LOCALAPPDATA%\ghostty\` is gone; whatever an earlier apply put
  there stays, unmanaged. A sync-side deletion would run on every machine — the
  same reason `tstack config ghostty off` was never a `.chezmoiremove` rule. To
  clean up, delete that directory by hand, once. The one trap worth keeping from
  the whole episode: **never treat `ghostty +show-config` as a validator**, on
  any build — it reports nothing for an unknown key or a bad value, so every
  "accepted" is meaningless.

### Added

- **The dashboard configures all of it now, not just the settings
  (08/28/2026).** Three settings were blind text boxes and one was a
  space-separated string, because their valid values are facts about the machine
  rather than a fixed list. A `Setting` now names a **provider** and
  `tstack/choices.py` is where one is asked: `options()` for what this machine
  can offer, `preview()` for what it looks like, `sample()` for what it sounds
  like. The CLI's probes moved behind that interface, so both front ends ask the
  same question.

  - `ccTtsKokoroVoice` / `ccTtsSayVoice` open a picker of the voices actually
    served, with `s` to hear one.
  - `starshipPreset` opens a picker that **renders each prompt** in a preview
    pane.
  - `apps` is a tick-list with `space`, `a` and `n`, saved in catalog order so
    the stored value is stable and diffable.
  - **AgentMemory's chat provider is editable too**, though it is not a saved
    setting at all: `OPENAI_BASE_URL` and `OPENAI_MODEL` live in the stack's
    `.env`. They appear as rows tagged with their own store, and a save routes
    to `tstack/llmconfig.py` rather than to the settings writer.

  `tstack agents llm set <url> <model>` and `tstack agents llm none` do the same
  from the command line. Clearing the endpoint clears the model and the labels
  with it -- the compose file defaults the labels to OpenAI, so a half-cleared
  provider names one the machine no longer has.

  Two traps the tests exist for. Escape needs a sentinel, because an unset
  `ccTtsSayVoice` **means** "the system voice" and `""` cannot also mean
  cancelled. And writing the `.env` normalises CRLF before matching and restores
  it after: a line-anchored `^KEY=.*$` swallows the `\r`, silently converting
  the one line it touched.

- **`tstack doctor` reports a prompt preset that is not the prompt you are
  running (08/28/2026).** `dot_config/starship.toml.tmpl` falls back to this
  stack's own prompt when starship is not on PATH — deliberately, because a
  bootstrap can render that template before starship is installed and chezmoi's
  `output` on a missing binary aborts the *entire* apply. The cost of that safety
  is a machine whose `starshipPreset` says one thing and whose prompt is another,
  with nothing anywhere reporting it.

  Silent on the default, which is the actual answer rather than a fallback. An
  unknown preset name is also flagged, because `starship preset <nonsense>`
  prints nothing and the rendered config would be **empty** — a working prompt
  replaced by no prompt.

- **`tstack ui` - every saved setting in one screen (08/27/2026).** The dashboard
  the revamp plan has carried as phase 8. It shows what each setting is, what its
  default is, and **which layer the value came from** - chezmoi `[data]`, the
  Windows mirror, or nothing at all. Those three look identical once a value is
  printed, which is the failure this whole schema exists for.

  Filtering searches the NOTE as well as the key, because the keys are camelCase
  internals nobody remembers: "ollama" finds `ccTtsSummarizer`. `Space` cycles a
  choice setting in place, `d` restores the default, and a derived key is listed
  and refused rather than hidden - knowing a value exists and is not yours to set
  is the point of showing it.

  It does not write the store. A dashboard is exactly the kind of thing that
  grows a second writer - it already has the key, the value and the path - so
  every save routes through `config.set_value`, the same function the command
  line uses, which is what keeps the validation, the chezmoi re-init and the
  DERIVED refusal identical in both front ends.

  Textual is the only third-party import in `tstack` and only this command uses
  it, so it is optional: `tstack ui` prints how to install it rather than raising
  ImportError. The rules live in `tstack/ui/model.py` (stdlib, 94% covered) and
  the Textual shell in `app.py` holds none of its own; `tests/test_ui_app.py`
  drives that shell headless through Textual's own `run_test()`, in a separate
  module because `importorskip` skips the file it is in and would otherwise have
  taken the fourteen stdlib-only tests with it.

- **kokoro natively on Apple Silicon, and a command that says which engine fits
  this Mac (08/27/2026).** There are three ways to get a voice on macOS and they
  are not interchangeable, so `tstack config tts engines` measures the machine
  (architecture, cores, memory, installed voices, and whether Docker, kokoro and
  mlx-audio are actually present) and **derives** a recommendation rather than
  carrying one.

  The deciding fact it exists to state: **Docker Desktop gives the container no
  GPU on Apple Silicon**, so the shipped kokoro image runs on the CPU a model the
  machine could run on its GPU. mlx-audio is that same Kokoro model running
  natively, and it speaks the same OpenAI protocol — `/v1/audio/speech` with
  model, voice, speed and response_format, plus `/v1/audio/voices` and
  `/v1/models`. Every field matched except one, which is why the whole port is a
  setting rather than a code path: the Docker image answers to the literal string
  `kokoro`, and mlx-audio wants the HuggingFace repo id and rejects anything else.

  `ccTtsKokoroModel` (default `kokoro`, `tstack config tts model kokoro <id>`) is
  now read by both hook libraries, the runtime config template and the Windows
  mirror. The voices endpoint gets `?model=` only when a model is configured —
  mlx-audio 400s without it, the container has no such parameter, and the default
  request must stay byte-for-byte the one that is known to work.

- **`tstack agents llm` — what a chat model switches on, and what runs without
  one (08/27/2026).** AgentMemory needs no LLM for storage, semantic search or
  embeddings; a chat model adds exactly four things (`compression`, `summary`,
  `graph`, `consolidation`) and the command names all four either way. It reads
  the stack's own `.env` — compose's authoritative interpolation source — so it
  is correct while the stack is **down**, which is when someone is most likely to
  be asking why nothing is being summarised.

  Two things it will not do. It never reports a host probe as container
  reachability: a container's DNS is Docker's embedded resolver and its egress a
  separate path, so the success line says so and names
  `tstack services test agentmemory` as the check that dials from inside. And an
  endpoint set with an empty `OPENAI_MODEL` is called out rather than ticked —
  `inferenceActive` is driven by the model, not the URL, so that configuration
  reads as done everywhere while every family stays off.

- **Local-runtime detection, printing the container's URL rather than the
  host's (08/27/2026).** With nothing configured, `tstack agents llm` probes
  Ollama (11434), LM Studio (1234), vLLM (8000) and llama.cpp (8080) and prints
  the two lines to paste for whichever answers. The URL it offers is
  `host.docker.internal`, never `localhost` — inside a container `localhost` is
  the container, and copying the host URL out of a browser lands squarely in the
  silent dead-letter state described below.

  `host.docker.internal` is free on Docker Desktop and does **not** exist on
  native Linux unless it is mapped, so `extra_hosts: host.docker.internal:
  host-gateway` is now on the agentmemory service. That makes the one printed URL
  correct on all three platforms; it is accepted and redundant on Desktop
  (verified against Docker Desktop on macOS).

- **`llmfit` in the app catalog, under a new `models` group (08/27/2026).**
  "Which model fits this machine" is the question standing between someone and a
  working LLM configuration, and it was answerable only by a KB page for a tool
  the installer never offered. brew on macOS, the release tarball on Debian/WSL
  (there is no apt package). Deliberately **not** in the `ai` group:
  `ts_app_is_ai` reads that group as the install *route*, so a packaged binary
  put there is handed to `ts_install_ai_cli`, which has no branch for it and
  prints "no agent-CLI installer defined" instead of installing anything.

  Absent from the Windows catalog. It ships a windows-msvc binary but is in no
  winget manifest, and that table takes verified ids only — the rule is "can this
  platform install it", never "is it in winget".

### Changed

- **`develop` is the default and integration branch; `main` is the protected
  release branch (08/28/2026).** Phase branches are cut from `develop` and merge
  back into it; `develop` reaches `main` only through a pull request with every
  CI check green. `main` also refuses force-pushes and deletion. Admins are
  exempt on purpose — a solo maintainer who locks themselves out has no second
  account to let them back in. `AGENTS.md` § Branches is the authority.
  `develop` was added to CI's push triggers, or the new integration branch would
  have had no CI on a direct push.

- **`tstack config` is the ported Python on POSIX (08/28/2026).** The row's two
  columns differ on purpose, which is what they are for. `apps`, `tts` and
  `reconfigure` are routed to `bootstrap/ts-config.sh` rather than reimplemented:
  they end in a package-manager install or the bootstrap's own save sequence, and
  REVAMP-PLAN.md lists the installer entry points as never ported. `mux`,
  `wezterm`, `ghostty` and `wizard` are handed to their ported commands
  in-process.

  **Windows stays on `Set-TerminalStackConfig` for now.** It is the most-used
  command in the stack and the delegation there needs a Windows machine to
  exercise; flipping it blind is how you find out on someone else's morning.

  `prompt` was ported on the way, so it is no longer shell either. Two
  divergences from the shell are recorded in the characterization harness rather
  than papered over: a usage error is exit 2 now, on every platform, where
  `ts-config.sh` returned 1 for an unknown verb and a missing argument.

  Fixed while flipping: `-h` anywhere in argv printed `config`'s own help, so
  `tstack config wizard -h` showed the wrong page. The shell forwarded it; the
  port now does too.

- **The install questionnaire is one implementation (08/28/2026).**
  `bootstrap/_wizard.sh` was 944 lines and the `Read-Ts*` half of
  `bootstrap/_config.ps1` about 800 more -- two implementations of the same
  fourteen questions, kept in agreement by hand and **already drifted**: the
  PowerShell tick-list rejected a whole multi-answer where bash applied the valid
  tokens and warned about the rest. Someone typing `1 3 9` at a six-row list
  means the first two, and throwing that away is how people stop reading menus.
  The bash behaviour is the one that survived.

  It is `tstack/wizard/` now, behind a `tstack wizard` command. What is left in
  the shell is a 50-line hand-off, because the four bootstraps are shell and need
  the answers as variables.

  **The answers travel in a file, not on stdout.** The wizard writes its menus to
  the terminal and its answers to a path the caller passed, so there is no `$( )`
  boundary for a stray line to corrupt -- the failure the bash version guarded
  against by routing every prompt to `/dev/tty`, now impossible by construction.
  Every variable is emitted unconditionally (the callers read some unguarded, and
  `set -u` aborts on a missing one), as `export` rather than assignment (the
  agent wiring reads them from a child process's environment), and the file is
  renamed into place so a crash cannot leave half of one to source. Windows gets
  the same answers as JSON, keyed by the PascalCase names the old hashtable used,
  so every `$w.X` downstream is unchanged.

  The behaviours that had to survive are pinned by tests rather than by reading:
  the three-try cap on a choice, the default returned verbatim and unvalidated
  (the prompt question depends on it), numbers splitting on space or comma
  without fusing `1 2` into `12`, and the exclusive-group collapse whose guard
  is why ticking Ghostty no longer unticks WezTerm.

- **The managed Ghostty config is one implementation instead of three
  (08/28/2026).** `bootstrap/ts-config.sh` covered macOS and the WSL view of the
  Windows side (~160 lines), `$PROFILE`'s `Set-TerminalStackConfig` covered
  native Windows (~90 more), and each carried its **own copy of the
  themeMode -> theme mapping** — a mapping that has to agree everywhere or
  `tstack ghostty diff` reports a phantom change, which is why a test existed to
  compare four copies of it against each other.

  Now `tstack/ghostty.py`, behind a new `tstack ghostty` command reached the way
  `mux` and `wezterm` already are; both shells hand off to it. The two sync
  scripts keep their own copy, because they run where Python may not be, so the
  comparison test stays — over three sources instead of five, and it now also
  asserts the shells did **not** grow one back.

  Two behaviour differences, both deliberate. WSL and native Windows resolve
  through `plat.local_app_data()`, so a combined machine targets one Ghostty (the
  Windows one) by construction rather than through two separate username lookups.
  And `diff` on macOS now says "up to date" instead of printing nothing — chezmoi
  is silent when there is nothing to change, and silence reads exactly like a
  diff that failed.

- **A fresh clone no longer ships a chat endpoint that resolves on one person's
  network (08/27/2026).** `services/stacks/agentmemory/.env.example` had
  `OPENAI_BASE_URL` and `OPENAI_MODEL` **active**, pointing at a private
  Tailscale host, and `tstack services bootstrap` copies that file verbatim. Of
  the three possible states that is the worst one: `ts-verify` treats an unset
  base URL as a supported skip and a set-but-unreachable one as a failure,
  because that is where every compression call returns empty, fails XML parsing,
  retries and dead-letters while the log line still reads `outcome:"success"`.
  52,570 jobs accumulated that way. Every clone but the author's booted into it.

  `services/.env.example`'s `OPENAI_API_KEY` placeholder is commented out for a
  related reason that is easier to miss: with a key set and no base URL the
  client falls back to `api.openai.com` and sends it there, while `ts-verify`
  still reports "skip" because it reads the container's `OPENAI_BASE_URL` and
  that is empty. The machine looks cleanly unconfigured while quietly 401ing
  against a service nobody chose.

  In their place the file names three provider shapes anyone can copy — any
  OpenAI-compatible server, Ollama (with the reminder that `localhost` inside a
  container is the container), and the OpenAI API — and points at `llmfit` for
  choosing a model. `LLM_PROVIDER_LABEL` / `LLM_ENDPOINT_LABEL` now say "none"
  rather than inheriting the compose default of "OpenAI"/"OpenAI API", which is
  wrong twice over on a machine with no provider. The compose *default* is
  unchanged on purpose: an unlabelled provider is assessed as paid, and
  over-reporting cost is the safe direction to be wrong in.

- **The agentmemory docs describe a provider you choose, not one you were given
  (08/27/2026).** `services/stacks/agentmemory/README.md`'s LLM section was a
  deployment record for one machine — "vLLM on <host> (current provider)", a
  table of its GPUs, a rollback path to the account it migrated from. A reader
  with an Ollama install and a question had nothing to copy.

  Rewritten as *Choosing a provider* (none / local runtime / another box /
  hosted, with what each costs and what bites), *Setting one* (the four values
  and the order they load in), and a switching table for moving between a
  ~16k local model and a large-context hosted one. Every hard-won failure
  analysis is kept — the truthy `reasoning_effort`, the chunk size that must
  track the context, the reflect stage that reports `success: true` with zero
  insights — reframed from "what happened here" to "what will happen to you".

  `services/.env.example` went the same way: the `VLLM_*` block was the author's
  endpoint record, read by nothing in the repo, and is replaced by the two things
  that actually go wrong when the endpoint is on another machine — host
  reachability is not container reachability, and prefer an IP to an overlay-DNS
  name.

  Also genericised in the same file: the embedding-provider warning and the
  reasoning-effort note were written against one specific vLLM deployment, and
  `LLM_HOST_BEARER_TOKEN` was a rollback credential for that host which nothing
  in the repo has ever read.

### Fixed

- **A test passed only because this machine had no runtime clone (08/28/2026).**
  `test_the_catalog_reader_survives_a_missing_file` pinned `TERMINAL_STACK_DIR`
  at an empty directory, which is a *stale* pin, not a partial clone — and a
  stale pin deliberately degrades rather than dead-ends, so resolution fell
  through to the candidate search and found whatever clone the machine had. That
  was nothing, until one was deployed to `~/.local/share/terminal-stack`; then
  the catalog resolved, the assertion failed, and the pre-push hook was blocked
  on the dev box while CI stayed green (CI has no runtime clone). The pin now
  names a real clone that lacks the file, which is what the docstring always
  claimed it was testing.


- **Every `modify_` script grew a `\r` per apply on a CRLF host (08/28/2026).**
  `sys.stdout.write` opens stdout in *text* mode, so each `\n` it writes becomes
  `\r\n`; the next apply reads those back, splits on `\n`, rejoins with `\n` and
  translates again. These scripts exist to be byte-preserving — `~/.zshenv` is
  part-owned, `settings.json` is written by Claude Code itself — and the bytes
  they write are part of that promise. All four apply-time writers
  (`modify_dot_zshenv.tmpl`, `dot_claude/modify_settings.json.tmpl`,
  `dot_codex/modify_private_terminal-stack.config.toml.tmpl` and the Windows sync
  hook's renderer) use `sys.stdout.buffer.write` now, pinned by a test, with a
  second test driving a CRLF `~/.zshenv` through two applies.

  Surfaced by `pytest (windows-latest)`, which is the only place native Windows
  runs — the idempotency test had been comparing a run against a
  differently-terminated one and blaming the transport.

- **`ghostty.binary()`'s WSL branch returned a host-flavoured path
  (08/28/2026).** `/mnt/c/Program Files/...` is POSIX by definition — it exists
  only inside WSL — and `str(Path(candidate))` re-renders it through whatever
  path flavour the running host uses, so it became `\mnt\c\...` the moment
  anything evaluated that branch on Windows.

- **`Get-TsConfigPath` threw on every non-Windows pwsh (08/28/2026).**
  `Join-Path $env:LOCALAPPDATA …` is a terminating error when that variable is
  unset, so dot-sourcing `_config.ps1` and calling `Get-TsConfig` died before
  returning anything on macOS and Linux. Found by running the strict-mode repro
  that `docs/powershell-quirks.md` gives for checking this exact class of bug —
  the repro itself failed. It returns `$null` there now, matching
  `tstack/store.py`'s `mirror_path`, and callers fall through to the defaults
  they already carry. Windows always sets the variable, so nothing changes there.

- **The `FileSystemWatcher` snippet in `docs/developing-wezterm.md` could never
  have run (08/28/2026).** `New-Object` has no `-PropertyName`, and
  `-IncludeSubdirectories` is a property of the watcher rather than a parameter,
  so the line threw before anything was watched; the `-Action` scriptblock also
  referenced outer variables it cannot see from the event runspace, so every
  change would have invoked `$null`. Rewritten, and verified by running it. Found
  by parsing every PowerShell block in the docs — which also caught a `$EDITOR
  .env` in a `powershell` fence in the agentmemory README.

- **`tstack services up <stack> --build` was documented and rejected
  (08/28/2026).** The agentmemory stack's README named it as the way to rebuild
  the console after editing `services/console/`; the parser answered `unknown
  option: --build`. Only two stacks here build an image from this repo's own
  source, and without it `up` reuses the image it already has, so the edit
  appears to have done nothing. Deliberately not wired into `test`, which proves
  a clean bring-up — rebuilding mid-proof changes what is being proved.

  Found by sweeping every `tstack <verb> --flag` in the docs against what the
  parsers accept, the same way the dangling-function sweep works.

- **The wizard port deleted three prompt primitives that six non-wizard callers
  used (08/28/2026).** Moving the install questionnaire into `tstack/wizard/`
  correctly deleted 21 bash prompt functions and the `Read-Ts*` half of
  `_config.ps1` — but `ts_prompt_choice`, `ts_tty_prompt` and `ts_is_interactive`
  were never questions. They are the primitives every *other* prompt in the stack
  is built from, and `wso` (six call sites), `tstack smb setup`, the rclone
  wizard, the TTS menu and `_cleanup.sh` all call them. Each died with `command
  not found` the moment it prompted. Five items of each `tstack config` menu —
  leader, theme, apps, session restore, and on Windows the re-run-wizard item —
  called questions that were likewise gone.

  Nothing caught it: bash resolves a function name at *call* time, `bash -n`
  checks syntax only, and PowerShell's parser is equally content with a command
  that does not exist. `tests/test_shell_symbols.py` now resolves every
  `ts_*` / `Read-Ts*` name statically, the way neither interpreter will, on both
  shells. It immediately found a second, older instance: a rename to
  `ts_smb_conn` had left one caller in `_smb_setup.sh` behind, so `tstack smb
  setup` died at the point where it asks the host for its share list.

  The primitives now live in `_config.sh` / `_config.ps1`, which every caller
  already sources — not with the questionnaire that moved. The menus ask their
  own single-setting questions (`menu_leader` / `$menuLeader`, and twins), with
  the same options the wizard offers but defaulting to whatever is currently
  *saved*: a menu's default is the value you already have.

- **`tstack config wizard` collected every answer and threw them away
  (08/28/2026).** It had been routed to `tstack wizard`, which only *asks* —
  that is what lets the four bootstraps each own their own save order. The
  variant under `config` is the one that also saves and installs, so it belongs
  with `apps` and `tts` on the delegated path, where the shell's `run_wizard`
  does the persisting. `-h` on any delegated verb is now answered in Python
  rather than forwarded: `ts-config.sh` dispatches on `$1` and ignores the rest,
  so `tstack config wizard -h` had been *running the installer*.

- **`Save-TsWorkspaceOverride $w.Workspace` on the `$PROFILE` wizard path
  (08/28/2026).** The workspace root is not a wizard question and the emitted
  JSON never carried the key, so the read was `$null` and an empty
  `WORKSPACE_DIR` was persisted over a real one. Both callers now go through one
  `Invoke-TsWizard`, which is also what stops the two copies drifting again.

### Fixed

- **A Windows-side save silently deleted `starshipPreset` and `atuinEnabled`
  (08/27/2026).** `Save-TsConfig` rebuilds config.json from a fixed set of
  properties, so a key missing from that set is dropped on any save - the same
  failure its own `ccTts` comment warns about, one level up. `atuinEnabled` has
  had this hole since it was added and has no pwsh consumer, so nothing showed;
  `starshipPreset` decides which prompt the Windows sync deploys, so losing it
  would visibly revert the prompt. Both are now parameters, carried forward when
  the caller does not pass them.

- **Windows had no synthesis floor, so "on" could still mean silence
  (08/28/2026).** `Invoke-CcTtsSynth`'s ladder ended at edge-tts and returned
  `$false`: a native-Windows host with the daemon off, kokoro down and edge-tts
  not installed produced nothing at all. That is the same gap `/usr/bin/say`
  closed on macOS in August, left open on the platform this stack started on.

  SAPI is the floor now, and it **speaks** rather than synthesising to a file.
  The Windows playback path is `cc-tts-play.ps1`, which requires `ffplay` and
  errors without it -- so a file-based floor would still be silent on exactly the
  machine that needs one. SAPI is part of Windows and needs neither a file nor a
  player. The daemon has done this since it shipped; this is the same rung for
  the hook path, which is what runs when the daemon is off. Both early returns in
  `Start-SpeakWorker` now reach it, and it cannot throw: the alternative is
  silence, so a failure must leave things no worse.

  **Not verified on Windows.** The COM call cannot run on the development Mac;
  the change is parse-checked, pinned by a test, and structured so its worst case
  is the silence it replaces. CI covers the rest.

- **The one line explaining a voice change went to a discarded stream.**
  `cc_tts_say_notice` printed to stderr, and `cc-tts-notify.sh` runs the worker
  as `( _worker ) >/dev/null 2>&1 &` -- so the message that answers "why is it
  speaking in a different voice" was written where nobody could read it, every
  time. The reason now goes into the dated sentinel file the notice already
  wrote, and `tstack config tts` reports it. Still once a day: the point is to
  explain a change, not narrate every announcement.

### Added

- **`say` is a real engine, and voices can be listed and heard (08/28/2026).**
  macOS's `say` was the floor of the ladder and nothing else: not a legal
  `ccTtsEngine` value, and no way to pick which of the machine's 184 voices it
  used -- it passed no `-v` at all, so it always spoke the system default. It is
  now selectable, with `ccTtsSayVoice` beside it, refused off Darwin at set time
  rather than saved as a choice that can never take effect.

  Choosing it is distinguishable from falling back to it, which matters for two
  reasons: the once-a-day "using the system voice" notice explains an
  *unexpected* fallback and would otherwise nag about a decision already made,
  and the log line should say which of the two happened. The floor is unchanged
  -- `say` stays last in the fallback chain, and the test that pinned that now
  scopes itself to the chain rather than the whole function.

  `tstack config tts voices` lists what the ACTIVE engine can produce, and
  `voices <name>` plays a sample. Both ask the engine: kokoro over
  `GET /v1/audio/voices`, which nothing in this repo had ever called, and macOS
  with `say -v '?'`. No list is checked in -- kokoro ships 68 and the set moves
  with the image, and a Mac has 184 with more downloadable, so a table here would
  be wrong on somebody's machine the week it was written. When the saved engine
  is kokoro but the container is down, the macOS list is shown instead.

  `voices` previously set the daemon's per-session rotation pool -- unrelated to
  picking a voice, and read only by the Windows daemon. That is `voice-pool`
  now. The old comma-separated form is redirected with the new spelling rather
  than silently honoured; a voice name never contains a comma, so the two stay
  distinguishable.

### Fixed

- **A backup of a SOURCE file became a permanent managed target (08/28/2026).**
  `.gitignore` carries `*.bak.*`, so a `dot_zshrc.bak.20260827204438` sitting in
  the chezmoi source tree is invisible to `git status` -- and therefore to
  `tstack update`'s dirty-clone refusal and to `run_before_05`, both of which
  read it. `.chezmoiignore` had no matching rule, so chezmoi treated it as a
  source entry and the next apply would have written
  `~/.zshrc.bak.20260827204438` into `$HOME`, and kept writing it forever. Same
  `$HOME`-pollution trap as `tests/**` and `services/**`, arriving by a different
  door: not a file someone added, but one a backup helper left behind. Found by
  reading `chezmoi status` before an apply, not by a test.

- **The managed gitconfig's header had its own precedence backwards.** It claimed
  user settings "always win, since includes resolve first". The bootstrap adds
  the include with `git config --global --add`, which **appends**, so the
  included file resolves LAST and its values win over anything set earlier in
  `~/.gitconfig`. Verified both orders. `user.name` and `user.email` are
  unaffected only because nothing in the included file sets them -- not because
  of ordering. Corrected in the canonical copy and its byte-identical Windows
  mirror.

### Added

- **AGENTMEMORY_SECRET now reaches the processes that need it (08/28/2026).**
  The plugin's MCP clients expand `${AGENTMEMORY_SECRET}` from the environment.
  Nothing set it on macOS -- there is no `HKCU\Environment` equivalent -- so
  every MCP tool answered 401, silently, because retrieval discards a non-2xx
  response. The hooks self-healed from the 0600 cache; the MCP server has no such
  recovery.

  Two carriers, because the three consumers reach differently. A spliced
  `~/.zshenv` block covers terminal agents **and hook subprocesses**, which is
  the reason it is `.zshenv` and not `.zshrc`: hooks are non-interactive, zsh
  never sources `.zshrc` for them, and a variable exported there reaches nothing
  and logs nothing. A `~/Library/LaunchAgents` plist covers GUI Cursor and Codex
  Desktop, which are launched by launchd and read no shell file at all;
  `launchctl setenv` alone is session-scoped and evaporates at logout, so the job
  runs at every login.

  `~/.zshenv` is **spliced, not owned**. It is where rustup writes
  `. "$HOME/.cargo/env"`, where nvm and pyenv write their shims, and where a
  person puts the one export they need everywhere -- a whole-file target would
  delete all of it with no error and nothing in `chezmoi diff`, which is the
  failure that removed every Claude TTS hook and emptied `~/.cursor/hooks.json`.

  Both carriers READ the cache rather than embedding the value: the secret
  rotates with the container's `/data/.hmac`, and a hardcoded copy works until it
  does not and then 401s with the error swallowed -- 56 consecutive captures were
  lost that way on 2026-08-21. `check-capture.sh`'s fixed-string scan now covers
  both, since they were the obvious place for a future "just inline it" change
  and were unscanned.

  The block reads with `$(<file)`, a zsh builtin: `.zshenv` runs for every zsh
  including every hook subprocess, and `$(cat file)` would be a process per
  shell. Both carriers are removed when `agentmemoryEnabled` is off, and the
  `.chezmoiignore` gates name the directory as well as its contents -- naming
  only `Library/**` still creates an empty `~/Library/LaunchAgents` on machines
  that opted out.

### Fixed

- **`chezmoi_data()` read 19 of the 59 saved keys (08/28/2026).** `DATA_KEYS` was
  a hand-maintained tuple -- a FOURTH parallel key list beside
  `.chezmoi.toml.tmpl`, `TS_MIRROR_DATA_KEYS` and the mirror heredoc -- and it
  omitted `apps`, all four derived bindings and 37 of the 41 `ccTts*` keys. Those
  keys were simply invisible to Python: `store.get("apps")` returned `""` on a
  machine whose `chezmoi.toml` lists 47 apps, and `schema.source_of()` reported
  `default` for values that were plainly saved -- the exact "right value for the
  wrong reason" the schema exists to make visible, in the one field added to make
  it visible. It now derives from `schema.SETTINGS`.

  Two things fell out of actually reading those keys. A TOML **array** needs
  `range`, not `index`: Go renders a slice as `[a b c]`, brackets included, so
  `apps` arrived as the literal string `"[tmux eza ...]"`. And the branch has to
  test the VALUE's kind, not the schema's -- `ccTtsEvents` and `ccTtsVoicePool`
  are `kind="list"` but are stored as comma-separated STRINGS, and `range` over a
  string makes chezmoi reject the whole template, so one wrong key returned
  nothing for all 59 and every value fell back to its default.

- **The commit gate reported "NOT RUN" for every gate and exited 0 (08/28/2026).**
  Both hooks probed for their tools with `python3 -c "import <tool>"` only, which
  is the one shape this stack does not produce: `TS_APPS_RECOMMENDED` installs
  `ruff` and `uv` as formulae, and `ruff` has no importable module at all. So on
  a machine the stack itself provisioned, `pre-commit` printed NOT RUN four times
  and exited 0 - the precise failure its own header warns about ("a gate you
  believe is running and is not is worse than no gate"), one level up.

  `.githooks/_gates.sh` now resolves a tool three ways - importable module, binary
  on PATH, then `uvx` - and both hooks share it rather than each carrying a copy.
  It also answers whether the chosen runner puts the working directory on
  `sys.path`, because `uvx pytest` does not and `tests/` has no `__init__.py`
  while its modules import each other, so collection failed outright.
  `tests/test_githooks.py` pins all three shapes; verified the shape-2 test fails
  against the old probe. Measured: the gate now runs in about 15 seconds here.

- **`tstack doctor`'s git-hooks check could never fire.** It keyed off the
  RESOLVED clone, and `resolve_source_dir()` refuses to return a dev clone by
  design - dev trees are deliberately invisible so `tstack update` cannot pull
  one. `is_dev_clone(src)` was therefore false by construction on any machine
  with a runtime clone, and the check returned early every time. Its existing
  tests could not see this: they pass a dev clone straight in, exercising the
  body without the reachability. It now asks `paths.dev_clone_at()` - the git
  toplevel of the working directory - which is where a developer actually is, and
  a new test pins the reachability rather than the body.

- **The `[Unreleased]` heading, dropped by the previous commit.** Its CHANGELOG
  edit anchored on the heading and did not re-emit it, so the entries below sat
  under no version at all.

- **Every nested TTS key read the wrong place in the Windows mirror (08/28/2026).**
  The two stores spell the TTS block differently on purpose - chezmoi `[data]` is
  flat (`ccTtsKokoroVoice`), the mirror nests (`ccTts.kokoro.voice`) because the
  daemon reads that file too - and `mirror_key` derived the nested name by
  lowercasing one character, producing `ccTts.kokoroVoice`. That path does not
  exist, so the lookup MISSED and fell through to the shipped default: on a
  Windows-standalone install every voice, URL, template, timeout and summarizer
  setting read back as the default with nothing reporting a problem. The same
  class of bug as the one `mirror_key` was written to fix, one level deeper.

  The path now lives on the setting itself, so there is one declaration rather
  than a lookup table beside a derivation rule. `tests/test_store.py` asserts the
  schema's path is the one `get` reads through, for every key that declares one.

- **`tstack config tts engine` advertised a value it would refuse.** The new
  schema listed `kokoro`, `chatterbox`, `edge`; the setter accepts `kokoro`,
  `chatterbox`, `auto`, and so do `docs/kb/common/tts.md` and the daemon's own
  schema. `edge-tts` is a fallback rung, never a choice. Third copy of an enum,
  and the only one that was wrong.

### Added

- **`tstack config`, phase II: the module, not yet the entry point (08/28/2026).**
  `tstack/commands/config.py` implements `show` (prose, byte-identical to the
  shell's, verified by diff), `show --json`, `get`, `set`, `leader`, `theme`,
  `tmux`, `restore`, `atuin`, `memory` and `agents`. `apps`, `ghostty`, `tts` and
  `wizard` stay with the shell for now.

  The registry row is deliberately NOT flipped. Both columns flip together, and a
  Python `config` that shelled out to `bootstrap/ts-config.sh` for its un-ported
  verbs would leave Windows -- which has no bash -- with no implementation at
  all. Half a subcommand cannot route.

  Three behaviours differ from the shell on purpose:

  - **argv is validated before the clone is resolved.** `tstack config theme`
    is a usage error whether or not a clone exists. The two already-ported
    comparators disagree on this (`mux` checks argv first, `services` does not),
    so it is now pinned by a test.
  - **`agents agentmemory on|off` is refused in both directions.** The shell
    guarded only `on`, so `off` wrote the DERIVED `agentmemoryEnabled` directly
    and produced the exact `memoryBackend=agentmemory` / `agentmemoryEnabled=off`
    pair `tstack doctor` reports as drift.
  - **`agents playwright` is routed.** The shell advertised it in its usage
    string and had working branches for it, but the dispatch never reached them,
    so the advertised command answered `unknown tool 'playwright'`.

  Also: `show`'s ghostty row now prints wherever the Ghostty config path resolves
  (macOS, WSL, Windows) rather than on Darwin alone, and `config atuin` works on
  Windows -- it sets the key and says it affects WSL shells only, because the
  pwsh save never wrote `atuinEnabled` and so STRIPPED it from the mirror.

  One deliberate byte difference: `==> applying...` uses three periods where the
  shell uses U+2026. `tests/test_tstack_cli.py` forbids non-ASCII anywhere under
  `tstack/` because a Windows console on codepage 437 renders it as a
  replacement glyph, and that gate is enforced where the shell's byte is not.

- **The settings schema now covers all 41 `ccTts*` keys (08/28/2026).**
  It carried three. The rest were reachable only through the shell, which is why
  the mirror bug above could not be seen from Python at all. Each declares its
  type, allowed values, default, group and mirror path, so `tstack config show`
  and the future dashboard describe the whole TTS surface from one place.

  `store.defaults()` is now built FROM the schema instead of a second literal
  table, and the test that guarded those two against each other has been
  repointed at the drift that can still happen: Python against `ts_cc_tts_default`
  in `bootstrap/_cc_tts.sh`, which is still what the shell TTS path reads. Also
  corrects a count repeated through the docs - the daemon has 72 runtime fields
  and chezmoi has 41 `ccTts*` keys; "43" was neither.

- **The macOS regression fixes, carried forward into the Python (08/27/2026).**
  `e969c30f` landed on `main` while the `tstack` port was in flight, fixing four
  regressions that ran on every non-Windows host - and three of the files it fixed
  are files the port had deleted. Resolving the merge as "deleted wins" would have
  dropped those fixes silently, so the *rules* moved instead:

  - **The doctor no longer believes `--check`'s exit code.** Every host gates on
    its agentmemory plugin cache and returns 0 when there is none, so a machine
    with no plugin at all reported `ok wiring intact` while capturing nothing.
    `tstack doctor` now asks that question first and reports the third outcome:
    *enabled but not installed for any agent - nothing captures*.
  - **`tstack services bootstrap` seeds kokoro for THIS machine.** kokoro's
    `.env.example` ships Profile A (Blackwell, CUDA 12.8) uncommented, and seeding
    was a blind copy - so a Mac or a 40-series box got a cu128 image and the NVIDIA
    device reservation, and `up` failed on "could not select device driver" after
    pulling several GB. `stacks.gpu_profile()` is the one implementation of the
    detection, keeping the darwin branch the pwsh twin never had: Docker Desktop
    for Mac has no passthrough of any kind, so C is the only profile that can run
    there and `nvidia-smi` is never probed.

  Every upstream change to a file that still exists was taken as-is: `ts_timeout`,
  the 0600 secret-cache reader, `ts_smb_timeout` delegating, the wizard keeping a
  saved app selection and no longer resetting `tmuxPrefix`, `ts_memory_apply` in
  all four save paths, and `-MemoryBackend` on the Windows `Save-TsConfig` calls.

- **Every caller of the deleted twins repointed (08/26/2026).**
  Four executable call sites still ran `bootstrap/ts-agents.ps1` after it was
  deleted: `windows-bootstrap.ps1`'s post-wizard wiring, `sync-windows.ps1`'s and
  `run_after_90-sync-windows.sh`'s reconciliation on every update, and `$PROFILE`'s
  `tstack config agents`. All four now run `tstack agents` through the same Python
  entry point, and the WSL one still crosses to the WINDOWS side deliberately -
  that is where the GUI agents and their configuration live, so a Linux
  interpreter would edit files in the WSL home that nothing reads.

- **`tstack agents` is Python (08/26/2026).**
  `bootstrap/ts-agents.sh` (359 lines) and `bootstrap/ts-agents.ps1` (431) are
  deleted; `tstack/commands/agents.py` is the one implementation. The merge takes
  the **union**, because the two had drifted: the pwsh status checked the Claude
  plugin list, the global skill file, the AgentMemory viewer and a TCP fallback,
  and the bash status checked none of them, while the bash status was the one that
  probed AgentMemory with a plain request rather than `curl -fsS` - that service
  answers 404 on `/` and 401 on `/health`, so the strict form reported it down
  while it was up. Both behaviours now apply everywhere.

  **The WSL handoff is now a re-exec of the same program.** On a combined install
  the GUI agents and their configuration are Windows-side: `~/.claude.json`,
  `~/.cursor/mcp.json` and the Codex home belong to Windows processes. The bash
  twin handled that by re-exec'ing the pwsh twin, which is exactly where the two
  were free to drift; it now re-execs itself under the Windows Python, and
  `user_root()` names the boundary explicitly so a registration cannot land in the
  WSL home where nothing reads it.

  Rules that were comments are tests now: a failed MCP `initialize` handshake
  REMOVES stale registrations rather than leaving a command no client can run; a
  Cursor `mcp.json` that will not parse is never overwritten; every rewrite takes a
  dated backup that never clobbers a same-day one; the proxy token is never
  printed; and `uninstall` always passes `--keep-data`.

- **Parity containers now mirror a clean checkout (08/26/2026).**
  `tests/parity/run.sh` copied the working tree verbatim, which inherited the
  developer's *untracked* files - `services/stacks/*/.env` among them. A test that
  read the live tree therefore passed in the container and failed on every CI
  runner, which is exactly the "only green on an already-installed machine" class
  the harness exists to catch. The copy now deletes everything git ignores, so
  uncommitted *tracked* changes are still what gets tested and nothing else is.

  Found by CI on the first commit after the harness landed: 4 stack `.env` files
  before, 0 after.

- **`tstack wezterm` is Python (08/26/2026).**
  `bootstrap/ts-wezterm.sh` (90 lines) is deleted and `bootstrap/_wezterm.sh` drops
  from 446 lines to 66 shims. That file was already half Python: five of its
  functions existed only to pipe JSON into an embedded `python3 -c` heredoc, with
  `PYTHONIOENCODING=utf-8` forced because WezTerm's changelog is full of
  box-drawing characters and Windows defaults stdout to cp1252. All of it now
  lives in `tstack/commands/wezterm.py`, once.

  The shims stay because the installers (`_wizard.sh`, `mac-bootstrap.sh`,
  `_common-debian.sh`) source that file before the package is on any path they
  know about. They hold no logic: each is a wrapper over a machine-readable verb
  (`channel`, `installed`, `update-available`, `intro`, `terminals-channel`) that
  is deliberately silent when there is no answer, because every caller treats
  empty as "nothing to say" and none of them may fail a shell mid-install.

  Every rule the four shell tests enforced is kept and now driven rather than
  grepped: the build date comes out of the release name with no network call, the
  changelog slice is counted against the saved fixture, no network degrades to
  version-and-date, and a channel switch removes the other package in BOTH
  directions - plus the one that was only a comment, that a hand-placed binary
  (channel `unknown`) is never replaced or upgraded.

- **`tstack mux` is Python (08/25/2026).**
  `bootstrap/ts-mux.sh` (301 lines) and `Invoke-TsMux` in `$PROFILE` (197) are
  deleted; `tstack/commands/mux.py` is the one implementation. The WSL interop
  rule survives with a test rather than a comment: the mux server is a Windows
  process, so pids come from `tasklist.exe` and not `pgrep`, which finds nothing
  inside WSL while a healthy server runs on the same machine. So does the rule
  that nothing here ever auto-restarts the server - a refused confirmation now
  stops `restart` outright instead of killing and then starting.

  `tstack config mux ...` on both sides hands off to it. On Windows that goes
  through a new `Invoke-TstackSub`, which is how a `$PROFILE` function calls a
  ported subcommand: the user-facing shim is for what someone types, and one
  stack function calling another should not go through argument re-parsing.

- **`tstack services` is one Python program (08/25/2026).**
  `bootstrap/ts-stack.sh` (635 lines) and `bootstrap/ts-stack.ps1` (897) are
  deleted, along with 508 lines of `services/_stack.sh` that only they called.
  What replaces them is `tstack/commands/services.py`, `tstack/stacks.py` and
  `tstack/engine.py` - one implementation of twelve verbs, on all four platforms.
  `services/_stack.sh` keeps everything each stack's own `ts-verify.sh` uses; the
  scripts *inside* the service tree still exist twice, deliberately.

  Two bugs fall out of the merge rather than out of anyone noticing them.

  **kokoro was never reported as off on macOS or Linux.** The bash twin asked for
  `enabled` and `engine`, where the keys are `ccTtsEnabled` and `ccTtsEngine`, so
  the lookup always missed, fell through to a default branch that runs the bare
  word `1` as a command, and the `|| echo true` guard turned that failure into
  "TTS is on with kokoro". The pwsh twin read the real values, so the two
  disagreed on every machine with voice notifications off - and the parity test
  passed throughout, because it checked that both files contained the string
  `ccTts`.

  **The WSL handoff is gone.** The bash twin re-exec'd the pwsh twin through
  interop for five of the twelve verbs, gave up entirely on a machine with no
  pwsh 7, and left the other seven running against Docker Desktop's stub. There
  is nothing to hand off to now: the same process runs `docker.exe` through
  interop. The path constraint that motivated the handoff is stated instead of
  side-stepped - a stack tree a Windows engine cannot bind-mount is refused
  *before* anything is torn down, naming the fix.

  Exit codes are consistent for the first time: 0 healthy, 1 problems found, 2 the
  command line was wrong. The same mistake used to exit 2 through Git Bash and 1
  through the WSL handoff.

- **Parity containers: the suite on a real Linux, in two seconds (08/25/2026).**
  `tests/parity/run.sh` runs the whole suite inside Debian 13, Ubuntu 24.04 and
  Ubuntu 22.04 containers, against each distro's *own* Python, bash and zsh, plus a
  `bash32` target that syntax-checks `services/**` under the bash 3.2 that macOS
  ships as `/bin/bash`. WSL is not native Linux for this repo: `/mnt/c` exists,
  interop exists, and `tstack/platform.py` reports `wsl` rather than `linux` on
  purpose, so every native-Linux branch was previously exercised only by CI - a
  slow loop nobody watches while writing the code. These run in about two seconds.

  It found a real break on its first run. Ubuntu 22.04 - an LTS still in support -
  ships Python 3.10, where `tomllib` does not exist, and
  `tests/test_codex_dashboard.py` imported it at module scope. That failed
  *collection* of the entire suite, not one file. Nothing else could see it: CI
  uses 3.12, WSL has 3.14 and Windows has 3.14. The file now skips itself rather
  than raising the stack's floor to 3.11 and dropping a supported LTS.

  macOS cannot be added and is not pretended at: containers share the host kernel,
  so Darwin cannot be containerised. `bash32` covers the part of macOS that
  actually bites here, and only for syntax - the locale-dependent multibyte
  `set -u` trap does **not** reproduce under musl (verified, not assumed) and stays
  covered by the test that greps for `$var` followed by a non-ASCII byte. The same
  three distros plus `bash32` are now CI jobs.

- **The settings schema, and one writer for the config store (08/26/2026).**
  `tstack/schema.py` says what every saved setting *is* - kind, allowed values, default,
  which group it belongs to, and **which layer supplied its current value**. That last
  column is the point: a key can come from chezmoi `[data]`, from the Windows
  `config.json` mirror, or from nothing, and those three look identical once the value is
  printed. Modelled on `ttsd/settings_schema.py`, which already does this for the 43 TTS
  keys and is the reason its dashboard can be trusted.

  Derived keys are marked and refuse to be written. `leaderKey`, `leaderMods`,
  `tmuxPrefixResolved` and `resolvedTheme` are regenerated by `chezmoi init` from the keys
  actually chosen, so a direct write survives until the next save and then vanishes.
  `agentmemoryEnabled` is derived from `memoryBackend` for the same reason.

  `tstack/store.py` gains the write side, and it is the **only** writer. Writes are atomic
  (temp file plus replace - a half-written `chezmoi.toml` stops chezmoi running at all,
  which takes out every command including the doctor that would have explained it),
  preserve unrelated content such as `sourceDir` and `[edit]`, invalidate the read cache,
  and raise rather than report a success that changed nothing.

  It also handles the platform the read side quietly ignored: a **Windows-standalone**
  install has no chezmoi, `sync-windows.ps1` renders from `config.json`, and nothing ever
  reads a `chezmoi.toml`. Writing `[data]` there would have created a file no code path
  consults. Writes now route to the mirror on that platform, preserving unknown keys and
  refusing to overwrite a mirror that will not parse.

  No registry row flips: `tstack config` still routes to the shell, because a row is
  per-subcommand and `config` also serves `leader`, `theme`, `apps`, `tts` and `wizard`.
  See `REVAMP-PLAN.md` § Status for why the phase boundary sits here.

  Coverage floor 78% -> 80%.

- **`tstack doctor` is Python, and runs the same checks everywhere (08/25/2026).** The first
  subsystem ported off the shell twins. `bootstrap/ts-doctor.sh` and `bootstrap/_doctor.sh`
  are deleted, and `Invoke-TsDoctor` / `Test-TerminalStack` / `Repair-TerminalStack` are gone
  from `$PROFILE`.

  The two implementations had drifted a long way apart: bash ran about twenty checks, pwsh
  about eight, and neither knew what the other looked at. Windows never checked the config
  stores for divergence, the memory-backend derivation, SMB mount records, or the agentmemory
  hook wiring. It does now, because there is one implementation.

  `--json` emits one record per check (id, status, message, hint), so the checks are a read
  model rather than prose to scrape. `--quiet` prints nothing at all on a healthy machine.
  Exit status is unchanged: 0 healthy, 1 issues found.

  Three bugs the characterization recording exposed, all fixed in the port:
  - `ts_chezmoi_bin` returned `$TERMINAL_STACK_CHEZMOI` unchecked, so a pin at a path with no
    binary was reported as `ok  chezmoi: <path>`.
  - The bash doctor resolved the clone through `chezmoi source-path` **alone**, so a machine
    with a valid `TERMINAL_STACK_DIR` pin and a broken chezmoi reported "no source dir" while
    every other command in the stack honoured the pin.
  - The daemon probe only tried `127.0.0.1`. On WSL the TTS daemon is a *Windows* process and
    WSL2's loopback is the VM's, so a healthy daemon read as dead under NAT networking. The
    port walks the same host ladder the hooks already used.

  A false positive was removed too: the `chezmoi source-path` check is POSIX-only, because on
  Windows the apply path is `scripts/sync-windows.ps1` and chezmoi is usually present only
  because winget installed it, pointing somewhere unrelated.

- **Failure-path tests for the doctor.** The branches that only run when something is
  already wrong -- an unreachable service, a probe whose binary is missing, a subprocess
  timeout, a stale pin, a clone that is not ours -- are exactly the ones a live run on a
  healthy machine never reaches. Coverage floor 74% -> 78%.

- **Characterization fixtures (`tests/characterize/`).** What the shell did, recorded before it
  was replaced, replayed against the port. Deliberate divergences need a written reason, and a
  test rejects a reason too thin to review. Fixtures carry the platform they represent and are
  only replayed there; host-dependent lines are filtered, so nothing personal reaches a tracked
  file and a fixture recorded on one machine still passes on another.

- **One command: `tstack` (08/25/2026).** The eight `ts-*` commands are replaced by a
  single entry point with subcommands: `tstack config`, `doctor`, `update`, `rollback`,
  `mux`, `services`, `smb`, `wezterm`, `agents`, `agentmemory`, `doc`. **No `ts-*` name
  survives and no alias is provided**, in either shell.

  Routing lives in `tstack/commands.conf`, a whitespace-delimited table read by four
  consumers: `tstack/registry.py`, the `tstack()` shim in `dot_zshrc`, `Invoke-Tstack` in
  `$PROFILE`, and the completion providers (the first in this repo). Help is rendered by
  `tstack/cli.py` and nowhere else, so the bash and pwsh help texts are identical by
  construction rather than by the manual pty diff.

  Nothing was reimplemented: every subcommand still routes to the shell that implements it
  today. Flipping a row to `python` is what ports a subsystem, and that is the whole
  mechanism for the rest of the work in `REVAMP-PLAN.md`.

- **Python core, gates and CI.** New `tstack/` package (dispatcher, registry, clone
  resolution, platform detection), `pyproject.toml` (ruff, mypy, pytest, branch coverage
  with a ratcheted floor), `.github/workflows/ci.yml` covering ubuntu, macos, windows
  **and WSL**, and a `.githooks/pre-push` full gate beside the existing pre-commit one.

### Fixed

- **The doctor's agentmemory secret check, which the port had dropped (08/27/2026).**
  The shell doctor compared the container's `/data/.hmac` against the value a hook
  would recover to; `tstack doctor` did not carry it over at all, so a stale secret
  - which 401s every request while both capture and retrieval swallow the error -
  had nothing watching for it. CLAUDE.md said the check existed. It does now.

  In the hardened form upstream gave it: the `cmd.exe` read is gated on the
  Windows side existing (it is 127 everywhere else), Unix reads the 0600 cache
  instead because there is no `HKCU\Environment` there, a group-readable cache is
  refused, every probe is bounded, a dead Docker is silence rather than a verdict,
  and neither value is ever printed.

- **`replace_in_file` called a correct file a broken one (08/27/2026).**
  It reported "the pattern matched nothing" whenever the text came back unchanged,
  so seeding kokoro on a Blackwell box - where the shipped example already carries
  the profile that machine needs - warned *no COMPOSE_FILE line to set* about a
  file that was perfectly correct. Both shell implementations had the same
  conflation (node exits 3 for "unchanged"). It now distinguishes matched from
  changed.

- **The Windows mirror nests the TTS block, and the reader did not know (08/26/2026).**
  chezmoi `[data]` is flat (`ccTtsEnabled`); `config.json` nests (`ccTts.enabled`),
  because the TTS daemon reads that file too and wants it structured. `store.get`
  looked the flat name up in the mirror, missed, and fell through to the default -
  so on Windows `tstack services status` reported *"kokoro running, but voice
  notifications are off"* on a machine with voice notifications very much on.

  `store.mirror_key` now maps between the two shapes, using `DIVERGENCE_PAIRS` as
  the explicit table so the reader and the divergence check cannot disagree about
  where a value lives, plus a general `ccTts*` rule for the keys that table does
  not name.

  Found by running the commands through the **pwsh shim** rather than by a test:
  every test in the suite injects a store, so none of them could see it. The new
  test uses the real reader against a real mirror file.

- **Two tests hung forever on Linux and nowhere else.** `ts_prompt_multi` reads from
  `/dev/tty`, not stdin, so `stdin=DEVNULL` did nothing: wherever a controlling terminal
  exists the prompt blocked without limit. It does under WSL and does not under Git Bash,
  so the suite passed on Windows and stalled on Linux with no failure to read. Every test
  subprocess is now detached with `start_new_session=True` and carries a `timeout=`, both
  enforced by a lint. A hang is worse than a failure: locally it reads as slowness, and in
  CI as an unattributed timeout.

- **Two tests only passed on an already-installed machine.** The first CI run this repo
  has ever had found both on all four targets: one required a gitignored `.env` that
  `tstack services bootstrap` creates, the other assumed a clone is always resolvable
  (a CI checkout lives at a path the candidate list deliberately excludes).

- **`ts-stack` had been broken on Windows since `54da056`.** `$PROFILE:1705` held a literal
  TAB byte where a backslash-t was intended, inside a single-quoted string, so `Join-Path` produced
  `<src>\bootstrap\<TAB>s-stack.ps1`, `Test-Path` failed, and every invocation printed
  "not found; run ts-update". A lint now fails on any literal TAB inside a single-quoted
  PowerShell string.

- **The only automated gate had never run.** `.githooks/pre-commit` said it was "installed
  by `bootstrap.sh --apply` / `bootstrap.ps1 -Apply`". Neither file has ever existed here,
  nothing set `core.hooksPath`, and it was unset in every clone. `ts_install_git_hooks` /
  `Install-TsGitHooks` now set it, all three bash bootstraps call it, and a test asserts
  both. This is why the TAB byte survived and why `services/console`'s suite stayed red.

- **Argument splatting dropped the leading dash.** `tstack services -h` reached
  `ts-stack.ps1` as two arguments, `-` and `h`, reporting "no stack named 'h'". An `if`
  used as an expression unrolls a single-element array to a scalar, and splatting a scalar
  string beginning with `-` re-parses it as a parameter token; with no tail it splatted one
  empty string. Both parse cleanly and fail silently. Fixed with `@()`, pinned by a test.

- **Claims that nothing enforced.** `ts-mux` and `wso` `-h` were documented as
  byte-identical between their twins with nothing comparing them; `Test-TsAppInstallable`
  was unpinned while its bash twin was pinned twice; "never pipe `Where-Object` into
  `Set-Content`" was prose only. All four are now tests. `CLAUDE.md`'s opening claim that
  there is "no build, no test suite, no lint" was false in three ways and contradicted
  nineteen lines later. Full list in `docs/decisions.md` § "The claims audit".

- **Tests that would have gone vacuous.** The chezmoi/Docker boundary test asserted that
  `docker compose` appears nowhere in `bootstrap/ts-agents.{sh,ps1}` — an assertion that
  passes forever once those files are deleted. It now resolves its targets through
  `tstack/commands.conf`, and `repo_file()` makes any "string X must appear in file Y" test
  fail loudly when Y is missing.

- **`check-capture.sh` probed for a command that never existed.** `command -v
  ts-agentmemory` led its candidate list; there has never been an executable by that name,
  so it matched nothing on every host, silently. Its `fail` branch also claimed no `.sh`
  twin exists, which stopped being true some time ago.

### Changed

- **Codex now speaks clarifying questions (08/25/2026).** Enhanced Codex profiles register an asynchronous `PreToolUse` matcher for `request_user_input`, dispatching existing `question/question` TTS events before the agent blocks on user input. Question text, session identity, project name, mute rules, event filters, daemon history, and direct fallback all reuse the established pipeline. Windows, WSL, macOS, and Linux input helpers now preserve the `codex` source instead of relabeling fallback speech as Claude. `Stop` completion speech remains unchanged; unrelated tools and `codex-stock` remain silent. New sessions must review and trust the added hook through `/hooks`.

- **The console zooms itself, and its grids follow the content (08/24/2026).** There was a UI scale already, but it was buried in the Customize drawer, capped at 80-125%, and stored **per page** — so it reset when you changed page, which is a per-page layout tweak rather than a zoom. People reach for the browser's zoom instead, and that shrinks the *viewport*: the app frame gets shorter and the SystemBar pinned at its bottom goes off the end of the window.

  Now a global scale, **50-200% in 5% steps**, persisted with the rest of the preferences, with a stepper in the sidebar (`−  100%  +`, click the number to reset) and the drawer's slider driving the same value. An existing per-page scale migrates to it rather than being reset. It is applied to the frame, and the frame is sized in **measured pixels divided by the zoom** — `zoom: z` renders a `w px` box at `w × z` in every engine that implements zoom, whereas a viewport unit inside a zoomed element is the part engines disagree about. The first attempt used viewport units and worked in Chromium up to 150% and overflowed 399px at 200%. `html`/`body` are `overflow: hidden` as an independent second guard, so the worst case is content scrolling in its own pane rather than the whole document sliding under the window. Verified with Playwright at 50/75/100/110/150/200%: frame exactly the viewport, zero document overflow, SystemBar on screen at every step.

  The grids were fixed breakpoint counts (`2xl:grid-cols-6`), so three projects filled half a row and left the rest empty while six got about 150px each — narrower than their own captions can render, and with `whitespace-nowrap` on those captions the overflow ran into the neighbouring cell. That is the collided text in the project cards and in the nine-metric memory band. Every one of those grids is now `repeat(auto-fit, minmax(<floor>, 1fr))`: measured live, six cards give four columns of 317px, three give **3 × 427px** with the empty track collapsed, one fills the row. Adding or removing a widget reflows the rest. Captions may wrap; values keep `nowrap`, because a number split over two lines reads as two numbers.

- **One memory backend, chosen at install (08/24/2026).** AgentMemory and Headroom both do semantic memory, and the installer asked about them as two independent yes/no questions — so every combination was reachable, including two stores each holding half the story. They are now one question with one slot: `memoryBackend` is `agentmemory` (the default: AgentMemory remembers, Headroom compresses), `headroom` (Headroom does both, AgentMemory is not installed), or `none`. A single slot cannot hold two values, so the bad combination is unrepresentable rather than merely discouraged. `agentmemoryEnabled` is derived from it, `ts-config memory <backend>` is the only writer of either and restarts headroom so the setting and the running state cannot disagree, and `ts-config agents agentmemory on` refuses when the backend is something else rather than silently reconciling.

  **What this uncovered: Headroom's memory had never run.** The proxy's command is `headroom proxy --host 0.0.0.0`, and memory engages only when passed `--memory` — for which there is no environment variable. The compose file set `QDRANT_URL` and `NEO4J_URI` and started both databases, so everything looked wired, and the proxy never contacted either. On a machine that had been running it for months: **0 memories, 0 Qdrant collections, 0 Neo4j nodes, and 899 MB of JVM**, with all four containers reporting healthy and no check anywhere that would have said so. (The flag also reads `HEADROOM_QDRANT_URL`, not the un-prefixed `QDRANT_URL` the datastores were wired with, so even the variable that was set was the wrong name.)

  Headroom's memory is now a compose overlay carrying all three things that must travel together — the datastores, the connection settings, and `--memory` — selected through the stack's `COMPOSE_FILE`. A machine using AgentMemory never references Qdrant or Neo4j, so it never pulls them: the base headroom stack is two small containers. `ts-stack doctor` reports the backend, flags drift between it and `agentmemoryEnabled`, fails when `headroom` is selected but the proxy is running without `--memory`, and notes leftover datastores that nothing writes to.

  Two mechanisms came out of it, both discovered by filename rather than registered: `ts-checks.<x>.conf` is loaded alongside `docker-compose.<x>.yml` (the Qdrant and Neo4j health checks used to sit in the base file, passing on every machine and proving nothing), and `ts-envfiles` names extra `--env-file` **interpolation** sources — never `env_file:` keys, which would hand a container every variable in the file, `OPENAI_API_KEY` included. A test asserts no path is both.

  `doc headroom` now says plainly what Headroom does and does not use a model for: compression is structural (tool-schema trimming, code-aware compression, CCR) and calls no model; embeddings are local and in-image; the only model it talks to is the one it relays to. It also records that `headroom doctor` run *inside* the container always reports claude/codex "not routed", because those files never exist there.


- **agent007memory is its own compose project (08/24/2026).** The console was an overlay merged into the agentmemory project, so Docker listed it as a second row under someone else's name. It is now `services/stacks/agent007memory/` — project `ts-agent007memory`, container `ts-agent007memory`, image `ts-agent007memory:local` — a stack `ts-stack` starts, stops, checks and verifies on its own. It joins `ts-agentmemory-net` (named, not left as a project-derived default, because anything reaching across projects has to be pinned) and mounts agentmemory's data volume read-only for the HMAC secret.

  Two mechanisms came with it, both discovered rather than registered. `ts-after` names the stacks a stack must follow: lexical order puts `agent007memory` *first* (`0` sorts before `m`) and an external network cannot be joined before it exists, so without it every fresh `up` failed with "network not found". `ts-envfiles` names extra `--env-file` interpolation sources: the console displays which model and endpoint AgentMemory is configured for, and the authority on that is the agentmemory stack's `.env`. That file is an interpolation source and never an `env_file:` entry — the distinction is what keeps `OPENAI_API_KEY` out of the console, and a test enforces it.

  `down` and `restart` now walk the stacks in reverse start order, and `restart` takes everything down before bringing anything up: restarting agentmemory while the console still held its network left the console pointed at a container that no longer existed. The billing helpers (`configure-openai-billing.*`, `.billing.env`, `docker-compose.billing.yml`) moved with the console, since they only ever configured it.

- **`http://localhost:8788/` redirects to the dashboard (08/24/2026).** It used to 404, because the dashboard is served at `/dashboard` and the gateway is deliberately not a general reverse proxy. The redirect is relative (`absolute_redirect off`) — nginx otherwise rebuilds the `Location` from `$host`, which carries no port, and sends the browser to port 80.

### Fixed

- **Windows pytest no longer launches WSL by accident (08/25/2026).** Python's
  `shutil.which("bash")` selected `C:\Windows\System32\bash.exe`, which is the WSL
  launcher, before Git Bash. Bash-backed tests then failed on Windows paths,
  inherited the wrong home/configuration, or hung inside interactive wizard code.
  The suite now resolves and probes a native MSYS/Cygwin Bash, rejects the WSL
  launcher, translates temporary paths with `cygpath`, and pins POSIX fixtures to
  LF plus UTF-8. Codex's direct self-summary test now uses an isolated config, and
  the shell hook falls back to Python for final-message JSON when `jq` is absent.

- **Headroom MCP no longer fails Codex startup with nginx `404` (08/25/2026).**
  Port `8788` serves the dashboard, not MCP, so both Claude and Codex were
  registered against a nonexistent `/mcp`; Codex exposed the failure on every
  launch while Claude made the same broken registration look healthy. Headroom
  MCP now runs on demand inside `ts-headroom-proxy` over Docker stdio. Repair and
  status send a real JSON-RPC `initialize`, validate server identity and tool
  capability, and compare exact stdio registrations for Claude, Codex, and
  Cursor. AgentMemory's Codex check now also requires all six plugin and stable
  hook scripts plus exactly one current registration for each supported event;
  changed hooks still require review and trust through Codex `/hooks`.

- **A console test had been red since the merge (08/24/2026).** Genericising rewrote a fixture endpoint to `192.0.2.10`, which is RFC 5737 TEST-NET-1 — a *documentation* range, not a private one — so `privateHost()` correctly refused to call it local and the assertion that a private vLLM endpoint is fee-free failed. RFC 1918 is the range that is actually private. Nothing in the repo runs the console's `npm test`, which is why it sat red; worth wiring up.

- **AgentMemory's LLM credential never reached the container, and nothing said so (08/24/2026).** Absorbing the Docker stacks moved them one directory deeper, and the agentmemory compose file kept loading the shared credential from `../.env` — which now resolves to `services/stacks/.env`, a file that has never existed. Both env files are `required: false` so a fresh clone starts in degraded no-LLM mode, and compose says *nothing at all* about an optional `env_file` it cannot find: no warning, no non-zero exit, nothing in `docker compose config`.

  What that looked like: `"outcome":"success"` with `providerLatencyMs: 0`, then `Failed to parse compression XML`, a retry, and a dead letter. With no usable provider AgentMemory returns an empty completion instead of raising, so the job "succeeds" without any HTTP request happening. **52,570 compression jobs dead-lettered that way**, over weeks, while capture, search and local embeddings kept working perfectly — which is exactly why nobody looked. The path is now `../../.env`, a test asserts every `env_file` path resolves next to a *tracked* `.env.example`, and `ts-verify.sh` asks the provider **from inside the container** with the container's own credentials (an unset base URL is a skip — no chat provider is a supported configuration; one that refuses is a failure).

- **Seven maintenance scripts died on their first executable line (08/24/2026).** The same merge renamed `_common.sh` to `_stack.sh` and moved it a level up. The sweep rewrote every `dl_` call *inside* `reconcile-llm-queue`, `migrate-durable-llm`, `migrate-memory-projects`, `configure-openai-billing`, `check-capture`, `setup-kokoro-docker` and `check-playwright`, and missed the `. "$SCRIPT_DIR/../_common.sh"` line in each. Nothing caught it because these are the scripts you reach for only when something is already wrong. A test now checks every dot-sourced path exists.

- **`reconcile-llm-queue` could not run against a real backlog (08/24/2026).** It passed the whole telemetry blob to node on **argv**, so with a large dead-letter queue `execve` failed with "Argument list too long", node never ran, the projected cost came back empty — and an empty value fell through the cost gate as *exceeded*, refusing to reconcile with a blank figure: `projected cost $ exceeds safety limit $1.00`. Telemetry now goes over stdin (as the neighbouring `metrics()` already did), and no output is treated as "the estimator died", not as a number. Its OpenAI-priced call and cost limits are also skipped, loudly and with the reason stated, when `OPENAI_BASE_URL` is not OpenAI — list prices for models a self-hosted endpoint does not serve were blocking a reconcile on a machine that cannot be billed for anything.

- **`ts-doctor` reported kokoro unreachable on every run, whatever the truth (08/24/2026).** `ts_cc_tts_probe | grep -q` looks right and is not: `grep -q` exits at the first match, closing the pipe, so the producer takes SIGPIPE and exits 141 — which `pipefail` makes the pipeline's status. A match was reported as a failure. Captured first, matched in the shell. The severity is engine-keyed now too: kokoro down while it *is* the chosen TTS engine is a failure, not a note, because voice notifications are silently gone.

- **The `ts-stack` port check could not tell "absent" from "exposed" (08/24/2026).** Docker collapses contiguous published ports into a range (`127.0.0.1:3112-3113->3112-3113/tcp`), so a literal `:3113->` matched nothing and the check reported "not loopback-only" about a port that was fine. Three outcomes now, and the loopback audit is scoped to `ts-` containers: it was failing on the operator's own unrelated projects, and noise is how the one check that must never be skipped gets ignored.

- **The pwsh headroom check could not read an error body (08/24/2026).** PowerShell 7 throws on 4xx with the response stream already consumed, so `GetResponseStream()` threw and the body read as empty — reporting "a refused connection, not a refusal" against a proxy that had just answered `401 {"error":"unauthorized"}`. `$_.ErrorDetails.Message` first, the stream as the 5.1 fallback.

- **`playwrightEnabled` was a toggle nothing could set (08/24/2026).** `ts_agent_get` rejected the key outright, so `ts-stack` reported the stack running with its toggle off, permanently.

- **AgentMemory's healthcheck failed while it was working (08/24/2026).** A 5s timeout against a single-threaded Node process chewing through a compression backlog (3-18s of provider latency per call, several in flight) goes unhealthy while `livez` answers a direct request in 260ms. 15s and five retries now. The console `depends_on` it being healthy, so this was one busy afternoon away from blocking a bring-up.

- **`ts_wez_changes_tally` died on WezTerm's own changelog on Windows (08/24/2026).** python3 defaults stdout to the ANSI code page there, and the changelog is full of box-drawing characters, so printing the slice raised `UnicodeEncodeError`. `PYTHONIOENCODING=utf-8` is pinned rather than detected.

### Added

- **The Docker services live here now (08/24/2026).** agentmemory, Headroom, Kokoro TTS and the Playwright MCP browser were a separate private repo, and the agentmemory console was a *third* repo that the second built from a pinned commit SHA. Three clones, two remotes, and a push-then-re-pin-then-rebuild loop for a one-line console change. They are all under `services/` now, with `ts-stack` driving them.

  `ts-stack bootstrap` is what a fresh machine runs: it seeds every `.env` from its tracked example, **generates** Headroom's `HEADROOM_PROXY_TOKEN` and `NEO4J_PASSWORD` rather than telling you to paste `openssl rand -hex 32` twice, and creates the two `external: true` volumes compose will not create for you. Then `ts-stack up`, `down`, `restart`, `logs`, `status`, `config`, `doctor`, `backup`, `reset` and `test` — bash and pwsh twins with byte-identical `-h`, exposed the way `ts-mux` and `ts-doctor` already are.

  **`ts-stack test` is the end-to-end one.** It takes everything down, brings it back up, and then checks the things "Up (healthy)" does not: that Headroom's proxy token is actually *enforced* (asserted on the response body, because a refused connection is also non-2xx), that a memory can be written through the console proxy and read back (every vendor hook swallows its errors and exits 0, so a round trip is the only proof capture works), that Kokoro really synthesises audio and has not restarted, and that every published port still binds `127.0.0.1` — an audit no toggle can skip. Checks are discovered, not registered: a stack ships `ts-checks.conf` and `ts-verify.sh`, and having them is the registration.

  Everything is named `ts-` now — projects, containers, networks and locally built images — because `docker ps` on a working machine also lists your own projects. Volumes too, which is the one part that touches data, so `ts-stack up` refuses to start while a legacy volume exists and its ts- replacement does not (compose would otherwise create an empty one and start the stack with no memories in it, reporting success) and `ts-stack migrate-volumes` copies, verifies the file count, and keeps the old volume as the rollback.

  Data safety is explicit: `down`, `restart`, `test` and `reset` destroy no volume; `--destroy-data` takes Headroom's three after a verified backup and a typed phrase; `--purge` also takes the two memory volumes, which are `external: true` precisely so an ordinary `down -v` cannot. That asymmetry is the safety property, not an inconvenience.

  Two platform truths are now handled rather than guessed at. In WSL with Docker Desktop's integration switched off, `docker` still exists — as Desktop's stub, which exits 1 for every command and prints its complaint on *stdout*, so `command -v docker` is true and useless; `ts-stack` names that specifically and re-runs its Windows twin over interop rather than proxying `docker.exe`, whose `-f`, build contexts and bind mounts all resolve as Windows paths. And on macOS it resolves the runtime from `docker context ls` rather than guessing between Docker Desktop, Colima, OrbStack and Rancher.

  New `doc` pages, because `doc agentmemory`, `doc headroom`, `doc kokoro` and `doc playwright` all matched **zero** topics before: `doc services`, `doc troubleshooting` (keyed by symptom), `doc agentmemory`, `doc agentmemory-console`, `doc headroom`, `doc playwright`, plus `doc docker-desktop` on Windows and macOS and an engine-install section on `doc docker` for Linux. `INSTALL.md` gains Phase 6a, and the sentence "Terminal-stack never manages the containers" is replaced by the invariant that survives and is enforced by test: **`ts-config agents` never touches Docker; `ts-stack` is the only thing that does.**

  Personal infrastructure was genericised in the same pass — the LLM host is a role, not a hostname, and the addresses are RFC-5737 documentation addresses. `CHANGELOG.md` and `docs/decisions.md` are exempt: rewriting history to hide a hostname makes the record dishonest.

- **Ghostty on Windows: the managed config now deploys there too (08/24/2026).** There is a Ghostty for Windows after all — [noctty](https://github.com/amanthanvi/noctty), Ghostty's terminal core in a native Win32 app. It was renamed from WingHostty in main on 2026-08-20 after a trademark request, but that landed *after* the v1.3.123 tag, so its releases still ship as `winghostty-…`; installing that is current, not stale.

  The stack's Ghostty config and generated `vs-code-light-modern` theme now mirror to **`%LOCALAPPDATA%\ghostty\`** — the *upstream* path, not the app-named one. noctty reads both, but `<appname>` flips from `winghostty` to `noctty` the day the rename ships, so the app-named path would silently stop being read on upgrade day. Because the upstream path is `ghostty/config` plus `ghostty/themes/`, it is the same relative layout as macOS, and the theme file ports byte-for-byte (a test pins the two copies together).

  `ts-config ghostty on|off|status|diff` gained a PowerShell twin and now works from WSL as well, driving the Windows copy over `/mnt/c/`. The terminal question offers Ghostty on Windows and pre-ticks an installed one — but like the WezTerm channels it is **asked, never installed**, so it stays out of `$TsTerminalWingetIds`.

  Two Windows-only divergences, both deliberate. The shell is pinned to `pwsh.exe -NoLogo` to match WezTerm's `default_prog`: noctty's picker will hand you "Windows PowerShell", which is PowerShell **5.1** — a shell this stack configures not at all, and which carries its own execution policy (separate from pwsh 7's) defaulting to Restricted, so it refuses to dot-source any profile and fills the window with `SecurityError`. And the config is **opaque**, unlike the macOS twin's `0.97` + blur: noctty turns that exact pair into a DWM tabbed backdrop painted under the Win32 chrome, which washes out the `Ctrl+Shift+P` command palette.

  Two honest limits are recorded rather than papered over. Windows drops four macOS directives (`macos-option-as-alt`, `font-thicken`, `window-colorspace`, the `cmd+…` chords) and gains `window-theme` for the DWM title bar. And there is **no working syntax gate**: `+validate-config` fails `FileTooBig` on 1.3.123 even for a 14-byte config, and `+show-config` reports nothing at all for an unknown key or a bad value — so `status` says `validate: unavailable on this build` instead of claiming a check it never ran.

- **Guided rclone, verified SMB setup, and Tailscale discovery helpers (08/23/2026).** Bare `rclone config` now explains what is being selected, leads with Windows/NAS shares, preselects common providers, and progressively searches the full catalog; `rclone-stock config` preserves upstream's raw wizard. `ts-smb setup` discovers live Tailscale SMB hosts and verifies credentials/share access before transactional local saving. New `tail-*` identity and diagnostic shortcuts are documented in `doc tailscale`.

- **`ts-update` now finishes the shell handoff (08/23/2026).** When an update
  changes zsh configuration, it explains why the current process still has old
  functions and offers a safe immediate restart when interactive with no
  background jobs; otherwise it prints `exec zsh`. PowerShell gives the matching
  new-tab instruction when its profile changes.

- **`ts-update` now owns chezmoi conflict resolution (08/23/2026).** Codex hook
  trust state survives profile refreshes instead of triggering an overwrite
  prompt. Unknown two-sided conflicts are reviewed one at a time with explained
  overwrite/merge/cancel choices, and the final apply can never fall through to
  chezmoi's terse prompt. Dirty runtime clones are refused before deployment.

- **macOS window shortcuts and Codex self-speech stop falling through (08/23/2026).**
  Ghostty no longer installs a global Command-Backtick quick-terminal binding;
  the standard macOS window-cycle shortcut remains untouched. The Codex Stop
  hook's top-level `last_assistant_message` is now consumed by the local `self`
  summarizer instead of falling back to the fixed completion template.

- **Offline Headroom MCP no longer breaks every Codex startup (08/23/2026).**
  Headroom's model proxy on 8787 and optional MCP sidecar on 8788 are separate
  services, but reconciliation registered the latter even when it was absent.
  Codex consequently warned that MCP startup was incomplete on every launch.
  `headroom on` and `repair` now register MCP only after it answers, and remove
  stale Claude, Codex, and Cursor registrations while leaving authenticated
  model proxying enabled.

- **The wizard now asks what the voice should say, and the docs can be found (08/23/2026).** The TTS question was a single on/off; engine, voice and message mode were never asked. It now probes what could actually speak here — Kokoro, Chatterbox, edge-tts, and the new `say` floor — recommends accordingly, and asks a follow-up: `self` (the agent writes its own line), `template` (fixed wording) or `hook` (last message raw). `self` states up front that it appends a marker block to `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`, an edit that previously happened with no consent. `haiku` and `ollama` are never offered on a host without a daemon.

  Two new pages: **`doc ts-config`**, which matched *zero* labels before — the material was inside `common/stack.md`, where nobody would guess — and **`doc tts`**, carrying the cross-platform half that was stranded in `windows/tts-daemon.md` where the picker hides it from every other OS, led by a macOS/Windows support matrix. `_index.md` advertised `windows/` as "pwsh, winget" and omitted the TTS page entirely.

  Discovery fixed too: a zero-match query dropped straight into fzf, which re-queried the *narrower* per-OS index, so `doc ts-config` produced an empty picker and no message rather than "no topic matching".

- **Daemon-only TTS settings now refuse instead of pretending (08/23/2026).** `ts-config tts music duck` and `duck-level` accepted and persisted a value on macOS that nothing would ever read — ducking is daemon-only *and* built on pycaw/WinRT. Same for `summarizer haiku|ollama`. All now say what is missing and why. And `ts-config tts` with no subcommand printed `unknown subcommand ''` — the only verb in the stack that answered with an error rather than status.

- **`ts-config wizard` stopped discarding your TTS tuning (08/23/2026).** `ts_cc_tts_apply_wizard_choice` called `ts_cc_tts_reset_defaults` on **both** `on` and `off`, so every re-run silently reset voice, engine, templates and events to defaults. Defaults are now seeded only on a host that has never been configured.

- **The wizard now recommends, and probes before it offers (08/23/2026).** Every behaviour question opens with a `RECOMMENDATION:` line that says which way to go *and what it costs*: WezTerm mux **off** (config changes need `ts-mux restart`, which kills every pane; mux panes lose the Claude state tint), session restore **off** (panes return without their processes, and the autosave means `Leader+L` still restores on demand), atuin **on** — and atuin's wizard default flips to `on`. The stored `[data]` default stays `off`, so a machine that never answered the question is not silently switched.

  The agent toggles are **interrogated rather than guessed**. `ts_probe_headroom` and `ts_probe_agentmemory` run before the question, print what they found, and set the default — on when the service answers, off when it does not. That matters because the agentmemory hooks `fetch(...).catch(() => {})` then `exit(0)`: a machine wired to a service that is not running captures nothing and says nothing about it, which is exactly the kind of silent failure this stack keeps finding. **Any HTTP response counts as up, never just a 2xx** — AgentMemory answers 404 on `/` and 401 on `/agentmemory/health`, so `curl -fsS` reported it *down while it was up*, which is a bug `ts-agents agentmemory status` had and has now. When a probe fails, `ts_docker_ports` says what docker is actually publishing, so the warning names the real port rather than repeating the expected one. Headroom's MCP endpoint is reported separately because `headroom mcp serve` is a separate process compose does not start — its absence is not a fault of this stack.

- **`docs/tui-design.md` — the design for a ratatui front-end (08/23/2026).** Design only; nothing built or shipped. Records the load-bearing decision that the TUI **shells out to the existing scripts for every write** and never touches chezmoi `[data]` itself, so the CLI stays authoritative and the two cannot diverge — this repo has been bitten three times by parallel implementations drifting, most expensively when two config stores disagreed and silently removed all five Claude TTS hooks in a day. Phase 1 is `--json` read models on `ts-config show`, `ts-doctor`, `wso status` and `ts-smb list`, modelled on `ttsd/settings_schema.py` (which already does exactly this, including which layer won per field) and worth building whether or not the TUI ever exists. Distribution is prebuilt cargo-dist binaries fetched by the existing `common_install_github_binary`, offered by `ts-update` rather than downloaded silently. Two traps written down before they bite: a separately-fetched binary participates in neither `ts-update` nor `ts-rollback`, so it needs the TTS daemon's git-SHA stamp and kept `.previous` artifact; and nothing may ever `stat` an SMB mountpoint, because a dead FUSE mount blocks forever and would freeze the render loop.

- **Ghostty gets a managed config, and a one-command revert (08/23/2026).** The stack previously shipped none, on the record in `docs/decisions.md` — that entry is now reversed rather than left contradicting the code. `dot_config/ghostty/config.tmpl` covers theme, font, window, keys and behaviour QoL, macOS-only and gated in `.chezmoiignore` beside `.wezterm.lua`. Driven by `ts-config ghostty on|off|status|diff`; **no pwsh twin**, deliberately, since Ghostty has no Windows build.

  **Theme is live, not baked.** Every other consumer reads `resolvedTheme` because Starship/tmux/Claude cannot re-evaluate at runtime; Ghostty's `theme = dark:X,light:Y` follows the OS *itself*, so the template reads `themeMode` and `follow` switches with no re-apply — WezTerm's class, not Starship's. Reading `resolvedTheme` would have looked correct and silently frozen `follow`. `Catppuccin Mocha` is a builtin; **VS Code Light Modern is not**, so `themes/vs-code-light-modern` is generated from `dot_wezterm.lua.tmpl`'s `PALETTES.light.scheme_def`, with a test pinning the two (drift one hex and it fails — verified).

  **`off` is a real revert.** `.chezmoiremove` was rejected for it: that file is evaluated on *every* machine, so a removal rule would delete a hand-written Ghostty config on a box that never opted in. Instead `off` restores the newest backup — or removes ours if there never was one — for the machine you run it on. That backup exists because `chezmoi apply` overwrites `$HOME` files with **no backup at all** on POSIX (the `.bak.YYYYMMDD[.N]` convention only fires in the Windows sync hook and the merge helpers), so `run_before_20-backup-ghostty.sh` takes one first and skips any file already carrying our marker, so a managed config doesn't spawn a `.bak` on every apply. All four revert paths drilled: backup restored, no-backup removal, newest-of-several wins, and a non-darwin refusal.

  Verified against Ghostty 1.3.1: all three theme modes pass `ghostty +validate-config` (exit 0) and a deliberately broken control still exits 1 — unlike WezTerm's `show-keys`, this is a real gate. `macos-option-as-alt` is the load-bearing key line (without it Alt never reaches tmux, vim or readline); `cmd+t`/`w`/`d` are deliberately **left alone**, since this stack multiplexes inside the terminal rather than with a host multiplexer. `auto-update = off` keeps Homebrew the sole owner of the cask it installed.

  Not done, and documented rather than faked: there is no sticky per-tab project name under Ghostty. It *has* the right primitive — `set_tab_title`, distinct from `set_surface_title`, the same split that makes the WezTerm approach work — but ships **no CLI to drive a running instance**, so nothing can invoke it from a shell wrapper. Whether a title set that way survives Claude Code's own OSC is untested and needs an interactive session.

- **`atuin`, `yazi` and `pi` join the install catalog (08/23/2026).** `atuin` (SQLite shell history) is in the `shell` group but is **a wizard question with its own `[data]` key**, not just a tick: it *replaces* `Ctrl+R`, and the binary is frequently already installed yet dormant — a brew dependency, an old manual install — so a `command -v atuin` guard would have hijacked the binding on the next apply without anyone choosing it. Default off; `ts-config atuin on|off`. The switch is a chezmoi-rendered fragment (`~/.config/terminal-stack/atuin.zsh`) that `dot_zshrc` sources and that renders **empty** when off, because `dot_zshrc` must stay a non-template for `chezmoi re-add ~/.zshrc` to keep working. Sourced after `fzf --zsh` so atuin wins `Ctrl+R` while fzf keeps `Ctrl+T`/`Alt+C`; `--disable-up-arrow` leaves Up on prefix search. Verified with atuin installed: off → `fzf-history-widget`, on → `atuin-search`.

  **The security half is not optional.** `dot_zshrc`'s `zshaddhistory()` returns 1 to *discard* commands containing secrets so they never reach `~/.zsh_history`, but atuin records through its own `preexec` and never sees that hook — so enabling it naively would start writing to atuin's database exactly the secrets the stack refuses to put on disk. `dot_config/atuin/config.toml.tmpl` ships in the same change with a `history_filter` mirroring those regexes plus atuin's own `secrets_filter`; drilled with `ANTHROPIC_API_KEY=sk-…`, a `Bearer` token and `--token=`, none of which reach `history.db` or its WAL. `auto_sync` and `update_check` are off — no account, and updates come from the package manager.

  `yazi` (optional, `editors`) ships the upstream `y` wrapper in both shells, which `cd`s the parent shell to wherever you exited via `--cwd-file`; without it a file manager cannot change your directory. `pi` (`@earendil-works/pi-coding-agent`) joins the `ai` group as a third npm-gated agent CLI at **Node 22.19+**, the highest floor in the catalog.

  Two package-id findings, both of which would have shipped broken: **`ellie.atuin` does not exist** — there is no winget manifest for atuin at all, and `atuin init` has no PowerShell target either, so it is deliberately absent from `$TsWingetIds` under the same "an id that always fails is worse than an honest not-available" rule as `ncdu`/`tree`/`bandwhich`, and reaches a Windows box through WSL. And `common_arch_tag` gained a third style, **`rust` → `x86_64`/`aarch64`**: atuin and yazi are cargo-dist projects whose ARM asset says `aarch64`, while `gnu` yields `arm64`. The obvious regex works on x86_64 and **fails silently on ARM only**, leaving the tool quietly missing on every Pi and ARM server. All four asset URLs were resolved against the live releases.

- **`v` opens Neovim, and fzf got portable defaults (08/23/2026).** `alias v='nvim'` in `dot_zshrc` and `function v { nvim @args }` in `$PROFILE`, both defined unconditionally and resolved per call — gating the *definition* on `command -v` is the trap already documented on `c`, where installing the tool mid-session left the name silently undefined until a new shell. Pairs with fzf's `Ctrl-T`, which inserts a shell-quoted *path* rather than launching anything, so `v` + `Ctrl-T` + Enter opens the picked file and the same works for `cat`, `less`, `cp`, `rm`. `FZF_DEFAULT_OPTS` sets height/layout/border; `FZF_CTRL_T_OPTS` adds a `bat` preview **only when `bat` is installed**, because a preview command whose binary is missing breaks the widget. `Ctrl-R` and `Alt-C` get no preview on purpose. No fzf init was added — `dot_zshrc` has sourced `fzf --zsh` (which binds all three keys) since before this change. Native pwsh still has no fzf key bindings; `docs/kb/windows/pwsh.md` and `docs/kb/common/tools/fzf.md` say so rather than implying parity.

- **`ts-smb` — SMB/CIFS shares over rclone, on macOS and Linux (08/23/2026).** One command to find SMB hosts on the LAN (mDNS, with an opt-in and confirmed port-445 sweep), list what a host offers, probe which credentials work and what they get you, browse/size/copy without mounting, and mount/unmount. rclone is the transport throughout, so the flag vocabulary is identical on both platforms and `rclone lsd` against a host root doubles as share discovery; on-the-fly connection strings mean interrogating a host needs no configuration at all. `bootstrap/ts-smb.sh` + `bootstrap/_smb.sh`, zsh wrapper in `dot_zshrc`, `rclone` added to the install catalog's `network` group. Shares live in an untracked `~/.config/terminal-stack/shares.local.conf` layered over a tracked `bootstrap/shares.conf` that holds defaults and never a host — no chezmoi `[data]` key, because this is a record list rather than a scalar. Passwords are obscured once by `ts-smb creds`, kept in the OS keychain (macOS `security`, Linux `secret-tool`, 0600 file fallback) and passed to rclone through the environment; there is no `--password VALUE` flag on purpose, and a live mount was verified to carry nothing secret in `ps`. **No PowerShell twin**, deliberately and on the record (`docs/decisions.md`) — Windows already has Explorer and `net use`.

  Three macOS findings are baked in, each of which silently breaks mounting and none of which says so:

  - **cgofuse picks its FUSE library by a fixed dlopen order and there is no flag to override it** (`--fuse-flag` only forwards arguments *to* libfuse). On the development Mac that meant macFUSE 4.2.4 built for macOS 12.1 winning over a current FUSE-T 1.2.6 — and because its kext will not load on macOS 26, the result is a **hang, not an error**. `ts-smb` now always pins `CGOFUSE_LIBFUSE_PATH`, prefers FUSE-T, and accepts macFUSE only when `kmutil showloaded` proves the kext is loaded (unprivileged, ~0.2s); a merely plausible macFUSE ranks below `rclone nfsmount`, since a slow mount beats a wedged one.
  - **Homebrew's macOS rclone refuses to mount at all**, aborting with a build-time guard no library or environment variable can get past. Browsing, listing and copying are unaffected, which is exactly why it is confusing. `ts-smb doctor` reports it and names the official binary.
  - **FUSE-T's FSKit backend fails on macOS 26.6** (`fuse: mount failed with error: -1`) where its default NFS backend does not, so `-o backend=fskit` is never passed automatically — a regression test pins that.

  Mount records live in `${XDG_STATE_HOME:-~/.local/state}/terminal-stack/smb/` for identity and intent, with liveness **derived** from the kernel mount table (live/zombie/orphan/gone) rather than stored — and nothing `stat`s or globs a mountpoint to test it, because a dead FUSE mount blocks forever and takes the shell with it. `rclone rc` was considered and rejected (per-process, so it still needs the state dir; the alternative is a second daemon to supervise). Eleven new tests, plus seven shell entrypoints that were never covered by the `bash -n` gate (`ts-mux.sh`, `wso.sh`, `ts-doctor.sh`, `ts-wezterm.sh`, `_workspace.sh`, `_doctor.sh`, `_common-debian.sh`) added to it.

### Fixed

- **`cd` into a JS repo asked to install Node, and cost 738ms when it did not (08/24/2026).** fnm resolves `engines.node` from `package.json` when there is no `.nvmrc`/`.node-version`, and that is on by default. `package.json` is in nearly every JS repo, so fnm's `use-on-cd` hook fired on nearly every `cd`; and an `engines` range that no fnm-**installed** version satisfies turns the `cd` into `Can't find an installed Node version matching >=24.0.0. Do you want to install it? answer [y/N]:` -- fnm counts only versions it installed itself, so a system Node 26 against `>=24` still got asked. Both shells now pass `--resolve-engines=false`: `cd` into that repo went from a 738ms spawn (or a prompt) to 2ms, and with the flag off fnm's own hook stops testing for `package.json` at all. An explicit `.nvmrc`/`.node-version` pin is still honoured -- that file is somebody's decision, an `engines` range is metadata. Both sides keep a fallback for fnm before 1.36, which has no such flag and exits non-zero; an empty `eval` would have left fnm unwired with nothing printed.

- **A new WezTerm pane spent most of a second on tool init (08/24/2026).** The pwsh profile ran `starship init`, `zoxide init` and an `Add-Type` C# compile at every shell start. On this machine, where a third-party antivirus scans each exec, that measured 1,835ms / 869ms / 339ms cold -- and `starship init powershell` prints a *bootstrap* that re-runs starship with `--print-full-init`, so starship was spawned twice. The generated text only changes when the binary does, so it is now cached under `%LOCALAPPDATA%\terminal-stack\cache\`, keyed on the producing exe's path, mtime and size, and the codepage P/Invoke is compiled once to an assembly there and loaded with `Add-Type -Path` (~25ms). Profile cost went from a 1,110ms median to 697ms, and its floor from 1,062ms to 355ms; the `cli-tools` block alone went from 972ms to 197ms.

  Two measurements shaped the design. `Get-TsToolInit` hands back a **file to dot-source** rather than a string for `Invoke-Expression`, because the same 10KB of starship init parses in 427ms dot-sourced against 612ms evaluated (the cache's key line is a `#` comment so the file stays a plain script). And the **caller** dot-sources it, never the helper: `$PROFILE` is dot-sourced into the global scope and a function body is not, so starship's `New-Module` and zoxide's `function global:` definitions would have landed somewhere the prompt never sees. `fnm env` is deliberately **not** cached -- its output embeds a per-shell `FNM_MULTISHELL_PATH` with the PID in it. What remains is starship's init parsing itself, which is not a spawn and not ours to trim.

- **`ts-config wizard` crashed on Windows and then saved the wreckage (08/24/2026).** `Read-TsWizard` moved to `bootstrap/_config.ps1` so `$PROFILE` could reach it, but the prompt it calls last, `Read-TsWorkspaceDir`, stayed in `windows-bootstrap.ps1` - a file `$PROFILE` never sources. So the questionnaire asked every question, then died on the workspace prompt with *"The term 'Read-TsWorkspaceDir' is not recognized"*, leaving `$w` null. The two follow-up assignments then reported `The property 'CcTtsDaemon' cannot be found on this object`, and the run continued into `Terminal emulator: none selected`, `No optional apps selected` and finally a `Save-TsConfig` `ValidateSet` failure on an empty `-HeadroomEnabled` - eight or nine minutes of answers discarded, with the only clue being the first error scrolled off the top.

  `Get-TsDetectedWorkspace` and `Read-TsWorkspaceDir` moved to `_config.ps1` alongside the rest of the questionnaire. The answer is no longer dropped either: the persistence logic became `Save-TsWorkspaceOverride` there, so `ts-config wizard` writes `WORKSPACE_DIR` to `profile.local.ps1` exactly as the installer does (the bootstrap keeps its `ShouldProcess` gate around the call). And `$runWizard` now refuses to install or save at all when the questionnaire did not complete, instead of persisting empty strings over real answers - `ValidateSet` only catches some of the keys, and the ones it does not catch save silently.

  The existing test named the two functions that had moved, which is exactly why it passed. It now derives the callee list from `Read-TsWizard`'s own body and asserts every `Read-Ts*`/`Get-Ts*` it calls is defined in `_config.ps1`, so the next prompt left behind fails in CI-less verification rather than mid-install.

- **A cold Headroom proxy blocked the repair that was meant to fix it (08/24/2026).** `ts-update` printed `!! Headroom proxy authentication failed; registrations were not changed.` on a machine whose proxy was up and whose token was correct: the probe was one attempt with a 2s timeout, and a container that has just started, or a host busy running winget, answers slower than that. Because `on` and `repair` gate on that probe, the false negative also meant the three missing MCP registrations it had just diagnosed (Claude, Codex, Cursor) stayed missing, on every update, silently.

  Both twins now retry once with a 5s timeout, and **never** retry a real HTTP answer - a 401 is conclusive, so a wrong token still fails immediately rather than taking 10 seconds to say so. The failure is also named: `unreachable`, `HTTP 401`, or `no proxy token`, instead of the old `(unreachable, missing token, or unauthorized)` guess-list, and the message that says registrations were not changed now says why. One trap on the bash side is worth remembering: `curl -w '%{http_code}'` **prints** `000` on a connection failure and exits non-zero, so the obvious `|| echo 000` fallback concatenates into `000000` and reports `HTTP 000000`.

- **`cursor-agent` could never install on Windows, and three agents that were already installed kept being offered (08/24/2026).** Ticking cursor-agent on Windows printed *"no Windows installer this stack can call; install it inside WSL"*. There is one: the same endpoint as POSIX with `?win32=true`, which serves a PowerShell script rather than a shell script. It installs to `%LOCALAPPDATA%\cursor-agent` and adds itself to the User PATH. Run under Windows PowerShell like its claude/grok siblings, since the script calls `Get-WmiObject`; execution policy is irrelevant here because it governs script *files*, and `iex` on a string does not qualify.

  The same run also offered `grok`, `gemini` and `pi`, all three of which were **already installed**. `Get-TsAppsPending` decides what is missing by reading PATH, but read the PATH the *process started with* — so anything installed since, by an installer that edited the User PATH or by fnm (whose entry is per-shell), reads as missing forever. It now refreshes first via `Update-TsSessionPath`, the counterpart of the `ts_load_node_env` call the POSIX twin has always made. A test pins both halves.

- **The Windows installer crashed partway through the wizard (08/23/2026).** `Read-TsMulti` assigned its exclusive-group helper to `$exclusive` while taking a `[string[]]$Exclusive` parameter. PowerShell variable names are case-insensitive, so those are one variable — and a typed parameter keeps its converter, so the scriptblock was silently coerced into a one-element string array holding its own source text. `& $exclusive -1` then tried to run that text as a command name. Every `Read-TsMulti` call died, taking `install.ps1`, `windows-bootstrap.ps1` and `ts-config apps` with it; the POSIX twin was never affected, because bash keeps functions and variables in separate namespaces. A new test walks the AST of every `.ps1` in the repo and fails on any assignment that shadows a typed parameter by casing alone.

- **Ticking Ghostty silently deselected WezTerm (08/23/2026).** In both wizard twins, the mutual-exclusion collapse was driven by the index of whatever had just been ticked — but that index is only a *winner* when it belongs to the group. Ticking an option outside it handed every ticked member a `$keep` no member could equal, so all of them were cleared. The terminal question is the only exclusive one and Ghostty is its only non-member, so on macOS ticking Ghostty returned Ghostty **alone**, with nothing on screen to say WezTerm had just been dropped. The Windows half was unreachable behind the `Read-TsMulti` crash above. Both twins now no-op when the winner is outside the group, and a six-case matrix pins the two implementations to the same answers.

- **The Windows app catalog offered tools it could never install (08/23/2026).** Three defects that each produced an identical, permanent nag on every `ts-update`.

  `pypa.pipx`, `Python-Poetry.Poetry` and `nicolargo.glances` were all in `$TsWingetIds` and none of the three exists — winget answers "No package found matching input criteria". `pipx` is in the *recommended* set, so it failed on every Windows machine on every run. They are real tools that simply do not ship through winget, so they now route through a new `Install-TsPyTool` (uv first, `pip install --user` as the fallback) alongside `ipython`, `httpie` and `pre-commit`, which Windows had been skipping entirely.

  winget's `aristocratos.btop4win` installs `btop4win.exe`, not `btop.exe`, so `Get-TsAppBin` probing for `btop` reported it missing however many times it was installed.

  And `Get-TsAppsPending` gated on "is it in winget" rather than "can this platform install it", so a machine missing `grok`, `gemini`, `pi` or `cursor-agent` was never told — those install through `Install-TsAiCli`, not winget. The gate is now `Test-TsAppInstallable`, the pwsh twin of `ts_app_installable`. Expect the agent CLIs you are missing to be offered on the next update; that is the intended behaviour and matches macOS and Linux.

  A freshly installed tool is also no longer reported as `NOT FOUND on PATH` seconds later: `Update-TsSessionPath` rebuilds the process PATH from the persisted Machine and User values after an install pass.

- **Headroom authentication, recovery, and Codex routing are now end-to-end safe (08/23/2026).** `/readyz` could succeed while every real request returned Headroom's own 401 because health endpoints bypass proxy authentication. Wrappers now authenticate `/stats` and go direct on failure. Claude preserves provider OAuth and sends `X-Headroom-Proxy-Token` separately. Codex uses a process-local custom `headroom` provider; targeting reserved built-in id `openai` had made every `cy`/`cyr` launch fail during config parsing. Nothing is persisted to provider config.

  `ts-config agents headroom off` immediately restores direct launches and removes terminal-stack-owned MCP registrations without touching Docker or data. `on` and `repair` require authenticated proxy access before enabling; the optional 8788 MCP sidecar is diagnostic only. Live Claude and Codex requests completed through Headroom after reboot, and regression tests cover the provider id, token mapping, authenticated gate, and off switch.

- **`CLAUDE.md` is below Claude Code's 40 KB project-instruction ceiling (08/23/2026).** It had reached 49,309 bytes by duplicating subsystem narratives already maintained in `docs/decisions.md` and `doc`. Those sections are now concise invariants plus canonical links; the file is 38,247 bytes and a regression test enforces a 40,000-byte maximum.

- **`self` voice summaries now work off Windows, and macOS TTS can no longer be silently silent (08/23/2026).** Two independent macOS gaps in the same feature.

  `self` — the mode where the agent writes its own one-line announcement — was implemented only in `ttsd/summarize.py`, which runs inside the Windows-only EXE. On macOS and native Linux it was accepted, persisted, and never read — while `ts-config tts summarizer self` **still** appended the marker block to `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`, so the agent dutifully emitted `<!-- speak: … -->` comments that nothing consumed. Ported to the shell path (`cc_tts_self_summary`), marker-first then a one-sentence fallback capped at 15 words, applied to the *done* event only exactly as the Python does. A test drives both implementations on the same six fixtures and requires identical output. The marker is also stripped from the speech text now: in `hook` message mode the raw final message *is* what gets spoken, so the comment would otherwise have been read out loud.

  And the ladder ended in silence. Synthesis went Kokoro → Chatterbox → edge-tts → **nothing**, while Windows falls back to SAPI; `/usr/bin/say` ships with every Mac and was never used. A Mac with the Kokoro container stopped and no `edge-tts` installed had voice notifications fully "on" and heard nothing — and the worker runs detached with its output discarded, so nothing anywhere said why. `say` is now the floor, with a once-a-day notice so a changed voice reads as "Kokoro is down" rather than "my config broke". One trap worth recording: **`say -o out.mp3` exits 0 and writes a 16-byte junk file** — it picks its format from the extension and only really writes AIFF — so the rung synthesises to `.aiff`, checks the size rather than the exit status, and moves it into place (`afplay` sniffs content, not the name).

- **The WezTerm tick-list pre-selected stable on a machine that had stable (08/23/2026).** It pre-ticked whatever was installed, so pressing Enter — the thing everyone does — silently kept the `20240203` build from February 2024, while row 1 still read "what this stack configures". Upstream has cut no stable since, and this stack's WezTerm config targets current builds, so a default that quietly preserves a two-and-a-half-year-old build is not conservative, it is wrong. **Nightly is now pre-selected on every machine**, with one exception: a WezTerm installed outside a package manager (`ts_wezterm_channel` → `unknown`) still leaves both unticked, because that is not ours to replace. The prompt gained a `RECOMMENDATION:` line saying why, and warning that picking nightly swaps the cask (both own `/Applications/WezTerm.app`).

  Worth recording how this got here: a previous commit "fixed" `CLAUDE.md` and `docs/decisions.md` to match the installed-wins code, having read the code as authoritative. It was the code that was wrong — `CLAUDE.md` had said "nightly is pre-selected" all along. Those doc edits are reverted, and a test now pins the behaviour across all four detected channels so the docs and the code cannot drift apart again.

- **`chezmoi apply` silently never ran at the end of the wizard (08/23/2026).** `ts_report_installed_apps` assigned a four-stage pipeline directly, so under `set -euo pipefail` any tool whose `--version` exits non-zero killed the function — and with it `finish`, so nothing was applied and the run just stopped after printing `==> Installed tools:` with an empty list. **`tmux` is exactly that tool** (it wants `-V` and exits 1 on `--version`) and it is *first* in `TS_APPS_RECOMMENDED`, so this fired on entry one of every single run. The settings saved correctly and then no template was re-rendered, which is why an enabled atuin still had an empty init fragment. Captured before processing now, with a `-V` fallback so tmux even reports a real version.

- **`ts-config wizard` never asked which terminal you wanted (08/23/2026).** Only the bootstraps set `TS_WIZ_ASK_TERMINALS`, so the re-run wizard skipped the question, `TS_WIZ_TERMINALS` came back empty and it reported `Terminal emulator: none selected` — meaning a re-run could not switch WezTerm channel, which is a main reason to run it again. It now asks on any GUI host, same rule as the bootstraps, and like them it saves the answers before installing anything and treats installs as non-fatal.

- **One already-installed app discarded an entire wizard run (08/23/2026).** A live macOS install answered ten questions, printed the Review block, and persisted **nothing** — TTS, headroom, agentmemory and atuin all came out `off`, `apps` held one entry, and WezTerm never switched channel. `ts-smb: command not found` and `atuin stats: Failed to find $ATUIN_SESSION` were downstream of the same cause, not separate faults.

  The cause was one line in `ts_brew_install_apps`: `brew list --cask zed … || brew install --cask zed`. `set -e` exempts only the **non-final** members of an `&&`/`||` list, so the install was never guarded at all. Zed had been installed by hand, Homebrew therefore did not consider the cask present, and the collision error killed the script at **line 55 of 207** — taking the terminal install, Nerd Font, oh-my-zsh, `chsh`, `chezmoi.toml`, every wizard answer and `chezmoi apply` with it, printing nothing of its own. Every neighbouring optional install in that file already ended `|| echo "…failed"`; this was the only one that did not.

  Fixed on both axes, because either alone leaves a hole. **No optional install can be fatal**: new `ts_note_failure` / `ts_report_failures` collect failures and print them at the end, matching the discipline `windows-bootstrap.ps1` already used, and the batched `brew install $formulae` (same `set -e` trap, one bad bottle) is guarded too. **And answers are persisted before anything optional runs** — `chezmoi` moves ahead of the app install on all three bootstraps, since `ts_save_config` needs it for `chezmoi init`; the Debian pair do it through a new `TS_PERSIST_HOOK` that `common_install_all` calls before its first optional step. Only the agent *wiring* stays late, because it needs the agent CLIs. Drilled: with a deliberately failing install, all six settings still persisted.

  `--cask --adopt` was tried for the hand-installed-app case and **rejected** — on a bundle whose xattrs brew cannot rewrite it fails partway and **removes the app it is adopting**, which deleted a real `/Applications/Zed.app` during testing. A hand-placed app is now simply left alone, the same rule `ts_wezterm_install` already applies to a WezTerm outside a package manager. A test bans both `--adopt` and `--cask --force`.

- **`ts-doctor --repair` crashed mid-repair, leaving the machine half-fixed (08/23/2026).** `_doctor.sh` had `"$desired…"` and `"$dst…"` — a **U+2026 with no separating space**. macOS ships bash 3.2, whose `legal_variable_char()` is not multibyte-aware: the UTF-8 lead byte passes `isalnum()`, so the name parses as `desired\xE2`, is never set, and `set -u` aborts. That is the stray byte in the reported error. It fired *after* repointing `sourceDir` and *before* `chezmoi apply`, so the clone moved with nothing re-applied, and the cleanup menu and final verify never ran. Latent since 2026-06-15 because it only bites under `set -u`, which the installers do not set when they source the same file. Braced both, and a test greps for `$var` followed by non-ASCII — `bash -n` cannot see it.

- **The terminal tick-list showed a state it would refuse (08/23/2026).** Ticking WezTerm nightly displayed **both** channels `[x]`, because the one-channel rule ran only after Enter and its note went to stderr. `ts_prompt_multi` and `Read-TsMulti` now take an optional mutually-exclusive group (`TS_MULTI_EXCLUSIVE` / `-Exclusive`), so ticking one visibly unticks the other; rendered output is unchanged, so the byte-identical twin rule still holds. The env path (`TS_TERMINALS=wezterm-nightly,wezterm-stable`) returned early without the constraint on both sides and put both keys in the saved list — now routed through the same helper.

- **Docs claimed the wrong WezTerm default (08/23/2026).** `CLAUDE.md` said flatly "Nightly is pre-selected" and `docs/decisions.md` asserted the installed-wins rule and its opposite two paragraphs apart. The code has always pre-ticked **whatever is installed, on its detected channel**, with nightly the default only when nothing is — which is why a stable machine correctly showed nightly unticked. Corrected in both, plus `docs/kb/windows/winget.md`.

- **`ccd`/`ccdc`/`ccr`/`ccdr` now keep the project name in the tab (08/23/2026).** They set it and always had, but Claude Code overwrote it moments later with `✳ Claude Code` and then its conversation slug. The fix is the other half of the problem rather than a better way to set titles: the wrappers now run Claude with **`CLAUDE_CODE_DISABLE_TERMINAL_TITLE=1`**, so it writes no title at all and theirs survives. Probed in a pty — the default run emits `OSC 0 ✳ Claude Code`, the disabled run emits nothing whatsoever, and the end-to-end before/after is exactly `terminal-stack` → `✳ Claude Code` versus `terminal-stack` alone.

  `_wez_tab_title` becomes `_ts_tab_title` (pwsh: `Set-WezTabTitle` → `Set-TsTabTitle`) and now handles three cases, because only one terminal has a sticky tab title a script can reach: WezTerm keeps `wezterm cli set-tab-title`, a real override; inside tmux it does nothing, because tmux owns the outer title and substitutes `set-titles-string`; everywhere else (Ghostty, Terminal.app) it emits plain `OSC 2`. `ccs` and `ssht` route through the same helper instead of calling `wezterm cli` inline, so they behave outside WezTerm too. Both halves are load-bearing and a control-tested regression pins them together — the `OSC 2` without the env var is overwritten in seconds, and the env var alone leaves whatever the shell last set.

  Ghostty's own sticky `set_tab_title` was ruled out first, not assumed away: it genuinely survives Claude, but nothing can trigger it from a script — `ghostty +new-window` reports "not supported on this platform", and ConEmu's `OSC 9;3`, which is present in the binary and looks like the answer, sets the *surface* title. Running `claude` directly is unaffected and still sets its own title.

- **A Ghostty tab now shows the project name, via tmux (08/23/2026).** `set-titles-string` changes from `'#S:#I.#P #W'` to `'#{s/^cc-//:session_name}'`, so a `ccs` session's tab reads `terminal-stack` instead of `cc-terminal-stack:0.0 claude` — matching the `cc*` wrappers' existing rule that the tab shows the bare project leaf with no `cc` prefix.

  This started as a Ghostty question and ended as a tmux one. Ghostty *does* have a sticky per-tab title — `set_tab_title` is distinct from `set_surface_title` and a title set that way survives Claude Code overwriting the OSC title, confirmed by running Claude in a tab whose title had been set. It is simply unreachable from a script: there is no CLI to drive a running instance (`ghostty +new-window` reports "not supported on this platform"), and no escape sequence maps to it. ConEmu's `OSC 9;3` is in the Ghostty binary and looks like the answer, but testing it showed the tab following `OSC 2` — the *surface* title, which Claude overwrites.

  tmux solves it instead, and terminal-agnostically: while a session is attached tmux **owns** the outer title, intercepting the inner program's `OSC 2` entirely. Verified by capturing what tmux writes to its own pty — it emitted exactly one title, `terminal-stack`, and the inner program's slug never reached the outer terminal at all. `ccd`/`ccdc`/`ccr`/`ccdr` run Claude without tmux and so cannot be helped under Ghostty; the KB page says that rather than implying parity.

  One trap pinned by a test: inside `#{...}` tmux wants the variable *name*. `#{s/^cc-//:#S}` is accepted and silently renders an **empty** string — a blank tab title, worse than the noisy one it replaced.

- **agentmemory captured nothing at all on macOS and Linux (08/23/2026).** The server was healthy, MCP tools resolved and searches returned hits, but not one observation was ever written — and nothing logged it, because every vendor hook does `fetch(...).catch(() => {})` then `exit(0)`. The host-side hook wiring existed only as PowerShell, and `_doctor.sh`'s check for it was gated on `[ -d /mnt/c/Users ]`, so the one thing that would have reported the gap never ran off WSL. Ported to `bootstrap/ts-agentmemory.sh` (the exact path `docker-local/agentmemory/check-capture.sh` probes), `_agentmemory.sh` and `_merge_json_settings.sh`, leaving the `.ps1` files untouched. Wired into `ts-agents.sh`'s `agentmemory on|repair|off`, and the WSL-only doctor gate removed.

  Exactly two behaviours had to change, and both fail *silently* if got wrong: the stale-secret recovery now reads the 0600 cache under `XDG_CONFIG_HOME` instead of `reg query HKCU\Environment`, which on Unix throws, is caught, and leaves the recovery a permanent no-op; and hook commands are a POSIX `VAR=value node "<path>"` prefix instead of a cmd.exe `set X=…&&` chain. Both env vars stay inlined per command rather than inherited — an exported variable only reaches processes started after it was set, which is why long-running shells and desktop apps retrieved nothing.

  Three engine findings, each caught by a drill rather than by review. The literal multi-line replace runs in **python3**, because `${x//a/b}` treats the needle as a glob and `sed` is line-oriented and appends a trailing newline to a file that lacked one. Python must read with `newline=""`: with translation on, a CRLF vendor file (the `~/.codex` copies) is silently rewritten to LF wholesale and the CRLF matching branch can never fire. And **inserted text must follow the file's line endings, not the matched form's** — a single-line anchor like `function authHeaders() {` is byte-identical in both, so deciding from the match leaves a CRLF file mixed. Unlike the `.ps1`, which reports problems and still exits 0, this exits non-zero in every mode so a caller can tell a clean apply from a moved anchor.

  Drilled against a fixture `HOME`, never real agent config: all 23 deployed scripts pass `node --check`; a second `--apply` reports `already` and re-patches nothing; a mangled vendor file throws and exits 1 rather than skipping; `--undo` restores every vendor `.mjs` byte-identical; a foreign Cursor `stop` hook (this repo's own TTS entry) survives both apply and undo, which is the per-entry ownership that once got Cursor's `hooks.json` emptied; and Claude's `settings.json` keeps `model`, `enabledPlugins`, `permissions`, `statusLine` **and its `//` comments** across the `env` splice.

- **The headroom image pin no longer resolved (08/23/2026).** `agent-tools.json` pinned `ghcr.io/chopratejas/headroom:0.36.3`, whose manifest now 404s; the live image is `ghcr.io/headroomlabs-ai/headroom:0.36.5`, which returns 200. Both verified against the ghcr registry API rather than assumed.

- **The prompt's command-duration ran into the path, and every Nerd Font glyph had been stripped (08/23/2026).** Two bugs in `dot_config/starship.toml.tmpl` and its Windows mirror. First, outside a git repo the prompt rendered `…/github.comtook 3s`: `[directory] format` ends at `$path` with no trailing space and `[cmd_duration] format` began with a bare `took`, and `$git_branch` — four leading spaces — was the only thing normally separating them. Inside a repo it looked fine, which is why it survived. `cmd_duration` is now `" [\uf252 $duration]($style)"`: a leading space fixes the collision by construction, the timer glyph replaces the word `took` (five columns narrower, and starship cannot measure remaining width to shorten conditionally), and the *trailing* space is dropped because `$fill` follows immediately and would otherwise eat a dot.

  Second, and larger: every Private-Use-Area glyph in the file had been silently stripped by an editor — exactly what the file's own header warned would happen — leaving all 19 `[os.symbols]` entries as `""` and the folder, octocat, branch, clock and lock glyphs as bare padding spaces. The prompt had been rendering with no icons at all. All of them are restored as `\uXXXX` escapes, and every codepoint was checked against `JetBrainsMonoNerdFont-Regular.ttf` with fontTools first, because a valid escape for a codepoint the font lacks renders as a tofu box — worse than the blank it replaced. Deleting `[os.symbols]` to inherit starship's defaults was considered and rejected: its built-in `Macos` symbol is 🍎, a colour emoji, not a Nerd Font glyph. `docs/verifying-changes.md` gains the PUA scan, the render check and the font-coverage check so the strip cannot recur unnoticed.

- **`ccd` and every other `cc*` wrapper were dead in every top-level login shell (08/23/2026).** `dot_zshrc` resolved the Claude and Codex binaries into `_TS_CLAUDE_BIN` / `_TS_CODEX_BIN` at line 213, but `export PATH="$HOME/.local/bin:$PATH"` — where the native installers put those CLIs — did not run until line 871, 658 lines later. In any shell that did not inherit `PATH` from a parent (i.e. every fresh WezTerm/Terminal tab), the snapshot was empty and `ccd` answered `claude executable was not found on PATH when this shell loaded` with `claude` sitting installed at `~/.local/bin/claude`. Reproducible in one line: `env -i HOME=$HOME zsh -lic 'echo "[$_TS_CLAUDE_BIN]"'`. The regression arrived with the wrapper functions in `8de3df0`; before that the wrappers invoked bare `claude`, which zsh resolved lazily and therefore correctly. Two fixes, because there were two bugs: the PATH export moved to the top of the file, and resolution moved from shell-load to **call time** via a shared `_ts_agent_bin` (modelled on `_ts_chezmoi`, including its literal `~/.local/bin` fallback) that `rehash`es first, caches the hit in the caller's shell, and re-checks `-x` so a garbage-collected `~/.local/share/claude/versions/*` self-heals. Installing an agent CLI into an already-open shell now works in that shell. The PowerShell twins had the same load-time snapshot and got the same treatment in `Get-TsAgentCommand`, which additionally re-reads `PATH` from the registry before giving up — a just-run installer sets the User `PATH`, but the running process still holds the copy it started with. `c` (Cursor) had a third variant of the bug: `command -v cursor && c() { ... }` gated the *definition*, so installing Cursor's shell command mid-session left `c` silently undefined; it is defined unconditionally now and checks inside. Six new regression tests, including a live `zsh` one that plants a binary after shell load and asserts the resolver finds it; all four fail against the previous commit.

- **`chezmoi apply` was deleting keys Claude Code writes to `~/.claude/settings.json` (08/23/2026).** `docs/decisions.md` predicted this exactly — the POSIX-side whole-file target was "correct only as long as WSL-side Claude Code has no plugins and no per-machine keys" — and macOS reached that day: an apply wanted to drop `agentPushNotifEnabled`, silently and with nothing in the diff to explain it, the same failure that disabled the agentmemory plugin on Windows in August. `dot_claude/settings.json.tmpl` is now `dot_claude/modify_settings.json.tmpl`, a chezmoi `modify_` script that receives the live file on stdin and returns it with only the stack-owned keys replaced. Ownership is derived from the rendered fragment rather than a hard-coded list, exactly like `bootstrap/_merge_claude_settings.ps1`, so the two platforms cannot drift; a live file that will not parse is echoed back untouched rather than overwritten.

- **The pytest suite was being installed into `$HOME` (08/23/2026).** `tests/**` was missing from `.chezmoiignore`, so `chezmoi apply` deployed `tests/test_agent_tools.py` and `tests/test_codex_dashboard.py` to `~/tests/` — the same trap that put the installer entry points there and the reason they are listed. Ignored now. A `.chezmoiremove` entry cannot clear the existing copies (chezmoi skips ignored paths entirely), so they are retired through `ts_find_stray` in `bootstrap/_cleanup.sh` and cleaned up by `ts-doctor --repair` / the installer's cleanup menu.

### Changed

- **The WezTerm channel is a question again, answered with real build dates (08/23/2026).** Earlier today this shipped as stable-only. That was wrong for one reason: upstream's newest *stable* is `20240203-110809` — February 2024, with no cut since — so "stable" means a two-and-a-half-year-old build, while nightly is what @wez daily-drives and what this stack's Lua config targets. Both channels are offered now, as separate ticks in the emulator list (`WezTerm nightly`, `WezTerm stable`, `Ghostty`), with **nightly pre-selected** — and **nothing is automatic**: the wizard asks at install, `ts-update` reports and offers when something newer exists on the channel you are already on, `ts-config wezterm` (and standalone `ts-wezterm`) changes it on demand, and a non-interactive run prints the command instead of running it. Ticking both WezTerm rows installs nightly and says so; the two packages install to the same place, and switching channel now uninstalls the other **in both directions** rather than the old unconditional nightly purge, so a machine that declines WezTerm keeps whatever it had.

  **The prompt shows facts, not just a default** — a choice between "stable" and "nightly" is meaningless without knowing one is from 2024 and the other was rebuilt this morning. New `bootstrap/_wezterm.sh` (+ the `*-TsWez*` twins in `_config.ps1`) reports your build and its date, the newest on each channel, and a count of what changed in between, all derived without an LLM: the build date is **in** the release name (`<YYYYMMDD>-<HHMMSS>-<githash>`), so `wezterm --version` dates your install with no network call; latest-stable is the `releases/latest` tag; latest-nightly is the `updated_at` of the nightly asset **for your platform**, because the rolling tag's own date is stuck in 2019 and per-platform builds diverge (Debian10's last built over a year ago, Debian12's today); and "what changed" is sliced out of upstream's own `docs/changelog.md` at the heading matching your version — their notes, counted per `Changed/New/Fixed/Updated`, with `ts-config wezterm changes` paging the full text through the same reader `doc` uses. A nightly has no changelog heading to anchor on, so the commit count from the compare API is the honest answer there. Every network call fails **open and silent** with a timeout, preferring `gh api` (5000/hr) over the bare REST endpoint (60/hr).

  **Still no `weztermChannel` key.** The channel is read back from the package manager (`brew list --cask`, `winget list --id`, `dpkg -s`), which cannot drift out of sync with what is installed and picks up a manual `brew install` on its own — the same auto-detected-with-no-saved-setting reasoning as the agentmemory wiring, and it keeps the seven-file blast radius out of this entirely. A WezTerm no package manager owns reports channel `unknown`: version and date still shown, install and upgrade leave it alone. Fixed while here: the bash `run_wizard` never installed the emulator it had just asked about, while the pwsh twin always did. Rationale in `docs/decisions.md` § "Why the WezTerm channel is a question, and why it is not a saved setting"; new `doc wezterm` KB page.

- **New `ts_prompt_multi` / `Read-TsMulti` — the wizard can ask questions with more than one answer (08/23/2026).** Modelled on `ts_cleanup_menu`'s checklist, which was already the house style for a multi-select but was welded to the cleanup flow. Renders `[x] 1) label  (note)`, accepts several toggles in one answer (`1 3` and `1,3` both work — deliberately **not** `ts_prompt_choice`'s strip-all-whitespace, which would fuse them into `13`), and takes `[a]ll` / `[n]one` / `[s]kip` / Enter. Non-interactive keeps the pre-ticked defaults instead of blocking. Answer matching is factored into `ts_resolve_multi_answer` / `Resolve-TsMultiAnswer` so the rules are testable without a terminal, following `Resolve-TsChoiceAnswer`'s precedent. The two implementations must stay byte-identical, same rule as `ts_prompt_choice`/`Read-TsChoice`.

### Added

- **The app catalog is grouped, and 15 tools wide (08/23/2026).** The picker gained two answers between "everything" and "one at a time": **choose whole groups** (`shell`, `search`, `disk`, `system`, `network`, `git`, `editors`, `ai`) and **choose individual tools**, which walks the groups as one tick-list each rather than 30 consecutive Y/n prompts. New in the catalog: `fd`, `tree`, `duf`, `ncdu`, `dust`, `gdu`, `btop`, `bottom` (binary `btm`), `glances`, `bandwhich`, `gping` — mapped for brew, apt and winget, with GitHub-release fallbacks for the several that are in no Debian or Ubuntu archive. **`fd` closes a real gap**: `README.md` has always said the WezTerm project picker needs it, and nothing installed it on any platform. Debian names it `fdfind`, so it gets the same `~/.local/bin` symlink `batcat` already had. Existing machines are offered the additions automatically — `ts_apps_pending` unions the saved selection with the recommended set, which is exactly what that design is for. **Groups are a picker concern only**: the saved `apps` array stays flat, so this adds no chezmoi `[data]` key and none of the seven-file blast radius one costs. Also fixed while in there: the `eza`, `delta` and `lazydocker` GitHub fallbacks hard-coded `x86_64`, so they silently missed on every arm64 box; all of them use `common_arch_tag` now.

- **All five agent CLIs install for real, and the group defaults to all (08/23/2026).** `claude`, `codex`, `cursor-agent`, `grok` and now **`gemini`** are a pre-ticked group in the picker — still asked, still individually untickable, never installed silently. None come from a package manager, so they route through `ts_install_ai_cli` / `Install-TsAiCli` rather than brew/apt/winget: claude, grok and cursor-agent have native installers needing no Node at all; codex (npm `@openai/codex`, Node 16+) and gemini (npm `@google/gemini-cli`, Node 20+) are gated on the Node version and print what to do instead of failing. **grok is no longer a placeholder** — xAI ship a standalone binary via `x.ai/cli/install.sh`, which also means it needs no Node. Two traps found while wiring it: its installer **appends a PATH line to `~/.zshrc`**, a file this stack owns whole-file, so the next `chezmoi apply` would silently delete it — `GROK_BIN_DIR="$HOME/.local/bin"` routes the binary onto the already-managed PATH instead, and `dot_zshrc` carries its completions `fpath` itself. And there is deliberately **no brew fallback for gemini**: the `gemini-cli` formula is deprecated upstream and scheduled for removal on 2026-12-18, so installing from it would hand you a dead end. Note both grok and cursor-agent claim a generic `agent` symlink, so whichever installs last wins that name; both always work under their own.

- **Node and Python are in the questionnaire (08/23/2026).** Two new groups. **`runtimes`** carries `fnm` and `node`: fnm rather than nvm because nvm costs 200-500ms on every shell start and fnm about 10ms, while reading the same `.nvmrc`/`.node-version` files — wired into both shells with `--use-on-cd`. Picking `fnm` also installs the current LTS, since the manager alone leaves you with no runtime and every npm-based agent CLI would still decline. **`python`** carries `python`, `uv`, `pipx`, `ruff`, `ipython`, `httpie`, `poetry` and `pre-commit`; `pip install` into the system Python is blocked by PEP 668 on modern Homebrew and Debian, so global Python CLIs go through `uv tool` / `pipx`. One subtle fix came with it: global npm binaries live under whatever Node fnm has active and fnm's PATH entry is created **per shell**, so `ts_apps_pending` (which `ts-update` runs in a bash subshell) could not see `codex`/`gemini` and would have nagged about them forever — both it and the install report now call `ts_load_node_env` first. New `doc node-python` KB page.

- **`ts-config wizard` — re-run the whole questionnaire (08/23/2026).** `ts-config apps` re-asks one question; this replays every prompt the installer asks — leader, theme, terminal emulator, apps, mux, restore, TTS, agent tools — and persists all of it, which also sidesteps `ts_save_config`'s "re-state every other value or lose it" trap since every value is being re-stated anyway. `TS_ASSUME_YES=1 ts-config wizard` is the non-interactive reset, and the per-question `TS_*` vars still skip individual prompts. Reachable as `w` from the interactive menu in both shells. The Windows side needed a structural fix first: `Read-TsWizard` and `Install-TsTerminals` lived in `windows-bootstrap.ps1`, so `$PROFILE` could not reach them and would have had to duplicate every prompt's wording — they moved to `bootstrap/_config.ps1`, matching the POSIX layout where `ts_wizard_collect` lives in `_wizard.sh` and both callers source it. `Install-TsTerminals` uses `Install-WingetPackage` when it is in scope and falls back to a direct winget call when it is not, so the bootstrap keeps its end-of-run failure report.

- **Installs report what actually landed (08/23/2026).** `ts_report_installed_apps` / `Show-TsInstalledApps` print each selected id, the binary it resolves to and its `--version`, or `NOT FOUND on PATH`. A curl-pipe installer that failed quietly is now visible instead of assumed, and the footer reminds you to `exec zsh` — the `command -v` gates for zoxide/fzf/eza/bat in `dot_zshrc` are evaluated at shell load and will not pick up a tool installed mid-session.

- **`db` / `dbx` — jump to Dropbox, in both shells (08/23/2026).** Sits alongside `ws`/`wsp`/`wspu`/`wsw` and follows the same rules: a shell function (a child process cannot `cd` its parent), resolved at call time, `$DROPBOX_DIR` / `$env:DROPBOX_DIR` overriding an autodetect. It reads Dropbox's own `info.json` before guessing at paths, because that file is the only thing that gets a relocated folder, a Business account, or two linked accounts right; the path candidates are the fallback. macOS Ventura moved the folder to `~/Library/CloudStorage/Dropbox`, so that is probed ahead of the classic `~/Dropbox` that Linux and older macOS still use, and under WSL it looks at the Windows store through `/mnt/c/Users/<you>/` via the same interop username lookup the sync hook uses.

- **Per-computer Headroom, Caveman, and AgentMemory lifecycle management (08/22/2026).** `ts-config agents` now installs, enables, repairs, disables, reports, and uninstalls user-global agent integrations without touching a project repository or Docker. Four mirrored settings (`headroomEnabled`, `headroomCursorMode`, `cavemanEnabled`, `agentmemoryEnabled`) let every computer differ; fresh installs default off while an existing AgentMemory plugin migrates on. The reviewed manifest pins Headroom 0.36.3, Caveman 2.2.0, and AgentMemory 0.9.29. Headroom uses the always-on docker-local proxy/dashboard on 8787 and separate HTTP MCP sidecar on 8788, routes Claude and enhanced Codex only for the child process, restores every environment variable on exit, and fails open to the provider when Docker is unavailable. Cursor explicitly chooses MCP-only subscription-safe mode, BYOK proxying, or off. Caveman installs only its one terse-output skill and a marked global Codex rule; Cursor's global rule remains a documented one-time UI step. `ts-update` reconciles only enabled tools, all JSON edits preserve foreign entries, and `claude-stock` / `codex-stock` stay direct escape hatches. Live smoke tests verified Claude/Anthropic and Codex/OpenAI traffic in Headroom with zero failures, plus Caveman full-mode activation in a fresh Claude session. Eight new regression tests cover pins, scope, config preservation/migration, MCP merge ownership, wrapper isolation, update gating, and shell parsing.

- **The dashboard configures, and can prove a summarizer mode works (08/21/2026).** A Settings tab covering every setting the daemon reads, the Anthropic key, and a test that reports what actually ran. Writes go to `local.json` as machine-local overrides, and every field shows which layer won and says so when an override is beating the saved value, because a change that appears to do nothing was the confusion this feature exists to end. New `ttsd/settings_schema.py` is the single list the server validates against and the page renders from: the enums previously existed only in `tray.py`, `_cc_tts.sh` and `_config.ps1`, and `write_local` accepted any dotted path with any value. Two tests check the schema's own claims against the code, so a `restart`-flagged key must really be read in `_build` and a `shell`-only key must appear nowhere the daemon reads config. The haiku model became a closed list rather than free text, since `max_tokens` is 60 and that interacts badly with a model that thinks by default. **Writes now require `X-TS-Token` even on loopback**, which also closes an existing hole: a cross-site form POST could previously mute the machine, because `/v1/mute` mutated on an empty body. `/v1/event`, `/v1/config/reload`, `/v1/duck/release` and `/v1/shutdown` stay open deliberately, since hooks and the installer call them without a token. The restart button spawns a replacement that waits for the port before binding, because otherwise it would see a healthy daemon, exit as designed, and leave nothing running. Both streams are newest-first with a sort toggle. New `tests/test_daemon_smoke.py` starts a real daemon and talks to it, which exists because a startup-path `NameError` slipped past 124 unit tests: nothing else in the suite calls `main()`. 32 new tests, 136 total. Rationale in `docs/decisions.md` §§ "Why the dashboard writes only local.json, and needs a token to do it" / "Why the summarizer test reports rather than just speaks".

- **A TTS dashboard at `/ui`, opened from the tray (08/21/2026).** Status, a decision timeline, and a live log stream, served by the daemon on loopback. Two panels rather than one because they answer different questions: the raw log says what the daemon is doing, including engine errors that never reach a decision, while the timeline from `history.db` says what it chose and why (`spoken`, `deduped`, `muted`, `suppressed_dnd`, `synth_failed`) and survives rotation and restarts. New `ttsd/webui.py` holds the page as a string literal, not a bundled asset: the `_MEIPASS` path would degrade silently to serving nothing from a healthy daemon. New `ttsd/logtail.py` follows `ttsd.log` without ever holding it open, because `RotatingFileHandler` renames the file and on Windows a reader with the handle open can make that rename fail *inside the handler*, breaking the daemon's own logging in order to display it; it also detects rotation by the file shrinking, decodes with `errors="replace"` since a byte offset can land mid-codepoint, holds back partial lines, and treats an unparseable line as a continuation rather than dropping it. Streaming is SSE with the connection explicitly closed (HTTP/1.1 keep-alive plus no `Content-Length` would hang the browser) and a stop flag the shutdown path sets, since `listener.shutdown()` says nothing to a response already in progress. Every route now refuses an unrecognised `Host` header: loopback is unauthenticated, any web page can reach 127.0.0.1, and without that check DNS rebinding could read your history. Read-only; the settings form, the per-mode summarizer test and the restart button are the next stage. Verified against the frozen EXE: `/ui` 200 with the page, a foreign `Host` 403, SSE delivering both the backlog and live lines parsed into fields, and a `muted` decision landing in the timeline. 15 new tests, 104 total. Rationale in `docs/decisions.md` § "Why the dashboard is a page served by the daemon".

- **The TTS daemon can now be asked why it did not speak (08/21/2026).** Groundwork for an in-app dashboard, and useful on its own. Every summarizer fall-back-to-template is counted with a reason and surfaced on `/v1/status` as `summarizerDegraded` and `summarizerLastDegrade`, warned once per reason per process rather than once per announcement. Before this, selecting `haiku` with no API key was **byte-for-byte indistinguishable from `template`**: no exception, no log line, no counter, and `/v1/status` still reporting `summarizerMode: haiku`. New `ttsd/keystore.py` stores the Anthropic key in `state/secrets.json` beside `token` and `history.db`, because an autostarted daemon inherits only the logon environment and so an exported variable never reaches it, and because neither config store is a safe home for a secret (one is tracked in git, the other is what people paste into bug reports). It refuses any name outside a fixed allow-list, writes atomically, never rewrites a file it cannot parse, and `describe()` returns where a key came from and its last four characters but never the value. The environment variable stays supported as a fallback. `ts-doctor` gained the long-promised **config-store divergence check**, outside the `ccTtsEnabled` gate on purpose since the failure is one store saying off while the other says on, plus a check that any TTS hook exists at all, which is the one-line version of the outage above. The tray icon now distinguishes three states rather than two: armed, muted (grey with a slash) and disabled (hollow outline, tooltip naming the missing hooks). 26 new tests, including the first coverage the `haiku` and `ollama` paths have ever had.

- **An absolute mute you can reach four ways (08/21/2026).** Silencing agent speech for a call used to mean `cctts off`, which rewrites the saved setting, removes the hooks and takes 5-15 seconds of scrolling output; or the tray's `Do not disturb`, which did almost nothing useful. New `ccmute` (either shell), a left-click on the tray icon, a global `Ctrl+Alt+Shift+M`, `Leader+m` in WezTerm, and `POST /v1/mute` all write one sentinel file (`state\muted`, new `ttsd/mute.py`) that `submit_hook`, `direct_speak`, the dispatcher and the native-WSL hook all read - so it holds with the daemon stopped, survives a reboot, and is **absolute**: questions, permission prompts and errors are silenced too. Muting also cuts off the utterance in flight, which nothing could do before (`Playback` now publishes the active WinRT player so `stop()` can end it, degrading to "let the sentence finish" if the cross-thread COM call fails). Sticky by choice - a mute that expires back into a call is worse than one you have to clear. It fails *open*: an unusable state directory reads as not muted, the opposite of the history store's bias, because a mute you cannot lift is indistinguishable from broken TTS. Three places report it - the tray icon greys out with a slash, WezTerm shows a `MUTED` chip (polled at most once a second; `update-status` runs at 10 Hz), and `ts-doctor` names it, along with a `local.json` `enabled:false` mask that hid a mute for an afternoon while `cctts` reported ON. `cctts` in both shells now reads the *effective* merged config instead of two different files. Rationale in `docs/decisions.md` § "Why the mute is a sentinel file, not the tray's DND".

- **`ts-agentmemory` — the agentmemory harness wiring now lives here, and repairs itself (08/21/2026).** Wiring Claude Code, Codex and Cursor to a local agentmemory server used to be four scripts in the `docker-local` repo, next to the compose file. That was proximity, not design: this repo already manages `~/.claude/settings.json`, `~/.cursor/hooks.json` and `dot_codex/**`, and `bootstrap/_merge_claude_settings.ps1` / `bootstrap/_merge_cursor_hooks.ps1` exist specifically to stop agentmemory's hook entries being clobbered. One installer (`bootstrap/ts-agentmemory.ps1`) over one edit set (`bootstrap/_agentmemory.ps1`) replaces the four, and **both sync paths run it**, so a plugin upgrade — which replaces the vendor caches and silently reverts every edit, turning retrieval off with nothing in any log — is now repaired by the next `ts-update` or `chezmoi apply` instead of needing a manual re-run nobody remembered. `ts-doctor` reports the same condition. Auto-detected per host from the plugin cache, so there is no new `[data]` key to diverge between the two config stores. Also fixes duplicated Codex retrieval: its two hook registrations meant the same ~5.7 KB context block was fetched and injected **twice per prompt**, and since Codex exposes no way to disable one registration, the duplicate is now dropped inside the hook by an atomic `openSync(..., "wx")` marker — before the request, keyed on everything *except* the timestamp each process stamps for itself, and failing open so a broken guard degrades to duplicate-but-working rather than dropping capture. Rationale in `docs/decisions.md` § "Why the agentmemory harness wiring lives here".

### Fixed

- **A single bad byte in `local.json` destroyed every other override (08/21/2026).** `Config.write_local` was a read-modify-write whose `except ValueError: data = {}` meant an unparseable overlay caused the *next* write to replace the whole file with a one-key document. It also wrote in place, so a crash mid-write left truncated JSON, which `Config.reload` discards wholesale and which presents as every local setting reverting at once, and it took no lock, so a tray toggle interleaving with another writer lost one of the two. Now atomic (temp file plus `os.replace`), locked by exclusive-create with a stale reclaim, and a corrupt overlay is preserved as `local.json.bad.YYYYMMDD` under the repo's dated-backup rule rather than overwritten. New `write_local_many` writes N fields in one pass, which is the workload that made the old behaviour dangerous. Rationale in `docs/decisions.md` § "Why `local.json` writes are atomic, locked, and refuse to destroy".

- **The Windows config mirror was never written from WSL, which silently deleted every TTS hook (08/21/2026).** Presented as a running, unmuted tray icon that never spoke. `ts_mirror_windows_config` resolved the Windows username from `[data].windowsUsername` only and returned **success** when that key was absent, so on a machine whose clone predates the bootstrap recording it, no WSL-side save ever updated `%LOCALAPPDATA%\terminal-stack\config.json`. The stores drifted, and because `scripts/sync-windows.ps1` gates the TTS hook tokens on the mirror's `ccTts.enabled`, a stale `false` there made the next pwsh sync strip all four Claude TTS hook entries from `~/.claude/settings.json` while `ccTtsDaemon` stayed on independently. Measured on the live machine: chezmoi `[data].ccTtsEnabled = "true"`, mirror `false`, zero TTS commands in `settings.json`. The writer now uses a shared `ts_win_user` carrying the same chezmoi-then-interop order the sync hook, `ts-mux` and `ts_canonical_clone_dir` already used, and warns rather than reporting success when the username cannot be resolved. Fixing it revealed the cost the no-op had hidden: 49 `chezmoi execute-template` spawns, **229 seconds** for one mirror write. Batched to **14 seconds** with byte-identical output, via `ts_data_prefetch` (one render for every plain key, cached, with a marker distinguishing cached-empty from never-fetched) plus one shared render for the six derived expressions. Rationale in `docs/decisions.md` § "Why the Windows mirror is written from a resolved username, loudly".

- **Claude was capturing 1041 observations per 5.7 hours and retrieving once (08/21/2026).** Diagnosed from the console request feed after few retrievals were noticed while Claude built in one repo and Codex in another. Capture was perfect; retrieval was thin, and the cause was our own wiring: `bootstrap/_agentmemory.ps1` withheld the *prompt-level context retrieval* edit from Claude behind `if ($Agent -ne 'claude')`, and `bootstrap/ts-agentmemory.ps1` never included `prompt-submit.mjs` in Claude's patch set at all, so it could not have applied anyway. The stated reason — Claude "already retrieves on file tools and at session start" — does not survive contact with real work: `/enrich` fires only for the vendor allow-list, **`Bash` is excluded** by both the `hooks.json` matcher and that list, and a path-less `Grep`/`Glob` is dropped, so a shell-heavy session retrieved nothing between session start and the first file edit. Claude's only `/context` caller was `pre-compact.mjs`, which is why the count was one — a compaction. Fixed by applying the existing edit to every agent (the vendor script is byte-identical across hosts, so the anchors needed no `Alternatives`) and adding the script to Claude's list; the shell denylist stays Codex/Cursor-only, since Claude's allow-list plus matcher is a different mechanism. Verified live: the patched hook injects a 653-token project context block where it previously produced nothing, with no duplicate `/context` within the dedupe window. Rationale in `docs/decisions.md` § "Why every agent gets prompt-level retrieval".

- **A stale `AGENTMEMORY_SECRET` silently destroyed 56 consecutive captures (08/21/2026).** A User environment variable only reaches processes started after it was set, so rotating the secret leaves every long-lived shell holding the old one — and every request from a session it launches returns 401. Found in the feed as a thirteen-minute blackout (`session/start`, `observe`, `enrich`, `session/end`, all rejected) with **nothing in any log**, because capture swallows errors in `.catch(() => {})` and retrieval discards non-2xx behind `if (res.ok)`. Hooks now re-read the authoritative value from the user environment on a 401 and retry once, caching it for the process; the recovery wraps `fetch` once per script rather than each of a dozen call sites, and fails open on every path, so it can only turn a silent failure into a success. It also covers a secret missing from the process entirely. A user environment that is itself stale relative to the container cannot be recovered locally, so `ts-doctor` now compares the two and reports the mismatch — bounded with `timeout` and skipped when Docker is unreachable. Rationale in `docs/decisions.md` § "Why a 401 refreshes the secret from the user environment".

- **Dropped the `PermissionRequest` TTS hook, which only ever said the tool name twice (08/21/2026).** Its `override` is `tool_name`, and `summarize.py` already renders that into the permission template before appending the same string again - "Claude. alpha wants to run AskUserQuestion. AskUserQuestion". `Notification` announces the same prompts in Claude's own words ("Claude needs your permission to use Bash") and the actual question text comes from the `AskUserQuestion` `PreToolUse` hook, the only place `_first_question` runs. Dedupe made the redundancy worse rather than harmless: `recently_spoken` is first-wins, not best-wins, so which of the three sentences you heard depended on which hook Claude fired first. Removed from all three render paths (both sync scripts and the WSL template), with the `permission` state left working for Cursor and `ts-config tts test`. Accepted cost: permission prompts can no longer be muted separately from questions via the `events` list - the absolute mute covers that case now. Rationale in `docs/decisions.md` § "Why `PermissionRequest` was dropped from the Claude TTS hooks".

- **`ts-update`, `ts-config` and the install wizard no longer break in a strict session (08/21/2026).** `Set-StrictMode` is session-scoped and inherited, so any shell that has it on — for reasons that need have nothing to do with this repo — turned three latent patterns into terminating errors. `Resolve-TsSourceDir` assigned `$stalePin` only inside its dangling-pin branch and read it unconditionally, so `ts-update` and `ts-config tts …` failed before doing any work, reporting an internal variable name. `Read-TsChoice` rendered its optional `Note` column with `$o.Note`, killing the install wizard on its first question, whose options carry no `Note`. And `Get-CcTtsConfig` probed for members added in later versions using the very dot syntax that throws on a missing member. Fixed by initializing the variable, reading optional hashtable keys by index, and adding `Get-TsProp` — a strict-safe optional-property read over `PSObject.Properties` — used for every `ConvertFrom-Json` field on the `ts-config` path. Verified by dot-sourcing both files under `Set-StrictMode -Version Latest` and exercising the wizard prompt, a config with no `ccTts` key, and a dangling `TERMINAL_STACK_DIR` pin (which must still degrade to the candidate search, not dead-end). Rules and a one-line reproduction in `docs/powershell-quirks.md` § "The caller's session may have `Set-StrictMode` on".

- **Duplicate and overlapping TTS, and the fifteen hours of silence that hid it (08/21/2026).** Three separate causes, all live. One `AskUserQuestion` trips **three** Claude TTS hooks (`Notification`, `PermissionRequest`, the `AskUserQuestion` `PreToolUse` matcher); all are `P0_INTERACTIVE` and `collect_due` drains `P0` immediately, so the first is spoken and gone ~2.5s before the next arrives and the scheduler's `(session, priority)` pending slot never holds two at once — nothing in memory to compare against. Second, `direct_speak` had no serialization at all: the machine-global play lock was removed when the single dispatcher thread replaced it, but the daemon-down path spawns a **detached process per hook**, and `debounceSec` had survived in `config.py` with no reader anywhere. Third, autostart is logon-only with no watchdog, so a daemon that died at 22:17 was still dead at 13:30 the next day — no error, nothing in the log — and every hook in between quietly took that unserialized path and exited 0. Fixed with one mechanism for the first two: a SQLite utterance history (`state\history.db`, new `ttsd/history.py`) recording one row per **decision** — `spoken`, `deduped`, `suppressed_dnd`, `synth_failed`, `failed` — which both the daemon and every direct worker consult before speaking, so dedupe holds across processes; plus an atomic `O_CREAT|O_EXCL` play lock (`ttsd/speaklock.py`) on the direct path, re-checking the history *inside* the lock, which is what actually collapses the burst. For the third, a hook that finds the daemon enabled but unreachable now starts it and retries once — safe to race, since the losing spawn fails to bind and exits. Everything fails open: an unusable database, lock or log must never stop an announcement. Drilling that with `LOCALAPPDATA` pointed at a regular file also found two **pre-existing** crashes on the way to speech — `_setup_logging` and `_spawn_direct` both ran `mkdir` unguarded, and the latter sat outside the `try` whose `False` return is what makes `submit_hook` fall back to speaking in-process. New `ts-config tts history [--dupes]` in both shells (one implementation: both run `terminal-stack-tts.exe history`, which reads the database directly so a dead daemon can still explain itself), `/v1/history` on the daemon, and `ts-doctor` now reports how long the daemon has been silent and flags sessions that spoke twice. Verified against the built EXE: three hooks fired together produce one `spoken` and two `deduped`, sequential audio, `--dupes` clean. 46 tests. Rationale in `docs/decisions.md` § "Why duplicate speech is collapsed by a history table".

- **Documented the config-store divergence that silently removes settings (08/21/2026).** The chezmoi `[data]` ↔ `config.json` bridge is one-way: a bash save writes both stores, a pwsh save writes only the mirror. On a combined Windows+WSL machine that is a silent divergence — each apply path reads only its own store and renders a valid file from it, so whichever ran last wins and the setting flips back and forth with no error and a diff that looks deliberate. Found live: `ccTtsEnabled` was `false` in `[data]` and `true` in the mirror, so a `chezmoi apply` from WSL removed all five Claude TTS hooks while every `ts-update` from pwsh put them back. Repaired with `ts-config tts on` from WSL (the only path that writes both). Written up in `docs/decisions.md` § "Why config lives in chezmoi `[data]` + a Windows JSON mirror" with the comparison commands, stated as a consequence rather than a style preference in CLAUDE.md, added to `docs/verifying-changes.md` § 4 as a required check for any new config key (apply from both sides, confirm the target is byte-identical after each), and given a user-facing "Voice went silent after an apply" section in `doc windows/tts-daemon`. Nothing yet *detects* the divergence — `ts-doctor` is the natural home for a check that walks the shared keys and reports disagreements. (Added later the same day: see the config-store divergence check in the entry above.)

- **Docs no longer tell you to `chezmoi re-add ~/.claude/settings.json` (08/21/2026).** `ARCHITECTURE.md` still described that file as whole-file-managed on both sides and offered the re-add as the way to capture a `/config` change — advice that now commits Claude Code's private state (`enabledPlugins`, `permissions`, and anything in `env`) into the tracked template, where the next apply pushes it to every machine. Corrected there and in CLAUDE.md's apply-workflow snippet, with the part-owned files named in both. Also swept the passing mentions: the `windows/` tree in `ARCHITECTURE.md` now shows both spliced destinations, `doc common/claude-code` gained a "Who owns `~/.claude/settings.json`" section (including that a plugin dropping out of `enabledPlugins` fails silently, and where to look), `doc common/tools/cursor` records that your own Cursor hooks survive an apply, the TTS verification step no longer implies a one-entry `stop` array, and `docs/powershell-quirks.md` § "Cross-shell quoting traps" documents the MSYS `/d /s /c` argument rewriting that made a working Cursor hook look broken during verification.

- **The sync no longer empties Cursor's hook config (08/21/2026).** Same 08/20 sync, one level deeper: `~/.cursor/hooks.json` was a whole-file mirror, so the copy deleted the seven agentmemory Cursor capture hooks (`hooks.json.bak.20260820.5` has them, `.6` is what the sync left). The key-splice that fixed `~/.claude/settings.json` is not enough here — everything lives under one `hooks` key and two of the events we write, `stop` and `postToolUse`, are events agentmemory writes too. New `bootstrap/_merge_cursor_hooks.ps1` therefore owns entries, not keys: each event array is rebuilt as our rendered entries plus every foreign entry already present, then handed to the shared splice engine so only the `hooks` value is re-serialised. Ours are matched on `terminal-stack`, `cursor-tts` (the legacy per-hook scripts, so an upgrade replaces them instead of double-speaking every event) and the `cat > /dev/null` no-op — which has to be a marker rather than an exact match against the render, since TTS off renders nothing and it still has to go. Ordering is ours-then-theirs, the same order `setup-cursor-integration.ps1` produces, so the two converge instead of rewriting the file on each other's account. Verified with an on → off → on round trip against a real pre-clobber backup. The bash hook's `merge_claude_settings` generalized to `merge_part_owned`. Rationale in `docs/decisions.md` § "Why `~/.cursor/hooks.json` needs per-entry ownership".

- **The sync no longer deletes Claude Code's own settings (08/21/2026).** `~/.claude/settings.json` was mirrored whole-file like every other `windows/**` file, but Claude Code writes that file too — `model` from `/model`, `enabledPlugins` and `extraKnownMarketplaces` from `/plugin`, MCP allowances in `permissions`, plugin environment in `env`. Every sync silently deleted all of it. On 08/20 that disabled the agentmemory plugin mid-session: twelve lifecycle hooks and its MCP server stopped loading with no error and nothing in `chezmoi diff`, so Claude Code quietly stopped recording memories while Codex (config in `~/.codex/`, which this repo does not whole-file-manage) carried on. The file is now **part-owned**: both sync paths splice in only the top-level keys the template renders (`statusLine`, `hooks`, `theme`) and leave every other byte where it was. New `bootstrap/_merge_claude_settings.ps1` over a new shared `bootstrap/_merge_json_settings.ps1` — the textual JSONC splice engine lifted out of `_merge_cursor_settings.ps1`, which keeps its behaviour unchanged. The splice refuses to write if the result does not re-parse or would disturb a key it does not own, backs up before every write, and from WSL without `pwsh.exe` leaves an existing file untouched rather than clobbering it. Rationale in `docs/decisions.md` § "Why `~/.claude/settings.json` is spliced, not copied".

- **TTS hooks no longer flash a Command Prompt window on Windows (08/20/2026).** The old background path still launched console-subsystem `ffprobe.exe` and `ffplay.exe` for every utterance, with PowerShell and `pythonw` elsewhere in the fallback/daemon chain. The Windows runtime is now one PyInstaller GUI-subsystem `terminal-stack-tts.exe`: Claude, Cursor, Codex, and WSL interop call it directly; it normalizes hook JSON, posts to the daemon or starts a detached direct worker, probes media with mutagen, plays through WinRT MediaPlayer, and falls back through COM SAPI in-process. The installer uses Python only in a temporary build venv, validates and atomically installs the EXE, points HKCU Run directly at it, then removes the legacy persistent venv and `.cmd` launcher. Unavoidable auxiliary children use centralized `CREATE_NO_WINDOW` flags. Added hook-normalization tests, packaged redirected-pipe verification (including Cursor's `{}`), PE subsystem validation, and a live Kokoro/duck/playback drill.

### Added

- **Three-line Codex dashboard, yolo launch shortcut, and Codex TTS (08/20/2026).** Every interactive `codex`, `resume`, and `fork` launch now gets a disposable three-row WezTerm dashboard; administrative/noninteractive commands remain stock, `codex-stock` bypasses enhancements, `cy` launches `codex --yolo`, and `cyr` resumes it. The dashboard is development-first: smart repo location and branch/upstream; detailed changes, sync, stashes, exact rollout patch, commit age, and cached PR review/CI/merge health; then live state/action and timers, model/effort, context and 5-hour/weekly consumed bars, token breakdown, permissions/version, and actionable tool/TTS faults. Narrow panes abbreviate and elide without wrapping, and the enhanced profile suppresses Codex's duplicate native metadata row. A named `$CODEX_HOME/terminal-stack.config.toml` profile lets guarded launches stay guarded while official SessionStart/Stop hooks map panes to rollouts and route completion speech through the existing TTS daemon/direct fallback as the `codex` source. The Windows mirror deploys `dot_codex`, docs cover `/hooks` trust, and both WezTerm configs permanently omit the date and clock from the title status bar.

- **Session-aware voice notifications: the `ttsd` tray daemon (08/20/2026).** "Claude finished" spoken with no idea *which* Claude was the problem — plus a machine-global 5 s debounce that silently dropped the second of two near-simultaneous completions. The TTS layer now has an optional native Windows daemon (`ccTtsDaemon`, **default off**; `ts-config tts daemon on`, wizard follow-up `TS_CC_TTS_DAEMON=on|off`) that the Claude Code and Cursor hooks POST their events to.
  - **Session identity**: announcements name the project, with ordinals when several sessions share one ("terminal-stack two finished"), and an opt-in per-session voice pool (`ts-config tts voices`). A registry keyed on `session_id`/`conversation_id` tracks project, ordinal, voice, and WezTerm pane.
  - **Smart queueing**: priority classes (question/permission speak immediately, then errors, then dones), per-session slot dedupe, a 1.8 s coalescing window that turns simultaneous completions into "Three sessions finished: …", hold + cooldown for Cursor's fires-every-turn completion hook, barge-in (a new prompt cancels that session's queued announcements), and staleness drops. Replaces the global debounce/play-lock on the daemon path; the direct path keeps them.
  - **Music ducking**: `ts-config tts music duck|smart|pause|off` (default duck) — per-app Core Audio volume ramped to `duck-level` % while speaking (pycaw), or true pause/resume of playing media sessions (WinRT GSMTC, never the blind media key); `smart` ducks short announcements and pauses for long ones. Crash-safe: pre-duck volumes snapshot to disk *before* any change, a stale snapshot is restored at next start, a 15 s watchdog force-restores, and `ts-doctor --repair` runs the restore oneshot (Windows persists per-app mixer volume, so this is the difference between a dip and music stuck at 30%).
  - **Four summarizer modes** (`ts-config tts summarizer …`, hot-switchable, each degrading to `template`): `self` — the model ends its turn with `<!-- speak: one sentence -->` and only that is read (zero latency; installs removable marker blocks in Claude's `CLAUDE.md` and Codex's active global `AGENTS.md`); when Cursor's GUI-managed User Rule or an already-running Codex session supplies no marker, the daemon derives a short local sentence from the final-response hook text before falling back to `template`. `haiku` — Claude Haiku rewrites the final message into one spoken sentence (key via `ANTHROPIC_API_KEY`, never stored); `ollama` — same against a local model; `template` — today's lines enriched by the typed hook payloads (`error_type`, `notification_type`, `tool_name`). Config changes now POST the daemon's reload endpoint, so “hot-switchable” is true for the running process as well as direct playback.
  - **Never silence**: hooks try the daemon with a short budget and fall back to a detached direct worker in the same EXE on any failure; native Linux retains its shell direct path. No daemon state touches the managed settings templates.
  - Plumbing: daemon package at `bootstrap/tts-daemon/ttsd` (stdlib HTTP on `127.0.0.1:8890` + token-guarded WSL-gateway listener, pystray tray, pytest suite, `simulate` fixtures); `bootstrap/install-tts-daemon.ps1` (temporary build venv, PyInstaller EXE, direct HKCU Run autostart, `-Uninstall`/`-Purge`); nine new `ccTts*` keys; `ts-doctor` health/staleness/snapshot checks; and deliberate restart nudges after updates.

- **`pm` Tab-completes `.md` files only (08/20/2026).** A `Register-ArgumentCompleter` on `pm`'s `Paths` parameter — the first argument completer anywhere in this profile — restricts candidates to markdown files and directories (so subfolders stay navigable), dropping every other file type. No `Set-PSReadLineKeyHandler` change needed: Tab already cycles whatever a completer returns by default, so `pm ` + Tab cycling every `.md` file in the current directory and `pm ins` + Tab narrowing to `INSTALL.md` are the same completer, just with an empty vs. partial `$wordToComplete`. A trailing separator (`pm docs\` + Tab) is special-cased to descend into that directory rather than re-matching the directory's own name, which `Split-Path`'s normal parent/leaf split doesn't do on its own.

- **`pm` alias for PrettyMark on Windows (08/20/2026).** Opens file(s) in [PrettyMark](https://prettymark.it/), a Windows/Mac markdown viewer, the same way `npp` opens Notepad++ — same exe-resolution + call-operator pattern in `$PROFILE`'s `editor-launch` block. PrettyMark also joins the Windows app catalog as `Eagle1.PrettyMark` (recommended tier), so `windows-bootstrap.ps1` offers to install it and `ts-update` notices if it ever goes missing — `Get-TsAppsPending`'s installed-check gained a fixed-path fallback (`Test-TsAppInstalled`/`$TsAppFixedPaths`) since PrettyMark's winget install doesn't land on `PATH`, unlike the rest of the catalog. Windows-only: `dot_zshrc` covers WSL/native Linux/macOS too, but the user's fleet has no Mac, so no zsh-side `pm` was added.

- **`docs/verifying-changes.md` — the pre-commit checklist that replaces the missing CI (08/20/2026).** CLAUDE.md pointed at `INSTALL.md` § Phase 9 for verification, but that is a post-install smoke test for a fresh machine, not a way to check a change you just made — so every technique got re-derived from scratch each time. Now written down: the syntax gates (including that `bash -n` happily passes a mangled `printf 'x
'`, so escape-touching edits need `cat -A`); load-testing a rendered `.wezterm.lua` with `wezterm --config-file … show-keys`, and the non-obvious fact that `wezterm.gui` is **non-nil** there so the plugin block really executes; diffing the bash and pwsh wizard menus byte-for-byte (the bash side needs a pty via `script`, wrapped in `bash -c` because `$SHELL` is zsh and zsh's `read -p` means something else); exercising config-store changes against a throwaway `HOME` / `$env:LOCALAPPDATA`, including the `Save-TsConfig` carry-forward regression that `ts-update` would otherwise trip; and why none of it can be verified by applying from a dev clone.

- **WezTerm no longer replays the previous session at every launch (08/20/2026).** Opening WezTerm reopened the tabs and panes you last had, scrollback and all, on every machine — undocumented behaviour nobody chose, and easy to mistake for the mux (it is not: killing the mux changes nothing). `resurrect.setup()` registers `wezterm.on('gui-startup', state_manager.resurrect_on_gui_startup)` unconditionally, with no opt-out, and every autosave rewrites the `current_state` pointer that arms it.
  - **The config stops calling `setup()`.** With `keybindings`/`status_bar` already off it reduced to `event_driven_save` + `periodic_save` + that one handler, so both GUI configs now drive the two save engines directly and register the handler themselves only behind a gate. Autosave, `Leader+S` and `Leader+L` are unchanged, and no saved state is deleted.
  - **New saved setting `weztermRestore`** (`on`|`off`, **default off**), gated as `local RESTORE_ENABLED` beside `MUX_ENABLED` in both configs (`__WEZ_RESTORE__` on the Windows mirror, `{{ .weztermRestore }}` on macOS). The install wizard asks (`TS_WEZ_RESTORE=on|off` to skip, skipped on headless hosts) and `ts-config restore on|off` flips it later — a plain boolean with no live process, so it lives in `ts-config` rather than earning its own `ts-*` command the way `ts-mux` did.
  - With the setting off the autosave still tracks your live workspace, so turning it back on restores the session you actually had rather than a stale one. Rationale: `docs/decisions.md` § "Why the startup session restore is opt-in".

- **The install wizard asks about the WezTerm multiplexer (08/20/2026).** The mux domain already defaulted to off, but only `ts-mux on` could turn it on and nothing told you it existed. It is a wizard question now — `ts_prompt_wezterm_mux` (bash) / `Read-TsWeztermMux` (pwsh), rendered through the shared menu helper and verified byte-identical like the rest — defaulting to **off**, skippable with `TS_WEZ_MUX=on|off`, and skipped entirely on headless hosts where there is no GUI to host anything. It shows on the review screen as `WezTerm mux`, and is persisted by the three bash bootstraps via `ts_wez_mux_set` and by `windows-bootstrap.ps1` via `Save-TsConfig -WeztermMux`.

- **The WezTerm mux domain is now opt-in, with a `ts-mux` command to drive it (08/20/2026).** Hosting panes in `wezterm-mux-server` shipped unconditionally on 08/18 and changed how the terminal behaves for anyone who ran `ts-update` — so it is now the saved setting `weztermMux` (`on`|`off`), **defaulting to off** (the pre-08/18 behaviour), gated in both GUI configs behind `local MUX_ENABLED` (`__WEZ_MUX__` on the Windows mirror, `{{ .weztermMux }}` on macOS — `dot_wezterm.lua.tmpl` gains the same optional block, so the two stay in sync).
  - **`ts-mux`** (zsh `bootstrap/ts-mux.sh`, pwsh `Invoke-TsMux`; parallel implementations, byte-identical `-h`): `status` (the setting, the *rendered* setting, the server pid, the pane count), `on`/`off` (persist + re-render + say what takes effect when), `list` (`wezterm cli list`), `kill`, `restart`, `reset` (off + re-apply + kill + clear stale sockets). `kill`/`restart`/`reset` confirm before running because they kill every pane the mux hosts; `-y` skips.
  - **`status` reports the rendered value separately from the saved one**, so a change you never applied shows up as stale — including a `.wezterm.lua` older than the toggle, which has no `MUX_ENABLED` line and is reported as `on (pre-toggle)`.
  - **From WSL it drives the Windows-side server over interop** (`tasklist.exe` / `taskkill.exe` / `wezterm.exe`), so the same command works from either shell.
  - Plumbed through the usual places: `.chezmoi.toml.tmpl`, `bootstrap/_config.sh` (`ts_wez_mux_get`/`ts_wez_mux_set` + the Windows `config.json` mirror), `bootstrap/_config.ps1` (`Save-TsConfig -WeztermMux`, carried forward when unset), both sync scripts (new `__WEZ_MUX__` token), and `ts-config` (`wezmux` in `show`, menu entry 7, `ts-config mux …` hand-off). The sync scripts' mux-restart reminder now fires **only when the mux is actually on**, and points at `ts-mux restart` instead of a hand-typed `taskkill`.

- **Install wizard rebuilt: robust prompts, optional WezTerm, review-before-acting (08/20/2026).** Every question used to be a `switch (Read-Host 'Choose [1]') { … default { … } }` — a typo, a stray `y`, or a fat-fingered `9` silently selected option 1 and the install carried on. One helper now backs every prompt (`Read-TsChoice` in `bootstrap/_config.ps1`, `ts_prompt_choice` in `bootstrap/_wizard.sh`, rendering kept byte-identical the way `wso`'s two implementations are): the default is **marked and captioned "press Enter"** instead of hidden in a `[1]`, an option's **name works wherever its number does** (`dark`, `stable`, `none`), and anything unrecognised **re-prompts** — falling back to the default only after three bad answers, so an automated caller can't spin. **WezTerm is no longer force-installed**: a `nightly` / `stable` / `skip` question replaces it in the required set, and a nightly whose winget manifest has gone stale (`Installer hash does not match` — a routine outcome that previously failed silently mid-run) **falls back to stable**. Every package that didn't install is **listed at the end with its retry command**. Also: "install everything" is reachable from the apps menu (it was `TS_APPS=all`-only), customize takes a **comma-separated list** instead of fourteen consecutive Y/n prompts, `Alt+Space` joins the leader options, and a **`[P]roceed / [e]dit / [q]uit` review** shows every answer before anything is installed or written — so the Windows workspace question moved up out of the middle of the winget runs. New env vars: `TS_WEZTERM=nightly|stable|skip`, `TS_ASSUME_YES=1`.

- **Canonical runtime clone location + dev-clone invisibility (08/20/2026).** The runtime clone now lives at `%LOCALAPPDATA%\terminal-stack\stack` (shared by Windows and WSL as one clone) / `~/.local/share/terminal-stack` (native Linux/macOS) — inside the app-data dir the stack already owns and outside every workspace root, so `wso migrate` can never relocate it out from under the install. Installers default there and offer to **move** an existing legacy clone (history, stashes, and dirty state intact) instead of cloning fresh; `ts-doctor --repair` gains the same move (`ts_relocate_clone` / `Move-TsClone`), plus origin-URL normalization for renamed accounts and stale-pin removal — pins are now only for non-canonical locations. `ts-update` prints a one-line notice at a legacy path but never moves anything. The seven divergent clone-candidate lists converged onto one documented priority order (pin > canonical > legacy; master in `bootstrap/_cleanup.sh`, decision in `docs/decisions.md`), and pwsh's newest-commit ranking is gone — it would have preferred a dev clone the moment you committed to it. **Dev clones at wso tier paths (`src/github.com/...`) are invisible to every resolver, doctor probe, doc root, and cleanup menu unless explicitly pinned**, so `ts-update` updates the runtime install, never the tree you're developing in; `wso` additionally marks the active runtime clone `runtime — not migrated` if scanned. WSL/Linux bootstrap `SOURCE_DIR` fallbacks are now self-relative (the mac-bootstrap pattern) instead of hardcoded legacy paths.

- **`doc` knowledge-base overhaul (08/19/2026): consistent rendering, keyboard-first reading, full content sweep.**
  - **Shipped glamour styles.** `docs/kb/_style/{dark,light}.json` (Catppuccin Mocha / VS Code Light Modern, tight margins, single-line table borders) ride the existing kb mirror sync; `doc` passes `-s <style>` everywhere and picks dark/light from the saved `resolvedTheme` (`$DOC_STYLE` overrides). This is what makes rendering identical across the three glow builds the bootstraps install — the WSL build was drawing every table row with its own border and a blank line, at a hard 80-column wrap from `glow.yml`.
  - **Explicit widths.** Previews render at the fzf pane's real width (`FZF_PREVIEW_COLUMNS`); the reading view at terminal width capped at 100.
  - **Keyboard-first pickers.** `Ctrl+U`/`Ctrl+D` scroll the preview, `Ctrl+/` toggles it, `Alt+E` jumps to editing the highlighted topic; borders + prompts added; opening a topic now pages through `glow | less -RF` (`/` searches, `q` quits, short topics print straight through) instead of glow's mouse-oriented pager.
  - **Machinery fixes (both shells).** `doc edit`/`doc new` refuse the read-only `%LOCALAPPDATA%` mirror and redirect matches to the clone copy; `doc -g` output is paged; `doc cmd` no longer breaks without bat; pwsh's last-resort viewer pages instead of dumping; `doc tui local` browses `~/.doc.local`.
  - **Content sweep (25+ topics).** New: `common/stack.md` documents `ts-doctor`/`--repair` (previously 100% undocumented) plus the full `ts-update`/`ts-rollback`/`ts-config` lifecycle; `windows/winget.md` (the `_index.md` promise now kept, with the verified app catalog); `common/tools/cursor.md`; `common/clipboard.md`. Rewritten: `common/tmux.md` now documents the stack's tmux (configurable prefix, OSC 52, extended-keys — why Shift+Enter works in Claude Code) instead of generic tmux; `common/search-history.md` adds `hgrep` and the `history all` override. Expanded: Claude statusline anatomy + `keybindings.json` in `common/claude-code.md`; `rmf`/`lt` in `common/files-disk.md`; literal-key bindings in `wezterm/panes.md`; all 12 thin tool pages grown into stack-flavored cheat-sheets (how each tool is wired here + daily commands). Corrected en route: `windows/pwsh.md` claimed fzf-wired `Ctrl+R`/`Ctrl+T` on Windows (the profile wires no fzf keys — that's native PSReadLine).

- **WezTerm overhaul (08/19/2026): directional pane nav, plugins, tab-title contract restored, terminal QoL.**
  - **`pane_nav.lua` replaces the strict-build-order 3×2 grid (`pane_grid.lua`).** `F1`–`F4` are now directions (left/right/down/up): press to **focus** the pane that way, or **split** one into existence (50/50) if none is there; `Shift+F1`–`F4` always split in that direction into a fuzzy-picked domain; `F5` is a labelled PaneSelect jump overlay and `F6` a PaneSelect swap-with-active; `Leader+1`–`6` mirror `F1`–`F6`. The grid silently no-opped on out-of-order presses and its cell labels shifted crossing 4→5 panes — directions are stateless, so every press does something predictable in any layout. Both configs (`windows/.wezterm/pane_nav.lua` + `dot_wezterm/pane_nav.lua`); `.chezmoiignore` now gates `.wezterm/**` to darwin so the module no longer litters WSL/native-Linux homes.
  - **Plugins, as pinned forks under `github.com/martybytes` (pcall-guarded).** `tabline.wez` renders the status bar — mode/workspace left, `user@host │ path` right (`tabs_enabled = false`, so the hand-rolled `format-tab-title` still draws the tabs with their cc-state dots and tints); falls back to the hand-rolled status handler if the plugin fails. `sessionizer.wezterm` gives **`Leader+p`**, a fuzzy project picker over the `wso` workspace layout plus the `*_Personal`/`*_Public`/`*_Work` suffix siblings (needs `fd`). `resurrect.wezterm` (the maintained StephenGemin fork) autosaves sessions every 15 min and on focus loss; **`Leader+S`** saves the workspace, **`Leader+L`** fuzzy-restores. Forks pin the code so upstream archival or a breaking change can't take the stack down; plugins clone at first GUI start (needs network once).
  - **`Leader+s`** toggles the `user@host │ path` status segment (`wezterm.GLOBAL.show_identity` — survives config reloads).
  - **`format-tab-title` reads `tab.tab_title` first again**, restoring the `wezterm cli set-tab-title` contract the `cc` wrappers and Claude hooks rely on, then falls back to the active pane's cwd leaf.
  - **Terminal QoL in both configs:** `quick_select_patterns` for git SHAs and `file:line` refs; hyperlink rules — `owner/repo` opens on GitHub, `path/file.ext:123` opens in **Cursor** at that line via an `open-uri` handler; `Ctrl+Shift+↑/↓` = `ScrollToPrompt` over OSC 133 semantic zones (zsh already sources the WezTerm shell integration); `visual_bell` cursor flash instead of a beep; retro tab bar (`use_fancy_tab_bar = false`, no new-tab button).
  - **tmux/Starship:** tmux gains `default-terminal tmux-256color`, RGB `terminal-features`, and `set-clipboard on`; Starship adds `$cmd_duration` to the prompt format (both templates).

- **`rmf` and `c` shortcuts (both shells).** `rmf <path…>` force-deletes recursively with no confirmation prompts (`rm -rf` / `Remove-Item -Recurse -Force`); `c [path]` launches Cursor on the given directory with the classic UI (defaults to `.`; zsh defines it only when `cursor` is on PATH, pwsh warns when it isn't).

### Changed

- **WezTerm tab bar redesigned: taller fancy bar, unmistakable active tab, hand-rolled status (08/20/2026).** Driven by daily frustrations — the active tab was nearly the same grey as its neighbours, a permanent `NORMAL` badge said nothing, `cc • ` prefixes wasted tab width, and remote tabs showed full paths.
  - **Active tab is a solid accent block** (`#89b4fa` dark / `#005fb8` light, dark bold text); inactive tabs dimmed. The cc-state background wash now applies to inactive tabs only — the active tab's accent is never diluted, and its dots still carry the Claude state.
  - **Taller bar.** Both configs switch to the fancy tab bar (`use_fancy_tab_bar = true` + `window_frame` at 12.5pt JetBrainsMono NF) — the retro bar's height is hard-locked to one terminal cell and WezTerm has no multi-line bar (wezterm/wezterm#3789), so `window_frame.font_size` is the only sanctioned height control. Tabs and status stay fully hand-drawn; flipping back to `false` renders the same content in the retro bar.
  - **tabline.wez dropped.** It required the retro bar, printed the permanent `NORMAL`, and duplicated the hand-rolled fallback status that already existed — the fallback is now the only renderer. Sessionizer and resurrect are unchanged. Rationale: `docs/decisions.md` § "Why the tab bar is fancy and fully hand-rolled".
  - **Short, smart tab titles.** The `cc*` wrappers (both shells), `ccs`, and the wez-tab-status hooks now set the **bare project leaf** — no `cc • ` / `cc ⚙ ` prefix (the Claude icon + state dots already say Claude); `strip_cc_prefix` cleans titles from not-yet-updated machines. Untitled tabs show the cwd leaf or the title's path leaf — never a full path — and panes on another machine get a ` host ·` chip (OSC 7 / SSH domain / `host: path` title; `ssht`'s `ssh-<host>:<sess>` titles render as the chip + session). More process icons (git, docker, go, rust, tmux, …), and an inactive tab with unseen output gets an accent dot.
  - **Status bar: badge only when it means something.** The left side renders nothing in the normal state; a colour-coded badge appears while the leader is pending or a move/resize/rotate/tab/font mode is live. The right side gains a **Claude fleet** segment (working/done/error counts across every pane in the mux), shows the workspace whenever it isn't `default` (no longer behind the toggle), and `Leader+s` toggles only `user@host │ path`. A briefly shipped date/clock segment was subsequently removed permanently.
- **The WezTerm status bar starts quiet (08/20/2026).** `wezterm.GLOBAL.show_identity` now defaults to `false`, so a fresh window shows only the mode badge — `user@host`, the active pane's path, and the workspace name stay hidden until you ask for them. **Leader+s** reveals and hides all three (it previously covered only `user@host │ path`, which would have left a named workspace stuck on screen). The workspace segment moved behind a new `status_workspace` helper so the tabline sections and the hand-rolled fallback status honour the toggle through the same two functions instead of each testing for themselves. Both GUI configs, in sync. Rationale: `docs/decisions.md` § "Why the status bar starts quiet".
- **WezTerm key tables renamed and de-stickied.** `activate_pane`→`move_mode`, `resize_pane`→`resize_mode`, `rotate_pane`→`rotate_mode`, `switch_tab`→`tab_mode`, `font_size`→`font_mode` (the `_mode` suffix lets tabline colour each mode's badge). **Resize is no longer sticky-forever** — it auto-exits like the others (`until_unknown` + 1.5s idle; `Esc`/`Enter`/`q` leave immediately), and rotate is now `←`/`→` (and `j`/`k`) only.
- **macOS config drift fixed:** `audible_bell = 'Disabled'` and `adjust_window_size_when_changing_font_size = false` now set on macOS too.
- **Sync scripts hardened.** `run_after_90-sync-windows.sh` now **requires python3** to render the Windows `.tmpl`s (the sed fallback rendered broken JSON for the multi-line `__CC_TTS_*__` tokens and broke on two-modifier leaders, so it was removed rather than left as a trap); the Windows-side `~/.claude/tts/config.json` render is now idempotent with `.bak.YYYYMMDD[.N]` backups; `sync-windows.ps1` token substitution uses string `.Replace` instead of regex `-replace` (which would interpret `$1`/`$&` in token values). Both scripts print a **restart reminder for `wezterm-mux-server`** when a WezTerm config changed — never restarting it automatically, since that kills every live pane.
- **Windows pane tint under the mux domain is a documented limitation.** `pane:inject_output` is local-pane-only, so with `default_domain = 'main'` the per-pane cc-state tints may not render; failures now log once per pane to the debug overlay (`Ctrl+Shift+L`). Tab dots and title tints are unaffected.

### Fixed

- **`ts-config tts daemon on` reported success with no daemon running (08/20/2026).** Surfaced on the very first live activation: only pip's stderr cache warnings appeared, then "done" — no daemon. Root cause: `Invoke-TsCcTtsDaemonInstaller` ran `& pwsh -File install-tts-daemon.ps1` bare inside a function, so the child's entire stdout — including its "Creating venv…", the firewall note, and any error text — was captured into the function's **return value** instead of reaching the console, and callers coercing that non-empty array to bool read every failure as success. Fixed by streaming through `| Out-Host` and returning only the exit-code boolean (see the new `powershell-quirks.md` entry — this is the output-stream sibling of the `Where-Object | Set-Content` trap). Hardened the launch itself while in there: `Start-Process` on a bare `.cmd` goes through ShellExecute, which is flaky from non-interactive/interop contexts, so the installer now starts the launcher via an explicit `cmd.exe /c`, and the health-probe window doubled to 10 s (first-ever pythonw start pays module-import cold start). `daemon on` from pwsh also prints a reminder that a combined setup needs the same command from WSL — pwsh saves only the Windows `config.json`, and the next WSL `chezmoi apply` re-renders that file from chezmoi `[data]`, silently reverting a pwsh-only enable (now called out in `doc windows/tts-daemon` and the CLAUDE.md TTS paragraph). Never-silence held throughout: the misreported "enabled" state just meant hooks quietly kept using direct playback.

- **`npp`/`pm` silently truncated every single-file open to one character (08/20/2026).** `pm install.md` opened PrettyMark on a nonexistent file named `i`, `npp` had the identical latent bug for any single-file call. Root cause: `$resolved = foreach ($p in $Paths) {...}` collapses to a bare `[string]` (not an array) when the loop produces exactly one output, and `& $exe @resolved` — splatting a scalar string — enumerates its **individual characters** as separate positional arguments instead of passing the one path whole; the launched app then treated the first character as the filename. Two files or more happened to work (`$resolved` stayed a real array), which is why this went unnoticed until a single-file `pm` call surfaced it. Fixed by wrapping both functions' resolution loop in `@(...)` to force an array regardless of count — a general PowerShell splatting gotcha, not anything specific to PrettyMark or Notepad++.

- **`zed`'s winget id was stale, failing every install/`ts-update` (08/20/2026).** The catalog carried `Zed.Zed`; winget now serves the editor under `ZedIndustries.Zed`, so `winget install Zed.Zed` returned "No package found matching input criteria" for anyone who had `zed` in their saved app selection. Surfaced by a `ts-update` run after the PrettyMark catalog addition above — unrelated to that change, just the same "pending apps" prompt that finally tried to (re)install it. Fixed in `bootstrap/_config.ps1`'s `$TsWingetIds`, `docs/kb/windows/winget.md`, and `docs/kb/common/tools/zed.md`.

- **`docs/verifying-changes.md` overstated the WezTerm load test (08/20/2026).** A broken config does **not** make `wezterm show-keys` exit non-zero — it exits 0 and silently prints the *default* key table, no traceback (proved with a deliberately broken config). The checklist now judges by content (`grep -c LEADER`, 0 = didn't load) and documents the load-time-assertion trick for testing pure helper functions headlessly. Memory of the same claim corrected.
- **The runtime clone can no longer end up inside a workspace root (08/20/2026).** The canonical-location work shipped one release earlier didn't hold: a clone at `C:\DATA\Workspace\terminal-stack` was migrated to a tier path by `wso migrate`, the pin left behind pointed at nothing, and the installer then re-created the clone at that dangling pin. Four independent holes, closed. **(1)** `install.ps1` treated any non-empty `$env:TERMINAL_STACK_DIR` as deliberate intent — but `profile.local.ps1` injects that pin into every pwsh session, so `irm … | iex` never sees a clean environment. A pin that matches the persisted line is now honoured only while a clone still lives there; a one-shot `$env:TERMINAL_STACK_DIR=…; irm … | iex` is untouched. **(2)** All four installers now warn and default to the canonical path when the target sits inside a detected workspace root (dev-clone tier paths exempt — pinning one is deliberate). **(3)** A dangling env pin was a hard dead end in `Resolve-TsSourceDir` / `_ts_src`, bricking `ts-update`/`wso`/`doc` machine-wide with no way out short of hand-editing `profile.local.ps1`; it now warns and falls through to the candidate search, while an explicit `-SourceDir` still fails loudly. **(4)** `wso`'s "never migrate the runtime clone" guard switched *itself* off whenever its narrow pin→canonical resolver came back empty — precisely the broken states where it matters. It now delegates to `Resolve-TsSourceDir`, the pwsh `wso` shim exports what it resolved (the zsh twin already did), and **any un-tiered terminal-stack clone at the workspace root is blocked from migration regardless**. Also: `ts-doctor -Repair` no longer dead-ends when the canonical location is already occupied (it switches to the canonical clone and offers the other for cleanup, instead of deferring to a menu that structurally cannot show it), the four clone-candidate lists that claimed to be in sync now are, and `profile.local.ps1.example` / `dot_zshrc.local.example` finally document `TERMINAL_STACK_DIR` — the file the installer writes the pin into never mentioned it.
- **`Clear-TsSourceDirPin` reported removing the pin and removed nothing.** `(Get-Content $f) | Where-Object {…} | Set-Content $f` leaves the file untouched when the filter yields nothing — an empty pipeline gives `Set-Content` no value to write, silently. So the pin survived exactly the common case: a `profile.local.ps1` whose only line *is* the pin. Uses `-Value` with an array now; written up in `docs/powershell-quirks.md`.
- **`install.ps1` hung before cloning when stdin was a pipe.** The clone-location and legacy-clone prompts called `Read-Host` unconditionally; on a redirected stdin that never closes it blocks rather than returning empty. Both take their default when `[Console]::IsInputRedirected`.
- **`wso plan` printed blocked repos with no reason on the bash side.** Tab is IFS whitespace, so `read -r _ s dd nn` collapsed the empty destination field and the note — the one line telling you what to do about a blocked repo — landed in `$dd` and was never shown. Reads via `cut -f`, which keeps empty fields.
- **Shell/config bug batch.** zsh `cctts` now reads `~/.claude/tts/config.json` (it always reported OFF); zsh `cc*`/`plain` wrappers use `{ } always { }` so Ctrl+C still clears the tab title; zsh gains `lt` (eza tree, matching pwsh); pwsh `ccat` is guarded on `bat` being installed; `_ts_clones` matches the origin URL case-insensitively; the statusline context bar handles float percentages; `cc-tts-lib.sh` no longer resets `messageMode: "hook"` to `"template"`; the delta git pager is guarded (`sh -c 'command -v delta …'`, falling back to less/cat); pwsh repo scans use `-Depth 4` so nested GitLab groups are found; `Save-TsConfig` preserves an existing `tmuxPrefix` when not passed; `bootstrap/_cleanup.ps1`'s candidate scan is renamed `Get-TsCleanupCloneCandidates` (it shadowed the profile's `Get-TsCloneCandidates`); dead `windows/.claude/statusline-command.ps1` deleted; `dot_zshrc.local.example` uses a `<your-user>` placeholder; stray control characters (TAB/BEL) repaired in `profile.local.ps1.example` and `docs/decisions.md`.
- **Docs reconciled with the code** — pane_nav/F-key scheme, plugin forks, the restored tab-title contract, the OpenGL/mux-domain decision (new entries in `docs/decisions.md`), the whole-file `$PROFILE` sync in `ARCHITECTURE.md`, the actual light palette (VS Code Light Modern, not Catppuccin Latte — tmux's light status colours stay Latte-derived), and the `doc wezterm/*` key references.
- **`ts-update` offers to install apps the catalog has gained.** Syncing config files was only half an update: a release that adds a CLI tool left that tool absent, and nothing ever installed it. The saved `apps` list is a snapshot of what you picked when you last ran the wizard, so a machine set up before a tool joined the catalog would never acquire it — `gh`, `ghq` and `lazygit` would have missed every existing install for exactly that reason. `ts_apps_pending` / `Get-TsAppsPending` now compute the gap from both the saved selection (a failed install, or a tool since removed) and anything added to the recommended set afterwards; `ts-update` lists it with descriptions and asks once, installing through the existing per-platform paths and folding the result back into the saved selection. Never installs unprompted, silent when nothing is missing, and prints a `ts-config apps` hint instead of asking when there is no terminal.

- **`ts-update` no longer picks a clone blind.** `Resolve-TsSourceDir` took the first path that merely had a `.git` directory, so a machine carrying a leftover install could pull and re-deploy from the wrong clone — silently overwriting a current `$PROFILE` with an old one. The existing "does the remote say terminal-stack?" guard could not catch it, because a stale clone from a renamed account still passes the name test: being a terminal-stack clone is necessary but not sufficient to *choose* one. `Get-TsClones` (pwsh) / `_ts_clones` (zsh) now enumerate every candidate, keep the real clones, and rank by commit date; resolution takes the newest so it self-heals after a pull, while an explicit `-SourceDir` / `$TERMINAL_STACK_DIR` still wins. More than one clone is reported with each origin and HEAD instead of chosen quietly, `ts-update` offers to pin the winner once, and both shells now print `==> clone: <path>` so it is never a guess which tree an update came from.

### Added

- **`wso` — workspace organizer for ~100 repos across many machines.** Puts every clone in one derivable tree, `<workspace>/<tier>/github.com/<owner>/<repo>`, where the destination is computed from the repo's `origin` remote rather than the folder name someone typed once. That derivation is the point: on a real tree it found a folder named `flipoff` whose origin was `37metrics/rotari`, spotted `sheet-sense` and `sheet_sense` as one remote cloned twice under two spellings, and refiled a clone still pointing at a renamed GitHub account — none of which are visible from the folder. Tiers are `src/` (owners you control), `public/` (third-party, a disposable cache), `archive/` (cold, mirrors `src/` exactly), `local/` (no remote yet — a path under an owner would be a false claim), and `scratch/` (not a repo at all). **`wso status`** is a read-only report of everything dirty, unpushed, stashed, detached or remote-less. **`wso plan`** previews the migration and never writes; **`wso migrate`** executes it as atomic same-volume renames, so uncommitted changes, stashes, reflog and untracked scratch survive, and refuses any destination that already exists — which is what keeps two diverged clones of one repo from being merged into a single path. **`wso sync`** is fast-forward-only, so it cannot destroy local work; the repos it skips *are* the output. **`wso archive`** prompts for a day threshold, then drives a pre-ticked checklist gated on uncommitted changes, unpushed commits on **any** branch, stashes, detached HEAD and missing remotes — re-checked immediately before each move, since the list can sit open a while. **`wso unarchive`** restores by picker, name, org, `--all`, or `--undo-last` (reversing a whole run from its log), optionally fast-forwarding as it goes. Plus `wso get`, `wso orphans [--push]`, `wso identity` (per-owner `includeIf` git identities, so work commits stop going up under a personal address) and `wso doctor`. Staleness is the later of the last commit and the newest child mtime, **excluding `.git`** — otherwise `git fetch`/`gc`/`status` churn makes every repo look touched today. Both shells, with the pwsh side a parallel implementation rather than a WSL shim. `TS_DRY_RUN=1` previews everything. See `doc common/workspace-org`.

- **Workspace jump shortcuts for the organised tree.** `ws37`, `ws42`, `wsmb`, `wsmd` jump to `src/github.com/<owner>`, `wsar` to the archive tier, and **`wsj`** fuzzy-jumps to any repo anywhere in the tree (fzf, falling back to a filtered numbered menu) — the piece that makes the deep paths free, since you never type them. `wspu` now prefers the organised `public/` tier and falls back to the old `*_Public` sibling root, so it behaves correctly before, during and after a migration. These stay shell functions rather than `wso` subcommands because a child process cannot change the parent shell's directory. Both shells. See `doc common/workspace-nav`.

- **`gh`, `ghq` and `lazygit` added to the app catalog** (recommended set), installed by every bootstrap: winget on Windows (`GitHub.cli`, `x-motemen.ghq`, `JesseDuffield.lazygit`), Homebrew on macOS, and upstream GitHub releases on Debian/WSL where none of the three are reliably packaged. The release fallback is now **arch-aware** via a new `common_arch_tag` helper, since these are commonly wanted on arm64 boxes where the previously hardcoded `x86_64` asset would be wrong.

- **`pull.ff = only` in the managed gitconfig.** With ~100 repos, this is the difference between a bulk update being safe and being a gamble: a pull either fast-forwards cleanly or refuses and leaves you exactly where you were, never manufacturing a surprise merge commit and never half-merging over uncommitted work.

- **Docs:** new `docs/kb/common/workspace-org.md` (the full `wso` reference — layout, safety gates, staleness rules, config format); `docs/kb/common/workspace-nav.md` gains the new jump shortcuts and the `wspu` repoint; five new entries in `docs/decisions.md` covering why paths are derived from the remote, why `archive/` is a parallel tree rather than `#archive`, why `wso` keeps its own tiering despite requiring `ghq`, why `.git` is excluded from the staleness scan, and why migration moves rather than re-clones; `ARCHITECTURE.md` records the dual implementation, what `wso` writes outside the clone, and why run logs live with the workspace; `README.md`'s layout tree refreshed (it had drifted — `docs/kb/`, the `bootstrap/_*` helpers and the `ts-*` backends were all missing).

- **`lsr` / `lsrr` — list top-level directories by most recent activity.** Ranks each directory by the newest mtime among its **immediate children** (one level deep, never recursive), so a project whose files you edited all day sorts first; `ls -lt` and `eza -s modified` sort by the directory's *own* mtime, which only moves when entries are added or removed. Empty directories show `(empty)` and sort last — the directory's own timestamp is never used as a fallback. `lsr -a` includes hidden/dotted dirs; hidden *children* always count. Both shells, with identical ordering: zsh/bash prints aligned text and probes GNU-vs-BSD `stat`/`date` at runtime (so one `dot_zshrc` serves Linux, WSL, and macOS); PowerShell emits objects, so `lsr | Where-Object …` and `lsr | Export-Csv` compose. **`lsrr`** is the same list capped at the 20 most recent, taking the same flags and optional directory (pipe `lsr` for any other count). See `doc common/files-disk`.

- **`wsw` — work-workspace navigation.** Jumps to the `*_Work` / `*-Work` sibling of the main workspace (`Workspace-Work` and `Workspace_Work` both resolve), matching how `wsp`/`wspu` already work. `$WORK_WORKSPACE_DIR` overrides the autodetect for machines where the work tree lives somewhere unrelated, and **`wsw --set [dir]`** writes that override into the per-machine file (`~/.zshrc.local` / `profile.local.ps1`, backed up first) and applies it to the running shell — no hand-editing. `wsw --show` prints the resolved path. Both shells. See `doc common/workspace-nav`.

- **Cursor settings merge is comment-safe and path-portable.** `bootstrap/_merge_cursor_settings.ps1` now splices stack-owned keys into `settings.json` as text instead of re-serialising the file, so `//` comments, key order, and formatting survive; a post-merge check refuses to write if any unrelated key would change. The shipped fragment carries `__PWSH_EXE__` / `__GIT_CMD_DIR__` placeholders resolved at merge time, so per-user winget/Store pwsh and Git installs work. The merge is skipped entirely when Cursor is not installed (no more phantom `%APPDATA%\Cursor\User`), and the fragment is read from the repo rather than the mirror so a redirected `%APPDATA%` cannot hide it.

- **Agent-friendly shells.** Cursor Agent and other capture runners set `TERM=dumb` / `CURSOR_AGENT=1`; the stack now skips Starship, transient prompt, and OSC title sequences in those shells (pwsh `Test-TsAgentShell`; zsh `_ts_agent_shell`) while keeping zoxide, git shortcuts, and workspace nav. **`windows/AppData/Roaming/Cursor/User/terminal-stack.terminal.json`** ships stack-owned Cursor IDE terminal keys; **`bootstrap/_merge_cursor_settings.ps1`** shallow-merges them into `%APPDATA%\Cursor\User\settings.json` on sync (backup before write). See `doc windows/pwsh`, `doc common/tools/starship`, `docs/decisions.md`.

- **TTS config folder + input notifications.** `~/.claude/tts/config.json` (+ untracked `local.json` override) replaces flat `tts.json`. Configurable **Claude/Cursor prefixes**, `{project}` inclusion, **excitement**, and **question/permission** events. Cursor **`postToolUse`** (AskQuestion) and Claude **Notification / PermissionRequest / AskUserQuestion** hooks speak when input is needed. User-level **`/test-voice`** slash commands. See `doc claude-code`.

- **Claude Code local TTS (Kokoro / Chatterbox / edge-tts).** Optional voice on agent lifecycle events through localhost Kokoro (`am_adam`). Off by default; `ts-config tts` / `cctts`. Cursor + Claude hooks share **`cc-tts-notify`**. See `doc claude-code`.

### Changed

- **WezTerm renders with OpenGL on Windows, and panes are hosted in a mux domain.** WebGpu (wgpu 25.0.2 / DX12) panicked at `wgpu_core.rs:3626:38` ("!?") whenever it reconfigured its swapchain surface after a display or session state change — monitor sleep, RDP/session disconnect. It aborted the GUI outright four nights running (08/15–08/18/2026), each crash traced through `NtUserDispatchMessage → CallWindowProcW → GetWindowDpiAwarenessContext`; not a driver TDR (no `LiveKernelReports`, no Display 4101) and not a regression from the 08/17 nightly, since the crashes predate it. Because panes were local to the GUI process, every shell died with it — three live Claude Code sessions in one case. `config.front_end = 'OpenGL'` cannot reach that wgpu code path at all; a commented `webgpu_preferred_adapter` block records the pinned-adapter config (this box has an AMD iGPU *and* an RTX 5070, so wgpu was free to pick either) to re-test once upstream wgpu is fixed. Separately, `config.unix_domains = { { name = 'main' } }` + `config.default_domain = 'main'` host panes in `wezterm-mux-server` outside the GUI, so a GUI crash no longer takes the shells with it — verified by running a process in a mux pane with zero clients attached. **Windows only:** `dot_wezterm.lua.tmpl` (macOS) intentionally stays on WebGpu, which is Metal-backed there and unaffected. Note the mux server loads its **own** copy of the config — restart it, not just the GUI, after changing anything that affects pane spawning.

- **Repository moved to `github.com/martybytes/terminal-stack`** (GitHub username renamed from `martsamp77`). Every install URL in `README.md`, `INSTALL.md`, `install.ps1`, `install-wsl.sh`, `install-mac.sh`, and `install-linux.sh` now points at the new owner. GitHub still redirects the old path, but only until someone else claims `martsamp77`.

- **TTS app prefix.** Claude Code hooks speak `Claude. …`; Cursor Agent completion hooks speak `Cursor. …` (prefix configurable via `ts-config tts prefix`).

- **WezTerm right status follows the active pane**, not the GUI host. Top-right `user@host │ path` now reads OSC 7 cwd (with hostname), shell-integration user vars, SSH/WSL domain, then pane title — so an SSH pane to Nova shows `Marty@Nova` and that pane's path instead of the Windows box. **Path falls back to the pane title** (`host: ~/path` from zsh `_set_title`) when OSC 7 is absent — fixes empty paths on Mac/Linux SSH panes. pwsh OSC 7 uses `$env:COMPUTERNAME`; zsh prefers WezTerm's shell-integration script, else emits OSC 7 on precmd. Both `windows/.wezterm.lua.tmpl` and `dot_wezterm.lua.tmpl`.

### Added

- **WezTerm dev workflow documented** (`docs/developing-wezterm.md`, `doc wezterm/dev-config`). WezTerm reads deployed home-dir files, not the clone — on Windows run `scripts\sync-windows.ps1` after editing `windows/.wezterm.lua.tmpl` / `windows/.wezterm/pane_grid.lua` (now `pane_nav.lua`), then reload (`Ctrl+Space` `r` for module changes); on macOS `chezmoi apply` deploys `dot_wezterm.*`. **`sync-windows.ps1` and the WSL run_after hook now also mirror `docs/kb/**` to `%LOCALAPPDATA%\terminal-stack\docs\kb\`** so `doc`/`wzr` pick up kb updates on sync/apply. **`doc wezterm/dev-config` adds a Windows 11 test checklist** (what sync covers, reload steps, WSL gaps). Covers `$env:TERMINAL_STACK_DIR`, optional file-watcher and `pane_grid.lua` symlink. Short pointers in `INSTALL.md`, `README.md`, `CLAUDE.md`, and cross-links from `doc common/stack`, `doc windows/pwsh`, `doc macos/wezterm`.

- **Robust, self-repairing, headless-aware installers + a `ts-doctor` command.** Every installer (`install-linux.sh`/`install-mac.sh`/`install-wsl.sh`/`install.ps1`) now **prompts for the clone location** (default unchanged per platform; `TERMINAL_STACK_DIR`/`$env:TERMINAL_STACK_DIR` skips the prompt) and, after cloning, offers a **pre-ticked cleanup checklist** of old clones and retired leftovers (`command-reference.{md,txt,html}`, `~/.local/bin/wzr`, `~/.wezterm-ref`) — safe items selected, one confirmation before anything is removed, keep-list (`~/.zshrc.local`/`profile.local.ps1`, `~/.doc.local`, rollback state, `*.local.md`) never touched, `TS_DRY_RUN=1` to preview. **Headless servers are auto-detected** (no `$DISPLAY`/`$WAYLAND_DISPLAY` + SSH/no-GUI; `TS_HEADLESS=1|0` overrides) and confirmed interactively; in headless mode the Nerd Font download and the WezTerm leader-key prompt are skipped (tmux/starship/zsh/CLI tools still install). New **`ts-doctor`** (both shells; pwsh `ts-doctor -Repair` / `Test-TerminalStack` / `Repair-TerminalStack`): checks that chezmoi's `sourceDir` resolves to the right clone, that `~/.zshrc`/`$PROFILE` carry the stack block (and `doc`), and that tools are on PATH — `ts-doctor --repair` repoints `sourceDir`, re-applies, and offers cleanup, confirming each step. `ts-update`/`ts-config` gained a preflight that flags a clone whose git remote isn't terminal-stack. New helpers `bootstrap/_detect.sh`, `bootstrap/_cleanup.sh`, `bootstrap/_cleanup.ps1`, `bootstrap/_doctor.sh`, `bootstrap/ts-doctor.sh`; the three POSIX bootstraps now share one `ts_ensure_source_dir` (in `_config.sh`) instead of three copies of the toml-writing block. Rationale in `docs/decisions.md`.

- **Install wizard + saved configuration + `ts-config` + light/dark theming.** The bootstraps now run a short wizard — **leader key** (`Ctrl+Space`/`Ctrl+A`/`Ctrl+B`/custom `mod-key`), **theme** (`dark` Catppuccin Mocha / `light` — now VS Code Light Modern / `follow` the OS), and **apps** (accept the recommended set or pick per-app from a catalog incl. `zed`/`tldr`/`nvtop`/`lazydocker`). Each prompt is skippable with an env var (`TS_LEADER`, `TS_THEME`, `TS_APPS=recommended|all|none|csv`) so scripted/`curl|bash` installs stay non-interactive. Choices are **persisted** — chezmoi `[data]` in `~/.config/chezmoi/chezmoi.toml` on WSL/Linux/macOS, mirrored to `%LOCALAPPDATA%\terminal-stack\config.json` on Windows — so `ts-update` keeps honoring them across updates. New **`ts-config`** command (both shells): bare = interactive menu; one-shot `ts-config theme follow` / `ts-config leader ctrl-a` / `ts-config tmux ctrl-a` / `ts-config apps` / `ts-config show`; it re-applies and installs newly-selected apps (never uninstalls). **Theming spans the whole stack:** WezTerm (`get_appearance()` lets `follow` switch *live*), Starship (light/dark palettes) and tmux (themed status bar) all flip together; in `follow` mode the Starship/tmux palette is baked at apply time and refreshed by `ts-update`/`ts-config`. The WezTerm leader is now configurable, and tmux gains a configurable prefix (`tmuxPrefix`, default `C-b`, kept separate from the WezTerm leader). New helpers: `bootstrap/_config.{sh,ps1}` (store I/O, app catalog, chord/theme mapping), `bootstrap/_wizard.sh`, `bootstrap/ts-config.sh`; the themed/leader files became templates (`dot_wezterm.lua.tmpl`, `windows/.wezterm.lua.tmpl`, `dot_config/starship.toml.tmpl`, `windows/.config/starship.toml.tmpl`, `dot_tmux.conf.tmpl`) driven by chezmoi `[data]` (WSL/native) or `__LEADER_*__`/`__THEME_*__`/`__TMUX_PREFIX__` tokens (Windows sync). Existing installs that update before running the wizard keep today's look (Ctrl+Space, Mocha) via template defaults. Rationale in `docs/decisions.md`.

- **Repeatable, arrow-driven WezTerm pane modes (key tables).** After the leader, arrows enter a *mode* that repeats without re-pressing `Ctrl+Space`: `Leader+←/→/↑/↓` = move focus, `Leader+Shift+←/→/↑/↓` = resize (3 cells), `Leader+Ctrl+←/→/↑/↓` = rotate panes through their slots (WezTerm has no directional pane-move, so this is `RotatePanes` — `←`/`↑` counter-clockwise, `→`/`↓` clockwise). Inside a mode, arrows **or** `j/k/i/m` repeat; every mode auto-exits on any non-mode key or a short idle (`Esc`/`Enter` leave immediately; resize originally stayed sticky until the 08/19 overhaul de-stickied it). Also `Leader+t` = repeatable tab-switch and `Leader+f` = font-size modes. A sapphire badge (`⤢ RESIZE` / `✛ MOVE` / `⟳ ROTATE` / `⇥ TAB` / `A± FONT`) shows the active mode in the right-status. Replaces the old one-shot `Leader j/k/i/m` (move) / `J/K/I/M` (resize) bindings. Both `windows/.wezterm.lua` and `dot_wezterm.lua`.

- **Clipboard helpers + `ccat` (both shells).** `clipcopy` (stdin → system clipboard; `wl-copy`/`xclip`/`clip.exe`/`pbcopy` chain on zsh, `Set-Clipboard` on pwsh) and `catclip <file>` (a file's contents → clipboard). The bat-without-paging alias is renamed `cat`→**`ccat`** so the real `cat` isn't shadowed (scripts, copy-pasted examples, and muscle memory keep working). PowerShell also gains `hgrep` over PSReadLine history.

- **Neovim and Zed added to the toolset.** `nvim` installs everywhere — current release via `ppa:neovim-ppa/unstable` on Debian/Ubuntu (apt's is too old on jammy; Debian falls back to its own repo), a brew formula on macOS, `Neovim.Neovim` via winget on Windows. **Zed** (GUI editor) is an optional pick in the install wizard's app catalog (off by default) on every platform — brew cask on macOS, `Zed.Zed` via winget on Windows, `zed.dev/install.sh` on Linux — select it interactively or with `TS_APPS=…,zed` / `ts-config apps`. `$EDITOR` stays `micro`. (Superseded by the install-wizard entry above; the old `TS_EXTRA_TOOLS` flag is replaced by `TS_APPS`.)

- **`doc` — a personal, repo-canonical markdown knowledge base.** Topic runbooks live as plain `.md` under `docs/kb/` in the clone (tracked; `docs/**` is already chezmoi-ignored, so no deploy step and no generate-twins pipeline) plus an untracked personal layer at `~/.doc.local` (real hostnames/key names, never committed) merged in by the viewer. One cross-shell `doc` function (zsh in `dot_zshrc`, pwsh marker block in `$PROFILE`): fuzzy finder (`fzf` + live `glow` preview, `bat` fallback), direct open (`doc veracrypt`), `doc -g` grep, `doc cmd` (find a command and drop it on the prompt via `print -z` / PSReadLine `Insert`), `doc tui`, `doc edit`/`new`, `doc ls`, `--os`, and **`doc sync`** (stages only `docs/kb` + `CHANGELOG.md`, inserts a `### Docs` bullet under `[Unreleased]`, opens the editor prefilled, pushes after a y/N prompt). Seeded with apt update, `.ssh` chmod, GitHub key gen+add, VeraCrypt (generic + personalized in `.local`), and scp/rsync between servers. **`wzr` is now a thin alias into it** (`wzr panes` → `doc wezterm/panes`); its old `.txt` topics moved to `docs/kb/wezterm/`, and the standalone script + `~/.wezterm-ref` are removed (`.chezmoiremove` cleans the deployed copies). `ref` is now an alias into `doc` too, and the `command-reference` content moved into `docs/kb/` (see **Removed**).

- **`glow` (Charm's terminal markdown renderer) now installs on Linux and macOS too.** Windows already shipped it via winget (`charmbracelet.glow`); the Debian/Ubuntu bootstrap (`_common-debian.sh`, used by both WSL and native Linux) now adds Charm's apt repository — keyring at `/etc/apt/keyrings/charm.gpg`, source at `/etc/apt/sources.list.d/charm.list` — and installs `glow` from it (idempotent, non-fatal), and `mac-bootstrap.sh` adds `glow` to the brew formulae. `glow file.md` renders a single file with the Nerd Font glyphs; `glow .` opens the TUI browser. (Charm's repo is the first third-party apt source the stack adds; every other non-apt tool uses the `common_install_github_binary` fallback.)

### Docs

- **Per-tool `doc` cheat-sheets** under `docs/kb/common/tools/` for every installed tool — `eza`, `fzf`, `bat`, `ripgrep`, `zoxide`, `delta`, `starship`, `chezmoi`, `micro`, `glow`, `neovim`, `zed` (`doc eza`, `doc nvim`, …). `doc <name>` now falls back to the fuzzy finder when there's no exact label match, so `doc nvim` finds `neovim` and `doc rg` finds `ripgrep`.

### Changed

- **WezTerm leader key no longer times out, and shows a "waiting" indicator.** `config.leader.timeout_milliseconds` is now ~24h (WezTerm has no true "infinite"), so `Ctrl+Space` waits for the next key instead of silently expiring after 1.5s. While the leader is pending the cursor turns peach instantly (`compose_cursor`) and a bold `⌨ LEADER` badge appears in the right-status (`status_update_interval` lowered to 100ms so it's snappy); `Ctrl+Space` then `Esc` cancels cleanly (a no-op `LEADER+Escape` binding). Applied to both `windows/.wezterm.lua` and `dot_wezterm.lua`.

- **zsh history reworked: per-shell, keep-dups-in-session, broader secret filter.** `HISTSIZE`/`SAVEHIST` 50k→100k; `HIST_IGNORE_DUPS`/`HIST_IGNORE_ALL_DUPS` off in favour of `HIST_EXPIRE_DUPS_FIRST` (keep dups while working, trim oldest only when the file fills); `SHARE_HISTORY`→`INC_APPEND_HISTORY` (each shell keeps its own history, appended as you go). New `history` shows the last 200 by default — `history all` imports other shells + shows everything, `hgrep <pattern>` greps all history. The `zshaddhistory` secret filter is broadened (API-key shapes, `Bearer`, `--token`/`--api-key`, `OPENAI/ANTHROPIC/GITHUB/GH/NPM` tokens, `_KEY=`/`_SECRET=`/`_PASSWORD=`/`_TOKEN=`).

- **`~/.claude/settings.json` no longer imposes personal preferences, permission posture, or plugins.** The tracked templates were baking a default model (`claude-fable-5[1m]`), `effortLevel: xhigh`, `theme`, `tui`, `autoUpdatesChannel`, and voice flags into `settings.json`, plus a loosened permission posture (`permissions.defaultMode: "auto"`, `skipDangerousModePermissionPrompt`, `skipAutoPermissionPrompt`) and two enabled plugins (`claude-obsidian`, GitKraken's `gitkraken-hooks`). Because the file is managed whole-file, every `chezmoi apply`/Windows sync reverted whatever you'd chosen in the Claude UI and silently re-applied the auto-approve permission mode and third-party hooks on every machine. Both `settings.json.tmpl`s now carry **only** the `statusLine` command and the `wez-tab-status` hooks — the actual stack infrastructure; model, effort, theme, permission mode, and plugin enablement are left to your live file / the Claude UI and are no longer clobbered. Rationale in `docs/decisions.md` § "Why `settings.json` ships only shared infra — no model, prefs, permissions, or plugins".

### Removed

- **The `command-reference` render pipeline, replaced by the `doc` knowledge base.** Its content moved into the `docs/kb/` tree (`common/` + per-OS `linux/`/`macos/`/`windows/` + `wezterm/`); `ref` and `wzr` became thin aliases into `doc`. Deleted: `command-reference.md.tmpl` and its `.txt.tmpl`/`.html.tmpl` twins, `windows/command-reference.{md,txt,html}`, `scripts/render-command-reference.sh`, the `docs/command-reference/` per-OS previews, `run_after_10-check-command-reference.sh`, and the staleness block in `scripts/sync-windows.ps1`. No more generate-and-commit-twins step or "twins are stale" warnings — `glow` renders the `.md` directly, and per-OS selection happens at runtime in `doc`. The browser/Obsidian `.html` export is gone (rationale in `docs/decisions.md` § "Why `doc` replaced the command-reference render pipeline"). `.chezmoiremove` drops the old deployed `~/command-reference.{md,txt,html}` on the next POSIX apply (your untracked `command-reference.local.md`, if any, is left alone).

### Fixed

- **Install prompts are editable; the workspace prompt expands `~`.** The wizard / cleanup / clone-location / workspace prompts used plain `read`, so Backspace and arrow keys inserted raw control codes — they now use readline (`read -e`). And a `~/foo` workspace answer was stored verbatim as `WORKSPACE_DIR="~/foo"` (unexpanded → `ws` couldn't `cd`); a leading `~` is now expanded.

- **`~/.zshrc` no longer dies with a parse error on a fresh oh-my-zsh shell.** The reworked `history` *function* (the per-shell history feature) collided with oh-my-zsh's `alias history='omz_history'` (from `lib/history.zsh`): with that alias live, zsh alias-expands the name in `history() { … }` and raises *"defining function based on alias `history'"* — a **parse error that aborts the entire `~/.zshrc`**, so Starship, `doc`, `ws`, the `cc*` wrappers, `ts-*` — nothing after line ~109 loads (you get a bare `%` prompt and "command not found" for everything). Fixed with a one-line `unalias history 2>/dev/null` before the function definition. (This is why `doc`/`ws` appeared missing even after a correct install — the clone and `sourceDir` were fine; the shell config never finished sourcing.)

- **chezmoi no longer litters `$HOME` with the installer scripts.** `install-linux.sh`/`install-mac.sh`/`install-wsl.sh`/`install.ps1` and `scripts/sync-windows.ps1` live at the repo root for the raw-URL one-liners, but they were missing from `.chezmoiignore`, so `chezmoi apply` deployed them as `~/install-linux.sh`, `~/scripts/sync-windows.ps1`, etc. on every run. They're now ignored, and `.chezmoiremove` drops the copies a previous apply already wrote (your own `~/scripts` contents are untouched — only the stack's `sync-windows.ps1` is removed).

- **WSL cleanup no longer pre-ticks your Windows-side clones.** A clone discovered under `/mnt/c/...` during the installer's cleanup is almost certainly your active Windows install or a dev checkout; deleting it from WSL would nuke the Windows-side repo. Such clones are now listed **unticked** with a warning label (you can still select them deliberately). Relatedly, `ts-doctor`/`Test-TerminalStack` treat leftover clones as an advisory note rather than a counted "issue", so a healthy install with old clones around still reports "all checks passed".

- **Re-running an installer no longer leaves `chezmoi apply` deploying a *stale* clone.** Each POSIX bootstrap used to print *"chezmoi.toml already exists; not overwriting sourceDir"* and leave the file untouched on a re-run. If a previous install had recorded a `sourceDir` pointing at an older clone (e.g. `~/terminal-stack`), a fresh clone at a new path (e.g. `~/code/terminal-stack`) was silently ignored — `chezmoi apply` kept rendering the old source, so newly-added features (like `doc`) never landed and the apply printed no changes. The bootstraps now call `ts_ensure_source_dir`, which **repoints a differing `sourceDir` while preserving the `[data]` block**; `ts-doctor` detects and repairs the same condition on an existing install. (Windows had a parallel hole — `Resolve-TsSourceDir` falls back to a hard-coded default and never consulted the real clone path; `ts-doctor`/install.ps1 now persist `$env:TERMINAL_STACK_DIR` to `profile.local.ps1`.)

- **`!! apt install eza/git-delta failed` is no longer a false alarm.** On Debian/Ubuntu releases that predate these packages (e.g. Ubuntu 22.04 jammy) the apt call is *expected* to fail and a GitHub-release fallback installs the binary — but the fallback ran silently, so the scary "failed" line was the only output. `_common-debian.sh` now suppresses the apt warning for ids that have a fallback and reports the real outcome (the fallback's own "Installed ~/.local/bin/…" line, or a single honest `eza/delta unavailable` only if both apt *and* the release fetch fail).

- **Per-pane Claude background tint now actually changes on Windows.** The `c7cd6c1` feature emitted the tint as an `OSC 11` background sequence from the hook, but on Windows every pane's byte-stream passes through **ConPTY**, which intercepts `OSC 10`/`11`/`12` and never forwards them to WezTerm — so the tab title and `cc_state` dots updated (they bypass the stream: the mux socket and the passed-through `OSC 1337` user var respectively) while the pane background stayed flat. Since WezTerm exposes no per-pane background in Lua, the tint must come from inside the pane via OSC 11 — exactly what ConPTY ate. Fixed by re-driving the tint from the already-reliable `cc_state` user var: a new `user-var-changed` handler in both `.wezterm.lua` configs calls **`pane:inject_output('\x1b]11;…')`**, which feeds the sequence straight into WezTerm's own emulator, downstream of ConPTY. Reset is free (the `cc`/`Set-WezTabTitle` wrappers already clear `cc_state` on exit → fires the handler with an empty value → base colour). The hook's raw OSC 11 is kept as the fallback for mux/SSH panes where `inject_output` is unsupported. Full write-up in `docs/powershell-quirks.md` § "ConPTY swallows the OSC 11 pane background tint".

- **Documented why `Ctrl+Space` and `F1`–`F6` look dead on macOS.** macOS reserves `Ctrl+Space` system-wide for *Input Sources → "Select the previous input source"* and treats the bare F-row as hardware media keys, so it swallows the WezTerm leader and the pane-grid keys — and the `Ctrl+Space 1`–`6` F-key fallback with them — before WezTerm ever sees the keystroke. Nothing in the docs warned a Mac user. Added the two-toggle fix (enable *"Use F1, F2, etc. keys as standard function keys"*; uncheck the *Select the previous input source* shortcut) to the darwin block of `command-reference.md.tmpl` (with regenerated `.txt`/`.html` twins and the `docs/command-reference/macos/` preview), `INSTALL.md` § macOS, the README WezTerm bullet, and `docs/decisions.md`. No config change — the bindings stay byte-identical across Windows/macOS/Linux by design.

## [1.2.0] — 06/13/2026

### Added

- **Per-pane Claude Code state, shown in the tab bar and pane background.** The `wez-tab-status` hook now emits two things for the pane Claude runs in: an **OSC 11 background tint** (peach = working, green = done, red = error) and an **OSC 1337 `cc_state` user var**; the `cc`/`ccc`/… wrappers (zsh) and `Set-WezTabTitle` (pwsh) reset both on exit. `format-tab-title` reads `cc_state` to draw one coloured dot per pane (● working/done/error, ○ idle) and tint the whole tab **green** (done) / **red** (error) on its most urgent pane — so a multi-pane tab shows which panes are busy, finished, or need you even when it is inactive. DCS-wrapped for tmux passthrough; works on both WSL/zsh and Windows/pwsh (the latter writes to `CONOUT$` because the hook's stdout is captured by Claude Code).

- **Per-OS command-reference previews committed under `docs/command-reference/`.** The final post-template content every platform receives — `linux/` (≡ WSL; the two render byte-identical), `macos/`, `windows/`, each in all three formats (`.md`/`.txt`/`.html`) — is now browsable in the repository. `scripts/render-command-reference.sh` gained an embedded chezmoi shadow-resolver (`resolve_template`) that resolves the `{{ if eq/ne .chezmoi.os ... }}` gates per OS, hard-fails on any unrecognized template construct, and is byte-verified against real `chezmoi execute-template` output (including the template's no-final-newline edge). Previews regenerate in the same script run as the `.txt`/`.html` twins and are covered by the same `--check` / `run_after_10` staleness warnings; `docs/**` is chezmoi-ignored, so nothing in the folder is ever deployed. See `docs/command-reference/README.md` and `docs/decisions.md` for the trade-off (a deliberate, bounded shadow of chezmoi's template engine, accepted for in-repo browsability).

- **Command reference now ships in three formats per environment** — `.md` (Obsidian / `ref`), `.html` (browser), `.txt` (console) — for both `command-reference.md.tmpl` (→ `~/command-reference.{md,html,txt}` on WSL/Linux/macOS) and `windows/command-reference.md` (→ `%USERPROFILE%`). The `.txt` is a byte-identical copy of the `.md`; the `.html` is a self-contained styled page (dark-mode aware, embeds a `source-sha256:` comment of its markdown source). Both twins are *generated, committed* files produced by the new `scripts/render-command-reference.sh` (bash + POSIX awk, runs under WSL, Git Bash, or macOS) — run it after any markdown edit and commit all four outputs. Consistency is enforced warn-only on both deployment paths: the new `run_after_10-check-command-reference.sh` re-renders and byte-compares on every POSIX `chezmoi apply`, and `scripts/sync-windows.ps1` hash-checks the Windows twins on every Windows-native sync. The WSL-side twins are `.tmpl`s — the converter passes `{{ ... }}` lines through verbatim, so the per-OS sections (darwin/Linux gates) still resolve at apply time in all three formats.

- **`plain` — escape hatch to a vanilla shell** (both shells, same cross-shell name convention as `ts-update`). pwsh: nested `pwsh -NoLogo -NoProfile`; zsh: nested `zsh -df` (no rc files). Tab title shows `plain • <dir>` while inside; `exit` drops back to the customized shell. The Windows `launch_menu` (`Alt+L`) gains matching "PowerShell 7 (plain)" and "WSL zsh (plain)" entries for new-tab use. Documented in both command references.
- **`help.autocorrect = prompt`** in the stack git include (canonical + Windows mirror): a typo'd subcommand (`git pulll`) offers the correction and waits for y/n instead of erroring. Needs git ≥ 2.40 — all bootstrap targets ship newer.
- **`Ctrl+Space x` closes the current pane** (both `windows/.wezterm.lua` and `dot_wezterm.lua`), with a confirmation prompt. `x` was freed when the domain picker moved to `Ctrl+Space V`. `wzr panes` cheat-sheet updated to match.
- **WezTerm workspace management** (both `windows/.wezterm.lua` and `dot_wezterm.lua`). New leader keys: `Ctrl+Space R` renames the current workspace (`wezterm.mux.rename_workspace`); `Ctrl+Space X` "kills" it — closes every pane (WezTerm exposes no Lua tab/workspace close, so it collects pane ids from the mux and runs `wezterm cli kill-pane`, switching to another workspace first so the app doesn't quit, and refusing when it's the only workspace). `wzr workspace` and both command references updated to match. Rationale in `docs/decisions.md`.
- **`wzr` — WezTerm key reference at your fingertips.** `wzr <topic>` (`panes`, `tabs`, `workspace`) prints a focused cheat-sheet of the leader keys; `wzr list` shows the topics. Deployed as `~/.local/bin/wzr` (zsh/Linux/macOS) and a matching `wzr` function in `$PROFILE` (Windows), each reading aligned `.txt` topic files from `~/.wezterm-ref/`.
- **`micro` editor on every target**, set as the default `$EDITOR`. Installed via apt (WSL/native Linux), `zyedidia.micro` through winget (Windows), and brew (macOS). The shells pick it up defensively: zsh exports `EDITOR=micro` only when the binary is present (falling back to `nano`, so bare ssh servers without micro still edit), and the pwsh `$PROFILE` sets `$env:EDITOR='micro'` when installed. git follows `$EDITOR`.

### Changed

- **WezTerm tab bar returned to the fancy/native bar**, restyled to match the theme (`window_frame` Catppuccin titlebar + bold Nerd Font, `colors.tab_bar`) and given a **per-pane process icon** in each label (pwsh/zsh/nvim/git/node/python…, a robot while Claude runs) plus a zoom indicator. Supersedes the short-lived flat retro bar from earlier in this cycle; Nerd-font glyph lookups are fallback-guarded so a missing glyph can't break the bar.
- **`F1`…`F6` pane grid rewritten to be geometry-driven** (`dot_wezterm/pane_grid.lua` + Windows mirror). Cell labels are recomputed from on-screen pane positions on every press, so `F<n>` always lands on the same cell regardless of build order: press an existing cell to focus it, the next-in-order cell to build it, anything else is a no-op. **`F1` now also maximizes the window.** Replaces the old pane-id-tracked construction tree. WezTerm has no equalize API, so a manually resized grid isn't auto-re-evened — rebuild with the F-keys.
- **WezTerm keybindings + pane signalling reworked** (both `windows/.wezterm.lua` and `dot_wezterm.lua`). Inactive panes dim harder (`inactive_pane_hsb` brightness `0.25`) with a bright lavender split line, and the right-status shows the active workspace + cwd. Keys: local splits are `Ctrl+Space h` (below) / `v` (right); `Ctrl+Space H` / `V` open a fuzzy domain picker and split the chosen domain (local / WSL / SSH) below / right; tab selection moved to `Alt+1…9` (the number matches the tab) with `Ctrl+Tab` / `Ctrl+Shift+Tab` to cycle — replacing the old `Ctrl+Space 6-9`, which clashed awkwardly with the `Ctrl+Space 1-4` quadrant grid. Command references and `wzr` updated to match.
- **`front_end` returned to `WebGpu`** (the WezTerm default) on both GUI configs, reverting the temporary `OpenGL` workaround (`7922da8`) now that the Intel-iGPU startup stall it addressed has cleared on current WezTerm nightly. OpenGL stays documented as the one-line fallback (`docs/decisions.md`, `docs/powershell-quirks.md`) if the stall ever returns.

### Fixed

- **Bare `chezmoi init` no longer breaks the setup.** `.chezmoi.toml.tmpl` now re-emits `sourceDir` (and `windowsUsername` when present) from the existing config. Previously, answering the apply-time warning "config file template has changed, run chezmoi init to regenerate" with a bare `chezmoi init` silently dropped `sourceDir` — chezmoi would fall back to `~/.local/share/chezmoi` and stop seeing the clone.
- **CLAUDE.md / decisions.md described `$PROFILE` as marker-block *merged*, but the sync has always been whole-file** (both `run_after_90-sync-windows.sh` and `scripts/sync-windows.ps1` copy the rendered source over the target, with `.bak`). Docs now state the real contract: whole-file sync + marker-block editing discipline, personal content in `profile.local.ps1`. Without this fix an agent following CLAUDE.md would wrongly assume hand-edits to the live `$PROFILE` survive an apply.

## [1.1.1] — 06/10/2026

### Added

- **macOS sections in the shared command reference.** `command-reference.md.tmpl` gains three darwin-gated sections (`{{ if eq .chezmoi.os "darwin" }}`, the mirror of the existing `ne` gate that hides systemd/docker on Macs): **WezTerm leader keys** (the macOS counterpart of the section `windows/command-reference.md` already had — same `Ctrl+A` bindings, verified against `dot_wezterm.lua`), **Homebrew maintenance** (`update`/`upgrade`/`cleanup`/`doctor`, including the `brew upgrade --cask wezterm@nightly` reminder since the plain `wezterm` cask is stale), and **macOS utilities** (`pbcopy`/`pbpaste`, `open`, `mdfind`, `caffeinate`). Linux/WSL renderings are unchanged.

### Changed

- **Default Claude Code model unified to `claude-fable-5[1m]`** in both settings templates. The POSIX side (`dot_claude/settings.json.tmpl`) was pinned to `sonnet[1m]` and the Windows side (`windows/.claude/settings.json.tmpl`) to `opus[1m]`; a `/model` choice made on one machine was silently reverted by the next `chezmoi apply`. Both now carry Fable 5 with the 1M context window.

## [1.1.0] — 06/10/2026

First tagged release (`v1.1.0`). Includes everything that had accumulated since 1.0.0 (the "[Unreleased → 1.1.0]" section below) plus the following.

### Added

- **Workspace navigation is location-independent.** `ws`/`wsp`/`wspu` (both shells) resolve the workspace at *call* time: `$WORKSPACE_DIR` — set in `~/.zshrc.local` / `profile.local.ps1` — wins, else the first existing autodetect candidate (`/mnt/c/DATA/Workspace`, `~/Documents/Workspace`, `~/workspace`, `~/Workspace`; pwsh: `C:\DATA\Workspace`, `~\workspace`, `~\Documents\Workspace`). The sibling resolver handles both `Workspace_Personal` (Windows) and `Workspace-Personal` (macOS) naming. `wscalibra`/`wsnetsuite` moved out of the shared configs into the local-file examples — they only exist on one machine. See `docs/decisions.md` § "Why `$WORKSPACE_DIR` + call-time resolution instead of chezmoi templating?".
- **`profile.local.ps1`** — the Windows counterpart of `~/.zshrc.local`, dot-sourced at the end of `$PROFILE`. Untracked; `windows/Documents/PowerShell/profile.local.ps1.example` ships as the documented template.
- **Install-time workspace question.** All bootstraps autodetect the workspace and prompt with the detection pre-filled (reading `/dev/tty`, so the prompt survives `curl | bash`; `WORKSPACE_DIR` env skips it). The answer persists to the local override file *only* when it differs from autodetect.
- **`ts-rollback`** (zsh + pwsh). `ts-update` now fetches first, prints the incoming commits, and records the pre-pull HEAD to `~/.local/state/terminal-stack/rollback-sha` / `%LOCALAPPDATA%\terminal-stack\rollback-sha` before pulling; `ts-rollback` resets the clone to that SHA and re-applies. Both refuse on a dirty clone (it may double as a dev checkout). Manual fallback documented in README § Updating & rollback.
- **`ref` + shipped command reference.** `command-reference.md.tmpl` applies to `~/command-reference.md` (systemd/docker sections gated off on macOS via `.chezmoi.os`); `windows/command-reference.md` mirrors a PowerShell/WezTerm-flavored version to `%USERPROFILE%`. `ref` (both shells) renders it with bat, appending the untracked `command-reference.local.md` when present.
- **Git include** — `~/.config/git/terminal-stack.gitconfig` (chezmoi-managed; byte-identical `windows/.config/git/` mirror) carries the `git st/lg/lga/br/co/cm` aliases and delta pager wiring (`core.pager`, `interactive.diffFilter`, `delta.navigate`). Bootstraps add `include.path` to the global gitconfig once, idempotently; the user's own `~/.gitconfig` still wins on conflicts.
- **Opt-in extra tools** in the bootstraps (`TS_EXTRA_TOOLS=1` or prompt): `tldr` always, `nvtop` only on GPU hosts (`nvidia-smi` present), `lazydocker` only where docker exists. macOS via brew; Windows skipped.

### Changed

- **`gp` and `gl` now mean *pull* and *log* on every machine.** The OMZ git plugin defines `gp='git push'` and `gl='git pull'` — a cross-machine footgun once muscle memory expects pull/log. `dot_zshrc` overrides both after oh-my-zsh sources; pwsh gains matching `gst`/`gp`/`gco`/`gf`/`gl`/`gd`/`ga`/`gb` functions in a new `git-shortcuts` marker block.
- **`dot_zshrc.local.example`**: `dot-pull` example no longer flattens `~/.ssh/config` into `~/config` (each file now pulled with its own rsync); new `WORKSPACE_DIR` and project-nav examples.

## [Unreleased → 1.1.0] — entries logged 06/05/2026, released in v1.1.0

### Added

- **GitKraken + claude-obsidian plugin enablement tracked in `windows/.claude/settings.json.tmpl`.** Claude Code writes plugin marketplaces and enable-flags directly into `~/.claude/settings.json`, which this repo manages whole-file — so the next `chezmoi apply` would have silently wiped both the `claude-obsidian` and `gitkraken-hooks` plugins. The template now carries `extraKnownMarketplaces` + `enabledPlugins` (the gitkraken marketplace path is tokenized with `__WIN_USER__`; the claude-obsidian `directory` source is a deliberately machine-specific local path). See `docs/decisions.md` § "Why the Windows settings template tracks the claude-obsidian + gitkraken plugins". The companion diagnosis of the GitKraken AI-hook log flood and the 0-byte `gk.exe` symlink red herring is written up in `docs/powershell-quirks.md` § "GitKraken `gk ai hook` plugin".
- **`.gitattributes`** enforcing `* text=auto eol=lf` plus binary markers for image/archive types. Overrides Windows' `core.autocrlf=true` (which is on at the system level by default) so fresh clones get LF in the working tree on every platform. Without this, every chezmoi-source file was being silently rewritten as CRLF on Windows checkout, then propagated through chezmoi to WSL — symptoms: `~/.zshrc:3: command not found: ^M`, `run_after_90-sync-windows.sh` failing with `env: $'bash\r': No such file or directory`, and spurious `.bak` files on every apply. See `docs/decisions.md` § "Why `.gitattributes` with `eol=lf`".
- **Cross-platform Nerd Font glyphs in `starship.toml`**: folder ( U+F07B), octocat ( U+F408) + git-branch ( U+E725), clock ( U+F017), per-distro OS logos (Ubuntu , Debian , Arch , Alpine , Fedora , macOS , Windows , and ~15 others). Both `dot_config/starship.toml` and `windows/.config/starship.toml` are now byte-identical and produce the rounded-frame two-line prompt from `context/bestprompt.jpg` on both sides — only the OS glyph differs by platform.
- **eza-backed `ls/ll/la/lt` functions** in the pwsh `cli-tools` marker block, matching the Linux `dot_zshrc` alias (`eza --icons=always --git --group-directories-first`). The built-in `ls` alias is removed first since pwsh pre-aliases it to `Get-ChildItem`. `ll` adds long-form (`-l`), `la` adds hidden+long (`-la`), `lt` switches to tree view (`--tree`).
- **Glow** (`charmbracelet.glow`) added to the Windows winget core packages for in-terminal markdown rendering. `glow README.md` renders a single file with the WezTerm Nerd Font glyphs; `glow .` opens a TUI file browser. No profile wrapper — winget puts it on PATH and the defaults are sensible.
- **`ccr` / `ccdr` resume shortcuts** on both shells. `ccr` runs `claude --resume`, `ccdr` runs `claude --dangerously-skip-permissions --resume`. PowerShell wraps each call in the existing `Set-WezTabTitle` try/finally pattern; zsh wraps via a new `_wez_tab_title` helper. Closes the gap where neither shell had a one-keystroke way to resume the previous Claude session.
- **`ws` / `wsp` / `wspu` / `wscalibra` / `wsnetsuite` workspace nav on zsh.** Mirrors the existing PowerShell functions that cd into `C:\DATA\Workspace*`. The zsh versions target `/mnt/c/DATA/Workspace*` and are guarded by `[[ -d /mnt/c/DATA/Workspace ]]` so the same `dot_zshrc` stays correct on native Linux — the guard fails and no `ws*` functions are defined, instead of defining ones that would error on call. See `docs/decisions.md` § "Why guard `ws*` on `/mnt/c` existence rather than `$WSL_INTEROP`?".
- **macOS support, validated end to end.** The stack now applies cleanly on macOS (Apple Silicon and Intel). `bootstrap/mac-bootstrap.sh` is no longer an untested stub — it installs the toolchain via Homebrew (zsh, git, tmux, eza, zoxide, fzf, bat, git-delta, ripgrep, Starship, chezmoi, the `wezterm@nightly` cask, the JetBrainsMono Nerd Font cask), installs oh-my-zsh, and writes `~/.config/chezmoi/chezmoi.toml` with `sourceDir` auto-detected from the script's own location. The `wezterm@nightly` cask is used deliberately — the plain `wezterm` cask is pinned to the stale `20240203` stable. The `run_after` Windows-sync hook self-no-ops on macOS exactly as it does on native Linux. New `INSTALL.md` § 2M documents the path.
- **`dot_wezterm.lua`** — a macOS WezTerm config, the chezmoi-managed counterpart of `windows/.wezterm.lua`. Same font stack (JetBrainsMono Nerd Font → CaskaydiaCove → Menlo), Catppuccin Mocha, fancy tab bar, `Ctrl+A` leader with tmux-style pane splits/navigation, `format-tab-title` / `update-right-status` hooks, and `front_end = 'OpenGL'`. Drops the Windows-only `default_prog`/`launch_menu` (macOS defaults to the login shell). Gated to darwin via a now-templated `.chezmoiignore` so WSL and native-Linux homes don't get a dead `~/.wezterm.lua`. See `docs/decisions.md` § "Why a separate `dot_wezterm.lua` for macOS".
- **Integrated window buttons in the WezTerm tab bar** — `window_decorations` changed from `'RESIZE'` to `'INTEGRATED_BUTTONS|RESIZE'` in both `windows/.wezterm.lua` and `dot_wezterm.lua`. Previously `'RESIZE'` drew a resize border with no title bar and *no* minimize/maximize/close controls at all; the fancy tab bar now carries the standard Min/Max/Close set in its upper-right (native-styled per platform — `Windows` on Windows, `MacOsNative` on macOS). Requires `use_fancy_tab_bar = true`, already set.
- **`LEADER o` pops the current tab into a new window** in both WezTerm configs. WezTerm has no native mouse drag-to-detach (GH discussion #4080, issue #549); this binds `Ctrl+A o` to a `pane:move_to_new_window()` callback as the supported equivalent. `o` was free among the existing leader bindings (`w n \ - h l k j`). For ad-hoc use the CLI equivalent is `wezterm cli move-pane-to-new-tab --new-window`.

### Fixed

- **Claude Code tab-status hook was dead on macOS.** `dot_claude/hooks/wez-tab-status.sh` hardcoded `wezterm.exe`, which only exists on WSL via Windows interop — on macOS the binary is plain `wezterm`. The hook now prefers `wezterm` and falls back to `wezterm.exe`, so the `cc ⏳/✓/✗ <project>` tab indicator works on macOS and WSL alike.
- **Deeper `Γ¥»` mojibake** — Claude Code and other native console children call `SetConsoleOutputCP()` and can leave the OS-level console codepage as 437 on exit. The previous fix (commit `116087d`) only consulted `[Console]::OutputEncoding.CodePage`, which is a .NET-side cached value that does NOT reflect direct Win32 codepage changes. The conditional short-circuited as "already UTF-8" while the underlying console was actually 437 → next prompt's `❯` decoded as `Γ¥»`. New approach: P/Invoke `kernel32!GetConsoleOutputCP` / `SetConsoleOutputCP(65001)` in `Invoke-Starship-PreCommand`, probing OS state authoritatively each prompt.
- **All `os.symbols` empty in `starship.toml`** — the Private-Use-Area Nerd Font glyphs had been silently stripped at some prior write, leaving every entry as `""`. The OS module emitted only a trailing space. `bestprompt.jpg` predates the strip. Restored with explicit visible glyphs; comment warns future edits not to round-trip the file through tools that drop PUA characters (U+E000–U+F8FF).
- **`OpenSUSE` rejected by starship's variant parser** — correct casing is `openSUSE`. The parse error silently disabled the entire `[os.symbols]` table on Windows, falling back to starship's emoji defaults (which render as `?` in most Nerd Fonts).
- **WezTerm Claude-Code startup render stall** — switched `front_end` from `WebGpu` to `OpenGL`. The post-Enter output-buffer stall ("type `ccd`, Claude doesn't draw until I press a key") is a known WebGpu behavior on certain Intel iGPU drivers. Also dropped `webgpu_power_preference` (no longer applies) and `max_fps = 120` (default 60 matches typical panel refresh, avoids wasted frames).

### Changed

- **Starship config now single-sourced.** `dot_config/starship.toml` is canonical; `windows/.config/starship.toml` is a byte-identical copy maintained via `run_after_90-sync-windows.sh`. To edit, change `dot_config/starship.toml`, then `cp dot_config/starship.toml windows/.config/starship.toml`.
- **`Invoke-Starship-PreCommand` UTF-8 restore** (in `$PROFILE`) is now the P/Invoke version described under "Fixed". The old `[Console]::OutputEncoding.CodePage` check is gone.
- **zsh `cc*` are functions, not aliases.** Previously plain `alias cc="claude"` etc.; now each invocation sets the WezTerm tab title to `cc • <leaf>` while claude runs and clears it on exit, matching the PowerShell side. Zsh has no `try/finally`, so the new pattern captures the claude exit code via `local rc=$?` before clearing the title and `return $rc` — without that, the function would always exit 0 and mask failures. Leaf computed via zsh's `${PWD:t}` (PowerShell uses `Split-Path -Leaf $PWD`). The `[[ -n "$WEZTERM_PANE" ]]` guard inside `_wez_tab_title` keeps these safe under PuTTY/ssh/native Linux terminals where WezTerm isn't the host.
- **`bootstrap/mac-bootstrap.sh` hardened from its stub state.** `SOURCE_DIR` now auto-detects the repo from the script's own location (`bootstrap/` is one level below the root) with an env-var override, instead of assuming `~/code/terminal-stack`. Dropped the `brew tap homebrew/cask-fonts` call — that tap was deprecated when font casks moved into `homebrew/cask` in 2024. Removed the "UNTESTED STUB" banner now that the path is validated.
- **`.chezmoiignore` is now a template.** It gains a `{{ if ne .chezmoi.os "darwin" }}` block that ignores `.wezterm.lua` everywhere except macOS. chezmoi has always evaluated `.chezmoiignore` as a template; this is the first entry in this repo to use that.
- **`ws` / `wspu` zsh functions now have a macOS branch.** The `ws*` block was guarded solely on `[[ -d /mnt/c/DATA/Workspace ]]`, so macOS got no workspace-nav functions. Added an `elif [[ -d "$HOME/Documents/Workspace" ]]` branch defining `ws` (→ `~/Documents/Workspace`) and `wspu` (→ `~/Documents/Workspace-Public`; the macOS dir uses a hyphen where the WSL side uses `Workspace_Public`). Same per-path guard philosophy as the WSL branch — see `docs/decisions.md` § "Why guard `ws*` on `/mnt/c` existence rather than `$WSL_INTEROP`?".

## [1.0.0] — 05/19/2026

Initial terminal stack — single-day deployment across 14+ chezmoi commits. The original work was scoped Phase 0 → Phase 10 (environment detection through final verification). Summary of the resulting capabilities:

### Added — Windows side

- **WezTerm nightly** (`20260331-040028-577474d8`) installed via `winget`, replaces the stale `20240203` stable. Per-pane WebGPU rendering, 120fps cap, 50k scrollback.
- **`.wezterm.lua`** at `%USERPROFILE%\.wezterm.lua` with:
  - JetBrainsMono Nerd Font primary, CaskaydiaCove + Cascadia Code fallbacks
  - Catppuccin Mocha color scheme, 100% opaque (changed from 0.97 after testing)
  - Fancy tab bar at the bottom, `tab_max_width = 120`, `window_frame.font_size = 11.0`
  - LEADER key `Ctrl+A` with tmux-style pane splits and navigation
  - `Ctrl+V` rebound to `PasteFrom 'Clipboard'` so Wispr Flow's synthetic Ctrl+V works in Claude Code (see issue [#38620](https://github.com/anthropics/claude-code/issues/38620))
  - Right-status: workspace · cwd · 12-hour time
  - `format-tab-title` uses `wezterm.truncate_right(title, max_width - 2)` to fit dynamically
- **JetBrainsMono Nerd Font** v3.3.0 installed machine-wide via `winget`
- **Starship 1.25.1** (pre-existing); not modified
- **Modern CLI tools** installed via winget: `eza`, `fzf`, `bat`, `delta`, `ripgrep`
- **PowerShell `$PROFILE`** at `%USERPROFILE%\Documents\PowerShell\Microsoft.PowerShell_profile.ps1`:
  - Marker block `# ---- starship-stack-start ----` with starship init, `Enable-TransientPrompt` guarded by `Get-Command` (works on PSReadLine 2.4.5 which doesn't export it), `Invoke-Starship-PreCommand` emitting OSC 7 (cwd hint) and OSC 0 (tab title with tilde-abbreviated path)
  - Marker block `# ---- cli-tools-start ----` with guarded zoxide init (replaces the previously unframed init line)
  - `Set-WezTabTitle` helper using `wezterm.exe cli set-tab-title` (sticky `tab.tab_title`, survives Claude Code's OSC overrides)
  - `cc` / `ccc` / `ccd` / `ccdc` / `cca` Claude Code wrappers that set `cc • <project>` before launching, clear on exit via `try/finally`
  - UTF-8 console restore at prompt time (heals the `Γ¥»` CP437-decode mojibake Claude Code leaves behind on exit)
- **Claude Code hooks** at `%USERPROFILE%\.claude\hooks\wez-tab-status.ps1`:
  - `UserPromptSubmit` → tab title becomes `cc ⏳ <project>` (thinking)
  - `Stop` → `cc ✓ <project>` (waiting for input)
  - `StopFailure` → `cc ✗ <project>` (error)
  - Commands in `settings.json` use forward slashes in the script path (`C:/Users/...`) to bypass CC's POSIX-style shell layer stripping backslashes

### Added — WSL side

- **zsh** 5.9 installed, set as login shell for `msampson`
- **oh-my-zsh** installed unattended, `ZSH_THEME=""` so Starship owns the prompt, `plugins=(git)` untouched
- **chezmoi** 2.70.3 installed to `~/.local/bin/chezmoi` via the official curl installer
- **Starship 1.25.1** installed in `/usr/local/bin/starship`
- **JetBrains Mono** (regular variant) via `apt`; Nerd Font variant downloaded from `ryanoasis/nerd-fonts` releases into `~/.local/share/fonts/JetBrainsMonoNerdFont/`
- **Modern CLI tools** via apt: `eza`, `zoxide`, `fzf`, `bat` (symlinked from `batcat`), `git-delta`, `ripgrep`
- **`~/.zshrc`**: oh-my-zsh template + marker blocks for Starship, terminal helpers (`precmd` OSC 0 setter, `ccs`, `ssht`), and CLI tool inits
- **`~/.tmux.conf`** with mouse on, base-index 1, `allow-passthrough on`, `extended-keys on` for `xterm*` and `wezterm*` (needed for Claude Code Shift+Enter)
- **`~/.config/starship.toml`** shared with the Windows side: branch symbol, git status `! ?` indicators (reverted from Nerd Font glyphs after user testing), command-duration, cloud-provider modules disabled
- **Claude Code hooks** at `~/.claude/hooks/wez-tab-status.sh` (executable via chezmoi `executable_` prefix), same three states as Windows side; calls `wezterm.exe` via WSL interop

### Added — Cross-side / repo

- **chezmoi source repo** with 14 commits (now living in this repo at `C:\DATA\Workspace\terminal-stack`)
- **`.chezmoiignore`** excluding `windows/**` from chezmoi's standard apply
- **`run_after_90-sync-windows.sh`** post-apply hook that mirrors `windows/` to `/mnt/c/Users/msampson/`, with `.bak.YYYYMMDD[.N]` backups for any overwrite (hardened against same-day clobber after a Phase 7 incident)
- **WSL git identity** mirrored from Windows-side global config

### Fixed (during the same session)

- **`Γ¥»` mojibake** after Claude Code exits — restored UTF-8 console encoding at prompt time in `Invoke-Starship-PreCommand`
- **Wispr Flow paste failing** in Claude Code — bound `Ctrl+V` to `PasteFrom 'Clipboard'` in WezTerm (default only binds `Ctrl+Shift+V`)
- **`Enable-TransientPrompt` not available** on PSReadLine 2.4.5 — wrapped in `Get-Command` guard
- **Hook backslashes stripped by POSIX shell layer** — switched Windows hook paths in `settings.json` to forward slashes (PowerShell accepts them via `-File`)
- **Tab title for `cc` overwritten by Claude Code** — switched from OSC 0 (pane.title) to `wezterm cli set-tab-title` (tab.tab_title, which our `format-tab-title` checks first)

## [Pre-1.0]

Stack didn't exist. WezTerm was on the stale `20240203` stable, PowerShell `$PROFILE` had just the user's workspace navigation funcs and zoxide init, no chezmoi, no oh-my-zsh, no Starship in WSL, no Nerd Font.
