"""Parser for tstack/commands.conf.

The conf file, not this module, is the source of truth. Python is one of four
readers -- the two shell shims and the two completion providers parse the same
table with awk and Select-String, which is why the format is whitespace-delimited
rather than JSON and why `tstack --help` still works when Python is missing or
broken.

See the header of tstack/commands.conf for the format and the implementation
tokens.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path

from . import platform as plat

CONF_NAME = "commands.conf"

PYTHON = "python"
UNSUPPORTED = "-"


@dataclass(frozen=True)
class Command:
    name: str
    posix: str
    windows: str
    summary: str

    def impl(self, kind: str | None = None) -> str:
        """The implementation token for a platform.

        WSL takes the posix column: it is a POSIX environment, chezmoi is
        authoritative there, and the bash implementations are the ones that know
        how to reach across to the Windows side.
        """
        k = kind or plat.kind()
        return self.windows if k == plat.WINDOWS else self.posix

    def is_ported(self, kind: str | None = None) -> bool:
        return self.impl(kind) == PYTHON

    def is_supported(self, kind: str | None = None) -> bool:
        return self.impl(kind) != UNSUPPORTED


def conf_path() -> Path:
    return Path(__file__).resolve().parent / CONF_NAME


def parse(text: str) -> list[Command]:
    out: list[Command] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 3)
        if len(parts) < 4:
            # A malformed row is a bug in the table, not user input. Say which
            # row, because a silently dropped subcommand is exactly the kind of
            # failure this repo keeps being bitten by.
            raise ValueError(f"{CONF_NAME}: expected 4 fields, got {len(parts)}: {raw!r}")
        name, posix, windows, summary = parts
        out.append(Command(name=name, posix=posix, windows=windows, summary=summary.strip()))
    return out


@functools.lru_cache(maxsize=1)
def commands() -> tuple[Command, ...]:
    return tuple(parse(conf_path().read_text(encoding="utf-8")))


def get(name: str) -> Command | None:
    for c in commands():
        if c.name == name:
            return c
    return None


def names() -> list[str]:
    return [c.name for c in commands()]
