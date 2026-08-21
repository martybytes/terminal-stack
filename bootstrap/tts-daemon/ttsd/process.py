"""Windows-safe subprocess helpers.

The packaged daemon has no console. Any console-subsystem child it starts must
explicitly opt out of console creation or Windows flashes a terminal window.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Sequence
from typing import Any

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200


def _flags(detached: bool = False) -> int:
    if os.name != "nt":
        return 0
    flags = CREATE_NO_WINDOW
    if detached:
        flags |= DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    return flags


def run_hidden(command: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess:
    """Run a child without creating a Windows console window."""
    if os.name == "nt":
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | _flags()
    return subprocess.run(command, **kwargs)


def popen_hidden(command: Sequence[str], *, detached: bool = False,
                 **kwargs: Any) -> subprocess.Popen:
    """Start a child without a Windows console, optionally detached."""
    if os.name == "nt":
        kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | _flags(detached)
    return subprocess.Popen(command, **kwargs)
