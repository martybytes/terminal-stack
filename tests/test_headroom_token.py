"""One proxy per machine, so one Headroom token per machine.

The reported machine had three clones and three token states (the WSL runtime
clone's, none in the Windows runtime clone, an old one in a Windows dev
checkout) against one Docker Desktop proxy. Every pwsh launch printed
"Headroom is enabled but unavailable" and went direct while the proxy was fine.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import engine, headroom_token, paths, stacks, store  # noqa: E402
from tstack import platform as plat  # noqa: E402
from tstack.commands import agents, doctor  # noqa: E402

TOKEN = "HEADROOM_PROXY_TOKEN"


# ------------------------------------------------------------------ the file


def test_windows_and_wsl_share_one_file_under_localappdata(monkeypatch, tmp_path):
    """Combined machines run ONE Docker Desktop proxy for both sides."""
    for kind in (plat.WINDOWS, plat.WSL):
        monkeypatch.setattr(plat, "kind", lambda k=kind: k)
        monkeypatch.setattr(plat, "local_app_data", lambda: tmp_path / "Local")
        assert headroom_token._default_path() == tmp_path / "Local/terminal-stack/headroom-token"


def test_native_posix_keeps_it_in_the_state_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    monkeypatch.setattr(plat, "state_dir", lambda: tmp_path / "state")
    assert headroom_token._default_path() == tmp_path / "state/headroom-token"


def test_write_then_read_round_trips_and_is_private():
    assert headroom_token.write("  abc123  ")
    assert headroom_token.read() == "abc123"
    target = headroom_token.path()
    assert target is not None
    if os.name == "posix":
        assert target.stat().st_mode & 0o077 == 0
    assert not list(target.parent.glob(".headroom-token.*.tmp")), "temp file left behind"


def test_an_empty_token_is_never_recorded():
    assert not headroom_token.write("   ")
    assert headroom_token.read() == ""


# ------------------------------------------------------------ reader order


def _clone_with_token(tmp_path: Path, value: str) -> Path:
    clone = tmp_path / "clone"
    env = clone / "services/stacks/headroom/.env"
    env.parent.mkdir(parents=True)
    env.write_text(f"{TOKEN}={value}\n", encoding="utf-8")
    return clone


def _headroom(clone: Path) -> agents.Headroom:
    return agents.Headroom(clone, agents.Out(), "mcp")


def test_python_reads_env_then_env_file_then_machine_then_clone(monkeypatch, tmp_path):
    clone = _clone_with_token(tmp_path, "from-clone")
    monkeypatch.delenv(TOKEN, raising=False)
    monkeypatch.delenv("HEADROOM_ENV_FILE", raising=False)
    assert _headroom(clone).token() == "from-clone"

    headroom_token.write("from-machine")
    assert _headroom(clone).token() == "from-machine", "the machine token must beat the clone's"

    other = tmp_path / "explicit.env"
    other.write_text(f"{TOKEN}=from-env-file\n", encoding="utf-8")
    monkeypatch.setenv("HEADROOM_ENV_FILE", str(other))
    assert _headroom(clone).token() == "from-env-file", "an explicit env file still wins"

    monkeypatch.setenv(TOKEN, "from-env")
    assert _headroom(clone).token() == "from-env"


ZSH = shutil.which("zsh")


def _zsh_function(name: str) -> str:
    body = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    start = body.index(f"{name}() {{")
    return body[start : body.index("\n}\n", start) + 3]


@pytest.mark.skipif(not ZSH, reason="zsh is unavailable")
def test_zsh_reads_the_machine_token_before_the_clone(tmp_path):
    """Run the real function, not a regex of it: the precedence IS the fix."""
    state = tmp_path / "state"
    (state / "terminal-stack").mkdir(parents=True)
    (state / "terminal-stack/headroom-token").write_text("from-machine\n", encoding="utf-8")
    clone_env = _clone_with_token(tmp_path, "from-clone") / "services/stacks/headroom/.env"
    script = (
        _zsh_function("_ts_headroom_token")
        + f'_ts_chezmoi() {{ :; }}\n_ts_src() {{ print -r -- "{clone_env.parents[3]}"; }}\n'
        + "_ts_headroom_token\n"
    )
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path), "XDG_STATE_HOME": str(state)}
    got = subprocess.run(
        [ZSH, "-f", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        start_new_session=True,
    )
    assert got.stdout.strip() == "from-machine", got.stderr
    (state / "terminal-stack/headroom-token").unlink()
    got = subprocess.run(
        [ZSH, "-f", "-c", script],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        start_new_session=True,
    )
    assert got.stdout.strip() == "from-clone", "no machine file: fall back to the clone's .env"


def test_pwsh_reads_the_machine_token_before_the_clone():
    body = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    fn = body[body.index("function Get-TsHeadroomToken {") :]
    fn = fn[: fn.index("\n}\n")]
    assert fn.index("headroom-token") < fn.index("services\\stacks\\headroom\\.env")
    assert fn.index("$env:HEADROOM_PROXY_TOKEN") < fn.index("headroom-token")


@pytest.mark.parametrize(
    "rel, helper",
    [
        ("dot_zshrc", "_ts_headroom_direct_warning"),
        (
            "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1",
            "Write-TsHeadroomDirectWarning",
        ),
    ],
)
def test_a_rejected_token_is_never_reported_as_unavailable(rel, helper):
    """The reported line was "unavailable" for a proxy that was up and fine."""
    body = (ROOT / rel).read_text(encoding="utf-8")
    assert len(re.findall(re.escape(helper) + r" '?(Claude|Codex)", body)) == 2
    assert "rejected" in body and "tstack doctor --repair" in body
    assert "no proxy token was found" in body


# --------------------------------------------------------------- the writers


@pytest.fixture
def svc_tree(tmp_path, monkeypatch):
    from tstack.commands import services

    root = tmp_path / "services" / "stacks" / "headroom"
    root.mkdir(parents=True)
    (root / "docker-compose.yml").write_text("name: ts-headroom\nservices: {}\n", "utf-8")
    monkeypatch.setenv("TS_STACK_ROOT", str(tmp_path / "services" / "stacks"))
    monkeypatch.setenv("TS_STACK_DOCKER_PROBE", engine.NATIVE)
    monkeypatch.setenv("NO_COLOR", "1")
    live: dict[str, str] = {}
    monkeypatch.setattr(stacks, "running_env", lambda kind, project, key: live.get(key, ""))
    svc = services.Services(tmp_path, services.parse(["bootstrap"]))
    return services, svc, root / ".env", live, monkeypatch


def test_a_fresh_clone_adopts_the_machine_token_when_no_proxy_is_running(svc_tree):
    services, svc, env, _, _ = svc_tree
    headroom_token.write("machine-token")
    env.write_text(f"{TOKEN}=changeme\n", encoding="utf-8")
    services._fill_secret(svc, env, TOKEN, "changeme", 32)
    assert stacks.env_value(env, TOKEN) == "machine-token"


def test_a_generated_token_becomes_the_machine_token(svc_tree):
    services, svc, env, _, _ = svc_tree
    env.write_text(f"{TOKEN}=changeme\n", encoding="utf-8")
    services._fill_secret(svc, env, TOKEN, "changeme", 32)
    written = stacks.env_value(env, TOKEN)
    assert written and written != "changeme"
    assert headroom_token.read() == written


def test_the_machine_token_follows_the_running_proxy_not_the_last_bootstrap(svc_tree, capsys):
    """A clone that already has a token never has it rotated -- but the machine
    file records what the running proxy accepts, and the mismatch is named."""
    services, svc, env, live, monkeypatch = svc_tree
    monkeypatch.setenv("TS_STACK_ENGINE_UP", "1")
    svc = services.Services(svc.source, services.parse(["bootstrap"]))
    env.write_text(f"{TOKEN}=this-clones-own\n", encoding="utf-8")
    live[TOKEN] = "the-live-one"
    services._fill_secret(svc, env, TOKEN, "changeme", 32)
    assert stacks.env_value(env, TOKEN) == "this-clones-own", "a set value is never rotated"
    assert headroom_token.read() == "the-live-one"
    out = capsys.readouterr().out
    assert "differs from the running proxy" in out
    assert "the-live-one" not in out and "this-clones-own" not in out, "a secret was printed"


def test_up_records_the_token_the_proxy_came_up_with():
    from tstack.commands import services

    src = Path(services.__file__).read_text(encoding="utf-8")
    up = src[src.index("def cmd_up(") : src.index("def _port_holders(")]
    assert "_record_machine_token(svc, _running_secret(svc, svc.dir(name), PROXY_TOKEN))" in up


# ------------------------------------------------------------------- doctor


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """headroom on; two clones; a live proxy holding `live`."""
    monkeypatch.setattr(store, "get", lambda k, d=None: {"headroomEnabled": "on"}.get(k, d or ""))
    a = _clone_with_token(tmp_path / "a", "the-live-one")
    b = _clone_with_token(tmp_path / "b", "stale")
    monkeypatch.setattr(paths, "clones", lambda: [paths.Clone(a, "o", ""), paths.Clone(b, "o", "")])
    monkeypatch.setattr(doctor, "_headroom_live_token", lambda: "the-live-one")
    return a, b


def test_doctor_names_every_place_the_proxy_would_reject(machine):
    _, b = machine
    report = doctor.Report()
    doctor.check_headroom_token(report)
    (result,) = [r for r in report.results if r.check == "headroom-token"]
    assert report.issues == 1
    assert str(b) in result.message and "machine token file" in result.message
    assert "the-live-one" not in result.message and "stale" not in result.message


def test_doctor_repair_aligns_the_machine_file_and_every_clone(machine):
    a, b = machine
    assert doctor.repair_headroom_token() == 0
    assert headroom_token.read() == "the-live-one"
    for clone in (a, b):
        assert stacks.env_value(clone / "services/stacks/headroom/.env", TOKEN) == "the-live-one"
    report = doctor.Report()
    doctor.check_headroom_token(report)
    assert report.issues == 0


def test_doctor_says_nothing_when_no_proxy_is_running(machine, monkeypatch):
    monkeypatch.setattr(doctor, "_headroom_live_token", lambda: "")
    report = doctor.Report()
    doctor.check_headroom_token(report)
    assert not [r for r in report.results if r.check == "headroom-token"]


def test_the_token_check_runs_in_collect_and_repair():
    import inspect

    assert "check_headroom_token(report)" in inspect.getsource(doctor.collect)
    assert "repair_headroom_token()" in inspect.getsource(doctor.repair)
