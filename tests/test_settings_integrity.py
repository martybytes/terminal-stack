"""Saves that corrupted, reverted or reset settings.

Each test here is one way a save used to lie: the value looked saved, and the
store, the rendered config or the next questionnaire said otherwise.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import platform as plat  # noqa: E402
from tstack import store  # noqa: E402
from tstack.commands import config  # noqa: E402
from tstack.wizard import flow  # noqa: E402
from tstack.wizard.console import Console  # noqa: E402


@pytest.fixture(autouse=True)
def _home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    monkeypatch.setattr(store, "mirror", lambda: {})
    monkeypatch.setattr(store, "mirror_path", lambda: None)
    # ROOT, not tmp_path: the app catalog resolves apps.conf through
    # resolve_source_dir and caches the result, so a throwaway clone here left
    # every later wizard test with an EMPTY catalog. The memory tests that need
    # a headroom .env point it at tmp_path themselves.
    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: ROOT)
    from tstack import apps as _apps

    _apps.catalog.cache_clear()
    store.clear_cache()
    yield
    _apps.catalog.cache_clear()
    for var in (
        "TS_PROFILE",
        "TS_DEVELOPMENT",
        "TS_APPS",
        "TS_THEME",
        "TS_LEADER",
        "TS_ATUIN",
        "TS_HERDR",
        "TS_MEMORY_BACKEND",
        "TS_HEADROOM",
        "TS_AGENTMEMORY",
        "TS_CAVEMAN",
        "TS_HEADROOM_CURSOR",
        "TS_WEZ_MUX",
        "TS_WEZ_RESTORE",
        "TS_CC_TTS",
        "TS_SERVICES",
        "TS_HEADLESS_RESOLVED",
        "TS_ASSUME_YES",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TS_HEADLESS_RESOLVED", "0")


def _saved(monkeypatch, values: dict[str, str]) -> None:
    monkeypatch.setattr(store, "get", lambda k, d=None: values.get(k, d if d is not None else ""))


# --------------------------------------------------------------- apps array


def test_apps_is_saved_as_a_toml_array_not_a_string(capsys):
    """`apps = "eza fzf"` made every later `chezmoi init` fail: the template
    does `range .apps`. Reads looked fine because they accept a string."""
    out = config.Out(quiet=True)
    assert config.set_value("apps", "eza fzf lazygit", out, dry_run=False) == 0
    body = store.toml_path().read_text(encoding="utf-8")
    assert 'apps = ["eza", "fzf", "lazygit"]' in body
    assert 'apps = "eza' not in body


# ------------------------------------------------------------ wizard re-run


def _run(monkeypatch, saved: dict[str, str], answers: list[str] | None = None) -> flow.Answers:
    _saved(monkeypatch, saved)
    console = Console.scripted(answers) if answers is not None else Console()
    return flow.collect(console)


SAVED = {
    "themeMode": "light",
    "leaderChord": "ctrl-a",
    "atuinEnabled": "off",
    "herdrConfig": "on",
    "weztermMux": "on",
    "weztermRestore": "on",
    "memoryBackend": "headroom",
    "headroomEnabled": "on",
    "headroomCursorMode": "byok",
    "cavemanEnabled": "on",
    "agentmemoryEnabled": "off",
    "apps": "eza fzf",
    "starshipPreset": "terminal-stack",
    "tmuxPrefix": "ctrl-b",
}


def test_pressing_enter_at_every_question_keeps_the_machine_as_it_is(monkeypatch):
    """`tstack reinstall` + Enter used to reset theme, leader, atuin, herdr, the
    memory backend and caveman to stock -- the bootstrap saves every field."""
    monkeypatch.setenv("TS_PROFILE", "full")
    monkeypatch.setenv("TS_DEVELOPMENT", "yes")
    monkeypatch.setattr(
        flow.shutil, "which", lambda name: "/usr/bin/herdr" if name == "herdr" else None
    )
    got = _run(monkeypatch, SAVED, answers=[])  # exhausted script == Enter everywhere
    assert got.theme == "light"
    assert got.leader == "ctrl-a"
    assert got.atuin == "off"
    assert got.herdr == "on"
    assert got.wez_mux == "on" and got.wez_restore == "on"
    assert got.memory_backend == "headroom" and got.headroom == "on"
    assert got.headroom_cursor == "byok"
    assert got.caveman == "on"


def test_the_prompt_profile_carries_saved_answers_instead_of_dataclass_defaults(monkeypatch):
    """Choosing `prompt` returned `apps=[]` and `memory_backend="none"`, which the
    bootstrap then SAVED: an empty app list and AgentMemory unwired."""
    monkeypatch.setenv("TS_PROFILE", "prompt")
    got = _run(monkeypatch, {**SAVED, "memoryBackend": "agentmemory", "agentmemoryEnabled": "on"})
    assert got.apps == ["eza", "fzf"]
    assert got.memory_backend == "agentmemory" and got.agentmemory == "on"
    assert got.leader == "ctrl-a" and got.atuin == "off" and got.herdr == "on"
    assert got.headroom_cursor == "byok"


def test_a_headless_rerun_keeps_the_memory_backend(monkeypatch):
    """The non-full path defaulted memory to `none` regardless of what was saved."""
    monkeypatch.setenv("TS_HEADLESS_RESOLVED", "1")
    got = _run(monkeypatch, SAVED | {"memoryBackend": "agentmemory", "agentmemoryEnabled": "on"})
    assert got.memory_backend == "agentmemory" and got.agentmemory == "on"
    assert got.headroom == "on" and got.caveman == "on"


def test_an_explicit_ts_headroom_off_wins_over_the_backend_mapping(monkeypatch):
    monkeypatch.setenv("TS_PROFILE", "full")
    monkeypatch.setenv("TS_DEVELOPMENT", "yes")
    monkeypatch.setenv("TS_HEADROOM", "off")
    monkeypatch.setenv("TS_AGENTMEMORY", "on")
    got = _run(monkeypatch, {})
    assert got.agentmemory == "on" and got.headroom == "off"


def test_ts_development_accepts_1_and_0(monkeypatch):
    monkeypatch.setenv("TS_PROFILE", "full")
    monkeypatch.setenv("TS_DEVELOPMENT", "1")
    assert _run(monkeypatch, {}).development == "yes"
    monkeypatch.setenv("TS_DEVELOPMENT", "0")
    assert _run(monkeypatch, {}).development == "no"


def test_assume_yes_takes_every_default_without_a_terminal(monkeypatch, tmp_path):
    """Documented as "takes every default without prompting"; it used to skip
    only the review and still ask every question on a terminal."""
    from tstack.commands import wizard as wizard_cmd

    _saved(monkeypatch, SAVED)
    monkeypatch.setenv("TS_PROFILE", "full")
    monkeypatch.setenv("TS_DEVELOPMENT", "yes")
    monkeypatch.setattr(
        Console, "open", classmethod(lambda cls, tty="/dev/tty": pytest.fail("asked"))
    )
    out = tmp_path / "answers.sh"
    assert wizard_cmd.main(["--assume-yes", "--emit", "sh", "--out", str(out)]) == 0
    body = out.read_text(encoding="utf-8")
    assert "TS_WIZ_THEME=light" in body and "TS_WIZ_LEADER=ctrl-a" in body


# ------------------------------------------------------------- the mirror


def test_a_windows_save_lands_where_the_mirror_reads_it(monkeypatch, tmp_path):
    """Flat `ccTtsKokoroVoice` was written while `store.get` (and the daemon) read
    nested `ccTts.kokoro.voice`, so a Windows-only save read back as the old
    value. Booleans stay JSON booleans."""
    mirror = tmp_path / "config.json"
    mirror.write_text(
        json.dumps({"ccTts": {"enabled": False, "kokoro": {"voice": "am_adam", "speed": 1.0}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(store, "mirror_path", lambda: mirror)
    monkeypatch.setattr(store, "writes_to_mirror", lambda: True)
    store.set("ccTtsKokoroVoice", "af_heart")
    store.set("ccTtsEnabled", "true")
    store.set("ccTtsKokoroSpeed", "1.2")
    data = json.loads(mirror.read_text(encoding="utf-8"))
    assert data["ccTts"]["kokoro"]["voice"] == "af_heart"
    assert data["ccTts"]["enabled"] is True
    assert data["ccTts"]["kokoro"]["speed"] == 1.2
    assert "ccTtsKokoroVoice" not in data


# -------------------------------------------------------------- agents/memory


def test_agents_on_runs_the_wiring_and_saves_only_on_success(monkeypatch, capsys):
    from tstack.commands import agents as agents_cmd

    calls: list[list[str]] = []
    monkeypatch.setattr(agents_cmd, "main", lambda argv: (calls.append(argv), 1)[1])
    monkeypatch.setattr(config, "_apply", lambda out, dry: 0)
    assert config.main(["agents", "headroom", "on"]) == 1
    assert calls == [["headroom", "on"]]
    assert "headroomEnabled" not in (
        store.toml_path().read_text() if store.toml_path().exists() else ""
    )
    monkeypatch.setattr(agents_cmd, "main", lambda argv: 0)
    assert config.main(["agents", "headroom", "on"]) == 0
    assert 'headroomEnabled = "on"' in store.toml_path().read_text(encoding="utf-8")


def test_agents_uninstall_turns_the_key_off(monkeypatch):
    """It never wrote the key, so the next sync's `repair` wired it all back."""
    from tstack.commands import agents as agents_cmd

    monkeypatch.setattr(agents_cmd, "main", lambda argv: 0)
    monkeypatch.setattr(config, "_apply", lambda out, dry: 0)
    store.set("headroomEnabled", "on")
    assert config.main(["agents", "headroom", "uninstall"]) == 0
    assert 'headroomEnabled = "off"' in store.toml_path().read_text(encoding="utf-8")


def test_agents_headroom_cursor_saves_the_mode_and_rewires(monkeypatch):
    """Documented in doc common/tstack; it was a usage error."""
    from tstack.commands import agents as agents_cmd

    calls: list[list[str]] = []
    monkeypatch.setattr(agents_cmd, "main", lambda argv: (calls.append(argv), 0)[1])
    assert config.main(["agents", "headroom", "cursor", "byok"]) == 0
    assert 'headroomCursorMode = "byok"' in store.toml_path().read_text(encoding="utf-8")
    assert calls == [["headroom", "repair", "byok"]]
    assert config.main(["agents", "headroom", "cursor", "sideways"]) == 2


def test_agents_repair_defaults_to_the_saved_cursor_mode(monkeypatch):
    from tstack.commands import agents as agents_cmd

    seen: dict[str, str] = {}
    monkeypatch.setattr(
        agents_cmd.store, "get", lambda k, d="": "byok" if k == "headroomCursorMode" else d
    )

    class Fake:
        def __init__(self, source, out, cursor_mode):
            seen["mode"] = cursor_mode

        def run(self, action):
            return 0

    monkeypatch.setattr(agents_cmd, "Headroom", Fake)
    monkeypatch.setattr(agents_cmd, "reexec_on_windows", lambda argv: None)
    monkeypatch.setattr(agents_cmd.paths, "resolve_source_dir", lambda: ROOT)
    agents_cmd.main(["headroom", "repair"])
    assert seen["mode"] == "byok"


def test_memory_none_does_not_start_a_headroom_nobody_enabled(monkeypatch, tmp_path, capsys):
    from tstack.commands import agents as agents_cmd
    from tstack.commands import services as services_cmd

    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: tmp_path)

    env = tmp_path / "services" / "stacks" / "headroom" / ".env"
    env.parent.mkdir(parents=True)
    env.write_text("COMPOSE_PATH_SEPARATOR=:\nCOMPOSE_FILE=docker-compose.yml\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(agents_cmd, "main", lambda argv: 0)
    monkeypatch.setattr(services_cmd, "main", lambda argv: (calls.append(argv), 0)[1])
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", "native")
    monkeypatch.setenv("TS_STACK_ENGINE_UP", "1")
    store.set("headroomEnabled", "off")
    assert config.main(["memory", "none"]) == 0
    assert ["restart", "headroom"] not in calls
    assert "not enabled on this machine" in capsys.readouterr().out


def test_memory_reports_a_failed_step_instead_of_0(monkeypatch, tmp_path):
    from tstack.commands import agents as agents_cmd
    from tstack.commands import services as services_cmd

    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: tmp_path)

    monkeypatch.setattr(agents_cmd, "main", lambda argv: 0)
    monkeypatch.setattr(services_cmd, "main", lambda argv: 1)  # bootstrap fails
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", "absent")
    assert config.main(["memory", "agentmemory"]) == 1


# ------------------------------------------------------------------ _apply


def test_apply_reports_a_failed_chezmoi_apply(monkeypatch, tmp_path, capsys):
    binary = tmp_path / "chezmoi"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(plat, "find_chezmoi", lambda: str(binary))
    monkeypatch.setattr(store, "chezmoi_init", lambda: True)
    monkeypatch.setattr(config, "_refresh_windows_mirror", lambda out: None)
    monkeypatch.setattr(
        config.proc,
        "capture",
        lambda argv, **k: subprocess.CompletedProcess(
            argv, 1, "", "chezmoi: template error at line 3"
        ),
    )
    out = config.Out(quiet=False)
    assert config._apply(out, dry_run=False) == 1
    text = capsys.readouterr().out
    assert "chezmoi apply failed (exit 1)" in text and "template error" in text
    assert "==> done." not in text


def test_set_value_returns_the_apply_result(monkeypatch):
    monkeypatch.setattr(config, "_apply", lambda out, dry: 1)
    assert config.set_value("themeMode", "light", config.Out(quiet=True), dry_run=False) == 1


def test_gui_side_keys_say_where_they_render_on_wsl(monkeypatch, capsys):
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    monkeypatch.setattr(config, "_apply", lambda out, dry: 0)
    config.set_value("weztermRestore", "on", config.Out(quiet=False), dry_run=False)
    assert "tstack update' in PowerShell" in capsys.readouterr().out
