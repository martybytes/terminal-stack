"""The four summarizer modes: what switches, what silently does not, and why.

No network. The haiku and ollama paths had zero coverage before this file, which is how a
missing API key came to be byte-for-byte indistinguishable from template mode.
"""

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ttsd import keystore
from ttsd.events import Event
from ttsd.registry import Registry
from ttsd.summarize import Summarizer


class DictCfg:
    def __init__(self, data=None) -> None:
        self.data = data or {}

    def get(self, dotted, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


def ev(state="waiting", key="claude:s1", project="alpha", text="", override="", **kw):
    return Event(source="claude", event=state, state=state, session_key=key,
                 project_name=project, text=text, override=override, **kw)


def line(cfg, event):
    return Summarizer(cfg).line_for_batch([event], Registry())


def summarize_with(cfg, event):
    """Return (line, summarizer) so a test can inspect the degrade record."""
    s = Summarizer(cfg)
    return s.line_for_batch([event], Registry()), s


class _FakeResponse:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


def _stub_urlopen(monkeypatch, payload=None, raises=None, captured=None):
    import ttsd.summarize as mod

    def _fake(req, timeout=None):
        if captured is not None:
            captured.append(req)
        if raises is not None:
            raise raises
        return _FakeResponse(payload)

    monkeypatch.setattr(mod.urllib.request, "urlopen", _fake)


def _isolate_keystore(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    importlib.reload(keystore)
    import ttsd.summarize as mod
    monkeypatch.setattr(mod, "keystore", keystore)
    return keystore


# ── the structural truth: modes only apply to one event class ────────────────

def test_only_done_events_reach_the_mode_dispatch(tmp_path, monkeypatch):
    """A question is always the template line, whatever mode is selected.

    `_line_for_one` returns before the dispatch unless the event is P2_DONE, so selecting
    haiku and then hearing a template-shaped question is correct behaviour, not a bug. This
    test exists so nobody "fixes" it by accident, and so the UI can state it honestly.
    """
    _isolate_keystore(tmp_path, monkeypatch)
    calls = []
    _stub_urlopen(monkeypatch, payload={}, captured=calls)
    cfg = DictCfg({"summarize": {"mode": "haiku"}})

    spoken = line(cfg, ev(state="question", override="Which database?", text="ignored"))
    assert "I have a question for you" in spoken
    assert calls == [], "no LLM request may be made for a question event"


def test_a_coalesced_batch_bypasses_every_mode(tmp_path, monkeypatch):
    _isolate_keystore(tmp_path, monkeypatch)
    calls = []
    _stub_urlopen(monkeypatch, payload={}, captured=calls)
    cfg = DictCfg({"summarize": {"mode": "haiku"}})
    reg = Registry()
    batch = [ev(key="claude:a", text="one"), ev(key="claude:b", text="two")]

    spoken = Summarizer(cfg).line_for_batch(batch, reg)
    assert "finished" in spoken
    assert calls == [], "a coalesced line is assembled locally"


# ── haiku ────────────────────────────────────────────────────────────────────

def test_haiku_without_a_key_records_why_and_uses_the_template(tmp_path, monkeypatch):
    """The state that made this feature untrustworthy: silent, identical to template."""
    _isolate_keystore(tmp_path, monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls = []
    _stub_urlopen(monkeypatch, payload={}, captured=calls)

    cfg = DictCfg({"summarize": {"mode": "haiku"}})
    spoken, s = summarize_with(cfg, ev(text="Rewrote the retry logic and all tests pass."))

    assert calls == [], "no request without a key"
    assert "I'm waiting for you" in spoken, "falls back to the template"
    assert s.degraded == 1
    assert "no API key" in s.last_degrade
    assert "ANTHROPIC_API_KEY" in s.last_degrade, "names the env var it looked for"


def test_haiku_uses_the_key_from_the_secret_store(tmp_path, monkeypatch):
    ks = _isolate_keystore(tmp_path, monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ks.set_value(ks.ANTHROPIC_API_KEY, "sk-ant-from-store") is True
    calls = []
    _stub_urlopen(monkeypatch, captured=calls, payload={
        "content": [{"type": "text", "text": "Retry logic rewritten and tests pass."}]})

    cfg = DictCfg({"summarize": {"mode": "haiku"}})
    spoken, s = summarize_with(cfg, ev(text="Rewrote the retry logic."))

    assert len(calls) == 1
    assert calls[0].headers["X-api-key"] == "sk-ant-from-store"
    assert "Retry logic rewritten" in spoken
    assert s.degraded == 0 and s.last_degrade == ""
    assert s.last_key_source == "store"


def test_the_store_wins_over_the_environment(tmp_path, monkeypatch):
    """The environment is the half that cannot reach an autostarted daemon."""
    ks = _isolate_keystore(tmp_path, monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    ks.set_value(ks.ANTHROPIC_API_KEY, "sk-ant-from-store")
    calls = []
    _stub_urlopen(monkeypatch, captured=calls,
                  payload={"content": [{"type": "text", "text": "Done."}]})

    line(DictCfg({"summarize": {"mode": "haiku"}}), ev(text="something"))
    assert calls[0].headers["X-api-key"] == "sk-ant-from-store"


def test_the_environment_still_works_when_the_store_is_empty(tmp_path, monkeypatch):
    _isolate_keystore(tmp_path, monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")
    calls = []
    _stub_urlopen(monkeypatch, captured=calls,
                  payload={"content": [{"type": "text", "text": "Done."}]})

    _, s = summarize_with(DictCfg({"summarize": {"mode": "haiku"}}), ev(text="something"))
    assert calls[0].headers["X-api-key"] == "sk-ant-from-env"
    assert s.last_key_source == "env"


def test_a_haiku_request_failure_names_the_exception_type(tmp_path, monkeypatch):
    """A timeout, a 401 and a rate limit are indistinguishable here, so name the class."""
    ks = _isolate_keystore(tmp_path, monkeypatch)
    ks.set_value(ks.ANTHROPIC_API_KEY, "sk-ant-x")
    _stub_urlopen(monkeypatch, raises=TimeoutError("timed out"))

    spoken, s = summarize_with(DictCfg({"summarize": {"mode": "haiku"}}),
                               ev(text="Rewrote the retry logic."))
    assert "I'm waiting for you" in spoken
    assert s.degraded == 1
    assert "TimeoutError" in s.last_degrade


def test_repeated_failures_warn_once_but_count_every_time(tmp_path, monkeypatch, caplog):
    ks = _isolate_keystore(tmp_path, monkeypatch)
    ks.set_value(ks.ANTHROPIC_API_KEY, "sk-ant-x")
    _stub_urlopen(monkeypatch, raises=TimeoutError("timed out"))
    s = Summarizer(DictCfg({"summarize": {"mode": "haiku"}}))
    reg = Registry()

    with caplog.at_level("WARNING"):
        for _ in range(4):
            s.line_for_batch([ev(text="x")], reg)

    assert s.degraded == 4, "every degrade is counted"
    warnings = [r for r in caplog.records if "degraded to template" in r.message]
    assert len(warnings) == 1, "but a broken key must not write a line per announcement"


# ── ollama ───────────────────────────────────────────────────────────────────

def test_ollama_success_and_failure(tmp_path, monkeypatch):
    _isolate_keystore(tmp_path, monkeypatch)
    calls = []
    _stub_urlopen(monkeypatch, captured=calls,
                  payload={"message": {"content": "Fixed the mirror writer."}})
    cfg = DictCfg({"summarize": {"mode": "ollama"}})

    spoken, s = summarize_with(cfg, ev(text="Fixed the Windows mirror writer today."))
    assert "Fixed the mirror writer" in spoken
    assert s.degraded == 0
    assert len(calls) == 1 and "/api/chat" in calls[0].full_url

    _stub_urlopen(monkeypatch, raises=ConnectionRefusedError("no ollama"))
    spoken, s = summarize_with(cfg, ev(text="Fixed the Windows mirror writer today."))
    assert "I'm waiting for you" in spoken
    assert "ConnectionRefusedError" in s.last_degrade


# ── self ─────────────────────────────────────────────────────────────────────

def test_self_mode_prefers_the_marker_then_derives_locally(tmp_path, monkeypatch):
    """Without a marker, self speaks the opening sentence rather than the template.

    That is what every Cursor session and every pre-install Codex session gets, so it is
    worth pinning: it is not a fallback to template.
    """
    _isolate_keystore(tmp_path, monkeypatch)
    cfg = DictCfg({"summarize": {"mode": "self"}})

    marked = line(cfg, ev(text="blah blah\n<!-- speak: Mirror writer fixed. -->"))
    assert "Mirror writer fixed" in marked

    derived = line(cfg, ev(text="# Heading\n\nThe mirror writer never ran from WSL."))
    assert "mirror writer never ran" in derived.lower()
    assert "waiting for you" not in derived, "not the template"
