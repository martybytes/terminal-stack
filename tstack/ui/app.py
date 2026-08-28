"""The Textual shell around `model.py`. No rules live here.

Everything this file does is bind a key to a function in the model and put the
result on screen. That split is what keeps the dashboard testable: the tests
exercise filtering, validation, cycling and saving without a terminal, and this
module has nothing left worth asserting about.

Textual is imported at module scope on purpose. `tstack/commands/ui.py` catches
the ImportError around importing THIS module and turns it into an instruction,
so the failure a person sees is "pip install textual", not a traceback.
"""

from __future__ import annotations

from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static

from . import model


class EditScreen(ModalScreen[str]):
    """One value, one box. Dismisses with the new value, or nothing on Escape."""

    BINDINGS: ClassVar[list[Binding]] = [Binding("escape", "cancel", "cancel")]

    def __init__(self, row: model.Row) -> None:
        super().__init__()
        self.row = row

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-box"):
            yield Label(f"{self.row.label}  [{self.row.key}]", id="edit-title")
            if self.row.note:
                yield Static(self.row.note, id="edit-note")
            if self.row.options:
                yield Static("one of: " + ", ".join(self.row.options), id="edit-options")
            yield Static(f"default: {self.row.default or '(unset)'}", id="edit-default")
            yield Input(value=self.row.value, id="edit-input")

    def on_mount(self) -> None:
        self.query_one("#edit-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss("")


class SettingsApp(App[None]):
    """Every saved setting, what it is now, and where that value came from."""

    CSS = """
    Screen { layout: vertical; }
    #filter { dock: top; height: 3; }
    #detail { dock: bottom; height: 4; padding: 0 1; border-top: solid $accent; }
    #edit-box {
        width: 70%; height: auto; padding: 1 2;
        background: $panel; border: thick $accent;
    }
    #edit-title { text-style: bold; }
    #edit-note, #edit-options, #edit-default { color: $text-muted; }
    EditScreen { align: center middle; }
    """

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "quit"),
        Binding("slash", "focus_filter", "filter"),
        Binding("enter", "edit", "edit"),
        Binding("space", "cycle", "next value"),
        Binding("r", "reload", "reload"),
        Binding("d", "reset_default", "default"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.all_rows: list[model.Row] = []
        self.shown: list[model.Row] = []
        # Kept as state as well as rendered. Reading it back off the widget means
        # reaching for a private attribute whose name has changed between Textual
        # releases (`renderable`, then `_content`, then `content`), and a test
        # that asserts on the message a save produced should not be the thing
        # that breaks on an upgrade.
        self.detail_text: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="filter: key, label, group, value or note", id="filter")
        with Horizontal():
            yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        table.add_columns("group", "setting", "value", "source", "then")
        self.action_reload()
        table.focus()

    # ------------------------------------------------------------------ data

    def action_reload(self) -> None:
        self.all_rows = model.rows()
        self.refresh_table()

    def refresh_table(self) -> None:
        query = self.query_one("#filter", Input).value
        self.shown = model.filter_rows(self.all_rows, query)
        table = self.query_one("#table", DataTable)
        keep = table.cursor_row
        table.clear()
        for row in self.shown:
            # A derived key is shown, never hidden: knowing a value exists and
            # is not yours to set is the point of listing it.
            name = row.key if row.editable else f"{row.key} (derived)"
            marker = "*" if model.changed(row) else " "
            table.add_row(row.group, name, f"{marker}{row.display}", row.source, row.after)
        if self.shown:
            table.move_cursor(row=min(keep, len(self.shown) - 1))
        self.show_detail()

    def current(self) -> model.Row | None:
        table = self.query_one("#table", DataTable)
        index = table.cursor_row
        if 0 <= index < len(self.shown):
            return self.shown[index]
        return None

    def detail_for(self, row: model.Row | None, message: str) -> str:
        if message:
            return message
        if row is None:
            return "no settings match this filter"
        bits = [f"{row.label} - {row.note}" if row.note else row.label]
        bits.append(f"default {row.default or '(unset)'}")
        if row.options:
            bits.append("one of " + ", ".join(row.options))
        if not row.editable:
            bits.append("derived by chezmoi; not editable here")
        return "\n".join(bits)

    def show_detail(self, message: str = "") -> None:
        self.detail_text = self.detail_for(self.current(), message)
        self.query_one("#detail", Static).update(self.detail_text)

    # --------------------------------------------------------------- actions

    def action_focus_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.refresh_table()

    def on_data_table_row_highlighted(self, _: DataTable.RowHighlighted) -> None:
        self.show_detail()

    def on_data_table_row_selected(self, _: DataTable.RowSelected) -> None:
        """Enter, when the table has focus.

        DataTable binds `enter` to its own select action, and a focused widget's
        bindings win over the App's -- so the App-level `enter` binding never
        fired here and pressing Enter on a row did nothing at all. It is kept in
        BINDINGS so the footer advertises it and so it still works when focus is
        in the filter box; this is the path that actually runs.
        """
        self.action_edit()

    def action_cycle(self) -> None:
        """Space on a choice setting advances it. Saves immediately, because the
        value is one of a known-good set and a dialog would add nothing."""
        row = self.current()
        if row is None:
            return
        if not row.editable:
            self.show_detail("derived by chezmoi; not editable here")
            return
        value = model.next_choice(row)
        if value is None:
            self.show_detail("not a choice setting - press Enter to type a value")
            return
        self.commit(row.key, value)

    def action_reset_default(self) -> None:
        row = self.current()
        if row is None or not row.editable:
            return
        self.commit(row.key, row.default)

    def action_edit(self) -> None:
        row = self.current()
        if row is None:
            return
        if not row.editable:
            self.show_detail("derived by chezmoi; not editable here")
            return

        def done(value: str | None) -> None:
            if value is not None and value != row.value:
                self.commit(row.key, value)

        self.push_screen(EditScreen(row), done)

    def commit(self, key: str, value: str) -> None:
        ok, message = model.save(key, value)
        self.action_reload()
        self.show_detail(message if ok else f"refused: {message}")
