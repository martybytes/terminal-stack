"""The managed Ghostty config: where it lives, what it should say, and `off`.

ONE implementation of what used to be three. `bootstrap/ts-config.sh` covered
macOS and the WSL view of the Windows side; `$PROFILE`'s
`Set-TerminalStackConfig` covered native Windows; and the themeMode -> theme
mapping existed a third time in each sync script. Three copies of a mapping that
must agree, or `tstack config ghostty diff` reports a phantom change -- which is
why `tests/test_agent_tools.py` had to pin them against each other.

The two shell entry points now hand off here, the way `tstack config mux` and
`tstack config wezterm` already do. The sync scripts keep their own copy of the
mapping because they run where Python may not be, and the test that compares them
stays.

WHY `off` REMOVES FILES ITSELF

It is a real revert, not merely "stop managing". Doing it through
`.chezmoiignore` or a sync-side delete would run that deletion on EVERY machine,
and would wipe a hand-written Ghostty config on a box that never opted in. This
removes for the machine you ran it on, because that is the machine that asked.
`run_before_20-backup-ghostty.sh` takes the backup that makes `off` a restore.
"""

from __future__ import annotations

import difflib
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

DARWIN = "darwin"
WINDOWS = "windows"

# The marker the rendered config carries. A config without it is someone's own
# file, and saying so is the difference between "apply will update this" and
# "apply will replace this".
OURS = "managed by terminal-stack"

# Command-neutral: both `tstack ghostty` and `tstack config ghostty` reach here,
# and naming only one of them was already misleading when the shells split this
# three ways. "macOS or WSL" was the old bash implementation's reach, not the
# feature's -- native Windows was the pwsh half.
UNSUPPORTED = """ghostty: macOS, Windows and WSL only. Ghostty runs on macOS, and on
  Windows as noctty/winghostty; this stack's native-Linux hosts are
  headless, so there is no GUI here to configure."""


@dataclass(frozen=True)
class Target:
    """Which Ghostty this machine configures, and where its files are."""

    kind: str
    directory: Path

    @property
    def config(self) -> Path:
        return self.directory / "config"

    @property
    def theme(self) -> Path:
        return self.directory / "themes" / "vs-code-light-modern"


def target() -> Target | None:
    """The Ghostty this machine owns, or None when there is not one.

    `%LOCALAPPDATA%\\ghostty\\`, never the app-named directory. noctty reads both
    its own `%LOCALAPPDATA%\\<appname>\\config.ghostty` and the
    upstream-compatible path; `<appname>` is `winghostty` today and `noctty` the
    day the rename ships, so only this one survives the upgrade.

    WSL resolves to the same Windows path, which is the point: a combined machine
    has one Ghostty, and it is the Windows one.
    """
    kind = plat.kind()
    if kind == plat.MACOS:
        return Target(DARWIN, Path.home() / ".config" / "ghostty")
    if kind in (plat.WINDOWS, plat.WSL):
        local = plat.local_app_data()
        if local is None:
            return None
        return Target(WINDOWS, local / "ghostty")
    return None


def setting() -> str:
    value = store.get("ghosttyConfig", "on")
    return value if value in ("on", "off") else "on"


def theme_tokens(mode: str) -> tuple[str, str]:
    """`themeMode` -> the two values the Windows template's tokens take.

    Ghostty's config format has no conditionals and the Windows mirror gets token
    substitution rather than Go templates, so this mapping is resolved before the
    file is written -- exactly as `tmuxPrefixResolved` is.

    `follow` MUST be a split `dark:...,light:...` theme. That form is what tracks
    the OS, so it cannot be expressed by pinning `window-theme`; and an explicit
    mode cannot be expressed by a split theme. The two directives are not
    interchangeable, which is why both are substituted rather than one derived
    from the other.
    """
    if mode == "light":
        return ("vs-code-light-modern", "light")
    if mode == "follow":
        return ("dark:Catppuccin Mocha,light:vs-code-light-modern", "auto")
    return ("Catppuccin Mocha", "dark")


def render_windows(source: Path) -> str | None:
    """The Windows template as the sync would write it.

    Blind token substitution, which is safe for exactly these two: both values
    are single-line and neither can contain a `#`. The sync's own no-substitution
    rule is about the multi-line `__CC_TTS_*__` blocks and does not apply here.
    """
    template = source / "windows" / "AppData" / "Local" / "ghostty" / "config.tmpl"
    try:
        body = template.read_text(encoding="utf-8")
    except OSError:
        return None
    theme, window = theme_tokens(store.get("themeMode", "dark"))
    return body.replace("__GHOSTTY_THEME__", theme).replace("__GHOSTTY_WINDOW_THEME__", window)


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
    """The Ghostty executable this machine would use, or None.

    On the Windows side both names are probed, post-rename first: `winghostty`
    today, `noctty` once the rename ships.
    """
    spot = target()
    if spot is None:
        return None
    if spot.kind == DARWIN:
        return shutil.which("ghostty")
    if plat.kind() == plat.WINDOWS:
        for name in ("noctty", "winghostty"):
            found = shutil.which(name)
            if found:
                return found
        return None
    # WSL, reaching the Windows install through interop.
    for candidate in (
        "/mnt/c/Program Files/noctty/noctty.com",
        "/mnt/c/Program Files/winghostty/winghostty.com",
    ):
        path = Path(candidate)
        if path.is_file():
            return str(path)
    return None


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
    say(f"ghostty config: {setting()}   (target: {spot.kind})")

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
        if spot.kind == DARWIN:
            say("  ghostty: not installed (tstack config wizard installs the cask)")
        else:
            say("  noctty/winghostty: not installed")
            say("    releases: https://github.com/amanthanvi/noctty/releases")
        return 0

    got = _run([exe, "--version"])
    version = got.stdout.splitlines()[0].strip() if got and got.stdout.strip() else "unknown"
    say(f"  {Path(exe).stem}: {version}")

    if spot.kind != DARWIN:
        # NO validate step, deliberately. `+validate-config` fails with
        # FileTooBig on winghostty 1.3.123 even for a 14-byte config, and
        # `+show-config` reports nothing at all for an unknown key or a bad
        # value -- so unlike macOS there is no honest syntax gate to run here.
        # Printing "validate: ok" would be a lie.
        say("  validate: unavailable on this build (see docs/decisions.md)")
        return 0
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
    spot = target()
    if spot is None:
        return _unsupported(say)
    if spot.kind == DARWIN:
        # chezmoi owns both files here, so its own diff is the honest answer.
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
            # chezmoi prints nothing when there is nothing to change, and so did
            # the shell this replaces. "What would an apply do?" deserves an
            # answer rather than silence, and the Windows branch already gives
            # one.
            say("ghostty config: up to date")
        return 0

    # The Windows copy is NOT chezmoi-managed -- `windows/**` is chezmoi-ignored
    # and mirrored by the sync -- so the comparison is against the rendered
    # template rather than against chezmoi's idea of the target.
    want = render_windows(source)
    if want is None:
        say("ghostty config: the Windows template is missing from the clone.")
        return 1
    _diff_one(spot.config, want, "ghostty config", say)
    theme_src = source / "windows" / "AppData" / "Local" / "ghostty" / "themes"
    theme_src = theme_src / "vs-code-light-modern"
    try:
        _diff_one(spot.theme, theme_src.read_text(encoding="utf-8"), "ghostty theme", say)
    except OSError:
        say("ghostty theme: the source theme is missing from the clone.")
    return 0


def _diff_one(live: Path, want: str, label: str, say: Say) -> None:
    if not live.exists():
        say(f"{label}: {live} would be created")
        return
    have = live.read_text(encoding="utf-8", errors="replace")
    if have == want:
        say(f"{label}: up to date")
        return
    say(f"{label}: {live} differs from the rendered template -")
    for line in difflib.unified_diff(
        have.splitlines(), want.splitlines(), "deployed", "rendered", lineterm=""
    ):
        say(f"  {line}")


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


def reload_hint(spot: Target) -> str:
    if spot.kind == DARWIN:
        return "Reload Ghostty with Cmd+Shift+, (or restart it)."
    return "Reload with Ctrl+Shift+, (or restart it)."


def _unsupported(say: Say) -> int:
    for line in UNSUPPORTED.splitlines():
        say(line)
    return 1
