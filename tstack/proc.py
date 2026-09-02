"""Running a child process and reading what it said, once, correctly.

Six modules had grown the same `_run` helper, and every copy captured with a
bare `text=True`. That decodes the child's output with the LOCALE codec, which
on a Windows host is cp1252 -- and everything this stack shells out to (starship,
wezterm, docker, git, chezmoi) emits UTF-8. The failure is not a mojibake
character you would notice:

    UnicodeDecodeError: 'charmap' codec can't decode byte 0x81 ...

is raised inside subprocess's stdout READER THREAD, so `subprocess.run` returns
a CompletedProcess with `returncode=0`, `stderr=''` and `stdout=None`. The
caller then does `got.stdout.strip()` and dies with an AttributeError three
frames from anything that mentions encoding. `tstack ui` did exactly that on
`starship preset tokyo-night`, whose Nerd Font glyphs are outside cp1252.

So: one helper, `encoding="utf-8"` always, and `errors="replace"` because a
child that is genuinely not UTF-8 (`tasklist.exe` on a non-Latin locale) must
cost a replacement character, never a None that every call site dereferences.

Same contract the callers already had, and it is the one in choices.py's
docstring: EVERY PROBE MAY FAIL AND THAT IS NORMAL. A missing binary, a timeout
or a refused exec is `None`, not an exception.
"""

from __future__ import annotations

import subprocess

# Long enough for a container probe, short enough that a wedged child cannot
# hang a login. Callers that know better pass their own.
TIMEOUT = 15


def capture(
    argv: list[str],
    *,
    timeout: int = TIMEOUT,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | None:
    """Run `argv`, capture both streams as UTF-8 text, or None if it could not run."""
    try:
        return subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            start_new_session=True,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def feed(argv: list[str], stdin: str, *, timeout: int | None = None) -> int:
    """Run `argv` with `stdin` on its input, streams INHERITED, and return its code.

    The pager path: stdout must reach the terminal, so nothing is captured. Only
    the write side needs the encoding fix here -- a locale-encoded stdin turns
    the box-drawing glyphs in piped markdown into `?` before the pager sees them.
    """
    try:
        return subprocess.run(
            argv,
            input=stdin,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            start_new_session=True,
        ).returncode
    except (OSError, subprocess.SubprocessError):
        return 1
