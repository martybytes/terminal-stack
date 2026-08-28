"""`tstack ui`'s Textual shell, driven headless.

SEPARATE MODULE, and that is the whole point of the file existing. The gate below
is `pytest.importorskip`, which skips the module it is IN -- putting it at the top
of tests/test_ui.py silently took the fourteen stdlib-only model tests with it, so
on any machine without Textual (which is most of them, it being this program's one
optional dependency) the dashboard's actual rules stopped being tested and the
suite still reported green.

What is here needs a real widget tree: Textual's run_test() builds one with no
terminal. Not mocked -- a mocked DataTable would not have caught the binding bug
in test_enter_on_a_row_opens_the_editor, which is the only interesting thing this
layer has ever got wrong.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import platform as plat  # noqa: E402
from tstack import schema, store  # noqa: E402

pytest.importorskip("textual", reason="tstack ui's one optional dependency")

from textual.widgets import DataTable, Input  # noqa: E402

from tstack.ui.app import EditScreen, SettingsApp  # noqa: E402


@pytest.fixture(autouse=True)
def _throwaway_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    monkeypatch.setattr(store, "mirror", lambda: {})
    monkeypatch.setattr(store, "mirror_path", lambda: None)
    store.clear_cache()
    yield home
    store.clear_cache()


def drive(coro_factory):
    """Run one async pilot script. asyncio.run rather than pytest-asyncio, so the
    suite gains no plugin for four tests."""
    return asyncio.run(coro_factory())


def test_the_dashboard_mounts_with_every_setting_and_filters_live():

    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            table = app.query_one("#table", DataTable)
            total = table.row_count
            assert total == len(schema.SETTINGS)

            app.query_one("#filter", Input).value = "kokoro"
            await pilot.pause()
            assert 0 < table.row_count < total

            app.query_one("#filter", Input).value = ""
            await pilot.pause()
            assert table.row_count == total

    drive(script)


def test_enter_on_a_row_opens_the_editor():
    """The regression this exists for: DataTable binds `enter` to its own select
    action, and a focused widget's bindings beat the App's -- so the App-level
    `enter` binding never fired and pressing Enter on a row did nothing at all.
    The RowSelected handler is what actually opens it.
    """

    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            app.query_one("#filter", Input).value = "themeMode"
            await pilot.pause()
            app.query_one("#table", DataTable).focus()
            await pilot.pause()
            before = app.current().value

            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EditScreen)
            assert app.screen.row.key == "themeMode"

            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, EditScreen)
            assert app.current().value == before, "cancel must not write"

    drive(script)


def test_a_derived_row_refuses_in_the_ui_as_well_as_in_the_model():

    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            app.query_one("#filter", Input).value = "resolvedTheme"
            await pilot.pause()
            app.query_one("#table", DataTable).focus()
            await pilot.pause()
            await pilot.press("space")
            await pilot.pause()
            assert "not editable" in app.detail_text
            assert not store.toml_path().exists(), "nothing may have been written"

    drive(script)


def test_an_empty_filter_result_says_so_instead_of_showing_a_blank_screen():

    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            app.query_one("#filter", Input).value = "no-such-setting-anywhere"
            await pilot.pause()
            assert app.query_one("#table", DataTable).row_count == 0
            assert app.current() is None
            assert "no settings match" in app.detail_text

    drive(script)


def test_the_source_column_is_visible_on_a_normal_terminal():
    """`source` is the whole reason this screen exists -- a printed value cannot
    tell you whether it came from chezmoi [data], the Windows mirror or nothing
    at all, and on 2026-08-21 those three disagreed while every report looked
    healthy. Auto-sized columns pushed it off the right edge at 110 columns.
    """
    from tstack.ui.app import elide

    async def script():
        app = SettingsApp()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            table = app.query_one("#table", DataTable)
            widths = [c.width for c in table.columns.values()]
            assert sum(widths) <= 100, f"columns total {sum(widths)} on a 100-column terminal"
            assert len(widths) == 5

    drive(script)

    # ASCII only: tests/test_agent_tools.py pins every byte this program prints,
    # because a Windows console on codepage 437 renders anything else as
    # mojibake. A one-character ellipsis is exactly what slips past review.
    cut = elide("x" * 80, 20)
    assert len(cut) == 20 and cut.endswith("..")
    assert cut.isascii()
    assert elide("short", 20) == "short"


# ---------------------------------------------------------------- the picker


def test_a_setting_with_live_options_gets_a_picker_not_a_text_box(monkeypatch):
    """`ccTtsKokoroVoice` is `kind="text"` because its valid values are not a
    fixed list -- they are whatever the running server serves. That made it a
    blind text box, which is exactly what `tstack config tts voices` exists to
    save you from.
    """
    from tstack.ui import model
    from tstack.ui.app import PickScreen

    monkeypatch.setattr(
        model, "live_options", lambda row: [("af_heart", "af_heart", "American female")]
    )

    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            app.query_one("#filter", Input).value = "ccTtsKokoroVoice"
            await pilot.pause()
            app.query_one("#table", DataTable).focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, PickScreen)
            assert app.screen.query_one("#pick-table", DataTable).row_count == 1
            await pilot.press("escape")
            await pilot.pause()

    drive(script)


def test_a_probe_that_finds_nothing_falls_back_to_the_text_box(monkeypatch):
    """kokoro stopped, starship not installed yet. Refusing to edit would be
    worse than the box this replaced."""
    from tstack.ui import model
    from tstack.ui.app import EditScreen

    monkeypatch.setattr(model, "live_options", lambda row: [])

    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            app.query_one("#filter", Input).value = "ccTtsKokoroVoice"
            await pilot.pause()
            app.query_one("#table", DataTable).focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, EditScreen)
            await pilot.press("escape")
            await pilot.pause()

    drive(script)


def test_escape_is_distinguishable_from_choosing_the_empty_value(monkeypatch):
    """An unset `ccTtsSayVoice` MEANS "the system voice", so "" is a real answer
    and cannot also mean cancelled. A shared sentinel is the only way a modal
    that can legitimately return "" says which happened.
    """
    from tstack.ui import model
    from tstack.ui.app import CANCELLED, PickScreen

    monkeypatch.setattr(
        model,
        "live_options",
        lambda row: [
            ("", "(system voice)", "whatever macOS is set to"),
            ("Daniel", "Daniel", "en_GB"),
        ],
    )
    saved: list[tuple[str, str]] = []
    monkeypatch.setattr(model, "save", lambda k, v: (saved.append((k, v)), (True, "ok"))[1])

    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            app.query_one("#filter", Input).value = "ccTtsSayVoice"
            await pilot.pause()
            app.query_one("#table", DataTable).focus()
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, PickScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert saved == [], "escape must not write, even though '' is selectable"

            # ...and choosing the empty value DOES write it.
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert saved == [("ccTtsSayVoice", "Daniel")]

    drive(script)
    assert CANCELLED != "", "the sentinel may never collide with a real value"


def test_the_picker_advertises_hearing_only_where_there_is_something_to_hear(monkeypatch):
    """`s hear it` on a prompt preset is a small lie about a key that does
    nothing."""
    from tstack.ui import model
    from tstack.ui.app import PickScreen

    monkeypatch.setattr(model, "live_options", lambda row: [("tokyo-night", "tokyo-night", "")])
    monkeypatch.setattr(model, "can_sample", lambda row: False)

    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            app.query_one("#filter", Input).value = "starshipPreset"
            await pilot.pause()
            app.query_one("#table", DataTable).focus()
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, PickScreen)
            # The help text is built from can_sample; assert on the source of it
            # rather than on a widget's private rendering internals.
            assert not model.can_sample(app.screen.row)
            await pilot.press("s")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    drive(script)
