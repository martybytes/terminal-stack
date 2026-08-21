"""In-process Windows media playback and SAPI fallback.

No command-line player is spawned: ffplay/ffprobe were console applications
and were the visible-window source on every spoken hook.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

log = logging.getLogger(__name__)

class Playback:
    def __init__(self) -> None:
        self.current_pid: int | None = None  # retained for AudioController API
        # The in-flight utterance, so `stop()` can end it. Before this nothing could
        # interrupt speech already playing: the player was a local and the caller simply
        # blocked until the audio finished.
        self._lock = threading.Lock()
        self._active: tuple[object, threading.Event] | None = None
        self._stopped = threading.Event()  # set by stop(), cleared per utterance

    def probe_duration(self, media: Path) -> float | None:
        try:
            from mutagen import File as MutagenFile

            parsed = MutagenFile(str(media))
            length = getattr(getattr(parsed, "info", None), "length", None)
            return float(length) if length is not None else None
        except (OSError, TypeError, ValueError):
            return None

    def play(self, media: Path, timeout: float = 60) -> bool:
        """Blocking play; returns True on success."""
        try:
            from winrt.windows.foundation import Uri
            from winrt.windows.media.core import MediaSource
            from winrt.windows.media.playback import MediaPlayer

            ended = threading.Event()
            failed = threading.Event()
            self._stopped.clear()  # per utterance, so a past stop cannot mask this one
            stopped = self._stopped
            player = MediaPlayer()
            try:
                player.command_manager.is_enabled = False
            except (AttributeError, RuntimeError):
                pass
            player.add_media_ended(lambda sender, args: ended.set())
            player.add_media_failed(lambda sender, args: (failed.set(), ended.set()))
            source = MediaSource.create_from_uri(Uri(media.resolve().as_uri()))
            player.source = source
            player.play()
            with self._lock:
                self._active = (player, ended)
            completed = ended.wait(timeout=timeout)
            if stopped.is_set():
                return True  # cut off on purpose; not a playback failure
            return completed and not failed.is_set()
        except Exception as exc:  # noqa: BLE001 — playback failure falls to SAPI upstream
            log.warning("Windows MediaPlayer failed: %s", exc)
            return False
        finally:
            with self._lock:
                self._active = None
            try:
                player.close()
            except (NameError, AttributeError, RuntimeError):
                pass

    def stop(self) -> bool:
        """Cut off the utterance in flight. True if there was one to cut off.

        Called when a mute lands, from a different thread than `play`. Everything here is
        best-effort: if the cross-thread WinRT call fails, the sentence merely finishes,
        which is what happened before this existed.
        """
        with self._lock:
            active = self._active
        if active is None:
            return False
        player, ended = active
        self._stopped.set()
        try:
            player.pause()
        except Exception as exc:  # noqa: BLE001 -- COM across threads; degrade, never raise
            log.debug("pausing the active player failed: %s", exc)
        ended.set()  # unblock play()'s wait; its finally does the close
        log.info("stopped speech in flight")
        return True

    @staticmethod
    def speak_sapi(text: str) -> bool:
        """Last-resort local voice — no media file, no engines, no network."""
        try:
            import comtypes
            import comtypes.client

            comtypes.CoInitialize()
            voice = comtypes.client.CreateObject("SAPI.SpVoice")
            voice.Speak(text)
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("SAPI fallback failed: %s", exc)
            return False
        finally:
            try:
                comtypes.CoUninitialize()
            except (NameError, AttributeError):
                pass
