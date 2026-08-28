"""The managed Ghostty config, ported from three shell implementations to one.

`bootstrap/ts-config.sh` covered macOS and the WSL view of the Windows side,
`$PROFILE`'s `Set-TerminalStackConfig` covered native Windows, and each carried
its own copy of the themeMode -> theme mapping. Both shells now hand off here.

Every test uses a throwaway HOME. `docs/verifying-changes.md` section 4 is
explicit about it, and `off` DELETES FILES -- a test that resolved to the
developer's real `~/.config/ghostty` would remove their config.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import ghostty, store  # noqa: E402
from tstack import platform as plat  # noqa: E402


@pytest.fixture
def home(monkeypatch, tmp_path):
    root = tmp_path / "home"
    root.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: root))
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    monkeypatch.setattr(store, "mirror", lambda: {})
    monkeypatch.setattr(store, "mirror_path", lambda: None)
    store.clear_cache()
    yield root
    store.clear_cache()


def macos(monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.MACOS)


def windows(monkeypatch, local: Path):
    """Pretend to be native Windows, with a real mirror to write to.

    The store routes writes to config.json there rather than to a chezmoi.toml,
    so a test that leaves `mirror_path` as None makes every save raise -- which
    is correct behaviour (a Windows box with no %LOCALAPPDATA% cannot persist
    anything) and not what these tests are about.
    """
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setattr(plat, "local_app_data", lambda: local)
    mirror = local / "terminal-stack" / "config.json"
    monkeypatch.setattr(store, "mirror_path", lambda: mirror)
    store.clear_cache()
    return mirror


def lines(capsys) -> list[str]:
    return capsys.readouterr().out.splitlines()


# ------------------------------------------------------------------- targeting


def test_wsl_targets_the_windows_ghostty_not_a_linux_one(monkeypatch, tmp_path):
    """A combined machine has ONE Ghostty and it is the Windows one. Managing a
    `~/.config/ghostty` inside WSL would configure a GUI that does not exist
    there, and leave the one that does untouched."""
    local = tmp_path / "AppData" / "Local"
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    monkeypatch.setattr(plat, "local_app_data", lambda: local)
    spot = ghostty.target()
    assert spot is not None
    assert spot.kind == ghostty.WINDOWS
    assert spot.directory == local / "ghostty"


def test_the_windows_target_is_the_upstream_dir_not_the_app_named_one(monkeypatch, tmp_path):
    """noctty reads both its own `%LOCALAPPDATA%\\<appname>\\config.ghostty` and
    the upstream-compatible path. `<appname>` is `winghostty` today and `noctty`
    the day the rename ships, so only the upstream one survives the upgrade --
    the other would silently stop being read."""
    windows(monkeypatch, tmp_path)
    spot = ghostty.target()
    assert spot is not None
    assert spot.directory.name == "ghostty"
    assert spot.config.name == "config"
    assert spot.theme == spot.directory / "themes" / "vs-code-light-modern"


def test_native_linux_is_refused_rather_than_guessed(monkeypatch, capsys):
    """Those hosts are headless; there is no GUI to configure. Refusing beats
    writing a config nothing will ever read."""
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    assert ghostty.target() is None
    assert ghostty.status(ROOT, print) == 1
    said = "\n".join(lines(capsys))
    assert "macOS, Windows and WSL only" in said
    # Command-neutral: two entry points reach this, so it may name neither.
    assert "tstack config ghostty:" not in said


# --------------------------------------------------------------- theme mapping


def test_follow_is_a_split_theme_because_that_is_what_tracks_the_os():
    """`follow` cannot be expressed by pinning `window-theme`, and an explicit
    mode cannot be expressed by a split theme. The two directives are not
    interchangeable, which is why both are substituted rather than one derived
    from the other."""
    assert ghostty.theme_tokens("follow") == (
        "dark:Catppuccin Mocha,light:vs-code-light-modern",
        "auto",
    )
    assert ghostty.theme_tokens("light") == ("vs-code-light-modern", "light")
    assert ghostty.theme_tokens("dark") == ("Catppuccin Mocha", "dark")
    # An unrecognised mode falls back to the stack's historical look rather than
    # emitting an empty theme, which Ghostty would reject.
    assert ghostty.theme_tokens("solarized") == ("Catppuccin Mocha", "dark")


def test_the_windows_template_renders_with_no_token_left_behind(monkeypatch, home):
    monkeypatch.setattr(store, "chezmoi_data", lambda: {"themeMode": "follow"})
    body = ghostty.render_windows(ROOT)
    assert body is not None
    assert "__GHOSTTY_THEME__" not in body and "__GHOSTTY_WINDOW_THEME__" not in body
    assert "dark:Catppuccin Mocha,light:vs-code-light-modern" in body
    assert "window-theme = auto" in body


# --------------------------------------------------------------------- status


def test_a_config_we_did_not_write_is_named_as_such(monkeypatch, home, tmp_path, capsys):
    """ "apply will update this" and "apply will REPLACE this" are different
    answers, and the marker in the rendered file is what separates them."""
    windows(monkeypatch, tmp_path)
    spot = ghostty.target()
    assert spot is not None
    spot.directory.mkdir(parents=True)

    assert ghostty.is_ours(spot.config) is None, "absent is a third state, not False"

    spot.config.write_text("font-size = 14\n", encoding="utf-8")
    assert ghostty.is_ours(spot.config) is False
    ghostty.status(ROOT, print)
    assert any("NOT ours" in line for line in lines(capsys))

    spot.config.write_text(f"# {ghostty.OURS}\nfont-size = 14\n", encoding="utf-8")
    assert ghostty.is_ours(spot.config) is True
    ghostty.status(ROOT, print)
    assert any("(ours)" in line for line in lines(capsys))


def test_the_newest_backup_is_chosen_by_name_not_by_mtime(monkeypatch, home, tmp_path):
    """The convention is `.bak.YYYYMMDD` with `.1`, `.2` on a same-day re-run, so
    lexical order IS chronological order. Sorting by mtime would be wrong the
    moment a backup is made with `cp -p`, which preserves the original's time."""
    windows(monkeypatch, tmp_path)
    spot = ghostty.target()
    assert spot is not None
    spot.directory.mkdir(parents=True)
    assert ghostty.newest_backup(spot.directory) is None

    for name in ("config.bak.20260101", "config.bak.20260827", "config.bak.20260827.1"):
        (spot.directory / name).write_text(name, encoding="utf-8")
    newest = ghostty.newest_backup(spot.directory)
    assert newest is not None and newest.name == "config.bak.20260827.1"


# ------------------------------------------------------------------------ off


def test_off_restores_the_backup_rather_than_only_unmanaging(monkeypatch, home, tmp_path, capsys):
    """`off` is a real revert. `run_before_20-backup-ghostty.sh` takes the backup
    that makes it one."""
    windows(monkeypatch, tmp_path)
    spot = ghostty.target()
    assert spot is not None
    spot.theme.parent.mkdir(parents=True)
    spot.config.write_text("ours\n", encoding="utf-8")
    spot.theme.write_text("theme\n", encoding="utf-8")
    (spot.directory / "config.bak.20260101").write_text("yours\n", encoding="utf-8")

    rc = ghostty.turn_off(ROOT, print, lambda: None)
    assert rc == 0
    assert spot.config.read_text(encoding="utf-8") == "yours\n", "the backup came back"
    assert not spot.theme.exists(), "our generated theme is removed"
    assert "restored" in "\n".join(lines(capsys))


def test_off_removes_our_file_when_there_was_nothing_to_restore(
    monkeypatch, home, tmp_path, capsys
):
    windows(monkeypatch, tmp_path)
    spot = ghostty.target()
    assert spot is not None
    spot.directory.mkdir(parents=True)
    spot.config.write_text("ours\n", encoding="utf-8")

    assert ghostty.turn_off(ROOT, print, lambda: None) == 0
    assert not spot.config.exists()
    assert "no backup existed" in "\n".join(lines(capsys))


def test_off_is_never_a_chezmoi_removal_or_a_sync_side_delete():
    """Both of those run on EVERY machine and would wipe a hand-written Ghostty
    config on a box that never opted in. `off` removes for the machine that asked
    and no other, which is why the deletion lives in this command."""
    ignore = (ROOT / ".chezmoiignore").read_text(encoding="utf-8")
    assert "ghostty" in ignore, "off must gate the render..."
    assert ".chezmoiremove" not in ignore, "...but never schedule a removal"
    for rel in ("run_after_90-sync-windows.sh", "scripts/sync-windows.ps1"):
        body = (ROOT / rel).read_text(encoding="utf-8").lower()
        for verb in ("rm -rf", "remove-item"):
            for chunk in body.split(verb)[1:]:
                assert "ghostty" not in chunk[:160], f"{rel}: sync must not delete the Ghostty tree"


def test_on_and_off_both_persist_through_the_one_writer(monkeypatch, home, tmp_path):
    mirror = windows(monkeypatch, tmp_path)
    (tmp_path / "ghostty").mkdir(parents=True)
    calls = []

    ghostty.turn_off(ROOT, lambda _m: None, lambda: calls.append("apply"))
    assert '"ghosttyConfig": "off"' in mirror.read_text(encoding="utf-8")
    ghostty.turn_on(ROOT, lambda _m: None, lambda: calls.append("apply"))
    assert '"ghosttyConfig": "on"' in mirror.read_text(encoding="utf-8")
    assert calls == ["apply", "apply"], "each must re-render, or the setting is inert"


# ------------------------------------------------------------------ the command


def test_the_command_rejects_a_bad_verb_with_a_usage_code(capsys):
    from tstack.commands import ghostty as cmd

    assert cmd.main(["nonsense"]) == 2
    assert "unknown action" in capsys.readouterr().err
    assert cmd.main(["status", "extra"]) == 2
    assert cmd.main(["-h"]) == 0


def test_ghostty_is_in_the_registry_on_both_platforms():
    from tstack import registry

    row = registry.get("ghostty")
    assert row is not None
    assert row.posix == "python" and row.windows == "python"


# -------------------------------------------------------------------- the diff


def test_diff_reports_the_three_answers_it_can_have(monkeypatch, home, tmp_path, capsys):
    """ "Would be created", "up to date", and the actual change. A diff that
    prints nothing when there is nothing to change is not an answer -- it reads
    exactly like a diff that failed."""
    windows(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "chezmoi_data", lambda: {"themeMode": "dark"})
    spot = ghostty.target()
    assert spot is not None
    spot.theme.parent.mkdir(parents=True)

    assert ghostty.diff(ROOT, print) == 0
    assert any("would be created" in line for line in lines(capsys))

    rendered = ghostty.render_windows(ROOT)
    assert rendered is not None
    spot.config.write_text(rendered, encoding="utf-8")
    theme_src = ROOT / "windows/AppData/Local/ghostty/themes/vs-code-light-modern"
    spot.theme.write_text(theme_src.read_text(encoding="utf-8"), encoding="utf-8")
    ghostty.diff(ROOT, print)
    out = "\n".join(lines(capsys))
    assert "ghostty config: up to date" in out and "ghostty theme: up to date" in out

    spot.config.write_text(rendered + "font-size = 99\n", encoding="utf-8")
    ghostty.diff(ROOT, print)
    out = "\n".join(lines(capsys))
    assert "differs from the rendered template" in out
    assert "font-size = 99" in out


def test_a_missing_template_is_reported_rather_than_crashing(monkeypatch, home, tmp_path, capsys):
    windows(monkeypatch, tmp_path)
    (tmp_path / "ghostty").mkdir(parents=True)
    assert ghostty.render_windows(tmp_path / "not-a-clone") is None
    assert ghostty.diff(tmp_path / "not-a-clone", print) == 1
    assert "template is missing" in "\n".join(lines(capsys))


def test_macos_diff_delegates_to_chezmoi_because_chezmoi_owns_those_files(
    monkeypatch, home, capsys
):
    """On macOS both files are chezmoi targets, so its own diff is the honest
    answer; the Windows copy is chezmoi-IGNORED and mirrored by the sync, which
    is why that branch compares against a rendered template instead."""
    macos(monkeypatch)
    seen: list[list[str]] = []

    class Done:
        stdout = ""

    def fake_run(argv, **kwargs):
        seen.append(argv)
        return Done()

    monkeypatch.setattr(plat, "find_chezmoi", lambda: "/usr/bin/chezmoi")
    monkeypatch.setattr(ghostty.subprocess, "run", fake_run)
    assert ghostty.diff(ROOT, print) == 0
    assert seen and seen[0][:3] == ["/usr/bin/chezmoi", "diff", "--"]
    assert "up to date" in "\n".join(lines(capsys))

    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    assert ghostty.diff(ROOT, print) == 1


# ------------------------------------------------------------------ the binary


def test_the_windows_binary_probe_tries_the_post_rename_name_first(monkeypatch, tmp_path):
    """noctty is the rename of winghostty. Probing the new name first means a
    machine with both reports the one it will actually launch."""
    windows(monkeypatch, tmp_path)
    tried: list[str] = []

    def fake_which(name):
        tried.append(name)
        return f"C:/{name}.exe" if name == "winghostty" else None

    monkeypatch.setattr(ghostty.shutil, "which", fake_which)
    assert ghostty.binary() == "C:/winghostty.exe"
    assert tried[0] == "noctty", "the post-rename name is probed first"


def test_wsl_reaches_the_windows_binary_through_interop(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    monkeypatch.setattr(plat, "local_app_data", lambda: tmp_path)
    monkeypatch.setattr(Path, "is_file", lambda self: "noctty" in str(self))
    assert ghostty.binary() == "/mnt/c/Program Files/noctty/noctty.com"


def test_windows_never_claims_validate_ok_because_it_cannot_check(
    monkeypatch, home, tmp_path, capsys
):
    """`+validate-config` fails with FileTooBig on winghostty 1.3.123 even for a
    14-byte config, and `+show-config` reports nothing for an unknown key or a
    bad value. There is no honest syntax gate on that build, so saying
    "validate: ok" would be a lie."""
    windows(monkeypatch, tmp_path)
    spot = ghostty.target()
    assert spot is not None
    spot.directory.mkdir(parents=True)
    spot.config.write_text("x\n", encoding="utf-8")
    monkeypatch.setattr(ghostty, "binary", lambda: "C:/winghostty.exe")
    monkeypatch.setattr(ghostty, "_run", lambda *a, **k: None)

    assert ghostty.status(ROOT, print) == 0
    out = "\n".join(lines(capsys))
    assert "validate: unavailable on this build" in out
    assert "validate: ok" not in out


def test_macos_reports_a_failing_validate_rather_than_swallowing_it(
    monkeypatch, home, tmp_path, capsys
):
    macos(monkeypatch)
    cfg = home / ".config" / "ghostty"
    cfg.mkdir(parents=True)
    (cfg / "config").write_text("nonsense-key = 1\n", encoding="utf-8")
    monkeypatch.setattr(ghostty, "binary", lambda: "/usr/bin/ghostty")

    class Bad:
        returncode = 1
        stdout = "config:1: unknown field\n"
        stderr = ""

    class Ok:
        returncode = 0
        stdout = "Ghostty 1.3.1\n"
        stderr = ""

    calls = {"n": 0}

    def fake_run(argv, timeout=20):
        calls["n"] += 1
        return Ok() if "--version" in argv else Bad()

    monkeypatch.setattr(ghostty, "_run", fake_run)
    assert ghostty.status(ROOT, print) == 0
    out = "\n".join(lines(capsys))
    assert "ghostty: Ghostty 1.3.1" in out
    assert "validate: FAILED" in out
    assert "unknown field" in out


def test_an_uninstalled_ghostty_says_so_per_platform(monkeypatch, home, tmp_path, capsys):
    macos(monkeypatch)
    monkeypatch.setattr(ghostty, "binary", lambda: None)
    ghostty.status(ROOT, print)
    assert "tstack config wizard installs the cask" in "\n".join(lines(capsys))

    windows(monkeypatch, tmp_path)
    monkeypatch.setattr(ghostty, "binary", lambda: None)
    ghostty.status(ROOT, print)
    assert "noctty/winghostty: not installed" in "\n".join(lines(capsys))


# ------------------------------------------------------------------ the command


def test_the_command_routes_every_verb(monkeypatch, home, tmp_path, capsys):
    from tstack.commands import ghostty as cmd

    windows(monkeypatch, tmp_path)
    (tmp_path / "ghostty").mkdir(parents=True)
    monkeypatch.setattr(cmd.paths, "resolve_source_dir", lambda: ROOT)
    monkeypatch.setattr(store, "chezmoi_data", lambda: {"themeMode": "dark"})

    assert cmd.main([]) == 0, "no verb means status"
    assert "ghostty config:" in "\n".join(lines(capsys))
    assert cmd.main(["diff"]) == 0
    capsys.readouterr()

    assert cmd.main(["on", "--dry-run"]) == 0
    assert "would set ghosttyConfig = on" in "\n".join(lines(capsys))
    assert not (tmp_path / "terminal-stack" / "config.json").exists(), "dry-run writes nothing"

    applied: list[str] = []
    monkeypatch.setattr(cmd, "_apply", lambda: applied.append("x"))
    assert cmd.main(["off"]) == 0
    assert applied == ["x"]


def test_the_command_needs_a_clone_and_says_which_variable_fixes_it(monkeypatch, capsys):
    from tstack import paths as tspaths
    from tstack.commands import ghostty as cmd

    def missing():
        raise tspaths.CloneNotFound("nope")

    monkeypatch.setattr(cmd.paths, "resolve_source_dir", missing)
    assert cmd.main(["status"]) == 1
    assert "TERMINAL_STACK_DIR" in capsys.readouterr().err


# ------------------------------------------------------------------ the apply


class Ran:
    """A stand-in for CompletedProcess.

    Patching `subprocess.run` patches the shared module, so anything else that
    runs a command during the test sees this too -- returning None made
    paths.py trip over `.returncode`.
    """

    returncode = 0
    stdout = ""
    stderr = ""


def test_the_apply_route_differs_by_platform(monkeypatch, tmp_path):
    """On Windows there is no chezmoi: `scripts/sync-windows.ps1` IS the apply,
    and it is what writes the Ghostty files on that side. Running `chezmoi
    apply` there would do nothing and report success."""
    from tstack.commands import ghostty as cmd

    ran: list[list[str]] = []
    monkeypatch.setattr(cmd.store, "chezmoi_init", lambda: None)
    monkeypatch.setattr(cmd.subprocess, "run", lambda argv, **kw: (ran.append(argv), Ran())[1])
    monkeypatch.setattr(cmd.paths, "resolve_source_dir", lambda: ROOT)

    monkeypatch.setattr(cmd.plat, "kind", lambda: cmd.plat.MACOS)
    monkeypatch.setattr(cmd.plat, "find_chezmoi", lambda: "/usr/bin/chezmoi")
    cmd._apply()
    assert ran and ran[-1][:2] == ["/usr/bin/chezmoi", "apply"]

    ran.clear()
    monkeypatch.setattr(cmd.plat, "kind", lambda: cmd.plat.WINDOWS)
    monkeypatch.setattr(cmd.plat, "find_pwsh", lambda: "pwsh")
    cmd._apply()
    assert ran, "the Windows apply is the sync script"
    assert ran[-1][0] == "pwsh"
    assert any("sync-windows.ps1" in str(a) for a in ran[-1])


def test_the_apply_is_a_no_op_rather_than_a_crash_when_the_tool_is_missing(monkeypatch, tmp_path):
    """A machine mid-bootstrap has neither yet. Failing here would abort a `off`
    that has already restored the backup, which is the half-done state."""
    from tstack.commands import ghostty as cmd

    ran: list[list[str]] = []
    monkeypatch.setattr(cmd.store, "chezmoi_init", lambda: None)
    monkeypatch.setattr(cmd.subprocess, "run", lambda argv, **kw: (ran.append(argv), Ran())[1])

    def applied() -> list[list[str]]:
        # `resolve_source_dir` shells out to git, and the stub above patches the
        # shared module, so it lands in `ran` too. What matters is that no APPLY
        # was attempted.
        # Match the COMMAND, not the argv text: resolve_source_dir probes a
        # chezmoi source directory, so `git -C <...chezmoi...>` matches a
        # substring search and is not an apply.
        return [a for a in ran if a and a[0] != "git"]

    monkeypatch.setattr(cmd.plat, "kind", lambda: cmd.plat.MACOS)
    monkeypatch.setattr(cmd.plat, "find_chezmoi", lambda: None)
    cmd._apply()
    assert applied() == []

    monkeypatch.setattr(cmd.plat, "kind", lambda: cmd.plat.WINDOWS)
    monkeypatch.setattr(cmd.plat, "find_pwsh", lambda: None)
    cmd._apply()
    assert applied() == []


def test_the_windows_apply_needs_a_clone_and_says_nothing_when_there_is_none(monkeypatch):
    from tstack import paths as tspaths
    from tstack.commands import ghostty as cmd

    ran: list[list[str]] = []
    monkeypatch.setattr(cmd.store, "chezmoi_init", lambda: None)
    monkeypatch.setattr(cmd.subprocess, "run", lambda argv, **kw: (ran.append(argv), Ran())[1])
    monkeypatch.setattr(cmd.plat, "kind", lambda: cmd.plat.WINDOWS)
    monkeypatch.setattr(cmd.plat, "find_pwsh", lambda: "pwsh")

    def missing():
        raise tspaths.CloneNotFound("nope")

    monkeypatch.setattr(cmd.paths, "resolve_source_dir", missing)
    cmd._apply()
    assert [a for a in ran if a and a[0] != "git"] == []
