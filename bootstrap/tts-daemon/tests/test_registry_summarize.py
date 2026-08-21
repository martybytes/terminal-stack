"""Registry ordinal/voice tests + summarizer marker/template tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ttsd.events import Event, EventError, parse_event
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


def ev(state="waiting", key="claude:s1", project="alpha", text="",
       override="", **kw) -> Event:
    return Event(source="claude", event=state, state=state, session_key=key,
                 project_name=project, text=text, override=override, **kw)


def test_ordinals_and_spoken_names():
    reg = Registry()
    a = reg.touch("claude:a", "claude", "terminal-stack")
    assert reg.spoken_name(a) == "terminal-stack"
    b = reg.touch("claude:b", "claude", "terminal-stack")
    assert reg.spoken_name(a) == "terminal-stack one"
    assert reg.spoken_name(b) == "terminal-stack two"
    reg.end("claude:a")
    assert reg.spoken_name(b) == "terminal-stack"
    c = reg.touch("claude:c", "claude", "terminal-stack")
    assert c.ordinal == 1  # freed slot reused


def test_voice_clash_gets_distinct_voices():
    reg = Registry(voice_pool=["v1", "v2"], per_session_voice=True)
    a = reg.touch("claude:a", "claude", "alpha")
    b = reg.touch("claude:b", "claude", "alpha")
    assert {a.voice, b.voice} == {"v1", "v2"}
    assert reg.voice_for(a, "default") == a.voice


def test_self_marker_extraction():
    s = Summarizer(DictCfg({"summarize": {"mode": "self"}}))
    reg = Registry()
    line = s.line_for_batch(
        [ev(text="Long answer…\n<!-- speak: Added retry logic, tests pass. -->")],
        reg)
    assert "Added retry logic, tests pass." in line
    assert "alpha finished." in line
    assert line.startswith("Claude.")


def test_self_without_marker_falls_back_to_template():
    s = Summarizer(DictCfg({"summarize": {"mode": "self"}}))
    line = s.line_for_batch([ev(text="no marker here")], Registry())
    assert "Done in alpha" in line


def test_error_type_enrichment():
    s = Summarizer(DictCfg())
    line = s.line_for_batch([ev(state="error", error_type="rate_limit")], Registry())
    assert "Rate limited in alpha." in line


def test_permission_names_tool():
    s = Summarizer(DictCfg())
    line = s.line_for_batch([ev(state="permission", tool_name="Bash")], Registry())
    assert "alpha wants to run Bash." in line


def test_coalesced_line():
    s = Summarizer(DictCfg())
    reg = Registry()
    batch = [ev(key=f"claude:{i}", project=p)
             for i, p in enumerate(["alpha", "beta", "gamma"])]
    line = s.line_for_batch(batch, reg)
    assert line == "Three sessions finished: alpha, beta, and gamma."


def test_clamp_max_chars():
    s = Summarizer(DictCfg({"maxChars": 50, "summarize": {"mode": "self"}}))
    line = s.line_for_batch(
        [ev(text="<!-- speak: " + "word " * 40 + "-->")], Registry())
    assert len(line) <= 50


def test_codex_source_parses_and_uses_prefix():
    parsed = parse_event({
        "source": "codex", "event": "stop", "state": "waiting",
        "session_key": "codex:s1", "project": {"name": "terminal-stack"},
    })
    line = Summarizer(DictCfg({"sources": {"codex": {
        "prefixEnabled": True, "prefix": "Codex"}}})).line_for_batch(
            [parsed], Registry())
    assert line.startswith("Codex.")


def test_unknown_source_is_rejected():
    try:
        parse_event({"source": "mystery", "event": "stop", "state": "waiting",
                     "session_key": "mystery:s1"})
    except EventError:
        return
    raise AssertionError("unknown TTS source was accepted")
