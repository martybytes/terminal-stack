"""`tstack reinstall` - the one-liner install, run again from the clone you have.

The documented installers (`curl ... | bash`, `irm ... | iex`) fetch a script,
find or clone the runtime clone, then run the bootstrap, the apply and doctor.
This does the same thing with what is already on disk: pull the runtime clone
FIRST, so the installer that runs is the one just pulled, then run that
installer from the clone, pinned to it. No script download, no clone-location
questions, and the questionnaire opens with this machine's saved answers as the
defaults.

The installer is run, not reimplemented. Four installers already encode every
ordering incident this repo has had, and a fifth copy is how two of them came to
disagree in the first place.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .. import paths, proc
from .. import platform as plat

HELP = """tstack reinstall - pull the latest stack, then run the installer again, locally.

Usage:
  tstack reinstall [--no-pull] [--dry-run]

In order:
  1. refuses a runtime clone with uncommitted changes, as update does
  2. fetches, returns a clone whose branch is gone to main, records a
     rollback point (tstack rollback), and pulls --ff-only
  3. runs the freshly pulled installer for this platform from the clone:
     install-wsl.sh, install-linux.sh, install-mac.sh or install.ps1

Everything the one-liner does follows - the questionnaire (your saved answers
are the defaults), the bootstrap, chezmoi apply and doctor - without
downloading anything or asking where the clone lives.

  --no-pull   reinstall the commit you already have
  --dry-run   say what would run and change nothing

exit status: the installer's own; 1 when the clone cannot be updated."""

INSTALLERS = {
    plat.WSL: "install-wsl.sh",
    plat.LINUX: "install-linux.sh",
    plat.MACOS: "install-mac.sh",
    plat.WINDOWS: "install.ps1",
}


def _git(src: Path, *args: str, timeout: int = 120) -> tuple[int, str]:
    out = proc.capture(["git", "-C", str(src), *args], timeout=timeout)
    if out is None:
        return 1, ""
    return out.returncode, (out.stdout or "").strip()


def pull(src: Path, dry_run: bool) -> bool:
    """Bring the clone to its upstream. False, having said why, when it cannot."""
    rc, dirty = _git(src, "status", "--porcelain")
    if rc != 0:
        print(f"tstack reinstall: {src} is not a git clone.", file=sys.stderr)
        return False
    if dirty:
        print(
            "tstack reinstall: runtime clone has uncommitted changes; refusing to pull.",
            file=sys.stderr,
        )
        for line in dirty.splitlines():
            print(f"  {line}", file=sys.stderr)
        print(
            "  Make changes in the workspace dev clone, commit them, then rerun."
            " (--no-pull reinstalls what is there.)",
            file=sys.stderr,
        )
        return False

    # --prune, or a branch deleted on the remote still looks alive through its
    # stale remote-tracking ref -- the same trap `tstack update` documents.
    rc, _ = _git(src, "fetch", "--quiet", "--prune", "origin", timeout=300)
    if rc != 0:
        print(
            "tstack reinstall: git fetch failed (offline?). Rerun with --no-pull to"
            " reinstall the commit you have.",
            file=sys.stderr,
        )
        return False

    rc, upstream = _git(src, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    _, branch = _git(src, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        # Gone from the remote, or detached: nothing can be pulled on it, so
        # return to the release branch, as the installers do.
        print(
            f"==> '{branch or 'HEAD'}' has no upstream on the remote;"
            f" returning to {paths.RELEASE_BRANCH}"
        )
        if not dry_run:
            rc, _ = _git(src, "checkout", paths.RELEASE_BRANCH)
            if rc != 0:
                print(
                    f"tstack reinstall: could not switch {src} to {paths.RELEASE_BRANCH}.",
                    file=sys.stderr,
                )
                return False
    elif branch != paths.RELEASE_BRANCH:
        # A live branch may be a deliberate test of unreleased work. Pull it; the
        # installer's own branch check then asks whether to switch.
        print(f"==> note: clone is on '{branch}', not {paths.RELEASE_BRANCH}; pulling {upstream}")

    _, incoming = _git(src, "log", "--oneline", "HEAD..@{u}")
    if not incoming:
        print("==> already up to date")
        return True
    print("==> incoming changes:")
    for line in incoming.splitlines():
        print(f"  {line}")
    if dry_run:
        return True
    _, head = _git(src, "rev-parse", "HEAD")
    # Written only when something is incoming, as update does: a no-op run must
    # not clobber the last real rollback point.
    state = plat.state_dir()
    state.mkdir(parents=True, exist_ok=True)
    (state / "rollback-sha").write_text(head + "\n", encoding="utf-8")
    print(f"==> recorded rollback point: {head[:7]} (tstack rollback to undo)")
    rc, _ = _git(src, "pull", "--ff-only", timeout=300)
    if rc != 0:
        print("tstack reinstall: git pull --ff-only failed.", file=sys.stderr)
        return False
    return True


def installer_argv(src: Path, kind: str) -> list[str] | None:
    script = src / INSTALLERS[kind]
    if not script.is_file():
        return None
    if kind == plat.WINDOWS:
        pwsh = plat.find_pwsh()
        if not pwsh:
            return None
        return [pwsh, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    return ["bash", str(script)]


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0
    unknown = [a for a in argv if a not in ("--no-pull", "--dry-run")]
    if unknown:
        print(f"tstack reinstall: unknown option {unknown[0]}", file=sys.stderr)
        return 2
    no_pull = "--no-pull" in argv
    dry_run = "--dry-run" in argv

    try:
        src = paths.resolve_source_dir(warn=lambda m: print(f"  {m}", file=sys.stderr))
    except paths.CloneNotFound as exc:
        print(f"tstack reinstall: {exc}", file=sys.stderr)
        return 1
    kind = plat.kind()
    print(f"==> clone: {src}")

    if not no_pull and not pull(src, dry_run):
        return 1

    cmd = installer_argv(src, kind)
    if cmd is None:
        print(
            f"tstack reinstall: no runnable {INSTALLERS[kind]} in {src}"
            + (" (pwsh not found)" if kind == plat.WINDOWS else ""),
            file=sys.stderr,
        )
        return 1
    print(f"==> running {INSTALLERS[kind]} from the clone")
    if dry_run:
        print(f"    would run: TERMINAL_STACK_DIR={src} {' '.join(cmd)}")
        return 0

    # The pin is what makes it local: every installer takes a live
    # TERMINAL_STACK_DIR as the clone location and skips the question, finds
    # the clone already there, and pulls (a no-op now) instead of cloning.
    env = {**os.environ, "TERMINAL_STACK_DIR": str(src)}
    # Deliberately NOT proc.capture, and deliberately no start_new_session: the
    # installer asks its questions on /dev/tty, which a child in its own session
    # has no controlling terminal to open -- and the questionnaire would take
    # every default in silence. Output streams straight to the terminal.
    return subprocess.run(cmd, env=env, check=False).returncode
