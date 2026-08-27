"""Shell helpers shared by cross-platform subprocess tests."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def _candidate_bashes():
    found = shutil.which("bash")
    if found:
        yield Path(found)

    if os.name != "nt":
        return

    git = shutil.which("git")
    if git:
        git_dir = Path(git).resolve().parent
        for parent in (git_dir, *git_dir.parents):
            yield parent / "bin" / "bash.exe"
            yield parent / "usr" / "bin" / "bash.exe"

    for variable, suffix in (
        ("ProgramFiles", ("Git", "bin", "bash.exe")),
        ("ProgramFiles(x86)", ("Git", "bin", "bash.exe")),
        ("LOCALAPPDATA", ("Programs", "Git", "bin", "bash.exe")),
    ):
        base = os.environ.get(variable)
        if base:
            yield Path(base).joinpath(*suffix)


def _compatible_bash(candidate: Path) -> bool:
    if not candidate.is_file():
        return False
    try:
        result = subprocess.run(
            [str(candidate), "-c", 'printf "%s" "$OSTYPE"'],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=False,
            start_new_session=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0:
        return False
    if os.name != "nt":
        return True
    # System32/bash.exe is the WSL launcher. It reports linux-gnu and cannot
    # consume Windows paths or the deliberately minimal environments used here.
    return result.stdout.strip().lower().startswith(("msys", "cygwin"))


def find_bash() -> str | None:
    seen: set[str] = set()
    for candidate in _candidate_bashes():
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        if _compatible_bash(candidate):
            return str(candidate)
    return None


BASH = find_bash()


def bash_path(path: str | Path) -> str:
    """Return a path the selected Bash can open."""
    resolved = str(Path(path).resolve())
    if os.name != "nt":
        return resolved
    if not BASH:
        raise RuntimeError("no compatible Bash is available")
    result = subprocess.run(
        [BASH, "-c", 'cygpath -u "$1"', "bash-path", resolved],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=5,
        check=False,
        start_new_session=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"could not translate path for Bash: {resolved}")
    return result.stdout.strip()
