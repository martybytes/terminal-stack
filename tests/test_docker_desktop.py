"""Docker Desktop's stale WSL integration: detection and `tstack services repair`.

No Docker, no WSL: every side effect goes through docker_desktop.Host, which a
scripted fake replaces. What matters here is the ORDER of the recycle (stop,
then `wsl --shutdown`, then start), that a stopped distro is never called stale,
that nobody at the terminal declines, and that the containers running before are
the ones started after.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tstack import docker_desktop as dd
from tstack import engine
from tstack import platform as plat
from tstack.commands import services

SOCK_TEST = ["-u", "root", "-e", "test", "-S", dd.SHARED_SOCK]


def done(code: int = 0, out: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, out, "")


class FakeHost(dd.Host):
    """A machine: Docker Desktop with Ubuntu integrated, scripted per test."""

    def __init__(self, tmp: Path) -> None:
        self.calls: list[list[str]] = []
        self.clock = 0.0
        self.engine = True
        self.backend = True
        self.running = ["Ubuntu", "docker-desktop"]
        self.sock_ok = False  # backend.sock published in Ubuntu
        self.sock_after_recycle = True
        self.containers = ["headroom", "playwright"]
        self.restart_policy = {"headroom": "unless-stopped", "playwright": "no"}
        self.started_after: list[str] = ["headroom"]  # come back by restart policy
        self.disk = {"me": "HOST\\u", "dirs": []}
        self.settings = tmp / "settings-store.json"
        self.settings.write_text(
            json.dumps(
                {"IntegratedWslDistros": ["Ubuntu"], "EnableIntegrationWithDefaultWslDistro": True}
            ),
            encoding="utf-8",
        )

    # -- seams --

    def sleep(self, seconds: float) -> None:
        self.clock += seconds

    def monotonic(self) -> float:
        return self.clock

    def settings_path(self) -> Path:
        return self.settings

    def backend_running(self) -> bool:
        return self.backend

    def run(self, argv, timeout=60):
        self.calls.append(list(argv))
        a = list(argv)
        if a[:1] == ["wsl.exe"]:
            return self._wsl(a[1:])
        if a[:1] == ["docker"]:
            return self._docker(a[1:])
        if "-Command" in a:  # the disk ownership snippet
            return done(0, json.dumps(self.disk))
        return done(1)

    def _wsl(self, a):
        if a[:2] == ["--list", "--quiet"]:
            if "--running" in a:
                return done(0, "\n".join(self.running))
            return done(0, "Ubuntu\ndocker-desktop\n")
        if a == ["--shutdown"]:
            self.running = []
            return done(0)
        if a[0] == "-d":
            distro = a[1]
            if distro not in self.running:
                self.running.append(distro)
            rest = a[2:]
            if rest == ["-e", "true"]:
                return done(0)
            if rest[-2:] == ["-S", dd.SHARED_SOCK] or rest[-2:] == ["-S", dd.DOCKER_SOCK]:
                return done(0 if self.sock_ok else 1)
            if rest[:3] == ["-e", "docker", "version"]:
                return done(0, "29.9.2") if self.sock_ok else done(1)
            if rest[:3] == ["-e", "docker", "run"]:
                return done(0, "Hello from Docker!")
        return done(1)

    def _docker(self, a):
        if a[:2] == ["desktop", "stop"]:
            self.engine = False
            self.backend = False
            return done(0)
        if a[:2] == ["desktop", "start"]:
            self.engine = True
            self.backend = True
            if self.running == []:  # a fresh VM
                self.sock_ok = self.sock_after_recycle
            self.containers = list(self.started_after)
            return done(0)
        if a[0] == "info":
            return done(0, "29.9.2") if self.engine else done(1)
        if a[0] == "version":
            return done(0, "Docker Desktop 4.99.0") if self.engine else done(1)
        if a[:2] == ["ps", "-q"]:
            return done(0, "\n".join(f"id-{n}" for n in self.containers))
        if a[:2] == ["ps", "--format"]:
            return done(0, "\n".join(self.containers))
        if a[0] == "inspect":
            rows = [
                {
                    "Name": "/" + i[3:],
                    "HostConfig": {"RestartPolicy": {"Name": self.restart_policy[i[3:]]}},
                }
                for i in a[1:]
            ]
            return done(0, json.dumps(rows))
        if a[0] == "start":
            self.containers.append(a[1])
            return done(0)
        return done(1)

    # -- what happened --

    def verbs(self) -> list[str]:
        out = []
        for c in self.calls:
            if c[:3] == ["docker", "desktop", "stop"]:
                out.append("stop")
            elif c == ["wsl.exe", "--shutdown"]:
                out.append("shutdown")
            elif c[:3] == ["docker", "desktop", "start"]:
                out.append("start")
        return out


@pytest.fixture
def host(tmp_path, monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setattr(dd.shutil, "which", lambda name: f"C:/bin/{name}.exe")
    return FakeHost(tmp_path)


def repair(host, answers=(), **kw):
    said: list[str] = []
    replies = iter(answers)
    code = dd.Repair(say=said.append, ask=lambda p: next(replies, None), host=host, **kw).run()
    return code, "\n".join(said)


# ------------------------------------------------------------------ detection


def test_the_default_distro_is_integrated_once_and_docker_desktop_never(host):
    assert dd.integrated_distros(host) == ["Ubuntu"]


def test_a_running_distro_without_the_socket_is_stale(host):
    assert dd.integration_status(host) == (dd.STALE, ["Ubuntu"])


def test_a_running_distro_with_the_socket_is_healthy(host):
    host.sock_ok = True
    assert dd.integration_status(host) == (dd.HEALTHY, ["Ubuntu"])


def test_a_stopped_distro_is_unknown_and_is_never_booted(host):
    """Docker publishes only while an integrated distro runs: empty is normal then."""
    host.running = ["docker-desktop"]
    assert dd.integration_status(host)[0] == dd.UNKNOWN
    assert not any(c[:2] == ["wsl.exe", "-d"] for c in host.calls)


def test_no_docker_desktop_running_is_not_applicable(host):
    host.backend = False
    assert dd.integration_status(host)[0] == dd.NOT_APPLICABLE


def test_wait_status_gives_a_fresh_backend_its_minute(host):
    def publish(seconds):
        host.clock += seconds
        if host.clock >= 20:
            host.sock_ok = True

    host.sleep = publish
    assert dd.wait_status(host, 75)[0] == dd.HEALTHY


def test_wsl_side_reads_the_socket_directly(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    monkeypatch.setattr(dd.Path, "is_dir", lambda self: True)
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu")
    h = FakeHost(tmp_path)
    h.is_socket = lambda path: False
    assert dd.integration_status(h) == (dd.STALE, ["Ubuntu"])
    assert h.calls == []


# --------------------------------------------------------------------- repair


def test_repair_stops_then_shuts_wsl_down_then_starts(host):
    code, said = repair(host, ["y", "y"])
    assert code == 0, said
    assert host.verbs() == ["stop", "shutdown", "start"]
    assert "hello-world works" in said


def test_repair_restarts_only_the_containers_that_were_running(host):
    code, _ = repair(host, ["y", "y"])
    assert code == 0
    starts = [c for c in host.calls if c[:2] == ["docker", "start"]]
    assert starts == [["docker", "start", "playwright"]]


def test_nobody_at_the_terminal_changes_nothing(host):
    code, said = repair(host, [])
    assert code == 0
    assert host.verbs() == []
    assert "nothing changed" in said


def test_integration_still_down_recycles_once_more_then_fails(host):
    host.sock_after_recycle = False
    code, said = repair(host, ["y", "y"])
    assert code == 1
    assert host.verbs() == ["stop", "shutdown", "start"] * 2
    assert "factory defaults" in said  # the warning, never the advice


def test_a_disk_the_installer_reowned_prints_the_icacls_and_never_elevates(host):
    host.disk = {"me": "HOST\\u", "dirs": "E:\\DockerWSL\\main"}  # pwsh unwraps 1-arrays
    _, said = repair(host, ["y", "", "y"], hello_world=False)
    assert 'icacls "E:\\DockerWSL\\main" /setowner "HOST\\u" /T /C' in said
    assert not any("icacls" in c[0] for c in host.calls)


def test_repair_refuses_inside_wsl(host, monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    code, said = repair(host, ["y"])
    assert code == 1 and "PowerShell" in said
    assert host.calls == []


def test_repair_never_suggests_destroying_data():
    import inspect

    src = inspect.getsource(dd)
    assert "--unregister" not in src.replace("`wsl --unregister docker-desktop`", "")


# ------------------------------------------------------------ services wiring


def test_services_repair_needs_no_clone(monkeypatch):
    seen = {}
    monkeypatch.setattr(services, "cmd_repair", lambda args: seen.setdefault("args", args) and 0)
    monkeypatch.setattr(
        services.paths, "resolve_source_dir", lambda: pytest.fail("repair must not need a clone")
    )
    services.main(["repair", "--update", "--distro", "Debian", "-y", "--no-hello-world"])
    args = seen["args"]
    assert args.update and args.assume_yes and not args.hello_world and args.distros == ["Debian"]


def test_services_repair_takes_no_stack():
    assert services.main(["repair", "headroom"]) == 2


@pytest.fixture
def offer_env(monkeypatch):
    monkeypatch.setattr(engine, "os_name", lambda: engine.WINDOWS)
    ran = []

    class FakeRepair:
        def __init__(self, **kw):
            ran.append(kw)

        def run(self):
            return 0

    monkeypatch.setattr(dd, "Repair", FakeRepair)
    return ran


def test_the_wizard_offer_defaults_to_no(offer_env, monkeypatch):
    monkeypatch.setattr(dd, "wait_status", lambda host, s: (dd.STALE, ["Ubuntu"]))
    said: list[str] = []
    services.offer_integration_repair(lambda p: "", said.append)
    assert offer_env == []
    assert any("tstack services repair" in s for s in said)


def test_the_wizard_offer_repairs_on_yes(offer_env, monkeypatch):
    monkeypatch.setattr(dd, "wait_status", lambda host, s: (dd.STALE, ["Ubuntu"]))
    services.offer_integration_repair(lambda p: "y", lambda s: None)
    assert len(offer_env) == 1


def test_the_wizard_offer_is_silent_when_healthy(offer_env, monkeypatch):
    monkeypatch.setattr(dd, "wait_status", lambda host, s: (dd.HEALTHY, ["Ubuntu"]))
    said: list[str] = []
    services.offer_integration_repair(lambda p: pytest.fail("must not ask"), said.append)
    assert said == [] and offer_env == []
