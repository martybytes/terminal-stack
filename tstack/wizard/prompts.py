"""The two interactive primitives, and the rules the shell versions earned.

`choice` is one answer from a list; `multi` is a tick-list. Everything the
wizard asks is one of these two, which is why their behaviour is written down
here rather than rediscovered per question.

The bash and pwsh versions had drifted on one of these rules and the bash one is
kept: a multi-answer applies its VALID tokens and warns about the rest, rather
than rejecting the lot. Someone typing `1 3 9` at a six-row list means the first
two, and throwing that away is the kind of thing that makes people stop reading
menus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .console import Console

# Splits a multi answer. Deliberately NOT `choice`'s strip-everything: that would
# fuse "1 2" into "12" and toggle row twelve.
_TOKENS = re.compile(r"[,\s]+")


@dataclass(frozen=True)
class Option:
    key: str
    label: str = ""
    note: str = ""

    def display(self) -> str:
        return self.label or self.key


def _render_intro(console: Console, title: str, intro: tuple[str, ...]) -> None:
    console.say()
    console.say(title)
    for line in intro:
        console.say(line)


def choice(
    console: Console,
    title: str,
    options: list[Option],
    default: str,
    intro: tuple[str, ...] = (),
) -> tuple[str, bool]:
    """One value from a list. Returns (value, asked).

    THE DEFAULT IS RETURNED VERBATIM and is never validated against the options.
    That is load-bearing: the starship-preset question offers what the installed
    starship ships and defaults to whatever is saved, which may be a preset this
    machine no longer has -- and silently rewriting someone's saved value to the
    first row would be worse than offering it back.

    Bounded at three wrong answers, then takes the default. An automated caller
    feeding rubbish can never spin here.
    """
    _render_intro(console, title, intro)
    for index, option in enumerate(options, start=1):
        marker = ">" if option.key == default else " "
        suffix = f"  ({option.note})" if option.note else ""
        if option.key == default:
            suffix += "  [default - press Enter]"
        console.say(f" {marker}  {index}) {option.display()}{suffix}")

    total = len(options)
    if not console.interactive:
        console.say(f"Choose [1-{total}, Enter=default]: (non-interactive - taking the default)")
        return (default, False)

    for _try in range(3):
        raw = console.ask(f"Choose [1-{total}, Enter=default]: ")
        if raw is None:
            return (default, False)
        # Strip ALL whitespace, unlike multi: one answer cannot be two.
        answer = re.sub(r"\s+", "", raw)
        if not answer:
            return (default, True)
        if answer.isdigit() and 1 <= int(answer) <= total:
            return (options[int(answer) - 1].key, True)
        lowered = answer.lower()
        for option in options:
            if option.key.lower() == lowered:
                return (option.key, True)  # the ORIGINAL casing, not what was typed
        console.say(
            f"  '{raw}' is not one of the choices - enter 1-{total}, a name, "
            "or press Enter for the default."
        )
    console.say("  three invalid answers - taking the default.")
    return (default, True)


def collapse_exclusive(
    ticked: list[bool], keys: list[str], groups: tuple[str, ...], keep: int
) -> None:
    """At most one member of an exclusive group stays ticked. Mutates `ticked`.

    `keep` is the index that just won, or -1 for "no winner" -- in which case the
    FIRST ticked member survives, matching the nightly-wins tie-break.

    THE GUARD IS THE WHOLE POINT: a winner only wins its OWN group. Without the
    membership test, `keep` is an index no member equals, every ticked member
    fails `j == keep`, and they are all cleared -- which is how ticking Ghostty
    silently unticked WezTerm on macOS.
    """
    if not groups:
        return
    if keep >= 0 and keys[keep] not in groups:
        return
    first = -1
    for index, key in enumerate(keys):
        if key not in groups or not ticked[index]:
            continue
        if keep >= 0:
            if index != keep:
                ticked[index] = False
        elif first < 0:
            first = index
        else:
            ticked[index] = False


def multi(
    console: Console,
    title: str,
    options: list[Option],
    preticked: list[str],
    intro: tuple[str, ...] = (),
    exclusive: tuple[str, ...] = (),
) -> tuple[list[str], bool]:
    """A tick-list. Returns (chosen keys in option order, asked).

    Unbounded, unlike `choice`: there is no wrong answer to loop on, only
    toggles, and Enter always ends it.
    """
    if not options:
        return ([], False)

    keys = [o.key for o in options]
    ticked = [o.key in preticked for o in options]
    # Before the FIRST render: a machine mid-channel-switch can legitimately have
    # both installed, and showing `[x] [x]` for an exclusive pair invites someone
    # to believe it.
    collapse_exclusive(ticked, keys, exclusive, -1)

    def render() -> None:
        _render_intro(console, title, intro)
        for index, option in enumerate(options):
            mark = "x" if ticked[index] else " "
            suffix = f"  ({option.note})" if option.note else ""
            console.say(f"  [{mark}] {index + 1:>2}) {option.display()}{suffix}")

    def chosen() -> list[str]:
        return [keys[i] for i, on in enumerate(ticked) if on]

    render()
    prompt = "Toggle a number, [a]ll, [n]one, Enter to continue, [s]kip: "
    if not console.interactive:
        console.say(prompt + "(non-interactive - keeping the defaults)")
        return (chosen(), False)

    while True:
        raw = console.ask(prompt)
        if raw is None:
            return (chosen(), False)
        answer = raw.strip().lower()
        if answer == "":
            break
        if answer in ("s", "skip"):
            ticked = [False] * len(options)
            break
        if answer in ("a", "all"):
            ticked = [True] * len(options)
            collapse_exclusive(ticked, keys, exclusive, -1)
            render()
            continue
        if answer in ("n", "no", "none"):
            ticked = [False] * len(options)
            render()
            continue

        bad = False
        for token in _TOKENS.split(raw.strip()):
            if not token.isdigit():
                bad = True
                continue
            index = int(token) - 1
            if not (0 <= index < len(options)):
                bad = True
                continue
            # Partial application: the valid tokens toggle even when a sibling
            # is nonsense. Rejecting the whole answer is the pwsh behaviour, and
            # it is the one that was not kept.
            if ticked[index]:
                ticked[index] = False
            else:
                ticked[index] = True
                collapse_exclusive(ticked, keys, exclusive, index)
        if bad:
            console.say(
                f"  ? enter a number 1-{len(options)} (several are fine), a, n, s, or Enter"
            )
        render()
    return (chosen(), True)


def text(console: Console, prompt: str) -> str:
    """Free text. Empty when there is nobody to ask, which every caller reads as
    "take the default"."""
    answer = console.ask(prompt)
    return (answer or "").strip()
