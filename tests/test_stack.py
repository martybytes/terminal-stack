"""ts-stack: the service-lifecycle CLI.

The high-value tests here need no Docker, which is the point — most machines
running this suite have no engine, and the WSL ones have Docker Desktop's stub
(see test_docker_kind_calls_the_desktop_stub_what_it_is). What they pin instead
is the argv the CLI *would* run, which is where the data-safety contract lives.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SH = ROOT / "bootstrap/ts-stack.sh"
PS = ROOT / "bootstrap/ts-stack.ps1"


def _help_text(path, marker):
    """The HELP block out of either twin, without running anything."""
    text = path.read_text(encoding="utf-8")
    start = text.index(marker) + len(marker)
    end = text.index("'@" if marker.endswith("@'\n") else "'\n\n", start)
    return text[start:end]


def test_help_is_byte_identical_between_the_twins():
    """`change one, change the other` is only checkable if -h is pinned. Both
    twins carry the text inline rather than shelling out, because -h has to work
    on a box where the clone or the engine is the thing that is broken."""
    sh = _help_text(SH, "HELP='")
    ps = _help_text(PS, "$HELP = @'\n")
    assert sh.rstrip("\n") == ps.rstrip("\n"), (
        "the -h text diverged:\n--- sh\n" + sh + "\n--- ps\n" + ps)


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


def test_toggle_map_is_the_same_in_both_twins():
    """A stack gated on the wrong saved setting is skipped for the wrong reason."""
    sh = SH.read_text(encoding="utf-8") + (ROOT / "services/_stack.sh").read_text(encoding="utf-8")
    ps = PS.read_text(encoding="utf-8")
    for stack, key in (("agentmemory", "agentmemoryEnabled"),
                       ("headroom", "headroomEnabled"),
                       ("playwright", "playwrightEnabled"),
                       ("kokoro", "ccTts")):
        assert key in sh and key in ps, f"{stack} -> {key} missing from a twin"


def test_only_ts_stack_may_run_docker():
    """The boundary that replaced the old inter-repo seam: services/ is the
    service side, everything outside it configures a host program. ts-agents may
    print the ts-stack verb but never the compose command — the existing
    lifecycle-adapter test matches `docker compose` as a substring over the whole
    file, so even a helpful comment fails it."""
    for rel in ("bootstrap/ts-agents.sh", "bootstrap/ts-agents.ps1"):
        text = (ROOT / rel).read_text(encoding="utf-8").lower()
        assert "docker compose" not in text, f"{rel} must not name the compose command"
    # And the CLI that may is the one that says so.
    assert "docker compose" in SH.read_text(encoding="utf-8")
    assert "docker compose" in PS.read_text(encoding="utf-8")


# ── the argv contract ─────────────────────────────────────────────────────────
def _dry_run(*args):
    env = {"TERMINAL_STACK_DIR": str(ROOT), "TS_STACK_DOCKER_PROBE": "absent",
           "NO_COLOR": "1", "HOME": str(Path.home()), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([shutil.which("bash"), str(SH), *args, "--dry-run"],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    return r.stdout


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_down_never_receives_dash_v():
    """`down -v` destroys the headroom knowledge graph and every vector. The
    invariant is that -v cannot reach this argv, and it is a test rather than a
    comment because a comment is what stack.sh had."""
    out = _dry_run("down", "--all")
    assert re.search(r"docker compose\b.*\bdown\b", out), out
    assert re.search(r"docker compose\b.*\s-v\b", out) is None, out
    assert "docker volume rm" not in out


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_restart_is_down_then_up_not_compose_restart():
    """`docker compose restart` reuses the existing container, so it ignores the
    changed .env or overlay that is the whole reason anyone restarts."""
    out = _dry_run("restart", "agentmemory")
    assert re.search(r"docker compose\b.*\bdown\b", out), out
    assert re.search(r"docker compose\b.*\bup -d\b", out), out
    assert "docker compose restart" not in out
    assert out.index("down") < out.index("up -d")


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_naming_a_stack_overrides_its_saved_toggle():
    """Asking by name is consent; otherwise a machine with the setting off could
    never start the stack to try it."""
    out = _dry_run("up", "headroom")
    assert re.search(r"\(headroom\) docker compose\b.*\bup -d\b", out), out


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_status_survives_an_absent_engine():
    """The most common state on a fresh box, and on any box where Docker Desktop
    is not running. One headline, not a wall of failures."""
    env = {"TERMINAL_STACK_DIR": str(ROOT), "TS_STACK_DOCKER_PROBE": "absent",
           "NO_COLOR": "1", "HOME": str(Path.home()), "PATH": "/usr/bin:/bin"}
    r = subprocess.run([shutil.which("bash"), str(SH), "status"],
                       cwd=ROOT, capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "engine unreachable" in r.stdout + r.stderr


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_docker_kind_calls_the_desktop_stub_what_it_is():
    """`docker` on PATH inside WSL is Docker Desktop's stub when integration is
    off: it exits 1 for every command and prints its complaint on STDOUT, so
    `command -v docker` is true and useless. Diagnosing that as "is Docker
    Desktop running?" is wrong — the engine may be perfectly healthy on the
    Windows side."""
    script = (
        f'. "{(ROOT / "services/_stack.sh").as_posix()}"\n'
        'bin=$(mktemp -d)\n'
        'printf "#!/bin/sh\\necho \\"The command \'docker\' could not be found in this WSL 2 distro.\\"\\nexit 1\\n" > "$bin/docker"\n'
        'chmod +x "$bin/docker"\n'
        'PATH="$bin:$PATH" tss_docker_kind; echo\n'
        'TS_STACK_DOCKER_PROBE=wsl-shim tss_engine_advice linux "$(TS_STACK_DOCKER_PROBE=wsl-shim tss_docker_kind)"\n'
        'rm -rf "$bin"\n')
    r = subprocess.run([shutil.which("bash"), "-c", script],
                       cwd=ROOT, capture_output=True, text=True)
    assert "wsl-shim" in r.stdout, r.stdout + r.stderr
    assert "WSL Integration" in r.stdout, "the advice must name the actual fix"
    assert "is Docker Desktop running" not in r.stdout


# ── one resolution rule, six copies ───────────────────────────────────────────
def test_the_stack_env_file_resolves_from_the_clone_in_every_copy():
    """Five sites walked the workspace for a sibling docker-local clone. That
    could never work from the runtime clone (which is not under the workspace)
    and, post-merge, can only find a stale file from an archived repo -- whose
    token may be for a proxy that has since rotated, producing a 401 that reads
    like a broken install. There is no fallback to the old path on purpose."""
    posix = ("bootstrap/ts-agents.sh", "bootstrap/_config.sh", "dot_zshrc")
    windows = ("bootstrap/ts-agents.ps1",
               "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1")
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
                continue      # the secret-cache path migrates with a fallback; see its own test
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
    assert f"HEADROOM_DASHBOARD_PORT={urlparse(cfg['headroom']['mcpUrl']).port}" in hr_env

    am = (ROOT / "services/stacks/agentmemory/docker-compose.yml").read_text(encoding="utf-8")
    assert f'AGENTMEMORY_VERSION: "{cfg["agentmemory"]["version"]}"' in am
    # The REST port the agents are told to use is the CONSOLE's, which proxies the
    # server; the server's own listener is the 3110 bypass. Both must be published.
    assert f":{urlparse(cfg['agentmemory']['restUrl']).port}:" in \
        (ROOT / "services/stacks/agentmemory/docker-compose.console.yml").read_text(encoding="utf-8")
    assert f":{urlparse(cfg['agentmemory']['viewerUrl']).port}:" in am


def test_every_published_port_binds_loopback_only():
    """None of these services authenticate. `"8880:8880"` would put one on the
    LAN, and the failure is silent until somebody else finds it."""
    import re as _re
    bad = []
    for f in sorted((ROOT / "services").rglob("docker-compose*.yml")):
        for m in _re.finditer(r'^\s*-\s*"?([0-9.]+:)?(\d+):\d+"?\s*$',
                              f.read_text(encoding="utf-8"), _re.M):
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
    expected_projects = {"agentmemory": "ts-agentmemory", "headroom": "ts-headroom",
                         "kokoro": "ts-kokoro", "playwright": "ts-playwright"}
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
    are removable by design and ts-stack gates that behind --destroy-data."""
    am = (ROOT / "services/stacks/agentmemory/docker-compose.yml").read_text(encoding="utf-8")
    con = (ROOT / "services/stacks/agentmemory/docker-compose.console.yml").read_text(encoding="utf-8")
    hr = (ROOT / "services/stacks/headroom/docker-compose.yml").read_text(encoding="utf-8")
    assert "ts-agentmemory-data:\n    external: true" in am
    assert "ts-agentmemory-console-history:\n    external: true" in con
    assert "external: true" not in hr.split("volumes:")[-1]
    # ...and pinned by name, or a plain key under a project called ts-headroom
    # would produce ts-headroom_ts-headroom-workspace.
    for name in ("ts-headroom-workspace", "ts-headroom-qdrant", "ts-headroom-neo4j"):
        assert f"name: {name}" in hr


def test_the_volume_rename_map_names_the_volumes_as_they_are_on_disk():
    """Checked against a live `docker volume ls`: headroom's three carry their old
    project prefix because they were plain named volumes under a project called
    headroom, while the two agentmemory volumes are external and never had one.
    Getting this wrong means the guard never fires and compose starts the stack
    on an empty volume, reporting success."""
    lib = (ROOT / "services/_stack.sh").read_text(encoding="utf-8")
    ps = PS.read_text(encoding="utf-8")
    for old, new in (("agentmemory_iii-data", "ts-agentmemory-data"),
                     ("agent007memory_history", "ts-agentmemory-console-history"),
                     ("headroom_headroom_workspace", "ts-headroom-workspace"),
                     ("headroom_qdrant_data", "ts-headroom-qdrant"),
                     ("headroom_neo4j_data", "ts-headroom-neo4j")):
        assert f"{old} {new}" in lib, f"bash map missing {old}"
        assert old in ps and new in ps, f"pwsh map missing {old}"


def test_up_refuses_while_a_legacy_volume_has_no_replacement():
    """Compose would create an empty ts- volume and start the stack with no
    memories in it, reporting success. Both twins refuse and name one command."""
    for text, name in ((SH.read_text(encoding="utf-8"), "bash"),
                       (PS.read_text(encoding="utf-8"), "pwsh")):
        i = text.index("    'up' {") if name == "pwsh" else text.index("    up)")
        window = text[i:i + 1200]
        assert "migrate-volumes" in window, f"the {name} up path does not name the fix"
        assert "pre-ts- names" in window, f"the {name} up path does not explain the refusal"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_the_billing_overlay_never_replaces_the_default_env_file():
    """A lone `--env-file .billing.env` REPLACES .env as compose's interpolation
    source, so every ${OPENAI_*}-derived LLM_* display value resolves to empty:
    a blank provider panel in the console, no error, everything healthy. The
    ordering used to live in update-console.*, which this replaced."""
    # The bash choke point is tss_compose in the shared library; the pwsh one is
    # Invoke-TsStackCompose in the script itself.
    for text in ((ROOT / "services/_stack.sh").read_text(encoding="utf-8"),
                 PS.read_text(encoding="utf-8")):
        i = text.index(".billing.env")
        window = text[max(0, i - 600):i + 200]
        assert "--env-file" in window
        assert window.index(".env") < window.index(".billing.env")
    # And when this machine actually has one, the emitted argv proves it.
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
    Same failure mode as ts-config once being buried inside common/stack.md."""
    for page in ("services.md", "troubleshooting.md", "agentmemory.md",
                 "agentmemory-console.md", "headroom.md", "playwright.md"):
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
    files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout.split()
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
    assert "ts-stack bootstrap" in ins
    assert "Terminal-stack never manages the containers" not in ins
