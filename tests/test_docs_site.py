"""`tstack docs`: the knowledge base rendered, indexed, served and exported.

The renderer is held to the constructs the KB actually uses; every KB file is
rendered and every `doc x` reference resolved, which makes this a permanent
gate on the KB itself. The server test binds an ephemeral loopback port.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import registry  # noqa: E402
from tstack.commands import docs as docs_cmd  # noqa: E402
from tstack.kb import index, render, server  # noqa: E402

KB = ROOT / "docs" / "kb"


@pytest.fixture(autouse=True)
def _kb(monkeypatch):
    monkeypatch.setenv("DOC_ROOT", str(KB))
    monkeypatch.setenv("DOC_LOCAL", str(ROOT / "nonexistent-doc-local"))


# ------------------------------------------------------------------ render


def test_the_kb_grammar_renders():
    md = (
        "# fzf (fuzzy finder)\n\nIntro with `code`, **bold**, *italic*, a [link](x.md) and <https://a.b/c>.\n\n"
        "## Keys\n\n| Key | Action |\n|---|---|\n| `Ctrl-R` | history \\| pipe kept |\n| `<name>` | placeholder |\n\n"
        "```sh\nls -la\ncd /tmp\n```\n\n- one\n  - nested\n- two\n\n1. first\n2. second\n\n> quoted\n\nSee `doc common/tools/atuin` and `doc cmd`.\n"
    )
    got = render.render(md, lambda ref: f"/kb/{ref}.html")
    assert got.title == "fzf (fuzzy finder)"
    assert [h.anchor for h in got.headings] == ["fzf-fuzzy-finder", "keys"]
    b = got.body
    assert '<h1 id="fzf-fuzzy-finder">' in b and '<h2 id="keys">' in b
    assert "<strong>bold</strong>" in b and "<em>italic</em>" in b
    assert '<a href="x">link</a>' in b and '<a href="https://a.b/c">https://a.b/c</a>' in b
    assert "<td><code>Ctrl-R</code></td><td>history | pipe kept</td>" in b
    assert "<code>&lt;name&gt;</code>" in b, "placeholders are shown, not interpreted"
    assert (
        '<code class="lang-sh"><span class="ln">ls -la</span>\n<span class="ln">cd /tmp</span>' in b
    )
    assert "<ul><li>one<ul><li>nested</li></ul></li><li>two</li></ul>" in b.replace("\n", "")
    assert "<ol><li>first</li><li>second</li></ol>" in b.replace("\n", "")
    assert "<blockquote>quoted</blockquote>" in b
    assert (
        '<a class="ref" href="/kb/common/tools/atuin.html"><code>doc common/tools/atuin</code></a>'
        in b
    )
    assert "<code>doc cmd</code>" in b, "the doc command's own verbs are not topics"
    assert got.refs == ["common/tools/atuin"]
    assert "ls -la" in got.text and "quoted" in got.text


def test_nothing_in_a_runbook_reaches_the_page_as_html():
    got = render.render("# t\n\n<script>alert(1)</script> and `<b>` in `code`\n")
    assert "<script>" not in got.body and "&lt;script&gt;" in got.body


def test_every_kb_topic_renders_and_every_reference_resolves(capsys):
    kb = server.Site(KB, None)
    assert len(kb.topics) >= 70
    assert server.check(kb, say=print) == 0, capsys.readouterr().out


def test_references_resolve_like_the_doc_command(monkeypatch):
    kb = server.Site(KB, None)
    assert index.resolve_ref("common/tools/fzf", kb.topics).label == "common/tools/fzf"
    assert index.resolve_ref("fzf", kb.topics).label == "common/tools/fzf"
    assert index.resolve_ref("git", kb.topics).label == "common/git"
    monkeypatch.setattr(index, "current_os_group", lambda: "macos")
    assert index.resolve_ref("docker-desktop", kb.topics).label == "macos/docker-desktop"
    assert index.resolve_ref("no-such-topic", kb.topics) is None
    assert not index.is_topic_ref("cmd") and index.is_topic_ref("fzf")


def test_the_personal_layer_is_included_and_tagged(tmp_path):
    local = tmp_path / "doc.local"
    (local / "common").mkdir(parents=True)
    (local / "common" / "secrets.md").write_text("# Secrets\n\nhost 10.0.0.1\n", encoding="utf-8")
    kb = server.Site(KB, local)
    mine = kb.table["common/secrets"]
    assert mine.local and mine.title == "Secrets [local]" and mine.group == "local"
    assert kb.topics[-1] is mine, "personal topics list last"


# ----------------------------------------------------------- server/build


def test_the_server_serves_pages_search_and_raw_on_loopback_only():
    srv = server.Server(port=0)
    srv.start_background()
    try:
        base = srv.url
        page = urllib.request.urlopen(base, timeout=10).read().decode("utf-8")
        assert "<title>Knowledge base" in page and 'class="here"' in page
        fzf = urllib.request.urlopen(base + "kb/common/tools/fzf.html", timeout=10).read().decode()
        assert (
            "<table>" in fzf
            and 'data-base="/"' in fzf
            and 'href="/kb/common/tools/atuin.html"' in fzf
        )
        raw = urllib.request.urlopen(base + "raw/common/tools/fzf.md", timeout=10).read().decode()
        assert raw.startswith("# fzf")
        corpus = json.loads(urllib.request.urlopen(base + "search.json", timeout=10).read())
        assert any(r["label"] == "common/tools/fzf" and "fzf" in r["title"].lower() for r in corpus)
        with pytest.raises(urllib.error.HTTPError) as missing:
            urllib.request.urlopen(base + "kb/nope.html", timeout=10)
        assert missing.value.code == 404
        # A page served for a foreign Host header is a DNS-rebinding read.
        req = urllib.request.Request(base, headers={"Host": "evil.example"})
        with pytest.raises(urllib.error.HTTPError) as bad_host:
            urllib.request.urlopen(req, timeout=10)
        assert bad_host.value.code == 421
        assert srv.httpd.server_address[0] == "127.0.0.1"
    finally:
        srv.shutdown()


def test_build_writes_a_folder_that_works_from_disk(tmp_path):
    out = tmp_path / "site"
    count = server.build(out, server.Site(KB, None))
    assert count >= 70
    assert (out / "index.html").is_file() and (out / "search.json").is_file()
    fzf = (out / "kb/common/tools/fzf.html").read_text(encoding="utf-8")
    assert 'href="../../../kb/common/tools/atuin.html"' in fzf, "links are relative"
    assert 'data-base="../../../"' in fzf
    top = (out / "index.html").read_text(encoding="utf-8")
    assert 'data-base=""' in top and 'href="kb/common/git.html"' in top
    assert "http://" not in fzf.split("<article>")[0], "no external assets in the shell"


def test_pages_carry_no_non_ascii_source_and_no_cdn():
    for name in ("site.py", "render.py", "server.py", "index.py"):
        text = (ROOT / "tstack" / "kb" / name).read_text(encoding="utf-8")
        assert text.isascii(), f"{name} has non-ASCII (the Windows console rule)"
    assert "cdn" not in (ROOT / "tstack/kb/site.py").read_text(encoding="utf-8").lower()


# ---------------------------------------------------------------- command


def test_docs_is_in_the_registry_on_both_platforms():
    cmd = registry.get("docs")
    assert cmd is not None
    assert cmd.impl() == "python"


def test_docs_check_and_build_verbs(tmp_path, capsys):
    assert docs_cmd.main(["check"]) == 0
    assert "every reference resolves" in capsys.readouterr().out
    assert docs_cmd.main(["build", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "index.html").is_file()
    assert docs_cmd.main(["serve", "--port", "x"]) == 2
    assert docs_cmd.main(["bogus"]) == 2
    assert docs_cmd.main([]) == 0  # help


def test_doc_web_reaches_tstack_docs_in_both_shells():
    zsh = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    ps = (ROOT / "windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1").read_text(
        encoding="utf-8"
    )
    assert "tstack docs serve" in zsh and "tstack docs open" in zsh
    assert "tstack docs serve" in ps and "tstack docs open" in ps
    for body in (zsh, ps):
        assert "doc web [topic]" in body
