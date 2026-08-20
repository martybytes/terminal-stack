"""ttsd entry point.

    python -m ttsd                     # run (tray on the main thread)
    python -m ttsd --no-tray           # run headless (debugging)
    python -m ttsd --simulate f.json   # push one fixture through the pipeline
    python -m ttsd --restore-volumes   # oneshot stale-duck repair (ts-doctor)
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from .audio_duck import AudioController, restore_volumes_oneshot
from .config import Config, load_or_create_token, logs_dir, state_dir
from .events import parse_event
from .pipeline import Dispatcher
from .playback import Playback
from .registry import Registry
from .scheduler import Scheduler, SchedulerConfig
from .server import App, Listener
from .summarize import Summarizer
from .synth import Synth
from .wez import WezInfo

log = logging.getLogger("ttsd")


def _setup_logging(console: bool) -> Path:
    logs_dir().mkdir(parents=True, exist_ok=True)
    path = logs_dir() / "ttsd.log"
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000,
                                             backupCount=3, encoding="utf-8")
    ]
    if console:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname).1s %(name)s: %(message)s",
        handlers=handlers,
    )
    return path


def _clone_version() -> str:
    """Git SHA of the clone this package runs from (staleness checks)."""
    clone = Path(__file__).resolve().parents[3]  # ttsd/ → tts-daemon/ → bootstrap/ → clone
    try:
        return subprocess.run(
            ["git", "-C", str(clone), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def _wsl_gateway_ip() -> str | None:
    """Windows-side IP of the WSL NAT adapter, if one exists."""
    script = ("Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | "
              "Where-Object { $_.InterfaceAlias -like 'vEthernet (WSL*' } | "
              "Select-Object -First 1 -ExpandProperty IPAddress")
    for shell in ("pwsh", "powershell"):
        try:
            out = subprocess.run(
                [shell, "-NoLogo", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=10, check=True,
            ).stdout.strip()
            if out:
                return out
        except (subprocess.SubprocessError, OSError):
            continue
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
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-tray", action="store_true")
    parser.add_argument("--simulate", metavar="EVENT_JSON")
    parser.add_argument("--restore-volumes", action="store_true")
    args = parser.parse_args(argv)

    if args.restore_volumes:
        return restore_volumes_oneshot(state_dir() / "duck-snapshot.json")

    log_path = _setup_logging(console=args.no_tray or bool(args.simulate))
    cfg = Config()
    version = _clone_version()

    if args.simulate:
        return _simulate(_build(cfg, version), Path(args.simulate))

    port = args.port or int(cfg.get("daemon.port", 8890))
    app = _build(cfg, version)

    try:
        loopback = Listener(app, "127.0.0.1", port, requires_token=False)
    except OSError:
        if _already_running(port):
            log.info("ttsd already healthy on port %d — exiting", port)
            return 0
        log.error("port %d is taken by something that is not a healthy ttsd", port)
        return 1

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
        for listener in listeners:
            listener.shutdown()
        app.dispatcher.stop()
        app.audio.stop()
        stop_evt.set()
        live_icon = icon or tray_holder.get("icon")
        if live_icon is not None:
            live_icon.stop()

    app.on_shutdown = _shutdown

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
