"""Destructive prompts are answered at the terminal or not at all.

`services._ask` and `mux._confirm` opened /dev/tty as one `r+` text handle,
which always fails (a tty is not seekable), then fell back to `input()` -- so
`echo "destroy all memories" | tstack services reset --purge` deleted every
volume with nobody at the keyboard. One helper now, on the wizard's Console.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import confirm  # noqa: E402
from tstack.wizard.console import Console  # noqa: E402

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX ptys only")


def _no_terminal(monkeypatch):
    monkeypatch.setattr(Console, "open", classmethod(lambda cls, tty="/dev/tty": cls()))


def test_a_pipe_cannot_type_the_destructive_phrase(monkeypatch, capsys):
    """stdin holds the exact phrase; it must still be refused."""
    monkeypatch.delenv("CI", raising=False)
    _no_terminal(monkeypatch)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("destroy all memories\n"))
    assert confirm.typed("Type it: ", "destroy all memories", tool="t") is False
    assert "needs 'destroy all memories' typed at a terminal" in capsys.readouterr().err


def test_a_pipe_cannot_say_yes_either(monkeypatch, capsys):
    monkeypatch.delenv("CI", raising=False)
    _no_terminal(monkeypatch)
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("y\n"))
    assert confirm.confirm("Proceed", tool="t") is False
    assert "no terminal to confirm on" in capsys.readouterr().err


def test_assume_yes_is_the_only_flag_that_stands_in_for_a_yes(monkeypatch):
    _no_terminal(monkeypatch)
    assert confirm.confirm("Proceed", assume_yes=True) is True


@posix_only
def test_the_terminal_answer_is_what_counts(monkeypatch):
    monkeypatch.delenv("CI", raising=False)  # a real terminal, not a runner
    master, slave = os.openpty()
    tty = os.ttyname(slave)
    try:
        real_open = Console.open
        Console.open = classmethod(lambda cls, t=tty: real_open.__func__(cls, t))  # type: ignore[method-assign]
        os.write(master, b"destroy all memories\n")
        assert confirm.typed("> ", "destroy all memories") is True
        os.write(master, b"nope\n")
        assert confirm.typed("> ", "destroy all memories") is False
        os.write(master, b"yes\n")
        assert confirm.confirm("Proceed") is True
    finally:
        Console.open = real_open  # type: ignore[method-assign]
        os.close(master)
        os.close(slave)


def test_no_module_opens_the_tty_as_one_read_write_handle():
    """The bug's signature. Grep the package, so a fourth copy cannot come back."""
    offenders = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "tstack").rglob("*.py")
        if 'open("/dev/tty", "r+"' in p.read_text(encoding="utf-8")
    ]
    assert not offenders, offenders


def test_every_prompting_command_goes_through_the_helper():
    for rel in (
        "commands/services.py",
        "commands/mux.py",
        "commands/ui.py",
        "commands/workspace.py",
    ):
        src = (ROOT / "tstack" / rel).read_text(encoding="utf-8")
        assert "input(" not in src, f"{rel} still reads stdin for a prompt"
        assert "confirm." in src, f"{rel} does not use tstack.confirm"


def test_under_ci_nothing_is_ever_asked(monkeypatch):
    """A runner's process can own a tty with nobody at it; the suite hung there."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.setattr(
        Console, "open", classmethod(lambda cls, tty="/dev/tty": pytest.fail("opened"))
    )
    assert confirm.ask("?") is None
