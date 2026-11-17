"""`tstack keys` (bootstrap/ts-keymap.ps1): every keyboard shortcut in one CSV.

The script is Windows-only at run time, but its help returns before the
platform check, so the collector list can be checked anywhere pwsh exists.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "bootstrap/ts-keymap.ps1"
HOOK = ROOT / "bootstrap/hkspy"


def _collectors() -> list[str]:
    text = SCRIPT.read_text(encoding="utf-8")
    block = text[text.index("$script:AllCollectors") : text.index("if ($Help)")]
    return re.findall(r"^\s{4}(\w+)\s+=", block, re.M)


def test_keys_is_registered_for_windows_only():
    row = next(
        line.split()
        for line in (ROOT / "tstack/commands.conf").read_text(encoding="utf-8").splitlines()
        if line.startswith("keys ")
    )
    assert row[1] == "-", "keys reads Windows hotkeys; POSIX must say 'not available'"
    assert row[2] == "bootstrap/ts-keymap.ps1"


def test_every_collector_is_dispatched():
    """A collector listed in -Help but missing from the dispatch table is a
    silent no-op: -Collect accepts the name and runs nothing."""
    text = SCRIPT.read_text(encoding="utf-8")
    dispatch = text[text.index("$dispatch = @{") : text.index("foreach ($x in $want)")]
    names = _collectors()
    assert "probe" in names and "deepscan" in names
    for name in names:
        assert re.search(rf"\b{name} = \{{ Invoke-Km", dispatch), f"{name} is not dispatched"


def test_the_hook_does_nothing_without_the_loaders_config():
    """The DLL stays loaded in other processes after the loader unhooks. It must
    act only while the loader's shared config exists, or it would keep
    swallowing hotkeys in every GUI process until they exit."""
    src = (HOOK / "src/lib.rs").read_text(encoding="utf-8")
    assert "if let Some(cfg) = read_config()" in src
    assert "msg.message = WM_NULL" in src
    swallow = src.index("msg.message = WM_NULL")
    assert src.rindex("if cfg.swallow", 0, swallow) > src.index("read_config()")
    assert 'crate-type = ["cdylib"]' in (HOOK / "Cargo.toml").read_text(encoding="utf-8")


def test_identify_never_presses_the_chords_windows_acts_on_directly():
    """Win+L locks the PC and is not a WM_HOTKEY, so no hook can swallow it."""
    text = SCRIPT.read_text(encoding="utf-8")
    deny = text[text.index("$deny = @(") :].split("\n", 1)[0]
    for chord in ("Win+L", "Ctrl+Alt+Delete", "Ctrl+Shift+Esc"):
        assert f"'{chord}'" in deny


@pytest.mark.skipif(not shutil.which("pwsh"), reason="PowerShell 7 is unavailable")
def test_the_script_parses_and_help_lists_every_collector():
    pwsh = shutil.which("pwsh")
    assert pwsh
    parse = subprocess.run(
        [
            pwsh,
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile("
            f"'{SCRIPT}', [ref]$null, [ref]$e); $e.Count",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=120,
        start_new_session=True,
    )
    assert parse.stdout.strip() == "0", parse.stdout
    shown = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT), "-Help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        timeout=120,
        start_new_session=True,
    ).stdout
    for name in _collectors():
        assert re.search(rf"^\s+{name}\s", shown, re.M), f"-Help does not list {name}"
