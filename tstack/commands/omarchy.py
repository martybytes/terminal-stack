"""`tstack omarchy` - the Omarchy desktop integration.

A thin entry point over `tstack/omarchy.py`, the same split `tstack ghostty` has
over `tstack/ghostty.py`.

Two of the verbs are not for people: `theme-changed` and `update-check` are what
the installed hooks exec. They live here rather than in the hook scripts because
a hook is bash in a desktop event handler -- the worst place to keep logic and
the hardest to test -- and because `tstack omarchy status` has to be able to say
what they would do.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .. import omarchy, paths, store
from .. import platform as plat

HELP = """tstack omarchy - the Omarchy desktop integration.

Usage:
  tstack omarchy [status]   what is installed, and whether it is current
  tstack omarchy sync       install or refresh the theme template and hooks
  tstack omarchy on         turn it back on, and sync
  tstack omarchy off        remove the files, on THIS machine, and remember

Installs three files into Omarchy's own extension points: a WezTerm theme
template (`~/.config/omarchy/themed/wezterm.lua.tpl`, rendered on every
`omarchy theme set`) and hooks for `theme-set` and `post-update`. Nothing
Omarchy or your stow tree owns is edited.

Omarchy only. `off` is per machine, because these files only exist where Omarchy
does."""

VERBS = ("status", "sync", "on", "off", "theme-changed", "update-check")


def say(message: str) -> None:
    print(message)


def _wezterm_configs() -> list[Path]:
    """The config files WezTerm watches on this machine.

    Touching one is what makes a running instance reload. WezTerm watches its
    OWN config, not the generated theme file beside it, so a theme change reaches
    nothing until this happens.
    """
    home = Path.home()
    return [home / ".wezterm.lua", home / ".config" / "wezterm" / "wezterm.lua"]


def _theme_changed(slug: str) -> int:
    """The `theme-set.d` hook's body.

    Deliberately cheap on the common path. Flicking through the theme picker
    fires this on every keystroke, so a full `chezmoi apply` per theme is not
    acceptable -- and it is not needed: only a light<->dark FLIP changes anything
    the stack bakes. Omarchy's colors.toml states the mode outright, so the
    comparison is exact rather than inferred from gsettings.
    """
    mode = omarchy.theme_mode()
    if slug:
        say(f"==> omarchy theme: {slug} ({mode or 'mode unknown'})")

    follow = mode and store.get("themeMode", "dark") == "follow"
    if follow and store.get("resolvedTheme", "") != mode:
        store.set("resolvedTheme", mode)
        store.chezmoi_init()
        chezmoi = plat.find_chezmoi()
        if chezmoi:
            say(f"==> palette flipped to {mode}; re-applying")
            subprocess.run([chezmoi, "apply"], check=False, timeout=900)

    # Always nudge WezTerm, flip or not: the per-theme colours changed even when
    # the light/dark mode did not, and those come from the generated file.
    for config in _wezterm_configs():
        if config.exists():
            os.utime(config, None)
    return 0


def _update_check() -> int:
    """The `post-update.d` hook's body: report, never pull.

    `tstack update` is a zsh function (commands.conf: `update @_tstack_update`)
    and carries behaviour a bash hook cannot call and must not reimplement -- the
    dirty-clone refusal, the rollback point, the duplicate-clone warning. So this
    fetches and says what is waiting, and leaves the decision where it belongs.
    """
    try:
        source = paths.resolve_source_dir()
    except paths.CloneNotFound:
        return 0
    git = ["git", "-C", str(source)]
    try:
        subprocess.run([*git, "fetch", "--quiet"], check=False, timeout=120)
        out = subprocess.run(
            [*git, "log", "--oneline", "HEAD..@{u}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    incoming = [line for line in out.stdout.splitlines() if line.strip()]
    if not incoming:
        return 0
    say(f"==> terminal-stack: {len(incoming)} commit(s) waiting in {source}")
    for line in incoming[:5]:
        say(f"      {line}")
    if len(incoming) > 5:
        say(f"      ... and {len(incoming) - 5} more")
    say("    run 'tstack update' to pull and re-apply")
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0

    verb = argv[0] if argv else "status"
    if verb not in VERBS:
        print(
            f"tstack omarchy: unknown action '{verb}' (try: {', '.join(VERBS[:4])})",
            file=sys.stderr,
        )
        return 2

    # The hook verbs run in a desktop event handler with no terminal attached.
    # They must never be able to take the whole `omarchy theme set` or
    # `omarchy update` down with them, whatever goes wrong in here.
    if verb == "theme-changed":
        try:
            return _theme_changed(argv[1] if len(argv) > 1 else "")
        except Exception as exc:
            print(f"tstack omarchy: theme hook failed: {exc}", file=sys.stderr)
            return 0
    if verb == "update-check":
        try:
            return _update_check()
        except Exception as exc:
            print(f"tstack omarchy: update check failed: {exc}", file=sys.stderr)
            return 0

    if len(argv) > 1:
        print(f"tstack omarchy: unexpected argument '{argv[1]}'", file=sys.stderr)
        return 2
    if verb == "status":
        return omarchy.status(say)
    if verb == "sync":
        return omarchy.sync(say)
    if verb == "on":
        return omarchy.turn_on(say)
    return omarchy.turn_off(say)
