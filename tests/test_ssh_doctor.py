"""`tstack ssh doctor` and the WSL agent bridge.

The checks are pure functions over text (ssh config, the probe's output) plus a
shell runner, so most of this needs no machine: the runner is a fake that
records what it was asked to run. The two shell scripts that DO change files
(the probe and the CRLF fix) are also run for real where a POSIX sh exists.
"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import platform as plat  # noqa: E402
from tstack import ssh, ssh_acl, ssh_doctor  # noqa: E402
from tstack.commands import ssh as cmd  # noqa: E402


def _pub(n: int, comment: str = "k") -> str:
    def f(b: bytes) -> bytes:
        return len(b).to_bytes(4, "big") + b

    blob = base64.b64encode(f(b"ssh-ed25519") + f(bytes([n]) * 32)).decode()
    return f"ssh-ed25519 {blob} {comment}"


def done(stdout: str = "", code: int = 0) -> SimpleNamespace:
    return SimpleNamespace(returncode=code, stdout=stdout, stderr="")


class FakeShell:
    """Answers the probe with canned output and records every other script."""

    def __init__(self, probe: str, config: str = "") -> None:
        self.probe = probe
        self.config = config
        self.ran: list[str] = []

    def __call__(self, script: str, stdin: str | None):
        if script == ssh_doctor.POSIX_PROBE:
            return done(self.probe)
        if script.startswith("cat "):
            return done(self.config)
        self.ran.append(script)
        return done()


CONFIG = """# mine
Host *
  AddKeysToAgent yes
  IdentitiesOnly yes

Host work
  IdentityFile ~/.ssh/id_lab

Host gpu-box
  HostName 192.0.2.20

Host work 192.0.2.14
  User me
"""


# ------------------------------------------------------------- ssh config


def test_duplicate_host_patterns_are_found():
    assert ssh_doctor.duplicate_hosts(CONFIG) == ["work"]
    assert ssh_doctor.duplicate_hosts("Host a\nHost b\n") == []


def test_add_keys_to_agent_is_read_with_either_spelling():
    assert ssh_doctor.adds_keys_to_agent(CONFIG)
    assert ssh_doctor.adds_keys_to_agent("AddKeysToAgent=confirm\n")
    assert not ssh_doctor.adds_keys_to_agent("AddKeysToAgent no\n")
    assert not ssh_doctor.adds_keys_to_agent("# AddKeysToAgent yes\n")


def test_identity_files_resolve_and_skip_tokens(tmp_path):
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_lab").write_text("x", encoding="utf-8")
    (tmp_path / ".ssh" / "bare").write_text("x", encoding="utf-8")
    text = (
        "IdentityFile ~/.ssh/id_lab\nIdentityFile bare\nIdentityFile ~/.ssh/id_lab\n"
        "IdentityFile ~/.ssh/%h\nIdentityFile ~/.ssh/missing\n"
    )
    assert ssh_doctor.identity_files(text, tmp_path) == [
        tmp_path / ".ssh" / "id_lab",
        tmp_path / ".ssh" / "bare",
    ]


def test_crlf_does_not_hide_a_directive():
    assert ssh_doctor.duplicate_hosts("Host a\r\nHost a\r\n") == ["a"]


# -------------------------------------------------------------- posix side

PROBE = """dir 700 /h/.ssh
priv 755 /h/.ssh/key.pem
priv 600 /h/.ssh/id_ok
nopass 0 /h/.ssh/id_ok
cfg 664 /h/.ssh/config
crlf 0 /h/.ssh/config
auth 600 /h/.ssh/authorized_keys
"""


def test_the_probe_output_parses_by_tag():
    got = ssh_doctor.parse_probe(PROBE + "junk line\n")
    assert got["priv"] == [(0o755, "/h/.ssh/key.pem"), (0o600, "/h/.ssh/id_ok")]
    assert got["crlf"] == [(0, "/h/.ssh/config")]


def test_posix_findings_name_each_problem_and_fix_it():
    sh = FakeShell(PROBE, CONFIG)
    keyed: list[str] = []
    found = ssh_doctor.posix_findings("WSL", sh, keygen_p=lambda p: keyed.append(p) or True)
    by = {f.what: f for f in found}
    assert "key.pem" in by["file modes"].detail and "config" in by["file modes"].detail
    assert "id_ok" not in by["file modes"].detail
    assert by["duplicate Host"].fix is None
    assert by["no passphrase"].interactive

    assert by["file modes"].fix()
    assert sh.ran == ["chmod '600' '/h/.ssh/key.pem'", "chmod 'go-w' '/h/.ssh/config'"]
    assert by["CRLF in config"].fix()
    assert sh.ran[-1].startswith("set -- '/h/.ssh/config'\n") and "sed -i" in sh.ran[-1]
    assert by["no passphrase"].fix() and keyed == ["/h/.ssh/id_ok"]


def test_a_tidy_posix_side_is_all_ok():
    sh = FakeShell(
        "dir 700 /h/.ssh\npriv 600 /h/.ssh/id\ncfg 600 /h/.ssh/config\n", "AddKeysToAgent yes\n"
    )
    found = ssh_doctor.posix_findings("WSL", sh, keygen_p=lambda p: True)
    assert {f.state for f in found} == {"ok"}


def test_no_ssh_dir_and_an_unreadable_one():
    assert ssh_doctor.posix_findings("WSL", FakeShell("none\n"), keygen_p=bool)[0].state == "info"
    found = ssh_doctor.posix_findings("WSL", lambda s, i: None, keygen_p=bool)
    assert found[0].state == "warn" and "could not be read" in found[0].detail


def test_no_config_is_info_not_a_warning():
    found = ssh_doctor.posix_findings("WSL", FakeShell("dir 700 /h/.ssh\n"), keygen_p=bool)
    assert ("info", "~/.ssh/config") in {(f.state, f.what) for f in found}


def test_a_path_with_a_quote_is_quoted():
    assert ssh_doctor._quote("it's") == "'it'\\''s'"


needs_sh = pytest.mark.skipif(
    sys.platform == "win32" or not shutil.which("sh"), reason="a POSIX sh is needed"
)


@needs_sh
def test_the_real_probe_reads_a_real_ssh_dir(tmp_path):
    d = tmp_path / ".ssh"
    d.mkdir(mode=0o700)
    key = d / "id_test"
    key.write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nxx\n", encoding="utf-8")
    key.chmod(0o644)
    (d / "id_test.pub").write_text(_pub(1) + "\n", encoding="utf-8")
    (d / "config").write_bytes(b"Host a\r\n")
    (d / "config").chmod(0o600)
    got = subprocess.run(
        ["sh", "-c", ssh_doctor.POSIX_PROBE], env=dict(os.environ, HOME=str(tmp_path)),
        capture_output=True, text=True, check=False, timeout=60, start_new_session=True,
    )  # fmt: skip
    probe = ssh_doctor.parse_probe(got.stdout)
    assert probe["priv"] == [(0o644, str(key))]
    assert probe["crlf"] == [(0, str(d / "config"))]
    assert "dir" in probe and "auth" not in probe


@needs_sh
def test_the_real_crlf_fix_backs_up_first(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_bytes(b"Host a\r\n  User b\r\n")

    def sh(script, stdin):
        return subprocess.run(["sh", "-c", script], capture_output=True, text=True, check=False,
                              timeout=60, start_new_session=True)  # fmt: skip

    assert ssh_doctor._crlf_fix(sh, str(cfg))
    assert assert_no_cr(cfg)
    backups = list(tmp_path.glob("config.bak.*"))
    assert len(backups) == 1 and b"\r" in backups[0].read_bytes()
    cfg.write_bytes(b"Host a\r\n")
    assert ssh_doctor._crlf_fix(sh, str(cfg))
    assert len(list(tmp_path.glob("config.bak.*"))) == 2, "a same-day backup is never clobbered"


def assert_no_cr(path: Path) -> bool:
    return b"\r" not in path.read_bytes()


# ----------------------------------------------------------- windows side


@pytest.fixture
def win(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setattr(ssh, "ssh_dir", lambda: tmp_path / ".ssh")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(ssh, "_windows_service", lambda name: ("Running", "Automatic"))
    monkeypatch.setattr(ssh_acl, "exposed", lambda d: [])
    monkeypatch.setattr(ssh, "has_passphrase", lambda p: True)
    d = tmp_path / ".ssh"
    d.mkdir()
    (d / "id_lab").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\n", encoding="utf-8")
    (d / "id_lab.pub").write_text(_pub(7) + "\n", encoding="utf-8")
    (d / "config").write_text(CONFIG, encoding="utf-8")
    return tmp_path


def test_a_key_the_agent_lacks_is_offered_to_ssh_add(win, monkeypatch):
    monkeypatch.setattr(ssh_doctor, "agent_fingerprints", lambda: (1, set()))
    monkeypatch.setattr(ssh_doctor, "ssh_add", lambda: "ssh-add.exe")
    ran = []
    monkeypatch.setattr(ssh_doctor, "_interactive", lambda argv: ran.append(argv) or True)
    by = {f.what: f for f in ssh_doctor.windows_findings()}
    assert "id_lab" in by["agent keys"].detail and by["agent keys"].interactive
    assert by["agent keys"].fix()
    assert ran == [["ssh-add.exe", str(win / ".ssh" / "id_lab")]]


def test_a_loaded_key_is_ok(win, monkeypatch):
    fp = ssh.parse_key(_pub(7)).fingerprint  # type: ignore[union-attr]
    monkeypatch.setattr(ssh_doctor, "agent_fingerprints", lambda: (0, {fp}))
    by = {f.what: f for f in ssh_doctor.windows_findings()}
    assert by["agent keys"].state == "ok"
    assert by["ssh-agent service"].state == "ok"


def test_windows_service_acl_and_passphrase_findings(win, monkeypatch):
    monkeypatch.setattr(ssh, "_windows_service", lambda name: ("Stopped", "Manual"))
    monkeypatch.setattr(ssh_acl, "exposed", lambda d: [(d / "id_lab", ["CodexSandboxUsers"])])
    monkeypatch.setattr(ssh_acl, "fix", lambda d: True)
    monkeypatch.setattr(ssh, "has_passphrase", lambda p: False)
    monkeypatch.setattr(ssh_doctor, "agent_fingerprints", lambda: (2, set()))
    by = {f.what: f for f in ssh_doctor.windows_findings()}
    assert by["ssh-agent service"].state == "warn"
    assert "does not answer" in by["agent keys"].detail
    assert by["no passphrase"].detail.startswith("id_lab")
    assert by["~/.ssh permissions"].fix is not None
    assert not by["~/.ssh permissions"].fix(), "still exposed after the fix is a failure"


def test_agent_fingerprints_reads_ssh_add(monkeypatch):
    monkeypatch.setattr(ssh_doctor, "ssh_add", lambda: "ssh-add")
    monkeypatch.setattr(ssh_doctor.proc, "capture",
                        lambda argv, timeout=15: done("256 SHA256:abc me (ED25519)\n"))  # fmt: skip
    assert ssh_doctor.agent_fingerprints() == (0, {"SHA256:abc"})
    monkeypatch.setattr(ssh_doctor, "ssh_add", lambda: None)
    assert ssh_doctor.agent_fingerprints() == (2, set())


# ------------------------------------------------------------------ bridge


def test_bridge_states_read_as_findings():
    assert ssh_doctor.bridge_finding(0, None).state == "ok"
    assert ssh_doctor.bridge_finding(1, lambda: True).fix is None, "nothing to fix when it relays"
    off = ssh_doctor.bridge_finding(3, lambda: True)
    assert off.state == "warn" and off.fix is not None
    assert ssh_doctor.bridge_finding(99, None).state == "warn"


def test_the_unit_relays_the_agent_pipe_to_the_socket_zshrc_probes():
    unit = ssh.bridge_unit()
    assert f"UNIX-LISTEN:%t/{ssh.BRIDGE_SOCK},fork,umask=077" in unit
    assert f"%h/.local/bin/npiperelay.exe -ei -s {ssh.AGENT_PIPE},nofork" in unit
    assert "WantedBy=default.target" in unit
    zshrc = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    assert f"$_ts_rt/{ssh.BRIDGE_SOCK}" in zshrc


def test_install_bridge_steps(monkeypatch):
    calls = []
    monkeypatch.setattr(ssh, "install_npiperelay", lambda: None)
    assert ssh.wsl_install_bridge("U") == (
        False,
        f"npiperelay is not installed (winget install --id {ssh.NPIPERELAY_ID})",
    )

    monkeypatch.setattr(ssh, "install_npiperelay", lambda: Path(r"C:\x\npiperelay.exe"))

    def wsl(argv, **kw):
        calls.append((argv, kw))
        return done(code=0)

    monkeypatch.setattr(ssh, "wsl", wsl)
    assert ssh.wsl_install_bridge("U") == (True, "")
    assert calls[0][1]["root"] is True and "socat" in calls[0][0][2]
    assert (
        calls[1][0][-1] == str(Path(r"C:\x\npiperelay.exe"))
        and calls[1][1]["stdin"] == ssh.bridge_unit()
    )

    monkeypatch.setattr(ssh, "wsl", lambda argv, **kw: done("E: no apt", 100))
    ok, why = ssh.wsl_install_bridge("U")
    assert not ok and "socat" in why

    seq = iter([done(), None])
    monkeypatch.setattr(ssh, "wsl", lambda argv, **kw: next(seq))
    assert ssh.wsl_install_bridge("U") == (
        False,
        "the bridge unit did not start: wsl.exe could not run",
    )


def test_bridge_state_and_remove(monkeypatch):
    monkeypatch.setattr(ssh, "wsl", lambda argv, **kw: done("0\n"))
    assert ssh.wsl_bridge_state("U") == 0
    monkeypatch.setattr(ssh, "wsl", lambda argv, **kw: None)
    assert ssh.wsl_bridge_state("U") == 2
    assert not ssh.wsl_remove_bridge("U")
    monkeypatch.setattr(ssh, "wsl", lambda argv, **kw: done("removed\n"))
    assert ssh.wsl_remove_bridge("U")
    monkeypatch.setattr(ssh, "wsl", lambda argv, **kw: done(""))
    assert not ssh.wsl_remove_bridge("U"), "nothing there is not 'removed'"


def test_npiperelay_is_found_where_winget_puts_it(monkeypatch, tmp_path):
    pkg = tmp_path / "Microsoft/WinGet/Packages/albertony.npiperelay_Microsoft.Winget.Source_x"
    pkg.mkdir(parents=True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(ssh.shutil, "which", lambda name: None)
    assert ssh.npiperelay_path() is None
    (pkg / "npiperelay.exe").write_bytes(b"MZ")
    assert ssh.npiperelay_path() == pkg / "npiperelay.exe"
    assert ssh.install_npiperelay() == pkg / "npiperelay.exe"


def test_install_npiperelay_runs_winget(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ran = []
    monkeypatch.setattr(ssh.shutil, "which", lambda name: "winget" if name == "winget" else None)
    monkeypatch.setattr(ssh.proc, "capture", lambda argv, timeout=0: ran.append(argv))
    assert ssh.install_npiperelay() is None
    assert ran[0][:4] == ["winget", "install", "--id", ssh.NPIPERELAY_ID]


# ------------------------------------------------------------------ collect


def test_collect_on_windows_reads_wsl_through_wsl_exe(monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setattr(ssh_doctor, "windows_findings", lambda: [])
    monkeypatch.setattr(ssh, "wsl_default_distro", lambda: "Ubuntu")
    monkeypatch.setattr(ssh, "settings", lambda: dict(ssh.DEFAULTS))
    monkeypatch.setattr(ssh, "wsl_bridge_state", lambda d: 3)
    seen = []

    def wsl(argv, **kw):
        seen.append((argv, kw["distro"]))
        return done("dir 700 /h/.ssh\n")

    monkeypatch.setattr(ssh, "wsl", wsl)
    found = ssh_doctor.collect()
    assert seen[0] == (["sh", "-c", ssh_doctor.POSIX_PROBE], "Ubuntu")
    assert any(f.what == "agent bridge" and f.fix is not None for f in found)


def test_collect_on_windows_without_wsl(monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setattr(ssh_doctor, "windows_findings", lambda: ["w"])
    monkeypatch.setattr(ssh, "wsl_default_distro", lambda: "")
    assert ssh_doctor.collect() == ["w"]


@pytest.mark.parametrize("kind", [plat.WSL, plat.LINUX])
def test_collect_on_posix_runs_locally(monkeypatch, kind):
    monkeypatch.setattr(plat, "kind", lambda: kind)
    monkeypatch.setattr(ssh_doctor.proc, "capture",
                        lambda argv, stdin=None, timeout=0: done("3\n" if ssh.BRIDGE_UNIT in argv[2] else "none\n"))  # fmt: skip
    found = ssh_doctor.collect()
    bridge = [f for f in found if f.what == "agent bridge"]
    if kind == plat.WSL:
        assert bridge and "from PowerShell" in bridge[0].detail and bridge[0].fix is None
    else:
        assert not bridge


# ------------------------------------------------------------------ command


def _findings():
    calls = []
    return calls, [
        ssh_doctor.Finding(
            "WSL",
            "warn",
            "file modes",
            "k",
            fix=lambda: calls.append("modes") or True,
            fix_says="chmod",
        ),
        ssh_doctor.Finding(
            "WSL",
            "warn",
            "no passphrase",
            "k",
            fix=lambda: calls.append("pass") or True,
            fix_says="passphrase",
            interactive=True,
        ),
        ssh_doctor.Finding("WSL", "warn", "duplicate Host", "a"),
        ssh_doctor.Finding("Windows", "ok", "agent keys", "3"),
    ]


def test_the_report_counts_what_can_be_repaired(monkeypatch, capsys):
    _, found = _findings()
    monkeypatch.setattr(ssh_doctor, "collect", lambda: found)
    assert cmd.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "2 can be repaired: tstack ssh doctor --fix" in out and "  Windows" in out


def test_yes_applies_only_the_fixes_that_ask_nothing(monkeypatch, capsys):
    calls, found = _findings()
    monkeypatch.setattr(ssh_doctor, "collect", lambda: found)
    assert cmd.main(["doctor", "--fix", "--yes"]) == 1
    assert calls == ["modes"]
    assert "skipped under --yes" in capsys.readouterr().out


def test_fix_asks_before_each_repair(monkeypatch, capsys):
    calls, found = _findings()
    monkeypatch.setattr(ssh_doctor, "collect", lambda: found[:2])
    answers = iter([True, False])
    from tstack import confirm

    monkeypatch.setattr(confirm, "confirm", lambda prompt, assume_yes=False: next(answers))
    monkeypatch.delenv("TS_ASSUME_YES", raising=False)
    assert cmd.main(["doctor", "--fix"]) == 1
    assert calls == ["modes"]


def test_everything_repaired_exits_zero(monkeypatch, capsys):
    calls, found = _findings()
    monkeypatch.setattr(ssh_doctor, "collect", lambda: found[:2] + found[3:])
    from tstack import confirm

    monkeypatch.setattr(confirm, "confirm", lambda prompt, assume_yes=False: True)
    monkeypatch.delenv("TS_ASSUME_YES", raising=False)
    assert cmd.main(["doctor", "--fix"]) == 0
    assert calls == ["modes", "pass"]
    assert "all repaired." in capsys.readouterr().out


def test_a_clean_machine_reports_zero(monkeypatch):
    monkeypatch.setattr(
        ssh_doctor, "collect", lambda: [ssh_doctor.Finding("WSL", "ok", "file modes")]
    )
    assert cmd.main(["doctor"]) == 0
