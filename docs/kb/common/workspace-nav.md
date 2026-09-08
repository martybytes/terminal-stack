# Workspace navigation

| Command | What it does |
|---|---|
| `ws` | cd to the workspace — `$WORKSPACE_DIR` (zsh `~/.zshrc.local` / pwsh `profile.local.ps1`) if set, else autodetected |
| `ws --set [dir]` | pin `WORKSPACE_DIR` in the per-machine override file (default: current dir) |
| `ws --set <dir> --move` | pin it **and relocate the tree there**, across volumes if needed |
| `ws --show` | print the resolved root and which layer it came from |
| `wsp` | cd to the `*_Personal` / `*-Personal` sibling |
| `wspu` | cd to `public/github.com` in the organised tree, else the `*_Public` / `*-Public` sibling |
| `ws37` `ws42` `wsmb` `wsmd` | cd to `src/github.com/<owner>` for 37metrics / dimension42ai / martybytes / moleculardesigns |
| `wsar` | cd to `archive/github.com` |
| `wsj [query]` | fuzzy-jump to any repo in any root (fzf; falls back to a filtered menu) |
| `wsloc` | cd to the local (machine-disk) root — `$LOCAL_WORKSPACE_DIR` if set, else `~/LocalWorkspace` |
| `wsw` | cd to the work workspace — `$WORK_WORKSPACE_DIR` if set, else the `*_Work` / `*-Work` sibling |
| `wsw --set [dir]` | write `WORK_WORKSPACE_DIR` into `~/.zshrc.local` / `profile.local.ps1` (default: current dir) |
| `wsw --show` | print the resolved work workspace without changing directory |
| `db` / `dbx` | cd to Dropbox — `$DROPBOX_DIR` if set, else Dropbox's own `info.json`, else the platform candidates |
| `z dirname` | zoxide — jump to any directory you've visited, from anywhere |
| `zi` | zoxide interactive picker when there are multiple matches |
| `zoxide-prune` | drop dead paths from zoxide's database (pwsh) |

## Where the root comes from, and how to change it

Resolution order, evaluated at **call time** (not shell startup — `~/.zshrc.local` is
sourced at the *end* of `.zshrc`, so anything resolved earlier would miss it):

1. `$WORKSPACE_DIR` from the environment
2. the `export WORKSPACE_DIR=` line in `~/.zshrc.local` (`$env:WORKSPACE_DIR` in
   `profile.local.ps1`), which is what puts it in the environment for a new shell
3. the first existing autodetect probe: `~/Documents/Workspace`, `~/workspace`,
   `~/Workspace` — pwsh probes `C:\DATA\Workspace`, `~\workspace`,
   `~\Documents\Workspace`

   **On WSL the Windows workspace is not probed.** `/mnt/c/DATA/Workspace` used to be
   FIRST, so `ws` landed there over drvfs no matter what existed in `$HOME`. A WSL
   install keeps its files on the Linux filesystem; set `WORKSPACE_DIR` in
   `~/.zshrc.local` if you want the Windows one anyway.

### The local root

Some repos cannot live on the main root. A workspace on a mounted data volume is the
usual reason: if that mount is ever missing — `nofail` in fstab makes that silent — the
path still exists as a bare mountpoint and the tree under it is empty. A dotfiles repo
stowed into `$HOME` does not survive that; every link into it dangles, and nothing says
so until the next login.

So there is a **second** root, on the machine's own disk, in the same
`<root>/src/github.com/<owner>/<repo>` shape: `$LOCAL_WORKSPACE_DIR` if set, else
`~/LocalWorkspace` when it exists. It is a second root and not a fourth autodetect
candidate — a machine can have both, and most have only the main one.

`wsj`, `ws37`/`ws42`/`wsmb`/`wsmd` and `wsloc` search it; the main root is searched
first, so nothing about a single-root machine changes. In `wsj`'s picker a row from the
main root stays relative (`src/github.com/o/repo`) and a row from any other root is
absolute with `~` (`~/LocalWorkspace/src/github.com/o/dots`), so the row's first
character says which root it came from — otherwise the same relative path under two
roots would be a coin flip.

**`wso` deliberately does not touch it.** `wso migrate` moves repos *into* the organised
main tree, which for a stowed dotfiles repo is the exact breakage above, arriving
non-interactively. The local root is dropped from the scan even when
`TS_WS_EXTRA_ROOTS` names it: that variable means "legacy root, empty this into the
tree", which is the opposite of what this root is for.

The root is deliberately **not** a chezmoi setting. It has to be readable by a machine
that never runs chezmoi, and changeable without an apply. `ws --show` and
`tstack workspace` both report which of the three layers actually won, which is the only
way to explain a save that appears to do nothing — a shell that exported the old value at
startup keeps winning until you start a new one.

| Command | What it does |
|---|---|
| `tstack workspace` | the root, the layer it came from, and repo counts per tier |
| `tstack workspace set <path>` | pin it; moves nothing |
| `tstack workspace set <path> --move` | pin it and relocate the tree |
| `tstack workspace reset` | drop the pin; go back to autodetect |

`ws --set` and `tstack workspace set` are the same writer — `ws` runs the command and
then exports the path it prints, which is why it takes effect in the shell you typed it
in while the bare command needs a new one. A child process cannot change its parent's
environment; that is the whole reason `ws` stays a shell function.

### Moving the tree

`wso migrate` refuses a cross-volume move on purpose: copy-then-delete can half-finish,
and a partly copied repo whose original is already gone is the worst outcome available.
Moving the *root* is the one case where crossing a volume is the entire point — a
workspace outgrowing its disk — so `--move` buys the same safety differently:

1. **Preflight**, which refuses for a reason it names: destination exists and is not
   empty, not enough free space, your shell is standing inside the tree, the
   terminal-stack runtime clone is inside it, or **symlinks elsewhere in `$HOME`
   point into the tree**.
2. **Copy**, preserving hardlinks (`rsync -aHAX`) — git object stores and worktrees use
   them.
3. **Verify** independently, with a second rsync pass that reports anything still
   different. A failure stops here with the original intact.
4. **Only then** offer to remove the original, behind a confirm (`--yes` or `TS_WS_YES=1`
   to skip, `--keep-source` to decline).

Nothing is unlinked before step 4, so an interruption at any earlier point leaves the
original complete. Uncommitted work, stashes, reflogs and untracked files all survive,
because the copy is of the directory and not a re-clone.

### Symlinks pointing into the workspace

A dotfiles repo living in the workspace and stowed into `$HOME` is the usual reason,
and it is the one failure here that is invisible until your next login. On the machine
this guard was written for, 26 links pointed into the workspace — the Quickshell bar,
Hyprland's config, `~/.ssh/config`, `~/.config/git/config`, `~/.claude/CLAUDE.md`. They
are relative links rooted at `$HOME`, so moving the tree dangles every one of them and
nothing says so at the time. (That repo has since moved to the local root above, which
is the durable fix; this guard is for every machine that has not done that yet.)

`--move` therefore refuses, counts them, and — when the targets share a `<repo>/stow/`
ancestor — prints the exact `stow -R` line for the packages it found. The way through is
`--keep-source`, which is what the flag is for:

```sh
tstack workspace set /new/path --move --keep-source
cd /new/path/<...>/your-dotfiles
stow -R --no-folding -d stow -t "$HOME" <packages>
find ~ -maxdepth 4 -xtype l          # must print nothing
rm -rf /old/path                     # only now
```

The originals stay in place while the links are repointed, so **no link is ever broken**
— not for a second. `--allow-inbound-symlinks` moves anyway, for the case where you know
the links are disposable.

A root on a filesystem that `$HOME` is not on gets one warning worth reading: if that
mount is ever missing — `nofail` in fstab makes that silent — the path still exists as a
bare mountpoint, and `ws` lands in an empty tree with no error.

`wsp`/`wspu`/`wsw` derive from that root by suffix, underscore first then dash — so
`Workspace_Work` and `Workspace-Work` both resolve. When the work tree lives somewhere
unrelated to the main workspace, `wsw --set /path/to/work` records it in the per-machine
override file (backing the file up first) and takes effect immediately.

`db` resolves in the same call-time, override-first style. It reads Dropbox's own
`info.json` (`~/.dropbox/`, `~/.config/dropbox/`, `%LOCALAPPDATA%\Dropbox\`) before guessing
at paths, because that file is the only thing that gets a relocated folder, a Business
account, or two linked accounts right; a `personal` root wins over a `business` one. The
fallbacks are `~/Library/CloudStorage/Dropbox` (macOS Ventura and later), `~/Dropbox`
(Linux, older macOS, Windows), then the `(Personal)` / `(Business)` variants. Under WSL it
looks at the Windows side via `/mnt/c/Users/<you>/`, since that is where the real store is.
Set `DROPBOX_DIR` in `~/.zshrc.local` / `profile.local.ps1` to override.

`ws37`/`ws42`/`wsmb`/`wsmd`/`wsar`/`wsj` address the organised tree that `wso` builds —
see `doc common/workspace-org`. They fall back to the archive tier when an owner has no
live `src/` directory, so they keep working as repos move between tiers, and (apart from
`wsar`, whose tier is a main-root one) on to the local root when the owner is not in the
main one at all. `wspu` prefers
the new `public/` tier and only falls back to the old `*_Public` sibling root, so it
behaves correctly before, during and after a migration.
