"""Platform detection and interop helpers.

Replaces the scattered `[ -r /proc/version ] && grep -qi microsoft` checks in
bootstrap/*.sh and the `$IsWindows` branches in bootstrap/*.ps1.

The distinction that matters throughout this stack is not "Windows vs Unix" but
four cases, because WSL is a POSIX environment that owns Windows-side state:

    windows   native pwsh; no chezmoi; config.json is the store
    wsl       POSIX, but /mnt/c exists and chezmoi is authoritative here
    linux     native; the Windows sync hook self-no-ops
    macos     native
"""

from __future__ import annotations

import functools
import os
import shutil
import sys
from pathlib import Path

# proc imports nothing from the package, so this cannot cycle back through here.
from . import proc

WINDOWS = "windows"
WSL = "wsl"
LINUX = "linux"
MACOS = "macos"


@functools.lru_cache(maxsize=1)
def kind() -> str:
    """Which of the four environments this is."""
    if os.name == "nt":
        return WINDOWS
    if sys.platform == "darwin":
        return MACOS
    if is_wsl():
        return WSL
    return LINUX


@functools.lru_cache(maxsize=1)
def is_wsl() -> bool:
    """True inside WSL.

    /proc/version is the probe the whole repo already uses. WSL2 also sets
    WSL_DISTRO_NAME, but that is absent under some service managers, so it is a
    fallback rather than the primary test.
    """
    if os.name == "nt":
        return False
    try:
        if (
            "microsoft"
            in Path("/proc/version").read_text(encoding="utf-8", errors="replace").lower()
        ):
            return True
    except OSError:
        pass
    return bool(os.environ.get("WSL_DISTRO_NAME"))


def is_windows_side() -> bool:
    """True when Windows-side paths (/mnt/c, %LOCALAPPDATA%) are reachable."""
    return kind() in (WINDOWS, WSL)


@functools.lru_cache(maxsize=1)
def windows_username() -> str | None:
    """The Windows account name, or None when there is no Windows side.

    Same two sources the sync hook uses, in the same order: the value the WSL
    bootstrap persisted, then cmd.exe interop. Never hard-coded -- a literal
    username in a source file is a documented regression in this repo.
    """
    if kind() == WINDOWS:
        return os.environ.get("USERNAME") or None
    if kind() != WSL:
        return None
    cmd = Path("/mnt/c/Windows/System32/cmd.exe")
    if not cmd.exists():
        return None
    out = proc.capture([str(cmd), "/c", "echo %USERNAME%"], timeout=10)
    if out is None:
        return None
    name = out.stdout.strip().strip("\r\n")
    return name or None


def local_app_data() -> Path | None:
    """%LOCALAPPDATA% as this process can reach it, or None.

    On WSL this is the /mnt/c view of the Windows path, which is why the stack
    can share one clone and one config.json across both sides.
    """
    if kind() == WINDOWS:
        raw = os.environ.get("LOCALAPPDATA")
        return Path(raw) if raw else None
    if kind() == WSL:
        user = windows_username()
        if not user:
            return None
        return Path(f"/mnt/c/Users/{user}/AppData/Local")
    return None


def state_dir() -> Path:
    """Where rollback-sha and friends live.

    Windows keeps it beside config.json; POSIX follows XDG. Matches _TS_STATE in
    dot_zshrc and the pwsh twin in $PROFILE.
    """
    if kind() == WINDOWS:
        base = local_app_data()
        if base:
            return base / "terminal-stack"
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "terminal-stack"


def find_chezmoi() -> str | None:
    """The chezmoi binary, or None.

    TERMINAL_STACK_CHEZMOI wins (testing and odd installs), then the ~/.local/bin
    copy the bootstraps install, then PATH. Port of _ts_chezmoi in dot_zshrc.

    None is a normal answer: a Windows-standalone install never runs chezmoi, and
    the config store falls back to the config.json mirror there.
    """
    pinned = os.environ.get("TERMINAL_STACK_CHEZMOI")
    if pinned:
        return pinned
    local = Path.home() / ".local" / "bin" / "chezmoi"
    if local.is_file() and os.access(local, os.X_OK):
        return str(local)
    return shutil.which("chezmoi")


def find_pwsh() -> str | None:
    """PowerShell 7+, or None. `pwsh` only; Windows PowerShell 5.1 is not used."""
    return shutil.which("pwsh") or shutil.which("pwsh.exe")


def to_windows_path(path: Path | str) -> str | None:
    """A POSIX path as Windows sees it, for handing to pwsh from WSL.

    Returns the input unchanged on native Windows. None when wslpath is missing
    or the path has no Windows equivalent -- callers must handle that rather than
    passing a POSIX path to a Windows process, which fails in confusing ways.
    """
    if kind() == WINDOWS:
        return str(path)
    if kind() != WSL:
        return None
    out = proc.capture(["wslpath", "-w", str(path)], timeout=10)
    if out is None or out.returncode != 0:
        return None
    return out.stdout.strip() or None
