"""WezTerm CLI lookups (focused pane) with a short cache.

Any failure returns None — callers treat that as "don't suppress".
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time

log = logging.getLogger(__name__)

_CACHE_SEC = 2.0


def _wezterm_exe() -> str | None:
    found = shutil.which("wezterm")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if not base:
            continue
        candidate = os.path.join(base, "WezTerm", "wezterm.exe")
        if os.path.isfile(candidate):
            return candidate
    return None


class WezInfo:
    def __init__(self) -> None:
        self.exe = _wezterm_exe()
        self._focused_pane: str | None = None
        self._checked = 0.0

    def focused_pane(self) -> str | None:
        """Pane id of the focused client's active pane, or None."""
        if not self.exe:
            return None
        now = time.monotonic()
        if now - self._checked < _CACHE_SEC:
            return self._focused_pane
        self._checked = now
        self._focused_pane = None
        try:
            out = subprocess.run(
                [self.exe, "cli", "list-clients", "--format", "json"],
                capture_output=True, text=True, timeout=3, check=True,
            ).stdout
            clients = json.loads(out)
            latest = max(clients, key=lambda c: c.get("last_input", ""), default=None)
            if latest and latest.get("focused_pane_id") is not None:
                self._focused_pane = str(latest["focused_pane_id"])
        except (subprocess.SubprocessError, ValueError, OSError) as exc:
            log.debug("wezterm list-clients failed: %s", exc)
        return self._focused_pane
