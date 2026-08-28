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
from dataclasses import dataclass, field, replace

from .. import apps as catalog
from .. import platform as plat
from .. import store
from .console import Console
from .prompts import Option, choice, multi, text

# Questions, in the order they are asked.
PROFILE_PROMPT, PROFILE_SHELL, PROFILE_FULL = "prompt", "shell", "full"

TERMINAL_GROUP = ("wezterm-nightly", "wezterm-stable")


@dataclass(frozen=True)
class Answers:
    """Everything the wizard collected. The four bootstraps persist it; this
    module never writes."""

    profile: str = PROFILE_FULL
    development: str = "yes"
    app_class: str = catalog.DEVELOPER
    starship: str = "terminal-stack"
    leader: str = "ctrl-space"
    theme: str = "dark"
    tmux: str = "ctrl-b"
    terminals: list[str] = field(default_factory=list)
    wez_mux: str = "off"
    wez_restore: str = "off"
    atuin: str = "off"
    apps: list[str] = field(default_factory=list)
    cc_tts: str = "off"
    cc_tts_message: str = "template"
    cc_tts_daemon: str = "off"
    memory_backend: str = "none"
    headroom: str = "off"
    headroom_cursor: str = "mcp"
    caveman: str = "off"
    agentmemory: str = "off"
    asked: int = 0


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _on_off(value: str, *, default: str = "off") -> str:
    if value.lower() in ("on", "yes", "true", "1"):
        return "on"
    if value.lower() in ("off", "no", "false", "0"):
        return "off"
    return default


@dataclass
class Asker:
    """Wraps the primitives so every question tallies `asked` the same way."""

    console: Console
    count: int = 0

    def choose(
        self, title: str, options: list[tuple[str, str, str]], default: str, intro: str = ""
    ) -> str:
        value, asked = choice(
            self.console,
            title,
            [Option(*o) for o in options],
            default,
            tuple(intro.splitlines()) if intro else (),
        )
        self.count += 1 if asked else 0
        return value

    def tick(
        self,
        title: str,
        options: list[tuple[str, str, str]],
        preticked: list[str],
        intro: str = "",
        exclusive: tuple[str, ...] = (),
    ) -> list[str]:
        value, asked = multi(
            self.console,
            title,
            [Option(*o) for o in options],
            preticked,
            tuple(intro.splitlines()) if intro else (),
            exclusive,
        )
        self.count += 1 if asked else 0
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


def collect(console: Console, ask_terminals: bool = False) -> Answers:
    """Every answer, in order. Nothing is written."""
    ask = Asker(console)
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
        development = "yes" if _env("TS_DEVELOPMENT").lower() in ("yes", "on", "true") else "no"
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
        "dark",
    )

    if profile == PROFILE_PROMPT:
        # What it says: Starship and a Nerd Font, and nothing else touched.
        # Every remaining answer is pinned rather than asked, and the review
        # lists them so that is visible rather than implied.
        return Answers(
            profile=profile,
            development=development,
            app_class=app_class,
            starship=starship,
            theme=theme,
            tmux=_saved_tmux(),
            asked=ask.count,
        )

    # ---------------------------------------------------------------- leader
    if _env("TS_LEADER"):
        leader = _env("TS_LEADER")
    elif bare:
        leader = "ctrl-space"
    else:
        leader = ask.choose(
            "Leader key (WezTerm) - prefix for pane / tab / workspace commands:",
            [
                ("ctrl-space", "Ctrl+Space", ""),
                ("ctrl-a", "Ctrl+A", "tmux muscle memory"),
                ("ctrl-b", "Ctrl+B", "tmux default"),
                ("alt-space", "Alt+Space", ""),
                ("custom", "custom chord", ""),
            ],
            "ctrl-space",
        )
        if leader == "custom":
            leader = (
                text(console, "Enter chord (mod-key, e.g. ctrl-x or alt-space): ") or "ctrl-space"
            )

    # ------------------------------------------------------------- terminals
    terminals: list[str] = []
    if ask_terminals:
        terminals = _terminals(ask)

    # ------------------------------------------------------- WezTerm settings
    wez_mux = _gui_toggle(
        ask,
        bare,
        "TS_WEZ_MUX",
        "WezTerm multiplexer (keeps panes alive when the GUI dies):",
        [("off", "off", "panes are spawned by the GUI"), ("on", "on", "panes survive a GUI crash")],
        "  RECOMMENDATION: off. Config changes then need `tstack mux restart`,\n"
        "  which kills every pane, and mux panes lose the Claude tint.",
    )
    wez_restore = _gui_toggle(
        ask,
        bare,
        "TS_WEZ_RESTORE",
        "WezTerm session restore (reopen the last session at startup):",
        [("off", "off", "start clean every time"), ("on", "on", "reopen the last session")],
        "  RECOMMENDATION: off. Panes come back without their processes, and the\n"
        "  autosave means Leader+L still restores on demand.",
    )

    # ----------------------------------------------------------------- atuin
    # Asked even when headless: unlike the WezTerm questions this is a shell
    # binding, and a headless server has a shell.
    atuin = (
        _on_off(_env("TS_ATUIN"))
        if _env("TS_ATUIN")
        else ask.choose(
            "atuin shell history (replaces Ctrl+R):",
            [("off", "off", "keep fzf on Ctrl+R"), ("on", "on", "atuin owns Ctrl+R")],
            "on",
            "  RECOMMENDATION: on. Ctrl+R searches every shell's history from one\n"
            "  database, with the directory and exit status of each command.\n"
            "  Ctrl+T, Alt+C and Up-arrow are untouched. Nothing syncs anywhere.\n"
            "  Reversible with `tstack config atuin off`.",
        )
    )

    # ------------------------------------------------------------------ apps
    selected = _apps(ask, app_class)

    # ------------------------------------------------------------------- tts
    if profile != PROFILE_FULL:
        # Voice notifications announce what an AGENT is doing. Without the agent
        # wiring there is nothing to announce.
        cc_tts, cc_tts_message, cc_tts_daemon = "off", "template", "off"
    else:
        cc_tts = (
            _on_off(_env("TS_CC_TTS"))
            if _env("TS_CC_TTS")
            else ask.choose(
                "Agent voice notifications?",
                [
                    ("off", "off", "stay silent"),
                    ("on", "on", "speak on finish, error and questions"),
                ],
                "off",
            )
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
            # with a Windows side can route through it.
            if plat.kind() == plat.WSL and not bare:
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
                    )
                )

    # ---------------------------------------------------------------- memory
    memory, headroom, agentmemory, caveman = _agents(ask, profile, development, bare)
    headroom_cursor = "mcp"
    if headroom == "on":
        headroom_cursor = _env("TS_HEADROOM_CURSOR") or ask.choose(
            "Cursor Headroom mode:",
            [
                ("mcp", "MCP only", "recommended for Cursor subscriptions"),
                ("byok", "BYOK proxy", "provider API key required"),
                ("off", "off", ""),
            ],
            "mcp",
        )

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
        apps=selected,
        cc_tts=cc_tts,
        cc_tts_message=cc_tts_message,
        cc_tts_daemon=cc_tts_daemon,
        memory_backend=memory,
        headroom=headroom,
        headroom_cursor=headroom_cursor,
        caveman=caveman,
        agentmemory=agentmemory,
        asked=ask.count,
    )


def _saved_tmux() -> str:
    """Never asked, but a re-run must not silently reset it.

    This used to be a bare `${TS_TMUX:-ctrl-b}`, so any machine whose prefix had
    been changed had it forced back by the next reconfigure.
    """
    return _env("TS_TMUX") or store.get("tmuxPrefix", "") or "ctrl-b"


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
    title: str,
    options: list[tuple[str, str, str]],
    intro: str,
) -> str:
    """A WezTerm setting. Skipped on a headless server, which has no GUI."""
    if _env(env):
        return _on_off(_env(env))
    if bare:
        return "off"
    return ask.choose(title, options, "off", intro)


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
        ("ghostty", "Ghostty", "GPU-accelerated, platform-native UI"),
    ]
    if plat.kind() == plat.WINDOWS:
        options[2] = (
            "ghostty",
            "Ghostty",
            "via noctty/winghostty; you install it, we configure it",
        )
    return ask.tick(
        "Terminal emulator:",
        options,
        ["wezterm-nightly"],
        "  Nothing installs unless you tick it, and neither channel ever upgrades\n"
        "  on its own. Ticking both WezTerm rows installs nightly.",
        exclusive=TERMINAL_GROUP,
    )


def _apps(ask: Asker, app_class: str) -> list[str]:
    """The CLI tool picker: a whole-set answer, then optionally per-tool."""
    here = plat.kind()
    available = [a for a in catalog.catalog() if a.installable(here)]
    pretick = [a.id for a in available if a.in_class(app_class)]

    if _env("TS_APPS"):
        raw = _env("TS_APPS").lower()
        if raw == "recommended":
            return pretick
        if raw == "all":
            return [a.id for a in available]
        if raw in ("none", ""):
            return []
        wanted = {t.strip() for t in raw.split(",") if t.strip()}
        return [a.id for a in available if a.id in wanted]

    saved = store.get("apps", "").split()
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
        "models": "local model sizing",
    }.get(group, group)


def _agents(ask: Asker, profile: str, development: str, bare: bool) -> tuple[str, str, str, str]:
    """The memory backend and caveman. Returns (memory, headroom, agentmemory, caveman).

    ONE question, not two. Headroom and AgentMemory used to be asked separately,
    which made "both memory systems on" a single keystroke away -- and they do
    the same job, so two stores means two half-filled ones.
    """
    if profile != PROFILE_FULL or development != "yes" or bare:
        memory = _env("TS_MEMORY_BACKEND") or "none"
        agentmemory = _on_off(_env("TS_AGENTMEMORY"))
        if agentmemory == "on":
            memory = "agentmemory"
        return (memory, _on_off(_env("TS_HEADROOM")), agentmemory, _on_off(_env("TS_CAVEMAN")))

    memory = _env("TS_MEMORY_BACKEND") or ask.choose(
        "Memory and compression:",
        [
            ("agentmemory", "AgentMemory remembers, Headroom compresses", "the default"),
            ("headroom", "Headroom does both", "AgentMemory is not installed"),
            ("none", "Headroom compresses only", "no memory at all"),
            ("off", "Neither", "no proxy, no memory"),
        ],
        "agentmemory",
    )
    mapping = {
        "agentmemory": ("agentmemory", "on", "on"),
        "headroom": ("headroom", "on", "off"),
        "none": ("none", "on", "off"),
    }
    memory, headroom, agentmemory = mapping.get(memory, ("none", "off", "off"))

    caveman = _env("TS_CAVEMAN") or ask.choose(
        "Caveman terse output for all projects?",
        [
            ("off", "off", "configure later with tstack config agents"),
            ("on", "on", "installs the pinned user-scope plugin/skill"),
        ],
        "off",
    )
    return (memory, headroom, agentmemory, _on_off(caveman))


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
    console.say(f"    tmux prefix      {answers.tmux}")
    console.say(f"    Apps             {' '.join(answers.apps) or '<none>'}")
    console.say(f"    Agent voice      {answers.cc_tts}")
    if answers.cc_tts == "on":
        console.say(f"    Voice says       {answers.cc_tts_message}")
        console.say(f"    TTS daemon       {answers.cc_tts_daemon}")
    console.say(f"    Headroom         {answers.headroom} (Cursor: {answers.headroom_cursor})")
    console.say(f"    Caveman          {answers.caveman}")
    console.say(f"    Memory backend   {answers.memory_backend}")


def confirm(console: Console, answers: Answers, assume_yes: bool) -> Answers | None:
    """Show the review and let it be edited or abandoned. None means quit.

    Skipped when nothing was asked: a fully env-driven run has nothing to review
    and must not block on a tty nobody is watching.
    """
    while True:
        review(console, answers)
        if assume_yes or answers.asked == 0 or not console.interactive:
            console.say("  (nothing to review - proceeding)")
            return answers
        reply = (text(console, "  [P]roceed / [e]dit / [q]uit: ") or "").lower()
        if reply in ("", "p", "proceed", "y", "yes"):
            return answers
        if reply in ("q", "quit"):
            console.say("==> quit - nothing was installed or changed.")
            return None
        if reply in ("e", "edit"):
            fresh = collect(console, ask_terminals=bool(answers.terminals))
            answers = replace(fresh, asked=fresh.asked or answers.asked)
            continue
        console.say(
            f"  '{reply}' is not one of the choices - Enter to proceed, 'e' to edit, 'q' to quit."
        )
