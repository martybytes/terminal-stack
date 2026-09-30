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

from collections.abc import Callable
from typing import ClassVar

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    MarkdownViewer,
    Static,
    TabbedContent,
    TabPane,
)

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


class ConfirmScreen(ModalScreen[bool]):
    """y / n. Used before anything that stops a running service."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("y", "yes", "yes"),
        Binding("n", "no", "no"),
        Binding("escape", "no", "cancel", show=False),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="edit-box"):
            yield Label(self.question, id="edit-title")
            yield Label("y = yes   n = no", id="edit-note")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class TextScreen(ModalScreen[None]):
    """Scrollable text, for logs. Escape or q closes."""

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("escape", "close", "close"),
        Binding("q", "close", "close", show=False),
    ]

    def __init__(self, title: str, text: str) -> None:
        super().__init__()
        self.title_text = title
        self.text = text

    def compose(self) -> ComposeResult:
        with Vertical(id="pick-box"):
            yield Label(self.title_text, id="pick-title")
            with VerticalScroll(id="text-scroll"):
                yield Static(self.text, id="text-body")
            yield Label("esc closes", id="pick-help")

    def action_close(self) -> None:
        self.dismiss(None)


class SettingsApp(App[None]):
    """The dashboard: home, every saved setting and where it came from, the
    doctor's checks, the service stacks, and the knowledge base.

    Nothing slow runs on the UI thread. Saves (which end in `chezmoi apply`),
    the doctor and the service probes run in worker threads and post their
    result back; the screen says "working..." meanwhile instead of freezing,
    which is what the first version did for seconds to minutes on every save.
    """

    TITLE = "tstack"
    SUB_TITLE = "dashboard"

    CSS = """
    Screen { layout: vertical; }
    TabbedContent { height: 1fr; }
    #filter, #docs-filter { height: 3; }
    #table, #doctor-table, #services-table, #home-table { height: 1fr; }
    #detail, #doctor-detail, #services-detail { height: 4; padding: 0 1; border-top: solid $accent; }
    #docs-side { width: 36; }
    #docs-list { height: 1fr; }
    #docs-view { height: 1fr; }
    #edit-box {
        width: 70%; height: auto; padding: 1 2;
        background: $panel; border: thick $accent;
    }
    #edit-title { text-style: bold; }
    #edit-note, #edit-options, #edit-default { color: $text-muted; }
    EditScreen { align: center middle; }
    PickScreen { align: center middle; }
    MultiPickScreen { align: center middle; }
    ConfirmScreen { align: center middle; }
    TextScreen { align: center middle; }
    #pick-box {
        width: 80%; height: 80%; padding: 1 2;
        background: $panel; border: thick $accent;
    }
    #pick-title { text-style: bold; }
    #pick-table { height: 1fr; }
    #text-scroll { height: 1fr; }
    #pick-preview { height: 4; padding: 1 0 0 0; }
    #pick-help { color: $text-muted; }
    """

    BINDINGS: ClassVar[list[Binding | tuple[str, str] | tuple[str, str, str]]] = [
        Binding("q", "quit", "quit"),
        Binding("alt+1", "switch_tab('home')", "home", show=False),
        Binding("alt+2", "switch_tab('settings')", "settings", show=False),
        Binding("alt+3", "switch_tab('doctor')", "doctor", show=False),
        Binding("alt+4", "switch_tab('services')", "services", show=False),
        Binding("alt+5", "switch_tab('docs')", "docs", show=False),
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
        Binding("s", "service_up", "start", show=False),
        Binding("x", "service_down", "stop", show=False),
        Binding("l", "service_logs", "logs", show=False),
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
        self.doctor_text: str = ""
        self.services_text: str = ""
        self.saving = False
        # A save's result must outlive the RowHighlighted the table refresh
        # posts right after it, which would otherwise replace the message with
        # the row's description before anyone read it.
        self.sticky_message: str = ""
        self.sticky_row: int = -1
        self.checks: list[model.Check] = []
        self.stack_rows: list[model.Stack] = []
        self.topics: list[tuple[str, str, object]] = []
        self.shown_topics: list[tuple[str, str, object]] = []
        self.loaded: set[str] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        with TabbedContent(initial="settings", id="tabs"):
            with TabPane("Home", id="home"):
                yield DataTable(id="home-table", cursor_type="row", zebra_stripes=True)
            with TabPane("Settings", id="settings"):
                yield Input(placeholder="filter: key, label, group, value or note", id="filter")
                yield DataTable(id="table", cursor_type="row", zebra_stripes=True)
                yield Static("", id="detail")
            with TabPane("Doctor", id="doctor"):
                yield DataTable(id="doctor-table", cursor_type="row", zebra_stripes=True)
                yield Static("", id="doctor-detail")
            with TabPane("Services", id="services"):
                yield DataTable(id="services-table", cursor_type="row", zebra_stripes=True)
                yield Static("", id="services-detail")
            with TabPane("Docs", id="docs"), Horizontal():
                with Vertical(id="docs-side"):
                    yield Input(placeholder="filter topics", id="docs-filter")
                    yield ListView(id="docs-list")
                yield MarkdownViewer("", show_table_of_contents=False, id="docs-view")
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
        home = self.query_one("#home-table", DataTable)
        home.add_column("what", width=18)
        home.add_column("state", width=80)
        doctor = self.query_one("#doctor-table", DataTable)
        doctor.add_column("status", width=6)
        doctor.add_column("check", width=24)
        doctor.add_column("message", width=90)
        services = self.query_one("#services-table", DataTable)
        services.add_column("stack", width=16)
        services.add_column("state", width=8)
        services.add_column("what", width=48)
        services.add_column("ports", width=24)
        self.action_reload()
        # After the first refresh: the pane's Input takes focus during mount,
        # and a filter box with focus would swallow every key binding.
        self.call_after_refresh(table.focus)

    # ------------------------------------------------------------------ tabs

    def active_tab(self) -> str:
        return str(self.query_one("#tabs", TabbedContent).active or "settings")

    def action_switch_tab(self, pane: str) -> None:
        self.query_one("#tabs", TabbedContent).active = pane

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        pane = str(event.pane.id or "")
        if pane == "home":
            self.load_home()
        elif pane == "doctor" and "doctor" not in self.loaded:
            self.load_doctor()
        elif pane == "services" and "services" not in self.loaded:
            self.load_services()
        elif pane == "docs" and "docs" not in self.loaded:
            self.load_docs()

    # ------------------------------------------------------------------ data

    def action_reload(self) -> None:
        tab = self.active_tab()
        if tab == "doctor":
            self.load_doctor()
        elif tab == "services":
            self.load_services()
        elif tab == "home":
            self.load_home()
        elif tab == "docs":
            self.load_docs()
        else:
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

    # ------------------------------------------------------------ home tab

    @work(thread=True, exclusive=True, group="home")
    def load_home(self) -> None:
        tiles = model.home_tiles()
        self.call_from_thread(self._show_home, tiles)

    def _show_home(self, tiles: list[tuple[str, str]]) -> None:
        table = self.query_one("#home-table", DataTable)
        table.clear()
        for what, state in tiles:
            table.add_row(what, elide(state, 78))
        issues = (
            f"{sum(1 for c in self.checks if c.status == 'FAIL')} failing check(s)"
            if self.checks
            else "run the Doctor tab"
        )
        up = sum(1 for r in self.stack_rows if r.level == "ok")
        table.add_row("doctor", issues)
        table.add_row(
            "services",
            f"{up}/{len(self.stack_rows)} stacks running"
            if self.stack_rows
            else "open the Services tab",
        )
        table.add_row(
            "keys", "1-5 tabs  /  filter  e edit  space next value  r reload  s x l services"
        )
        self.loaded.add("home")

    # ---------------------------------------------------------- doctor tab

    @work(thread=True, exclusive=True, group="doctor")
    def load_doctor(self) -> None:
        self.call_from_thread(self._doctor_detail, "running the checks...")
        try:
            checks, issues = model.doctor_report()
        except Exception as exc:  # a broken machine is what this tab is FOR
            self.call_from_thread(
                self._doctor_detail, f"doctor failed: {type(exc).__name__}: {exc}"
            )
            return
        self.call_from_thread(self._show_doctor, checks, issues)

    def _doctor_detail(self, text: str) -> None:
        self.doctor_text = text
        self.query_one("#doctor-detail", Static).update(text)

    def _show_doctor(self, checks: list[model.Check], issues: int) -> None:
        self.checks = checks
        table = self.query_one("#doctor-table", DataTable)
        table.clear()
        order = {"FAIL": 0, "NOTE": 1, "OK": 2}
        for check in sorted(checks, key=lambda c: (order.get(c.status, 3), c.check)):
            table.add_row(check.status.lower(), check.check, elide(check.message, 88))
        self._doctor_detail(
            f"{issues} issue(s). r re-runs; 'tstack doctor --repair' fixes what is fixable, asking first."
            if issues
            else "all checks passed. r re-runs."
        )
        self.loaded.add("doctor")

    # -------------------------------------------------------- services tab

    @work(thread=True, exclusive=True, group="services")
    def load_services(self) -> None:
        self.call_from_thread(self._services_detail, "asking the engine...")
        try:
            rows = model.service_rows()
        except Exception as exc:
            self.call_from_thread(
                self._services_detail, f"services failed: {type(exc).__name__}: {exc}"
            )
            return
        self.call_from_thread(self._show_services, rows)

    def _services_detail(self, text: str) -> None:
        self.services_text = text
        self.query_one("#services-detail", Static).update(text)

    def _show_services(self, rows: list[model.Stack]) -> None:
        self.stack_rows = rows
        table = self.query_one("#services-table", DataTable)
        table.clear()
        for row in rows:
            table.add_row(row.name, row.level, elide(row.line, 46), row.ports)
        self._services_detail(
            "s start  x stop  l logs  r refresh"
            + ("" if rows else "  (no stacks: is there a clone?)")
        )
        self.loaded.add("services")

    def current_stack(self) -> model.Stack | None:
        table = self.query_one("#services-table", DataTable)
        index = table.cursor_row
        if 0 <= index < len(self.stack_rows):
            return self.stack_rows[index]
        return None

    def action_service_up(self) -> None:
        if self.active_tab() != "services":
            return
        stack = self.current_stack()
        if stack:
            self.run_service("up", stack.name)

    def action_service_down(self) -> None:
        if self.active_tab() != "services":
            return
        stack = self.current_stack()
        if not stack:
            return

        def done(yes: bool | None) -> None:
            if yes:
                self.run_service("down", stack.name)

        self.push_screen(
            ConfirmScreen(f"Stop {stack.name}? Its containers go down; volumes stay."), done
        )

    def action_service_logs(self) -> None:
        if self.active_tab() != "services":
            return
        stack = self.current_stack()
        if stack:
            self.run_service("logs", stack.name)

    @work(thread=True, exclusive=True, group="service-action")
    def run_service(self, verb: str, name: str) -> None:
        self.call_from_thread(self._services_detail, f"{verb} {name}...")
        ok, text = model.service_action(verb, name)
        if verb == "logs":
            self.call_from_thread(self.push_screen, TextScreen(f"{name} logs", text))
            self.call_from_thread(self._services_detail, "s start  x stop  l logs  r refresh")
            return
        self.call_from_thread(self._services_detail, text if ok else f"failed: {text}")
        rows = model.service_rows()
        self.call_from_thread(self._show_services_keep_detail, rows)

    def _show_services_keep_detail(self, rows: list[model.Stack]) -> None:
        keep = self.services_text
        self._show_services(rows)
        self._services_detail(keep)

    # ------------------------------------------------------------ docs tab

    def load_docs(self) -> None:
        self.topics = list(model.kb_topics())
        self.refresh_topics()
        self.loaded.add("docs")

    def refresh_topics(self) -> None:
        query = self.query_one("#docs-filter", Input).value.strip().lower()
        self.shown_topics = [
            t for t in self.topics if not query or query in t[0].lower() or query in t[1].lower()
        ]
        listing = self.query_one("#docs-list", ListView)
        listing.clear()
        for label, title, _path in self.shown_topics:
            listing.append(ListItem(Label(title), name=label))
        if not self.topics:
            self.query_one("#docs-view", MarkdownViewer).document.update(
                "# no knowledge base found\n\nSet TERMINAL_STACK_DIR or DOC_ROOT."
            )

    async def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if item is None or item.name is None:
            return
        for label, _title, path in self.shown_topics:
            if label == item.name:
                text = model.kb_markdown(path)  # type: ignore[arg-type]
                await self.query_one("#docs-view", MarkdownViewer).document.update(text)
                return

    # -------------------------------------------------------------- inputs

    def action_focus_filter(self) -> None:
        target = "#docs-filter" if self.active_tab() == "docs" else "#filter"
        self.query_one(target, Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "docs-filter":
            self.refresh_topics()
        elif event.input.id == "filter":
            self.refresh_table()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        table_id = event.data_table.id
        if table_id == "table":
            if self.sticky_message and event.cursor_row == self.sticky_row:
                return  # the refresh after a save, not the user moving
            self.sticky_message = ""
            self.show_detail()
        elif table_id == "doctor-table":
            index = event.cursor_row
            order = {"FAIL": 0, "NOTE": 1, "OK": 2}
            ordered = sorted(self.checks, key=lambda c: (order.get(c.status, 3), c.check))
            if 0 <= index < len(ordered):
                check = ordered[index]
                self._doctor_detail(
                    f"{check.check}: {check.message}"
                    + (f"\n  -> {check.hint}" if check.hint else "")
                )
        elif table_id == "services-table":
            stack = self.current_stack()
            if stack:
                self._services_detail(
                    f"{stack.name}: {stack.line}" + (f"\n  {stack.hint}" if stack.hint else "")
                )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on a row. Not reached through the `enter` binding: the DataTable
        binds enter to its own select action and a focused widget's bindings
        beat the screen's, so the App-level binding never fires. It is kept in
        BINDINGS so the footer advertises it and so it still works when focus
        is elsewhere; this handler is the path that actually runs."""
        if event.data_table.id == "table":
            self.action_edit()

    # ----------------------------------------------------------- settings

    def action_cycle(self) -> None:
        if self.active_tab() != "settings" or self.saving:
            return
        row = self.current()
        if row is None:
            return
        if not row.editable:
            self.show_detail("derived by chezmoi; not editable here")
            return
        value = model.next_choice(row)
        if value is None:
            self.show_detail("free text: press e to edit")
            return
        self.commit(row.key, value)

    def action_reset_default(self) -> None:
        if self.active_tab() != "settings" or self.saving:
            return
        row = self.current()
        if row is None or not row.editable or row.value == row.default:
            return
        self.commit(row.key, row.default)

    def action_edit(self) -> None:
        if self.active_tab() != "settings" or self.saving:
            return
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

    # One writer per store, chosen by the row rather than by the key: the key
    # alone cannot say which store it belongs to, and guessing is how a second
    # writer gets born.
    WRITERS: ClassVar[dict[str, Callable[[str, str], tuple[bool, str]]]] = {
        model.LLM: model.save_llm,
        model.WORKSPACE: model.save_workspace,
    }

    def commit(self, key: str, value: str) -> None:
        row = next((r for r in self.shown if r.key == key), None)
        store = row.store if row is not None else model.SETTINGS
        writer = self.WRITERS.get(store, model.save)
        self.saving = True
        self.show_detail(f"saving {key} and applying... (chezmoi runs in the background)")
        self.save_in_background(writer, key, value)

    @work(thread=True, exclusive=True, group="save")
    def save_in_background(
        self, writer: Callable[[str, str], tuple[bool, str]], key: str, value: str
    ) -> None:
        # Off the UI thread: a save ends in `chezmoi apply`, which took seconds
        # to minutes with the screen frozen. Every write still goes through the
        # one writer; only the waiting moved.
        ok, message = writer(key, value)
        self.call_from_thread(self._saved, ok, message)

    def _saved(self, ok: bool, message: str) -> None:
        self.saving = False
        self.all_rows = model.rows()
        self.refresh_table()
        self.sticky_message = message if ok else f"refused: {message}"
        self.sticky_row = self.query_one("#table", DataTable).cursor_row
        self.show_detail(self.sticky_message)
