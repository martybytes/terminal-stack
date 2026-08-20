"""Priority queue with coalescing for spoken announcements.

Classes: P0 question/permission · P1 error · P2 done · P3 info.

Rules
- One pending item per (session_key, class); newer replaces older.
- Cursor "done" gets a hold (its stop hook can fire every model turn) and a
  per-conversation cooldown between spoken dones.
- The first eligible P2 opens a coalescing window; if ≥2 sessions finish
  inside it they become one utterance ("Three sessions finished: …").
  P0/P1 bypass the window.
- Activity for a session (new prompt, session start) cancels its pending
  P1/P2 — the user is already looking.
- Stale items are dropped at dequeue, not enqueue.

All decisions live in collect_due(now) with an injected clock so the whole
state machine is unit-testable without threads.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from .events import P0_INTERACTIVE, P1_ERROR, P2_DONE, P3_INFO, Event

log = logging.getLogger(__name__)


@dataclass
class _Item:
    event: Event
    enqueued: float  # monotonic
    eligible: float  # monotonic; > enqueued only for held cursor stops


@dataclass
class SchedulerConfig:
    coalesce_sec: float = 1.8
    coalesce_cap_sec: float = 4.0
    done_max_age_sec: float = 20.0
    interactive_max_age_sec: float = 120.0
    max_queue: int = 12
    cursor_hold_sec: float = 3.0
    cursor_cooldown_sec: float = 15.0


class Scheduler:
    def __init__(self, cfg: SchedulerConfig, clock=time.monotonic) -> None:
        self.cfg = cfg
        self.clock = clock
        self.cond = threading.Condition()
        self._pending: dict[tuple[str, int], _Item] = {}
        self._cooldown_until: dict[str, float] = {}
        self._window_close: float | None = None
        self._window_cap: float | None = None
        self.dropped = 0  # stats for /v1/status

    # ── producers (HTTP handler threads) ──────────────────────────────────

    def submit(self, ev: Event) -> None:
        now = self.clock()
        with self.cond:
            if ev.is_activity or ev.is_session_end:
                self._cancel_locked(ev.session_key, (P1_ERROR, P2_DONE, P3_INFO))
                self.cond.notify()
                return

            cls = ev.priority
            if cls == P2_DONE and ev.source == "cursor":
                if now < self._cooldown_until.get(ev.session_key, 0.0):
                    self.dropped += 1
                    return
                eligible = now + self.cfg.cursor_hold_sec
            else:
                eligible = now

            self._pending[(ev.session_key, cls)] = _Item(ev, now, eligible)
            if cls == P2_DONE:
                if self._window_close is None:
                    # Open the coalescing window as the item arrives, so an
                    # idle dispatcher speaks exactly coalesce_sec later.
                    self._window_close = eligible + self.cfg.coalesce_sec
                    self._window_cap = eligible + self.cfg.coalesce_cap_sec
                elif self._window_cap is not None:
                    # Extend an open window for the newcomer, capped.
                    self._window_close = min(now + self.cfg.coalesce_sec, self._window_cap)
            self._evict_overflow_locked()
            self.cond.notify()

    def cancel_session(self, session_key: str) -> None:
        with self.cond:
            self._cancel_locked(session_key, (P0_INTERACTIVE, P1_ERROR, P2_DONE, P3_INFO))

    # ── consumer (dispatcher thread) ──────────────────────────────────────

    def collect_due(self, now: float | None = None) -> list[Event]:
        """Return the next batch to speak ([] if nothing is due yet).

        A batch is one utterance: a single event, or several P2 "done"
        events that coalesced.
        """
        if now is None:
            now = self.clock()
        with self.cond:
            self._drop_stale_locked(now)

            for cls in (P0_INTERACTIVE, P1_ERROR):
                item = self._earliest_locked(cls, now)
                if item:
                    del self._pending[(item.event.session_key, cls)]
                    self._reset_window_if_empty_locked()
                    return [item.event]

            done = sorted(
                (i for (k, c), i in self._pending.items()
                 if c == P2_DONE and i.eligible <= now),
                key=lambda i: i.enqueued,
            )
            if done:
                if self._window_close is None:  # defensive; submit() opens it
                    self._window_close = now + self.cfg.coalesce_sec
                    self._window_cap = now + self.cfg.coalesce_cap_sec
                if now < self._window_close:
                    return []
                for item in done:
                    del self._pending[(item.event.session_key, P2_DONE)]
                    if item.event.source == "cursor":
                        self._cooldown_until[item.event.session_key] = (
                            now + self.cfg.cursor_cooldown_sec
                        )
                self._window_close = self._window_cap = None
                return [i.event for i in done]

            item = self._earliest_locked(P3_INFO, now)
            if item:
                del self._pending[(item.event.session_key, P3_INFO)]
                return [item.event]
            return []

    def wait_hint(self, now: float | None = None) -> float:
        """Seconds until the next possible action (dispatcher sleep bound)."""
        if now is None:
            now = self.clock()
        with self.cond:
            deadlines = [i.eligible for i in self._pending.values()]
            if self._window_close is not None:
                deadlines.append(self._window_close)
            if not deadlines:
                return 30.0
            return max(0.05, min(deadlines) - now)

    def pending_count(self) -> int:
        with self.cond:
            return len(self._pending)

    def pending_summary(self) -> list[dict]:
        with self.cond:
            return [
                {
                    "session": key[0],
                    "class": key[1],
                    "event": item.event.event,
                    "state": item.event.state,
                    "project": item.event.project_name,
                }
                for key, item in sorted(self._pending.items(), key=lambda kv: kv[1].enqueued)
            ]

    # ── internals (lock held) ─────────────────────────────────────────────

    def _earliest_locked(self, cls: int, now: float) -> _Item | None:
        due = [i for (k, c), i in self._pending.items() if c == cls and i.eligible <= now]
        return min(due, key=lambda i: i.enqueued) if due else None

    def _cancel_locked(self, session_key: str, classes: tuple[int, ...]) -> None:
        for cls in classes:
            if self._pending.pop((session_key, cls), None) is not None:
                self.dropped += 1
        self._reset_window_if_empty_locked()

    def _drop_stale_locked(self, now: float) -> None:
        for key, item in list(self._pending.items()):
            cls = key[1]
            age = now - item.enqueued
            limit = (self.cfg.interactive_max_age_sec
                     if cls in (P0_INTERACTIVE, P1_ERROR)
                     else self.cfg.done_max_age_sec)
            if age > limit:
                del self._pending[key]
                self.dropped += 1
                log.info("dropped stale %s (%s, %.0fs old)",
                         item.event.state or item.event.event, key[0], age)
        self._reset_window_if_empty_locked()

    def _reset_window_if_empty_locked(self) -> None:
        if not any(c == P2_DONE for (_, c) in self._pending):
            self._window_close = self._window_cap = None

    def _evict_overflow_locked(self) -> None:
        while len(self._pending) > self.cfg.max_queue:
            victims = sorted(
                ((k, i) for k, i in self._pending.items() if k[1] in (P2_DONE, P3_INFO)),
                key=lambda kv: kv[1].enqueued,
            )
            if not victims:
                break
            del self._pending[victims[0][0]]
            self.dropped += 1
