# Verifying a change before you commit

CI runs on every push (`.github/workflows/ci.yml`: ubuntu, macos, windows and a
WSL job) and is the only coverage macOS and native Debian/Ubuntu get, since
neither can be run from a Windows development machine. It does not replace this
page: what follows is the set of gates a runner cannot perform - loading a
WezTerm config without a GUI, proving a Nerd Font glyph actually renders, driving
an interactive prompt through a pty, exercising a real config store.

Run the automated gates first (`ruff check`, `ruff format --check`, `mypy`,
`pytest tests/ --cov`); `.githooks/pre-commit` and `pre-push` do it for you once
`core.hooksPath=.githooks` is set. `INSTALL.md` § Phase 9 is
the *post-install* smoke test for a fresh machine; this is the *pre-commit* pass for
a change you just made.

**On a macOS development clone, install pwsh.** `brew install powershell` (the
formula; the `powershell` *cask* no longer exists and `powershell@preview` is not
what you want). Five gates key off `shutil.which("pwsh")` and skip silently
without it - the AST scan for a local shadowing a typed parameter, the two
`_config.ps1` store tests, the wizard's exclusive-group twin, and the lone-dash
splatting regression. Every one of them runs pure PowerShell with `USERPROFILE`
and `LOCALAPPDATA` overridden, so macOS pwsh satisfies them; none needs Windows.
Skipping is the failure mode that matters here, because the defects those gates
exist for - a literal TAB in a `Join-Path`, a `$foo`/`$Foo` collision that coerced
a scriptblock - all parse cleanly and are invisible to every other check.

Every technique below was worked out the hard way. None of it needs a GUI, a second
machine, or a real `chezmoi apply`.

## 0. Parity: run it on a real Linux, in two seconds

```sh
tests/parity/run.sh                  # debian13, ubuntu2404, ubuntu2204, bash32
tests/parity/run.sh ubuntu2204       # one target
tests/parity/run.sh --shell debian13 # a shell inside it, to poke about
```

**WSL is not native Linux here.** `/mnt/c` exists, interop exists, and
`tstack/platform.py` reports `wsl` rather than `linux` deliberately - so every
native-Linux branch was only ever exercised by CI. That is a slow loop and one
nobody watches while writing the code. The containers run the whole suite in
about two seconds, against each distro's *own* Python, bash and zsh.

The container is a CLEAN CHECKOUT, not a copy of your tree: everything git
ignores is deleted after the copy, so `services/stacks/*/.env` and friends are
absent exactly as they are on a runner. Uncommitted *tracked* changes are still
what gets tested. Copying verbatim let a test that only passes on an installed
machine go green here and red in CI.

That last part is the point. The runner-provided Python hides a class of problem:
CI uses 3.12, this machine has 3.14, and Ubuntu 22.04 - an LTS still in support -
ships 3.10. A test importing `tomllib` (3.11+) broke collection of the entire
suite there, invisibly to every other gate.

**macOS cannot be added.** Containers share the host kernel, so Darwin cannot be
containerised, and macOS VMs are restricted to Apple hardware. The `bash32` target
covers the part of macOS that actually bites this repo - `/bin/bash` is 3.2 there
and `services/**/*.sh` must be clean under it - but only for *syntax*. It does
**not** reproduce the locale-dependent multibyte trap (`"$var<non-ascii>"` under
`set -u`), because musl handles locales differently from Darwin; verified, not
assumed. That trap stays covered by the test that greps for `$var` followed by a
non-ASCII byte, which works everywhere. Real macOS remains CI's job.

## 1. Syntax gates (always, every touched file)

```sh
bash -n <file>.sh                    # every changed shell script
zsh  -n dot_zshrc                    # zsh, not bash — dot_zshrc uses zsh-only syntax
```

```powershell
$e = $null
[System.Management.Automation.Language.Parser]::ParseFile((Resolve-Path $f), [ref]$null, [ref]$e)
$e   # empty = clean
```

`ParseFile` is the pwsh equivalent of `-n`: it parses without executing, so it is
safe on `$PROFILE` and the bootstraps.

**`ParseFile` is weaker than it looks too — pwsh has no `set -u`.** PowerShell
variable names are case-insensitive, so a local `$foo` inside a function taking a
parameter `$Foo` *is* that parameter, and a typed parameter keeps its converter:
assigning a scriptblock to it coerces the block into a `[string[]]` holding its
own source text, so `& $foo` then tries to run that text as a command name. That
parses perfectly and kills the function at runtime — it took out every
`Read-TsMulti` call, i.e. the whole Windows wizard. There is a gate for it:

```sh
python -m pytest tests/test_agent_tools.py -k shadows -q
```

It walks the AST of every `.ps1`/`.psm1` in the repo and fails on any assignment
whose target matches a typed parameter case-insensitively but not
case-sensitively. Run it after touching any PowerShell file.

### Windows: Bash-backed pytest

Run the Python suite normally from PowerShell:

```powershell
python -m pytest tests -q
```

The suite resolves a native MSYS/Cygwin Bash from Git for Windows. It deliberately
rejects `C:\Windows\System32\bash.exe`: that file is the WSL launcher, not a
Windows-hosted POSIX shell, and it cannot consume the Windows paths and minimal
environments used by these tests. If Git Bash is unavailable, Bash-dependent tests
skip explicitly instead of hanging inside WSL. POSIX fixtures also translate temp
paths with `cygpath`, write LF, and decode output as UTF-8; keep those boundaries
when adding another Bash subprocess test.

**`bash -n` is weaker than it looks.** It only proves the file parses. A mangled
`printf 'x\n'` that became a literal two-line string is still valid shell and passes
cleanly. After any programmatic edit that touched an escape sequence, check the bytes:

```sh
sed -n '<range>p' <file> | cat -A
```

Also check nothing picked up CRLF (see `.gitattributes` — the repo forces LF):

```sh
grep -l $'\r' $(git diff --name-only)
```

**Nerd Font glyphs must stay `\u` escapes, never literal characters.** Both
starship templates (`dot_config/starship.toml.tmpl` and
`windows/.config/starship.toml.tmpl`) carry Private-Use-Area glyphs. Pasted
literally they are silently stripped by some editors — which is exactly what
happened: all 19 `[os.symbols]` entries and the folder/branch/clock/lock glyphs
were reduced to empty strings and bare padding spaces, and the prompt lost every
icon with nothing in any diff to explain it. After touching either file, assert
the source contains **no** PUA bytes:

```sh
python3 - <<'EOF'
for p in ["dot_config/starship.toml.tmpl", "windows/.config/starship.toml.tmpl"]:
    s = open(p, encoding="utf-8").read()
    bad = [(i, hex(ord(c))) for i, c in enumerate(s) if 0xE000 <= ord(c) <= 0xF8FF]
    print(p, "PUA bytes:", bad or "none")
EOF
```

Then prove the escapes actually *render* — a valid escape for a codepoint the
font lacks renders as a tofu box, which is worse than the blank it replaced:

```sh
starship prompt --terminal-width=100 --cmd-duration 3000 \
  | python3 -c "import sys;s=sys.stdin.buffer.read().decode('utf8','replace');\
print([hex(ord(c)) for c in s if 0xE000<=ord(c)<=0xF8FF])"
```

Check coverage against the actual font before adding a new codepoint:

```sh
uv run --with fonttools python -c "
from fontTools.ttLib import TTFont
cm = TTFont('$HOME/Library/Fonts/JetBrainsMonoNerdFont-Regular.ttf', fontNumber=0).getBestCmap()
print(0xf07b in cm)"
```

**Do not 'simplify' by deleting `[os.symbols]` and taking starship's defaults.**
Verified 2026-08-23: starship's built-in `Macos` symbol is 🍎 — a colour *emoji*,
not a Nerd Font glyph. Dropping the block trades stripped glyphs for emoji that
clash with the rest of the prompt.

## 2. WezTerm configs — load them without a GUI

Render the template, then let WezTerm parse and execute it:

```powershell
# substitute the tokens the sync would: __WEZ_MUX__ __WEZ_RESTORE__ __LEADER_KEY__
# __LEADER_MODS__ __THEME_MODE__ __THEME_RESOLVED__ __TMUX_PREFIX__
# (for dot_wezterm.lua.tmpl, resolve the {{ }} expressions instead)
& 'C:\Program Files\WezTerm\wezterm.exe' --config-file <rendered>.lua show-keys
```

Copy the matching `pane_nav.lua` next to the rendered file first — the config
`require`s it. **A broken config does NOT fail the command**: `show-keys` exits 0
and silently prints WezTerm's *default* key table instead (verified 2026-08-20
with a deliberately broken config — no traceback on stdout/stderr either). Judge
success by content, not exit code:

```sh
wezterm --config-file <rendered>.lua show-keys | grep -c LEADER   # 0 = config did not load
```

Run it once per value of any new gate (e.g. mux `on` and `off`).

Because the chunk executes at load, you can also **inject `assert`-style tests of
pure helper functions before `return config`** (mock `PaneInformation` tables and
all) in a throwaway copy — a failed assertion aborts the config, which shows up as
the default key table / `grep -c LEADER` → 0. Always run a deliberately-failing
control once to prove the harness bites.

**This is a behavioural test, not just a parse check.** `wezterm.gui` is **non-nil**
under `show-keys`, so the whole `if wezterm.gui then … end` plugin block —
sessionizer, resurrect — actually executes. `Leader+S` / `Leader+L` appearing in the
output is real evidence the resurrect block ran. (Verified with a probe config that
bound a different key depending on `wezterm.gui`; do not assume the opposite.)

Confirm the token was substituted while you are there — a literal `__WEZ_*__`
surviving into the rendered file renders as "not on", which looks correct by accident
while the default is off and breaks the moment someone turns it on:

```sh
grep -c '__WEZ_' <rendered>.lua      # must be 0
```

What this does **not** cover is anything that only happens at GUI startup. For that,
relaunch for real and read the newest log:

```sh
ls -t ~/.local/share/wezterm/wezterm-gui.exe-log-*.txt | head -1 | xargs grep 'lua:'
```

`wezterm.log_info` from config *or plugin* Lua lands there prefixed `lua:`. That log
is what identified `resurrect: restoring workspace '…' on gui-startup`.

## 3. Parallel implementations must render identically

`ts_prompt_choice` (bash) and `Read-TsChoice` (pwsh) are required to produce
byte-identical menus, as are the `wso` and `tstack mux` `-h` texts. Eyeballing them
misses a single space or an em dash. Diff the bytes.

The bash side needs a pty — `ts_prompt_choice` writes the menu to `/dev/tty` and it
is silently discarded when there is none:

```sh
printf "\n" | timeout 20 script -qec "bash -c '. bootstrap/_wizard.sh; ts_prompt_<name> >/dev/null'" /dev/null | tr -d '\r'
```

Wrap the payload in `bash -c`. `script` runs `$SHELL`, which is zsh here, and zsh's
`read -p` means "read from the coprocess" — the prompt helper errors out under it.

**That recipe is util-linux `script`, and it is Linux-only.** macOS/BSD `script`
takes `script [-q] <file> <cmd>...` and does **not** forward piped stdin into
the pty. It fails *silently and wrongly*: the prompt renders, the keystrokes go
nowhere, every run takes the default, and a check of "does option 2 work?"
passes-looking with the option-1 answer. Verified 2026-08-23 — five different
inputs all returned the default. On macOS drive the pty directly instead:

```python
import os, pty, select, time
pid, fd = pty.fork()
if pid == 0:
    os.execvp("bash", ["bash", "-c", ". bootstrap/_wizard.sh; ts_prompt_<name> > /tmp/_answer"])
time.sleep(0.5); os.write(fd, b"2\r")      # then drain fd until EOF
```

Assert on two things, not one: the **answer**, and how many times the prompt was
rendered — a bogus input must render it **twice** (re-prompt), which is the
documented rule that a `default:` catch-all would silently break.

The pwsh side just needs the helper dot-sourced:

```powershell
. bootstrap/_config.ps1; Read-Ts<Name>
```

Then strip ANSI and blank lines, drop the trailing `Choose …` line (it differs
legitimately: a live prompt vs `(non-interactive — taking the default)`), and
`Compare-Object`.

A pwsh prompt must also be **reachable from the `tstack config wizard` path**, which
dot-sources `bootstrap/_config.ps1` and nothing else. A prompt that lives in
`windows-bootstrap.ps1` works during install and dies mid-questionnaire on a
re-run, discarding every answer already given. Resolve the whole callee list from
a clean shell:

```powershell
pwsh -NoLogo -NoProfile -Command @'
. bootstrap/_config.ps1
$b = (Get-Content -Raw bootstrap/_config.ps1)
$b = $b.Substring($b.IndexOf('function Read-TsWizard'))
$b = $b.Substring(0, $b.IndexOf("`nfunction ", 1))
[regex]::Matches($b, '\b(?:Read|Get|Test|Save)-Ts[A-Za-z]+') |
  ForEach-Object { $_.Value } | Sort-Object -Unique |
  Where-Object { -not (Get-Command $_ -ErrorAction SilentlyContinue) }
'@
```

Anything it prints is a prompt `tstack config wizard` cannot see.
`test_wizard_callees_are_all_defined_in_config_ps1` pins the same rule.

## 4. Config-store changes — use a throwaway store

Adding or changing a key in chezmoi `[data]` / `config.json` can be exercised without
touching your real config.

POSIX side — a temp `HOME` with its own `chezmoi.toml`. Omit `windowsUsername` and
`ts_mirror_windows_config` no-ops, so it cannot write to your real Windows mirror:

```sh
H=/tmp/ts-test-home; mkdir -p "$H/.config/chezmoi"
printf 'sourceDir = "%s"\n\n[data]\nos = "wsl"\n' "$PWD" > "$H/.config/chezmoi/chezmoi.toml"
HOME="$H" bash -c '. bootstrap/_config.sh; ts_<key>_get; ts_<key>_set on; ts_<key>_get'
```

Windows side — override `$env:LOCALAPPDATA` in a child pwsh, since `Get-TsConfigPath`
derives from it:

```powershell
$env:LOCALAPPDATA = (New-Item -ItemType Directory -Force "$env:TEMP\ts-test").FullName
. bootstrap\_config.ps1
```

**Always regression-test the carry-forward guard.** Several `Save-TsConfig` callers
pass no value for a given key — `Update-TsResolvedTheme`, and `tstack update`'s
app-backfill. Without `$PSBoundParameters.ContainsKey(...)` handling, every
`tstack update` silently resets the user's choice:

```powershell
Save-TsConfig -<Key> 'on' | Out-Null
Save-TsConfig -ThemeMode 'dark' | Out-Null   # omits the key on purpose
Update-TsResolvedTheme
Get-Ts<Key>                                   # must still be 'on'
```

**Then check both stores agree.** A bash save writes chezmoi `[data]` and mirrors to
`config.json`; a pwsh save writes only the mirror. A new key that is read by one apply
path and written by the other diverges silently — each side renders a valid file from its
own store, and the setting flips depending on which applied last:

```sh
chezmoi execute-template '{{ .<key> }}'      # WSL, authoritative
python -c "import json;print(json.load(open('/mnt/c/Users/<you>/AppData/Local/terminal-stack/config.json')))"
```

Then apply from *both* sides in sequence and confirm the rendered target is byte-identical
after each. If the second apply changes what the first wrote, the two paths disagree about
the key and will keep overwriting each other. See `docs/decisions.md` for the incident.

## 4b. TTS daemon changes (`bootstrap/tts-daemon/`)

The daemon's pure logic (scheduler, registry, summarizer, event parsing) has a
real test suite — run it on any machine, no COM/audio needed:

```sh
cd bootstrap/tts-daemon && python -m pytest tests -q
```

Full-pipeline checks (these speak — Windows, Kokoro up):

```sh
# build the actual GUI-subsystem artifact, then validate its command surface:
pwsh -File bootstrap/tts-daemon/build.ps1
bootstrap/tts-daemon/dist/terminal-stack-tts.exe simulate bootstrap/tts-daemon/fixtures/stop.json

# live daemon drills (use a test port so the real one is undisturbed):
python -m ttsd daemon --no-tray --port 8899 &
curl -s http://127.0.0.1:8899/healthz                 # version = clone HEAD sha
# three stops within ~1s → expect ONE coalesced utterance; check /v1/status:
#   spoken:1, lastLine "Three sessions finished: …"
curl -s -X POST http://127.0.0.1:8899/v1/shutdown
```

**Assert on the log, never the exit code.** The EXE is GUI-subsystem and exits 0 whether or
not it spoke, so a drill that checks `$LASTEXITCODE` passes on a silent build. The only
proof is a `ttsd.pipeline: spoke [engine]: …` line in `logs/ttsd.log`. (A
`ttsd.registry: session …` line proves receipt, not speech.) Note `test` ignores any text
argument — it sends a fixed empty-message stop event — so it cannot be used to check what
gets said, only that the pipeline runs.

Duplicate-speech drills need a **throwaway home**, because the dedupe state and the
config both live under it. Redirecting three variables gives a full sandbox — the live
`~/.claude/tts/config.json`, `history.db` and `speak.lock` are never touched:

```sh
S=/tmp/ttshome && mkdir -p $S/.claude/tts   # copy config.json in, set enabled=true
# three payloads for ONE event (notification / permission / question), then fire together:
for i in 0 1 2; do
  HOME=$S USERPROFILE=$S LOCALAPPDATA=$S dist/terminal-stack-tts.exe _direct $S/p$i.json &
done; wait
HOME=$S USERPROFILE=$S LOCALAPPDATA=$S dist/terminal-stack-tts.exe history
# expect exactly one `spoken` and two `deduped`, and audio that never overlaps
```

Use the **EXE, not bare `python -m ttsd`**, for anything that reaches playback: `winrt`,
`comtypes` and `mutagen` are bundled only in the frozen build, so from source `play()`
fails instantly and `probe_duration` raises — you get `play_failed` rows, or no rows at
all, and conclude the wrong thing. Source mode is fine for `history`, `--check` and the
pytest suite.

Mute drills, in the same sandbox (`ccmute` is the EXE's `mute` subcommand):

```sh
HOME=$S USERPROFILE=$S LOCALAPPDATA=$S dist/terminal-stack-tts.exe mute        # toggle
# then fire the burst: expect zero `spoken` and one `muted` row per hook
HOME=$S USERPROFILE=$S LOCALAPPDATA=$S dist/terminal-stack-tts.exe history
```

The three that actually matter, because each covers a way the old DND failed:

- **With the daemon stopped**, a muted hook must still be silent — that path never consulted
  the old in-memory flag at all.
- **A `P0` question and a `P1` error must both be silenced.** The old `Do not disturb` let
  every question, permission prompt and error through, because it shared
  `quietHours.allowInteractive`, whose default is `true`.
- **An unusable state dir must read as *not* muted.** The mute fails open toward speech, the
  opposite of the history store: a mute you cannot lift looks exactly like broken TTS.

Dashboard and settings changes have their own suite, and it is the one that binds a
socket:

```sh
cd bootstrap/tts-daemon && python -m pytest tests/test_daemon_smoke.py -q
```

That file starts a real daemon on an ephemeral port and talks to it. It exists because a
startup-path `NameError` slipped past 124 unit tests: nothing else in the suite calls
`main()`, so anything reached only by the daemon branch was invisible until a live run.
**Any change to `__main__.py`'s startup, `server.py`'s routing, or the schema needs this
suite, not just the unit tests.**

Four checks worth doing by hand against the built EXE, because they are about honesty
rather than mechanics:

- **The mode test must admit a fall-back.** Clear the API key, select `haiku`, and press
  Test: it has to say it fell back and why. A missing key otherwise produces exactly the
  template line with no exception and nothing logged, which is indistinguishable from
  working.
- **A write with no token must fail.** `POST /v1/config/set` without `X-TS-Token` is a 401,
  and nothing lands in `local.json`. Same for `/v1/mute`, which a cross-site form could
  once reach on an empty body.
- **An override must be visible.** Set something in `local.json` by hand, reload the page,
  and confirm the field says an override is beating the saved value. That label is the whole
  defence against the divergence that removed every TTS hook twice in one day.
- **Restart-required fields must say so.** `/v1/config/reload` returns `ok` for them
  regardless, so a field in that group that does not carry the warning is a lie.

The invariants to drill after touching the hook senders:

- **No console process:** inspect the built PE Optional Header (`Subsystem=2`,
  Windows GUI), run Claude and Cursor hooks with redirected stdin, and verify
  no new `cmd`, `conhost`, `pwsh`, `python[w]`, `ffplay`, or `ffprobe` process.
- **Fallback (never-silence):** set `CC_TTS_DAEMON_PORT_OVERRIDE` to a dead
  port and invoke `terminal-stack-tts.exe hook …`; its detached `_direct`
  worker must speak without any console child. Then the harder version: point
  `LOCALAPPDATA` at a **regular file** so the history DB, play lock and log
  directory are all unusable, and confirm it still speaks. That drill is what
  found two unguarded `mkdir` calls that crashed the process before a word came
  out.
- **Self-start:** with `daemon.enabled` true and nothing listening, one
  `terminal-stack-tts.exe hook …` must leave a daemon on the port and a
  `spoken` row with `daemon=1` — not a direct-path fallback. Kill any test
  daemon before rebuilding; a running one holds `dist\terminal-stack-tts.exe`
  open and PyInstaller fails with `Access is denied`.
- **Inert while off:** with `ccTtsDaemon=off` (the default), a `chezmoi apply`
  on an unchanged config must produce **zero** `updated` lines for
  `settings.json` / `hooks.json`, and the hooks must not POST anywhere
  (`cc_tts_daemon_ready` gates on `.daemon.enabled`).
- **Both entry shells:** drill the pwsh verbs (`tstack config tts daemon on` in
  pwsh, `Update-TerminalStack`) as well as the bash ones — day-to-day driving
  happens from PowerShell, and the daemon's first activation failed only on
  that path (`& pwsh` output capture; see `powershell-quirks.md`). Remember
  pwsh `tstack config tts` saves don't survive a WSL apply — persistence checks
  belong on the WSL side.

Duck-restore drill (music playing): trigger speech, kill the daemon mid-duck
(`taskkill /f /im terminal-stack-tts.exe`), confirm music is stuck quiet, then
`tstack doctor --repair` (or restart the daemon) — volumes must come back and
`state\duck-snapshot.json` must be gone.

New wizard/menu text (`ts_prompt_cc_tts_daemon` ↔ `Read-TsCcTtsDaemon`,
`tstack config tts -h` both shells, both TTS submenus) goes through the §3
byte-diff like everything else.

## 4c. Sync changes — run the whole sync against a throwaway profile

`scripts/sync-windows.ps1` derives every destination from `$env:USERPROFILE` /
`$env:LOCALAPPDATA`, so a child pwsh with both redirected exercises the real code path —
template rendering, backups, the Claude settings splice — without writing to your profile:

```powershell
$sb = (New-Item -ItemType Directory -Force "$env:TEMP\ts-sync-sandbox").FullName
New-Item -ItemType Directory -Force "$sb\.claude" | Out-Null
Copy-Item ~\.claude\settings.json "$sb\.claude\settings.json"   # seed a realistic live file
pwsh -NoLogo -NonInteractive -Command "
  `$env:USERPROFILE='$sb'; `$env:LOCALAPPDATA='$sb\LocalAppData'; `$env:APPDATA='$sb\AppData\Roaming'
  & ./scripts/sync-windows.ps1 -SourceDir (Resolve-Path .).Path -WinUser $env:USERNAME"
```

The sandboxed profile has no `config.json`, so the run uses wizard defaults (TTS off) — the
rendered `hooks` will legitimately differ from your live ones. What it does prove is which
keys survive: for `.claude\settings.json`, everything Claude Code owns (`model`,
`enabledPlugins`, `permissions`, `env`) must come out of the run byte-identical, and a second
run must report `already up to date`. Same check for the WSL hook by sourcing just its
functions with `dst_home` pointed at a `/mnt/c/...` sandbox — `resolve_pwsh` and
`merge_part_owned` need nothing else from the script.

**Seed the sandbox from a real pre-clobber backup, not a hand-written file.** The
`.bak.yyyyMMdd[.N]` chain next to the live file is the best available fixture: it is what the
other tool actually wrote, including entries the current code has never seen. That is how the
Cursor merge got tested against legacy `cursor-tts.ps1` entries it has to *replace* rather
than duplicate.

For the per-entry merges, TTS off is a distinct case, not a weaker version of TTS on. Run an
**on → off → on round trip** on one file and count entries by owner at each step: turning TTS
off must remove every one of ours and keep every one of theirs, and turning it back on must
return to exactly the starting counts with no duplicates.

## 4d. `tstack smb` changes (`bootstrap/ts-smb.sh`, `bootstrap/_smb.sh`)

The store parser, the engine probe and the mount lifecycle are all testable without
an SMB server; only the last two steps need one.

```sh
python -m pytest tests -q -k smb        # store, flags tail, validate, help, invariants
bash -n bootstrap/ts-smb.sh bootstrap/_smb.sh
TERMINAL_STACK_DIR="$PWD" bash bootstrap/ts-smb.sh engine    # and `doctor`
```

Point the store and state dir somewhere throwaway so you never touch your real
shares — the same discipline as §4:

```sh
export XDG_CONFIG_HOME=/tmp/smbtest/cfg XDG_STATE_HOME=/tmp/smbtest/state
mkdir -p "$XDG_CONFIG_HOME/terminal-stack"
```

`--dry-run` prints the exact rclone command without running it, which is the fastest
way to check flag assembly:

```sh
TERMINAL_STACK_DIR="$PWD" bash bootstrap/ts-smb.sh mount NAME -n
```

Mount-record states are testable with synthetic records — no mount required. Write a
`<name>.mnt` into the state dir with a live pid and a mountpoint that is not mounted
and `tstack smb list` must report `zombie`; a dead pid and no mount must report `gone`
and be pruned on sight.

For the real thing, a container is enough:

```sh
docker run -d --name smbtest -p 4450:445 \
  -e "USER=tester;testpass123" -e "SHARE=Media;/share;yes;no;no;tester" \
  -v /tmp/smbshare:/share dperson/samba:latest -p
printf 'testpass123' | bash bootstrap/ts-smb.sh shares 127.0.0.1 \
  --port 4450 --user tester --password-stdin
```

Two things to check every time you touch the credential path:

- **Nothing secret in `argv`.** With a mount (or any long rclone call) live,
  `ps auxww | grep '[r]clone'` must show the connection string and flags and no
  password. It travels in `RCLONE_SMB_PASS`, and it must be **obscured** there —
  rclone rejects plaintext with "input too short when revealing password".
- **`--password-stdin` is consumed exactly once.** `tstack smb probe` tries several
  credential candidates; re-reading an exhausted stdin used to leave rclone
  retrying against an empty password until it timed out.

And two platform traps worth re-confirming rather than assuming, because both fail
*silently*: Homebrew's macOS rclone refuses to mount at all (a build-time guard, so
`tstack smb doctor` should say so), and `-o backend=fskit` must never be passed
automatically — a test pins that, because it fails on macOS 26.6 where fuse-t's
default NFS backend does not.

## 4e. Installer changes — the two failure modes that hide

**Nothing optional may be fatal.** The bootstraps run under `set -euo pipefail`,
and `set -e` exempts only the **non-final** members of an `&&`/`||` list. So

```sh
brew list --cask zed >/dev/null 2>&1 || brew install --cask zed
```

looks guarded and is not — the install is last, so its failure kills the script.
That exact line aborted a real run at line 55 of 207, taking every terminal,
oh-my-zsh, `chsh`, `chezmoi.toml` and the whole persistence of the user's wizard
answers with it, printing nothing of its own. Reproduce the class in one line:

```sh
bash -c 'set -e; false || /usr/bin/false; echo SURVIVED'   # prints nothing, exits 1
```

Every optional install must end in `|| ts_note_failure …`. A test enforces it.
Also **never** `brew install --cask --adopt`: on a bundle whose xattrs brew
cannot rewrite it fails partway and **removes the app it was adopting** —
verified by deleting a real `/Applications/Zed.app`.

**Answers must be saved before anything that can fail.** Persistence used to run
last, so any abort discarded the whole questionnaire. Drill it with a throwaway
`HOME` and a deliberately failing install:

```sh
H=/tmp/ts-wiz; rm -rf $H; mkdir -p $H/.config/chezmoi
HOME=$H TS_ASSUME_YES=1 TS_ATUIN=on TS_THEME=light TS_APPS=none bash -c '
  . bootstrap/_config.sh; . bootstrap/_wizard.sh; ts_wizard_collect >/dev/null
  ts_ensure_source_dir "$PWD" >/dev/null; ts_atuin_set "$TS_WIZ_ATUIN"
  false || ts_note_failure "optional apps" "retry"'
HOME=$H bash -c '. bootstrap/_config.sh; ts_atuin_get'    # must be "on"
```

**A `$var` followed by a non-ASCII character is a latent crash.** macOS bash 3.2
is not multibyte-aware, so `"$desired…"` parses the name as `desired\xE2` and
`set -u` aborts — at runtime, invisible to `bash -n`. Brace it: `"${desired}…"`.

```sh
bash -uc 'desired=/tmp; echo "$desired…"'    # bash: desired?: unbound variable
```

**A catalog entry is a claim about a package manager — check it.** A winget id
that does not resolve costs nothing at parse time and never stops failing:
`pypa.pipx` sat in `$TsWingetIds` while `pipx` was in the *recommended* set, so
every Windows machine was offered it on every `tstack update`, accepted, and watched
winget answer "No package found matching input criteria". Two of the other three
Python entries were dead the same way. Sweep the whole table after touching it:

```powershell
. bootstrap\_config.ps1
foreach ($k in ($script:TsWingetIds.Keys | Sort-Object)) {
    $out = winget show --id $script:TsWingetIds[$k] --exact --accept-source-agreements 2>&1 | Out-String
    if ($out -match 'No package found') { Write-Host "BAD $k -> $($script:TsWingetIds[$k])" }
}
```

**A Ghostty change now has two targets, and only one of them can be checked.**
macOS has a real gate — `ghostty +validate-config` exits 1 on error. The Windows
build (noctty, shipping as winghostty) has none: `+validate-config` fails with
`FileTooBig` on 1.3.123 even for a 14-byte config, and `+show-config` silently
reports **nothing** for an unknown key or a bad value on a real key. So never
treat `+show-config` as a validator — probing options that way returns
"accepted" for garbage. What you can check is that the file *renders* and that
the values you set actually land:

```powershell
# render the mirror template the way the sync will, then read it back
$t = (Get-Content windows\AppData\Local\ghostty\config.tmpl -Raw).
     Replace('__GHOSTTY_THEME__','Catppuccin Mocha').Replace('__GHOSTTY_WINDOW_THEME__','dark')
$t | Set-Content "$env:LOCALAPPDATA\ghostty\config" -NoNewline -Encoding utf8
& 'C:\Program Files\winghostty\winghostty.com' +show-config |
    Select-String '^(theme|window-theme|font-family|background) ='
```

A directive that is absent from the output was **not** applied. And remember the
mirror gets blind token substitution: any `__TOKEN__` the sync knows about is
replaced even inside a comment (a comment mentioning the tmux-prefix token was
rewritten to `C-b` mid-sentence). A test pins the token set.

And check the id's **binary name**, which is a separate claim: winget's
`aristocratos.btop4win` installs `btop4win.exe`, so probing for `btop` reported
it missing forever even though it was installed. `Get-TsAppBin` must name what
actually lands on PATH — confirm with `Get-Command` after a real install, and
confirm `Get-TsAppsPending` then stops listing it.

## 5. What you cannot verify from a dev clone

`chezmoi source-path` points at the **runtime** clone
(`%LOCALAPPDATA%\terminal-stack\stack`), and dev clones at workspace tier paths are
deliberately invisible to resolution. So `chezmoi apply` run while working in a dev
tree deploys the *old* code and proves nothing about your change.

Do not apply from the dev tree to "test" something. Verify with §§1–4, commit, then
`tstack update` on the target machine and check there.

A newly added `[data]` key is safe in that gap: every consumer defaults it (`hasKey`
guards in chezmoi templates, `cfg <key> <default>` in the sync hook, `else` fallbacks
in `sync-windows.ps1`), and the first `ts_*_set` or `chezmoi init` backfills it.

## 6. Before you push

- Docs updated *with* the change, not after — and sweep the passing mentions, not
  just the reference tables. See the `-h` landmine below.
- `CHANGELOG.md` entry under `[Unreleased]`.
- If you added a line to a script's header comment, check any
  `sed -n '2,NNp' "$0"` help range that prints it — `bootstrap/ts-config.sh` does
  this, and an unbumped range silently truncates its own `-h` output.
