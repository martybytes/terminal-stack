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
    assert "docker compose down" in out
    assert re.search(r"docker compose\b.*\s-v\b", out) is None, out
    assert "docker volume rm" not in out


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_restart_is_down_then_up_not_compose_restart():
    """`docker compose restart` reuses the existing container, so it ignores the
    changed .env or overlay that is the whole reason anyone restarts."""
    out = _dry_run("restart", "agentmemory")
    assert "docker compose down" in out and "docker compose up -d" in out
    assert "docker compose restart" not in out
    assert out.index("down") < out.index("up -d")


@pytest.mark.skipif(not shutil.which("bash"), reason="bash is unavailable")
def test_naming_a_stack_overrides_its_saved_toggle():
    """Asking by name is consent; otherwise a machine with the setting off could
    never start the stack to try it."""
    out = _dry_run("up", "headroom")
    assert "(headroom) docker compose up -d" in out


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
