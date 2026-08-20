"""Session registry: session_key → identity (spoken name, ordinal, voice, pane).

Ordinals disambiguate sessions sharing a project name: the first live
session in a project is plain "terminal-stack"; a second becomes
"terminal-stack two". Ordinals are the lowest free slot at creation and
live sessions are never renumbered; a freed ordinal may be reused later.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_ORDINAL_WORDS = {
    1: "", 2: "two", 3: "three", 4: "four", 5: "five",
    6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten",
}


def ordinal_word(n: int) -> str:
    return _ORDINAL_WORDS.get(n, str(n))


@dataclass
class Session:
    session_key: str
    source: str
    project_name: str
    ordinal: int
    voice: str = ""
    pane: str = ""
    project_dir: str = ""
    created: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    last_state: str = ""


class Registry:
    def __init__(self, voice_pool: list[str] | None = None,
                 per_session_voice: bool = False,
                 ttl_min: float = 240,
                 persist_path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._sessions: dict[str, Session] = {}
        self.voice_pool = list(voice_pool or [])
        self.per_session_voice = per_session_voice
        self.ttl_sec = ttl_min * 60
        self._persist_path = persist_path
        if persist_path:
            self._load(persist_path)

    # ── lookup / upsert ────────────────────────────────────────────────────

    def touch(self, session_key: str, source: str, project_name: str,
              project_dir: str = "", pane: str = "", state: str = "") -> Session:
        with self._lock:
            self._expire_locked()
            sess = self._sessions.get(session_key)
            if sess is None:
                ordinal = self._next_ordinal_locked(project_name)
                sess = Session(
                    session_key=session_key,
                    source=source,
                    project_name=project_name,
                    ordinal=ordinal,
                    voice=self._pick_voice_locked(project_name, ordinal),
                )
                self._sessions[session_key] = sess
                log.info("session %s → %s #%d voice=%s",
                         session_key, project_name, ordinal, sess.voice or "-")
            sess.last_seen = time.time()
            if project_dir:
                sess.project_dir = project_dir
            if pane:
                sess.pane = pane
            if state:
                sess.last_state = state
            self._save_locked()
            return sess

    def end(self, session_key: str) -> None:
        with self._lock:
            if self._sessions.pop(session_key, None) is not None:
                log.info("session %s ended", session_key)
                self._save_locked()

    def get(self, session_key: str) -> Session | None:
        with self._lock:
            return self._sessions.get(session_key)

    def all(self) -> list[Session]:
        with self._lock:
            self._expire_locked()
            return list(self._sessions.values())

    # ── identity ───────────────────────────────────────────────────────────

    def spoken_name(self, sess: Session) -> str:
        """Project name, plus the ordinal word while ≥2 live sessions share it."""
        with self._lock:
            twins = sum(1 for s in self._sessions.values()
                        if s.project_name == sess.project_name)
        if twins >= 2 and sess.ordinal >= 2:
            return f"{sess.project_name} {ordinal_word(sess.ordinal)}"
        if twins >= 2:
            return f"{sess.project_name} one"
        return sess.project_name

    def voice_for(self, sess: Session, default_voice: str) -> str:
        if self.per_session_voice and sess.voice:
            return sess.voice
        return default_voice

    # ── internals (call with lock held) ───────────────────────────────────

    def _next_ordinal_locked(self, project_name: str) -> int:
        used = {s.ordinal for s in self._sessions.values()
                if s.project_name == project_name}
        n = 1
        while n in used:
            n += 1
        return n

    def _pick_voice_locked(self, project_name: str, ordinal: int) -> str:
        if not self.voice_pool:
            return ""
        in_use = {s.voice for s in self._sessions.values()
                  if s.project_name == project_name and s.voice}
        for voice in self.voice_pool:
            if voice not in in_use:
                return voice
        return self.voice_pool[(ordinal - 1) % len(self.voice_pool)]

    def _expire_locked(self) -> None:
        cutoff = time.time() - self.ttl_sec
        stale = [k for k, s in self._sessions.items() if s.last_seen < cutoff]
        for k in stale:
            del self._sessions[k]
        if stale:
            log.info("expired %d idle session(s)", len(stale))

    # ── persistence (best-effort; losing it only loses ordinals) ──────────

    def _save_locked(self) -> None:
        if not self._persist_path:
            return
        try:
            payload = [vars(s) for s in self._sessions.values()]
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_path.write_text(json.dumps(payload), encoding="utf-8")
        except OSError as exc:
            log.debug("registry save failed: %s", exc)

    def _load(self, path: Path) -> None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for row in payload:
                sess = Session(**row)
                self._sessions[sess.session_key] = sess
        except (OSError, ValueError, TypeError):
            pass
