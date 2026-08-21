"""Dispatcher: drains the scheduler and turns batches into ducked speech.

Single thread — speech is naturally serialized, which replaces the old
machine-global play lock.
"""

from __future__ import annotations

import datetime
import logging
import threading
import time

from .events import P0_INTERACTIVE, P1_ERROR, P2_DONE, Event

log = logging.getLogger(__name__)


class Dispatcher(threading.Thread):
    def __init__(self, cfg, scheduler, registry, summarizer, synth, playback,
                 audio, wez) -> None:
        super().__init__(name="ttsd-dispatch", daemon=True)
        self.cfg = cfg
        self.scheduler = scheduler
        self.registry = registry
        self.summarizer = summarizer
        self.synth = synth
        self.playback = playback
        self.audio = audio
        self.wez = wez
        self._stop = threading.Event()
        self.dnd_until: float | None = None  # time.time(); None = off
        self.spoken = 0
        self.suppressed = 0
        self.last_line = ""

    def stop(self) -> None:
        self._stop.set()
        with self.scheduler.cond:
            self.scheduler.cond.notify()

    # ── DND ───────────────────────────────────────────────────────────────

    def dnd_active(self) -> bool:
        if self.dnd_until is None:
            return False
        if self.dnd_until == 0:
            return True  # indefinite
        if time.time() >= self.dnd_until:
            self.dnd_until = None
            return False
        return True

    def set_dnd(self, enabled: bool, minutes: float | None = None) -> None:
        if not enabled:
            self.dnd_until = None
        else:
            self.dnd_until = time.time() + minutes * 60 if minutes else 0

    def _quiet_hours(self) -> bool:
        if not self.cfg.get("quietHours.enabled", False):
            return False
        try:
            now = datetime.datetime.now().time()
            start = datetime.time.fromisoformat(str(self.cfg.get("quietHours.start", "22:00")))
            end = datetime.time.fromisoformat(str(self.cfg.get("quietHours.end", "07:00")))
        except ValueError:
            return False
        if start <= end:
            return start <= now < end
        return now >= start or now < end  # crosses midnight

    # ── main loop ─────────────────────────────────────────────────────────

    def run(self) -> None:
        while not self._stop.is_set():
            batch = self.scheduler.collect_due()
            if not batch:
                if self.scheduler.pending_count() == 0:
                    # Releases the anticipatory hold if queued work vanished
                    # (barge-in) before it was spoken. Extra releases clamp at 0.
                    self.audio.release()
                hint = min(self.scheduler.wait_hint(), 1.0)
                with self.scheduler.cond:
                    self.scheduler.cond.wait(timeout=hint)
                continue
            try:
                self._speak_batch(batch)
            except Exception as exc:  # noqa: BLE001 — one bad batch must not kill the loop
                log.exception("speak failed: %s", exc)
            if self.scheduler.pending_count() == 0:
                self.audio.release()

    def _speak_batch(self, batch: list[Event]) -> None:
        batch = [ev for ev in batch if not self._suppress(ev)]
        if not batch:
            return

        line = self.summarizer.line_for_batch(batch, self.registry)
        if not line:
            return

        voice = ""
        if len(batch) == 1:
            sess = self.registry.get(batch[0].session_key)
            if sess:
                voice = self.registry.voice_for(
                    sess, str(self.cfg.get("kokoro.voice", "am_adam")))

        result = self.synth.synthesize(line, voice)
        if result is None:
            return
        duration = None
        if result.media is not None:
            duration = self.playback.probe_duration(result.media)

        self.audio.hold(duration)
        try:
            if result.media is not None:
                if not self.playback.play(result.media):
                    self.playback.speak_sapi(line)
            else:
                self.playback.speak_sapi(result.sapi_text)
        finally:
            self.audio.release()
            # A back-to-back batch re-holds before idleRestoreSec expires,
            # so the music doesn't pump between coalesced utterances.
            if self.scheduler.pending_count() > 0:
                self.audio.hold(None)
        self.spoken += 1
        self.last_line = line
        log.info("spoke [%s]: %s", result.engine, line)

    def _suppress(self, ev: Event) -> bool:
        # Same .events gate the direct cc-tts-notify path applies.
        events = self.cfg.get("events") or []
        if ev.state and isinstance(events, list) and ev.state not in events:
            self.suppressed += 1
            return True
        interactive = ev.priority in (P0_INTERACTIVE, P1_ERROR)
        if self.dnd_active() or self._quiet_hours():
            if not (interactive and self.cfg.get("quietHours.allowInteractive", True)):
                self.suppressed += 1
                return True
        if (ev.priority == P2_DONE
                and self.cfg.get("daemon.suppressFocused", False)
                and ev.pane):
            focused = self.wez.focused_pane()
            if focused is not None and focused == ev.pane:
                self.suppressed += 1
                log.info("suppressed done for focused pane %s (%s)",
                         ev.pane, ev.project_name)
                return True
        return False
