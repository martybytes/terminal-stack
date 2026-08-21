"""Dispatcher: drains the scheduler and turns batches into ducked speech.

Single thread, so speech here is naturally serialized. That is only true of the daemon:
`hooks.direct_speak` spawns a detached process per hook and needs `speaklock.py` to get the
same guarantee, which is why the machine-global play lock came back for that path alone.

Serializing is not deduplicating. Several hooks can describe one user-facing event, and
`_suppress` collapses those through `history.recently_spoken`.
"""

from __future__ import annotations

import datetime
import logging
import threading
import time

from . import history, mute
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
        self.spoken = 0
        self.suppressed = 0
        self.last_line = ""

    def stop(self) -> None:
        self._stop.set()
        with self.scheduler.cond:
            self.scheduler.cond.notify()

    # ── mute / quiet hours ────────────────────────────────────────────────
    #
    # `dnd_active` used to be a float on this object, set from the tray. Three problems:
    # it died with the process, a direct worker in another process could not see it, and
    # the enforcement below let every P0/P1 event through anyway. `mute.py` replaces it
    # with a sentinel file that all three paths read; this method survives only so
    # /healthz and /v1/status keep reporting the same field.

    def dnd_active(self) -> bool:
        return mute.is_muted()

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
                # Record the crash too. A batch that died mid-speak is the most
                # interesting thing history can tell you, and without this the row
                # simply never appears -- which reads as "nothing was ever queued".
                for ev in batch:
                    history.record("failed", event=ev, line=str(exc)[:200], daemon=True)
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

        synth_started = time.monotonic()
        result = self.synth.synthesize(line, voice)
        synth_ms = int((time.monotonic() - synth_started) * 1000)
        if result is None:
            for ev in batch:
                history.record("synth_failed", event=ev, line=line, daemon=True)
            return
        duration = None
        if result.media is not None:
            duration = self.playback.probe_duration(result.media)

        self.audio.hold(duration)
        play_started = time.monotonic()
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
        # One row per session in the batch, not per utterance: a coalesced line announces
        # several sessions, and each needs its own dedupe memory so a straggling hook for
        # any of them is recognised as a duplicate.
        play_ms = int((time.monotonic() - play_started) * 1000)
        for ev in batch:
            history.record(history.SPOKEN, event=ev, line=line, daemon=True,
                           engine=str(getattr(result, "engine", "") or ""),
                           synth_ms=synth_ms, play_ms=play_ms)
        if len(batch) > 1:
            log.info("coalesced %d sessions into one line", len(batch))
        history.prune(float(self.cfg.get("history.days", 14)))

    def _suppress(self, ev: Event) -> bool:
        # Same .events gate the direct cc-tts-notify path applies.
        events = self.cfg.get("events") or []
        if ev.state and isinstance(events, list) and ev.state not in events:
            self.suppressed += 1
            return True
        # One user-facing event can arrive as several hooks: a Claude AskUserQuestion trips
        # Notification, PermissionRequest and PreToolUse. They are all P0, and P0 is drained
        # immediately, so the scheduler's (session, class) slot never holds two at once --
        # the first is spoken and gone before the next arrives. This is the check that
        # collapses them, and it works across processes so a direct worker sees it too.
        dedupe_sec = float(self.cfg.get("debounceSec", 5) or 0)
        if history.recently_spoken(ev.session_key, ev.priority, dedupe_sec):
            history.record(history.DEDUPED, event=ev, daemon=True)
            self.suppressed += 1
            log.info("duplicate suppressed: %s p%s within %.0fs",
                     ev.session_key, ev.priority, dedupe_sec)
            return True
        # Muted is absolute -- no allowInteractive escape. That exemption is why the old
        # tray "Do not disturb" silenced "done" announcements and let every question,
        # permission prompt and error through, which is exactly backwards.
        if mute.is_muted():
            history.record(history.MUTED, event=ev, daemon=True)
            self.suppressed += 1
            return True
        # Quiet hours keep their own escape hatch: they are a schedule, not a panic button.
        interactive = ev.priority in (P0_INTERACTIVE, P1_ERROR)
        if self._quiet_hours():
            if not (interactive and self.cfg.get("quietHours.allowInteractive", True)):
                history.record(history.SUPPRESSED_DND, event=ev, daemon=True)
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
