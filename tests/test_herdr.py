"""The managed herdr config: a key splice, not a whole-file render.

The distinction is the whole point of the module, so most of what is pinned here
is what a write must NOT do. The first machine this shipped to already had a
hand-written `~/.config/herdr/config.toml` carrying `onboarding = false` and
`[terminal] default_shell = "pwsh"`; a whole-file render would have deleted both
with nothing in any diff, the same way whole-file-copying `~/.claude/settings.json`
once disabled the agentmemory plugin.

Every test uses a throwaway config path via HERDR_CONFIG_PATH. `off` REWRITES
FILES, and a test that resolved to the developer's real config would eat it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import herdr, store  # noqa: E402
from tstack import platform as plat  # noqa: E402
from tstack.commands import herdr as command  # noqa: E402

# What a real machine had before the stack touched it. Used verbatim so the
# preservation tests are testing the case that actually occurred.
HAND_WRITTEN = 'onboarding = false\n[terminal]\ndefault_shell = "pwsh"\n'


def _toml_data() -> dict[str, str]:
    """Read back what `store.set` wrote to chezmoi.toml, standing in for chezmoi.

    `store.get` reads `[data]` through `chezmoi execute-template`, so with no
    chezmoi binary a POSIX save is written and then unreadable: `on` saved and
    `setting()` still answered `off`. Windows did not show it, because there the
    save goes to the config.json mirror, which `get` reads directly.

    Parsing the file the writer just produced keeps both platforms honest without
    stubbing the writer itself -- which is the half worth testing.
    """
    path = store.toml_path()
    if not path.is_file():
        return {}
    found: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            found[key.strip()] = value.strip().strip('"')
    return found


@pytest.fixture
def config(monkeypatch, tmp_path):
    """A throwaway config path, and a store that writes into tmp_path.

    Both store routes are real files here rather than stubs: on Windows a save
    goes to the config.json mirror and everywhere else to chezmoi.toml under the
    throwaway HOME, so `on` and `off` round-trip through whichever one this
    machine actually uses. Stubbing the writer to a no-op would have hidden the
    thing worth testing -- that the setting survives the save.
    """
    root = tmp_path / "home"
    root.mkdir()
    spot = tmp_path / "herdr" / "config.toml"
    spot.parent.mkdir(parents=True)
    monkeypatch.setenv("HERDR_CONFIG_PATH", str(spot))
    monkeypatch.setattr(Path, "home", staticmethod(lambda: root))
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    monkeypatch.setattr(store, "mirror_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr(store, "chezmoi_data", _toml_data)
    store.clear_cache()
    yield spot
    store.clear_cache()


def quiet(_message: str) -> None:
    pass


# ------------------------------------------------------------------- the target


def test_config_path_honours_herdr_own_override(config):
    assert herdr.target().config == config


def test_wsl_resolves_to_the_wsl_path_never_mnt_c(monkeypatch, tmp_path):
    """The two servers are independent, so neither side owns the other's config.

    Resolving across the boundary is the mistake tstack/ghostty.py documents
    making, and it would point WSL's herdr at a file only Windows' herdr reads.
    """
    monkeypatch.delenv("HERDR_CONFIG_PATH", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    resolved = herdr.target().config
    assert resolved == tmp_path / ".config" / "herdr" / "config.toml"
    assert "/mnt/c" not in str(resolved)


# ------------------------------------------------------------------- the splice


def test_splice_appends_a_theme_table_when_there_is_none():
    out = herdr.splice(HAND_WRITTEN)
    assert "[theme]" in out
    assert f'name = "{herdr.THEME}"' in out
    assert herdr.MARKER in out


def test_splice_keeps_every_other_setting():
    out = herdr.splice(HAND_WRITTEN)
    assert "onboarding = false" in out
    assert 'default_shell = "pwsh"' in out
    assert "[terminal]" in out


def test_splice_inserts_into_an_existing_theme_table():
    out = herdr.splice("[theme]\nauto_switch = false\n")
    lines = out.splitlines()
    assert lines[0] == "[theme]"
    assert herdr.MARKER in lines[1]
    assert "auto_switch = false" in out


def test_splice_replaces_a_theme_name_already_set():
    out = herdr.splice('[theme]\nname = "gruvbox"\n')
    assert "gruvbox" not in out
    assert out.count("name =") == 1


def test_splice_ignores_a_commented_key():
    """`herdr --default-config` ships every key commented out.

    A commented `# name = "catppuccin"` is documentation, not a setting.
    Rewriting it would lose the comment AND leave the real value ambiguous.
    """
    out = herdr.splice('[theme]\n# name = "catppuccin"\n')
    assert '# name = "catppuccin"' in out
    assert herdr.MARKER in out


def test_splice_does_not_touch_a_name_in_another_table():
    out = herdr.splice('[agents]\nname = "claude"\n')
    assert 'name = "claude"' in out
    assert "[theme]" in out


def test_splice_is_idempotent():
    once = herdr.splice(HAND_WRITTEN)
    assert herdr.splice(once) == once


def test_splice_preserves_crlf():
    """The FILE's line endings decide what is inserted, never the platform's."""
    out = herdr.splice("[theme]\r\nauto_switch = false\r\n")
    assert "\r\n" in out
    assert "\n" not in out.replace("\r\n", "")


def test_unsplice_removes_only_our_line():
    out = herdr.unsplice(herdr.splice(HAND_WRITTEN))
    assert herdr.MARKER not in out
    assert "onboarding = false" in out
    assert 'default_shell = "pwsh"' in out


def test_unsplice_keeps_a_hand_edited_theme_name():
    """A `name` the user has since edited is theirs, marker gone or not."""
    out = herdr.unsplice('[theme]\nname = "nord"\n')
    assert 'name = "nord"' in out


# ------------------------------------------------------------------- backups


def test_render_backs_the_file_up_before_the_first_write(config):
    config.write_text(HAND_WRITTEN, encoding="utf-8")
    herdr.render(quiet)
    saved = herdr.newest_backup(config.parent)
    assert saved is not None
    assert saved.read_text(encoding="utf-8") == HAND_WRITTEN


def test_render_does_not_re_backup_a_file_already_ours(config):
    config.write_text(HAND_WRITTEN, encoding="utf-8")
    herdr.render(quiet)
    first = herdr.newest_backup(config.parent)
    config.write_text(herdr.splice(HAND_WRITTEN) + "extra = 1\n", encoding="utf-8")
    herdr.render(quiet)
    assert herdr.newest_backup(config.parent) == first


def test_backup_never_clobbers_a_same_day_one(config):
    config.write_text("first\n", encoding="utf-8")
    one = herdr.backup(config)
    config.write_text("second\n", encoding="utf-8")
    two = herdr.backup(config)
    assert one is not None and two is not None
    assert one != two
    assert one.read_text(encoding="utf-8") == "first\n"


def test_backup_is_none_when_there_is_no_file(config):
    assert herdr.backup(config) is None


# ------------------------------------------------------------------- the verbs


def test_off_restores_the_backup(config):
    config.write_text(HAND_WRITTEN, encoding="utf-8")
    herdr.turn_on(quiet, lambda: None)
    herdr.turn_off(quiet, lambda: None)
    assert config.read_text(encoding="utf-8") == HAND_WRITTEN


def test_off_never_deletes_the_file(config):
    """Ghostty's `off` unlinks what it deployed. Here the file is mostly yours."""
    config.write_text(HAND_WRITTEN, encoding="utf-8")
    herdr.turn_on(quiet, lambda: None)
    herdr.turn_off(quiet, lambda: None)
    assert config.exists()


def test_off_with_no_backup_removes_only_our_key(config):
    """The stack created the file, so there is no backup to restore."""
    herdr.turn_on(quiet, lambda: None)
    assert herdr.MARKER in config.read_text(encoding="utf-8")
    herdr.turn_off(quiet, lambda: None)
    assert herdr.MARKER not in config.read_text(encoding="utf-8")


def test_on_saves_the_setting(config):
    herdr.turn_on(quiet, lambda: None)
    assert herdr.setting() == "on"
    herdr.turn_off(quiet, lambda: None)
    assert herdr.setting() == "off"


def test_default_setting_is_off(config):
    """A machine that has never heard of herdr must not grow a herdr config."""
    assert herdr.setting() == "off"


# --------------------------------------------------------- the prefix collision


def test_prefix_defaults_to_herdrs_own(config):
    assert herdr.configured_prefix() == "ctrl+b"


def test_prefix_is_read_from_the_file(config):
    config.write_text('[keys]\nprefix = "f12"\n', encoding="utf-8")
    assert herdr.configured_prefix() == "f12"


def test_collision_is_reported_against_the_saved_tmux_prefix(config, monkeypatch):
    monkeypatch.setattr(store, "get", lambda key, default=None: "ctrl-b")
    monkeypatch.setattr(herdr.shutil, "which", lambda name: "/usr/bin/" + name)
    assert ("tmuxPrefix", "ctrl-b") in herdr.collisions()


def test_no_collision_when_the_prefixes_differ(config, monkeypatch):
    config.write_text('[keys]\nprefix = "f12"\n', encoding="utf-8")
    monkeypatch.setattr(store, "get", lambda key, default=None: "ctrl-b")
    monkeypatch.setattr(herdr.shutil, "which", lambda name: "/usr/bin/" + name)
    assert herdr.collisions() == []


def test_no_collision_when_the_other_program_is_absent(config, monkeypatch):
    """A warning nobody can act on is a nag.

    herdr keeps its own ctrl+b by decision, so on a box with no tmux this would
    otherwise print on every `tstack doctor` run forever and never be
    satisfiable -- the failure `ts_app_installable` was added to end.
    """
    monkeypatch.setattr(store, "get", lambda key, default=None: "ctrl-b")
    monkeypatch.setattr(herdr.shutil, "which", lambda name: None)
    assert herdr.collisions() == []


# ------------------------------------------------------ parsing `herdr status`


def test_server_state_reads_the_server_block_not_the_first_line(monkeypatch):
    """The first line of `herdr status` is "client:" and means nothing."""
    text = (
        "client:\n  version: 0.8.2\n\n"
        "server:\n  status: running\n  socket: /tmp/herdr.sock\n\n"
        "update:\n  restart_needed: no\n"
    )

    class Ran:
        returncode = 0
        stdout = text
        stderr = ""

    monkeypatch.setattr(herdr, "_run", lambda *a, **k: Ran())
    monkeypatch.setattr(herdr, "binary", lambda: "herdr")
    assert herdr.server_state() == "running  (/tmp/herdr.sock)"


def test_windows_side_is_none_off_wsl(monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    assert herdr.windows_side() is None


def test_windows_side_says_so_when_interop_cannot_see_herdr(monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    monkeypatch.setattr(herdr.shutil, "which", lambda name: None)
    assert "not on PATH" in (herdr.windows_side() or "")


def test_server_state_falls_back_to_the_exit_code(monkeypatch):
    """A `herdr status` with no server block still has to say something."""

    class Ran:
        returncode = 1
        stdout = "client:\n  version: 0.8.2\n"
        stderr = ""

    monkeypatch.setattr(herdr, "_run", lambda *a, **k: Ran())
    monkeypatch.setattr(herdr, "binary", lambda: "herdr")
    assert herdr.server_state() == "not running"


def test_server_state_says_so_when_herdr_is_absent(monkeypatch):
    monkeypatch.setattr(herdr, "binary", lambda: None)
    assert herdr.server_state() == "herdr is not installed"


def test_version_and_channel_are_none_without_the_binary(monkeypatch):
    monkeypatch.setattr(herdr, "binary", lambda: None)
    assert herdr.version() is None
    assert herdr.channel() is None


def test_channel_is_read_back_never_stored(monkeypatch):
    """Detected, like the WezTerm channel. A stored value can disagree."""

    class Ran:
        returncode = 0
        stdout = "stable\n"
        stderr = ""

    monkeypatch.setattr(herdr, "binary", lambda: "herdr")
    monkeypatch.setattr(herdr, "_run", lambda *a, **k: Ran())
    assert herdr.channel() == "stable"


# ------------------------------------------------------------------- reporting


def _installed(monkeypatch, version: str = "herdr 0.8.2") -> None:
    monkeypatch.setattr(herdr, "binary", lambda: "herdr")
    monkeypatch.setattr(herdr, "version", lambda: version)
    monkeypatch.setattr(herdr, "channel", lambda: "stable")
    monkeypatch.setattr(herdr, "server_state", lambda: "running")
    monkeypatch.setattr(herdr, "windows_side", lambda: None)


def test_status_reports_an_absent_config(config, monkeypatch, capsys):
    _installed(monkeypatch)
    monkeypatch.setattr(herdr, "collisions", lambda: [])
    assert herdr.status(print) == 0
    out = capsys.readouterr().out
    assert "(absent)" in out
    assert "read back, never stored" in out


def test_status_distinguishes_our_file_from_yours(config, monkeypatch, capsys):
    _installed(monkeypatch)
    monkeypatch.setattr(herdr, "collisions", lambda: [])
    config.write_text(HAND_WRITTEN, encoding="utf-8")
    herdr.status(print)
    assert "yours" in capsys.readouterr().out
    config.write_text(herdr.splice(HAND_WRITTEN), encoding="utf-8")
    herdr.status(print)
    assert "carries our" in capsys.readouterr().out


def test_status_names_both_places_to_fix_a_collision(config, monkeypatch, capsys):
    _installed(monkeypatch)
    monkeypatch.setattr(herdr, "collisions", lambda: [("tmuxPrefix", "ctrl-b")])
    herdr.status(print)
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "tstack config" in out
    assert "[keys] prefix" in out


def test_status_says_when_herdr_is_not_installed(config, monkeypatch, capsys):
    monkeypatch.setattr(herdr, "binary", lambda: None)
    monkeypatch.setattr(herdr, "version", lambda: None)
    monkeypatch.setattr(herdr, "collisions", lambda: [])
    assert herdr.status(print) == 0
    assert "not installed" in capsys.readouterr().out


def test_status_reports_the_windows_server_too(config, monkeypatch, capsys):
    """Two independent servers, so both get said out loud."""
    _installed(monkeypatch)
    monkeypatch.setattr(herdr, "windows_side", lambda: "running")
    monkeypatch.setattr(herdr, "collisions", lambda: [])
    herdr.status(print)
    assert "Windows side" in capsys.readouterr().out


def test_update_reports_and_installs_nothing(config, monkeypatch, capsys):
    _installed(monkeypatch)
    assert herdr.report_update(print) == 0
    out = capsys.readouterr().out
    assert "herdr update" in out
    assert "does not run that for you" in out


def test_update_fails_when_herdr_is_absent(config, monkeypatch, capsys):
    monkeypatch.setattr(herdr, "version", lambda: None)
    assert herdr.report_update(print) == 1
    assert "not installed" in capsys.readouterr().out


def test_off_on_a_machine_with_no_config_says_nothing_alarming(config, monkeypatch, capsys):
    assert herdr.turn_off(print, lambda: None) == 0
    assert not config.exists()


# ------------------------------------------------------- the command entry point


def test_help_is_printed_for_every_help_flag(capsys):
    for flag in ("-h", "--help", "help"):
        assert command.main([flag]) == 0
        assert "the managed herdr config" in capsys.readouterr().out


def test_an_unknown_verb_is_usage_not_a_crash(capsys):
    assert command.main(["frobnicate"]) == 2
    assert "unknown action" in capsys.readouterr().err


def test_a_stray_argument_is_refused(capsys):
    assert command.main(["on", "extra"]) == 2
    assert "unexpected argument" in capsys.readouterr().err


def test_no_verb_means_status(config, monkeypatch, capsys):
    monkeypatch.setattr(herdr, "status", lambda say: 0)
    assert command.main([]) == 0


def test_dry_run_saves_nothing(config, capsys):
    assert command.main(["on", "--dry-run"]) == 0
    assert "would set herdrConfig = on" in capsys.readouterr().out
    assert herdr.setting() == "off"
    assert not config.exists()


def test_the_command_routes_on_and_off(config, monkeypatch):
    monkeypatch.setattr(command.store, "chezmoi_init", lambda: True)
    assert command.main(["on"]) == 0
    assert herdr.setting() == "on"
    assert command.main(["off"]) == 0
    assert herdr.setting() == "off"


def test_the_command_routes_update(config, monkeypatch, capsys):
    monkeypatch.setattr(herdr, "version", lambda: None)
    assert command.main(["update"]) == 1
