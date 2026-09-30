"""`tstack docs` - the knowledge base in your browser."""

from __future__ import annotations

import sys
from pathlib import Path

from ..kb import index, server

HELP = """tstack docs - browse the knowledge base (doc) in your browser.

Usage:
  tstack docs serve [--port N] [--no-open] [--verbose]
  tstack docs open <topic>
  tstack docs build [DIR]
  tstack docs check

  serve   a local server on 127.0.0.1 (default port 8896); opens your browser.
          Pages render on each request, so an edit shows on reload. Ctrl+C stops.
  open    serve, and open one topic (e.g. `tstack docs open fzf`).
  build   write plain HTML into DIR (default ./tstack-docs): every topic,
          index.html and search.json, with relative links, so the folder can be
          hosted anywhere or opened from disk.
  check   every `doc a/b` reference and relative link resolves. Exit 1 if not.

Sidebar, search (press /), dark/light, click any code line to copy it. The
personal ~/.doc.local layer is included, tagged [local], never written.
Also: `doc web` in either shell."""


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0
    verb, rest = argv[0], argv[1:]
    try:
        if verb == "check":
            return server.check(server.Site())
        if verb == "build":
            out = Path(rest[0]) if rest else Path("tstack-docs")
            count = server.build(out)
            print(f"==> {count} pages written to {out.resolve()} (open {out / 'index.html'})")
            return 0
        if verb in ("serve", "open"):
            port = server.DEFAULT_PORT
            open_browser = True
            verbose = False
            topic = ""
            items = list(rest)
            while items:
                item = items.pop(0)
                if item == "--port":
                    if not items or not items[0].isdigit():
                        print("tstack docs: --port needs a number", file=sys.stderr)
                        return 2
                    port = int(items.pop(0))
                elif item == "--no-open":
                    open_browser = False
                elif item == "--verbose":
                    verbose = True
                elif verb == "open" and not topic:
                    topic = item
                else:
                    print(f"tstack docs: unknown option {item}", file=sys.stderr)
                    return 2
            kb = server.Site()  # resolves the KB before binding a port
            path = "/"
            if verb == "open":
                hit = index.resolve_ref(topic, kb.topics) if topic else None
                if hit is None:
                    print(f"tstack docs: no topic named '{topic}'", file=sys.stderr)
                    return 1
                path = f"/kb/{hit.label}.html"
            return _serve(port, path, open_browser, verbose)
    except index.KbNotFound as exc:
        print(f"tstack docs: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"tstack docs: {exc}", file=sys.stderr)
        return 1
    print(f"tstack docs: unknown verb '{verb}'", file=sys.stderr)
    print(HELP, file=sys.stderr)
    return 2


def _serve(port: int, path: str, open_browser: bool, verbose: bool) -> int:
    try:
        srv = server.Server(port, verbose=verbose)
    except OSError as exc:
        print(
            f"tstack docs: cannot listen on 127.0.0.1:{port} ({exc}); try --port", file=sys.stderr
        )
        return 1
    url = srv.url.rstrip("/") + path
    print(f"==> docs at {url}   (Ctrl+C to stop)")
    if open_browser:
        from .agents import _open_url

        _open_url(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n==> stopped.")
    finally:
        srv.shutdown()
    return 0
