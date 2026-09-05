"""`tstack herdr` - the managed herdr config.

A thin entry point over `tstack/herdr.py`, the same split `tstack ghostty` has
over `tstack/ghostty.py`. Top-level for the reason `mux` and `wezterm` are:
`tstack config herdr` in either shell hands off here, so there is one
implementation rather than a bash one and a pwsh one drifting apart.
"""

from __future__ import annotations

import sys

from .. import herdr, store

HELP = """tstack herdr - the managed herdr config.

Usage:
  tstack herdr [status]   the setting, the config file, the binary and the servers
  tstack herdr on         manage it, and splice our key in now
  tstack herdr off        stop, and RESTORE your backup (or remove just our key)
  tstack herdr update     say whether a newer herdr exists; never installs it

The stack owns exactly one key in herdr's config, `[theme] name`, set to
"terminal" so herdr uses the palette the terminal already has - correct in dark,
light and follow alike. Every other byte of that file is yours and survives a
write untouched, because herdr and you both edit it too.

`off` acts on THIS machine only, and never deletes the file: a .chezmoiremove
rule or a sync-side delete would run everywhere, and the file is mostly yours."""

VERBS = ("status", "on", "off", "update")


def say(message: str) -> None:
    print(message)


def _apply() -> None:
    """Re-render after a save.

    The config file itself is written by `tstack/herdr.py`, not by chezmoi - it
    is a key splice into someone else's file. What this refreshes is the store:
    `chezmoi init` regenerates the derived keys and the Windows mirror, which is
    what makes the setting visible to the other side of a combined machine.
    """
    store.chezmoi_init()


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0

    dry_run = "--dry-run" in argv
    rest = [a for a in argv if a != "--dry-run"]
    verb = rest[0] if rest else "status"
    if verb not in VERBS:
        print(f"tstack herdr: unknown action '{verb}' (try: {', '.join(VERBS)})", file=sys.stderr)
        return 2
    if len(rest) > 1:
        print(f"tstack herdr: unexpected argument '{rest[1]}'", file=sys.stderr)
        return 2

    if verb == "status":
        return herdr.status(say)
    if verb == "update":
        return herdr.report_update(say)
    if dry_run:
        say(f"==> would set herdrConfig = {verb}")
        return 0
    if verb == "on":
        return herdr.turn_on(say, _apply)
    return herdr.turn_off(say, _apply)
