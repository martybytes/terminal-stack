"""In-process unit tests for the tstack core modules.

The CLI tests in test_tstack_cli.py shell out, which is the right shape for
checking exit codes and real help output but invisible to coverage and unable to
simulate another OS. These run in-process and inject the platform, so the
macOS/Linux branches are exercised on Windows and vice versa -- which matters
because two of the four targets cannot be run on this machine at all.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import cli, paths, registry  # noqa: E402
from tstack import platform as plat  # noqa: E402


def _clear() -> None:
    for fn in (plat.kind, plat.is_wsl, plat.windows_username):
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()


@pytest.fixture(autouse=True)
def _clear_caches():
    """Every platform probe is lru_cached, so a test that injects an OS must
    clear them or it inherits the previous test's answer."""
    _clear()
    yield
    _clear()


def as_platform(monkeypatch, kind: str) -> None:
    """Make plat.kind() report `kind`, whatever we are really running on.

    Injected at kind() rather than at os.name, deliberately. Patching os.name to
    "posix" on Windows makes pathlib hand out PosixPath, which raises
    UnsupportedOperation the moment anything builds a path -- so the fake OS
    breaks the very code under test. The detection logic gets its own test below.
    """
    monkeypatch.setattr(plat, "kind", lambda: kind)


# ------------------------------------------------------------------ platform


@pytest.mark.parametrize("kind", [plat.WINDOWS, plat.WSL, plat.LINUX, plat.MACOS])
def test_every_platform_is_reachable_from_any_host(monkeypatch, kind):
    as_platform(monkeypatch, kind)
    assert plat.kind() == kind
    assert plat.is_windows_side() == (kind in (plat.WINDOWS, plat.WSL))


@pytest.mark.parametrize(
    "os_name,sys_platform,wsl,expected",
    [
        ("nt", "win32", False, plat.WINDOWS),
        ("posix", "darwin", False, plat.MACOS),
        ("posix", "linux", True, plat.WSL),
        ("posix", "linux", False, plat.LINUX),
    ],
)
def test_detection_itself(monkeypatch, os_name, sys_platform, wsl, expected):
    """The real branch logic, asserted without building any path."""
    monkeypatch.setattr(os, "name", os_name)
    monkeypatch.setattr(sys, "platform", sys_platform)
    monkeypatch.setattr(plat, "is_wsl", lambda: wsl)
    plat.kind.cache_clear()
    assert plat.kind() == expected
    plat.kind.cache_clear()


def test_is_wsl_reads_proc_version(monkeypatch, tmp_path):
    monkeypatch.setattr(os, "name", "posix")
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    proc = tmp_path / "version"
    proc.write_text("Linux version 5.15 Microsoft WSL2", encoding="utf-8")
    monkeypatch.setattr(plat, "Path", lambda p: proc if p == "/proc/version" else Path(p))
    plat.is_wsl.cache_clear()
    assert plat.is_wsl() is True
    plat.is_wsl.cache_clear()


def test_state_dir_follows_xdg_on_posix_and_localappdata_on_windows(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.LINUX)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    assert plat.state_dir() == tmp_path / "xdg" / "terminal-stack"

    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert plat.state_dir() == Path.home() / ".local" / "state" / "terminal-stack"


def test_state_dir_falls_back_when_localappdata_is_missing(monkeypatch):
    """A Windows box with no LOCALAPPDATA must degrade, not raise."""
    as_platform(monkeypatch, plat.WINDOWS)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert plat.state_dir() == Path.home() / ".local" / "state" / "terminal-stack"


def test_find_chezmoi_prefers_the_explicit_override(monkeypatch):
    monkeypatch.setenv("TERMINAL_STACK_CHEZMOI", "/nowhere/chezmoi")
    assert plat.find_chezmoi() == "/nowhere/chezmoi"


def test_to_windows_path_is_identity_on_windows_and_none_on_native_posix(monkeypatch):
    as_platform(monkeypatch, plat.WINDOWS)
    assert plat.to_windows_path("C:/x") == "C:/x"
    as_platform(monkeypatch, plat.LINUX)
    assert plat.to_windows_path("/home/x") is None


# --------------------------------------------------------------------- paths


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/home/u/src/github.com/martybytes/terminal-stack", True),
        ("C:\\DATA\\Workspace\\src\\github.com\\martybytes\\terminal-stack", True),
        ("/home/u/public/github.com/o/r", True),
        # Safe by construction: the leading dot in ".local" breaks the /local/ bound.
        ("/home/u/.local/share/terminal-stack", False),
        # No dot in any host position.
        ("/mnt/c/Users/u/AppData/Local/terminal-stack/stack", False),
        ("/home/u/terminal-stack", False),
    ],
)
def test_dev_clone_detection_matches_the_documented_cases(path, expected):
    assert paths.is_dev_clone(path) is expected


def test_the_pin_leads_the_candidate_list(monkeypatch, tmp_path):
    monkeypatch.setenv("TERMINAL_STACK_DIR", str(tmp_path / "pinned"))
    assert paths.clone_candidates()[0] == tmp_path / "pinned"


def test_candidates_are_deduplicated_case_insensitively(monkeypatch, tmp_path):
    monkeypatch.setenv("TERMINAL_STACK_DIR", str(Path.home() / "terminal-stack"))
    found = paths.clone_candidates()
    keys = [os.path.normcase(str(p)) for p in found]
    assert len(keys) == len(set(keys))


def make_clone(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-q", str(root)],
        check=True,
        capture_output=True,
        timeout=300,
        start_new_session=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "remote",
            "add",
            "origin",
            "https://github.com/martybytes/terminal-stack.git",
        ],
        check=True,
        capture_output=True,
        timeout=300,
        start_new_session=True,
    )
    return root


def test_an_explicit_source_dir_hard_fails_when_dangling(tmp_path):
    """Typed per call, so a bad one is a mistake worth failing on."""
    with pytest.raises(paths.CloneNotFound):
        paths.resolve_source_dir(tmp_path / "nope")


def test_an_explicit_source_dir_is_accepted_when_real(tmp_path):
    clone = make_clone(tmp_path / "clone")
    assert paths.resolve_source_dir(clone) == clone


def test_a_dangling_env_pin_degrades_instead_of_dead_ending(monkeypatch, tmp_path):
    """The asymmetry with --source-dir is deliberate: the env pin arrives from a
    local override in every session, so a stale line would brick the machine."""
    real = make_clone(tmp_path / "real")
    monkeypatch.setenv("TERMINAL_STACK_DIR", str(tmp_path / "gone"))
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    monkeypatch.setattr(paths, "clone_candidates", lambda: [real])

    notes: list[str] = []
    assert paths.resolve_source_dir(warn=notes.append) == real
    assert any("stale TERMINAL_STACK_DIR" in n for n in notes)


def test_a_live_env_pin_wins_without_searching(monkeypatch, tmp_path):
    clone = make_clone(tmp_path / "pinned")
    monkeypatch.setenv("TERMINAL_STACK_DIR", str(clone))
    monkeypatch.setattr(
        paths, "clone_candidates", lambda: (_ for _ in ()).throw(AssertionError("searched"))
    )
    assert paths.resolve_source_dir() == clone


def test_no_clone_anywhere_raises_with_an_actionable_message(monkeypatch):
    monkeypatch.delenv("TERMINAL_STACK_DIR", raising=False)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    monkeypatch.setattr(paths, "clone_candidates", lambda: [])
    with pytest.raises(paths.CloneNotFound, match="install one-liner"):
        paths.resolve_source_dir()


def test_multiple_clones_are_reported_not_silently_chosen(monkeypatch, tmp_path):
    a, b = make_clone(tmp_path / "a"), make_clone(tmp_path / "b")
    monkeypatch.delenv("TERMINAL_STACK_DIR", raising=False)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    monkeypatch.setattr(paths, "clone_candidates", lambda: [a, b])
    notes: list[str] = []
    assert paths.resolve_source_dir(warn=notes.append) == a
    assert any("2 terminal-stack clones found" in n for n in notes)


def test_a_dev_clone_is_invisible_unless_it_is_the_pin(monkeypatch, tmp_path):
    dev = make_clone(tmp_path / "src" / "github.com" / "o" / "terminal-stack")
    monkeypatch.delenv("TERMINAL_STACK_DIR", raising=False)
    monkeypatch.setattr(paths, "clone_candidates", lambda: [dev])
    assert paths.clones() == []

    monkeypatch.setenv("TERMINAL_STACK_DIR", str(dev))
    assert [c.path for c in paths.clones()] == [dev]


def test_clone_version_reports_dirtiness(tmp_path):
    clone = make_clone(tmp_path / "c")
    (clone / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(clone), "add", "-A"],
        check=True,
        capture_output=True,
        timeout=300,
        start_new_session=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(clone),
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-qm",
            "one",
        ],
        check=True,
        capture_output=True,
        timeout=300,
        start_new_session=True,
    )
    assert paths.clone_version(clone)["dirty"] is False
    (clone / "f.txt").write_text("y", encoding="utf-8")
    assert paths.clone_version(clone)["dirty"] is True


def test_paths_with_spaces_and_non_ascii_resolve(tmp_path):
    clone = make_clone(tmp_path / "a b" / "\u00e9\u00e7\u00fc")
    assert paths.resolve_source_dir(clone) == clone


# ------------------------------------------------------------------ registry


def test_parse_rejects_a_short_row_by_naming_it():
    with pytest.raises(ValueError, match="expected 4 fields"):
        registry.parse("doctor  a  b\n")


def test_parse_skips_comments_and_blanks():
    assert registry.parse("# c\n\n  \nx a b sum\n")[0].name == "x"


def test_wsl_takes_the_posix_column():
    """WSL is POSIX, chezmoi is authoritative there, and the bash halves are the
    ones that know how to reach across to the Windows side."""
    cmd = registry.Command("x", "posix.sh", "@Win", "s")
    assert cmd.impl(plat.WSL) == "posix.sh"
    assert cmd.impl(plat.LINUX) == "posix.sh"
    assert cmd.impl(plat.MACOS) == "posix.sh"
    assert cmd.impl(plat.WINDOWS) == "@Win"


def test_supported_and_ported_predicates():
    assert registry.Command("x", "-", "-", "s").is_supported(plat.LINUX) is False
    assert registry.Command("x", "python", "-", "s").is_ported(plat.LINUX) is True
    assert registry.Command("x", "a.sh", "-", "s").is_ported(plat.LINUX) is False


def test_get_returns_none_for_an_unknown_name():
    assert registry.get("no-such-command") is None


# ----------------------------------------------------------------------- cli


def test_render_help_marks_platform_gaps(monkeypatch):
    as_platform(monkeypatch, plat.WINDOWS)
    assert "not available on windows" in cli.render_help()
    as_platform(monkeypatch, plat.LINUX)
    assert "not available on" not in cli.render_help()


def test_main_returns_usage_for_unknown_and_ok_for_help():
    assert cli.main(["--help"]) == cli.EXIT_OK
    assert cli.main([]) == cli.EXIT_OK
    assert cli.main(["nope"]) == cli.EXIT_USAGE


def test_main_refuses_an_unported_subcommand_by_naming_the_shell_target(capsys):
    """Reached only by running main.py directly, or by a shim older than the
    registry. `smb` is the remaining POSIX row that is still shell."""
    assert cli.main(["smb"]) == cli.EXIT_USAGE
    assert "still implemented in the shell" in capsys.readouterr().err


def test_main_reports_a_platform_gap(monkeypatch, capsys):
    as_platform(monkeypatch, plat.WINDOWS)
    assert cli.main(["smb"]) == cli.EXIT_USAGE
    assert "not available on windows" in capsys.readouterr().err


def test_version_survives_having_no_clone(monkeypatch):
    monkeypatch.delenv("TERMINAL_STACK_DIR", raising=False)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    monkeypatch.setattr(paths, "clone_candidates", lambda: [])
    text = cli.render_version()
    assert "no terminal-stack clone found" in text
