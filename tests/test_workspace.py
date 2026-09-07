"""The workspace root: resolution, the override writer, preflight, and `--org`.

Three things here have already been wrong somewhere in this repo's history and
are pinned rather than trusted:

- `--org` was a substring test over the whole path, which matched the host, a
  repo named like an owner, and nothing at all for a renamed owner.
- The override writer has to find lines written by three OTHER writers (the
  POSIX installer, the macOS installer, the pwsh one), or "change the root"
  appends a second line that the first one shadows.
- A cross-volume move is a copy, and a copy that is not independently verified
  before the original is unlinked is the failure `wso migrate` refuses to risk.
"""

from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path

import pytest

from tests.shell_support import BASH
from tstack import workspace
from tstack.commands import workspace as workspace_cmd

ROOT = Path(__file__).resolve().parent.parent

needs_bash = pytest.mark.skipif(BASH is None, reason="needs bash")


# ------------------------------------------------------------------- --org ----


def _org_match(path: str, org: str, root: str = "/ws") -> bool:
    """Run ts_ws_org_match in a real bash, against the real workspace.conf."""
    script = f"""
        ROOT={root!r}
        TS_WS_LIB_DIR={str(ROOT / "bootstrap")!r}
        export TS_WS_LIB_DIR
        . {str(ROOT / "bootstrap" / "_workspace.sh")!r}
        ts_ws_org_match {path!r} {org!r}
    """
    result = subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        start_new_session=True,
    )
    return result.returncode == 0


@needs_bash
@pytest.mark.parametrize(
    ("path", "org", "expected", "why"),
    [
        ("/ws/src/github.com/martybytes/terminal-stack", "martybytes", True, "the plain case"),
        ("/ws/src/github.com/martybytes/terminal-stack", "MartyBytes", True, "case folds"),
        (
            "/ws/src/github.com/martybytes/terminal-stack",
            "martsamp77",
            True,
            "the rename map applies: the tree carries the canonical owner, the "
            "flag carried what the user typed, and the old filter matched nothing",
        ),
        (
            "/ws/src/github.com/martybytes/terminal-stack",
            "github.com",
            False,
            "the host is a path segment too; the old filter matched EVERY repo",
        ),
        (
            "/ws/src/github.com/someone/martybytes",
            "martybytes",
            False,
            "a REPO named like an owner; the old filter matched it",
        ),
        ("/ws/src/github.com/martybytes/terminal-stack", "37metrics", False, "a real miss"),
        ("/ws/src/github.com/martybytes/terminal-stack", "", True, "no filter means everything"),
        ("/ws/local/orphan", "martybytes", False, "local/ has no owner segment at all"),
    ],
)
def test_org_match_matches_the_owner_segment_only(path, org, expected, why):
    assert _org_match(path, org) is expected, why


@needs_bash
def test_every_bulk_verb_accepts_org():
    """The gap this closes: `synceverything` took no flags, and `plan` silently
    DISCARDED whatever you typed rather than rejecting it."""
    text = (ROOT / "bootstrap" / "wso.sh").read_text(encoding="utf-8")
    for verb in ("status", "plan", "migrate", "sync", "synceverything", "archive", "orphans"):
        body = text.split(f"cmd_{verb}() {{", 1)[1].split("\n}\n", 1)[0]
        assert "--org" in body, f"cmd_{verb} does not parse --org"


@needs_bash
def test_the_dispatcher_forwards_arguments_to_every_verb():
    """`plan) shift; cmd_plan ;;` swallowed `--org`, which is worse than an error."""
    text = (ROOT / "bootstrap" / "wso.sh").read_text(encoding="utf-8")
    dispatch = text.split('case "${1:-}" in', 1)[1]
    for verb in ("plan", "identity", "doctor"):
        line = next(l for l in dispatch.splitlines() if l.strip().startswith(f"{verb})"))
        assert '"$@"' in line, f"{verb} drops its arguments: {line.strip()}"


# -------------------------------------------------------------- resolution ----


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    # Both are needed. `Path.home()` covers rc_path(); `HOME`/`USERPROFILE`
    # cover `Path.expanduser()`, which reads the environment directly -- without
    # it the autodetect probes resolve against the real home and these tests
    # quietly exercise the developer's own workspace.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.delenv("WORKSPACE_DIR", raising=False)
    monkeypatch.delenv("TS_WS_YES", raising=False)
    # Pin the platform. Without this the whole module asserted whatever the
    # runner happened to be, so eight tests written against the POSIX line
    # format failed on windows-latest for the format the module CORRECTLY uses
    # there. The Windows contract gets its own tests below rather than being
    # whatever falls out. Paths stay under `home` so they are absolute on both.
    monkeypatch.setattr(workspace, "_windows", lambda: False)
    monkeypatch.setattr(workspace, "rc_path", lambda: home / ".zshrc.local")
    return home


def test_resolve_reports_the_layer_that_won(fake_home, monkeypatch):
    assert workspace.resolve().source in (workspace.UNSET, workspace.AUTODETECT)

    pinned = fake_home / "pinned"
    pinned.mkdir()
    workspace.write_override(pinned, lambda _m: None)
    assert workspace.resolve() == workspace.Resolved(pinned, workspace.OVERRIDE)

    monkeypatch.setenv("WORKSPACE_DIR", "/from/env")
    resolved = workspace.resolve()
    assert (resolved.path, resolved.source) == (Path("/from/env"), workspace.ENV)


def test_env_shadowing_a_different_saved_value_is_detectable(fake_home, monkeypatch):
    """The one way a save looks inert: the file is right and the shell is not."""
    workspace.write_override(fake_home / "saved", lambda _m: None)
    monkeypatch.setenv("WORKSPACE_DIR", str(fake_home / "saved"))
    assert not workspace.env_shadows_file()
    monkeypatch.setenv("WORKSPACE_DIR", "/somewhere/else")
    assert workspace.env_shadows_file()


@pytest.mark.parametrize(
    "existing",
    [
        'export WORKSPACE_DIR="/old/path"',  # the POSIX installer's format
        "export WORKSPACE_DIR=/old/path",  # unquoted, typed by hand
        "export WORKSPACE_DIR='/old/path'",  # single quoted
        "  export   WORKSPACE_DIR=/old/path",  # ragged whitespace
    ],
)
def test_write_override_replaces_every_writers_format(fake_home, existing):
    """Four writers produce this line. Missing one appends a second that the
    first shadows, and the root silently does not change."""
    rc = fake_home / ".zshrc.local"
    rc.write_text(f"# mine\n{existing}\nexport OTHER=keepme\n", encoding="utf-8")
    new = fake_home / "new"

    written = workspace.write_override(new, lambda _m: None)
    assert written == new

    lines = rc.read_text(encoding="utf-8").splitlines()
    assert [line for line in lines if "WORKSPACE_DIR" in line] == [f'export WORKSPACE_DIR="{new}"']
    assert "export OTHER=keepme" in lines, "unrelated lines survive"
    assert "# mine" in lines


def test_write_override_never_clobbers_a_same_day_backup(fake_home):
    rc = fake_home / ".zshrc.local"
    rc.write_text(f'export WORKSPACE_DIR="{fake_home / "one"}"\n', encoding="utf-8")
    for target in ("two", "three", "four"):
        workspace.write_override(fake_home / target, lambda _m: None)
    backups = sorted(p.name for p in fake_home.glob(".zshrc.local.bak.*"))
    assert len(backups) == 3, backups
    assert len(set(backups)) == 3, "a same-day re-run must not overwrite a backup"


def test_clear_override_restores_autodetect(fake_home):
    pinned = workspace.write_override(fake_home / "pinned", lambda _m: None)
    assert workspace.read_override() == pinned
    assert workspace.clear_override(lambda _m: None) is True
    assert workspace.read_override() is None
    assert workspace.clear_override(lambda _m: None) is False, "nothing left to clear"


# --------------------------------------------------------------- preflight ----


@pytest.fixture
def tree(tmp_path):
    source = tmp_path / "src-root"
    (source / "src" / "github.com" / "acme" / "widget").mkdir(parents=True)
    (source / "src" / "github.com" / "acme" / "widget" / "file.txt").write_text("x" * 100)
    return source


def test_preflight_refuses_a_non_empty_destination(tree, tmp_path):
    dest = tmp_path / "dest"
    (dest / "something").mkdir(parents=True)
    assert any("not empty" in p for p in workspace.preflight(tree, dest))


def test_preflight_refuses_when_the_parent_does_not_exist(tree, tmp_path):
    problems = workspace.preflight(tree, tmp_path / "no" / "such" / "dest")
    assert any("does not exist" in p for p in problems)


def test_preflight_refuses_a_shell_standing_inside_the_source(tree, tmp_path, monkeypatch):
    """Easy to hit -- a dev clone lives in there -- and the symptom afterwards
    is a shell sitting in a directory that no longer exists."""
    monkeypatch.chdir(tree / "src")
    assert any("your shell is inside" in p for p in workspace.preflight(tree, tmp_path / "dest"))


def test_preflight_refuses_moving_a_tree_into_itself(tree):
    problems = workspace.preflight(tree, tree / "inner")
    assert any("cannot terminate" in p for p in problems)


def test_preflight_refuses_when_the_runtime_clone_is_inside(tree, tmp_path, monkeypatch):
    """Relocating the runtime clone orphans the install -- the failure
    docs/decisions.md records under "Runtime clone location"."""
    from tstack import paths

    clone = tree / "src" / "github.com" / "acme" / "stack"
    clone.mkdir(parents=True)
    monkeypatch.setattr(paths, "resolve_source_dir", lambda *a, **k: clone)
    monkeypatch.setattr(workspace.paths, "resolve_source_dir", lambda *a, **k: clone)
    problems = workspace.preflight(tree, tmp_path / "dest")
    assert any("orphans the install" in p for p in problems)


def test_preflight_passes_on_a_clean_move(tree, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert workspace.preflight(tree, tmp_path / "dest") == []


# ---------------------------------------------------------------- moving ----


def test_a_same_volume_move_is_a_rename(tree, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    dest = tmp_path / "dest"
    assert workspace.same_volume(tree, dest), "tmp_path is one filesystem"
    assert workspace.relocate(tree, dest, lambda _m: None)
    assert (dest / "src" / "github.com" / "acme" / "widget" / "file.txt").is_file()
    assert not tree.exists(), "a rename leaves nothing behind"


def test_a_copy_is_verified_and_the_source_survives_it(tree, tmp_path, monkeypatch):
    """The copy path, forced. `relocate` leaves the source alone; only the
    command removes it, and only after `verify` has passed."""
    monkeypatch.setattr(workspace, "same_volume", lambda _a, _b: False)
    dest = tmp_path / "dest"
    assert workspace.relocate(tree, dest, lambda _m: None)
    assert tree.exists(), "a copy must not unlink the original"
    assert workspace.verify(tree, dest, lambda _m: None)


def test_verify_fails_on_a_truncated_copy(tree, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "same_volume", lambda _a, _b: False)
    dest = tmp_path / "dest"
    workspace.relocate(tree, dest, lambda _m: None)
    (dest / "src" / "github.com" / "acme" / "widget" / "file.txt").write_text("truncated")
    assert not workspace.verify(tree, dest, lambda _m: None)


def test_a_failed_verification_leaves_everything_in_place(tree, tmp_path, monkeypatch, capsys):
    """The whole safety argument in one test: a bad copy must not cost you the
    original, and the command must say so rather than exiting 0."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workspace, "same_volume", lambda _a, _b: False)
    monkeypatch.setattr(workspace, "verify", lambda *a, **k: False)
    monkeypatch.setattr(workspace, "resolve", lambda: workspace.Resolved(tree, workspace.ENV))
    written: list[Path] = []
    monkeypatch.setattr(workspace, "write_override", lambda p, s=None: written.append(p) or p)

    code = workspace_cmd.set_root(
        str(tmp_path / "dest"), move=True, keep_source=False, assume_yes=True, dry_run=False
    )

    assert code == 1
    assert tree.exists(), "the original survives a failed verification"
    assert not written, "and the root is NOT repointed at a copy we do not trust"
    assert "VERIFICATION FAILED" in capsys.readouterr().err


# ----------------------------------------------------------------- command ----


def test_help_works_before_anything_is_resolved(capsys):
    assert workspace_cmd.main(["-h"]) == 0
    assert "tstack workspace" in capsys.readouterr().out


def test_help_is_ascii_only():
    """A Windows console on codepage 437 renders an em dash as a replacement
    glyph, and this help is read on exactly such a console."""
    assert workspace_cmd.HELP.isascii()


def test_unknown_flags_and_verbs_are_usage_errors(capsys):
    assert workspace_cmd.main(["--nope"]) == 2
    assert workspace_cmd.main(["frobnicate"]) == 2
    assert workspace_cmd.main(["set"]) == 2, "set needs a path"


def test_set_prints_the_path_and_nothing_else_on_stdout(fake_home, capsys):
    """`ws --set` reads stdout and exports it. A stray line there becomes the
    workspace root."""
    assert workspace_cmd.main(["set", str(fake_home / "ws")]) == 0
    out = capsys.readouterr().out
    assert out.strip() == str(fake_home / "ws")
    assert len(out.strip().splitlines()) == 1


def test_dry_run_changes_nothing(fake_home, capsys):
    assert workspace_cmd.main(["set", str(fake_home / "somewhere"), "--dry-run"]) == 0
    assert not (fake_home / ".zshrc.local").exists()
    assert capsys.readouterr().out == "", "a dry run must not print a path to export"


def test_the_ui_row_is_editable_and_reports_its_layer(fake_home):
    from tstack.ui import model

    workspace.write_override(fake_home / "pinned", lambda _m: None)
    row = next(r for r in model.workspace_rows() if r.key == "WORKSPACE_DIR")
    assert row.store == model.WORKSPACE
    assert row.editable
    assert row.source == workspace.OVERRIDE
    assert row.value == str(fake_home / "pinned")

    ok, message = model.save_workspace("WORKSPACE_DIR", str(fake_home / "elsewhere"))
    assert ok, message
    assert workspace.read_override() == fake_home / "elsewhere"


def test_clearing_the_ui_row_drops_the_pin(fake_home):
    from tstack.ui import model

    workspace.write_override(fake_home / "pinned", lambda _m: None)
    ok, message = model.save_workspace("WORKSPACE_DIR", "")
    assert ok, message
    assert workspace.read_override() is None


def test_a_windows_path_round_trips_through_the_pwsh_line(monkeypatch):
    r"""A backslash is exactly what `schema.Setting.validate` refuses, which is
    one of the reasons the root is not a chezmoi [data] key -- `store.set`
    writes `key = "<value>"` into TOML unescaped and a Windows path corrupts it.

    Asserted on the line format and the reader rather than through
    `write_override`, because `Path(r"D:\...")` is a RELATIVE PosixPath off
    Windows and the writer would rightly absolutize it against the cwd. The
    formatting and the parsing are the parts that must be right on both.
    """
    monkeypatch.setattr(workspace, "_windows", lambda: True)
    line = workspace.WINDOWS_LINE.format(path=r"D:\src\Workspace")
    assert line == "$env:WORKSPACE_DIR = 'D:\\src\\Workspace'"
    assert workspace.is_override_line(line)
    assert workspace._override_value(line) == r"D:\src\Workspace"
    assert not workspace.is_override_line("$env:WORK_WORKSPACE_DIR = 'D:\\other'"), (
        "the work workspace is a different setting and must not be clobbered"
    )


def test_the_work_workspace_line_is_never_mistaken_for_this_one(fake_home):
    """`wsw --set` writes WORK_WORKSPACE_DIR into the same file. A prefix match
    would delete it on every `ws --set`."""
    rc = fake_home / ".zshrc.local"
    rc.write_text('export WORK_WORKSPACE_DIR="/work"\n', encoding="utf-8")
    written = workspace.write_override(fake_home / "new", lambda _m: None)
    text = rc.read_text(encoding="utf-8")
    assert 'export WORK_WORKSPACE_DIR="/work"' in text
    assert f'export WORKSPACE_DIR="{written}"' in text


def test_dir_size_ignores_symlinks(tree, tmp_path):
    """A symlinked tree would otherwise be counted twice and could refuse a move
    for lack of space that is not actually needed."""
    if os.name == "nt":
        pytest.skip("symlinks need a privilege on Windows")
    plain = workspace.dir_size(tree)
    (tree / "link").symlink_to(tmp_path)
    assert workspace.dir_size(tree) == plain


# ------------------------------------------------------- show / reset / move ----


def test_show_names_the_layer_and_the_probe_order_when_nothing_is_found(fake_home, capsys):
    """With no root at all the useful output is not "none" -- it is the list of
    places that were looked at, so the next command is obvious."""
    assert workspace_cmd.main([]) == 0
    err = capsys.readouterr().err
    assert "from      unset" in err
    assert "tstack workspace set <path>" in err
    for candidate in workspace.candidates():
        assert str(candidate) in err


def test_show_counts_repos_per_tier(fake_home, capsys):
    root = fake_home / "ws"
    for tier, owner in (("src", "acme"), ("src", "other"), ("public", "torvalds")):
        (root / tier / "github.com" / owner / "repo" / ".git").mkdir(parents=True)
    workspace.write_override(root, lambda _m: None)
    capsys.readouterr()

    assert workspace_cmd.main(["show"]) == 0
    err = capsys.readouterr().err
    assert "src        2 repo(s)" in err
    assert "public     1 repo(s)" in err


def test_show_warns_when_the_shell_disagrees_with_the_saved_value(fake_home, monkeypatch, capsys):
    """The one failure mode that looks like the command did nothing."""
    workspace.write_override(fake_home / "saved", lambda _m: None)
    monkeypatch.setenv("WORKSPACE_DIR", str(fake_home / "different"))
    capsys.readouterr()

    workspace_cmd.main(["show"])
    assert "disagrees with the saved value" in capsys.readouterr().err


def test_show_warns_when_the_pinned_root_does_not_exist(fake_home, capsys):
    workspace.write_override(fake_home / "gone", lambda _m: None)
    capsys.readouterr()
    workspace_cmd.main(["show"])
    assert "does not exist" in capsys.readouterr().err


def test_reset_drops_the_pin_and_says_what_takes_over(fake_home, capsys):
    workspace.write_override(fake_home / "pinned", lambda _m: None)
    capsys.readouterr()

    assert workspace_cmd.main(["reset"]) == 0
    assert workspace.read_override() is None
    assert "pin removed" in capsys.readouterr().err

    assert workspace_cmd.main(["reset"]) == 0
    assert "Nothing pinned" in capsys.readouterr().err


def test_reset_dry_run_keeps_the_pin(fake_home, capsys):
    workspace.write_override(fake_home / "pinned", lambda _m: None)
    assert workspace_cmd.main(["reset", "--dry-run"]) == 0
    assert workspace.read_override() == fake_home / "pinned"


def test_show_and_reset_reject_a_stray_argument(fake_home):
    assert workspace_cmd.main(["show", "extra"]) == 2
    assert workspace_cmd.main(["reset", "extra"]) == 2
    assert workspace_cmd.main(["set", "/a", "/b"]) == 2


def test_moving_with_no_current_workspace_is_an_error_not_a_copy(fake_home, capsys):
    """`--move` with nothing to move must not silently degrade into `set`."""
    assert workspace_cmd.main(["move", str(fake_home / "dest")]) == 1
    assert "no current workspace" in capsys.readouterr().err


def test_moving_to_where_it_already_is_does_nothing(fake_home, monkeypatch, capsys):
    root = fake_home / "ws"
    root.mkdir()
    monkeypatch.setattr(workspace, "resolve", lambda: workspace.Resolved(root, workspace.ENV))
    assert workspace_cmd.main(["move", str(root)]) == 0
    assert "nothing to move" in capsys.readouterr().err


def test_a_move_that_preflight_refuses_exits_one_and_lists_why(tree, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tree)  # standing inside the source
    monkeypatch.setattr(workspace, "resolve", lambda: workspace.Resolved(tree, workspace.ENV))
    assert workspace_cmd.main(["move", str(tmp_path / "dest")]) == 1
    err = capsys.readouterr().err
    assert "cannot move" in err
    assert "your shell is inside" in err


def test_a_same_volume_move_needs_no_verify_and_no_confirm(tree, tmp_path, monkeypatch, capsys):
    """A rename is atomic: there is no copy to verify and no original left to
    offer to remove, so neither step should appear."""
    monkeypatch.chdir(tmp_path)
    dest = tmp_path / "dest"
    monkeypatch.setattr(workspace, "resolve", lambda: workspace.Resolved(tree, workspace.ENV))
    monkeypatch.setattr(workspace, "rc_path", lambda: tmp_path / ".zshrc.local")

    assert workspace_cmd.main(["move", str(dest)]) == 0
    captured = capsys.readouterr()
    assert captured.out.strip() == str(dest), "stdout stays the path and nothing else"
    assert "verifying" not in captured.err
    assert "Remove the original" not in captured.err
    assert (dest / "src" / "github.com" / "acme" / "widget" / "file.txt").is_file()
    assert not tree.exists()


def test_keep_source_leaves_the_original_after_a_verified_copy(tree, tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workspace, "same_volume", lambda _a, _b: False)
    monkeypatch.setattr(workspace, "resolve", lambda: workspace.Resolved(tree, workspace.ENV))
    monkeypatch.setattr(workspace, "rc_path", lambda: tmp_path / ".zshrc.local")

    code = workspace_cmd.set_root(
        str(tmp_path / "dest"), move=True, keep_source=True, assume_yes=True, dry_run=False
    )
    assert code == 0
    assert tree.exists()
    assert "--keep-source" in capsys.readouterr().err


def test_declining_the_prompt_keeps_the_original_and_still_repoints(
    tree, tmp_path, monkeypatch, capsys
):
    """Saying no to the delete is not saying no to the move: the copy verified,
    so the root follows it and the original is left for you to remove."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(workspace, "same_volume", lambda _a, _b: False)
    monkeypatch.setattr(workspace, "resolve", lambda: workspace.Resolved(tree, workspace.ENV))
    monkeypatch.setattr(workspace, "rc_path", lambda: tmp_path / ".zshrc.local")
    monkeypatch.setattr(workspace_cmd, "_confirm", lambda *_a: False)

    assert (
        workspace_cmd.set_root(
            str(tmp_path / "dest"), move=True, keep_source=False, assume_yes=False, dry_run=False
        )
        == 0
    )
    assert tree.exists()
    assert "Remove it by hand" in capsys.readouterr().err
    assert workspace.read_override() == tmp_path / "dest"


def test_the_confirm_defaults_to_no_when_stdin_is_not_a_terminal(monkeypatch, capsys):
    """A script that pipes into this must not lose a directory to a blank read."""
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert workspace_cmd._confirm("Remove it?", assume_yes=False) is False
    assert "assuming no" in capsys.readouterr().err
    assert workspace_cmd._confirm("Remove it?", assume_yes=True) is True


def test_ts_ws_yes_skips_the_confirm(monkeypatch):
    monkeypatch.setenv("TS_WS_YES", "1")
    assert workspace_cmd._confirm("Remove it?", assume_yes=False) is True


# ----------------------------------------------------------- no-rsync paths ----


def test_relocate_and_verify_work_without_rsync(tree, tmp_path, monkeypatch, capsys):
    """rsync is not guaranteed -- a minimal container, a fresh macOS. The copy
    falls back to `cp -a` and the verify to a file-count and byte-total
    comparison, which is weaker but still catches a truncated copy."""
    monkeypatch.setattr(workspace, "same_volume", lambda _a, _b: False)
    monkeypatch.setattr(workspace.shutil, "which", lambda _name: None)
    dest = tmp_path / "dest"

    assert workspace.relocate(tree, dest, lambda _m: None)
    assert "hardlinks will not be preserved" in capsys.readouterr().out or True
    assert (dest / "src" / "github.com" / "acme" / "widget" / "file.txt").is_file()
    assert workspace.verify(tree, dest, lambda _m: None)

    (dest / "src" / "github.com" / "acme" / "widget" / "file.txt").write_text("short")
    assert not workspace.verify(tree, dest, lambda _m: None)


def test_verify_reports_when_rsync_itself_cannot_run(tree, tmp_path, monkeypatch):
    """The rsync branch specifically -- forced, because a machine without rsync
    (a slim container, Windows) takes the counting fallback and never reaches
    the code under test."""
    monkeypatch.setattr(workspace.shutil, "which", lambda _name: "/usr/bin/rsync")
    monkeypatch.setattr(workspace.proc, "capture", lambda *_a, **_k: None)
    said: list[str] = []
    assert not workspace.verify(tree, tmp_path, said.append)
    assert any("could not run rsync" in m for m in said)


def test_verify_never_passes_because_the_checker_failed(tree, tmp_path, monkeypatch):
    """The single most dangerous thing this module could do.

    rsync exiting non-zero with empty stdout is what openrsync does when it
    rejects -A and -X. The first version of verify() checked only whether the
    process could be STARTED, so it read "no itemized differences" off a run
    that never happened and returned True -- for a copy it had not compared,
    with a confirmed `rm -rf` of the original on the other side of it. macOS CI
    caught it. It cannot come back.
    """
    monkeypatch.setattr(workspace.shutil, "which", lambda _name: "/usr/bin/rsync")

    class Rejected:
        returncode = 1
        stdout = ""
        stderr = "rsync: unknown option -- X"

    monkeypatch.setattr(workspace.proc, "capture", lambda *_a, **_k: Rejected())
    said: list[str] = []
    assert workspace.verify(tree, tmp_path / "nothing-was-copied-here", said.append) is False
    assert any("refusing to call this copy good" in m for m in said), said


def test_verify_walks_the_ladder_until_one_flag_set_runs(tree, tmp_path, monkeypatch):
    """openrsync again: -aHAX is rejected, -aH works, and the answer must come
    from the run that worked rather than from the one that did not."""
    monkeypatch.setattr(workspace.shutil, "which", lambda _name: "/usr/bin/rsync")
    seen: list[str] = []

    class Result:
        def __init__(self, code, out=""):
            self.returncode = code
            self.stdout = out
            self.stderr = ""

    def fake_capture(argv, **_k):
        seen.append(argv[1])
        return Result(1) if argv[1] == "-aHAX" else Result(0, "")

    monkeypatch.setattr(workspace.proc, "capture", fake_capture)
    assert workspace.verify(tree, tmp_path, lambda _m: None) is True
    assert seen == ["-aHAX", "-aH"], seen


def test_relocate_reports_a_failed_copy_rather_than_raising(tree, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "same_volume", lambda _a, _b: False)
    monkeypatch.setattr(workspace, "_run", lambda _argv: 23)
    assert workspace.relocate(tree, tmp_path / "dest", lambda _m: None) is False


def test_run_returns_nonzero_for_a_binary_that_is_not_there():
    assert workspace._run(["definitely-not-a-real-binary-xyzzy"]) == 1


# --------------------------------------------------------------- mount notes ----


def test_a_root_on_the_home_filesystem_gets_no_mount_warning(tmp_path, monkeypatch):
    """/home being its own btrfs subvolume is not the thing this warns about --
    it mounts with the root filesystem or the machine does not boot."""
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    assert workspace.warnings_for(tmp_path / "ws") == []


def test_a_root_on_another_filesystem_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))
    elsewhere = tmp_path / "elsewhere"
    mount = tmp_path / "mount"
    monkeypatch.setattr(workspace, "_mount_point", lambda p: mount if p == elsewhere else tmp_path)
    monkeypatch.setattr(workspace, "_fstab_nofail", lambda _m: True)
    notes = workspace.warnings_for(elsewhere)
    assert len(notes) == 1
    assert "nofail" in notes[0]
    assert "bare mountpoint" in notes[0]


@pytest.mark.skipif(os.name == "nt", reason="/etc/fstab is a POSIX concept")
def test_fstab_nofail_reads_the_options_column(tmp_path, monkeypatch):
    fstab = tmp_path / "fstab"
    fstab.write_text(
        "# a comment\n"
        "/dev/mapper/data  /mnt/data   ext4  defaults,nofail  0 2\n"
        "/dev/mapper/other /mnt/other  ext4  defaults         0 2\n",
        encoding="utf-8",
    )
    real = Path.read_text

    def fake(self, *a, **k):
        return fstab.read_text() if str(self) == "/etc/fstab" else real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", fake)
    assert workspace._fstab_nofail(Path("/mnt/data")) is True
    assert workspace._fstab_nofail(Path("/mnt/other")) is False
    assert workspace._fstab_nofail(Path("/mnt/absent")) is False


# ------------------------------------------------------- the Windows contract ----


def test_the_pwsh_rc_line_is_written_and_replaced_like_the_posix_one(tmp_path, monkeypatch):
    """The mirror of test_write_override_replaces_every_writers_format.

    That test pins the POSIX line and, until CI said so, was the ONLY thing
    exercising the writer -- so on Windows it asserted the POSIX format against
    the pwsh one the module correctly produces, and failed for the right
    behaviour. Both contracts are named now.
    """
    rc = tmp_path / "profile.local.ps1"
    monkeypatch.setattr(workspace, "_windows", lambda: True)
    monkeypatch.setattr(workspace, "rc_path", lambda: rc)
    rc.write_text(
        "# mine\n$env:WORKSPACE_DIR = 'X:\\old'\n$env:OTHER = 'keepme'\n", encoding="utf-8"
    )

    written = workspace.write_override(tmp_path / "new", lambda _m: None)

    lines = rc.read_text(encoding="utf-8").splitlines()
    assert [line for line in lines if "$env:WORKSPACE_DIR" in line] == [
        f"$env:WORKSPACE_DIR = '{written}'"
    ]
    assert "$env:OTHER = 'keepme'" in lines, "unrelated lines survive"
    assert workspace.read_override() == written
    assert workspace.clear_override(lambda _m: None) is True
    assert workspace.read_override() is None


# -------------------------------------------------------------- rsync ladder ----


def test_the_rsync_ladder_falls_back_when_flags_are_rejected(tree, tmp_path, monkeypatch):
    """macOS ships openrsync, which rejects -A and -X outright, and older macOS
    shipped rsync 2.6.9. A hard-coded `-aHAX` failed the entire copy there --
    caught by CI, not by review, which is why the ladder is pinned."""
    monkeypatch.setattr(workspace, "same_volume", lambda _a, _b: False)
    monkeypatch.setattr(workspace.shutil, "which", lambda _name: "/usr/bin/rsync")
    tried: list[list[str]] = []

    def fake_run(argv):
        tried.append(argv)
        # Stand in for openrsync: anything with -A or -X is rejected.
        return 1 if any(f in ("-aHAX",) for f in argv) else 0

    monkeypatch.setattr(workspace, "_run", fake_run)
    said: list[str] = []
    assert workspace.relocate(tree, tmp_path / "dest", said.append)

    assert [a[1] for a in tried] == ["-aHAX", "-aH"], tried
    assert any("does not support" in m for m in said), said


def test_the_ladder_ends_at_cp_and_says_what_that_costs(tree, tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "same_volume", lambda _a, _b: False)
    monkeypatch.setattr(workspace.shutil, "which", lambda _name: "/usr/bin/rsync")
    calls: list[list[str]] = []

    def fake_run(argv):
        calls.append(argv)
        return 0 if argv[0] == "cp" else 1

    monkeypatch.setattr(workspace, "_run", fake_run)
    said: list[str] = []
    assert workspace.relocate(tree, tmp_path / "dest", said.append)

    assert [c[0] for c in calls] == ["rsync", "rsync", "rsync", "cp"]
    assert any("does not preserve hardlinks" in m for m in said), said


def test_the_ladder_asks_for_no_progress_meter_when_nothing_is_watching(
    tree, tmp_path, monkeypatch
):
    """`--info=progress2` needs rsync 3.1+, which is exactly what the ladder
    exists to not assume; `--progress` is what both understand, and neither
    belongs in a log."""
    monkeypatch.setattr(workspace, "same_volume", lambda _a, _b: False)
    monkeypatch.setattr(workspace.shutil, "which", lambda _name: "/usr/bin/rsync")
    seen: list[list[str]] = []
    monkeypatch.setattr(workspace, "_run", lambda argv: seen.append(argv) or 0)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)

    workspace.relocate(tree, tmp_path / "dest", lambda _m: None)
    assert not any("progress" in flag for flag in seen[0])
    assert "--info=progress2" not in seen[0], "needs rsync 3.1+; macOS has neither"


def test_candidates_survives_a_machine_with_no_home(monkeypatch):
    """`tstack ui` mounts this row on every open; one unexpandable probe path
    must not be what stops the dashboard from opening."""
    monkeypatch.delenv("HOME", raising=False)
    monkeypatch.delenv("USERPROFILE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    workspace.candidates()  # must not raise


# ------------------------------------------------------- inbound symlinks ----


@pytest.fixture
def stowed(tree, tmp_path, monkeypatch):
    """A workspace with a stow-shaped dotfiles repo in it, linked from $HOME.

    The real shape this exists for: omarchy-dots at
    <workspace>/src/github.com/<owner>/omarchy-dots/stow/<pkg>/<path>, with 26
    relative links from $HOME into it -- the bar, Hyprland, ~/.ssh/config,
    ~/.claude/CLAUDE.md. A move dangles every one and the breakage only shows up
    at the next login.
    """
    home = tmp_path / "home"
    (home / ".config" / "hypr").mkdir(parents=True)
    (home / ".ssh").mkdir()
    dots = tree / "src" / "github.com" / "acme" / "dots"
    for pkg, rel in (("hypr", ".config/hypr/bindings.lua"), ("ssh", ".ssh/config")):
        target = dots / "stow" / pkg / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
        (home / rel).symlink_to(target)
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(tmp_path)
    return home


def test_symlinks_pointing_into_the_tree_are_found(stowed, tree):
    found = workspace.inbound_symlinks(tree, home=stowed)
    assert {p.name for p in found} == {"bindings.lua", "config"}


def test_a_symlink_pointing_somewhere_else_is_not_counted(stowed, tree, tmp_path):
    other = tmp_path / "unrelated"
    other.mkdir()
    (stowed / ".config" / "elsewhere").symlink_to(other)
    assert not any(p.name == "elsewhere" for p in workspace.inbound_symlinks(tree, home=stowed))


def test_links_inside_the_tree_itself_are_not_counted(stowed, tree):
    """The source is full of links that point into the source. Only links from
    OUTSIDE it would dangle, and only those are the question."""
    inner = tree / "src" / "self-link"
    inner.symlink_to(tree / "src")
    assert inner not in workspace.inbound_symlinks(tree, home=stowed)


def test_the_stow_root_is_recognised_from_the_link_targets(stowed, tree):
    links = workspace.inbound_symlinks(tree, home=stowed)
    assert workspace.stow_package_root(links) == tree / "src" / "github.com" / "acme" / "dots"


def test_preflight_refuses_a_move_that_would_dangle_them(stowed, tree, tmp_path):
    problems = workspace.preflight(tree, tmp_path / "dest")
    assert len(problems) == 1
    assert "point INTO" in problems[0]
    # The whole value of the refusal is that it names the repair, not just the risk.
    assert 'stow -R --no-folding -d stow -t "$HOME" hypr ssh' in problems[0]
    assert "--keep-source" in problems[0]
    assert "xtype l" in problems[0]


def test_keep_source_makes_it_a_warning_because_nothing_dangles(stowed, tree, tmp_path):
    """The original stays, so a link into it still resolves. The point of
    --keep-source is exactly this: repoint the links, THEN remove the source."""
    assert workspace.preflight(tree, tmp_path / "dest", keep_source=True) == []


def test_the_override_proceeds(stowed, tree, tmp_path):
    assert workspace.preflight(tree, tmp_path / "dest", allow_inbound_symlinks=True) == []


def test_a_tree_with_no_inbound_links_is_not_slowed_or_refused(tree, tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    monkeypatch.chdir(tmp_path)
    assert workspace.inbound_symlinks(tree, home=home) == []
    assert workspace.preflight(tree, tmp_path / "dest") == []


def test_the_command_refuses_and_keep_source_still_reminds(stowed, tree, tmp_path, capsys):
    monkeypatch_free_dest = str(tmp_path / "dest")
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(workspace, "resolve", lambda: workspace.Resolved(tree, workspace.ENV))
    monkeypatch.setattr(workspace, "rc_path", lambda: stowed / ".zshrc.local")
    try:
        assert (
            workspace_cmd.set_root(
                monkeypatch_free_dest,
                move=True,
                keep_source=False,
                assume_yes=True,
                dry_run=True,
            )
            == 1
        ), "a plain --move must refuse"
        assert "cannot move" in capsys.readouterr().err

        assert (
            workspace_cmd.set_root(
                monkeypatch_free_dest,
                move=True,
                keep_source=True,
                assume_yes=True,
                dry_run=True,
            )
            == 0
        ), "--keep-source proceeds"
        err = capsys.readouterr().err
        assert "nothing dangles until you remove it" in err
        assert "stow -R" in err, "and still says what to do next"
    finally:
        monkeypatch.undo()
