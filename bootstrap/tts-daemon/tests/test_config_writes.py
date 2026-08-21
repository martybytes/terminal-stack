"""local.json writes and the machine-local secret store.

The old writer was a plain read-modify-write with no lock and no atomicity, and one bad
byte made the next write replace every other override with a single-key document. A
settings form is exactly that workload, so these are the tests that make it safe to build
one.
"""

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ttsd import config as config_mod
from ttsd import keystore


def _isolate(tmp_path, monkeypatch):
    """Redirect both homes: tts_config_dir uses Path.home(), state_dir uses LOCALAPPDATA."""
    home = tmp_path / "home"
    (home / ".claude" / "tts").mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    importlib.reload(config_mod)
    importlib.reload(keystore)
    return home / ".claude" / "tts" / "local.json"


def _cfg():
    return config_mod.Config()


# ── local.json ───────────────────────────────────────────────────────────────

def test_single_and_nested_writes(tmp_path, monkeypatch):
    local = _isolate(tmp_path, monkeypatch)
    cfg = _cfg()

    cfg.write_local("summarize.mode", "haiku")
    cfg.write_local("music.duckPercent", 45)

    saved = json.loads(local.read_text(encoding="utf-8"))
    assert saved == {"summarize": {"mode": "haiku"}, "music": {"duckPercent": 45}}
    assert cfg.get("summarize.mode") == "haiku", "and the live view reloaded"


def test_many_keys_land_in_one_document(tmp_path, monkeypatch):
    local = _isolate(tmp_path, monkeypatch)
    cfg = _cfg()

    assert cfg.write_local_many({
        "summarize.mode": "ollama",
        "summarize.ollama.model": "llama3.2:3b",
        "music.mode": "pause",
        "events": ["waiting", "error"],
    }) is True

    saved = json.loads(local.read_text(encoding="utf-8"))
    assert saved["summarize"] == {"mode": "ollama", "ollama": {"model": "llama3.2:3b"}}
    assert saved["music"]["mode"] == "pause"
    assert saved["events"] == ["waiting", "error"]


def test_an_unparseable_overlay_is_preserved_not_overwritten(tmp_path, monkeypatch):
    """One bad byte used to destroy every other override on the next write."""
    local = _isolate(tmp_path, monkeypatch)
    local.write_text('{"summarize": {"mode": "self"} ,,, broken', encoding="utf-8")

    cfg = _cfg()
    assert cfg.write_local_many({"music.mode": "off"}) is True

    kept = list(local.parent.glob("local.json.bad.*"))
    assert len(kept) == 1, "the corrupt file is set aside, with the repo's dated suffix"
    assert "broken" in kept[0].read_text(encoding="utf-8")
    assert json.loads(local.read_text(encoding="utf-8")) == {"music": {"mode": "off"}}


def test_a_same_day_second_corruption_does_not_clobber_the_first(tmp_path, monkeypatch):
    local = _isolate(tmp_path, monkeypatch)
    cfg = _cfg()
    for marker in ("first", "second"):
        local.write_text("{ broken " + marker, encoding="utf-8")
        cfg.write_local_many({"music.mode": "off"})
    kept = sorted(p.name for p in local.parent.glob("local.json.bad.*"))
    assert len(kept) == 2, kept
    assert kept[1].endswith(".1"), "same-day collisions get the .N suffix"


def test_no_temp_or_lock_files_are_left_behind(tmp_path, monkeypatch):
    local = _isolate(tmp_path, monkeypatch)
    _cfg().write_local_many({"music.mode": "duck", "summarize.mode": "template"})
    leftovers = [p.name for p in local.parent.iterdir() if p.name != "local.json"]
    assert leftovers == [], leftovers


def test_a_scalar_in_the_way_is_replaced_by_the_branch(tmp_path, monkeypatch):
    local = _isolate(tmp_path, monkeypatch)
    local.write_text(json.dumps({"summarize": "self"}), encoding="utf-8")
    cfg = _cfg()

    assert cfg.write_local_many({"summarize.mode": "haiku"}) is True
    saved = json.loads(local.read_text(encoding="utf-8"))
    assert saved["summarize"] == {"mode": "haiku"}


def test_an_empty_update_is_a_no_op(tmp_path, monkeypatch):
    local = _isolate(tmp_path, monkeypatch)
    assert _cfg().write_local_many({}) is True
    assert not local.exists()


def test_a_stale_lock_does_not_block_a_save_forever(tmp_path, monkeypatch):
    """A leftover lock must degrade to an unserialized write, never to a silent no-op."""
    local = _isolate(tmp_path, monkeypatch)
    lock = local.with_suffix(".json.lock")
    lock.write_text("999999", encoding="utf-8")

    cfg = _cfg()
    assert cfg.write_local_many({"music.mode": "smart"}, ) is True
    assert json.loads(local.read_text(encoding="utf-8"))["music"]["mode"] == "smart"


# ── the secret store ─────────────────────────────────────────────────────────

def test_secret_round_trip_and_clear(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert keystore.get(keystore.ANTHROPIC_API_KEY) == ""
    assert keystore.set_value(keystore.ANTHROPIC_API_KEY, "sk-ant-abcdef123456") is True
    assert keystore.get(keystore.ANTHROPIC_API_KEY) == "sk-ant-abcdef123456"
    assert keystore.set_value(keystore.ANTHROPIC_API_KEY, "") is True
    assert keystore.get(keystore.ANTHROPIC_API_KEY) == ""


def test_the_store_never_holds_an_arbitrary_name(tmp_path, monkeypatch):
    """The settings endpoint must not become a way to write any key anywhere."""
    _isolate(tmp_path, monkeypatch)
    assert keystore.set_value("somethingElse", "value") is False
    assert keystore.get("somethingElse") == ""


def test_resolve_reports_where_the_value_came_from(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert keystore.resolve(keystore.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY") == ("", "")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert keystore.resolve(keystore.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY") == (
        "from-env", "env")

    keystore.set_value(keystore.ANTHROPIC_API_KEY, "from-store")
    assert keystore.resolve(keystore.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY") == (
        "from-store", "store")


def test_describe_never_returns_the_value(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    keystore.set_value(keystore.ANTHROPIC_API_KEY, "sk-ant-secret-tail9999")
    shown = keystore.describe(keystore.ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY")
    rendered = json.dumps(shown)
    assert "sk-ant-secret" not in rendered
    assert shown["set"] is True and shown["source"] == "store"
    assert shown["tail"] == "9999", "enough to tell two keys apart, not enough to use one"


def test_a_corrupt_secret_store_is_ignored_not_rewritten(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    path = keystore.secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not json", encoding="utf-8")

    assert keystore.get(keystore.ANTHROPIC_API_KEY) == "", "fails soft"
    assert path.read_text(encoding="utf-8") == "{ not json", "a typo stays fixable by hand"


def test_an_unusable_state_dir_reports_failure(tmp_path, monkeypatch):
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where the state dir should be", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(blocker))
    importlib.reload(keystore)
    assert keystore.set_value(keystore.ANTHROPIC_API_KEY, "x") is False
    assert keystore.get(keystore.ANTHROPIC_API_KEY) == ""
