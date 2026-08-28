"""The install questionnaire, once, in Python.

Replaced `bootstrap/_wizard.sh` (944 lines) and the `Read-Ts*` half of
`bootstrap/_config.ps1` (~800) -- two implementations of the same fourteen
questions, kept in agreement by hand and already drifted: the pwsh tick-list
rejected a whole multi-answer where bash applied the valid tokens and warned
about the rest.

Every test drives a SCRIPTED console, so the suite exercises the real prompt
loops without a terminal and without the flakiness of a pty.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import store  # noqa: E402
from tstack.wizard import emit, flow  # noqa: E402
from tstack.wizard.console import Console  # noqa: E402
from tstack.wizard.prompts import Option, choice, collapse_exclusive, multi  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path):
    """No TS_* leaking in from the developer's shell, and a throwaway store."""
    for name in list(__import__("os").environ):
        if name.startswith("TS_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TERMINAL_STACK_DIR", str(ROOT))
    monkeypatch.setattr(store, "chezmoi_data", lambda: {})
    monkeypatch.setattr(store, "mirror", lambda: {})
    monkeypatch.setattr(store, "mirror_path", lambda: None)
    store.clear_cache()
    yield
    store.clear_cache()


# --------------------------------------------------------------- the console


def test_the_wizard_reads_the_terminal_and_never_stdin():
    """`curl ... | bash` and `irm ... | iex` are documented install paths, and on
    both of them stdin is the SCRIPT. Reading answers from it would consume the
    installer and prompt with its own source."""
    body = (ROOT / "tstack/wizard/console.py").read_text(encoding="utf-8")
    assert '"/dev/tty"' in body
    assert "CONIN$" in body and "CONOUT$" in body
    assert "sys.stdin" not in body, "stdin is the installer, not the answers"


def test_a_console_that_cannot_open_a_terminal_is_not_an_error():
    """A container, a CI runner and a piped installer all land here, and every
    one of them must still complete with defaults."""
    console = Console()
    assert not console.interactive
    assert console.ask("anything? ") is None
    console.say("this goes nowhere")


def test_eof_is_an_empty_answer_not_a_failure():
    """EOF on an open tty means take the default and move on, exactly as Enter
    does. Treating it as an error strands a half-configured machine."""
    console = Console.scripted([])
    assert console.ask("q: ") == ""


# -------------------------------------------------------------- the choice


def _pick(script: list[str], default: str = "dark") -> tuple[str, bool]:
    options = [Option("dark", "dark"), Option("light", "light"), Option("follow", "follow OS")]
    return choice(Console.scripted(script), "Theme:", options, default)


def test_a_choice_accepts_an_index_a_name_or_enter():
    assert _pick(["2"])[0] == "light"
    assert _pick([""])[0] == "dark", "Enter takes the default"
    assert _pick(["follow"])[0] == "follow"
    assert _pick(["FOLLOW"])[0] == "follow", "case-insensitive"
    assert _pick([" 3 "])[0] == "follow", "whitespace is stripped"


def test_a_choice_gives_up_after_three_wrong_answers():
    """An automated caller feeding rubbish can never spin here."""
    value, asked = _pick(["9", "nonsense", "zz", "2"])
    assert value == "dark", "the default, not the fourth answer"
    assert asked


def test_a_choice_returns_its_default_verbatim_and_unvalidated():
    """Load-bearing for the prompt question: it offers what the installed
    starship ships and defaults to whatever is saved, which may be a preset this
    machine no longer has. Silently rewriting someone's saved value to the first
    row would be worse than offering it back."""
    assert _pick([""], default="a-preset-that-is-gone")[0] == "a-preset-that-is-gone"


def test_a_non_interactive_choice_takes_the_default_and_says_so():
    console = Console()
    value, asked = choice(console, "Theme:", [Option("dark"), Option("light")], "dark")
    assert (value, asked) == ("dark", False)


# ------------------------------------------------------------- the tick-list


TERMINALS = [Option("wezterm-nightly"), Option("wezterm-stable"), Option("ghostty")]
GROUP = ("wezterm-nightly", "wezterm-stable")


def test_ticking_outside_an_exclusive_group_leaves_it_alone():
    """The bug this guard exists for: `keep` is an index no group member equals,
    so every ticked member failed `j == keep` and was cleared -- ticking Ghostty
    silently unticked WezTerm on macOS."""
    console = Console.scripted(["3", ""])
    got, _asked = multi(console, "Terminals:", TERMINALS, ["wezterm-nightly"], exclusive=GROUP)
    assert got == ["wezterm-nightly", "ghostty"]


def test_ticking_inside_the_group_collapses_it():
    console = Console.scripted(["2", ""])
    got, _asked = multi(console, "Terminals:", TERMINALS, ["wezterm-nightly"], exclusive=GROUP)
    assert got == ["wezterm-stable"], "the two channels cannot coexist"


def test_both_preticked_collapses_before_the_first_render():
    """A machine mid-channel-switch can legitimately have both installed, and
    showing `[x] [x]` for an exclusive pair invites someone to believe it.
    Nightly wins, matching the channel tie-break."""
    console = Console.scripted([""])
    got, _asked = multi(
        console, "Terminals:", TERMINALS, ["wezterm-nightly", "wezterm-stable"], exclusive=GROUP
    )
    assert got == ["wezterm-nightly"]
    rendered = "\n".join(console.captured)
    assert "[x]  1)" in rendered and "[x]  2)" not in rendered


def test_a_multi_answer_applies_its_valid_tokens_and_warns_about_the_rest():
    """The one behaviour the two shells disagreed on. Someone typing `1 3 9` at a
    three-row list means the first two, and throwing that away is how people stop
    reading menus. The pwsh all-or-nothing was the bug and is not ported."""
    console = Console.scripted(["1 3 99", ""])
    got, _asked = multi(console, "T:", TERMINALS, [])
    assert got == ["wezterm-nightly", "ghostty"]
    assert any("enter a number 1-3" in line for line in console.captured)


def test_numbers_split_on_space_or_comma_and_never_fuse():
    """Deliberately NOT the choice prompt's strip-everything, which would fuse
    "1 2" into "12" and toggle row twelve."""
    for answer in ("1 2", "1,2", "1, 2"):
        console = Console.scripted([answer, ""])
        got, _asked = multi(console, "T:", TERMINALS, [])
        assert got == ["wezterm-nightly", "wezterm-stable"], answer


def test_the_tick_list_verbs():
    for answer, want in (("a", 3), ("all", 3), ("n", 0), ("none", 0)):
        console = Console.scripted([answer, ""])
        got, _asked = multi(console, "T:", TERMINALS, ["ghostty"])
        assert len(got) == want, answer
    console = Console.scripted(["s"])
    got, _asked = multi(console, "T:", TERMINALS, ["ghostty"])
    assert got == [], "skip clears and leaves"


def test_all_re_collapses_an_exclusive_group():
    console = Console.scripted(["a", ""])
    got, _asked = multi(console, "T:", TERMINALS, [], exclusive=GROUP)
    assert got == ["wezterm-nightly", "ghostty"], "'all' cannot select both channels"


def test_a_non_interactive_tick_list_keeps_the_pre_ticks():
    """Not none, and not all: the pre-ticks are the considered default."""
    got, asked = multi(Console(), "T:", TERMINALS, ["ghostty"])
    assert (got, asked) == (["ghostty"], False)


def test_an_empty_tick_list_renders_nothing():
    got, asked = multi(Console.scripted([]), "T:", [], [])
    assert (got, asked) == ([], False)


def test_the_collapse_guard_directly():
    keys = ["a", "b", "c"]
    ticked = [True, False, True]
    collapse_exclusive(ticked, keys, ("a", "b"), 2)  # c is not in the group
    assert ticked == [True, False, True], "an outsider wins nothing"
    ticked = [True, True, False]
    collapse_exclusive(ticked, keys, ("a", "b"), 1)
    assert ticked == [False, True, False]
    ticked = [True, True, False]
    collapse_exclusive(ticked, keys, ("a", "b"), -1)
    assert ticked == [True, False, False], "no winner keeps the first"


# ------------------------------------------------------------------- the flow


def test_just_the_prompt_stops_asking():
    """The honest answer to "can I only have the prompt" has to be yes, and the
    wizard has to stop after it."""
    answers = flow.collect(Console.scripted(["1", "", "2"]))
    assert answers.profile == "prompt"
    assert answers.apps == [] and answers.terminals == []
    assert answers.cc_tts == "off" and answers.memory_backend == "none"
    assert answers.caveman == "off" and answers.atuin == "off"
    assert answers.theme == "light", "the theme still applies - it is the prompt's palette"


def test_the_development_answer_picks_the_app_class(monkeypatch):
    monkeypatch.setenv("TS_PROFILE", "full")
    monkeypatch.setenv("TS_DEVELOPMENT", "no")
    monkeypatch.setenv("TS_APPS", "recommended")
    answers = flow.collect(Console())
    assert answers.app_class == "sysadmin"
    assert "claude" not in answers.apps and "fnm" not in answers.apps
    assert "btop" in answers.apps


def test_the_agent_questions_are_skipped_when_there_are_no_agents(monkeypatch):
    """Voice announces what an AGENT is doing; a memory backend stores what one
    learned. On a machine getting neither they are questions about something not
    being installed."""
    monkeypatch.setenv("TS_PROFILE", "shell")
    monkeypatch.setenv("TS_APPS", "none")
    answers = flow.collect(Console())
    assert answers.cc_tts == "off" and answers.memory_backend == "none"


def test_headless_never_asks_about_a_gui_it_does_not_have(monkeypatch):
    monkeypatch.setenv("TS_HEADLESS_RESOLVED", "1")
    monkeypatch.setenv("TS_APPS", "none")
    answers = flow.collect(Console())
    assert answers.profile == "shell", "the only profile whose questions still mean something"
    assert answers.wez_mux == "off" and answers.wez_restore == "off"
    assert answers.leader == "ctrl-space"


def test_the_tmux_prefix_is_never_reset_by_a_re_run(monkeypatch):
    """This used to be a bare `${TS_TMUX:-ctrl-b}`, so any machine whose prefix
    had been changed had it forced back by the next reconfigure."""
    monkeypatch.setattr(store, "chezmoi_data", lambda: {"tmuxPrefix": "ctrl-a"})
    store.clear_cache()
    monkeypatch.setenv("TS_PROFILE", "prompt")
    monkeypatch.setenv("TS_THEME", "dark")
    assert flow.collect(Console()).tmux == "ctrl-a"


def test_one_memory_question_not_two(monkeypatch):
    """Headroom and AgentMemory used to be asked separately, which made "both
    memory systems on" a single keystroke away -- and they do the same job."""
    monkeypatch.setenv("TS_PROFILE", "full")
    monkeypatch.setenv("TS_DEVELOPMENT", "yes")
    monkeypatch.setenv("TS_APPS", "none")
    monkeypatch.setenv("TS_CC_TTS", "off")
    for backend, want in (
        ("agentmemory", ("on", "on")),
        ("headroom", ("on", "off")),
        ("none", ("on", "off")),
    ):
        monkeypatch.setenv("TS_MEMORY_BACKEND", backend)
        answers = flow.collect(Console())
        assert (answers.headroom, answers.agentmemory) == want, backend


def test_asked_counts_only_what_actually_rendered(monkeypatch):
    """It is what decides whether the review appears: a fully env-driven run has
    nothing to review and must not block on a tty nobody is watching."""
    monkeypatch.setenv("TS_PROFILE", "prompt")
    monkeypatch.setenv("TS_THEME", "dark")
    monkeypatch.setenv("TS_STARSHIP_PRESET", "terminal-stack")
    assert flow.collect(Console()).asked == 0, "every answer came from the environment"

    # ...and with nothing pre-answered, the same three questions do tally.
    for name in ("TS_PROFILE", "TS_THEME", "TS_STARSHIP_PRESET"):
        monkeypatch.delenv(name, raising=False)
    assert flow.collect(Console.scripted(["1", "", "2"])).asked > 0


def test_the_review_lists_the_answers_the_prompt_scope_pinned():
    """A review that silently omits what it decided for you is how "I didn't
    choose that" happens."""
    console = Console.scripted([])
    flow.review(console, flow.Answers(profile="prompt", starship="tokyo-night"))
    text = "\n".join(console.captured)
    assert "Scope            prompt" in text
    assert "Everything else  left alone" in text


def test_quitting_the_review_returns_nothing(monkeypatch):
    console = Console.scripted(["q"])
    assert flow.confirm(console, flow.Answers(asked=3), assume_yes=False) is None
    assert any("nothing was installed" in line for line in console.captured)


def test_the_review_is_skipped_when_nothing_was_asked():
    console = Console.scripted([])
    answers = flow.Answers(asked=0)
    assert flow.confirm(console, answers, assume_yes=False) is answers
    assert any("nothing to review" in line for line in console.captured)


# ------------------------------------------------------------------ the emit


def _answers() -> flow.Answers:
    return flow.Answers(profile="full", apps=["eza", "fzf"], terminals=["wezterm-nightly"], asked=4)


def test_every_shell_variable_is_emitted_even_when_empty():
    """The callers read some of them unguarded, and `set -u` aborts on a missing
    one."""
    body = emit.to_sh(flow.Answers())
    for name, _field in emit.SHELL_NAMES:
        assert f"export {name}=" in body, name


def test_the_emitted_file_is_sourceable_under_strict_bash(tmp_path):
    from tests.shell_support import BASH

    if not BASH:
        pytest.skip("compatible bash is unavailable")
    path = tmp_path / "answers.sh"
    emit.write(path, emit.to_sh(_answers()))
    got = subprocess.run(
        [BASH, "-c", f'set -euo pipefail; . "{path}"; echo "$TS_WIZ_APPS|$TS_WIZ_PROFILE"'],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        start_new_session=True,
    )
    assert got.returncode == 0, got.stderr
    assert got.stdout.strip() == "eza fzf|full"


def test_the_emitted_variables_are_exported_not_merely_assigned():
    """`ts_agents_apply_wizard` reads them from the ENVIRONMENT of a child
    process; a bare assignment would silently turn the agent wiring off."""
    for line in emit.to_sh(_answers()).splitlines():
        if line.startswith("#"):
            continue
        assert line.startswith("export "), line


def test_a_value_that_cannot_be_emitted_safely_is_refused():
    """Better to fail than to write a file the caller will source."""
    with pytest.raises(ValueError):
        emit.to_sh(flow.Answers(leader="ctrl-—"))
    with pytest.raises(ValueError):
        emit.to_sh(flow.Answers(leader="a\nrm -rf /"))


def test_the_json_keys_are_the_ones_powershell_already_used():
    """So every `$w.X` call site in windows-bootstrap.ps1 is unchanged."""
    payload = json.loads(emit.to_json(_answers()))
    for key in ("Leader", "Theme", "Apps", "CcTts", "MemoryBackend", "StarshipPreset", "Asked"):
        assert key in payload, key
    assert isinstance(payload["Apps"], list), "an array on that side, a string in the shell one"


def test_the_emit_is_written_whole_then_renamed(tmp_path):
    """A crashed wizard cannot leave a partial file for the caller to source."""
    body = (ROOT / "tstack/wizard/emit.py").read_text(encoding="utf-8")
    assert ".replace(path)" in body
    path = tmp_path / "out.sh"
    emit.write(path, "export X=1\n")
    assert path.read_text(encoding="utf-8") == "export X=1\n"
    assert not list(tmp_path.glob("*.tmp")), "no leftover temp file"


# ------------------------------------------------------------ the invariants


def test_the_wizard_never_writes_anything():
    """It collects; the four bootstraps persist. That ordering is what keeps the
    documented invariant that answers are saved before anything that can fail."""
    for path in sorted((ROOT / "tstack/wizard").glob("*.py")):
        # CODE only. The module docstrings say "no store.set" in prose, and a
        # grep that cannot tell a rule from its statement is not a gate.
        code = [
            line
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        body = "\n".join(code)
        # The last needle is split on purpose: written whole it is matched by
        # test_every_subprocess_call_in_the_suite_has_a_timeout, which scans the
        # suite for that literal and would flag this string as a call.
        for writer in ("store.set(", "store.save(", "chezmoi_init(", "subprocess" + ".run("):
            assert writer not in body, f"{path.name} calls {writer}"


def test_the_shell_wizard_is_a_shim_now():
    """944 lines of bash and ~800 of PowerShell became one implementation. What
    is left is the hand-off, because the bootstraps are shell."""
    sh = (ROOT / "bootstrap/_wizard.sh").read_text(encoding="utf-8")
    assert len(sh.splitlines()) < 80, "the questions moved; only the hand-off stays"
    assert "main.py" in sh and "--emit sh" in sh
    assert "ts_prompt_choice" not in sh and "ts_prompt_multi" not in sh

    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    for gone in ("function Read-TsChoice", "function Read-TsMulti", "function Read-TsWizard"):
        assert gone not in ps, gone


def test_the_wizard_is_in_the_registry_on_both_platforms():
    from tstack import registry

    row = registry.get("wizard")
    assert row is not None
    assert row.posix == "python" and row.windows == "python"
