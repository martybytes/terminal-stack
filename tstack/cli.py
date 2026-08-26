"""The tstack dispatcher.

Only three things live here: help, --version, and handing a ported subcommand to
its module. Routing to *unported* subcommands is the shell shims' job, not this
module's -- a not-yet-ported Windows subcommand is a function inside $PROFILE and
cannot be invoked from a child process. See tstack/commands.conf.

HELP IS RENDERED HERE AND ONLY HERE. The shims call `tstack --help` rather than
formatting the table themselves, because three implementations of one help text
is the exact problem this whole port exists to remove. Completions parse
commands.conf directly, but they only need names, so there is no format to drift.
"""

from __future__ import annotations

import json
import sys

from . import __version__, paths, registry
from . import platform as plat

# Exit codes with meaning to the shell shims. Anything else is passed through.
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
# Reserved for the update/rollback port (phase 7): "work done, now restart the
# shell". A child process cannot re-exec its parent, so the shim acts on this.
EXIT_RESTART_SHELL = 75


def render_help() -> str:
    cmds = registry.commands()
    kind = plat.kind()
    width = max((len(c.name) for c in cmds), default=8)

    # ASCII only, deliberately. A Windows console on codepage 437 renders an em
    # dash as a replacement glyph, and the repo already hit this class of bug
    # hard enough that bootstrap/_wezterm.sh:99 forces PYTHONIOENCODING=utf-8.
    lines = [
        "tstack - terminal-stack management",
        "",
        "Usage: tstack <command> [args]",
        "",
    ]
    for c in cmds:
        if c.is_supported(kind):
            lines.append(f"  {c.name.ljust(width)}  {c.summary}")
        else:
            # Listed, but honest. Silently hiding it makes a missing feature look
            # like a typo; reporting "not found" makes it look like breakage.
            lines.append(f"  {c.name.ljust(width)}  {c.summary}  (not available on {kind})")
    trailer = max(width, len("<command> -h"))
    lines += [
        "",
        f"  {'<command> -h'.ljust(trailer)}  help for one command",
        f"  {'--version'.ljust(trailer)}  clone path, branch and commit",
        "",
    ]
    return "\n".join(lines)


def render_version(as_json: bool = False) -> str:
    notes: list[str] = []
    try:
        src = paths.resolve_source_dir(warn=notes.append)
        info = paths.clone_version(src)
    except paths.CloneNotFound as exc:
        info = {"error": str(exc)}

    info["tstack"] = __version__
    info["platform"] = plat.kind()

    if as_json:
        if notes:
            info["notes"] = notes
        return json.dumps(info, indent=2)

    if "error" in info:
        return f"tstack {__version__} ({plat.kind()}) - {info['error']}"
    dirty = " (dirty)" if info["dirty"] else ""
    return "\n".join(
        [
            f"tstack {__version__}  platform {info['platform']}",
            f"  clone   {info['path']}",
            f"  commit  {info['short']} on {info['branch']}{dirty}",
            f"          {info['subject']}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if not args or args[0] in ("-h", "--help", "help"):
        print(render_help())
        return EXIT_OK

    if args[0] in ("-V", "--version"):
        print(render_version(as_json="--json" in args[1:]))
        return EXIT_OK

    name, rest = args[0], args[1:]
    cmd = registry.get(name)
    if cmd is None:
        print(f"tstack: unknown command '{name}'", file=sys.stderr)
        print(f"  try: {', '.join(registry.names())}", file=sys.stderr)
        return EXIT_USAGE

    if not cmd.is_supported():
        print(f"tstack {name}: not available on {plat.kind()}.", file=sys.stderr)
        return EXIT_USAGE

    if not cmd.is_ported():
        # Reached only by running main.py directly, or by a shim older than the
        # registry. Both are worth naming rather than failing obscurely.
        print(
            f"tstack {name}: still implemented in the shell ({cmd.impl()}); "
            f"run 'tstack {name}' so the shim can route it.",
            file=sys.stderr,
        )
        return EXIT_USAGE

    module = __import__(f"tstack.commands.{name}", fromlist=["main"])
    return int(module.main(rest))
