# PowerShell + WezTerm + Claude Code quirks

A field guide to the subtle Windows-side gotchas this stack works around. If something breaks and the symptom matches one of these, you'll find the fix here.

## CP437 mojibake after Claude Code exits

**Symptom.** After exiting Claude Code (`/exit` or Ctrl-D), the next pwsh prompt shows `Γ¥»` (or similar three-character mojibake) where the starship `❯` glyph should be.

**Cause.** Claude Code's TUI calls Win32 `SetConsoleOutputCP()` to change the OS-level console code page (typically to 437) during runtime and doesn't restore it on exit. After exit, pwsh emits the UTF-8 bytes of `❯` (`E2 9D AF`), but the OS console is in CP437. CP437 decodes those bytes as three separate characters: `Γ` `¥` `»`.

**Fix.** P/Invoke `kernel32!GetConsoleOutputCP` and `SetConsoleOutputCP` in `Invoke-Starship-PreCommand`, probing the OS console state every prompt:

```powershell
if (-not ('Native.ConsoleCP' -as [type])) {
    Add-Type -Namespace Native -Name ConsoleCP -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern uint GetConsoleOutputCP();
[System.Runtime.InteropServices.DllImport("kernel32.dll")]
public static extern bool SetConsoleOutputCP(uint wCodePageID);
'@ | Out-Null
}
[Native.ConsoleCP]::SetConsoleOutputCP(65001) | Out-Null
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Invoke-Starship-PreCommand {
    if ([Native.ConsoleCP]::GetConsoleOutputCP() -ne 65001) {
        [Native.ConsoleCP]::SetConsoleOutputCP(65001) | Out-Null
        [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    }
    ...
}
```

**Why `[Console]::OutputEncoding` alone wasn't enough.** The first version of this fix (commit `116087d`) only consulted `[Console]::OutputEncoding.CodePage` — a .NET-side cached value that does NOT get invalidated when a native child process changes the codepage via raw `SetConsoleOutputCP`. After Claude Code exited, .NET still believed the codepage was 65001 and the conditional skipped the reset, while the underlying OS console was actually at 437. The P/Invoke version asks the OS directly.

## Claude Code startup output stalls until next keypress (WebGpu)

**Symptom.** You type `ccd`, hit Enter. The cursor moves to a new line but Claude Code's TUI doesn't draw. You press any key — even space — and the entire Claude Code intro screen pops into existence at once.

**Cause.** WezTerm's `WebGpu` front_end has an output-buffer behavior on some Intel iGPU drivers where rapid post-redirect output from a child process doesn't trigger an immediate redraw. The buffer is flushed only when WezTerm processes the next input event.

**Status.** The stack runs `WebGpu` (the WezTerm default) on both GUI configs. This stall was last reproduced in May 2026; a later WezTerm-nightly / driver update cleared it, so the configs returned to WebGpu. macOS (Metal) never had it.

**Fallback if it reappears.** Switch the front_end to `OpenGL` in the affected `.wezterm.lua`:

```lua
config.front_end = 'OpenGL'
```

OpenGL trades slightly less polished scrolling animation for immunity to the stall. The comment next to `config.front_end` in each config points back here.

## CRLF drift on chezmoi sources

**Symptom.** In WSL, starting `zsh` shows a stream of `~/.zshrc:N: command not found: ^M` errors. Or `chezmoi apply` fails with `env: $'bash\r': No such file or directory` (the `run_after` hook). Or every apply produces a fresh `.bak.YYYYMMDD.N` file even though you didn't change anything.

**Cause.** Windows git's system-wide `core.autocrlf=true` rewrites LF-stored files as CRLF on checkout. POSIX shells and `env`-based shebangs choke on the trailing `\r`. chezmoi then dutifully copies the CRLF working-tree file to `~/.zshrc`.

**Fix.** This repo's `.gitattributes` (`* text=auto eol=lf`) overrides `core.autocrlf` and forces LF in the working tree on every platform. On a fresh clone, no further action is needed.

To rescue an existing clone where the damage was already done:

```sh
git add --renormalize .
# any newly-staged changes are pure line-ending normalization — commit them
```

Defensive last-resort for a single file that slipped through (e.g., an editor that ignored attributes):

```sh
sed -i 's/\r$//' <file>
```

Do not remove the `.gitattributes` to "match the user's git config" — it intentionally overrides the user's config so the repo is correct regardless of `autocrlf` setting.

## `Enable-TransientPrompt` cmdlet not found

**Symptom.** Fresh pwsh shows `Enable-TransientPrompt : The term 'Enable-TransientPrompt' is not recognized...` when sourcing `$PROFILE`.

**Cause.** PSReadLine documents `Enable-TransientPrompt`, but version **2.4.5** (the latest stable PSReadLine on Windows as of this stack's deployment) doesn't actually export the cmdlet. Only six commands are exported from the module: `Get-PSReadLineKeyHandler`, `Get-PSReadLineOption`, `PSConsoleHostReadLine`, `Remove-PSReadLineKeyHandler`, `Set-PSReadLineKeyHandler`, `Set-PSReadLineOption`. `Enable-TransientPrompt` may exist as an internal function in some PSReadLine builds, but not in 2.4.5.

**Fix.** Wrap the call in `Get-Command`:

```powershell
if (Get-Command Enable-TransientPrompt -ErrorAction SilentlyContinue) {
    Enable-TransientPrompt
}
```

Future PSReadLine versions that do export it will pick it up automatically; older versions skip gracefully.

## Backslashes in JSON paths get stripped twice

**Symptom.** Claude Code hooks fail with `The argument 'C:Users<you>.claudehookswez-tab-status.ps1' is not recognized as the name of a script file.` (Note: zero backslashes in the path.)

**Cause.** Two passes of backslash interpretation:

1. JSON parses `"C:\\\\Users\\\\..."` → `C:\\Users\\...` (string field after escape).
2. Claude Code's hook executor passes the resulting string through a POSIX-style shell layer that consumes each `\` as the start of an escape sequence (`\U` → `U`, `\m` → `m`, etc.).

The net effect: the path arrives at PowerShell with zero backslashes.

**Fix.** Use forward slashes in the JSON path:

```json
"command": "pwsh -NoLogo -NonInteractive -ExecutionPolicy Bypass -File C:/Users/__WIN_USER__/.claude/hooks/wez-tab-status.ps1 -State thinking"
```

PowerShell's `-File` accepts forward slashes on Windows. Forward slashes have no special meaning in any shell, so neither layer interprets them.

Commit: [`a63044a`](../CHANGELOG.md).

## Claude Code overwrites the tab title

**Symptom.** Our `cc` PowerShell wrapper set the per-project tab title (then `cc • <project>`; today the bare project leaf) via OSC 0 (`Write-Host -NoNewline "ESC ]0;cc • myproject BEL"`). Claude Code launches, and the tab title changes to the conversation slug (e.g., `distinguish-claude-code-tabs-pwsh`).

**Cause.** Claude Code's TUI emits its own OSC 0 / OSC 2 with a conversation-derived title. OSC writes to `pane.title`, which is mutable. Last writer wins. Claude Code writes after our wrapper does.

**Fix.** Use `wezterm cli set-tab-title` to set `tab.tab_title` instead of `pane.title`. `tab.tab_title` is independent of OSC streams and Claude Code can't touch it. Our `format-tab-title` Lua reads `tab.tab_title` first and only falls back — to the active pane's cwd leaf, then `pane.title` — when it is empty.

```powershell
function Set-WezTabTitle([string]$title) {
    if ($env:WEZTERM_PANE) {
        & wezterm.exe cli set-tab-title $title 2>$null
    }
}
```

Commit: [`d291b92`](../CHANGELOG.md).

## ConPTY swallows the OSC 11 pane background tint

**Symptom.** The `wez-tab-status` hook is supposed to tint a pane's background by Claude state (peach = working, green = done, red = error). On Windows the tab title and the per-pane `●/○` dots + green/red tab-text update correctly, but the **pane background never changes**. Same hook works on macOS / native Linux.

**Cause.** On Windows every pane's byte-stream passes through **ConPTY** (the Windows pseudo-console) on its way to WezTerm. ConPTY parses standard VT itself and **intercepts the dynamic-colour OSC sequences (`OSC 10`/`11`/`12`)** to track its own buffer colours — it does **not** forward them to the host terminal. So the `\033]11;#…\007` the hook writes to `CONOUT$` dies inside ConPTY and WezTerm never sees it.

The two signals that *do* work bypass that stream entirely, which is the tell:

- `wezterm cli set-tab-title` → out-of-band over the WezTerm mux socket (no terminal stream).
- The `cc_state` dots → `OSC 1337 SetUserVar`, an iTerm2-proprietary sequence ConPTY doesn't recognise, so it passes through verbatim and fires WezTerm's `user-var-changed`.

And WezTerm has **no Lua API to set one pane's background** (`window:set_config_overrides` is per-*window*), so OSC-11-from-inside-the-pane is the only mechanism — exactly the thing ConPTY blocks.

**Fix.** Re-drive the tint from the user var that already arrives, using **`pane:inject_output()`** — which feeds the escape sequence directly into WezTerm's own terminal emulator, downstream of ConPTY. Added to both `.wezterm.lua` configs:

```lua
local CC_BG = { working = '#4a3020', done = '#1e3828', error = '#3a1828' }
-- sync_pane_backgrounds(window) injects OSC 11 per pane: cc tint when set,
-- else crust (active) or base (inactive). Called from user-var-changed and
-- update-right-status so focus switches and cc_state changes both re-apply.
wezterm.on('user-var-changed', function(window, pane, name, value)
  if name ~= 'cc_state' then return end
  sync_pane_backgrounds(window)
end)
```

OSC 11 only sets the default background colour — it never moves the cursor — so injecting it is safe even while Claude Code's full-screen TUI is drawing. On exit the `cc`/`Set-WezTabTitle` wrappers clear `cc_state`; the Lua `sync_pane_backgrounds` handler (driven by `user-var-changed` and `update-right-status`) restores active/inactive idle colours or reapplies cc tints.

The hook's raw `OSC 11` is **left in place on purpose**: it's harmless where ConPTY drops it, and it's the correct path for WezTerm **mux/SSH panes**, where `inject_output` is unsupported but the remote (ConPTY-free) shell's OSC 11 flows through the mux stream.

**Caveat.** `pane:inject_output` requires WezTerm `20221119` or newer and works for **local panes only**. ConPTY's OSC handling has shifted across Windows builds; if a future build forwards OSC 11, the handler simply re-sets the same colour (no flicker, no harm).

## Synthetic Ctrl+V doesn't reach Claude Code

**Symptom.** Wispr Flow's voice-dictation paste works in pwsh, but not in Claude Code. Other apps that simulate Ctrl+V (some clipboard managers, accessibility tools) also fail.

**Cause.** WezTerm's default Windows keybindings put paste on `Ctrl+Shift+V` and `Shift+Insert`. Not `Ctrl+V`. Plain pwsh handles `Ctrl+V` itself because PSReadLine has its own paste binding for that key. Claude Code's TUI has no equivalent — it expects WezTerm-originated bracketed-paste sequences, which only fire when WezTerm intercepts the paste key. Synthetic `Ctrl+V` from Wispr passes straight through.

**Fix.** Bind `Ctrl+V` in WezTerm to `PasteFrom 'Clipboard'`:

```lua
{ key = 'v', mods = 'CTRL', action = act.PasteFrom 'Clipboard' },
```

Now WezTerm intercepts the synthetic Ctrl+V, performs a real paste, sends bracketed-paste sequences that Claude Code accepts.

Trade-off: `Ctrl+V` no longer enters visual-block mode in vim/nvim inside WezTerm. Use `Ctrl+Q` instead (vim's documented alternative).

Commit: [`2a3f527`](../CHANGELOG.md). Related upstream issue: [anthropics/claude-code#38620](https://github.com/anthropics/claude-code/issues/38620).

## GitKraken `gk ai hook` plugin: log flood + the 0-byte `gk.exe` red herring

**Symptom.** Two things that look like the GitKraken/Claude Code integration is broken: (1) `gk.exe` in `%LOCALAPPDATA%\GitKrakenCLI\` reports `Length 0` and appears corrupt; (2) `gk_cli.log` balloons (16 MB+) with hundreds of `aihook: broadcast failed … Post "http://127.0.0.1:<port>/agents/session" … target machine actively refused it`.

**Background.** GitKraken installs a Claude Code **plugin** (not an MCP server), `gitkraken-hooks@gitkraken`, enabled in `~/.claude/settings.json` (`enabledPlugins` + `extraKnownMarketplaces.gitkraken`). It registers a hook on ~24 lifecycle events; each runs `"…\GitKrakenCLI\gk.exe" ai hook run --host claude-code`, broadcasting the live session state to GitKraken Desktop / GitLens for their "AI session tracking" panel.

**Cause / what's actually true.**

- The `0 bytes` is a **red herring**. `gk.exe` is a **symlink** to `versions\gk_<ver>\gk_<ver>.exe` (the real ~40 MB binary); a symlink's reparse point legitimately reports length 0. `gk version` runs fine, exit 0. Do **not** "repair" it by copying the binary over it — that fails with *"Cannot overwrite the item … with itself"* because the copy resolves the link to the same file. Confirm with `(Get-Item gk.exe -Force).LinkTarget`.
- The Claude Code hook **exits 0 with no output**, so Claude Code never surfaces an error from it. The integration is functionally fine; the noise is internal to gk's own log.
- The `broadcast failed` lines are gk pushing updates to **stale localhost listener ports** from AI sessions that have since closed. That registry is **not** in `sessions\*.json` (session state) and **not** in the gk CLI `.cache\` BadgerDB — clearing both has zero effect. It is held by **GitKraken Desktop** (`%APPDATA%\GitKraken\`, the `DIPS` store), which persists dead ports and never prunes them. They are `warning` level and harmless.
- On a network that firewalls `api.gitkraken.dev` (corporate proxy), gk's auto-update check times out (`context deadline exceeded`), adding latency and proxy-log noise.

**Fix / mitigation (all machine state, not repo).**

- `%LOCALAPPDATA%\GitKrakenCLI\gk.cfg`: set `AUTO_UPDATE=false` (back it up first) to stop the firewalled update-check stalls.
- Truncate `gk_cli.log`; kill any orphaned long-running `gk` / `gk_<ver>` processes (a finished `ai hook run` should not linger for minutes — they leak).
- Restarting GitKraken Desktop clears the **in-memory** portion of the stale registry (observed ~87 → ~31 dead ports) but does **not** fully drain it — the remainder is persisted in `DIPS` and only a GitKraken-side prune would clear it. Don't perform surgery on `DIPS` to chase benign warnings.
- To silence the broadcasts entirely you would disable the `gitkraken-hooks` plugin — but that removes the feature.

**Note.** Plugin enablement lives in `~/.claude/settings.json`, which this repo manages whole-file. The tracked templates **no longer** carry `enabledPlugins` / `extraKnownMarketplaces` — plugins are a per-machine choice you make through the `/plugin` UI, owned by your live file. The trade-off (why the repo stopped imposing them) is in `decisions.md` § "Why `settings.json` ships only shared infra — no model, prefs, permissions, or plugins". If you want GitKraken's hooks, re-enable `gitkraken-hooks` there; this section describes its behavior once you do.

## Same-day backup file got clobbered

**Symptom.** You overwrite a file via the run_after sync hook on the same day twice. The second overwrite destroys the first backup, leaving you with no rollback to the original.

**Cause.** Naïve backup logic: `cp $dst $dst.bak.$today`. Same-day re-runs use the same target filename and overwrite.

**Fix.** Check for existing backup; suffix with `.1`, `.2`, etc:

```sh
bak="$dst.bak.$today"
if [ -e "$bak" ]; then
    n=1
    while [ -e "$dst.bak.$today.$n" ]; do n=$((n + 1)); done
    bak="$dst.bak.$today.$n"
fi
cp -p -- "$dst" "$bak"
```

This is hardened in `run_after_90-sync-windows.sh` as of the initial deployment. If you write your own scripts that write `.bak.YYYYMMDD` files, use the same pattern.

## `~/.local/bin` not on zsh PATH in Ubuntu

**Symptom.** You install something to `~/.local/bin` (or symlink something there — like `bat` from `batcat`), and `command -v` from zsh returns empty.

**Cause.** oh-my-zsh's default `~/.zshrc` template includes a commented-out `export PATH=$HOME/bin:$HOME/.local/bin:/usr/local/bin:$PATH`. It's intentional — different distros handle PATH differently, and you opt in. Ubuntu's default `~/.profile` adds `~/.local/bin` to PATH, but `.profile` isn't sourced by interactive zsh sessions.

**Fix.** Add an explicit PATH export inside our cli-tools marker block in `~/.zshrc`:

```sh
export PATH="$HOME/.local/bin:$PATH"
```

It's the first line inside the block, runs every shell init, idempotent.

## Cross-shell quoting traps

Several different tool-invocation paths go through this stack:

| From | To | Quoting layer count |
|---|---|---|
| PowerShell tool | WezTerm-launched pwsh | 1 (PS arg parsing) |
| PowerShell tool | wsl.exe → bash | 2 (PS → wsl.exe → bash) |
| PowerShell tool | wsl.exe → bash → zsh | 3 |
| Claude Code hook | bash | 1 |
| Claude Code hook | pwsh -File → script | 2 |

Each layer eats some quoting. Symptoms when something is wrong:

- Variables come back empty (PS ate the `$var`).
- Backslashes disappear (POSIX shell ate the `\`).
- Newlines get converted (PS pipeline added CR before LF).
- `head -1` errors as "unknown option" (because `\r` was injected from CRLF stdin).

Defensive practices used in this stack:
- For shell commands invoked through PS, prefer single-quoted strings for arguments.
- For multi-line scripts, write to a tempfile in WSL native filesystem and execute that.
- Strip `\r` from any file edited via Windows-side tools that will be parsed by bash: `sed -i 's/\r$//' <file>`.
- For paths in JSON consumed by shell layers, use forward slashes.

**One more layer nobody counts: Git Bash rewrites arguments that start with `/`.** MSYS
path conversion turns `/d` `/s` `/c` into Windows paths before `cmd.exe` ever sees them,
so reproducing a configured Windows hook command from the Bash tool fails in a way that
looks exactly like the hook being broken:

```sh
# looks like "the hook doesn't work" — actually /d /s /c became paths
printf '%s' "$payload" | cmd.exe /d /s /c "set VAR=x&& node ./hook.mjs"

# what actually tests the configured command
MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' \
  cmd.exe /d /s /c "set VAR=x&& node ./hook.mjs" < payload.json
```

This bit during the Cursor hook verification: the first form silently captured nothing
(agent hooks swallow their own errors and exit 0), the second landed correctly. When a
hook probe fails, rule out the harness before believing the hook — run the underlying
interpreter directly first (`node ./hook.mjs` with the env var set), and only then the
full wrapped command.

## The caller's session may have `Set-StrictMode` on

Every function here can be dot-sourced into a shell we do not control, and strictness is
session-scoped and inherited. Under `Set-StrictMode` two patterns that are ordinarily
harmless become **terminating** errors:

| Pattern | Under strictness |
|---|---|
| reading a variable assigned only on some branch | `The variable '$x' cannot be retrieved because it has not been set.` |
| `$obj.MissingProperty` (including `ConvertFrom-Json` output) | `The property 'X' cannot be found on this object.` |

Both were live. `Resolve-TsSourceDir` assigned `$stalePin` only inside the dangling-pin
branch and then read it unconditionally, so **`tstack update` and `tstack config` failed outright**
in a strict session — before doing anything, with an error naming an internal variable.
`Read-TsChoice` rendered its optional `Note` column with `$o.Note`, so the install wizard
died on the very first question (leader key), whose options have no `Note`. `Get-CcTtsConfig`
was worse: it *probed* for missing members with the syntax that throws on missing members.

The rules:

- **Initialize every variable you will read**, even when a branch is the only writer.
- **Read optional hashtable keys by index** — `$o['Note']` returns `$null` for a missing key
  under any strictness, `$o.Note` does not.
- **Read optional object properties through `Get-TsProp`** (`bootstrap/_config.ps1`), which
  probes `PSObject.Properties` and treats `$null`/empty as the caller's default. This matters
  most for `ConvertFrom-Json` results: a `config.json` written before a key existed makes
  plain dot access a crash rather than a fallback.
- Do **not** fix this by adding `Set-StrictMode` yourself, and do not add it to a
  dot-sourced helper — it leaks into the caller's session and outlives the call
  (`bootstrap/_agentmemory.ps1` carries a comment saying exactly that). Write code that is
  correct either way.

Reproducing is a one-liner, and worth doing for anything on the `tstack config` / `tstack update` /
wizard path:

```powershell
pwsh -NoProfile -Command "Set-StrictMode -Version Latest; . .\bootstrap\_config.ps1; Read-TsChoice -Title t -Default a -Options @(@{Key='a';Label='A'})"
```

## `| Set-Content` silently no-ops when the pipeline is empty

`Clear-TsSourceDirPin` (`bootstrap/_cleanup.ps1`) strips the `$env:TERMINAL_STACK_DIR`
line from `profile.local.ps1`. It was written the obvious way:

```powershell
(Get-Content $f) | Where-Object { $_ -notmatch '^\s*\$env:TERMINAL_STACK_DIR\s*=' } |
    Set-Content $f
```

That works whenever *something* survives the filter, and does **nothing at all** when
nothing does — which is the common case here, because a machine whose only per-machine
override is the pin has a `profile.local.ps1` containing exactly that one line. The
function printed "removed the pin", the backup was written, and the file was untouched.
It was found on a real repair run, by checking the file instead of trusting the message.

The cause is that `Set-Content` takes its content from the **pipeline**, and a pipeline
that yields zero objects never gives it a value to write — the cmdlet's process block
never runs, so the existing file is left alone. It is not an error and there is no
warning. Contrast `-Value`, which is a parameter and therefore always supplied:

```powershell
$kept = @((Get-Content $f) | Where-Object { $_ -notmatch '…' })
Set-Content -LiteralPath $f -Value $kept -Encoding utf8   # @() truncates, as intended
```

Demonstration:

```powershell
'only-line' | Set-Content t.txt
'only-line' | Where-Object { $_ -notmatch 'only' } | Set-Content t.txt
Get-Content t.txt          # -> only-line     (unchanged!)
Set-Content t.txt -Value @()
Get-Content t.txt          # -> (empty)
```

**Rule for this repo:** when rewriting a file by filtering its lines, collect into an
array and pass `-Value`. Never pipe a `Where-Object` straight into `Set-Content`. A
`-replace` pipeline is safe (it emits one line per input line and cannot go empty), and
`Set-TsSourceDirPersisted` in the profile already uses the `-Value ($kept + $line)` form.

## `& child.exe` inside a function: stdout becomes the return value

Calling a native executable from a PowerShell function without redirecting it
sends the child's **entire stdout to the function's output stream** — i.e. into
whatever the caller assigns or tests, not to the console:

```powershell
function Invoke-Thing {
    & pwsh -File .\does-stuff.ps1      # every line the child prints goes HERE
    return ($LASTEXITCODE -eq 0)       # ...appended after all those lines
}
if (-not (Invoke-Thing)) { ... }       # non-empty array is ALWAYS truthy
```

Three failures at once, observed live when `tstack config tts daemon on` shipped:
the child's output (including its error text) never reaches the user, the
boolean is buried as the last element of an array, and `-not (array)` reads
any failure as success. Only the child's *stderr* leaks to the console, which
is why the user saw pip warnings and nothing else.

**Rule for this repo:** a pwsh function that both runs a child process and
returns a status must stream the output explicitly — `& child.exe … | Out-Host`
— and return only the boolean/exit code. This is the output-stream sibling of
the `Where-Object | Set-Content` trap above. Reference fix:
`Invoke-TsCcTtsDaemonInstaller` in `bootstrap/_config.ps1`.

Related: `Start-Process -FilePath some.cmd` resolves through **ShellExecute**,
which is unreliable from non-interactive / WSL-interop contexts (the process
may simply never start, with no error). Launch batch files through an explicit
host instead: `Start-Process $env:ComSpec -ArgumentList '/c', $launcher`.

## TTS EXE: GUI subsystem, inherited pipes, and HKCU Run

Assorted Windows-side facts baked into `bootstrap/install-tts-daemon.ps1` and the
TTS hook senders, recorded so they don't get "simplified" away:

- **Autostart is an HKCU `…\CurrentVersion\Run` value**, not a Startup-folder
  shortcut or a scheduled task: no admin, trivially idempotent
  (`New-ItemProperty -Force` / `Remove-ItemProperty`), and crash-restart
  semantics are unnecessary because the hooks fall back to direct playback when
  the daemon is dead. The value points directly at the installed GUI-subsystem
  `terminal-stack-tts.exe daemon`; there is no `.cmd` or shell host.
- **A windowed PyInstaller build sets `sys.stdin/stdout/stderr` to `None`.**
  Hook hosts still provide JSON through inherited pipes, so the EXE reads and
  writes those handles with `GetStdHandle` + `ReadFile` / `WriteFile`. Cursor's
  required `{}` response is covered by a packaged-EXE pipe test.
- **GUI subsystem is necessary but not sufficient.** Any console-subsystem
  child can still flash a window, so media probing/playback and SAPI run
  in-process (mutagen, WinRT MediaPlayer, COM). Optional children use
  `CREATE_NO_WINDOW` through one helper.
- **The WSL-facing listener needs a firewall rule** (inbound TCP on the daemon
  port from `172.16.0.0/12`) and creating one needs elevation — the installer
  tries, and on failure reports the need for elevation instead of failing the
  install. Mirrored-networking WSL (Win11) never needs it: loopback works.
- **Per-app mixer volume persists across app restarts.** Anything that lowers a
  session volume must write its restore data to disk *first* — see
  `state\duck-snapshot.json` and docs/decisions.md § ducking snapshots.

## `Add-Type` compiles every session, and `Invoke-Expression` parses slower than a file

Two costs that only show up when you measure a profile rather than read it.

**`Add-Type -MemberDefinition` runs the C# compiler at every shell start.**
PowerShell caches the result for the life of the session and nothing beyond it,
so the console-codepage P/Invoke cost ~340ms per pane. Compile it once with
`-OutputAssembly` and load that with `Add-Type -Path` (~25ms):

```powershell
if (-not (Test-Path -LiteralPath $dll)) {
    $tmp = "$dll.$PID.tmp"      # never compile onto the target: another pane may have it loaded
    Add-Type -Namespace Native -Name ConsoleCP -MemberDefinition $src -OutputAssembly $tmp -ErrorAction Stop
    Move-Item -LiteralPath $tmp -Destination $dll -Force
}
Add-Type -Path $dll
```

Keep the in-memory compile as a fallback, so an unwritable cache costs what it
used to instead of losing the type.

**Dot-sourcing a file beats `Invoke-Expression` on a string.** Same 10KB of
`starship init` output: 427ms dot-sourced, 612ms through `Invoke-Expression`
(medians of 5, alternating). If you are evaluating generated shell code, write it
to a file and dot-source it — and dot-source it from the profile's own scope, not
from inside a function, or `New-Module` and `function global:` definitions land
out of the prompt's reach.

**`<tool> init powershell` may spawn the tool twice.** `starship init powershell`
prints a bootstrap that re-runs `starship ... --print-full-init`. On a machine
where a spawn costs 300ms-2s (antivirus scanning each exec) that is worth
knowing: request `--print-full-init` yourself.
