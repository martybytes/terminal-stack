"""The container engine: probing it, advising about it, and running it.

Port of the engine half of services/_stack.sh (tss_docker_kind, tss_engine_advice,
tss_docker_path) and of Get-TsDockerKind in bootstrap/ts-stack.ps1.

`docker` on PATH is not evidence. Inside WSL with Docker Desktop's integration
switched off, PATH still holds Desktop's stub, which exits 1 for every command and
prints "could not be found in this WSL 2 distro" ON STDOUT -- so a `which docker`
check is true and useless, and the engine may be perfectly healthy on the Windows
side at the same time.

THE ONE DELIBERATE BEHAVIOUR CHANGE OF THIS PORT is here. The bash twin handled
wsl-shim by re-exec'ing the pwsh twin through interop, because the logic existed
twice and the Windows copy was the one that could talk to the engine. It is now
one implementation, so there is nothing to hand off to: this module runs
`docker.exe` through interop instead, from the same Python process. That is a
strict improvement in two ways -- it works on a machine with no pwsh 7 (the bash
twin gave up there), and the verbs the handoff did not cover (bootstrap, test,
backup, reset, migrate-volumes, doctor) now work on WSL too, where they used to
run against the stub and fail.

It carries one real constraint, which is why require_windows_visible() exists: a
Windows engine cannot bind-mount a \\wsl.localhost 9p path. A clone under /mnt/c
translates to a drive path and is fine; a clone inside the WSL filesystem is not,
and that has to be said before the stack is taken down rather than after.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath

from . import platform as plat
from . import proc

# The four answers of the probe. Exactly the vocabulary of tss_docker_kind.
NATIVE = "native"
WSL_SHIM = "wsl-shim"
ABSENT = "absent"
DENIED = "denied"

# tss_os's vocabulary, which engine_advice() switches on. Not plat.kind(): the
# advice for WSL is Linux's advice, and Git Bash reports windows.
DARWIN = "darwin"
LINUX = "linux"
WINDOWS = "windows"


def os_name() -> str:
    """tss_os, in the same three words. WSL answers `linux`, as `uname -s` does."""
    kind = plat.kind()
    if kind == plat.MACOS:
        return DARWIN
    if kind == plat.WINDOWS:
        return WINDOWS
    return LINUX


def _run(argv: list[str], timeout: int = 30) -> subprocess.CompletedProcess | None:
    return proc.capture(argv, timeout=timeout)


def docker_kind() -> str:
    """native | wsl-shim | absent | denied.

    TS_STACK_DOCKER_PROBE overrides the whole probe, which is how every test in
    this subsystem runs without an engine.
    """
    probe = os.environ.get("TS_STACK_DOCKER_PROBE")
    if probe:
        return probe

    binary = shutil.which("docker")
    if not binary:
        # On WSL a missing Linux docker is not the end of it: interop may still
        # reach the Windows engine, which is the whole point of the shim path.
        if plat.kind() == plat.WSL and shutil.which("docker.exe"):
            return WSL_SHIM
        return ABSENT

    # The shim lives under a Windows mount with no Linux docker beside it.
    if binary.startswith("/mnt/") and not Path("/usr/bin/docker").exists():
        return WSL_SHIM

    # Belt and braces: the stub prints its complaint to STDOUT, so redirecting
    # stderr alone does not catch it.
    version = _run([binary, "version"])
    blob = ((version.stdout if version else "") + (version.stderr if version else "")).lower()
    if "could not be found in this wsl" in blob:
        return WSL_SHIM

    info = _run([binary, "info"])
    if info and info.returncode == 0:
        return NATIVE
    blob = ((info.stdout if info else "") + (info.stderr if info else "")).lower()
    if "permission denied while trying to connect" in blob:
        return DENIED
    return NATIVE  # CLI present, engine down: the caller reports that


def binary_for(kind: str) -> str:
    """Which docker CLI to invoke for this engine kind."""
    return "docker.exe" if kind == WSL_SHIM else "docker"


def is_up(kind: str | None = None) -> bool:
    """Engine reachable. Both native and the WSL interop path count."""
    kind = docker_kind() if kind is None else kind
    if kind in (ABSENT, DENIED):
        return False
    if os.environ.get("TS_STACK_DOCKER_PROBE"):
        # Under an injected probe there is no engine to ask; the probe value is
        # the whole answer, and tests set TS_STACK_ENGINE_UP when they want one.
        return os.environ.get("TS_STACK_ENGINE_UP", "0") == "1"
    out = _run([binary_for(kind), "info"])
    return bool(out and out.returncode == 0)


def require_windows_visible(path: Path) -> str | None:
    """Refuse a path a Windows engine cannot bind-mount, before anything is torn down.

    Only ever consulted on the wsl-shim path. A clone under /mnt/<drive> is fine;
    one inside the WSL filesystem reaches the engine as \\\\wsl.localhost, which is
    a 9p share and not reliably bind-mountable -- and the failure surfaces inside
    a container as tar saying "Cannot open: No such file or directory", which
    reads as a broken archive rather than a broken mount.

    Returns None when the path is usable, or the reason it is not.
    """
    # Pure string work on a POSIX path. Path.resolve() must NOT be used here: this
    # is only ever asked about a WSL path, and resolving one on Windows -- where
    # this suite also runs -- turns /mnt/c/x into a drive-relative path and
    # inverts the answer.
    resolved = PurePosixPath(path).as_posix()
    parts = resolved.split("/")
    if len(parts) > 3 and parts[1] == "mnt" and len(parts[2]) == 1 and parts[2].isalpha():
        return None
    return (
        f"{resolved} is inside the WSL filesystem, and the Docker engine here is a "
        "Windows process that cannot bind-mount it.\n"
        "  fix:  keep the clone under a Windows drive (the canonical "
        "%LOCALAPPDATA%\\terminal-stack\\stack already is),\n"
        "        or enable this distro under Docker Desktop -> Settings -> "
        "Resources -> WSL Integration"
    )


def engine_advice(os_kind: str, kind: str) -> list[str]:
    """PURE. What to do about a failed probe, as lines.

    Split out and string-for-string with the bash twin because the text IS the
    deliverable of a failed probe: it is what a person acts on, and it is
    unit-testable with no Docker anywhere.
    """
    if kind == WSL_SHIM:
        return [
            "the `docker` on PATH is Docker Desktop's stub - it exits 1 for every",
            "command and says nothing about whether the engine is healthy.",
            "  fix either way:",
            "    Docker Desktop -> Settings -> Resources -> WSL Integration -> enable this distro",
            "    or install a Linux docker CLI in this distro",
        ]
    if kind == DENIED:
        return [
            "the engine is there but this user may not talk to it.",
            '  fix:  sudo usermod -aG docker "$USER"   then LOG OUT and back in',
            "        (a new shell in the same session does not pick the group up)",
        ]
    if kind == ABSENT:
        if os_kind == DARWIN:
            return [
                "no container engine found.",
                "  fix:  brew install --cask docker      (Docker Desktop)",
                "        brew install colima && colima start   (lighter, no GUI)",
            ]
        if os_kind == LINUX:
            return [
                "no container engine found.",
                "  fix:  see `doc docker` for the docker-ce install for your distro",
            ]
        return [
            "no container engine found.",
            "  fix:  winget install --id Docker.DockerDesktop --exact",
        ]
    if os_kind == DARWIN:
        return [
            "the engine is not answering.",
            "  fix:  open -a Docker      (or: colima start)",
        ]
    if os_kind == LINUX:
        return [
            "the engine is not answering.",
            "  fix:  sudo systemctl start docker    (rootless: systemctl --user start docker)",
        ]
    return [
        "the engine is not answering.",
        "  fix:  start Docker Desktop, or re-run with --start-engine",
    ]


def host_path(path: Path | str) -> str:
    """A host path in the form the ENGINE understands.

    Identical everywhere except where the engine is a Windows process and this
    one is not: Git Bash (cygpath) and WSL talking to Desktop (wslpath).
    """
    kind = docker_kind()
    if plat.kind() == plat.WSL and kind == WSL_SHIM:
        return plat.to_windows_path(path) or str(path)
    if os_name() == WINDOWS and shutil.which("cygpath"):
        out = _run(["cygpath", "-w", str(path)], timeout=10)
        if out and out.returncode == 0:
            return out.stdout.strip()
    return str(path)
