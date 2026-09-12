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

AND BETTER THAN AN INSTRUCTION IS DOING IT

Correct advice is still a wall. The reader has asked for a dashboard, and what
they get is a paragraph, a command to copy, and a second run of the thing they
already ran. So the command OFFERS, once, to fetch Textual itself and go straight
into the dashboard -- with permission, never silently, and never at all when
there is no terminal to ask on.

What it offers is probed on a different axis from the printed advice. That text
leads with `uv run` because it needs nothing decided; the offer leads with a real
install because it is about to solve the problem PERMANENTLY -- `uv run --with`
resolves into a cache and leaves `import textual` no more possible than before,
so the next `tstack ui` would ask again. pacman is left to the printed hint
rather than put behind a sudo prompt nobody asked for.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

from .. import platform as plat

# `<clone>/tstack/main.py` -- the file every entry point already runs. Resolved
# from this module rather than from TERMINAL_STACK_DIR so a dev clone re-runs
# ITSELF, not whatever that pin happens to name.
ENTRY = Path(__file__).resolve().parents[1] / "main.py"

HEADER = "tstack ui: needs Textual, which is not installed."

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
it offers to fetch it and open the dashboard; decline, or run somewhere with no
terminal to ask on, and it prints the way to get it on THIS machine instead.
TS_UI_INSTALL=1 accepts the offer unasked; TS_UI_INSTALL=0 never offers."""


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


def missing(*, header: bool = True) -> str:
    """The full explanation. `header=False` when the caller has already said it
    -- the offer has to name the problem before it can ask about fixing it, and
    saying it twice reads like a bug."""
    return "\n".join(
        [
            *([HEADER, ""] if header else []),
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


def _pip_install() -> list[str] | None:
    """`pip install textual` for THIS interpreter, or None if pip cannot do it.

    `-m pip` rather than a `pip` on PATH: Arch ships no bare `pip`, and a `pip`
    that IS on PATH may belong to a different interpreter than the one running
    this, which is the one that has to import textual afterwards.
    """
    if importlib.util.find_spec("pip") is None:
        return None
    argv = [sys.executable, "-m", "pip", "install"]
    if sys.prefix == sys.base_prefix:
        # Only outside a venv. Inside one `--user` is an error ("User
        # site-packages are not visible in this virtualenv"), and pointless.
        argv.append("--user")
    if _externally_managed():
        argv.append("--break-system-packages")
    return [*argv, "textual"]


def _plan() -> tuple[str, list[str] | None, list[str]] | None:
    """(what permission is for, install command or None, command that then runs
    the dashboard). None when this machine has nothing to offer."""
    pip = _pip_install()
    if pip:
        where = "your user site-packages" if "--user" in pip else "this environment"
        return (
            f"Install Textual into {where} and open the dashboard",
            pip,
            [sys.executable, str(ENTRY), "ui"],
        )
    uv = shutil.which("uv")
    if uv:
        # Nothing lands outside uv's cache, so this run works and the next one
        # asks again. Second choice for exactly that reason.
        return (
            "Fetch Textual through uv and open the dashboard, installing nothing",
            None,
            [uv, "run", "--with", "textual", str(ENTRY), "ui"],
        )
    return None


def _confirm(question: str, *, default_yes: bool) -> bool:
    # Both halves: a cron run has a tty on neither, and a piped `tstack ui | cat`
    # would otherwise block on a question nobody can see.
    if not (sys.stdin.isatty() and sys.stderr.isatty()):
        return False
    print(f"  {question}? {'[Y/n]' if default_yes else '[y/N]'} ", end="", file=sys.stderr)
    sys.stderr.flush()
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return False
    return answer in (("", "y", "yes") if default_yes else ("y", "yes"))


def _spawn(argv: list[str]) -> int:
    """Inherit this terminal -- deliberately NOT proc.capture(). A TUI needs the
    real stdin and stdout, and a captured pip hides the one part worth watching.

    TS_UI_INSTALL=0 stops the child offering all over again if the install
    reported success and `import textual` still fails.
    """
    try:
        return subprocess.call(argv, env={**os.environ, "TS_UI_INSTALL": "0"})
    except OSError as exc:
        print(f"tstack ui: could not run {argv[0]}: {exc}", file=sys.stderr)
        return 1


def offer() -> int | None:
    """Ask to fetch Textual and go straight into the dashboard.

    None means the caller should print the full explanation instead: nothing to
    offer here, no terminal to ask on, a declined offer, or a failed install.

    Its own knob, and NOT TS_ASSUME_YES. That variable means "take every
    default", and the default for a real install is no -- so reading it as yes
    would invert it. It is also set for every parity container, which would have
    made an unattended `tstack ui` reach the network and write to site-packages
    there. TS_UI_INSTALL=1 accepts unasked, 0 never offers.
    """
    want = os.environ.get("TS_UI_INSTALL", "").strip().lower()
    if want in ("0", "no", "false", "off"):
        return None
    plan = _plan()
    if plan is None:
        return None
    question, install, run = plan
    # A real install defaults to no. The uv path writes nothing outside a cache,
    # so it defaults to yes -- the difference in the brackets is the difference
    # in what the answer costs.
    if want not in ("1", "yes", "true", "on") and not _confirm(
        question, default_yes=install is None
    ):
        return None
    if install is not None:
        print(f"  $ {' '.join(install)}", file=sys.stderr)
        if _spawn(install) != 0:
            print("tstack ui: that install failed.", file=sys.stderr)
            return None
    return _spawn(run)


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
        print(HEADER, file=sys.stderr)
        print(file=sys.stderr)
        code = offer()
        if code is not None:
            return code
        print(missing(header=False), file=sys.stderr)
        return 1
    SettingsApp().run()
    return 0
