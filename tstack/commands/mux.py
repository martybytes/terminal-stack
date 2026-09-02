"""`tstack mux` - the WezTerm multiplexer domain, and the live mux server.

Replaces bootstrap/ts-mux.sh (301 lines) and Invoke-TsMux in $PROFILE. The
setting lives with the rest of the saved config (chezmoi `[data]` weztermMux,
mirrored to %LOCALAPPDATA%\\terminal-stack\\config.json) and renders into
.wezterm.lua as `local MUX_ENABLED = '<on|off>' == 'on'`. Nothing here edits
.wezterm.lua directly.

On WSL the GUI, the mux server and the rendered config are all on the WINDOWS
side, so every process command goes through interop (tasklist.exe / taskkill.exe /
wezterm.exe) and never the Linux process table. That is not an optimisation: a
`pgrep wezterm-mux-server` inside WSL finds nothing while a healthy server runs
three feet away on the same machine.

The mux server is never auto-restarted. It loads its own copy of .wezterm.lua, so
a config change does not reach it -- but restarting it kills every live pane, so
that stays a deliberate, confirmed command.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .. import paths, proc, store
from .. import platform as plat

HELP = """tstack mux - WezTerm multiplexer domain: keep panes alive when the GUI dies.

Usage:
  tstack mux [status]   the setting, the mux server, and the panes it hosts
  tstack mux on         host panes in the mux domain (unix domain "main")
  tstack mux off        spawn panes locally (the default)
  tstack mux list       wezterm cli list - every pane the mux knows about
  tstack mux kill       stop wezterm-mux-server       [KILLS EVERY PANE IT HOSTS]
  tstack mux restart    stop it, then start a fresh one, so it re-reads the config
  tstack mux reset      back to default: off + re-apply + kill + clear stale sockets
  tstack mux -h         this help

  -y, --yes         skip the confirmation for kill / restart / reset

With the mux on, your shells run inside wezterm-mux-server instead of the GUI, so
a GUI crash leaves every pane (and everything running in it) alive and relaunching
WezTerm reattaches. The costs are why it is off by default: the mux server loads
its OWN copy of .wezterm.lua, so a config change needs "tstack mux restart" - which
kills every pane - and not just a GUI reload; and the Claude per-pane tint needs
pane:inject_output, which mux panes do not have.

on/off re-render .wezterm.lua and take effect for newly spawned tabs; relaunch
WezTerm for a clean switch. Panes already hosted in the mux stay there until you
close them or run "tstack mux kill". The setting is saved with the rest of the config
(chezmoi [data] weztermMux / config.json weztermMux) and shown by "tstack config show"."""

WINDOWS_WEZTERM = "/mnt/c/Program Files/WezTerm"
_MUX_LINE = re.compile(r"^local MUX_ENABLED = '(on|off)'", re.MULTILINE)
_DEFAULT_DOMAIN = re.compile(r"^config\.default_domain = 'main'", re.MULTILINE)


# ----------------------------------------------------------------- binaries


def wez_cli() -> str | None:
    """The `wezterm` CLI. On WSL that is the Windows .exe, because the mux it
    talks to is the Windows one."""
    if plat.kind() == plat.WSL:
        found = shutil.which("wezterm.exe")
        if found:
            return found
        candidate = Path(WINDOWS_WEZTERM) / "wezterm.exe"
        return str(candidate) if candidate.exists() else None
    return shutil.which("wezterm")


def mux_bin() -> str | None:
    if plat.kind() == plat.WSL:
        found = shutil.which("wezterm-mux-server.exe")
        if found:
            return found
        candidate = Path(WINDOWS_WEZTERM) / "wezterm-mux-server.exe"
        return str(candidate) if candidate.exists() else None
    return shutil.which("wezterm-mux-server")


def _run(argv: list[str], timeout: int = 30) -> subprocess.CompletedProcess | None:
    return proc.capture(argv, timeout=timeout)


def mux_pids() -> list[str]:
    """Every running mux server's pid.

    Windows-side on WSL, through tasklist.exe. CSV output, so a localized
    "INFO: No tasks are running..." line cannot be mistaken for a row.
    """
    if plat.kind() in (plat.WSL, plat.WINDOWS):
        tasklist = (
            "/mnt/c/Windows/System32/tasklist.exe" if plat.kind() == plat.WSL else "tasklist.exe"
        )
        if plat.kind() == plat.WSL and not Path(tasklist).exists():
            return []
        got = _run([tasklist, "/FI", "IMAGENAME eq wezterm-mux-server.exe", "/NH", "/FO", "CSV"])
        if not got or got.returncode != 0:
            return []
        pids = []
        for line in got.stdout.replace("\r", "").splitlines():
            if line.startswith('"wezterm-mux-server.exe"'):
                fields = line.split('","')
                if len(fields) > 1:
                    pids.append(fields[1].strip('"'))
        return pids
    got = _run(["pgrep", "-f", "(^|/)wezterm-mux-server"])
    if not got or got.returncode != 0:
        return []
    return [line.strip() for line in got.stdout.splitlines() if line.strip()]


# ------------------------------------------------------------ rendered config


def rendered_cfg() -> Path | None:
    """The .wezterm.lua the GUI actually loads, which on WSL is the Windows one."""
    if plat.kind() == plat.WSL:
        user = plat.windows_username()
        if not user:
            return None
        candidate = Path(f"/mnt/c/Users/{user}/.wezterm.lua")
        return candidate if candidate.is_file() else None
    candidate = Path.home() / ".wezterm.lua"
    return candidate if candidate.is_file() else None


def rendered_mux() -> str | None:
    """What the rendered config says, which can differ from the saved setting.

    That difference is the whole reason status prints both: a saved `on` that was
    never applied looks identical to a working one from the setting alone.
    """
    path = rendered_cfg()
    if not path:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found = _MUX_LINE.search(text)
    if found:
        return found.group(1)
    # A config rendered before this toggle existed: the domain was unconditional.
    # Line-anchored, like the bash twin's grep: the same assignment appears
    # indented inside a conditional block, where it means the opposite.
    if _DEFAULT_DOMAIN.search(text):
        return "on (pre-toggle)"
    return "off (pre-toggle)"


def sock_dirs() -> list[Path]:
    """WezTerm's runtime dirs, where a crashed server leaves a stale socket."""
    out = []
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        out.append(Path(runtime) / "wezterm")
    out.append(Path.home() / ".local" / "share" / "wezterm")
    if plat.kind() == plat.WSL:
        user = plat.windows_username()
        if user:
            out.append(Path(f"/mnt/c/Users/{user}/AppData/Local/wezterm"))
    return out


# -------------------------------------------------------------------- actions


def _confirm(prompt: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    try:
        with open("/dev/tty", "r+", encoding="utf-8") as tty:
            tty.write(f"{prompt} [y/N]: ")
            tty.flush()
            answer = (tty.readline() or "").strip()
    except OSError:
        if not sys.stdin.isatty():
            print(
                "tstack mux: no terminal to confirm on - re-run with -y if you mean it.",
                file=sys.stderr,
            )
            return False
        try:
            answer = input(f"{prompt} [y/N]: ").strip()
        except (OSError, EOFError):
            return False
    if answer.lower() in ("y", "yes"):
        return True
    print("aborted.")
    return False


def _apply() -> None:
    print("==> applying...")
    chezmoi = plat.find_chezmoi()
    if chezmoi and Path(chezmoi).exists():
        subprocess.run([chezmoi, "apply"], check=False, start_new_session=True)
    else:
        print("    (no chezmoi here; the Windows sync renders this side)")
    print("==> done.")


def show_status() -> int:
    setting = store.get("weztermMux", "off")
    print("tstack mux:")
    print(f"  setting  : {setting}   (saved as weztermMux)")

    rendered = rendered_mux()
    if rendered is None:
        print("  rendered : (no .wezterm.lua found - run 'chezmoi apply')")
    elif rendered != setting:
        print(
            f"  rendered : {rendered}   !! stale - run 'chezmoi apply' (Windows: sync-windows.ps1)"
        )
    else:
        print(f"  rendered : {rendered}   ({rendered_cfg()})")

    pids = mux_pids()
    if pids:
        print(f"  server   : running (pid {' '.join(pids)})")
    else:
        print("  server   : not running")

    cli = wez_cli()
    if cli:
        got = _run([cli, "cli", "list"])
        if got and got.returncode == 0:
            panes = len([ln for ln in got.stdout.splitlines()[1:] if ln.strip()])
            print(f"  panes    : {panes}   ('tstack mux list' for detail)")

    if setting == "off" and pids:
        print("  note     : panes spawned while the mux was on are still hosted by it;")
        print("             they stay alive until you close them or run 'tstack mux kill'.")
    return 0


def set_mux(want: str) -> int:
    current = store.get("weztermMux", "off")
    if current == want:
        print(f"==> mux already {want}; re-applying anyway to refresh the rendered config.")
    store.set("weztermMux", want)
    store.chezmoi_init()
    _apply()
    if want == "on":
        print("    Panes now spawn into the mux domain 'main'. Relaunch WezTerm for a")
        print("    clean switch; 'tstack mux status' shows the server once it starts.")
    else:
        print("    New tabs spawn locally again. Panes already hosted by the mux stay")
        print("    there until you close them or run 'tstack mux kill'.")
    return 0


def do_list() -> int:
    cli = wez_cli()
    if not cli:
        print("tstack mux: wezterm CLI not found on PATH.", file=sys.stderr)
        return 1
    return subprocess.run([cli, "cli", "list"], check=False, start_new_session=True).returncode


def do_kill(assume_yes: bool) -> int:
    pids = mux_pids()
    if not pids:
        print("==> wezterm-mux-server is not running.")
        return 0
    if not _confirm(
        f"Stop wezterm-mux-server (pid {' '.join(pids)})? Every pane it hosts dies - "
        "including this one, if you are in one",
        assume_yes,
    ):
        return 1
    if plat.kind() in (plat.WSL, plat.WINDOWS):
        taskkill = (
            "/mnt/c/Windows/System32/taskkill.exe" if plat.kind() == plat.WSL else "taskkill.exe"
        )
        _run([taskkill, "/IM", "wezterm-mux-server.exe", "/F"])
    else:
        _run(["pkill", "-f", "(^|/)wezterm-mux-server"])
        for _ in range(5):
            if not mux_pids():
                break
            time.sleep(1)
        if mux_pids():
            _run(["pkill", "-9", "-f", "(^|/)wezterm-mux-server"])
    if mux_pids():
        print("!! wezterm-mux-server is still running - kill it by hand.", file=sys.stderr)
        return 1
    print("==> wezterm-mux-server stopped.")
    return 0


def do_start() -> int:
    if mux_pids():
        print("==> wezterm-mux-server is already running.")
        return 0
    binary = mux_bin()
    if not binary:
        print(
            "tstack mux: wezterm-mux-server not found - relaunch WezTerm and it will spawn one.",
            file=sys.stderr,
        )
        return 1
    print("==> starting wezterm-mux-server --daemonize")
    got = _run([binary, "--daemonize"])
    if not got or got.returncode != 0:
        print("tstack mux: start failed - relaunch WezTerm and it will spawn one.", file=sys.stderr)
        return 1
    return 0


def clear_sockets() -> int:
    cleared = 0
    for directory in sock_dirs():
        if not directory.is_dir():
            continue
        for candidate in [directory / "sock", *directory.glob("gui-sock-*")]:
            if candidate.exists():
                try:
                    candidate.unlink()
                    cleared += 1
                except OSError:
                    pass
    print(f"==> cleared {cleared} stale socket file(s)")
    return 0


def do_reset(assume_yes: bool) -> int:
    if not _confirm(
        "Reset the WezTerm mux: set it off, re-apply, stop the server "
        "(every pane it hosts dies) and clear stale sockets",
        assume_yes,
    ):
        return 1
    store.set("weztermMux", "off")
    store.chezmoi_init()
    _apply()
    do_kill(assume_yes=True)
    clear_sockets()
    print("==> mux reset to the default (off).")
    return 0


# ----------------------------------------------------------------- entry point


def main(argv: list[str]) -> int:
    # Help before anything else: `tstack mux -h` must work on a box where the
    # clone or the config store is the very thing that is broken.
    assume_yes = False
    command = ""
    for item in argv:
        if item in ("-h", "--help", "help"):
            print(HELP)
            return 0
        if item in ("-y", "--yes"):
            assume_yes = True
        elif item.startswith("-"):
            print(f"tstack mux: unknown flag '{item}' (try: tstack mux -h)", file=sys.stderr)
            return 2
        elif not command:
            command = item
        else:
            print(f"tstack mux: unexpected argument '{item}'", file=sys.stderr)
            return 2

    if command in ("", "status"):
        return show_status()
    if command in ("on", "off"):
        # A clone is only needed for the write path; status must work without one.
        try:
            paths.resolve_source_dir()
        except paths.CloneNotFound as exc:
            print(f"tstack mux: {exc}", file=sys.stderr)
            return 1
        return set_mux(command)
    if command == "list":
        return do_list()
    if command == "kill":
        return do_kill(assume_yes)
    if command == "restart":
        killed = do_kill(assume_yes)
        return killed if killed else do_start()
    if command == "reset":
        return do_reset(assume_yes)
    print(
        f"tstack mux: unknown command '{command}' (status, on, off, list, kill, restart, reset)",
        file=sys.stderr,
    )
    return 2
