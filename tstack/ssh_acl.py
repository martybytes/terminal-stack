r"""Windows OpenSSH ignores a key that anyone else can open. Find those, and fix them.

Windows OpenSSH (ssh, and sshd for authorized_keys) refuses a file with an ALLOW
ACE for anybody except the owner, SYSTEM and Administrators:

    Bad permissions. Try removing permissions for user: HOST\CodexSandboxUsers ...
    Load key "C:\Users\you/.ssh/id_ed25519": bad permissions

The key is then skipped without an error, so the user sees `Permission denied
(publickey)` from the server and assumes the problem is on the server side.

The first case seen on a real machine came from Codex's Windows sandbox. It adds
an explicit `CodexSandboxUsers:(OI)(CI)(RX)` to the PROFILE ROOT, and every file
under it inherits that ACE, `~\.ssh` included. Removing it from the profile root
does not last, because Codex owns it and puts it back. So the fix breaks
inheritance on `~\.ssh` only: owner, SYSTEM and Administrators get full control,
and the children are reset so they inherit from that. It needs no elevation,
because the owner can always rewrite the DACL. It also means a sandboxed agent
can no longer read your private keys.

This is a doctor check rather than an install step, because the ACE arrives
whenever Codex is installed or updated, which is usually long after our install
ran. Windows only: on POSIX ssh gives its own `chmod 600` message, and the stack
never creates keys there.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from . import proc

SYSTEM_SID = "S-1-5-18"
ADMINS_SID = "S-1-5-32-544"

# What `icacls` prints for those two SIDs on an English install. On other
# locales the names are resolved through the API (see _well_known_names).
_ENGLISH = {"nt authority\\system", "builtin\\administrators"}

# ACE line: `PRINCIPAL:(flag)(flag)...`. The principal may contain spaces
# (`NT AUTHORITY\SYSTEM`) but never a colon followed by a parenthesis.
_ACE = re.compile(r"^(?P<who>.+?):(?P<flags>(?:\([^)]*\))+)\s*$")

# Files OpenSSH checks for permissions: private keys, plus the two it also
# refuses (client config; sshd's authorized_keys with StrictModes).
_ALSO_CHECKED = ("config", "authorized_keys")

Runner = Callable[[list[str]], "str | None"]


def _icacls(argv: list[str]) -> str | None:
    got = proc.capture(["icacls", *argv], timeout=15)
    if got is None or got.returncode != 0:
        return None
    return got.stdout or ""


def _well_known_names() -> set[str]:
    """SYSTEM and Administrators as this machine spells them, lower-cased."""
    names = set(_ENGLISH)
    try:
        import ctypes
        from ctypes import wintypes

        windll = getattr(ctypes, "windll", None)  # absent off Windows
        if windll is None:
            return names
        advapi = windll.advapi32
        for sid_str in (SYSTEM_SID, ADMINS_SID):
            psid = ctypes.c_void_p()
            if not advapi.ConvertStringSidToSidW(sid_str, ctypes.byref(psid)):
                continue
            name = ctypes.create_unicode_buffer(256)
            dom = ctypes.create_unicode_buffer(256)
            n, d = wintypes.DWORD(256), wintypes.DWORD(256)
            use = wintypes.DWORD()
            ok = advapi.LookupAccountSidW(
                None, psid, name, ctypes.byref(n), dom, ctypes.byref(d), ctypes.byref(use)
            )
            windll.kernel32.LocalFree(psid)
            if ok:
                names.add(f"{dom.value}\\{name.value}".lower())
    except (AttributeError, OSError, ValueError):
        pass
    return names


def _user() -> str:
    return os.environ.get("USERNAME", "")


def candidate_files(ssh_dir: Path) -> list[Path]:
    """The files in ~/.ssh that OpenSSH refuses when other users can open them."""
    if not ssh_dir.is_dir():
        return []
    out: list[Path] = []
    for f in sorted(ssh_dir.iterdir()):
        if not f.is_file() or f.suffix == ".pub":
            continue
        if (
            f.with_name(f.name + ".pub").exists()
            or (f.name.startswith("id_") and not f.suffix)
            or f.name in _ALSO_CHECKED
        ):
            out.append(f)
    return out


def foreign_principals(
    listing: str, path: str, user: str, allowed: set[str] | None = None
) -> list[str]:
    """Principals in one `icacls <path>` listing that OpenSSH would object to.

    An ALLOW ACE that applies to the object itself counts. `(DENY)` and
    inherit-only `(IO)` ACEs do not, and neither do the owner, SYSTEM or
    Administrators. The owner is matched by name, `DOMAIN\\user` or a bare `user`.
    """
    ok = {a.lower() for a in (allowed if allowed is not None else _ENGLISH)}
    ok.update(s.lower() for sid in (SYSTEM_SID, ADMINS_SID) for s in (sid, "*" + sid))
    me = user.lower()
    found: list[str] = []
    for raw in listing.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower().startswith(path.lower()):
            line = line[len(path) :].strip()
        m = _ACE.match(line)
        if not m:
            continue
        who, flags = m.group("who").strip(), m.group("flags").upper()
        if "(DENY)" in flags or "(IO)" in flags:
            continue
        low = who.lower()
        if low in ok or (me and (low == me or low.endswith("\\" + me))):
            continue
        if who not in found:
            found.append(who)
    return found


def exposed(
    ssh_dir: Path, *, run: Runner | None = None, user: str | None = None
) -> list[tuple[Path, list[str]]]:
    """Every checked file with at least one principal OpenSSH would refuse."""
    run = run or _icacls
    me = _user() if user is None else user
    allowed = _well_known_names()
    out: list[tuple[Path, list[str]]] = []
    for f in candidate_files(ssh_dir):
        listing = run([str(f)])
        if listing is None:
            continue
        who = foreign_principals(listing, str(f), me, allowed)
        if who:
            out.append((f, who))
    return out


def fix_argv(ssh_dir: Path, user: str | None = None) -> list[list[str]]:
    """The two icacls runs: lock the directory down, then have the children inherit it.

    SYSTEM and Administrators are given by SID so a non-English install works
    too. `/grant:r` replaces whatever the user had rather than adding to it.
    """
    me = _user() if user is None else user
    grant = "(OI)(CI)F"
    return [
        [
            str(ssh_dir),
            "/inheritance:r",
            "/grant:r",
            f"{me}:{grant}",
            f"*{SYSTEM_SID}:{grant}",
            f"*{ADMINS_SID}:{grant}",
        ],
        [str(ssh_dir / "*"), "/reset", "/T", "/C", "/Q"],
    ]


def manual_fix(ssh_dir: Path, user: str | None = None) -> list[str]:
    """fix_argv as lines to paste into a shell."""
    return [
        "icacls " + " ".join(f'"{a}"' if any(c in a for c in " *()") else a for a in argv)
        for argv in fix_argv(ssh_dir, user)
    ]


def fix(ssh_dir: Path, *, run: Runner | None = None, user: str | None = None) -> bool:
    """Apply fix_argv. True when both runs succeeded."""
    run = run or _icacls
    return all(run(argv) is not None for argv in fix_argv(ssh_dir, user))


def summary(found: list[tuple[Path, list[str]]]) -> str:
    who = sorted({w for _, ws in found for w in ws})
    return f"{len(found)} file(s) in ~/.ssh readable by {', '.join(who)} - ssh ignores them"
