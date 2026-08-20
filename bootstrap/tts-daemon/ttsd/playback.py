"""Media playback via ffplay (the stack's existing player) + duration probe.

The live ffplay PID is exposed so the ducking engine can exempt it from
per-app volume changes.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

_WINGET_HINTS = (
    r"%LOCALAPPDATA%\Microsoft\WinGet\Links\ffplay.exe",
)


def _find(tool: str) -> str | None:
    found = shutil.which(tool)
    if found:
        return found
    for hint in _WINGET_HINTS:
        path = os.path.expandvars(hint.replace("ffplay", tool))
        if os.path.isfile(path):
            return path
    return None


class Playback:
    def __init__(self) -> None:
        self.ffplay = _find("ffplay")
        self.ffprobe = _find("ffprobe")
        self.current_pid: int | None = None

    def probe_duration(self, media: Path) -> float | None:
        if not self.ffprobe:
            return None
        try:
            out = subprocess.run(
                [self.ffprobe, "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(media)],
                capture_output=True, text=True, timeout=5, check=True,
            ).stdout.strip()
            return float(out)
        except (subprocess.SubprocessError, ValueError, OSError):
            return None

    def play(self, media: Path, timeout: float = 60) -> bool:
        """Blocking play; returns True on success."""
        if self.ffplay:
            try:
                proc = subprocess.Popen(
                    [self.ffplay, "-nodisp", "-autoexit", "-hide_banner",
                     "-loglevel", "quiet", str(media)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                self.current_pid = proc.pid
                try:
                    proc.wait(timeout=timeout)
                finally:
                    self.current_pid = None
                return proc.returncode == 0
            except OSError as exc:
                log.warning("ffplay failed: %s", exc)
        return self._play_mediaplayer(media, timeout)

    @staticmethod
    def _play_mediaplayer(media: Path, timeout: float) -> bool:
        """Fallback mirroring cc-tts-play.ps1's MediaPlayer path."""
        script = (
            "Add-Type -AssemblyName PresentationCore;"
            "$p = New-Object System.Windows.Media.MediaPlayer;"
            f"$p.Open([Uri]::new('{media.as_uri()}'));"
            "$p.Play();"
            "while (-not $p.NaturalDuration.HasTimeSpan) { Start-Sleep -Milliseconds 50 };"
            "Start-Sleep -Seconds $p.NaturalDuration.TimeSpan.TotalSeconds;"
            "$p.Close()"
        )
        for shell in ("pwsh", "powershell"):
            exe = shutil.which(shell)
            if not exe:
                continue
            try:
                subprocess.run(
                    [exe, "-NoLogo", "-NonInteractive", "-Command", script],
                    timeout=timeout, check=True,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return True
            except subprocess.SubprocessError:
                continue
        return False

    @staticmethod
    def speak_sapi(text: str) -> bool:
        """Last-resort local voice — no media file, no engines, no network."""
        script = (
            "Add-Type -AssemblyName System.Speech;"
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
            "$s.Speak($env:TTSD_SAPI_TEXT)"
        )
        for shell in ("pwsh", "powershell"):
            exe = shutil.which(shell)
            if not exe:
                continue
            try:
                subprocess.run(
                    [exe, "-NoLogo", "-NonInteractive", "-Command", script],
                    timeout=30, check=True,
                    env={**os.environ, "TTSD_SAPI_TEXT": text},
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return True
            except subprocess.SubprocessError:
                continue
        return False
