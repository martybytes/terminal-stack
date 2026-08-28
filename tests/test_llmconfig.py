"""AgentMemory's chat provider -- the one piece of configuration that is not a
saved setting.

`OPENAI_BASE_URL` and `OPENAI_MODEL` live in `services/stacks/agentmemory/.env`,
compose's own interpolation source, gitignored per machine. The credential lives
one level up in `services/.env`, which loads AFTER it and is therefore the only
place a key can win. None of it is in `schema.py`, which is exactly why the
settings dashboard could not touch it.

THE ASYMMETRY IS THE DESIGN. Unset is a supported skip every check reports;
set-but-unreachable fails silently. So `clear()` is a first-class operation and
is not the same as writing an empty string.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import llmconfig  # noqa: E402


@pytest.fixture
def source(tmp_path, monkeypatch):
    """A throwaway clone carrying the REAL shipped example, so the tests run
    against the file people actually get."""
    stack = tmp_path / "services" / "stacks" / "agentmemory"
    stack.mkdir(parents=True)
    (stack / ".env").write_text(
        (ROOT / "services/stacks/agentmemory/.env.example").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tmp_path / "services" / ".env").write_text(
        (ROOT / "services/.env.example").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setenv("TS_STACK_ROOT", str(tmp_path / "services" / "stacks"))
    return tmp_path


def test_the_shipped_example_reads_as_unconfigured(source):
    """The state a fresh clone is in, and the one this whole workstream exists
    to make the default."""
    provider = llmconfig.read(source)
    assert not provider.configured
    assert not provider.complete
    assert provider.base_url == "" and provider.model == ""
    assert not provider.api_key_set, "the shipped key placeholder is commented out"


def test_configured_is_the_url_and_complete_is_both(source):
    """`inferenceActive` in the console is driven by the MODEL, not the URL, so
    an endpoint with an empty model reads as configured everywhere and leaves
    every family off. The two questions are not the same question."""
    llmconfig.configure(source, "http://h:8000/v1", "", ("x", "y"))
    provider = llmconfig.read(source)
    assert provider.configured, "a base URL is what makes the features run at all"
    assert not provider.complete, "...but without a model none of them do anything"


def test_the_documented_provider_shapes_are_never_uncommented(source):
    """Those three commented blocks are the explanation, and are most of that
    file's worth. Writing a value into one destroys it."""
    before = (source / "services/stacks/agentmemory/.env").read_text(encoding="utf-8")
    documented = [ln for ln in before.splitlines() if ln.startswith("# OPENAI_BASE_URL=")]
    assert len(documented) == 3, "the example documents three shapes"

    llmconfig.configure(source, "http://h:8000/v1", "m", ("x", "y"))
    after = (source / "services/stacks/agentmemory/.env").read_text(encoding="utf-8")
    assert [ln for ln in after.splitlines() if ln.startswith("# OPENAI_BASE_URL=")] == documented
    assert "COMMENTED OUT ON PURPOSE" in after, "and the explanation survives"


def test_exactly_one_active_line_per_key(source):
    """`stacks.env_value` reads the FIRST match, so two active lines make the
    answer depend on position."""
    for url in ("http://a:1/v1", "http://b:2/v1", "http://c:3/v1"):
        llmconfig.configure(source, url, "m", ("x", "y"))
    body = (source / "services/stacks/agentmemory/.env").read_text(encoding="utf-8")
    assert len([ln for ln in body.splitlines() if ln.startswith("OPENAI_BASE_URL=")]) == 1
    assert llmconfig.read(source).base_url == "http://c:3/v1"


def test_the_file_does_not_grow_on_every_configure_clear_cycle(source):
    env = source / "services/stacks/agentmemory/.env"
    llmconfig.configure(source, "http://h:1/v1", "m", ("x", "y"))
    llmconfig.clear(source)
    settled = len(env.read_text(encoding="utf-8").splitlines())
    for _ in range(4):
        llmconfig.configure(source, "http://h:1/v1", "m", ("x", "y"))
        llmconfig.clear(source)
    assert len(env.read_text(encoding="utf-8").splitlines()) == settled


def test_clear_leaves_honest_labels_rather_than_removing_them(source):
    """The compose file defaults them to "OpenAI"/"OpenAI API", so an absent
    label makes the console name a provider this machine does not have."""
    llmconfig.configure(
        source, "https://api.openai.com/v1", "gpt-4o-mini", ("OpenAI", "OpenAI API")
    )
    llmconfig.clear(source)
    provider = llmconfig.read(source)
    assert not provider.configured
    assert provider.provider_label == llmconfig.UNCONFIGURED_PROVIDER
    assert provider.endpoint_label == llmconfig.UNCONFIGURED_ENDPOINT


def test_labels_are_derived_from_the_endpoint(source):
    """Not cosmetic: the console assesses an UNLABELLED provider as paid, which
    is the safe direction to be wrong in and wrong for a local runtime."""
    assert llmconfig.labels_for("https://api.openai.com/v1") == ("OpenAI", "OpenAI API")
    assert llmconfig.labels_for("http://host.docker.internal:11434/v1")[0] == "Ollama"
    assert llmconfig.labels_for("http://127.0.0.1:1234/v1")[0] == "LM Studio"
    assert llmconfig.labels_for("http://10.0.0.5:8000/v1")[0] == "OpenAI-compatible"


def test_crlf_survives(source):
    """A .env a Windows editor has touched is CRLF, and universal-newline
    translation would silently rewrite every line of it."""
    env = source / "services/stacks/agentmemory/.env"
    with env.open("w", encoding="utf-8", newline="") as handle:
        handle.write("# note\r\nOPENAI_MODEL=old\r\n")
    llmconfig.configure(source, "http://h:1/v1", "new", ("x", "y"))
    raw = env.read_bytes()
    assert b"# note\r\n" in raw, "an untouched line keeps its ending"
    assert raw.count(b"\r\n") >= 2
    assert llmconfig.read(source).model == "new"


def test_a_missing_env_is_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setenv("TS_STACK_ROOT", str(tmp_path / "nope"))
    provider = llmconfig.read(tmp_path)
    assert not provider.configured
    assert llmconfig.configure(tmp_path, "http://h/v1", "m", ("x", "y")) == []
    assert llmconfig.clear(tmp_path) == []


def test_the_four_features_are_stated_once(source):
    """`tstack agents llm` prints them and the docs quote them; a second list
    would be a second thing to keep true."""
    names = [name for name, _why in llmconfig.FEATURES]
    assert names == ["compression", "summary", "graph", "consolidation"]
