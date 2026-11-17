"""tstack ssh: key parsing, the managed sshd block, firewall scope, the .wslconfig
splice, the wizard questions and the elevated script's contract.

Nothing here touches the real sshd, firewall or WSL: those are exercised live
(docs/kb/windows/ssh-server.md). What can be pinned offline is every decision
the plan encodes."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import platform as plat  # noqa: E402
from tstack import ssh  # noqa: E402


def _blob(kind: str, body: bytes = b"\x01" * 32) -> str:
    def field(b: bytes) -> bytes:
        return len(b).to_bytes(4, "big") + b

    return base64.b64encode(field(kind.encode()) + field(body)).decode()


ED = f"ssh-ed25519 {_blob('ssh-ed25519')} me@laptop"
ED2 = "ssh-ed25519 " + _blob("ssh-ed25519", bytes([2]) * 32) + " other@box"


# ------------------------------------------------------------------ keys


def test_a_key_line_parses_with_its_comment():
    k = ssh.parse_key(ED)
    assert k is not None and k.kind == "ssh-ed25519" and k.comment == "me@laptop"
    assert k.line == ED


@pytest.mark.parametrize(
    "line",
    [
        "",
        "not a key",
        "ssh-ed25519 !!!notbase64",
        f"ssh-rsa {_blob('ssh-ed25519')}",  # type field disagrees with the blob
        "ssh-ed25519 " + _blob("ssh-ed25519")[:-12],  # truncated in a copy/paste
        f'from="10.0.0.1" {ED}',  # options are not added by the stack
    ],
)
def test_a_bad_key_line_is_refused(line):
    assert ssh.parse_key(line) is None


def test_the_fingerprint_is_openssh_s(tmp_path):
    k = ssh.parse_key(ED)
    assert k is not None and k.fingerprint.startswith("SHA256:") and "=" not in k.fingerprint
    keygen = shutil.which("ssh-keygen")
    if keygen:
        pub = tmp_path / "k.pub"
        pub.write_text(ED + "\n", encoding="utf-8")
        got = subprocess.run(
            [keygen, "-lf", str(pub)],
            capture_output=True, text=True, encoding="utf-8", timeout=30, check=False,
            start_new_session=True,
        )  # fmt: skip
        if got.returncode == 0:
            assert k.fingerprint in got.stdout


def test_merging_keeps_every_existing_line_and_adds_only_new_blobs():
    existing = f'# mine\nfrom="10.0.0.0/8",no-pty {ED}\n'
    text, added = ssh.merge_authorized(existing, ssh.parse_keys(ED + "\n" + ED2))
    assert text.startswith(existing)
    assert [k.comment for k in added] == ["other@box"]
    again, added2 = ssh.merge_authorized(text, ssh.parse_keys(ED2))
    assert again == text and added2 == []


def test_local_keys_reads_every_pub(tmp_path, monkeypatch):
    monkeypatch.setattr(ssh, "ssh_dir", lambda: tmp_path)
    (tmp_path / "a.pub").write_text(ED + "\n", encoding="utf-8")
    (tmp_path / "b.pub").write_text(ED2 + "\n", encoding="utf-8")
    (tmp_path / "junk.pub").write_text("nonsense\n", encoding="utf-8")
    assert [k.source for k in ssh.local_keys()] == ["a.pub", "b.pub"]


def test_a_github_username_is_checked_before_any_request():
    with pytest.raises(OSError, match="not a GitHub username"):
        ssh.github_keys("bad/user")


# ---------------------------------------------------------------- sshd block


def _s(**kw: str) -> dict[str, str]:
    return dict(ssh.DEFAULTS, sshServer="on", **kw)


def test_other_port_lines_are_disabled_because_port_is_additive():
    """sshd answered on 22 AND the old 2222: every Port line adds a listener."""
    out = ssh.splice_block("#Port 22\nPort 2222\nAddressFamily any\n", ssh.windows_block(_s(), "on"))
    assert "# terminal-stack disabled: Port 2222" in out and "#Port 22" in out
    assert [ln for ln in out.splitlines() if ln.startswith("Port ")] == ["Port 22"]
    assert ssh.splice_block(out, ssh.windows_block(_s(), "on")) == out


def test_the_script_disables_other_port_lines_too():
    script = (ROOT / "bootstrap" / "ssh-server.ps1").read_text(encoding="utf-8")
    assert "# terminal-stack disabled: " in script and "Port\\s+\\S" in script


def test_the_proof_checks_which_side_answered():
    assert ssh.verify_args("22", "me")[-1] == ssh.PROOF["windows"][0]
    assert ssh.verify_args("2222", "me", "wsl")[-1] == "uname -s"
    script = (ROOT / "bootstrap" / "ssh-server.ps1").read_text(encoding="utf-8")
    assert "$p.verify_expect" in script


def test_the_block_goes_first_and_replaces_itself():
    config = "#Port 22\n#PasswordAuthentication yes\n"
    once = ssh.splice_block(config, ssh.windows_block(_s(), "on"))
    assert once.startswith(ssh.BLOCK_START) and once.endswith(config)
    assert "Port 22\n" in once and "PasswordAuthentication yes" in once
    twice = ssh.splice_block(once, ssh.windows_block(_s(), "off"))
    assert twice.count(ssh.BLOCK_START) == 1 and "PasswordAuthentication no" in twice
    assert twice.endswith(config)


def test_the_admin_keys_file_is_followed_only_when_its_match_block_is_live():
    stock = "Match Group administrators\n       AuthorizedKeysFile __PROGRAMDATA__/ssh/administrators_authorized_keys\n"
    assert ssh.admin_keys_file_active(stock)
    assert not ssh.admin_keys_file_active("".join("#" + ln + "\n" for ln in stock.splitlines()))


@pytest.mark.parametrize(
    "scope,expected",
    [
        ("private", [("Private,Domain", "Any")]),
        ("tailnet", [("Any", ",".join(ssh.TAILNET))]),
        ("lan-tailnet", [("Private,Domain", "Any"), ("Any", ",".join(ssh.TAILNET))]),
        ("any", [("Any", "Any")]),
    ],
)
def test_firewall_rules_follow_the_scope(scope, expected):
    rules = ssh.firewall_rules(_s(sshScope=scope, sshTargets="windows"))
    assert [(r["Profile"], r["Remote"]) for r in rules] == expected
    assert {r["Port"] for r in rules} == {"22"}


def test_wsl_rules_are_hyper_v_rules_on_the_wsl_port():
    rules = ssh.firewall_rules(_s(sshTargets="both", sshWslPort="2300"))
    assert {(r["Side"], r["Layer"], r["Port"]) for r in rules} == {
        ("Windows", "host", "22"),
        ("WSL", "hyperv", "2300"),
    }


def test_ports_must_be_numbers_and_differ():
    assert ssh.port_problem(_s()) is None
    assert "differ" in (ssh.port_problem(_s(sshWslPort="22")) or "")
    assert "port number" in (ssh.port_problem(_s(sshWindowsPort="70000")) or "")
    assert ssh.port_problem(_s(sshTargets="windows", sshWslPort="22")) is None


def test_passwords_go_off_in_two_phases_unless_forced(monkeypatch, tmp_path):
    monkeypatch.setattr(ssh, "sshd_config_path", lambda: tmp_path / "none")
    staged = ssh.plan_windows(_s(), [])
    assert "PasswordAuthentication yes" in staged.sshd_block
    assert "PasswordAuthentication no" in staged.sshd_block_final
    assert staged.password_off_after_verify and not staged.password_off_without_verify
    forced = ssh.plan_windows(_s(), [], force_password_off=True)
    assert "PasswordAuthentication no" in forced.sshd_block
    assert forced.password_off_without_verify and not forced.password_off_after_verify
    kept = ssh.plan_windows(_s(sshPasswordAuth="on"), [])
    assert "PasswordAuthentication yes" in kept.sshd_block_final


def test_the_proof_ignores_the_users_ssh_config():
    """`IdentitiesOnly yes` under `Host *` hid every agent key from the proof."""
    args = ssh.verify_args("22", "me")
    assert args[:2] == ["-F", "none"] and "BatchMode=yes" in args


# ------------------------------------------------------------- .wslconfig


def test_the_wslconfig_splice_keeps_every_other_line():
    text = "[wsl2]\nmemory=32GB\n\n[experimental]\nsparseVhd=true\n"
    out = ssh.splice_ini(text, "wsl2", "networkingMode", "mirrored")
    assert out == "[wsl2]\nmemory=32GB\nnetworkingMode=mirrored\n\n[experimental]\nsparseVhd=true\n"
    assert ssh.splice_ini(out, "wsl2", "networkingMode", "mirrored") == out
    swapped = ssh.splice_ini("[wsl2]\nnetworkingMode=nat\n", "wsl2", "networkingMode", "mirrored")
    assert swapped == "[wsl2]\nnetworkingMode=mirrored\n"
    assert ssh.splice_ini("", "wsl2", "networkingMode", "mirrored") == "[wsl2]\nnetworkingMode=mirrored\n"


def test_the_wsl_dropin_carries_the_port_and_password_choice():
    text = ssh.wsl_dropin(_s(sshWslPort="2300"), "off")
    assert "Port 2300" in text and "PasswordAuthentication no" in text


# ------------------------------------------------------------------ wizard


def test_the_wizard_skips_ssh_off_windows(monkeypatch):
    from tstack.wizard import flow

    monkeypatch.delenv("TS_SSH_SERVER", raising=False)
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    monkeypatch.setattr(flow, "ssh_saved", lambda: dict(ssh.DEFAULTS))
    assert flow.ssh_questions(None, [], bare=False) == ssh.DEFAULTS  # type: ignore[arg-type]


def test_the_wizard_ssh_answers_come_from_the_environment(monkeypatch):
    from tstack.wizard import flow

    monkeypatch.setattr(flow, "ssh_saved", lambda: dict(ssh.DEFAULTS))
    monkeypatch.setenv("TS_SSH_SERVER", "on")
    monkeypatch.setenv("TS_SSH_WSL_PORT", "2300")
    monkeypatch.setenv("TS_SSH_SCOPE", "tailnet")
    got = flow.ssh_questions(None, [], bare=False)  # type: ignore[arg-type]
    assert got["sshServer"] == "on" and got["sshWslPort"] == "2300" and got["sshScope"] == "tailnet"


def test_every_ssh_setting_is_a_schema_setting_with_the_same_default():
    from tstack import schema

    by_key = {s.key: s for s in schema.SETTINGS}
    for key, default in ssh.DEFAULTS.items():
        assert by_key[key].default == default, key
    assert by_key["sshWslPort"].validate("70000")
    assert by_key["sshWslPort"].validate("2222") is None


def test_the_answers_emit_every_ssh_field():
    from tstack.wizard import emit, flow

    names = {f for _, f in emit.JSON_NAMES}
    assert set(flow.SSH_FIELDS.values()) <= names
    assert set(flow.SSH_FIELDS.values()) <= {f for _, f in emit.SHELL_NAMES}


# --------------------------------------------------------- elevated script


SCRIPT = (ROOT / "bootstrap" / "ssh-server.ps1").read_text(encoding="utf-8")


def test_the_elevated_script_takes_a_plan_and_nothing_else():
    """The one script the stack runs as admin executes data, not code."""
    head = SCRIPT.split("param(", 1)[1].split("\n)", 1)[0]
    assert "$Plan" in head and "$Result" in head
    assert head.count("$") == 2
    assert "Invoke-Expression" not in SCRIPT and "iex " not in SCRIPT


def test_the_elevated_script_backs_up_and_tests_before_restarting():
    backup = SCRIPT.index("Backup-TsFile $config")
    write = SCRIPT.index("Set-TsBlock $p.sshd_block\n")
    check = SCRIPT.index("& $sshd -t")
    restart = SCRIPT.index("Restart-Service sshd")
    assert backup < write < check < restart


def test_passwords_go_off_only_after_the_proof_in_the_script():
    proof = SCRIPT.index("& $p.ssh_exe @($p.verify_args)")
    final = SCRIPT.index("Set-TsBlock $p.sshd_block_final")
    assert proof < final
    assert "if ($verified)" in SCRIPT[proof:final]


def test_other_rules_on_the_port_are_disabled_never_deleted():
    assert "Disable-NetFirewallRule" in SCRIPT
    removed = [ln for ln in SCRIPT.splitlines() if "Remove-NetFirewallRule" in ln or "Remove-NetFirewallHyperVRule" in ln]
    assert removed, "the managed rules are replaced"
    for line in removed:
        assert "Remove-NetFirewall" in line
    # Only our own rules are ever removed: both removals are filtered by our names.
    assert "Group 'terminal-stack ssh'" in SCRIPT and "terminal-stack-sshd-wsl-*" in SCRIPT


_PWSH = shutil.which("pwsh")


@pytest.mark.skipif(_PWSH is None, reason="needs pwsh")
def test_the_elevated_script_parses():
    got = subprocess.run(
        [
            _PWSH,  # type: ignore[list-item]
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
            f"'{ROOT / 'bootstrap' / 'ssh-server.ps1'}', [ref]$null, [ref]$e); $e.Count",
        ],
        capture_output=True, text=True, encoding="utf-8", timeout=120, check=False,
        start_new_session=True,
    )  # fmt: skip
    assert got.stdout.strip() == "0", got.stdout + got.stderr


# ------------------------------------------------------------------ command


def test_setup_refuses_off_windows(monkeypatch, capsys):
    from tstack.commands import ssh as cmd

    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    assert cmd.main(["setup"]) == 2
    assert "runs on Windows" in capsys.readouterr().out


def test_status_off_windows_points_at_windows(monkeypatch, capsys):
    from tstack.commands import ssh as cmd

    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    monkeypatch.setattr(ssh, "settings", lambda: dict(ssh.DEFAULTS))
    assert cmd.main([]) == 0
    assert "Set up from Windows" in capsys.readouterr().out


def test_the_dry_run_changes_nothing(monkeypatch, capsys, tmp_path):
    from tstack.commands import ssh as cmd

    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setenv("TS_ASSUME_YES", "1")
    monkeypatch.setenv("TS_SSH_SERVER", "on")
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.setattr("tstack.wizard.flow.ssh_saved", lambda: dict(ssh.DEFAULTS))
    monkeypatch.setattr(ssh, "sshd_config_path", lambda: tmp_path / "none")
    monkeypatch.setattr(ssh, "wsl_default_distro", lambda: "Ubuntu")
    monkeypatch.setattr(ssh, "ssh_dir", lambda: tmp_path)
    monkeypatch.setattr(ssh, "tailscale_ip", lambda: "")
    called = []
    for name in ("run_elevated", "write_user_authorized", "wsl_apply_server", "set_mirrored", "save"):
        monkeypatch.setattr(ssh, name, lambda *a, _n=name, **k: called.append(_n))
    assert cmd.main(["setup", "--dry-run", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "dry run: nothing changed" in out and "port 22" in out and "port 2222" in out
    assert called == []
    assert os.environ.get("TS_SSH_SERVER") == "on"
