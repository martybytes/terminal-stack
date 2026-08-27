"""The failure paths: unreachable services, broken subprocesses, degraded state.

These are the branches that only run when something is already wrong, which is
precisely when the doctor has to be right. They are also the ones a live run on a
healthy machine never reaches, so without injection they would ship untested.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_doctor import as_platform, statuses  # noqa: E402
from tstack import checks, paths, store  # noqa: E402
from tstack import platform as plat  # noqa: E402
from tstack.checks import Report  # noqa: E402
from tstack.commands import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    store.clear_cache()
    for fn in (plat.kind, plat.is_wsl, plat.windows_username):
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()
    monkeypatch.setattr(store, "chezmoi_data", lambda: {})
    monkeypatch.setattr(store, "mirror", lambda: {})
    monkeypatch.setattr(store, "mirror_path", lambda: None)
    yield
    store.clear_cache()


# ------------------------------------------------------------- subprocesses


def test_a_missing_binary_is_not_an_exception(monkeypatch):
    """_run returns None rather than raising. A doctor that dies because one
    probe's binary is absent reports nothing about the other twenty checks."""

    def boom(*a, **k):
        raise FileNotFoundError("no such binary")

    monkeypatch.setattr(subprocess, "run", boom)
    assert doctor._run(["definitely-not-a-command"]) is None


def test_a_timeout_is_not_an_exception(monkeypatch):
    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="x", timeout=1)

    monkeypatch.setattr(subprocess, "run", slow)
    assert doctor._run(["x"]) is None


def _with_agentmemory_plugin(monkeypatch, tmp_path):
    """A machine that HAS the plugin installed.

    The wiring check now asks that question before believing `--check`, because
    every host gates on its plugin cache and returns 0 when there is none -- so a
    machine with no plugin at all used to report `ok wiring intact` while
    capturing nothing. These two tests are about what happens once the plugin IS
    there, so they have to say so; without it they passed on a developer's machine
    and failed in a clean container, which is the trap the parity harness exists
    to catch.
    """
    from tstack.commands import agents

    home = tmp_path / "agent-home"
    (home / ".claude/plugins/cache/agentmemory/agentmemory").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(agents, "user_root", lambda: home)
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))


def test_a_broken_agentmemory_probe_is_silent_not_fatal(monkeypatch, tmp_path):
    """When the probe itself cannot run, say nothing rather than claim the wiring
    is broken -- an unrunnable check is not evidence."""
    as_platform(monkeypatch, plat.LINUX)
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "ts-agentmemory.sh").write_text("", encoding="utf-8")
    _with_agentmemory_plugin(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "get", lambda k, d=None: "on")
    monkeypatch.setattr(doctor, "_run", lambda *a, **k: None)
    report = Report()
    doctor.check_agentmemory_wiring(report, tmp_path)
    assert report.results == []


def test_agentmemory_wiring_intact_is_ok(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.LINUX)
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "ts-agentmemory.sh").write_text("", encoding="utf-8")
    _with_agentmemory_plugin(monkeypatch, tmp_path)
    monkeypatch.setattr(store, "get", lambda k, d=None: "on")
    monkeypatch.setattr(
        doctor, "_run", lambda argv, **k: subprocess.CompletedProcess(argv, 0, "", "")
    )
    report = Report()
    doctor.check_agentmemory_wiring(report, tmp_path)
    assert statuses(report)["agentmemory-wiring"] == checks.OK


# ---------------------------------------------------------------- http probe


def test_answering_is_the_test_not_a_2xx(monkeypatch):
    """AgentMemory returns 404 on / and 401 on /agentmemory/health, so a
    `curl -fsS`-shaped check reported the service down while it was up. Only a
    refused connection counts as down."""
    import urllib.request

    def http_error(*a, **k):
        raise urllib.error.HTTPError("http://x", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(urllib.request, "urlopen", http_error)
    assert doctor._probe_http("http://127.0.0.1:1/health") is True

    def refused(*a, **k):
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", refused)
    assert doctor._probe_http("http://127.0.0.1:1/health") is False


def test_a_reachable_service_is_reachable(monkeypatch):
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: object())
    assert doctor._probe_http("http://127.0.0.1:1/health") is True


def test_the_daemon_token_is_read_from_the_secrets_file(monkeypatch, tmp_path):
    home = tmp_path / "h"
    state = home / ".claude" / "tts" / "state"
    state.mkdir(parents=True)
    (state / "secrets.json").write_text('{"token": "abc123"}', encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    assert doctor._daemon_token() == "abc123"


def test_a_missing_token_is_empty_not_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "nowhere"))
    assert doctor._daemon_token() == ""


def test_an_unparseable_token_file_does_not_raise(monkeypatch, tmp_path):
    home = tmp_path / "h"
    state = home / ".claude" / "tts" / "state"
    state.mkdir(parents=True)
    (state / "secrets.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    assert doctor._daemon_token() == ""


def test_the_daemon_is_reachable_on_loopback(monkeypatch):
    as_platform(monkeypatch, plat.LINUX)
    monkeypatch.setattr(doctor, "_probe_http", lambda url, **k: "127.0.0.1" in url)
    assert doctor._daemon_reachable(8890) is True


def test_the_daemon_is_reachable_via_the_gateway_under_nat(monkeypatch):
    """Mirrored networking answers on loopback; NAT does not, and only the
    gateway does. Reporting the daemon dead there is the bug this ladder fixes."""
    as_platform(monkeypatch, plat.WSL)
    monkeypatch.setattr(doctor, "_daemon_hosts", lambda port: ["127.0.0.1", "172.20.0.1"])
    monkeypatch.setattr(doctor, "_daemon_token", lambda: "tok")
    seen: list[str] = []

    def probe(url, **kwargs):
        seen.append(url)
        return "172.20.0.1" in url

    monkeypatch.setattr(doctor, "_probe_http", probe)
    assert doctor._daemon_reachable(8890) is True
    assert len(seen) == 2, "loopback must be tried first"


# ------------------------------------------------------------ degraded state


def test_a_clone_that_is_not_ours_is_reported(monkeypatch, tmp_path):
    clone = tmp_path / "someone-elses"
    (clone / ".git").mkdir(parents=True)
    monkeypatch.setattr(paths, "resolve_source_dir", lambda *a, **k: clone)
    monkeypatch.setattr(paths, "is_stack_clone", lambda p: False)
    report = Report()
    assert doctor.check_clone(report, None) == clone
    assert statuses(report)["clone"] == checks.FAIL
    assert "not a terminal-stack clone" in report.results[0].message


def test_clone_resolution_warnings_become_notes(monkeypatch, tmp_path):
    """A stale pin degrades rather than dead-ending, and the user is told."""
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)

    def resolve(*args, warn=None, **kwargs):
        if warn:
            warn("stale TERMINAL_STACK_DIR: no clone at /gone")
        return clone

    monkeypatch.setattr(paths, "resolve_source_dir", resolve)
    monkeypatch.setattr(paths, "is_stack_clone", lambda p: True)
    as_platform(monkeypatch, plat.WINDOWS)
    report = Report()
    doctor.check_clone(report, None)
    assert statuses(report)["clone-resolution"] == checks.NOTE


def test_chezmoi_pointing_elsewhere_is_a_failure_on_posix(monkeypatch, tmp_path):
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setattr(paths, "resolve_source_dir", lambda *a, **k: clone)
    monkeypatch.setattr(paths, "is_stack_clone", lambda p: True)
    monkeypatch.setattr(
        doctor, "_run", lambda argv, **k: subprocess.CompletedProcess(argv, 0, str(other), "")
    )
    as_platform(monkeypatch, plat.LINUX)
    report = Report()
    doctor.check_clone(report, "chezmoi")
    assert statuses(report)["chezmoi-sourcedir"] == checks.FAIL


def test_no_canonical_location_means_no_advisory(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "canonical_clone_dir", lambda: None)
    report = Report()
    doctor.check_clone_location(report, tmp_path)
    assert report.results == []


def test_a_clone_already_canonical_produces_no_advisory(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "canonical_clone_dir", lambda: tmp_path)
    report = Report()
    doctor.check_clone_location(report, tmp_path)
    assert report.results == []


def test_notes_render_distinctly_from_problems():
    report = Report()
    report.note("n", "worth knowing")
    report.fail("f", "worth fixing")
    lines = doctor.render(report, quiet=False)
    assert any(line.strip().startswith("note:") for line in lines)
    assert any(line.strip().startswith("!!") for line in lines)
