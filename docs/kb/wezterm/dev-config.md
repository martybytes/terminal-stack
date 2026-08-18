# WezTerm — developing config

WezTerm reads your **home directory**, not the git clone. Edit source files in the
clone, **deploy** them home, then **reload**. Run WezTerm normally — no special launch
flags.

## Source → deployed

| Platform | Edit in clone | WezTerm loads |
|---|---|---|
| Windows | `windows/.wezterm.lua.tmpl` | `%USERPROFILE%\.wezterm.lua` |
| Windows | `windows/.wezterm/pane_grid.lua` | `%USERPROFILE%\.wezterm\pane_grid.lua` |
| Windows | `docs/kb/**` | `%LOCALAPPDATA%\terminal-stack\docs\kb\` (`doc` read fallback) |
| macOS | `dot_wezterm.lua.tmpl` | `~/.wezterm.lua` |
| macOS | `dot_wezterm/pane_grid.lua` | `~/.wezterm/pane_grid.lua` |

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

When the dev clone is not `%USERPROFILE%\terminal-stack`, set once in
`Documents\PowerShell\profile.local.ps1`:

```powershell
$env:TERMINAL_STACK_DIR = 'C:\DATA\Workspace\terminal-stack'
```

Then:

```powershell
& "$env:TERMINAL_STACK_DIR\scripts\sync-windows.ps1" -SourceDir $env:TERMINAL_STACK_DIR
```

## Reload in WezTerm

| What changed | How to pick it up |
|---|---|
| `.wezterm.lua` | Usually auto-reloads when the deployed file changes |
| `pane_grid.lua` | **`Ctrl+Space` `r`** (`ReloadConfiguration`) |

No need to quit WezTerm.

## Windows 11 — what sync covers (test checklist)

`sync-windows.ps1` deploys everything WezTerm on Windows reads **plus** the
Windows-side pieces that show up inside WezTerm panes. One sync, then reload /
new tabs as needed.

### Synced by `sync-windows.ps1`

| Edit in clone | Deployed to | Test by |
|---|---|---|
| `windows/.wezterm.lua.tmpl` | `%USERPROFILE%\.wezterm.lua` | Keys, theme, tab bar, status line, launch menu |
| `windows/.wezterm/pane_grid.lua` | `%USERPROFILE%\.wezterm\pane_grid.lua` | `F1`–`F6`, leader+`1`–`6` grid |
| `windows/.claude/settings.json.tmpl` | `%USERPROFILE%\.claude\settings.json` | Claude hook wiring |
| `windows/.claude/hooks/wez-tab-status.ps1` | `%USERPROFILE%\.claude\hooks\…` | Tab tint + `cc_state` user var |
| `windows/Documents/PowerShell/…profile.ps1` | `$PROFILE` | `cc*` wrappers, `wezterm cli set-tab-title` |
| `windows/.config/starship.toml.tmpl` | `%USERPROFILE%\.config\starship.toml` | Prompt in pwsh panes |
| `windows/AppData/Roaming/Cursor/User/terminal-stack.terminal.json` | same path under `%USERPROFILE%` | Fragment merged into `%APPDATA%\Cursor\User\settings.json` (`automationProfile`) |
| `docs/kb/**` | `%LOCALAPPDATA%\terminal-stack\docs\kb\` | `doc` / `wzr` only — not WezTerm |

WezTerm loads only `.wezterm.lua` and `require 'pane_grid'` — both are under
`windows/` and sync covers them.

### After sync — pick up changes

| What you changed | Do this |
|---|---|
| `.wezterm.lua` | Usually auto-reloads; else **`Ctrl+Space` `r`** |
| `pane_grid.lua` | **`Ctrl+Space` `r`** (required) |
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
chezmoi apply -v ~/.wezterm.lua ~/.wezterm/pane_grid.lua
```

Reload: auto for `~/.wezterm.lua`; **`Ctrl+Space` `r`** for `pane_grid.lua`.

## Optional shortcuts

**Auto-sync on save** — run in a side pwsh window; fires `sync-windows.ps1` when
anything under `windows/` changes:

```powershell
$clone = 'C:\DATA\Workspace\terminal-stack'
$src   = Join-Path $clone 'windows'
$sync  = Join-Path $clone 'scripts\sync-windows.ps1'
$w = New-Object IO.FileSystemWatcher $src -PropertyName LastWrite,FileName,DirectoryName -IncludeSubdirectories
Register-ObjectEvent $w Changed -Action { & $sync -SourceDir $clone } | Out-Null
Write-Host "Watching $src — Ctrl+C to stop"
while ($true) { Start-Sleep 60 }
```

Still **`Ctrl+Space` `r`** after `pane_grid.lua` edits.

**Symlink `pane_grid.lua`** — iterate on the grid module without re-syncing each
save (symlinks may need Developer Mode / elevated shell on Windows):

```powershell
$clone = 'C:\DATA\Workspace\terminal-stack'
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.wezterm" | Out-Null
Remove-Item "$env:USERPROFILE\.wezterm\pane_grid.lua" -ErrorAction SilentlyContinue
New-Item -ItemType SymbolicLink `
  -Path "$env:USERPROFILE\.wezterm\pane_grid.lua" `
  -Target (Join-Path $clone 'windows\.wezterm\pane_grid.lua')
```

A full `sync-windows.ps1` replaces the symlink with a regular copy — re-create the
link if that happens.

## Don't

- Hand-edit `%USERPROFILE%\.wezterm.lua` or `~/.wezterm.lua` — the next sync/apply
  overwrites it (`.bak.YYYYMMDD` backup). Edit the `.tmpl` / repo source.
- Point `WEZTERM_CONFIG_FILE` at the clone — this stack deploys to `%USERPROFILE%`
  and `require 'pane_grid'` from `~/.wezterm/`. Use the sync script instead.
