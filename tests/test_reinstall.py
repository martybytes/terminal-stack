"""`tstack reinstall`: pull first, then the clone's own installer, pinned to it.

The git half runs against real repositories (a bare origin and a clone of it),
because every trap it guards -- a stale remote-tracking ref, a deleted branch,
a rollback point written on a no-op -- is git behaviour, not ours.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import paths  # noqa: E402
from tstack import platform as plat  # noqa: E402
from tstack.commands import reinstall  # noqa: E402


def git(*args: str, cwd: Path | None = None) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        start_new_session=True,
    )
    return out.stdout.strip()


def commit(repo: Path, name: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    git("-C", str(repo), "add", name)
    git("-C", str(repo), "commit", "-q", "-m", name)


@pytest.fixture
def clones(tmp_path, monkeypatch):
    """(origin work tree, runtime clone). Pushing from the first is "upstream moved"."""
    for key, value in {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
    }.items():
        monkeypatch.setenv(key, value)
    # state_dir() directly, not XDG_STATE_HOME: Windows ignores that and uses
    # %LOCALAPPDATA%, where a real rollback-sha lives -- and this suite wrote one.
    monkeypatch.setattr(plat, "state_dir", lambda: tmp_path / "state")
    bare = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    work = tmp_path / "work"
    git("clone", "-q", str(bare), str(work))
    git("-C", str(work), "checkout", "-q", "-b", "main")
    commit(work, "one")
    git("-C", str(work), "push", "-q", "-u", "origin", "main")
    runtime = tmp_path / "runtime"
    git("clone", "-q", "--branch", "main", str(bare), str(runtime))
    return work, runtime


def rollback_sha() -> Path:
    return plat.state_dir() / "rollback-sha"


def test_it_pulls_and_records_a_rollback_point(clones):
    work, runtime = clones
    before = git("-C", str(runtime), "rev-parse", "HEAD")
    commit(work, "two")
    git("-C", str(work), "push", "-q")
    assert reinstall.pull(runtime, dry_run=False)
    assert git("-C", str(runtime), "rev-parse", "HEAD") == git("-C", str(work), "rev-parse", "HEAD")
    assert rollback_sha().read_text(encoding="utf-8").strip() == before


def test_a_no_op_pull_leaves_the_last_rollback_point_alone(clones):
    _, runtime = clones
    assert reinstall.pull(runtime, dry_run=False)
    assert not rollback_sha().exists()


def test_a_dirty_clone_is_refused_and_nothing_moves(clones, capsys):
    work, runtime = clones
    commit(work, "two")
    git("-C", str(work), "push", "-q")
    (runtime / "one").write_text("edited", encoding="utf-8")
    before = git("-C", str(runtime), "rev-parse", "HEAD")
    assert not reinstall.pull(runtime, dry_run=False)
    assert git("-C", str(runtime), "rev-parse", "HEAD") == before
    assert "uncommitted changes" in capsys.readouterr().err


def test_a_clone_on_a_deleted_branch_returns_to_main(clones):
    """Merged-and-deleted: without --prune the stale ref still looked alive."""
    work, runtime = clones
    git("-C", str(runtime), "checkout", "-q", "-b", "feat/x")
    git("-C", str(runtime), "push", "-q", "-u", "origin", "feat/x")
    git("-C", str(work), "push", "-q", "origin", "--delete", "feat/x")
    commit(work, "two")
    git("-C", str(work), "push", "-q")
    assert reinstall.pull(runtime, dry_run=False)
    assert git("-C", str(runtime), "rev-parse", "--abbrev-ref", "HEAD") == paths.RELEASE_BRANCH
    assert (runtime / "two").exists()


def test_a_dry_run_moves_nothing(clones):
    work, runtime = clones
    before = git("-C", str(runtime), "rev-parse", "HEAD")
    commit(work, "two")
    git("-C", str(work), "push", "-q")
    assert reinstall.pull(runtime, dry_run=True)
    assert git("-C", str(runtime), "rev-parse", "HEAD") == before
    assert not rollback_sha().exists()


@pytest.mark.parametrize(
    "kind, script",
    [
        (plat.WSL, "install-wsl.sh"),
        (plat.LINUX, "install-linux.sh"),
        (plat.MACOS, "install-mac.sh"),
    ],
)
def test_each_posix_platform_runs_its_own_installer(kind, script):
    assert reinstall.installer_argv(ROOT, kind) == ["bash", str(ROOT / script)]


def test_windows_runs_install_ps1_under_pwsh(monkeypatch):
    monkeypatch.setattr(plat, "find_pwsh", lambda: "pwsh")
    argv = reinstall.installer_argv(ROOT, plat.WINDOWS)
    assert argv is not None
    assert argv[0] == "pwsh" and argv[-1] == str(ROOT / "install.ps1")


def test_every_installer_it_names_exists():
    for script in reinstall.INSTALLERS.values():
        assert (ROOT / script).is_file(), script


def _run_main(monkeypatch, tmp_path, argv):
    ran: list[tuple[list[str], dict]] = []

    def fake_run(cmd, env=None, check=False, **kwargs):
        ran.append((cmd, {"env": env, **kwargs}))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(paths, "resolve_source_dir", lambda **_: tmp_path)
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    (tmp_path / "install-linux.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    monkeypatch.setattr(reinstall.subprocess, "run", fake_run)
    return reinstall.main(argv), ran


def test_the_installer_runs_pinned_and_attached_to_the_terminal(monkeypatch, tmp_path):
    """The pin skips every clone-location question. The terminal is the other half:
    a child in its own session cannot open /dev/tty, and the questionnaire then
    takes every default in silence -- the bug this stack just shipped a fix for."""
    rc, ran = _run_main(monkeypatch, tmp_path, ["--no-pull"])
    assert rc == 0
    ((cmd, opts),) = ran
    assert cmd == ["bash", str(tmp_path / "install-linux.sh")]
    assert opts["env"]["TERMINAL_STACK_DIR"] == str(tmp_path)
    assert not opts.get("start_new_session")
    assert "stdin" not in opts and "capture_output" not in opts


def test_a_dry_run_never_starts_the_installer(monkeypatch, tmp_path, capsys):
    rc, ran = _run_main(monkeypatch, tmp_path, ["--no-pull", "--dry-run"])
    assert rc == 0 and ran == []
    assert "would run" in capsys.readouterr().out


def test_a_failed_pull_stops_before_the_installer(monkeypatch, tmp_path):
    monkeypatch.setattr(reinstall, "pull", lambda src, dry_run: False)
    rc, ran = _run_main(monkeypatch, tmp_path, [])
    assert rc == 1 and ran == []


def test_an_unknown_option_is_a_usage_error(capsys):
    assert reinstall.main(["--force"]) == 2
    assert "unknown option" in capsys.readouterr().err
