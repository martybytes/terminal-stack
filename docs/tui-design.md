# A TUI for terminal-stack — design

Status: **design only.** Nothing here is built or shipped. The prototype is a
separate, later step; see "Phasing" at the end.

## Why

The stack's configuration surface is now ~17k lines of shell and PowerShell
across `bootstrap/`, `dot_zshrc` and `$PROFILE`, and every user-facing menu
exists **twice** — bash and pwsh — under a rule that their rendered output stay
byte-identical, verified by a manual pty diff (`docs/verifying-changes.md` § 3).
That rule is the cost a single binary eventually removes. The surface itself is
also past the point where a flat command list is discoverable: `ts-config` alone
fronts leader/theme/tmux/apps/mux/restore/atuin/ghostty/agents/wezterm/wizard,
and the TTS subtree has **43 `ccTts*` keys**.

The goal is a `ts` TUI that can see and change everything — add, remove, change —
and browse the docs, **with every existing command still working**. The TUI is a
front-end, not a replacement.

## The load-bearing decision: the TUI never writes config itself

**Every mutation shells out to the existing scripts.** Reads go through new
`--json` modes; writes invoke `ts-config`, `ts_data_set`, `ts_save_config` and
friends exactly as a human would.

This is not timidity, it is the repo's own history:

- bash and pwsh are already parallel implementations held together only by a
  byte-identical-menu rule and a manual diff.
- the old Cursor script "drifted into not reproducing its own installed state".
- the two config stores diverging silently removed **all five** Claude TTS hooks
  in a single day, with no error and a diff that looked deliberate.

A Rust reimplementation of `ts_data_set` / `ts_save_config` would be a **third**
store with the same failure mode, and the first bug would be invisible. Shelling
out makes CLI/TUI divergence structurally impossible — which is precisely what
"keep the command lines too" requires. It also means `chezmoi init` (which
regenerates the derived `leaderKey` / `leaderMods` / `tmuxPrefixResolved`) and
`ts_mirror_windows_config` keep happening for free, rather than being two more
things a second implementation must remember.

The cost is process-spawn latency on each write. That is the right trade for a
config editor, where writes are rare and correctness is everything.

## Phase 1 is `--json`, not Rust

Every script today emits `printf`-formatted human text. A TUI over that is
screen-scraping, and every cosmetic change to a status line becomes a parsing
bug.

The in-repo precedent is already built: `bootstrap/tts-daemon/ttsd/settings_schema.py`
is a machine-readable settings schema with a real front-end over it
(`ttsd/webui.py`), including **which config layer won per field** — the exact
thing a config TUI needs to render honestly. Copy that shape for the chezmoi
`[data]` keys.

Add `--json` read models to:

| Command | Emits |
|---|---|
| `ts-config show` | every key, its value, its default, and where it came from |
| `ts-doctor` | one record per check: id, status, message, repair hint |
| `wso status` | one record per repo: path, dirty, unpushed, detached |
| `ts-smb list` | one record per share/mount, with derived liveness |

**These are worth building whether or not the TUI ever exists** — they make the
stack scriptable, and they are what `check-capture.sh`-style external probes
want too.

## Surface the TUI must cover

- `ts-config`: leader, theme, tmux prefix, apps, mux, session restore, atuin,
  ghostty, agents, WezTerm channel, re-run wizard
- the TTS subtree: 43 `ccTts*` keys, engines, voices, templates, daemon, history
- `wso`: status, plan, migrate, archive/unarchive checklists
- `ts-smb`: hosts → shares → probe → browse → mount
- `ts-doctor`: checks and `--repair`
- the `doc` knowledge base

## Distribution: prebuilt binaries only

The repo is **public**, so unauthenticated release downloads work and
`common_install_github_binary` needs no auth change. `common_arch_tag rust`
(added for atuin/yazi) is already the correct arch mapping — cargo-dist projects
name their ARM asset `aarch64`, not `arm64`.

- Build with **cargo-dist** in `.github/workflows` (none exists yet). atuin's own
  `dist-workspace.toml` is the working reference, and it is a ratatui app, so the
  target matrix is already proven.
- A platform with no published asset simply has no TUI and keeps the scripts.

**Why not build on device.** The TTS daemon compiles on-device, but it is
Windows-only, opt-in (`ccTtsDaemon` defaults off), and its Python 3.10+
toolchain is already in the catalog and present on essentially every machine.
Rust is in neither the catalog nor any bootstrap. A toolchain requirement gating
`ts-config` itself is a different proposition from one gating an optional
feature, and `cargo build --release` on every `ts-update` is minutes, not
seconds.

## Fetch UX: offer, never force

`ts-update` detects a newer release and prompts `[y/N]`, mirroring exactly what
it already does for `ts_apps_pending` and `ts_wezterm_update_available`. Plus a
standalone `ts-tui update` for on-demand.

Nothing downloads silently. That would be the only thing in the stack that
changes a machine without asking.

## The version-skew trap

This is the real risk in the release approach and it must be designed for, not
discovered.

`ts-update` is `git pull --ff-only` + `chezmoi apply`. `ts-rollback` is
`git reset --hard <sha>` + `chezmoi apply`. **A separately-fetched binary
participates in neither**, so a rollback leaves a *newer* binary driving *older*
scripts — and since the TUI shells out to those scripts, that is exactly the
configuration most likely to misbehave.

The TTS daemon already solved this and the TUI must copy it wholesale:

- stamp the **git SHA/tag** into the binary at build time (the daemon does this
  in its PyInstaller spec) and expose it as `ts-tui --version`
- `ts-doctor` reports a mismatch between the binary's stamp and the clone's HEAD
- keep a `.previous` artifact beside the installed one
- install as **stage → validate → atomic swap**, restoring `.previous` if the
  final move leaves no binary (`bootstrap/install-tts-daemon.ps1` is the
  reference)
- `ts-rollback` must fetch the binary matching the SHA it rolled back to, or
  refuse and say so

## Two hard runtime rules

- **Never `stat`, `ls` or glob an SMB mountpoint.** A dead FUSE mount blocks
  forever and takes the calling process with it — in a TUI that means a frozen
  render loop with no way out. Liveness comes from the kernel mount table, which
  is why `ts-smb` derives it rather than storing it.
- **`ts-update` and `ts-rollback` are ~140 lines of zsh inside `dot_zshrc`**,
  with no `.sh` file. Shell out to them (`zsh -ic`), do not reimplement. They are
  also *interactive* multi-stage flows with their own prompts, so the TUI must
  hand the terminal over rather than trying to drive them.

## Phasing

1. `--json` read models (useful alone; no Rust)
2. Prototype: the **doc browser** only. It needs no `--json` work —
   `_doc_index`'s `label<TAB>path` output is effectively the doc system's public
   contract and is ~30 lines to reimplement — and a native browser deletes the
   `_doc_edit_bind` fzf-0.42 `become()` compatibility shim outright. It exercises
   list, filter, preview and key handling while risking no config write.
3. Read-only dashboard over the `--json` models
4. Mutations, shelling out
5. cargo-dist release pipeline + `ts-tui update` + the `ts-update` offer

Ratatui **0.30.2** is the current release. `cargo` is not installed on the
development Mac; the prototype needs `rustup` locally, which is deliberately
**not** a catalog addition — no user machine should ever need Rust.
