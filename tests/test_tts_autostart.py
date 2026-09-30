"""A daemon a hook starts must have the tray, like the one logon starts.

Here, not in bootstrap/tts-daemon/tests: CI runs `tests/` only. The hook-side
autostart passed `--no-tray` (a debugging mode), so after any exe rebuild or
crash the daemon that came back spoke normally with no icon -- and a WSL
session, whose speech goes through it, had nothing to mute from.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bootstrap" / "tts-daemon"))

from ttsd import hooks  # noqa: E402


def test_the_hook_autostart_keeps_the_tray(monkeypatch):
    for frozen in (False, True):
        monkeypatch.setattr(sys, "frozen", frozen, raising=False)
        argv = hooks._daemon_command()
        assert "daemon" in argv
        assert "--no-tray" not in argv


def test_logon_autostart_and_hook_autostart_launch_the_same_way():
    """The Run-key launch is `terminal-stack-tts.exe daemon`; two different
    launches of one daemon is how one of them lost its icon."""
    ps1 = (ROOT / "bootstrap" / "install-tts-daemon.ps1").read_text(encoding="utf-8")
    assert "-ArgumentList 'daemon'" in ps1
    assert "--no-tray" not in ps1
