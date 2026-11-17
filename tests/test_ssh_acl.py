"""tstack/ssh_acl.py: the ~/.ssh files Windows OpenSSH refuses because someone else
can open them, and the icacls runs that fix it.

The fixtures are real `icacls` output, captured on 11/16/2026 from a machine
where Codex's sandbox had added a profile-wide `CodexSandboxUsers` ACE. ssh
skipped every key with "bad permissions" and the server said
`Permission denied (publickey)`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_doctor import as_platform, statuses
from tstack import checks, ssh_acl
from tstack import platform as plat
from tstack.checks import Report
from tstack.commands import doctor

KEY = "C:/Users/you/.ssh/id_ed25519_msampson_work"

CODEX = f"""{KEY} HOST\\CodexSandboxUsers:(I)(RX)
                                             NT AUTHORITY\\SYSTEM:(I)(F)
                                             BUILTIN\\Administrators:(I)(F)
                                             HOST\\you:(I)(F)

Successfully processed 1 files; Failed processing 0 files
"""

CLEAN = f"""{KEY} NT AUTHORITY\\SYSTEM:(I)(F)
                                             BUILTIN\\Administrators:(I)(F)
                                             HOST\\you:(I)(F)

Successfully processed 1 files; Failed processing 0 files
"""


def test_the_codex_sandbox_group_is_the_one_principal_reported():
    assert ssh_acl.foreign_principals(CODEX, KEY, "you") == ["HOST\\CodexSandboxUsers"]


def test_owner_system_and_administrators_are_allowed():
    assert ssh_acl.foreign_principals(CLEAN, KEY, "you") == []


def test_a_different_user_is_foreign_even_with_the_same_domain():
    """Matching the owner on a substring would let `HOST\\other` through."""
    other = CLEAN.replace("HOST\\you:", "HOST\\other:")
    assert ssh_acl.foreign_principals(other, KEY, "you") == ["HOST\\other"]


def test_deny_and_inherit_only_aces_do_not_count():
    """A DENY grants nothing, and an (IO) ACE does not apply to the file itself."""
    listing = CLEAN + "Everyone:(DENY)(R)\nGuests:(OI)(CI)(IO)(RX)\n"
    assert ssh_acl.foreign_principals(listing, KEY, "you") == []


def test_a_bare_sid_principal_is_reported():
    """An unresolved SID (a deleted account, an AppContainer) still counts."""
    listing = CLEAN + "S-1-15-3-65536-1:(S,X)\n"
    assert ssh_acl.foreign_principals(listing, KEY, "you") == ["S-1-15-3-65536-1"]


def test_localised_well_known_names_are_accepted_when_passed():
    listing = f"{KEY} NT-AUTORITÄT\\SYSTEM:(I)(F)\nVORDEFINIERT\\Administratoren:(I)(F)\n"
    allowed = {"nt-autorität\\system", "vordefiniert\\administratoren"}
    assert ssh_acl.foreign_principals(listing, KEY, "you", allowed) == []


def test_candidates_are_private_keys_config_and_authorized_keys(tmp_path):
    for name in ("id_ed25519", "id_ed25519.pub", "work", "work.pub", "config",
                 "authorized_keys", "known_hosts", "notes.txt"):  # fmt: skip
        (tmp_path / name).write_text("", encoding="utf-8")
    got = {p.name for p in ssh_acl.candidate_files(tmp_path)}
    assert got == {"id_ed25519", "work", "config", "authorized_keys"}


def test_a_missing_ssh_dir_has_no_candidates(tmp_path):
    assert ssh_acl.candidate_files(tmp_path / "nope") == []


def test_exposed_lists_each_file_with_its_principals(tmp_path):
    (tmp_path / "id_a").write_text("", encoding="utf-8")
    (tmp_path / "id_b").write_text("", encoding="utf-8")

    def run(argv):
        path = argv[0]
        return (CODEX if path.endswith("id_a") else CLEAN).replace(KEY, path)

    found = ssh_acl.exposed(tmp_path, run=run, user="you")
    assert [(p.name, who) for p, who in found] == [("id_a", ["HOST\\CodexSandboxUsers"])]
    assert "CodexSandboxUsers" in ssh_acl.summary(found)


def test_an_icacls_that_cannot_run_reports_nothing(tmp_path):
    """No answer is not an exposure: a false alarm would ask to rewrite a DACL."""
    (tmp_path / "id_a").write_text("", encoding="utf-8")
    assert ssh_acl.exposed(tmp_path, run=lambda argv: None, user="you") == []


def test_the_fix_breaks_inheritance_on_ssh_only_and_resets_its_children(tmp_path):
    first, second = ssh_acl.fix_argv(tmp_path, "you")
    assert first[0] == str(tmp_path), "the profile root's ACE is Codex's; leave it alone"
    assert "/inheritance:r" in first and "/grant:r" in first
    assert "you:(OI)(CI)F" in first
    # SIDs, not names, so a non-English Windows gets the same fix.
    assert "*S-1-5-18:(OI)(CI)F" in first and "*S-1-5-32-544:(OI)(CI)F" in first
    assert second[0] == str(tmp_path / "*") and "/reset" in second


def test_fix_reports_a_failed_icacls(tmp_path):
    calls: list[list[str]] = []
    assert ssh_acl.fix(tmp_path, run=lambda a: calls.append(a) or "", user="you")
    assert len(calls) == 2
    assert not ssh_acl.fix(tmp_path, run=lambda a: None, user="you")


# ------------------------------------------------------------------ doctor


def test_the_doctor_check_is_windows_only(monkeypatch):
    called = []
    monkeypatch.setattr(ssh_acl, "exposed", lambda d: called.append(d) or [])
    for kind in (plat.WSL, plat.LINUX, plat.MACOS):
        as_platform(monkeypatch, kind)
        report = Report()
        doctor.check_ssh_key_acl(report)
        assert report.results == []
    assert called == []


def test_the_doctor_check_fails_with_the_repair_hint(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.WINDOWS)
    monkeypatch.setattr(
        ssh_acl, "exposed", lambda d: [(tmp_path / "id_a", ["HOST\\CodexSandboxUsers"])]
    )
    report = Report()
    doctor.check_ssh_key_acl(report)
    assert statuses(report)["ssh-key-acl"] == checks.FAIL
    assert "tstack doctor --repair" in report.results[0].hint


def test_the_doctor_check_passes_when_private(monkeypatch):
    as_platform(monkeypatch, plat.WINDOWS)
    monkeypatch.setattr(ssh_acl, "exposed", lambda d: [])
    report = Report()
    doctor.check_ssh_key_acl(report)
    assert statuses(report)["ssh-key-acl"] == checks.OK


def test_repair_without_consent_prints_the_commands_and_changes_nothing(
    monkeypatch, tmp_path, capsys
):
    as_platform(monkeypatch, plat.WINDOWS)
    monkeypatch.setattr(ssh_acl, "exposed", lambda d: [(tmp_path / "id_a", ["X\\Y"])])
    fixed = []
    monkeypatch.setattr(ssh_acl, "fix", lambda d: fixed.append(d) or True)
    monkeypatch.setattr(doctor.confirm, "confirm", lambda *a, **k: False)
    assert doctor.repair_ssh_key_acl() == 0
    assert fixed == []
    assert "/inheritance:r" in capsys.readouterr().out


def test_repair_rechecks_and_fails_if_still_exposed(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.WINDOWS)
    monkeypatch.setattr(ssh_acl, "exposed", lambda d: [(tmp_path / "id_a", ["X\\Y"])])
    monkeypatch.setattr(ssh_acl, "fix", lambda d: True)
    monkeypatch.setattr(doctor.confirm, "confirm", lambda *a, **k: True)
    assert doctor.repair_ssh_key_acl() == 1


def test_repair_succeeds_when_the_recheck_is_clean(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.WINDOWS)
    answers = iter([[(tmp_path / "id_a", ["X\\Y"])], []])
    monkeypatch.setattr(ssh_acl, "exposed", lambda d: next(answers))
    monkeypatch.setattr(ssh_acl, "fix", lambda d: True)
    monkeypatch.setattr(doctor.confirm, "confirm", lambda *a, **k: True)
    assert doctor.repair_ssh_key_acl() == 0
