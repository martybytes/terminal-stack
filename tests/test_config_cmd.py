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

from tstack import engine, schema, stacks, store  # noqa: E402
from tstack import platform as plat  # noqa: E402
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


@pytest.fixture(autouse=True)
def _no_real_docker(monkeypatch):
    """`tstack config memory` calls into `tstack services`, which runs DOCKER.

    Autouse and module-wide, because one test forgetting it is not a failed
    assertion -- it is `docker compose up` against the developer's real machine.
    That is not hypothetical: `test_memory_is_the_only_writer_of_the_derived_key`
    pointed `resolve_source_dir` at ROOT, and once set_memory learned to bootstrap
    and restart, a plain `pytest` started Qdrant and Neo4j and wrote the live
    clone's headroom/.env. It surfaced in `scripts/preflight.sh`, whose test-merge
    worktree left containers labelled with a path under /tmp.

    A test that means to assert about the calls overrides this with its own
    recorder; nothing may reach the real thing by omission. Same rule, same
    reason, as the throwaway HOME above.
    """
    from tstack.commands import services as services_cmd

    monkeypatch.setattr(services_cmd, "main", lambda argv: 0)


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


def test_memory_is_the_only_writer_of_the_derived_key(monkeypatch, tmp_path):
    # tmp_path, never ROOT: set_memory writes headroom's .env now, and aiming a
    # test at the real tree edits the developer's own clone.
    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: tmp_path)
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

    # A DELEGATED verb answers -h ITSELF. Forwarding it would have run the
    # installer: ts-config.sh dispatches on $1 and ignores every later argument.
    assert config.main(["wizard", "-h"]) == 0
    got = capsys.readouterr().out
    assert "tstack config wizard" in got and "SAVE" in got
    assert "not the same command as `tstack wizard`" in got

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


@pytest.fixture
def memory_clone(monkeypatch, tmp_path):
    """A throwaway clone with a headroom .env, and both callees recorded.

    Never ROOT. `set_memory` writes headroom's COMPOSE_FILE now, and pointing a
    test at the real tree would have it edit the developer's own `.env` -- the
    hazard `docs/verifying-changes.md` § 4 exists for, one directory over.
    """
    from tstack.commands import agents as agents_cmd
    from tstack.commands import services as services_cmd

    env = tmp_path / "services" / "stacks" / "headroom" / ".env"
    env.parent.mkdir(parents=True)
    env.write_text("COMPOSE_PATH_SEPARATOR=:\nCOMPOSE_FILE=docker-compose.yml\n", encoding="utf-8")
    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: tmp_path)
    monkeypatch.setattr(config.store, "set", lambda k, v: None)

    calls: dict[str, list] = {"agents": [], "services": []}
    monkeypatch.setattr(agents_cmd, "main", lambda argv: (calls["agents"].append(argv), 0)[1])
    monkeypatch.setattr(services_cmd, "main", lambda argv: (calls["services"].append(argv), 0)[1])
    calls["env"] = env  # type: ignore[assignment]
    return calls


def _backend(monkeypatch, value):
    monkeypatch.setattr(
        config.store, "get", lambda k, d=None: value if k == "memoryBackend" else (d or "")
    )


def test_switching_the_memory_backend_moves_the_wiring_and_restarts_headroom(
    monkeypatch, memory_clone
):
    """Two things the shell did that the port had dropped.

    The agent WIRING is what actually captures, so it moves with the setting --
    writing only the key leaves the hooks pointed at a store that is no longer
    the one in use. And headroom is restarted rather than being told about: a
    headroom still running the old compose file is exactly the silent mismatch
    this setting exists to remove.
    """
    _backend(monkeypatch, "agentmemory")
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.NATIVE)
    monkeypatch.setenv("TS_STACK_ENGINE_UP", "1")

    assert config.main(["memory", "headroom"]) == 0
    assert memory_clone["agents"] == [["agentmemory", "off"]], "leaving agentmemory unwires it"
    assert memory_clone["services"] == [["bootstrap"], ["restart", "headroom"]]

    memory_clone["agents"].clear()
    memory_clone["services"].clear()
    _backend(monkeypatch, "none")
    assert config.main(["memory", "agentmemory"]) == 0
    assert memory_clone["agents"] == [["agentmemory", "on"]], "choosing it wires it"


def test_the_backend_is_seeded_before_it_is_restarted(monkeypatch, memory_clone):
    """Order, not membership. Asserting only that bootstrap is *called* would
    pass with it bolted on after the restart, which fixes nothing.

    `restart` is down+up, and `up` on an unseeded headroom never reaches compose:
    both its secrets are `:?`-required, so it dies at `compose config` about a
    VARIABLE rather than about the missing file. That is the error the reported
    install printed, twice.
    """
    _backend(monkeypatch, "none")
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.NATIVE)
    monkeypatch.setenv("TS_STACK_ENGINE_UP", "1")
    assert config.main(["memory", "headroom"]) == 0
    verbs = [c[0] for c in memory_clone["services"]]
    assert verbs.index("bootstrap") < verbs.index("restart")


def test_the_compose_file_round_trips_through_the_consumer(monkeypatch, memory_clone):
    """The overlay's `command:` carries `--memory`, which has no environment
    variable and is the entire feature. Asserted through `stacks.compose_files`,
    because that is what `Compose` and `check_files` actually read."""
    env = memory_clone["env"]
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.ABSENT)

    _backend(monkeypatch, "none")
    assert config.main(["memory", "headroom"]) == 0
    assert stacks.compose_files(env.parent) == [
        "docker-compose.yml",
        "docker-compose.memory.yml",
    ]

    _backend(monkeypatch, "headroom")
    assert config.main(["memory", "agentmemory"]) == 0
    assert stacks.compose_files(env.parent) == ["docker-compose.yml"]


def test_a_missing_compose_file_key_is_appended_not_ignored(monkeypatch, memory_clone):
    """The awk twin's END block: .env.example is not guaranteed to carry either
    key, and a silent no-op there is the bug in a different costume."""
    env = memory_clone["env"]
    env.write_text("HEADROOM_PORT=8787\n", encoding="utf-8")
    _backend(monkeypatch, "none")
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.ABSENT)

    assert config.main(["memory", "headroom"]) == 0
    body = env.read_text(encoding="utf-8")
    assert "COMPOSE_FILE=docker-compose.yml:docker-compose.memory.yml" in body
    assert "COMPOSE_PATH_SEPARATOR=:" in body
    assert body.startswith("HEADROOM_PORT=8787\n"), "and it appends rather than rewriting"


def test_a_crlf_env_file_is_not_half_converted(monkeypatch, memory_clone):
    """A .env a Windows side also writes must not come back half LF, which is
    what universal newline translation does to exactly the line being edited."""
    env = memory_clone["env"]
    env.write_bytes(b"HEADROOM_PORT=8787\r\nCOMPOSE_FILE=docker-compose.yml\r\n")
    _backend(monkeypatch, "none")
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.ABSENT)

    assert config.main(["memory", "headroom"]) == 0
    raw = env.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n"), "every line ending survived"


def test_an_existing_separator_is_never_rewritten(monkeypatch, memory_clone):
    """The awk prints one straight through. A machine that chose ';' would
    otherwise get its overlay parsed as one impossible filename."""
    env = memory_clone["env"]
    env.write_text("COMPOSE_PATH_SEPARATOR=;\nCOMPOSE_FILE=docker-compose.yml\n", encoding="utf-8")
    _backend(monkeypatch, "none")
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.ABSENT)

    assert config.main(["memory", "headroom"]) == 0
    assert "COMPOSE_PATH_SEPARATOR=;" in env.read_text(encoding="utf-8")
    assert env.read_text(encoding="utf-8").count("COMPOSE_PATH_SEPARATOR=") == 1


def test_the_engine_probe_decides_the_restart_not_which_docker(monkeypatch, memory_clone, capsys):
    """`shutil.which("docker")` is wrong in BOTH directions, which is why
    engine.py's docstring calls it "true and useless".

    The false positive is Docker Desktop's WSL stub: on PATH, exits 1 for every
    command, and prints its complaint on STDOUT. The false NEGATIVE is worse and
    was undocumented -- a WSL box reaching the engine through interop has no
    Linux `docker` at all and `tstack services` works perfectly, while this told
    the user "no docker on PATH" and skipped the restart.
    """
    _backend(monkeypatch, "none")
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.WSL_SHIM)
    monkeypatch.delenv("TS_STACK_ENGINE_UP", raising=False)

    assert config.main(["memory", "headroom"]) == 0
    assert ["restart", "headroom"] not in memory_clone["services"]
    out = capsys.readouterr().out
    assert "WSL Integration" in out, "it routes through engine_advice, not its own copy"
    # The file edit is NEVER gated on the engine: it is a file edit.
    assert "docker-compose.memory.yml" in memory_clone["env"].read_text(encoding="utf-8")


def test_a_missing_docker_says_what_to_run_later_rather_than_failing(
    monkeypatch, memory_clone, capsys
):
    """The setting is still saved. A machine with no engine is not a broken one."""
    _backend(monkeypatch, "none")
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.ABSENT)

    assert config.main(["memory", "headroom"]) == 0
    out = capsys.readouterr().out
    assert "no container engine found" in out
    assert "tstack services restart headroom" in out
    assert ["restart", "headroom"] not in memory_clone["services"]


def test_a_denied_engine_is_told_about_the_distro_s_own_door(monkeypatch, memory_clone, capsys):
    """Omarchy declines the docker group on purpose -- membership is equivalent
    to passwordless root -- so this must never tell an Omarchy user to `usermod`.
    Routing through engine_advice is what makes that true here for free."""
    _backend(monkeypatch, "none")
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.DENIED)

    monkeypatch.setattr(plat, "is_omarchy", lambda: True)
    assert config.main(["memory", "headroom"]) == 0
    out = capsys.readouterr().out
    assert "omarchy-setup-security-sudoless-docker" in out
    assert "usermod" not in out

    monkeypatch.setattr(plat, "is_omarchy", lambda: False)
    assert config.main(["memory", "headroom"]) == 0
    assert "usermod -aG docker" in capsys.readouterr().out


def test_config_wizard_saves_where_bare_wizard_only_asks(monkeypatch):
    """Two commands, two jobs, and conflating them threw away every answer.

    `tstack wizard` ASKS -- it collects and emits, and persists nothing, which is
    what lets the four bootstraps own their own save order. `tstack config
    wizard` asks and then SAVES AND INSTALLS, which is ts-config.sh's
    `run_wizard`, which in turn calls the Python questionnaire. Handing straight
    to `tstack wizard` collected the answers and discarded them.
    """
    assert "wizard" in config.DELEGATED
    assert "wizard" not in config.HANDOFF

    seen: list[list[str]] = []

    class Done:
        returncode = 0

    monkeypatch.setattr(config.paths, "resolve_source_dir", lambda: ROOT)
    monkeypatch.setattr(config.subprocess, "run", lambda argv, **kw: (seen.append(argv), Done())[1])
    assert config.main(["wizard"]) == 0
    assert seen and seen[0][-1] == "wizard"
    assert "ts-config.sh" in seen[0][1], "it must reach run_wizard, not tstack wizard"

    # ...and the shell arm that does the saving still exists.
    body = (ROOT / "bootstrap/ts-config.sh").read_text(encoding="utf-8")
    assert "wizard|reconfigure) run_wizard ;;" in body
    run_wizard = body[body.index("run_wizard() {") :]
    for setter in ("ts_save_config", "ts_memory_apply", "ts_atuin_set", "ts_starship_set"):
        assert setter in run_wizard, f"run_wizard stopped calling {setter}"


def test_help_on_a_delegated_verb_never_reaches_the_shell(monkeypatch):
    """The near-miss worth a permanent test.

    `ts-config.sh` dispatches on `case "$1"` and ignores everything after it, so
    forwarding `-h` to it does not print help -- it RUNS the verb. For `wizard`
    and `reconfigure` that means asking every install question and installing
    packages because somebody typed a help flag.
    """

    def explode(*a, **kw):  # pragma: no cover - the point is that it is not called
        raise AssertionError("-h reached the shell")

    monkeypatch.setattr(config.subprocess, "run", explode)
    for verb in config.DELEGATED:
        for flag in ("-h", "--help", "help"):
            assert config.main([verb, flag]) == 0, f"{verb} {flag}"
    assert set(config.DELEGATED) <= set(config.DELEGATED_HELP), "a verb with no help text"
