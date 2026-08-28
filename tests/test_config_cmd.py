"""`tstack config` — the Python port, phase II.

The module is built and tested before the registry row flips, which is the only
order that works: both columns flip together, and a Python `config` that shelled
out to bash for its un-ported verbs would leave Windows with nothing.

Every test uses a throwaway HOME. `docs/verifying-changes.md` § 4 is explicit
about this and the reason is not hypothetical: a test that writes the developer's
real chezmoi.toml corrupts the machine it is meant to protect.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import platform as plat  # noqa: E402
from tstack import schema, store  # noqa: E402
from tstack.commands import config  # noqa: E402


def toml_text() -> str:
    """What was actually written.

    The fixture supplies no chezmoi binary -- which is the normal state of a
    Windows-standalone install -- so `store.get` cannot read `[data]` back and
    falls through to the default. Writes are therefore asserted against the file,
    exactly as tests/test_store.py does.
    """
    return store.toml_path().read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _throwaway_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    monkeypatch.setattr(store, "mirror", lambda: {})
    monkeypatch.setattr(store, "mirror_path", lambda: None)
    store.clear_cache()
    yield home
    store.clear_cache()


# ------------------------------------------------------------- argv before clone


def test_an_unknown_verb_is_a_usage_error_even_with_no_clone(monkeypatch, capsys):
    """The `mux` ordering, not the `services` one.

    `tstack config theme` is a usage error whether or not a clone exists, and a
    user whose clone is broken should still be told their command line was wrong.
    The two already-ported comparators disagree on exactly this, which is why it
    is pinned rather than left to whichever branch happened to run first.
    """

    def boom():
        raise config.paths.CloneNotFound("no clone")

    monkeypatch.setattr(config.paths, "resolve_source_dir", boom)
    assert config.main(["definitely-not-a-verb"]) == 2
    assert "unknown command" in capsys.readouterr().err


def test_a_missing_argument_is_a_usage_error_even_with_no_clone(monkeypatch, capsys):
    def boom():
        raise config.paths.CloneNotFound("no clone")

    monkeypatch.setattr(config.paths, "resolve_source_dir", boom)
    assert config.main(["theme"]) == 2
    assert capsys.readouterr().err.strip() == "usage: tstack config theme <dark|light|follow>"


def test_the_unknown_verb_hint_names_every_verb():
    """One list, and complete. The bash hint omits `memory`, which it implements;
    the pwsh hint omits `atuin` instead. A user cannot be told to try a verb the
    hint does not mention."""
    for verb in (
        "show",
        "leader",
        "theme",
        "tmux",
        "apps",
        "tts",
        "mux",
        "restore",
        "atuin",
        "ghostty",
        "memory",
        "agents",
        "wezterm",
        "wizard",
    ):
        assert verb in config.KNOWN, verb


def test_a_delegated_verb_is_routed_rather_than_refused(monkeypatch, capsys):
    """`apps`, `tts` and `reconfigure` are not unported so much as UNPORTABLE by
    the plan's own rule: they end in a package-manager install or the bootstrap's
    save sequence, and REVAMP-PLAN.md lists the installer entry points as never
    ported. Python routes them to the shell that owns them.
    """
    seen: list[list[str]] = []

    class Done:
        returncode = 0

    # The delegation resolves the clone so it can name the script; the suite runs
    # with a throwaway HOME where the installed one is not found.
    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: ROOT)
    monkeypatch.setattr(config.subprocess, "run", lambda argv, **kw: (seen.append(argv), Done())[1])
    assert config.main(["tts", "show"]) == 0
    assert seen, "the verb was refused instead of routed"
    assert seen[0][0] == "bash" and seen[0][-2:] == ["tts", "show"]
    assert "ts-config.sh" in seen[0][1]


def test_a_handed_off_verb_runs_the_ported_command_in_process(monkeypatch):
    """`mux`, `wezterm`, `ghostty` and `wizard` are ported commands in this same
    program. Spawning a second interpreter to reach one would double the startup
    cost for nothing."""
    from tstack.commands import ghostty as ghostty_cmd

    calls: list[list[str]] = []
    monkeypatch.setattr(ghostty_cmd, "main", lambda argv: (calls.append(argv), 0)[1])
    assert config.main(["ghostty", "status"]) == 0
    assert calls == [["status"]]


# ----------------------------------------------------------------------- reading


def test_show_prints_every_row_with_the_contract_column(capsys):
    assert config.main(["show"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "terminal-stack config:"
    labels = {ln.split(":")[0].strip() for ln in lines[1:] if ln.startswith("  ")}
    for want in (
        "leader",
        "theme",
        "tmux",
        "apps",
        "wezmux",
        "wezrestore",
        "atuin",
        "wezterm",
        "headroom",
        "caveman",
        "agentmemory",
    ):
        assert want in labels, want
    # The 13-character column: every colon lands in the same place.
    columns = {ln.index(":") for ln in lines[1:] if ln.startswith("  ") and ":" in ln}
    assert len(columns) == 1, f"ragged label column: {columns}"


def test_json_is_one_document_and_names_the_layer(capsys):
    assert config.main(["show", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert {"settings", "groups", "divergences", "stores"} <= set(doc)
    assert len(doc["settings"]) == len(schema.SETTINGS)
    for row in doc["settings"]:
        assert {"key", "value", "default", "source", "flags"} <= set(row)
        assert row["source"] in ("chezmoi", "mirror", "default", "unset")
    assert doc["stores"]["authoritative"] in ("chezmoi", "mirror")


def test_json_for_one_key_and_for_a_bad_key(capsys):
    assert config.main(["show", "--json", "themeMode"]) == 0
    assert json.loads(capsys.readouterr().out)["key"] == "themeMode"
    assert config.main(["show", "--json", "nosuchkey"]) == 2
    assert "unknown setting" in capsys.readouterr().err


def test_get_prints_a_bare_value(capsys):
    """No prose, no colour, no trailing note -- `get` is for `$(...)`."""
    assert config.main(["get", "themeMode"]) == 0
    out = capsys.readouterr().out
    assert out == f"{store.get('themeMode')}\n"


# ----------------------------------------------------------------------- writing


def test_set_validates_through_the_schema(monkeypatch, capsys):
    monkeypatch.setattr(config, "_apply", lambda out, dry: None)
    assert config.main(["set", "themeMode", "purple"]) == 2
    assert "must be one of" in capsys.readouterr().err
    assert config.main(["set", "themeMode", "light"]) == 0
    assert 'themeMode = "light"' in toml_text()


def test_a_derived_key_is_refused(monkeypatch, capsys):
    """`Setting.validate()` already refuses it; this pins that `set` asks."""
    monkeypatch.setattr(config, "_apply", lambda out, dry: None)
    assert config.main(["set", "agentmemoryEnabled", "off"]) == 2
    assert "derived" in capsys.readouterr().err


def test_memory_is_the_only_writer_of_the_derived_key(monkeypatch):
    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: ROOT)
    assert config.main(["memory", "headroom"]) == 0
    body = toml_text()
    assert 'memoryBackend = "headroom"' in body
    assert 'agentmemoryEnabled = "off"' in body
    assert config.main(["memory", "agentmemory"]) == 0
    body = toml_text()
    assert 'memoryBackend = "agentmemory"' in body
    assert 'agentmemoryEnabled = "on"' in body


def test_agents_agentmemory_cannot_write_the_derived_key(monkeypatch, capsys):
    """The shell guarded only `on`, so `agents agentmemory off` wrote the derived
    key directly and produced the exact drift `tstack doctor` reports. Both
    directions are refused here."""
    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: ROOT)
    for action in ("on", "off"):
        assert config.main(["agents", "agentmemory", action]) == 2
        assert "derived from memoryBackend" in capsys.readouterr().err


def test_playwright_is_routed_rather_than_advertised_and_dropped(monkeypatch, capsys):
    """`ts-config.sh` names playwright in its usage string and has working
    branches for it, but the dispatch never routes it -- so the advertised
    command answered "unknown tool 'playwright'"."""
    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: ROOT)
    assert config.main(["agents", "playwright", "on"]) == 0
    assert 'playwrightEnabled = "on"' in toml_text()
    assert "playwright" in config.AGENT_KEYS


def test_dry_run_writes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: ROOT)
    assert config.main(["--dry-run", "set", "themeMode", "light"]) == 0
    assert not store.toml_path().exists(), "--dry-run wrote a store"
    assert "would set" in capsys.readouterr().out


def test_atuin_on_windows_sets_the_key_and_says_what_it_does_not_do(monkeypatch, capsys):
    """atuin has no PowerShell integration -- `atuin init` has no pwsh target --
    but the key still belongs in the store. The pwsh save never wrote it, so
    every Windows save STRIPPED it from the mirror."""
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    local = Path.home() / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    # The autouse fixture nulls the mirror; a Windows-standalone install IS the
    # mirror, so this test restores it.
    mirror = local / "terminal-stack" / "config.json"
    monkeypatch.setattr(store, "mirror_path", lambda: mirror)
    monkeypatch.setattr(config, "_apply", lambda out, dry: None)
    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: ROOT)
    assert config.main(["atuin", "on"]) == 0
    assert "no PowerShell integration" in capsys.readouterr().out


# --------------------------------------------------------------- the key set


def test_every_schema_key_is_read_from_the_store():
    """`DATA_KEYS` was a hand-maintained tuple of 19 -- a fourth parallel key
    list. It omitted `apps`, the four derived bindings and 37 of the 41 ccTts*
    keys, so `store.get` returned "" for them and `schema.source_of` reported
    `default` for values that were plainly saved."""
    keys = set(store.data_keys())
    for setting in schema.SETTINGS:
        assert setting.key in keys, setting.key
    assert "windowsUsername" in keys, "the sync hook's username is still needed"


def test_a_sub_commands_help_is_forwarded_not_swallowed(capsys):
    """`tstack config wizard -h` wants the wizard's help. `-h` anywhere in argv
    printed this command's page instead, which the shell it replaced did not do:
    it forwarded the flag to the hand-off."""
    assert config.main(["-h"]) == 0
    assert "tstack config -" in capsys.readouterr().out

    assert config.main(["wizard", "-h"]) == 0
    assert "tstack wizard -" in capsys.readouterr().out

    assert config.main(["ghostty", "-h"]) == 0
    assert "tstack ghostty -" in capsys.readouterr().out


def test_no_verb_opens_the_menu_rather_than_printing_show(monkeypatch):
    """Every doc says "run it bare for a menu", and the shell has always opened
    one. Quietly turning that into a one-shot print is the kind of regression a
    port makes and nobody reports, because it still prints something plausible.
    """
    seen: list[list[str]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: ROOT)
    monkeypatch.setattr(config.subprocess, "run", lambda argv, **kw: (seen.append(argv), Done())[1])
    assert config.main([]) == 0
    assert seen, "bare config was answered in-process instead of opening the menu"
    # No stray empty argument: the shell reads `case "${1:-}"` and "" IS the menu,
    # but an explicit "" would also match `show`'s neighbours by accident.
    assert seen[0][-1].endswith("ts-config.sh"), seen[0]


def test_switching_the_memory_backend_moves_the_wiring_and_restarts_headroom(monkeypatch):
    """Two things the shell did that the port had dropped.

    The agent WIRING is what actually captures, so it moves with the setting --
    writing only the key leaves the hooks pointed at a store that is no longer
    the one in use. And headroom is restarted rather than being told about: a
    headroom still running the old compose file is exactly the silent mismatch
    this setting exists to remove.
    """
    agent_calls: list[list[str]] = []
    service_calls: list[list[str]] = []
    monkeypatch.setattr(
        config.store, "get", lambda k, d=None: "agentmemory" if k == "memoryBackend" else (d or "")
    )
    monkeypatch.setattr(config.store, "set", lambda k, v: None)
    monkeypatch.setattr(config.shutil, "which", lambda name: "/usr/bin/docker")
    # Every write verb resolves the clone first; the suite runs with a
    # throwaway HOME where the installed one is not found.
    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: ROOT)

    from tstack.commands import agents as agents_cmd
    from tstack.commands import services as services_cmd

    monkeypatch.setattr(agents_cmd, "main", lambda argv: (agent_calls.append(argv), 0)[1])
    monkeypatch.setattr(services_cmd, "main", lambda argv: (service_calls.append(argv), 0)[1])

    assert config.main(["memory", "headroom"]) == 0
    assert agent_calls == [["agentmemory", "off"]], "leaving agentmemory unwires it"
    assert service_calls == [["restart", "headroom"]]

    agent_calls.clear()
    service_calls.clear()
    monkeypatch.setattr(
        config.store, "get", lambda k, d=None: "none" if k == "memoryBackend" else (d or "")
    )
    assert config.main(["memory", "agentmemory"]) == 0
    assert agent_calls == [["agentmemory", "on"]], "choosing it wires it"


def test_a_missing_docker_says_what_to_run_later_rather_than_failing(monkeypatch):
    """The setting is still saved. A machine with no engine is not a broken one."""
    monkeypatch.setattr(
        config.store, "get", lambda k, d=None: "none" if k == "memoryBackend" else (d or "")
    )
    monkeypatch.setattr(config.store, "set", lambda k, v: None)
    monkeypatch.setattr(config.shutil, "which", lambda name: None)
    # Every write verb resolves the clone first; the suite runs with a
    # throwaway HOME where the installed one is not found.
    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: ROOT)
    from tstack.commands import agents as agents_cmd

    monkeypatch.setattr(agents_cmd, "main", lambda argv: 0)
    assert config.main(["memory", "headroom"]) == 0
