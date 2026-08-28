# Architecture

## The cross-side problem

chezmoi natively manages files under `$HOME` on the machine where it runs. On Windows, `$HOME` is `C:\Users\<you>\` and chezmoi can manage it directly. On WSL, `$HOME` is `/home/<you>/` and chezmoi manages that.

Our terminal stack spans both. WezTerm's `.wezterm.lua` lives on the Windows side (because WezTerm runs as a Windows process). zsh's `.zshrc` lives on the WSL side. PowerShell's `$PROFILE` is at `C:\Users\<you>\Documents\PowerShell\...`. zsh's `precmd` and CC's hook scripts need to reach `wezterm.exe` on the Windows side via WSL interop.

We could run chezmoi twice — once on each side, with its own source repo. That doubles the artifact and creates sync problems.

## The cross-side solution

**One chezmoi source repo. chezmoi runs natively in WSL and applies to WSL home directly. A `run_after_` hook script syncs the Windows-targeted files out to `/mnt/c/Users/<you>/` after the WSL apply finishes.**

### Source-tree convention

```
terminal-stack/
├── dot_zshrc                       → ~/.zshrc (WSL)
├── dot_tmux.conf.tmpl              → ~/.tmux.conf (WSL/Linux/macOS)
├── dot_config/starship.toml        → ~/.config/starship.toml (WSL)
├── dot_claude/modify_settings.json.tmpl → ~/.claude/settings.json (spliced per key, not replaced)
├── dot_claude/hooks/...            → ~/.claude/hooks/... (WSL)
├── dot_codex/...                   → ~/.codex/... (WSL; also mirrored to Windows)
└── windows/                        ← NOT applied by chezmoi
    ├── .wezterm.lua.tmpl           → /mnt/c/Users/<you>/.wezterm.lua (sync-hook template)
    ├── .wezterm/pane_nav.lua       → /mnt/c/Users/<you>/.wezterm/pane_nav.lua
    ├── .config/...                 → /mnt/c/Users/<you>/.config/...
    ├── Documents/...               → /mnt/c/Users/<you>/Documents/...
    ├── .claude/settings.json.tmpl  → /mnt/c/Users/<you>/.claude/settings.json (rendered, then spliced per key)
    └── .cursor/hooks.json.tmpl     → /mnt/c/Users/<you>/.cursor/hooks.json (rendered, then spliced per entry)
```

`.chezmoiignore` excludes `windows/**` from the normal target-tree apply, so chezmoi never tries to write `~/windows/.wezterm.lua` to your home directory.

### Username resolution

No file in this repo hard-codes a username. The username is resolved at apply time:

- **WSL-side `.tmpl` files** (anything under the chezmoi source root, e.g. `dot_config/starship.toml.tmpl`) use chezmoi's native template engine — `{{ .chezmoi.homeDir }}` expands to the current `$HOME`.
- **Windows-side `.tmpl` files** (anything under `windows/`) use a `__WIN_USER__` placeholder that the `run_after_90-sync-windows.sh` hook substitutes. The hook resolves the Windows username in this order:
  1. `chezmoi data` → `windowsUsername` (set by the bootstrap script under `[data]` in `~/.config/chezmoi/chezmoi.toml`).
  2. Fallback: `cmd.exe /c echo %USERNAME%` via WSL interop.

The WSL bootstrap (`bootstrap/wsl-bootstrap.sh`) prompts for the Windows username at install time (pre-filling the interop-detected value) and persists it under `[data]`.

`__WIN_USER__` is one of several tokens the sync substitutes: the saved wizard config supplies `__LEADER_KEY__` / `__LEADER_MODS__` (WezTerm leader), `__THEME_MODE__` / `__THEME_RESOLVED__` (theme), `__TMUX_PREFIX__`, `__WEZ_MUX__` (WezTerm multiplexer domain, `tstack mux`), `__WEZ_RESTORE__` (reopen the last session at startup), and the optional `__CC_TTS_*__` hook blocks. See `CLAUDE.md` § "User config tokens" and the header of `run_after_90-sync-windows.sh` for the full list.

### The run_after hook

`run_after_90-sync-windows.sh` runs after every successful `chezmoi apply`. It mirrors `$CHEZMOI_SOURCE_DIR/windows/` to `/mnt/c/Users/<you>/`, `dot_codex/` to `/mnt/c/Users/<you>/.codex/`, and `docs/kb/` to the Windows documentation cache (substituting `__WIN_USER__` and the config tokens in `.tmpl` files — via python3, which the hook requires — and stripping the `.tmpl` suffix), and:

- **Idempotent**: only touches files whose content differs from what's already at the destination. If the rendered source is byte-identical to the destination, it's skipped.
- **Backup-first**: any pre-existing file that gets overwritten is first copied to `<path>.bak.YYYYMMDD`. If that backup name is already taken (you applied twice in one day), the new backup gets a `.N` suffix (`.bak.YYYYMMDD.1`, `.2`, …). The original-day backup is never clobbered.
- **Silent on miss**: if `/mnt/c/Users/<you>/` doesn't exist (running on a non-WSL host like macOS), the script exits cleanly without error.

## Why this shape

- **Single `chezmoi apply` updates both sides.** No "remember to also run X" workflow.
- **Single git history.** Every Windows-side config change shows up in `git log` alongside its WSL-side counterpart. Easy to audit "what did I change last Tuesday".
- **Mac sync works.** On a Mac, `chezmoi apply` will skip the `windows/` subtree (excluded) and the run_after hook exits cleanly because `/mnt/c/Users/<you>/` doesn't exist. You get just the dot-files that make sense on macOS.
- **No usernames in source.** Forks-for-different-users just need to provide the username once during bootstrap (or let interop detect it).
- **Recoverable.** Any time the sync hook overwrites a file, the backup-first behavior preserves the prior state for at least the rest of that day.

## Trade-offs we accepted

- **Two sources of CR-LF drift to watch.** The Edit tool in Windows-side workflows can leave CR-LF endings on files that the WSL chezmoi source has as LF. The first `chezmoi apply` after a Windows-side hand-edit may trip the "differs from chezmoi source" detection on EOL alone and create a backup of the LF-ified version. We use `sed -i 's/\r$//'` on chezmoi-source files defensively whenever we edit through the Windows UNC path.
- **chezmoi `run_after` scripts always appear in `chezmoi diff`.** This is chezmoi's own metadata view, not a real-target diff. The script doesn't actually get *placed* anywhere — it just runs. So the diff output looks noisier than it is.
- **No native chezmoi templating for the Windows-side paths.** chezmoi has `{{ .chezmoi.os }}` etc. that could in principle template-conditionalize where files land, but for our case the `windows/` + `run_after_` pattern is simpler and explicit.

## Other architectural notes

- **Per-machine overrides have a file on every platform.** zsh sources `~/.zshrc.local` at the end of `.zshrc`; pwsh dot-sources `Documents\PowerShell\profile.local.ps1` at the end of `$PROFILE`. Neither is tracked — only `.example` twins ship. Workspace location is the canonical use: `ws`/`wsp`/`wspu` resolve `$WORKSPACE_DIR` → autodetect candidates at *call* time (see `docs/decisions.md` § "Why `$WORKSPACE_DIR` + call-time resolution"), so the override file is only needed on machines whose workspace lives somewhere non-standard.
- **`tstack update` is reversible.** It records the pre-pull HEAD to `~/.local/state/terminal-stack/rollback-sha` (zsh) / `%LOCALAPPDATA%\terminal-stack\rollback-sha` (pwsh) before pulling; `tstack rollback` resets the clone to that SHA and re-applies. Both refuse to act on a dirty clone.
- **`wso` is the one command implemented twice rather than shimmed.** Everything else in the stack is either a shell function mirrored per shell or a script one side calls; the workspace organizer is a full parallel pair — `bootstrap/_workspace.sh` + `bootstrap/wso.sh` (bash: WSL, native Linux, macOS) and `bootstrap/_workspace.ps1` + `bootstrap/_workspace_cmd.ps1` (pwsh: Windows). Calling into WSL from Windows would break a Windows-standalone install, and driving ~100 repos' worth of `git` calls across the 9p boundary is slow enough to matter. Both live under `bootstrap/**` (chezmoi-ignored) and run from the clone, so `tstack update` ships a fix without a profile re-sync. They must agree: same subcommands, same flags, same plan output, byte-identical `--help`.
- **`tstack smb` is the one command that is deliberately *not* implemented twice.** Every other dual-shell command keeps a pwsh twin with byte-identical `-h`; `tstack smb` (`bootstrap/ts-smb.sh` + `bootstrap/_smb.sh`, zsh wrapper only) is macOS/Linux as of 2026-08-23. Most of what it does is moot on Windows — Explorer and `net use` already browse and map SMB shares, credentials live in Credential Manager, and the whole FUSE engine layer has no analogue beyond WinFsp. The gap is stated in its `-h`, in `CLAUDE.md`, and in `docs/decisions.md` § "Why `tstack smb` ships without a PowerShell twin", so it reads as a decision rather than drift. Its share store is untracked and machine-local by design and adds no chezmoi `[data]` key — see `docs/decisions.md` § "Why the SMB share inventory is local-only and never synced".
- **`wso` writes outside the clone, and says so.** It moves repositories inside `$WORKSPACE_DIR` (atomic same-volume renames only — it refuses a cross-volume move rather than silently degrading to copy+delete), appends a TSV to `<workspace>/.terminal-stack/workspace-runs/`, and `wso identity` generates `~/.config/git/terminal-stack-workspace.gitconfig` plus per-owner `identity-<owner>` files, registering them with a single `git config --global --add include.path`. Those identity files hold real names and emails, so they are per-machine and generated rather than tracked — the source tree stays free of personal data. Anything it overwrites gets the standard `.bak.YYYYMMDD[.N]` treatment first, it never deletes a repository, and it never migrates a terminal-stack clone found un-tiered at the workspace root — moving the stack's own runtime clone is `tstack doctor --repair`'s job, and doing it here once orphaned an install.
- **Run logs live with the workspace, not in per-OS state.** Unlike `rollback-sha`, which describes the clone and is genuinely per-side, an archive run describes the *workspace* — and on a combined Windows+WSL machine both sides drive the same tree. Logs therefore sit in `<workspace>/.terminal-stack/workspace-runs/` with paths stored relative to the workspace root and forward-slashed, so `wso unarchive --undo-last` from zsh can reverse a run made from PowerShell.
- **PowerShell `$PROFILE` is whole-file-synced, marker-block *edited*.** Both sync scripts copy the repo source (`windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1`) over `$PROFILE` whole, with a `.bak.YYYYMMDD[.N]` backup on every overwrite — anything hand-added to the live `$PROFILE` outside the repo is replaced on the next sync (recoverable from the `.bak`, but gone from the live file). Per-machine content belongs in `profile.local.ps1`, which `$PROFILE` dot-sources at the end and is never synced. The `# ---- name-start ----` / `# ---- name-end ----` marker blocks survive as *editing discipline* in the repo source — they delimit the stack's functional regions, not a merge mechanism. See `docs/decisions.md` § "Why a whole-file `~/.zshrc` and a marker-block `$PROFILE`?".
- **`~/.zshrc` is whole-file-managed.** It was created from scratch by oh-my-zsh during our deployment, so we own the entire file, and its source is not a template. Both conditions hold, so `chezmoi re-add ~/.zshrc` is correct here — it is the case the rule permits, not an exception to it. Whether re-add is safe for any other target is decided by **`CLAUDE.md` § "The one `re-add` rule"**, which states it once for all three cases; the entry below and `AGENTS.md` each cover one of the other two.
- **Claude Code `settings.json` and Cursor `hooks.json` are *part-owned*, and must never be re-added or copied whole.** Both files hold another tool's state next to ours: Claude Code writes `model`, `enabledPlugins`, `permissions` and `env` into its settings (via `/model`, `/plugin`, `/config`), and agentmemory's Cursor hooks share the `stop` and `postToolUse` event arrays with our TTS hooks. On the Windows side the sync therefore splices — `bootstrap/_merge_claude_settings.ps1` per top-level key, `bootstrap/_merge_cursor_hooks.ps1` per hook entry — and leaves every byte it does not own alone. Do **not** run `chezmoi re-add ~/.claude/settings.json` to capture a UI preference: that pulls the other tool's private state (up to and including anything in `env`) into the tracked template, where the next apply pushes it to every machine. Change ours in the template; leave theirs where the app put it. See `docs/decisions.md` §§ "Why `~/.claude/settings.json` is spliced, not copied" / "Why `~/.cursor/hooks.json` needs per-entry ownership".

## Backup discipline

**This is the canonical statement of the rule; `CLAUDE.md` links here.**

Any script in this repo that overwrites a user file writes a backup first, named
`<path>.bak.YYYYMMDD`. If that name already exists (a same-day re-run), append
`.1`, `.2`, and so on: a same-day backup is never clobbered, because the second
run of a bad script would otherwise destroy the good copy the first one saved.

This covers human-or-script overwrites, not a chezmoi-managed apply, which has
its own state. Reference implementation: the `.bak` block near the top of
`run_after_90-sync-windows.sh`. See `docs/decisions.md` § "Why two backups" for
the Phase 7 incident that motivated the `.N` collision guard.

## Two halves: config and services

Headroom MCP crosses the config/service boundary as a process, not another
published port. Agent clients run `docker exec -i ts-headroom-proxy headroom mcp
serve --transport stdio --proxy-url http://127.0.0.1:8787`; lifecycle adapters
probe it with JSON-RPC `initialize` but still never start or mutate Docker. Port
`8788` remains the dashboard-only nginx gateway, so `/mcp` there is invalid.

chezmoi owns `$HOME`. `tstack services` owns Docker. They meet in exactly two places: a
published loopback port, and `bootstrap/agent-tools.json`, the single file where
a port, URL, image tag or version pin is written down.

```
services/                        outside services/
  compose files, images,   <->   ~/.claude, ~/.codex, ~/.cursor,
  in-container patches           the shells, the prompt
  tstack services                       tstack config agents / tstack agentmemory
```

The line used to be a repository boundary, which enforced itself — you could not
accidentally put a hook installer in the Docker repo, because it was a different
clone. Absorbing that repo removes the enforcement, so the rule is written down
and tested instead: `tests/test_agent_tools.py` asserts that `docker compose`,
`docker rm` and `restart: unless-stopped` appear nowhere in
`tstack/commands/agents.py` — as a case-insensitive match over the whole file,
so even a comment naming the compose command fails it. When a probe fails,
`tstack agents` prints the *verb* (`tstack services up playwright`), never the command.
