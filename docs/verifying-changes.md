# Verifying a change before you commit

There is no CI, no test suite and no lint here — but that does not mean there is
nothing to run. This is the checklist that replaces them. `INSTALL.md` § Phase 9 is
the *post-install* smoke test for a fresh machine; this is the *pre-commit* pass for
a change you just made.

Every technique below was worked out the hard way. None of it needs a GUI, a second
machine, or a real `chezmoi apply`.

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
byte-identical menus, as are the `wso` and `ts-mux` `-h` texts. Eyeballing them
misses a single space or an em dash. Diff the bytes.

The bash side needs a pty — `ts_prompt_choice` writes the menu to `/dev/tty` and it
is silently discarded when there is none:

```sh
printf "\n" | timeout 20 script -qec "bash -c '. bootstrap/_wizard.sh; ts_prompt_<name> >/dev/null'" /dev/null | tr -d '\r'
```

Wrap the payload in `bash -c`. `script` runs `$SHELL`, which is zsh here, and zsh's
`read -p` means "read from the coprocess" — the prompt helper errors out under it.

The pwsh side just needs the helper dot-sourced:

```powershell
. bootstrap/_config.ps1; Read-Ts<Name>
```

Then strip ANSI and blank lines, drop the trailing `Choose …` line (it differs
legitimately: a live prompt vs `(non-interactive — taking the default)`), and
`Compare-Object`.

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
pass no value for a given key — `Update-TsResolvedTheme`, and `ts-update`'s
app-backfill. Without `$PSBoundParameters.ContainsKey(...)` handling, every
`ts-update` silently resets the user's choice:

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
- **Both entry shells:** drill the pwsh verbs (`ts-config tts daemon on` in
  pwsh, `Update-TerminalStack`) as well as the bash ones — day-to-day driving
  happens from PowerShell, and the daemon's first activation failed only on
  that path (`& pwsh` output capture; see `powershell-quirks.md`). Remember
  pwsh `ts-config tts` saves don't survive a WSL apply — persistence checks
  belong on the WSL side.

Duck-restore drill (music playing): trigger speech, kill the daemon mid-duck
(`taskkill /f /im terminal-stack-tts.exe`), confirm music is stuck quiet, then
`ts-doctor --repair` (or restart the daemon) — volumes must come back and
`state\duck-snapshot.json` must be gone.

New wizard/menu text (`ts_prompt_cc_tts_daemon` ↔ `Read-TsCcTtsDaemon`,
`ts-config tts -h` both shells, both TTS submenus) goes through the §3
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

## 4d. `ts-smb` changes (`bootstrap/ts-smb.sh`, `bootstrap/_smb.sh`)

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
and `ts-smb list` must report `zombie`; a dead pid and no mount must report `gone`
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
- **`--password-stdin` is consumed exactly once.** `ts-smb probe` tries several
  credential candidates; re-reading an exhausted stdin used to leave rclone
  retrying against an empty password until it timed out.

And two platform traps worth re-confirming rather than assuming, because both fail
*silently*: Homebrew's macOS rclone refuses to mount at all (a build-time guard, so
`ts-smb doctor` should say so), and `-o backend=fskit` must never be passed
automatically — a test pins that, because it fails on macOS 26.6 where fuse-t's
default NFS backend does not.

## 5. What you cannot verify from a dev clone

`chezmoi source-path` points at the **runtime** clone
(`%LOCALAPPDATA%\terminal-stack\stack`), and dev clones at workspace tier paths are
deliberately invisible to resolution. So `chezmoi apply` run while working in a dev
tree deploys the *old* code and proves nothing about your change.

Do not apply from the dev tree to "test" something. Verify with §§1–4, commit, then
`ts-update` on the target machine and check there.

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
