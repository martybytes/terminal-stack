# WezTerm — developing config

WezTerm reads your **home directory**, not the git clone. Edit source files in the
clone, **deploy** them home, then **reload**. Run WezTerm normally — no special launch
flags.

## Source → deployed

| Platform | Edit in clone | WezTerm loads |
|---|---|---|
| Windows | `windows/.wezterm.lua.tmpl` | `%USERPROFILE%\.wezterm.lua` |
| Windows | `windows/.wezterm/pane_nav.lua` | `%USERPROFILE%\.wezterm\pane_nav.lua` |
| Windows | `docs/kb/**` | `%LOCALAPPDATA%\terminal-stack\docs\kb\` (`doc` read fallback) |
| macOS | `dot_wezterm.lua.tmpl` | `~/.wezterm.lua` |
| macOS | `dot_wezterm/pane_nav.lua` | `~/.wezterm/pane_nav.lua` |

Keep the Windows and macOS twins in sync when changing shared behaviour. On
Windows + WSL, the GUI is still the **Windows** process — WSL home gets no WezTerm
config.

Long-form write-up: `docs/developing-wezterm.md` in the clone.

## Windows — deploy after save

```powershell
& C:\path\to\terminal-stack\scripts\sync-windows.ps1 -SourceDir C:\path\to\terminal-stack
```

Renders `.tmpl` tokens (leader, theme, username) and copies only changed files.
Also mirrors `docs/kb/**` to `%LOCALAPPDATA%\terminal-stack\docs\kb\` so `doc`
picks up kb updates after sync (clone paths still win for `doc edit` / `doc sync`).
Same script `install.ps1` runs at install time; `ts-update` runs it after a pull.

A dev clone at a workspace tier path is **invisible** to `ts-update` and the
resolvers — pinning `$env:TERMINAL_STACK_DIR` at it is exactly how you develop
against it (the canonical install at `%LOCALAPPDATA%\terminal-stack\stack` needs
no pin), and a tier path is exempt from the installers' refusal to put the runtime
clone inside a workspace root. If you later move or delete the dev clone, the pin
goes stale: the resolvers warn and fall back to the canonical install rather than
breaking, and `ts-doctor -Repair` removes the dead line. Set once in
`Documents\PowerShell\profile.local.ps1`:

```powershell
$env:TERMINAL_STACK_DIR = 'C:\DATA\Workspace\src\github.com\martybytes\terminal-stack'
```

Then:

```powershell
& "$env:TERMINAL_STACK_DIR\scripts\sync-windows.ps1" -SourceDir $env:TERMINAL_STACK_DIR
```

## Reload in WezTerm

| What changed | How to pick it up |
|---|---|
| `.wezterm.lua` | Usually auto-reloads when the deployed file changes |
| `pane_nav.lua` | **`Ctrl+Space` `r`** (`ReloadConfiguration`) |

No need to quit WezTerm — but see the mux-server caveat below.

## Mux server (Windows)

On Windows the panes live in `wezterm-mux-server` (`default_domain = 'main'`),
which loads its **own** copy of `.wezterm.lua`. A GUI reload does not update the
config the mux uses for spawning panes; both sync scripts print a reminder when a
WezTerm file changed. Nothing restarts the mux automatically — that would kill
every live pane. When convenient (closes all panes!): close WezTerm, then
`taskkill /IM wezterm-mux-server.exe /F`, and relaunch.

## Plugins

`tabline.wez` (status bar), `sessionizer.wezterm` (`Ctrl+Space` `p`), and
`resurrect.wezterm` (save/restore) load from **pinned forks under
`github.com/martybytes`** — upstream archival or a breaking change can't take the
stack down. `wezterm.plugin.require` clones each fork at the **first GUI start**
(needs network once; cached in WezTerm's plugin dir after that). Every load is
pcall-guarded: tabline falls back to the hand-rolled status handler, the other two
just lose their binding.

To update a plugin: pull upstream into the fork deliberately, then run
`wezterm.plugin.update_all()` from the debug overlay (**`Ctrl+Shift+L`**) — or
delete the plugin cache dir and restart WezTerm.

## Windows 11 — what sync covers (test checklist)

`sync-windows.ps1` deploys everything WezTerm on Windows reads **plus** the
Windows-side pieces that show up inside WezTerm panes. One sync, then reload /
new tabs as needed.

### Synced by `sync-windows.ps1`

| Edit in clone | Deployed to | Test by |
|---|---|---|
| `windows/.wezterm.lua.tmpl` | `%USERPROFILE%\.wezterm.lua` | Keys, theme, tab bar, status line, launch menu |
| `windows/.wezterm/pane_nav.lua` | `%USERPROFILE%\.wezterm\pane_nav.lua` | `F1`–`F4` directional nav-or-split, `F5`/`F6` PaneSelect, leader+`1`–`6` |
| `windows/.claude/settings.json.tmpl` | `%USERPROFILE%\.claude\settings.json` | Claude hook wiring |
| `windows/.claude/hooks/wez-tab-status.ps1` | `%USERPROFILE%\.claude\hooks\…` | Tab tint + `cc_state` user var |
| `windows/Documents/PowerShell/…profile.ps1` | `$PROFILE` | `cc*` wrappers, `wezterm cli set-tab-title` |
| `windows/.config/starship.toml.tmpl` | `%USERPROFILE%\.config\starship.toml` | Prompt in pwsh panes |
| `windows/AppData/Roaming/Cursor/User/terminal-stack.terminal.json` | same path under `%USERPROFILE%` | Fragment merged into `%APPDATA%\Cursor\User\settings.json` (`automationProfile`) |
| `docs/kb/**` | `%LOCALAPPDATA%\terminal-stack\docs\kb\` | `doc` / `wzr` only — not WezTerm |

WezTerm loads only `.wezterm.lua` and `require 'pane_nav'` — both are under
`windows/` and sync covers them.

### After sync — pick up changes

| What you changed | Do this |
|---|---|
| `.wezterm.lua` | Usually auto-reloads; else **`Ctrl+Space` `r`** |
| `pane_nav.lua` | **`Ctrl+Space` `r`** (required) |
| `$PROFILE` or Starship | **New pwsh tab** or `. $PROFILE` |
| Claude hooks / settings | **Restart Claude Code** in that pane |

### Not covered by sync (separate steps)

| Gap | Fix |
|---|---|
| **WSL zsh panes** (launch menu → WSL zsh) | `chezmoi apply -v` from WSL — edits live in `dot_zshrc`, `dot_claude`, … |
| **Leader / theme tokens** in rendered `.tmpl` | Run `ts-config` (or ensure `%LOCALAPPDATA%\terminal-stack\config.json` is current) **before** sync |
| **WezTerm binary / Nerd Font** | winget — not in the repo |
| **`profile.local.ps1`**, `~/.doc.local/` | Intentionally never synced |

### Minimal pwsh-only test loop

```powershell
& C:\path\to\terminal-stack\scripts\sync-windows.ps1 -SourceDir C:\path\to\terminal-stack
```

In WezTerm: **`Ctrl+Space` `r`** → new pwsh tab if you touched `$PROFILE` → run
`cc` in a project dir to exercise tab titles / Claude tint hooks.

### WSL panes in the same window

```sh
chezmoi apply -v    # when dot_zshrc / WSL-side Claude hooks changed
```

## WSL / combined setup

From WSL (chezmoi `sourceDir` = your dev clone):

```sh
chezmoi apply -v
```

The `run_after_90-sync-windows.sh` hook mirrors `windows/**` to
`/mnt/c/Users/<you>/` — same result as `sync-windows.ps1` for WezTerm files.
Use this when you are also changing WSL-side chezmoi targets in one session.

## macOS — deploy after save

```sh
chezmoi apply -v ~/.wezterm.lua ~/.wezterm/pane_nav.lua
```

Reload: auto for `~/.wezterm.lua`; **`Ctrl+Space` `r`** for `pane_nav.lua`.

## Optional shortcuts

**Auto-sync on save** — run in a side pwsh window; fires `sync-windows.ps1` when
anything under `windows/` changes:

```powershell
$clone = 'C:\DATA\Workspace\src\github.com\martybytes\terminal-stack'
$src   = Join-Path $clone 'windows'
$sync  = Join-Path $clone 'scripts\sync-windows.ps1'
$w = New-Object IO.FileSystemWatcher $src -PropertyName LastWrite,FileName,DirectoryName -IncludeSubdirectories
Register-ObjectEvent $w Changed -Action { & $sync -SourceDir $clone } | Out-Null
Write-Host "Watching $src — Ctrl+C to stop"
while ($true) { Start-Sleep 60 }
```

Still **`Ctrl+Space` `r`** after `pane_nav.lua` edits.

**Symlink `pane_nav.lua`** — iterate on the grid module without re-syncing each
save (symlinks may need Developer Mode / elevated shell on Windows):

```powershell
$clone = 'C:\DATA\Workspace\src\github.com\martybytes\terminal-stack'
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.wezterm" | Out-Null
Remove-Item "$env:USERPROFILE\.wezterm\pane_nav.lua" -ErrorAction SilentlyContinue
New-Item -ItemType SymbolicLink `
  -Path "$env:USERPROFILE\.wezterm\pane_nav.lua" `
  -Target (Join-Path $clone 'windows\.wezterm\pane_nav.lua')
```

A full `sync-windows.ps1` replaces the symlink with a regular copy — re-create the
link if that happens.

## Don't

- Hand-edit `%USERPROFILE%\.wezterm.lua` or `~/.wezterm.lua` — the next sync/apply
  overwrites it (`.bak.YYYYMMDD` backup). Edit the `.tmpl` / repo source.
- Point `WEZTERM_CONFIG_FILE` at the clone — this stack deploys to `%USERPROFILE%`
  and `require 'pane_nav'` from `~/.wezterm/`. Use the sync script instead.
