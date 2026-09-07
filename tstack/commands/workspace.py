"""`tstack workspace` - the workspace root, and moving the tree that lives at it.

A thin entry point over `tstack/workspace.py`, the split `tstack ghostty` and
`tstack herdr` already have. Top-level rather than a `tstack config` verb for
the reason `mux` and `wezterm` are: it is reached from `tstack config
workspace` in either shell, so there is one implementation instead of a bash
one and a pwsh one drifting apart.

STDOUT IS A CONTRACT HERE

On a successful `set`, stdout is the canonical absolute path and nothing else.
`ws --set` reads it and exports it into the calling shell, which is the one
thing this process structurally cannot do for itself -- a child cannot change
its parent's environment. Everything else this command says goes to stderr.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .. import workspace

HELP = """tstack workspace - the workspace root, and moving the tree that lives at it.

Usage:
  tstack workspace [show]          the root, the layer it came from, what is in it
  tstack workspace set <path>      pin the root; does not move anything
  tstack workspace set <path> --move   pin it, and relocate the tree there
  tstack workspace move <path>     the same as `set <path> --move`
  tstack workspace reset           drop the pin; go back to autodetect

  --keep-source   after a verified copy, leave the original where it is
  --yes           do not ask before removing the original (or TS_WS_YES=1)
  --dry-run       say what would happen; change nothing
  --allow-inbound-symlinks   move even when symlinks point into the tree
  -h, --help      this help

The root is NOT a chezmoi setting. It is one `export WORKSPACE_DIR=` line in
~/.zshrc.local (`$env:WORKSPACE_DIR` in profile.local.ps1 on Windows), because
it has to be readable by a shell that never ran chezmoi and changeable without
an apply. `ws --set` is the same thing from inside a shell, and takes effect
immediately; this command needs a new shell.

A cross-volume move copies, verifies the copy independently, and only then
offers to remove the original. Nothing is unlinked before that.

It also refuses when symlinks elsewhere in $HOME point INTO the tree -- a
dotfiles repo stowed from your workspace is the usual reason -- because moving
it dangles them and you find out at your next login. `--keep-source` is the way
through: the originals stay while you repoint the links, and you remove them
once `find ~ -maxdepth 4 -xtype l` is quiet."""

VERBS = ("show", "set", "move", "reset")


def _err(message: str) -> None:
    print(message, file=sys.stderr)


def _tier_counts(root: Path) -> list[tuple[str, int]]:
    """Repos per tier, for the `show` report. Cheap: one listing per tier."""
    counts = []
    for tier in ("src", "public", "archive", "local", "scratch"):
        base = root / tier
        if not base.is_dir():
            continue
        n = sum(1 for p in base.rglob(".git") if p.parent.is_dir())
        counts.append((tier, n))
    return counts


def show() -> int:
    resolved = workspace.resolve()
    _err(f"root      {resolved.display}")
    _err(f"from      {resolved.source}")
    _err(f"rc file   {workspace.rc_path()}")
    pinned = workspace.read_override()
    if pinned:
        _err(f"pinned    {pinned}")
    else:
        _err("pinned    (nothing; autodetect decides)")

    if workspace.env_shadows_file():
        _err("")
        _err("NOTE: $WORKSPACE_DIR in this shell disagrees with the saved value. The")
        _err("      shell wins until you start a new one, so a save can look inert.")

    if resolved.path is None:
        _err("")
        _err("Nothing found. Probe order on this platform:")
        for candidate in workspace.candidates():
            _err(f"   {candidate}")
        _err("")
        _err("Set one with: tstack workspace set <path>")
        return 0

    if not resolved.path.is_dir():
        _err("")
        _err(f"WARNING: {resolved.path} does not exist. `ws` will fail until it does.")
        return 0

    counts = _tier_counts(resolved.path)
    if counts:
        _err("")
        for tier, n in counts:
            _err(f"   {tier:<10} {n} repo(s)")
    for note in workspace.warnings_for(resolved.path):
        _err("")
        _err(f"NOTE: {note}")
    return 0


def reset(dry_run: bool) -> int:
    if dry_run:
        _err("==> would drop the WORKSPACE_DIR pin and fall back to autodetect")
        return 0
    if not workspace.clear_override(_err):
        _err("Nothing pinned; autodetect already decides.")
        return 0
    after = workspace.resolve()
    _err(f"pin removed. Autodetect now gives: {after.display}")
    _err("Open a new shell (or `unset WORKSPACE_DIR`) for this one to follow.")
    return 0


def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes or os.environ.get("TS_WS_YES") == "1":
        return True
    if not sys.stdin.isatty():
        _err(f"{question} -- not a terminal, assuming no.")
        return False
    try:
        return input(f"{question} [y/N]: ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        _err("")
        return False


def set_root(
    target: str,
    *,
    move: bool,
    keep_source: bool,
    assume_yes: bool,
    dry_run: bool,
    allow_inbound_symlinks: bool = False,
) -> int:
    dest = Path(target).expanduser()
    if not dest.is_absolute():
        dest = (Path.cwd() / dest).resolve()

    if not move:
        if dry_run:
            _err(f"==> would pin the workspace root to {dest}")
            return 0
        written = workspace.write_override(dest, _err)
        if not written.is_dir():
            _err(f"NOTE: {written} does not exist yet. `ws` will warn until it does.")
        for note in workspace.warnings_for(written):
            _err(f"NOTE: {note}")
        _err("Open a new shell for this to take effect (or use `ws --set`).")
        print(written)
        return 0

    current = workspace.resolve()
    if current.path is None:
        _err("tstack workspace: no current workspace to move; use `set` without --move.")
        return 1
    source = current.path
    already = source.resolve() == dest.resolve() if dest.exists() else source == dest
    if already:
        _err(f"Already at {dest}; nothing to move.")
        return 0

    problems = workspace.preflight(
        source,
        dest,
        keep_source=keep_source,
        allow_inbound_symlinks=allow_inbound_symlinks,
    )
    if problems:
        _err(f"tstack workspace: cannot move {source} -> {dest}")
        for problem in problems:
            _err(f"  - {problem}")
        return 1

    # With the original left in place a link into it still resolves, so this is
    # a reminder rather than a refusal -- but repointing them is the step people
    # forget, and forgetting it is only visible at the next login.
    if keep_source and not allow_inbound_symlinks:
        links = workspace.inbound_symlinks(source)
        if links:
            _err(workspace.inbound_symlink_report(links, source, dest, keep_source=True))

    size_mb = workspace.dir_size(source) // (1 << 20)
    _err(f"==> move {source} -> {dest}  ({size_mb} MiB)")
    for note in workspace.warnings_for(dest):
        _err(f"NOTE: {note}")
    if dry_run:
        _err("==> [dry-run] nothing copied, nothing pinned.")
        return 0

    # Decided BEFORE the move, because afterwards the source is gone and the
    # answer to "did this copy or rename?" -- which is what decides whether a
    # verify pass and a removal prompt are needed -- is no longer observable.
    copied = not workspace.same_volume(source, dest)
    if not workspace.relocate(source, dest, _err):
        _err("tstack workspace: the copy failed; the original is untouched.")
        return 1

    if copied:
        _err("==> verifying the copy")
        if not workspace.verify(source, dest, _err):
            _err("")
            _err("tstack workspace: VERIFICATION FAILED. Nothing was removed and the")
            _err(f"original at {source} is intact. The partial copy is at {dest}.")
            return 1
        _err("==> verified: the copy is complete")

    written = workspace.write_override(dest, _err)

    if copied and not keep_source:
        _err("")
        if _confirm(f"Remove the original at {source}?", assume_yes):
            shutil.rmtree(source, ignore_errors=False)
            _err(f"removed {source}")
        else:
            _err(f"kept {source}. Remove it by hand once you are happy: rm -rf {source}")
    elif copied:
        _err(f"kept {source} (--keep-source). Remove it by hand when you are happy.")

    _err("Open a new shell for this to take effect (or use `ws --set`).")
    print(written)
    return 0


def main(argv: list[str]) -> int:
    # -h before anything else, and before any probe: help has to work on a
    # machine where nothing else does. Same ordering rule as tstack/commands/mux.py.
    if argv and argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0

    move = False
    keep_source = False
    assume_yes = False
    dry_run = False
    allow_inbound_symlinks = False
    positional: list[str] = []
    for item in argv:
        if item in ("-h", "--help", "help"):
            print(HELP)
            return 0
        if item == "--move":
            move = True
        elif item == "--keep-source":
            keep_source = True
        elif item in ("-y", "--yes"):
            assume_yes = True
        elif item == "--dry-run":
            dry_run = True
        elif item == "--allow-inbound-symlinks":
            allow_inbound_symlinks = True
        elif item.startswith("-"):
            _err(f"tstack workspace: unknown flag '{item}' (try: tstack workspace --help)")
            return 2
        else:
            positional.append(item)

    verb = positional[0] if positional else "show"
    if verb not in VERBS:
        _err(f"tstack workspace: unknown action '{verb}' (try: {', '.join(VERBS)})")
        return 2
    rest = positional[1:]

    if verb == "show":
        if rest:
            _err(f"tstack workspace show: unexpected argument '{rest[0]}'")
            return 2
        return show()
    if verb == "reset":
        if rest:
            _err(f"tstack workspace reset: unexpected argument '{rest[0]}'")
            return 2
        return reset(dry_run)

    if not rest:
        _err(f"tstack workspace {verb}: needs a path (try: tstack workspace --help)")
        return 2
    if len(rest) > 1:
        _err(f"tstack workspace {verb}: unexpected argument '{rest[1]}'")
        return 2
    return set_root(
        rest[0],
        move=move or verb == "move",
        keep_source=keep_source,
        assume_yes=assume_yes,
        dry_run=dry_run,
        allow_inbound_symlinks=allow_inbound_symlinks,
    )
