"""`tstack wizard` - the install questionnaire.

Runs the questions and writes the answers where the caller asked for them. It
persists NOTHING: the four bootstraps keep their own setter sequences, which is
what preserves the documented invariant that answers are saved before anything
that can fail.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ..wizard import answers as answers_file
from ..wizard import emit, flow
from ..wizard.console import Console

HELP = """tstack wizard - PREVIEW the install questionnaire. Saves nothing.

  Run on its own, this asks every install question and shows the review, then
  exits WITHOUT saving, installing or changing anything. It is for seeing what
  the questions are and what you would get.

  To answer the questions AND apply them, run one of:
    tstack config wizard      the same questions, then saves and applies
    tstack config             the settings menu; press  w  to re-run the wizard
    tstack config leader ctrl-backslash   change one setting directly

  The options below are how the installers call it; you do not need them.

Usage:
  tstack wizard [--emit sh|json] [--out PATH] [--answers FILE]
                [--ask-terminals] [--assume-yes] [--no-review]

  Keys: up/down move, space ticks, enter continues, left (or b) goes BACK a
  step, q quits. The review can jump to any step and change just that answer.
  TS_WIZ_PLAIN=1 uses numbered prompts instead (type < to go back).

  --emit sh       shell `export NAME=value` lines, for a bootstrap to source
  --emit json     one object, for the PowerShell bootstrap
  --out PATH      where to write them (required with --emit)
  --only apps     just the CLI tool picker, no review
  --answers FILE  answers from a JSON file (the shape --emit json writes);
                  questions it answers are skipped, the rest are asked.
                  TS_WIZ_ANSWERS=FILE does the same through an installer.
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
    only = ""
    ask_terminals = False
    assume_yes = False
    no_review = False
    # TS_WIZ_ANSWERS is the same thing through the environment, which is how it
    # reaches the wizard through an installer (`TS_WIZ_ANSWERS=a.json
    # ./install-mac.sh`) without either shim growing a flag.
    env_answers = os.environ.get("TS_WIZ_ANSWERS", "").strip()
    answers_path: Path | None = Path(env_answers) if env_answers else None

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
        elif item == "--only":
            if not rest or rest[0] not in ("apps",):
                print("tstack wizard: --only takes apps", file=sys.stderr)
                return 2
            only = rest.pop(0)
        elif item == "--answers":
            if not rest:
                print("tstack wizard: --answers needs a file", file=sys.stderr)
                return 2
            answers_path = Path(rest.pop(0))
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

    if answers_path is not None:
        try:
            preset = answers_file.load(answers_path)
        except answers_file.AnswersError as exc:
            print(f"tstack wizard: --answers: {exc}", file=sys.stderr)
            return 2
        # The variables each question already honours. An explicit TS_* in the
        # environment wins over the file: it is the more deliberate act.
        for name, value in preset.items():
            os.environ.setdefault(name, value)

    # Documented everywhere as "takes every default without prompting", and the
    # shell shim passes --assume-yes when it is set. Reading it here too means
    # `TS_ASSUME_YES=1 tstack wizard` behaves the same as through the shim --
    # otherwise the flag works only on the path nobody types.
    if os.environ.get("TS_ASSUME_YES", "").strip() not in ("", "0", "no", "false"):
        assume_yes = True

    # --assume-yes means "take every default without prompting" (as documented
    # in tstack config's help and INSTALL.md), so it gets a console with nobody
    # at it: every question takes its default -- which is this machine's saved
    # answer -- and the review is skipped. It used to skip only the review and
    # still ask every question on a terminal.
    console = Console() if assume_yes else Console.open()
    # No --emit means a person typed `tstack wizard` and nothing will be saved.
    # It must say so before the first question and again at the end: it used to
    # end on "[P]roceed", return to the prompt silently, and leave the user
    # wondering why none of their answers took effect.
    preview = not emit_as
    try:
        if preview:
            _say_preview_banner(console)
        if only == "apps":
            # One question, no review: the caller asked for the picker, not the
            # questionnaire.
            picked = flow.run(console, only_apps=True, preview=preview)
            if picked is None:
                return QUIT
            if preview:
                _say_preview_footer(console)
            return _emit(picked, emit_as, out)
        confirmed = flow.run(
            console,
            ask_terminals=ask_terminals,
            assume_yes=assume_yes,
            preview=preview,
            review_screen=not no_review,
        )
        if confirmed is None:
            return QUIT
        answers = confirmed
        if no_review:
            flow.review(console, answers)
        if preview:
            _say_preview_footer(console)
    finally:
        console.close()

    return _emit(answers, emit_as, out)


def _say_preview_banner(console: Console) -> None:
    console.say()
    console.say("==> tstack wizard: PREVIEW MODE - nothing you answer here is saved.")
    console.say("    Answer the questions to see what you would get. To save and apply")
    console.say("    them, quit (Ctrl+C) and run:  tstack config wizard")


def _say_preview_footer(console: Console) -> None:
    console.say()
    console.say("==> Preview finished. NOTHING was saved, installed or changed.")
    console.say("    To save and apply these answers, run:")
    console.say("      tstack config wizard     the same questions, then saves and applies")
    console.say("    Or change one setting at a time:")
    console.say("      tstack config            the settings menu (shows what is saved now)")
    console.say("      tstack config -h         every setting and the command that changes it")


def _emit(answers: flow.Answers, emit_as: str, out: Path | None) -> int:
    if not emit_as or out is None:
        return 0
    try:
        body = emit.to_sh(answers) if emit_as == "sh" else emit.to_json(answers)
        emit.write(out, body)
    except (OSError, ValueError) as exc:
        print(f"tstack wizard: could not write {out}: {exc}", file=sys.stderr)
        return 1
    return 0
