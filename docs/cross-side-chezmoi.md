# Cross-side chezmoi: deep dive

ARCHITECTURE.md gives the 30-second version. This file is for when you (or your future self) want to actually understand the mechanism and modify it safely.

## The basic problem

You're using one tool — chezmoi — to manage configuration files. Some of those files live in your WSL/Linux home (`/home/<you>/`). Others live on the Windows side (`C:\Users\<you>\`). Both are mounted on the same machine, but they're separate filesystems with separate `$HOME` concepts.

chezmoi, by default, manages exactly one target tree: `$HOME` on the machine where it's running. Whichever side you run `chezmoi apply` from is the side whose home gets updated. The other side gets nothing.

Workarounds people try:

1. **Run chezmoi twice, once per side.** Maintain two source repos. Drift is inevitable.
2. **Symlink Windows-side configs into WSL home.** Some configs (like `.wezterm.lua`) WezTerm needs to find at the Windows-side absolute path, so this doesn't actually work.
3. **One repo, single chezmoi run, post-apply mirror script.** ← what we do.

## Our convention

`.chezmoiignore` at the source root contains a single line:

```
windows/**
```

This excludes anything under `windows/` from chezmoi's normal apply. chezmoi-managed files (`dot_zshrc`, `dot_tmux.conf`, etc.) outside of `windows/` are applied normally to WSL home.

Files under `windows/` use absolute-path-mirror naming (with `$WIN_USER` resolved at sync time — see § "Username resolution" below):

| Source path | Sync destination |
|---|---|
| `windows/.wezterm.lua.tmpl` | `/mnt/c/Users/$WIN_USER/.wezterm.lua` (rendered) |
| `windows/.config/starship.toml` | `/mnt/c/Users/$WIN_USER/.config/starship.toml` |
| `windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1` | `/mnt/c/Users/$WIN_USER/Documents/PowerShell/Microsoft.PowerShell_profile.ps1` |
| `windows/.claude/settings.json.tmpl` | `/mnt/c/Users/$WIN_USER/.claude/settings.json` (rendered) |
| `windows/.claude/hooks/wez-tab-status.ps1` | `/mnt/c/Users/$WIN_USER/.claude/hooks/wez-tab-status.ps1` |
| `dot_codex/**` | `/mnt/c/Users/$WIN_USER/.codex/**` (also applied normally to WSL `~/.codex/**`) |
| `docs/kb/**` | `/mnt/c/Users/$WIN_USER/AppData/Local/terminal-stack/docs/kb/**` (plain copy; `doc` read fallback) |

The destination is computed from the source relative path by joining onto `$dst_dir` (`/mnt/c/Users/$WIN_USER`) for `windows/**`, `$dst_dir/.codex` for `dot_codex/**`, or `$dst_dir/AppData/Local/terminal-stack/docs/kb` for the kb mirror. Files ending in `.tmpl` under either rendered mirror are passed through a small **python3** substitution (python3 is required — a sed fallback was removed because it could not render the multi-line `__CC_TTS_*__` tokens and broke on two-modifier leader values) that replaces `__WIN_USER__` and the saved-config tokens (`__LEADER_KEY__`, `__LEADER_MODS__`, `__THEME_MODE__`, `__THEME_RESOLVED__`, `__TMUX_PREFIX__`, `__CC_TTS_*__`) with their resolved values, then the `.tmpl` suffix is stripped from the destination path.

## Username resolution

`run_after_90-sync-windows.sh` resolves the Windows username in this order:

1. **`chezmoi data` → `windowsUsername`.** If `~/.config/chezmoi/chezmoi.toml` contains:

   ```toml
   [data]
   windowsUsername = "your-windows-user"
   ```

   the script reads it via `chezmoi execute-template '{{ if hasKey . "windowsUsername" }}{{ .windowsUsername }}{{ end }}'`. The WSL bootstrap (`bootstrap/wsl-bootstrap.sh`) writes this during install.

2. **`cmd.exe /c echo %USERNAME%` via WSL interop.** Used when chezmoi data is unset; usually returns the same value `$env:USERNAME` would report on the Windows side.

If both resolution paths fail, the script exits 1 with a message telling you to add `windowsUsername` to `chezmoi.toml`.

## Adding a templated Windows-side file

If you need a Windows-side file that should reference the username:

1. Name the source file with a `.tmpl` suffix, e.g. `windows/SomeApp/config.toml.tmpl`.
2. Inside the file, use `__WIN_USER__` wherever the username should appear.
3. `chezmoi apply` → the hook renders to `/mnt/c/Users/<you>/SomeApp/config.toml`.

No additional placeholder syntax (no Go templates, no jinja) — just literal `__TOKEN__` substitution. Besides `__WIN_USER__`, the saved-config tokens listed above (`__LEADER_KEY__`, `__LEADER_MODS__`, `__THEME_MODE__`, `__THEME_RESOLVED__`, `__TMUX_PREFIX__`, `__WEZ_MUX__`, `__WEZ_RESTORE__`, `__CC_TTS_*__`) are available; see `CLAUDE.md` § "User config tokens".

## The post-apply hook

`run_after_90-sync-windows.sh` is the orchestrator. chezmoi recognizes the `run_after_` prefix and executes it after every `chezmoi apply`. The `90` is a sort-order number — if you add more `run_after_` scripts later, they run in ascending order.

The body iterates `$CHEZMOI_SOURCE_DIR/windows/`, `dot_codex/`, and `docs/kb/`, doing an idempotent compare-and-replace against each destination with backup-first semantics.

### Idempotency

For each source file:

1. If the destination doesn't exist → create it (mkdir parents, cp).
2. If the destination exists and matches byte-for-byte (`cmp -s`) → skip.
3. If the destination exists and differs → backup destination to `<path>.bak.YYYYMMDD`, then overwrite.

### Backup hardening (added during Phase 7 incident)

The original version of the script blindly wrote `<path>.bak.YYYYMMDD`, overwriting any existing same-day backup. This bit us once: on the same day the stack was deployed, a Windows-side hand-edit caused a sync to fire, and the existing `.bak.YYYYMMDD` (which was the *original* pre-deployment file) got clobbered with the post-deployment state.

Fix:

```sh
bak="$dst.bak.$today"
if [ -e "$bak" ]; then
    n=1
    while [ -e "$dst.bak.$today.$n" ]; do n=$((n + 1)); done
    bak="$dst.bak.$today.$n"
fi
cp -p -- "$dst" "$bak"
```

First overwrite of the day still goes to `.bak.YYYYMMDD`. Second goes to `.bak.YYYYMMDD.1`. Third to `.2`. Originals are never lost.

### macOS / non-WSL safety

```sh
if [ ! -d "$src_dir" ]; then exit 0; fi
```

If `$CHEZMOI_SOURCE_DIR/windows/` doesn't exist (which would happen if you've stripped it out), the script noops. Same logic applied to `$dst_dir` — if `/mnt/c/Users/<you>` doesn't exist (you're on macOS), the script exits clean without errors.

Actually that's how it works today. Worth double-checking the source.

## EOL hygiene

chezmoi source files end up with LF endings (they're text files in a Linux-native source). When we edit those source files from the Windows side (via UNC `\\wsl$\Ubuntu\...`), Edit/Write tools sometimes inject CRLF. Then `chezmoi apply` runs, the run_after script sees the chezmoi source (LF) and the destination Windows file (CRLF), `cmp -s` reports "differ", the script backs up the destination and overwrites with the LF version.

This isn't strictly a bug — PowerShell parses both LF and CRLF — but it pollutes the backup directory with non-content-change backups.

Mitigation we use:

```sh
sed -i 's/\r$//' <chezmoi-source-file>
```

Run on any chezmoi-source file we've just edited through a Windows-side tool. This is in our deployment muscle-memory but isn't enforced. If you regularly hand-edit chezmoi sources via Windows tools, consider adding a pre-commit hook (no-op git hook in `.git/hooks/pre-commit` that runs the sed).

## Running chezmoi from outside WSL

The chezmoi.toml override at `~/.config/chezmoi/chezmoi.toml` points sourceDir at `/mnt/c/Users/<you>/AppData/Local/terminal-stack/stack`. This path exists in WSL (via the drvfs mount) but not directly on Windows.

If you wanted to run chezmoi from the Windows side natively (without WSL), you'd:

1. Install chezmoi on Windows (`winget install twpayne.chezmoi`)
2. Write a separate `%USERPROFILE%\AppData\Local\chezmoi\chezmoi.toml` with `sourceDir = "C:\\Users\\<you>\\AppData\\Local\\terminal-stack\\stack"` (note: Windows path)
3. Run `chezmoi apply` from Windows pwsh — this would apply to `C:\Users\<you>\` directly, *without* running the run_after script (since `.sh` files require a shell to execute, and chezmoi's Windows binary doesn't have a POSIX shell to fall back on for `run_after_*.sh`)

We deliberately don't do this. Running chezmoi from WSL on this machine gives us one orchestrator and one source of truth.

## What if I want to add more Windows-side files?

1. Drop the file in the right place under `windows/`. Example: a new Windows-side CLI tool config at `C:\Users\<you>\.foo\config.toml` → put it at `windows/.foo/config.toml` in the chezmoi source. If the file needs to embed the username, add a `.tmpl` suffix and use the `__WIN_USER__` placeholder.
2. `chezmoi apply` — the run_after script picks it up and syncs.
3. `chezmoi git -- add -A && chezmoi git -- commit -m "..."`.

No additional script or config change needed.

## What if I want to add more WSL-side files?

Standard chezmoi conventions. `dot_foo` → `~/.foo`. `dot_config/foo/bar` → `~/.config/foo/bar`. `executable_foo.sh` → executable bit set on apply.

## Limitations

- **`windows/` subtree is invisible to chezmoi's diff machinery.** `chezmoi diff` doesn't show pending changes to `/mnt/c/Users/<you>/...` because chezmoi doesn't know about them. You can preview the run_after sync by running the script directly with `--dry-run` semantics (not built in; you'd need to add it).
- **No templating in `windows/`.** chezmoi's `.tmpl` files only apply to chezmoi-managed paths. If you need OS- or hostname-conditional content in a `windows/` file, you'd add it via the run_after script reading templates, or just maintain platform-specific files.
- **Mac side is a clean miss.** macOS won't have `windows/.wezterm.lua` synced anywhere; the run_after script noops. That's correct — macOS doesn't have `C:\Users\<you>\.wezterm.lua`. macOS-specific configs (if any) would live as native chezmoi-managed files (e.g., `dot_zshrc` continues to work).
