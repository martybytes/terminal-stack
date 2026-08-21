"""Machine-global play lock for the direct fallback path.

The daemon serializes speech by having exactly one dispatcher thread — `pipeline.py` says
as much, and that thread is why the original machine-global lock was removed. But when the
daemon is unreachable, `submit_hook` spawns a *detached process per hook*, and those have no
thread and no knowledge of each other. Three hooks firing for one event means three
processes calling `Playback.play` at the same moment: overlapping voices. That is what this
restores, for that path only.

Two details are load-bearing:

- **The mutex is an atomic exclusive create**, not a read-then-write check. Two workers a
  millisecond apart would both pass an "is it locked?" read, which is precisely the race
  being closed.
- **It never drops audio.** A waiter polls for the holder to finish and then speaks anyway
  once `wait_sec` is up. A lock that silences an announcement would be worse than the
  overlap it prevents; this only orders them. Dropping genuinely duplicated announcements is
  `history.recently_spoken`'s job, not this file's.

A holder that dies mid-play leaves the file behind, so a lock older than `stale_sec` is
reclaimed rather than trusted forever.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from pathlib import Path

from .config import state_dir

log = logging.getLogger(__name__)


def lock_path() -> Path:
    return state_dir() / "speak.lock"


def _try_create(path: Path) -> int | None:
    """Atomically create the lock file. Returns a fd, or None if someone else holds it."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return None
    except OSError as exc:
        # Unwritable state dir and the like: report as "not held" so the caller proceeds.
        log.debug("speak lock unavailable, proceeding unserialized: %s", exc)
        raise
    try:
        os.write(fd, f"{os.getpid()} {time.time():.3f}\n".encode())
    except OSError:
        pass
    return fd


def _age(path: Path) -> float:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except OSError:
        return 0.0


@contextlib.contextmanager
def hold(wait_sec: float = 30.0, stale_sec: float = 90.0):
    """Hold the play lock for the duration of the block.

    Yields True when the lock was actually acquired and False when it was not (waited too
    long, or the lock could not be used at all). Either way the block runs — the caller must
    still speak.
    """
    path = lock_path()
    fd: int | None = None
    deadline = time.time() + max(0.0, wait_sec)
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = _try_create(path)
            except OSError:
                fd = None
                break  # cannot lock here at all; proceed unserialized
            if fd is not None:
                break
            if _age(path) > stale_sec:
                # The holder died mid-utterance. Reclaim rather than wait forever.
                log.warning("reclaiming stale speak lock (%.0fs old)", _age(path))
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass
                continue
            if time.time() >= deadline:
                log.info("speak lock busy for %.0fs; speaking anyway", wait_sec)
                break
            time.sleep(0.1)
    except OSError as exc:
        log.debug("speak lock setup failed, proceeding: %s", exc)

    try:
        yield fd is not None
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
