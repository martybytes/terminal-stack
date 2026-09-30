"""Markdown -> HTML for the knowledge base, and nothing more general than that.

The KB is 77 hand-written files that use: ATX headings, GFM tables, fenced
code, bullet and numbered lists (two-space nesting), blockquotes, paragraphs,
`code`, **bold**, *italic*, [links](url), <http://autolinks>, and the house
cross-reference `` `doc a/b` ``. That is the whole grammar handled here. Every
piece of text goes through html.escape, so a `<placeholder>` in a runbook is
shown, not interpreted.

No third-party markdown library: tstack is standard-library only, so that a
fresh machine can run it before anything is installed.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass, field

Resolver = Callable[[str], str | None]  # a `doc` reference -> href, or None


@dataclass
class Heading:
    level: int
    text: str
    anchor: str


@dataclass
class Rendered:
    title: str
    body: str
    headings: list[Heading] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)  # every `doc x` reference seen
    text: str = ""  # plain text, for the search corpus


_FENCE = re.compile(r"^```\s*([A-Za-z0-9_+-]*)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^(\s*)([-*+])\s+(.*)$")
_NUMBER = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_TABLE_SEP = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_RULE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_DOC_REF = re.compile(r"^doc\s+([A-Za-z0-9_./-]+)$")
# The doc command's own verbs, which are not topics (kept in step with index.DOC_VERBS).
_DOC_VERBS = frozenset({"cmd", "tui", "edit", "new", "ls", "sync", "web", "-g", "--os", "help"})
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*([^*\n]+?)\*(?![\w*])")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_AUTOLINK = re.compile(r"&lt;(https?://[^&\s]+)&gt;")
_BARE_URL = re.compile(r"(?<![\"'>=/\w])(https?://[^\s<>\"')]+[^\s<>\"').,;:])")


def slug(text: str) -> str:
    """GitHub-style anchors: lowercase, punctuation dropped, spaces to dashes."""
    text = re.sub(r"`|\*|_", "", text)
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s]+", "-", text).strip("-") or "section"


def _split_row(line: str) -> list[str]:
    """Table cells. `\\|` is a literal pipe (the KB writes `<linux\\|macos>`)."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells = re.split(r"(?<!\\)\|", line)
    return [c.replace("\\|", "|").strip() for c in cells]


class _Inline:
    def __init__(self, resolver: Resolver | None, refs: list[str]) -> None:
        self.resolver = resolver
        self.refs = refs

    def render(self, text: str) -> str:
        # Code spans are lifted out first so nothing inside them is styled.
        spans: list[str] = []

        def lift(match: re.Match[str]) -> str:
            code = match.group(1)
            spans.append(self._code(code))
            return f"\x00{len(spans) - 1}\x00"

        work = _CODE_SPAN.sub(lift, text)
        work = html.escape(work, quote=False)
        work = _AUTOLINK.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', work)
        work = _LINK.sub(self._link, work)
        work = _BOLD.sub(r"<strong>\1</strong>", work)
        work = _ITALIC.sub(r"<em>\1</em>", work)
        work = _BARE_URL.sub(lambda m: f'<a href="{m.group(1)}">{m.group(1)}</a>', work)
        return re.sub(r"\x00(\d+)\x00", lambda m: spans[int(m.group(1))], work)

    def _link(self, match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        # Escaped already; unescape the URL so `&amp;` does not reach the href twice.
        href = html.unescape(url)
        if href.endswith(".md") and "://" not in href:
            href = href[:-3]  # a sibling topic
        return f'<a href="{html.escape(href, quote=True)}">{label}</a>'

    def _code(self, code: str) -> str:
        ref = _DOC_REF.match(code.strip())
        if (
            ref
            and self.resolver
            and ref.group(1) not in _DOC_VERBS
            and not ref.group(1).startswith("-")
            and "..." not in ref.group(1)
        ):
            self.refs.append(ref.group(1))
            href = self.resolver(ref.group(1))
            if href:
                return f'<a class="ref" href="{html.escape(href, quote=True)}"><code>{html.escape(code)}</code></a>'
        return f"<code>{html.escape(code)}</code>"


def render(markdown: str, resolver: Resolver | None = None) -> Rendered:
    lines = markdown.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    headings: list[Heading] = []
    refs: list[str] = []
    plain: list[str] = []
    inline = _Inline(resolver, refs)
    title = ""
    seen_anchors: dict[str, int] = {}
    i = 0
    n = len(lines)

    def anchor_for(text: str) -> str:
        base = slug(text)
        count = seen_anchors.get(base, 0)
        seen_anchors[base] = count + 1
        return base if count == 0 else f"{base}-{count}"

    def flush_para(buf: list[str]) -> None:
        if buf:
            joined = " ".join(s.strip() for s in buf)
            plain.append(joined)
            out.append(f"<p>{inline.render(joined)}</p>")
            buf.clear()

    para: list[str] = []
    while i < n:
        line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            flush_para(para)
            lang = fence.group(1) or "text"
            i += 1
            code: list[str] = []
            while i < n and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1  # closing fence
            plain.extend(code)
            rows = "".join(f'<span class="ln">{html.escape(c)}</span>\n' for c in code)
            out.append(
                f'<div class="codeblock"><button class="copy" type="button" title="copy">copy</button>'
                f'<pre><code class="lang-{html.escape(lang)}">{rows}</code></pre></div>'
            )
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_para(para)
            level = len(heading.group(1))
            text = heading.group(2)
            a = anchor_for(text)
            headings.append(Heading(level, re.sub(r"`", "", text), a))
            plain.append(text)
            if level == 1 and not title:
                title = re.sub(r"`", "", text)
            out.append(
                f'<h{level} id="{a}">{inline.render(text)}<a class="hl" href="#{a}">#</a></h{level}>'
            )
            i += 1
            continue
        if line.lstrip().startswith("|") and i + 1 < n and _TABLE_SEP.match(lines[i + 1]):
            flush_para(para)
            head = _split_row(line)
            i += 2
            body_rows: list[list[str]] = []
            while i < n and lines[i].lstrip().startswith("|"):
                body_rows.append(_split_row(lines[i]))
                i += 1
            plain.extend(" ".join(r) for r in [head, *body_rows])
            ths = "".join(f"<th>{inline.render(c)}</th>" for c in head)
            trs = "".join(
                "<tr>" + "".join(f"<td>{inline.render(c)}</td>" for c in r) + "</tr>"
                for r in body_rows
            )
            out.append(f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>")
            continue
        if line.startswith(">"):
            flush_para(para)
            quote: list[str] = []
            while i < n and lines[i].startswith(">"):
                quote.append(lines[i][1:].strip())
                i += 1
            joined = " ".join(quote)
            plain.append(joined)
            out.append(f"<blockquote>{inline.render(joined)}</blockquote>")
            continue
        if _RULE.match(line) and not para:
            out.append("<hr>")
            i += 1
            continue
        if _BULLET.match(line) or _NUMBER.match(line):
            flush_para(para)
            i = _list(lines, i, out, inline, plain)
            continue
        if not line.strip():
            flush_para(para)
            i += 1
            continue
        para.append(line)
        i += 1
    flush_para(para)
    return Rendered(
        title=title, body="\n".join(out), headings=headings, refs=refs, text="\n".join(plain)
    )


def _list(lines: list[str], i: int, out: list[str], inline: _Inline, plain: list[str]) -> int:
    """One list (possibly nested by indentation) starting at lines[i]."""
    stack: list[tuple[int, str]] = []  # (indent, tag)

    def open_list(indent: int, tag: str) -> None:
        stack.append((indent, tag))
        out.append(f"<{tag}>")

    def close_to(indent: int) -> None:
        while stack and stack[-1][0] > indent:
            out.append(f"</li></{stack.pop()[1]}>")

    first = True
    n = len(lines)
    while i < n:
        line = lines[i]
        m = _BULLET.match(line) or _NUMBER.match(line)
        if not m:
            # A continuation line indented under the item, or the end of the list.
            if line.strip() and line.startswith(("  ", "\t")) and stack:
                plain.append(line.strip())
                out.append(" " + inline.render(line.strip()))
                i += 1
                continue
            break
        indent = len(m.group(1).replace("\t", "  "))
        tag = "ol" if m.group(2).isdigit() else "ul"
        text = m.group(3)
        if first:
            open_list(indent, tag)
            first = False
        elif indent > stack[-1][0]:
            open_list(indent, tag)
        else:
            close_to(indent)
            out.append("</li>")
            if not stack or stack[-1][0] != indent:
                open_list(indent, tag)
        plain.append(text)
        out.append(f"<li>{inline.render(text)}")
        i += 1
    while stack:
        out.append(f"</li></{stack.pop()[1]}>")
    return i
