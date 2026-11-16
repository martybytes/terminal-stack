"""The arrow-key wizard: widgets, Back, Quit, the review's jump-to-step, the
desktop-apps step, and `--answers`.

Driven by Console.scripted_keys, which turns the arrow-key widgets on the same
way a real terminal does, so these exercise the real loops without a pty. The
numbered prompts stay covered by tests/test_wizard.py, unchanged.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.test_wizard import _clean_env  # noqa: E402,F401  (autouse fixture)
from tstack.wizard import answers as answers_file  # noqa: E402
from tstack.wizard import emit, flow  # noqa: E402
from tstack.wizard import prompts as p  # noqa: E402
from tstack.wizard.console import DOWN, ENTER, LEFT, SPACE, UP, Console  # noqa: E402

THEMES = [p.Option("dark", "dark"), p.Option("light", "light"), p.Option("follow", "follow")]

# Everything but the profile and theme questions, pinned, so a flow test only
# has to script the two it is about.
PINNED = {
    "TS_STARSHIP_PRESET": "terminal-stack",
    "TS_DEVELOPMENT": "yes",
    "TS_LEADER": "ctrl-backslash",
    "TS_WEZ_MUX": "off",
    "TS_WEZ_RESTORE": "off",
    "TS_ATUIN": "on",
    "TS_APPS": "eza,bat",
    "TS_HERDR": "off",
    "TS_CC_TTS": "off",
    "TS_MEMORY_BACKEND": "none",
    "TS_HEADROOM": "off",
    "TS_CAVEMAN": "off",
    "TS_SERVICES": "off",
}


@pytest.fixture
def pinned(monkeypatch):
    for name, value in PINNED.items():
        monkeypatch.setenv(name, value)


def _frames(console: Console, title: str) -> int:
    """How many frames drew a question with this title. One frame per key
    press: a question answered with one Enter draws once."""
    return sum(1 for line in console.captured if line == p.bold(title))


# ------------------------------------------------------------------ widgets


def test_select_moves_with_the_arrows_and_enter_chooses():
    console = Console.scripted_keys([DOWN, ENTER])
    assert p.select(console, "Theme:", THEMES, "dark") == ("light", True)


def test_select_enter_without_moving_keeps_an_unlisted_default_verbatim():
    """Same contract as the numbered prompt: a saved Starship preset this
    machine no longer ships is offered back, never rewritten to row one."""
    console = Console.scripted_keys([ENTER])
    assert p.select(console, "Prompt:", THEMES, "gone-preset") == ("gone-preset", True)


def test_select_back_and_quit():
    assert p.select(Console.scripted_keys([LEFT]), "T", THEMES, "dark")[0] == p.BACK
    assert p.select(Console.scripted_keys(["b"]), "T", THEMES, "dark")[0] == p.BACK
    assert p.select(Console.scripted_keys(["q", "y"]), "T", THEMES, "dark")[0] == p.QUIT
    # A quit that is not confirmed carries on where it was.
    assert p.select(Console.scripted_keys(["q", "n", ENTER]), "T", THEMES, "dark")[0] == "dark"


def test_select_shows_the_highlighted_rows_preview():
    options = [p.Option("a", "a", preview="PREVIEW-A"), p.Option("b", "b", preview="PREVIEW-B")]
    console = Console.scripted_keys([DOWN, ENTER])
    p.select(console, "Which prompt?", options, "a")
    joined = "\n".join(console.captured)
    assert "PREVIEW-A" in joined and "PREVIEW-B" in joined


def test_checklist_space_ticks_and_the_exclusive_pair_collapses():
    options = [
        p.Option("wezterm-nightly"),
        p.Option("wezterm-stable"),
        p.Option("ghostty"),
    ]
    console = Console.scripted_keys([DOWN, SPACE, DOWN, SPACE, ENTER])
    got, asked = p.checklist(
        console, "T", options, ["wezterm-nightly"], exclusive=("wezterm-nightly", "wezterm-stable")
    )
    assert asked
    assert got == ["wezterm-stable", "ghostty"], "ticking stable unticked nightly; ghostty kept"


def test_checklist_all_none_and_presets():
    options = [p.Option(k) for k in ("a", "b", "c")]
    assert p.checklist(Console.scripted_keys(["a", ENTER]), "T", options, [])[0] == ["a", "b", "c"]
    assert p.checklist(Console.scripted_keys(["n", ENTER]), "T", options, ["a"])[0] == []
    presets = {"r": ("recommended", ["b"])}
    got = p.checklist(Console.scripted_keys(["a", "r", ENTER]), "T", options, [], presets=presets)
    assert got[0] == ["b"]
    assert p.checklist(Console.scripted_keys([LEFT]), "T", options, [])[0] == [p.BACK]


def test_checklist_draws_group_headings():
    options = [p.Option("x", group="shell essentials"), p.Option("y", group="git tooling")]
    console = Console.scripted_keys([ENTER])
    p.checklist(console, "Tools", options, [])
    joined = "\n".join(console.captured)
    assert "shell essentials" in joined and "git tooling" in joined


# --------------------------------------------------------------------- flow


def test_back_reshapes_the_flow_after_changing_an_earlier_answer(pinned):
    """Back re-runs the flow on the answers given, so gates re-evaluate: going
    back from the `prompt` scope and choosing `full` must reach the full flow."""
    # profile: UP UP -> "prompt"; theme: LEFT (back); profile: DOWN DOWN -> full;
    # theme: Enter; review: Enter (Proceed).
    console = Console.scripted_keys([UP, UP, ENTER, LEFT, DOWN, DOWN, ENTER, ENTER, ENTER])
    answers = flow.run(console)
    assert answers is not None
    assert answers.profile == "full"
    assert answers.apps == ["eza", "bat"], "the full flow ran, so the pinned apps applied"
    # Drawn three times (UP, UP, Enter), then three more after the Back.
    assert _frames(console, "How much of this do you want?") == 6


def test_back_from_the_first_question_stays_there(pinned):
    console = Console.scripted_keys([LEFT, ENTER, ENTER, ENTER])
    answers = flow.run(console)
    assert answers is not None and answers.profile == "full"


def test_the_review_can_change_one_answer_without_re_asking_the_rest(pinned):
    # profile Enter (full); theme DOWN Enter (light); review: DOWN Enter
    # (Change an answer); pick the theme step: DOWN Enter; theme: UP Enter
    # (dark); review: Enter (Proceed).
    keys = [ENTER, DOWN, ENTER, DOWN, ENTER, DOWN, ENTER, UP, ENTER, ENTER]
    console = Console.scripted_keys(keys)
    answers = flow.run(console)
    assert answers is not None
    assert answers.theme == "dark" and answers.profile == "full"
    assert _frames(console, "How much of this do you want?") == 1, "profile not re-asked"
    assert _frames(console, "Change which answer?") == 2  # DOWN, Enter


def test_quitting_mid_flow_returns_nothing(pinned):
    console = Console.scripted_keys(["q", "y"])
    assert flow.run(console) is None
    assert any("nothing was installed" in line for line in console.captured)


def test_quitting_at_the_review_returns_nothing(pinned):
    # profile, theme, then review: DOWN DOWN (Quit) Enter.
    console = Console.scripted_keys([ENTER, ENTER, DOWN, DOWN, ENTER])
    assert flow.run(console) is None


def test_plain_prompts_go_back_with_a_less_than(pinned):
    """The numbered fallback has Back too: `<` at any prompt."""
    console = Console.scripted(["1", "<", "3", "", ""])
    answers = flow.run(console)
    assert answers is not None and answers.profile == "full"


# ------------------------------------------------------------------- apps


@pytest.fixture
def linux_desktop(monkeypatch):
    monkeypatch.setattr(flow.plat, "kind", lambda: flow.plat.LINUX)


def test_apps_are_three_steps_and_the_desktop_apps_are_opt_in(linux_desktop):
    # Tools: none. Agents: keep the pre-ticked set. Desktop: tick the first two.
    keys = ["n", ENTER, ENTER, SPACE, DOWN, SPACE, ENTER]
    console = Console.scripted_keys(keys)
    answers = flow.run(console, only_apps=True)
    assert answers is not None
    from tstack import apps as catalog

    agents = [a.id for a in catalog.in_group("ai")]
    assert set(agents) <= set(answers.apps), "a development machine pre-ticks every agent CLI"
    assert "herdr-app" in answers.apps and "orca" in answers.apps
    assert "t3code" not in answers.apps
    assert not [a for a in answers.apps if a not in [*agents, "herdr-app", "orca"]]
    joined = "\n".join(console.captured)
    assert "Command-line tools" in joined
    assert "AI coding agents (command-line)" in joined
    assert "Desktop agent apps" in joined


def test_desktop_apps_are_never_preticked_on_a_fresh_machine(linux_desktop):
    console = Console.scripted_keys([ENTER, ENTER, ENTER])
    answers = flow.run(console, only_apps=True)
    assert answers is not None
    assert not {"herdr-app", "orca", "t3code"} & set(answers.apps)


def test_a_headless_machine_is_never_offered_the_desktop_apps(linux_desktop, monkeypatch):
    monkeypatch.setenv("TS_HEADLESS_RESOLVED", "1")
    console = Console.scripted_keys(["a", ENTER, ENTER])
    answers = flow.run(console, only_apps=True)
    assert answers is not None
    assert "Desktop agent apps" not in "\n".join(console.captured)
    assert not {"herdr-app", "orca", "t3code"} & set(answers.apps)


def test_back_from_the_agents_step_returns_to_the_tools_list(linux_desktop):
    # Tools: none; agents: Back; tools again (remembered: none) -> "a" all;
    # agents Enter; desktop Enter.
    keys = ["n", ENTER, LEFT, "a", ENTER, ENTER, ENTER]
    console = Console.scripted_keys(keys)
    answers = flow.run(console, only_apps=True)
    assert answers is not None
    assert "eza" in answers.apps
    assert _frames(console, "Command-line tools") >= 2


# ----------------------------------------------------------------- --answers


def test_answers_round_trip_through_emit_json(pinned, monkeypatch):
    """A recorded run replays to the same answers: what --emit json writes,
    --answers reads."""
    first = flow.collect(Console())
    payload = json.loads(emit.to_json(first))
    for name in list(os.environ):
        if name.startswith("TS_"):
            monkeypatch.delenv(name, raising=False)
    for name, value in answers_file.to_env(payload).items():
        monkeypatch.setenv(name, value)
    second = flow.collect(Console())
    assert emit.to_json(second) == emit.to_json(first)


def test_an_empty_list_is_an_answer_not_an_absence():
    env = answers_file.to_env({"Apps": [], "Terminals": []})
    assert env == {"TS_APPS": "none", "TS_TERMINALS": "none"}


@pytest.mark.parametrize(
    ("payload", "names"),
    [
        ({"Thme": "dark"}, "Thme"),
        ({"Theme": "purple"}, "Theme"),
        ({"Apps": "eza"}, "Apps"),
        ({"Atuin": True}, "Atuin"),
        ([], "one JSON object"),
    ],
)
def test_a_bad_answers_file_is_refused_naming_the_key(payload, names):
    with pytest.raises(answers_file.AnswersError, match=names):
        answers_file.to_env(payload)


def test_the_command_refuses_a_bad_answers_file(tmp_path, capsys):
    from tstack.commands import wizard as cmd

    bad = tmp_path / "a.json"
    bad.write_text('{"Theme": "purple"}')
    assert cmd.main(["--answers", str(bad)]) == 2
    assert "Theme" in capsys.readouterr().err


def test_the_command_skips_what_the_file_answers(tmp_path, monkeypatch):
    from tstack.commands import wizard as cmd

    for name, value in PINNED.items():
        monkeypatch.setenv(name, value)
    answers_json = tmp_path / "in.json"
    answers_json.write_text(json.dumps({"Profile": "shell", "Theme": "light"}))
    out = tmp_path / "out.json"
    monkeypatch.setenv("TS_ASSUME_YES", "1")
    assert cmd.main(["--answers", str(answers_json), "--emit", "json", "--out", str(out)]) == 0
    got = json.loads(out.read_text())
    assert got["Profile"] == "shell" and got["Theme"] == "light"


# --------------------------------------------------------------- terminal


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX termios")
def test_the_terminal_is_restored_even_when_a_read_fails(monkeypatch):
    import pty
    import termios

    from tstack.wizard import console as console_mod

    master, slave = pty.openpty()
    try:
        before = termios.tcgetattr(slave)

        def boom(fd, n):
            raise RuntimeError("terminal went away")

        monkeypatch.setattr(console_mod.os, "read", boom)
        with pytest.raises(RuntimeError):
            console_mod._posix_key(slave)
        after = termios.tcgetattr(slave)
        # PENDIN is the kernel's own bookkeeping, set when ICANON flips.
        pendin = getattr(termios, "PENDIN", 0)
        after[3] &= ~pendin
        before[3] &= ~pendin
        assert after == before
    finally:
        os.close(master)
        os.close(slave)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX termios")
def test_arrow_keys_decode_from_a_real_pty():
    import pty
    import termios
    import tty

    from tstack.wizard import console as console_mod

    master, slave = pty.openpty()
    try:
        # Non-canonical BEFORE the bytes arrive. Written into a canonical pty,
        # a partial line with no newline is never handed to read() on macOS
        # once the mode flips, and the read blocks until CI cancels the job.
        tty.setcbreak(slave, termios.TCSANOW)
        for raw, want in ((b"\x1b[A", UP), (b"\x1b[B", DOWN), (b" ", SPACE), (b"\r", ENTER)):
            os.write(master, raw)
            assert console_mod._posix_key(slave) == want
    finally:
        os.close(master)
        os.close(slave)
