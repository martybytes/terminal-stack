"""The second workspace root, and the two ways it can be got wrong.

THE SHAPE THIS EXISTS FOR

The main workspace usually lives on a mounted data volume. A dotfiles repo
stowed into `$HOME` cannot: `nofail` in fstab makes a missing mount SILENT --
the mountpoint still exists, the tree under it is empty, and every link into it
dangles with nothing said until the next login. `doc common/workspace-nav`
already warned about that. So the repos that have to survive it live on the
machine's own disk, at `~/LocalWorkspace/src/github.com/<owner>/<repo>` -- the
same shape as the main tree, on a root `$WORKSPACE_DIR` does not cover.

Two failures follow from a second root, and each has a test below.

The navigation half: `wsj` and the owner jumps searched exactly one root, so a
repo in the local one was unreachable by every shortcut the stack ships. `wsj`
rows are the subtle part -- they are root-RELATIVE, and two roots make a
relative row ambiguous. Rows from other roots are absolute-with-`~` so the row's
first character says which root it came from and no selection has to be guessed.

The organiser half is the dangerous one, and runs the other way. `wso migrate`
derives a destination from a repo's `origin` and moves it into the main tree,
non-interactively, dozens at a time. Doing that to the local root would put a
stowed dotfiles repo back on the volume it was moved off -- re-creating the
exact silent breakage it exists to avoid, in one command nobody was thinking
hard about. So the scan drops that root, and drops it even when
`TS_WS_EXTRA_ROOTS` names it: that variable means "legacy root, empty this into
the tree", which is the opposite of what the local root is.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.shell_support import BASH, bash_path

ROOT = Path(__file__).resolve().parent.parent
ZSHRC = ROOT / "dot_zshrc"
PROFILE = ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1"
WS_SH = ROOT / "bootstrap/_workspace.sh"
WS_PS1 = ROOT / "bootstrap/_workspace.ps1"


def _zsh_nav_block() -> str:
    """dot_zshrc from the root resolver to the end of the jumps."""
    src = ZSHRC.read_text(encoding="utf-8")
    return src[src.index("_ts_workspace() {") : src.index("# wso — workspace organizer.")]


def _run_zsh(script: str, home: Path, env: dict[str, str] | None = None) -> str:
    full = {"HOME": str(home), "PATH": "/usr/bin:/bin", "TERM": "dumb"}
    full.update(env or {})
    result = subprocess.run(
        [shutil.which("zsh") or "zsh", "-f", "-c", _zsh_nav_block() + "\n" + script],
        env=full,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


@pytest.fixture
def two_roots(tmp_path):
    """A main root and a local root, one repo in each."""
    home = tmp_path / "home"
    main = tmp_path / "data" / "Workspace"
    local = home / "LocalWorkspace"
    (main / "src/github.com/o/main-repo/.git").mkdir(parents=True)
    (local / "src/github.com/o/dots/.git").mkdir(parents=True)
    return home, main, local


# ------------------------------------------------------------- navigation ----


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh is unavailable")
def test_both_roots_are_searched_main_first(two_roots):
    home, main, _ = two_roots
    out = _run_zsh("_ts_ws_roots", home, {"WORKSPACE_DIR": str(main)})
    assert out.split() == [str(main), str(home / "LocalWorkspace")]


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh is unavailable")
def test_a_machine_with_no_local_root_still_has_exactly_one(tmp_path):
    """The common case. Nothing here may assume a second root exists."""
    home = tmp_path / "home"
    (home / "Workspace").mkdir(parents=True)
    roots = _run_zsh("_ts_ws_roots", home).split()
    # The COUNT is the claim. Not the spelling: macOS and Windows are
    # case-insensitive, and `_ts_workspace` probes `~/workspace` before
    # `~/Workspace`, so what comes back is the probe's capitalisation and not
    # the directory's. Asserting the string passed on Linux and failed on macOS.
    assert len(roots) == 1
    assert roots[0].lower() == str(home / "Workspace").lower()


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh is unavailable")
def test_pointing_the_workspace_at_the_local_root_yields_one_root_not_two(two_roots):
    """Deduped, or wsj lists every repo twice."""
    home, _, local = two_roots
    out = _run_zsh("_ts_ws_roots", home, {"WORKSPACE_DIR": str(local)})
    assert out.split() == [str(local)]


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh is unavailable")
def test_an_owner_jump_falls_through_to_the_local_root(two_roots):
    """wsmb and friends. The owner exists under both here; main wins, and the
    fall-through is what finds an owner that lives only in the local root."""
    home, main, local = two_roots
    (main / "src/github.com/o").rename(main / "src/github.com/other")
    out = _run_zsh("_ts_ws_org_cd o probe && pwd", home, {"WORKSPACE_DIR": str(main)})
    assert out.strip() == str(local / "src/github.com/o")


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh is unavailable")
def test_wsj_rows_say_which_root_they_came_from(two_roots):
    """A relative row means the main root; a `~` row is absolute and means some
    other one. Without that, the same relative path under two roots is a guess."""
    home, main, _ = two_roots
    out = _run_zsh(
        "wsj main-repo >/dev/null; wsj dots >/dev/null; "
        # the rows themselves, built the way wsj builds them
        "local -a roots repos found; local root; local primary=1\n"
        'roots=(${(f)"$(_ts_ws_roots)"})\n'
        'for root in "${roots[@]}"; do\n'
        '  found=(${(f)"$(find "$root"/{src,public,archive,local} -maxdepth 5 -name .git -prune 2>/dev/null | sed \'s|/\\.git$||\' | sort)"})\n'
        '  if (( primary )); then repos+=("${found[@]#"$root"/}"); else repos+=("${found[@]/#"$HOME"/~}"); fi\n'
        "  primary=0\n"
        "done\n"
        'printf "%s\\n" "${repos[@]}"',
        home,
        {"WORKSPACE_DIR": str(main)},
    )
    rows = out.split()
    assert "src/github.com/o/main-repo" in rows
    assert "~/LocalWorkspace/src/github.com/o/dots" in rows


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh is unavailable")
def test_wsj_cds_into_the_local_root_when_a_tilde_row_is_picked(two_roots):
    """The end-to-end proof: pick the local-root repo, land in the local root."""
    home, main, local = two_roots
    # A stand-in for fzf: pick the single row matching --query=<term>.
    fake_fzf = home / "bin"
    fake_fzf.mkdir(parents=True)
    (fake_fzf / "fzf").write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do case "$a" in --query=*) q=${a#--query=} ;; esac; done\n'
        'grep -i -- "$q"\n',
        encoding="utf-8",
    )
    (fake_fzf / "fzf").chmod(0o755)
    out = _run_zsh(
        "wsj dots && pwd",
        home,
        {"WORKSPACE_DIR": str(main), "PATH": f"{fake_fzf}:/usr/bin:/bin"},
    )
    assert out.strip() == str(local / "src/github.com/o/dots")


@pytest.mark.skipif(not shutil.which("zsh"), reason="zsh is unavailable")
def test_wsloc_lands_in_the_local_root(two_roots):
    home, main, local = two_roots
    out = _run_zsh("wsloc && pwd", home, {"WORKSPACE_DIR": str(main)})
    assert out.strip() == str(local)


# -------------------------------------------------------------- organiser ----


needs_bash = pytest.mark.skipif(BASH is None, reason="needs bash")


def _run_scan(home: Path, env: dict[str, str]) -> list[str]:
    r"""ts_ws_scan_roots in a real bash, with paths that bash can open.

    `bash_path` rather than str(): on a Windows runner the only compatible bash
    is git-bash, which cannot open `C:\...` -- the same translation every other
    bash test here already does.
    """
    full = {"HOME": bash_path(home), "PATH": "/usr/bin:/bin"}
    full.update({k: bash_path(v) if k != "PATH" else v for k, v in env.items()})
    assert BASH is not None
    result = subprocess.run(
        [BASH, "-c", f'. "{bash_path(WS_SH)}"; ts_ws_scan_roots'],
        env=full,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.split()


@needs_bash
def test_wso_never_scans_the_local_root(two_roots):
    home, main, local = two_roots
    assert _run_scan(home, {"WORKSPACE_DIR": str(main)}) == [bash_path(main)]
    assert bash_path(local) not in _run_scan(home, {"WORKSPACE_DIR": str(main)})


@needs_bash
def test_extra_roots_cannot_re_add_the_local_root(two_roots):
    """TS_WS_EXTRA_ROOTS means "legacy root, empty this into the tree" -- the
    one thing the local root must never be, however it got named."""
    home, main, local = two_roots
    roots = _run_scan(home, {"WORKSPACE_DIR": str(main), "TS_WS_EXTRA_ROOTS": str(local)})
    assert roots == [bash_path(main)]


@needs_bash
def test_the_guard_does_not_fire_when_the_workspace_is_the_local_root(two_roots):
    """Otherwise wso is left with no roots at all and silently plans nothing."""
    home, _, local = two_roots
    assert _run_scan(home, {"WORKSPACE_DIR": str(local)}) == [bash_path(local)]


# ------------------------------------------------------------ both shells ----


def test_the_local_root_resolves_the_same_way_in_all_four_implementations():
    """zsh and pwsh navigate; the two wso libraries guard. A resolver that
    disagrees with its twin points one of them at a root the other cannot see."""
    for path, needle in (
        (ZSHRC, "LOCAL_WORKSPACE_DIR"),
        (PROFILE, "LOCAL_WORKSPACE_DIR"),
        (WS_SH, "LOCAL_WORKSPACE_DIR"),
        (WS_PS1, "LOCAL_WORKSPACE_DIR"),
    ):
        text = path.read_text(encoding="utf-8")
        assert needle in text, f"{path.name} does not honour ${needle}"
        assert "LocalWorkspace" in text, f"{path.name} has no ~/LocalWorkspace default"


def test_every_nav_jump_has_a_twin_in_the_other_shell():
    zsh = ZSHRC.read_text(encoding="utf-8")
    pwsh = PROFILE.read_text(encoding="utf-8")
    zsh_fns = set(re.findall(r"^(ws[a-z0-9]*)\(\)", zsh, re.M))
    pwsh_fns = set(re.findall(r"^function (ws[a-z0-9]*)\b", pwsh, re.M))
    assert "wsloc" in zsh_fns and "wsloc" in pwsh_fns
    # wsw/ws --set are argument-parsing wrappers, not jumps, and both exist.
    assert zsh_fns == pwsh_fns, (
        f"only in zsh: {zsh_fns - pwsh_fns}; only in pwsh: {pwsh_fns - zsh_fns}"
    )
