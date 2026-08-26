"""`tstack services`, driven directly, with no Docker anywhere.

The point of these is the half `tests/test_stack.py` cannot reach from a child
process: what each verb *does* to the engine, in order, when the answers are
controlled. Every docker call goes through two seams (`stacks.docker` for one-shot
calls, `Compose.run` for compose) so both are recorded rather than run.

The data-safety rules are the ones worth having here. `down` never carries -v,
`--purge` is the only path that removes a memory volume, a backup is verified
before anything is torn down, and a secret is never printed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tstack import engine, paths, stacks, store
from tstack.commands import services

# --------------------------------------------------------------------- fixtures


@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A believable stack tree: two stacks, one ordered after the other."""
    root = tmp_path / "services" / "stacks"
    for name in ("agentmemory", "agent007memory", "headroom"):
        (root / name).mkdir(parents=True)
        (root / name / "docker-compose.yml").write_text(
            f"name: ts-{name}\nservices: {{}}\n", encoding="utf-8"
        )
    (root / "agent007memory" / "ts-after").write_text(
        "# joins the network agentmemory creates\nagentmemory\n", encoding="utf-8"
    )
    (root / "headroom" / ".env.example").write_text("HEADROOM_PROXY_TOKEN=changeme\n", "utf-8")
    monkeypatch.setenv("TS_STACK_ROOT", str(root))
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.NATIVE)
    monkeypatch.setenv("NO_COLOR", "1")
    return tmp_path


@pytest.fixture
def store_off(monkeypatch):
    """Every toggle off unless a test says otherwise."""
    values: dict[str, str] = {}
    monkeypatch.setattr(store, "get", lambda key, default=None: values.get(key, default or ""))
    return values


@pytest.fixture
def calls(monkeypatch):
    """Record every docker and compose invocation instead of running it."""
    recorded: dict[str, list] = {"docker": [], "compose": []}
    answers: dict[str, tuple[int, str]] = {}

    def fake_docker(kind, args, timeout=60):
        recorded["docker"].append(args)
        for needle, answer in answers.items():
            if needle in " ".join(args):
                return answer
        return (0, "")

    def fake_run(self, stack, args, capture=False):
        recorded["compose"].append((stack, args))
        import subprocess

        return subprocess.CompletedProcess(["docker", "compose", *args], 0, "", "")

    monkeypatch.setattr(stacks, "docker", fake_docker)
    monkeypatch.setattr(stacks.Compose, "run", fake_run)
    recorded["answers"] = answers  # type: ignore[assignment]
    return recorded


def build(tree_root: Path, *argv: str) -> services.Services:
    svc = services.Services(tree_root, services.parse(list(argv)))
    svc.stacks = list(svc.all_stacks)
    return svc


# ------------------------------------------------------------------- discovery


def test_a_stack_is_a_directory_with_a_compose_file(tree):
    (stacks.stack_root(tree) / "not-a-stack").mkdir()
    assert stacks.stack_list(tree) == ["agentmemory", "agent007memory", "headroom"]


def test_ts_after_moves_a_stack_behind_the_network_it_joins(tree):
    """agent007memory sorts BEFORE agentmemory ('0' < 'm'), and an external
    network cannot be joined before it exists."""
    order = stacks.stack_list(tree)
    assert order.index("agentmemory") < order.index("agent007memory")


def test_a_cycle_leaves_the_order_alone_rather_than_hanging(tree):
    root = stacks.stack_root(tree)
    (root / "agentmemory" / "ts-after").write_text("agent007memory\n", encoding="utf-8")
    assert sorted(stacks.stack_list(tree)) == ["agent007memory", "agentmemory", "headroom"]


def test_an_unreadable_ts_after_is_ignored_not_fatal(tree):
    root = stacks.stack_root(tree)
    (root / "headroom" / "ts-after").write_text("   \n#comment\nno-such-stack\n", encoding="utf-8")
    assert "headroom" in stacks.stack_list(tree)


# --------------------------------------------------------------------- toggles


def test_a_stack_whose_setting_is_off_is_skipped_not_broken(tree, store_off, calls):
    store_off["agentmemoryEnabled"] = "off"
    svc = build(tree, "up")
    services.cmd_up(svc)
    assert [s for s, _ in calls["compose"]] == [], "an off stack was started"
    assert svc.out.issues == 0, "an off stack was reported as a problem"


def test_naming_a_stack_is_consent(tree, store_off, calls):
    store_off["headroomEnabled"] = "off"
    svc = services.Services(tree, services.parse(["up", "headroom"]))
    svc.stacks = ["headroom"]
    svc.args.all = True
    services.cmd_up(svc)
    assert [s for s, _ in calls["compose"]] == ["headroom"]


def test_an_ungated_stack_always_takes_part(tree, store_off, calls):
    assert stacks.stack_state("something-new") == ""


# --------------------------------------------------------------- the argv rules


def test_down_runs_in_reverse_and_never_carries_dash_v(tree, store_off, calls):
    for key in ("agentmemoryEnabled", "headroomEnabled"):
        store_off[key] = "on"
    svc = build(tree, "down")
    services.cmd_down(svc)
    names = [s for s, _ in calls["compose"]]
    assert names.index("agent007memory") < names.index("agentmemory"), names
    for _, args in calls["compose"]:
        assert "-v" not in args, args


def test_restart_takes_everything_down_before_bringing_anything_up(tree, store_off, calls):
    """Restarting agentmemory while agent007memory still holds ts-agentmemory-net
    leaves the console pointed at a container that no longer exists."""
    for key in ("agentmemoryEnabled", "headroomEnabled"):
        store_off[key] = "on"
    svc = build(tree, "restart")
    services.cmd_restart(svc)
    verbs = [args[0] for _, args in calls["compose"]]
    assert verbs == ["down"] * 3 + ["up"] * 3, verbs
    assert "restart" not in verbs, "compose restart reuses the container and ignores .env"


def test_dry_run_prints_the_argv_and_runs_nothing(tree, capsys):
    compose = stacks.Compose(tree, engine.NATIVE, dry_run=True)
    got = compose.run("agentmemory", ["up", "-d"])
    assert got.returncode == 0
    assert capsys.readouterr().out.strip() == "(agentmemory) docker compose up -d"


def test_the_dry_run_line_names_the_binary_that_would_actually_run(tree, capsys):
    stacks.Compose(tree, engine.WSL_SHIM, dry_run=True).run("agentmemory", ["down"])
    assert "docker.exe compose down" in capsys.readouterr().out


# --------------------------------------------------------------------- volumes


def test_up_refuses_while_a_legacy_volume_has_no_replacement(tree, store_off, calls, monkeypatch):
    store_off["agentmemoryEnabled"] = "on"
    monkeypatch.setattr(stacks, "volumes_pending", lambda kind: [("old", "ts-agentmemory-data")])
    svc = build(tree, "up")
    with pytest.raises(SystemExit) as raised:
        services.cmd_up(svc)
    assert raised.value.code == 1
    assert calls["compose"] == []


def test_volumes_pending_only_reports_a_pair_whose_new_name_is_absent(monkeypatch):
    existing = {"agentmemory_iii-data", "headroom_qdrant_data", "ts-headroom-qdrant"}
    monkeypatch.setattr(stacks, "volume_exists", lambda kind, name: name in existing)
    assert stacks.volumes_pending(engine.NATIVE) == [
        ("agentmemory_iii-data", "ts-agentmemory-data")
    ]


def test_migrate_volumes_refuses_to_report_all_clear_without_an_engine(tree, calls, capsys):
    """With the engine down `docker volume inspect` fails for BOTH names, so an
    empty pending list means "unknown", not "current"."""
    svc = build(tree, "migrate-volumes")
    svc.engine_ok = False
    with pytest.raises(SystemExit) as raised:
        services.cmd_migrate_volumes(svc)
    assert raised.value.code == 1
    assert "cannot be read" in capsys.readouterr().out


def test_migrate_volumes_needs_consent_and_keeps_the_old_volume(tree, calls, monkeypatch, capsys):
    monkeypatch.setattr(stacks, "volumes_pending", lambda kind: [("old", "new")])
    monkeypatch.setattr(services, "_ask", lambda prompt: "n")
    svc = build(tree, "migrate-volumes")
    svc.engine_ok = True
    services.cmd_migrate_volumes(svc)
    assert "nothing copied" in capsys.readouterr().out
    assert calls["docker"] == []


def test_a_verified_copy_leaves_the_old_volume_as_the_rollback(tree, calls, monkeypatch, capsys):
    monkeypatch.setattr(stacks, "volumes_pending", lambda kind: [("old", "new")])
    monkeypatch.setattr(services, "_count_files", lambda svc, volume, mount: 41)
    svc = build(tree, "migrate-volumes")
    svc.engine_ok = True
    svc.args.assume_yes = True
    services.cmd_migrate_volumes(svc)
    flat = [" ".join(a) for a in calls["docker"]]
    assert any("volume create new" in f for f in flat)
    assert not any("volume rm" in f for f in flat), "the rollback was destroyed"
    assert "41 files" in capsys.readouterr().out


def test_a_short_copy_is_reported_and_nothing_is_removed(tree, calls, monkeypatch, capsys):
    counts = iter([100, 3])
    monkeypatch.setattr(services, "_count_files", lambda svc, volume, mount: next(counts))
    svc = build(tree, "migrate-volumes")
    assert services._volume_copy(svc, "old", "new") is False
    out = capsys.readouterr().out
    assert "100 files in, 3 out" in out
    assert "NOT removing anything" in out


# ---------------------------------------------------------------------- bootstrap


def test_bootstrap_seeds_env_files_and_leaves_an_existing_one_alone(tree, calls, capsys):
    root = stacks.stack_root(tree)
    (tree / "bootstrap").mkdir()
    (tree / "bootstrap" / "agent-tools.json").write_text("{}", encoding="utf-8")
    svc = build(tree, "bootstrap")
    services.cmd_bootstrap(svc)
    assert (root / "headroom" / ".env").read_text(
        encoding="utf-8"
    ) == "HEADROOM_PROXY_TOKEN=changeme\n"

    capsys.readouterr()
    services.cmd_bootstrap(svc)
    assert "left untouched" in capsys.readouterr().out


def test_bootstrap_never_creates_an_empty_replacement_for_a_legacy_volume(
    tree, calls, monkeypatch, capsys
):
    """Creating it here would DEFEAT the migration guard: pending pairs are only
    reported while the new name is absent."""
    (tree / "bootstrap").mkdir()
    (tree / "bootstrap" / "agent-tools.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        services,
        "_external_volumes",
        lambda source: ["ts-agentmemory-data"],
    )
    monkeypatch.setattr(stacks, "volume_exists", lambda kind, name: name == "agentmemory_iii-data")
    svc = build(tree, "bootstrap")
    services.cmd_bootstrap(svc)
    out = capsys.readouterr().out
    assert "NOT creating an empty" in out
    assert "migrate-volumes" in out
    assert not any("volume create" in " ".join(a) for a in calls["docker"])


def test_a_generated_secret_is_fingerprinted_never_printed(tree, calls, capsys):
    root = stacks.stack_root(tree)
    (root / "headroom" / ".env").write_text("HEADROOM_PROXY_TOKEN=changeme\n", encoding="utf-8")
    (tree / "bootstrap").mkdir()
    (tree / "bootstrap" / "agent-tools.json").write_text(
        json.dumps(
            {
                "headroom": {
                    "generatedSecrets": [
                        {"key": "HEADROOM_PROXY_TOKEN", "placeholder": "changeme", "bytes": 32}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    svc = build(tree, "bootstrap")
    services.cmd_bootstrap(svc)
    written = stacks.env_value(root / "headroom" / ".env", "HEADROOM_PROXY_TOKEN")
    assert written and written != "changeme" and len(written) == 32
    out = capsys.readouterr().out
    assert written not in out, "the secret was printed"
    assert f"{written[:6]}...{written[-4:]}" in out


def test_a_secret_somebody_set_is_never_rotated(tree, calls, capsys):
    root = stacks.stack_root(tree)
    (root / "headroom" / ".env").write_text("HEADROOM_PROXY_TOKEN=mine\n", encoding="utf-8")
    svc = build(tree, "bootstrap")
    services._fill_secret(svc, root / "headroom" / ".env", "HEADROOM_PROXY_TOKEN", "changeme", 32)
    assert stacks.env_value(root / "headroom" / ".env", "HEADROOM_PROXY_TOKEN") == "mine"
    assert "already set" in capsys.readouterr().out


def test_external_volumes_are_read_out_of_the_compose_files(tree):
    root = stacks.stack_root(tree)
    (root / "agentmemory" / "docker-compose.yml").write_text(
        "name: ts-agentmemory\n"
        "services:\n"
        "  server:\n"
        "    image: x\n"
        "volumes:\n"
        "  ts-agentmemory-data:\n"
        "    external: true\n"
        "  scratch:\n"
        "    driver: local\n",
        encoding="utf-8",
    )
    assert services._external_volumes(tree) == ["ts-agentmemory-data"]


# ------------------------------------------------------------------------ checks


def test_check_files_pick_up_the_overlays_this_machine_selected(tree):
    d = stacks.stack_dir(tree, "headroom")
    (d / "ts-checks.conf").write_text("health ts-headroom-proxy up 60 -\n", encoding="utf-8")
    (d / "ts-checks.memory.conf").write_text("port ts-qdrant - - 6333\n", encoding="utf-8")
    (d / "docker-compose.memory.yml").write_text("services: {}\n", encoding="utf-8")
    (d / ".env").write_text(
        "COMPOSE_FILE=docker-compose.yml:docker-compose.memory.yml\n", encoding="utf-8"
    )
    names = [p.name for p in stacks.check_files(tree, "headroom")]
    assert names == ["ts-checks.conf", "ts-checks.memory.conf"]


def test_an_overlay_nobody_selected_is_not_checked(tree):
    d = stacks.stack_dir(tree, "headroom")
    (d / "ts-checks.conf").write_text("health x up 60 -\n", encoding="utf-8")
    (d / "ts-checks.memory.conf").write_text("port y - - 6333\n", encoding="utf-8")
    assert [p.name for p in stacks.check_files(tree, "headroom")] == ["ts-checks.conf"]


def test_comments_and_blank_lines_are_not_checks(tmp_path):
    conf = tmp_path / "ts-checks.conf"
    conf.write_text("# a note\n\nhttp id - 10 http://127.0.0.1:1\n", encoding="utf-8")
    got = stacks.read_checks(conf)
    assert len(got) == 1 and got[0].kind == "http"


def test_a_port_range_still_matches_the_port_inside_it(tree, calls):
    """Docker collapses contiguous ports, so 3113 appears as
    `127.0.0.1:3112-3113->3112-3113/tcp` and a literal `:3113->` finds nothing."""
    calls["answers"]["ps --format"] = (0, "127.0.0.1:3112-3113->3112-3113/tcp\n")
    svc = build(tree, "status")
    assert services.port_publication(svc, "3113") == 0


def test_a_port_published_beyond_loopback_is_told_apart_from_an_absent_one(tree, calls):
    """Three outcomes, not two: a check that cannot tell "absent" from "bad"
    reports the wrong one."""
    calls["answers"]["ps --format"] = (0, "0.0.0.0:8880->8880/tcp\n")
    svc = build(tree, "status")
    assert services.port_publication(svc, "8880") == 1
    assert services.port_publication(svc, "9999") == 2


def test_the_loopback_audit_ignores_other_peoples_containers(tree, calls):
    calls["answers"]["--filter name=ts-"] = (
        0,
        "ts-kokoro 127.0.0.1:8880->8880/tcp\nts-leaky 0.0.0.0:9999->9999/tcp\n",
    )
    svc = build(tree, "status")
    exposed = services.audit_loopback(svc)
    assert len(exposed) == 1 and "ts-leaky" in exposed[0]


def test_an_unknown_check_kind_warns_rather_than_failing_the_run(tree, calls, capsys):
    svc = build(tree, "test")
    check = stacks.Check("wat", "id", "-", "5", "-")
    assert services._run_one_check(svc, "headroom", check) is True
    assert "unknown check kind" in capsys.readouterr().out


# ------------------------------------------------------------------------ backup


def test_a_backup_is_verified_before_anything_is_torn_down(tree, calls, monkeypatch, tmp_path):
    monkeypatch.setenv("TS_STACK_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setattr(stacks, "volume_exists", lambda kind, name: name == "ts-agentmemory-data")

    def fake_docker(kind, args, timeout=60):
        calls["docker"].append(args)
        joined = " ".join(args)
        if "tar -C /from" in joined:
            # The tar runs in a container; fake its output landing on the host.
            # rsplit, not split: a Windows host path starts with "C:".
            out = next(a for a in args if a.endswith(":/to")).rsplit(":/to", 1)[0]
            Path(out).mkdir(parents=True, exist_ok=True)
            (Path(out) / "ts-agentmemory-data.tgz").write_bytes(b"x" * 4096)
        return (0, "")

    monkeypatch.setattr(stacks, "docker", fake_docker)
    svc = build(tree, "backup")
    svc.engine_ok = True
    assert services.backup_all(svc) is True
    joined = [" ".join(a) for a in calls["docker"]]
    assert any("tar -C /from" in j for j in joined), "nothing was archived"
    assert any("tar -tzf" in j for j in joined), "the archive was never read back"


def test_a_suspiciously_small_archive_fails_the_backup(tree, calls, monkeypatch, tmp_path):
    monkeypatch.setenv("TS_STACK_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setattr(stacks, "volume_exists", lambda kind, name: True)
    monkeypatch.setattr(stacks, "data_volumes", lambda kind: ["ts-agentmemory-data"])
    svc = build(tree, "backup")
    svc.engine_ok = True
    assert services.backup_all(svc) is False


def test_backup_lists_the_memory_volumes_first_and_includes_legacy_names(monkeypatch):
    """Listing only the new names made backup a no-op on exactly the machine that
    needed it most: the one about to migrate."""
    monkeypatch.setattr(
        stacks,
        "volume_exists",
        lambda kind, name: name in ("ts-agentmemory-data", "headroom_qdrant_data"),
    )
    got = stacks.data_volumes(engine.NATIVE)
    assert got[0] == "ts-agentmemory-data"
    assert "headroom_qdrant_data" in got


def test_the_backup_root_never_hard_codes_one_persons_path(monkeypatch):
    monkeypatch.delenv("TS_STACK_BACKUP_ROOT", raising=False)
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("XDG_STATE_HOME", "/state")
    got = stacks.backup_dir()
    assert got.parent.as_posix().endswith("terminal-stack/stack-backups")


# ------------------------------------------------------------------------- reset


def test_reset_destroys_nothing_without_the_typed_phrase(tree, calls, monkeypatch, capsys):
    monkeypatch.setattr(services, "_ask", lambda prompt: "yes please")
    monkeypatch.setattr(services, "backup_all", lambda svc: True)
    svc = build(tree, "reset", "--destroy-data")
    svc.engine_ok = True
    with pytest.raises(SystemExit) as raised:
        services.cmd_reset(svc)
    assert raised.value.code == 1
    assert "nothing was destroyed" in capsys.readouterr().out
    assert calls["compose"] == []


def test_only_purge_removes_a_memory_volume(tree, calls, monkeypatch, store_off):
    """The two memory volumes are external, so `down -v` cannot touch them. That
    asymmetry is the safety property, and removing them needs its own path.

    The typed phrase differs between the two levels on purpose: answering the
    milder prompt must not be enough to destroy every memory you have.
    """
    monkeypatch.setattr(services, "backup_all", lambda svc: True)
    store_off["agentmemoryEnabled"] = "on"

    monkeypatch.setattr(services, "_ask", lambda prompt: "destroy headroom data")
    svc = build(tree, "reset", "--destroy-data")
    svc.engine_ok = True
    services.cmd_reset(svc)
    assert not any("volume rm" in " ".join(a) for a in calls["docker"])

    calls["docker"].clear()
    monkeypatch.setattr(services, "_ask", lambda prompt: "destroy all memories")
    svc = build(tree, "reset", "--purge")
    svc.engine_ok = True
    services.cmd_reset(svc)
    removed = [" ".join(a) for a in calls["docker"] if "volume rm" in " ".join(a)]
    assert len(removed) == 2, removed
    for volume in stacks.MEMORY_VOLUMES:
        assert any(volume in r for r in removed)


def test_reset_without_destroy_data_keeps_every_volume(tree, calls, store_off):
    store_off["agentmemoryEnabled"] = "on"
    svc = build(tree, "reset")
    svc.engine_ok = True
    services.cmd_reset(svc)
    for _, args in calls["compose"]:
        assert "-v" not in args


# ------------------------------------------------------------------------ doctor


def test_doctor_reports_a_derived_setting_that_has_drifted(tree, calls, store_off, capsys):
    store_off["memoryBackend"] = "headroom"
    store_off["agentmemoryEnabled"] = "on"
    svc = build(tree, "doctor")
    svc.engine_ok = False
    services._doctor_memory_backend(svc)
    out = capsys.readouterr().out
    assert "tstack config memory headroom" in out
    assert svc.out.issues == 1


def test_doctor_accepts_the_three_consistent_combinations(tree, calls, store_off):
    for backend, derived in (("agentmemory", "on"), ("headroom", "off"), ("none", "off")):
        store_off["memoryBackend"] = backend
        store_off["agentmemoryEnabled"] = derived
        svc = build(tree, "doctor")
        svc.engine_ok = False
        services._doctor_memory_backend(svc)
        assert svc.out.issues == 0, f"{backend}/{derived} was reported as drift"


def test_doctor_catches_a_headroom_proxy_running_without_memory(tree, calls, store_off, capsys):
    """THE bug the memoryBackend setting came from: databases up, memory never
    engaged, everything reporting healthy."""
    store_off["memoryBackend"] = "headroom"
    store_off["agentmemoryEnabled"] = "off"
    calls["answers"]["inspect ts-headroom-proxy"] = (0, '["node","proxy.js","--port","8787"]')
    calls["answers"]["name=ts-headroom-qdrant"] = (0, "ts-headroom-qdrant\n")
    calls["answers"]["name=ts-headroom-neo4j"] = (0, "ts-headroom-neo4j\n")
    svc = build(tree, "doctor")
    svc.engine_ok = True
    services._doctor_memory_backend(svc)
    out = capsys.readouterr().out
    assert "WITHOUT --memory" in out
    assert "restart headroom" in out


def test_doctor_is_quiet_when_the_proxy_has_memory(tree, calls, store_off, capsys):
    store_off["memoryBackend"] = "headroom"
    store_off["agentmemoryEnabled"] = "off"
    calls["answers"]["inspect ts-headroom-proxy"] = (0, '["node","proxy.js","--memory"]')
    calls["answers"]["name=ts-headroom-qdrant"] = (0, "ts-headroom-qdrant\n")
    calls["answers"]["name=ts-headroom-neo4j"] = (0, "ts-headroom-neo4j\n")
    svc = build(tree, "doctor")
    svc.engine_ok = True
    services._doctor_memory_backend(svc)
    assert svc.out.issues == 0
    assert "--memory" in capsys.readouterr().out


def test_doctor_notes_datastores_left_running_for_a_backend_nobody_uses(
    tree, calls, store_off, capsys
):
    store_off["memoryBackend"] = "agentmemory"
    store_off["agentmemoryEnabled"] = "on"
    calls["answers"]["name=ts-headroom-qdrant"] = (0, "ts-headroom-qdrant\n")
    svc = build(tree, "doctor")
    svc.engine_ok = True
    services._doctor_memory_backend(svc)
    out = capsys.readouterr().out
    assert "nothing writes to them" in out
    assert svc.out.issues == 0, "a leftover datastore is a note, not a failure"


def test_doctor_reports_a_stack_missing_its_env(tree, calls, store_off, capsys):
    svc = build(tree, "doctor")
    svc.engine_ok = False
    services.cmd_doctor(svc)
    out = capsys.readouterr().out
    assert "headroom: .env.example exists but .env does not" in out
    assert "compose config, health and the port audit need the engine" in out


# ------------------------------------------------------------------------ status


def test_status_reports_intent_and_reality_disagreeing_as_a_warning(
    tree, calls, store_off, capsys, monkeypatch
):
    store_off["agentmemoryEnabled"] = "off"

    def fake_quiet(self, stack, args):
        return (0, "abc123\n") if stack == "agentmemory" else (0, "")

    monkeypatch.setattr(stacks.Compose, "quiet", fake_quiet)
    svc = build(tree, "status")
    svc.engine_ok = True
    services.cmd_status(svc)
    out = capsys.readouterr().out
    assert "running, but agentmemoryEnabled=off" in out
    assert "tstack services down agentmemory" in out
    assert svc.out.issues == 1


def test_status_reports_a_partial_stack(tree, calls, store_off, capsys, monkeypatch):
    store_off["agentmemoryEnabled"] = "on"

    def fake_quiet(self, stack, args):
        if stack != "agentmemory":
            return (0, "")
        return (0, "a\n") if "--status" in args else (0, "a\nb\n")

    monkeypatch.setattr(stacks.Compose, "quiet", fake_quiet)
    svc = build(tree, "status")
    svc.engine_ok = True
    services.cmd_status(svc)
    assert "partial (1/2)" in capsys.readouterr().out


def test_status_lists_the_published_ports_of_a_healthy_stack(
    tree, calls, store_off, capsys, monkeypatch
):
    store_off["agentmemoryEnabled"] = "on"

    def fake_quiet(self, stack, args):
        if stack != "agentmemory":
            return (0, "")
        if "Publishers" in " ".join(args):
            return (0, "127.0.0.1:3112->3112/tcp, 127.0.0.1:3110->3110/tcp\n")
        return (0, "a\n")

    monkeypatch.setattr(stacks.Compose, "quiet", fake_quiet)
    svc = build(tree, "status")
    svc.engine_ok = True
    services.cmd_status(svc)
    assert "running (1/1)  3110 3112" in capsys.readouterr().out


def test_status_calls_a_stack_that_was_never_created_a_problem(tree, calls, store_off, capsys):
    store_off["agentmemoryEnabled"] = "on"
    svc = build(tree, "status")
    svc.engine_ok = True
    services.cmd_status(svc)
    assert "not created" in capsys.readouterr().out
    assert svc.out.issues >= 1


# -------------------------------------------------------------------------- test


def test_the_test_verb_stops_before_teardown_when_preflight_fails(
    tree, calls, store_off, monkeypatch, capsys
):
    """`compose config -q` names a missing required value HERE, not after the
    teardown, which is the whole reason preflight is the exhaustive phase."""
    store_off["headroomEnabled"] = "on"
    monkeypatch.setattr(stacks.Compose, "quiet", lambda self, stack, args: (1, "boom"))
    svc = build(tree, "test")
    svc.engine_ok = True
    with pytest.raises(SystemExit) as raised:
        services.cmd_test(svc)
    assert raised.value.code == 2
    assert calls["compose"] == [], "something was torn down after a failed preflight"


def test_the_test_verb_refuses_without_an_engine(tree, calls, capsys):
    svc = build(tree, "test")
    svc.engine_ok = False
    with pytest.raises(SystemExit) as raised:
        services.cmd_test(svc)
    assert raised.value.code == 2
    assert "engine unreachable" in capsys.readouterr().out


def test_no_backup_is_taken_when_no_volume_is_at_risk(tree, calls, store_off, monkeypatch, capsys):
    monkeypatch.setattr(stacks.Compose, "quiet", lambda self, stack, args: (0, ""))
    monkeypatch.setattr(stacks, "volumes_pending", lambda kind: [])
    monkeypatch.setattr(services, "_snapshot_bytes", lambda: 0)
    monkeypatch.setattr(services, "run_checks", lambda svc, stack: True)
    monkeypatch.setattr(services, "audit_loopback", lambda svc: [])
    taken = []
    monkeypatch.setattr(services, "backup_all", lambda svc: taken.append(1) or True)
    svc = build(tree, "test")
    svc.engine_ok = True
    services.cmd_test(svc)
    assert taken == []
    assert "no --destroy-data" in capsys.readouterr().out


def test_the_loopback_audit_runs_even_when_everything_else_failed(
    tree, calls, store_off, monkeypatch, capsys
):
    """A service reachable off-box is a security incident, not an outage."""
    store_off["agentmemoryEnabled"] = "on"
    monkeypatch.setattr(stacks.Compose, "quiet", lambda self, stack, args: (0, ""))
    monkeypatch.setattr(stacks, "volumes_pending", lambda kind: [])
    monkeypatch.setattr(services, "_snapshot_bytes", lambda: 0)
    monkeypatch.setattr(services, "run_checks", lambda svc, stack: False)
    monkeypatch.setattr(services, "audit_loopback", lambda svc: ["ts-leaky 0.0.0.0:9->9/tcp"])
    svc = build(tree, "test")
    svc.engine_ok = True
    services.cmd_test(svc)
    assert "publishes beyond loopback" in capsys.readouterr().out


# ------------------------------------------------------------------------- misc


def test_the_engine_advice_names_a_fix_for_every_state():
    for os_kind in (engine.DARWIN, engine.LINUX, engine.WINDOWS):
        for kind in (engine.NATIVE, engine.ABSENT, engine.DENIED, engine.WSL_SHIM):
            lines = engine.engine_advice(os_kind, kind)
            assert lines, f"{os_kind}/{kind} has no advice"
            assert any("fix" in line for line in lines), f"{os_kind}/{kind} names no fix"


def test_engine_advice_is_ascii_only():
    """A Windows console on codepage 437 renders an em dash as a replacement
    glyph, and this text is what someone acts on when nothing else works."""
    for os_kind in (engine.DARWIN, engine.LINUX, engine.WINDOWS):
        for kind in (engine.NATIVE, engine.ABSENT, engine.DENIED, engine.WSL_SHIM):
            for line in engine.engine_advice(os_kind, kind):
                assert line.isascii(), line


def test_env_value_survives_crlf_and_leading_whitespace(tmp_path):
    f = tmp_path / ".env"
    f.write_bytes(b"# note\r\n  KEY=value  \r\nOTHER=2\r\n")
    assert stacks.env_value(f, "KEY") == "value"
    assert stacks.env_value(f, "MISSING") is None
    assert stacks.env_value(tmp_path / "nope", "KEY") is None


def test_replace_in_file_keeps_the_line_endings_it_found(tmp_path):
    """sed appends a trailing newline to a file that lacked one, and universal
    newline translation would silently rewrite a CRLF file to LF."""
    f = tmp_path / "x.env"
    f.write_bytes(b"A=1\r\nB=2\r\n")
    assert stacks.replace_in_file(f, "^B=.*$", "B=3") is True
    assert f.read_bytes() == b"A=1\r\nB=3\r\n"
    assert stacks.replace_in_file(f, "^NOPE=.*$", "x") is False


def test_an_env_seeded_stack_is_one_with_no_example_or_a_real_env(tmp_path):
    assert stacks.env_seeded(tmp_path) is True
    (tmp_path / ".env.example").write_text("x", encoding="utf-8")
    assert stacks.env_seeded(tmp_path) is False
    (tmp_path / ".env").write_text("x", encoding="utf-8")
    assert stacks.env_seeded(tmp_path) is True


def test_compose_files_follow_the_machines_own_env(tmp_path):
    assert stacks.compose_files(tmp_path) == ["docker-compose.yml"]
    (tmp_path / ".env").write_text(
        "COMPOSE_PATH_SEPARATOR=;\nCOMPOSE_FILE=a.yml; b.yml\n", encoding="utf-8"
    )
    assert stacks.compose_files(tmp_path) == ["a.yml", "b.yml"]


def test_the_parser_rejects_two_commands_and_two_stacks():
    with pytest.raises(services.Usage):
        services.parse(["up", "down"])
    with pytest.raises(services.Usage):
        services.parse(["up", "one", "two"])
    with pytest.raises(services.Usage):
        services.parse(["--tail"])
    with pytest.raises(services.Usage):
        services.parse(["--stack"])
    with pytest.raises(services.Usage):
        services.parse(["--wat"])


def test_purge_implies_destroy_data():
    args = services.parse(["reset", "--purge"])
    assert args.purge and args.destroy_data


def test_colour_is_off_when_anything_says_so(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert services._use_colour(False) is False
    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("TSS_COLOR", "never")
    assert services._use_colour(False) is False
    monkeypatch.setenv("TSS_COLOR", "always")
    assert services._use_colour(False) is True
    assert services._use_colour(True) is False


def test_the_output_gutter_lines_up(capsys):
    out = services.Out(colour=False, apply=True)
    out.ok("a")
    out.bad("b")
    out.skip("c")
    out.note("d")
    lines = capsys.readouterr().out.splitlines()
    assert [len(line) - len(line.lstrip()) for line in lines[:1]] == [2]
    assert out.issues == 1
    assert all(len(line.split()[0]) <= 4 for line in lines if line.strip())


def test_apply_and_preview_tags_are_the_same_width(capsys):
    services.Out(colour=False, apply=True).step("x")
    doing = capsys.readouterr().out.rstrip("\n")
    services.Out(colour=False, apply=False).step("x")
    would = capsys.readouterr().out.rstrip("\n")
    assert len(doing) == len(would), f"{doing!r} vs {would!r}"


# ------------------------------------------------------------- the entry point


def test_help_works_when_everything_else_is_broken(monkeypatch, capsys):
    """-h has to work on a box where the clone, the config store or docker is the
    very thing that is broken, so it is answered before any of them is touched."""

    def explode():
        raise AssertionError("the clone was resolved before printing help")

    monkeypatch.setattr(paths, "resolve_source_dir", explode)
    assert services.main(["-h"]) == 0
    assert "tstack services" in capsys.readouterr().out


def test_a_missing_clone_is_reported_not_crashed(monkeypatch, capsys):
    def missing(**kwargs):
        raise paths.CloneNotFound("no clone")

    monkeypatch.setattr(paths, "resolve_source_dir", missing)
    assert services.main(["status"]) == 1
    assert "cannot locate the service tree" in capsys.readouterr().err


def test_a_clone_with_no_service_tree_is_reported(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("TS_STACK_ROOT", raising=False)
    monkeypatch.setattr(paths, "resolve_source_dir", lambda **kwargs: tmp_path)
    assert services.main(["status"]) == 1
    assert "cannot locate the service tree" in capsys.readouterr().err


def test_an_empty_service_tree_says_so(monkeypatch, tmp_path, capsys):
    root = tmp_path / "services" / "stacks"
    root.mkdir(parents=True)
    monkeypatch.setenv("TS_STACK_ROOT", str(root))
    monkeypatch.setattr(paths, "resolve_source_dir", lambda **kwargs: tmp_path)
    assert services.main(["status"]) == 1
    assert "no stacks found" in capsys.readouterr().err


def test_an_unknown_stack_lists_the_real_ones(tree, monkeypatch, capsys):
    monkeypatch.setattr(paths, "resolve_source_dir", lambda **kwargs: tree)
    assert services.main(["up", "nope"]) == 2
    err = capsys.readouterr().err
    assert "no stack named 'nope'" in err
    assert "agentmemory" in err, "the message does not say what the real names are"


def test_logs_without_a_stack_is_a_usage_error_everywhere(tree, monkeypatch, capsys):
    monkeypatch.setattr(paths, "resolve_source_dir", lambda **kwargs: tree)
    assert services.main(["logs"]) == 2
    assert "logs needs a stack name" in capsys.readouterr().err


def test_status_exits_one_when_it_found_something(tree, store_off, monkeypatch, capsys):
    store_off["agentmemoryEnabled"] = "on"
    monkeypatch.setattr(paths, "resolve_source_dir", lambda **kwargs: tree)
    monkeypatch.setattr(engine, "is_up", lambda kind=None: True)
    monkeypatch.setattr(stacks.Compose, "quiet", lambda self, stack, args: (0, ""))
    assert services.main(["status"]) == 1
    assert "issue(s) found" in capsys.readouterr().out


def test_a_mutating_verb_without_an_engine_stops_and_advises(tree, monkeypatch, capsys):
    monkeypatch.setattr(paths, "resolve_source_dir", lambda **kwargs: tree)
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.ABSENT)
    assert services.main(["up"]) == 1
    got = capsys.readouterr()
    assert "engine unreachable" in got.out
    assert "fix:" in got.err, "the advice must reach stderr with the failure"


def test_dry_run_says_that_nothing_changed(tree, monkeypatch, capsys):
    monkeypatch.setattr(paths, "resolve_source_dir", lambda **kwargs: tree)
    assert services.main(["down", "--all", "--dry-run"]) == 0
    assert "Nothing changed (--dry-run)." in capsys.readouterr().out


def test_a_wsl_clone_the_engine_cannot_reach_is_refused_up_front(tree, monkeypatch, capsys):
    monkeypatch.setattr(paths, "resolve_source_dir", lambda **kwargs: tree)
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.WSL_SHIM)
    monkeypatch.setattr(engine, "require_windows_visible", lambda path: "9p, sorry")
    assert services.main(["up"]) == 1
    assert "9p, sorry" in capsys.readouterr().err


def test_start_engine_waits_for_the_engine_it_launched(tree, monkeypatch, capsys):
    launched = []
    monkeypatch.setattr(services.subprocess, "run", lambda *a, **k: launched.append(a[0]) or None)
    monkeypatch.setattr(services.time, "sleep", lambda seconds: None)
    answers = iter([False, False, True])
    monkeypatch.setattr(engine, "is_up", lambda kind=None: next(answers, True))
    monkeypatch.setattr(engine, "os_name", lambda: engine.LINUX)
    svc = build(tree, "up", "--start-engine")
    services._start_engine(svc)
    assert svc.engine_ok is True
    assert launched and "systemctl" in " ".join(launched[0])


def test_start_engine_on_macos_opens_docker(tree, monkeypatch):
    launched = []
    monkeypatch.setattr(services.subprocess, "run", lambda *a, **k: launched.append(a[0]) or None)
    monkeypatch.setattr(engine, "is_up", lambda kind=None: True)
    monkeypatch.setattr(engine, "os_name", lambda: engine.DARWIN)
    services._start_engine(build(tree, "up", "--start-engine"))
    assert launched == [["open", "-a", "Docker"]]


# --------------------------------------------------------------- config, logs


def test_config_shows_what_compose_resolves_to_for_each_selected_stack(tree, calls, store_off):
    store_off["agentmemoryEnabled"] = "on"
    svc = build(tree, "config")
    services.cmd_config(svc)
    assert [args for _, args in calls["compose"]] == [["config"], ["config"]]


def test_logs_passes_the_tail_and_follow_through(tree, calls):
    svc = services.Services(tree, services.parse(["logs", "agentmemory", "-n", "7", "-f"]))
    svc.stacks = ["agentmemory"]
    services.cmd_logs(svc)
    assert calls["compose"] == [("agentmemory", ["logs", "--tail", "7", "-f"])]


def test_an_unseeded_stack_is_warned_about_before_it_starts(tree, calls, capsys):
    svc = build(tree, "up")
    services.warn_unseeded(svc)
    assert "the stack will start with the wrong profile" in capsys.readouterr().out


def test_backup_refuses_without_an_engine(tree, calls, capsys):
    svc = build(tree, "backup")
    svc.engine_ok = False
    with pytest.raises(SystemExit) as raised:
        services.cmd_backup(svc)
    assert raised.value.code == 2


# ------------------------------------------------------------------ the checks


def test_a_health_check_passes_on_a_healthy_container(tree, calls, monkeypatch, capsys):
    calls["answers"]["State.Health"] = (0, "healthy\n")
    monkeypatch.setattr(services.time, "sleep", lambda seconds: None)
    svc = build(tree, "test")
    check = stacks.Check("health", "ts-x", "up", "4", "-")
    assert services._run_one_check(svc, "headroom", check) is True
    assert "ts-x healthy" in capsys.readouterr().out


def test_a_container_with_no_healthcheck_only_has_to_be_running(tree, calls, monkeypatch):
    calls["answers"]["State.Status"] = (0, "running\n")
    calls["answers"]["State.Health"] = (0, "\n")
    monkeypatch.setattr(services.time, "sleep", lambda seconds: None)
    svc = build(tree, "test")
    assert services._wait_healthy(svc, "ts-x", 4) is True


def test_a_failed_health_check_prints_the_container_log(tree, calls, monkeypatch, capsys):
    calls["answers"]["State.Status"] = (0, "restarting\n")
    calls["answers"]["State.Health"] = (0, "unhealthy\n")
    calls["answers"]["logs --tail"] = (0, "boom\nagain\n")
    monkeypatch.setattr(services.time, "sleep", lambda seconds: None)
    svc = build(tree, "test")
    check = stacks.Check("health", "ts-x", "up", "2", "-")
    assert services._run_one_check(svc, "headroom", check) is False
    out = capsys.readouterr().out
    assert "not healthy within 2s" in out
    assert "boom" in out, "the log that explains it was not shown"


def test_http_treats_any_answer_as_alive_and_http_ok_does_not(tree, calls, monkeypatch, capsys):
    """A 404 or a 401 is not "down" -- that distinction is why there are two kinds."""
    monkeypatch.setattr(services.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(services, "_http_code", lambda url: 404)
    svc = build(tree, "test")
    assert services._run_one_check(svc, "am", stacks.Check("http", "x", "-", "2", "u")) is True
    assert services._run_one_check(svc, "am", stacks.Check("http-ok", "x", "-", "2", "u")) is False
    monkeypatch.setattr(services, "_http_code", lambda url: 204)
    assert services._run_one_check(svc, "am", stacks.Check("http-ok", "x", "-", "2", "u")) is True


def test_a_refused_connection_is_not_an_answer(tree, monkeypatch):
    monkeypatch.setattr(services.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(services, "_http_code", lambda url: 0)
    assert services._wait_http("http://127.0.0.1:1", 2, "any") is False


def test_http_code_reports_the_status_of_an_error_response(monkeypatch):
    import urllib.error

    def raise_http(request, timeout=None):
        raise urllib.error.HTTPError("u", 401, "no", {}, None)

    monkeypatch.setattr(services.urllib.request, "urlopen", raise_http)
    assert services._http_code("http://127.0.0.1:1") == 401

    def refuse(request, timeout=None):
        raise OSError("refused")

    monkeypatch.setattr(services.urllib.request, "urlopen", refuse)
    assert services._http_code("http://127.0.0.1:1") == 0
    assert services._snapshot_bytes() == 0


def test_a_stack_with_no_checks_is_not_a_failure(tree, calls, capsys):
    svc = build(tree, "test")
    assert services.run_checks(svc, "headroom") is True
    assert "no ts-checks.conf" in capsys.readouterr().out


def test_run_checks_reports_every_file_it_found(tree, calls, monkeypatch, capsys):
    d = stacks.stack_dir(tree, "headroom")
    (d / "ts-checks.conf").write_text("port x - - 8787\nport y - - 8788\n", encoding="utf-8")
    calls["answers"]["ps --format"] = (0, "127.0.0.1:8787->8787/tcp\n")
    svc = build(tree, "test")
    assert services.run_checks(svc, "headroom") is False
    out = capsys.readouterr().out
    assert "published on 127.0.0.1:8787" in out
    assert "is not published at all" in out


def test_a_non_numeric_port_check_is_absent_rather_than_a_crash(tree, calls):
    svc = build(tree, "status")
    assert services.port_publication(svc, "not-a-port") == 2
