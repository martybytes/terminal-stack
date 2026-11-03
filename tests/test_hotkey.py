"""A leader held by another program's global hotkey must be reported, never assumed free.

Found 2026-11-01: `ctrl-backslash` saved and rendered correctly, `wezterm
show-keys` listed it, and pressing it did nothing -- a tray app had registered
Ctrl+\\ with RegisterHotKey, so WezTerm only ever received the key-UP.
"""

from __future__ import annotations

import sys

import pytest

from tstack import hotkey
from tstack.checks import FAIL, OK
from tstack.commands import config, doctor, wizard
from tstack.wizard import flow
from tstack.wizard.console import Console

# Captured at import, before conftest's autouse fixture replaces it per test.
REAL_HELD_ELSEWHERE = hotkey.held_elsewhere


@pytest.mark.parametrize(
    ("chord", "parsed"),
    [
        ("ctrl-backslash", (hotkey.MOD_CONTROL, 0xDC)),
        ("ctrl-space", (hotkey.MOD_CONTROL, 0x20)),
        ("alt-space", (hotkey.MOD_ALT, 0x20)),
        ("ctrl-a", (hotkey.MOD_CONTROL, ord("A"))),
        ("ctrl-shift-backslash", (hotkey.MOD_CONTROL | hotkey.MOD_SHIFT, 0xDC)),
        ("alt-f4", (hotkey.MOD_ALT, 0x73)),
    ],
)
def test_the_wizards_chords_map_to_windows_key_codes(chord, parsed):
    assert hotkey.parse(chord) == parsed


@pytest.mark.parametrize("chord", ["", "backslash", "hyper-x", "ctrl-nosuchkey"])
def test_an_unmappable_chord_is_none_not_a_guess(chord):
    assert hotkey.parse(chord) is None


def test_cannot_tell_is_none_off_windows(monkeypatch):
    """None, never False: "free" printed off Windows would be a lie."""
    monkeypatch.setattr(hotkey, "held_elsewhere", REAL_HELD_ELSEWHERE)  # undo conftest's stub
    monkeypatch.setattr(sys, "platform", "linux")
    assert hotkey.held_elsewhere("ctrl-backslash") is None


@pytest.mark.skipif(sys.platform != "win32", reason="RegisterHotKey is Windows-only")
def test_the_real_probe_answers_on_windows(monkeypatch):
    """Not which answer -- that is this PC's tray -- only that it gives one."""
    monkeypatch.setattr(hotkey, "held_elsewhere", REAL_HELD_ELSEWHERE)
    assert hotkey.held_elsewhere("ctrl-shift-alt-f13") in (True, False)


def test_the_label_is_what_the_user_presses():
    assert hotkey.label("ctrl-backslash") == "Ctrl+\\"
    assert hotkey.label("alt-space") == "Alt+Space"
    assert hotkey.label("ctrl-a") == "Ctrl+A"


def test_the_advice_names_both_ways_out():
    text = "\n".join(hotkey.advice("ctrl-backslash"))
    assert "Ctrl+\\" in text
    assert "tstack config leader" in text
    assert "tstack doctor" in text
    assert "\n" not in hotkey.one_line_fix(), "doctor renders hints on one line"


def test_doctor_fails_a_held_leader_and_passes_a_free_one(monkeypatch):
    monkeypatch.setattr(doctor.store, "get", lambda key, default="": "ctrl-backslash")

    monkeypatch.setattr(doctor.hotkey, "held_elsewhere", lambda chord: True)
    report = doctor.Report()
    doctor.check_leader_hotkey(report)
    assert [r.status for r in report.results] == [FAIL]
    assert "tstack config leader" in report.results[0].hint

    monkeypatch.setattr(doctor.hotkey, "held_elsewhere", lambda chord: False)
    report = doctor.Report()
    doctor.check_leader_hotkey(report)
    assert [r.status for r in report.results] == [OK]

    # Cannot tell (not Windows): no line at all, rather than a false "ok".
    monkeypatch.setattr(doctor.hotkey, "held_elsewhere", lambda chord: None)
    report = doctor.Report()
    doctor.check_leader_hotkey(report)
    assert report.results == []


def test_the_wizard_marks_a_held_chord_and_asks_before_keeping_it(monkeypatch):
    monkeypatch.setattr(hotkey, "held_elsewhere", lambda chord: chord == "ctrl-backslash")
    monkeypatch.setattr(flow, "_saved", lambda key, default: default)
    # Enter takes Ctrl+\ (the default); refuse to keep it; then pick 3 (Ctrl+A).
    console = Console.scripted(["", "n", "3"])
    got = flow._leader(flow.Asker(console), console)
    assert got == "ctrl-a"
    said = "\n".join(console.captured)
    assert "TAKEN on this PC by another program" in said
    assert "already taken by another program" in said
    assert "leader then z" in said, "the question explains how the leader is used"


def test_the_wizard_keeps_a_held_chord_when_told_to(monkeypatch):
    monkeypatch.setattr(hotkey, "held_elsewhere", lambda chord: True)
    monkeypatch.setattr(flow, "_saved", lambda key, default: default)
    console = Console.scripted(["", "y"])
    assert flow._leader(flow.Asker(console), console) == "ctrl-backslash"


def test_a_bare_wizard_says_it_is_a_preview_and_how_to_apply(monkeypatch):
    """It used to end on "[P]roceed" and return to the shell, having saved nothing."""
    console = Console.scripted([])
    monkeypatch.setattr(wizard.Console, "open", classmethod(lambda cls, tty="": console))
    monkeypatch.setattr(
        wizard.flow, "collect", lambda c, ask_terminals=False: flow.Answers(asked=1)
    )
    monkeypatch.setattr(wizard.flow, "review", lambda c, a: None)
    assert wizard.main([]) == 0
    said = "\n".join(console.captured)
    assert "PREVIEW" in said
    assert "NOTHING was saved" in said
    assert "tstack config wizard" in said
    assert "[D]one" in said and "[P]roceed" not in said


def test_an_emitting_wizard_stays_quiet_about_previews(monkeypatch, tmp_path):
    """The installers' path saves; telling them nothing was saved would be wrong."""
    console = Console.scripted([])
    monkeypatch.setattr(wizard.Console, "open", classmethod(lambda cls, tty="": console))
    monkeypatch.setattr(
        wizard.flow, "collect", lambda c, ask_terminals=False: flow.Answers(asked=1)
    )
    monkeypatch.setattr(wizard.flow, "review", lambda c, a: None)
    assert wizard.main(["--emit", "sh", "--out", str(tmp_path / "a.sh")]) == 0
    said = "\n".join(console.captured)
    assert "PREVIEW" not in said
    assert "[P]roceed (save and apply)" in said


def test_config_says_what_to_do_after_a_change(monkeypatch):
    monkeypatch.setattr(config.hotkey, "held_elsewhere", lambda chord: None)
    lines = "\n".join(config.next_steps("leaderChord", "ctrl-a"))
    assert "Ctrl+Shift+R" in lines and "tstack doctor" in lines
    assert config.next_steps("apps", "eza") == [], "nothing to add for a setting with no steps"
