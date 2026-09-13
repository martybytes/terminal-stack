"""The installers' services step: every call site, and the order it runs in.

Text-anchored gates, because the thing being pinned is a wiring decision spread
across six shell and PowerShell files that no unit test reaches. Every path goes
through `repo_file`, so a moved or deleted target fails loudly rather than
turning an `in` assertion vacuously true.

The six call sites are the point. The wizard-answer path exists in six places,
not the four people remember, and the two that are easy to forget --
`ts-config.sh::run_wizard` and `$runWizard` in the profile -- are exactly the
`tstack config wizard` / `reconfigure` re-runs. Shipping four of six leaves a
re-run silently on the old behaviour, which is the bug the ts_memory_apply line
in run_wizard was itself added to fix.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from test_agent_tools import repo_file  # noqa: E402

BASH_HELPER = "ts_services_apply_wizard"
PWSH_HELPER = "Invoke-TsServicesWizard"

BASH_SITES = (
    "bootstrap/linux-bootstrap.sh",
    "bootstrap/wsl-bootstrap.sh",
    "bootstrap/mac-bootstrap.sh",
    "bootstrap/ts-config.sh",
)
PWSH_SITES = (
    "bootstrap/windows-bootstrap.ps1",
    "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1",
)


def body(rel: str) -> str:
    return repo_file(rel).read_text(encoding="utf-8")


def test_every_wizard_call_site_runs_the_one_services_helper():
    """Four bash, two PowerShell. The two re-run paths are the ones that drift."""
    for rel in BASH_SITES:
        assert BASH_HELPER in body(rel), f"{rel} never runs the services step"
    for rel in PWSH_SITES:
        assert PWSH_HELPER in body(rel), f"{rel} never runs the services step"


def test_the_services_step_runs_before_the_agent_wiring():
    """Ordering IS the fix for the doubled warning in the reported install log.

    `tstack agents headroom` calls Headroom.token(), which reads
    services/stacks/headroom/.env -- the file `services bootstrap` is what
    creates. Run the wiring first and it reports "proxy token unavailable" for a
    token that is about to exist.
    """
    for rel in ("bootstrap/linux-bootstrap.sh", "bootstrap/wsl-bootstrap.sh"):
        text = body(rel)
        assert text.index(BASH_HELPER) < text.index("ts_agents_apply_wizard"), rel
    mac = body("bootstrap/mac-bootstrap.sh")
    assert mac.index(BASH_HELPER) < mac.rindex("ts_agents_apply_wizard")
    win = body("bootstrap/windows-bootstrap.ps1")
    assert win.index(PWSH_HELPER) < win.index("agents headroom on")


def test_the_bring_up_is_gated_on_the_answer_and_bootstrap_is_not():
    """The whole shape of the change: bootstrap is free, `up` is the question.

    `services bootstrap` needs no engine, no network and no consent, and is what
    writes the .env files and generates HEADROOM_PROXY_TOKEN. `services up`
    pulls 1-2 GB. Conflating them would either leave the reported bug unfixed or
    pull gigabytes at everyone.
    """
    sh = body("bootstrap/_config.sh")
    helper = sh[sh.index(f"{BASH_HELPER}() {{") :]
    helper = helper[: helper.index("\n}\n") + 2]
    assert "services bootstrap" in helper
    assert helper.index("services bootstrap") < helper.index("TS_WIZ_SERVICES")
    assert helper.index("TS_WIZ_SERVICES") < helper.index("services up")

    ps = body("bootstrap/_config.ps1")
    fn = ps[ps.index(f"function {PWSH_HELPER}") :]
    fn = fn[: fn.index("\n}\n") + 2]
    assert fn.index("services bootstrap") < fn.index("$Services -ne 'on'")
    assert fn.index("$Services -ne 'on'") < fn.index("services up")


def test_a_failed_services_step_never_aborts_the_install():
    """An optional step that dies takes every answered question with it -- the
    incident recorded in _common-posix.sh's ORDERING comment. A multi-gigabyte
    pull over a bad link is the likeliest step in the whole install to die."""
    sh = body("bootstrap/_config.sh")
    helper = sh[sh.index(f"{BASH_HELPER}() {{") :]
    helper = helper[: helper.index("\n}\n") + 2]
    assert helper.count("ts_note_failure") == 2, "both steps warn rather than abort"
    assert "tstack services bootstrap" in helper and "tstack services up" in helper

    ps = body("bootstrap/_config.ps1")
    fn = ps[ps.index(f"function {PWSH_HELPER}") :]
    fn = fn[: fn.index("\n}\n") + 2]
    assert fn.count("Write-Warning") == 2
    assert "throw" not in fn


def test_no_bootstrap_splats_the_memory_pair_into_save_tsconfig():
    """Save-TsConfig writes keys and nothing else. Only Set-TsMemoryBackend also
    rewrites headroom's COMPOSE_FILE, which is what carries `--memory`.

    windows-bootstrap.ps1 splatted both keys and so never wrote the overlay; the
    profile's $runWizard hand-rolled the same three calls, which is how the
    bootstrap came to do two of them and miss the third.
    """
    win = body("bootstrap/windows-bootstrap.ps1")
    splat = win[win.index("$saveArgs = @{") :]
    splat = splat[: splat.index("\n}\n")]
    assert "MemoryBackend" not in splat
    assert "AgentmemoryEnabled" not in splat
    assert "Set-TsMemoryBackend" in win

    profile = body("windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1")
    assert "-AgentmemoryEnabled $w.Agentmemory" not in profile
    assert "Set-TsMemoryBackend $w.MemoryBackend" in profile


def test_the_services_helper_never_probes_the_engine_itself():
    """One engine probe, in tstack/engine.py. `tstack services` already refuses
    on the NEEDS_ENGINE path and prints engine_advice from the one implementation
    of both -- and the check a shell reaches for first, `command -v docker`, is
    the one engine.py's docstring calls "true and useless"."""
    sh = body("bootstrap/_config.sh")
    helper = sh[sh.index(f"{BASH_HELPER}() {{") :]
    helper = helper[: helper.index("\n}\n") + 2]
    code = "\n".join(line for line in helper.splitlines() if not line.lstrip().startswith("#"))
    assert "command -v docker" not in code
    assert "docker" not in code.replace("docker services", "").replace("tstack services", "")


def test_the_memory_set_path_seeds_before_it_restarts():
    """The bash twin of the same ordering fix in tstack/commands/config.py.

    `restart` is down+up, and `up` on an unseeded headroom dies at `compose
    config` about a VARIABLE rather than about the file that is missing.
    """
    sh = body("bootstrap/ts-config.sh")
    fn = sh[sh.index("memory_set() {") :]
    fn = fn[: fn.index("\n}\n") + 2]
    assert fn.index("services bootstrap") < fn.index("services restart headroom")
    # Comments stripped first: this function explains at length why it does not
    # use `command -v docker`, and a blunt substring check fails on the
    # explanation -- the same way a regex guard matches the example in its own
    # docstring.
    code = "\n".join(line for line in fn.splitlines() if not line.lstrip().startswith("#"))
    assert "command -v docker" not in code, "the engine probe lives in one place"
