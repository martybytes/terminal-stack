"""The machine's Headroom proxy token: one file, because there is one proxy.

The proxy is per MACHINE -- on a combined Windows+WSL box one Docker Desktop
container serves both sides -- but the token used to be per CLONE: each clone's
`services/stacks/headroom/.env` held its own. With three clones on one machine
(the WSL runtime clone, the Windows runtime clone, a Windows dev checkout) only
one could match the running proxy, and every wrapper reading another clone
printed "Headroom is enabled but unavailable" and went direct, silently.

So the token that counts is the one the RUNNING proxy holds, and it is recorded
in one place both sides can read:

  combined Windows+WSL  %LOCALAPPDATA%\\terminal-stack\\headroom-token
                        (WSL: /mnt/c/Users/<you>/AppData/Local/...)
  native Linux / macOS  $XDG_STATE_HOME/terminal-stack/headroom-token

Readers, in this order everywhere (Python here, `_ts_headroom_token` in
dot_zshrc, `Get-TsHeadroomToken` in $PROFILE): HEADROOM_PROXY_TOKEN, then
HEADROOM_ENV_FILE, then this file, then the clone's own .env. Never printed.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from . import platform as plat

FILENAME = "headroom-token"


def path() -> Path | None:
    """Where the machine token lives, or None when it cannot be located.

    A seam: the suite points this at a temporary file (tests/conftest.py), so no
    test can read or overwrite the developer's real token.
    """
    return _default_path()


def _default_path() -> Path | None:
    if plat.kind() in (plat.WINDOWS, plat.WSL):
        base = plat.local_app_data()
        return base / "terminal-stack" / FILENAME if base else None
    return plat.state_dir() / FILENAME


def read() -> str:
    target = path()
    if target is None:
        return ""
    try:
        return target.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write(token: str) -> bool:
    """Record `token` as the machine's. Atomic, 0600 where that means anything."""
    target = path()
    token = token.strip()
    if target is None or not token:
        return False
    if read() == token:
        return True
    tmp = target.with_name(f".{FILENAME}.{os.getpid()}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(token + "\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            tmp.chmod(0o600)
        os.replace(tmp, target)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        return False
    return True
