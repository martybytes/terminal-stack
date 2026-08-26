"""The tstack entry point, the registry, and the rules the claims audit found unenforced.

Several tests here exist because CLAUDE.md asserted a guarantee that nothing
checked. An unenforced invariant in prose is worse than no invariant: it is read
as settled and then quietly violated. Each one is labelled with the claim it
backs.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "tstack/commands.conf"
ZSHRC = ROOT / "dot_zshrc"
PROFILE = ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1"

PWSH = shutil.which("pwsh") or shutil.which("pwsh.exe")
needs_pwsh = pytest.mark.skipif(PWSH is None, reason="pwsh not installed")


def strip_comment(line: str) -> str:
    """Drop a PowerShell comment so a lint cannot match its own rationale.

    bootstrap/_config.ps1:1751 is a comment stating the Where-Object/Set-Content
    rule. The first version of that lint flagged the sentence describing the bug.
    """
    return line.split("#", 1)[0]


def rows() -> list[list[str]]:
    out = []
    for line in CONF.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split(None, 3)
        assert len(fields) == 4, f"malformed row: {line!r}"
        out.append(fields)
    return out


# --------------------------------------------------------------- the registry


def test_every_row_is_well_formed_and_unique():
    names = [r[0] for r in rows()]
    assert names, "commands.conf is empty"
    assert len(names) == len(set(names)), "duplicate subcommand"
    for name, posix, windows, summary in rows():
        assert re.fullmatch(r"[a-z][a-z0-9-]*", name), name
        assert summary and not summary.startswith("-"), name
        for token in (posix, windows):
            assert (
                token == "-"
                or token == "python"
                or token.startswith("@")
                or token.endswith((".sh", ".ps1"))
            ), f"{name}: unknown implementation token {token!r}"


def test_every_shell_implementation_actually_exists():
    """The path-existence guard.

    The rename inventory found the same path written three ways -- forward slash,
    backslash, and bare via $PSScriptRoot / $ROOT -- so a grep for 'bootstrap/ts-'
    misses a third of them. A missing target currently fails at runtime with
    "not found; run tstack update", which reads like a stale clone rather than a
    broken reference.
    """
    for name, posix, windows, _ in rows():
        for token in (posix, windows):
            if token in ("-", "python") or token.startswith("@"):
                continue
            assert (ROOT / token).exists(), f"{name}: {token} does not exist"


def test_every_at_token_names_a_function_that_exists():
    zsh = ZSHRC.read_text(encoding="utf-8")
    profile = PROFILE.read_text(encoding="utf-8")
    for name, posix, windows, _ in rows():
        if posix.startswith("@"):
            fn = posix[1:]
            assert f"\n{fn}() {{" in zsh, f"{name}: {fn}() missing from dot_zshrc"
        if windows.startswith("@"):
            fn = windows[1:]
            assert re.search(rf"^function {re.escape(fn)}\b", profile, re.M), (
                f"{name}: function {fn} missing from $PROFILE"
            )


def test_ported_subcommands_have_a_module():
    for name, posix, windows, _ in rows():
        if "python" in (posix, windows):
            assert (ROOT / f"tstack/commands/{name}.py").exists(), name


def test_no_retired_ts_command_names_survive_in_the_shells():
    """No aliases anywhere was the decision; this is what keeps it true."""
    retired = r"(?<![\w./\\-])ts-(?:config|update|doctor|rollback|mux|smb|stack|wezterm)(?!-)(?!\.\w)"
    for path in (ZSHRC, PROFILE):
        found = sorted(set(re.findall(retired, path.read_text(encoding="utf-8"))))
        assert not found, f"{path.name} still references {found}"


# ------------------------------------------------------------------- the CLI


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "tstack/main.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_help_lists_every_subcommand_and_exits_zero():
    out = run_cli("--help")
    assert out.returncode == 0, out.stderr
    for name, _, _, summary in rows():
        assert name in out.stdout, name
        assert summary in out.stdout, name


def test_bare_invocation_prints_help_rather_than_launching_anything():
    bare, helped = run_cli(), run_cli("--help")
    assert bare.returncode == 0
    assert bare.stdout == helped.stdout


def test_all_cli_output_is_ascii_only():
    """A Windows console on codepage 437 renders an em dash as a replacement
    glyph. Caught in phase 0 when the first help text did exactly that, and again
    in the --version error path, which the first version of this test missed.

    Source-level too: a non-ASCII literal anywhere in tstack/ can reach a user.
    """
    for args in (("--help",), ("--version",), ("definitely-not-a-command",)):
        out = run_cli(*args)
        bad = [c for c in out.stdout + out.stderr if ord(c) > 126]
        assert not bad, f"non-ASCII from tstack {' '.join(args)}: {bad}"

    for path in sorted((ROOT / "tstack").rglob("*.py")):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            bad = [c for c in line if ord(c) > 126]
            assert not bad, f"{path.relative_to(ROOT)}:{n} has non-ASCII {bad}"


def test_unknown_subcommand_exits_two_and_suggests():
    out = run_cli("definitely-not-a-command")
    assert out.returncode == 2
    assert "unknown command" in out.stderr
    assert "doctor" in out.stderr


def test_version_json_is_stable():
    out = run_cli("--version", "--json")
    assert out.returncode == 0, out.stderr
    import json

    data = json.loads(out.stdout)
    for key in ("path", "sha", "short", "branch", "dirty", "tstack", "platform"):
        assert key in data, key
    assert data["platform"] in ("windows", "wsl", "linux", "macos")


# --------------------------------------------- claims the audit found unenforced


def test_ts_mux_help_is_byte_identical_between_the_twins():
    """CLAUDE.md asserts this pair is kept byte-identical. Nothing checked it."""
    sh = (ROOT / "bootstrap/ts-mux.sh").read_text(encoding="utf-8")
    ps = PROFILE.read_text(encoding="utf-8")
    bash_help = sh.split("HELP='", 1)[1].split("'\n", 1)[0]
    pwsh_help = ps.split("$script:TsMuxHelp = @'\n", 1)[1].split("\n'@", 1)[0]
    assert bash_help.rstrip("\n") == pwsh_help.rstrip("\n")


def test_wso_help_is_byte_identical_between_the_twins():
    """bootstrap/wso.sh:21-22 states this requirement in a comment. Now enforced."""
    sh = (ROOT / "bootstrap/wso.sh").read_text(encoding="utf-8").splitlines()
    marker = sh[0:30]
    rng = next(l for l in marker if "end of --help text" in l)
    lo, hi = (int(n) for n in re.search(r"lines (\d+)-(\d+)", rng).groups())
    bash_help = "\n".join(re.sub(r"^# ?", "", l) for l in sh[lo - 1 : hi])
    cmd = (ROOT / "bootstrap/_workspace_cmd.ps1").read_text(encoding="utf-8")
    body = cmd.split("function Show-TsWsHelp", 1)[1]
    pwsh_help = body.split("@'\n", 1)[1].split("\n'@", 1)[0]
    assert bash_help.rstrip("\n") == pwsh_help.rstrip("\n")


def test_app_installable_is_pinned_on_both_sides_not_just_bash():
    """The bash half had two assertions; the pwsh twin had none, so it could
    drift silently -- which is the exact failure the rule exists to prevent."""
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "function Test-TsAppInstallable" in ps
    # macOS cannot install nvtop; the id must be filtered, not offered forever.
    sh = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    assert "nvtop" in sh and "ts_app_installable" in sh


def test_the_git_hooks_are_actually_installed_by_something():
    """The gate that had never run.

    .githooks/pre-commit claimed it was "installed by bootstrap.sh --apply /
    bootstrap.ps1 -Apply, which set core.hooksPath". Neither file has ever
    existed in this repo, nothing anywhere set core.hooksPath, and it was unset
    in every clone -- so the repo's only automated gate had never executed. That
    is how a literal TAB byte in $PROFILE survived from 54da056 and how
    services/console's suite stayed red unnoticed.
    """
    sh = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "ts_install_git_hooks()" in sh
    assert "function Install-TsGitHooks" in ps

    for rel in ("bootstrap/wsl-bootstrap.sh",
                "bootstrap/linux-bootstrap.sh",
                "bootstrap/mac-bootstrap.sh"):
        body = (ROOT / rel).read_text(encoding="utf-8")
        assert "ts_install_git_hooks" in body, f"{rel} never installs the hooks"

    # The hook files themselves must stay executable and parseable.
    for name in ("pre-commit", "pre-push"):
        hook = ROOT / ".githooks" / name
        assert hook.exists(), name
        assert hook.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")


def test_the_hooks_never_claim_a_file_that_does_not_exist():
    """The false-provenance class: a comment naming an installer that was never
    written reads as settled and stops anyone checking."""
    for name in ("pre-commit", "pre-push"):
        body = (ROOT / ".githooks" / name).read_text(encoding="utf-8")
        for claimed in re.findall(r"\b(bootstrap[\w./-]*\.(?:sh|ps1))\b", body):
            assert (ROOT / claimed).exists(), f".githooks/{name} names missing {claimed}"


# ---------------------------------------------------- PowerShell hazard lints


def test_no_literal_tab_inside_a_powershell_single_quoted_path():
    r"""$PROFILE:1705 held `Join-Path $src 'bootstrap<TAB>s-stack.ps1'`.

    Single quotes meant pwsh never re-expanded it, Test-Path failed, and every
    ts-stack call on Windows reported "not found" from 54da056 until phase 0.
    """
    offenders = []
    for path in [*list(ROOT.glob("bootstrap/*.ps1")), PROFILE, *list(ROOT.glob("scripts/*.ps1"))]:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"'[^']*\t[^']*'", strip_comment(line)):
                offenders.append(f"{path.relative_to(ROOT)}:{n}")
    assert not offenders, f"literal TAB inside a single-quoted string: {offenders}"


def test_no_where_object_piped_straight_into_set_content():
    """An empty pipeline gives Set-Content nothing to write, so it leaves the file
    untouched -- silently. Filtering a file down to nothing therefore KEEPS the
    line you meant to remove. CLAUDE.md states the rule; nothing enforced it."""
    offenders = []
    for path in [*list(ROOT.glob("bootstrap/*.ps1")), PROFILE, *list(ROOT.glob("scripts/*.ps1"))]:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"Where-Object[^|]*\|\s*Set-Content", strip_comment(line)):
                offenders.append(f"{path.relative_to(ROOT)}:{n}")
    assert not offenders, offenders


@needs_pwsh
def test_splatting_a_lone_dash_flag_survives_the_shim():
    """Regression for the phase-0 argument bug.

    An `if` used as an expression unrolls a single-element array to a scalar, and
    splatting a scalar string beginning with '-' re-parses it as a parameter
    token: `tstack services -h` reached ts-stack.ps1 as two arguments, '-' and
    'h'. With no tail at all it splatted one empty string. Both parse cleanly.
    """
    script = (
        'function Show-Args { $args.Count }\n'
        '$passed = @("services", "-h")\n'
        '$tail = @(if ($passed.Count -gt 1) { $passed[1..($passed.Count - 1)] } else { @() })\n'
        '& "Show-Args" @tail\n'
        '$none = @("services")\n'
        '$t2 = @(if ($none.Count -gt 1) { $none[1..($none.Count - 1)] } else { @() })\n'
        '& "Show-Args" @t2\n'
    )
    out = subprocess.run(
        [PWSH, "-NoLogo", "-NoProfile", "-Command", script],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert out.returncode == 0, out.stderr
    counts = [int(x) for x in out.stdout.split()]
    assert counts == [1, 0], f"expected [1, 0], got {counts} -- the @() wrapper regressed"


# ------------------------------------------------------ the guard's own test


def test_the_vacuity_guard_actually_bites():
    """Proves repo_file fails loudly on a missing target.

    Without this, the guard itself could rot and the whole class of
    "string X must appear in file Y" tests would go quiet again.
    """
    from tests.test_agent_tools import repo_file

    repo_file("dot_zshrc")  # existing path: no raise
    with pytest.raises(AssertionError, match="does not exist"):
        repo_file("bootstrap/this-file-was-deleted.sh")
