"""Table-driven scheduler tests with a fake clock — no threads, no COM."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ttsd.events import Event
from ttsd.scheduler import Scheduler, SchedulerConfig


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, sec: float) -> None:
        self.now += sec


def make(state="waiting", key="claude:s1", project="alpha", source="claude",
         event="") -> Event:
    return Event(source=source, event=event or state, state=state,
                 session_key=key, project_name=project)


def make_sched(**kw):
    clock = FakeClock()
    cfg = SchedulerConfig(**kw)
    return Scheduler(cfg, clock=clock), clock


def drain(sched, clock, horizon=30.0, step=0.1):
    batches = []
    end = clock.now + horizon
    while clock.now < end:
        batch = sched.collect_due()
        if batch:
            batches.append(batch)
        clock.advance(step)
    return batches


def test_single_done_speaks_after_window():
    sched, clock = make_sched()
    sched.submit(make())
    assert sched.collect_due() == []  # opens the window
    clock.advance(1.9)
    batch = sched.collect_due()
    assert [e.session_key for e in batch] == ["claude:s1"]


def test_three_dones_coalesce():
    sched, clock = make_sched()
    sched.submit(make(key="claude:a", project="alpha"))
    clock.advance(0.3)
    sched.submit(make(key="claude:b", project="beta"))
    clock.advance(0.3)
    sched.submit(make(key="claude:c", project="gamma"))
    batches = drain(sched, clock, horizon=6.0)
    assert len(batches) == 1
    assert {e.project_name for e in batches[0]} == {"alpha", "beta", "gamma"}


def test_interactive_bypasses_window():
    sched, clock = make_sched()
    sched.submit(make(key="claude:a"))
    sched.collect_due()  # window opens
    sched.submit(make(state="question", key="claude:q"))
    batch = sched.collect_due()
    assert [e.state for e in batch] == ["question"]


def test_slot_dedupe_newer_wins():
    sched, clock = make_sched()
    first = make()
    second = make()
    second.text = "newer"
    sched.submit(first)
    sched.submit(second)
    clock.advance(2.0)
    batch = sched.collect_due()
    assert len(batch) == 1 and batch[0].text == "newer"


def test_barge_in_cancels_done():
    sched, clock = make_sched()
    sched.submit(make())
    sched.submit(make(event="prompt_submit", state=""))
    clock.advance(5.0)
    assert sched.collect_due() == []
    assert sched.pending_count() == 0


def test_cursor_hold_and_cooldown():
    sched, clock = make_sched()
    sched.submit(make(key="cursor:c1", source="cursor"))
    clock.advance(1.0)
    assert sched.collect_due() == []  # still held
    batches = drain(sched, clock, horizon=8.0)
    assert len(batches) == 1
    # Immediately after speaking, another cursor stop is inside the cooldown.
    sched.submit(make(key="cursor:c1", source="cursor"))
    assert drain(sched, clock, horizon=8.0) == []
    # After the cooldown it speaks again.
    clock.advance(20.0)
    sched.submit(make(key="cursor:c1", source="cursor"))
    assert len(drain(sched, clock, horizon=8.0)) == 1


def test_stale_done_dropped():
    sched, clock = make_sched()
    sched.submit(make())
    clock.advance(25.0)  # past done_max_age_sec
    assert sched.collect_due() == []
    assert sched.pending_count() == 0


def test_error_outranks_done():
    sched, clock = make_sched()
    sched.submit(make(key="claude:a"))
    sched.submit(make(state="error", key="claude:b"))
    batch = sched.collect_due()
    assert batch[0].state == "error"


def test_overflow_evicts_oldest_done():
    sched, clock = make_sched(max_queue=3)
    for i in range(5):
        sched.submit(make(key=f"claude:s{i}", project=f"p{i}"))
        clock.advance(0.01)
    assert sched.pending_count() == 3
