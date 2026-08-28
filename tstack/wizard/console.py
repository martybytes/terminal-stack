"""The terminal the wizard talks to, which is never stdin.

`curl ... | bash` and `irm ... | iex` are documented install paths, and on both
of them stdin is the SCRIPT. Reading answers from it would consume the installer
and prompt with its source. The shell wizard opened `/dev/tty` for exactly this
reason and so does this.

Interactive means one thing: the tty pair opened. Not `isatty`, not an
environment variable. A machine where it cannot be opened takes every default
and says so, which is what makes a scripted install deterministic.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Iterable
from typing import IO


class Console:
    """Reads and writes the controlling terminal, or nothing at all."""

    def __init__(
        self,
        reader: IO[str] | None = None,
        writer: IO[str] | None = None,
        script: list[str] | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        # A scripted console answers from a list and records what it was asked,
        # so the suite exercises the real prompt loops without a terminal.
        self._script = script
        self.captured: list[str] = []

    @property
    def interactive(self) -> bool:
        return self._script is not None or (self._reader is not None and self._writer is not None)

    @classmethod
    def open(cls) -> Console:
        """The controlling terminal, or a non-interactive console.

        Never raises. A container, a CI runner and a piped installer all land
        here, and every one of them must still complete with defaults.
        """
        if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
            try:
                return cls(open("CONIN$", encoding="utf-8"), open("CONOUT$", "w", encoding="utf-8"))
            except OSError:
                return cls()
        try:
            # Deliberately not a context manager: the handle has to outlive this
            # call and is closed by close(). ruff's SIM115 is about leaks, and
            # the lifetime here is the wizard's.
            handle = open("/dev/tty", "r+", encoding="utf-8")  # noqa: SIM115
        except OSError:
            return cls()
        return cls(handle, handle)

    @classmethod
    def scripted(cls, answers: Iterable[str]) -> Console:
        """A console that replays answers, for tests. Never touches a terminal."""
        return cls(script=list(answers))

    def say(self, text: str = "") -> None:
        if self._script is not None:
            self.captured.append(text)
            return
        if self._writer is None:
            return
        # ValueError as well as OSError: writing to a CLOSED handle raises
        # ValueError("I/O operation on closed file"), which is what a terminal
        # going away mid-run looks like. Losing a menu line is survivable; a
        # traceback out of an installer is not.
        with contextlib.suppress(OSError, ValueError):
            self._writer.write(text + "\n")
            self._writer.flush()

    def ask(self, prompt: str) -> str | None:
        """One answer, or None when there is nobody to ask.

        None and "" are different: "" is somebody pressing Enter, which every
        prompt reads as "take the default". None is nobody there at all.
        """
        if self._script is not None:
            self.captured.append(prompt)
            # An exhausted script behaves like Enter, so a test that supplies
            # three answers to a five-question flow takes the defaults for the
            # rest rather than hanging or raising.
            return self._script.pop(0) if self._script else ""
        if self._reader is None or self._writer is None:
            return None
        try:
            self._writer.write(prompt)
            self._writer.flush()
            line = self._reader.readline()
        except (OSError, ValueError):
            # Same reason as say(): a closed handle is a ValueError. No answer
            # means take the default, which is what every caller does with None.
            return None
        if line == "":
            # EOF on an open tty. Treated exactly as an empty answer -- take the
            # default, break the loop -- and never as an error.
            return ""
        return line.rstrip("\r\n")

    def close(self) -> None:
        for handle in {self._reader, self._writer}:
            if handle is not None:
                with contextlib.suppress(OSError, ValueError):
                    handle.close()
