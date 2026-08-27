"""Localhost HTTP API.

Two listeners share one handler: 127.0.0.1 (always, no token) and — when a
NAT-mode WSL adapter exists — the WSL gateway IP, which requires the
X-TS-Token header. Handler threads only validate and enqueue; nothing here
blocks on speech.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import PROTOCOL_VERSION, history, mute
from .config import logs_dir
from . import keystore, settings_schema
from .logtail import LogTail, parse_line
from .webui import PAGE
from .events import EventError, parse_event


def _qs_int(query: dict, key: str, default):
    try:
        return int(query.get(key, [default])[0])
    except (TypeError, ValueError):
        return default


def _qs_float(query: dict, key: str, default):
    try:
        return float(query.get(key, [default])[0])
    except (TypeError, ValueError):
        return default

log = logging.getLogger(__name__)

_TEST_NOTE = ("Non-template modes only apply to 'done' announcements. A question, a "
              "permission prompt or an error always uses the template, and a coalesced "
              "multi-session line bypasses every mode.")


def _key_text(described: dict) -> str:
    if not described.get("set"):
        return f"not set (looked in the secret store and ${described.get('envVar')})"
    where = "secret store" if described.get("source") == "store" else "environment"
    tail = described.get("tail")
    return f"set, from the {where}" + (f" (ends {tail})" if tail else "")

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
        self.on_shutdown = None  # wired by __main__; POST /v1/shutdown
        # Set on shutdown so a long-lived log stream stops promptly instead of being left
        # for the interpreter to reap. listener.shutdown() stops the accept loop but says
        # nothing to a response already in progress.
        self.stopping = threading.Event()


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

    def _send_raw(self, code: int, body: bytes, ctype: str) -> None:
        """Non-JSON response. Everything here spoke only JSON before the dashboard."""
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        """Reject a Host header we do not recognise.

        Loopback needs no token, which is safe against other machines and not at all safe
        against a browser: any page can reach 127.0.0.1, and with no Host validation a DNS
        rebinding attack could read this daemon's history and status. The bound address is
        always acceptable, so the WSL-facing listener keeps working for hooks that address
        it by gateway IP.

        A missing Host is allowed: HTTP/1.1 clients must send one and every browser does,
        so the only callers without it are local scripts, and refusing them would break
        working paths to no security benefit.
        """
        host = self.headers.get("Host")
        if not host:
            return True
        name = host.rsplit(":", 1)[0].strip("[]").lower()
        bound = str(self.server.server_address[0])
        return name in {"127.0.0.1", "localhost", "::1", bound.lower()}

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
        if not self._host_ok():
            self._send(403, {"error": "unexpected Host header"})
            return
        app = self.app
        route = self.path.split("?", 1)[0]
        if route in ("/ui", "/ui/", "/dashboard"):
            # The page is same-origin and no route sends CORS headers, so cross-origin
            # script cannot read this token out of the response. That, plus the Host
            # allowlist, is what makes a write endpoint on an unauthenticated loopback
            # port acceptable.
            page = PAGE.replace("__TS_TOKEN__", app.token)
            self._send_raw(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if route == "/v1/config/schema":
            self._send(200, {"fields": settings_schema.public_schema(),
                             "groups": list(settings_schema.GROUPS)})
            return
        if route == "/v1/config/effective":
            self._send(200, self._effective_config())
            return
        if route == "/v1/history/summary":
            # history.summary() was CLI-only. daemon_silent_for is the number that let a
            # fifteen-hour outage pass unnoticed, so a status panel needs it.
            self._send(200, history.summary(
                dupe_window=float(app.cfg.get("debounceSec", 5) or 5)))
            return
        if route == "/v1/logs/stream":
            self._stream_logs()
            return
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
                # Durable answer to "I selected haiku, why does it sound like template".
                # Before these two, a missing API key produced no exception, no log line
                # and no counter, so the only honest report was silence.
                "summarizerDegraded": getattr(app.dispatcher.summarizer, "degraded", 0),
                "summarizerLastDegrade": getattr(
                    app.dispatcher.summarizer, "last_degrade", ""),
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
        elif self.path in ("/v1/mute", "/v1/dnd"):
            self._send(200, dict(mute.state(), enabled=mute.is_muted(),
                                 muted=mute.is_muted(),
                                 describe=mute.describe()))
        elif self.path.split("?", 1)[0] == "/v1/history":
            # Durable counterpart to /v1/status: those counters die with the process.
            query = urllib.parse.parse_qs(urlsplit(self.path).query)
            limit = _qs_int(query, "limit", 50)
            since = _qs_float(query, "since", None)
            if _qs_int(query, "dupes", 0):
                self._send(200, {"duplicates": history.duplicates(
                    within_sec=float(app.cfg.get("debounceSec", 5) or 5), since=since)})
            else:
                self._send(200, {"rows": history.recent(limit=limit, since=since)})
        else:
            self._send(404, {"error": "not found"})

    # ── POST ──────────────────────────────────────────────────────────────

    # Writes need the token on every listener, not just the WSL-facing one. Loopback is
    # unauthenticated, and the Host allowlist does not help here: a cross-site form POST
    # carries the *target* Host, so any page you visit could otherwise mute your machine or
    # write your config. Left deliberately open: /v1/event (every hook posts it and none
    # carries a token), /v1/config/reload (tstack config from pwsh has no token to hand), and
    # /v1/duck/release and /v1/shutdown (the installer calls them, and both are nuisances
    # rather than compromises now that a dead daemon restarts itself on the next hook).
    _TOKEN_ROUTES = frozenset({
        "/v1/config/set", "/v1/secrets/set", "/v1/summarizer/test", "/v1/daemon/restart",
        "/v1/mute", "/v1/dnd", "/v1/speak",
    })

    def _token_ok(self) -> bool:
        return self.headers.get("X-TS-Token", "") == self.app.token

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._send(401, {"error": "bad token"})
            return
        if not self._host_ok():
            self._send(403, {"error": "unexpected Host header"})
            return
        route = self.path.split("?", 1)[0]
        if route in self._TOKEN_ROUTES and not self._token_ok():
            self._send(401, {"error": "this route needs X-TS-Token"})
            return
        app = self.app
        if route == "/v1/config/set":
            self._set_config()
            return
        if route == "/v1/secrets/set":
            body = self._read_json() or {}
            name = str(body.get("name") or "")
            if name not in keystore.KNOWN:
                self._send(400, {"error": "unknown secret"})
                return
            ok = keystore.set_value(name, str(body.get("value") or ""))
            self._send(200 if ok else 500,
                       {"ok": ok, "secret": keystore.describe(
                           name, str(app.cfg.get("summarize.haiku.keyEnv",
                                                 "ANTHROPIC_API_KEY")))})
            return
        if route == "/v1/summarizer/test":
            self._send(200, self._summarizer_test())
            return
        if route == "/v1/daemon/restart":
            self._send(200, {"restarting": True})
            self._restart_daemon()
            return
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
            if mute.is_muted():
                self._send(200, {"muted": True})
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
        elif self.path == "/v1/shutdown":
            self._send(200, {"ok": True})
            if app.on_shutdown is not None:
                threading.Thread(target=app.on_shutdown, daemon=True,
                                 name="ttsd-shutdown").start()
        elif self.path in ("/v1/mute", "/v1/dnd"):
            # /v1/dnd is kept as an alias: it was the documented route, and callers of it
            # now get a mute that persists and that the direct path also honours. The
            # `minutes` field is accepted and ignored -- the mute is sticky by design, so
            # that a mute cannot expire back into a call.
            body = self._read_json() or {}
            if bool(body.get("enabled", True)):
                mute.mute(by=str(body.get("by") or "api"))
                app.dispatcher.playback.stop()
            else:
                mute.unmute()
            self._send(200, {"enabled": mute.is_muted(), "muted": mute.is_muted()})
        else:
            self._send(404, {"error": "not found"})

    def _effective_config(self) -> dict:
        """Every schema key with its effective value, its saved value, and which layer won."""
        app = self.app
        base, local = app.cfg.layers()

        def dig(tree: dict, key: str):
            node = tree
            for part in key.split("."):
                if not isinstance(node, dict) or part not in node:
                    return None, False
                node = node[part]
            return node, True

        values = {}
        for field in settings_schema.FIELDS:
            key = field["key"]
            saved, in_base = dig(base, key)
            override, in_local = dig(local, key)
            values[key] = {
                "effective": app.cfg.get(key, None),
                "saved": saved if in_base else None,
                # "local" means an override is winning; the page says so next to the field,
                # because a change made anywhere else would otherwise look ignored.
                "layer": "local" if in_local else ("saved" if in_base else "default"),
                "override": override if in_local else None,
            }
        env_var = str(app.cfg.get("summarize.haiku.keyEnv", "ANTHROPIC_API_KEY"))
        return {
            "values": values,
            "secrets": {keystore.ANTHROPIC_API_KEY: keystore.describe(
                keystore.ANTHROPIC_API_KEY, env_var)},
        }

    def _set_config(self) -> None:
        body = self._read_json()
        if body is None:
            self._send(400, {"error": "invalid JSON"})
            return
        clean, errors = settings_schema.validate(body.get("updates") or {})
        written = 0
        if clean:
            # One read-modify-write for the whole form, which is what write_local_many
            # exists for: N separate writes was the shape that could destroy the overlay.
            if not self.app.cfg.write_local_many(clean):
                self._send(500, {"error": "could not write local.json", "errors": errors})
                return
            written = len(clean)
            log.info("dashboard wrote %d setting(s): %s", written, ", ".join(sorted(clean)))
        self._send(200, {"written": written, "errors": errors})

    def _summarizer_test(self) -> dict:
        """Run the configured mode and report what actually happened.

        A missing API key makes haiku produce exactly the template line, with no exception
        and no log entry, so a test that only played audio could not tell the two apart.
        This one names the mode, the key source, the latency and the fall-back reason.
        """
        import time as _time

        from .events import Event
        from .registry import Registry
        from .summarize import Summarizer

        app = self.app
        mode = str(app.cfg.get("summarize.mode", "template"))
        env_var = str(app.cfg.get("summarize.haiku.keyEnv", "ANTHROPIC_API_KEY"))
        key = keystore.describe(keystore.ANTHROPIC_API_KEY, env_var)
        sample = ("Rewrote the retry logic so a stale token refreshes once instead of "
                  "failing every request for the life of the session, and added tests.")
        event = Event(source="claude", event="stop", state="waiting",
                      session_key="dashboard:test", project_name="terminal-stack",
                      text=sample)
        # A throwaway Summarizer, so a test never disturbs the daemon's own counters.
        summarizer = Summarizer(app.cfg)
        started = _time.monotonic()
        try:
            line = summarizer.line_for_batch([event], Registry()) or ""
        except Exception as exc:  # noqa: BLE001 - a test must report, never 500
            return {"mode": mode, "ran": "error", "key": _key_text(key), "ms": 0,
                    "fell_back": True, "reason": f"{type(exc).__name__}: {exc}",
                    "line": "", "note": _TEST_NOTE}
        elapsed = int((_time.monotonic() - started) * 1000)
        fell_back = mode != "template" and summarizer.degraded > 0
        return {
            "mode": mode,
            "ran": "template" if (fell_back or mode == "template") else mode,
            "key": _key_text(key),
            "ms": elapsed,
            "fell_back": fell_back,
            "reason": summarizer.last_degrade,
            "line": line,
            "note": _TEST_NOTE,
        }

    def _restart_daemon(self) -> None:
        """Spawn a replacement that waits for this one to release the port, then stop."""
        import subprocess
        import sys as _sys

        from .process import popen_hidden

        def _go() -> None:
            time.sleep(0.2)  # let the 200 reach the browser first
            command = ([_sys.executable, "daemon"] if getattr(_sys, "frozen", False)
                       else [_sys.executable, "-m", "ttsd", "daemon"])
            env = dict(os.environ)
            env["CC_TTS_RESTART_WAIT"] = "12"
            if getattr(_sys, "frozen", False):
                env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
            try:
                popen_hidden(command, detached=True, env=env,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True)
            except OSError as exc:
                log.warning("restart spawn failed: %s", exc)
                return
            log.info("restarting on request from the dashboard")
            if self.app.on_shutdown is not None:
                self.app.on_shutdown()

        threading.Thread(target=_go, daemon=True, name="ttsd-restart").start()

    def _stream_logs(self) -> None:
        """Server-sent events, one per log line, until the client or the daemon goes away.

        Hand-rolled because `BaseHTTPRequestHandler` has no notion of streaming. Two
        details are load-bearing: `protocol_version = "HTTP/1.1"` means a response without
        a Content-Length would leave the browser waiting forever, so the connection is
        explicitly closed rather than kept alive; and every write can raise once the tab
        closes, which is a normal end of stream rather than an error worth logging.
        """
        app = self.app
        tail = LogTail(logs_dir() / "ttsd.log")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.close_connection = True
        self.end_headers()

        def emit(event: str, payload: dict) -> None:
            self.wfile.write(
                f"event: {event}\ndata: {json.dumps(payload)}\n\n".encode("utf-8"))

        def as_payload(line: str) -> dict:
            parsed = parse_line(line)
            # A line that does not parse is a continuation (a traceback, say). Send it as
            # raw so the page can attach it to the record above instead of dropping it.
            return parsed if parsed is not None else {"raw": line}

        try:
            if not tail.exists():
                emit("meta", {"note": "no log file yet"})
            for line in tail.snapshot(200):
                emit("line", as_payload(line))
            emit("meta", {"note": "streaming"})
            idle = 0.0
            while not app.stopping.is_set():
                lines = tail.read_new()
                for line in lines:
                    emit("line", as_payload(line))
                if lines:
                    idle = 0.0
                else:
                    idle += 0.5
                    if idle >= 15:
                        # A comment keeps the connection warm and, more usefully, fails
                        # here when the peer has gone so the thread does not linger.
                        self.wfile.write(b": ping\n\n")
                        idle = 0.0
                time.sleep(0.5)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # the tab closed; not an error
        except OSError as exc:
            log.debug("log stream ended: %s", exc)

    def _speak_raw(self, text: str, voice: str) -> None:
        """Test path: bypasses queue rules, still ducks."""
        app = self.app
        result = app.synth.synthesize(text, voice)
        if result is None:
            return
        app.audio.hold(None)
        try:
            if result.media is not None:
                if not app.dispatcher.playback.play(result.media):
                    app.dispatcher.playback.speak_sapi(text)
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
