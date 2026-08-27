"""`tstack agents`, with no vendor CLIs, no Docker and no network.

The rules worth having here are the ones that were only comments in the twins:
which HOME the agent configuration lives in, that a failed handshake removes
stale registrations rather than leaving them, that a file we cannot parse is
never overwritten, and that nothing in this command touches Docker.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tstack import platform as plat
from tstack.commands import agents

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def no_agents(monkeypatch):
    monkeypatch.setattr(agents, "find_agent", lambda name: None)
    monkeypatch.setattr(agents, "reexec_on_windows", lambda argv: None)


def test_help_is_ascii_only_and_names_every_action():
    assert agents.HELP.isascii()
    for action in agents.ACTIONS:
        assert action in agents.HELP


def test_the_argument_grid_is_validated_before_anything_runs(capsys):
    assert agents.main(["nope"]) == 2
    assert agents.main(["headroom", "nope"]) == 2
    assert agents.main(["headroom", "on", "nope"]) == 2
    err = capsys.readouterr().err
    assert "unknown tool" in err and "unknown action" in err and "cursor mode" in err


def test_on_wsl_the_configuration_that_counts_is_the_windows_one(monkeypatch):
    """~/.claude.json and ~/.cursor/mcp.json belong to the GUI agents, which are
    Windows processes. Writing into the WSL home puts a registration where nothing
    ever reads it."""
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    monkeypatch.setattr(plat, "windows_username", lambda: "someone")
    monkeypatch.setattr(agents.Path, "is_dir", lambda self: True)
    assert agents.user_root().as_posix() == "/mnt/c/Users/someone"

    monkeypatch.setattr(plat, "windows_username", lambda: None)
    assert agents.user_root() == Path.home()


def test_on_wsl_it_re_execs_itself_rather_than_a_second_implementation(monkeypatch):
    """The bash twin handed off to the pwsh twin here, which is exactly where the
    two were free to drift."""
    ran = []
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    monkeypatch.setattr(agents, "find_windows_python", lambda: "/mnt/c/py/python.exe")
    monkeypatch.setattr(agents.paths, "resolve_source_dir", lambda **k: ROOT)
    monkeypatch.setattr(plat, "to_windows_path", lambda p: "C:\\clone\\tstack\\main.py")

    class Got:
        returncode = 3

    monkeypatch.setattr(agents.subprocess, "run", lambda argv, **k: ran.append(argv) or Got())
    assert agents.reexec_on_windows(["headroom", "status"]) == 3
    assert ran[0][:3] == ["/mnt/c/py/python.exe", "C:\\clone\\tstack\\main.py", "agents"]


def test_no_windows_python_degrades_rather_than_failing(monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    monkeypatch.setattr(agents, "find_windows_python", lambda: None)
    assert agents.reexec_on_windows(["status"]) is None

    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    assert agents.reexec_on_windows(["status"]) is None


def test_the_manifest_is_the_one_place_a_port_or_pin_is_written_down():
    body = agents.manifest(ROOT)
    assert agents.dig(body, "headroom.proxyUrl").startswith("http://127.0.0.1:")
    assert agents.dig(body, "headroom.mcp.container") == "ts-headroom-proxy"
    assert agents.dig(body, "nothing.here", "fallback") == "fallback"
    assert agents.manifest(Path("/no/such/clone")) == {}


def test_the_headroom_token_comes_from_the_clone_not_a_workspace_walk(tmp_path, monkeypatch):
    """Five sites used to walk the workspace for a sibling checkout. That could
    never work from the runtime clone and, post-merge, could only find a stale
    file whose token may be for a proxy that has since rotated."""
    monkeypatch.delenv("HEADROOM_PROXY_TOKEN", raising=False)
    monkeypatch.delenv("HEADROOM_ENV_FILE", raising=False)
    env = tmp_path / "services" / "stacks" / "headroom"
    env.mkdir(parents=True)
    (env / ".env").write_text("HEADROOM_PROXY_TOKEN=abc123\n", encoding="utf-8")
    headroom = agents.Headroom(tmp_path, agents.Out(), "mcp")
    assert headroom.token() == "abc123"

    monkeypatch.setenv("HEADROOM_PROXY_TOKEN", "from-env")
    assert headroom.token() == "from-env", "the environment wins, as documented"

    monkeypatch.delenv("HEADROOM_PROXY_TOKEN")
    monkeypatch.setenv("HEADROOM_ENV_FILE", str(tmp_path / "nope"))
    assert headroom.token() == ""


def test_a_missing_docker_is_a_reason_not_a_crash(monkeypatch):
    monkeypatch.setattr(agents.shutil, "which", lambda name: None)
    headroom = agents.Headroom(ROOT, agents.Out(), "mcp")
    assert headroom.mcp_spec() is None
    assert headroom.mcp_reason == "docker command not installed"
    assert headroom.mcp_ready() is False


def test_the_mcp_argv_comes_out_of_the_manifest(monkeypatch):
    monkeypatch.setattr(agents.shutil, "which", lambda name: "/usr/bin/docker")
    spec = agents.Headroom(ROOT, agents.Out(), "mcp").mcp_spec()
    assert spec
    command, args = spec
    assert command == "/usr/bin/docker"
    assert args[:4] == ["exec", "-i", "ts-headroom-proxy", "headroom"]
    assert "--transport" in args and "stdio" in args


def test_cursor_byok_removes_the_mcp_entry_and_says_what_to_do(monkeypatch, capsys):
    """BYOK means the provider key goes to the proxy directly; leaving an MCP
    entry behind would route the same traffic twice."""
    written = []
    monkeypatch.setattr(agents, "find_agent", lambda name: None)
    monkeypatch.setattr(agents, "_write_cursor_mcp", lambda name, entry: written.append(entry))
    headroom = agents.Headroom(ROOT, agents.Out(), "byok")
    monkeypatch.setattr(headroom, "mcp_spec", lambda: ("/usr/bin/docker", ["exec"]))
    monkeypatch.setattr(headroom, "mcp_ready", lambda: True)
    headroom.register(add=True)
    assert written == [None]
    out = capsys.readouterr().out
    assert "127.0.0.1:8787" in out
    assert "subscription traffic cannot be redirected" in out


def test_status_reports_a_missing_registration_only_when_the_server_answers(
    monkeypatch, capsys, no_agents
):
    """ "Registration missing" is a problem only when the MCP server is actually
    available; otherwise it is the expected state and saying so would be noise."""
    headroom = agents.Headroom(ROOT, agents.Out(), "off")
    monkeypatch.setattr(headroom, "probe_auth", lambda: (True, ""))
    monkeypatch.setattr(headroom, "mcp_spec", lambda: ("/usr/bin/docker", ["exec"]))
    monkeypatch.setattr(headroom, "mcp_ready", lambda: False)
    headroom.mcp_reason = "docker MCP command failed"
    monkeypatch.setattr(agents, "find_agent", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(headroom, "claude_registered", lambda spec: False)
    monkeypatch.setattr(headroom, "codex_registered", lambda spec: False)
    headroom.status()
    out = capsys.readouterr().out
    assert "unavailable (expected)" in out
    assert "missing or stale" not in out


def test_the_dashboard_verb_opens_a_url_and_changes_nothing(monkeypatch):
    opened = []
    monkeypatch.setattr(agents, "_open_url", lambda url: opened.append(url))
    headroom = agents.Headroom(ROOT, agents.Out(), "mcp")
    assert headroom.run("dashboard") == 0
    assert opened and opened[0].endswith("/dashboard")


# ------------------------------------------------------------------- caveman


def test_the_caveman_rule_is_marker_delimited_and_keeps_the_rest(tmp_path, monkeypatch):
    """That AGENTS.md is the user's file. Everything outside the markers has to
    survive, and a second `on` must not stack a second copy."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    path = tmp_path / "AGENTS.md"
    path.write_text("# mine\n\nkeep this\n", encoding="utf-8")

    agents.caveman_rule(True)
    body = path.read_text(encoding="utf-8")
    assert "keep this" in body
    assert body.count(agents.CAVEMAN_START) == 1

    agents.caveman_rule(True)
    assert path.read_text(encoding="utf-8").count(agents.CAVEMAN_START) == 1

    agents.caveman_rule(False)
    body = path.read_text(encoding="utf-8")
    assert agents.CAVEMAN_START not in body
    assert "keep this" in body
    assert list(tmp_path.glob("AGENTS.md.bak.*")), "the user's file was rewritten with no backup"


def test_caveman_status_is_honest_about_each_half(tmp_path, monkeypatch, capsys, no_agents):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(agents, "user_root", lambda: tmp_path)
    caveman = agents.Caveman(ROOT, agents.Out())
    assert caveman.status() is False
    out = capsys.readouterr().out
    assert "Codex global always-on rule absent" in out
    assert "global Codex/Cursor caveman skill missing" in out

    agents.caveman_rule(True)
    skill = tmp_path / ".agents" / "skills" / "caveman" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("x", encoding="utf-8")
    assert caveman.status() is True
    out = capsys.readouterr().out
    assert "rule present" in out and "skill installed" in out


def test_caveman_off_keeps_the_downloaded_skill_and_uninstall_says_so(
    tmp_path, monkeypatch, capsys, no_agents
):
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    caveman = agents.Caveman(ROOT, agents.Out())
    caveman.remove(uninstall=False)
    assert "global skill was preserved" in capsys.readouterr().out
    caveman.remove(uninstall=True)
    assert "global skill was preserved" not in capsys.readouterr().out


def test_an_unsupported_action_is_reported_per_tool(capsys, no_agents):
    out = agents.Out()
    assert agents.Caveman(ROOT, out).run("dashboard") == 2
    assert agents.AgentMemory(ROOT, out).run("dashboard") == 2
    assert "has no 'dashboard' action" in capsys.readouterr().out


# --------------------------------------------------------------- agentmemory


def test_agentmemory_status_treats_any_answer_as_up(monkeypatch, capsys, no_agents):
    memory = agents.AgentMemory(ROOT, agents.Out())
    monkeypatch.setattr(memory, "adapter", lambda: None)
    monkeypatch.setattr(agents, "http_answers", lambda url, timeout=2: True)
    monkeypatch.setattr(agents, "tcp_answers", lambda host, port, timeout=1.0: False)
    assert memory.status() is True
    assert "REST server reachable" in capsys.readouterr().out


def test_agentmemory_status_falls_back_to_a_tcp_connect(monkeypatch, capsys, no_agents):
    memory = agents.AgentMemory(ROOT, agents.Out())
    monkeypatch.setattr(memory, "adapter", lambda: None)
    monkeypatch.setattr(agents, "http_answers", lambda url, timeout=2: False)
    monkeypatch.setattr(agents, "tcp_answers", lambda host, port, timeout=1.0: port == 3111)
    assert memory.status() is True
    out = capsys.readouterr().out
    assert "REST server reachable" in out
    assert "viewer not reachable" in out


def test_incomplete_hook_wiring_names_the_repair(monkeypatch, capsys, no_agents):
    memory = agents.AgentMemory(ROOT, agents.Out())
    monkeypatch.setattr(memory, "adapter", lambda: ["bash", "adapter.sh"])
    monkeypatch.setattr(agents, "http_answers", lambda url, timeout=2: True)
    monkeypatch.setattr(agents, "tcp_answers", lambda host, port, timeout=1.0: False)

    class Failed:
        returncode = 1
        stdout = ""
        stderr = ""

    monkeypatch.setattr(agents.subprocess, "run", lambda argv, **k: Failed())
    memory.status()
    assert "tstack agents agentmemory repair" in capsys.readouterr().out


def test_a_missing_adapter_is_skipped_rather_than_crashed(monkeypatch, tmp_path, capsys):
    memory = agents.AgentMemory(tmp_path, agents.Out())
    assert memory.adapter() is None
    monkeypatch.setattr(agents, "find_agent", lambda name: None)
    memory.install()
    assert "plugin enabled" in capsys.readouterr().out


# ------------------------------------------------------------------ backups


def test_a_same_day_backup_is_never_clobbered(tmp_path):
    """The repo-wide rule: <path>.bak.YYYYMMDD, then .1, .2 - never overwrite one
    taken earlier the same day."""
    path = tmp_path / "mcp.json"
    path.write_text("one", encoding="utf-8")
    agents._backup(path)
    path.write_text("two", encoding="utf-8")
    agents._backup(path)
    backups = sorted(p.read_text(encoding="utf-8") for p in tmp_path.glob("mcp.json.bak.*"))
    assert backups == ["one", "two"]


def test_a_json_match_needs_the_command_and_every_argument(tmp_path):
    path = tmp_path / "mcp.json"
    path.write_text(
        json.dumps({"mcpServers": {"headroom": {"command": "docker", "args": ["a", "b"]}}}),
        encoding="utf-8",
    )
    assert agents._json_mcp_matches(path, "headroom", ("docker", ["a", "b"])) is True
    assert agents._json_mcp_matches(path, "headroom", ("docker", ["a"])) is False
    assert agents._json_mcp_matches(path, "headroom", ("podman", ["a", "b"])) is False
    assert agents._json_mcp_matches(tmp_path / "gone.json", "headroom", ("docker", [])) is False


def test_running_all_tools_reports_the_worst_outcome(monkeypatch, capsys, no_agents):
    """`tstack agents` with no arguments is a whole-host report, and one broken
    tool has to be visible in the exit code."""
    monkeypatch.setattr(agents.paths, "resolve_source_dir", lambda **k: ROOT)
    monkeypatch.setattr(agents.Headroom, "run", lambda self, action: 0)
    monkeypatch.setattr(agents.Caveman, "run", lambda self, action: 0)

    def unhappy(self, action):
        self.out.bad("something is wrong")
        return 1

    monkeypatch.setattr(agents.AgentMemory, "run", unhappy)
    assert agents.main([]) == 1


def test_install_paths_skip_a_vendor_cli_that_is_not_there(monkeypatch, capsys):
    """Every install step is optional: a host with no Claude and no Codex must
    still wire what it can and say what it skipped."""
    ran = []
    monkeypatch.setattr(agents, "find_agent", lambda name: None)
    monkeypatch.setattr(agents, "_run", lambda argv, timeout=60, stdin=None: ran.append(argv))
    monkeypatch.setattr(agents, "caveman_rule", lambda enable: ran.append(["rule", enable]))
    agents.Caveman(ROOT, agents.Out()).install()
    out = capsys.readouterr().out
    assert "Claude Code not installed" in out
    assert "npx not installed" in out
    assert ["rule", True] in ran


def test_caveman_install_pins_the_manifest_version(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(agents, "find_agent", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(agents, "_run", lambda argv, timeout=60, stdin=None: ran.append(argv))
    monkeypatch.setattr(agents, "caveman_rule", lambda enable: None)
    agents.Caveman(ROOT, agents.Out()).install()
    flat = [" ".join(c) for c in ran]
    assert any("plugin marketplace add" in f and "caveman" in f for f in flat)
    assert any("plugin install caveman@caveman --scope user -y" in f for f in flat)
    assert any("skills@latest add" in f for f in flat)
    assert "2.2.0" in capsys.readouterr().out


def test_agentmemory_install_wires_both_vendors_then_the_hooks(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(agents, "find_agent", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(agents, "_run", lambda argv, timeout=60, stdin=None: ran.append(argv))

    class Ok:
        returncode = 0

    hooks = []
    monkeypatch.setattr(agents.subprocess, "run", lambda argv, **k: hooks.append(argv) or Ok())
    memory = agents.AgentMemory(ROOT, agents.Out())
    monkeypatch.setattr(memory, "adapter", lambda: ["bash", "adapter.sh"])
    memory.install()
    flat = [" ".join(c) for c in ran]
    assert any("plugin install agentmemory@agentmemory" in f for f in flat)
    assert any("codex plugin add agentmemory@agentmemory" in f for f in flat)
    assert hooks and hooks[0][-1] == "--apply"
    assert "Docker, secrets and server feature flags were not changed" in capsys.readouterr().out


def test_agentmemory_uninstall_keeps_the_data(monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(agents, "find_agent", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(agents, "_run", lambda argv, timeout=60, stdin=None: ran.append(argv))
    monkeypatch.setattr(agents.subprocess, "run", lambda argv, **k: None)
    memory = agents.AgentMemory(ROOT, agents.Out())
    monkeypatch.setattr(memory, "adapter", lambda: None)
    memory.remove(uninstall=True)
    flat = [" ".join(c) for c in ran]
    assert any("--keep-data" in f for f in flat), "uninstall must never drop the memories"
    assert "data were not changed" in capsys.readouterr().out


def test_the_adapter_is_the_shell_one_for_this_platform(monkeypatch, tmp_path):
    """The hook-wiring adapter is still shell on both sides; this only has to pick
    the right one and skip cleanly when it is absent."""
    (tmp_path / "bootstrap").mkdir()
    (tmp_path / "bootstrap" / "ts-agentmemory.sh").write_text("x", encoding="utf-8")
    (tmp_path / "bootstrap" / "ts-agentmemory.ps1").write_text("x", encoding="utf-8")
    memory = agents.AgentMemory(tmp_path, agents.Out())

    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    assert memory.adapter()[0] == "bash"

    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setattr(plat, "find_pwsh", lambda: "/usr/bin/pwsh")
    assert memory.adapter()[0] == "/usr/bin/pwsh"

    monkeypatch.setattr(plat, "find_pwsh", lambda: None)
    assert memory.adapter() is None


def test_headroom_off_removes_every_registration(monkeypatch, capsys):
    ran = []
    written = []
    monkeypatch.setattr(agents, "find_agent", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(agents, "_run", lambda argv, timeout=60, stdin=None: ran.append(argv))
    monkeypatch.setattr(agents, "_write_cursor_mcp", lambda name, entry: written.append(entry))
    headroom = agents.Headroom(ROOT, agents.Out(), "mcp")
    monkeypatch.setattr(headroom, "mcp_spec", lambda: ("/usr/bin/docker", ["exec"]))
    assert headroom.run("off") == 0
    flat = [" ".join(c) for c in ran]
    assert any("mcp remove --scope user headroom" in f for f in flat)
    assert any("codex mcp remove headroom" in f for f in flat)
    assert written == [None]
    assert "Docker was not changed" in capsys.readouterr().out


def test_a_missing_clone_is_reported_rather_than_crashed(monkeypatch, capsys):
    from tstack import paths

    def missing(**kwargs):
        raise paths.CloneNotFound("no clone")

    monkeypatch.setattr(agents, "reexec_on_windows", lambda argv: None)
    monkeypatch.setattr(agents.paths, "resolve_source_dir", missing)
    assert agents.main(["headroom", "status"]) == 1
    assert "no clone" in capsys.readouterr().err


def test_open_url_uses_this_platforms_opener(monkeypatch):
    ran = []
    monkeypatch.setattr(agents, "_run", lambda argv, timeout=15: ran.append(argv))
    monkeypatch.setattr(plat, "kind", lambda: plat.MACOS)
    agents._open_url("http://x")
    assert ran[-1][0] == "open"
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    agents._open_url("http://x")
    assert ran[-1][0] == "cmd.exe"


def test_a_probe_of_a_dead_port_is_false():
    assert agents.tcp_answers("127.0.0.1", 9, timeout=0.2) is False
