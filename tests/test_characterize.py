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


# A fixture whose EXIT CODE the port deliberately does not reproduce. Keyed by
# fixture id, because an exit code is a whole-run property rather than a line.
EXIT_DIVERGENCES: dict[str, str] = {
    "services/bad-verb": (
        "Recorded exit 2 through Git Bash and exit 1 through the WSL handoff for the "
        "same mistake, depending only on which machine ran it. An unknown verb is a "
        "usage error and the port always exits 2, on every platform."
    ),
    "services/bad-stack": (
        "The bash twin validated the stack name only after re-exec'ing the pwsh twin "
        "through WSL interop, so a misspelt stack surfaced as a PowerShell Write-Error "
        "and exit 1. There is one implementation now: the name is checked before "
        "anything else happens and a bad one is exit 2, with the list of real names."
    ),
    "config/bad-verb": (
        "`ts-config.sh` ended every usage mistake with `exit 2` in the case arm but "
        "reached the unknown-verb arm through a path that exited 1. The port exits 2 "
        "for every usage error, on every platform, which is the rule the rest of the "
        "program already followed."
    ),
    "config/leader-no-arg": (
        "Same cause: a missing argument is a usage error and is exit 2 now. The shell "
        "printed the same usage line and exited 1, so only the code changed -- and it "
        "changed toward what `tstack services` and `tstack agents` already did."
    ),
    "config/theme-no-arg": (
        "As above. Recorded here rather than special-cased in the port: a caller that "
        "keys off the exit code should see one answer for one kind of mistake."
    ),
    "services/logs-no-stack": (
        "Same handoff, same cause: `logs` with no stack name exited 1 on WSL and 2 "
        "elsewhere. It is a usage error in both places and now says so in both places."
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

    # A corpus is recorded BEFORE the port, so between recording and porting the
    # subsystem still routes to the shell and `main.py <name>` exits 2 saying so.
    # Those fixtures are pending, not failing: they become a gate the moment the
    # registry row flips, which is exactly when they should start biting.
    sys.path.insert(0, str(ROOT))
    from tstack import registry

    command = registry.get(subsystem)
    if command is None:
        pytest.fail(f"{subsystem!r} has fixtures but is not in tstack/commands.conf")
    if not command.is_ported():
        pytest.skip(f"{subsystem} is still {command.impl()!r}; fixtures are pending the port")

    # A fixture records one FAMILY's behaviour, and the line that matters is
    # Windows vs POSIX: bootstrap/*.sh under Git Bash behaves POSIX-ish and checks
    # ~/.zshrc, while the port on that same host correctly detects Windows and
    # checks $PROFILE. Replaying one against the other compares two different,
    # both-correct behaviours.
    #
    # Matching the exact platform instead would strand a wsl-recorded fixture on
    # the ubuntu and macos CI jobs, which is most of the corpus doing nothing. The
    # sandbox filters the Windows-side checks out of a WSL recording anyway, so
    # what remains is the behaviour every POSIX host shares.
    sys.path.insert(0, str(ROOT))
    from tstack import platform as plat

    def family(kind: str) -> str:
        return "windows" if kind == plat.WINDOWS else "posix"

    if family(fixture.get("platform", "")) != family(plat.kind()):
        pytest.skip(
            f"recorded on {fixture.get('platform')} ({family(fixture.get('platform', ''))}), "
            f"running on {plat.kind()} ({family(plat.kind())})"
        )

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

    # Exit codes: 0 healthy, 1 problems found, 2 the command line was wrong. The
    # third is a deliberate correction rather than a match, so it needs a written
    # reason like any other divergence.
    if proc.returncode == 2:
        reason = EXIT_DIVERGENCES.get(fixture_id(path))
        assert reason, (
            f"{fixture_id(path)}: the port exits 2 (usage) where the shell exited "
            f"{fixture['exit_code']}, and there is no entry in EXIT_DIVERGENCES saying why.\n"
            f"port output:\n" + "\n".join(f"  {line}" for line in got)
        )
        return
    assert proc.returncode in (0, 1), f"unexpected exit {proc.returncode}"
    if expected:
        assert proc.returncode == 1, "problems were detected but the exit code says healthy"


def test_every_divergence_is_explained():
    """The waiver list is the review surface. An empty reason is a silent waiver,
    which is the thing this whole corpus exists to prevent."""
    for needle, reason in {**DIVERGENCES, **EXIT_DIVERGENCES}.items():
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
