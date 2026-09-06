"""Clone resolution.

Single port of logic that existed in three places, all of which carried a
"keep in sync with the others" comment:

    bootstrap/_cleanup.sh   ts_clone_candidates / ts_is_dev_clone   (the master)
    dot_zshrc               _ts_clone_candidates / _ts_clones / _ts_src
    $PROFILE                Get-TsCloneCandidates / Get-TsClones / Resolve-TsSourceDir

Three behaviours are load-bearing and each has an entry in docs/decisions.md.
They are preserved exactly:

1.  CANDIDATE ORDER IS PRIORITY: pin > canonical > legacy. Ranking by newest
    commit was deliberately removed -- it would prefer a dev clone the moment you
    commit to it, updating the tree you are developing in.

2.  DEV CLONES ARE INVISIBLE unless they ARE the pin. A checkout at a wso
    workspace tier path is where you work; auto-resolution must never select it,
    or `tstack update` would operate on your working tree.

3.  THE TWO PIN SOURCES ARE NOT EQUIVALENT WHEN DANGLING. An explicit
    --source-dir is typed per call, so a bad one is a mistake worth failing on.
    TERMINAL_STACK_DIR arrives from ~/.zshrc.local or profile.local.ps1 in every
    session, so a stale line there would otherwise brick every command on the
    machine with no way out. It degrades to the candidate search instead.

One deliberate divergence from dot_zshrc's _ts_src: when `chezmoi source-path`
fails, this falls through to the candidate search rather than returning an error.
_ts_src dead-ended there, which contradicts rule 3's own reasoning and leaves a
machine with a held chezmoi state lock unable to run anything.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import platform as plat
from . import proc

# A dev clone sits at a wso workspace tier path: <tier>/<host>/<owner>/<repo>,
# where the host segment must contain a dot. That dot is what makes the pattern
# safe by construction -- ~/.local/share/... does not match (the leading dot in
# ".local" breaks the /local/ bound) and .../AppData/Local/terminal-stack/stack
# does not match (no dot in any host position).
_DEV_CLONE_RE = re.compile(r"/(src|public|archive|local|scratch)/[^/]+\.[^/]+/[^/]+/[^/]+/?$")


@dataclass(frozen=True)
class Clone:
    path: Path
    origin: str
    short: str  # "<abbrev sha> <subject>"


def is_dev_clone(path: Path | str) -> bool:
    """True for a checkout at a workspace tier path."""
    return bool(_DEV_CLONE_RE.search(str(path).replace("\\", "/")))


def canonical_clone_dir() -> Path | None:
    """The one location `tstack update` expects the runtime clone to be.

    Windows and WSL share it via %LOCALAPPDATA%\\terminal-stack\\stack, which WSL
    reaches through /mnt/c. Native Linux and macOS use the XDG data home. Pins
    are only for non-canonical locations.
    """
    if plat.kind() in (plat.WINDOWS, plat.WSL):
        base = plat.local_app_data()
        return base / "terminal-stack" / "stack" if base else None
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "terminal-stack"


def clone_candidates() -> list[Path]:
    """Every place a clone might be, highest priority first, deduplicated."""
    home = Path.home()
    out: list[Path] = []

    pin = os.environ.get("TERMINAL_STACK_DIR")
    if pin:
        out.append(Path(pin))

    canon = canonical_clone_dir()
    if canon:
        out.append(canon)

    out += [
        home / "code" / "terminal-stack",
        home / "terminal-stack",
        home / "Workspace" / "terminal-stack",
        home / "workspace" / "terminal-stack",
        home / "Documents" / "Workspace" / "terminal-stack",
        home / ".local" / "share" / "chezmoi",
    ]

    if plat.kind() == plat.WSL:
        out += (
            sorted(Path("/mnt/c/Users").glob("*/terminal-stack"))
            if Path("/mnt/c/Users").is_dir()
            else []
        )
        out.append(Path("/mnt/c/DATA/Workspace/terminal-stack"))
    elif plat.kind() == plat.WINDOWS:
        out.append(Path("C:/DATA/Workspace/terminal-stack"))

    seen: set[str] = set()
    unique: list[Path] = []
    for p in out:
        key = os.path.normcase(str(p))
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def _git(cwd: Path, *args: str) -> str | None:
    out = proc.capture(["git", "-C", str(cwd), *args], timeout=15)
    if out is None or out.returncode != 0:
        return None
    return out.stdout.strip()


def is_stack_clone(path: Path) -> bool:
    """True when <path> is a git repo whose origin names the project.

    The name test is necessary but NOT sufficient to *pick* a clone: a stale
    install under ~/terminal-stack from an old account still matches. That is why
    callers report ambiguity rather than silently choosing.
    """
    if not (path / ".git").exists():
        return False
    origin = _git(path, "config", "--get", "remote.origin.url")
    return origin is not None and "terminal-stack" in origin.lower()


def dev_clone_at(start: Path | None = None) -> Path | None:
    """The terminal-stack DEV clone the caller is standing in, or None.

    resolve_source_dir() deliberately never returns a dev clone -- dev trees are
    invisible to resolution so that `tstack update` cannot pull one. That is
    right for deployment and wrong for any check about *developing*, which is
    why check_git_hooks keyed off the resolved clone and could never once fire.

    Discovery is the git toplevel of the working directory, not a candidate
    search: the question is "am I in a dev clone right now", and the answer is
    wherever the developer actually is.
    """
    here = Path.cwd() if start is None else Path(start)
    top = _git(here, "rev-parse", "--show-toplevel")
    if not top:
        return None
    path = Path(top)
    if not is_dev_clone(path) or not is_stack_clone(path):
        return None
    return path


def clones() -> list[Clone]:
    """Every terminal-stack clone on this machine, in priority order."""
    pin = os.environ.get("TERMINAL_STACK_DIR")
    pin_key = os.path.normcase(pin) if pin else None
    found: list[Clone] = []
    for path in clone_candidates():
        if not (path / ".git").exists():
            continue
        if is_dev_clone(path) and os.path.normcase(str(path)) != pin_key:
            continue
        origin = _git(path, "config", "--get", "remote.origin.url")
        if not origin or "terminal-stack" not in origin.lower():
            continue
        found.append(
            Clone(
                path=path,
                origin=origin,
                short=_git(path, "log", "-1", "--format=%h %s") or "",
            )
        )
    return found


class CloneNotFound(RuntimeError):
    """No usable clone, and the caller cannot proceed without one."""


def resolve_source_dir(
    explicit: str | Path | None = None,
    *,
    warn: Callable[[str], None] | None = None,
) -> Path:
    """The clone to operate on.

    `warn` is called with human-readable strings for the degraded paths (stale
    pin, multiple clones). Callers pass a printer; --json callers pass a
    collector so diagnostics never contaminate stdout.
    """
    say = warn if warn is not None else (lambda _msg: None)

    if explicit:
        path = Path(explicit)
        if not (path / ".git").exists():
            # Typed per call, so a bad one is a mistake worth failing on.
            raise CloneNotFound(f"no terminal-stack clone at {path}")
        return path

    stale_pin = False
    pin = os.environ.get("TERMINAL_STACK_DIR")
    if pin:
        if (Path(pin) / ".git").exists():
            return Path(pin)
        say(f"stale TERMINAL_STACK_DIR: no clone at {pin} -- searching the usual locations.")
        say(
            "  Clear it with 'tstack doctor --repair', or remove the line from your local override."
        )
        stale_pin = True

    # chezmoi is authoritative where it exists. A failure here (state lock held by
    # another instance, say) is not a missing clone, so fall through rather than
    # dead-ending -- see the module docstring.
    chezmoi = plat.find_chezmoi()
    if chezmoi:
        out = proc.capture([chezmoi, "source-path"], timeout=30)
        if out is not None and out.returncode == 0:
            src = Path(out.stdout.strip())
            if str(src) and (src / ".git").exists():
                return src

    found = clones()
    if not found:
        raise CloneNotFound("no terminal-stack clone found. Re-run the install one-liner.")

    if stale_pin:
        say(f"  using {found[0].path}")
    if len(found) > 1:
        say(f"{len(found)} terminal-stack clones found; using the highest-priority location:")
        for c in found:
            mark = "->" if c.path == found[0].path else "  "
            say(f"  {mark} {c.path}")
            say(f"       {c.origin}  |  {c.short}")
        say("  Consolidate with 'tstack doctor --repair', or pin one.")
    return found[0].path


def clone_version(src: Path) -> dict:
    """HEAD, branch and dirtiness of a clone.

    This is what `tstack --version` reports. The stack updates by `git pull`, so
    the clone's HEAD is the only version number that means anything.
    """
    dirty = _git(src, "status", "--porcelain")
    return {
        "path": str(src),
        "sha": _git(src, "rev-parse", "HEAD") or "",
        "short": _git(src, "rev-parse", "--short", "HEAD") or "",
        "branch": _git(src, "rev-parse", "--abbrev-ref", "HEAD") or "",
        "subject": _git(src, "log", "-1", "--format=%s") or "",
        "dirty": bool(dirty),
    }
