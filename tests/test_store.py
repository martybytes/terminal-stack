"""The one writer, and the schema that describes what it writes.

Every test here uses a throwaway HOME. `docs/verifying-changes.md` section 4 is
explicit about this and the reason is not hypothetical: a test that writes the
developer's real chezmoi.toml corrupts the machine it is meant to protect.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import platform as plat  # noqa: E402
from tstack import schema, store  # noqa: E402


@pytest.fixture(autouse=True)
def _throwaway_home(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    # Pin a POSIX platform: chezmoi [data] is the store there, which is what the
    # TOML tests below are about. On Windows with no chezmoi the writer correctly
    # routes to config.json instead, and the tests for that path say so
    # explicitly by overriding this.
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    monkeypatch.setattr(store, "mirror", lambda: {})
    monkeypatch.setattr(store, "mirror_path", lambda: None)
    store.clear_cache()
    yield home
    store.clear_cache()


def toml_text() -> str:
    return store.toml_path().read_text(encoding="utf-8")


# ------------------------------------------------------------------- writing


def test_the_first_write_creates_the_data_block(_throwaway_home):
    store.set("themeMode", "light")
    assert toml_text() == '[data]\nthemeMode = "light"\n'


def test_an_existing_key_is_replaced_in_place():
    store.set("themeMode", "dark")
    store.set("themeMode", "light")
    body = toml_text()
    assert body.count("themeMode") == 1
    assert 'themeMode = "light"' in body


def test_a_new_key_lands_inside_the_existing_data_block():
    store.set("themeMode", "dark")
    store.set("tmuxPrefix", "ctrl-a")
    lines = [line for line in toml_text().split("\n") if line]
    assert lines[0] == "[data]"
    assert set(lines[1:]) == {'themeMode = "dark"', 'tmuxPrefix = "ctrl-a"'}


def test_a_data_block_is_appended_to_a_toml_that_lacks_one():
    path = store.toml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('sourceDir = "/somewhere"\n', encoding="utf-8")
    store.set("themeMode", "dark")
    body = toml_text()
    assert 'sourceDir = "/somewhere"' in body, "the existing content must survive"
    assert "[data]" in body
    assert 'themeMode = "dark"' in body


def test_unrelated_content_is_never_disturbed():
    """chezmoi.toml holds sourceDir and whatever else the user put there. A write
    that reformats the file is a write that loses something."""
    path = store.toml_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        'sourceDir = "/x"\n\n[edit]\ncommand = "nvim"\n\n[data]\nthemeMode = "dark"\n',
        encoding="utf-8",
    )
    store.set("themeMode", "light")
    body = toml_text()
    assert '[edit]\ncommand = "nvim"' in body
    assert 'sourceDir = "/x"' in body
    assert 'themeMode = "light"' in body


def test_a_list_is_written_as_a_toml_array_not_a_string():
    """apps is an array. Quoting it as one string produces a chezmoi.toml that
    parses but renders every template with a single nonsense app name."""
    store.set_list("apps", ["fzf", "bat", "ripgrep"])
    assert 'apps = ["fzf", "bat", "ripgrep"]' in toml_text()


def test_an_existing_list_is_replaced_not_appended():
    store.set_list("apps", ["fzf"])
    store.set_list("apps", ["bat", "eza"])
    body = toml_text()
    assert body.count("apps = ") == 1
    assert 'apps = ["bat", "eza"]' in body


def test_a_write_is_atomic_and_leaves_no_temp_file():
    store.set("themeMode", "dark")
    leftovers = list(store.toml_path().parent.glob("*.tmp.*"))
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_a_write_to_an_unwritable_location_raises_rather_than_lying(monkeypatch):
    """A save that reports success while changing nothing is the failure this
    module exists to end, so the error is raised, never swallowed."""

    def refuse(*a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "write_text", refuse)
    # The FIRST write, on a machine with no chezmoi.toml yet: the fresh-install
    # path, and the one that used to raise a bare OSError instead.
    with pytest.raises(store.StoreError, match="could not write"):
        store.set("themeMode", "dark")
    with pytest.raises(store.StoreError, match="could not write"):
        store.set_list("apps", ["fzf"])


def test_writing_invalidates_the_read_cache(monkeypatch):
    """chezmoi_data() is memoised. Without invalidation, a set followed by a get
    in the same process returns the old value - which is exactly the shape of the
    bug where a save 'did not take'."""
    seen = {"calls": 0}

    def fake():
        seen["calls"] += 1
        return {}

    monkeypatch.setattr(store, "chezmoi_data", fake)
    store.get("themeMode")
    store.set("themeMode", "light")
    store.get("themeMode")
    assert seen["calls"] >= 2


def test_chezmoi_init_is_skipped_when_chezmoi_is_absent(monkeypatch):
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    assert store.chezmoi_init() is False


# -------------------------------------------------------------------- schema


def test_every_setting_has_a_label_and_a_group():
    for setting in schema.SETTINGS:
        assert setting.label, setting.key
        assert setting.group in schema.GROUPS, setting.key
        assert setting.kind in ("choice", "text", "list"), setting.key


def test_a_choice_setting_lists_its_options():
    for setting in schema.SETTINGS:
        if setting.kind == "choice":
            assert setting.options, f"{setting.key} is a choice with no options"


def test_a_default_is_always_one_of_the_options():
    for setting in schema.SETTINGS:
        if setting.options and setting.default:
            assert setting.default in setting.options, setting.key


def test_derived_keys_refuse_to_be_written():
    """leaderKey and friends are regenerated by `chezmoi init`, so a direct write
    survives until the next save and then silently vanishes."""
    for key in ("leaderKey", "leaderMods", "tmuxPrefixResolved", "resolvedTheme"):
        reason = schema.BY_KEY[key].validate("anything")
        assert reason and "derived" in reason, key


def test_agentmemory_enabled_is_derived_from_the_backend():
    """One slot. Anything else writing it produces the drift doctor reports."""
    assert schema.DERIVED in schema.BY_KEY["agentmemoryEnabled"].flags


def test_a_bad_choice_is_rejected_by_name():
    reason = schema.BY_KEY["themeMode"].validate("purple")
    assert reason and "dark" in reason and "light" in reason


def test_a_good_choice_is_accepted():
    assert schema.BY_KEY["themeMode"].validate("follow") is None


def test_empty_text_is_rejected():
    assert schema.BY_KEY["leaderChord"].validate("  ") is not None


def test_the_source_layer_is_reported(monkeypatch):
    """Which layer won is the whole point: a value that looks right for the wrong
    reason is otherwise invisible."""
    monkeypatch.setattr(store, "chezmoi_data", lambda: {"themeMode": "light"})
    monkeypatch.setattr(store, "mirror", lambda: {"tmuxPrefix": "ctrl-a"})
    assert schema.source_of("themeMode") == schema.FROM_CHEZMOI
    assert schema.source_of("tmuxPrefix") == schema.FROM_MIRROR
    assert schema.source_of("weztermMux") == schema.FROM_DEFAULT
    assert schema.source_of("leaderKey") == schema.UNSET


def test_snapshot_is_serialisable_and_complete(monkeypatch):
    import json

    monkeypatch.setattr(store, "chezmoi_data", lambda: {})
    rows = schema.snapshot()
    assert len(rows) == len(schema.SETTINGS)
    for row in rows:
        assert {"key", "label", "kind", "group", "value", "default", "source", "flags"} <= set(row)
    json.dumps(rows)


def test_the_schema_and_the_store_agree_on_defaults():
    """Two default tables would drift, and the one that lost would be the one
    nobody was reading."""
    for key, default in store.DEFAULTS.items():
        if key in schema.BY_KEY:
            assert schema.BY_KEY[key].default == default, key


# ------------------------------------------- the Windows-standalone write path


def test_windows_without_chezmoi_writes_the_mirror_not_a_toml(monkeypatch, tmp_path):
    """A Windows-standalone install has no chezmoi: sync-windows.ps1 renders from
    config.json and nothing ever reads a chezmoi.toml. Writing [data] there is a
    save that reports success and changes nothing that matters."""
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    mirror = tmp_path / "AppData" / "Local" / "terminal-stack" / "config.json"
    monkeypatch.setattr(store, "mirror_path", lambda: mirror)

    assert store.writes_to_mirror() is True
    store.set("themeMode", "light")

    import json as _json

    assert _json.loads(mirror.read_text(encoding="utf-8"))["themeMode"] == "light"
    assert not store.toml_path().exists(), "no chezmoi.toml may be created there"


def test_wsl_is_not_the_standalone_case(monkeypatch):
    """WSL can see the mirror but chezmoi is authoritative there, and
    ts_mirror_windows_config derives config.json from [data] afterwards."""
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    assert store.writes_to_mirror() is False


def test_windows_with_chezmoi_is_not_the_standalone_case(monkeypatch, tmp_path):
    binary = tmp_path / "chezmoi.exe"
    binary.write_text("", encoding="utf-8")
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: str(binary))
    assert store.writes_to_mirror() is False


def test_a_mirror_write_preserves_every_other_key(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    mirror = tmp_path / "config.json"
    mirror.write_text(
        '{"leaderChord": "ctrl-a", "somethingFuture": {"nested": true}}', encoding="utf-8"
    )
    monkeypatch.setattr(store, "mirror_path", lambda: mirror)

    store.set("themeMode", "dark")

    import json as _json

    body = _json.loads(mirror.read_text(encoding="utf-8"))
    assert body["leaderChord"] == "ctrl-a"
    assert body["somethingFuture"] == {"nested": True}, "unknown keys must survive"
    assert body["themeMode"] == "dark"


def test_an_unreadable_mirror_is_never_overwritten(monkeypatch, tmp_path):
    """It may hold settings this version does not know about. Clobbering them is
    the silent loss the whole module is built to avoid."""
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    mirror = tmp_path / "config.json"
    mirror.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(store, "mirror_path", lambda: mirror)

    with pytest.raises(store.StoreError, match="refusing to overwrite"):
        store.set("themeMode", "dark")
    assert mirror.read_text(encoding="utf-8") == "{ this is not json"


def test_a_mirror_list_is_written_as_json(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    mirror = tmp_path / "config.json"
    monkeypatch.setattr(store, "mirror_path", lambda: mirror)

    store.set_list("apps", ["fzf", "bat"])

    import json as _json

    assert _json.loads(mirror.read_text(encoding="utf-8"))["apps"] == ["fzf", "bat"]
