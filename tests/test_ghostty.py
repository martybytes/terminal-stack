"""The managed Ghostty config: one implementation, and now one platform.

`bootstrap/ts-config.sh` and `$PROFILE`'s `Set-TerminalStackConfig` both hand off
here. The Windows target these tests used to cover -- the noctty mirror under
`%LOCALAPPDATA%\\ghostty\\`, its token-substituted template and its interop binary
probe -- is gone, so macOS is the only target left and every other platform is a
refusal.

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


def deployed(monkeypatch, home: Path):
    """Pretend to be macOS and hand back the target, its directory made.

    On macOS `store.set` writes chezmoi.toml under the throwaway HOME rather than
    a config.json mirror, so a save round-trips through a real file without
    touching anything of the developer's.
    """
    macos(monkeypatch)
    spot = ghostty.target()
    assert spot is not None
    spot.theme.parent.mkdir(parents=True, exist_ok=True)
    return spot


class Ran:
    """A stand-in for CompletedProcess.

    Patching `subprocess.run` patches the shared module, so anything else that
    runs a command during the test sees this too -- returning None made
    paths.py trip over `.returncode`.
    """

    returncode = 0
    stdout = ""
    stderr = ""


def lines(capsys) -> list[str]:
    return capsys.readouterr().out.splitlines()


# ------------------------------------------------------------------- targeting


def test_macos_is_the_only_target(monkeypatch, home):
    """`~/.config/ghostty/`, with the generated light theme beside it."""
    macos(monkeypatch)
    spot = ghostty.target()
    assert spot is not None
    assert spot.directory == home / ".config" / "ghostty"
    assert spot.config == spot.directory / "config"
    assert spot.theme == spot.directory / "themes" / "vs-code-light-modern"


@pytest.mark.parametrize("kind", ["LINUX", "WSL", "WINDOWS"])
def test_every_other_platform_is_refused_rather_than_guessed(monkeypatch, capsys, kind):
    """Linux hosts here are headless, and there is no Windows Ghostty this stack
    configures any more. WSL is the one worth pinning: it used to resolve to the
    Windows install, so a regression there would write to a /mnt/c path that
    nothing on the machine reads -- silently, and reporting success."""
    monkeypatch.setattr(plat, "kind", lambda: getattr(plat, kind))
    assert ghostty.target() is None
    assert ghostty.status(ROOT, print) == 1
    said = "\n".join(lines(capsys))
    assert "macOS only" in said
    assert "/mnt/c" not in said and "LOCALAPPDATA" not in said
    # Command-neutral: two entry points reach this, so it may name neither.
    assert "tstack config ghostty:" not in said




# --------------------------------------------------------------------- status


def test_a_config_we_did_not_write_is_named_as_such(monkeypatch, home, capsys):
    """ "apply will update this" and "apply will REPLACE this" are different
    answers, and the marker in the rendered file is what separates them."""
    spot = deployed(monkeypatch, home)

    assert ghostty.is_ours(spot.config) is None, "absent is a third state, not False"

    spot.config.write_text("font-size = 14\n", encoding="utf-8")
    assert ghostty.is_ours(spot.config) is False
    ghostty.status(ROOT, print)
    assert any("NOT ours" in line for line in lines(capsys))

    spot.config.write_text(f"# {ghostty.OURS}\nfont-size = 14\n", encoding="utf-8")
    assert ghostty.is_ours(spot.config) is True
    ghostty.status(ROOT, print)
    assert any("(ours)" in line for line in lines(capsys))


def test_the_newest_backup_is_chosen_by_name_not_by_mtime(monkeypatch, home):
    """The convention is `.bak.YYYYMMDD` with `.1`, `.2` on a same-day re-run, so
    lexical order IS chronological order. Sorting by mtime would be wrong the
    moment a backup is made with `cp -p`, which preserves the original's time."""
    spot = deployed(monkeypatch, home)
    assert ghostty.newest_backup(spot.directory) is None

    for name in ("config.bak.20260101", "config.bak.20260827", "config.bak.20260827.1"):
        (spot.directory / name).write_text(name, encoding="utf-8")
    newest = ghostty.newest_backup(spot.directory)
    assert newest is not None and newest.name == "config.bak.20260827.1"


# ------------------------------------------------------------------------ off


def test_off_restores_the_backup_rather_than_only_unmanaging(monkeypatch, home, capsys):
    """`off` is a real revert. `run_before_20-backup-ghostty.sh` takes the backup
    that makes it one."""
    spot = deployed(monkeypatch, home)
    spot.config.write_text("ours\n", encoding="utf-8")
    spot.theme.write_text("theme\n", encoding="utf-8")
    (spot.directory / "config.bak.20260101").write_text("yours\n", encoding="utf-8")

    rc = ghostty.turn_off(ROOT, print, lambda: None)
    assert rc == 0
    assert spot.config.read_text(encoding="utf-8") == "yours\n", "the backup came back"
    assert not spot.theme.exists(), "our generated theme is removed"
    assert "restored" in "\n".join(lines(capsys))


def test_off_removes_our_file_when_there_was_nothing_to_restore(monkeypatch, home, capsys):
    spot = deployed(monkeypatch, home)
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
    # Neither sync knows about Ghostty any more, which settles the question for
    # the Windows side more firmly than a delete-verb scan ever did.
    for rel in ("run_after_90-sync-windows.sh", "scripts/sync-windows.ps1"):
        body = (ROOT / rel).read_text(encoding="utf-8").lower()
        assert "ghostty" not in body, f"{rel}: the Windows Ghostty target is gone"


def test_on_and_off_both_persist_through_the_one_writer(monkeypatch, home):
    deployed(monkeypatch, home)
    toml = home / ".config" / "chezmoi" / "chezmoi.toml"
    calls = []

    ghostty.turn_off(ROOT, lambda _m: None, lambda: calls.append("apply"))
    assert 'ghosttyConfig = "off"' in toml.read_text(encoding="utf-8")
    ghostty.turn_on(ROOT, lambda _m: None, lambda: calls.append("apply"))
    assert 'ghosttyConfig = "on"' in toml.read_text(encoding="utf-8")
    assert calls == ["apply", "apply"], "each must re-render, or the setting is inert"


# ------------------------------------------------------------------ the command


def test_the_command_rejects_a_bad_verb_with_a_usage_code(capsys):
    from tstack.commands import ghostty as cmd

    assert cmd.main(["nonsense"]) == 2
    assert "unknown action" in capsys.readouterr().err
    assert cmd.main(["status", "extra"]) == 2
    assert cmd.main(["-h"]) == 0


def test_the_registry_says_posix_python_and_windows_unsupported():
    """`-` rather than a missing row: the shim then says "not supported on this
    platform" plainly instead of reporting a command that cannot be found."""
    from tstack import registry

    row = registry.get("ghostty")
    assert row is not None
    assert row.posix == "python"
    assert row.windows == "-"


# -------------------------------------------------------------------- the diff


def test_diff_delegates_to_chezmoi_because_chezmoi_owns_those_files(
    monkeypatch, home, capsys
):
    """Both files are chezmoi targets, so its own diff is the honest answer --
    and it is the only route left. The second branch compared against a rendered
    template because the Windows copy was chezmoi-IGNORED and mirrored by the
    sync; it went with that copy.

    Silence is not an answer here: chezmoi prints nothing when there is nothing
    to change, which reads exactly like a diff that failed."""
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


def test_an_uninstalled_ghostty_names_the_thing_that_installs_it(monkeypatch, home, capsys):
    macos(monkeypatch)
    monkeypatch.setattr(ghostty, "binary", lambda: None)
    ghostty.status(ROOT, print)
    assert "tstack config wizard installs the cask" in "\n".join(lines(capsys))


# ------------------------------------------------------------------ the command


def test_the_command_routes_every_verb(monkeypatch, home, capsys):
    from tstack.commands import ghostty as cmd

    deployed(monkeypatch, home)
    monkeypatch.setattr(cmd.paths, "resolve_source_dir", lambda: ROOT)
    monkeypatch.setattr(store, "chezmoi_data", lambda: {"themeMode": "dark"})
    # `diff` delegates to chezmoi and rc=1 when it is absent, which the throwaway
    # HOME makes true. Routing is what this test is about, not that outcome.
    monkeypatch.setattr(plat, "find_chezmoi", lambda: "/usr/bin/chezmoi")
    monkeypatch.setattr(ghostty.subprocess, "run", lambda *a, **k: Ran())

    assert cmd.main([]) == 0, "no verb means status"
    assert "ghostty config:" in "\n".join(lines(capsys))
    assert cmd.main(["diff"]) == 0
    capsys.readouterr()

    assert cmd.main(["on", "--dry-run"]) == 0
    assert "would set ghosttyConfig = on" in "\n".join(lines(capsys))
    toml = home / ".config" / "chezmoi" / "chezmoi.toml"
    assert not toml.exists(), "dry-run writes nothing"

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


def test_the_apply_is_chezmoi_and_never_the_windows_sync(monkeypatch, tmp_path):
    """One route: these files are chezmoi's. The Windows branch drove
    `scripts/sync-windows.ps1`, which was what wrote the mirror -- with no mirror
    to write, running it here would do nothing and report success."""
    from tstack.commands import ghostty as cmd

    ran: list[list[str]] = []
    monkeypatch.setattr(cmd.store, "chezmoi_init", lambda: None)
    monkeypatch.setattr(cmd.subprocess, "run", lambda argv, **kw: (ran.append(argv), Ran())[1])
    monkeypatch.setattr(cmd.paths, "resolve_source_dir", lambda: ROOT)

    monkeypatch.setattr(cmd.plat, "kind", lambda: cmd.plat.MACOS)
    monkeypatch.setattr(cmd.plat, "find_chezmoi", lambda: "/usr/bin/chezmoi")
    cmd._apply()
    assert ran and ran[-1][:2] == ["/usr/bin/chezmoi", "apply"]
    assert not any("sync-windows.ps1" in str(a) for argv in ran for a in argv)


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


# --------------------------------------------------------------------- the ssh
# fix


def test_the_config_opts_into_the_ssh_shell_integration_features():
    """The one directive that makes remote shells usable.

    Ghostty announces TERM=xterm-ghostty and ssh forwards it; a host with no
    xterm-ghostty terminfo entry cannot resolve kbs or kdch1, so backspace
    inserts junk and Delete does nothing. Neither feature is in Ghostty's default
    set, and naming ANY value for this key replaces that set -- so both have to
    be spelled out here or they are simply off.

    ssh-terminfo installs the real entry per host; ssh-env is the fallback that
    sets TERM=xterm-256color where that upload cannot happen. Listing only one is
    a half fix: terminfo alone leaves hosts without `tic` broken, and env alone
    gives up Ghostty's own capabilities everywhere.
    """
    body = (ROOT / "dot_config/ghostty/config.tmpl").read_text(encoding="utf-8")
    lines_ = [l for l in body.splitlines() if l.startswith("shell-integration-features")]
    assert len(lines_) == 1, "exactly one such line, or the last one silently wins"
    value = lines_[0].split("=", 1)[1].strip()
    features = [f.strip() for f in value.split(",")]
    assert "ssh-terminfo" in features and "ssh-env" in features
    # The rest of the set has to survive the edit that adds them.
    assert "no-cursor" in features and "sudo" in features and "title" in features


def test_no_config_pins_term_globally():
    """`term = xterm-256color` would fix ssh by giving up Ghostty's terminfo in
    LOCAL panes too. The ssh features are scoped to ssh; a global pin is not."""
    body = (ROOT / "dot_config/ghostty/config.tmpl").read_text(encoding="utf-8")
    assert not [l for l in body.splitlines() if l.startswith("term ")], (
        "fix ssh with the ssh features, not by lying about TERM everywhere"
    )
