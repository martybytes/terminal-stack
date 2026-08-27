"""In-process tests for `tstack doctor` and the settings store it reads.

Every check is exercised with injected state rather than whatever this machine
happens to look like. That matters more here than anywhere else in the port: a
doctor that only works on the developer's box is the exact failure it exists to
catch, and two of the four target platforms cannot be run from here at all.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import checks, paths, store  # noqa: E402
from tstack import platform as plat  # noqa: E402
from tstack.checks import Report  # noqa: E402
from tstack.commands import doctor  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """No test may read the developer's real store, clone or daemon."""
    store.clear_cache()
    for fn in (plat.kind, plat.is_wsl, plat.windows_username):
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()
    monkeypatch.setattr(store, "chezmoi_data", lambda: {})
    monkeypatch.setattr(store, "mirror", lambda: {})
    monkeypatch.setattr(store, "mirror_path", lambda: None)
    monkeypatch.setattr(doctor, "_probe_http", lambda *a, **k: False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir(parents=True, exist_ok=True)
    yield
    store.clear_cache()


def as_platform(monkeypatch, kind: str) -> None:
    monkeypatch.setattr(plat, "kind", lambda: kind)


def statuses(report: Report) -> dict[str, str]:
    return {r.check: r.status for r in report.results}


# ------------------------------------------------------------------ the store


def test_normalise_compares_meaning_not_spelling():
    """chezmoi [data] holds on/off strings, the mirror holds JSON booleans. A
    divergence check that compares raw text reports a difference on every
    machine, so it gets ignored, so it may as well not exist."""
    for truthy in ("on", "true", "TRUE", "yes", "1", True):
        assert store.normalise(truthy) == "true"
    for falsey in ("off", "false", "no", "0", "", None, False):
        assert store.normalise(falsey) == "false"
    assert store.normalise("kokoro") == "kokoro"


def test_missing_mirror_key_is_not_a_disagreement(monkeypatch):
    """A mirror written by an older version simply lacks the key. Reporting that
    as drift would make the check cry wolf on every machine that has not synced."""
    monkeypatch.setattr(store, "chezmoi_data", lambda: {"themeMode": "dark"})
    monkeypatch.setattr(store, "mirror", lambda: {"leaderChord": "ctrl-space"})
    assert store.mirror_value("themeMode") == store.MISSING
    assert store.divergences() == []


def test_real_disagreement_is_reported(monkeypatch):
    monkeypatch.setattr(store, "chezmoi_data", lambda: {"weztermMux": "on"})
    monkeypatch.setattr(store, "mirror", lambda: {"weztermMux": False})
    assert store.divergences() == [("weztermMux", "on", "false")]


def test_get_prefers_chezmoi_then_mirror_then_default(monkeypatch):
    monkeypatch.setattr(store, "chezmoi_data", lambda: {"themeMode": "light"})
    monkeypatch.setattr(store, "mirror", lambda: {"themeMode": "dark", "tmuxPrefix": "ctrl-a"})
    assert store.get("themeMode") == "light"
    assert store.get("tmuxPrefix") == "ctrl-a"
    assert store.get("weztermMux") == "off"  # documented default


# ----------------------------------------------------------------- the checks


def test_a_pinned_chezmoi_that_does_not_exist_is_a_failure(monkeypatch, tmp_path):
    """The shell reported `ok  chezmoi: <path>` for a path with no binary,
    because ts_chezmoi_bin returned $TERMINAL_STACK_CHEZMOI unchecked."""
    monkeypatch.setattr(plat, "find_chezmoi", lambda: str(tmp_path / "nope"))
    report = Report()
    assert doctor.check_chezmoi(report) is None
    assert statuses(report)["chezmoi"] == checks.FAIL
    assert "does not exist" in report.results[0].message


def test_a_real_chezmoi_is_ok(monkeypatch, tmp_path):
    binary = tmp_path / "chezmoi"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(plat, "find_chezmoi", lambda: str(binary))
    report = Report()
    assert doctor.check_chezmoi(report) == str(binary)
    assert statuses(report)["chezmoi"] == checks.OK


def test_missing_chezmoi_is_a_note_on_windows_and_a_failure_on_posix(monkeypatch):
    """A Windows-standalone install has no chezmoi and is not broken."""
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)

    as_platform(monkeypatch, plat.WINDOWS)
    win = Report()
    doctor.check_chezmoi(win)
    assert statuses(win)["chezmoi"] == checks.NOTE

    as_platform(monkeypatch, plat.LINUX)
    posix = Report()
    doctor.check_chezmoi(posix)
    assert statuses(posix)["chezmoi"] == checks.FAIL


def test_no_clone_is_reported_once_with_an_action(monkeypatch):
    monkeypatch.setattr(
        paths,
        "resolve_source_dir",
        lambda *a, **k: (_ for _ in ()).throw(paths.CloneNotFound("no terminal-stack clone found")),
    )
    report = Report()
    assert doctor.check_clone(report, None) is None
    assert statuses(report)["clone"] == checks.FAIL
    assert report.results[0].hint


def test_the_chezmoi_sourcedir_check_is_skipped_on_windows(monkeypatch, tmp_path):
    """chezmoi is not the apply path on Windows; sync-windows.ps1 is. Reporting
    its unrelated default as a failure is a false positive on every box."""
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    monkeypatch.setattr(paths, "resolve_source_dir", lambda *a, **k: clone)
    monkeypatch.setattr(paths, "is_stack_clone", lambda p: True)
    called: list[list[str]] = []
    monkeypatch.setattr(doctor, "_run", lambda argv, **k: called.append(argv))

    as_platform(monkeypatch, plat.WINDOWS)
    doctor.check_clone(Report(), "chezmoi")
    assert not called, "chezmoi source-path must not be consulted on Windows"


def test_memory_backend_drift_is_reported_with_the_fix(monkeypatch):
    monkeypatch.setattr(
        store,
        "get",
        lambda k, d=None: {"memoryBackend": "headroom", "agentmemoryEnabled": "on"}.get(k, d or ""),
    )
    report = Report()
    doctor.check_memory_backend(report)
    assert statuses(report)["memory-backend"] == checks.FAIL
    assert "tstack config memory headroom" in report.results[0].hint


def test_memory_backend_agreement_is_ok(monkeypatch):
    monkeypatch.setattr(
        store,
        "get",
        lambda k, d=None: {"memoryBackend": "agentmemory", "agentmemoryEnabled": "on"}.get(
            k, d or ""
        ),
    )
    report = Report()
    doctor.check_memory_backend(report)
    assert statuses(report)["memory-backend"] == checks.OK


def test_tts_checks_are_silent_when_the_feature_is_off(monkeypatch):
    monkeypatch.setattr(
        store, "get", lambda k, d=None: "false" if k == "ccTtsEnabled" else (d or "")
    )
    report = Report()
    doctor.check_tts(report)
    assert report.results == []


def test_an_enabled_but_dead_daemon_is_a_failure(monkeypatch):
    monkeypatch.setattr(
        store,
        "get",
        lambda k, d=None: {"ccTtsEnabled": "true", "ccTtsDaemon": "on", "ccTtsEngine": "edge"}.get(
            k, d or ""
        ),
    )
    monkeypatch.setattr(doctor, "_daemon_reachable", lambda port: False)
    report = Report()
    doctor.check_tts(report)
    assert statuses(report)["tts-daemon"] == checks.FAIL


def test_the_daemon_probe_walks_the_wsl_host_ladder(monkeypatch):
    """On WSL the daemon is a WINDOWS process and 127.0.0.1 is the VM's loopback.
    Probing only loopback reported a healthy daemon as dead."""
    as_platform(monkeypatch, plat.WSL)
    monkeypatch.setattr(
        doctor,
        "_run",
        lambda argv, **k: subprocess.CompletedProcess(
            argv, 0, "default via 172.20.0.1 dev eth0\n", ""
        ),
    )
    hosts = doctor._daemon_hosts(8890)
    assert hosts[0] == "127.0.0.1"
    assert "172.20.0.1" in hosts, hosts


def test_the_daemon_probe_is_loopback_only_off_wsl(monkeypatch):
    as_platform(monkeypatch, plat.LINUX)
    assert doctor._daemon_hosts(8890) == ["127.0.0.1"]


def test_a_local_override_forcing_enabled_false_is_a_failure(monkeypatch, tmp_path):
    """The untracked override beats the rendered config, so `cctts on` reports
    success while every hook stays silent."""
    override = tmp_path / "local.json"
    override.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    monkeypatch.setattr(
        store,
        "get",
        lambda k, d=None: {"ccTtsEnabled": "true", "ccTtsDaemon": "off", "ccTtsEngine": "edge"}.get(
            k, d or ""
        ),
    )
    monkeypatch.setattr(doctor, "_tts_local_json", lambda: override)
    report = Report()
    doctor.check_tts(report)
    assert statuses(report)["tts-local-override"] == checks.FAIL


def test_smb_never_touches_a_mountpoint(monkeypatch, tmp_path):
    """A dead FUSE mount blocks forever and takes the process with it. Liveness
    comes from the record and the pid, never from stat/ls/glob on the mount."""
    source = (ROOT / "tstack" / "commands" / "doctor.py").read_text(encoding="utf-8")
    seg = source[source.index("def check_smb") : source.index("def check_clone_location")]
    for forbidden in (".is_mount(", "os.statvfs", "listdir(mount"):
        assert forbidden not in seg, f"check_smb must not call {forbidden}"


def test_smb_reports_a_stale_mount_record(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.LINUX)
    state = tmp_path / "state" / "terminal-stack" / "smb"
    state.mkdir(parents=True)
    (state / "media.mnt").write_text("pid 999999999\nmountpoint /mnt/x\n", encoding="utf-8")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    report = Report()
    doctor.check_smb(report)
    assert statuses(report).get("smb-stale-mounts") == checks.FAIL


def test_smb_is_silent_when_unused(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.LINUX)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    report = Report()
    doctor.check_smb(report)
    assert report.results == []


def test_a_legacy_clone_location_is_a_note_not_a_failure(monkeypatch, tmp_path):
    """A working install at a legacy path still works; failing it would train
    people to ignore the exit code."""
    legacy = tmp_path / "somewhere" / "terminal-stack"
    legacy.mkdir(parents=True)
    monkeypatch.setattr(paths, "canonical_clone_dir", lambda: tmp_path / "canon")
    report = Report()
    doctor.check_clone_location(report, legacy)
    assert statuses(report)["clone-location"] == checks.NOTE


def test_a_dev_clone_location_says_it_is_deliberate(monkeypatch, tmp_path):
    dev = tmp_path / "src" / "github.com" / "o" / "terminal-stack"
    dev.mkdir(parents=True)
    monkeypatch.setattr(paths, "canonical_clone_dir", lambda: tmp_path / "canon")
    report = Report()
    doctor.check_clone_location(report, dev)
    assert "deliberate" in report.results[0].message


# --------------------------------------------------------------- the reporting


def test_quiet_hides_ok_lines_but_never_problems():
    report = Report()
    report.ok("a", "fine")
    report.fail("b", "broken", "fix it")
    loud = doctor.render(report, quiet=False)
    quiet = doctor.render(report, quiet=True)
    assert any("fine" in line for line in loud)
    assert not any("fine" in line for line in quiet)
    assert any("broken" in line for line in quiet)


def test_a_healthy_report_says_so_and_a_broken_one_counts():
    healthy = Report()
    healthy.ok("a", "fine")
    healthy.note("b", "advisory")
    assert healthy.issues == 0
    assert doctor.PASSED in doctor.render(healthy, quiet=False)

    broken = Report()
    broken.fail("a", "one")
    broken.fail("b", "two")
    assert broken.issues == 2
    assert "2 issue(s) found" in doctor.render(broken, quiet=False)[-1]


def test_a_note_never_counts_as_an_issue():
    report = Report()
    for _ in range(5):
        report.note("n", "just so you know")
    assert report.issues == 0


def test_the_hint_is_rendered_with_the_problem():
    report = Report()
    report.fail("x", "something broke", "run: tstack update")
    assert "run: tstack update" in report.results[0].render()


def test_json_is_a_read_model_not_prose():
    report = Report()
    report.ok("a", "fine")
    report.fail("b", "broken", "fix it")
    payload = report.as_dict()
    assert payload["issues"] == 1
    assert payload["checks"][0] == {"check": "a", "status": "ok", "message": "fine"}
    assert payload["checks"][1]["hint"] == "fix it"
    json.dumps(payload)  # must be serialisable


def test_help_and_exit_codes(capsys):
    with pytest.raises(SystemExit) as excinfo:
        doctor.main(["--help"])
    assert excinfo.value.code == 0
    assert "tstack doctor" in capsys.readouterr().out
