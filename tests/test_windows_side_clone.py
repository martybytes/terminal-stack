"""On a combined machine the Windows install's clone is not WSL's to move or remove.

install-wsl.sh listed /mnt/c/Users/<u>/AppData/Local/terminal-stack/stack as a
LEGACY clone with "Move" as the default answer -- and on a machine installed in
the documented order (install.ps1 first) that path is the Windows install's live
clone. Enter would have moved it onto ext4 and orphaned the Windows side.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.shell_support import BASH  # noqa: E402
from tstack import paths  # noqa: E402
from tstack import platform as plat  # noqa: E402
from tstack.commands import doctor  # noqa: E402

WIN = Path("/mnt/c/Users/Someone/AppData/Local/terminal-stack/stack")


@pytest.fixture
def wsl(monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)


def test_the_windows_canonical_clone_is_recognised_on_wsl(wsl):
    assert paths.is_windows_side_clone(WIN)
    assert paths.is_windows_side_clone("/mnt/c/users/x/appdata/local/terminal-stack/stack/")
    assert not paths.is_windows_side_clone("/mnt/c/Users/Someone/terminal-stack")
    assert not paths.is_windows_side_clone(Path.home() / ".local/share/terminal-stack")


def test_nowhere_else_is_it_special(monkeypatch):
    for kind in (plat.LINUX, plat.MACOS, plat.WINDOWS):
        monkeypatch.setattr(plat, "kind", lambda k=kind: k)
        assert not paths.is_windows_side_clone(WIN)


def test_doctor_does_not_offer_to_move_it(wsl, monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "canonical_clone_dir", lambda: tmp_path / "canon")
    monkeypatch.setattr(paths, "is_dev_clone", lambda p: False)
    report = doctor.Report()
    doctor.check_clone_location(report, WIN)
    (r,) = report.results
    assert "shares the Windows install's clone" in r.message
    assert "--repair" not in r.message and "move" not in r.message.lower()


def test_doctor_does_not_list_it_as_another_clone(wsl, monkeypatch, tmp_path):
    mine = tmp_path / "mine"
    monkeypatch.setattr(
        paths, "clones", lambda: [paths.Clone(mine, "o", ""), paths.Clone(WIN, "o", "")]
    )
    report = doctor.Report()
    doctor.check_other_clones(report, mine)
    assert not report.results


def test_repair_refuses_to_relocate_it(wsl, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(paths, "canonical_clone_dir", lambda: tmp_path / "canon")
    monkeypatch.setattr(paths, "is_dev_clone", lambda p: False)
    monkeypatch.setattr(doctor, "_run_attached", lambda argv: pytest.fail("must not run"))
    assert doctor.repair_clone_location(WIN) == 0
    assert "Not moving it" in capsys.readouterr().out


def test_the_installer_no_longer_scans_it_as_legacy():
    body = (ROOT / "install-wsl.sh").read_text(encoding="utf-8")
    start = body.index('LEGACY=""')
    scan = body[start : body.index("done", start)]
    code = "\n".join(l for l in scan.splitlines() if not l.strip().startswith("#"))
    assert "AppData/Local/terminal-stack/stack" not in code
    assert "Move failed and left $TARGET_DIR behind" in body


@pytest.mark.skipif(not BASH, reason="bash is unavailable")
def test_the_cleanup_menu_never_offers_it(tmp_path):
    """The bash twin of is_windows_side_clone, driving the real finder."""
    import subprocess

    fake = tmp_path / "mnt/c/Users/Someone/AppData/Local/terminal-stack/stack"
    fake.mkdir(parents=True)
    script = (
        f". {ROOT / 'bootstrap/_cleanup.sh'} >/dev/null 2>&1\n"
        "ts_cleanup_on_wsl() { return 0; }\n"
        f'_ts_realpath() {{ printf %s "${{1#{tmp_path}}}"; }}\n'
        f'ts_is_windows_side_clone "{fake}" && echo windows-side\n'
        'ts_is_windows_side_clone "/home/u/.local/share/terminal-stack" || echo mine\n'
    )
    got = subprocess.run(
        [BASH, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        start_new_session=True,
    )
    assert got.stdout.split() == ["windows-side", "mine"], got.stderr


def test_the_pwsh_installer_stops_on_quit_and_on_git_failure():
    ps = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert "if ($LASTEXITCODE -eq 3)" in ps
    assert ps.count("if ($LASTEXITCODE) { throw") >= 2
    boot = (ROOT / "bootstrap/windows-bootstrap.ps1").read_text(encoding="utf-8")
    assert "nothing was installed or changed.'; exit 3 }" in boot


def test_cleanup_never_deletes_what_it_could_not_back_up():
    sh = (ROOT / "bootstrap/_cleanup.sh").read_text(encoding="utf-8")
    assert 'echo "$WARN not removing $d: no backup"; continue' in sh
    ps = (ROOT / "bootstrap/_cleanup.ps1").read_text(encoding="utf-8")
    assert 'Write-Warning "not removing $($it.Path): no backup"; continue' in ps
    assert "[Console]::IsInputRedirected" in ps.split("function Invoke-TsCleanupMenu", 1)[1]


def test_doctor_repair_actually_runs_the_checklist(monkeypatch, tmp_path):
    ran: list[list[str]] = []
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    src = tmp_path / "clone"
    (src / "bootstrap").mkdir(parents=True)
    (src / "bootstrap/_cleanup.sh").write_text("", encoding="utf-8")
    monkeypatch.setattr(doctor, "repair_clone_branch", lambda s: 0)
    monkeypatch.setattr(doctor, "repair_headroom_token", lambda: 0)
    monkeypatch.setattr(doctor, "repair_clone_location", lambda s: 0)
    monkeypatch.setattr(doctor, "_run_attached", lambda argv: ran.append(argv) or 0)
    assert doctor.repair(src) == 0
    assert ran and "ts_cleanup_menu" in ran[0][-1]
    # A failing step is a failing repair, not "==> done".
    monkeypatch.setattr(doctor, "repair_headroom_token", lambda: 1)
    assert doctor.repair(src) == 1
