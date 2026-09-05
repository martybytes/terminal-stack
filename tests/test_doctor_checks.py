"""The rest of the doctor checks, plus collect() and the CLI surface.

Split from test_doctor.py only for size. Same discipline: every check gets
injected state, so a branch that only exists on macOS or on a Windows-standalone
install is still exercised from here - which is the point, since two of the four
targets cannot be run on this machine.
"""

from __future__ import annotations

import json
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
def _isolate(monkeypatch, tmp_path):
    store.clear_cache()
    for fn in (plat.kind, plat.is_wsl, plat.windows_username):
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()
    monkeypatch.setattr(store, "chezmoi_data", lambda: {})
    monkeypatch.setattr(store, "mirror", lambda: {})
    monkeypatch.setattr(store, "mirror_path", lambda: None)
    monkeypatch.setattr(doctor, "_probe_http", lambda *a, **k: False)
    # check_git_hooks reads the AMBIENT working directory, which is a dev clone
    # whenever the suite runs from one. Left live it makes every report in this
    # module depend on where pytest was invoked from -- exactly what the module
    # docstring says it does not do. Reachability gets its own test below.
    monkeypatch.setattr(paths, "dev_clone_at", lambda *a, **k: None)
    yield
    store.clear_cache()


# ------------------------------------------------- shell integration and PATH


def test_shell_integration_wants_the_block_on_posix(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.LINUX)
    home = tmp_path / "h"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    missing = Report()
    doctor.check_shell_integration(missing)
    assert statuses(missing)["zshrc"] == checks.FAIL

    (home / ".zshrc").write_text("nothing of ours here\n", encoding="utf-8")
    stale = Report()
    doctor.check_shell_integration(stale)
    assert statuses(stale)["zshrc"] == checks.FAIL
    assert statuses(stale)["zshrc-doc"] == checks.FAIL

    (home / ".zshrc").write_text("# terminal-stack-zsh-start\n# doc-start\n", encoding="utf-8")
    good = Report()
    doctor.check_shell_integration(good)
    assert statuses(good) == {"zshrc": checks.OK, "zshrc-doc": checks.OK}


def test_shell_integration_wants_the_block_on_windows(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.WINDOWS)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "nowhere"))
    monkeypatch.delenv("TS_PROFILE_PATH", raising=False)

    absent = Report()
    doctor.check_shell_integration(absent)
    assert statuses(absent)["pwsh-profile"] == checks.FAIL

    profile = tmp_path / "Microsoft.PowerShell_profile.ps1"
    profile.write_text("# ---- terminal-stack-update-start ----\n", encoding="utf-8")
    monkeypatch.setenv("TS_PROFILE_PATH", str(profile))
    good = Report()
    doctor.check_shell_integration(good)
    assert statuses(good)["pwsh-profile"] == checks.OK


def test_windows_does_not_demand_zsh_on_path(monkeypatch):
    as_platform(monkeypatch, plat.WINDOWS)
    report = Report()
    doctor.check_tools_on_path(report)
    assert "path-zsh" not in statuses(report)

    as_platform(monkeypatch, plat.LINUX)
    posix = Report()
    doctor.check_tools_on_path(posix)
    assert "path-zsh" in statuses(posix)


# ------------------------------------------------------------- store checks


def test_config_store_divergence_is_reported_with_both_values(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.WSL)
    mirror = tmp_path / "config.json"
    mirror.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(store, "mirror_path", lambda: mirror)
    monkeypatch.setattr(store, "chezmoi_data", lambda: {"weztermMux": "on"})
    monkeypatch.setattr(store, "divergences", lambda: [("weztermMux", "on", "false")])
    report = Report()
    doctor.check_config_stores(report)
    assert statuses(report)["config-divergence"] == checks.FAIL
    message = next(r.message for r in report.results if r.check == "config-divergence")
    assert "'on'" in message and "'false'" in message


def test_a_missing_mirror_is_a_failure_on_windows_and_silent_on_wsl(monkeypatch):
    monkeypatch.setattr(store, "mirror_path", lambda: None)

    as_platform(monkeypatch, plat.WINDOWS)
    win = Report()
    doctor.check_config_stores(win)
    assert statuses(win)["config-mirror"] == checks.FAIL

    as_platform(monkeypatch, plat.WSL)
    wsl = Report()
    doctor.check_config_stores(wsl)
    assert wsl.results == []


def test_config_stores_are_not_checked_on_native_posix(monkeypatch):
    as_platform(monkeypatch, plat.LINUX)
    report = Report()
    doctor.check_config_stores(report)
    assert report.results == []


# --------------------------------------------------------------- clone notes


def test_other_clones_are_a_note_listing_them(monkeypatch, tmp_path):
    here, there = tmp_path / "a", tmp_path / "b"
    here.mkdir()
    there.mkdir()
    monkeypatch.setattr(
        paths, "clones", lambda: [paths.Clone(here, "origin", ""), paths.Clone(there, "origin", "")]
    )
    report = Report()
    doctor.check_other_clones(report, here)
    assert statuses(report)["other-clones"] == checks.NOTE
    assert str(there) in report.results[0].message


def test_a_single_clone_produces_no_note(monkeypatch, tmp_path):
    here = tmp_path / "a"
    here.mkdir()
    monkeypatch.setattr(paths, "clones", lambda: [paths.Clone(here, "origin", "")])
    report = Report()
    doctor.check_other_clones(report, here)
    assert report.results == []


def test_git_hooks_are_only_checked_in_a_dev_clone(tmp_path):
    runtime = tmp_path / "runtime"
    (runtime / ".githooks").mkdir(parents=True)
    report = Report()
    doctor.check_git_hooks(report, runtime)
    assert report.results == [], "a runtime clone never commits, so it needs no hook"


def test_git_hooks_is_reachable_when_the_resolved_clone_is_the_runtime_one(monkeypatch, tmp_path):
    """The check was DEAD, and its other tests could not see it.

    They pass a dev clone straight in, so they exercise the body. collect() can
    only ever pass the RESOLVED clone, and resolve_source_dir() refuses to return
    a dev clone by design -- so on any machine with a runtime clone the check
    returned early and never fired. This pins the reachability rather than the
    body: resolved clone is the runtime one, the developer is standing in a dev
    clone, and the check must still report.
    """
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    dev = tmp_path / "src" / "github.com" / "o" / "terminal-stack"
    (dev / ".githooks").mkdir(parents=True)
    monkeypatch.setattr(paths, "dev_clone_at", lambda *a, **k: dev)
    monkeypatch.setattr(
        doctor, "_run", lambda argv, **k: subprocess.CompletedProcess(argv, 1, "", "")
    )
    report = Report()
    doctor.check_git_hooks(report, runtime)
    assert statuses(report)["git-hooks"] == checks.FAIL
    assert str(dev) in report.results[0].hint, "the hint must name the clone to fix"


def test_git_hooks_missing_in_a_dev_clone_is_a_failure(monkeypatch, tmp_path):
    dev = tmp_path / "src" / "github.com" / "o" / "terminal-stack"
    (dev / ".githooks").mkdir(parents=True)
    monkeypatch.setattr(
        doctor, "_run", lambda argv, **k: subprocess.CompletedProcess(argv, 1, "", "")
    )
    report = Report()
    doctor.check_git_hooks(report, dev)
    assert statuses(report)["git-hooks"] == checks.FAIL
    assert "core.hooksPath" in report.results[0].hint


def test_git_hooks_set_in_a_dev_clone_is_ok(monkeypatch, tmp_path):
    dev = tmp_path / "src" / "github.com" / "o" / "terminal-stack"
    (dev / ".githooks").mkdir(parents=True)
    monkeypatch.setattr(
        doctor, "_run", lambda argv, **k: subprocess.CompletedProcess(argv, 0, ".githooks\n", "")
    )
    report = Report()
    doctor.check_git_hooks(report, dev)
    assert statuses(report)["git-hooks"] == checks.OK


# ------------------------------------------------------------ agentmemory/tts


def test_agentmemory_wiring_is_silent_when_the_backend_is_off(monkeypatch, tmp_path):
    monkeypatch.setattr(store, "get", lambda k, d=None: "off")
    report = Report()
    doctor.check_agentmemory_wiring(report, tmp_path)
    assert report.results == []


def test_agentmemory_wiring_failure_names_the_repair(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.LINUX)
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "ts-agentmemory.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setattr(store, "get", lambda k, d=None: "on")
    monkeypatch.setattr(
        doctor, "_run", lambda argv, **k: subprocess.CompletedProcess(argv, 3, "", "")
    )
    report = Report()
    doctor.check_agentmemory_wiring(report, tmp_path)
    assert statuses(report)["agentmemory-wiring"] == checks.FAIL
    assert "repair" in report.results[0].hint


def test_claude_tts_hooks_missing_is_a_failure(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.WINDOWS)
    home = tmp_path / "h"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text('{"hooks":{}}', encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    report = Report()
    doctor._check_claude_tts_hooks(report)
    assert statuses(report)["tts-hooks"] == checks.FAIL


def test_claude_tts_hooks_present_is_ok(monkeypatch, tmp_path):
    as_platform(monkeypatch, plat.WINDOWS)
    home = tmp_path / "h"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        '{"hooks": "terminal-stack-tts.exe hook stop"}', encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    report = Report()
    doctor._check_claude_tts_hooks(report)
    assert statuses(report)["tts-hooks"] == checks.OK


def test_the_tts_port_falls_back_when_the_config_is_unreadable(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert doctor._tts_port() == 8890
    cfg = tmp_path / ".claude" / "tts"
    cfg.mkdir(parents=True)
    (cfg / "config.json").write_text('{"daemon": {"port": 9999}}', encoding="utf-8")
    assert doctor._tts_port() == 9999
    (cfg / "config.json").write_text("not json", encoding="utf-8")
    assert doctor._tts_port() == 8890


# ------------------------------------------------------------- collect / main


def _stub_everything(monkeypatch, tmp_path, *, healthy: bool) -> None:
    as_platform(monkeypatch, plat.LINUX)
    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True, exist_ok=True)
    # A real file: check_chezmoi verifies the binary exists, which is one of the
    # bugs this port fixed, so a stub returning a fictional path would fail here
    # for the right reason and make the test look wrong.
    binary = tmp_path / "chezmoi"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(plat, "find_chezmoi", lambda: str(binary))
    monkeypatch.setattr(
        doctor, "_run", lambda argv, **k: subprocess.CompletedProcess(argv, 0, str(clone), "")
    )
    monkeypatch.setattr(paths, "resolve_source_dir", lambda *a, **k: clone)
    monkeypatch.setattr(paths, "is_stack_clone", lambda p: True)
    monkeypatch.setattr(paths, "clones", lambda: [paths.Clone(clone, "origin", "")])
    monkeypatch.setattr(paths, "canonical_clone_dir", lambda: clone)
    monkeypatch.setattr(
        store,
        "get",
        lambda k, d=None: {
            "memoryBackend": "agentmemory",
            "agentmemoryEnabled": "on" if healthy else "off",
            "ccTtsEnabled": "false",
        }.get(k, d or ""),
    )
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / ".zshrc").write_text("terminal-stack-zsh-start\ndoc-start\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    # A healthy machine with agentmemory ON has the plugin installed somewhere.
    # Without a cache the wiring check correctly reports "enabled but not
    # installed for any agent" -- which is the whole point of that gate, so the
    # sandbox has to be honest about which machine it is pretending to be.
    if healthy:
        (home / ".claude/plugins/cache/agentmemory/agentmemory").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    monkeypatch.setattr(doctor.shutil, "which", lambda t: "/usr/bin/" + t)
    # herdr is optional, and its checks read the real machine. The `which` stub
    # above answers yes to every program, so without this the sandbox grows a
    # herdr AND a tmux and reports the prefix collision between them -- on a box
    # that has neither. Say which machine this is pretending to be rather than
    # inheriting whatever the developer running the suite happens to have.
    monkeypatch.setattr(doctor.herdr, "binary", lambda: None)


def test_collect_runs_every_check_without_touching_the_machine(monkeypatch, tmp_path):
    _stub_everything(monkeypatch, tmp_path, healthy=True)
    report = doctor.collect()
    ids = {r.check for r in report.results}
    assert {"clone", "zshrc", "path-zsh", "memory-backend"} <= ids
    assert report.issues == 0


def test_main_exit_code_follows_the_health(monkeypatch, tmp_path, capsys):
    _stub_everything(monkeypatch, tmp_path, healthy=True)
    assert doctor.main([]) == 0
    assert doctor.PASSED in capsys.readouterr().out

    _stub_everything(monkeypatch, tmp_path, healthy=False)
    assert doctor.main([]) == 1
    assert "issue(s) found" in capsys.readouterr().out


def test_main_json_emits_a_parseable_document(monkeypatch, tmp_path, capsys):
    _stub_everything(monkeypatch, tmp_path, healthy=True)
    assert doctor.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["platform"] == plat.LINUX
    assert payload["issues"] == 0
    assert all({"check", "status", "message"} <= set(c) for c in payload["checks"])


def test_main_quiet_prints_nothing_when_healthy(monkeypatch, tmp_path, capsys):
    _stub_everything(monkeypatch, tmp_path, healthy=True)
    assert doctor.main(["--quiet"]) == 0
    assert capsys.readouterr().out.strip() == ""


def test_repair_without_a_clone_says_so(capsys):
    assert doctor.repair(None) == 1
    assert "no clone to repair" in capsys.readouterr().err


def test_repair_needs_the_cleanup_helper(tmp_path, capsys):
    assert doctor.repair(tmp_path) == 1
    assert "not found" in capsys.readouterr().err


def test_repair_points_at_the_cleanup_checklist(monkeypatch, tmp_path, capsys):
    as_platform(monkeypatch, plat.LINUX)
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "_cleanup.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    assert doctor.repair(tmp_path) == 0
    assert "cleanup checklist" in capsys.readouterr().out


# ------------------------------------------------------- the prompt preset


def _prompt_report(monkeypatch, preset: str, *, starship: str | None, presets: list[str]):
    from tstack import checks as tschecks
    from tstack import store as tsstore
    from tstack.commands import doctor as doc

    monkeypatch.setattr(
        tsstore, "get", lambda k, d=None: preset if k == "starshipPreset" else (d or "")
    )
    monkeypatch.setattr(doc.shutil, "which", lambda name: starship)
    monkeypatch.setattr(doc, "_starship_presets", lambda _s: presets)
    report = tschecks.Report()
    doc.check_prompt(report)
    return report


def test_the_default_prompt_is_not_reported_at_all(monkeypatch):
    """`terminal-stack` is the actual answer, not a fallback. A check that says
    "ok" for it adds a line to every run and tells nobody anything."""
    report = _prompt_report(monkeypatch, "terminal-stack", starship="/s", presets=["tokyo-night"])
    assert report.results == []


def test_a_chosen_preset_with_no_starship_is_a_failure_not_a_note(monkeypatch):
    """The template falls back to this stack's own prompt when starship is
    missing -- deliberately, because a bootstrap can render it before starship
    exists and chezmoi's `output` on a missing binary aborts the WHOLE apply.

    The cost of that safety is a machine whose setting says one thing and whose
    prompt is another, with nothing reporting it. That is what doctor is for.
    """
    report = _prompt_report(monkeypatch, "tokyo-night", starship=None, presets=[])
    assert report.issues == 1
    said = report.results[0].render()
    assert "not on PATH" in said and "this stack's own" in said
    assert "install starship" in said, "a failing check names the fix"


def test_an_unknown_preset_is_reported_as_an_empty_config(monkeypatch):
    """`starship preset nonsense` prints nothing and exits non-zero, so the
    rendered config is EMPTY -- a working prompt replaced by no prompt. The set
    check at save time is the guard; this catches a value that got in another
    way, such as a hand-edited chezmoi.toml."""
    report = _prompt_report(
        monkeypatch, "nonsense", starship="/s", presets=["tokyo-night", "jetpack"]
    )
    assert report.issues == 1
    assert "EMPTY config" in report.results[0].render()


def test_a_valid_preset_reports_ok(monkeypatch):
    report = _prompt_report(monkeypatch, "tokyo-night", starship="/s", presets=["tokyo-night"])
    assert report.issues == 0
    assert "tokyo-night" in report.results[0].render()


def test_an_unlistable_starship_does_not_invent_a_failure(monkeypatch):
    """If `starship preset --list` cannot be read, the honest answer is that the
    name could not be checked -- not that it is wrong. Failing here would report
    every preset as broken on a starship whose CLI changed."""
    report = _prompt_report(monkeypatch, "tokyo-night", starship="/s", presets=[])
    assert report.issues == 0


def test_the_prompt_check_runs_in_collect():
    """A check nothing calls is a check that does not exist."""
    import inspect

    from tstack.commands import doctor as doc

    assert "check_prompt(report)" in inspect.getsource(doc.collect)
