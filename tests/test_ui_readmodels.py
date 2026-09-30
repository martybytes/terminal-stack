"""The dashboard's read models, over stubbed commands. No Textual, no engine."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import paths, store  # noqa: E402
from tstack.commands import services  # noqa: E402
from tstack.ui import model  # noqa: E402


def test_status_rows_is_what_status_prints(monkeypatch, tmp_path, capsys):
    """One computation, two renderings: the CLI prints the rows the TUI shows."""
    root = tmp_path / "services" / "stacks"
    for name in ("agentmemory", "headroom"):
        (root / name).mkdir(parents=True)
        (root / name / "docker-compose.yml").write_text(
            f"name: ts-{name}\nservices: {{}}\n", "utf-8"
        )
    monkeypatch.setenv("TS_STACK_ROOT", str(root))
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", "native")
    monkeypatch.setenv("TS_STACK_ENGINE_UP", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(
        services.stacks,
        "stack_state",
        lambda name: "" if name == "agentmemory" else "headroom is off",
    )
    answers = {
        "ps -q --status running": (0, "a\n"),
        "ps -aq": (0, "a\n"),
        "ps --format": (0, "127.0.0.1:3110->3111/tcp\n"),
    }

    def quiet(self, stack, args):
        for needle, answer in answers.items():
            if needle in " ".join(args):
                return answer
        return (0, "")

    monkeypatch.setattr(services.stacks.Compose, "quiet", quiet)
    svc = services.Services(tmp_path, services.parse(["status"]))
    svc.stacks = list(svc.all_stacks)
    rows = services.status_rows(svc)
    by = {r.name: r for r in rows}
    assert (
        by["agentmemory"].level == "ok"
        and by["agentmemory"].running == 1
        and "3110" in by["agentmemory"].ports
    )
    assert by["headroom"].level == "warn" and "running, but headroom is off" in by["headroom"].line
    assert "tstack config agents headroom on" in by["headroom"].hint
    services.cmd_status(svc)
    out = capsys.readouterr().out
    assert "ok  agentmemory" in out and "running, but headroom is off" in out


def test_service_rows_is_empty_without_a_clone(monkeypatch):
    def boom():
        raise paths.CloneNotFound("no clone")

    monkeypatch.setattr(paths, "resolve_source_dir", boom)
    assert model.service_rows() == []


def test_service_action_captures_the_command_and_refuses_unknown_verbs(monkeypatch):
    monkeypatch.setattr(services, "main", lambda argv: print(f"ran {' '.join(argv)}") or 0)
    ok, text = model.service_action("up", "kokoro")
    assert ok and "ran up kokoro" in text
    ok, text = model.service_action("logs", "kokoro")
    assert ok and text == "ran logs kokoro -n 60"
    assert model.service_action("rm", "kokoro") == (False, "unknown action: rm")

    def refuse(argv):
        raise SystemExit(2)

    monkeypatch.setattr(services, "main", refuse)
    ok, text = model.service_action("down", "kokoro")
    assert not ok and "exit 2" in text


def test_doctor_report_wraps_collect(monkeypatch):
    from tstack.commands import doctor

    report = doctor.Report()
    report.ok("clone", "clone: /x")
    report.fail("headroom-token", "rejected", "tstack doctor --repair")
    monkeypatch.setattr(doctor, "collect", lambda: report)
    checks, issues = model.doctor_report()
    assert issues == 1
    assert [c.check for c in checks] == ["clone", "headroom-token"]
    assert checks[1].hint == "tstack doctor --repair" and checks[1].status == "FAIL"


def test_home_tiles_never_touch_docker_and_survive_a_missing_clone(monkeypatch):
    def boom():
        raise paths.CloneNotFound("nowhere")

    monkeypatch.setattr(paths, "resolve_source_dir", boom)
    monkeypatch.setattr(
        store,
        "get",
        lambda k, d=None: {"ccTtsEnabled": "false", "themeMode": "light"}.get(k, d or ""),
    )
    tiles = dict(model.home_tiles())
    assert tiles["clone"].startswith("not found")
    assert tiles["theme / leader"].startswith("light /")
    assert tiles["voice"] == "off"


def test_kb_topics_is_empty_when_there_is_no_knowledge_base(monkeypatch):
    from tstack.kb import index

    def boom():
        raise index.KbNotFound("no kb")

    monkeypatch.setattr(index, "topics", boom)
    assert model.kb_topics() == []
    assert model.kb_markdown(Path("/nonexistent/x.md")).startswith("# unreadable")
