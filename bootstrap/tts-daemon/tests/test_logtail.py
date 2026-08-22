"""Following ttsd.log: rotation, partial lines, continuations, and a missing file."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ttsd.logtail import LogTail, parse_line

LINE_A = "2026-08-21 18:09:03,764 I ttsd.pipeline: spoke [kokoro]: Claude. alpha finished."
LINE_B = "2026-08-21 18:09:04,916 W ttsd.audio_duck: restored 4 session(s)"


def write(path: Path, *lines: str, mode: str = "a") -> None:
    with open(path, mode, encoding="utf-8", newline="") as handle:
        for line in lines:
            handle.write(line + "\n")


# ── parsing ──────────────────────────────────────────────────────────────────

def test_parse_line_fields_and_level_names():
    parsed = parse_line(LINE_A)
    assert parsed["ts"] == "2026-08-21 18:09:03,764"
    assert parsed["level"] == "info"
    assert parsed["logger"] == "ttsd.pipeline"
    assert parsed["message"].startswith("spoke [kokoro]")
    assert parse_line(LINE_B)["level"] == "warning"


def test_a_continuation_line_is_reported_as_such_not_dropped():
    """A future log.exception would emit these; the UI attaches them to the record above."""
    assert parse_line('  File "ttsd/pipeline.py", line 120, in _speak_batch') is None
    assert parse_line("Traceback (most recent call last):") is None


# ── following ────────────────────────────────────────────────────────────────

def test_reads_only_what_is_new(tmp_path):
    path = tmp_path / "ttsd.log"
    write(path, LINE_A, mode="w")
    tail = LogTail(path)

    assert tail.snapshot() == [LINE_A]
    assert tail.read_new() == [], "nothing new yet"

    write(path, LINE_B)
    assert tail.read_new() == [LINE_B]
    assert tail.read_new() == []


def test_a_line_still_being_written_is_held_back(tmp_path):
    path = tmp_path / "ttsd.log"
    write(path, LINE_A, mode="w")
    tail = LogTail(path)
    tail.snapshot()

    with open(path, "a", encoding="utf-8", newline="") as handle:
        handle.write("2026-08-21 18:10:00,000 I ttsd.synth: half a li")
    assert tail.read_new() == [], "no half records may reach the UI"

    with open(path, "a", encoding="utf-8", newline="") as handle:
        handle.write("ne now complete\n")
    assert tail.read_new() == [
        "2026-08-21 18:10:00,000 I ttsd.synth: half a line now complete"]


def test_rotation_is_detected_by_the_file_shrinking(tmp_path):
    path = tmp_path / "ttsd.log"
    write(path, LINE_A, LINE_B, mode="w")
    tail = LogTail(path)
    tail.snapshot()

    # What RotatingFileHandler does: rename away, start a fresh file at zero bytes.
    path.replace(tmp_path / "ttsd.log.1")
    write(path, "2026-08-21 18:11:00,000 I ttsd: after rotation", mode="w")

    assert tail.read_new() == ["2026-08-21 18:11:00,000 I ttsd: after rotation"]
    assert tail.rotations == 1


def test_a_missing_file_is_a_steady_state(tmp_path):
    """The NullHandler fallback writes nothing; that is not the same as an error."""
    path = tmp_path / "ttsd.log"
    tail = LogTail(path)

    assert tail.exists() is False
    assert tail.snapshot() == []
    assert tail.read_new() == []

    write(path, LINE_A, mode="w")
    assert tail.exists() is True
    assert tail.read_new() == [LINE_A], "and it is picked up once it appears"


def test_undecodable_bytes_do_not_raise(tmp_path):
    """Spoken lines carry smart quotes, so a byte offset can land mid-codepoint."""
    path = tmp_path / "ttsd.log"
    path.write_bytes(b"2026-08-21 18:09:03,764 I ttsd: caf\xc3\xa9 \xff\xfe broken\n")
    tail = LogTail(path)
    lines = tail.snapshot()
    assert len(lines) == 1
    assert "café" in lines[0]
    assert "�" in lines[0], "the bad bytes are replaced, not fatal"


def test_snapshot_drops_a_partial_first_line_when_seeking(tmp_path, monkeypatch):
    import ttsd.logtail as mod

    monkeypatch.setattr(mod, "_SNAPSHOT_BYTES", 80)
    path = tmp_path / "ttsd.log"
    write(path, LINE_A, LINE_B, mode="w")

    lines = mod.LogTail(path).snapshot()
    # The seek lands inside LINE_A, so that truncated record is discarded rather than
    # rendered as a mangled line.
    assert LINE_A not in lines
    assert lines[-1] == LINE_B


def test_snapshot_respects_max_lines(tmp_path):
    path = tmp_path / "ttsd.log"
    write(path, *[f"2026-08-21 18:00:{n:02d},000 I ttsd: line {n}" for n in range(20)],
          mode="w")
    lines = LogTail(path).snapshot(max_lines=5)
    assert len(lines) == 5
    assert lines[-1].endswith("line 19")


def test_a_snapshot_positions_the_follower_at_the_end(tmp_path):
    path = tmp_path / "ttsd.log"
    write(path, LINE_A, mode="w")
    tail = LogTail(path)
    tail.snapshot()
    write(path, LINE_B)
    assert tail.read_new() == [LINE_B], "no re-delivery of what the snapshot already showed"
