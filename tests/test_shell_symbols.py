"""Every stack function a shell script calls must exist somewhere in the tree.

Ports delete things. Moving the install questionnaire out of bash and PowerShell
and into `tstack/wizard/` deleted 21 bash prompt functions and the whole `Read-Ts*`
half of `_config.ps1` -- correctly, they were the questionnaire. What it missed is
that three of them were not questions at all but prompt PRIMITIVES, and that six
non-wizard callers used them:

    ts_prompt_choice        the agents menu, `tstack smb setup`, the rclone
                            wizard, the TTS menu
    ts_tty_prompt           `wso` (six call sites), `_cleanup.sh`, `_smb_setup.sh`
    ts_is_interactive       `_smb_setup.sh`, `ts-rclone-config.sh`

and that five items of each config menu -- leader, theme, apps, session restore,
re-run wizard -- called questions that were now gone. Every one of those paths
died with "command not found" at the moment it prompted, on both platforms, and
nothing caught it: bash resolves a function name at CALL time, `bash -n` checks
syntax only, and PowerShell's parser is equally happy with a command that does
not exist. The same class of bug was already sitting in `_smb_setup.sh`, where a
rename to `ts_smb_conn` had left one caller behind.

So: resolve names statically, the way neither interpreter will.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Names that are deliberately resolved at runtime from somewhere this scan
# cannot see. Keep this empty if you can; an entry is a promise that something
# else guarantees the definition.
BASH_ALLOWED: set[str] = set()
PWSH_ALLOWED: set[str] = set()

# The PowerShell verbs this repo actually uses on its Ts-suffixed functions.
PWSH_VERBS = (
    "Read|Get|Set|Show|Save|Test|Install|Resolve|Invoke|New|Write|Remove|Update"
    "|Repair|Add|Convert|Enable|Sync|Start|Stop|Find|Format|Select|Export|Import"
)


def _sh_sources() -> list[Path]:
    files = [p for p in ROOT.rglob("*.sh") if ".git" not in p.parts]
    files.append(ROOT / "dot_zshrc")
    return [p for p in files if p.is_file()]


def _ps_sources() -> list[Path]:
    return [p for p in ROOT.rglob("*.ps1") if ".git" not in p.parts and p.is_file()]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def test_no_bash_script_calls_a_ts_function_that_no_longer_exists():
    defined = set()
    for p in _sh_sources():
        defined |= {
            m.group(1)
            for m in re.finditer(
                r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{", _read(p), re.M
            )
        }

    dangling = []
    for p in _sh_sources():
        if p.parts[len(ROOT.parts)] not in ("bootstrap", "scripts"):
            continue
        for lineno, line in enumerate(_read(p).splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            code = line.split(" #")[0]
            # Not preceded by $ or a word char (that is a variable or a longer
            # name), and not followed by = (that is an assignment).
            for m in re.finditer(r"(?<![\w.$-])(ts_[a-z0-9_]+|_ts_[a-z0-9_]+)\b(?!\s*=)", code):
                name = m.group(1)
                if name not in defined and name not in BASH_ALLOWED:
                    dangling.append(f"{_rel(p)}:{lineno} calls {name}(), which is defined nowhere")

    assert not dangling, "\n" + "\n".join(dangling)


def test_no_powershell_script_calls_a_ts_function_that_no_longer_exists():
    defined = {
        m.group(1).lower()
        for p in _ps_sources()
        for m in re.finditer(r"^\s*function\s+([A-Za-z][\w-]*)", _read(p), re.M | re.I)
    }

    dangling = []
    for p in _ps_sources():
        for lineno, line in enumerate(_read(p).splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#") or stripped.startswith("<#"):
                continue
            code = line.split(" #")[0]
            for m in re.finditer(rf"(?<![\w.$-])((?:{PWSH_VERBS})-Ts[\w]*)", code):
                name = m.group(1)
                if name.lower() not in defined and name not in PWSH_ALLOWED:
                    dangling.append(f"{_rel(p)}:{lineno} calls {name}, which is defined nowhere")

    assert not dangling, "\n" + "\n".join(dangling)


def test_the_prompt_primitives_live_outside_the_questionnaire():
    """The specific arrangement that stops the regression recurring.

    These three are not wizard questions and must not live with the wizard: they
    are what every OTHER prompt in the stack is built from. `_config.sh` and
    `_config.ps1` are what the callers already source.
    """
    sh = _read(ROOT / "bootstrap/_config.sh")
    for fn in ("ts_tty_prompt()", "ts_is_interactive()", "ts_prompt_choice()"):
        assert fn in sh, f"{fn} left bootstrap/_config.sh"

    ps = _read(ROOT / "bootstrap/_config.ps1")
    for fn in ("function Read-TsChoice", "function Resolve-TsChoiceAnswer"):
        assert fn in ps, f"{fn} left bootstrap/_config.ps1"

    wiz = _read(ROOT / "bootstrap/_wizard.sh")
    assert "ts_prompt_choice()" not in wiz, "the primitive moved back into the questionnaire"


def test_both_config_menus_ask_with_the_same_options():
    """The menus are twins, and they were both broken in the same five places.

    Leader and theme are the two questions the menu asks itself rather than
    handing to the wizard, so the option sets are written twice. Pin them
    together: a chord added on one side and not the other is a silent drift.
    """
    sh = _read(ROOT / "bootstrap/ts-config.sh")
    ps = _read(ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1")

    for chord in ("ctrl-space", "ctrl-a", "ctrl-b", "alt-space"):
        assert chord in sh.split("menu_leader()")[1][:600], f"{chord} missing from menu_leader"
        assert chord in ps.split("$menuLeader = {")[1][:800], f"{chord} missing from $menuLeader"

    for mode in ("dark", "light", "follow"):
        assert mode in sh.split("menu_theme()")[1][:500], f"{mode} missing from menu_theme"
        assert mode in ps.split("$menuTheme = {")[1][:700], f"{mode} missing from $menuTheme"


def test_the_windows_wizard_runner_has_exactly_one_implementation():
    """Two callers, one runner.

    `windows-bootstrap.ps1` and `$PROFILE`'s `tstack config wizard` both run the
    Python questionnaire and read its JSON. When each had its own copy, $PROFILE
    was left calling a `Read-TsWizard` that no longer existed and reading a
    `$w.Workspace` the JSON never carried -- which persisted an empty
    WORKSPACE_DIR rather than failing.
    """
    ps = _read(ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1")
    assert "Invoke-TsWizard" in ps
    assert "Save-TsWorkspaceOverride (Read-TsWorkspaceDir)" in ps
    code = [ln for ln in ps.splitlines() if not ln.lstrip().startswith("#")]
    assert "$w.Workspace" not in "\n".join(code), "reading a key the wizard JSON does not emit"


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell 7 is unavailable")
def test_the_config_helper_loads_where_there_is_no_windows_side():
    """`docs/powershell-quirks.md` gives a strict-mode repro for checking the
    `tstack config` path. The repro itself threw.

    `Get-TsConfigPath` was `Join-Path $env:LOCALAPPDATA ...`, and pwsh runs on
    macOS and Linux where that variable is unset -- `Join-Path -Path $null` is a
    terminating error, so dot-sourcing the helper and calling `Get-TsConfig` died
    before returning anything. Python's twin (`tstack/store.py` `mirror_path`)
    already returns None when there is no Windows side; this now matches, and
    `Get-TsConfig` falls through to the defaults it already carries.

    On Windows LOCALAPPDATA is always set, so none of this changes behaviour there.
    """
    script = (
        "Set-StrictMode -Version Latest; "
        f". '{ROOT / 'bootstrap/_config.ps1'}'; "
        "$env:LOCALAPPDATA = ''; "
        "if ($null -ne (Get-TsConfigPath)) { throw 'expected $null with no LOCALAPPDATA' }; "
        "(Get-TsConfig).leaderChord"
    )
    got = subprocess.run(
        [shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
        start_new_session=True,
    )
    assert got.returncode == 0, got.stdout + got.stderr
    assert "ctrl-space" in got.stdout


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell 7 is unavailable")
def test_the_restored_choice_prompt_is_strict_mode_safe():
    """The trap `powershell-quirks.md` records against this exact function: an
    option with no `Note` must not crash the first question of the wizard. It
    reads `$o['Note']`, which is `$null` for a missing key under any strictness;
    `$o.Note` throws."""
    script = (
        "Set-StrictMode -Version Latest; "
        f". '{ROOT / 'bootstrap/_config.ps1'}'; "
        "Read-TsChoice -Title 'Leader key:' -Default 'ctrl-space' "
        "-Options @(@{Key='ctrl-space';Label='Ctrl+Space'},"
        "@{Key='ctrl-a';Label='Ctrl+A';Note='tmux muscle memory'})"
    )
    got = subprocess.run(
        [shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
        start_new_session=True,
    )
    assert got.returncode == 0, got.stdout + got.stderr
    assert got.stdout.strip().splitlines()[-1] == "ctrl-space"
