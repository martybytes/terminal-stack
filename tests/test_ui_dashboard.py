"""The dashboard tabs and the worker-thread save. Headless Textual, no terminal.

Every slow or machine-touching read is stubbed at the model boundary, which is
the whole reason `model.py` exists: the app binds keys to it and nothing else.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

pytest.importorskip("textual", reason="tstack ui's one optional dependency")

from textual.widgets import (  # noqa: E402
    DataTable,
    ListView,
    MarkdownViewer,
    TabbedContent,
    TabPane,
)

from tstack import platform as plat  # noqa: E402
from tstack import store  # noqa: E402
from tstack.ui import model  # noqa: E402
from tstack.ui.app import SettingsApp  # noqa: E402


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
    # Nothing in these tests may probe Docker, run doctor or read the clone.
    monkeypatch.setattr(model, "home_tiles", lambda: [("clone", "/x"), ("version", "abc on main")])
    monkeypatch.setattr(
        model,
        "doctor_report",
        lambda: (
            [
                model.Check("clone", "OK", "clone: /x", ""),
                model.Check(
                    "headroom-token",
                    "FAIL",
                    "the proxy rejects the token",
                    "tstack doctor --repair",
                ),
            ],
            1,
        ),
    )
    monkeypatch.setattr(
        model,
        "service_rows",
        lambda: [
            model.Stack("agentmemory", "ok", "running (1/1)", 1, 1, "3110", ""),
            model.Stack("kokoro", "off", "TTS engine is edge", 0, 0, "", ""),
        ],
    )
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "fzf.md").write_text("# fzf\n\nfuzzy things\n", encoding="utf-8")
    (kb / "git.md").write_text("# git\n\nversion control\n", encoding="utf-8")
    monkeypatch.setattr(
        model, "kb_topics", lambda: [("fzf", "fzf", kb / "fzf.md"), ("git", "git", kb / "git.md")]
    )
    yield home
    store.clear_cache()


def drive(coro_factory):
    return asyncio.run(coro_factory())


async def settle(pilot, predicate, what, tries=80):
    for _ in range(tries):
        if predicate():
            return
        await pilot.pause()
    raise AssertionError(f"timed out waiting for {what}")


def test_the_tabs_exist_and_settings_is_first():
    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            tabs = app.query_one("#tabs", TabbedContent)
            assert tabs.active == "settings"
            assert app.query_one("#table", DataTable).row_count > 0
            assert {p.id for p in app.query(TabPane)} == {
                "home",
                "settings",
                "doctor",
                "services",
                "docs",
            }
            await settle(
                pilot, lambda: type(app.focused).__name__ == "DataTable", "the table to take focus"
            )
            await pilot.press("alt+1")
            home = app.query_one("#home-table", DataTable)
            await settle(pilot, lambda: home.row_count >= 3, "home tiles")
            assert "home" in app.loaded

    drive(script)


def test_the_doctor_tab_runs_the_checks_in_a_worker_and_lists_failures_first():
    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            app.action_switch_tab("doctor")
            table = app.query_one("#doctor-table", DataTable)
            await settle(pilot, lambda: table.row_count == 2, "doctor rows")
            first = table.get_row_at(0)
            assert first[0] == "fail" and first[1] == "headroom-token"
            # The first row (a FAIL) is highlighted on load, so the detail shows
            # its message and hint rather than the summary line.
            await settle(
                pilot, lambda: "the proxy rejects the token" in app.doctor_text, "the row detail"
            )
            assert "tstack doctor --repair" in app.doctor_text

    drive(script)


def test_the_services_tab_lists_stacks_and_stop_asks_first(monkeypatch):
    actions: list[tuple[str, str]] = []
    monkeypatch.setattr(
        model,
        "service_action",
        lambda verb, name: actions.append((verb, name)) or (True, f"{verb} {name} ok"),
    )

    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            app.action_switch_tab("services")
            table = app.query_one("#services-table", DataTable)
            await settle(pilot, lambda: table.row_count == 2, "service rows")
            assert table.get_row_at(0)[0] == "agentmemory" and table.get_row_at(1)[1] == "off"
            table.focus()
            await pilot.pause()
            await pilot.press("x")
            await settle(pilot, lambda: len(app.screen_stack) > 1, "the confirm screen")
            await pilot.press("n")
            await settle(pilot, lambda: len(app.screen_stack) == 1, "the confirm to close")
            assert actions == [], "n means nothing stops"
            await pilot.press("s")
            await settle(pilot, lambda: actions == [("up", "agentmemory")], "the start action")

    drive(script)


def test_the_docs_tab_renders_the_highlighted_topic():
    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            app.action_switch_tab("docs")
            listing = app.query_one("#docs-list", ListView)
            await settle(pilot, lambda: len(listing.children) == 2, "topics")
            viewer = app.query_one("#docs-view", MarkdownViewer)
            listing.focus()
            listing.index = 1
            await settle(pilot, lambda: "version control" in viewer.document.source, "the git page")
            app.query_one("#docs-filter").value = "fz"  # type: ignore[attr-defined]
            await settle(pilot, lambda: len(listing.children) == 1, "the topic filter")

    drive(script)


def test_a_save_runs_off_the_ui_thread_and_reports_when_done(monkeypatch):
    seen: list[tuple[str, str]] = []

    def slow_save(key: str, value: str) -> tuple[bool, str]:
        seen.append((key, value))
        return (True, f"saved: {key} = {value}")

    monkeypatch.setattr(model, "save", slow_save)

    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            app.query_one("#filter").value = "themeMode"  # type: ignore[attr-defined]
            table = app.query_one("#table", DataTable)
            await settle(pilot, lambda: table.row_count == 1, "the filter")
            app.commit("themeMode", "light")
            assert app.saving is True
            assert "applying" in app.detail_text
            await settle(pilot, lambda: not app.saving, "the worker to finish")
            assert seen == [("themeMode", "light")]
            assert app.detail_text == "saved: themeMode = light"

    drive(script)


def test_edit_and_cycle_are_refused_while_a_save_is_in_flight():
    async def script():
        app = SettingsApp()
        async with app.run_test() as pilot:
            app.saving = True
            opened_before = len(app.screen_stack)
            await pilot.press("e")
            await pilot.pause()
            assert len(app.screen_stack) == opened_before
            app.saving = False

    drive(script)
