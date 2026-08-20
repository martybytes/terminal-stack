"""Music duck / pause engine.

One dedicated thread owns all Core Audio (pycaw) and media-session (winrt)
work; other threads talk to it through a command queue. pycaw/comtypes are
imported inside the thread so COM is initialized on the thread that uses it.

Crash safety: pre-duck volumes are written to duck-snapshot.json BEFORE the
first volume change; a stale snapshot found at startup is restored (matched
by exe name if the PID is gone) and deleted. Windows persists per-app mixer
volume forever, so this file is the difference between "music dips" and
"music is stuck at 30% until the user finds the mixer".
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

_RAMP_STEPS = 5
_RAMP_DOWN_SEC = 0.10
_RAMP_UP_SEC = 0.30
_NEWCOMER_POLL_SEC = 0.5


class AudioController(threading.Thread):
    """Public API (thread-safe): hold(duration_hint), release(), force_restore()."""

    def __init__(self, cfg, snapshot_path: Path, playback=None) -> None:
        super().__init__(name="ttsd-audio", daemon=True)
        self.cfg = cfg
        self.snapshot_path = snapshot_path
        self.playback = playback  # exposes current_pid to exempt from ducking
        self._commands: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        # state owned by the audio thread:
        self._active_mode: str | None = None  # "duck" | "pause" while engaged
        self._hold_count = 0
        self._engaged_at = 0.0
        self._released_at = 0.0
        self._ducked: dict[int, tuple[str, float]] = {}  # pid → (exe, orig_volume)
        self._paused_aumids: list[str] = []
        self.state = "idle"  # for /healthz

    # ── public (any thread) ───────────────────────────────────────────────

    def hold(self, duration_hint: float | None) -> None:
        self._commands.put(("hold", duration_hint))

    def release(self) -> None:
        self._commands.put(("release", None))

    def force_restore(self) -> None:
        self._commands.put(("force", None))

    def stop(self) -> None:
        self._stop.set()
        self._commands.put(("force", None))

    # ── thread body ───────────────────────────────────────────────────────

    def run(self) -> None:
        self._restore_stale_snapshot()
        while not self._stop.is_set():
            try:
                cmd, arg = self._commands.get(timeout=0.25)
            except queue.Empty:
                cmd, arg = None, None
            try:
                if cmd == "hold":
                    self._hold_count += 1
                    if self._active_mode is None:
                        self._engage(arg)
                elif cmd == "release":
                    self._hold_count = max(0, self._hold_count - 1)
                    if self._hold_count == 0:
                        self._released_at = time.monotonic()
                elif cmd == "force":
                    self._hold_count = 0
                    self._disengage()
                self._tick()
            except Exception as exc:  # noqa: BLE001 — audio failures never kill the thread
                log.exception("audio controller error: %s", exc)
                try:
                    self._disengage()
                except Exception:  # noqa: BLE001
                    pass
        self._disengage()

    def _tick(self) -> None:
        if self._active_mode is None:
            return
        now = time.monotonic()
        max_duck = float(self.cfg.get("music.maxDuckSec", 15))
        if now - self._engaged_at > max_duck:
            log.warning("audio watchdog: engaged > %.0fs, force restoring", max_duck)
            self._hold_count = 0
            self._disengage()
            return
        idle_restore = float(self.cfg.get("daemon.idleRestoreSec", 0.7))
        if self._hold_count == 0 and now - self._released_at >= idle_restore:
            self._disengage()
            return
        if self._active_mode == "duck":
            self._duck_newcomers()

    # ── engage / disengage ────────────────────────────────────────────────

    def _resolve_mode(self, duration_hint: float | None) -> str | None:
        mode = str(self.cfg.get("music.mode", "duck"))
        if mode == "off":
            return None
        if mode == "smart":
            threshold = float(self.cfg.get("music.smartThresholdSec", 5))
            if duration_hint is not None and duration_hint >= threshold:
                return "pause"
            return "duck"
        return mode if mode in ("duck", "pause") else "duck"

    def _engage(self, duration_hint: float | None) -> None:
        mode = self._resolve_mode(duration_hint)
        if mode is None:
            return
        self._engaged_at = time.monotonic()
        if mode == "duck":
            self._duck_engage()
        else:
            self._pause_engage()
        self._active_mode = mode
        self.state = mode

    def _disengage(self) -> None:
        if self._active_mode == "duck":
            self._duck_restore()
        elif self._active_mode == "pause":
            self._pause_resume()
        self._active_mode = None
        self.state = "idle"

    # ── ducking (pycaw) ───────────────────────────────────────────────────

    def _target_sessions(self):
        try:
            from pycaw.pycaw import AudioUtilities  # deferred: COM on this thread
        except Exception as exc:  # noqa: BLE001
            log.warning("pycaw unavailable, ducking disabled: %s", exc)
            return []
        apps = self.cfg.get("music.apps", "all")
        wanted = None
        if isinstance(apps, list):
            wanted = {str(a).lower() for a in apps}
        own_pids = {0, os.getpid()}
        if self.playback and self.playback.current_pid:
            own_pids.add(self.playback.current_pid)
        out = []
        try:
            for session in AudioUtilities.GetAllSessions():
                proc = session.Process
                if proc is None or session.SimpleAudioVolume is None:
                    continue
                if proc.pid in own_pids:
                    continue
                exe = (proc.name() or "").lower()
                if not exe or exe in ("ffplay.exe",):
                    continue
                if wanted is not None and exe not in wanted:
                    continue
                out.append((proc.pid, exe, session.SimpleAudioVolume))
        except Exception as exc:  # noqa: BLE001
            log.warning("audio session enumeration failed: %s", exc)
        return out

    def _duck_factor(self) -> float:
        try:
            pct = float(self.cfg.get("music.duckPercent", 30))
        except (TypeError, ValueError):
            pct = 30
        return min(1.0, max(0.0, pct / 100.0))

    def _duck_engage(self) -> None:
        factor = self._duck_factor()
        targets = []
        for pid, exe, vol in self._target_sessions():
            try:
                orig = float(vol.GetMasterVolume())
            except Exception:  # noqa: BLE001
                continue
            if orig < 0.02:  # already effectively silent — nothing to duck or restore
                continue
            targets.append((pid, exe, vol, orig))
        if not targets:
            return
        self._ducked = {pid: (exe, orig) for pid, exe, _, orig in targets}
        self._write_snapshot()  # BEFORE any change
        for step in range(1, _RAMP_STEPS + 1):
            frac = step / _RAMP_STEPS
            for _, _, vol, orig in targets:
                try:
                    vol.SetMasterVolume(orig + (orig * factor - orig) * frac, None)
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(_RAMP_DOWN_SEC / _RAMP_STEPS)
        log.info("ducked %d session(s) to %d%%", len(targets), int(factor * 100))

    def _duck_newcomers(self) -> None:
        """Catch sessions that appeared mid-duck (Spotify/Chrome children)."""
        if not self._ducked:
            return
        if getattr(self, "_last_newcomer_scan", 0.0) + _NEWCOMER_POLL_SEC > time.monotonic():
            return
        self._last_newcomer_scan = time.monotonic()
        factor = self._duck_factor()
        known_exes = {exe for exe, _ in self._ducked.values()}
        for pid, exe, vol in self._target_sessions():
            if pid in self._ducked or exe not in known_exes:
                continue
            try:
                orig = float(vol.GetMasterVolume())
                if orig > 0.02:
                    self._ducked[pid] = (exe, orig)
                    self._write_snapshot()
                    vol.SetMasterVolume(orig * factor, None)
            except Exception:  # noqa: BLE001
                pass

    def _duck_restore(self) -> None:
        if not self._ducked:
            return
        sessions = {pid: vol for pid, _, vol in self._target_sessions()}
        for step in range(1, _RAMP_STEPS + 1):
            frac = step / _RAMP_STEPS
            for pid, (_, orig) in self._ducked.items():
                vol = sessions.get(pid)
                if vol is None:
                    continue
                try:
                    factor = self._duck_factor()
                    vol.SetMasterVolume(orig * factor + (orig - orig * factor) * frac, None)
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(_RAMP_UP_SEC / _RAMP_STEPS)
        log.info("restored %d session(s)", len(self._ducked))
        self._ducked = {}
        self._delete_snapshot()

    # ── snapshot file ─────────────────────────────────────────────────────

    def _write_snapshot(self) -> None:
        try:
            rows = [{"pid": pid, "exe": exe, "volume": orig}
                    for pid, (exe, orig) in self._ducked.items()]
            self.snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            self.snapshot_path.write_text(json.dumps(rows), encoding="utf-8")
        except OSError as exc:
            log.warning("snapshot write failed: %s", exc)

    def _delete_snapshot(self) -> None:
        try:
            self.snapshot_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _restore_stale_snapshot(self) -> None:
        if not self.snapshot_path.is_file():
            return
        try:
            rows = json.loads(self.snapshot_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._delete_snapshot()
            return
        log.warning("stale duck snapshot found (%d entries) — restoring", len(rows))
        by_pid = {row.get("pid"): row for row in rows if isinstance(row, dict)}
        by_exe: dict[str, float] = {}
        for row in rows:
            if isinstance(row, dict) and row.get("exe"):
                by_exe[str(row["exe"]).lower()] = float(row.get("volume", 1.0))
        for pid, exe, vol in self._target_sessions():
            row = by_pid.get(pid)
            target = float(row["volume"]) if row else by_exe.get(exe)
            if target is None:
                continue
            try:
                if float(vol.GetMasterVolume()) < target:
                    vol.SetMasterVolume(target, None)
            except Exception:  # noqa: BLE001
                pass
        self._delete_snapshot()

    # ── pause / resume (winrt GSMTC) ──────────────────────────────────────

    def _pause_engage(self) -> None:
        self._paused_aumids = self._gsmtc("pause") or []
        if self._paused_aumids:
            log.info("paused: %s", ", ".join(self._paused_aumids))

    def _pause_resume(self) -> None:
        if self._paused_aumids:
            self._gsmtc("resume", self._paused_aumids)
            log.info("resumed: %s", ", ".join(self._paused_aumids))
        self._paused_aumids = []

    @staticmethod
    def _gsmtc(action: str, aumids: list[str] | None = None) -> list[str] | None:
        """Pause exactly the Playing sessions / resume exactly those AUMIDs."""
        try:
            import asyncio

            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as Manager,
                GlobalSystemMediaTransportControlsSessionPlaybackStatus as Status,
            )

            async def _run() -> list[str]:
                mgr = await Manager.request_async()
                touched: list[str] = []
                for sess in mgr.get_sessions():
                    aumid = sess.source_app_user_model_id or ""
                    info = sess.get_playback_info()
                    if action == "pause":
                        if info and info.playback_status == Status.PLAYING:
                            if await sess.try_pause_async():
                                touched.append(aumid)
                    elif aumids and aumid in aumids:
                        await sess.try_play_async()
                        touched.append(aumid)
                return touched

            return asyncio.run(asyncio.wait_for(_run(), timeout=4))
        except Exception as exc:  # noqa: BLE001
            log.warning("media-session %s failed: %s", action, exc)
            return None


def restore_volumes_oneshot(snapshot_path: Path) -> int:
    """`python -m ttsd --restore-volumes` / ts-doctor --repair entry point."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ctl = AudioController(cfg=_NullCfg(), snapshot_path=snapshot_path)
    ctl._restore_stale_snapshot()
    return 0


class _NullCfg:
    def get(self, dotted: str, default=None):
        return default
