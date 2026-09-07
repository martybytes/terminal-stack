"""`tstack ui` - the settings dashboard.

Thin on purpose. Its whole job is to turn a missing optional dependency into an
instruction instead of a traceback, because Textual is the only third-party
import in this program and a fresh machine will not have it.

AND THE INSTRUCTION HAS TO BE ONE THAT WORKS

This module used to print three fixed lines -- `uv tool install textual`,
`pipx install textual`, `pip install --user textual` -- and on an Omarchy box all
three FAIL:

    uv tool  : "No executables are provided by package `textual`; removing tool"
    pipx     : "No apps associated with package textual"
    pip      : "zsh: command not found: pip"

The first two are not a platform quirk. `uv tool` and `pipx` install
APPLICATIONS into isolated venvs and refuse a package with no entry points --
textual is a library, and its CLI lives in the separate `textual-dev` package.
Those two could never have worked, anywhere. The third is Arch not shipping a
bare `pip`, plus PEP 668 refusing the write even where it exists.

So the advice is PROBED rather than listed, the way the wizard's toggles are, and
it leads with the no-install path because that one needs nothing decided.
"""

from __future__ import annotations

import os
import shutil
import sys
import sysconfig

from .. import platform as plat

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

Needs Textual, which nothing else in tstack does. Run `tstack ui` without it and
it prints the way to get it on THIS machine."""


def _externally_managed() -> bool:
    """PEP 668: this interpreter refuses `pip install` without an override.

    The marker is a file next to the stdlib, which is what pip itself reads --
    so this agrees with pip rather than guessing from the distro.
    """
    return os.path.exists(os.path.join(sysconfig.get_path("stdlib"), "EXTERNALLY-MANAGED"))


def _install_hint() -> list[str]:
    """How to make `import textual` work for THIS interpreter, best first."""
    lines = []

    # No install at all, and nothing to decide about where things land. uv is in
    # this stack's own app catalog, so it is usually already here.
    if shutil.which("uv"):
        clone = os.environ.get("TERMINAL_STACK_DIR", "")
        script = os.path.join(clone, "tstack", "main.py") if clone else "tstack/main.py"
        lines += [
            "  Run it once, installing nothing:",
            f"    uv run --with textual {script} ui",
            "",
        ]

    # A distro package, but ONLY where the distro ships a current one. Arch has
    # 8.2.8; Debian 13 has 2.1.2 and Ubuntu 24.04 still has 0.1.13, old enough
    # that naming it would send someone to a version this app cannot use.
    if plat.is_arch():
        lines += ["  Or install it for the system python:", "    sudo pacman -S python-textual", ""]
    else:
        flag = " --break-system-packages" if _externally_managed() else ""
        lines += [
            "  Or install it for the system python:",
            f"    python3 -m pip install --user{flag} textual",
            "",
        ]

    lines += [
        "  Not `uv tool install` or `pipx install`: both install APPLICATIONS and",
        "  refuse a package with no entry points. textual is a library -- its CLI",
        "  is the separate `textual-dev` package -- so neither can ever work.",
    ]
    return lines


def missing() -> str:
    return "\n".join(
        [
            "tstack ui: needs Textual, which is not installed.",
            "",
            *_install_hint(),
            "",
            "It is the only third-party library this program uses, and only this command",
            "uses it - everything else runs on the standard library so a fresh machine can",
            "run `tstack doctor` before anything is installed.",
            "",
            "Meanwhile the same settings are on the command line:",
            "  tstack config show",
        ]
    )


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
        print(missing(), file=sys.stderr)
        return 1
    SettingsApp().run()
    return 0
