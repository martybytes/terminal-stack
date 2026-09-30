"""Which topics exist, where, and in what order the sidebar lists them."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .. import paths
from .. import platform as plat
from . import render

# Sidebar order. `common/tools` is its own group because it is 36 of the 77
# files; the OS groups come after the shared ones; anything unlisted last.
GROUP_ORDER = ("common", "common/tools", "wezterm", "linux", "macos", "windows")
GROUP_TITLES = {
    "": "Start here",
    "common": "Common",
    "common/tools": "Tools",
    "wezterm": "WezTerm",
    "linux": "Linux",
    "macos": "macOS",
    "windows": "Windows",
    "local": "Personal (~/.doc.local)",
}


@dataclass(frozen=True)
class Topic:
    label: str  # common/tools/fzf
    path: Path
    title: str
    group: str
    local: bool = False

    @property
    def name(self) -> str:
        return self.label.rsplit("/", 1)[-1]


class KbNotFound(RuntimeError):
    pass


def kb_root() -> Path:
    """docs/kb in the clone. $DOC_ROOT first, as the `doc` shell command does."""
    env = os.environ.get("DOC_ROOT")
    if env and Path(env).is_dir():
        return Path(env)
    try:
        root = paths.resolve_source_dir() / "docs" / "kb"
    except paths.CloneNotFound as exc:
        raise KbNotFound(str(exc)) from exc
    if not root.is_dir():
        raise KbNotFound(f"no knowledge base at {root}")
    return root


def local_root() -> Path | None:
    """The personal, uncommitted layer: same folder layout, tagged [local]."""
    env = os.environ.get("DOC_LOCAL")
    candidate = Path(env) if env else Path.home() / ".doc.local"
    return candidate if candidate.is_dir() else None


def _title_of(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                m = re.match(r"^#\s+(.*?)\s*$", line)
                if m:
                    return re.sub(r"`", "", m.group(1))
    except OSError:
        pass
    return path.stem


def _group_of(label: str) -> str:
    parent = label.rsplit("/", 1)[0] if "/" in label else ""
    if parent.startswith("common/tools"):
        return "common/tools"
    return parent.split("/", 1)[0] if parent else ""


def topics(root: Path | None = None, local: Path | None = None) -> list[Topic]:
    """Every topic, sidebar order. `_index` leads; `_style` is not a topic."""
    root = root or kb_root()
    found: list[Topic] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("_style/"):
            continue
        label = rel[:-3]
        found.append(Topic(label, path, _title_of(path), _group_of(label)))
    if local is None:
        local = local_root()
    if local:
        for path in sorted(local.rglob("*.md")):
            label = path.relative_to(local).as_posix()[:-3]
            found.append(Topic(label, path, _title_of(path) + " [local]", "local", local=True))

    def key(t: Topic) -> tuple[int, int, str]:
        if t.local:
            return (99, 0, t.label)
        if t.label == "_index":
            return (-1, 0, "")
        order = GROUP_ORDER.index(t.group) if t.group in GROUP_ORDER else 50
        return (order, 0, t.title.lower())

    return sorted(found, key=key)


def by_label(all_topics: list[Topic]) -> dict[str, Topic]:
    return {t.label: t for t in all_topics}


# `doc <verb>` in a runbook is the doc COMMAND's own verb, not a topic.
DOC_VERBS = frozenset({"cmd", "tui", "edit", "new", "ls", "sync", "web", "-g", "--os", "help"})


def is_topic_ref(ref: str) -> bool:
    """A `doc x` that names a topic, as opposed to a verb or a usage example
    (`doc -h`, `doc wezterm/...`)."""
    ref = ref.strip("/")
    return ref not in DOC_VERBS and not ref.startswith("-") and "..." not in ref


def resolve_ref(ref: str, all_topics: list[Topic]) -> Topic | None:
    """`doc x` the way the shell command resolves it: an exact label, else a
    basename (`doc fzf` -> common/tools/fzf; `doc docker-desktop` -> this OS's
    copy when several OS folders have one), else the common/ copy."""
    table = by_label(all_topics)
    ref = ref.strip("/")
    if ref in table:
        return table[ref]
    names = [t for t in all_topics if t.name == ref and not t.local]
    if len(names) == 1:
        return names[0]
    if names:
        here = current_os_group()
        for t in names:
            if t.group == here:
                return t
        return names[0]
    for prefix in ("common/", "common/tools/"):
        if prefix + ref in table:
            return table[prefix + ref]
    # The shell's own rule, last: a case-insensitive SUBSTRING of the label,
    # when it is unique (`doc veracrypt` -> linux/veracrypt-ssh-keys).
    needle = ref.lower()
    hits = [t for t in all_topics if needle in t.label.lower() and not t.local]
    if len(hits) == 1:
        return hits[0]
    return None


def current_os_group() -> str:
    kind = plat.kind()
    if kind in (plat.WINDOWS,):
        return "windows"
    if kind == plat.MACOS:
        return "macos"
    return "linux"


def search_corpus(all_topics: list[Topic]) -> list[dict[str, object]]:
    """What the page's search box matches against. Title, headings and code
    lines are kept whole; body text is capped so the file stays small."""
    rows: list[dict[str, object]] = []
    for t in all_topics:
        try:
            markdown = t.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rendered = render.render(markdown)
        code = [ln for ln in rendered.text.splitlines() if ln.strip()]
        rows.append(
            {
                "label": t.label,
                "title": t.title,
                "group": GROUP_TITLES.get(t.group, t.group),
                "headings": [h.text for h in rendered.headings if h.level > 1],
                "text": " ".join(code)[:4000],
            }
        )
    return rows


def search_json(all_topics: list[Topic]) -> str:
    return json.dumps(search_corpus(all_topics), ensure_ascii=True)
