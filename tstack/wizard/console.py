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
import os
import sys
from collections.abc import Iterable, Iterator
from typing import IO

# Named keys `key()` returns. Anything else comes back as the character itself.
UP, DOWN, LEFT, RIGHT = "up", "down", "left", "right"
ENTER, SPACE, ESC, BACKSPACE, HOME, END = "enter", "space", "esc", "backspace", "home", "end"
PGUP, PGDN = "pgup", "pgdn"

_CSI = {"A": UP, "B": DOWN, "C": RIGHT, "D": LEFT, "H": HOME, "F": END}
_CSI_TILDE = {"1": HOME, "4": END, "5": PGUP, "6": PGDN, "7": HOME, "8": END}
# msvcrt.getwch() prefixes a special key with \x00 or \xe0, then a scan code.
_WIN_SCAN = {"H": UP, "P": DOWN, "K": LEFT, "M": RIGHT, "G": HOME, "O": END, "I": PGUP, "Q": PGDN}


class Console:
    """Reads and writes the controlling terminal, or nothing at all."""

    def __init__(
        self,
        reader: IO[str] | None = None,
        writer: IO[str] | None = None,
        script: list[str] | None = None,
        keys: list[str] | None = None,
    ) -> None:
        self._reader = reader
        self._writer = writer
        # A scripted console answers from a list and records what it was asked,
        # so the suite exercises the real prompt loops without a terminal.
        self._script = script
        # Scripted KEYS turn on the arrow-key widgets under test, the same way a
        # real terminal does. Plain scripts keep the numbered prompts.
        self._keys = keys
        self.captured: list[str] = []
        # Output HELD while the flow replays answers after a Back: the lines a
        # replayed step prints (a prompt preview, a probe report) belong to that
        # step, and printing them again would bury the question being asked.
        # The Asker flushes or discards them; see flow.Asker.
        self._hold = False
        self._pending: list[str] = []

    @property
    def interactive(self) -> bool:
        return self._script is not None or (self._reader is not None and self._writer is not None)

    @classmethod
    def open(cls, tty: str = "/dev/tty") -> Console:
        """The controlling terminal, or a non-interactive console.

        Never raises. A container, a CI runner and a piped installer all land
        here, and every one of them must still complete with defaults.

        Two handles, never one `r+`: a text-mode `r+` is a BufferedRandom, which
        demands a SEEKABLE file, and a tty is not one. The UnsupportedOperation
        it raises is an OSError, so the except below turned every POSIX install
        into a silent all-defaults run -- no menu printed, nothing asked. `tty`
        is a parameter so the suite can hand it a real pty.
        """
        if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
            try:
                return cls(open("CONIN$", encoding="utf-8"), open("CONOUT$", "w", encoding="utf-8"))
            except OSError:
                return cls()
        reader = None
        try:
            # Deliberately not context managers: the handles have to outlive
            # this call and are closed by close(). ruff's SIM115 is about leaks,
            # and the lifetime here is the wizard's.
            reader = open(tty, encoding="utf-8")  # noqa: SIM115
            writer = open(tty, "w", encoding="utf-8")  # noqa: SIM115
        except OSError:
            if reader is not None:
                reader.close()
            return cls()
        return cls(reader, writer)

    @classmethod
    def scripted(cls, answers: Iterable[str]) -> Console:
        """A console that replays answers, for tests. Never touches a terminal."""
        return cls(script=list(answers))

    @classmethod
    def scripted_keys(cls, keys: Iterable[str], answers: Iterable[str] = ()) -> Console:
        """A console that replays KEY presses (and, for free text, answers)."""
        return cls(script=list(answers), keys=list(keys))

    # ---------------------------------------------------------------- held output

    def hold(self, on: bool) -> None:
        self._hold = on

    def take_pending(self) -> list[str]:
        lines, self._pending = self._pending, []
        return lines

    def flush(self) -> None:
        """Print whatever was held, in order."""
        held = self._hold
        self._hold = False
        for line in self.take_pending():
            self.say(line)
        self._hold = held

    @contextlib.contextmanager
    def released(self) -> Iterator[None]:
        """Output goes straight out for the duration (a question being asked)."""
        held = self._hold
        self._hold = False
        try:
            yield
        finally:
            self._hold = held

    # ---------------------------------------------------------------- raw keys

    @property
    def tui(self) -> bool:
        """Can the arrow-key widgets run here?

        Off for TERM=dumb and with TS_WIZ_PLAIN set (an escape hatch for a
        terminal that mangles the redraw), and wherever single keys cannot be
        read: then the numbered prompts below are used, unchanged.
        """
        if self._keys is not None:
            return True
        if self._script is not None or self._reader is None or self._writer is None:
            return False
        if os.environ.get("TS_WIZ_PLAIN", "").strip() not in ("", "0", "no", "false"):
            return False
        if os.environ.get("TERM", "") == "dumb":
            return False
        if sys.platform == "win32":  # pragma: no cover - Windows only
            return _enable_vt()
        try:
            import termios  # noqa: F401
        except ImportError:  # pragma: no cover
            return False
        try:
            return os.isatty(self._reader.fileno())
        except (OSError, ValueError):
            return False

    def key(self) -> str:
        """One key press, decoded. Ctrl+C still raises KeyboardInterrupt.

        The terminal is switched to cbreak for ONE read and restored in a
        `finally`, so nothing that dies between reads can leave it unechoed.
        """
        if self._keys is not None:
            # An exhausted key script presses Enter, the same rule as ask().
            return self._keys.pop(0) if self._keys else ENTER
        if sys.platform == "win32":  # pragma: no cover - Windows only
            return _win_key()
        assert self._reader is not None
        return _posix_key(self._reader.fileno())

    def write(self, text: str) -> None:
        """Raw output with no newline, for redraws. Dropped when scripted."""
        if self._script is not None or self._keys is not None:
            return
        if self._writer is None:
            return
        with contextlib.suppress(OSError, ValueError):
            self._writer.write(text)
            self._writer.flush()

    def draw(self, lines: list[str]) -> None:
        """Clear the screen and draw one frame. A scripted console records it."""
        if self._script is not None or self._keys is not None:
            self.captured.extend(lines)
            return
        self.write("\x1b[H\x1b[2J" + "\n".join(lines) + "\n")

    def size(self) -> tuple[int, int]:
        """(columns, rows) of the terminal, with a sane fallback."""
        if self._writer is not None and self._keys is None:
            with contextlib.suppress(OSError, ValueError):
                size = os.get_terminal_size(self._writer.fileno())
                # A pty nobody has sized reports 0x0; draw for a normal one.
                if size.columns >= 20 and size.lines >= 10:
                    return (size.columns, size.lines)
        return (100, 40)

    def say(self, text: str = "") -> None:
        if self._hold:
            self._pending.append(text)
            return
        if self._script is not None or self._keys is not None:
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


def _posix_key(fd: int) -> str:
    import select
    import termios
    import tty

    old = termios.tcgetattr(fd)
    try:
        # TCSANOW, not the default TCSAFLUSH: a flush DISCARDS keys typed ahead
        # of this read, so a fast arrow-arrow-Enter would lose presses.
        tty.setcbreak(fd, termios.TCSANOW)

        def more(timeout: float = 0.05) -> str:
            ready, _, _ = select.select([fd], [], [], timeout)
            return os.read(fd, 1).decode("utf-8", "replace") if ready else ""

        ch = os.read(fd, 1).decode("utf-8", "replace")
        if ch == "\x1b":
            nxt = more()
            if nxt not in ("[", "O"):
                return ESC
            code = more()
            if code in _CSI:
                return _CSI[code]
            if code.isdigit():
                tail = more()
                while tail and tail != "~" and not tail.isalpha():
                    tail = more()
                return _CSI_TILDE.get(code, ESC)
            return ESC
        if ch in ("\r", "\n"):
            return ENTER
        if ch == " ":
            return SPACE
        if ch in ("\x7f", "\x08"):
            return BACKSPACE
        if ch == "\x03":  # cbreak keeps ISIG, but be explicit
            raise KeyboardInterrupt
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _win_key() -> str:  # pragma: no cover - Windows only
    import msvcrt

    ch = msvcrt.getwch()  # type: ignore[attr-defined]
    if ch in ("\x00", "\xe0"):
        return _WIN_SCAN.get(msvcrt.getwch(), ESC)  # type: ignore[attr-defined]
    if ch == "\r":
        return ENTER
    if ch == " ":
        return SPACE
    if ch == "\x08":
        return BACKSPACE
    if ch == "\x1b":
        return ESC
    if ch == "\x03":
        raise KeyboardInterrupt
    return ch


def _enable_vt() -> bool:  # pragma: no cover - Windows only
    """Turn on ANSI processing for the console. False on a console that cannot,
    which is the old conhost: the numbered prompts are used there instead."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        kernel32.CreateFileW.restype = ctypes.c_void_p
        # CONOUT$ itself, not STD_OUTPUT: the installers may capture stdout,
        # and the wizard draws on the console whatever stdout is.
        handle = kernel32.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None)
        if not handle or handle == ctypes.c_void_p(-1).value:
            return False
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        return False
