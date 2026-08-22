"""Follow ttsd.log without breaking the daemon's own logging.

Five things make a naive `open(...).readlines()` loop wrong here, and each one is a real
property of this log rather than a hypothetical:

1. **Rotation renames the file under you.** `_setup_logging` uses a `RotatingFileHandler`
   with `maxBytes=1_000_000` and `backupCount=3`. On Windows a reader holding the file open
   can make that rename *fail inside the handler*, which would break the daemon's logging to
   provide a log viewer. So: stat, open, read, close, every poll. Never hold the handle.
2. **Rotation is detected by the file getting smaller**, since the fresh `ttsd.log` starts at
   zero while our offset is a megabyte in.
3. **A poll can land mid-line.** Anything after the last newline is held back and prepended
   next time, so the UI never renders half a record.
4. **A byte offset can land mid-codepoint.** Spoken lines carry smart quotes and ellipses, so
   reading bytes and decoding with `errors="replace"` is the only safe option; strict
   decoding would raise on a perfectly healthy file.
5. **A missing file is a steady state, not an error.** When the log directory is unusable,
   `_setup_logging` falls back to a `NullHandler` and nothing is ever written. That is the
   same condition that once hid fifteen hours of silence, so the caller is told "no file"
   rather than "no activity".

Multi-line records: nothing in the package logs a traceback today, but a future
`log.exception` or a third-party library would emit continuation lines with no timestamp
prefix. `parse_line` returns None for those so a renderer can attach them to the previous
record instead of dropping them.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

# `%(asctime)s %(levelname).1s %(name)s: %(message)s`. The level is a single letter, so
# CRITICAL and DEBUG both collapse to one character and cannot be told apart by width.
_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) "
    r"(?P<level>[A-Z]) (?P<logger>[\w.]+): (?P<message>.*)$")

_LEVELS = {"D": "debug", "I": "info", "W": "warning", "E": "error", "C": "critical"}

# How far back a first render reaches. 256 KiB of this log is comfortably more than the
# 200 lines a UI shows, without reading a rotated megabyte for nothing.
_SNAPSHOT_BYTES = 256 * 1024


def parse_line(line: str) -> dict | None:
    """One log record as fields, or None when the line is a continuation."""
    match = _LINE.match(line)
    if match is None:
        return None
    fields = match.groupdict()
    fields["level"] = _LEVELS.get(fields["level"], fields["level"].lower())
    return fields


class LogTail:
    """Incremental follower for one log file. Not thread-safe by design: one per stream."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._offset = 0
        self._partial = ""
        self.rotations = 0

    def exists(self) -> bool:
        try:
            return self.path.is_file()
        except OSError:
            return False

    def snapshot(self, max_lines: int = 200) -> list[str]:
        """The last `max_lines` complete lines, and position us at the end of the file."""
        try:
            size = self.path.stat().st_size
        except OSError:
            self._offset = 0
            return []
        start = max(0, size - _SNAPSHOT_BYTES)
        try:
            with open(self.path, "rb") as handle:
                handle.seek(start)
                raw = handle.read()
        except OSError as exc:
            log.debug("log snapshot failed: %s", exc)
            return []
        self._offset = size
        self._partial = ""
        text = raw.decode("utf-8", errors="replace")
        if start:
            # The first line is almost certainly truncated by the seek; drop it.
            text = text.partition("\n")[2]
        lines = [line.rstrip("\r") for line in text.split("\n")]
        if lines and lines[-1] == "":
            lines.pop()          # trailing newline, not a real empty record
        elif lines:
            self._partial = lines.pop()   # the file ended mid-line; hold it back
        return lines[-max_lines:]

    def read_new(self) -> list[str]:
        """Complete lines appended since the last call. Never raises."""
        try:
            size = self.path.stat().st_size
        except OSError:
            # Gone, or never created. Reset so a later creation is picked up from its start.
            self._offset = 0
            self._partial = ""
            return []
        if size < self._offset:
            self.rotations += 1
            self._offset = 0
            self._partial = ""
        if size == self._offset:
            return []
        try:
            with open(self.path, "rb") as handle:
                handle.seek(self._offset)
                raw = handle.read()
                self._offset = handle.tell()
        except OSError as exc:
            log.debug("log read failed: %s", exc)
            return []
        text = self._partial + raw.decode("utf-8", errors="replace")
        parts = text.split("\n")
        self._partial = parts.pop()   # always the (possibly empty) tail after the last \n
        return [line.rstrip("\r") for line in parts]
