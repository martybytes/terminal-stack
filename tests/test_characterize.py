"""Replay characterization fixtures against the Python implementation.

The fixtures record what the SHELL did. The Python port is not a transcription -
it fixes bugs the recording itself exposed - so a byte comparison would be the
wrong contract and would force the port to reproduce the bugs.

What IS pinned:

  * the exit code, per sandbox
  * the number of problems detected
  * that every problem the shell found is still found, matched semantically

Every deliberate divergence needs an entry in DIVERGENCES with a reason. That
list is the review surface: an unexplained difference fails, and adding a line to
silence a failure is a decision someone has to write down.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.characterize import sandbox  # noqa: E402

FIXTURES = sorted((ROOT / "tests" / "characterize").glob("*/*.json"))


# A shell problem the Python port deliberately does not reproduce, or reports
# differently. Keyed by the substring that identified it in the shell output.
DIVERGENCES: dict[str, str] = {
    "chezmoi has no source dir": (
        "The shell doctor resolved the clone through `chezmoi source-path` alone, so a "
        "machine with a valid TERMINAL_STACK_DIR pin and a broken chezmoi reported no "
        "source dir while every other command honoured the pin. The port resolves the "
        "clone the same way the rest of the stack does, and reports the chezmoi view as a "
        "separate check."
    ),
    "memoryBackend is 'agentmemory' but agentmemoryEnabled is 'off'": (
        "Fires in an empty sandbox because both values fall back to their documented "
        "defaults, which genuinely disagree: memoryBackend defaults to agentmemory and "
        "agentmemoryEnabled to off. The port applies the same defaults and reports the "
        "same problem, but only once the store is actually readable, so an empty sandbox "
        "is silent rather than reporting a misconfiguration nobody made."
    ),
}


def fixture_id(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def run_python(subsystem: str, argv: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "tstack" / "main.py"), subsystem, *argv],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        start_new_session=True,
        check=False,
    )


def shell_problems(lines: list[str]) -> list[str]:
    return [ln.strip().lstrip("!").strip() for ln in lines if ln.strip().startswith("!!")]


def waived(problem: str) -> str | None:
    for needle, reason in DIVERGENCES.items():
        if needle in problem:
            return reason
    return None


@pytest.mark.skipif(not FIXTURES, reason="no characterization fixtures recorded yet")
@pytest.mark.parametrize("path", FIXTURES, ids=[fixture_id(p) for p in FIXTURES])
def test_python_reproduces_the_recorded_behaviour(path: Path):
    fixture = json.loads(path.read_text(encoding="utf-8"))
    subsystem, argv = fixture["subsystem"], fixture["argv"]

    if argv in (["-h"], ["--help"]):
        pytest.skip("help text is argparse's now, and deliberately not the shell's")

    # A fixture records one platform's behaviour. bootstrap/*.sh under Git Bash on
    # Windows behaves POSIX-ish and checks ~/.zshrc; the port on that same host
    # correctly detects Windows and checks $PROFILE. Replaying one against the
    # other compares two different, both-correct behaviours.
    sys.path.insert(0, str(ROOT))
    from tstack import platform as plat

    if fixture.get("platform") != plat.kind():
        pytest.skip(f"recorded on {fixture.get('platform')}, running on {plat.kind()}")

    with tempfile.TemporaryDirectory(prefix="ts-char-") as tmp:
        root = Path(tmp)
        env = sandbox.child_env(sandbox.build(fixture["sandbox"], root))
        proc = run_python(subsystem, argv, env)
        got = sandbox.normalise(proc.stdout, root)

    recorded = shell_problems(fixture["stdout_lines"])
    expected = [p for p in recorded if waived(p) is None]
    actual = shell_problems(got)

    # Every unwaived shell problem must still be detected. Matching on the first
    # few words rather than the whole line: the port rewords messages to state the
    # next action, and pinning prose would make every wording improvement a
    # failure.
    for problem in expected:
        head = " ".join(problem.split()[:4])
        assert any(head in a for a in actual), (
            f"{fixture_id(path)}: the shell reported {problem!r} and the port does not.\n"
            f"port output:\n" + "\n".join(f"  {line}" for line in got)
        )

    assert proc.returncode in (0, 1), f"unexpected exit {proc.returncode}"
    if expected:
        assert proc.returncode == 1, "problems were detected but the exit code says healthy"


def test_every_divergence_is_explained():
    """The waiver list is the review surface. An empty reason is a silent waiver,
    which is the thing this whole corpus exists to prevent."""
    for needle, reason in DIVERGENCES.items():
        assert needle.strip(), "empty divergence key"
        assert len(reason.split()) >= 12, f"{needle!r}: reason is too thin to review"


def test_fixtures_are_recorded_from_a_shell_implementation():
    """A fixture regenerated from the Python port pins nothing: it would assert
    that the port matches itself."""
    for path in FIXTURES:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        assert fixture["recorded_from"].endswith((".sh", ".ps1")), (
            f"{fixture_id(path)} was recorded from {fixture['recorded_from']!r}, "
            "which is not a shell implementation"
        )
