"""The commit gates themselves.

`.githooks/pre-commit` and `pre-push` are the only automated gate that runs
before CI, and they have failed silently twice: nothing set `core.hooksPath`
until 2026-08-25, so they never ran at all; and both probed for their tools with
`python3 -c "import <tool>"` only, which is the ONE shape the stack does not
produce -- `TS_APPS_RECOMMENDED` installs `ruff` and `uv` as formulae, and `ruff`
has no importable module in any case. The hook then printed "NOT RUN" four times
and exited 0.

So these tests are about reachability, not about linting. A gate you believe is
running and is not is worse than no gate; that sentence is in the hook's own
header and both failures were instances of it.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.shell_support import BASH  # noqa: E402
from tests.test_agent_tools import repo_file  # noqa: E402

GATES = ROOT / ".githooks" / "_gates.sh"

pytestmark = pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")


def _runner(module: str, *, path: str | None = None, package: str | None = None) -> str:
    """`gate_runner <module>` as the hook would evaluate it, with a chosen PATH."""
    env = dict(os.environ)
    if path is not None:
        env["PATH"] = path
    arg = f"{module} {package}" if package else module
    out = subprocess.run(
        [BASH, "-c", f'. "{GATES}" && gate_runner {arg}'],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        start_new_session=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_an_importable_module_is_preferred():
    """Shape 1. `json` stands in for a pip-installed tool: always importable."""
    assert _runner("json") == "python3 -m json"


def test_a_binary_on_path_is_found_when_the_module_is_not(tmp_path):
    """Shape 2, and the regression.

    This is what brew and winget produce, and what the catalog asks for. The old
    probe stopped at shape 1, so on a machine the stack itself provisioned every
    gate reported NOT RUN and the hook exited 0.
    """
    fake = tmp_path / "bin"
    fake.mkdir()
    tool = fake / "notamodule"
    tool.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    tool.chmod(0o755)
    assert _runner("notamodule", path=str(fake)) == "notamodule"


def test_uvx_is_the_last_resort(tmp_path):
    """Shape 3. uv is in TS_APPS_RECOMMENDED, so this is a real path, not a hope."""
    fake = tmp_path / "bin"
    fake.mkdir()
    uvx = fake / "uvx"
    uvx.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    uvx.chmod(0o755)
    got = _runner("notamodule", path=f"{fake}:{os.environ['PATH']}")
    assert got == "uvx --quiet --from notamodule notamodule"
    # A package whose import name differs from its command name still resolves.
    got = _runner("notamodule", path=f"{fake}:{os.environ['PATH']}", package="some-dist")
    assert got == "uvx --quiet --from some-dist notamodule"


def test_nothing_available_reports_rather_than_pretending(tmp_path):
    """Empty means the caller must SAY the gate did not run, never skip quietly."""
    empty = tmp_path / "bin"
    empty.mkdir()
    assert _runner("notamodule", path=str(empty)) == ""


def test_only_the_module_shape_puts_cwd_on_sys_path():
    """tests/ has no __init__.py and its modules import each other, so the repo
    root must be importable. `python3 -m pytest` adds cwd; uvx and a bare binary
    do not, and without PYTHONPATH collection fails with ModuleNotFoundError."""

    def needs(runner: str) -> bool:
        out = subprocess.run(
            [BASH, "-c", f'. "{GATES}" && gate_needs_pythonpath "{runner}"'],
            capture_output=True,
            text=True,
            timeout=60,
            start_new_session=True,
            check=False,
        )
        return out.returncode == 0

    assert not needs("python3 -m pytest")
    assert needs("pytest")
    assert needs("uvx --quiet --from pytest pytest")


def test_both_hooks_resolve_through_the_shared_helper():
    """One implementation. Fixing this twice is how the two drifted in the first
    place, and the hooks are not covered by ruff, mypy or the suite."""
    for name in ("pre-commit", "pre-push"):
        body = repo_file(f".githooks/{name}").read_text(encoding="utf-8")
        assert "_gates.sh" in body, f"{name} must source the shared resolver"
        assert "gate_runner" in body, f"{name} must resolve its tools through gate_runner"
        assert 'python3 -c "import ruff"' not in body, (
            f"{name} probes for a ruff module, which does not exist"
        )


def test_the_hooks_are_bash_32_clean():
    """/bin/bash is 3.2 on macOS and these run there. `declare -A`, `mapfile` and
    `${x^^}` are all parse errors under it, and the suite cannot see them."""
    for name in ("_gates.sh", "pre-commit", "pre-push"):
        path = repo_file(f".githooks/{name}")
        out = subprocess.run(
            [BASH, "-n", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            start_new_session=True,
            check=False,
        )
        assert out.returncode == 0, f"{name}: {out.stderr}"


def test_both_hooks_are_executable():
    """git silently ignores a hook without the executable bit.

    `.githooks/pre-push` shipped as 100644 and was therefore never run in any
    clone, even once core.hooksPath was set - the coverage floor and the
    characterization replay had no gate at all. The mode that matters is the one
    in the INDEX, not the working tree: a fresh clone gets git's copy.
    """
    out = subprocess.run(
        ["git", "ls-files", "-s", ".githooks"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        start_new_session=True,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    modes = {}
    for line in out.stdout.splitlines():
        mode, _, rest = line.partition(" ")
        modes[rest.split("\t", 1)[1]] = mode
    for name in (".githooks/pre-commit", ".githooks/pre-push"):
        assert name in modes, f"{name} is not tracked"
        assert modes[name] == "100755", f"{name} is {modes[name]}; git will not run it"
