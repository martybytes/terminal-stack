"""Getting AGENTMEMORY_SECRET to the processes that need it.

Three consumers, three reaches:

  terminal agents      ~/.zshrc would do -- but so does ~/.zshenv, and only one
                       of them also covers the next case
  hook subprocesses    NON-INTERACTIVE, so zsh never sources ~/.zshrc for them.
                       A variable exported there reaches nothing and logs
                       nothing, because every agentmemory hook does
                       `fetch(...).catch(() => {})` and then exits 0
  GUI Cursor / Codex   launched by launchd, which reads no shell file at all

So: a spliced ~/.zshenv block for the first two, and a LaunchAgent for the third.
These tests are about the two properties that make either safe -- the file is
part-owned, and the value is read rather than embedded.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.shell_support import BASH  # noqa: E402
from tests.test_agent_tools import repo_file  # noqa: E402

TEMPLATE = "modify_dot_zshenv.tmpl"
PLIST = "Library/LaunchAgents/com.terminal-stack.agentmemory-secret.plist.tmpl"
HOOK = "run_after_40-launchagents.sh"
CACHE = "terminal-stack/agentmemory.secret"


# The template's ONLY Go construct, pinned so the renderer below cannot drift
# away from it. chezmoi is not used to render: pointing `--source` at this repo
# makes it reach for .git/index.lock, which is a lock this test has no business
# taking, and rendering one if/else needs none of chezmoi.
GATE_IF = '{{- if eq (index . "agentmemoryEnabled" | default "off") "on" }}'
GATE_ELSE = "{{- else }}"
GATE_END = "{{- end }}"


def _render(agentmemory: str) -> str:
    """The template as chezmoi would render it for a given setting."""
    body = repo_file(TEMPLATE).read_text(encoding="utf-8")
    markers = [ln for ln in body.splitlines() if ln.startswith("{{")]
    assert markers == [GATE_IF, GATE_ELSE, GATE_END], (
        f"the template grew a construct this renderer does not handle: {markers}"
    )
    head, _, rest = body.partition(GATE_IF + "\n")
    on_branch, _, rest = rest.partition(GATE_ELSE + "\n")
    off_branch, _, tail = rest.partition(GATE_END + "\n")
    return head + (on_branch if agentmemory == "on" else off_branch) + tail


def _run(script: str, stdin: str) -> str:
    got = subprocess.run(
        [BASH, "-c", script],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=60,
        start_new_session=True,
        check=False,
    )
    assert got.returncode == 0, got.stderr
    return got.stdout


# ------------------------------------------------------------------- the block


def test_it_is_zshenv_and_not_zshrc():
    """The whole reason the file is .zshenv.

    zsh sources .zshrc for INTERACTIVE shells only. Agent hooks are
    non-interactive subprocesses, so a variable exported from .zshrc reaches
    none of them -- and the failure is silent, which is why it has to be pinned
    rather than remembered.
    """
    assert repo_file(TEMPLATE).name == "modify_dot_zshenv.tmpl"
    body = repo_file(TEMPLATE).read_text(encoding="utf-8")
    assert "non-interactive" in body.lower(), "the reason belongs next to the rule"
    assert not (ROOT / "dot_zshrc.tmpl").exists(), (
        "dot_zshrc must stay a non-template: `chezmoi re-add ~/.zshrc` is a "
        "documented workflow and would clobber template directives"
    )


def test_the_value_is_read_not_embedded():
    """A hardcoded secret works until the container regenerates /data/.hmac and
    then 401s on every request with the error swallowed -- 56 consecutive
    captures were lost that way on 2026-08-21. Both carriers read the cache."""
    for rel in (TEMPLATE, PLIST):
        body = repo_file(rel).read_text(encoding="utf-8")
        assert CACHE in body, f"{rel} must read the 0600 cache"
        assert "XDG_CONFIG_HOME" in body, f"{rel} must honour XDG_CONFIG_HOME"


def test_the_block_does_not_fork():
    """.zshenv runs for EVERY zsh, including every hook subprocess. `$(<file)` is
    a zsh builtin read; `$(cat file)` would be a process per shell."""
    body = repo_file(TEMPLATE).read_text(encoding="utf-8")
    exported = [ln for ln in body.splitlines() if "export AGENTMEMORY_SECRET" in ln]
    assert exported, "nothing exports the secret"
    for line in exported:
        assert "$(<" in line, f"forks per shell: {line.strip()}"
        assert "cat " not in line, f"forks per shell: {line.strip()}"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_foreign_content_survives():
    """~/.zshenv is where rustup writes `. \"$HOME/.cargo/env\"`, and where nvm,
    pyenv and a person's own exports live. A whole-file target would delete all
    of it with no error and nothing in `chezmoi diff` -- the failure that removed
    every Claude TTS hook and emptied ~/.cursor/hooks.json."""
    script = _render("on")
    foreign = '. "$HOME/.cargo/env"\nexport EDITOR=micro\n'
    out = _run(script, foreign)
    assert '. "$HOME/.cargo/env"' in out
    assert "export EDITOR=micro" in out
    assert "terminal-stack-agentmemory-start" in out


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_it_is_idempotent():
    """An apply runs on every update. Two runs must not leave two blocks."""
    script = _render("on")
    once = _run(script, '. "$HOME/.cargo/env"\n')
    twice = _run(script, once)
    assert once == twice
    assert once.count("terminal-stack-agentmemory-start") == 1


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_off_removes_the_block_and_keeps_the_rest():
    """Turning the feature off must actually stop exporting the secret, not leave
    a stale block behind."""
    on = _run(_render("on"), '. "$HOME/.cargo/env"\n')
    off = _run(_render("off"), on)
    assert "terminal-stack-agentmemory" not in off
    assert '. "$HOME/.cargo/env"' in off


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_an_empty_zshenv_is_fine():
    """A fresh machine has no ~/.zshenv at all, so chezmoi hands the script
    nothing on stdin."""
    out = _run(_render("on"), "")
    assert out.startswith("# ---- terminal-stack-agentmemory-start ----")


# -------------------------------------------------------------- the LaunchAgent


def test_the_plist_exits_clean_when_there_is_no_cache():
    """agentmemory not being set up yet is a normal state, not a login-time
    error worth a crash report."""
    body = repo_file(PLIST).read_text(encoding="utf-8")
    assert "exit 0" in body
    assert "launchctl setenv AGENTMEMORY_SECRET" in body


def test_the_plist_is_gated_on_darwin_and_on_the_setting():
    """~/Library/LaunchAgents is a Darwin path, and a login job that reads a file
    nobody writes is worse than no job."""
    ignore = repo_file(".chezmoiignore").read_text(encoding="utf-8")
    assert 'ne .chezmoi.os "darwin"' in ignore
    assert 'ne (index . "agentmemoryEnabled" | default "off") "on"' in ignore
    # The DIRECTORY as well as its contents: naming only `Library/**` still
    # creates an empty ~/Library/LaunchAgents on every machine that opted out.
    assert ignore.count("\nLibrary\nLibrary/**\n") == 2, (
        "both gates must name the directory and its contents"
    )


def test_the_loader_is_darwin_guarded_and_never_fails_an_apply():
    """A run_after runs on every target. Finding out by `launchctl: command not
    found` is not a diagnosis, and a login job that could not be reloaded is not
    worth aborting the deployment of everything else."""
    body = repo_file(HOOK).read_text(encoding="utf-8")
    assert "uname -s" in body and "Darwin" in body
    assert "command -v launchctl" in body
    # bootout before bootstrap, or launchd keeps running the previous definition
    # until the next logout.
    assert body.index("launchctl bootout") < body.index("launchctl bootstrap")


def test_check_capture_scans_what_this_change_added():
    """Both carriers are the obvious place for a future "just inline it" change,
    and both were unscanned by the guard that exists to catch exactly that."""
    body = repo_file("services/stacks/agentmemory/check-capture.sh").read_text(encoding="utf-8")
    assert "com.terminal-stack.agentmemory-secret.plist" in body
    assert "$HOME/.zshenv" in body
