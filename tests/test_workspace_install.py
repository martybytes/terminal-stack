"""The installers' workspace question persists only a real directory.

It used to save any answer verbatim. One machine ended up with
`export WORKSPACE_DIR="tstack services"` in ~/.zshrc.local -- text typed ahead
while the install was still running -- which broke ws, wsmb and wso. Because
that file exports the value, the next install read it back "from env", skipped
the prompt and wrote it again. These pin the bash function shared by all three
POSIX bootstraps (ts_workspace_config) and the pwsh check (Test-TsWorkspaceChoice).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.shell_support import BASH, bash_path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "bootstrap" / "_config.sh"

pytestmark = pytest.mark.skipif(
    BASH is None or os.name == "nt", reason="needs a POSIX bash with a POSIX $HOME"
)


def _run(home: Path, script: str, *, env: dict[str, str] | None = None, answers=()):
    """Source _config.sh with a fake $HOME, no terminal, and scripted answers."""
    queue = "\n".join(answers)
    prelude = f"""
set -u
. {bash_path(CONFIG)}
ts_is_interactive() {{ [ -n "${{TS_TEST_TTY:-}}" ]; }}
_ts_answers_file="$HOME/.answers"
printf '%s\\n' {_q(queue)} > "$_ts_answers_file"
ts_tty_prompt() {{
    local first
    first="$(head -n 1 "$_ts_answers_file")"
    tail -n +2 "$_ts_answers_file" > "$_ts_answers_file.n" && mv "$_ts_answers_file.n" "$_ts_answers_file"
    printf '%s\\n' "$first"
}}
"""
    full_env = {
        "HOME": str(home),
        "PATH": os.environ.get("PATH", ""),
        "TERM": "dumb",
    }
    if answers:
        full_env["TS_TEST_TTY"] = "1"
    full_env.update(env or {})
    return subprocess.run(
        [str(BASH), "-c", prelude + script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=full_env,
        timeout=60,
        check=False,
        start_new_session=True,
    )


def _q(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def _rc(home: Path) -> str:
    rc = home / ".zshrc.local"
    return rc.read_text(encoding="utf-8") if rc.exists() else ""


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    (h / "Workspace").mkdir(parents=True)
    (h / "Code").mkdir()
    return h


@pytest.mark.parametrize(
    ("answer", "ok", "expected"),
    [
        ("tstack services", False, "not an absolute path"),
        ("Workspace", False, "not an absolute path"),
        ("/definitely/not/here", False, "no such directory"),
        ("~/Code", True, "{home}/Code"),
        ("~/Code/", True, "{home}/Code"),
        ("{home}/Code", True, "{home}/Code"),
    ],
)
def test_check_accepts_only_an_existing_absolute_directory(home, answer, ok, expected):
    got = _run(home, f'ts_workspace_check "{answer.format(home=home)}"')
    assert (got.returncode == 0) is ok, got
    assert got.stdout.strip() == expected.format(home=home)


def test_a_broken_pin_read_back_from_env_is_repaired_not_rewritten(home):
    # The incident: the bad value is both in the file and, because the file
    # exports it, in the environment of the shell that reruns the installer.
    (home / ".zshrc.local").write_text(
        'export PATH="$HOME/bin:$PATH"\nexport WORKSPACE_DIR="tstack services"\n',
        encoding="utf-8",
    )
    got = _run(home, "ts_workspace_config", env={"WORKSPACE_DIR": "tstack services"})
    assert got.returncode == 0, got
    rc = _rc(home)
    assert "tstack services" not in rc
    assert "WORKSPACE_DIR" not in rc
    assert 'export PATH="$HOME/bin:$PATH"' in rc


def test_an_invalid_env_value_is_ignored(home):
    got = _run(home, "ts_workspace_config", env={"WORKSPACE_DIR": "nope"})
    assert got.returncode == 0, got
    assert "Ignoring WORKSPACE_DIR" in got.stdout
    assert _rc(home) == ""


def test_an_invalid_answer_is_asked_again(home):
    got = _run(home, "ts_workspace_config", answers=("tstack services", "~/Code"))
    assert got.returncode == 0, got
    assert "not an absolute path" in got.stdout
    assert f'export WORKSPACE_DIR="{home}/Code"' in _rc(home)


def test_three_invalid_answers_keep_the_current_root(home):
    got = _run(home, "ts_workspace_config", answers=("a", "b", "c"))
    assert got.returncode == 0, got
    assert "Three invalid answers" in got.stdout
    assert _rc(home) == ""


def test_a_valid_pin_survives_a_headless_rerun(home):
    (home / ".zshrc.local").write_text(f'export WORKSPACE_DIR="{home}/Code"\n', encoding="utf-8")
    got = _run(home, "ts_workspace_config")
    assert got.returncode == 0, got
    assert f'export WORKSPACE_DIR="{home}/Code"' in _rc(home)


def test_the_mac_bootstrap_uses_the_shared_question():
    mac = (ROOT / "bootstrap" / "mac-bootstrap.sh").read_text(encoding="utf-8")
    posix = (ROOT / "bootstrap" / "_common-posix.sh").read_text(encoding="utf-8")
    assert "ts_workspace_config" in mac
    assert "WS_CHOICE" not in mac
    assert "ts_workspace_config" in posix


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell 7 is unavailable")
def test_pwsh_check_refuses_a_relative_answer(tmp_path):
    folder = tmp_path / "ws"
    folder.mkdir()
    command = f"""
$env:USERPROFILE = '{tmp_path}'
. '{ROOT / "bootstrap" / "_config.ps1"}'
$why = ''
$a = Test-TsWorkspaceChoice 'tstack services' ([ref]$why)
"rel=[$a] $why"
$why = ''
$b = Test-TsWorkspaceChoice 'C:\\definitely\\not\\here' ([ref]$why)
"missing=[$b] $why"
"""
    got = subprocess.run(
        [shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
        start_new_session=True,
    )
    assert "rel=[] not an absolute path" in got.stdout, got
    assert "missing=[] no such directory" in got.stdout, got
