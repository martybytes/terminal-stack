"""ttsd entry point.

    python -m ttsd [daemon]            # run (tray on the main thread)
    python -m ttsd hook ...            # console-free lifecycle hook client
    python -m ttsd --no-tray           # run headless (debugging)
    python -m ttsd --simulate f.json   # push one fixture through the pipeline
    python -m ttsd --restore-volumes   # oneshot stale-duck repair (ts-doctor)
    python -m ttsd history [--dupes]   # what was said, and what was suppressed
    python -m ttsd mute [on|off]       # absolute mute, honoured by every path
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .audio_duck import AudioController, restore_volumes_oneshot
from .config import Config, load_or_create_token, logs_dir, state_dir
from .events import parse_event
from . import history as history_store
from . import hotkey, mute
from .hooks import direct_speak, direct_speak_file, submit_hook, test_payload
from .pipeline import Dispatcher
from .playback import Playback
from .registry import Registry
from .scheduler import Scheduler, SchedulerConfig
from .server import App, Listener
from .summarize import Summarizer
from .synth import Synth
from .wez import WezInfo
from .winio import read_stdin_bytes, write_stdout

log = logging.getLogger("ttsd")


def _setup_logging(console: bool) -> Path:
    path = logs_dir() / "ttsd.log"
    handlers: list[logging.Handler] = []
    try:
        logs_dir().mkdir(parents=True, exist_ok=True)
        handlers.append(logging.handlers.RotatingFileHandler(
            path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"))
    except OSError:
        # Losing the log is a nuisance; dying here is a fault. This runs before a single
        # word is spoken, so an unwritable state root must not take the process with it.
        handlers.append(logging.NullHandler())
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
        handlers=handlers,
    )
    return path


def _nudge_daemon_stop() -> None:
    """Ask a running daemon to cut off the utterance in flight.

    The sentinel is already written by the time this runs, so the mute holds whether or not
    anyone answers -- this only buys the barge-in, which needs the process that owns the
    audio.
    """
    try:
        port = int(Config().get("daemon.port", 8890))
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/mute", method="POST",
            data=json.dumps({"enabled": True, "by": "cli"}).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-TS-Token": load_or_create_token()})
        with urllib.request.urlopen(request, timeout=0.4):
            pass
    except (OSError, ValueError):
        pass  # no daemon, or it is busy; the mute itself is already in effect


def _cli_mute(arg: str) -> int:
    """`mute` toggles; `mute on|off|status` is explicit. One line of output, always."""
    want = arg.strip().lower()
    if want in ("status", "show"):
        write_stdout(mute.describe() + "\n")
        return 0
    if want in ("on", "mute"):
        target = True
    elif want in ("off", "unmute"):
        target = False
    elif want in ("", "toggle"):
        target = not mute.is_muted()
    else:
        write_stdout("usage: mute [on|off|status]\n")
        return 2

    ok = mute.mute(by="cli") if target else mute.unmute()
    if target:
        _nudge_daemon_stop()
    if not ok:
        write_stdout(f"tts: could not {'mute' if target else 'unmute'} "
                     f"({mute.mute_path()})\n")
        return 1
    write_stdout(mute.describe() + "\n")
    return 0


def _print_history(limit: int, dupes: bool, within: float, check: bool = False) -> int:
    """Render the utterance history for `ts-config tts history`.

    One formatter for both shells: bash calls this through WSL interop and pwsh calls it
    directly, so there is no parallel implementation to keep in sync.
    """
    db = history_store.db_path()
    if check:
        # One line, stable keys, ASCII: ts-doctor parses this with shell string ops.
        s = history_store.summary(dupe_window=within)
        silent = s["daemon_silent_for"]
        write_stdout(f"spoken={s['spoken']} deduped={s['deduped']} dupes={s['dupes']} "
                     f"daemon_silent_for={'-' if silent is None else int(silent)}\n")
        return 0
    if dupes:
        rows = history_store.duplicates(within_sec=within)
        write_stdout(f"tts history - sessions that spoke twice inside {within:.0f}s "
                     f"(last 24h)\n")
        if not rows:
            write_stdout("  none - no duplicate speech recorded\n")
            return 0
        for r in rows:
            write_stdout(
                f"  {r['session_key']}  p{r['priority']}  {r['extra']} extra utterance(s), "
                f"closest {r['closest_sec']:.1f}s\n"
                f"      first: {(r['first_line'] or '')[:88]}\n"
                f"      then : {(r['later_line'] or '')[:88]}\n")
        return 0

    rows = history_store.recent(limit)
    write_stdout(f"tts history - last {len(rows)} decision(s) of {limit} requested\n")
    if not rows:
        write_stdout(f"  nothing recorded yet ({db})\n")
        return 0
    for r in reversed(rows):  # oldest first, so a burst reads top to bottom
        stamp = time.strftime("%H:%M:%S", time.localtime(r["ts"]))
        played = f"{r['play_ms'] / 1000:.1f}s" if r.get("play_ms") else ""
        where = "daemon" if r.get("daemon") else "direct"
        write_stdout(
            f"  {stamp}  {r['decision']:<12} p{r['priority'] if r['priority'] is not None else '?'}"
            f" {r['state'] or '-':<10} {where:<6} {r['engine'] or '':<9}{played:<6}"
            f"  {(r['line'] or '')[:64]}\n")
    return 0


def _build_version() -> str:
    """Build-time Git SHA in frozen builds; Git fallback only in source mode."""
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        try:
            return (Path(frozen_root) / "ttsd-build-version.txt").read_text(
                encoding="utf-8").strip() or "unknown"
        except OSError:
            return "unknown"
    clone = Path(__file__).resolve().parents[3]  # ttsd/ → tts-daemon/ → bootstrap/ → clone
    try:
        import subprocess

        return subprocess.run(["git", "-C", str(clone), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=5,
                              check=True).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _wsl_gateway_ip() -> str | None:
    """Windows-side IP of the WSL NAT adapter, if one exists."""
    try:
        import psutil

        for name, addresses in psutil.net_if_addrs().items():
            if not name.lower().startswith("vethernet (wsl"):
                continue
            for address in addresses:
                if address.family == socket.AF_INET and address.address:
                    return str(address.address)
    except Exception as exc:  # noqa: BLE001 — loopback still works without WSL listener
        log.debug("WSL adapter discovery failed: %s", exc)
    return None


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as resp:
            return resp.status == 200
    except OSError:
        return False


def _build(cfg: Config, version: str) -> App:
    registry = Registry(
        voice_pool=list(cfg.get("voices.pool", []) or []),
        per_session_voice=bool(cfg.get("voices.perSession", False)),
        ttl_min=float(cfg.get("daemon.sessionTtlMin", 240)),
        persist_path=state_dir() / "sessions.json",
    )
    scheduler = Scheduler(SchedulerConfig(
        coalesce_sec=float(cfg.get("daemon.coalesceSec", 1.8)),
        coalesce_cap_sec=float(cfg.get("daemon.coalesceCapSec", 4.0)),
        done_max_age_sec=float(cfg.get("daemon.doneMaxAgeSec", 20)),
        interactive_max_age_sec=float(cfg.get("daemon.interactiveMaxAgeSec", 120)),
        max_queue=int(cfg.get("daemon.maxQueue", 12)),
        cursor_hold_sec=float(cfg.get("daemon.cursor.holdSec", 3)),
        cursor_cooldown_sec=float(cfg.get("daemon.cursor.cooldownSec", 15)),
    ))
    playback = Playback()
    audio = AudioController(cfg, state_dir() / "duck-snapshot.json", playback)
    synth = Synth(cfg)
    dispatcher = Dispatcher(cfg, scheduler, registry, Summarizer(cfg), synth,
                            playback, audio, WezInfo())
    return App(cfg, scheduler, registry, dispatcher, audio, synth,
               version=version, token=load_or_create_token())


def _simulate(app: App, fixture: Path) -> int:
    ev = parse_event(json.loads(fixture.read_text(encoding="utf-8")))
    app.audio.start()
    app.registry.touch(ev.session_key, ev.source, ev.project_name,
                       ev.project_dir, ev.pane, ev.state)
    app.scheduler.submit(ev)
    app.dispatcher.start()
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if app.scheduler.pending_count() == 0 and app.dispatcher.spoken > 0:
            break
        time.sleep(0.2)
    app.dispatcher.stop()
    app.audio.stop()
    if app.dispatcher.spoken:
        print(f"spoke: {app.dispatcher.last_line}")
        return 0
    print("nothing spoken (suppressed, stale, or synth failed — see log)")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ttsd")
    parser.add_argument("command", nargs="?", default="daemon",
                        choices=("daemon", "hook", "test", "simulate",
                                 "restore-volumes", "version", "history", "mute",
                                 "_direct"))
    parser.add_argument("command_arg", nargs="?")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--simulate", metavar="EVENT_JSON")  # legacy spelling
    parser.add_argument("--restore-volumes", action="store_true")  # legacy spelling
    parser.add_argument("--source", default="claude")
    parser.add_argument("--event", default="stop")
    parser.add_argument("--state", default="waiting")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--dupes", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--within", type=float, default=8.0)
    args = parser.parse_args(argv)

    if args.command == "version":
        write_stdout(_build_version() + "\n")
        return 0
    if args.command == "mute":
        return _cli_mute(args.command_arg or "")
    if args.command == "history":
        # Reads the database directly rather than asking the daemon, because the times you
        # most want this are exactly the times the daemon is not running.
        return _print_history(args.limit, args.dupes, args.within, args.check)
    if args.command == "hook":
        result = submit_hook(args.source, args.event, args.state, read_stdin_bytes())
        if args.source.lower() == "cursor":
            write_stdout("{}\n")
        return result
    if args.command == "_direct":
        if not args.command_arg:
            return 2
        _setup_logging(console=False)
        return direct_speak_file(Path(args.command_arg))
    if args.command == "test":
        _setup_logging(console=False)
        payload = test_payload(args.source)
        cfg = Config()
        if cfg.get("daemon.enabled", False):
            from .hooks import _post  # internal test path, same request as hooks

            if _post(cfg, payload):
                return 0
        return direct_speak(payload)
    if args.command == "restore-volumes" or args.restore_volumes:
        return restore_volumes_oneshot(state_dir() / "duck-snapshot.json")

    simulate_path = args.command_arg if args.command == "simulate" else args.simulate
    log_path = _setup_logging(console=args.no_tray or bool(simulate_path))
    cfg = Config()
    version = _build_version()

    if simulate_path:
        return _simulate(_build(cfg, version), Path(simulate_path))

    port = args.port or int(cfg.get("daemon.port", 8890))
    app = _build(cfg, version)

    # A dashboard restart spawns us while the previous daemon is still listening, so wait
    # for it to let go before binding. Without this the replacement would see a healthy
    # daemon on the port, exit 0 as designed, and leave nothing running once the old one
    # shut down.
    restart_wait = 0.0
    try:
        restart_wait = float(os.environ.get("CC_TTS_RESTART_WAIT") or 0)
    except ValueError:
        restart_wait = 0.0
    deadline = time.time() + restart_wait
    loopback = None
    while loopback is None:
        try:
            loopback = Listener(app, "127.0.0.1", port, requires_token=False)
        except OSError:
            if time.time() < deadline:
                time.sleep(0.25)
                continue
            if _already_running(port):
                log.info("ttsd already healthy on port %d — exiting", port)
                return 0
            log.error("port %d is taken by something that is not a healthy ttsd", port)
            return 1
    if restart_wait:
        log.info("bound port %d after waiting for the previous daemon", port)

    listeners = [loopback]
    gateway = _wsl_gateway_ip()
    if gateway:
        try:
            listeners.append(Listener(app, gateway, port, requires_token=True))
            log.info("WSL-facing listener on %s:%d (token required)", gateway, port)
        except OSError as exc:
            log.warning("WSL-facing listener failed (%s) — loopback only", exc)

    app.audio.start()
    app.dispatcher.start()
    for listener in listeners:
        listener.start()
    log.info("ttsd %s listening on port %d", version[:12], port)

    tray_holder: dict = {"icon": None}
    stop_evt = threading.Event()

    def _shutdown(icon=None) -> None:
        log.info("shutting down")
        # Before the listeners: a log stream is sitting in a sleep loop and polls this.
        app.stopping.set()
        for listener in listeners:
            listener.shutdown()
        app.dispatcher.stop()
        app.audio.stop()
        stop_evt.set()
        live_icon = icon or tray_holder.get("icon")
        if live_icon is not None:
            live_icon.stop()

    app.on_shutdown = _shutdown

    def _toggle_mute_from_hotkey() -> None:
        if mute.is_muted():
            mute.unmute()
        else:
            mute.mute(by="hotkey")
            app.dispatcher.playback.stop()  # silence means now
        live = tray_holder.get("icon")
        refresh = getattr(live, "ts_refresh", None)
        if refresh is not None:
            refresh()

    # Only while the daemon runs, which is why it is a convenience over the sentinel and
    # not the mute itself. A chord another app already owns logs once and is dropped.
    hotkey.start(str(cfg.get("hotkey", "") or ""), _toggle_mute_from_hotkey)

    if args.no_tray:
        try:
            stop_evt.wait()
        except KeyboardInterrupt:
            _shutdown()
        return 0

    try:
        from .tray import build_icon
        icon = build_icon(app, log_path, on_quit=_shutdown)
        tray_holder["icon"] = icon
        icon.run()  # blocks the main thread until Quit or /v1/shutdown
    except Exception as exc:  # noqa: BLE001 — tray is optional chrome
        log.warning("tray unavailable (%s) — running headless", exc)
        try:
            stop_evt.wait()
        except KeyboardInterrupt:
            _shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
