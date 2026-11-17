"""Suite-wide isolation that every module needs and none should have to remember."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tstack import headroom_token

# What git exports to a hook to say which repository it is running in. The
# pre-commit hook runs this suite, and every test that builds a throwaway repo
# with `git -C <tmp>` inherits them. In a main clone GIT_INDEX_FILE is the
# relative `.git/index`, which happens to resolve inside each temp repo; in a
# linked worktree it is an absolute path to the worktree's index, so those
# tests checked out against the wrong index and the hook failed tests that
# pass anywhere else.
_GIT_REPO_ENV = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_PREFIX",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
)


@pytest.fixture(autouse=True)
def _no_inherited_git_repo(monkeypatch):
    for name in _GIT_REPO_ENV:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _no_terminal_prompts(monkeypatch):
    """No test may block on /dev/tty. tstack.confirm refuses under CI; a
    developer's interactive terminal is not CI, so the suite says it is."""
    monkeypatch.setenv("CI", "1")


@pytest.fixture(autouse=True)
def _no_real_console(monkeypatch):
    """The wizard's Console.open() with no argument is the developer's real
    terminal: /dev/tty, or CONIN$ on Windows. Wherever one exists (a local run,
    and evidently the macOS runner) the arrow-key review comes up and waits for
    a key forever, and the whole suite hangs with no output. A test that wants a
    terminal hands Console.open its own pty; the real one is
    `Console._unguarded_open`."""
    from tstack.wizard.console import Console

    real = Console.open
    monkeypatch.setattr(Console, "_unguarded_open", real, raising=False)

    def guarded(cls, tty=None):
        return cls() if tty is None else real.__func__(cls, tty)

    monkeypatch.setattr(Console, "open", classmethod(guarded))


@pytest.fixture(autouse=True)
def _no_real_hotkey_probe(monkeypatch):
    """tstack.hotkey asks Windows whether another program holds a chord, and the
    answer is the developer's desktop: on a PC where something holds Ctrl+Backslash
    the wizard asks an extra question and every scripted answer after it shifts.
    "Cannot tell" is what Linux and macOS CI see, so every test sees that too.
    tests/test_hotkey.py stubs it per test where the answer matters."""
    from tstack import hotkey

    monkeypatch.setattr(hotkey, "held_elsewhere", lambda chord: None)


@pytest.fixture(autouse=True)
def _isolated_headroom_token(tmp_path, monkeypatch):
    """The machine's Headroom token lives in %LOCALAPPDATA% or the XDG state dir.
    Anything that seeds a secret or reads a token writes or reads it, so without
    this the suite would overwrite the developer's real one -- or, worse, pass
    because it happened to find it."""
    monkeypatch.setattr(headroom_token, "path", lambda: tmp_path / "machine-headroom-token")
