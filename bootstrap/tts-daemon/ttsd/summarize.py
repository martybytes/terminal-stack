"""Build the spoken line for a batch of events.

Four modes for "done" announcements — self | haiku | ollama | template —
each degrading rightward to template, which always produces something.
Interactive (P0) events skip the LLM modes so questions stay snappy.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.request

from .events import P0_INTERACTIVE, P2_DONE, Event
from .registry import Registry

log = logging.getLogger(__name__)

SPEAK_MARKER = re.compile(r"<!--\s*speak:\s*(.{1,200}?)\s*-->", re.DOTALL)

_HAIKU_SYSTEM = (
    "You turn an AI coding assistant's final message into ONE spoken sentence "
    "under 15 words for a voice completion announcement. Plain words only — no "
    "markdown, no code, no paths. If there is nothing worth saying aloud, "
    "return an empty string."
)

# Friendlier template lines for typed StopFailure reasons.
_ERROR_TYPE_LINES = {
    "rate_limit": "Rate limited in {project}.",
    "overloaded": "The API is overloaded in {project}.",
    "billing_error": "Billing issue in {project}.",
    "authentication_failed": "Authentication failed in {project}.",
    "max_output_tokens": "Hit the output limit in {project}.",
}


class Summarizer:
    def __init__(self, cfg, degraded_counter=None) -> None:
        self.cfg = cfg
        self.degraded = 0

    # ── public ────────────────────────────────────────────────────────────

    def line_for_batch(self, batch: list[Event], registry: Registry) -> str | None:
        """None means "deliberately silent" (emptyMeansSilent honored)."""
        if len(batch) > 1:
            names = [registry.spoken_name(registry.touch(
                e.session_key, e.source, e.project_name, e.project_dir, e.pane))
                for e in batch]
            return f"{_count_word(len(names))} sessions finished: {_join(names)}."
        return self._line_for_one(batch[0], registry)

    # ── single event ──────────────────────────────────────────────────────

    def _line_for_one(self, ev: Event, registry: Registry) -> str | None:
        sess = registry.touch(ev.session_key, ev.source, ev.project_name,
                              ev.project_dir, ev.pane, ev.state)
        spoken = registry.spoken_name(sess)
        prefix = self._prefix(ev.source)

        if ev.priority != P2_DONE:
            body = self._template_line(ev, spoken)
            return _clamp(_assemble(prefix, body), self._max_chars())

        mode = str(self.cfg.get("summarize.mode", "template"))
        summary = ""
        if mode == "self":
            summary = self._extract_marker(ev.text)
        elif mode == "haiku":
            summary = self._llm_haiku(ev.text)
            if summary == "" and self.cfg.get("summarize.emptyMeansSilent", False):
                return None
        elif mode == "ollama":
            summary = self._llm_ollama(ev.text)
            if summary == "" and self.cfg.get("summarize.emptyMeansSilent", False):
                return None

        if summary:
            body = f"{spoken} finished. {summary}"
        else:
            body = self._template_line(ev, spoken)
        return _clamp(_assemble(prefix, body), self._max_chars())

    # ── template mode (the floor everything lands on) ─────────────────────

    def _template_line(self, ev: Event, spoken: str) -> str:
        templates = {
            "waiting": str(self.cfg.get("announce.templates.waiting",
                                        "Done in {project}. I'm waiting for you.")),
            "error": str(self.cfg.get("announce.templates.error",
                                      "Error in {project}. You may want to look.")),
            "question": str(self.cfg.get("announce.templates.question",
                                         "I have a question for you.")),
            "permission": str(self.cfg.get("announce.templates.permission",
                                           "Permission needed in {project}.")),
        }
        state = ev.state or "waiting"
        line = templates.get(state, templates["waiting"])
        if state == "error" and ev.error_type in _ERROR_TYPE_LINES:
            line = _ERROR_TYPE_LINES[ev.error_type]
        elif state == "permission" and ev.tool_name:
            line = "{project} wants to run " + _speakable(ev.tool_name) + "."
        elif state == "waiting" and ev.notification_type == "idle_prompt":
            line = "Still waiting in {project}."
        elif state == "question" and "{project}" not in line:
            line = "{project}: " + line
        if ev.priority == P0_INTERACTIVE and ev.override:
            line = line.rstrip(".") + ". " + _speakable(ev.override)
        return line.replace("{project}", spoken)

    # ── self mode ─────────────────────────────────────────────────────────

    @staticmethod
    def _extract_marker(text: str) -> str:
        matches = SPEAK_MARKER.findall(text or "")
        return _speakable(matches[-1]) if matches else ""

    # ── LLM modes (best-effort; empty string on any failure) ─────────────

    def _llm_haiku(self, text: str) -> str:
        if not text:
            return ""
        key = os.environ.get(str(self.cfg.get("summarize.haiku.keyEnv",
                                              "ANTHROPIC_API_KEY")), "")
        if not key:
            return ""
        payload = {
            "model": str(self.cfg.get("summarize.haiku.model", "claude-haiku-4-5")),
            "max_tokens": 60,
            "system": _HAIKU_SYSTEM,
            "messages": [{"role": "user", "content": text[:4000]}],
        }
        try:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps(payload).encode(),
                headers={
                    "content-type": "application/json",
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
            )
            timeout = float(self.cfg.get("summarize.haiku.timeoutSec", 3))
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            parts = [b.get("text", "") for b in data.get("content", [])
                     if b.get("type") == "text"]
            return _speakable(" ".join(parts))
        except Exception as exc:  # noqa: BLE001 — any failure degrades to template
            self.degraded += 1
            log.warning("haiku summarizer failed: %s", exc)
            return ""

    def _llm_ollama(self, text: str) -> str:
        if not text:
            return ""
        url = str(self.cfg.get("summarize.ollama.url", "http://127.0.0.1:11434"))
        payload = {
            "model": str(self.cfg.get("summarize.ollama.model", "llama3.2:3b")),
            "stream": False,
            "messages": [
                {"role": "system", "content": _HAIKU_SYSTEM},
                {"role": "user", "content": text[:4000]},
            ],
        }
        try:
            req = urllib.request.Request(
                url.rstrip("/") + "/api/chat",
                data=json.dumps(payload).encode(),
                headers={"content-type": "application/json"},
            )
            timeout = float(self.cfg.get("summarize.ollama.timeoutSec", 4))
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            return _speakable(data.get("message", {}).get("content", ""))
        except Exception as exc:  # noqa: BLE001
            self.degraded += 1
            log.warning("ollama summarizer failed: %s", exc)
            return ""

    # ── helpers ───────────────────────────────────────────────────────────

    def _prefix(self, source: str) -> str:
        if source == "test":
            source = "claude"
        if not self.cfg.get(f"sources.{source}.prefixEnabled", True):
            return ""
        return str(self.cfg.get(f"sources.{source}.prefix", source.title()))

    def _max_chars(self) -> int:
        try:
            return max(40, int(self.cfg.get("maxChars", 120)))
        except (TypeError, ValueError):
            return 120


def _assemble(prefix: str, body: str) -> str:
    return f"{prefix}. {body}" if prefix else body


def _clamp(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _speakable(text: str) -> str:
    """Strip the things that read badly aloud: code, markdown, URLs."""
    text = re.sub(r"```.*?```", " ", text or "", flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"[*_#>|]", " ", text)
    return " ".join(text.split())


def _count_word(n: int) -> str:
    words = {2: "Two", 3: "Three", 4: "Four", 5: "Five",
             6: "Six", 7: "Seven", 8: "Eight", 9: "Nine"}
    return words.get(n, str(n))


def _join(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"
