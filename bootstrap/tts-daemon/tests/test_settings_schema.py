"""The settings schema: coercion, ranges, and the two flags that make claims about code.

The enums used to exist only in UI layers, and `write_local` accepted any dotted path with
any value. This is the validation a form makes necessary, plus two tests that check the
schema's `restart` and `shell` flags still match what the daemon actually does, since a
stale flag is a lie the UI would repeat.
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ttsd import settings_schema as schema

PKG = Path(__file__).resolve().parents[1] / "ttsd"


# ── coercion ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,want", [
    (True, True), ("true", True), ("on", True), ("1", True),
    (False, False), ("false", False), ("off", False), ("", False),
])
def test_bool_forms(raw, want):
    assert schema.coerce("edge.enabled", raw) is want


def test_bool_rejects_nonsense():
    with pytest.raises(ValueError):
        schema.coerce("edge.enabled", "maybe")


def test_numbers_and_their_ranges():
    assert schema.coerce("maxChars", "150") == 150
    assert schema.coerce("excitement", "0.4") == 0.4
    for key, bad in (("excitement", 1.5), ("music.duckPercent", 300),
                     ("daemon.port", 80), ("maxChars", 5)):
        with pytest.raises(ValueError):
            schema.coerce(key, bad)


def test_enums_are_closed():
    assert schema.coerce("summarize.mode", "haiku") == "haiku"
    with pytest.raises(ValueError) as caught:
        schema.coerce("summarize.mode", "gpt")
    assert "template" in str(caught.value), "the message lists the valid options"


def test_the_haiku_model_is_a_closed_list():
    """It was free text, and max_tokens 60 interacts badly with a thinking model."""
    assert schema.BY_KEY["summarize.haiku.model"]["kind"] == "enum"
    with pytest.raises(ValueError):
        schema.coerce("summarize.haiku.model", "some-other-model")


def test_csv_forms_and_the_events_allow_list():
    assert schema.coerce("events", "waiting, error") == ["waiting", "error"]
    assert schema.coerce("voices.pool", ["am_adam", " af_heart "]) == ["am_adam", "af_heart"]
    with pytest.raises(ValueError) as caught:
        schema.coerce("events", "waiting,shouting")
    assert "shouting" in str(caught.value)


def test_quiet_hours_must_be_a_time():
    assert schema.coerce("quietHours.start", "22:30") == "22:30"
    for bad in ("22", "9pm", "25:00", "22:75"):
        with pytest.raises(ValueError):
            schema.coerce("quietHours.start", bad)


def test_an_unknown_key_is_refused():
    """The write endpoint must not become a way to set arbitrary config paths."""
    with pytest.raises(ValueError):
        schema.coerce("summarize.somethingElse", "x")


def test_validate_splits_good_from_bad():
    clean, errors = schema.validate({
        "summarize.mode": "self",
        "music.duckPercent": 900,
        "nope": 1,
    })
    assert clean == {"summarize.mode": "self"}
    assert set(errors) == {"music.duckPercent", "nope"}


def test_public_schema_is_json_safe_and_complete():
    fields = schema.public_schema()
    json.dumps(fields)                                   # must not raise
    assert len(fields) == len(schema.FIELDS)
    for f in fields:
        assert f["group"] and f["label"] and f["kind"]
        assert isinstance(f["flags"], list)
        if f["kind"] == "enum":
            assert f["options"], f["key"]


# ── the flags make claims about the code; check them ─────────────────────────

def test_restart_flagged_keys_really_are_captured_at_startup():
    """If one of these became hot, the UI would keep telling you to restart for nothing."""
    build = (PKG / "__main__.py").read_text(encoding="utf-8")
    for field in schema.FIELDS:
        if "restart" not in field["flags"]:
            continue
        leaf = field["key"].split(".")[-1]
        assert leaf in build, f"{field['key']} is flagged restart but __main__ never reads it"


def test_shell_only_keys_are_not_read_by_the_daemon():
    """The claim on the page is that these change nothing here. Prove it."""
    sources = {
        path.name: path.read_text(encoding="utf-8")
        for path in PKG.glob("*.py")
        # config.py declares DEFAULTS, which mentions every key by name without reading
        # any of them; webui and the schema are the UI side of this very question.
        if path.name not in ("settings_schema.py", "webui.py", "config.py")
    }
    for field in schema.FIELDS:
        if "shell" not in field["flags"]:
            continue
        key = field["key"]
        leaf = key.split(".")[-1]
        hits = [
            name for name, text in sources.items()
            # A config read looks like cfg.get("that.key" ...); the leaf alone would match
            # unrelated identifiers, so match the quoted dotted path or quoted leaf.
            if re.search(rf'["\']{re.escape(key)}["\']', text)
            or re.search(rf'get\(\s*["\']{re.escape(leaf)}["\']', text)
        ]
        assert hits == [], f"{key} is flagged shell-only but {hits} reads it"


def test_every_undefaulted_key_is_actually_missing_from_defaults():
    from ttsd.config import DEFAULTS

    def present(tree, key):
        node = tree
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return False
            node = node[part]
        return True

    for field in schema.FIELDS:
        if "undefaulted" in field["flags"]:
            assert not present(DEFAULTS, field["key"]), (
                f"{field['key']} is in DEFAULTS now; drop the undefaulted flag")
