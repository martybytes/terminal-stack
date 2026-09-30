"""One yes/no (or typed-phrase) prompt, on the controlling terminal, never stdin.

Three copies of this existed (services, mux, ui) and two of them opened
`/dev/tty` as one `r+` text handle -- which always fails, because a tty is not
seekable -- then fell back to `input()`. So `echo "destroy all memories" |
tstack services reset --purge` deleted every volume with nobody at the keyboard,
under a docstring promising the opposite.

The rule: a prompt that guards a destructive step is answered from the terminal
(`Console.open()`, the wizard's reader+writer pair) or not at all. No terminal,
no consent; the caller says so and stops. Piped stdin is never read.
"""

from __future__ import annotations

import os
import sys

from .wizard.console import Console


def ask(prompt: str) -> str | None:
    """One line from the terminal, or None when there is nobody to ask.

    Never under CI: a runner's process can own a tty with nobody at it, and a
    prompt there waits forever. The Windows and WSL suites hung for 30 minutes
    on exactly that before this guard existed.
    """
    if os.environ.get("CI"):
        return None
    console = Console.open()
    try:
        if not console.interactive:
            return None
        return console.ask(prompt)
    finally:
        console.close()


def confirm(prompt: str, *, assume_yes: bool = False, tool: str = "tstack") -> bool:
    """[y/N] on the terminal. `assume_yes` is the explicit -y flag, nothing else."""
    if assume_yes:
        return True
    answer = ask(f"{prompt} [y/N]: ")
    if answer is None:
        print(
            f"{tool}: no terminal to confirm on - re-run with -y if you mean it.", file=sys.stderr
        )
        return False
    if answer.strip().lower() in ("y", "yes"):
        return True
    print("aborted.")
    return False


def typed(prompt: str, phrase: str, *, tool: str = "tstack") -> bool:
    """The exact phrase, typed at the terminal. There is deliberately no flag
    that stands in for it: this guards steps with no rollback."""
    answer = ask(prompt)
    if answer is None:
        print(
            f"{tool}: this needs '{phrase}' typed at a terminal; a pipe cannot answer it.",
            file=sys.stderr,
        )
        return False
    return answer.strip() == phrase
