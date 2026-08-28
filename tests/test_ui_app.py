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
