"""Serve the knowledge base on loopback, and export it as static files.

The same rules as the TTS daemon's dashboard server: 127.0.0.1 only, the Host
header checked (a DNS-rebinding page must not be able to read local runbooks),
GET only, standard library only. Pages render on every request, so an edit to
a topic shows on reload.
"""

from __future__ import annotations

import html
import json
import shutil
import sys
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .. import store
from . import index, render, site

DEFAULT_PORT = 8896  # free next to 8787/8788 (headroom), 8880 (kokoro), 8890 (tts)
_ALLOWED_HOSTS = ("127.0.0.1", "localhost", "[::1]", "::1")


def theme() -> str:
    resolved = store.get("resolvedTheme", "") or store.get("themeMode", "dark")
    return "light" if resolved == "light" else "dark"


class Site:
    """Everything the pages need, computed once per request or per build."""

    def __init__(self, root: Path | None = None, local: Path | None = None) -> None:
        self.root = root or index.kb_root()
        self.topics = index.topics(self.root, local)
        self.table = index.by_label(self.topics)
        self.theme = theme()

    def render_topic(self, topic: index.Topic, href: Callable[[str], str], base: str) -> str:
        markdown = topic.path.read_text(encoding="utf-8", errors="replace")

        def resolver(ref: str) -> str | None:
            hit = index.resolve_ref(ref, self.topics)
            return href(hit.label) if hit else None

        rendered = render.render(markdown, resolver)
        order = [t for t in self.topics if not t.local or t is topic]
        pos = order.index(topic) if topic in order else -1
        return site.page(
            topic=topic,
            body=rendered.body or f"<h1>{html.escape(topic.title)}</h1><p>(empty)</p>",
            all_topics=self.topics,
            href=href,
            base=base,
            theme=self.theme,
            prev_topic=order[pos - 1] if pos > 0 else None,
            next_topic=order[pos + 1] if 0 <= pos < len(order) - 1 else None,
        )

    def search_json(self) -> str:
        return index.search_json(self.topics)


# ------------------------------------------------------------------- server


def _server_href(label: str) -> str:
    return f"/kb/{label}.html"


class _Handler(BaseHTTPRequestHandler):
    server_version = "tstack-docs"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:  # quiet by default
        if self.server.verbose:  # type: ignore[attr-defined]
            super().log_message(fmt, *args)

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
        return host in _ALLOWED_HOSTS

    def do_GET(self) -> None:
        if not self._host_ok():
            self._send(421, b"misdirected", "text/plain")
            return
        path = unquote(urlsplit(self.path).path)
        kb: Site = Site()  # fresh per request: edits show on reload
        try:
            if path in ("/", "/index.html", "/kb/_index.html"):
                label = "_index"
            elif path == "/search.json":
                self._send(200, kb.search_json().encode("utf-8"), "application/json")
                return
            elif path == "/healthz":
                self._send(200, b"ok", "text/plain")
                return
            elif path.startswith("/raw/") and path.endswith(".md"):
                topic = kb.table.get(path[len("/raw/") : -3])
                if topic is None:
                    self._send(404, b"no such topic", "text/plain")
                    return
                self._send(200, topic.path.read_bytes(), "text/markdown; charset=utf-8")
                return
            elif path.startswith("/kb/") and path.endswith(".html"):
                label = path[len("/kb/") : -5]
            else:
                self._send(404, b"not found", "text/plain")
                return
            topic = kb.table.get(label)
            if topic is None:
                self._send(404, b"no such topic", "text/plain")
                return
            page = kb.render_topic(topic, _server_href, "/")
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        except OSError as exc:
            self._send(500, str(exc).encode("utf-8", "replace"), "text/plain")


class Server:
    def __init__(self, port: int = DEFAULT_PORT, verbose: bool = False) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        self.httpd.daemon_threads = True
        self.httpd.verbose = verbose  # type: ignore[attr-defined]
        self.port = self.httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def serve_forever(self) -> None:
        self.httpd.serve_forever(poll_interval=0.5)

    def start_background(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, name="tstack-docs", daemon=True)
        thread.start()
        return thread

    def shutdown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


# -------------------------------------------------------------------- build


def build(out_dir: Path, kb: Site | None = None) -> int:
    """Write every page, `index.html` and `search.json` under `out_dir`.

    Links are RELATIVE, so the folder can be hosted at any path or opened from
    disk with file://. Returns the number of pages written.
    """
    kb = kb or Site()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "kb").mkdir(exist_ok=True)
    count = 0
    for topic in kb.topics:
        depth = topic.label.count("/") + 1  # pages live under kb/<label>.html
        rel = "../" * depth

        def href(label: str, rel: str = rel) -> str:
            return f"{rel}kb/{label}.html"

        page = kb.render_topic(topic, href, rel)
        target = out_dir / "kb" / f"{topic.label}.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page, encoding="utf-8")
        count += 1
    (out_dir / "search.json").write_text(kb.search_json(), encoding="utf-8")
    shutil.copyfile(out_dir / "kb" / "_index.html", out_dir / "index.html")
    # index.html sits one level up from kb/, so its links need re-basing.
    top = (out_dir / "index.html").read_text(encoding="utf-8").replace('href="../kb/', 'href="kb/')
    top = top.replace('data-base="../"', 'data-base=""')
    (out_dir / "index.html").write_text(top, encoding="utf-8")
    return count


def check(kb: Site | None = None, say: Callable[[str], None] = print) -> int:
    """Every `doc x` reference and relative link resolves. 0 when clean."""
    kb = kb or Site()
    problems = 0
    for topic in kb.topics:
        markdown = topic.path.read_text(encoding="utf-8", errors="replace")
        # Any resolver makes the renderer collect refs; the href it returns is
        # only a placeholder here, which _relative_links skips.
        rendered = render.render(markdown, lambda ref: "x")
        for ref in rendered.refs:
            if index.is_topic_ref(ref) and index.resolve_ref(ref, kb.topics) is None:
                say(f"{topic.label}: `doc {ref}` names no topic")
                problems += 1
        for m in _relative_links(rendered.body):
            target = (topic.path.parent / m).resolve()
            if not target.exists() and not (topic.path.parent / (m + ".md")).exists():
                say(f"{topic.label}: link to {m} does not exist")
                problems += 1
    if problems == 0:
        say(f"ok: {len(kb.topics)} topics, every reference resolves")
    return 1 if problems else 0


def _relative_links(body: str) -> list[str]:
    import re

    out: list[str] = []
    for m in re.finditer(r'<a href="([^"]+)">', body):
        href = m.group(1)
        if "://" in href or href.startswith(("#", "/", "mailto:")) or href.startswith("x"):
            continue
        out.append(html.unescape(href).split("#", 1)[0])
    return out


def dump_json(kb: Site, stream: object = sys.stdout) -> None:
    json.dump([t.label for t in kb.topics], stream)  # type: ignore[arg-type]
