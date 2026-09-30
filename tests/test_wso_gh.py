"""`wso synceverything` and `plan` on a machine where they found "nothing".

Reported on WSL: `wso synceverything` printed `0 cloned.` and `wso plan` printed
four zeros. The Linux `gh` was never logged in (the Windows gh.exe was), every
`gh repo list` failed with its stderr discarded, and each owner looked like one
with nothing missing. The plan was right -- the two repos there were already
filed -- but four zeros read as a broken scan.

Driven through the real wso.sh with a fake `gh` and `git` first on PATH, against
a temporary workspace: no network, no real GitHub.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from tests.shell_support import BASH

ROOT = Path(__file__).resolve().parent.parent
WSO = ROOT / "bootstrap" / "wso.sh"
PWSH_TWIN = ROOT / "bootstrap" / "_workspace_cmd.ps1"

needs_bash = pytest.mark.skipif(BASH is None, reason="needs bash")

FAKE_GH = """#!/usr/bin/env bash
case "$1 $2" in
  "auth status") [ "${FAKE_GH_AUTHED:-1}" = 1 ] && exit 0
                 echo "You are not logged into any GitHub hosts." >&2; exit 1 ;;
  "repo list")
    if [ "$3" = "${FAKE_GH_FAIL_OWNER:-}" ]; then echo "HTTP 403: rate limited" >&2; exit 1; fi
    [ "${FAKE_GH_AUTHED:-1}" = 1 ] || { echo "not logged in" >&2; exit 4; }
    printf '%s\\n' ${FAKE_GH_REPOS:-} ;;
esac
exit 0
"""

FAKE_GIT = """#!/usr/bin/env bash
# Records clones; delegates everything else to the real git.
if [ "$1" = clone ]; then echo "$@" >> "$FAKE_GIT_LOG"; exit 0; fi
exec "$REAL_GIT" "$@"
"""


@pytest.fixture
def ws(tmp_path):
    """A workspace with one already-organised repo, plus fake gh/git."""
    root = tmp_path / "Workspace"
    repo = root / "src" / "github.com" / "martybytes" / "terminal-stack"
    (repo / ".git").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("gh", FAKE_GH), ("git", FAKE_GIT)):
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    real_git = subprocess.run(
        [BASH, "-c", "command -v git"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        start_new_session=True,
    ).stdout.strip()
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path / "home"),
        "WORKSPACE_DIR": str(root),
        "FAKE_GIT_LOG": str(tmp_path / "clones.log"),
        "REAL_GIT": real_git,
        "NO_COLOR": "1",
    }
    (tmp_path / "home").mkdir()
    return root, env, tmp_path / "clones.log"


def run(env: dict, *args: str, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(WSO), *args],
        env={**env, **extra},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        start_new_session=True,
    )


@needs_bash
def test_synceverything_refuses_a_logged_out_gh_instead_of_saying_0_cloned(ws):
    _, env, log = ws
    got = run(env, "synceverything", FAKE_GH_AUTHED="0", FAKE_GH_REPOS="a b")
    assert got.returncode == 1
    assert "gh is not logged in" in got.stderr
    assert "gh.exe auth token | gh auth login --with-token" in got.stderr
    assert "0 cloned" not in got.stdout + got.stderr
    assert not log.exists(), "nothing may be cloned when gh cannot list"


@needs_bash
def test_an_owner_that_cannot_be_listed_is_named_and_fails_the_run(ws):
    _, env, _ = ws
    got = run(env, "synceverything", FAKE_GH_FAIL_OWNER="martybytes", TS_DRY_RUN="1")
    assert got.returncode == 1
    assert "could not list martybytes's repos: HTTP 403: rate limited" in got.stderr
    assert "owner(s) could not be listed" in got.stderr


@needs_bash
def test_an_authenticated_gh_still_clones_what_is_missing(ws):
    _, env, _ = ws
    got = run(env, "synceverything", FAKE_GH_REPOS="terminal-stack newrepo", TS_DRY_RUN="1")
    out = got.stdout + got.stderr
    assert got.returncode == 0, out
    assert "would clone martybytes/newrepo" in out
    assert "would clone martybytes/terminal-stack" not in out, "already here"


@needs_bash
def test_an_organised_workspace_says_so_instead_of_four_zeros(ws):
    _, env, _ = ws
    got = run(env, "plan")
    assert got.returncode == 0, got.stderr
    assert "0 ready, 0 conflicted, 0 blocked, 0 already correct" in got.stdout
    assert "1 repo(s) already organised under the tier folders - nothing to migrate" in got.stdout


@needs_bash
def test_sync_reports_the_login_instead_of_silently_listing_nothing(ws):
    _, env, _ = ws
    got = run(env, "sync", FAKE_GH_AUTHED="0")
    assert "gh is not logged in, so repos missing from this machine cannot be listed" in got.stdout


def test_the_pwsh_twin_carries_the_same_guards_and_words():
    """Twins: change one, change the other (CLAUDE.md). Same user-facing text."""
    ps = PWSH_TWIN.read_text(encoding="utf-8")
    sh = WSO.read_text(encoding="utf-8")
    for phrase in (
        "gh is not logged in - needed to enumerate your orgs",
        "gh is not logged in, so repos missing from this machine cannot be listed",
        "owner(s) could not be listed",
        "repo(s) already organised under the tier folders - nothing to migrate",
        "gh.exe auth token | gh auth login --with-token",
    ):
        assert phrase in ps, f"pwsh twin lacks: {phrase}"
        assert phrase.replace(" - needed", " — needed") in sh or phrase in sh, (
            f"bash twin lacks: {phrase}"
        )
    assert "2>$null" not in ps.split("function Get-TsWsGhRepos", 1)[1].split("\nfunction ", 1)[0]
