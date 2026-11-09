"""The mem:insights compaction and the hung-engine watchdog.

agentmemory 0.9.29 stored ~280 KB of unused provenance on every insight. The
scope reached 1.0 GB, the iii engine (which keeps every state scope resident)
idled at 17 GB, hung with its process alive, and was OOM-killed at 28.5 GB.
compact-insights.mjs rewrites the scope file offline; these tests pin its file
codec against the iii file_based kv layout and its refusal to lose records.
"""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STACK = ROOT / "services" / "stacks" / "agentmemory"
COMPACT = STACK / "compact-insights.mjs"

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def encode(json_bytes: bytes) -> bytes:
    """iii 0.11 file_based kv: one rkyv ArchivedString holding the scope JSON."""
    n = len(json_bytes)
    pad = (4 - n % 4) % 4
    repr_ = bytes(
        [0x80 | (n & 0x3F), (n >> 6) & 0xFF, (n >> 14) & 0xFF, (n >> 22) & 0xFF]
    ) + struct.pack("<i", -(n + pad))
    return json_bytes + b"\0" * pad + repr_


def decode(raw: bytes) -> bytes:
    b0, b1, b2, b3 = raw[-8:-4]
    n = (b0 & 0x3F) | (b1 << 6) | (b2 << 14) | (b3 << 22)
    assert struct.unpack("<i", raw[-4:])[0] == -(len(raw) - 8)
    return raw[:n]


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(NODE), str(COMPACT), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=120,
        start_new_session=True,
    )


def insight(i: int, concepts: int, facts: int) -> dict:
    names = [f"concept é{n}" for n in range(concepts)]
    return {
        "id": f"ins_{i:04d}",
        "title": f"Insight {i}",
        "content": 'quoted "text" with \\ backslash and } brace',
        "confidence": 0.5,
        "tags": names,
        "sourceConceptCluster": names,
        "sourceMemoryIds": [f"sem_{n}" for n in range(facts)],
        "sourceLessonIds": [],
        "sourceCrystalIds": [],
    }


def write_scope(path: Path, records: dict) -> None:
    path.write_bytes(encode(json.dumps(records, ensure_ascii=False).encode()))


@needs_node
def test_codec_round_trips_the_python_encoder(tmp_path: Path) -> None:
    store = tmp_path / "state_store.db"
    store.mkdir()
    # Lengths around every padding remainder and each length-byte boundary.
    for n in (9, 10, 11, 12, 63, 64, 16383, 16384, 70000):
        body = json.dumps({"k": "x" * max(0, n - 8)}).encode()
        (store / f"s{n}.bin").write_bytes(encode(body))
    result = run("--verify-codec", str(store))
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["bad"] == []


@needs_node
def test_compaction_trims_provenance_and_keeps_every_record(tmp_path: Path) -> None:
    store = tmp_path / "state_store.db"
    store.mkdir()
    scope = store / "mem%3Ainsights.bin"
    records = {f"ins_{i:04d}": insight(i, 500, 600) for i in range(30)}
    records["ins_small"] = insight(99, 3, 2)
    write_scope(scope, records)
    before = scope.read_bytes()

    result = run(str(scope), "--backup-dir", str(tmp_path))
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["skipped"] is False
    assert report["records"] == 31 and report["trimmed"] == 30
    assert Path(report["backup"]).read_bytes() == before

    out = json.loads(decode(scope.read_bytes()))
    assert set(out) == set(records)
    big = out["ins_0000"]
    assert len(big["tags"]) == 60 and len(big["sourceConceptCluster"]) == 60
    assert len(big["sourceMemoryIds"]) == 40
    assert big["sourceTruncated"] == {
        "tags": 500,
        "sourceConceptCluster": 500,
        "sourceMemoryIds": 600,
    }
    assert big["content"] == records["ins_0000"]["content"]
    assert big["tags"][0] == "concept é0"
    assert out["ins_small"] == records["ins_small"]

    again = json.loads(run(str(scope), "--backup-dir", str(tmp_path)).stdout)
    assert again["skipped"] is True and again["reason"] == "nothing to trim"


@needs_node
def test_compaction_leaves_a_small_file_alone(tmp_path: Path) -> None:
    store = tmp_path / "state_store.db"
    store.mkdir()
    scope = store / "mem%3Ainsights.bin"
    write_scope(scope, {"ins_0": insight(0, 500, 500)})
    before = scope.read_bytes()
    report = json.loads(run(str(scope), "--min-bytes", str(10**9)).stdout)
    assert report["skipped"] is True
    assert scope.read_bytes() == before
    assert list(tmp_path.glob("*.before-compact-*")) == []


@needs_node
def test_compaction_refuses_a_file_it_cannot_decode(tmp_path: Path) -> None:
    store = tmp_path / "state_store.db"
    store.mkdir()
    scope = store / "mem%3Ainsights.bin"
    scope.write_bytes(b"not an rkyv string at all")
    before = scope.read_bytes()
    result = run(str(scope), "--backup-dir", str(tmp_path))
    assert result.returncode != 0
    assert scope.read_bytes() == before


def test_entrypoint_compacts_before_the_engine_starts() -> None:
    text = (STACK / "entrypoint.sh").read_text(encoding="utf-8")
    compact_at = text.index("compact-insights.mjs")
    start_at = text.index('gosu "$RUN_AS" agentmemory "$@" &')
    assert compact_at < start_at, "the scope may only be rewritten while no engine has it open"
    assert "compact-insights.mjs" in (STACK / "Dockerfile").read_text(encoding="utf-8")


def test_entrypoint_restarts_a_hung_engine_only_after_it_answered() -> None:
    """A hung engine kept its process alive for four days. Detect it by livez,
    but only after livez has answered once and only after a long outage: a
    busy node event loop misses livez for minutes while healthy."""
    text = (STACK / "entrypoint.sh").read_text(encoding="utf-8")
    assert 'HANG_SECONDS="${AGENTMEMORY_ENGINE_HANG_SECONDS:-900}"' in text
    assert '[ "$answered" = 1 ] && [ $((elapsed - last_ok)) -ge "$HANG_SECONDS" ]' in text


def test_new_insights_store_only_the_provenance_the_prompt_used() -> None:
    patch = (STACK / "patch-agentmemory.mjs").read_text(encoding="utf-8")
    assert "insights store only the provenance the prompt used" in patch
    assert "tags: cluster.used?.concepts ?? conceptNames" in patch
    assert "sourceMemoryIds: cluster.used?.factIds ?? cluster.factIds" in patch
