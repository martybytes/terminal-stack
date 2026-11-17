"""The questions, the order they are asked in, and what gates each one.

Order is not cosmetic. `profile` is first because everything below is downstream
of it, and asking about the WezTerm leader key before establishing that someone
wanted more than a prompt is fourteen questions aimed at the wrong person.

`asked` is tallied only when a question actually rendered. It is what decides
whether the review screen appears: a fully env-driven run has nothing to review
and must not block on a tty nobody is watching.
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from .. import apps as catalog
from .. import platform as plat
from .. import schema, store
from . import probes
from .console import Console
from .prompts import BACK, QUIT, Option, checklist, choice, multi, select, text

# Questions, in the order they are asked.
PROFILE_PROMPT, PROFILE_SHELL, PROFILE_FULL = "prompt", "shell", "full"

TERMINAL_GROUP = ("wezterm-nightly", "wezterm-stable")

# Catalog groups that get a step of their own in arrow-key mode, rather than a
# section of the command-line tools list: they are the ones people come to the
# installer to choose.
AI_GROUP, DESKTOP_GROUP = "ai", "desktop"


@dataclass(frozen=True)
class Answers:
    """Everything the wizard collected. The four bootstraps persist it; this
    module never writes."""

    profile: str = PROFILE_FULL
    development: str = "yes"
    app_class: str = catalog.DEVELOPER
    starship: str = "terminal-stack"
    leader: str = "ctrl-backslash"
    theme: str = "dark"
    tmux: str = "ctrl-b"
    terminals: list[str] = field(default_factory=list)
    wez_mux: str = "off"
    wez_restore: str = "off"
    atuin: str = "off"
    herdr: str = "off"
    apps: list[str] = field(default_factory=list)
    cc_tts: str = "off"
    cc_tts_message: str = "template"
    cc_tts_daemon: str = "off"
    memory_backend: str = "none"
    headroom: str = "off"
    headroom_cursor: str = "mcp"
    caveman: str = "off"
    agentmemory: str = "off"
    services: str = "off"
    asked: int = 0


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _on_off(value: str, *, default: str = "off") -> str:
    if value.lower() in ("on", "yes", "true", "1"):
        return "on"
    if value.lower() in ("off", "no", "false", "0"):
        return "off"
    return default


class GoBack(Exception):
    """The user asked for the previous step. Caught by `run`."""


class QuitWizard(Exception):
    """The user quit mid-questionnaire. Caught by `run`; exit 3."""


@dataclass(frozen=True)
class Step:
    """One answered question, as `run` replays it after a Back."""

    title: str
    value: str | list[str]
    free_text: bool = False


OptionSpec = tuple[str, str, str] | Option


def _options(options: Sequence[OptionSpec]) -> list[Option]:
    return [o if isinstance(o, Option) else Option(*o) for o in options]


@dataclass
class Asker:
    """Wraps the primitives so every question tallies `asked` the same way --
    and records each answer, which is what makes Back work.

    BACK IS A REPLAY, not a rewind. `collect` is straight-line code whose later
    questions are gated on earlier answers (the profile reshapes everything after
    it). Rather than restructure that into a state machine, `run` re-runs it with
    the answers before the target step in `replay`: those return instantly and
    silently, so the gates are re-evaluated on exactly the answers given, and the
    flow stops at the step being revisited. `memory` makes every earlier answer
    the default when a step comes round again.

    `autofill` is the review screen's "change one answer": after the edited step,
    any question already answered takes its remembered answer silently, so only
    the edited one -- and any question it newly unlocks -- is asked.
    """

    console: Console
    count: int = 0
    replay: list[Step] = field(default_factory=list)
    memory: dict[str, str | list[str]] = field(default_factory=dict)
    autofill: bool = False
    banner: str = "terminal-stack setup"
    log: list[Step] = field(default_factory=list)
    _pos: int = 0
    _live: bool = False

    @property
    def header(self) -> str:
        return f"{self.banner}  -  step {sum(1 for s in self.log if not s.free_text) + 1}"

    def _remembered(self, title: str) -> Step | None:
        if self._pos < len(self.replay):
            step = self.replay[self._pos]
            if step.title == title:
                self._pos += 1
                return step
            # The flow went somewhere the old answers do not cover. Stop
            # replaying and ask from here.
            self._pos = len(self.replay)
        if self.autofill and self._live and title in self.memory:
            return Step(title, self.memory[title])
        return None

    def _record(self, step: Step) -> None:
        self.log.append(step)
        self.memory[step.title] = step.value
        if not step.free_text:
            self.count += 1

    def _intro(self, intro: str) -> tuple[str, ...]:
        """Whatever the flow printed since the last question, then the intro.
        In arrow-key mode that becomes part of the screen; otherwise it is
        printed above the prompt exactly as before."""
        pending = self.console.take_pending()
        lines = tuple(intro.splitlines()) if intro else ()
        if self.console.tui:
            return tuple(pending) + lines
        with self.console.released():
            for line in pending:
                self.console.say(line)
        return lines

    def _settle(self, value: str | list[str], asked: bool, title: str) -> None:
        if value == BACK or value == [BACK]:
            raise GoBack
        if value == QUIT or value == [QUIT]:
            raise QuitWizard
        if asked:
            self._record(Step(title, value))
            self._live = True

    def choose(
        self, title: str, options: Sequence[OptionSpec], default: str, intro: str = ""
    ) -> str:
        step = self._remembered(title)
        if step is not None and isinstance(step.value, str):
            self.console.take_pending()
            self._record(step)
            return step.value
        remembered = self.memory.get(title)
        if isinstance(remembered, str):
            default = remembered
        lines = self._intro(intro)
        with self.console.released():
            if self.console.tui:
                value, asked = select(
                    self.console, title, _options(options), default, lines, self.header
                )
            else:
                value, asked = choice(self.console, title, _options(options), default, lines)
        self._settle(value, asked, title)
        return value

    def tick(
        self,
        title: str,
        options: Sequence[OptionSpec],
        preticked: list[str],
        intro: str = "",
        exclusive: tuple[str, ...] = (),
        presets: dict[str, tuple[str, list[str]]] | None = None,
    ) -> list[str]:
        step = self._remembered(title)
        if step is not None and isinstance(step.value, list):
            self.console.take_pending()
            self._record(step)
            return list(step.value)
        remembered = self.memory.get(title)
        if isinstance(remembered, list):
            preticked = remembered
        lines = self._intro(intro)
        with self.console.released():
            if self.console.tui:
                value, asked = checklist(
                    self.console,
                    title,
                    _options(options),
                    preticked,
                    lines,
                    exclusive,
                    self.header,
                    presets,
                )
            else:
                value, asked = multi(
                    self.console, title, _options(options), preticked, lines, exclusive
                )
        self._settle(value, asked, title)
        return value

    def text(self, prompt: str) -> str:
        """Free text (a custom chord, a y/N). Recorded so a replay repeats it,
        but never tallied: it is part of the question before it."""
        step = self._remembered(prompt)
        if step is not None and isinstance(step.value, str):
            self.console.take_pending()
            self._record(Step(prompt, step.value, free_text=True))
            return step.value
        self._intro("")
        with self.console.released():
            value = text(self.console, prompt)
        if self.console.interactive:
            self._record(Step(prompt, value, free_text=True))
        return value


def headless() -> bool:
    """A machine with no GUI to configure.

    WSL is never headless -- it drives a Windows GUI. An explicit display says
    no; an SSH session says yes; otherwise a Linux box with no graphical target
    is one.
    """
    if _env("TS_HEADLESS_RESOLVED"):
        return _env("TS_HEADLESS_RESOLVED") in ("1", "yes", "true")
    kind = plat.kind()
    if kind in (plat.WSL, plat.WINDOWS, plat.MACOS):
        return False
    if _env("DISPLAY") or _env("WAYLAND_DISPLAY"):
        return False
    return bool(_env("SSH_CONNECTION") or _env("SSH_TTY"))


def collect(console: Console, ask_terminals: bool = False, ask: Asker | None = None) -> Answers:
    """Every answer, in order. Nothing is written.

    `ask` is passed by `run`, which owns Back/Quit; called bare (the tests, an
    old caller) it behaves exactly as it always did.
    """
    ask = ask if ask is not None else Asker(console)
    bare = headless()

    # ---------------------------------------------------------------- profile
    if _env("TS_PROFILE"):
        profile = _env("TS_PROFILE")
        if profile not in (PROFILE_PROMPT, PROFILE_SHELL, PROFILE_FULL):
            profile = PROFILE_FULL
    elif bare:
        # A headless server has no GUI to configure but does have a shell, and
        # is exactly the machine someone administers. `shell` is the only
        # profile whose questions all still mean something there.
        profile = PROFILE_SHELL
    else:
        console.say()
        console.say("  This is what you would get:")
        console.say()
        _show_prompt(console, store.get("starshipPreset", "terminal-stack"))
        profile = ask.choose(
            "How much of this do you want?",
            [
                (
                    "prompt",
                    "just the prompt",
                    "Starship + a Nerd Font. Your shell config, aliases and terminal are left alone",
                ),
                (
                    "shell",
                    "prompt and terminal",
                    "adds the managed shell/tmux/WezTerm configs and the CLI tools",
                ),
                (
                    "full",
                    "the whole stack",
                    "adds the agent wiring, the Docker services, voice notifications and memory",
                ),
            ],
            PROFILE_FULL,
            "  RECOMMENDATION: full on your own machine - the pieces are individually\n"
            "  switchable afterwards with `tstack config`, and nothing here is hard to undo.\n"
            "  Take prompt on a box that is not yours, or when you came for the prompt.",
        )

    # ------------------------------------------------------------ development
    if profile == PROFILE_PROMPT:
        development = "no"
    elif _env("TS_DEVELOPMENT"):
        # `1` and `0` too: every other TS_* toggle takes them, and `=1` meant "no".
        development = "yes" if _on_off(_env("TS_DEVELOPMENT"), default="yes") == "on" else "no"
    elif bare:
        development = "no"
    else:
        development = ask.choose(
            "Will you write code on this machine?",
            [
                (
                    "yes",
                    "yes, this is a development machine",
                    "git tooling, language runtimes, Python tools, the AI agent CLIs",
                ),
                (
                    "no",
                    "no, I administer it",
                    "monitors, disk and network tools, editors, search - no runtimes, no agents",
                ),
            ],
            "yes",
            "  Only decides which tools are pre-ticked and whether the agent and memory\n"
            "  questions are asked at all. Everything stays individually selectable.",
        )
    app_class = catalog.DEVELOPER if development == "yes" else catalog.SYSADMIN

    # ---------------------------------------------------------------- prompt
    starship = _starship(ask, console)

    # ----------------------------------------------------------------- theme
    theme = _env("TS_THEME") or ask.choose(
        "Theme:",
        [
            ("dark", "dark", "Catppuccin Mocha"),
            ("light", "light", "VS Code Light Modern"),
            ("follow", "follow OS appearance", "WezTerm switches live"),
        ],
        _saved("themeMode", "dark"),
    )

    if profile == PROFILE_PROMPT:
        # What it says: Starship and a Nerd Font, and nothing else touched.
        # Every remaining answer is pinned rather than asked, and the review
        # lists them so that is visible rather than implied.
        # Carry this machine's SAVED answers through, not the dataclass defaults:
        # the bootstrap saves every field, so `apps=[]` and `memory_backend="none"`
        # here wiped the app list and unwired AgentMemory on a configured box.
        return Answers(
            profile=profile,
            development=development,
            app_class=app_class,
            starship=starship,
            theme=theme,
            leader=_saved("leaderChord", "ctrl-backslash"),
            tmux=_saved_tmux(),
            wez_mux=_saved_on_off("weztermMux"),
            wez_restore=_saved_on_off("weztermRestore"),
            atuin=_saved_on_off("atuinEnabled"),
            herdr=_saved_on_off("herdrConfig"),
            apps=store.get("apps", "").split(),
            cc_tts="on" if store.normalise(store.get("ccTtsEnabled", "false")) == "true" else "off",
            cc_tts_message=_saved("ccTtsMessageMode", "template"),
            cc_tts_daemon=_saved_on_off("ccTtsDaemon"),
            memory_backend=_saved("memoryBackend", "none"),
            headroom=_saved_on_off("headroomEnabled"),
            headroom_cursor=_saved("headroomCursorMode", "mcp"),
            caveman=_saved_on_off("cavemanEnabled"),
            agentmemory=_saved_on_off("agentmemoryEnabled"),
            asked=ask.count,
        )

    # ---------------------------------------------------------------- leader
    if _env("TS_LEADER"):
        leader = _env("TS_LEADER")
    elif bare:
        leader = "ctrl-backslash"
    else:
        leader = _leader(ask, console)

    # ------------------------------------------------------------- terminals
    terminals: list[str] = []
    if ask_terminals:
        terminals = _terminals(ask)

    # ------------------------------------------------------- WezTerm settings
    wez_mux = _gui_toggle(
        ask,
        bare,
        "TS_WEZ_MUX",
        "weztermMux",
        "WezTerm multiplexer (keeps panes alive when the GUI dies):",
        [("off", "off", "panes are spawned by the GUI"), ("on", "on", "panes survive a GUI crash")],
        "  RECOMMENDATION: off. Config changes then need `tstack mux restart`,\n"
        "  which kills every pane, and mux panes lose the Claude tint.",
    )
    wez_restore = _gui_toggle(
        ask,
        bare,
        "TS_WEZ_RESTORE",
        "weztermRestore",
        "WezTerm session restore (reopen the last session at startup):",
        [("off", "off", "start clean every time"), ("on", "on", "reopen the last session")],
        "  RECOMMENDATION: off. Panes come back without their processes, and the\n"
        "  autosave means Leader+L still restores on demand.",
    )

    # ----------------------------------------------------------------- atuin
    # Asked even when headless: unlike the WezTerm questions this is a shell
    # binding, and a headless server has a shell. Asked on Windows too, where
    # atuin cannot run (no pwsh target, no Windows package): the saved answer
    # is what the WSL side renders, so it says so rather than implying pwsh.
    atuin_where = (
        "\n  On Windows this affects your WSL shells only; PowerShell keeps PSReadLine."
        if plat.kind() == plat.WINDOWS
        else ""
    )
    atuin = (
        _on_off(_env("TS_ATUIN"))
        if _env("TS_ATUIN")
        else ask.choose(
            "atuin shell history (replaces Ctrl+R):",
            [("off", "off", "keep fzf on Ctrl+R"), ("on", "on", "atuin owns Ctrl+R")],
            _saved("atuinEnabled", "on"),
            "  RECOMMENDATION: on. Ctrl+R searches every shell's history from one\n"
            "  database, with the directory and exit status of each command.\n"
            "  Ctrl+T, Alt+C and Up-arrow are untouched. Nothing syncs anywhere.\n"
            "  Reversible with `tstack config atuin off`." + atuin_where,
        )
    )

    # ------------------------------------------------------------------ apps
    selected = _apps(ask, app_class, bare)

    # ----------------------------------------------------------------- herdr
    herdr = _herdr(ask, selected)

    # ------------------------------------------------------------------- tts
    if profile != PROFILE_FULL:
        # Voice notifications announce what an AGENT is doing. Without the agent
        # wiring there is nothing to announce.
        cc_tts, cc_tts_message, cc_tts_daemon = "off", "template", "off"
    else:
        if _env("TS_CC_TTS"):
            cc_tts = _on_off(_env("TS_CC_TTS"))
        else:
            # PROBED, not guessed. Offering voice where nothing can speak
            # promises silence; defaulting it off on a Mac ignores that `say` is
            # a floor which cannot be missing.
            best, report = probes.voice()
            cc_tts = ask.choose(
                "Agent voice notifications?",
                [
                    ("off", "off", "stay silent"),
                    ("on", "on", "speak on finish, error and questions"),
                ],
                best,
                f"  RECOMMENDATION: {best}. Claude, Cursor and Codex speak when they finish,\n"
                "  hit an error, or need you - so you can leave a long run and be called back.\n"
                "  What can speak here, probed just now:\n" + "\n".join(report) + "\n"
                "  The first reachable engine wins, in that order. Nothing is installed for\n"
                "  you. Turn it off any time with `cctts off`.",
            )
        cc_tts_message = "template"
        cc_tts_daemon = "off"
        if cc_tts == "on":
            cc_tts_message = _env("TS_CC_TTS_MESSAGE") or ask.choose(
                "What should it say when the agent finishes?",
                [
                    ("self", "self", "the agent writes its own line"),
                    ("template", "template", "same fixed sentence every time"),
                    ("hook", "hook", "read the last message out raw"),
                ],
                "self",
            )
            # The tray daemon is a native Windows process, so only a machine
            # with a Windows side can route through it -- which means WSL *and*
            # Windows itself. The port asked on WSL only, so a Windows install
            # pinned this off without asking, then installed the built EXE with
            # -NoStart -NoAutostart: voice on, and nothing in the tray.
            if plat.kind() in (plat.WSL, plat.WINDOWS) and not bare:
                cc_tts_daemon = (
                    _on_off(_env("TS_CC_TTS_DAEMON"))
                    if _env("TS_CC_TTS_DAEMON")
                    else ask.choose(
                        "Route voice notifications through the tray daemon?",
                        [
                            ("off", "Direct EXE playback", ""),
                            ("on", "Tray daemon", "installs now, autostarts at login"),
                        ],
                        "off",
                        "  RECOMMENDATION: off. Direct playback needs nothing running, and is\n"
                        "  what the hooks do on their own. The tray daemon queues and coalesces\n"
                        "  announcements, gives each session its own voice, ducks music while\n"
                        "  it speaks, and puts a mute icon in the tray - for one background\n"
                        "  process started at login. Either way the console-free EXE is built\n"
                        "  and Python is build-time only.\n"
                        "  Reversible with `tstack config tts daemon on|off`.",
                    )
                )

    # ---------------------------------------------------------------- memory
    memory, headroom, agentmemory, caveman = _agents(ask, profile, development, bare)
    headroom_cursor = _saved("headroomCursorMode", "mcp")
    if headroom == "on":
        headroom_cursor = _env("TS_HEADROOM_CURSOR") or ask.choose(
            "Cursor Headroom mode:",
            [
                ("mcp", "MCP only", "recommended for Cursor subscriptions"),
                ("byok", "BYOK proxy", "provider API key required"),
                ("off", "off", ""),
            ],
            _saved("headroomCursorMode", "mcp"),
        )

    # -------------------------------------------------------------- services
    services = _services(ask, profile, bare, headroom, agentmemory)

    return Answers(
        profile=profile,
        development=development,
        app_class=app_class,
        starship=starship,
        leader=leader,
        theme=theme,
        tmux=_saved_tmux(),
        terminals=terminals,
        wez_mux=wez_mux,
        wez_restore=wez_restore,
        atuin=atuin,
        herdr=herdr,
        apps=selected,
        cc_tts=cc_tts,
        cc_tts_message=cc_tts_message,
        cc_tts_daemon=cc_tts_daemon,
        memory_backend=memory,
        headroom=headroom,
        headroom_cursor=headroom_cursor,
        caveman=caveman,
        agentmemory=agentmemory,
        services=services,
        asked=ask.count,
    )


def collect_apps(console: Console, ask: Asker | None = None) -> Answers:
    """Just the tool picker, for `tstack config apps`.

    A whole `collect()` would ask about the leader key and the memory backend to
    answer "which tools", which is the shape of wizard people close. The class is
    INFERRED from what the machine already has rather than asked, because this is
    a re-run: `tstack config apps` on a server should not start by asking whether
    it is a server.
    """
    ask = ask if ask is not None else Asker(console)
    app_class = catalog.saved_class(store.get("apps", "").split())
    selected = _apps(ask, app_class, headless())
    return Answers(app_class=app_class, apps=selected, asked=ask.count)


_CHORD_PROMPT = "Enter chord (mod-key, e.g. ctrl-x, alt-space, ctrl-backslash): "

# A key with no printable spelling is stored BY NAME, because neither sink can
# carry the character itself. chezmoi.toml is written as `key = "<value>"` with
# no escaping, so a backslash corrupts it and every later chezmoi command fails
# to parse -- which is why schema.Setting.validate refuses one. And .wezterm.lua
# emits `key = '<value>'`, where a backslash escapes the closing quote: the
# config dies at startup with
#
#     [string "C:\Users\...\.wezterm.lua"]:291: '}' expected near 'CTRL'
#
# naming neither the chord nor this prompt. Windows hit exactly that -- its
# store is JSON, so `ctrl-\` survived the save and only broke WezTerm.
#
# Typing the symbol is the natural way to answer "enter a chord", so take it and
# spell it, rather than refusing an answer that is not wrong so much as
# unstorable.
_KEY_SPELLINGS = {"\\": "backslash", " ": "space"}


_LEADER_INTRO = """\
The leader is a key you press FIRST, then let go, then press a second key:
  leader then h   split the pane          leader then z   zoom the pane
  leader then t   tab mode                leader then r   reload the config
  leader then w   pick a workspace        leader then Esc cancel
While it is waiting, the cursor turns peach and the tab bar shows LEADER.
Press the leader twice to send the chord itself to the program in the pane.
It applies to WezTerm only. Open WezTerm windows pick up a change within a
second on their own; if one does not, press Ctrl+Shift+R in it.
Change it later with:  tstack config leader <chord>   (e.g. ctrl-a)
Check it with:         tstack doctor   (says if another program holds it)"""


def _leader(ask: Asker, console: Console) -> str:
    """The leader question, re-asked while the answer is a chord another program holds.

    A held chord never reaches WezTerm (tstack/hotkey.py), so taking it would save
    a leader that does nothing. It is marked in the menu and confirmed, never
    refused outright: the user may be about to free it in the other program.
    """
    from .. import hotkey

    def note(chord: str, text_: str) -> str:
        return "TAKEN on this PC by another program" if hotkey.held_elsewhere(chord) else text_

    while True:
        leader = ask.choose(
            "Leader key (WezTerm) - prefix for pane / tab / workspace commands:",
            [
                (
                    "ctrl-backslash",
                    "Ctrl+\\",
                    note("ctrl-backslash", "clashes with no shell or TUI"),
                ),
                ("ctrl-space", "Ctrl+Space", note("ctrl-space", "macOS and PSReadLine claim it")),
                ("ctrl-a", "Ctrl+A", note("ctrl-a", "tmux muscle memory")),
                ("ctrl-b", "Ctrl+B", note("ctrl-b", "tmux default")),
                ("alt-space", "Alt+Space", note("alt-space", "")),
                ("custom", "custom chord", ""),
            ],
            _saved("leaderChord", "ctrl-backslash"),
            intro=_LEADER_INTRO,
        )
        if leader == "custom":
            leader = _chord(console, ask.text(_CHORD_PROMPT))
        if not hotkey.held_elsewhere(leader) or not console.interactive:
            return leader
        console.say()
        for line in hotkey.advice(leader):
            console.say(f"  {line}")
        reply = (ask.text(f"  Keep {hotkey.label(leader)} anyway? [y/N]: ") or "").lower()
        if reply in ("y", "yes"):
            return leader


def _spell(part: str) -> str:
    """One chord segment, by name where it has one. `or " "` rather than
    stripping the whole answer first: the key may BE a space, and
    `"alt- ".strip()` loses it."""
    stripped = part.strip()
    return _KEY_SPELLINGS.get(stripped or " ", stripped)


def _chord(console: Console, typed: str) -> str:
    """A typed leader chord, spelled so that both sinks can carry it."""
    for _ in range(3):
        if not typed.strip():
            break
        chord = "-".join(_spell(p) for p in typed.split("-"))
        why = schema.BY_KEY["leaderChord"].validate(chord)
        if not why and "'" in chord:
            # Not refused by the store, but it closes the Lua string just as a
            # backslash does. There is no phys: name for it, so re-ask.
            why = "leaderChord cannot contain a single quote"
        if not why:
            return chord
        console.say(f"  {why}")
        typed = text(console, _CHORD_PROMPT)
    return "ctrl-backslash"


def _saved(key: str, default: str) -> str:
    """This machine's saved answer, else the fresh-install default.

    Every question's default used to be the FRESH-INSTALL value, so a re-run of
    the questionnaire (`tstack reinstall`, `tstack config wizard`) that pressed
    Enter at each prompt reset the theme, the leader, atuin, herdr, the memory
    backend and the rest to stock. The bootstraps then save what the wizard
    returns, unconditionally.
    """
    value = store.get(key, "")
    return value if value else default


def _saved_on_off(key: str, default: str = "off") -> str:
    return _on_off(_saved(key, default), default=default)


def _saved_tmux() -> str:
    """Never asked, but a re-run must not silently reset it.

    This used to be a bare `${TS_TMUX:-ctrl-b}`, so any machine whose prefix had
    been changed had it forced back by the next reconfigure.

    The FALLBACK is distro-aware. Omarchy's own tmux config uses C-Space, and
    herdr -- the tmux replacement in its base package set -- mirrors it
    deliberately: /usr/share/omarchy/config/herdr/config.toml says so in its
    header and uses ctrl+space too. Defaulting to ctrl-b there would silently
    desynchronise the two, so a machine that never answers the question keeps
    the desktop it already has. C-b still works: the rendered config keeps it as
    `prefix2`.
    """
    default = "ctrl-space" if plat.is_omarchy() else "ctrl-b"
    return _env("TS_TMUX") or store.get("tmuxPrefix", "") or default


def _show_prompt(console: Console, preset: str) -> None:
    from .. import choices

    rendered = choices.preview(choices.STARSHIP, preset)
    for line in (rendered or "  (starship is not installed yet)").splitlines():
        console.say(line)


def _starship(ask: Asker, console: Console) -> str:
    """Which prompt. Asked on every scope -- it is the one thing all three have
    in common, and on `prompt` it is very nearly the whole install.

    Returns the current value untouched when starship is not installed, which on
    a fresh machine it is not: the bootstrap installs it after this runs. That
    path does not tally as asked, because nothing was rendered.
    """
    from .. import choices

    current = store.get("starshipPreset", "terminal-stack")
    if _env("TS_STARSHIP_PRESET"):
        return _env("TS_STARSHIP_PRESET")
    offered = choices.options(choices.STARSHIP)
    if len(offered) <= 1:
        return current
    if console.tui:
        # One preview at a time, for the highlighted row, instead of every
        # preset scrolled past before the question.
        return ask.choose(
            "Which prompt?",
            [
                Option(
                    o.value,
                    o.value,
                    o.note,
                    preview=choices.preview(choices.STARSHIP, o.value) or "",
                )
                for o in offered
            ],
            current,
            "  Arrow through them: each one is rendered below as you go.",
        )
    console.say()
    console.say("  Every prompt, rendered here so you can see them:")
    for option in offered:
        console.say(f"    {option.value}")
        _show_prompt(console, option.value)
    return ask.choose(
        "Which prompt?",
        [(o.value, o.value, o.note) for o in offered],
        current,
    )


def _gui_toggle(
    ask: Asker,
    bare: bool,
    env: str,
    key: str,
    title: str,
    options: list[tuple[str, str, str]],
    intro: str,
) -> str:
    """A WezTerm setting. Skipped on a headless server, which has no GUI."""
    if _env(env):
        return _on_off(_env(env))
    if bare:
        return _saved_on_off(key)
    return ask.choose(title, options, _saved_on_off(key), intro)


def _herdr(ask: Asker, selected: list[str]) -> str:
    """Whether the stack manages herdr's config. PROBED, never guessed.

    Asked only when there is a herdr to configure: already on PATH, or ticked in
    the app picker moments ago. A machine with no herdr answering a question
    about herdr's config file is the noise every skipped question here exists to
    avoid, and the answer would be "off" either way.

    Asked when headless, unlike the WezTerm toggles. herdr is a multiplexer, not
    a GUI -- a server reached over ssh is exactly where one earns its keep.

    Not the same question as "install herdr", which the app picker already asked.
    This one is only about the config file, so a machine can run herdr with its
    own untouched config and that is a supported answer rather than an oversight.
    """
    if _env("TS_HERDR"):
        return _on_off(_env("TS_HERDR"))
    installed = shutil.which("herdr") is not None
    if not installed and "herdr" not in selected:
        return "off"
    return ask.choose(
        "Manage herdr's config (the terminal multiplexer for coding agents):",
        [
            ("off", "off", "herdr's config stays entirely yours"),
            ("on", "on", "the stack sets one key: the theme"),
        ],
        _saved("herdrConfig", "on"),
        "  RECOMMENDATION: on. The stack sets exactly one key, [theme] name =\n"
        '  "terminal", so herdr uses the palette your terminal already has in\n'
        "  dark, light and follow alike. Every other line of that file is left\n"
        "  untouched, and a backup is taken before the first write.\n"
        "  Reversible with `tstack config herdr off`, which restores it.",
    )


def _terminals(ask: Asker) -> list[str]:
    """Which terminal emulator, as a tick-list.

    The two WezTerm channels are exclusive: they install to the same place and
    cannot coexist. Ghostty is not in that group, which is the bug the collapse
    guard exists for.
    """
    if _env("TS_TERMINALS"):
        raw = _env("TS_TERMINALS").lower()
        if raw in ("none", "skip"):
            return []
        wanted = [t.strip() for t in raw.split(",") if t.strip()]
        return ["wezterm-nightly" if t == "wezterm" else t for t in wanted]
    if _env("TS_WEZTERM"):
        legacy = _env("TS_WEZTERM").lower()
        if legacy in ("skip", "none"):
            return []
        return ["wezterm-stable" if legacy == "stable" else "wezterm-nightly"]
    options = [
        ("wezterm-nightly", "WezTerm nightly", "current builds; what this stack configures"),
        ("wezterm-stable", "WezTerm stable", "20240203 - upstream has not cut one since"),
    ]
    # Ghostty is a macOS row. Windows has no Ghostty this stack configures, and
    # a headless Linux host has no GUI at all -- offering it there would take an
    # answer and then do nothing with it.
    if plat.kind() == plat.MACOS:
        options.append(("ghostty", "Ghostty", "GPU-accelerated, platform-native UI"))
    return ask.tick(
        "Terminal emulator:",
        options,
        ["wezterm-nightly"],
        "  Nothing installs unless you tick it, and neither channel ever upgrades\n"
        "  on its own. Ticking both WezTerm rows installs nightly.",
        exclusive=TERMINAL_GROUP,
    )


def _apps(ask: Asker, app_class: str, bare: bool = False) -> list[str]:
    """The CLI tool picker: a whole-set answer, then optionally per-tool.

    A headless machine is never offered the desktop apps: there is nothing to
    run a GUI on, and the installer would only skip them.
    """
    here = plat.kind()
    available = [
        a
        for a in catalog.catalog()
        if a.installable(here) and not (bare and a.group == DESKTOP_GROUP)
    ]
    if not available:
        # A clone with no apps.conf, or one this platform can install nothing
        # from. Answering "recommended" with silence is the silently-dropped-tool
        # failure this repo keeps being bitten by, so it says so.
        ask.console.say(
            "  !! the app catalog is empty (bootstrap/apps.conf missing?) - no tools offered"
        )
        return []
    pretick = [a.id for a in available if a.in_class(app_class)]

    if _env("TS_APPS"):
        raw = _env("TS_APPS").lower()
        if raw == "recommended":
            return pretick
        if raw == "all":
            return [a.id for a in available]
        if raw in ("none", ""):
            return []
        # Commas OR whitespace. `tstack update` hands its pending list over
        # space-separated (the shell's own list form), and a comma-only split
        # read "lazygit fnm pipx" as one unknown id: "y" to "install them now?"
        # then installed nothing and said no apps were selected.
        wanted = {t for t in re.split(r"[,\s]+", raw) if t}
        return [a.id for a in available if a.id in wanted]

    saved = store.get("apps", "").split()
    if ask.console.tui:
        return _apps_tui(ask, available, pretick, saved, app_class)
    options = (
        [
            (
                "keep",
                "keep this machine's current selection",
                f"{len(saved)} tools already chosen here",
            ),
        ]
        if saved
        else []
    )
    options += [
        ("recommended", "install the recommended set", f"the {app_class} set for this machine"),
        ("all", "install everything", f"{len(available)} tools"),
        ("groups", "choose whole groups", ", ".join(catalog.groups())),
        ("customize", "choose individual tools", ""),
        ("none", "skip all optional apps", ""),
    ]
    answer = ask.choose(
        "Optional CLI tools (font, Starship, chezmoi, zsh - always installed):",
        options,
        "keep" if saved else "recommended",
    )
    if answer == "keep":
        return saved
    if answer == "all":
        return [a.id for a in available]
    if answer == "none":
        return []
    if answer == "groups":
        return _pick_groups(ask, available, pretick)
    if answer == "customize":
        return _pick_items(ask, available, pretick)
    return pretick


def _apps_tui(
    ask: Asker,
    available: list[catalog.App],
    pretick: list[str],
    saved: list[str],
    app_class: str,
) -> list[str]:
    """Arrow-key mode: three tick-lists instead of a menu of menus.

    Every tool is visible and individually tickable on one screen, grouped; the
    agent CLIs and the desktop apps get a step each, because they are what
    people come to an installer to choose. Pre-ticked with this machine's saved
    selection, or the recommended set on a fresh one.
    """
    base = set(saved) if saved else set(pretick)
    tools = [a for a in available if a.group not in (AI_GROUP, DESKTOP_GROUP)]
    agents = [a for a in available if a.group == AI_GROUP]
    desktop = [a for a in available if a.group == DESKTOP_GROUP]

    def rows(members: list[catalog.App], grouped: bool) -> list[OptionSpec]:
        return [
            Option(a.id, a.id, a.description, group=catalog_group_desc(a.group) if grouped else "")
            for a in members
        ]

    def presets(members: list[catalog.App]) -> dict[str, tuple[str, list[str]]]:
        ids = {a.id for a in members}
        out = {"r": ("recommended", [i for i in pretick if i in ids])}
        if saved:
            out["k"] = ("keep saved", [i for i in saved if i in ids])
        return out

    chosen: set[str] = set()
    if tools:
        chosen |= set(
            ask.tick(
                "Command-line tools",
                rows(tools, grouped=True),
                [a.id for a in tools if a.id in base],
                "  The font, Starship, chezmoi and zsh are always installed; this is the rest.\n"
                f"  r resets to the recommended set for a {app_class} machine"
                + ("; k restores what this machine has saved." if saved else "."),
                presets=presets(tools),
            )
        )
    if agents:
        chosen |= set(
            ask.tick(
                "AI coding agents (command-line)",
                rows(agents, grouped=False),
                [a.id for a in agents if a.id in base],
                "  Each comes from its vendor's own installer, never a package manager.\n"
                "  codex, gemini and pi need Node: keep fnm ticked on the previous screen.",
                presets=presets(agents),
            )
        )
    if desktop:
        chosen |= set(
            ask.tick(
                "Desktop agent apps",
                rows(desktop, grouped=False),
                [a.id for a in desktop if a.id in saved],
                "  GUI workspaces for running coding agents side by side. None is ticked\n"
                "  by default. A copy you installed yourself is detected and left alone.\n"
                "  macOS: Homebrew casks.  Windows: winget, or herdr.dev's installer.\n"
                "  Linux: herdr.dev's installer, and a .deb (Ubuntu) or AppImage (Arch).",
            )
        )
    return [a.id for a in available if a.id in chosen]


def _pick_groups(ask: Asker, available: list[catalog.App], pretick: list[str]) -> list[str]:
    groups = [g for g in catalog.groups() if any(a.group == g for a in available)]
    chosen = ask.tick(
        "Which groups?",
        [(g, g, ", ".join(a.id for a in available if a.group == g)[:60]) for g in groups],
        [g for g in groups if any(a.id in pretick for a in available if a.group == g)],
    )
    return [a.id for a in available if a.group in chosen]


def _pick_items(ask: Asker, available: list[catalog.App], pretick: list[str]) -> list[str]:
    """Group by group, so thirty consecutive prompts becomes a handful of
    tick-lists."""
    selected: list[str] = []
    for group in catalog.groups():
        members = [a for a in available if a.group == group]
        if not members:
            continue
        selected += ask.tick(
            f"  {catalog_group_desc(group)}:",
            [(a.id, a.id, a.description) for a in members],
            pretick,
        )
    return selected


def catalog_group_desc(group: str) -> str:
    return {
        "shell": "shell essentials",
        "search": "search and find",
        "disk": "disk usage",
        "system": "system monitors",
        "network": "network",
        "git": "git tooling",
        "editors": "editors and readers",
        "runtimes": "language runtimes",
        "python": "Python tooling",
        "ai": "AI coding agents",
        "desktop": "desktop agent apps",
        "models": "local model sizing",
    }.get(group, group)


def _agents(ask: Asker, profile: str, development: str, bare: bool) -> tuple[str, str, str, str]:
    """The memory backend and caveman. Returns (memory, headroom, agentmemory, caveman).

    ONE question, not two. Headroom and AgentMemory used to be asked separately,
    which made "both memory systems on" a single keystroke away -- and they do
    the same job, so two stores means two half-filled ones.
    """
    if profile != PROFILE_FULL or development != "yes" or bare:
        # Nothing is asked here, so nothing may be RESET here either: a headless
        # or shell-profile re-run keeps what the machine already has.
        memory = _env("TS_MEMORY_BACKEND") or _saved("memoryBackend", "none")
        if _env("TS_AGENTMEMORY"):
            agentmemory = _on_off(_env("TS_AGENTMEMORY"))
            if agentmemory == "on":
                memory = "agentmemory"
        else:
            agentmemory = "on" if memory == "agentmemory" else "off"
        headroom = (
            _on_off(_env("TS_HEADROOM"))
            if _env("TS_HEADROOM")
            else _saved_on_off("headroomEnabled")
        )
        caveman = (
            _on_off(_env("TS_CAVEMAN")) if _env("TS_CAVEMAN") else _saved_on_off("cavemanEnabled")
        )
        return (memory, headroom, agentmemory, caveman)

    if _env("TS_MEMORY_BACKEND"):
        memory = _env("TS_MEMORY_BACKEND")
    elif _env("TS_AGENTMEMORY") or _env("TS_HEADROOM"):
        # A pre-merge unattended install only knew the two booleans. Honour them
        # rather than ignoring them, so an old script cannot land on a
        # combination this menu will not offer.
        memory = "agentmemory" if _on_off(_env("TS_AGENTMEMORY")) == "on" else "none"
    else:
        _am_up, am_line = probes.agentmemory()
        _hr_up, hr_line = probes.headroom()
        memory = ask.choose(
            "Memory and compression:",
            [
                ("agentmemory", "AgentMemory remembers, Headroom compresses", "the default"),
                ("headroom", "Headroom does both", "AgentMemory is not installed"),
                ("none", "Headroom compresses only", "no memory at all"),
                ("off", "Neither", "no proxy, no memory"),
            ],
            _saved("memoryBackend", "agentmemory")
            if _saved_on_off("headroomEnabled") == "on" or not store.get("memoryBackend", "")
            else "off",
            "  RECOMMENDATION: AgentMemory remembers, Headroom compresses.\n"
            "  Only ONE memory system runs. They overlap, and two stores means two\n"
            "  half-filled ones with no way to tell which holds the answer you want.\n"
            f"{am_line}\n{hr_line}\n"
            "  Compression is not a memory feature and is unaffected by this. Headroom's\n"
            "  memory additionally runs Qdrant and Neo4j (about 940 MB); the other\n"
            "  answers never pull those images.",
        )
    mapping = {
        "agentmemory": ("agentmemory", "on", "on"),
        "headroom": ("headroom", "on", "off"),
        "none": ("none", "on", "off"),
    }
    memory, headroom, agentmemory = mapping.get(memory, ("none", "off", "off"))
    if _env("TS_HEADROOM"):
        # An explicit answer beats the mapping: TS_HEADROOM=off TS_AGENTMEMORY=on
        # used to come out with headroom on.
        headroom = _on_off(_env("TS_HEADROOM"))

    caveman = _env("TS_CAVEMAN") or ask.choose(
        "Caveman terse output for all projects?",
        [
            ("off", "off", "configure later with tstack config agents"),
            ("on", "on", "installs the pinned user-scope plugin/skill"),
        ],
        _saved_on_off("cavemanEnabled"),
    )
    return (memory, headroom, agentmemory, _on_off(caveman))


def _services(ask: Asker, profile: str, bare: bool, headroom: str, agentmemory: str) -> str:
    """Whether the install STARTS the containers the answers above just chose.

    Every other question here records an intent. This is the only one that pulls
    gigabytes and starts long-lived processes, which is why it is its own
    question and why it defaults to off.

    What is NOT behind it: `tstack services bootstrap`. That needs no engine, no
    network and no consent -- it writes the .env files and generates
    HEADROOM_PROXY_TOKEN, without which headroom's compose does not even parse.
    The installers run it either way, and that alone is what fixes a machine
    whose agent wiring reported "proxy token unavailable" on every step.

    The gate is "is any stack enabled", NOT "was a backend chosen". The third
    memory answer -- Headroom compresses only -- is backend `none` with
    headroomEnabled=on, and there is a real container to start; gating on the
    backend would leave a compression-only user's proxy permanently down.

    Two deliberate deviations from the house style, both worth stating:

      * The probe changes the REPORT, never the DEFAULT. Elsewhere here a
        reachable service moves the recommendation; a healthy engine does not
        make a 1-2 GB download cheaper.
      * TS_ASSUME_YES is NOT read. It means "take every default", the default is
        off, and tests/parity/run.sh passes it to every container -- so reading
        it as consent would have an unattended install pull images in CI. Same
        rule and the same reason as tstack/commands/ui.py's install offer.
    """
    if _env("TS_SERVICES"):
        return _on_off(_env("TS_SERVICES"))
    if profile != PROFILE_FULL or bare:
        return "off"
    if headroom != "on" and agentmemory != "on":
        # "Neither" enabled no stack at all. There is nothing to bring up.
        return "off"
    _up, report = probes.container_engine()
    return ask.choose(
        "Start the local services now?",
        [
            ("off", "no", "set them up now, start them when you want"),
            ("on", "yes", "pull the images and bring the stacks up"),
        ],
        "off",
        "  RECOMMENDATION: no, unless you have the bandwidth and twenty minutes.\n"
        "  The .env files, the generated secrets and the named volumes are written\n"
        "  either way - that half needs no engine and no network, and it is what\n"
        "  makes this machine configured rather than half-configured.\n"
        "  Only the IMAGES are in question: 1-2 GB, and about 940 MB more if you\n"
        "  chose Headroom's memory, which adds Qdrant and Neo4j.\n"
        "  The container engine here, probed just now:\n" + "\n".join(report) + "\n"
        "  Either way: `tstack services up` starts them later, and\n"
        "  `tstack services doctor` says what is missing.",
    )


def review(console: Console, answers: Answers) -> None:
    """Print every answer before anything is written or installed.

    A review that silently omits what it decided for you is how "I didn't choose
    that" happens, which is why the `prompt` scope lists its pinned answers too.
    """
    theme_label = {
        "dark": "dark (Catppuccin Mocha)",
        "light": "light (VS Code Light Modern)",
        "follow": "follow OS appearance",
    }.get(answers.theme, answers.theme)
    console.say()
    console.say("==> Review")
    console.say(f"    Scope            {answers.profile}")
    console.say(f"    Prompt           {answers.starship}")
    if answers.profile == PROFILE_PROMPT:
        console.say(f"    Theme            {theme_label}")
        console.say("    Everything else  left alone (no tools, no configs, no agents)")
        return
    console.say(f"    For development  {answers.development}")
    console.say(f"    Leader           {answers.leader}")
    console.say(f"    Theme            {theme_label}")
    if answers.terminals:
        console.say(f"    Terminals        {' '.join(answers.terminals)}")
    console.say(f"    WezTerm mux      {answers.wez_mux}")
    console.say(f"    Session restore  {answers.wez_restore}")
    console.say(f"    atuin (Ctrl+R)   {answers.atuin}")
    console.say(f"    herdr config     {answers.herdr}")
    console.say(f"    tmux prefix      {answers.tmux}")
    console.say(f"    Apps             {' '.join(answers.apps) or '<none>'}")
    console.say(f"    Agent voice      {answers.cc_tts}")
    if answers.cc_tts == "on":
        console.say(f"    Voice says       {answers.cc_tts_message}")
        console.say(f"    TTS daemon       {answers.cc_tts_daemon}")
    console.say(f"    Headroom         {answers.headroom} (Cursor: {answers.headroom_cursor})")
    console.say(f"    Caveman          {answers.caveman}")
    console.say(f"    Memory backend   {answers.memory_backend}")
    console.say(f"    Start services   {answers.services}")


def confirm(
    console: Console, answers: Answers, assume_yes: bool, *, preview: bool = False
) -> Answers | None:
    """Show the review and let it be edited or abandoned. None means quit.

    Skipped when nothing was asked: a fully env-driven run has nothing to review
    and must not block on a tty nobody is watching.

    `preview` is a bare `tstack wizard`, which saves nothing. Its prompt must not
    say "Proceed": that reads as "apply", and a user who pressed it watched the
    command return to the shell with nothing changed and no word as to why.
    """
    while True:
        review(console, answers)
        if assume_yes or answers.asked == 0 or not console.interactive:
            console.say("  (nothing to review - proceeding)")
            return answers
        if preview:
            console.say("  This was a PREVIEW. Pressing Enter saves nothing and changes nothing.")
        prompt = (
            "  [D]one / [e]dit answers / [q]uit: "
            if preview
            else "  [P]roceed (save and apply) / [e]dit answers / [q]uit: "
        )
        reply = (text(console, prompt) or "").lower()
        if reply in ("", "p", "proceed", "y", "yes", "d", "done"):
            return answers
        if reply in ("q", "quit"):
            console.say("==> quit - nothing was installed or changed.")
            return None
        if reply in ("e", "edit"):
            fresh = collect(console, ask_terminals=bool(answers.terminals))
            answers = replace(fresh, asked=fresh.asked or answers.asked)
            continue
        console.say(
            f"  '{reply}' is not one of the choices - Enter to "
            f"{'finish' if preview else 'proceed'}, 'e' to edit, 'q' to quit."
        )


def _summary(value: str | list[str]) -> str:
    if isinstance(value, list):
        return " ".join(value) if value else "<none>"
    return value or "<empty>"


def _last_question(log: list[Step]) -> int:
    """Index of the last real question in `log` (free text belongs to the
    question before it), or 0 when there is none."""
    for index in range(len(log) - 1, -1, -1):
        if not log[index].free_text:
            return index
    return 0


def _review_tui(
    console: Console, answers: Answers, log: list[Step], preview: bool, header: str
) -> str | int:
    """The review as a menu. Returns "proceed", "quit", "back", or the index in
    `log` of the step to change."""
    console.hold(True)
    review(console, answers)
    console.hold(False)
    summary = tuple(console.take_pending())
    proceed = (
        ("proceed", "Done", "this is a preview - nothing is saved")
        if preview
        else ("proceed", "Proceed", "save these answers and install")
    )
    while True:
        picked, _ = select(
            console,
            "Review",
            [
                Option(*proceed),
                Option("change", "Change an answer", "jump to any step, then come back here"),
                Option("quit", "Quit", "nothing is installed or changed"),
            ],
            "proceed",
            summary,
            header,
        )
        if picked in ("proceed", BACK):
            return "proceed" if picked == "proceed" else "back"
        if picked in ("quit", QUIT):
            return "quit"
        steps = [i for i, step in enumerate(log) if not step.free_text]
        if not steps:
            continue
        target, _ = select(
            console,
            "Change which answer?",
            [
                Option(str(i), log[i].title.strip().rstrip(":"), _summary(log[i].value)[:60])
                for i in steps
            ],
            str(steps[0]),
            ("  The step you pick is asked again; everything else keeps its answer.",),
            header,
        )
        if target in (BACK, QUIT):
            continue
        return int(target)


def run(
    console: Console,
    *,
    ask_terminals: bool = False,
    assume_yes: bool = False,
    preview: bool = False,
    review_screen: bool = True,
    only_apps: bool = False,
) -> Answers | None:
    """The questionnaire with Back, Quit and the review. None means quit.

    Drives `collect` (or `collect_apps`) through an Asker that records every
    answer; a Back re-runs it replaying the answers before the target step. In
    plain-prompt mode the review is `confirm`, unchanged; in arrow-key mode it
    is a menu that can jump to any step.
    """
    replay: list[Step] = []
    memory: dict[str, str | list[str]] = {}
    autofill = False
    banner = "terminal-stack setup" + ("  (preview - nothing is saved)" if preview else "")
    while True:
        ask = Asker(console, replay=replay, memory=memory, autofill=autofill, banner=banner)
        console.hold(True)
        try:
            if only_apps:
                answers = collect_apps(console, ask=ask)
            else:
                answers = collect(console, ask_terminals=ask_terminals, ask=ask)
        except GoBack:
            console.hold(False)
            console.take_pending()
            replay, memory, autofill = ask.log[: _last_question(ask.log)], ask.memory, False
            continue
        except QuitWizard:
            console.hold(False)
            console.take_pending()
            console.say("==> quit - nothing was installed or changed.")
            return None
        console.hold(False)
        console.flush()
        if not review_screen or only_apps:
            return answers
        if not console.tui:
            return confirm(console, answers, assume_yes, preview=preview)
        if assume_yes or answers.asked == 0:
            review(console, answers)
            return answers
        verdict = _review_tui(console, answers, ask.log, preview, ask.header)
        if verdict == "proceed":
            # The final frame is gone with the menu; leave the answers on screen.
            review(console, answers)
            return answers
        if verdict == "quit":
            console.say("==> quit - nothing was installed or changed.")
            return None
        memory = ask.memory
        if verdict == "back":
            replay, autofill = ask.log[: _last_question(ask.log)], False
        else:
            assert isinstance(verdict, int)
            replay, autofill = ask.log[:verdict], True
