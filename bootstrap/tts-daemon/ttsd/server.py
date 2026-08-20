"""Localhost HTTP API.

Two listeners share one handler: 127.0.0.1 (always, no token) and — when a
NAT-mode WSL adapter exists — the WSL gateway IP, which requires the
X-TS-Token header. Handler threads only validate and enqueue; nothing here
blocks on speech.
"""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import PROTOCOL_VERSION
from .events import EventError, parse_event

log = logging.getLogger(__name__)

_MAX_BODY = 256 * 1024


class App:
    """Shared wiring passed to both listeners."""

    def __init__(self, cfg, scheduler, registry, dispatcher, audio, synth,
                 version: str, token: str) -> None:
        self.cfg = cfg
        self.scheduler = scheduler
        self.registry = registry
        self.dispatcher = dispatcher
        self.audio = audio
        self.synth = synth
        self.version = version
        self.token = token
        self.received = 0


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ttsd"

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:  # quiet http.server
        log.debug("%s %s", self.address_string(), fmt % args)

    def _authorized(self) -> bool:
        if not getattr(self.server, "requires_token", False):
            return True
        return self.headers.get("X-TS-Token", "") == self.app.token

    def _send(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > _MAX_BODY:
            return None
        try:
            return json.loads(self.rfile.read(length))
        except (ValueError, OSError):
            return None

    # ── GET ───────────────────────────────────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(401, {"error": "bad token"})
            return
        app = self.app
        if self.path == "/healthz":
            self._send(200, {
                "ok": True,
                "v": PROTOCOL_VERSION,
                "version": app.version,
                "queue": app.scheduler.pending_count(),
                "audio": app.audio.state,
                "dnd": app.dispatcher.dnd_active(),
            })
        elif self.path == "/v1/status":
            self._send(200, {
                "version": app.version,
                "received": app.received,
                "spoken": app.dispatcher.spoken,
                "suppressed": app.dispatcher.suppressed,
                "dropped": app.scheduler.dropped,
                "lastLine": app.dispatcher.last_line,
                "lastEngine": app.synth.last_engine,
                "queue": app.scheduler.pending_summary(),
                "audio": app.audio.state,
                "dnd": app.dispatcher.dnd_active(),
                "summarizerMode": app.cfg.get("summarize.mode", "template"),
                "musicMode": app.cfg.get("music.mode", "duck"),
            })
        elif self.path == "/v1/sessions":
            self._send(200, {"sessions": [
                {
                    "key": s.session_key,
                    "project": s.project_name,
                    "spoken": app.registry.spoken_name(s),
                    "ordinal": s.ordinal,
                    "voice": s.voice,
                    "pane": s.pane,
                    "lastState": s.last_state,
                    "lastSeen": s.last_seen,
                }
                for s in app.registry.all()
            ]})
        elif self.path == "/v1/dnd":
            self._send(200, {"enabled": app.dispatcher.dnd_active()})
        else:
            self._send(404, {"error": "not found"})

    # ── POST ──────────────────────────────────────────────────────────────

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(401, {"error": "bad token"})
            return
        app = self.app
        if self.path == "/v1/event":
            body = self._read_json()
            if body is None:
                self._send(400, {"error": "invalid JSON"})
                return
            try:
                ev = parse_event(body)
            except EventError as exc:
                self._send(422, {"error": str(exc)})
                return
            app.received += 1
            if ev.is_session_end:
                app.registry.end(ev.session_key)
            else:
                app.registry.touch(ev.session_key, ev.source, ev.project_name,
                                   ev.project_dir, ev.pane, ev.state)
            app.scheduler.submit(ev)
            self._send(202, {"queued": True})
        elif self.path == "/v1/speak":
            body = self._read_json() or {}
            text = str(body.get("text") or "")[:500]
            if not text:
                self._send(400, {"error": "text required"})
                return
            threading.Thread(
                target=self._speak_raw, args=(text, str(body.get("voice") or "")),
                daemon=True, name="ttsd-speak-raw",
            ).start()
            self._send(202, {"queued": True})
        elif self.path == "/v1/config/reload":
            app.cfg.reload()
            self._send(200, {"ok": True})
        elif self.path == "/v1/duck/release":
            app.audio.force_restore()
            self._send(200, {"ok": True})
        elif self.path == "/v1/dnd":
            body = self._read_json() or {}
            enabled = bool(body.get("enabled", True))
            minutes = body.get("minutes")
            app.dispatcher.set_dnd(enabled, float(minutes) if minutes else None)
            self._send(200, {"enabled": app.dispatcher.dnd_active()})
        else:
            self._send(404, {"error": "not found"})

    def _speak_raw(self, text: str, voice: str) -> None:
        """Test path: bypasses queue rules, still ducks."""
        app = self.app
        result = app.synth.synthesize(text, voice)
        if result is None:
            return
        app.audio.hold(None)
        try:
            if result.media is not None:
                app.dispatcher.playback.play(result.media)
            else:
                app.dispatcher.playback.speak_sapi(result.sapi_text)
        finally:
            app.audio.release()


class Listener(threading.Thread):
    def __init__(self, app: App, host: str, port: int, requires_token: bool) -> None:
        super().__init__(name=f"ttsd-http-{host}", daemon=True)
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.app = app  # type: ignore[attr-defined]
        self.httpd.requires_token = requires_token  # type: ignore[attr-defined]
        self.httpd.daemon_threads = True

    def run(self) -> None:
        self.httpd.serve_forever(poll_interval=0.5)

    def shutdown(self) -> None:
        self.httpd.shutdown()
