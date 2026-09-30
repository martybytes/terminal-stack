"""`tstack update`'s "install them now?" and the `apps` writer behind it.

Text-anchored, because the failure lives in the hand-off between zsh, bash and
Python: the pending list crossed as a space-separated string, the picker split
on commas only, and `set_apps` saved the empty result as the whole selection --
erasing every tool the machine had chosen, after the user said yes.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_agent_tools import repo_file  # noqa: E402


def test_update_hands_apps_the_union_not_just_the_missing_tools():
    """`apps` saves its argument as the WHOLE selection, and pending includes
    class defaults that were never saved. The pwsh twin merges; so must zsh."""
    body = repo_file("dot_zshrc").read_text(encoding="utf-8")
    start = body.index("_tstack_update() {")
    update = body[start : body.index("\n}\n", start)]
    call = re.search(r'ts-config\.sh" apps "([^"]*)"', update)
    assert call, "tstack update no longer installs pending apps through ts-config.sh"
    assert "$_saved" in call.group(1) and "$pending" in call.group(1)
    assert "ts_data_get_apps" in update


def test_the_pwsh_twin_still_merges_before_saving():
    body = repo_file("windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    assert "@($cfg.apps) + $pending" in body


def test_a_spec_that_resolves_to_nothing_never_overwrites_the_selection():
    body = repo_file("bootstrap/ts-config.sh").read_text(encoding="utf-8")
    arm = body[body.index("    apps)") :]
    arm = arm[: arm.index(";;")]
    guard = arm.index('[ -z "$_apps_sel" ]')
    assert guard < arm.index('set_apps "$_apps_sel"'), (
        "the empty-result guard must run before the save"
    )
    assert "exit 2" in arm[guard:]
