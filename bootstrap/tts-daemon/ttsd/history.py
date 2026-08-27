"""Durable record of what was said, and what was deliberately not said.

Two jobs, and the second is why this is not just a log file:

1. **Forensics.** One row per *decision*, including the rejections, so "why did it say
   that twice" is a query instead of hand-parsing ttsd.log. The in-memory counters on the
   dispatcher (`spoken`, `suppressed`) die with the process; these do not.

2. **Cross-process dedupe.** The daemon serializes speech on one thread, but a detached
   direct worker has no such thread and no knowledge of its siblings. Several hooks can
   describe one user-facing event -- a single Claude AskUserQuestion trips Notification,
   PermissionRequest and PreToolUse -- and each would speak. This table is the only place
   those processes can agree on what has already been said.

**Every public function fails open.** A missing, locked, read-only or corrupt database must
never stop an announcement: `record` returns silently and `recently_spoken` returns None, so
the caller behaves as though there were no history at all. Hearing something twice is a
nuisance; not hearing a permission prompt is a fault. The first failure logs once and then
the module goes quiet, so a broken disk cannot flood the log either.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path

from .config import state_dir

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS utterances (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    source      TEXT    NOT NULL DEFAULT '',
    event       TEXT    NOT NULL DEFAULT '',
    state       TEXT    NOT NULL DEFAULT '',
    priority    INTEGER,
    session_key TEXT    NOT NULL DEFAULT '',
    project     TEXT    NOT NULL DEFAULT '',
    hook_origin TEXT    NOT NULL DEFAULT '',
    decision    TEXT    NOT NULL,
    line        TEXT    NOT NULL DEFAULT '',
    engine      TEXT    NOT NULL DEFAULT '',
    synth_ms    INTEGER,
    play_ms     INTEGER,
    pid         INTEGER,
    daemon      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_utt_session_ts ON utterances(session_key, ts);
CREATE INDEX IF NOT EXISTS ix_utt_ts          ON utterances(ts);
"""

# Decisions worth distinguishing when reading the table back.
SPOKEN = "spoken"
COALESCED = "coalesced"
DEDUPED = "deduped"
DROPPED_STALE = "dropped_stale"
SUPPRESSED_DND = "suppressed_dnd"
MUTED = "muted"
COOLDOWN = "cooldown"

_broken = False  # set after the first failure; keeps a bad disk from flooding the log


def db_path() -> Path:
    return state_dir() / "history.db"


def _connect() -> sqlite3.Connection | None:
    """Open (and migrate) the database, or None if it cannot be used."""
    global _broken
    if _broken:
        return None
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path(), timeout=1.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        # WAL so a reader (a direct worker checking for duplicates) never blocks the
        # daemon's writer, and vice versa.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        return conn
    except (sqlite3.Error, OSError) as exc:
        _broken = True
        log.warning("tts history unavailable, continuing without it: %s", exc)
        return None


def record(decision: str, *, event=None, line: str = "", engine: str = "",
           synth_ms: int | None = None, play_ms: int | None = None,
           daemon: bool = False, hook_origin: str = "") -> None:
    """Append one decision. Never raises."""
    conn = _connect()
    if conn is None:
        return
    try:
        with conn:
            conn.execute(
                "INSERT INTO utterances (ts, source, event, state, priority, session_key,"
                " project, hook_origin, decision, line, engine, synth_ms, play_ms, pid, daemon)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    time.time(),
                    getattr(event, "source", "") or "",
                    getattr(event, "event", "") or "",
                    getattr(event, "state", "") or "",
                    getattr(event, "priority", None),
                    getattr(event, "session_key", "") or "",
                    getattr(event, "project_name", "") or "",
                    hook_origin or getattr(event, "event", "") or "",
                    decision,
                    line,
                    engine,
                    synth_ms,
                    play_ms,
                    os.getpid(),
                    1 if daemon else 0,
                ),
            )
    except (sqlite3.Error, OSError) as exc:
        log.debug("tts history write failed: %s", exc)
    finally:
        _close(conn)


def recently_spoken(session_key: str, priority: int | None, within_sec: float):
    """The most recent `spoken` row for this session at this priority, or None.

    Priority matters: a 'done' announcement should not be suppressed by a question that
    was spoken two seconds earlier. Passing priority=None matches any.
    """
    if not session_key or within_sec <= 0:
        return None
    conn = _connect()
    if conn is None:
        return None
    try:
        cutoff = time.time() - within_sec
        if priority is None:
            sql = ("SELECT * FROM utterances WHERE session_key=? AND decision=? AND ts>=?"
                   " ORDER BY ts DESC LIMIT 1")
            args = (session_key, SPOKEN, cutoff)
        else:
            sql = ("SELECT * FROM utterances WHERE session_key=? AND decision=? AND ts>=?"
                   " AND priority=? ORDER BY ts DESC LIMIT 1")
            args = (session_key, SPOKEN, cutoff, priority)
        return conn.execute(sql, args).fetchone()
    except (sqlite3.Error, OSError) as exc:
        log.debug("tts history read failed: %s", exc)
        return None
    finally:
        _close(conn)


def prune(days: float) -> None:
    """Drop rows older than `days`. Cheap enough to call on the write path."""
    if days <= 0:
        return
    conn = _connect()
    if conn is None:
        return
    try:
        with conn:
            conn.execute("DELETE FROM utterances WHERE ts < ?", (time.time() - days * 86400,))
    except (sqlite3.Error, OSError):
        pass
    finally:
        _close(conn)


def recent(limit: int = 50, since: float | None = None) -> list[dict]:
    conn = _connect()
    if conn is None:
        return []
    try:
        limit = max(1, min(int(limit), 1000))
        if since is None:
            rows = conn.execute("SELECT * FROM utterances ORDER BY ts DESC LIMIT ?",
                                (limit,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM utterances WHERE ts>=? ORDER BY ts DESC LIMIT ?",
                                (float(since), limit)).fetchall()
        return [dict(r) for r in rows]
    except (sqlite3.Error, OSError):
        return []
    finally:
        _close(conn)


def duplicates(within_sec: float = 8.0, since: float | None = None) -> list[dict]:
    """Sessions that produced more than one `spoken` row inside `within_sec`.

    This is the report that answers the original complaint. Self-join rather than a window
    function so it works on the SQLite that ships with any Python we might be frozen
    against, and DISTINCT because the join yields one row per *pair* -- three
    utterances inside the window make three pairs, which would read as three
    extras instead of two.
    """
    conn = _connect()
    if conn is None:
        return []
    try:
        cutoff = float(since) if since is not None else time.time() - 86400
        rows = conn.execute(
            "SELECT a.session_key, a.priority, COUNT(DISTINCT b.id) AS extra,"
            "       MIN(b.ts - a.ts) AS closest_sec,"
            "       a.line AS first_line, MAX(b.line) AS later_line"
            "  FROM utterances a JOIN utterances b"
            "    ON b.session_key = a.session_key AND b.id <> a.id"
            "   AND b.ts > a.ts AND b.ts - a.ts <= ?"
            " WHERE a.decision = ? AND b.decision = ? AND a.ts >= ?"
            " GROUP BY a.session_key, a.priority"
            " ORDER BY extra DESC, closest_sec ASC LIMIT 100",
            (float(within_sec), SPOKEN, SPOKEN, cutoff),
        ).fetchall()
        return [dict(r) for r in rows]
    except (sqlite3.Error, OSError):
        return []
    finally:
        _close(conn)


def summary(within_sec: float = 86400.0, dupe_window: float = 8.0) -> dict:
    """Counts for `tstack doctor` / `history --check`. Empty-but-valid on any failure.

    `daemon_silent_for` is the age of the last utterance the *daemon* spoke, which is the
    number that matters: while it is dead every hook takes the direct path and still exits
    0, so a 15-hour degradation looks exactly like a quiet afternoon.
    """
    out = {"spoken": 0, "deduped": 0, "dupes": 0, "daemon_silent_for": None}
    conn = _connect()
    if conn is None:
        return out
    try:
        cutoff = time.time() - within_sec
        for row in conn.execute(
                "SELECT decision, COUNT(*) AS n FROM utterances WHERE ts >= ?"
                " GROUP BY decision", (cutoff,)):
            if row["decision"] == SPOKEN:
                out["spoken"] = row["n"]
            elif row["decision"] == DEDUPED:
                out["deduped"] = row["n"]
        last = conn.execute(
            "SELECT ts FROM utterances WHERE decision = ? AND daemon = 1"
            " ORDER BY ts DESC LIMIT 1", (SPOKEN,)).fetchone()
        if last is not None:
            out["daemon_silent_for"] = max(0.0, time.time() - last["ts"])
    except (sqlite3.Error, OSError) as exc:
        log.debug("tts history summary failed: %s", exc)
        return out
    finally:
        _close(conn)
    out["dupes"] = len(duplicates(within_sec=dupe_window, since=time.time() - within_sec))
    return out


def _close(conn: sqlite3.Connection) -> None:
    try:
        conn.close()
    except sqlite3.Error:
        pass
