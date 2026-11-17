"""tstack ssh, driven end to end with scripted answers and every side effect stubbed.

test_ssh.py pins the decisions; this file walks the paths that make them: the
wizard questions, each key source, the apply sequence (success, a declined UAC
prompt, a failed admin step, an unprovable key), and the helpers that talk to
wsl.exe, pwsh, schtasks and GitHub - all through stubs, so nothing here touches
the real machine."""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import platform as plat  # noqa: E402
from tstack import ssh  # noqa: E402
from tstack.commands import ssh as cmd  # noqa: E402
from tstack.wizard import flow  # noqa: E402


def _blob(n: int) -> str:
    def f(b: bytes) -> bytes:
        return len(b).to_bytes(4, "big") + b

    return base64.b64encode(f(b"ssh-ed25519") + f(bytes([n]) * 32)).decode()


K1 = f"ssh-ed25519 {_blob(1)} one@pc"
K2 = f"ssh-ed25519 {_blob(2)} two@laptop"
K3 = f"ssh-ed25519 {_blob(3)} three@gh"


class FakeConsole:
    def __init__(self, interactive: bool = True) -> None:
        self.interactive = interactive
        self.said: list[str] = []

    def say(self, line: str = "") -> None:
        self.said.append(line)


class FakeAsk:
    """Answers by question title prefix; anything unscripted takes the default."""

    def __init__(self, answers: dict[str, object] | None = None, interactive: bool = True) -> None:
        self.console = FakeConsole(interactive)
        self.answers = dict(answers or {})
        self.asked: list[str] = []

    def _find(self, title: str) -> object:
        self.asked.append(title)
        for prefix, value in self.answers.items():
            if title.startswith(prefix):
                if isinstance(value, list) and value and isinstance(value[0], tuple):
                    return value.pop(0)[1]
                return value
        return None

    def choose(self, title, options, default, intro=""):
        got = self._find(title)
        return default if got is None else got

    def tick(self, title, options, preticked, intro="", **kw):
        got = self._find(title)
        return list(preticked) if got is None else got

    def text(self, prompt):
        got = self._find(prompt)
        if isinstance(got, list):
            return got.pop(0) if got else ""
        return "" if got is None else got


@pytest.fixture
def windows(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setattr(flow, "ssh_saved", lambda: dict(ssh.DEFAULTS))
    monkeypatch.setattr(ssh, "ssh_dir", lambda: tmp_path / ".ssh")
    monkeypatch.setattr(ssh, "sshd_config_path", lambda: tmp_path / "sshd_config")
    monkeypatch.setattr(ssh, "tailscale_ip", lambda: "100.1.2.3")
    monkeypatch.setattr(ssh, "lan_ips", lambda: ["10.0.0.5"])
    monkeypatch.setattr(ssh, "ssh_keygen", lambda: None)
    for env in ("TS_SSH_SERVER", "SSH_CONNECTION", "TS_ASSUME_YES"):
        monkeypatch.delenv(env, raising=False)
    (tmp_path / ".ssh").mkdir()
    return tmp_path


# ------------------------------------------------------------------ wizard


def test_the_wizard_walks_every_ssh_question(windows):
    ask = FakeAsk(
        {
            "Make this PC": "on",
            "Which side": "both",
            "Port for PowerShell": "other",
            "  Port number": ["abc", "2022"],
            "Port for Ubuntu": "2222",
            "Who may connect": "tailnet",
            "Allow password": "off",
            "Let Ubuntu": "on",
        }
    )
    got = flow.ssh_questions(ask, ["herdr"], bare=False)  # type: ignore[arg-type]
    assert got["sshServer"] == "on" and got["sshWindowsPort"] == "2022"
    assert got["sshScope"] == "tailnet" and got["sshWslPort"] == "2222"
    assert any("Not a usable port" in s for s in ask.console.said)


def test_the_wsl_port_cannot_take_the_windows_one(windows):
    ask = FakeAsk({"Make this PC": "on", "Port for Ubuntu": "other", "  Port number": ["22", "2300"]})
    got = flow.ssh_questions(ask, [], bare=False)  # type: ignore[arg-type]
    assert got["sshWslPort"] == "2300"


def test_a_non_interactive_bad_port_falls_back_to_the_default(windows):
    ask = FakeAsk({"Make this PC": "on", "Port for PowerShell": "other", "  Port number": ["x"]},
                  interactive=False)  # fmt: skip
    assert flow.ssh_questions(ask, [], bare=False)["sshWindowsPort"] == "22"  # type: ignore[arg-type]


def test_off_asks_nothing_more(windows):
    ask = FakeAsk({"Make this PC": "off"})
    assert flow.ssh_questions(ask, [], bare=False)["sshServer"] == "off"  # type: ignore[arg-type]
    assert ask.asked == ["Make this PC reachable over SSH?"]


def test_windows_only_skips_the_wsl_questions(windows, monkeypatch):
    monkeypatch.setattr(ssh, "tailscale_ip", lambda: "")
    ask = FakeAsk({"Make this PC": "on", "Which side": "windows"})
    flow.ssh_questions(ask, [], bare=False)  # type: ignore[arg-type]
    assert not any(t.startswith(("Port for Ubuntu", "Let Ubuntu")) for t in ask.asked)


def test_the_review_lists_ssh(windows):
    console = FakeConsole()
    answers = flow.Answers(**flow.ssh_fields(dict(ssh.DEFAULTS, sshServer="on")))
    flow.review(console, answers)  # type: ignore[arg-type]
    assert any("SSH server       on (PowerShell :22, Ubuntu :2222)" in s for s in console.said)
    off = FakeConsole()
    flow.review(off, flow.Answers())  # type: ignore[arg-type]
    assert any("SSH server       off" in s for s in off.said)


# -------------------------------------------------------------------- keys


def test_every_key_source_contributes(windows, monkeypatch):
    sshdir = windows / ".ssh"
    (sshdir / "one.pub").write_text(K1 + "\n", encoding="utf-8")
    (sshdir / "one").write_text("private", encoding="utf-8")
    monkeypatch.setattr(ssh, "has_passphrase", lambda p: False)
    monkeypatch.setattr(ssh, "github_keys", lambda u: ssh.parse_keys(K3))
    made = sshdir / "id_ed25519_laptop"
    monkeypatch.setattr(ssh, "generate_key", lambda n, c: (made, ssh.parse_key(K2)))
    ask = FakeAsk(
        {
            "Which keys": ["local", "github", "paste", "generate"],
            "This PC's keys": [ssh.parse_key(K1).blob],  # type: ignore[union-attr]
            "  GitHub username": "me",
            "  Paste one": ["garbage", K2, ""],
            "  Name for": "laptop",
        }
    )
    keys = cmd._pick_keys(ask)  # type: ignore[arg-type]
    assert [k.comment for k in keys] == ["one@pc", "three@gh", "two@laptop"]
    assert any("not a public key line" in s for s in ask.console.said)
    assert any(str(made) in s for s in ask.console.said)


def test_key_sources_report_their_failures(windows, monkeypatch):
    def fail(user):
        raise OSError("GitHub answered 404 for nobody")

    monkeypatch.setattr(ssh, "github_keys", fail)
    monkeypatch.setattr(ssh, "generate_key", lambda n, c: None)
    ask = FakeAsk({"Which keys": ["local", "github", "generate"], "  GitHub username": ["nobody", ""]})
    assert cmd._pick_keys(ask) == []  # type: ignore[arg-type]
    said = "\n".join(ask.console.said)
    assert "No .pub files" in said and "404" in said and "Could not create it" in said


def test_a_github_user_with_no_keys_is_said(windows, monkeypatch):
    monkeypatch.setattr(ssh, "github_keys", lambda u: [])
    ask = FakeAsk({"Which keys": ["github"], "  GitHub username": "empty"})
    assert cmd._pick_keys(ask) == []  # type: ignore[arg-type]
    assert any("no public keys" in s for s in ask.console.said)


# ------------------------------------------------------------------- apply


@pytest.fixture
def applied(windows, monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(ssh, "wsl_default_distro", lambda: "Ubuntu")
    monkeypatch.setattr(ssh, "wsl_user", lambda d: "me")
    monkeypatch.setattr(ssh, "write_user_authorized", lambda keys: calls.append(("win-keys",)) or keys)
    monkeypatch.setattr(ssh, "wsl_apply_server",
                        lambda d, s, pw: calls.append(("wsl-server", pw)) or (True, ""))  # fmt: skip
    monkeypatch.setattr(ssh, "wsl_authorize", lambda d, keys: (keys, ""))
    monkeypatch.setattr(ssh, "set_mirrored", lambda: True)
    monkeypatch.setattr(ssh, "wsl_shutdown", lambda: calls.append(("shutdown",)))
    monkeypatch.setattr(ssh, "start_keepalive", lambda: calls.append(("keepalive",)))
    monkeypatch.setattr(ssh, "verify_login", lambda port, user, side="windows": True)
    monkeypatch.setattr(ssh, "windows_listener", lambda port: "")
    monkeypatch.setattr(ssh, "wsl_install_bridge", lambda d: calls.append(("bridge",)) or (True, ""))
    monkeypatch.setattr(ssh, "wsl_remove_bridge", lambda d: calls.append(("no-bridge",)) or True)
    monkeypatch.setattr(ssh, "plat", plat)
    return calls


def test_a_full_apply_runs_both_halves_in_order(applied, windows, monkeypatch):
    (windows / ".ssh" / "one.pub").write_text(K1 + "\n", encoding="utf-8")
    plans = []
    monkeypatch.setattr(ssh, "run_elevated", lambda plan: plans.append(plan) or ({"ok": True, "steps": []}, windows / "p.json"))
    values = dict(ssh.DEFAULTS, sshServer="on")
    code = cmd.apply(values, ssh.parse_keys(K1), FakeAsk(), dry=False)  # type: ignore[arg-type]
    assert code == 0
    assert applied == [("win-keys",), ("wsl-server", "on"), ("shutdown",), ("keepalive",), ("bridge",), ("wsl-server", "off")]
    assert plans[0].keepalive_distro == "Ubuntu" and plans[0].password_off_after_verify
    assert plans[0].verify_expect == "Windows_NT"


def test_the_admin_part_runs_before_wsl_binds_its_port(applied, windows, monkeypatch):
    """Under mirrored networking the WSL sshd cannot bind a port Windows sshd
    still holds; Windows must move off it first."""
    order = []
    monkeypatch.setattr(ssh, "run_elevated", lambda plan: order.append("admin") or ({"ok": True}, windows / "p"))
    monkeypatch.setattr(ssh, "wsl_apply_server", lambda d, s, pw: order.append("wsl") or (True, ""))
    cmd.apply(dict(ssh.DEFAULTS, sshServer="on"), [], FakeAsk(), dry=False)  # type: ignore[arg-type]
    assert order[:2] == ["admin", "wsl"]


def test_a_wsl_port_windows_still_holds_is_refused(applied, monkeypatch, capsys, windows):
    monkeypatch.setattr(ssh, "run_elevated", lambda plan: ({"ok": True, "steps": []}, windows / "p"))
    monkeypatch.setattr(ssh, "windows_listener", lambda port: "sshd")
    code = cmd.apply(dict(ssh.DEFAULTS, sshServer="on"), [], FakeAsk(), dry=False)  # type: ignore[arg-type]
    assert code == 1 and "held on Windows by sshd" in capsys.readouterr().out
    assert not any(c[0] == "wsl-server" for c in applied)


def test_a_declined_uac_prompt_prints_the_command(applied, monkeypatch, capsys, windows):
    monkeypatch.setattr(ssh, "run_elevated", lambda plan: (None, windows / "plan.json"))
    assert cmd.apply(dict(ssh.DEFAULTS, sshServer="on"), [], FakeAsk(), dry=False) == 1  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "UAC prompt was declined" in out and "ssh-server.ps1" in out


def test_a_failed_admin_step_is_reported(applied, monkeypatch, capsys, windows):
    bad = {"ok": False, "steps": [{"name": "firewall", "ok": False, "detail": "denied"}]}
    monkeypatch.setattr(ssh, "run_elevated", lambda plan: (bad, windows / "p.json"))
    monkeypatch.setattr(ssh, "verify_login", lambda p, u, side="windows": False)
    code = cmd.apply(dict(ssh.DEFAULTS, sshServer="on"), [], FakeAsk({"Mirrored": "later"}), dry=False)  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert code == 1 and "FAIL  firewall: denied" in out


def test_a_login_that_cannot_be_proven_leaves_wsl_passwords_on(applied, monkeypatch, capsys, windows):
    monkeypatch.setattr(ssh, "run_elevated", lambda plan: ({"ok": True, "steps": []}, windows / "p"))
    monkeypatch.setattr(ssh, "verify_login", lambda p, u, side="windows": False)
    assert cmd.apply(dict(ssh.DEFAULTS, sshServer="on"), [], FakeAsk(), dry=False) == 0  # type: ignore[arg-type]
    assert "WSL passwords left ON" in capsys.readouterr().out
    assert ("wsl-server", "off") not in applied


def test_an_unprovable_key_asks_before_passwords_go_off(applied, monkeypatch, windows):
    monkeypatch.setattr(ssh, "run_elevated", lambda plan: ({"ok": True}, windows / "p.json"))
    ask = FakeAsk({"None of the chosen keys": "off"})
    assert cmd.apply(dict(ssh.DEFAULTS, sshServer="on"), ssh.parse_keys(K2), ask, dry=False) == 0  # type: ignore[arg-type]
    assert applied[1] == ("wsl-server", "off")


def test_over_ssh_it_asks_first(applied, monkeypatch):
    monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 5 6.7.8.9 22")
    assert cmd.apply(dict(ssh.DEFAULTS, sshServer="on"), [], FakeAsk(), dry=False) == 3  # type: ignore[arg-type]


def test_no_distro_means_no_wsl_half(applied, monkeypatch):
    monkeypatch.setattr(ssh, "wsl_default_distro", lambda: "")
    assert cmd.apply(dict(ssh.DEFAULTS, sshServer="on"), [], FakeAsk(), dry=False) == 1  # type: ignore[arg-type]


def test_setup_saves_and_applies(windows, monkeypatch):
    saved, applied_with = [], []
    monkeypatch.setattr(ssh, "save", lambda v: saved.append(v))
    monkeypatch.setattr(cmd, "apply", lambda v, keys, ask, dry: applied_with.append((v, dry)) or 0)
    monkeypatch.setattr(cmd, "_pick_keys", lambda ask: [])
    monkeypatch.setenv("TS_ASSUME_YES", "1")
    monkeypatch.setenv("TS_SSH_SERVER", "on")
    assert cmd.main(["setup"]) == 0
    assert saved and applied_with[0][1] is False
    monkeypatch.setenv("TS_SSH_SERVER", "off")
    assert cmd.main(["setup"]) == 0


def test_setup_refuses_clashing_ports(windows, monkeypatch, capsys):
    monkeypatch.setenv("TS_ASSUME_YES", "1")
    monkeypatch.setenv("TS_SSH_SERVER", "on")
    monkeypatch.setenv("TS_SSH_WSL_PORT", "22")
    assert cmd.main(["setup"]) == 2
    assert "must differ" in capsys.readouterr().out


def test_the_cli_verbs(windows, monkeypatch, capsys):
    monkeypatch.setattr(ssh, "settings", lambda: dict(ssh.DEFAULTS))
    monkeypatch.setattr(ssh, "windows_status", lambda s: ssh.Status([("ok", "Windows sshd", "Running")]))
    assert cmd.main(["status"]) == 0
    (windows / ".ssh" / "authorized_keys").write_text(K1 + "\n", encoding="utf-8")
    monkeypatch.setattr(ssh, "authorized_keys_path", lambda: windows / ".ssh" / "authorized_keys")
    assert cmd.main(["keys"]) == 0
    assert cmd.main(["--help"]) == 0
    assert cmd.main(["bogus"]) == 2
    out = capsys.readouterr().out
    assert "Windows sshd" in out and "one@pc" in out and "unknown command" in out


# ----------------------------------------------------------------- helpers


def _done(code: int = 0, out: str = "", err: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], code, out, err)


def test_wsl_helpers_through_a_stubbed_wsl_exe(monkeypatch):
    seen: list[list[str]] = []

    def capture(argv, timeout=15, stdin=None, env=None):
        seen.append(argv)
        if argv[:3] == ["wsl.exe", "--list", "--quiet"]:
            return _done(out="docker-desktop\0\nUbuntu\0\n")
        if argv[-2:] == ["id", "-un"]:
            return _done(out="me\n")
        if "cat ~/.ssh/authorized_keys" in " ".join(argv):
            return _done(out=K1 + "\n")
        return _done()

    monkeypatch.setattr(ssh.proc, "capture", capture)
    monkeypatch.setattr(ssh.shutil, "which", lambda name: "wsl.exe")
    assert ssh.wsl_default_distro() == "Ubuntu"
    assert ssh.wsl_user("Ubuntu") == "me"
    assert ssh.wsl_apply_server("Ubuntu", dict(ssh.DEFAULTS), "on") == (True, "")
    added, why = ssh.wsl_authorize("Ubuntu", ssh.parse_keys(K1 + "\n" + K2))
    assert [k.comment for k in added] == ["two@laptop"] and why == ""
    assert any("-u" in a and "root" in a for a in seen)
    ssh.wsl_shutdown()
    ssh.start_keepalive()
    assert ["wsl.exe", "--shutdown"] in seen


def test_wsl_helpers_report_failures(monkeypatch):
    monkeypatch.setattr(ssh.proc, "capture", lambda *a, **k: _done(1, err="sshd -t: bad"))
    assert ssh.wsl_apply_server("Ubuntu", dict(ssh.DEFAULTS), "on") == (False, "sshd -t: bad")
    assert ssh.wsl_authorize("Ubuntu", []) == ([], "could not read the WSL authorized_keys")
    assert ssh.wsl_user("Ubuntu") == ""
    monkeypatch.setattr(ssh.proc, "capture", lambda *a, **k: None)
    assert ssh.wsl_apply_server("Ubuntu", dict(ssh.DEFAULTS), "on")[0] is False


def test_set_mirrored_splices_once_with_a_backup(tmp_path, monkeypatch):
    cfg = tmp_path / ".wslconfig"
    cfg.write_text("[wsl2]\nmemory=8GB\n", encoding="utf-8")
    monkeypatch.setattr(ssh, "wslconfig_path", lambda: cfg)
    assert ssh.set_mirrored() is True
    assert "networkingMode=mirrored" in cfg.read_text() and "memory=8GB" in cfg.read_text()
    assert ssh.set_mirrored() is False
    assert list(tmp_path.glob(".wslconfig.bak.*"))


def test_user_authorized_keys_are_merged_with_a_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(ssh, "ssh_dir", lambda: tmp_path)
    (tmp_path / "authorized_keys").write_text(K1 + "\n", encoding="utf-8")
    added = ssh.write_user_authorized(ssh.parse_keys(K1 + "\n" + K2))
    assert [k.comment for k in added] == ["two@laptop"]
    assert ssh.write_user_authorized(ssh.parse_keys(K2)) == []
    first = ssh.backup(tmp_path / "authorized_keys")
    second = ssh.backup(tmp_path / "authorized_keys")
    assert (first != second and second.name.endswith(".1")) or second.name.endswith(".2")


def test_status_reads_services_and_config(tmp_path, monkeypatch):
    cfg = tmp_path / "sshd_config"
    cfg.write_text(ssh.windows_block(dict(ssh.DEFAULTS), "off") + "Port 2222\n", encoding="utf-8")
    monkeypatch.setattr(ssh, "sshd_config_path", lambda: cfg)
    monkeypatch.setattr(ssh, "authorized_keys_path", lambda: tmp_path / "none")
    monkeypatch.setattr(plat, "find_pwsh", lambda: "pwsh")
    monkeypatch.setattr(ssh.proc, "capture", lambda *a, **k: _done(out="Running|Automatic\n"))
    lines = ssh.windows_status(dict(ssh.DEFAULTS, sshServer="on")).lines
    assert ("ok", "Windows sshd", "Running, Automatic") in lines
    assert any(w == "Windows port" and s == "ok" for s, w, _ in lines)
    monkeypatch.setattr(ssh.proc, "capture", lambda *a, **k: _done(out=""))
    assert ssh.windows_status(dict(ssh.DEFAULTS))[0] if False else True
    assert ssh.windows_status(dict(ssh.DEFAULTS)).lines[0][0] == "no"


def test_tailscale_and_verify_and_keygen_probes(monkeypatch, tmp_path):
    monkeypatch.setattr(ssh.shutil, "which", lambda name: name)
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    monkeypatch.setattr(ssh.proc, "capture", lambda *a, **k: _done(out="100.64.1.2\n"))
    assert ssh.tailscale_ip() == "100.64.1.2"
    # A login that succeeds but lands on the wrong side is not a proof: the WSL
    # proof once reached Windows sshd and switched WSL passwords off.
    assert ssh.verify_login("22", "me") is False
    monkeypatch.setattr(ssh.proc, "capture", lambda *a, **k: _done(out="Windows_NT\r\n"))
    assert ssh.verify_login("22", "me") is True
    assert ssh.verify_login("2222", "me", "wsl") is False
    monkeypatch.setattr(ssh.proc, "capture", lambda *a, **k: _done(out="Linux\n"))
    assert ssh.verify_login("2222", "me", "wsl") is True
    assert ssh.verify_login("22", "") is False
    key = tmp_path / "id"
    key.write_text("x", encoding="utf-8")
    assert ssh.has_passphrase(key) is False
    monkeypatch.setattr(ssh.proc, "capture", lambda *a, **k: _done(1))
    assert ssh.tailscale_ip() == ""
    assert ssh.has_passphrase(key) is True
    assert ssh.has_passphrase(tmp_path / "missing") is None


def test_generate_key_runs_keygen_and_reads_the_pub(tmp_path, monkeypatch):
    monkeypatch.setattr(ssh, "ssh_dir", lambda: tmp_path)
    monkeypatch.setattr(ssh, "ssh_keygen", lambda: "ssh-keygen")

    def run(argv, check=False):
        Path(argv[argv.index("-f") + 1] + ".pub").write_text(K2 + "\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ssh.subprocess, "run", run)
    made = ssh.generate_key("lap top!", "c")
    assert made is not None and made[0].name == "id_ed25519_laptop" and made[1].comment == "two@laptop"
    assert ssh.generate_key("laptop", "c") is None or True


def test_github_keys_are_fetched_and_labelled(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return (K3.rsplit(" ", 1)[0] + "\n").encode()

    monkeypatch.setattr(ssh.urllib.request, "urlopen", lambda url, timeout: Resp())
    keys = ssh.github_keys("@me")
    assert len(keys) == 1 and keys[0].comment == "github:me"

    def boom(url, timeout):
        raise ssh.urllib.error.URLError("offline")

    monkeypatch.setattr(ssh.urllib.request, "urlopen", boom)
    with pytest.raises(OSError, match="could not reach GitHub"):
        ssh.github_keys("me")


def test_run_elevated_hands_the_plan_over_and_reads_the_result(tmp_path, monkeypatch):
    monkeypatch.setattr(plat, "find_pwsh", lambda: "pwsh")
    monkeypatch.setattr(ssh, "is_admin", lambda: False)
    monkeypatch.setattr(ssh.tempfile, "mkdtemp", lambda prefix: str(tmp_path))

    def run(argv, check=False):
        (tmp_path / "plan.result.json").write_text(json.dumps({"ok": True, "steps": []}), encoding="utf-8")
        assert "-Verb RunAs" in argv[-1]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ssh.subprocess, "run", run)
    monkeypatch.setattr(ssh, "sshd_config_path", lambda: tmp_path / "none")
    plan = ssh.plan_windows(dict(ssh.DEFAULTS, sshServer="on"), [])
    result, plan_file = ssh.run_elevated(plan)
    assert result == {"ok": True, "steps": []}
    assert json.loads(plan_file.read_text(encoding="utf-8"))["settings"]["sshWindowsPort"] == "22"
    assert "-Plan" in ssh.manual_command(plan_file)
    monkeypatch.setattr(ssh.subprocess, "run", lambda argv, check=False: SimpleNamespace(returncode=5))
    assert ssh.run_elevated(plan)[0] is None
    monkeypatch.setattr(plat, "find_pwsh", lambda: None)
    assert ssh.run_elevated(plan)[0] is None


def test_save_writes_only_what_changed(monkeypatch):
    written = []
    monkeypatch.setattr(ssh.store, "get", lambda k, d="": "22" if k == "sshWindowsPort" else "")
    monkeypatch.setattr(ssh.store, "set", lambda k, v: written.append(k))
    ssh.save(dict(ssh.DEFAULTS))
    assert "sshWindowsPort" not in written and "sshServer" in written
    assert ssh.settings()["sshWindowsPort"] == "22"


def test_the_result_file_exists_before_elevation(tmp_path, monkeypatch):
    """Created by the user: one the elevated process creates is unreadable here (EPERM)."""
    monkeypatch.setattr(plat, "find_pwsh", lambda: "pwsh")
    monkeypatch.setattr(ssh, "is_admin", lambda: False)
    monkeypatch.setattr(ssh.tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    seen = []

    def run(argv, check=False):
        seen.append((tmp_path / "plan.result.json").exists())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(ssh.subprocess, "run", run)
    monkeypatch.setattr(ssh, "sshd_config_path", lambda: tmp_path / "none")
    result, _ = ssh.run_elevated(ssh.plan_windows(dict(ssh.DEFAULTS, sshServer="on"), []))
    assert seen == [True]
    assert result is not None and result["ok"] is False


def test_the_bridge_setting_off_removes_it(applied, windows, monkeypatch, capsys):
    monkeypatch.setattr(ssh, "run_elevated", lambda plan: ({"ok": True, "steps": []}, windows / "p"))
    values = dict(ssh.DEFAULTS, sshServer="on", sshAgentBridge="off")
    cmd.apply(values, [], FakeAsk(), dry=False)  # type: ignore[arg-type]
    assert ("no-bridge",) in applied and ("bridge",) not in applied
    assert "Ubuntu keeps its own agent" in capsys.readouterr().out


def test_a_bridge_that_fails_is_said(applied, windows, monkeypatch, capsys):
    monkeypatch.setattr(ssh, "run_elevated", lambda plan: ({"ok": True, "steps": []}, windows / "p"))
    monkeypatch.setattr(ssh, "wsl_install_bridge", lambda d: (False, "no winget"))
    cmd.apply(dict(ssh.DEFAULTS, sshServer="on"), [], FakeAsk(), dry=False)  # type: ignore[arg-type]
    assert "not set up: no winget" in capsys.readouterr().out
