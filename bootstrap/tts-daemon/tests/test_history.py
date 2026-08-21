"""History store and play lock — the two things that stop duplicate/overlapping speech.

No audio, no COM, no daemon. Every test redirects LOCALAPPDATA so the real state directory
is never touched, and reloads the modules' cached "broken" flag between cases.
"""

import importlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ttsd import history, speaklock
from ttsd.events import Event


def _isolate(tmp_path, monkeypatch):
    """Point the state dir at a temp path and reset the fail-open latch."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    importlib.reload(history)
    importlib.reload(speaklock)
    return tmp_path


def ev(key="claude:s1", state="question", source="claude", project="alpha"):
    return Event(source=source, event=state, state=state,
                 session_key=key, project_name=project)


# ── history ───────────────────────────────────────────────────────────────────

def test_records_and_reads_back(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    history.record(history.SPOKEN, event=ev(), line="Claude. alpha has a question.",
                   engine="kokoro", synth_ms=120, play_ms=1400)
    rows = history.recent(10)
    assert len(rows) == 1
    assert rows[0]["decision"] == history.SPOKEN
    assert rows[0]["engine"] == "kokoro"
    assert rows[0]["session_key"] == "claude:s1"
    assert rows[0]["pid"] == os.getpid()


def test_recently_spoken_is_scoped_by_session_and_priority(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    question = ev(state="question")          # P0
    done = ev(state="waiting")               # P2
    history.record(history.SPOKEN, event=question, line="q")

    assert history.recently_spoken("claude:s1", question.priority, 30) is not None
    # A finished announcement must not be silenced by a question spoken a moment ago.
    assert history.recently_spoken("claude:s1", done.priority, 30) is None
    # Nor may one session mute another.
    assert history.recently_spoken("claude:s2", question.priority, 30) is None


def test_recently_spoken_expires_and_ignores_non_spoken(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    e = ev()
    history.record(history.SPOKEN, event=e, line="q")
    time.sleep(0.05)  # the row is microseconds old; get clear of the window under test
    assert history.recently_spoken("claude:s1", e.priority, 0.01) is None, "window elapsed"

    _isolate(tmp_path / "b", monkeypatch)
    history.record(history.DEDUPED, event=e, line="q")
    assert history.recently_spoken("claude:s1", e.priority, 30) is None, \
        "a suppressed row must not itself suppress the next one"


def test_prune_drops_old_rows_only(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    history.record(history.SPOKEN, event=ev(), line="new")
    conn = history._connect()
    with conn:
        conn.execute("UPDATE utterances SET ts = ?", (time.time() - 40 * 86400,))
        conn.execute("INSERT INTO utterances (ts, decision) VALUES (?, ?)",
                     (time.time(), history.SPOKEN))
    conn.close()
    history.prune(14)
    assert len(history.recent(10)) == 1


def test_duplicates_report_finds_the_three_hook_case(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    # The observed shape: one AskUserQuestion announced three times, ~2.5s apart.
    conn = history._connect()
    base = time.time()
    with conn:
        for offset, line in ((0.0, "has a question"), (2.5, "wants to run"), (4.9, "needs permission")):
            conn.execute(
                "INSERT INTO utterances (ts, decision, session_key, priority, line)"
                " VALUES (?,?,?,?,?)", (base + offset, history.SPOKEN, "claude:s1", 0, line))
    conn.close()
    report = history.duplicates(within_sec=8)
    assert report and report[0]["session_key"] == "claude:s1"
    assert report[0]["extra"] >= 2


def test_fails_open_when_the_database_cannot_be_used(tmp_path, monkeypatch):
    """A broken store must never block speech: writes no-op, reads say 'nothing known'."""
    _isolate(tmp_path, monkeypatch)
    # A file where the state directory should be makes mkdir/connect impossible.
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(blocker))
    importlib.reload(history)

    history.record(history.SPOKEN, event=ev(), line="must not raise")
    assert history.recently_spoken("claude:s1", 0, 30) is None
    assert history.recent(5) == []
    assert history.duplicates() == []
    history.prune(14)


def test_summary_reports_downtime_and_duplicates(tmp_path, monkeypatch):
    """What ts-doctor reads: a dead daemon's age, and whether anything spoke twice."""
    _isolate(tmp_path, monkeypatch)
    conn = history._connect()
    base = time.time()
    with conn:
        # Two utterances 2.5s apart in one session: the shape of the original complaint.
        for off in (0.0, 2.5):
            conn.execute(
                "INSERT INTO utterances (ts, decision, session_key, priority, daemon)"
                " VALUES (?,?,?,?,1)", (base - 3600 + off, history.SPOKEN, "claude:s1", 0))
        conn.execute("INSERT INTO utterances (ts, decision, session_key, priority, daemon)"
                     " VALUES (?,?,?,?,0)", (base, history.DEDUPED, "claude:s1", 0))
    conn.close()

    s = history.summary()
    assert s["spoken"] == 2 and s["deduped"] == 1
    assert s["dupes"] == 1, "one session spoke twice inside the window"
    assert 3500 < s["daemon_silent_for"] < 3700, "roughly an hour since the daemon spoke"


def test_summary_is_empty_but_valid_when_the_store_is_broken(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(blocker))
    importlib.reload(history)
    assert history.summary() == {"spoken": 0, "deduped": 0, "dupes": 0,
                                "daemon_silent_for": None}


# ── play lock ─────────────────────────────────────────────────────────────────

def test_lock_is_exclusive_then_released(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with speaklock.hold(wait_sec=0.2) as first:
        assert first is True
        with speaklock.hold(wait_sec=0.2) as second:
            assert second is False, "a second holder must not get the lock"
    # Released on exit, so the next caller gets it.
    with speaklock.hold(wait_sec=0.2) as third:
        assert third is True


def test_lock_speaks_anyway_when_the_holder_will_not_yield(tmp_path, monkeypatch):
    """Never drop audio: a waiter proceeds rather than staying silent."""
    _isolate(tmp_path, monkeypatch)
    with speaklock.hold(wait_sec=5):
        entered = False
        with speaklock.hold(wait_sec=0.2) as got:
            entered = True
            assert got is False
        assert entered, "the block must run even without the lock"


def test_stale_lock_is_reclaimed(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    path = speaklock.lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("99999 0", encoding="utf-8")
    old = time.time() - 600
    os.utime(path, (old, old))
    with speaklock.hold(wait_sec=0.5, stale_sec=90) as got:
        assert got is True, "a lock left behind by a dead holder must be reclaimed"


def test_lock_proceeds_when_it_cannot_be_created(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(blocker))
    importlib.reload(speaklock)
    with speaklock.hold(wait_sec=0.2) as got:
        assert got is False  # unusable, but the block still runs


# ── the dispatcher filter (cause A, end to end through _suppress) ─────────────

class _Cfg:
    """Minimal config: only the keys _suppress reads."""

    def __init__(self, **over):
        self.values = {"events": ["waiting", "error", "question", "permission"],
                       "debounceSec": 5}
        self.values.update(over)

    def get(self, dotted, default=None):
        return self.values.get(dotted, default)


def _dispatcher(cfg):
    from ttsd.pipeline import Dispatcher
    return Dispatcher(cfg, scheduler=None, registry=None, summarizer=None,
                      synth=None, playback=None, audio=None, wez=None)


def test_three_hooks_for_one_question_speak_once(tmp_path, monkeypatch):
    """Notification, PermissionRequest and PreToolUse all describe one AskUserQuestion.

    They are all P0 and P0 is drained immediately, so the scheduler's (session, class) slot
    never holds two at once. The history check is what collapses them.
    """
    _isolate(tmp_path, monkeypatch)
    import ttsd.pipeline as pipeline
    importlib.reload(pipeline)

    disp = _dispatcher(_Cfg())
    notification = ev(state="question")
    permission = ev(state="permission")

    # First hook: nothing spoken yet, so it passes the filter and is recorded as spoken.
    assert disp._suppress(notification) is False
    history.record(history.SPOKEN, event=notification, line="alpha has a question", daemon=True)

    # Second hook, same session, same priority class, moments later: suppressed.
    assert disp._suppress(ev(state="question")) is True
    # permission shares P0 with question, so the generic follow-up is suppressed too.
    assert permission.priority == notification.priority
    assert disp._suppress(permission) is True

    rows = [r["decision"] for r in history.recent(10)]
    assert rows.count(history.DEDUPED) == 2 and rows.count(history.SPOKEN) == 1


def test_a_genuinely_new_question_still_speaks(tmp_path, monkeypatch):
    """The suppression window must not swallow a real second question."""
    _isolate(tmp_path, monkeypatch)
    import ttsd.pipeline as pipeline
    importlib.reload(pipeline)

    disp = _dispatcher(_Cfg(debounceSec=0.05))
    history.record(history.SPOKEN, event=ev(state="question"), line="first", daemon=True)
    time.sleep(0.1)
    assert disp._suppress(ev(state="question")) is False


def test_a_different_session_is_never_muted(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    import ttsd.pipeline as pipeline
    importlib.reload(pipeline)

    disp = _dispatcher(_Cfg())
    history.record(history.SPOKEN, event=ev(key="claude:s1"), line="one", daemon=True)
    assert disp._suppress(ev(key="codex:s9")) is False
