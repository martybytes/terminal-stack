"""tstack services: the service-lifecycle CLI.

The high-value tests here need no Docker, which is the point - most machines
running this suite have no engine, and the WSL ones have Docker Desktop's stub
(see test_docker_kind_calls_the_desktop_stub_what_it_is). What they pin instead
is the argv the CLI *would* run, which is where the data-safety contract lives.

These used to scan two shell twins for agreement. There is one implementation
now, so they exercise it instead: the rules are the same rules, checked against
behaviour rather than against two files' source text.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tstack import engine, stacks
from tstack.commands import services

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "tstack/main.py"


def test_there_is_exactly_one_help_text_and_it_covers_every_verb():
    """The old rule was "keep the two -h strings byte-identical", enforced by
    diffing bootstrap/ts-stack.sh against bootstrap/ts-stack.ps1. One
    implementation makes that structurally true, so what is worth pinning now is
    that the help and the dispatch table cannot drift apart -- a verb that runs
    but is undocumented is the same failure in a new place.
    """
    for verb in services.VERBS:
        listed = f"tstack services {verb}" in services.HELP
        # status is documented as the default, in brackets.
        listed = listed or f"tstack services [{verb}]" in services.HELP
        assert listed, f"{verb} is not in the help"
    for verb in services.VERBS:
        assert verb in services._HANDLERS, f"{verb} parses but has no handler"
    assert set(services._HANDLERS) == set(services.VERBS)
    # And nothing else in the repo carries a competing copy to drift from.
    assert not (ROOT / "bootstrap/ts-stack.sh").exists()
    assert not (ROOT / "bootstrap/ts-stack.ps1").exists()


def test_no_two_script_scope_pwsh_variables_differ_only_by_case():
    """PowerShell variable names are case-insensitive, so $STACK_ROOT (a
    directory) and $stacks (a list of names) would be ONE variable: the list
    clobbered the path, Join-Path built a doubled directory name, and Test-Path
    was handed an array so every compose call grew an --env-file pair. The
    existing AST test catches this for parameters; this catches it between two
    script-scope assignments, which is how it actually happened.

    Scope: assignments at column 0 only. A function parameter $Name beside a
    local $name in a different function is normal and safe -- the parameter wins
    inside its own body -- and flagging it would only teach everyone to delete
    the test.
    """
    offenders = []
    for f in sorted(ROOT.glob("bootstrap/*.ps1")) + sorted(ROOT.glob("scripts/*.ps1")):
        seen = {}
        for name in re.findall(r"^\$([A-Za-z_]\w*)\s*=", f.read_text(encoding="utf-8"), re.M):
            seen.setdefault(name.lower(), set()).add(name)
        for group in seen.values():
            if len(group) > 1:
                offenders.append(f"{f.name}: {sorted(group)} are the same variable")
    assert not offenders, "\n".join(offenders)


def test_every_stack_is_gated_on_the_right_saved_setting():
    """A stack gated on the wrong saved setting is skipped for the wrong reason.

    This was two files being scanned for the same strings, which is why the twins
    could both contain 'ccTts' while only one of them read it correctly -- see
    test_kokoro_reads_the_real_tts_keys.
    """
    for stack, key in (
        ("agentmemory", "agentmemoryEnabled"),
        ("agent007memory", "agentmemoryEnabled"),
        ("headroom", "headroomEnabled"),
        ("playwright", "playwrightEnabled"),
        ("kokoro", "ccTts"),
    ):
        assert stacks.toggle_for(stack) == key
    # A stack nobody gated runs everywhere, which is the safe default.
    assert stacks.toggle_for("something-new") == ""


def test_kokoro_reads_the_real_tts_keys(monkeypatch):
    """The bash twin asked for `enabled` and `engine`; the keys are `ccTtsEnabled`
    and `ccTtsEngine`. Its lookup therefore always missed, fell through to a
    default branch that ran the non-existent command `1`, and its `|| echo true`
    guard turned that failure into "TTS is on, engine kokoro" -- so kokoro was
    never once reported as off on macOS or Linux however the machine was set up,
    while the pwsh twin read the real values and disagreed.
    """
    from tstack import store

    seen: dict[str, str] = {}

    def fake_get(key, default=None):
        return seen.get(key, default if default is not None else "")

    monkeypatch.setattr(store, "get", fake_get)

    seen = {"ccTtsEnabled": "false", "ccTtsEngine": "kokoro"}
    assert stacks.stack_state("kokoro") == "voice notifications are off"

    seen = {"ccTtsEnabled": "true", "ccTtsEngine": "edge"}
    assert stacks.stack_state("kokoro") == "ccTts.engine=edge"

    seen = {"ccTtsEnabled": "true", "ccTtsEngine": "kokoro"}
    assert stacks.stack_state("kokoro") == ""


def test_only_ts_stack_may_run_docker():
    """The boundary that replaced the old inter-repo seam: services/ is the
    service side, everything outside it configures a host program. ts-agents may
    print the tstack services verb but never the compose command — the existing
    lifecycle-adapter test matches `docker compose` as a substring over the whole
    file, so even a helpful comment fails it."""
    text = (ROOT / "tstack/commands/agents.py").read_text(encoding="utf-8").lower()
    assert "docker compose" not in text, "tstack agents must not name the compose command"
    assert "docker rm" not in text
    assert "restart: unless-stopped" not in text
    # And the one place that may is the compose choke point. Every docker argv is
    # built there, which is the whole reason the invariants below are testable at
    # all: a second site would be a second set of rules nobody checks.
    argv = stacks.Compose(ROOT, engine.NATIVE).argv("agentmemory", ["up", "-d"])
    assert argv[:2] == ["docker", "compose"], argv
    builders = [
        f.name
        for f in sorted((ROOT / "tstack").rglob("*.py"))
        if '"compose"' in f.read_text(encoding="utf-8")
    ]
    assert builders == ["stacks.py"], f"compose argv is built in more than one place: {builders}"


# ── the argv contract ─────────────────────────────────────────────────────────
def _run_cli(*args):
    """The real entry point, in a child process, with no engine and no store.

    A child rather than an in-process call on purpose: exit codes and stderr are
    part of this CLI's contract, and the shims act on them.
    """
    env = dict(os.environ)
    env.update(
        {
            "TERMINAL_STACK_DIR": str(ROOT),
            "TS_STACK_DOCKER_PROBE": "absent",
            "NO_COLOR": "1",
            "PYTHONIOENCODING": "utf-8",
            # No chezmoi: every toggle falls back to its default, so the argv is a
            # property of the code rather than of the machine running the suite.
            "TERMINAL_STACK_CHEZMOI": str(ROOT / "no-such-chezmoi"),
        }
    )
    return subprocess.run(
        [sys.executable, str(MAIN), "services", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
        timeout=300,
        start_new_session=True,
    )


def _dry_run(*args):
    return _run_cli(*args, "--dry-run").stdout


def test_down_never_receives_dash_v():
    """`down -v` destroys the headroom knowledge graph and every vector. The
    invariant is that -v cannot reach this argv, and it is a test rather than a
    comment because a comment is what stack.sh had."""
    out = _dry_run("down", "--all")
    assert re.search(r"docker compose\b.*\bdown\b", out), out
    assert re.search(r"docker compose\b.*\s-v\b", out) is None, out
    assert "docker volume rm" not in out


def test_restart_is_down_then_up_not_compose_restart():
    """`docker compose restart` reuses the existing container, so it ignores the
    changed .env or overlay that is the whole reason anyone restarts."""
    out = _dry_run("restart", "agentmemory")
    assert re.search(r"docker compose\b.*\bdown\b", out), out
    assert re.search(r"docker compose\b.*\bup -d\b", out), out
    assert "docker compose restart" not in out
    assert out.index("down") < out.index("up -d")


def test_naming_a_stack_overrides_its_saved_toggle():
    """Asking by name is consent; otherwise a machine with the setting off could
    never start the stack to try it."""
    out = _dry_run("up", "headroom")
    assert re.search(r"\(headroom\) docker compose\b.*\bup -d\b", out), out


def test_status_survives_an_absent_engine():
    """The most common state on a fresh box, and on any box where Docker Desktop
    is not running. One headline, not a wall of failures."""
    r = _run_cli("status")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "engine unreachable" in r.stdout + r.stderr
    # One headline, and no stack reported as broken: with no engine their state is
    # unknown, not wrong. `!!` is the problem gutter, and it must not appear.
    assert "!!" not in r.stdout, r.stdout
    assert "all checks passed" in r.stdout


def test_a_usage_error_exits_two_and_a_failure_exits_one():
    """The shell twins blurred these: `logs` with no stack exited 1 on WSL because
    it had already handed off to pwsh, and 2 elsewhere. A caller cannot key off
    that. Usage is always 2."""
    assert _run_cli("definitely-not-a-verb").returncode == 2
    assert _run_cli("logs").returncode == 2
    assert _run_cli("up", "no-such-stack").returncode == 2
    assert _run_cli("--tail", "banana", "logs", "agentmemory").returncode == 2
    assert _run_cli("-h").returncode == 0


def test_docker_kind_calls_the_desktop_stub_what_it_is(tmp_path, monkeypatch):
    """`docker` on PATH inside WSL is Docker Desktop's stub when integration is
    off: it exits 1 for every command and prints its complaint on STDOUT, so
    `which docker` is true and useless. Diagnosing that as "is Docker Desktop
    running?" is wrong - the engine may be perfectly healthy on the Windows side.
    """
    stub = tmp_path / ("docker.bat" if os.name == "nt" else "docker")
    if os.name == "nt":
        stub.write_text(
            "@echo off\r\n"
            "echo The command 'docker' could not be found in this WSL 2 distro.\r\n"
            "exit /b 1\r\n",
            encoding="utf-8",
        )
    else:
        stub.write_text(
            "#!/bin/sh\n"
            "echo \"The command 'docker' could not be found in this WSL 2 distro.\"\n"
            "exit 1\n",
            encoding="utf-8",
        )
        stub.chmod(0o755)
    monkeypatch.delenv("TS_STACK_DOCKER_PROBE", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("PATHEXT", ".BAT;.EXE" if os.name == "nt" else "")
    assert engine.docker_kind() == engine.WSL_SHIM

    advice = "\n".join(engine.engine_advice(engine.LINUX, engine.WSL_SHIM))
    assert "WSL Integration" in advice, "the advice must name the actual fix"
    assert "is Docker Desktop running" not in advice


def test_the_wsl_shim_runs_docker_exe_rather_than_handing_off_to_pwsh():
    """The bash twin re-exec'd bootstrap/ts-stack.ps1 through interop, gave up
    entirely on a machine with no pwsh 7, and only ever covered five of the twelve
    verbs that way. One implementation reaches the same engine directly."""
    assert engine.binary_for(engine.WSL_SHIM) == "docker.exe"
    assert engine.binary_for(engine.NATIVE) == "docker"
    argv = stacks.Compose(ROOT, engine.WSL_SHIM).argv("agentmemory", ["up", "-d"])
    assert argv[0] == "docker.exe"


def test_a_wsl_only_clone_is_refused_before_anything_is_torn_down():
    """A Windows engine cannot bind-mount a \\\\wsl.localhost 9p path, and the
    failure surfaces inside a container as tar saying "Cannot open" - which reads
    as a broken archive rather than a broken mount, after the stack is down."""
    assert engine.require_windows_visible(Path("/mnt/c/Users/x/stack")) is None
    reason = engine.require_windows_visible(Path("/home/x/stack"))
    assert reason and "cannot bind-mount" in reason


# ── one resolution rule, six copies ───────────────────────────────────────────
def test_the_stack_env_file_resolves_from_the_clone_in_every_copy():
    """Five sites walked the workspace for a sibling docker-local clone. That
    could never work from the runtime clone (which is not under the workspace)
    and, post-merge, can only find a stale file from an archived repo -- whose
    token may be for a proxy that has since rotated, producing a 401 that reads
    like a broken install. There is no fallback to the old path on purpose."""
    posix = ("bootstrap/_config.sh", "dot_zshrc")
    windows = ("windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1",)
    # The agents implementation is Python now, and resolves the same way: from the
    # clone, never by walking a workspace for a sibling checkout.
    agents_py = (ROOT / "tstack/commands/agents.py").read_text(encoding="utf-8")
    assert 'source / "services" / "stacks" / "headroom" / ".env"' in agents_py
    assert "HEADROOM_ENV_FILE" in agents_py
    assert "docker-local" not in agents_py
    for rel in posix:
        body = (ROOT / rel).read_text(encoding="utf-8")
        # _config.sh takes the stack name as an argument; the rest name headroom.
        assert "services/stacks/headroom/.env" in body or "services/stacks/$1/.env" in body, rel
        assert "martybytes/docker-local" not in body, rel
    for rel in windows:
        body = (ROOT / rel).read_text(encoding="utf-8")
        assert "services\\stacks\\headroom\\.env" in body, rel
        assert "martybytes\\docker-local" not in body, rel
    # HEADROOM_ENV_FILE stays the documented override in all five.
    for rel in posix + windows:
        assert "HEADROOM_ENV_FILE" in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_no_runtime_file_points_at_the_absorbed_repo_by_name():
    """'docker-local owns it' pointed the reader at a repo they do not have."""
    for pattern in ("bootstrap/*.sh", "bootstrap/*.ps1", "scripts/*.ps1"):
        for f in sorted(ROOT.glob(pattern)):
            body = f.read_text(encoding="utf-8")
            if f.name == "_agentmemory.sh" or f.name == "_agentmemory.ps1":
                continue  # the secret-cache path migrates with a fallback; see its own test
            assert "docker-local" not in body, f"{f.name} still names the absorbed repo"


# ── the manifest and the compose tree must agree ──────────────────────────────
def test_manifest_and_compose_agree_on_pins_and_ports():
    """New, and only POSSIBLE now: the manifest pinned 0.36.5 and 8787 in one
    repo while the compose file pinned them in another, so the existing manifest
    test could stay green while compose ran a different image."""
    import json
    from urllib.parse import urlparse

    cfg = json.loads((ROOT / "bootstrap/agent-tools.json").read_text(encoding="utf-8"))

    hr_env = (ROOT / "services/stacks/headroom/.env.example").read_text(encoding="utf-8")
    assert f"HEADROOM_IMAGE={cfg['headroom']['dockerImage']}" in hr_env
    assert f"HEADROOM_PORT={urlparse(cfg['headroom']['proxyUrl']).port}" in hr_env
    assert f"HEADROOM_DASHBOARD_PORT={urlparse(cfg['headroom']['dashboardUrl']).port}" in hr_env

    am = (ROOT / "services/stacks/agentmemory/docker-compose.yml").read_text(encoding="utf-8")
    assert f'AGENTMEMORY_VERSION: "{cfg["agentmemory"]["version"]}"' in am
    # The REST port the agents are told to use is the CONSOLE's, which proxies the
    # server; the server's own listener is the 3110 bypass. Both must be published.
    assert f":{urlparse(cfg['agentmemory']['restUrl']).port}:" in (
        ROOT / "services/stacks/agent007memory/docker-compose.yml"
    ).read_text(encoding="utf-8")
    assert f":{urlparse(cfg['agentmemory']['viewerUrl']).port}:" in am


def test_every_published_port_binds_loopback_only():
    """None of these services authenticate. `"8880:8880"` would put one on the
    LAN, and the failure is silent until somebody else finds it."""
    import re as _re

    bad = []
    for f in sorted((ROOT / "services").rglob("docker-compose*.yml")):
        for m in _re.finditer(
            r'^\s*-\s*"?([0-9.]+:)?(\d+):\d+"?\s*$', f.read_text(encoding="utf-8"), _re.M
        ):
            if m.group(1) != "127.0.0.1:":
                bad.append(f"{f.relative_to(ROOT)}: {m.group(0).strip()}")
    assert not bad, "\n".join(bad)


# ── naming ────────────────────────────────────────────────────────────────────
def test_every_project_container_and_volume_is_ts_prefixed():
    """`docker ps` on this machine also shows three unrelated work stacks, so the
    prefix is what tells you at a glance which containers belong here. Projects
    used to be the directory name, containers mixed three conventions (bare
    `kokoro`, `headroom-proxy`, and nothing at all for the memory server -- which
    Docker then called `agentmemory-agentmemory-1`), and volumes were split
    between prefixed and bare."""
    expected_projects = {
        "agentmemory": "ts-agentmemory",
        "headroom": "ts-headroom",
        "kokoro": "ts-kokoro",
        "playwright": "ts-playwright",
    }
    for stack, project in expected_projects.items():
        base = (ROOT / "services/stacks" / stack / "docker-compose.yml").read_text(encoding="utf-8")
        assert f"\nname: {project}\n" in base, f"{stack}: project name not pinned"

    for f in sorted((ROOT / "services/stacks").rglob("docker-compose*.yml")):
        for line in f.read_text(encoding="utf-8").splitlines():
            t = line.strip()
            if t.startswith("container_name:"):
                assert t.split(":", 1)[1].strip().startswith("ts-"), f"{f.name}: {t}"


def test_the_memory_volumes_are_external_and_the_headroom_ones_are_not():
    """The asymmetry IS the safety property. `down -v` cannot remove an external
    volume, which is why every memory ever saved lives in one; headroom's three
    are removable by design and tstack services gates that behind --destroy-data."""
    am = (ROOT / "services/stacks/agentmemory/docker-compose.yml").read_text(encoding="utf-8")
    con = (ROOT / "services/stacks/agent007memory/docker-compose.yml").read_text(encoding="utf-8")
    hr = (ROOT / "services/stacks/headroom/docker-compose.yml").read_text(encoding="utf-8")
    assert "ts-agentmemory-data:\n    external: true" in am
    assert "ts-agentmemory-console-history:\n    external: true" in con
    assert "external: true" not in hr.split("volumes:")[-1]
    # ...and pinned by name, or a plain key under a project called ts-headroom
    # would produce ts-headroom_ts-headroom-workspace. The two datastore volumes
    # live with the datastores, in the memory overlay -- they only exist on a
    # machine that chose Headroom as its memory backend.
    assert "name: ts-headroom-workspace" in hr
    mem = (ROOT / "services/stacks/headroom/docker-compose.memory.yml").read_text(encoding="utf-8")
    for name in ("ts-headroom-qdrant", "ts-headroom-neo4j"):
        assert f"name: {name}" in mem
        assert f"name: {name}" not in hr


def test_the_volume_rename_map_names_the_volumes_as_they_are_on_disk():
    """Checked against a live `docker volume ls`: headroom's three carry their old
    project prefix because they were plain named volumes under a project called
    headroom, while the two agentmemory volumes are external and never had one.
    Getting this wrong means the guard never fires and compose starts the stack
    on an empty volume, reporting success."""
    assert stacks.VOLUME_RENAMES == (
        ("agentmemory_iii-data", "ts-agentmemory-data"),
        ("agent007memory_history", "ts-agentmemory-console-history"),
        ("headroom_headroom_workspace", "ts-headroom-workspace"),
        ("headroom_qdrant_data", "ts-headroom-qdrant"),
        ("headroom_neo4j_data", "ts-headroom-neo4j"),
    )
    # The two memory volumes are the ones you would miss, so backup lists them
    # first and --purge is the only thing that removes them.
    assert stacks.DATA_VOLUMES[:2] == stacks.MEMORY_VOLUMES


def test_up_refuses_while_a_legacy_volume_has_no_replacement(monkeypatch, capsys):
    """Compose would create an empty ts- volume and start the stack with no
    memories in it, reporting success. It refuses, names one command, and starts
    nothing."""
    started = []
    monkeypatch.setattr(
        stacks, "volumes_pending", lambda kind: [("agentmemory_iii-data", "ts-agentmemory-data")]
    )
    monkeypatch.setattr(
        stacks.Compose, "run", lambda self, stack, args, capture=False: started.append(args)
    )
    svc = services.Services(ROOT, services.parse(["up"]))
    svc.stacks = ["agentmemory"]
    with pytest.raises(SystemExit) as raised:
        services.cmd_up(svc)
    assert raised.value.code == 1
    out = capsys.readouterr().out
    assert "migrate-volumes" in out, "the refusal does not name the fix"
    assert "pre-ts- names" in out, "the refusal does not explain itself"
    assert started == [], "it started something anyway"


def test_the_billing_overlay_never_replaces_the_default_env_file():
    """A lone `--env-file .billing.env` REPLACES .env as compose's interpolation
    source, so every ${OPENAI_*}-derived LLM_* display value resolves to empty:
    a blank provider panel in the console, no error, everything healthy. The
    ordering used to live in update-console.*, which this replaced."""
    # Order out of the choke point itself, on a tree built for the purpose, so it
    # is asserted on every machine rather than only on one that happens to have a
    # billing file.
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        stack_dir = Path(raw) / "services" / "stacks" / "agentmemory"
        stack_dir.mkdir(parents=True)
        (stack_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        (stack_dir / ".env").write_text("A=1\n", encoding="utf-8")
        (stack_dir / ".billing.env").write_text("B=2\n", encoding="utf-8")
        (stack_dir / "extra.env").write_text("C=3\n", encoding="utf-8")
        (stack_dir / "ts-envfiles").write_text("# a comment\nextra.env\nmissing.env\n", "utf-8")

        assert stacks.env_file_list(stack_dir) == ["extra.env", ".env", ".billing.env"]
        argv = stacks.Compose(Path(raw), engine.NATIVE).argv("agentmemory", ["up", "-d"])
        joined = " ".join(argv)
        assert joined.index("--env-file .env") < joined.index("--env-file .billing.env"), joined
        # ts-envfiles names interpolation sources ONLY. A file it lists that does
        # not exist is skipped rather than passed on to compose.
        assert "missing.env" not in joined
    # And when this machine actually has one, the emitted argv proves it too.
    out = _dry_run("up", "agentmemory")
    if "--env-file" in out:
        assert out.index("--env-file .env") < out.index("--env-file .billing.env"), out


def test_line_endings_and_bom_are_scoped_to_the_service_tree():
    """Two conventions, both right in their own scope, and a blanket `sed -i` over
    the working tree quietly broke one of them.

    Inside services/: UTF-8 WITH BOM and CRLF. Those .ps1 run standalone, possibly
    under Windows PowerShell 5.1, which reads a BOM-less file as ANSI and then
    dies on the non-ASCII they print.

    Outside: LF and no BOM. Those files are chezmoi source or sync-hook inputs,
    where CRLF breaks ~/.zshrc under zsh and makes `#!/usr/bin/env bash\r`
    non-executable.
    """
    inside = sorted((ROOT / "services").rglob("*.ps1"))
    assert inside, "the service tree has no .ps1 files to check"
    for f in inside:
        raw = f.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf"), f"{f.relative_to(ROOT)}: needs a UTF-8 BOM"
        assert b"\r\n" in raw, f"{f.relative_to(ROOT)}: needs CRLF"
    for f in sorted(ROOT.glob("bootstrap/*.ps1")) + sorted(ROOT.glob("scripts/*.ps1")):
        raw = f.read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{f.name}: must not carry a BOM"
        assert b"\r" not in raw, f"{f.name}: must be LF"


# ── documentation ─────────────────────────────────────────────────────────────
def test_the_services_are_findable_by_name():
    """`doc agentmemory`, `doc headroom` and `doc playwright` all matched ZERO
    topics: the material was a 1167-line repo README with no `doc` label at all.
    Same failure mode as tstack config once being buried inside common/stack.md."""
    for page in (
        "services.md",
        "troubleshooting.md",
        "agentmemory.md",
        "agentmemory-console.md",
        "headroom.md",
        "playwright.md",
    ):
        assert (ROOT / "docs/kb/common" / page).exists(), page
    assert (ROOT / "docs/kb/windows/docker-desktop.md").exists()
    assert (ROOT / "docs/kb/macos/docker-desktop.md").exists()
    idx = (ROOT / "docs/kb/_index.md").read_text(encoding="utf-8")
    assert "doc troubleshooting" in idx, "_index.md must advertise the entry point"
    # The windows/ bullet is pinned to one line by an existing test; both words
    # have to survive on it.
    win = idx.split("`windows/`")[1].split("\n")[0]
    assert "TTS" in win and "Docker" in win


def test_no_tracked_file_carries_personal_infrastructure():
    """This repo is public, and is now somebody else's onboarding path. History
    is exempt: rewriting it to hide a hostname makes the record dishonest."""
    import subprocess

    # This file names the strings it forbids, and CHANGELOG/decisions are history.
    exempt = {"CHANGELOG.md", "docs/decisions.md", "LICENSE", "tests/test_stack.py"}
    files = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        start_new_session=True,
    ).stdout.split()
    for rel in files:
        if rel in exempt or rel.startswith("services/console/public/"):
            continue
        f = ROOT / rel
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        assert "lambda-dual" not in text, f"{rel} names a private host"
        assert "10.30.1." not in text, f"{rel} names a private address"


def test_install_documents_docker_before_the_agent_toggles():
    """Phase 6b enables agents against services that Phase 6a has to have
    started -- `ts-agents headroom on` refuses to persist until the proxy
    answers, so the order is not cosmetic."""
    ins = (ROOT / "INSTALL.md").read_text(encoding="utf-8")
    assert "Phase 6a" in ins and ins.index("Phase 6a") < ins.index("Phase 6b")
    assert "tstack services bootstrap" in ins
    assert "Terminal-stack never manages the containers" not in ins


def test_every_optional_env_file_points_at_a_documented_location():
    """An `env_file` entry with `required: false` is SILENT when it is wrong:
    compose says nothing, the container starts, and the variables simply are not
    there. That is how the merge broke LLM compression -- the tree gained a level
    (services/stacks/<stack>/), so a `../.env` written for the old two-level
    layout resolved to services/stacks/.env, which does not exist, and
    OPENAI_API_KEY silently stopped reaching AgentMemory. Every compression call
    then returned empty, failed XML parsing, retried and dead-lettered, for
    weeks, with `outcome: success` in the log because the HTTP call never
    happened.

    The invariant that catches it without needing a real (untracked) .env: every
    env_file path must sit beside a TRACKED .env.example documenting it. That is
    true of services/.env and of each stack's own .env, and false of any level
    the path lands on by accident."""
    import re

    for compose in sorted((ROOT / "services" / "stacks").glob("*/docker-compose*.yml")):
        for path in re.findall(r"- path:\s*(\S+)", compose.read_text(encoding="utf-8")):
            target = (compose.parent / path).resolve()
            example = target.parent / ".env.example"
            assert example.is_file(), (
                f"{compose.relative_to(ROOT)} loads {path}, which resolves to "
                f"{target} -- no tracked .env.example there, so nothing documents "
                f"or verifies that file. A silently-missing env_file is invisible."
            )


def test_every_sourced_helper_path_resolves():
    """`. "$SCRIPT_DIR/../_common.sh"` was correct in docker-local, where the
    stacks sat one level under the repo root. The merge put them two levels down
    AND renamed the helper to _stack.sh, and the sweep changed every tss_ call
    inside these scripts while leaving the source line pointing at a file that
    exists nowhere. Seven scripts -- reconcile-llm-queue, migrate-durable-llm,
    migrate-memory-projects, configure-openai-billing, check-capture,
    setup-kokoro-docker, check-playwright -- died on their first line, and
    nothing ran them because they are the tools you reach for only when
    something is already wrong."""
    import re

    bad = []
    for sh in sorted((ROOT / "services").rglob("*.sh")):
        if "node_modules" in sh.parts:
            continue
        for ref in re.findall(
            r'^\s*\.\s+"\$SCRIPT_DIR/([^"]+)"', sh.read_text(encoding="utf-8"), re.M
        ):
            if not (sh.parent / ref).resolve().is_file():
                bad.append(f"{sh.relative_to(ROOT)} sources {ref}, which does not exist")
    assert not bad, chr(10).join(bad)


def test_a_stack_that_joins_another_network_declares_ts_after():
    """Lexical order puts agent007memory FIRST ('0' < 'm'), and it joins
    ts-agentmemory-net, which the agentmemory stack creates. An external network
    cannot be joined before it exists, so without `ts-after` every fresh
    `tstack services up` fails with "network not found" on a stack that is perfectly
    configured. Any stack declaring an external network must name the stack that
    owns it."""
    import re

    stacks = ROOT / "services" / "stacks"
    owners = {}
    for compose in sorted(stacks.glob("*/docker-compose.yml")):
        text = compose.read_text(encoding="utf-8")
        block = text.split("networks:", 1)[-1] if "networks:" in text else ""
        for name in re.findall(r"^\s+name:\s*(\S+)", block, re.M):
            if "external: true" not in block.split(name, 1)[-1][:200]:
                owners[name] = compose.parent.name
    for compose in sorted(stacks.glob("*/docker-compose.yml")):
        text = compose.read_text(encoding="utf-8")
        if "external: true" not in text.split("networks:", 1)[-1]:
            continue
        block = text.split("networks:", 1)[-1]
        for name in re.findall(r"^\s+name:\s*(\S+)", block, re.M):
            owner = owners.get(name)
            if not owner or owner == compose.parent.name:
                continue
            after = compose.parent / "ts-after"
            assert after.is_file(), f"{compose.parent.name} joins {name} but has no ts-after"
            assert owner in after.read_text(encoding="utf-8").split(), (
                f"{compose.parent.name} joins {name}, owned by {owner}, but ts-after does not name it"
            )


def test_the_env_file_order_puts_the_stacks_own_env_last():
    """`--env-file .billing.env` alone REPLACES .env as compose's interpolation
    source, which is how the console's provider panel went blank while every
    container reported healthy. Extras from ts-envfiles are interpolation
    sources for values another stack owns, so they come first and the stack's
    own .env wins; .billing.env is written by a generator and wins over both.

    Checked against the real tree rather than against source text: the ordering
    used to be asserted by slicing a bash function body, which pins the shape of
    an implementation rather than the rule it exists to keep.

    The real ts-envfiles content, in a copy of the stack directory with the
    untracked files it would have on an installed machine. Reading the live tree
    instead made this pass here and fail on every clean checkout, because .env is
    gitignored -- the same "only green on an already-installed machine" trap CI
    caught once before.
    """
    import shutil
    import tempfile

    root = ROOT / "services" / "stacks"
    sources = sorted(root.glob("*/ts-envfiles"))
    assert sources, "no ts-envfiles tree to check"
    for extra in sources:
        with tempfile.TemporaryDirectory() as raw:
            stack_dir = Path(raw) / extra.parent.name
            shutil.copytree(extra.parent, stack_dir)
            (stack_dir / ".env").write_text("A=1\n", encoding="utf-8")
            (stack_dir / ".billing.env").write_text("B=2\n", encoding="utf-8")
            listed = [
                ln.strip()
                for ln in extra.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.strip().startswith("#")
            ]
            # An entry that names a file in ANOTHER stack has to exist there too.
            for name in listed:
                target = stack_dir / name
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text("C=3\n", encoding="utf-8")

            names = stacks.env_file_list(stack_dir)
            for name in listed:
                assert names.index(name) < names.index(".env"), (
                    f"{extra.parent.name}: {name} comes after .env"
                )
            assert names.index(".env") < names.index(".billing.env")


def test_ts_envfiles_never_becomes_an_env_file_entry():
    """An `env_file:` entry hands every key in the file to the container. The
    console is deliberately never given a provider secret, and the agentmemory
    .env it reads for display values holds OPENAI_API_KEY -- so that file may
    only ever be an INTERPOLATION source (--env-file), never an env_file."""
    for extra in (ROOT / "services" / "stacks").glob("*/ts-envfiles"):
        compose = (extra.parent / "docker-compose.yml").read_text(encoding="utf-8")
        for line in extra.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            assert f"path: {line}" not in compose, (
                f"{extra.parent.name}: {line} is listed in ts-envfiles AND as an env_file: "
                f"entry -- that injects every key in it, including provider secrets"
            )


def test_the_console_is_its_own_project_named_for_what_it_is():
    """agent007memory is a separate application with a separate lifecycle. As an
    overlay on the agentmemory project it appeared in Docker as a second row
    under someone else's name."""
    d = ROOT / "services" / "stacks" / "agent007memory"
    compose = (d / "docker-compose.yml").read_text(encoding="utf-8")
    assert "name: ts-agent007memory" in compose
    assert "container_name: ts-agent007memory" in compose
    assert "image: ts-agent007memory:local" in compose
    # depends_on cannot reach across compose projects; leaving one behind would
    # be a silently ignored key, not an error.
    # Comments about it are fine; a real key is not -- compose IGNORES depends_on
    # across projects silently, so leaving one would read as ordering that is not
    # happening.
    assert not re.search(r"^\s+depends_on:", compose, re.M)
    assert not (
        ROOT / "services" / "stacks" / "agentmemory" / "docker-compose.console.yml"
    ).exists()


def test_headroom_memory_needs_the_flag_and_the_flag_lives_in_the_overlay():
    """`headroom proxy` engages memory ONLY when passed --memory, and there is no
    environment variable for that flag. The base compose used to set QDRANT_URL
    and NEO4J_URI and start both databases while the proxy never contacted
    either: 0 memories, 0 Qdrant collections, 0 Neo4j nodes, a 900 MB Neo4j, and
    four containers reporting healthy.

    So the overlay has to carry three things together -- the datastores, the
    connection settings, and the flag. An overlay that starts the databases
    without --memory reproduces the original bug in a tidier shape, which is
    exactly the edit this test is here to fail."""
    d = ROOT / "services" / "stacks" / "headroom"
    base = (d / "docker-compose.yml").read_text(encoding="utf-8")
    overlay = (d / "docker-compose.memory.yml").read_text(encoding="utf-8")

    for name in ("qdrant:", "neo4j:"):
        assert name not in base, f"the base compose still defines {name}"
        assert name in overlay, f"the overlay does not define {name}"
    for key in ("QDRANT_URL", "NEO4J_URI", "NEO4J_PASSWORD"):
        assert key not in base, f"{key} is still in the base compose"
        assert key in overlay, f"{key} is missing from the overlay"
    assert "--memory" in overlay, "the overlay starts the datastores but never turns memory on"


def test_the_memory_backend_is_one_slot_with_three_values():
    """One key, so two memory systems are unrepresentable rather than merely
    discouraged, and agentmemoryEnabled is derived from it rather than set
    independently."""
    sh = (ROOT / "bootstrap" / "_config.sh").read_text(encoding="utf-8")
    ps = (ROOT / "bootstrap" / "_config.ps1").read_text(encoding="utf-8")
    toml = (ROOT / ".chezmoi.toml.tmpl").read_text(encoding="utf-8")

    for value in ("agentmemory", "headroom", "none"):
        assert f"memoryBackend:{value}" in sh, f"{value} is not an accepted value in bash"
    assert "'agentmemory','headroom','none'" in ps.replace(" ", ""), "pwsh ValidateSet"
    assert 'default "agentmemory"' in toml, "the chezmoi default must be agentmemory"
    # The single writer, in both twins.
    assert "ts_memory_apply()" in sh
    assert "function Set-TsMemoryBackend" in ps


def test_the_wizard_asks_once_and_derives_the_rest():
    """The two independent Headroom/AgentMemory toggles are what made a
    two-memory-system machine one keystroke away, so they must not come back."""
    sh = (ROOT / "bootstrap" / "_wizard.sh").read_text(encoding="utf-8")
    ps = (ROOT / "bootstrap" / "_config.ps1").read_text(encoding="utf-8")
    assert "ts_prompt_memory_backend()" in sh
    assert "function Read-TsMemoryBackend" in ps
    assert "TS_AGENTMEMORY 'AgentMemory for all projects?'" not in sh
    assert "Read-TsAgentToggle TS_AGENTMEMORY" not in ps
    assert "TS_HEADROOM 'Headroom prompt compression" not in sh
    # Both twins offer the same four answers.
    for key in ("agentmemory", "headroom", "none", "off"):
        assert key in sh and key in ps


def test_ts_envfiles_paths_are_interpolation_sources_only():
    """An `env_file:` entry hands the container every variable in the file. The
    console reads the agentmemory stack's .env for display values, and that file
    holds OPENAI_API_KEY -- so it may only ever be a --env-file interpolation
    source."""
    for extra in sorted((ROOT / "services" / "stacks").glob("*/ts-envfiles")):
        compose = (extra.parent / "docker-compose.yml").read_text(encoding="utf-8")
        for line in extra.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            assert f"path: {line}" not in compose, (
                f"{extra.parent.name}: {line} is both a ts-envfiles entry and an env_file: "
                f"entry -- that injects every key in it, secrets included"
            )
            # The referenced file must be a real path, not a typo -- but `.env`
            # is gitignored and only exists after `tstack services bootstrap`,
            # so requiring it here made this test pass only on an already-set-up
            # machine and fail on every clean checkout, which is exactly what CI
            # is. Accept the tracked `.example` as proof the path is real.
            target = (extra.parent / line).resolve()
            example = target.with_name(target.name + ".example")
            assert target.is_file() or example.is_file(), (
                f"{extra.parent.name}: {line} names neither an existing file nor "
                f"a tracked {example.name}"
            )


def test_overlay_checks_are_paired_with_their_overlay():
    """ts-checks.<x>.conf goes with docker-compose.<x>.yml. Without the pairing an
    overlay's services either go unchecked, or their checks sit in the base file
    and pass on every machine that has not enabled the overlay -- which is what
    the Qdrant and Neo4j health checks were doing."""
    stacks = ROOT / "services" / "stacks"
    for conf in sorted(stacks.glob("*/ts-checks.*.conf")):
        name = conf.name[len("ts-checks.") : -len(".conf")]
        assert (conf.parent / f"docker-compose.{name}.yml").is_file(), (
            f"{conf.relative_to(ROOT)} has no docker-compose.{name}.yml to belong to"
        )
    # And the base file must not assert the overlay's containers.
    base = (stacks / "headroom" / "ts-checks.conf").read_text(encoding="utf-8")
    assert "ts-headroom-qdrant" not in base and "ts-headroom-neo4j" not in base
    assert "sh" in "sh"  # keep the module import-light; no docker needed anywhere above
