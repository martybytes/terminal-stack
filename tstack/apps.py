"""The CLI tool catalog, read from `bootstrap/apps.conf`.

There used to be two copies -- `bootstrap/_config.sh` and `bootstrap/_config.ps1`
-- kept in agreement by hand, each carrying the id list, the group membership,
the descriptions and two default sets. Adding a tool meant editing both and
remembering four places in each.

A third reader is what forced the issue: the settings dashboard, the wizard port
and `tstack config apps` all need to know what the catalog contains, and only one
of those is bash. So the catalog is now data, and all three read it.

THE TWO DEFAULT SETS ARE DERIVED, not listed. `classes` says which machine kind
pre-ticks a tool, and `recommended()`/`sysadmin()` are computed from it -- so the
sets cannot drift apart the way two hand-maintained lists did.
"""

from __future__ import annotations

import functools
import sys
from dataclasses import dataclass
from pathlib import Path

from . import paths
from . import platform as plat

CONF_NAME = "bootstrap/apps.conf"

# Which machine class pre-ticks a tool. `none` is offered but never pre-ticked.
BOTH, DEV, SYS, NONE = "both", "dev", "sys", "none"
CLASSES = (BOTH, DEV, SYS, NONE)

DEVELOPER = "developer"
SYSADMIN = "sysadmin"


# Where a tool can actually be installed. "can this platform install it", NOT
# "is it in winget" -- conflating the two is why a Windows box missing
# grok/gemini/pi/cursor-agent was never once told so.
ALL, POSIX, LINUX, WINDOWS = "all", "posix", "linux", "windows"
PLATFORMS = (ALL, POSIX, LINUX, WINDOWS)


@dataclass(frozen=True)
class App:
    id: str
    group: str
    classes: str
    platforms: str
    description: str

    def installable(self, machine: str) -> bool:
        """`machine` is a tstack.platform kind: macos, linux, wsl or windows."""
        if self.platforms == ALL:
            return True
        if self.platforms == WINDOWS:
            return machine == plat.WINDOWS
        if self.platforms == LINUX:
            return machine == plat.LINUX
        # posix: everything with a POSIX package manager. WSL counts -- it has
        # apt, and a tool installed there is a tool you can use.
        return machine in (plat.MACOS, plat.LINUX, plat.WSL)

    def in_class(self, machine: str) -> bool:
        if self.classes == BOTH:
            return True
        if machine == SYSADMIN:
            return self.classes == SYS
        return self.classes == DEV


def parse(text: str, *, strict: bool = True) -> list[App]:
    """Rows in file order.

    `strict` raises on a malformed row, which is what the tests and any
    developer editing the table want. The INSTALLER path passes strict=False and
    skips the row with a warning instead: bash's `ts_apps_load || true` and
    pwsh's reader both shrug at a bad row, and a raise here meant one typo in
    `apps.conf` aborted the whole questionnaire halfway through an install.
    """
    out: list[App] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 4)
        # A malformed row is a bug in the table, not user input. Naming the row
        # matters: a silently dropped tool is exactly the failure this repo keeps
        # being bitten by -- so it is always named, on stderr when not strict.
        problem: str | None = None
        if len(parts) < 5:
            problem = f"expected 5 fields, got {len(parts)}: {raw!r}"
        else:
            app_id, group, classes, platforms, description = parts
            if classes not in CLASSES:
                problem = f"{app_id}: unknown class '{classes}'"
            elif platforms not in PLATFORMS:
                problem = f"{app_id}: unknown platform '{platforms}'"
        if problem is not None:
            if strict:
                raise ValueError(f"{CONF_NAME}: {problem}")
            print(f"!! {CONF_NAME}: skipping row -- {problem}", file=sys.stderr)
            continue
        out.append(App(app_id, group, classes, platforms, description.strip()))
    return out


def conf_path() -> Path | None:
    try:
        return paths.resolve_source_dir() / CONF_NAME
    except paths.CloneNotFound:
        return None


@functools.lru_cache(maxsize=1)
def catalog() -> tuple[App, ...]:
    """Every tool, in file order -- which is picker order, grouped."""
    path = conf_path()
    if path is None or not path.is_file():
        return ()
    return tuple(parse(path.read_text(encoding="utf-8"), strict=False))


def clear_cache() -> None:
    catalog.cache_clear()


def ids(machine: str | None = None) -> list[str]:
    """Every tool, or only those this machine can install.

    The platform filter is the whole reason a Windows picker never offered tmux
    and a macOS one never nagged about nvtop -- behaviour that used to live in
    two separate hand-maintained id lists.
    """
    if machine is None:
        return [a.id for a in catalog()]
    return [a.id for a in catalog() if a.installable(machine)]


def installable(app_id: str, machine: str) -> bool:
    app = by_id(app_id)
    return app.installable(machine) if app else False


def by_id(app_id: str) -> App | None:
    for app in catalog():
        if app.id == app_id:
            return app
    return None


def groups() -> list[str]:
    """Group names in file order, deduplicated."""
    return list(dict.fromkeys(a.group for a in catalog()))


def in_group(group: str, machine: str | None = None) -> list[App]:
    return [
        a for a in catalog() if a.group == group and (machine is None or a.installable(machine))
    ]


def for_class(machine: str) -> list[str]:
    """The ids pre-ticked for a machine kind.

    Neither set is a subset of the other: a server's default kit includes the
    monitors and network tools that are merely optional on a laptop, and drops
    the runtimes and agent CLIs entirely.
    """
    return [a.id for a in catalog() if a.in_class(machine)]


def recommended() -> list[str]:
    return for_class(DEVELOPER)


def sysadmin() -> list[str]:
    return for_class(SYSADMIN)


def optional() -> list[str]:
    """Everything not in the developer default set -- what `all` adds to
    `recommended`, which is the wording the picker uses."""
    default = set(recommended())
    return [a.id for a in catalog() if a.id not in default]


def saved_class(saved: list[str]) -> str:
    """Which class a machine LOOKS like, from what it has chosen.

    Inferred rather than stored, and from a predicate that cannot drift: does the
    selection contain anything outside the sysadmin set? Without this, a box set
    up as a server is told on every `tstack update` that it is missing fnm,
    poetry and six agent CLIs it deliberately declined.

    A machine that has never been configured reports `developer`, which keeps the
    previous behaviour rather than guessing.
    """
    if not saved:
        return DEVELOPER
    known = set(sysadmin())
    return DEVELOPER if any(app_id not in known for app_id in saved) else SYSADMIN
