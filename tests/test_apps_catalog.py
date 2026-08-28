"""One catalog, three readers.

`bootstrap/apps.conf` replaced two hand-maintained copies -- one in
`bootstrap/_config.sh`, one in `bootstrap/_config.ps1` -- that carried the same
ids, groups, descriptions and default sets and had already drifted: the pwsh
side kept a SECOND id list to express "Windows cannot install this", doing by
omission what `Test-TsAppInstallable` was supposed to do by rule.

What matters is not that the file parses. It is that bash, PowerShell and Python
derive the SAME answers from it, which is what these tests check by running all
three and comparing.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.shell_support import BASH  # noqa: E402
from tstack import apps  # noqa: E402
from tstack import platform as plat  # noqa: E402

CONF = ROOT / "bootstrap/apps.conf"


@pytest.fixture(autouse=True)
def _dev_clone(monkeypatch):
    """Point the reader at THIS checkout, not whatever clone is installed."""
    monkeypatch.setenv("TERMINAL_STACK_DIR", str(ROOT))
    apps.clear_cache()
    yield
    apps.clear_cache()


def _bash(expr: str) -> list[str]:
    got = subprocess.run(
        [BASH, "-c", f". bootstrap/_config.sh >/dev/null 2>&1; {expr}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        start_new_session=True,
    )
    return got.stdout.split()


def _pwsh(expr: str) -> list[str] | None:
    pwsh = plat.find_pwsh()
    if not pwsh:
        return None
    got = subprocess.run(
        [
            pwsh,
            "-NoLogo",
            "-NoProfile",
            "-Command",
            "$env:LOCALAPPDATA = [IO.Path]::GetTempPath(); . ./bootstrap/_config.ps1; " + expr,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        start_new_session=True,
    )
    return got.stdout.split()


# ------------------------------------------------------------------ the file


def test_every_row_has_all_five_fields_and_valid_values():
    """A malformed row is a bug in the table, not user input -- and a silently
    dropped tool is exactly the failure this repo keeps being bitten by."""
    parsed = apps.parse(CONF.read_text(encoding="utf-8"))
    assert len(parsed) > 40
    for app in parsed:
        assert app.classes in apps.CLASSES, app.id
        assert app.platforms in apps.PLATFORMS, app.id
        assert app.description, f"{app.id} has no description"
    assert len({a.id for a in parsed}) == len(parsed), "an id appears twice"


def test_the_catalog_is_ascii():
    """Python reads this and the dashboard prints it, and a Windows console on
    codepage 437 renders anything else as mojibake."""
    body = CONF.read_text(encoding="utf-8")
    assert body.isascii(), [c for c in body if ord(c) > 127]


def test_a_hash_inside_a_description_is_not_a_comment():
    """The description is the rest of the line by definition, so only a
    FULL-LINE comment is a comment. A reader that strips inline `#` silently
    truncates a description."""
    rows = apps.parse("tool  shell  both  all  does a thing # and mentions one\n")
    assert rows[0].description == "does a thing # and mentions one"


def test_a_bad_row_names_itself():
    for bad, why in (
        ("tool  shell  both  all\n", "expected 5 fields"),
        ("tool  shell  nonsense  all  x\n", "unknown class"),
        ("tool  shell  both  solaris  x\n", "unknown platform"),
    ):
        with pytest.raises(ValueError) as caught:
            apps.parse(bad)
        assert why in str(caught.value)


# ------------------------------------------------------- the derived answers


def test_the_default_sets_are_derived_not_listed():
    """Two hand-maintained lists is how they drift. `classes` is the one place
    a tool's membership is stated, and both sets fall out of it."""
    both = {a.id for a in apps.catalog() if a.classes == apps.BOTH}
    dev = {a.id for a in apps.catalog() if a.classes == apps.DEV}
    sys_only = {a.id for a in apps.catalog() if a.classes == apps.SYS}
    assert set(apps.recommended()) == both | dev
    assert set(apps.sysadmin()) == both | sys_only
    # Neither is a subset of the other: a server's kit has the monitors that are
    # merely optional on a laptop, and none of the runtimes or agents.
    assert not set(apps.sysadmin()) <= set(apps.recommended())
    assert not set(apps.recommended()) <= set(apps.sysadmin())


def test_platform_availability_is_a_column_not_a_second_id_list():
    """ "can this platform install it", NOT "is it in winget". Conflating them is
    why a Windows box missing grok/gemini/pi/cursor-agent was never told so."""
    assert not apps.installable("nvtop", plat.MACOS), "NVIDIA/Linux only"
    assert apps.installable("nvtop", plat.LINUX)
    assert not apps.installable("tmux", plat.WINDOWS), "no Windows package"
    assert apps.installable("tmux", plat.WSL), "WSL has apt, so WSL counts"
    assert apps.installable("prettymark", plat.WINDOWS)
    assert not apps.installable("prettymark", plat.MACOS), "Windows-only tool"
    assert apps.installable("fzf", plat.WINDOWS) and apps.installable("fzf", plat.MACOS)


def test_the_inferred_class_cannot_drift_because_it_is_not_stored():
    """A server told on every update that it is missing six agent CLIs it
    declined is the nag `ts_app_installable` was added to end, in a new place."""
    assert apps.saved_class(["eza", "fzf", "btop", "glances"]) == apps.SYSADMIN
    assert apps.saved_class(["eza", "claude"]) == apps.DEVELOPER
    assert apps.saved_class([]) == apps.DEVELOPER, "never configured keeps the old behaviour"


# `_config.sh` is not a Windows file. It decides the platform from `uname -s`,
# which under CI's Git Bash reports MINGW and falls through to "linux" -- so the
# bash reader offers `tmux` while the Python reader, correctly asked about
# Windows, does not. That is a comparison between two readers that never coexist:
# on Windows the catalog is read by pwsh, and
# `test_powershell_and_python_agree_on_the_windows_view` below is what covers it.
NOT_A_BASH_PLATFORM = plat.kind() == plat.WINDOWS


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
@pytest.mark.skipif(NOT_A_BASH_PLATFORM, reason="_config.sh is not read on Windows")
def test_bash_and_python_agree_on_every_derived_set():
    """The whole point of one file. Run on THIS platform, so the comparison
    includes the platform filter rather than skipping past it."""
    here = plat.kind()
    assert sorted(_bash('echo "$TS_APPS_ALL"')) == sorted(apps.ids(here))
    assert sorted(_bash('echo "$TS_APPS_RECOMMENDED"')) == sorted(
        i for i in apps.recommended() if apps.installable(i, here)
    )
    assert sorted(_bash('echo "$TS_APPS_SYSADMIN"')) == sorted(
        i for i in apps.sysadmin() if apps.installable(i, here)
    )
    assert _bash('echo "$TS_APP_GROUPS"') == [g for g in apps.groups() if apps.in_group(g, here)]


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
@pytest.mark.skipif(NOT_A_BASH_PLATFORM, reason="_config.sh is not read on Windows")
def test_bash_and_python_agree_on_group_membership_and_descriptions():
    here = plat.kind()
    for group in apps.groups():
        want = [a.id for a in apps.in_group(group, here)]
        if not want:
            continue
        assert _bash(f"ts_app_group_members {group}") == want, group
    for app in apps.catalog():
        if not apps.installable(app.id, here):
            continue
        got = subprocess.run(
            [BASH, "-c", f'. bootstrap/_config.sh >/dev/null 2>&1; ts_app_desc "{app.id}"'],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            start_new_session=True,
        )
        assert got.stdout.strip() == app.description, app.id


@pytest.mark.pwsh
def test_powershell_and_python_agree_on_the_windows_view():
    """The pwsh reader filters to `all` + `windows`, which is what its second
    hand-maintained id list used to do by omission."""
    got = _pwsh('($script:TsAppsAll | Sort-Object) -join " "')
    if got is None:
        pytest.skip("pwsh is unavailable")
    assert got == sorted(apps.ids(plat.WINDOWS))

    rec = _pwsh('($script:TsAppsRecommended | Sort-Object) -join " "')
    assert rec == sorted(i for i in apps.recommended() if apps.installable(i, plat.WINDOWS))
    sysa = _pwsh('($script:TsAppsSysadmin | Sort-Object) -join " "')
    assert sysa == sorted(i for i in apps.sysadmin() if apps.installable(i, plat.WINDOWS))


@pytest.mark.pwsh
def test_powershell_descriptions_come_from_the_file_too():
    pwsh = plat.find_pwsh()
    if not pwsh:
        pytest.skip("pwsh is unavailable")
    wanted = [a for a in apps.catalog() if apps.installable(a.id, plat.WINDOWS)][:6]
    script = "; ".join(f'Get-TsAppDesc "{a.id}"' for a in wanted)
    got = subprocess.run(
        [
            pwsh,
            "-NoLogo",
            "-NoProfile",
            "-Command",
            "$env:LOCALAPPDATA = [IO.Path]::GetTempPath(); . ./bootstrap/_config.ps1; " + script,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
        start_new_session=True,
    )
    lines = [ln.strip() for ln in got.stdout.splitlines() if ln.strip()]
    assert lines == [a.description for a in wanted]


def test_no_reader_carries_a_hardcoded_id_list_any_more():
    """The point of the file. A list that creeps back is the drift returning."""
    sh = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "TS_APPS_CONF" in sh and "apps.conf" in sh
    assert "Read-TsAppsCatalog" in ps and "apps.conf" in ps
    # The tell-tale shape: a long quoted id run assigned to a catalog variable.
    assert 'TS_APPS_RECOMMENDED="tmux' not in sh
    assert "$script:TsAppsRecommended = @('eza'" not in ps
    assert "$script:TsAppsSysadmin = @(\n" not in ps


def test_the_catalog_reader_survives_a_missing_file(monkeypatch, tmp_path):
    """A partial clone must not take the whole config store down with it."""
    monkeypatch.setenv("TERMINAL_STACK_DIR", str(tmp_path))
    apps.clear_cache()
    assert apps.catalog() == ()
    assert apps.recommended() == [] and apps.groups() == []
    assert apps.saved_class(["eza"]) == apps.DEVELOPER


def test_the_json_read_model_stays_serialisable():
    """The dashboard and any future --json consumer read this."""
    payload = [
        {
            "id": a.id,
            "group": a.group,
            "classes": a.classes,
            "platforms": a.platforms,
            "description": a.description,
        }
        for a in apps.catalog()
    ]
    assert json.loads(json.dumps(payload)) == payload
