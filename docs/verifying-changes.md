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

The invariants to drill after touching the hook senders:

- **No console process:** inspect the built PE Optional Header (`Subsystem=2`,
  Windows GUI), run Claude and Cursor hooks with redirected stdin, and verify
  no new `cmd`, `conhost`, `pwsh`, `python[w]`, `ffplay`, or `ffprobe` process.
- **Fallback (never-silence):** set `CC_TTS_DAEMON_PORT_OVERRIDE` to a dead
  port and invoke `terminal-stack-tts.exe hook …`; its detached `_direct`
  worker must speak without any console child.
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
