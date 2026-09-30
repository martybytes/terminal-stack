"""Agent hooks need `node` on the PATH their agent started with.

Reported: every agentmemory hook failed `/bin/sh: 1: node: not found` in Claude
sessions opened before fnm installed Node. fnm's PATH entry exists only in a
shell that ran `fnm env`; hooks run under /bin/sh. ts_link_fnm_node links the
fnm DEFAULT version into ~/.local/bin, which every stack PATH carries.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.shell_support import BASH

ROOT = Path(__file__).resolve().parent.parent
needs_bash = pytest.mark.skipif(BASH is None or os.name != "posix", reason="POSIX bash only")


def _fnm_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    bindir = home / ".local/share/fnm/aliases/default/bin"
    bindir.mkdir(parents=True)
    for tool in ("node", "npm", "npx"):
        exe = bindir / tool
        exe.write_text("#!/bin/sh\necho v24.0.0\n", encoding="utf-8")
        exe.chmod(0o755)
    return home


def _link(home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, "-c", f". {ROOT / 'bootstrap/_config.sh'} >/dev/null 2>&1; ts_link_fnm_node"],
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        start_new_session=True,
    )


@needs_bash
def test_hooks_under_a_bare_sh_find_the_fnm_default_node(tmp_path):
    home = _fnm_home(tmp_path)
    assert _link(home).returncode == 0
    for tool in ("node", "npm", "npx"):
        link = home / ".local/bin" / tool
        assert link.is_symlink(), tool
        assert os.readlink(link).endswith(f"fnm/aliases/default/bin/{tool}")
    got = subprocess.run(
        ["/bin/sh", "-c", "node"],
        env={"PATH": f"/usr/bin:/bin:{home / '.local/bin'}"},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        start_new_session=True,
    )
    assert got.stdout.strip() == "v24.0.0"


@needs_bash
def test_relinking_is_a_no_op(tmp_path):
    home = _fnm_home(tmp_path)
    _link(home)
    assert "linked" not in _link(home).stdout


@needs_bash
def test_a_node_that_is_not_our_link_is_never_replaced(tmp_path):
    home = _fnm_home(tmp_path)
    mine = home / ".local/bin/node"
    mine.parent.mkdir(parents=True)
    mine.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")
    other = home / ".local/bin/npm"
    other.symlink_to("/opt/somewhere/npm")
    _link(home)
    assert not mine.is_symlink() and "mine" in mine.read_text(encoding="utf-8")
    assert os.readlink(other) == "/opt/somewhere/npm"


def test_both_node_paths_link():
    """The early 'already current' return is how this machine missed it."""
    src = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    fn = src[src.index("ts_install_node_lts() {") : src.index("ts_link_fnm_node() {")]
    assert fn.count("ts_link_fnm_node") == 2
