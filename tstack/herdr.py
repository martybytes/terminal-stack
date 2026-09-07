"""The managed herdr config: which keys the stack owns, and what `off` restores.

ONE implementation, the way `tstack/ghostty.py` is one. Both shells hand off
here through `tstack herdr` and `tstack config herdr`.

A KEY SPLICE, NOT A WHOLE-FILE RENDER

This is the one place it diverges from the Ghostty module it is otherwise
modelled on, and the divergence was found by looking at a real machine rather
than reasoned about. herdr writes this file itself (`herdr config reset-keys`
backs it up and rewrites it; the global menu edits it), and so does the user --
the first box this shipped to already had a hand-written config carrying
`onboarding = false` and `[terminal] default_shell = "pwsh"`. A whole-file render
would have deleted both, silently and with nothing in any diff. That is the same
hazard as whole-file-copying `~/.claude/settings.json`, on a format with no cheap
key splice, so the splice is written out here by hand.

Ownership is therefore per KEY, and the set is deliberately tiny: `[theme] name`
and nothing else. Every other byte of the file survives a write untouched,
comments and formatting included.

WHY `theme.name = "terminal"`

herdr ships eleven built-in themes plus an `auto_switch` pair. Naming one would
make the stack a second theme owner and would have to be re-derived every time
`themeMode` changed -- and picking a fixed name is exactly the trap the Ghostty
config hit by reading `resolvedTheme`, which looks right and silently freezes
`follow`. `terminal` tells herdr to use the host terminal's ANSI palette, which
this stack already themes, so one setting is correct for dark, light AND follow
and stays correct when the OS appearance flips underneath.

WHY `off` DOES NOT REMOVE THE FILE

Ghostty's `off` unlinks what it deployed, because it deployed the whole file.
Here the file is mostly someone else's, so `off` restores the backup taken before
the first write, and failing that removes only the spliced key. It never unlinks.
And, as with Ghostty, it is not a `.chezmoiremove` rule and not a sync-side
delete: both of those run on every machine and would reach a box that never
opted in.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import platform as plat
from . import proc, store

Say = Callable[[str], None]
Apply = Callable[[], None]

# The comment stamped on the one line the stack owns. Per-line rather than
# per-file, because ownership here is per key: a file without it is entirely
# someone else's, and a file with it still is, apart from that line.
MARKER = "managed by terminal-stack"

# The value written for `[theme] name`. See the module docstring.
THEME = "terminal"

# The table/key pairs the stack can own. Ownership stays per KEY: every byte
# outside these two lines is someone else's and survives a write untouched.
TABLE = "theme"
KEY = "name"
SHELL_TABLE = "terminal"
SHELL_KEY = "default_shell"

# What `herdrShell` may be. `auto` is the point of the setting -- see auto_shell.
# `login` means the stack owns no shell key at all, which is herdr's own
# behaviour: spawn the login shell.
SHELL_OPTIONS = ("auto", "zsh", "bash", "pwsh", "login")


@dataclass(frozen=True)
class Owned:
    """One line the stack writes: `[table] key = value`."""

    table: str
    key: str
    value: str


@dataclass(frozen=True)
class Target:
    """Where this machine's herdr config lives."""

    config: Path

    @property
    def directory(self) -> Path:
        return self.config.parent


def target() -> Target:
    """The config file herdr on THIS machine reads.

    Never None: unlike Ghostty, herdr runs on all four platforms.

    HERDR_CONFIG_PATH is herdr's own override and wins here for the same reason
    it wins there -- a machine that has moved its config must not be written to
    at the default path instead.

    On WSL this resolves to the WSL path, never a /mnt/c one. The Windows and
    WSL servers are independent (docs/decisions.md), so each side owns its own
    config, and resolving across the boundary is the mistake the Ghostty module
    documents making.
    """
    pinned = os.environ.get("HERDR_CONFIG_PATH")
    if pinned:
        return Target(Path(pinned))
    if plat.kind() == plat.WINDOWS:
        roaming = os.environ.get("APPDATA")
        base = Path(roaming) if roaming else Path.home() / "AppData" / "Roaming"
        return Target(base / "herdr" / "config.toml")
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return Target(base / "herdr" / "config.toml")


def setting() -> str:
    value = store.get("herdrConfig", "off")
    return value if value in ("on", "off") else "off"


def shell_setting() -> str:
    value = store.get("herdrShell", "auto")
    return value if value in SHELL_OPTIONS else "auto"


def auto_shell() -> str:
    """The shell THIS STACK configures on this platform, by name.

    Not the login shell, which is the whole reason the setting exists. On
    Omarchy the login shell is bash and always will be -- the fleet never runs
    `chsh`, because Omarchy's own desktop is bash-first -- while the shell this
    stack actually configures, with the prompt, the tools and the agent
    wrappers, is zsh. herdr spawning the login shell therefore gives a pane that
    is not the machine the rest of the stack set up.

    macOS and Debian/Ubuntu land on zsh for the same reason and by a shorter
    road: it is what `dot_zshrc` is. Windows is pwsh, where `$PROFILE` is the
    file the stack owns. That is the whole map -- four platforms, two answers,
    and neither is "whatever /etc/passwd says".
    """
    return "pwsh" if plat.kind() == plat.WINDOWS else "zsh"


def _hand_written_shell(text: str) -> str | None:
    """A `default_shell` already in the file that is NOT ours, if there is one."""
    line_re = _key_re(SHELL_KEY)
    table = ""
    for line in text.splitlines():
        found = _TABLE_RE.match(line)
        if found:
            table = found.group(1).strip()
            continue
        if table != SHELL_TABLE or line.lstrip().startswith("#"):
            continue
        if line_re.match(line) and MARKER not in line:
            return line.strip()
    return None


def resolve_shell(text: str = "") -> tuple[str | None, str]:
    """(the path to write, why) -- or (None, why not).

    An ABSOLUTE path, never a bare name, and resolved on the machine at write
    time rather than stored. Both halves of that matter:

    * Stored, a path would be wrong on the other side of a combined
      Windows+WSL machine, and a Windows one carries backslashes, which
      `schema.Setting.validate` refuses for exactly this store (it writes
      chezmoi.toml unescaped). So `[data]` holds the CHOICE and this resolves it.
    * Absolute, because the herdr SERVER's PATH is not your shell's. That server
      is long-lived and keeps the environment it started with -- the same
      property that cost this repo an ssh agent in every pane -- so a bare
      `zsh` is resolved against an environment nobody has looked at.

    A shell that is not installed returns None. Writing a `default_shell` that
    does not exist would break every new pane, which is far worse than leaving
    herdr on the login shell it was already using, so the key is simply not
    written and `status` says why.
    """
    choice = shell_setting()
    if choice == "login":
        return None, "login (herdr spawns your login shell; the stack owns no shell key)"
    if choice == "auto":
        # `auto` DEFERS to a value you wrote yourself. This module's whole
        # premise is that a line without our marker is yours -- the first box it
        # shipped to had a hand-written `default_shell = "pwsh"` -- and a
        # default that quietly took that over would be the same silent loss a
        # whole-file render causes, just slower. Naming a shell explicitly
        # (`tstack herdr shell zsh`) is how you hand the key over; that is a
        # choice, and the file is backed up before the first write either way.
        existing = _hand_written_shell(text)
        if existing is not None:
            return None, f"auto, deferring to your own `{existing}`"
    name = auto_shell() if choice == "auto" else choice
    found = plat.find_pwsh() if name == "pwsh" else shutil.which(name)
    if not found:
        return None, f"{name} is not installed here, so the login shell is left alone"
    return found, f"auto -> {name}" if choice == "auto" else name


def owned(text: str = "") -> list[Owned]:
    """Every line the stack writes on this machine, given the file it is writing.

    `text` matters because ownership of the shell key is conditional: see
    `resolve_shell`. Passing nothing means "no file yet", which is the right
    reading for a machine that has none.
    """
    items = [Owned(TABLE, KEY, THEME)]
    path, _ = resolve_shell(text)
    if path is not None:
        items.append(Owned(SHELL_TABLE, SHELL_KEY, path))
    return items


# ------------------------------------------------------------------- the splice


def _newline(text: str) -> str:
    """The line ending the FILE already uses.

    The file's own endings decide what is inserted, never the platform's. Same
    rule as bootstrap/_merge_json_settings.sh, and for the same reason: a CRLF
    file that grows one LF line produces a diff nobody asked for and, on the
    files this stack manages, a spurious `.bak` on every apply.
    """
    if "\r\n" in text:
        return "\r\n"
    return "\n"


def _toml(value: str) -> str:
    r"""`value` as a TOML string, correct for a Windows path.

    A backslash is an ESCAPE in a basic string, so `"C:\Users\x"` is wrong --
    and worse than wrong when the escape happens to be a valid one, because then
    it parses and means something else. A literal (single-quoted) string has no
    escapes at all, which is exactly what a path wants. Windows paths may also
    contain a single quote, so that is checked rather than assumed.
    """
    if "\\" in value and "'" not in value:
        return f"'{value}'"
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _owned_line(item: Owned) -> str:
    return f"{item.key} = {_toml(item.value)}  # {MARKER}"


_TABLE_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")


def _key_re(key: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(key)}\s*=")


def splice(text: str) -> str:
    """Return `text` with every key the stack owns set, and nothing else changed.

    Ownership is a SET now, not a single key: `[theme] name` always, and
    `[terminal] default_shell` when `herdrShell` resolves to a shell that
    actually exists on this machine. A key the stack could own but currently
    does not -- `herdrShell = login`, or a zsh that is not installed -- has its
    own line REMOVED rather than left behind, or turning the setting off would
    leave the last value it wrote in force forever, which is the failure mode a
    splice is supposed to be immune to.

    For each owned key, three cases in the order they are checked:

    * the key exists in its table  -> that line is replaced
    * the table exists without it  -> the line is inserted just after the header
    * no such table at all         -> a two-line table is appended

    Appending at end-of-file is safe in TOML: table order does not matter, and
    EOF is top level, so a new header cannot land inside somebody else's table.

    A COMMENTED key (`# name = "catppuccin"`, which is what
    `herdr --default-config` emits) is deliberately not a match. It is
    documentation, not a setting, and rewriting it would both lose the comment
    and leave the real value ambiguous.
    """
    items = owned(text)
    for item in items:
        text = _set_key(text, item)
    held = {(item.table, item.key) for item in items}
    for table, key in ((TABLE, KEY), (SHELL_TABLE, SHELL_KEY)):
        if (table, key) not in held:
            text = _drop_key(text, key)
    return text


def _set_key(text: str, item: Owned) -> str:
    """`text` with this one line written, wherever it belongs."""
    newline = _newline(text)
    lines = text.splitlines()
    line_re = _key_re(item.key)
    table = ""
    for index, line in enumerate(lines):
        found = _TABLE_RE.match(line)
        if found:
            table = found.group(1).strip()
            continue
        if table != item.table:
            continue
        if line.lstrip().startswith("#"):
            continue
        if line_re.match(line):
            if line.strip() == _owned_line(item):
                return text
            lines[index] = _owned_line(item)
            return newline.join(lines) + newline

    for index, line in enumerate(lines):
        found = _TABLE_RE.match(line)
        if found and found.group(1).strip() == item.table:
            lines.insert(index + 1, _owned_line(item))
            return newline.join(lines) + newline

    if lines and lines[-1].strip():
        lines.append("")
    lines.append(f"[{item.table}]")
    lines.append(_owned_line(item))
    return newline.join(lines) + newline


def _drop_key(text: str, key: str) -> str:
    """`text` with OUR line for `key` removed, and any other line for it kept.

    Marker-gated, like `unsplice`: a `default_shell` the user has since written
    by hand is theirs, and removing it because it sits where ours did is the
    silent loss this whole module exists to avoid.
    """
    line_re = _key_re(key)
    kept = [line for line in text.splitlines() if not (MARKER in line and line_re.match(line))]
    if len(kept) == len(text.splitlines()):
        return text
    newline = _newline(text)
    if not kept:
        return ""
    return newline.join(kept) + newline


def unsplice(text: str) -> str:
    """Return `text` with the stack's own line removed, and nothing else changed.

    Only a line carrying the marker is removed. A `name = ...` the user has since
    edited by hand is theirs, and taking it out because it sits where ours did
    would be the same class of silent loss the splice exists to avoid.
    """
    newline = _newline(text)
    kept = [line for line in text.splitlines() if MARKER not in line]
    if not kept:
        return ""
    return newline.join(kept) + newline


def is_ours(config: Path) -> bool | None:
    """True when the deployed file carries our line, None when it is absent."""
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return MARKER in text


# ------------------------------------------------------------------- backups


def newest_backup(directory: Path) -> Path | None:
    """The most recent `config.toml.bak.*`, by NAME.

    By name, not mtime: the convention is `.bak.YYYYMMDD` with `.1`, `.2` on a
    same-day re-run, so lexical order is chronological order and a copy that
    preserves the original's mtime cannot mislead it.
    """
    try:
        backups = sorted(directory.glob("config.toml.bak.*"))
    except OSError:
        return None
    return backups[-1] if backups else None


def backup(config: Path) -> Path | None:
    """Copy `config` aside before the first write, never clobbering a same-day one.

    `<path>.bak.YYYYMMDD`, then `.1`, `.2`. Returns the backup written, or None
    when there was nothing to back up.

    Taken only when the file is not already ours: once it carries our line, the
    thing worth preserving has already been preserved, and re-backing-up on
    every write would bury the original under copies of itself.
    """
    if not config.is_file():
        return None
    if is_ours(config):
        return None
    stamp = date.today().strftime("%Y%m%d")
    candidate = config.with_name(f"{config.name}.bak.{stamp}")
    suffix = 0
    while candidate.exists():
        suffix += 1
        candidate = config.with_name(f"{config.name}.bak.{stamp}.{suffix}")
    candidate.write_bytes(config.read_bytes())
    return candidate


def _read(config: Path) -> str:
    try:
        return config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _write(config: Path, text: str) -> None:
    config.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.with_name(config.name + ".tsnew")
    temporary.write_text(text, encoding="utf-8", newline="")
    temporary.replace(config)


def render(say: Say) -> int:
    """Splice our key in, backing the file up first. Idempotent."""
    spot = target()
    before = _read(spot.config)
    after = splice(before)
    if after == before and spot.config.exists():
        say(f"  {spot.config}  (already current)")
        return 0
    saved = backup(spot.config)
    if saved is not None:
        say(f"  backed up {spot.config} -> {saved.name}")
    _write(spot.config, after)
    say(f"  wrote {spot.config}")
    return 0


# ------------------------------------------------------------------- the binary


def binary() -> str | None:
    """The herdr executable this machine would use, or None."""
    return shutil.which("herdr")


def _run(argv: list[str], timeout: int = 20) -> subprocess.CompletedProcess[str] | None:
    """The one capture helper. `text=True` alone decodes with the LOCALE codec --
    see tstack/proc.py, which is where this stopped being six copies."""
    return proc.capture(argv, timeout=timeout)


def version() -> str | None:
    exe = binary()
    if exe is None:
        return None
    got = _run([exe, "--version"])
    if got is None or not got.stdout.strip():
        return None
    return got.stdout.splitlines()[0].strip()


def channel() -> str | None:
    """The update channel, read back from herdr rather than stored.

    Detected, never persisted -- the same call the WezTerm channel makes. A
    stored value can disagree with the machine; a read-back cannot.
    """
    exe = binary()
    if exe is None:
        return None
    got = _run([exe, "channel", "show"])
    if got is None or got.returncode != 0 or not got.stdout.strip():
        return None
    return got.stdout.splitlines()[0].strip()


def _server_state(exe: str) -> str:
    """The `server:` block's `status:` from `herdr status`, in one line.

    `herdr status` prints four indented blocks (client, server, update, and
    sometimes more), so the FIRST line is "client:" and means nothing. Read the
    server block specifically, or the report says "client:" and looks broken --
    which is what the first cut of this did.
    """
    got = _run([exe, "status"])
    if got is None:
        return "unknown (herdr status did not answer)"
    text = got.stdout or got.stderr
    block = ""
    state = ""
    socket = ""
    for line in text.splitlines():
        if line and not line[0].isspace():
            block = line.strip().rstrip(":")
            continue
        if block != "server":
            continue
        key, _, value = line.strip().partition(":")
        if key == "status":
            state = value.strip()
        elif key == "socket":
            socket = value.strip()
    if not state:
        return "running" if got.returncode == 0 else "not running"
    return f"{state}  ({socket})" if socket else state


def server_state() -> str:
    """Whether a herdr server is answering on THIS side of the machine."""
    exe = binary()
    if exe is None:
        return "herdr is not installed"
    return _server_state(exe)


def windows_side() -> str | None:
    """The Windows server's state, seen from WSL, or None when not applicable.

    Reached through interop, never `pgrep`: a healthy Windows-side server is
    invisible to a POSIX process table, which is the trap `tstack mux` already
    documents. The two servers are independent by design (decision 6 in
    docs/decisions.md), so this reports both rather than reconciling them.
    """
    if plat.kind() != plat.WSL:
        return None
    exe = shutil.which("herdr.exe")
    if exe is None:
        return "herdr.exe not on PATH (no Windows-side herdr, or interop is off)"
    return _server_state(exe)


# --------------------------------------------------------------- prefix collision


def configured_prefix() -> str:
    """herdr's prefix chord, read from its config, defaulting to its own default.

    Read rather than stored: the stack deliberately owns no prefix key here
    (docs/decisions.md), so the file is the only authority.
    """
    text = _read(target().config)
    table = ""
    for line in text.splitlines():
        found = _TABLE_RE.match(line)
        if found:
            table = found.group(1).strip()
            continue
        if table != "keys" or line.lstrip().startswith("#"):
            continue
        match = re.match(r"^\s*prefix\s*=\s*\"([^\"]*)\"", line)
        if match:
            return match.group(1)
    return "ctrl+b"


def _normalise(chord: str) -> str:
    return chord.strip().lower().replace("-", "+").replace(" ", "")


def collisions() -> list[tuple[str, str]]:
    """Saved chords that equal herdr's prefix, as (setting name, chord).

    A WARNING's evidence, not a failure's: the clash only bites when one
    multiplexer is nested inside the other, which is a reachable state here
    because herdr sits beside tmux rather than replacing it.

    Gated on the OTHER program actually existing, which is the difference
    between a warning and a nag. herdr keeps its own `ctrl+b` default by
    decision, so a machine that reports this on every `tstack doctor` run and
    can never satisfy it is a report nobody reads -- the same failure mode
    `ts_apps_pending` grew `ts_app_installable` to end. No tmux on the box, no
    nesting, nothing to say.
    """
    prefix = _normalise(configured_prefix())
    found = []
    for key, default, program in (
        ("tmuxPrefix", "ctrl-b", "tmux"),
        ("leaderChord", "ctrl-space", "wezterm"),
    ):
        if shutil.which(program) is None:
            continue
        chord = store.get(key, default)
        if _normalise(chord) == prefix:
            found.append((key, chord))
    return found


# ----------------------------------------------------------------------- verbs


def status(say: Say) -> int:
    spot = target()
    say(f"herdr config: {setting()}")

    ours = is_ours(spot.config)
    if ours is None:
        say(f"  {spot.config}  (absent)")
    text = _read(spot.config)
    if ours:
        keys = ", ".join(f"[{i.table}] {i.key}" for i in owned(text))
        say(f"  {spot.config}  (carries our {keys})")
    elif ours is False:
        say(f"  {spot.config}  (yours; `tstack herdr on` splices our keys and backs it up first)")

    path, why = resolve_shell(text)
    say(f"  pane shell: {shell_setting()}  ({why})")
    if path is not None:
        say(f"    -> {path}")
    saved = newest_backup(spot.directory)
    if saved:
        say(f"  newest backup: {saved}")

    got = version()
    say(f"  herdr: {got}" if got else "  herdr: not installed (tstack config apps herdr)")
    if got:
        detected = channel()
        if detected:
            say(f"  channel: {detected}  (read back, never stored)")
        say(f"  server here: {server_state()}")
        other = windows_side()
        if other:
            say(f"  server on the Windows side: {other}")

    clashes = collisions()
    for key, chord in clashes:
        say(f"  WARNING: herdr's prefix ({configured_prefix()}) is also {key} ({chord}).")
        say(f"    Nested, the inner one never sees it. Change {key} with `tstack config`,")
        say(f"    or set [keys] prefix in {spot.config}.")
    return 0


def turn_on(say: Say, apply: Apply) -> int:
    store.set("herdrConfig", "on")
    say("==> herdr config on.")
    render(say)
    apply()
    say(f"  reload it with: {binary() or 'herdr'} server reload-config")
    return 0


def set_shell(value: str, say: Say, apply: Apply) -> int:
    """Save `herdrShell` and re-splice, so the setting and the file agree.

    Saving without re-splicing is the drift `tstack config memory` already
    refuses to allow: the store would say zsh and the config would still say
    whatever it said, with nothing to explain the difference.

    Re-splicing when the managed config is OFF would be a write to a file the
    user has told us to leave alone, so that only saves.
    """
    if value not in SHELL_OPTIONS:
        say(f"tstack herdr shell: must be one of: {', '.join(SHELL_OPTIONS)}")
        return 2
    store.set("herdrShell", value)
    _, why = resolve_shell(_read(target().config))
    say(f"==> herdr pane shell: {value}  ({why})")
    if setting() == "on":
        render(say)
        say(f"  reload it with: {binary() or 'herdr'} server reload-config")
        say("  open panes keep the shell they started with.")
    else:
        say("  herdr config is off, so nothing was written. `tstack herdr on` applies it.")
    apply()
    return 0


def turn_off(say: Say, apply: Apply) -> int:
    """Restore the backup, or take our one line back out. Never unlinks."""
    store.set("herdrConfig", "off")
    spot = target()

    saved = newest_backup(spot.directory)
    if saved is not None and saved.is_file():
        _write(spot.config, saved.read_text(encoding="utf-8", errors="replace"))
        say(f"==> restored {spot.config} from {saved.name}")
    elif spot.config.is_file():
        before = _read(spot.config)
        after = unsplice(before)
        if after != before:
            _write(spot.config, after)
            say(f"==> removed our keys from {spot.config}")
        else:
            say(f"==> nothing of ours in {spot.config}; left it alone")

    say("==> herdr config off.")
    apply()
    return 0


def report_update(say: Say) -> int:
    """Say whether a newer herdr exists. Never installs one.

    Updating a live multiplexer kills nothing by itself, but it is the same class
    of hazard as restarting the WezTerm mux server, which this stack deliberately
    never automates. herdr's own background `version_check` already watches; this
    prints the command and stops.
    """
    got = version()
    if got is None:
        say("herdr is not installed on this machine.")
        return 1
    say(f"herdr: {got}")
    detected = channel()
    if detected:
        say(f"channel: {detected}")
    say("Update it yourself when no session is mid-flight:  herdr update")
    say("The stack does not run that for you; a multiplexer is not something to")
    say("restart behind your back.")
    return 0
