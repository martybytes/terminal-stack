"""`tstack ghostty` - the managed Ghostty config.

A thin entry point over `tstack/ghostty.py`, the same split `tstack services` has
over `tstack/stacks.py`. It is a top-level command for the reason `mux` and
`wezterm` are: `tstack config ghostty` in either shell hands off to it, so there
is one implementation instead of the three there used to be.
"""

from __future__ import annotations

import subprocess
import sys

from .. import ghostty, paths, store
from .. import platform as plat

HELP = """tstack ghostty - the managed Ghostty config.

Usage:
  tstack ghostty [status]   the setting, the deployed files, and the binary
  tstack ghostty diff       what an apply would change, without applying it
  tstack ghostty on         manage it, and render it now
  tstack ghostty off        stop, and RESTORE your backup (or remove ours)

macOS and Windows only. Ghostty runs on macOS, and on Windows as
noctty/winghostty; this stack's native-Linux hosts are headless. On WSL the
target is the Windows install, because that is the one with a GUI.

`off` is a real revert rather than "stop managing", and it acts on THIS machine
only: a .chezmoiremove rule or a sync-side delete would run everywhere and wipe a
hand-written config on a box that never opted in."""

VERBS = ("status", "diff", "on", "off")


def say(message: str) -> None:
    print(message)


def _apply() -> None:
    """Re-render after a save, by whichever route this platform applies.

    On Windows there is no chezmoi: `scripts/sync-windows.ps1` is the apply, and
    it is what writes the Ghostty files on that side.
    """
    store.chezmoi_init()
    if plat.kind() == plat.WINDOWS:
        pwsh = plat.find_pwsh()
        try:
            source = paths.resolve_source_dir()
        except paths.CloneNotFound:
            return
        script = source / "scripts" / "sync-windows.ps1"
        if pwsh and script.is_file():
            print("==> applying...")
            subprocess.run(
                [pwsh, "-NoLogo", "-NoProfile", "-File", str(script), "-SourceDir", str(source)],
                check=False,
                timeout=900,
            )
            print("==> done.")
        return
    chezmoi = plat.find_chezmoi()
    if chezmoi:
        print("==> applying...")
        subprocess.run([chezmoi, "apply"], check=False, timeout=900)
        print("==> done.")


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0

    dry_run = "--dry-run" in argv
    rest = [a for a in argv if a != "--dry-run"]
    verb = rest[0] if rest else "status"
    if verb not in VERBS:
        print(f"tstack ghostty: unknown action '{verb}' (try: {', '.join(VERBS)})", file=sys.stderr)
        return 2
    if len(rest) > 1:
        print(f"tstack ghostty: unexpected argument '{rest[1]}'", file=sys.stderr)
        return 2

    try:
        source = paths.resolve_source_dir()
    except paths.CloneNotFound:
        print("tstack ghostty: cannot locate the clone (set TERMINAL_STACK_DIR).", file=sys.stderr)
        return 1

    if verb == "status":
        return ghostty.status(source, say)
    if verb == "diff":
        return ghostty.diff(source, say)
    if dry_run:
        say(f"==> would set ghosttyConfig = {verb}")
        return 0
    if verb == "on":
        return ghostty.turn_on(source, say, _apply)
    return ghostty.turn_off(source, say, _apply)
