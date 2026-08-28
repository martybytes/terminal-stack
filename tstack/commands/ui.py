"""`tstack ui` - the settings dashboard.

Thin on purpose. Its whole job is to turn a missing optional dependency into an
instruction instead of a traceback, because Textual is the only third-party
import in this program and a fresh machine will not have it.
"""

from __future__ import annotations

import sys

HELP = """tstack ui - every saved setting, what it is now, and where it came from.

Usage:
  tstack ui

  /        filter by key, label, group, value or note
  Enter    edit the selected setting
  Space    next value        (choice settings; saves straight away)
  d        back to default
  r        reload from the store
  q        quit

Writes go through the same setter the command line uses, so the schema's rules
apply here too: a value chezmoi derives from your other choices is shown and
refused, not silently written and then regenerated.

Needs Textual, which nothing else in tstack does:
  uv tool install textual   (or: pipx install textual, or: pip install textual)"""

MISSING = """tstack ui: needs Textual, which is not installed.

  uv tool install textual
  pipx install textual
  pip install --user textual

It is the only third-party library this program uses, and only this command uses
it - everything else runs on the standard library so a fresh machine can run
`tstack doctor` before anything is installed.

Meanwhile the same settings are on the command line:
  tstack config show"""


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0
    if argv:
        print(f"tstack ui: unexpected argument '{argv[0]}' (try -h)", file=sys.stderr)
        return 2
    try:
        from ..ui.app import SettingsApp
    except ImportError:
        print(MISSING, file=sys.stderr)
        return 1
    SettingsApp().run()
    return 0
