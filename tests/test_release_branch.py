"""The branch a runtime clone tracks, and the two ways that used to go wrong.

Both failures were invisible to the suite before this module existed, because
nothing anywhere asserted a branch name:

1.  No installer passed a branch to `git clone`, so the tree an install landed
    was decided by the repo's DEFAULT branch on GitHub -- while every documented
    one-liner was fetched from `main`. Installer and installed tree came from
    different branches for months.

2.  `tstack update` inferred "nothing incoming" from an EMPTY `HEAD..@{u}`, which
    is also what that command prints when it fails outright. A clone left on a
    merged-and-deleted feature branch reported "already up to date" forever, exit
    0, and applied anyway.

The constant is carried six times over because the shells cannot import Python
and the installers cannot import anything at all -- they run before a clone
exists. Duplication is therefore the design; drift is what this module prevents.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_agent_tools import read_repo  # noqa: E402
from tstack import paths  # noqa: E402

BASH_INSTALLERS = ("install-mac.sh", "install-wsl.sh", "install-linux.sh")

# Every carrier of the literal, and the pattern that extracts it.
CARRIERS = {
    "install-mac.sh": r"^RELEASE_BRANCH='([^']+)'",
    "install-wsl.sh": r"^RELEASE_BRANCH='([^']+)'",
    "install-linux.sh": r"^RELEASE_BRANCH='([^']+)'",
    "install.ps1": r"^\$releaseBranch = '([^']+)'",
    "dot_zshrc": r"^_TS_RELEASE_BRANCH=\"([^\"]+)\"",
    "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1": (
        r"^\$script:TsReleaseBranch = '([^']+)'"
    ),
}


def test_every_implementation_names_the_same_release_branch():
    found = {"tstack/paths.py": paths.RELEASE_BRANCH}
    for rel, pattern in CARRIERS.items():
        match = re.search(pattern, read_repo(rel), re.MULTILINE)
        assert match, f"{rel} no longer declares a release branch constant"
        found[rel] = match.group(1)
    assert len(set(found.values())) == 1, f"release branch has drifted: {found}"


def test_the_release_branch_is_main_not_the_repo_default():
    """An installer must land a released tree, whatever GitHub's default is.

    AGENTS.md is the authority on the branching model and now names `main` for
    all three roles. This pins the half of it that code depends on, so a settings
    change on GitHub cannot quietly redecide what a fresh install gets -- which
    is exactly what happened when the default moved to `develop`.
    """
    assert paths.RELEASE_BRANCH == "main"


def test_no_installer_clones_without_pinning_the_branch():
    for rel in (*BASH_INSTALLERS, "install.ps1"):
        text = read_repo(rel)
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "git clone" not in stripped:
                continue
            assert "--branch" in stripped, (
                f"{rel}: `git clone` with no --branch inherits the repo default "
                f"branch, which is not the release branch: {stripped}"
            )


def test_each_installer_realigns_an_existing_clone_before_pulling():
    """The pull is what fails on a deleted branch, so the fix must precede it."""
    for rel in BASH_INSTALLERS:
        text = read_repo(rel)
        assert "ts_align_branch" in text, f"{rel} does not realign an existing clone"
        assert text.index('ts_align_branch "$TARGET_DIR"') < text.index(
            'git -C "$TARGET_DIR" pull --ff-only'
        ), f"{rel} realigns after the pull that the misalignment breaks"
    ps = read_repo("install.ps1")
    assert ps.index("Set-TsCloneBranch -CloneDir") < ps.index("git -C $targetDir pull --ff-only")


def test_realignment_never_touches_a_dirty_clone():
    """Switching branches under uncommitted work either fails or carries it across."""
    for rel in BASH_INSTALLERS:
        text = read_repo(rel)
        block = text[text.index("ts_align_branch() {") :]
        block = block[: block.index("\n}\n")]
        assert "status --porcelain" in block
        assert "leaving it on its current branch" in block
    ps = read_repo("install.ps1")
    block = ps[ps.index("function Set-TsCloneBranch") :]
    assert "status --porcelain" in block[:1200]


def test_both_update_twins_prune_and_name_the_upstream():
    """--prune, or a deleted branch still looks alive through its stale ref."""
    zsh = read_repo("dot_zshrc")
    block = zsh[zsh.index("_tstack_update() {") :]
    assert "fetch --quiet --prune" in block[: block.index("\n}\n")]
    assert "--symbolic-full-name '@{u}'" in block, (
        "update must ask for the upstream by name; an empty HEAD..@{u} cannot "
        "tell 'nothing incoming' from 'that command failed'"
    )
    assert "has no upstream on the remote" in block

    ps = read_repo("windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1")
    assert "fetch --quiet --prune" in ps
    assert "--symbolic-full-name '@{u}'" in ps
    assert "has no upstream on the remote" in ps


def test_the_upstream_query_is_judged_by_its_exit_status_not_its_output():
    """`git rev-parse @{u}` exits 128 AND prints the literal "@{u}" on stdout.

    A plain capture therefore reads a gone upstream as one helpfully named
    "@{u}", which is non-empty and so looks healthy -- the same class of mistake
    as the empty-diff inference this replaced, and it was in the first cut of the
    replacement. The bash installers and tstack/paths.py were always safe (an
    `if git ...` and a returncode test respectively); the two shells had to be
    told.
    """
    zsh = read_repo("dot_zshrc")
    assert (
        'if ! upstream="$(git -C "$src" rev-parse --abbrev-ref '
        "--symbolic-full-name '@{u}' 2>/dev/null)\"; then" in zsh
    ), "zsh must branch on git's exit status, not on whether the capture is empty"

    ps = read_repo("windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1")
    after = ps[ps.index("$upstream = & git -C $SourceDir rev-parse") :][:400]
    assert "if ($LASTEXITCODE -ne 0) { $upstream = $null }" in after


def test_a_gone_upstream_stops_the_update_rather_than_applying():
    """It used to print "already up to date" and apply. Silence was the bug."""
    zsh = read_repo("dot_zshrc")
    block = zsh[zsh.index("_tstack_update() {") :]
    block = block[: block.index("\n}\n")]
    assert block.index('if [[ -z "$upstream" ]]; then') < block.index(
        'echo "==> already up to date"'
    )
    ps = read_repo("windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1")
    assert ps.index("if (-not $upstream)") < ps.index("Write-Host '==> already up to date'")
