# Developing WezTerm config

> **`doc wezterm/dev-config`** — same content in the `doc` knowledge base (cheat-sheet format).

WezTerm does **not** read your git clone directly. It loads config from your home directory. Edits in the repo take effect only after they are **deployed** there and WezTerm **reloads**.

## Source → deployed paths

| Platform | Edit in clone | WezTerm reads |
|---|---|---|
| **Windows** | `windows/.wezterm.lua.tmpl` | `%USERPROFILE%\.wezterm.lua` (rendered) |
| **Windows** | `windows/.wezterm/pane_nav.lua` | `%USERPROFILE%\.wezterm\pane_nav.lua` |
| **Windows** | `docs/kb/**` | `%LOCALAPPDATA%\terminal-stack\docs\kb\` (`doc` read fallback) |
| **macOS** | `dot_wezterm.lua.tmpl` | `~/.wezterm.lua` (chezmoi-rendered) |
| **macOS** | `dot_wezterm/pane_nav.lua` | `~/.wezterm/pane_nav.lua` |

Keep `windows/.wezterm.lua.tmpl` and `dot_wezterm.lua.tmpl` visually in sync when changing shared behaviour (see `docs/decisions.md` § "Why a separate `dot_wezterm.lua` for macOS"). Keep `windows/.wezterm/pane_nav.lua` and `dot_wezterm/pane_nav.lua` in sync — they differ only in their header comment.

On Windows + WSL, the WSL GUI is still the **Windows** WezTerm process — WSL home gets no WezTerm config.

## Windows dev loop

Run WezTerm normally (no special launch flags). After saving WezTerm files in your clone:

```powershell
& C:\path\to\terminal-stack\scripts\sync-windows.ps1 -SourceDir C:\path\to\terminal-stack
```

`sync-windows.ps1` renders `.tmpl` files (leader key, theme tokens, `__WIN_USER__`, etc.) and copies only targets whose bytes differ. Same script `install.ps1` runs at the end of a Windows install, and `ts-update` runs it after a pull.

If your dev clone is not the install default (`%USERPROFILE%\terminal-stack`), point the stack at it once in `Documents\PowerShell\profile.local.ps1`:

```powershell
$env:TERMINAL_STACK_DIR = 'C:\DATA\Workspace\terminal-stack'
```

Then sync with:

```powershell
& "$env:TERMINAL_STACK_DIR\scripts\sync-windows.ps1" -SourceDir $env:TERMINAL_STACK_DIR
```

**Reload in WezTerm:**

- Changes to `.wezterm.lua` — WezTerm usually auto-reloads when the deployed file changes on disk.
- Changes to `pane_nav.lua` — press **`Ctrl+Space` `r`** (`ReloadConfiguration`). Lua modules are not always picked up without an explicit reload.

You do not need to quit and relaunch WezTerm — with one caveat. On Windows the panes are hosted in `wezterm-mux-server` (`default_domain = 'main'`), and the mux server loads its **own** copy of `.wezterm.lua`: a GUI reload does not update the config the mux uses for spawning panes. Both sync scripts print a reminder when a WezTerm file changed; nothing restarts the mux automatically, because that would kill every live pane. When convenient (closes all panes!): close WezTerm, run `taskkill /IM wezterm-mux-server.exe /F`, and relaunch.

### Plugins (tabline / sessionizer / resurrect)

The status bar (`tabline.wez`), the `Ctrl+Space` `p` project picker (`sessionizer.wezterm`), and session save/restore (`resurrect.wezterm`) are WezTerm plugins loaded from **pinned forks under `github.com/martybytes`**, so an upstream archival or breaking change can't take the stack down. `wezterm.plugin.require` clones each fork at the **first GUI start** — that one start needs network access; afterwards the clone is cached in WezTerm's plugin directory. Each load is pcall-guarded: if tabline fails, the hand-rolled status handler takes over; if sessionizer or resurrect fail, only their keybindings are lost.

To update a plugin, pull upstream into the fork deliberately, then either run `wezterm.plugin.update_all()` from the debug overlay (**`Ctrl+Shift+L`**) or delete the plugin cache directory and restart WezTerm.

### Windows 11 — what sync covers (test checklist)

Full tables: **`doc wezterm/dev-config`**. Summary:

- **Synced and enough for pwsh WezTerm testing:** `.wezterm.lua`, `pane_nav.lua`, `$PROFILE` (`cc*` tab titles), `.claude` hooks/settings (tab tint), Starship in pwsh panes, and `docs/kb` (for `doc`/`wzr` only).
- **After sync:** `Ctrl+Space` `r` (required for `pane_nav.lua`); new pwsh tab for `$PROFILE`/Starship; restart Claude Code for hook changes.
- **Not synced:** WSL zsh panes (`chezmoi apply` from WSL); WezTerm/font winget packages; wizard tokens unless `ts-config` / `config.json` was refreshed before sync.

### Auto-sync on save (optional)

Run in a side pwsh window while editing; re-syncs whenever anything under `windows/` changes:

```powershell
$clone = 'C:\DATA\Workspace\terminal-stack'   # your dev clone
$src   = Join-Path $clone 'windows'
$sync  = Join-Path $clone 'scripts\sync-windows.ps1'
$w = New-Object IO.FileSystemWatcher $src -PropertyName LastWrite,FileName,DirectoryName -IncludeSubdirectories
Register-ObjectEvent $w Changed -Action { & $sync -SourceDir $clone } | Out-Null
Write-Host "Watching $src — Ctrl+C to stop"
while ($true) { Start-Sleep 60 }
```

Still use **`Ctrl+Space` `r`** after `pane_nav.lua` edits.

### Symlink `pane_nav.lua` (optional)

If you are iterating mostly on the grid module, link the repo file into place once (symlinks may require an elevated or Developer Mode shell on Windows):

```powershell
$clone = 'C:\DATA\Workspace\terminal-stack'
New-Item -ItemType Directory -Force -Path "$env:USERPROFILE\.wezterm" | Out-Null
Remove-Item "$env:USERPROFILE\.wezterm\pane_nav.lua" -ErrorAction SilentlyContinue
New-Item -ItemType SymbolicLink `
  -Path "$env:USERPROFILE\.wezterm\pane_nav.lua" `
  -Target (Join-Path $clone 'windows\.wezterm\pane_nav.lua')
```

Edits in the clone are visible at WezTerm's module path immediately; **`Ctrl+Space` `r`** to reload. A full `sync-windows.ps1` run replaces the symlink with a regular copy if it thinks the file differs — re-create the link if that happens.

## WSL / combined Windows + WSL

From WSL, with chezmoi's `sourceDir` pointing at your dev clone:

```sh
cd /mnt/c/DATA/Workspace/terminal-stack   # adjust path
~/.local/bin/chezmoi apply -v
```

The `run_after_90-sync-windows.sh` hook at the end mirrors `windows/**` to `/mnt/c/Users/<you>/` — same result as `sync-windows.ps1` for Windows-side WezTerm files. Prefer this path when you are also changing WSL-side chezmoi targets in the same session.

## macOS dev loop

After saving `dot_wezterm.lua.tmpl` or `dot_wezterm/pane_nav.lua`:

```sh
chezmoi apply -v ~/.wezterm.lua ~/.wezterm/pane_nav.lua
```

Or apply everything:

```sh
chezmoi apply -v
```

Reload: auto-reload for `~/.wezterm.lua` when it changes; **`Ctrl+Space` `r`** for `pane_nav.lua`.

## What not to do

- **Do not edit the deployed `%USERPROFILE%\.wezterm.lua` or `~/.wezterm.lua` by hand** — the next sync or `chezmoi apply` overwrites it (with a `.bak.YYYYMMDD` backup). Edit the `.tmpl` / repo source.
- **`WEZTERM_CONFIG_FILE`** can point WezTerm at a custom path, but this repo's Windows side relies on `%USERPROFILE%` deploy + `require 'pane_nav'` from `~/.wezterm/`. The sync script is the intended dev path; custom env-based setups are unsupported here.
