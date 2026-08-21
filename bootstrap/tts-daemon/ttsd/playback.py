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
            completed = ended.wait(timeout=timeout)
            return completed and not failed.is_set()
        except Exception as exc:  # noqa: BLE001 — playback failure falls to SAPI upstream
            log.warning("Windows MediaPlayer failed: %s", exc)
            return False
        finally:
            try:
                player.close()
            except (NameError, AttributeError, RuntimeError):
                pass

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
