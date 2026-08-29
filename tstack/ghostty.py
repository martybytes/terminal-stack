"""The managed Ghostty config: where it lives, what it should say, and `off`.

ONE implementation of what used to be three, and now one PLATFORM as well. Both
shell entry points hand off here, the way `tstack config mux` and
`tstack config wezterm` already do.

MACOS ONLY, DELIBERATELY

This stack briefly configured Ghostty on Windows too, through noctty. That target
is gone: the Windows mirror file, the themeMode -> theme token mapping each sync
carried, and the interop binary probe went with it. Native-Linux hosts here are
headless and never had a GUI to configure. So there is exactly one target, and
`target()` returning None is a refusal rather than a branch.

WHY `off` REMOVES FILES ITSELF

It is a real revert, not merely "stop managing". Doing it through
`.chezmoiignore` or a sync-side delete would run that deletion on EVERY machine,
and would wipe a hand-written Ghostty config on a box that never opted in. This
removes for the machine you ran it on, because that is the machine that asked.
`run_before_20-backup-ghostty.sh` takes the backup that makes `off` a restore.
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import platform as plat
from . import store

# `say` is the caller's output function and `apply` its post-save step, injected
# so this module never decides how a message is printed or how a machine
# re-renders -- `tstack config` owns both, and on Windows the apply is a
# PowerShell sync rather than `chezmoi apply`.
Say = Callable[[str], None]
Apply = Callable[[], None]

# The marker the rendered config carries. A config without it is someone's own
# file, and saying so is the difference between "apply will update this" and
# "apply will replace this".
OURS = "managed by terminal-stack"

# Command-neutral: both `tstack ghostty` and `tstack config ghostty` reach here,
# and naming only one of them was already misleading when the shells split this
# three ways. "macOS or WSL" was the old bash implementation's reach, not the
# feature's -- native Windows was the pwsh half.
UNSUPPORTED = """ghostty: macOS only. This stack configures no Windows Ghostty, and
  its native-Linux hosts are headless, so there is no GUI here to
  configure."""


@dataclass(frozen=True)
class Target:
    """Where this machine's Ghostty files are.

    No `kind` field: there is one target now. It carried `darwin` vs `windows`
    while the mirror existed, and every branch on it has gone with the mirror.
    """

    directory: Path

    @property
    def config(self) -> Path:
        return self.directory / "config"

    @property
    def theme(self) -> Path:
        return self.directory / "themes" / "vs-code-light-modern"


def target() -> Target | None:
    """The Ghostty this machine owns, or None when there is not one.

    None everywhere but macOS -- including WSL, which used to resolve to the
    Windows install. Callers turn that into the refusal above rather than
    guessing at a path no Ghostty on this machine would read.
    """
    if plat.kind() == plat.MACOS:
        return Target(Path.home() / ".config" / "ghostty")
    return None


def setting() -> str:
    value = store.get("ghosttyConfig", "on")
    return value if value in ("on", "off") else "on"


def newest_backup(directory: Path) -> Path | None:
    """The most recent `config.bak.*`, by name.

    By NAME, not mtime: the convention is `.bak.YYYYMMDD` with `.1`, `.2` on a
    same-day re-run, so lexical order is chronological order and a `cp -p`
    (which preserves the ORIGINAL's mtime) cannot mislead it.
    """
    try:
        backups = sorted(directory.glob("config.bak.*"))
    except OSError:
        return None
    return backups[-1] if backups else None


def is_ours(config: Path) -> bool | None:
    """True when the deployed file is the one this stack renders, None if absent."""
    try:
        head = config.read_text(encoding="utf-8", errors="replace").splitlines()[:20]
    except OSError:
        return None
    return any(OURS in line for line in head)


# ------------------------------------------------------------------- the binary


def binary() -> str | None:
    """The Ghostty executable this machine would use, or None."""
    if target() is None:
        return None
    return shutil.which("ghostty")


def _run(argv: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None


# ----------------------------------------------------------------------- verbs


def status(source: Path, say: Say) -> int:
    spot = target()
    if spot is None:
        return _unsupported(say)
    say(f"ghostty config: {setting()}")

    ours = is_ours(spot.config)
    if ours is None:
        say(f"  {spot.config}  (absent)")
    elif ours:
        say(f"  {spot.config}  (ours)")
    else:
        say(f"  {spot.config}  (NOT ours - apply would replace it; a backup is taken first)")
    if spot.theme.exists():
        say(f"  {spot.theme}  (custom light theme)")
    backup = newest_backup(spot.directory)
    if backup:
        say(f"  newest backup: {backup}")

    exe = binary()
    if exe is None:
        say("  ghostty: not installed (tstack config wizard installs the cask)")
        return 0

    got = _run([exe, "--version"])
    version = got.stdout.splitlines()[0].strip() if got and got.stdout.strip() else "unknown"
    say(f"  {Path(exe).stem}: {version}")

    if not spot.config.exists():
        return 0
    check = _run([exe, "+validate-config", f"--config-file={spot.config}"])
    if check is not None and check.returncode == 0:
        say("  validate: ok")
        return 0
    say("  validate: FAILED -")
    for line in ((check.stdout + check.stderr) if check else "").splitlines():
        say(f"    {line}")
    return 0


def diff(source: Path, say: Say) -> int:
    """What an apply would change. chezmoi owns both files, so its diff is it.

    There is no second route any more. The Windows copy was mirrored by the sync
    rather than managed by chezmoi, so it needed its own rendered-template
    comparison; with that target gone, so is the comparison.
    """
    spot = target()
    if spot is None:
        return _unsupported(say)
    chezmoi = plat.find_chezmoi()
    if not chezmoi:
        say("chezmoi is not installed, so there is nothing to diff against.")
        return 1
    got = subprocess.run(
        [chezmoi, "diff", "--", str(spot.config), str(spot.theme)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if got.stdout.strip():
        print(got.stdout, end="" if got.stdout.endswith("\n") else "\n")
    else:
        # chezmoi prints nothing when there is nothing to change, and so did the
        # shell this replaces. "What would an apply do?" deserves an answer
        # rather than silence.
        say("ghostty config: up to date")
    return 0


def turn_on(source: Path, say: Say, apply: Apply) -> int:
    spot = target()
    if spot is None:
        return _unsupported(say)
    store.set("ghosttyConfig", "on")
    apply()
    say(f"==> ghostty config on. {reload_hint(spot)}")
    return 0


def turn_off(source: Path, say: Say, apply: Apply) -> int:
    """A real revert: restore the newest backup, or remove what we deployed.

    NOT a `.chezmoiremove` rule and not a sync-side delete -- both of those run
    on every machine and would wipe a hand-written config on a box that never
    opted in. This removes for THIS machine, because this machine asked.
    """
    spot = target()
    if spot is None:
        return _unsupported(say)
    store.set("ghosttyConfig", "off")

    backup = newest_backup(spot.directory)
    if backup is not None and backup.is_file():
        spot.config.write_bytes(backup.read_bytes())
        say(f"==> restored {spot.config} from {backup}")
    elif spot.config.exists():
        spot.config.unlink()
        say(f"==> removed {spot.config} (no backup existed; Ghostty uses its defaults)")
    if spot.theme.exists():
        spot.theme.unlink()
        say(f"==> removed {spot.theme}")

    say(f"==> ghostty config off. {reload_hint(spot)}")
    apply()
    return 0


def reload_hint(_spot: Target) -> str:
    return "Reload Ghostty with Cmd+Shift+, (or restart it)."


def _unsupported(say: Say) -> int:
    for line in UNSUPPORTED.splitlines():
        say(line)
    return 1
