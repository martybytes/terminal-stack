"""Record characterization fixtures from the SHELL implementation.

    python -m tests.characterize.record doctor

Run this before porting a subsystem, while the shell is still the thing that
runs. Re-record only when the shell's behaviour genuinely changed: regenerating
a fixture to match a regression turns the safety net into a rubber stamp.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.characterize import sandbox

ROOT = sandbox.ROOT

# One entry per subsystem: the cases worth pinning. Failure paths first -- they
# are where a port silently diverges, and they are the ones nobody thinks to
# check by hand.
CASES: dict[str, list[dict]] = {
    "doctor": [
        {"case": "no-clone", "sandbox": "empty-home", "argv": []},
        {"case": "no-clone-quiet", "sandbox": "empty-home", "argv": ["--quiet"]},
        {"case": "help", "sandbox": "empty-home", "argv": ["-h"]},
        {"case": "clone-present", "sandbox": "clone-only", "argv": []},
        {"case": "clone-present-quiet", "sandbox": "clone-only", "argv": ["--quiet"]},
    ],
}


def shell_impl(subsystem: str) -> str:
    """The POSIX implementation path for a subcommand, from the registry."""
    for line in (ROOT / "tstack" / "commands.conf").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(None, 3)
        if len(fields) == 4 and fields[0] == subsystem:
            return fields[1]
    raise SystemExit(f"{subsystem!r} is not in tstack/commands.conf")


def record(subsystem: str, impl_override: str | None = None) -> int:
    # --impl exists for exactly one case: re-recording mid-port, after the
    # registry row has been flipped but before the shell file is deleted. The
    # guard below is what stops a fixture being "recorded" from the port itself,
    # which would assert only that the port matches itself.
    impl = impl_override or shell_impl(subsystem)
    if impl in ("python", "-") or impl.startswith("@"):
        raise SystemExit(
            f"{subsystem} is implemented as {impl!r}; there is no shell to record. "
            "Record BEFORE porting, or pass --impl <path-to-shell-script>."
        )
    if not (ROOT / impl).is_file():
        raise SystemExit(f"{impl} does not exist")
    bash = sandbox.find_bash()
    if not bash:
        raise SystemExit("no compatible bash found (Git Bash on Windows, /bin/bash elsewhere)")

    out_dir = ROOT / "tests" / "characterize" / subsystem
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec in CASES[subsystem]:
        with tempfile.TemporaryDirectory(prefix="ts-char-") as tmp:
            root = Path(tmp)
            env = sandbox.child_env(sandbox.build(spec["sandbox"], root))
            proc = subprocess.run(
                [bash, str(ROOT / impl), *spec["argv"]],
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
            # The platform the RECORDING represents, not the host that ran it.
            # bootstrap/*.sh under Git Bash on Windows behaves POSIX-ish and
            # checks ~/.zshrc; the Python port on that same host correctly
            # detects Windows and checks $PROFILE. Replaying one against the
            # other compares two different, both-correct behaviours -- so the
            # fixture carries its platform and is only replayed there.
            probe = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "import sys; sys.path.insert(0, '.'); "
                    "from tstack import platform as p; print(p.kind())",
                ],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
                start_new_session=True,
                check=False,
            )
            fixture = {
                "subsystem": subsystem,
                "case": spec["case"],
                "platform": probe.stdout.strip() or "unknown",
                "sandbox": spec["sandbox"],
                "argv": spec["argv"],
                "recorded_from": impl,
                "exit_code": proc.returncode,
                "stdout_lines": sandbox.normalise(proc.stdout, root),
                "stderr_lines": sandbox.normalise(proc.stderr, root),
            }
        path = out_dir / f"{spec['case']}.json"
        path.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
        print(
            f"  {path.relative_to(ROOT)}  exit={proc.returncode} "
            f"stdout={len(fixture['stdout_lines'])}L stderr={len(fixture['stderr_lines'])}L"
        )
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    override = None
    if "--impl" in args:
        i = args.index("--impl")
        override = args[i + 1]
        del args[i : i + 2]
    if len(args) != 1 or args[0] not in CASES:
        raise SystemExit(
            f"usage: python -m tests.characterize.record <{'|'.join(CASES)}> [--impl <script>]"
        )
    raise SystemExit(record(args[0], override))
