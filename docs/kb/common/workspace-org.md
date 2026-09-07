# Workspace organizer (`wso`)

| Command | What it does |
|---|---|
| `wso status` | every repo that is dirty, unpushed, detached or remote-less (read-only) |
| `wso status --dirty` | same, suppressing the clean ones |
| `wso status --org 37metrics` | limit to one owner |
| `wso plan` | preview the migration — what would move where, and what is blocked |
| `wso plan --org 37metrics` | preview just that owner's moves |
| `wso migrate` | execute the plan (moves only; re-prints it and asks first) |
| `wso migrate --fix-remotes` | also apply owner renames and normalise your orgs to SSH |
| `wso migrate --org 37metrics` | execute only that owner's moves |
| `wso sync` | fast-forward-only update of every repo already here |
| `wso sync --org martybytes` | fast-forward just that owner's repos |
| `wso synceverything` | `sync`, then clone every org repo missing from this machine |
| `wso synceverything --org martybytes` | the same, for one owner only |
| `wso archive` | interactive: asks a day threshold, shows a checklist, confirms |
| `wso archive --days 180` | skip the threshold prompt |
| `wso archive --org 37metrics` | only consider that owner's repos |
| `wso unarchive` | fzf picker over `archive/`, multi-select, restore |
| `wso unarchive --update` | restore, then fast-forward each restored repo |
| `wso unarchive calibra` | restore by name |
| `wso unarchive --org moleculardesigns` | restore a whole owner |
| `wso unarchive --undo-last` | reverse the most recent archive run |
| `wso get <url\|owner/repo>` | clone straight to the derived path |
| `wso orphans` | repos with no remote — they exist on this disk only |
| `wso orphans --push` | create a private remote for each, one at a time |
| `wso orphans --org 37metrics` | only ones parked at that owner's path (see below) |
| `wso identity` | write this machine's per-owner git identity rules |
| `wso doctor` | tools, config, git rules and tree health |

Jump shortcuts (shell functions, because a child process cannot change your directory):

| Command | Goes to |
|---|---|
| `ws` | the workspace root |
| `ws37` | `src/github.com/37metrics` |
| `ws42` | `src/github.com/dimension42ai` |
| `wsmb` | `src/github.com/martybytes` |
| `wsmd` | `src/github.com/moleculardesigns` |
| `wspu` | `public/github.com` (falls back to the old `*_Public` sibling) |
| `wsar` | `archive/github.com` |
| `wsj` | fuzzy-jump to any repo anywhere in the tree |
| `wsj ironcl` | pre-filter the picker |

## What `--org` matches

Every bulk verb takes `--org <owner>`: `status`, `plan`, `migrate`, `sync`,
`synceverything`, `archive`, `unarchive` and `orphans`. It is one implementation
(`ts_ws_org_match` / `Test-TsWsOrgMatch`), and it matches the **owner segment** of
`<tier>/<host>/<owner>/<repo>` — not any segment anywhere in the path.

That distinction is the whole point, and the earlier per-verb substring test got three
things wrong without ever erroring:

- `--org github.com` matched every repo in the tree, because the host is a path segment
  too.
- A *repo* named like an owner matched, so `--org martybytes` also caught
  `someone-else/martybytes`.
- `--org martsamp77` matched nothing after a migration. The tree carries the canonical
  owner; the flag carried whatever you typed. The rename map from `workspace.conf` is
  now applied to both sides, so the old name and the new one select the same repos.

Two verbs are deliberately different:

- **`plan` and `migrate` filter the DESTINATION**, not the folder a repo is sitting in.
  A misfiled clone's whole point is that its current directory does not say who owns it,
  so `wso plan --org 37metrics` has to show the clone in a folder called `flipoff` whose
  origin is `37metrics/rotari`. Rows with no destination — blocked repos, and anything
  with an unparseable origin — survive every filter, because they are the rows that need
  a human and hiding them behind a flag is how they get forgotten.
- **`orphans` has no owner to match.** A repo with no remote is exactly a repo nothing
  derives an owner for, and it normally sits in `local/`, which has no owner segment at
  all. `--org` there only ever matches one parked at an owner path — a clone whose origin
  was stripped — and the empty result names the filter so it does not read as "you have
  none".

`synceverything --org X` also rejects an owner that is not one of yours, and it does so
*before* the sync rather than after fast-forwarding every repo on the machine.

## The layout

```
<workspace>/
  src/github.com/<owner>/<repo>       owners you control
  public/github.com/<owner>/<repo>    third-party clones
  archive/github.com/<owner>/<repo>   cold repos; same shape as src/
  local/<repo>                        no remote yet
  scratch/<dir>                       not a git repo at all
```

Every path is **derived from the repo's `origin` remote**, never from the folder it
happens to be sitting in. That is the whole point, and it is what catches the cases you
would otherwise never notice: a folder called `flipoff` whose origin is
`37metrics/rotari` files itself under `rotari`; `sheet-sense` and `sheet_sense` are
recognised as one repo with two local spellings; a clone still pointing at a renamed
GitHub account lands under the new name.

You never type these paths. `wsj` is what makes the depth free.

## Why `archive/` is a parallel tree, not a folder inside each org

Archiving is a path-preserving move: `src/github.com/x/y` becomes
`archive/github.com/x/y`, and restoring is the same move backwards. Nothing about the
derivation changes, so `wso plan` and `wsj` keep working across both tiers.

A `#archive` or `_archive` folder nested inside each org directory was the obvious
alternative and is worse in two ways. It breaks the path-equals-remote rule that makes
the tree machine-generatable. And punctuation prefixes do not sort the way people
expect: under the default `en_US.UTF-8` collation glibc ignores punctuation, so
`_archive` interleaves with the `a` repos and only sorts first under `LC_COLLATE=C`.
Across a fleet of machines and three operating systems, any scheme whose behaviour
depends on locale will behave differently on different machines.

## Archiving is per-machine, deliberately

Nothing about an archive decision is written back to the terminal-stack repo. A repo
being cold on the laptop and hot on the desktop is correct — it is local cache state,
not a fact about the repo. Each machine's `archive/` reflects that machine's habits.

## What "cold" means

`wso archive` ranks by the **later of** the last commit date and the newest modification
time among the repo's immediate children — the same reasoning as `lsr` (see
`doc common/files-disk`). A directory's own timestamp only moves when entries are added
or removed, so a repo you edited all afternoon would otherwise look untouched.

`.git` is excluded from that scan. It has to be: `git fetch`, `git gc` and even
`git status` add and remove files under `.git`, so counting it would make every repo
look like you touched it today.

## The safety gates

`wso archive` refuses to move a repo that has any of:

- uncommitted changes
- untracked files that are not ignored
- unpushed commits **on any branch**, not just the one you are standing on
- stash entries
- a detached HEAD
- no remote at all

Held repos are shown with the reason and cannot be ticked. The check runs twice — once
when the list is built, and again immediately before each move, because the checklist
may have been open for a while.

`wso migrate` has its own gates. It refuses when the destination already exists, which
is what protects two diverged clones of the same repo from being merged into one path.
It refuses a cross-volume move, because that silently degrades from an atomic rename to
a copy. It never deletes anything: the old roots are left in place for you to remove by
hand once you have verified. And moves are renames, so uncommitted work, stashes,
reflog and untracked scratch files all survive intact.

It also refuses to move **terminal-stack's own runtime clone**, listing it as
`runtime — not migrated`. That gate is deliberately blunt: it blocks *any* un-tiered
terminal-stack clone found at the workspace root, not merely the one that currently
resolves as active. The narrower version — compare each candidate against the resolved
runtime clone — switched itself off whenever resolution came back empty, which is
precisely the broken state (a pin pointing at nothing, a clone at a legacy path) where
the guard is needed. It cost a real install: a clone at `<workspace>/terminal-stack`
was migrated to `src/github.com/martybytes/terminal-stack`, a path no resolver knows,
and the machinery went with it. A genuine dev clone already lives at a tier path and is
therefore never a scan candidate, so nothing legitimate is caught. Relocating the
runtime clone is `tstack doctor --repair`'s job — see `doc common/stack`.

Every run that moves anything writes a TSV log, which is what `wso unarchive --undo-last`
reads. Those logs live in `<workspace>/.terminal-stack/workspace-runs/` — inside the
workspace rather than in per-OS state, because they describe the workspace and not the
machine. On a combined Windows + WSL setup both sides drive the same tree, so an archive
run done from PowerShell can be undone from zsh and vice versa. Paths inside the log are
stored relative to the workspace root with forward slashes, which is what makes that work
across the two path conventions.

## Dirty counts are entries, not files

`wso status` reports what `git status --porcelain` reports, and git collapses an
untracked *directory* into a single entry. A repo showing `1 dirty` may hold one
modified file or one untracked folder with hundreds of files in it. The count is a
signal, not an inventory — use `git status` in the repo for the real picture. The
safety gates only care whether the count is zero, so this never affects what gets moved.

## Configuration

The layout map lives in the clone at `bootstrap/workspace.conf` and is tracked, so every
machine agrees. Per-machine overrides go in an untracked twin that is read second and
wins key by key:

- POSIX: `~/.config/terminal-stack/workspace.local.conf`
- Windows: `%LOCALAPPDATA%\terminal-stack\workspace.local.conf`

```
org       37metrics          src
rename    martsamp77         martybytes
set       default_tier       public
set       archive_days       90
set       scheme_own         ssh
set       scheme_public      preserve
set       host_default       github.com
```

`org` maps an owner to a tier. `rename` handles an upstream account rename — GitHub
redirects the old URL, so clones keep working and nothing tells you it happened.

The five `set` keys:

| Key | Default | What it does |
|---|---|---|
| `default_tier` | `public` | tier for any owner with no `org` line |
| `archive_days` | `90` | default staleness threshold for `wso archive` |
| `scheme_own` | `ssh` | remote scheme for the owners listed above |
| `scheme_public` | `preserve` | remote scheme for everyone else |
| `host_default` | `github.com` | host assumed by `wso get owner/repo` and the missing-repo report |

`scheme_own` normalises your own repos to one remote scheme; `scheme_public` is left at
`preserve` because you have no push access to third-party clones and the scheme there is
upstream's business.

## Environment knobs

| Variable | Effect |
|---|---|
| `TS_DRY_RUN=1` | preview only — every verb that writes says what it would do and stops |
| `TS_WS_YES=1` | answer yes to the confirmations (for scripts; think before you use it) |
| `TS_WS_VERBOSE=1` | show per-repo detail that is normally summarised |
| `TS_WS_DAYS` | the `wso archive` threshold, skipping the prompt (`--days` still wins) |
| `TS_WS_EXTRA_ROOTS` | extra legacy roots to include when scanning for repos to migrate |
| `TS_WS_MOVE_RETRIES` | how many times a failed rename is retried (Windows holds directory handles open asynchronously) |
| `WORKSPACE_DIR` | the workspace root itself — see `doc common/workspace-nav` |

## Where the root itself comes from

Everything above is relative to the workspace root, which is **not** part of this file
and not a chezmoi setting. It resolves at call time: `$WORKSPACE_DIR` if set, else the
first existing autodetect candidate. Change it with `ws --set <dir>` or
`tstack workspace set <path>`, and move the tree with `--move`. See
`doc common/workspace-nav`.

## First run on a new machine

```
wso doctor
wso identity
wso plan
wso migrate
```

`wso identity` writes per-owner `user.email` and signing keys as git `includeIf` rules,
so committing inside `src/github.com/moleculardesigns/` uses your work address
automatically and you stop discovering three months later that company commits went up
under a personal one. Those files are per-machine and never enter the source tree.

Read every line of `wso plan` before running `wso migrate`. Anything it lists as blocked
needs a human — usually two diverged clones of the same repo, which is a `git diff`
session, not something a tool should guess at. The exception is
`runtime — not migrated`, which needs nothing from you: it is the stack protecting its
own install, and `tstack doctor --repair` is what moves that clone.
