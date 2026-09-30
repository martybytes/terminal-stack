"""Suite-wide isolation that every module needs and none should have to remember."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tstack import headroom_token


@pytest.fixture(autouse=True)
def _no_terminal_prompts(monkeypatch):
    """No test may block on /dev/tty. tstack.confirm refuses under CI; a
    developer's interactive terminal is not CI, so the suite says it is."""
    monkeypatch.setenv("CI", "1")


@pytest.fixture(autouse=True)
def _isolated_headroom_token(tmp_path, monkeypatch):
    """The machine's Headroom token lives in %LOCALAPPDATA% or the XDG state dir.
    Anything that seeds a secret or reads a token writes or reads it, so without
    this the suite would overwrite the developer's real one -- or, worse, pass
    because it happened to find it."""
    monkeypatch.setattr(headroom_token, "path", lambda: tmp_path / "machine-headroom-token")
