"""`tstack wizard` - the install questionnaire.

Runs the questions and writes the answers where the caller asked for them. It
persists NOTHING: the four bootstraps keep their own setter sequences, which is
what preserves the documented invariant that answers are saved before anything
that can fail.
"""

from __future__ import annotations

import sys
from pathlib import Path

from ..wizard import emit, flow
from ..wizard.console import Console

HELP = """tstack wizard - the install questionnaire.

Usage:
  tstack wizard [--emit sh|json] [--out PATH] [--ask-terminals]
                [--assume-yes] [--no-review]

  --emit sh       shell `export NAME=value` lines, for a bootstrap to source
  --emit json     one object, for the PowerShell bootstrap
  --out PATH      where to write them (required with --emit)
  --ask-terminals include the terminal-emulator question
  --assume-yes    accept the review without showing the prompt
  --no-review     skip the review screen entirely

With no --emit it prints the review and exits, which is a dry run: nothing is
written, installed or saved either way. Every question can be skipped with its
own TS_* environment variable.

exit status: 0 proceed, 3 you quit, 2 usage, 1 failure."""

QUIT = 3


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0

    emit_as = ""
    out: Path | None = None
    ask_terminals = False
    assume_yes = False
    no_review = False

    rest = list(argv)
    while rest:
        item = rest.pop(0)
        if item == "--emit":
            if not rest or rest[0] not in ("sh", "json"):
                print("tstack wizard: --emit takes sh or json", file=sys.stderr)
                return 2
            emit_as = rest.pop(0)
        elif item == "--out":
            if not rest:
                print("tstack wizard: --out needs a path", file=sys.stderr)
                return 2
            out = Path(rest.pop(0))
        elif item == "--ask-terminals":
            ask_terminals = True
        elif item == "--assume-yes":
            assume_yes = True
        elif item == "--no-review":
            no_review = True
        else:
            print(f"tstack wizard: unknown option '{item}' (try -h)", file=sys.stderr)
            return 2

    if emit_as and out is None:
        print("tstack wizard: --emit needs --out", file=sys.stderr)
        return 2

    console = Console.open()
    try:
        answers = flow.collect(console, ask_terminals=ask_terminals)
        if no_review:
            flow.review(console, answers)
        else:
            confirmed = flow.confirm(console, answers, assume_yes)
            if confirmed is None:
                return QUIT
            answers = confirmed
    finally:
        console.close()

    if not emit_as or out is None:
        return 0
    try:
        body = emit.to_sh(answers) if emit_as == "sh" else emit.to_json(answers)
        emit.write(out, body)
    except (OSError, ValueError) as exc:
        print(f"tstack wizard: could not write {out}: {exc}", file=sys.stderr)
        return 1
    return 0
