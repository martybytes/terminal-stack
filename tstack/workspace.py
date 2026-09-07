"""The workspace root: where it is, how to change it, and how to move the tree.

WHY THIS IS NOT A CHEZMOI [data] KEY

`docs/decisions.md` "Why $WORKSPACE_DIR + call-time resolution" rejects
templating the root, and all three reasons still hold: a template needs
`chezmoi apply` to change while an env var is live on the next prompt; the
rsync `dot-push` flow ships a rendered `.zshrc` to machines that never run
chezmoi; and `~/.zshrc.local` is sourced at the END of `.zshrc`, so anything
resolved at startup runs before the override exists.

There is a fourth reason now that this is settable at runtime rather than only
at install: `store.set` writes `key = "<value>"` into TOML with no escaping, so
`schema.Setting.validate` refuses any text value containing a backslash. A
Windows workspace path could never be a [data] key at all.

So the store stays what it has always been -- one `export WORKSPACE_DIR=` line
in `~/.zshrc.local`, or one `$env:WORKSPACE_DIR =` line in `profile.local.ps1`.
This module is the only thing in the Python tree that writes it, and it emits
the same line the installer does so the two can find and replace each other's
output.

WHY MOVING ACROSS VOLUMES IS SAFE HERE AND NOT IN `wso migrate`

`wso migrate` refuses a cross-volume move because copy-then-delete can
half-finish, and a partially copied repo whose original is already unlinked is
the worst outcome available (`docs/decisions.md` "Why the migration moves
rather than re-clones"). Relocating the ROOT is the one case where crossing a
volume is the entire point -- moving a workspace to a bigger disk -- so the
safety is bought a different way instead of by refusing:

  1. preflight, which refuses for a reason it can name
  2. copy, preserving hardlinks (git object stores use them)
  3. VERIFY independently, and stop if anything differs
  4. only then offer to remove the original, behind a confirm

Nothing is unlinked until step 4, so an interrupted move at any earlier point
leaves the original untouched and complete.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import paths, proc
from . import platform as plat

Say = Callable[[str], None]

# Where an override is persisted, per shell. Both are per-machine and untracked;
# neither is a chezmoi target. See dot_zshrc.local.example and
# windows/Documents/PowerShell/profile.local.ps1.example.
POSIX_LINE = 'export WORKSPACE_DIR="{path}"'
WINDOWS_LINE = "$env:WORKSPACE_DIR = '{path}'"

# The autodetect probe order, mirrored from the four shell resolvers. This is a
# READ-ONLY mirror: `_ts_workspace` (dot_zshrc), `ts_ws_root` (_workspace.sh),
# `Get-TsWorkspace` ($PROFILE) and `Get-TsWsRoot` (_workspace.ps1) remain
# authoritative for `ws` itself, because resolution has to happen at call time
# in the shell. Python only needs to REPORT what they would pick.
#
# The two lists differ in more than separators and always have: pwsh probes
# `~/workspace` before `~/Documents/Workspace` and POSIX probes them the other
# way round. Preserved rather than harmonised -- a machine whose root is
# currently found by one order would silently move if this "fixed" it.
# /mnt/c/DATA/Workspace was the first POSIX candidate and is gone: on WSL it
# meant `ws` resolved to the Windows workspace over drvfs regardless of $HOME.
# WORKSPACE_DIR still points there deliberately for anyone who wants it.
POSIX_CANDIDATES = (
    "~/Documents/Workspace",
    "~/workspace",
    "~/Workspace",
)
WINDOWS_CANDIDATES = (
    "C:/DATA/Workspace",
    "~/workspace",
    "~/Documents/Workspace",
)

# Flag sets to try, best first, with what dropping to it costs.
#
# `-aHAX` is what you want and is NOT portable: macOS ships openrsync, which
# rejects the ACL and xattr flags outright, and older macOS shipped rsync 2.6.9.
# A hard-coded `-aHAX` therefore failed the whole copy on macOS -- caught by CI,
# not by review. Each rung is attempted in turn; rsync is restartable, so a
# retry over a partial copy just finishes it.
#
# -H is the one worth announcing when it goes: git object stores and worktrees
# hardlink, so losing it inflates the copy and breaks `git worktree`.
RSYNC_LADDER: tuple[tuple[list[str], str], ...] = (
    (["-aHAX"], ""),
    (["-aH"], "ACLs or extended attributes"),
    (["-a"], "hardlinks, ACLs or extended attributes"),
)

# Where a value came from, most specific first. Reported rather than inferred:
# "the root is /mnt/data/Workspace" and "the root is /mnt/data/Workspace
# BECAUSE an env var says so and the file says something else" are different
# facts, and only the second explains why an edit had no effect.
ENV = "env"
OVERRIDE = "zshrc.local"
AUTODETECT = "autodetect"
UNSET = "unset"


@dataclass(frozen=True)
class Resolved:
    """The active root and the layer that won."""

    path: Path | None
    source: str

    @property
    def display(self) -> str:
        return str(self.path) if self.path else "(none found)"


def _windows() -> bool:
    return plat.kind() == plat.WINDOWS


def rc_path() -> Path:
    """The per-machine shell RC that carries the override."""
    if _windows():
        return Path.home() / "Documents" / "PowerShell" / "profile.local.ps1"
    return Path.home() / ".zshrc.local"


def candidates() -> tuple[Path, ...]:
    """The autodetect probes, expanded. Skips any that cannot be expanded.

    `expanduser()` raises RuntimeError when there is no home to expand against
    -- no HOME on POSIX, no USERPROFILE on Windows. Rare, but this runs on every
    `tstack ui` mount, and a settings dashboard that cannot open because one
    probe path could not be spelled is a worse failure than a missing probe.
    """
    raw = WINDOWS_CANDIDATES if _windows() else POSIX_CANDIDATES
    out = []
    for c in raw:
        try:
            out.append(Path(c).expanduser())
        except RuntimeError:
            continue
    return tuple(out)


def read_override() -> Path | None:
    """The path the RC file pins, or None when it pins nothing.

    Matched loosely on purpose: the installer writes `export WORKSPACE_DIR="x"`
    with no backup, `wsw --set`-style writers use zsh `%q` quoting, and a user
    may have typed it by hand with single quotes or none. All of them are the
    same setting and all of them must be found, or a "change the root" command
    appends a second line that the first one shadows.
    """
    rc = rc_path()
    try:
        text = rc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found = None
    for line in text.splitlines():
        value = _override_value(line)
        if value is not None:
            found = value  # last one wins, exactly as the shell would
    return Path(found).expanduser() if found else None


def _override_value(line: str) -> str | None:
    """The path a single RC line sets, or None when it sets nothing."""
    stripped = line.strip()
    if _windows():
        head, sep, tail = stripped.partition("=")
        if not sep or head.strip().lower() != "$env:workspace_dir":
            return None
    else:
        if not stripped.startswith("export"):
            return None
        rest = stripped[len("export") :].lstrip()
        head, sep, tail = rest.partition("=")
        if not sep or head.strip() != "WORKSPACE_DIR":
            return None
    value = tail.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value or None


def is_override_line(line: str) -> bool:
    return _override_value(line) is not None


def resolve() -> Resolved:
    """The active root and why, in the order the shell resolvers use."""
    env = os.environ.get("WORKSPACE_DIR")
    if env:
        return Resolved(Path(env).expanduser(), ENV)
    pinned = read_override()
    if pinned:
        return Resolved(pinned, OVERRIDE)
    for candidate in candidates():
        if candidate.is_dir():
            return Resolved(candidate, AUTODETECT)
    return Resolved(None, UNSET)


def env_shadows_file() -> bool:
    """True when $WORKSPACE_DIR is winning over a DIFFERENT saved value.

    This is the one way a save appears to do nothing: the file is correct, the
    shell that ran the command exported something else at startup, and the next
    `ws` still goes to the old place.
    """
    env = os.environ.get("WORKSPACE_DIR")
    pinned = read_override()
    if not env or not pinned:
        return False
    return Path(env).expanduser() != pinned


# ----------------------------------------------------------------- writing ----


def backup_path(target: Path, today: str | None = None) -> Path:
    """`<file>.bak.YYYYMMDD`, then `.1`, `.2` -- never clobber a same-day backup.

    The repo-wide convention (ARCHITECTURE.md "Backup discipline"). The
    installer's writer skips the backup entirely; this one does not, because a
    command you can run any number of times will eventually be run by mistake.
    """
    stamp = today or date.today().strftime("%Y%m%d")
    candidate = target.with_name(f"{target.name}.bak.{stamp}")
    n = 1
    while candidate.exists():
        candidate = target.with_name(f"{target.name}.bak.{stamp}.{n}")
        n += 1
    return candidate


def _write_rc(lines: list[str], say: Say) -> None:
    """Replace the RC atomically, backing up whatever was there."""
    rc = rc_path()
    rc.parent.mkdir(parents=True, exist_ok=True)
    if rc.exists():
        backup = backup_path(rc)
        shutil.copy2(rc, backup)
        say(f"backup: {backup}")
    tmp = rc.with_name(f"{rc.name}.tstack.{os.getpid()}")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, rc)


def _rc_lines() -> list[str]:
    rc = rc_path()
    if rc.exists():
        return rc.read_text(encoding="utf-8", errors="replace").splitlines()
    header = (
        "# Per-machine pwsh overrides -- not synced by the stack."
        if _windows()
        else "# Per-machine zsh overrides -- not tracked by chezmoi."
    )
    return [header]


def write_override(path: Path, say: Say = print) -> Path:
    """Pin the root in the RC file. Returns the absolute path that was written."""
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()
    pin = (WINDOWS_LINE if _windows() else POSIX_LINE).format(path=resolved)
    kept = [line for line in _rc_lines() if not is_override_line(line)]
    _write_rc([*kept, pin], say)
    say(f"{rc_path()}: {pin}")
    return resolved


def clear_override(say: Say = print) -> bool:
    """Drop the pin so autodetect decides again. False when there was none."""
    lines = _rc_lines()
    kept = [line for line in lines if not is_override_line(line)]
    if len(kept) == len(lines):
        return False
    _write_rc(kept, say)
    return True


# --------------------------------------------------------------- relocating ----


def same_volume(a: Path, b: Path) -> bool:
    """Do these two live on one filesystem? Compares the nearest existing dirs."""
    try:
        return _device(a) == _device(b)
    except OSError:
        return False


def _device(path: Path) -> int:
    probe = path
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return probe.stat().st_dev


def dir_size(path: Path) -> int:
    """Bytes on disk under `path`, following no symlinks."""
    total = 0
    for root, dirs, files in os.walk(path, onerror=lambda _e: None):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(root, d))]
        for name in files:
            full = os.path.join(root, name)
            try:
                if not os.path.islink(full):
                    total += os.lstat(full).st_size
            except OSError:
                continue
    return total


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except (ValueError, OSError):
        return False
    return True


# Directories that never hold a config symlink and can be very large. Walking
# them is the difference between an instant check and one nobody waits for.
_SKIP_DIRS = frozenset(
    {".cache", ".git", "node_modules", ".venv", "venv", "__pycache__", ".npm", ".rustup"}
)

# How deep to look for a link into the tree. Four covers the real shapes --
# `.config/elephant/x.toml`, `.config/environment.d/x.conf`, `bin/ssh-load` --
# and keeps this from becoming a full home-directory crawl.
_SYMLINK_DEPTH = 4


def inbound_symlinks(source: Path, home: Path | None = None) -> list[Path]:
    """Symlinks in $HOME that resolve INTO `source`, and would dangle if it moved.

    The case this exists for: a dotfiles repo living in the workspace and stowed
    into $HOME. On the machine this was written for, 26 links pointed into the
    tree -- the Quickshell bar, Hyprland's config, ~/.ssh/config, ~/.claude/CLAUDE.md
    -- all of them relative and rooted at $HOME, so a move dangles every one and
    the damage shows up at the next login rather than at move time.

    Nothing else in preflight looks outward like this: every other refusal is a
    fact about the two directories. This one is a fact about the rest of the
    machine, which is exactly why it was missed.
    """
    root = home or Path.home()
    try:
        target = source.resolve()
    except OSError:
        return []
    found: list[Path] = []
    for current, dirs, files in os.walk(root, followlinks=False, onerror=lambda _e: None):
        here = Path(current)
        try:
            depth = len(here.relative_to(root).parts)
        except ValueError:
            continue
        # Every entry, symlinked directories included -- os.walk files them under
        # `dirs`, and `dirs` is about to be pruned for descent. Read before pruning
        # or a symlinked directory pointing into the tree is never examined.
        for name in (*dirs, *files):
            link = here / name
            try:
                if link.is_symlink() and link.resolve().is_relative_to(target):
                    found.append(link)
            except (OSError, ValueError):
                continue
        # Prune AFTER looking. The source tree is full of links that point into
        # itself and none of them is what this is for; the rest is noise or depth.
        dirs[:] = [
            d
            for d in dirs
            if d not in _SKIP_DIRS
            and depth < _SYMLINK_DEPTH - 1
            and not (here / d).is_symlink()
            and not _is_within(here / d, source)
        ]
    return sorted(set(found))


def stow_package_root(links: list[Path]) -> Path | None:
    """The dotfiles repo behind these links, when they came from GNU stow.

    Stow's layout is `<repo>/stow/<package>/<path under $HOME>`, so the targets
    share a `.../stow` ancestor. Recognising it is what turns "26 links would
    break" into the one command that repairs them.
    """
    roots = set()
    for link in links:
        try:
            parts = link.resolve().parts
        except OSError:
            continue
        if "stow" in parts:
            roots.add(Path(*parts[: parts.index("stow")]))
    return roots.pop() if len(roots) == 1 else None


def preflight(
    source: Path,
    dest: Path,
    *,
    keep_source: bool = False,
    allow_inbound_symlinks: bool = False,
) -> list[str]:
    """Everything that makes this move a bad idea, phrased for a person.

    An empty list means go. Each entry names the fix, because "refused" without
    one just moves the problem to the next command the user has to guess at.

    `keep_source` is not merely informational: with the original left in place,
    a symlink pointing into it still resolves, so that refusal becomes a warning
    the caller prints instead.
    """
    problems: list[str] = []

    if not source.is_dir():
        problems.append(f"{source} is not a directory; there is nothing to move")
        return problems
    if dest.exists() and source.resolve() == dest.resolve():
        problems.append("source and destination are the same directory")
        return problems
    if _is_within(dest, source):
        problems.append(f"{dest} is inside {source}; moving a tree into itself cannot terminate")
        return problems

    if dest.exists():
        if not dest.is_dir():
            problems.append(f"{dest} exists and is not a directory")
        elif any(dest.iterdir()):
            problems.append(
                f"{dest} already exists and is not empty; move or remove it first, "
                f"or pick a path that does not exist yet"
            )
    elif not dest.parent.is_dir():
        problems.append(f"{dest.parent} does not exist; create it first")

    probe = dest if dest.exists() else dest.parent
    if probe.is_dir() and not os.access(probe, os.W_OK):
        problems.append(f"{probe} is not writable by you")

    # Space, with headroom: a copy that fills the disk is a copy that has to be
    # cleaned up by hand, and du and the filesystem never quite agree.
    if probe.is_dir():
        need = dir_size(source)
        try:
            free = shutil.disk_usage(probe).free
        except OSError:
            free = None
        if free is not None and free < need * 1.1:
            problems.append(
                f"{probe} has {free // (1 << 20)} MiB free; the tree needs about "
                f"{int(need * 1.1) // (1 << 20)} MiB including headroom"
            )

    # A shell standing inside the tree survives the copy and then finds itself
    # in a directory that no longer exists. Easy to hit: a dev clone lives here.
    cwd = Path.cwd()
    if _is_within(cwd, source):
        problems.append(
            f"your shell is inside {source} (at {cwd}); cd somewhere else first, "
            f"or the move leaves this shell in a deleted directory"
        )

    # Relocating the runtime clone out from under the install is the failure
    # docs/decisions.md "Runtime clone location" records. It lives in app-data
    # precisely so this cannot happen, so finding one here means a pinned or
    # legacy-path clone -- worth stopping for.
    try:
        runtime = paths.resolve_source_dir()
    except paths.CloneNotFound:
        runtime = None
    except Exception:  # a broken clone probe must not block a move
        runtime = None
    if runtime and _is_within(Path(runtime), source):
        problems.append(
            f"the terminal-stack runtime clone is inside {source} (at {runtime}); "
            f"moving it orphans the install -- relocate it with `tstack doctor --repair` first"
        )

    # Only a move that REMOVES the original can dangle these. With the source
    # left in place every link into it still resolves, so it is the caller's job
    # to remind rather than this one's to refuse.
    if not allow_inbound_symlinks and not keep_source:
        links = inbound_symlinks(source)
        if links:
            problems.append(inbound_symlink_report(links, source, dest, keep_source=False))

    return problems


def inbound_symlink_report(links: list[Path], source: Path, dest: Path, keep_source: bool) -> str:
    """Why those links matter, and the exact command that repairs them."""
    home = Path.home()
    shown = ", ".join(str(link.relative_to(home)) for link in links[:4] if _is_within(link, home))
    more = f" and {len(links) - 4} more" if len(links) > 4 else ""
    lines = [
        f"{len(links)} symlink(s) under {home} point INTO {source} ({shown}{more}). "
        f"Moving it dangles every one of them, and the breakage shows up at your "
        f"next login rather than now."
    ]
    stow_root = stow_package_root(links)
    if stow_root:
        moved = dest / stow_root.relative_to(source) if _is_within(stow_root, source) else stow_root
        packages = " ".join(sorted(p.name for p in (stow_root / "stow").iterdir() if p.is_dir()))
        lines.append(
            f"    Those come from GNU stow. Re-run `--move --keep-source`, then from "
            f"{moved} run:\n"
            f'      stow -R --no-folding -d stow -t "$HOME" {packages}\n'
            f"    verify with `find ~ -maxdepth 4 -xtype l`, and only then remove the original."
        )
    else:
        lines.append(
            "    Re-run with --keep-source so the originals stay while you repoint them, "
            "or --allow-inbound-symlinks to move anyway."
        )
    if keep_source:
        lines.append("    (--keep-source is set, so nothing dangles until you remove it.)")
    return "\n".join(lines)


def warnings_for(dest: Path) -> list[str]:
    """Things worth saying that are not reasons to refuse.

    The one that matters is a root on a filesystem that home is not on. `/home`
    being its own btrfs subvolume is not that -- it mounts with the root
    filesystem or the machine does not boot -- so the test is "a different
    mount from $HOME's", not "not /".
    """
    notes: list[str] = []
    mount = _mount_point(dest)
    home_mount = _mount_point(Path.home())
    if mount and home_mount and mount != home_mount:
        detail = (
            " fstab mounts it `nofail`, so a failure to mount is silent."
            if _fstab_nofail(mount)
            else ""
        )
        notes.append(
            f"{dest} is on a separate filesystem mounted at {mount}.{detail} If that "
            f"mount is ever missing, the path still exists as a bare mountpoint and "
            f"`ws` lands in an empty tree with no error."
        )
    return notes


def _fstab_nofail(mount: Path) -> bool:
    """Does fstab mount this point with `nofail`? Best effort; False when unknown."""
    try:
        text = Path("/etc/fstab").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        row = line.split("#", 1)[0].split()
        if len(row) >= 4 and row[1] == str(mount):
            return "nofail" in row[3].split(",")
    return False


def _mount_point(path: Path) -> Path | None:
    probe = path if path.exists() else path.parent
    if not probe.exists():
        return None
    try:
        dev = probe.stat().st_dev
        while probe != probe.parent and probe.parent.stat().st_dev == dev:
            probe = probe.parent
    except OSError:
        return None
    return probe


def relocate(source: Path, dest: Path, say: Say = print) -> bool:
    """Put the tree at `dest`. Leaves `source` in place when it had to copy."""
    if same_volume(source, dest):
        # One filesystem: a rename is atomic and preserves everything inside it
        # for free -- uncommitted work, stashes, reflogs, untracked scratch.
        say(f"same filesystem: renaming {source} -> {dest}")
        if dest.exists():
            dest.rmdir()  # preflight proved it is an empty directory
        os.rename(source, dest)
        return True

    say(f"different filesystems: copying {source} -> {dest}")
    dest.mkdir(parents=True, exist_ok=True)
    if shutil.which("rsync"):
        for flags, lost in RSYNC_LADDER:
            argv = ["rsync", *flags]
            # A live progress meter is worth having for a big tree and is pure
            # noise in a log, and it redraws with \r either way -- so it is
            # asked for only when someone is actually watching. `--progress` and
            # not `--info=progress2`: the latter needs rsync 3.1+, and the whole
            # point of this ladder is the rsync macOS ships.
            if sys.stdout.isatty():
                argv.append("--progress")
            argv += [f"{source}/", f"{dest}/"]
            if _run(argv) == 0:
                if lost:
                    say(f"note: this rsync does not support {lost}; copied without it")
                return True
            say(f"rsync {' '.join(flags)} failed; retrying with a smaller flag set")
        say("every rsync flag set failed; falling back to cp -a")
    else:
        say("rsync not found; falling back to cp -a")
    say("cp -a does not preserve hardlinks, so a git object store may grow")
    return _run(["cp", "-a", f"{source}/.", str(dest)]) == 0


def verify(source: Path, dest: Path, say: Say = print) -> bool:
    """Is `dest` a faithful copy of `source`? Independently, after the fact.

    An rsync dry run reports anything it WOULD still transfer, which is exactly
    "what is not identical yet". Without rsync, fall back to comparing the file
    count and total bytes -- weaker, but it still catches a truncated copy.
    """
    if shutil.which("rsync"):
        out = None
        for flags, _lost in RSYNC_LADDER:
            # Same ladder as the copy, and for the same reason: openrsync
            # rejects -A and -X. The FIRST version of this checked only
            # `out is None`, so on macOS rsync exited non-zero with empty
            # stdout, "no differences" was inferred from no output, and verify
            # returned TRUE for a copy it had not looked at -- the one result
            # this function must never produce, because a confirmed delete is
            # on the other side of it.
            attempt = proc.capture(
                ["rsync", *flags, "-n", "--itemize-changes", "--delete", f"{source}/", f"{dest}/"]
            )
            if attempt is not None and attempt.returncode == 0:
                out = attempt
                break
        if out is None:
            say("could not run rsync to verify; refusing to call this copy good")
            return False
        # Directory mtimes settle after their contents are written, so rsync
        # reports the destination's own directories as needing a touch. Those
        # start with `.d` (a directory whose attributes differ) and are not a
        # difference in content; anything else is.
        diffs = [
            row
            for row in out.stdout.splitlines()
            if row.strip() and not row.startswith(".d") and not row.startswith("cd")
        ]
        if diffs:
            say(f"verification found {len(diffs)} difference(s):")
            for line in diffs[:20]:
                say(f"   {line}")
            return False
        return True

    src_files, src_bytes = _count(source)
    dst_files, dst_bytes = _count(dest)
    if (src_files, src_bytes) != (dst_files, dst_bytes):
        say(
            f"verification failed: {src_files} files / {src_bytes} bytes at the source, "
            f"{dst_files} / {dst_bytes} at the destination"
        )
        return False
    return True


def _count(path: Path) -> tuple[int, int]:
    files = 0
    total = 0
    for root, _dirs, names in os.walk(path, onerror=lambda _e: None):
        for name in names:
            full = os.path.join(root, name)
            try:
                total += os.lstat(full).st_size
            except OSError:
                continue
            files += 1
    return files, total


def _run(argv: list[str]) -> int:
    """Run a child with its output attached to the terminal (progress matters)."""
    try:
        return subprocess.run(argv, check=False).returncode
    except (OSError, subprocess.SubprocessError):
        return 1
