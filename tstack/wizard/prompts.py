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

import os
import re
from dataclasses import dataclass

from . import console as keys
from .console import Console

# Returned instead of an answer. Strings, so every primitive keeps returning a
# `str`/`list[str]`; the NUL makes them impossible to type or to be an option key.
BACK = "\x00back"
QUIT = "\x00quit"

# Splits a multi answer. Deliberately NOT `choice`'s strip-everything: that would
# fuse "1 2" into "12" and toggle row twelve.
_TOKENS = re.compile(r"[,\s]+")


@dataclass(frozen=True)
class Option:
    key: str
    label: str = ""
    note: str = ""
    # Shown under the list while this row is highlighted (arrow-key mode only):
    # the rendered prompt for each Starship preset, for instance.
    preview: str = ""
    # Rows sharing a group are drawn under one heading (arrow-key mode only).
    group: str = ""

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
        if answer in ("<", "back"):
            return (BACK, True)
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
        if answer in ("<", "back"):
            return ([BACK], True)
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


# ---------------------------------------------------------------------------
# Arrow-key widgets. Used when Console.tui is true; the numbered prompts above
# are the fallback and stay byte-for-byte what they were.
# ---------------------------------------------------------------------------

_COLOUR = not os.environ.get("NO_COLOR")


def _sgr(code: str, text_: str) -> str:
    return f"\x1b[{code}m{text_}\x1b[0m" if _COLOUR and text_ else text_


def bold(text_: str) -> str:
    return _sgr("1", text_)


def dim(text_: str) -> str:
    return _sgr("2", text_)


def accent(text_: str) -> str:
    return _sgr("1;36", text_)


def _clip(text_: str, width: int) -> str:
    return text_ if len(text_) <= width else text_[: max(0, width - 3)] + "..."


def _row(lead: str, label: str, note: str, here: bool, cols: int) -> str:
    """One list row that fits on one line: the NOTE gives way first, then the
    label. Measured on the plain text, coloured afterwards."""
    room = cols - 1 - len(lead)
    if len(label) > room:
        label, note = _clip(label, room), ""
    elif note and len(label) + 2 + len(note) > room:
        spare = room - len(label) - 2
        note = _clip(note, spare) if spare >= 12 else ""
    shown = accent(label) if here else label
    return f"{lead}{shown}" + (f"  {dim(note)}" if note else "")


def frame(
    console: Console,
    header: str,
    title: str,
    intro: tuple[str, ...],
    body: list[str],
    footer: str,
    extra: tuple[str, ...] = (),
) -> None:
    """One full screen: header rule, title, intro, body, extra, key hints."""
    cols, _rows = console.size()
    rule = "-" * min(cols - 1, 78)
    lines = [dim(header), dim(rule), "", bold(title)]
    lines += list(intro)
    lines.append("")
    lines += body
    if extra:
        lines.append("")
        lines += list(extra)
    lines += ["", dim(rule), dim(footer)]
    console.draw(lines)


def _window(count: int, cursor: int, room: int) -> tuple[int, int]:
    """The [start, end) slice of `count` rows to show so `cursor` is visible."""
    room = max(5, room)
    if count <= room:
        return (0, count)
    start = min(max(0, cursor - room // 2), count - room)
    return (start, start + room)


def _confirm_quit(console: Console) -> bool:
    console.say("")
    console.say("  Quit setup? Nothing has been installed or changed.  [y/N]")
    reply = console.key()
    return reply in ("y", "Y")


def select(
    console: Console,
    title: str,
    options: list[Option],
    default: str,
    intro: tuple[str, ...] = (),
    header: str = "",
) -> tuple[str, bool]:
    """One value, chosen with the arrow keys. Returns (value | BACK | QUIT, True).

    Same contract as `choice`: the default is returned verbatim even when it is
    not one of the rows, by pressing Enter without moving (a saved Starship
    preset this machine no longer ships stays saved).
    """
    keys_ = [o.key for o in options]
    cursor = keys_.index(default) if default in keys_ else 0
    moved = False
    footer = "up/down move   enter choose   left/b back   q quit"
    while True:
        cols, rows = console.size()
        room = rows - len(intro) - 12
        start, end = _window(len(options), cursor, room)
        body: list[str] = []
        if start:
            body.append(dim(f"     ... {start} more above"))
        for index in range(start, end):
            option = options[index]
            here = index == cursor
            radio = "(*)" if option.key == default else "( )"
            lead = f" {'>' if here else ' '} {radio} "
            body.append(_row(lead, option.display(), option.note, here, cols))
        if end < len(options):
            body.append(dim(f"     ... {len(options) - end} more below"))
        preview = options[cursor].preview if options else ""
        frame(
            console,
            header,
            title,
            intro,
            body,
            footer,
            tuple(preview.splitlines()) if preview else (),
        )
        key = console.key()
        if key in (keys.UP, "k") and cursor > 0:
            cursor, moved = cursor - 1, True
        elif key in (keys.DOWN, "j") and cursor < len(options) - 1:
            cursor, moved = cursor + 1, True
        elif key == keys.HOME:
            cursor, moved = 0, True
        elif key == keys.END:
            cursor, moved = len(options) - 1, True
        elif key.isdigit() and 1 <= int(key) <= len(options):
            cursor, moved = int(key) - 1, True
        elif key in (keys.ENTER, keys.RIGHT, keys.SPACE):
            if not options:
                return (default, True)
            if not moved and default not in keys_:
                return (default, True)
            return (options[cursor].key, True)
        elif key in (keys.LEFT, keys.BACKSPACE, "b", "h"):
            return (BACK, True)
        elif key in ("q", "Q", keys.ESC) and _confirm_quit(console):
            return (QUIT, True)


def checklist(
    console: Console,
    title: str,
    options: list[Option],
    preticked: list[str],
    intro: tuple[str, ...] = (),
    exclusive: tuple[str, ...] = (),
    header: str = "",
    presets: dict[str, tuple[str, list[str]]] | None = None,
) -> tuple[list[str], bool]:
    """A tick-list driven by the arrow keys and space.

    Returns (chosen keys in option order, True), or ([BACK]) / ([QUIT]).
    `presets` maps a hotkey to (label, keys): pressing it replaces the ticks
    with that set -- r for the recommended set, k to keep what is saved.
    """
    if not options:
        return ([], False)
    keys_ = [o.key for o in options]
    ticked = [o.key in preticked for o in options]
    collapse_exclusive(ticked, keys_, exclusive, -1)
    presets = presets or {}
    cursor = 0
    hints = "up/down move   space tick   a all   n none"
    for hotkey, (label, _ids) in presets.items():
        hints += f"   {hotkey} {label}"
    footer = hints + "   enter continue   left/b back   q quit"

    while True:
        cols, rows = console.size()
        groups = len({o.group for o in options if o.group})
        room = rows - len(intro) - 12 - groups
        start, end = _window(len(options), cursor, room)
        body: list[str] = []
        if start:
            body.append(dim(f"     ... {start} more above"))
        last_group = options[start - 1].group if start else None
        for index in range(start, end):
            option = options[index]
            if option.group and option.group != last_group:
                body.append(bold(f"   {option.group}"))
            last_group = option.group
            here = index == cursor
            box = "[x]" if ticked[index] else "[ ]"
            lead = f" {'>' if here else ' '} {box} "
            body.append(_row(lead, option.display(), option.note, here, cols))
        if end < len(options):
            body.append(dim(f"     ... {len(options) - end} more below"))
        count = sum(ticked)
        frame(console, header, title, intro, body, footer, (dim(f"  {count} selected"),))
        key = console.key()
        if key in (keys.UP, "k") and cursor > 0:
            cursor -= 1
        elif key in (keys.DOWN, "j") and cursor < len(options) - 1:
            cursor += 1
        elif key == keys.PGUP:
            cursor = max(0, cursor - max(5, room))
        elif key == keys.PGDN:
            cursor = min(len(options) - 1, cursor + max(5, room))
        elif key == keys.HOME:
            cursor = 0
        elif key == keys.END:
            cursor = len(options) - 1
        elif key in (keys.SPACE, "x"):
            ticked[cursor] = not ticked[cursor]
            if ticked[cursor]:
                collapse_exclusive(ticked, keys_, exclusive, cursor)
        elif key == "a":
            ticked = [True] * len(options)
            collapse_exclusive(ticked, keys_, exclusive, -1)
        elif key == "n":
            ticked = [False] * len(options)
        elif key in presets:
            wanted = set(presets[key][1])
            ticked = [k in wanted for k in keys_]
            collapse_exclusive(ticked, keys_, exclusive, -1)
        elif key in (keys.ENTER, keys.RIGHT):
            return ([keys_[i] for i, on in enumerate(ticked) if on], True)
        elif key in (keys.LEFT, keys.BACKSPACE, "b", "h"):
            return ([BACK], True)
        elif key in ("q", "Q", keys.ESC) and _confirm_quit(console):
            return ([QUIT], True)


def text(console: Console, prompt: str) -> str:
    """Free text. Empty when there is nobody to ask, which every caller reads as
    "take the default"."""
    answer = console.ask(prompt)
    return (answer or "").strip()
