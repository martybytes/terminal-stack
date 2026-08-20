"""TTS synthesis ladder: Kokoro → Chatterbox → edge-tts → SAPI.

Payloads mirror cc-tts-lib.sh exactly (same endpoints, same fields), so a
Kokoro/Chatterbox setup that works for the direct path works here too.
SAPI is the last-resort floor and speaks directly (no media file).
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)


class SynthResult:
    def __init__(self, media: Path | None, engine: str, sapi_text: str = "") -> None:
        self.media = media  # None → engine speaks itself (SAPI)
        self.engine = engine
        self.sapi_text = sapi_text


class Synth:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.last_engine = ""

    def synthesize(self, text: str, voice: str = "") -> SynthResult | None:
        engine = str(self.cfg.get("engine", "kokoro"))
        order = {
            "kokoro": ["kokoro"],
            "chatterbox": ["chatterbox"],
            "auto": ["kokoro", "chatterbox"],
        }.get(engine, ["kokoro"])
        for name in order:
            media = getattr(self, f"_synth_{name}")(text, voice)
            if media:
                self.last_engine = name
                return SynthResult(media, name)
        media = self._synth_edge(text)
        if media:
            self.last_engine = "edge"
            return SynthResult(media, "edge")
        self.last_engine = "sapi"
        return SynthResult(None, "sapi", sapi_text=text)

    # ── engines ───────────────────────────────────────────────────────────

    def _effective_speed(self) -> float:
        try:
            exc = float(self.cfg.get("excitement", 0.25))
            return round(0.8 + exc * 0.4, 2)
        except (TypeError, ValueError):
            return float(self.cfg.get("kokoro.speed", 1.0))

    def _synth_kokoro(self, text: str, voice: str) -> Path | None:
        url = str(self.cfg.get("kokoro.url", "http://127.0.0.1:8880"))
        fmt = str(self.cfg.get("kokoro.format", "mp3"))
        payload = {
            "model": "kokoro",
            "input": text,
            "voice": voice or str(self.cfg.get("kokoro.voice", "am_adam")),
            "response_format": fmt,
            "speed": self._effective_speed(),
        }
        return self._post_speech(url, payload,
                                 float(self.cfg.get("kokoro.timeoutSec", 15)), fmt)

    def _synth_chatterbox(self, text: str, voice: str) -> Path | None:
        url = str(self.cfg.get("chatterbox.url", "http://127.0.0.1:8881"))
        try:
            energy = float(self.cfg.get("excitement",
                                        self.cfg.get("chatterbox.energy", 0.25)))
        except (TypeError, ValueError):
            energy = 0.25
        payload = {
            "input": text,
            "voice": str(self.cfg.get("chatterbox.voice", "adam")),
            "exaggeration": round(0.25 + energy, 2),
            "cfg_weight": float(self.cfg.get("chatterbox.cfgWeight", 0.5)),
            "temperature": float(self.cfg.get("chatterbox.temperature", 0.6)),
        }
        return self._post_speech(url, payload,
                                 float(self.cfg.get("chatterbox.timeoutSec", 60)), "mp3")

    def _post_speech(self, url: str, payload: dict, timeout: float, fmt: str) -> Path | None:
        try:
            req = urllib.request.Request(
                url.rstrip("/") + "/v1/audio/speech",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            if not data:
                return None
            out = Path(tempfile.gettempdir()) / f"ttsd-{abs(hash(payload['input'])) % 10**8}.{fmt}"
            out.write_bytes(data)
            return out
        except Exception as exc:  # noqa: BLE001 — every engine failure falls through
            log.debug("synth via %s failed: %s", url, exc)
            return None

    def _synth_edge(self, text: str) -> Path | None:
        if not self.cfg.get("edge.enabled", True):
            return None
        voice = str(self.cfg.get("edge.voice", "en-US-AndrewMultilingualNeural"))
        out = Path(tempfile.gettempdir()) / f"ttsd-edge-{abs(hash(text)) % 10**8}.mp3"
        try:
            import asyncio

            import edge_tts

            async def _run() -> None:
                await edge_tts.Communicate(text, voice).save(str(out))

            asyncio.run(_run())
            return out if out.is_file() and out.stat().st_size > 0 else None
        except Exception as exc:  # noqa: BLE001
            log.debug("edge-tts failed: %s", exc)
            return None
