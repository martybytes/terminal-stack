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
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Label, Static

from . import model

# Escape must be distinguishable from choosing the empty value: an unset
# `ccTtsSayVoice` MEANS "the system voice", so "" is a real answer and cannot
# also mean cancelled.
CANCELLED = "\x00cancelled"


def elide(text: str, width: int) -> str:
    """Trim to a fixed column, marking that something was cut.

    ASCII only: `tests/test_agent_tools.py` pins every byte this program can
    print, because a Windows console on codepage 437 renders anything else as
    mojibake. A single-character ellipsis is exactly the kind of thing that slips
    past review and then only fails on the platform nobody is testing on.
    """
    return text if len(text) <= width else text[: width - 2] + ".."


class MultiPickScreen(ModalScreen[str]):
    """Tick many. `apps` is the only setting shaped like this, and it is why the
    dashboard needed more than a menu: editing 32 tool names as one
    space-separated string is not editing, it is retyping.

    Returns the selection as the space-separated string the store holds.
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("escape", "cancel", "cancel"),
        Binding("space", "toggle_row", "toggle"),
        Binding("a", "all", "all"),
        Binding("n", "none", "none"),
        Binding("enter", "accept", "save", show=True),
    ]

    def __init__(self, row: model.Row, options: list[tuple[str, str, str]]) -> None:
        super().__init__()
        self.row = row
        self.options = options
        self.chosen: set[str] = model.selected(row)

    def compose(self) -> ComposeResult:
        with Vertical(id="pick-box"):
            yield Label(f"{self.row.label}  [{self.row.key}]", id="pick-title")
            yield DataTable(id="pick-table", cursor_type="row", zebra_stripes=True)
            yield Static("", id="pick-preview")
            yield Static(
                "space toggle  -  a all  -  n none  -  Enter save  -  Esc cancel",
                id="pick-help",
            )

    def on_mount(self) -> None:
        table = self.query_one("#pick-table", DataTable)
        table.add_column("", width=3)
        table.add_column("tool", width=16)
        table.add_column("what it is", width=52)
        self.redraw()
        table.focus()

    def redraw(self) -> None:
        table = self.query_one("#pick-table", DataTable)
        keep = table.cursor_row
        table.clear()
        for value, label, note in self.options:
            table.add_row("[x]" if value in self.chosen else "[ ]", label, elide(note, 50))
        if self.options:
            table.move_cursor(row=min(keep, len(self.options) - 1))
        self.count()

    def count(self) -> None:
        self.query_one("#pick-preview", Static).update(
            f"{len(self.chosen)} of {len(self.options)} selected. "
            "Installs only -- nothing is ever uninstalled."
        )

    def action_toggle_row(self) -> None:
        index = self.query_one("#pick-table", DataTable).cursor_row
        if not (0 <= index < len(self.options)):
            return
        value = self.options[index][0]
        self.chosen.symmetric_difference_update({value})
        self.redraw()

    def action_all(self) -> None:
        self.chosen = {value for value, _l, _n in self.options}
        self.redraw()

    def action_none(self) -> None:
        self.chosen = set()
        self.redraw()

    def on_data_table_row_selected(self, _: DataTable.RowSelected) -> None:
        """Enter, when the table has focus.

        The same trap as the settings table: DataTable binds `enter` to its own
        select action and a focused widget's bindings beat the screen's, so the
        `enter` binding above never fires here. It is kept so the footer
        advertises it; this is the path that runs.
        """
        self.action_accept()

    def action_accept(self) -> None:
        # Catalog order, not tick order: the saved value should be stable and
        # diffable rather than a record of the order someone clicked.
        self.dismiss(" ".join(v for v, _l, _n in self.options if v in self.chosen))

    def action_cancel(self) -> None:
        self.dismiss(CANCELLED)


class PickScreen(ModalScreen[str]):
    """Choose from what this machine can actually offer, having seen or heard it.

    The reason this exists rather than a text box: `ccTtsKokoroVoice` and
    `starshipPreset` are `kind="text"` in the schema because their valid values
    are not a fixed list -- they are the 68 voices a running kokoro happens to
    serve and the presets the installed starship happens to ship. Typing a name
    blind is exactly what `tstack config tts voices` and `tstack config prompt
    list` exist to save you from, and the dashboard had no equivalent.

    The options are probed when the screen opens, so a kokoro started since the
    dashboard launched shows up on the next open.
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("escape", "cancel", "cancel"),
        Binding("s", "sample", "hear it"),
    ]

    def __init__(self, row: model.Row, options: list[tuple[str, str, str]]) -> None:
        super().__init__()
        self.row = row
        self.options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="pick-box"):
            yield Label(f"{self.row.label}  [{self.row.key}]", id="pick-title")
            yield DataTable(id="pick-table", cursor_type="row", zebra_stripes=True)
            yield Static("", id="pick-preview")
            # ASCII only. Every byte this program prints is pinned, because a
            # Windows console on codepage 437 renders anything else as mojibake
            # -- and `s` is advertised only where there is something to hear.
            hear = "  -  s hear it" if model.can_sample(self.row) else ""
            yield Static(f"Enter choose{hear}  -  Esc cancel", id="pick-help")

    def on_mount(self) -> None:
        table = self.query_one("#pick-table", DataTable)
        table.add_column("value", width=34)
        table.add_column("what it is", width=30)
        here = 0
        for index, (value, label, note) in enumerate(self.options):
            marker = "*" if value == self.row.value else " "
            table.add_row(f"{marker}{elide(label, 32)}", elide(note, 28))
            if value == self.row.value:
                here = index
        table.move_cursor(row=here)
        table.focus()
        self.show_preview()

    def current(self) -> str | None:
        index = self.query_one("#pick-table", DataTable).cursor_row
        if 0 <= index < len(self.options):
            return self.options[index][0]
        return None

    def show_preview(self, message: str = "") -> None:
        if message:
            self.query_one("#pick-preview", Static).update(message)
            return
        value = self.current()
        rendered = model.preview_of(self.row, value) if value is not None else None
        # A preview is only meaningful for some providers. Where there is none,
        # the row's own note is more use than an empty box.
        self.query_one("#pick-preview", Static).update(rendered or self.row.note or "")

    def on_data_table_row_highlighted(self, _: DataTable.RowHighlighted) -> None:
        self.show_preview()

    def on_data_table_row_selected(self, _: DataTable.RowSelected) -> None:
        value = self.current()
        if value is not None:
            self.dismiss(value)

    def action_sample(self) -> None:
        value = self.current()
        if value is None or not model.can_sample(self.row):
            return
        self.show_preview("listening...")
        played, message = model.sample_of(self.row, value)
        self.show_preview(message if played else f"could not play it: {message}")

    def action_cancel(self) -> None:
        self.dismiss(CANCELLED)


class EditScreen(ModalScreen[str]):
    """One value, one box. Dismisses with the new value, or nothing on Escape."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("escape", "cancel", "cancel")
    ]

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
        self.dismiss(CANCELLED)


class SettingsApp(App[None]):
    """Every saved setting, what it is now, and where that value came from."""

    TITLE = "tstack"
    SUB_TITLE = "saved settings"

    CSS = """
    Screen { layout: vertical; }
    #filter { height: 3; }
    #table { height: 1fr; }
    #detail { height: 4; padding: 0 1; border-top: solid $accent; }
    #edit-box {
        width: 70%; height: auto; padding: 1 2;
        background: $panel; border: thick $accent;
    }
    #edit-title { text-style: bold; }
    #edit-note, #edit-options, #edit-default { color: $text-muted; }
    EditScreen { align: center middle; }
    PickScreen { align: center middle; }
    MultiPickScreen { align: center middle; }
    #pick-box {
        width: 80%; height: 80%; padding: 1 2;
        background: $panel; border: thick $accent;
    }
    #pick-title { text-style: bold; }
    #pick-table { height: 1fr; }
    #pick-preview { height: 4; padding: 1 0 0 0; }
    #pick-help { color: $text-muted; }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit", "quit"),
        Binding("slash", "focus_filter", "filter"),
        # `e` as well as Enter, and it is the one the footer advertises: a
        # focused DataTable claims `enter` for its own select action, so the
        # App-level binding is invisible there. The Enter path still works --
        # on_data_table_row_selected -- it just cannot be shown.
        Binding("e", "edit", "edit"),
        Binding("enter", "edit", "edit", show=False),
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
        yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="detail")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#table", DataTable)
        # Explicit widths. Auto-sizing to content pushed `source` off the right
        # edge on an 110-column terminal -- and `source` is the whole reason this
        # screen exists, because a printed value cannot tell you which layer it
        # came from.
        table.add_column("group", width=12)
        table.add_column("setting", width=30)
        table.add_column("value", width=38)
        table.add_column("source", width=9)
        table.add_column("then", width=9)
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
            table.add_row(
                row.group, name, f"{marker}{elide(row.display, 36)}", row.source, row.after
            )
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
            if value is None or value == CANCELLED or value == row.value:
                return
            self.commit(row.key, value)

        live = model.live_options(row)
        if live and model.is_multi(row):
            self.push_screen(MultiPickScreen(row, live), done)
            return
        if live:
            self.push_screen(PickScreen(row, live), done)
            return
        # No provider, or the probe found nothing -- kokoro down, starship not
        # installed yet. A text box is still better than refusing to edit.
        self.push_screen(EditScreen(row), done)

    def commit(self, key: str, value: str) -> None:
        row = next((r for r in self.shown if r.key == key), None)
        writer = model.save_llm if row is not None and row.store == model.LLM else model.save
        ok, message = writer(key, value)
        self.action_reload()
        self.show_detail(message if ok else f"refused: {message}")
