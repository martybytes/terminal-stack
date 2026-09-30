"""Hangs, escapes and lies the audit found in the Python core, pinned."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import engine, stacks  # noqa: E402
from tstack import platform as plat  # noqa: E402
from tstack.commands import agents, doctor, services  # noqa: E402
from tstack.wizard import probes  # noqa: E402


def test_a_wedged_engine_cannot_hang_compose_forever(monkeypatch, tmp_path):
    def hang(*a, **k):
        raise subprocess.TimeoutExpired(a[0], k.get("timeout", 0))

    monkeypatch.setattr(stacks.subprocess, "run", hang)
    (tmp_path / "services/stacks/x").mkdir(parents=True)
    monkeypatch.setenv("TS_STACK_ROOT", str(tmp_path / "services/stacks"))
    compose = stacks.Compose(tmp_path, engine.NATIVE)
    got = compose.run("x", ["ps"], timeout=1)
    assert got.returncode == 124 and "timed out" in got.stderr


def test_replace_in_file_treats_the_value_as_text_not_a_template(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TOKEN=old\n", encoding="utf-8")
    assert stacks.replace_in_file(env, r"^TOKEN=.*$", r"TOKEN=a\1b\g<0>\\")
    assert env.read_text(encoding="utf-8") == "TOKEN=a\\1b\\g<0>\\\\\n"


def test_the_probe_reads_an_empty_or_junk_url_as_nothing_answering():
    assert probes.status("") == 0
    assert probes.status("not a url") == 0
    assert probes.answers("") is False


def test_there_is_one_http_probe_implementation():
    """Four copies of "answering is the test" had grown. Each former copy now
    delegates to wizard.probes; the direct urlopen calls left are the ones that
    READ a body (releases, voices, the authenticated Headroom /stats)."""
    for rel, name in (
        ("tstack/commands/doctor.py", "def _probe_http("),
        ("tstack/commands/agents.py", "def http_answers("),
        ("tstack/commands/services.py", "def _http_code("),
    ):
        src = (ROOT / rel).read_text(encoding="utf-8")
        body = src[src.index(name) : src.index("\n\n\n", src.index(name))]
        assert "probes." in body, f"{rel}: {name} does not delegate to wizard.probes"
        assert "urlopen(" not in body, f"{rel}: {name} still has its own probe"


def test_bootstrap_is_allowed_on_the_wsl_shim_path():
    src = (ROOT / "tstack/commands/services.py").read_text(encoding="utf-8")
    assert 'args.cmd not in ("status", "bootstrap")' in src


def test_the_backup_message_does_not_name_a_restore_verb_that_does_not_exist():
    src = (ROOT / "tstack/commands/services.py").read_text(encoding="utf-8")
    assert "tstack services restore" not in src
    assert 'random bytes)"' not in src, "the step message must not claim 32 BYTES for 32 hex chars"


def test_cursor_mcp_is_not_rewritten_when_already_right(tmp_path, monkeypatch):
    """`repair` runs on every sync: it wrote a new .bak every time, and created
    ~/.cursor on machines with no Cursor."""
    home = tmp_path / "home"
    (home / ".cursor").mkdir(parents=True)
    monkeypatch.setattr(agents, "user_root", lambda: home)
    entry = {"type": "stdio", "command": "docker", "args": ["exec"]}
    agents._write_cursor_mcp("headroom", entry)
    agents._write_cursor_mcp("headroom", entry)
    agents._write_cursor_mcp("headroom", entry)
    written = json.loads((home / ".cursor/mcp.json").read_text(encoding="utf-8"))
    assert written["mcpServers"]["headroom"] == entry
    assert not list((home / ".cursor").glob("mcp.json.bak.*")), "unchanged means no backup churn"
    # No Cursor here: nothing is created.
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.setattr(agents, "user_root", lambda: bare)
    agents._write_cursor_mcp("headroom", entry)
    assert not (bare / ".cursor").exists()


def test_the_kokoro_probe_reads_the_configured_url():
    src = (ROOT / "tstack/commands/doctor.py").read_text(encoding="utf-8")
    assert 'store.get("ccTtsKokoroUrl"' in src
    assert 'alive = _probe_http("http://127.0.0.1:8880' not in src


def test_the_agentmemory_secret_check_asks_the_engine_not_which_docker():
    src = doctor.check_agentmemory_secret.__code__.co_consts
    body = (ROOT / "tstack/commands/doctor.py").read_text(encoding="utf-8")
    fn = body[body.index("def check_agentmemory_secret") : body.index("def _tts_port")]
    assert 'shutil.which("docker")' not in fn
    assert "engine.is_up(" in fn and "engine.binary_for(kind)" in fn
    assert src is not None


def test_one_windows_home_helper(monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    monkeypatch.setattr(plat, "windows_username", lambda: "Some One")
    assert plat.windows_home() == Path("/mnt/c/Users/Some One")
    assert plat.local_app_data() == Path("/mnt/c/Users/Some One/AppData/Local")
    stray = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "tstack").rglob("*.py")
        if p.name != "platform.py"
        and re.search(r'Path\(f"/mnt/c/Users/\{[^}]+\}/', p.read_text(encoding="utf-8"))
    ]
    assert not stray, stray


def test_dead_code_stays_dead():
    cli = (ROOT / "tstack/cli.py").read_text(encoding="utf-8")
    assert "EXIT_RESTART_SHELL" not in cli
    config = (ROOT / "tstack/commands/config.py").read_text(encoding="utf-8")
    assert "def _ghostty(" not in config and "NOT yet the entry point" not in config
    agents_src = (ROOT / "tstack/commands/agents.py").read_text(encoding="utf-8")
    caveman = agents_src[
        agents_src.index("class Caveman:") : agents_src.index("class AgentMemory:")
    ]
    assert "def pinned" not in caveman and "def codex_cached" not in caveman


def test_sudo_runs_attached_when_there_is_a_terminal():
    src = (ROOT / "tstack/commands/wezterm.py").read_text(encoding="utf-8")
    assert "def _sudo(" in src
    assert '_run(["sudo"' not in src, "every sudo goes through _sudo"
    svc = (ROOT / "tstack/commands/services.py").read_text(encoding="utf-8")
    assert "start_new_session=not sys.stdin.isatty()" in svc


def test_services_never_hangs_on_a_stuck_verify_script():
    src = (ROOT / "tstack/commands/services.py").read_text(encoding="utf-8")
    assert "integration checks timed out" in src
    assert services is not None
