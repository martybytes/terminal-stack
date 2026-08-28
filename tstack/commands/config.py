"""`tstack config` - view and change saved settings.

PHASE II of the port (REVAMP-PLAN.md, phase 4). This module is built and tested
but is NOT yet the entry point: `tstack/commands.conf` still routes `config` to
`bootstrap/ts-config.sh` on POSIX and `@Set-TerminalStackConfig` on Windows.

The row flips when every verb here is native. It cannot flip earlier: the two
columns flip together, and a Python `config` that shelled out to
`bootstrap/ts-config.sh` for its un-ported verbs would leave Windows -- which has
no bash -- with no implementation at all. Half a subcommand cannot route.

What IS native here: show (prose and --json), get, set, leader, theme, tmux,
restore, atuin, memory, agents. What is not, and why:

    apps      the picker plus a package-manager install path per platform
    ghostty   file surgery: backup, restore, diff, and the WSL path resolution
    tts       25 sub-verbs over 41 keys; _cc_tts.sh survives as a library
    wizard    five callers outside `config`, so porting it here ports a
              subsystem those five cannot reach

Design rules this module is built to, from the port specification:

* **argv before the clone.** `tstack config theme` is a usage error whether or
  not a clone exists, and a user with a broken clone should still be told their
  command line was wrong. This is the `mux` ordering, not the `services` one.
* **One key per write.** The shell's `ts_save_config` is positional, so every
  caller re-states all four values because omitting one DROPS it -- which is why
  `set_leader` reads the theme back out just to write it again. Here each verb
  writes exactly the key it owns.
* **`agentmemoryEnabled` is derived.** It is written only by the memory writer.
  The shell let `agents agentmemory off` write it directly, producing the exact
  `memoryBackend=agentmemory` / `agentmemoryEnabled=off` pair `tstack doctor`
  reports as drift.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

from .. import paths, schema, store
from .. import platform as plat

HELP = """tstack config - view and change saved settings.

Usage:
  tstack config                    interactive menu
  tstack config show               the saved settings and the derived bindings
  tstack config show --json        the same as one JSON document
  tstack config show --json <key>  one setting as a record

  tstack config get <key>          one value, bare, for scripts
  tstack config set <key> <value>  any setting the schema knows about

  tstack config leader <chord>     the WezTerm leader key
  tstack config theme <mode>       dark | light | follow
  tstack config tmux <chord>       the tmux prefix
  tstack config restore <on|off>   reopen the last session on launch
  tstack config atuin <on|off>     atuin owns Ctrl+R
  tstack config memory <backend>   agentmemory | headroom | none | status
  tstack config agents [...]       per-machine agent wiring

  -h, --help                       this help

Values are saved to chezmoi [data], and mirrored to config.json on Windows.
`show --json` names which store each value came from."""

# The verbs this module owns. Anything else is still the shell's until the
# registry row flips; main() says so rather than pretending.
NATIVE = (
    "show",
    "get",
    "set",
    "leader",
    "theme",
    "tmux",
    "restore",
    "atuin",
    "memory",
    "agents",
    "ghostty",
    "prompt",
)
# `prompt` stays here rather than becoming a generic `set starshipPreset`: the
# value has to be checked against `starship preset --list`, which is the
# authority and grows, and an unknown name renders an EMPTY config -- a working
# prompt replaced by no prompt, with nothing in the diff to explain it.
# Verbs Python does not implement itself. They are not unported so much as
# UNPORTABLE by the plan's own rule: `apps` ends in a package-manager install,
# `tts` is 25 sub-verbs over the daemon, and `wizard`/`reconfigure` are the
# bootstrap's save-then-install sequence -- and REVAMP-PLAN.md lists the
# installer entry points as never ported. Python routes them to the shell.
#
# `wizard` is here rather than in HANDOFF for a reason worth stating: `tstack
# wizard` ASKS, and that is all it does. `tstack config wizard` asks and then
# SAVES AND INSTALLS, which is ts-config.sh's `run_wizard` -- and which in turn
# calls the Python questionnaire. Handing straight to `tstack wizard` collected
# every answer and threw them away.
DELEGATED = ("apps", "tts", "reconfigure", "wizard")
# Handed to another ported command rather than reimplemented here.
HANDOFF = {"mux": "mux", "wezterm": "wezterm", "ghostty": "ghostty"}

# The unknown-verb hint. ONE list, and it must be complete: the bash hint omits
# `memory`, which it implements, and the pwsh one omits `atuin` instead.
KNOWN = (
    "show, get, set, leader, theme, tmux, apps, tts, mux, restore, atuin, "
    "prompt, ghostty, memory, agents, wezterm, wizard"
)


def _colour() -> bool:
    """NO_COLOR, a pipe, or a dumb terminal all mean plain text."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    return sys.stdout.isatty()


class Out:
    """`ts-config.sh`'s own shape: a bare line, or the `!!` problem marker.

    The marker is what the characterization replay greps for
    (`tests/test_characterize.py` `shell_problems()`), so a problem line that
    prints without it is invisible to the corpus.
    """

    def __init__(self, colour: bool | None = None, quiet: bool = False) -> None:
        self.problems = 0
        self.quiet = quiet
        use = _colour() if colour is None else colour
        self.warn = "\033[1;33m!!\033[0m" if use else "!!"

    def say(self, message: str = "") -> None:
        if not self.quiet:
            print(message)

    def bad(self, message: str) -> None:
        """Problems print even under --quiet: a suppressed problem is a lie."""
        self.problems += 1
        print(f"  {self.warn} {message}")


def _fail(message: str) -> int:
    print(f"tstack config: {message}", file=sys.stderr)
    return 1


def _usage(line: str) -> int:
    print(line, file=sys.stderr)
    return 2


# --------------------------------------------------------------------- reading


def _row(label: str, value: str, note: str = "") -> str:
    """A `show` row. The 13-character label column is the contract.

    `agentmemory` is exactly 11 characters plus the colon, which is why it needs
    no padding and why the column is 13 rather than a rounder number.
    """
    tail = f"   ({note})" if note else ""
    return f"  {label:<11}: {value}{tail}"


def _wezterm_cell() -> str:
    """`<channel>[   (built YYYY-MM-DD)]`.

    The channel is DETECTED from the package manager, never stored: a saved value
    would go stale the moment someone switched channel by hand. Reuses the ported
    wezterm module rather than re-implementing the probe.
    """
    from . import wezterm

    cell = wezterm.channel()
    got = wezterm.installed()
    if got and got[1]:
        cell += f"   (built {wezterm.fmt_date(got[1])})"
    return cell


def show(out: Out) -> int:
    """The prose form. Row labels and the column are byte-for-byte contract."""
    data_leader = store.get("leaderChord", "ctrl-space")
    out.say("terminal-stack config:")
    out.say(
        _row(
            "leader",
            data_leader,
            f"WezTerm: {store.get('leaderMods', '')}+{store.get('leaderKey', '')}",
        )
    )
    out.say(
        _row(
            "theme",
            store.get("themeMode", "dark"),
            f"baked palette: {store.get('resolvedTheme', '')}",
        )
    )
    out.say(
        _row(
            "tmux",
            store.get("tmuxPrefix", "ctrl-b"),
            f"prefix: {store.get('tmuxPrefixResolved', '')}",
        )
    )
    out.say(_row("apps", store.get("apps", "")))
    out.say(_row("wezmux", store.get("weztermMux", "off"), "tstack mux on|off|status"))
    out.say(_row("wezrestore", store.get("weztermRestore", "off"), "tstack config restore on|off"))
    out.say(
        _row(
            "prompt",
            store.get("starshipPreset", "terminal-stack"),
            "tstack config prompt list",
        )
    )
    out.say(_row("atuin", store.get("atuinEnabled", "off"), "tstack config atuin on|off"))
    # Ghostty is printed wherever its config path resolves -- macOS, WSL and
    # Windows. The shell gated this on Darwin alone, so a WSL user's Ghostty
    # setting was invisible in `show` while `tstack config ghostty` still worked.
    if plat.kind() in (plat.MACOS, plat.WSL, plat.WINDOWS):
        out.say(_row("ghostty", store.get("ghosttyConfig", "on"), "tstack config ghostty on|off"))
    out.say(_row("wezterm", _wezterm_cell(), "tstack config wezterm"))
    out.say(
        _row(
            "headroom",
            store.get("headroomEnabled", "off"),
            f"Cursor: {store.get('headroomCursorMode', 'mcp')}",
        )
    )
    out.say(_row("caveman", store.get("cavemanEnabled", "off")))
    # No note on this row: `show` matches the shell, and the memory-backend
    # pairing belongs to `agents show`, which is where it is actionable.
    out.say(_row("agentmemory", store.get("agentmemoryEnabled", "off")))
    return 0


def show_json(key: str | None = None) -> int:
    """The read model. One document on stdout, no prose, and never a write.

    `schema.snapshot()` already existed for this and had no consumer; reusing it
    is the point. Its `source` field -- chezmoi | mirror | default | unset -- is
    what makes the output worth having: a value that looks right for the wrong
    reason is invisible without it.
    """
    if key is not None:
        if key not in schema.BY_KEY:
            near = [k for k in schema.BY_KEY if key.lower() in k.lower()][:5]
            hint = f" (did you mean: {', '.join(near)})" if near else ""
            print(f"tstack config: unknown setting '{key}'{hint}", file=sys.stderr)
            return 2
        print(json.dumps(schema.describe(key), indent=2))
        return 0

    mirror = store.mirror_path()
    toml = store.toml_path()
    document = {
        "settings": schema.snapshot(),
        "groups": list(schema.GROUPS),
        "divergences": [
            {"key": k, "chezmoi": mine, "mirror": theirs} for k, mine, theirs in store.divergences()
        ],
        "stores": {
            "chezmoi": str(toml) if toml else None,
            "mirror": str(mirror) if mirror else None,
            "authoritative": "mirror" if store.writes_to_mirror() else "chezmoi",
        },
    }
    print(json.dumps(document, indent=2))
    return 0


def get(key: str) -> int:
    """One value, bare, for scripts. No trailing prose, no colour."""
    if key not in schema.BY_KEY:
        return _usage(f"tstack config: unknown setting '{key}'")
    print(store.get(key))
    return 0


# --------------------------------------------------------------------- writing


def _apply(out: Out, dry_run: bool) -> None:
    """`chezmoi init` regenerates the derived keys; apply renders the files.

    init is not optional after a save: leaderKey, leaderMods, tmuxPrefixResolved
    and resolvedTheme are computed from .chezmoi.toml.tmpl, so skipping it leaves
    them describing the previous answer.
    """
    if dry_run:
        out.say("==> would apply (--dry-run)")
        return
    # "..." not U+2026, deliberately. The shell prints an ellipsis character and
    # this is the one place the port does not reproduce it byte-for-byte: a
    # Windows console on codepage 437 renders it as a replacement glyph, and
    # tests/test_tstack_cli.py forbids non-ASCII anywhere under tstack/ for
    # exactly that reason. The gate is enforced; the shell's byte is not.
    out.say("==> applying...")
    store.chezmoi_init()
    chezmoi = plat.find_chezmoi()
    if chezmoi:
        subprocess.run([chezmoi, "apply"], check=False, timeout=600)
    out.say("==> done.")


def set_value(key: str, value: str, out: Out, dry_run: bool) -> int:
    """The generic setter, validated by the schema rather than by hand.

    Refusing a DERIVED key here is the schema's own message, and it is the same
    refusal `agents agentmemory off` needs -- see set_agents().
    """
    setting = schema.BY_KEY.get(key)
    if setting is None:
        near = [k for k in schema.BY_KEY if key.lower() in k.lower()][:5]
        hint = f" (did you mean: {', '.join(near)})" if near else ""
        return _usage(f"tstack config: unknown setting '{key}'{hint}")
    reason = setting.validate(value)
    if reason:
        return _usage(f"tstack config: {reason}")
    if dry_run:
        out.say(f"==> would set {key} = {value}")
        return 0
    store.set(key, value)
    out.say(f"saved: {key} = {value}")
    _apply(out, dry_run)
    return 0


DELEGATED_HELP = {
    "apps": (
        "tstack config apps [<id> ...]\n"
        "  Re-open the optional-app picker, save the selection, and install what\n"
        "  is missing. Naming ids skips the picker. The install itself is the\n"
        "  platform's package manager, which is why this half stays in the shell.\n"
        "  List what is available:  tstack config show"
    ),
    "tts": (
        "tstack config tts <sub-command>\n"
        "  Voice notifications: on/off, engine, voices, voice-pool, message,\n"
        "  test, status, doctor and the daemon verbs. Run it bare for the list.\n"
        "  Full reference:  doc tts"
    ),
    "reconfigure": ("tstack config reconfigure\n  Alias for `tstack config wizard`. See that."),
    "wizard": (
        "tstack config wizard\n"
        "  Re-ask every install question, SAVE the answers, and install what they\n"
        "  imply -- the optional apps and the terminal emulator.\n"
        "\n"
        "  This is not the same command as `tstack wizard`, which only ASKS and\n"
        "  prints or emits the answers for a bootstrap to save. If you want the\n"
        "  questions without the consequences, run that one.\n"
        "\n"
        "  TS_ASSUME_YES=1  take every default without prompting\n"
        "  TS_LEADER, TS_THEME, TS_APPS, ...  skip individual questions"
    ),
}


def _delegate(verb: str, args: list[str]) -> int:
    """Hand a verb to the shell that owns it.

    These end in a package-manager install or the bootstrap's own save sequence,
    and REVAMP-PLAN.md lists the installer entry points as never ported. Calling
    the shell is the design, not a gap.
    """
    if any(a in ("-h", "--help", "help") for a in args):
        # NEVER forward this. `ts-config.sh` dispatches on `case "$1"` and simply
        # ignores the rest, so `tstack config wizard -h` would have RUN the
        # wizard -- asking every install question and installing packages -- for
        # someone who typed a help flag. Answer it here instead.
        print(DELEGATED_HELP[verb])
        return 0

    try:
        source = paths.resolve_source_dir()
    except paths.CloneNotFound:
        return _fail("cannot locate the terminal-stack clone (set TERMINAL_STACK_DIR).")
    script = source / "bootstrap" / "ts-config.sh"
    if not script.is_file():
        return _fail(f"{script} is missing from the clone")
    # An empty verb is the bare invocation: the shell's `case "${1:-}"` reads ""
    # as the menu, so it must not receive a stray empty argument either.
    argv = ["bash", str(script), *([verb] if verb else []), *args]
    got = subprocess.run(
        argv,
        check=False,
        timeout=3600,
        env={**os.environ, "TERMINAL_STACK_DIR": str(source)},
    )
    return got.returncode


def _prompt(args: list[str], out: Out, dry_run: bool) -> int:
    """Which Starship prompt, with every option rendered.

    A preset name tells you nothing, so `list` renders each one. The name is
    checked against `starship preset --list` BEFORE it is saved: an unknown one
    makes `starship preset` print nothing, and the deployed config would be
    EMPTY -- a working prompt replaced by no prompt, with nothing in the diff to
    explain it.
    """
    from .. import choices

    sub = args[0] if args else "status"
    current = store.get("starshipPreset", "terminal-stack")

    if sub in ("status", "show"):
        out.say(f"prompt: {current}")
        rendered = choices.preview(choices.STARSHIP, current)
        for line in (rendered or "  (starship is not installed yet)").splitlines():
            out.say(line)
        out.say("  tstack config prompt list      every option, each one rendered")
        out.say("  tstack config prompt <name>    switch to it")
        return 0

    offered = choices.options(choices.STARSHIP)
    if sub == "list":
        if len(offered) <= 1:
            return _fail("starship is not installed, so its presets cannot be listed.")
        for option in offered:
            out.say(f"{'*' if option.value == current else ' '} {option.value}")
            rendered = choices.preview(choices.STARSHIP, option.value)
            for line in (rendered or "").splitlines():
                out.say(line)
        out.say("  * is what you have now.  Switch: tstack config prompt <name>")
        return 0

    if sub == "preview":
        if len(args) < 2:
            return _usage("usage: tstack config prompt preview <name>")
        rendered = choices.preview(choices.STARSHIP, args[1])
        if rendered is None:
            return _fail(f"no preset named '{args[1]}'")
        for line in rendered.splitlines():
            out.say(line)
        return 0

    known = {o.value for o in offered}
    if sub not in known:
        if len(offered) <= 1:
            return _fail(
                "starship is not installed, so its presets cannot be listed.\n"
                "  Only 'terminal-stack' can be set without it."
            )
        listing = "\n".join(f"     {name}" for name in sorted(known))
        return _usage(f"tstack config: no starship preset named '{sub}'. Available:\n{listing}")
    if dry_run:
        out.say(f"==> would set starshipPreset = {sub}")
        return 0
    store.set("starshipPreset", sub)
    out.say(f"==> prompt: {sub}")
    _apply(out, dry_run)
    rendered = choices.preview(choices.STARSHIP, sub)
    for line in (rendered or "").splitlines():
        out.say(line)
    return 0


def _ghostty(args: list[str], out: Out, dry_run: bool) -> int:
    """The one implementation of the managed Ghostty config.

    It replaces three: `bootstrap/ts-config.sh` covered macOS and the WSL view of
    the Windows side, `$PROFILE`'s Set-TerminalStackConfig covered native
    Windows, and each carried its own copy of the themeMode -> theme mapping.
    Both shells now hand off here, the way `mux` and `wezterm` already do.
    """
    from . import ghostty as ghostty_cmd

    sub = args[0] if args else "status"
    if sub not in ghostty_cmd.VERBS:
        return _usage("usage: tstack config ghostty [on|off|status|diff]")
    return ghostty_cmd.main([sub, *(["--dry-run"] if dry_run else [])])


def set_memory(backend: str, out: Out, dry_run: bool) -> int:
    """The ONLY writer of memoryBackend and its derived agentmemoryEnabled.

    One slot, so two memory systems are unrepresentable rather than merely
    discouraged. Anything else writing either key produces drift that
    `tstack doctor` reports.
    """
    if backend not in ("agentmemory", "headroom", "none"):
        return _usage("usage: tstack config memory [agentmemory|headroom|none|status]")
    if dry_run:
        out.say(f"==> would set memoryBackend = {backend}")
        return 0
    before = store.get("memoryBackend", "agentmemory")
    store.set("memoryBackend", backend)
    store.set("agentmemoryEnabled", "on" if backend == "agentmemory" else "off")
    out.say(f"saved: memoryBackend = {backend}")

    # The agent WIRING is what actually captures, so it moves with the setting.
    # `tstack agents` refuses to persist a state it cannot verify, which is why
    # this runs it rather than only writing the key.
    from . import agents as agents_cmd

    if backend == "agentmemory":
        if agents_cmd.main(["agentmemory", "on"]) != 0:
            out.bad("AgentMemory wiring failed; retry: tstack config agents agentmemory repair")
    elif before == "agentmemory":
        agents_cmd.main(["agentmemory", "off"])
        out.say("  AgentMemory hooks removed from Claude/Codex/Cursor.")

    # Restart rather than print the command: the setting and the running state
    # must not disagree, and a headroom still running the old compose file is
    # exactly the silent mismatch this setting exists to remove.
    if shutil.which("docker"):
        out.say("  restarting headroom so the change takes effect...")
        from . import services as services_cmd

        if services_cmd.main(["restart", "headroom"]) != 0:
            out.bad("headroom restart failed - run: tstack services restart headroom")
    else:
        out.say("  no docker on PATH; apply it later with: tstack services restart headroom")
    return 0


def show_memory(out: Out) -> int:
    backend = store.get("memoryBackend", "agentmemory")
    out.say(f"memory backend: {backend}")
    blurb = {
        "agentmemory": "  AgentMemory remembers (3111), Headroom compresses (8787).",
        "headroom": "  Headroom remembers and compresses; AgentMemory is not installed.",
        "none": "  No memory. Headroom still compresses if it is enabled.",
    }.get(backend)
    if blurb:
        out.say(blurb)
    out.say(
        f"  agentmemory wiring: {store.get('agentmemoryEnabled', 'off')}"
        f"   headroom: {store.get('headroomEnabled', 'off')}"
    )
    derived = "on" if backend == "agentmemory" else "off"
    if store.normalise(store.get("agentmemoryEnabled", "off")) != store.normalise(derived):
        out.bad(
            f"agentmemoryEnabled disagrees with memoryBackend - fix: tstack config memory {backend}"
        )
    return 1 if out.problems else 0


AGENT_KEYS = {
    "headroom": "headroomEnabled",
    "caveman": "cavemanEnabled",
    "agentmemory": "agentmemoryEnabled",
    "playwright": "playwrightEnabled",
}


def show_agents(out: Out) -> int:
    out.say("coding agents (user-global on this computer):")
    out.say(
        _row(
            "headroom",
            store.get("headroomEnabled", "off"),
            f"Cursor: {store.get('headroomCursorMode', 'mcp')}",
        )
    )
    out.say(_row("caveman", store.get("cavemanEnabled", "off")))
    out.say(
        _row(
            "agentmemory",
            store.get("agentmemoryEnabled", "off"),
            f"memory backend: {store.get('memoryBackend', 'agentmemory')}",
        )
    )
    out.say(_row("playwright", store.get("playwrightEnabled", "off"), "tstack services status"))
    return 0


def set_agents(tool: str, action: str, out: Out, dry_run: bool, cursor: str = "") -> int:
    """Per-machine agent toggles.

    agentmemory is refused in BOTH directions, not just `on`. The shell guarded
    only `on`, so `agents agentmemory off` wrote the derived key directly and
    produced the drift `tstack doctor` exists to report.
    """
    if tool not in AGENT_KEYS:
        return _usage(f"tstack config agents: unknown tool '{tool}'")
    if action not in ("on", "off", "status", "repair", "uninstall"):
        return _usage(
            "usage: tstack config agents "
            "<headroom|caveman|agentmemory|playwright> on|off|status|repair|uninstall"
        )
    if action == "status":
        return show_agents(out)
    if cursor:
        # `agents headroom cursor <mcp|byok|off>` in the shell. Only headroom has
        # a Cursor mode, and only `tstack agents` knows how to rewire it.
        from . import agents as agents_cmd

        return int(agents_cmd.main([tool, action, cursor]))
    if tool == "agentmemory" and action in ("on", "off"):
        return _usage(
            "tstack config agents: agentmemoryEnabled is derived from memoryBackend "
            "- use: tstack config memory agentmemory|headroom|none"
        )
    if action in ("repair", "uninstall"):
        # `tstack agents` owns the client wiring and does exactly this. Saying
        # "use the shell" became a dead end the moment `config` stopped being the
        # shell on POSIX.
        from . import agents as agents_cmd

        return int(agents_cmd.main([tool, action]))
    if dry_run:
        out.say(f"==> would set {AGENT_KEYS[tool]} = {action}")
        return 0
    store.set(AGENT_KEYS[tool], action)
    out.say(f"saved: {AGENT_KEYS[tool]} = {action}")
    return 0


# ----------------------------------------------------------------- entry point


def main(argv: list[str]) -> int:
    """Dispatch. argv is validated BEFORE the clone is resolved.

    `tstack config theme` is a usage error whether or not a clone exists, and a
    user whose clone is broken should still be told their command line was
    wrong. `mux` orders it this way; `services` does not, and the two disagree
    on the exit code for an unknown verb as a result.
    """
    dry_run = False
    quiet = False
    as_json = False
    rest: list[str] = []
    for item in argv:
        if item in ("-h", "--help", "help"):
            # Only BEFORE a verb is it OURS. `tstack config wizard -h` wants the
            # wizard's help, and the shell this replaced forwarded it -- claiming
            # it here made every sub-command's -h print this page instead.
            if not rest:
                print(HELP)
                return 0
            rest.append(item)
            continue
        if item == "--dry-run":
            dry_run = True
        elif item == "--quiet":
            quiet = True
        elif item == "--json":
            as_json = True
        elif item.startswith("-") and item != "-":
            return _usage(f"tstack config: unknown flag '{item}' (try: tstack config -h)")
        else:
            rest.append(item)

    # NO VERB IS THE INTERACTIVE MENU, not `show`. The shell has always opened
    # one, every doc says "run it bare for a menu", and quietly turning that into
    # a one-shot print is the kind of regression a port makes and nobody reports
    # -- it still prints something plausible. The menu itself is shell: it drives
    # the same delegated verbs, so reimplementing it here would fork the loop.
    if not rest:
        return _delegate("", [])

    verb = rest[0]
    args = rest[1:]

    if verb in HANDOFF:
        # In-process, not a subprocess: these are ported commands in this same
        # program, and spawning a second interpreter to reach one would double
        # the startup cost for nothing.
        module = __import__(f"tstack.commands.{HANDOFF[verb]}", fromlist=["main"])
        return int(module.main(args))
    if verb in DELEGATED:
        return _delegate(verb, args)
    if verb not in NATIVE:
        return _usage(f"tstack config: unknown command '{verb}' (try: {KNOWN})")

    out = Out(quiet=quiet)

    if verb == "show":
        return show_json(args[0] if args else None) if as_json else show(out)
    if verb == "get":
        if not args:
            return _usage("usage: tstack config get <key>")
        return get(args[0])
    if verb == "set":
        if len(args) < 2:
            return _usage("usage: tstack config set <key> <value>")
        return set_value(args[0], args[1], out, dry_run)

    simple = {
        "leader": ("leaderChord", "usage: tstack config leader <chord>"),
        "theme": ("themeMode", "usage: tstack config theme <dark|light|follow>"),
        "tmux": ("tmuxPrefix", "usage: tstack config tmux <chord>"),
        "restore": ("weztermRestore", "usage: tstack config restore <on|off>"),
        "atuin": ("atuinEnabled", "usage: tstack config atuin <on|off>"),
    }
    # Argument arity is part of the command line, so it is checked with the rest
    # of argv -- BEFORE the clone. Resolving the clone first turns
    # `tstack config theme` into "no clone" on a broken machine, hiding the fact
    # that the command line was wrong either way.
    if verb in simple and not args:
        return _usage(simple[verb][1])

    # Everything below writes, so it needs a clone.
    try:
        paths.resolve_source_dir()
    except paths.CloneNotFound:
        return _fail("cannot locate the terminal-stack clone (set TERMINAL_STACK_DIR).")

    if verb == "ghostty":
        return _ghostty(args, out, dry_run)

    if verb == "prompt":
        return _prompt(args, out, dry_run)

    if verb == "memory":
        sub = args[0] if args else "status"
        if sub in ("status", "show"):
            return show_memory(out)
        return set_memory(sub, out, dry_run)

    if verb == "agents":
        if not args or args[0] in ("show",):
            return show_agents(out)
        return set_agents(
            args[0],
            args[1] if len(args) > 1 else "status",
            out,
            dry_run,
            cursor=args[2] if len(args) > 2 else "",
        )

    key, _usage_line = simple[verb]
    rc = set_value(key, args[0], out, dry_run)
    # atuin has no PowerShell integration -- `atuin init` has no pwsh target --
    # but the key still belongs in the store: the pwsh save never wrote it, so
    # every Windows save STRIPPED it from the mirror.
    if rc == 0 and verb == "atuin" and plat.kind() == plat.WINDOWS:
        out.say("    no PowerShell integration; this affects WSL shells only.")
    return rc
