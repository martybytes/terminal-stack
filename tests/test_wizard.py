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


def test_just_the_prompt_stops_asking(monkeypatch):
    """The honest answer to "can I only have the prompt" has to be yes, and the
    wizard has to stop after it.

    The prompt question is pinned: it only RENDERS where starship is installed,
    so a scripted answer list that assumes it does passes on a developer's Mac
    and consumes the wrong answers in a container.
    """
    monkeypatch.setenv("TS_STARSHIP_PRESET", "terminal-stack")
    answers = flow.collect(Console.scripted(["1", "2"]))
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

    # ...and with the profile unanswered, it does tally. The prompt question is
    # left pinned: whether it renders depends on starship being installed.
    monkeypatch.delenv("TS_PROFILE", raising=False)
    monkeypatch.delenv("TS_THEME", raising=False)
    assert flow.collect(Console.scripted(["1", "2"])).asked > 0


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


# ------------------------------------------------------- the app picker paths


def test_the_app_picker_offers_keeping_what_is_already_chosen(monkeypatch):
    """Defaulting to `recommended` on a re-run shrank a larger saved list,
    silently, on Enter. An existing selection has to be offered AND be the
    default."""
    monkeypatch.setattr(store, "chezmoi_data", lambda: {"apps": "eza fzf bat"})
    store.clear_cache()
    monkeypatch.setenv("TS_PROFILE", "shell")
    monkeypatch.setenv("TS_STARSHIP_PRESET", "terminal-stack")
    monkeypatch.setenv("TS_THEME", "dark")
    monkeypatch.setenv("TS_LEADER", "ctrl-space")
    monkeypatch.setenv("TS_ATUIN", "off")
    monkeypatch.setenv("TS_WEZ_MUX", "off")
    monkeypatch.setenv("TS_WEZ_RESTORE", "off")
    console = Console.scripted([""])  # Enter takes the default: keep
    answers = flow.collect(console)
    assert answers.apps == ["eza", "fzf", "bat"]
    assert any("keep this machine's current selection" in line for line in console.captured)


def test_the_app_picker_whole_set_answers(monkeypatch):
    from tstack import apps as catalog

    monkeypatch.setenv("TS_PROFILE", "shell")
    ask = flow.Asker(Console.scripted(["all"]))
    everything = flow._apps(ask, catalog.DEVELOPER)
    assert len(everything) > 40

    ask = flow.Asker(Console.scripted(["none"]))
    assert flow._apps(ask, catalog.DEVELOPER) == []

    ask = flow.Asker(Console.scripted(["recommended"]))
    assert set(flow._apps(ask, catalog.SYSADMIN)) == {
        a
        for a in catalog.sysadmin()
        if catalog.installable(a, __import__("tstack.platform", fromlist=["kind"]).kind())
    }


def test_choosing_groups_selects_their_members():
    from tstack import apps as catalog

    # "groups", then tick only `search`, then Enter.
    groups = [g for g in catalog.groups() if catalog.in_group(g)]
    index = groups.index("search") + 1
    ask = flow.Asker(Console.scripted(["groups", "n", str(index), ""]))
    chosen = flow._apps(ask, catalog.DEVELOPER)
    assert set(chosen) == {a.id for a in catalog.in_group("search")}


def test_choosing_individual_tools_walks_group_by_group():
    """Thirty consecutive Y/n prompts is a lot to sit through; the walk is a
    tick-list per group instead."""
    from tstack import apps as catalog

    # "customize", then clear and accept each group in turn.
    script = ["customize"] + ["n", ""] * (len(catalog.groups()) + 2)
    ask = flow.Asker(Console.scripted(script))
    assert flow._apps(ask, catalog.DEVELOPER) == []


def test_an_empty_catalog_says_so_rather_than_silently_offering_nothing(monkeypatch):
    """ "recommended installed nothing" is the silently-dropped-tool failure this
    repo keeps being bitten by."""
    from tstack import apps as catalog

    monkeypatch.setattr(catalog, "catalog", lambda: ())
    console = Console.scripted([])
    assert flow._apps(flow.Asker(console), catalog.DEVELOPER) == []
    assert any("catalog is empty" in line for line in console.captured)


# --------------------------------------------------------------- voice, agents


def test_the_voice_follow_ups_only_appear_once_voice_is_on(monkeypatch):
    monkeypatch.setenv("TS_PROFILE", "full")
    monkeypatch.setenv("TS_DEVELOPMENT", "no")
    monkeypatch.setenv("TS_APPS", "none")
    monkeypatch.setenv("TS_CC_TTS", "off")
    assert flow.collect(Console()).cc_tts_message == "template"

    monkeypatch.setenv("TS_CC_TTS", "on")
    monkeypatch.setenv("TS_CC_TTS_MESSAGE", "hook")
    answers = flow.collect(Console())
    assert answers.cc_tts == "on" and answers.cc_tts_message == "hook"


def test_the_cursor_mode_is_only_asked_when_headroom_is_on(monkeypatch):
    monkeypatch.setenv("TS_PROFILE", "full")
    monkeypatch.setenv("TS_DEVELOPMENT", "yes")
    monkeypatch.setenv("TS_APPS", "none")
    monkeypatch.setenv("TS_CC_TTS", "off")
    monkeypatch.setenv("TS_MEMORY_BACKEND", "off")
    monkeypatch.setenv("TS_CAVEMAN", "off")
    answers = flow.collect(Console())
    assert answers.headroom == "off"
    assert answers.headroom_cursor == "mcp", "the default, unasked"


def test_the_full_review_lists_every_answer():
    console = Console.scripted([])
    flow.review(console, flow.Answers(profile="full", apps=["eza"], terminals=["ghostty"]))
    text = "\n".join(console.captured)
    for label in (
        "For development",
        "Leader",
        "Theme",
        "Terminals",
        "WezTerm mux",
        "Session restore",
        "atuin",
        "tmux prefix",
        "Apps",
        "Agent voice",
        "Headroom",
        "Caveman",
        "Memory backend",
    ):
        assert label in text, label


def test_editing_at_the_review_asks_again():
    """`e` must re-run the questions, not fall through to the install. In the
    PowerShell version a `switch` made `continue` bind to the switch rather than
    the loop, which did exactly that."""
    console = Console.scripted(["e", "1", "2", ""])
    answers = flow.confirm(console, flow.Answers(asked=1, profile="full"), assume_yes=False)
    assert answers is not None
    assert answers.profile == "prompt", "the second pass replaced the first"


def test_an_unrecognised_review_answer_re_asks_rather_than_proceeding():
    console = Console.scripted(["maybe", ""])
    answers = flow.confirm(console, flow.Answers(asked=1), assume_yes=False)
    assert answers is not None
    assert any("is not one of the choices" in line for line in console.captured)


# ------------------------------------------------------------------- headless


def test_headless_detection(monkeypatch):
    from tstack import platform as tsplat

    monkeypatch.delenv("TS_HEADLESS_RESOLVED", raising=False)
    for kind in (tsplat.WSL, tsplat.WINDOWS, tsplat.MACOS):
        monkeypatch.setattr(tsplat, "kind", lambda k=kind: k)
        assert not flow.headless(), f"{kind} drives a GUI"

    monkeypatch.setattr(tsplat, "kind", lambda: tsplat.LINUX)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setenv("SSH_CONNECTION", "1.2.3.4 22 5.6.7.8 22")
    assert flow.headless(), "an SSH session has no local display"

    monkeypatch.setenv("DISPLAY", ":0")
    assert not flow.headless(), "an explicit display wins"


def test_an_explicitly_resolved_headless_answer_wins(monkeypatch):
    """The caller may have ASKED. Recomputing here made an explicit override
    silently ineffective, which is the kind that looks like it worked."""
    monkeypatch.setenv("TS_HEADLESS_RESOLVED", "1")
    assert flow.headless()
    monkeypatch.setenv("TS_HEADLESS_RESOLVED", "0")
    assert not flow.headless()


def test_the_console_survives_a_terminal_it_cannot_open(monkeypatch):
    """A container, a CI runner and `curl | bash` all land here."""
    import builtins

    real = builtins.open

    def refuse(path, *a, **k):
        if str(path) in ("/dev/tty", "CONIN$", "CONOUT$"):
            raise OSError("no controlling terminal")
        return real(path, *a, **k)

    monkeypatch.setattr(builtins, "open", refuse)
    console = Console.open()
    assert not console.interactive
    console.close()


def test_a_console_write_that_fails_does_not_take_the_wizard_down(tmp_path):
    """A terminal can go away mid-run. Losing the menu is survivable; a
    traceback out of an installer is not."""
    handle = (tmp_path / "tty").open("w")
    console = Console(reader=None, writer=handle)
    handle.close()
    # A CLOSED handle raises ValueError, not OSError -- which is why suppressing
    # only OSError was not enough and this test exists.
    console.say("into the void")
    assert console.ask("q: ") is None
    console.close()


# ------------------------------------------------------------- the entry point


def _cmd(argv, monkeypatch, answers=None, quit_it=False):
    """Run the command with the questions stubbed out."""
    from tstack.commands import wizard as cmd

    monkeypatch.setattr(
        cmd.flow, "collect", lambda console, ask_terminals=False: answers or flow.Answers()
    )
    monkeypatch.setattr(cmd.flow, "collect_apps", lambda console: answers or flow.Answers())
    monkeypatch.setattr(cmd.flow, "review", lambda console, a: None)
    monkeypatch.setattr(cmd.flow, "confirm", lambda console, a, assume_yes: None if quit_it else a)
    return cmd.main(argv)


def test_the_command_rejects_bad_arguments(monkeypatch, capsys):
    assert _cmd(["--emit"], monkeypatch) == 2
    assert "takes sh or json" in capsys.readouterr().err
    assert _cmd(["--emit", "toml"], monkeypatch) == 2
    assert _cmd(["--out"], monkeypatch) == 2
    assert "needs a path" in capsys.readouterr().err
    assert _cmd(["--only", "leader"], monkeypatch) == 2
    assert _cmd(["--nonsense"], monkeypatch) == 2
    assert "unknown option" in capsys.readouterr().err


def test_emitting_without_a_destination_is_a_usage_error(monkeypatch, capsys):
    """Silently discarding the answers would look like it worked."""
    assert _cmd(["--emit", "sh"], monkeypatch) == 2
    assert "needs --out" in capsys.readouterr().err


def test_quitting_at_the_review_exits_three(monkeypatch, tmp_path):
    """Each caller already handles 3 as cancelled, and it has to be
    distinguishable from a failure."""
    out = tmp_path / "a.sh"
    assert _cmd(["--emit", "sh", "--out", str(out)], monkeypatch, quit_it=True) == 3
    assert not out.exists(), "a quit writes nothing"


def test_help_and_a_plain_run(monkeypatch, capsys):
    from tstack.commands import wizard as cmd

    assert cmd.main(["-h"]) == 0
    assert "tstack wizard -" in capsys.readouterr().out
    # No --emit is a dry run: it collects, reviews and writes nothing.
    assert _cmd([], monkeypatch) == 0


def test_only_apps_skips_the_review_entirely(monkeypatch, tmp_path):
    """The caller asked for the picker, not the questionnaire."""
    from tstack.commands import wizard as cmd

    reviewed: list[int] = []
    monkeypatch.setattr(cmd.flow, "collect_apps", lambda console: flow.Answers(apps=["eza"]))
    monkeypatch.setattr(cmd.flow, "confirm", lambda *a, **k: reviewed.append(1))
    out = tmp_path / "a.sh"
    assert cmd.main(["--only", "apps", "--emit", "sh", "--out", str(out)]) == 0
    assert reviewed == [], "no review for a single question"
    assert "export TS_WIZ_APPS=eza\n" in out.read_text(encoding="utf-8")


def test_an_unwritable_destination_is_reported_not_swallowed(monkeypatch, tmp_path, capsys):
    assert _cmd(["--emit", "sh", "--out", str(tmp_path / "no" / "such" / "a.sh")], monkeypatch) == 1
    assert "could not write" in capsys.readouterr().err


def test_no_review_skips_the_confirm_loop(monkeypatch, tmp_path):
    from tstack.commands import wizard as cmd

    confirmed: list[int] = []
    monkeypatch.setattr(cmd.flow, "collect", lambda c, ask_terminals=False: flow.Answers())
    monkeypatch.setattr(cmd.flow, "review", lambda c, a: None)
    monkeypatch.setattr(cmd.flow, "confirm", lambda *a, **k: confirmed.append(1))
    assert cmd.main(["--no-review"]) == 0
    assert confirmed == []


def test_every_variable_the_bootstraps_read_is_emitted():
    """The contract between the wizard and its four callers, checked rather than
    remembered.

    The callers read several of these UNGUARDED, and every bootstrap runs
    `set -euo pipefail` -- so a name they read and the wizard stopped emitting is
    not a wrong answer, it is an aborted install. This is the whole reason
    `to_sh` emits all of them unconditionally, empty where there is no value.
    """
    import re

    read: set[str] = set()
    for path in sorted((ROOT / "bootstrap").glob("*.sh")):
        read |= set(re.findall(r"TS_WIZ_[A-Z_]+", path.read_text(encoding="utf-8")))
    emitted = {name for name, _field in emit.SHELL_NAMES}
    # Set by the shim to ask FOR the terminal question; never an answer.
    read.discard("TS_WIZ_ASK_TERMINALS")

    missing = sorted(read - emitted)
    assert not missing, f"read by a bootstrap but never emitted: {missing}"


def test_the_powershell_bootstrap_reads_only_keys_the_json_carries():
    """Same contract on the other side. A `$w.X` that is not in the payload is
    `$null`, which PowerShell will happily pass to a setter."""
    import re

    body = (ROOT / "bootstrap/windows-bootstrap.ps1").read_text(encoding="utf-8")
    used = set(re.findall(r"\$w(?:izard)?\.([A-Za-z]+)", body))
    carried = {name for name, _field in emit.JSON_NAMES}
    missing = sorted(used - carried)
    assert not missing, f"windows-bootstrap.ps1 reads {missing}, which the JSON does not carry"


# ------------------------------------------------------------- probe, do not guess


def test_the_voice_question_defaults_from_what_can_actually_speak(monkeypatch):
    """Offering voice where nothing can speak promises silence; defaulting it
    off on a Mac ignores that `say` is a floor which cannot be missing. The bash
    wizard probed and printed a report, and dropping that in the port was a
    regression, not a simplification.
    """
    from tstack.wizard import probes

    monkeypatch.setenv("TS_PROFILE", "full")
    monkeypatch.setenv("TS_DEVELOPMENT", "yes")
    monkeypatch.setenv("TS_APPS", "none")
    monkeypatch.setenv("TS_MEMORY_BACKEND", "none")
    monkeypatch.setenv("TS_CAVEMAN", "off")
    monkeypatch.setenv("TS_HEADROOM_CURSOR", "mcp")

    monkeypatch.setattr(probes, "voice", lambda: ("off", ["    kokoro: not reachable"]))
    console = Console.scripted([""])
    assert flow.collect(console).cc_tts == "off"
    assert any("not reachable" in line for line in console.captured), "the report is shown"

    monkeypatch.setattr(probes, "voice", lambda: ("on", ["    say: always available on macOS"]))
    console = Console.scripted([""])
    assert flow.collect(console).cc_tts == "on", "Enter takes the PROBED default"


def test_the_memory_question_reports_what_is_running(monkeypatch):
    """A blind on/off question happily wired a machine to a service that was not
    running, and the failure showed up much later as an agent that silently
    retrieved nothing."""
    from tstack.wizard import probes

    monkeypatch.setenv("TS_PROFILE", "full")
    monkeypatch.setenv("TS_DEVELOPMENT", "yes")
    monkeypatch.setenv("TS_APPS", "none")
    monkeypatch.setenv("TS_CC_TTS", "off")
    monkeypatch.setenv("TS_CAVEMAN", "off")
    monkeypatch.setenv("TS_HEADROOM_CURSOR", "mcp")
    monkeypatch.setattr(probes, "agentmemory", lambda: (False, "  AgentMemory: not reachable"))
    monkeypatch.setattr(probes, "headroom", lambda: (True, "  Headroom: ready"))

    console = Console.scripted([""])
    flow.collect(console)
    rendered = "\n".join(console.captured)
    assert "AgentMemory: not reachable" in rendered
    assert "Headroom: ready" in rendered


def test_the_pre_merge_booleans_are_honoured_not_ignored(monkeypatch):
    """An unattended install written before the two toggles became one question
    only knew TS_AGENTMEMORY/TS_HEADROOM. Ignoring them would land it on a
    combination this menu will not offer."""
    monkeypatch.setenv("TS_PROFILE", "full")
    monkeypatch.setenv("TS_DEVELOPMENT", "yes")
    monkeypatch.setenv("TS_APPS", "none")
    monkeypatch.setenv("TS_CC_TTS", "off")
    monkeypatch.setenv("TS_CAVEMAN", "off")
    monkeypatch.setenv("TS_HEADROOM_CURSOR", "mcp")

    monkeypatch.setenv("TS_AGENTMEMORY", "on")
    assert flow.collect(Console()).memory_backend == "agentmemory"

    monkeypatch.setenv("TS_AGENTMEMORY", "off")
    assert flow.collect(Console()).memory_backend == "none"


def test_answering_is_the_test_never_a_2xx():
    """AgentMemory returns 404 on `/` and 401 on its health endpoint; both prove
    a server is listening. `curl -fsS` treats either as failure, which is why it
    once reported the service down while it was up and serving."""
    body = (ROOT / "tstack/wizard/probes.py").read_text(encoding="utf-8")
    assert "except urllib.error.HTTPError:\n        return True" in body
    # ...and the STRICT form is used only where the endpoint is a real readiness
    # check, which is Headroom's /readyz.
    strict = body[body.index("def headroom(") :]
    assert "/readyz" in strict and "200 <= response.status" in strict


def test_a_probe_that_cannot_reach_anything_is_not_an_error(monkeypatch):
    from tstack.wizard import probes

    def refuse(*a, **k):
        raise probes.urllib.error.URLError("refused")

    monkeypatch.setattr(probes.urllib.request, "urlopen", refuse)
    assert probes.agentmemory()[0] is False
    assert probes.headroom()[0] is False
    best, lines = probes.voice()
    assert best in ("on", "off") and lines
