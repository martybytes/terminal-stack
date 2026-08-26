"""`tstack mux`, with no WezTerm and no mux server.

What is worth pinning is the part that was wrong twice: the difference between the
*saved* setting and the *rendered* one, and that nothing here ever restarts the
mux server on its own.
"""

from __future__ import annotations

import pytest

from tstack import platform as plat
from tstack import store
from tstack.commands import mux


@pytest.fixture
def quiet_store(monkeypatch):
    values: dict[str, str] = {}
    monkeypatch.setattr(store, "get", lambda key, default=None: values.get(key, default or ""))
    return values


@pytest.fixture
def no_processes(monkeypatch):
    monkeypatch.setattr(mux, "mux_pids", lambda: [])
    monkeypatch.setattr(mux, "wez_cli", lambda: None)


def test_help_works_with_no_clone_and_no_chezmoi(capsys):
    assert mux.main(["-h"]) == 0
    assert "tstack mux" in capsys.readouterr().out


def test_help_is_ascii_only():
    """A Windows console on codepage 437 renders an em dash as a replacement
    glyph, and this help is read on exactly such a console."""
    assert mux.HELP.isascii()


def test_an_unknown_command_and_an_unknown_flag_both_exit_two(capsys):
    assert mux.main(["nonsense"]) == 2
    assert mux.main(["--nonsense"]) == 2
    assert mux.main(["status", "extra"]) == 2


def test_status_reports_the_setting_and_the_rendered_config(
    quiet_store, no_processes, monkeypatch, tmp_path, capsys
):
    quiet_store["weztermMux"] = "on"
    cfg = tmp_path / ".wezterm.lua"
    cfg.write_text("local MUX_ENABLED = 'on' == 'on'\n", encoding="utf-8")
    monkeypatch.setattr(mux, "rendered_cfg", lambda: cfg)
    assert mux.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "setting  : on" in out
    assert "rendered : on" in out
    assert "!! stale" not in out


def test_a_saved_setting_that_was_never_applied_is_called_stale(
    quiet_store, no_processes, monkeypatch, tmp_path, capsys
):
    """The saved value and the value the GUI actually loads are different facts.
    Reporting only the first makes a config that was never applied look healthy."""
    quiet_store["weztermMux"] = "on"
    cfg = tmp_path / ".wezterm.lua"
    cfg.write_text("local MUX_ENABLED = 'off' == 'on'\n", encoding="utf-8")
    monkeypatch.setattr(mux, "rendered_cfg", lambda: cfg)
    mux.main(["status"])
    out = capsys.readouterr().out
    assert "!! stale" in out
    assert "chezmoi apply" in out


def test_a_config_from_before_the_toggle_is_read_as_unconditional(monkeypatch, tmp_path):
    cfg = tmp_path / ".wezterm.lua"
    cfg.write_text("config.default_domain = 'main'\n", encoding="utf-8")
    monkeypatch.setattr(mux, "rendered_cfg", lambda: cfg)
    assert mux.rendered_mux() == "on (pre-toggle)"

    cfg.write_text("config.font_size = 12\n", encoding="utf-8")
    assert mux.rendered_mux() == "off (pre-toggle)"


def test_a_missing_config_is_reported_rather_than_guessed(
    quiet_store, no_processes, monkeypatch, capsys
):
    monkeypatch.setattr(mux, "rendered_cfg", lambda: None)
    mux.main(["status"])
    assert "no .wezterm.lua found" in capsys.readouterr().out


def test_status_says_when_panes_outlive_a_setting_turned_off(quiet_store, monkeypatch, capsys):
    quiet_store["weztermMux"] = "off"
    monkeypatch.setattr(mux, "mux_pids", lambda: ["4242"])
    monkeypatch.setattr(mux, "wez_cli", lambda: None)
    monkeypatch.setattr(mux, "rendered_cfg", lambda: None)
    mux.main(["status"])
    out = capsys.readouterr().out
    assert "running (pid 4242)" in out
    assert "still hosted by it" in out


def test_kill_asks_before_taking_every_pane_with_it(monkeypatch, capsys):
    monkeypatch.setattr(mux, "mux_pids", lambda: ["7"])
    asked = []
    monkeypatch.setattr(mux, "_confirm", lambda prompt, yes: asked.append(prompt) or False)
    assert mux.main(["kill"]) == 1
    assert asked and "Every pane it hosts dies" in asked[0]


def test_yes_skips_the_confirmation():
    assert mux._confirm("really?", assume_yes=True) is True


def test_kill_on_a_stopped_server_is_a_no_op(monkeypatch, capsys):
    monkeypatch.setattr(mux, "mux_pids", lambda: [])
    assert mux.main(["kill"]) == 0
    assert "not running" in capsys.readouterr().out


def test_restart_does_not_start_anything_if_the_kill_was_refused(monkeypatch):
    """Never auto-restart the mux server: it kills every live pane. A refused
    confirmation must stop the whole verb, not just its first half."""
    started = []
    monkeypatch.setattr(mux, "mux_pids", lambda: ["7"])
    monkeypatch.setattr(mux, "_confirm", lambda prompt, yes: False)
    monkeypatch.setattr(mux, "do_start", lambda: started.append(1) or 0)
    assert mux.main(["restart"]) == 1
    assert started == []


def test_setting_the_mux_writes_the_setting_and_re_applies(monkeypatch, quiet_store, capsys):
    written = {}
    applied = []
    monkeypatch.setattr(store, "set", lambda key, value: written.setdefault(key, value))
    monkeypatch.setattr(store, "chezmoi_init", lambda: True)
    monkeypatch.setattr(mux, "_apply", lambda: applied.append(1))
    assert mux.set_mux("on") == 0
    assert written == {"weztermMux": "on"}
    assert applied == [1], "the setting alone changes nothing until chezmoi re-renders"
    assert "mux domain 'main'" in capsys.readouterr().out


def test_setting_it_to_what_it_already_is_still_re_renders(monkeypatch, quiet_store, capsys):
    quiet_store["weztermMux"] = "off"
    monkeypatch.setattr(store, "set", lambda key, value: None)
    monkeypatch.setattr(store, "chezmoi_init", lambda: True)
    monkeypatch.setattr(mux, "_apply", lambda: None)
    mux.set_mux("off")
    assert "already off; re-applying anyway" in capsys.readouterr().out


def test_reset_goes_back_to_the_default_and_clears_sockets(monkeypatch, capsys):
    done = []
    monkeypatch.setattr(mux, "_confirm", lambda prompt, yes: True)
    monkeypatch.setattr(store, "set", lambda key, value: done.append((key, value)))
    monkeypatch.setattr(store, "chezmoi_init", lambda: True)
    monkeypatch.setattr(mux, "_apply", lambda: done.append("apply"))
    monkeypatch.setattr(mux, "do_kill", lambda assume_yes: done.append("kill") or 0)
    monkeypatch.setattr(mux, "clear_sockets", lambda: done.append("sockets") or 0)
    assert mux.main(["reset", "-y"]) == 0
    assert done == [("weztermMux", "off"), "apply", "kill", "sockets"]


def test_clear_sockets_removes_only_socket_files(tmp_path, monkeypatch, capsys):
    keep = tmp_path / "wezterm" / "keep.log"
    keep.parent.mkdir(parents=True)
    keep.write_text("x", encoding="utf-8")
    (keep.parent / "sock").write_text("x", encoding="utf-8")
    (keep.parent / "gui-sock-1").write_text("x", encoding="utf-8")
    monkeypatch.setattr(mux, "sock_dirs", lambda: [keep.parent, tmp_path / "nope"])
    mux.clear_sockets()
    assert "cleared 2 stale socket file(s)" in capsys.readouterr().out
    assert keep.exists(), "a non-socket file was removed"


def test_list_without_a_wezterm_cli_says_so(monkeypatch, capsys):
    monkeypatch.setattr(mux, "wez_cli", lambda: None)
    assert mux.main(["list"]) == 1
    assert "wezterm CLI not found" in capsys.readouterr().err


def test_on_wsl_the_binaries_and_the_config_are_the_windows_ones(monkeypatch):
    """A pgrep inside WSL finds nothing while a healthy server runs on the same
    machine, because the mux server is a Windows process."""
    monkeypatch.setattr(plat, "kind", lambda: plat.WSL)
    monkeypatch.setattr(
        mux.shutil, "which", lambda name: f"/usr/bin/{name}" if ".exe" in name else None
    )
    assert mux.wez_cli().endswith("wezterm.exe")
    assert mux.mux_bin().endswith("wezterm-mux-server.exe")

    monkeypatch.setattr(plat, "windows_username", lambda: "someone")
    dirs = [d.as_posix() for d in mux.sock_dirs()]
    assert any("/mnt/c/Users/someone/AppData/Local/wezterm" in d for d in dirs)


def test_the_windows_pid_probe_ignores_a_localized_no_tasks_line(monkeypatch):
    """CSV output on purpose: a localized "INFO: No tasks are running" line must
    not be mistaken for a row."""
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)

    class Got:
        returncode = 0
        stdout = "INFO: No tasks are running which match the specified criteria.\r\n"

    monkeypatch.setattr(mux, "_run", lambda argv, timeout=30: Got())
    assert mux.mux_pids() == []

    Got.stdout = '"wezterm-mux-server.exe","1234","Console","1","70,000 K"\r\n'
    assert mux.mux_pids() == ["1234"]


def test_on_a_native_host_the_plain_binaries_are_used(monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    monkeypatch.setattr(mux.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert mux.wez_cli() == "/usr/bin/wezterm"
    assert mux.mux_bin() == "/usr/bin/wezterm-mux-server"
    monkeypatch.setattr(mux.shutil, "which", lambda name: None)
    assert mux.wez_cli() is None
    assert mux.mux_bin() is None


def test_a_missing_binary_is_none_rather_than_an_exception(monkeypatch):
    """_run swallows OSError on purpose: probing for a tool that is not there is
    the normal case, not an error to propagate."""
    monkeypatch.setattr(
        mux.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError("nope"))
    )
    assert mux._run(["no-such-binary"]) is None


def test_the_posix_pid_probe_reads_pgrep(monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)

    class Got:
        returncode = 0
        stdout = "111\n222\n"

    monkeypatch.setattr(mux, "_run", lambda argv, timeout=30: Got())
    assert mux.mux_pids() == ["111", "222"]

    Got.returncode = 1
    assert mux.mux_pids() == []


def test_start_reports_a_missing_server_binary(monkeypatch, capsys):
    monkeypatch.setattr(mux, "mux_pids", lambda: [])
    monkeypatch.setattr(mux, "mux_bin", lambda: None)
    assert mux.do_start() == 1
    assert "relaunch WezTerm" in capsys.readouterr().err


def test_start_is_a_no_op_when_one_is_already_running(monkeypatch, capsys):
    monkeypatch.setattr(mux, "mux_pids", lambda: ["9"])
    assert mux.do_start() == 0
    assert "already running" in capsys.readouterr().out


def test_start_daemonizes(monkeypatch, capsys):
    ran = []

    class Got:
        returncode = 0

    monkeypatch.setattr(mux, "mux_pids", lambda: [])
    monkeypatch.setattr(mux, "mux_bin", lambda: "/usr/bin/wezterm-mux-server")
    monkeypatch.setattr(mux, "_run", lambda argv, timeout=30: ran.append(argv) or Got())
    assert mux.do_start() == 0
    assert ran == [["/usr/bin/wezterm-mux-server", "--daemonize"]]


def test_a_failed_start_is_reported(monkeypatch, capsys):
    class Got:
        returncode = 1

    monkeypatch.setattr(mux, "mux_pids", lambda: [])
    monkeypatch.setattr(mux, "mux_bin", lambda: "/usr/bin/wezterm-mux-server")
    monkeypatch.setattr(mux, "_run", lambda argv, timeout=30: Got())
    assert mux.do_start() == 1
    assert "start failed" in capsys.readouterr().err


def test_status_counts_the_panes_the_mux_knows_about(quiet_store, monkeypatch, capsys):
    class Got:
        returncode = 0
        stdout = "WINID TABID PANEID\n0 1 2\n0 1 3\n"

    monkeypatch.setattr(mux, "mux_pids", lambda: [])
    monkeypatch.setattr(mux, "wez_cli", lambda: "/usr/bin/wezterm")
    monkeypatch.setattr(mux, "_run", lambda argv, timeout=30: Got())
    monkeypatch.setattr(mux, "rendered_cfg", lambda: None)
    mux.main(["status"])
    assert "panes    : 2" in capsys.readouterr().out


def test_turning_it_on_without_a_clone_fails_rather_than_half_writing(monkeypatch, capsys):
    from tstack import paths

    def missing(**kwargs):
        raise paths.CloneNotFound("no clone here")

    monkeypatch.setattr(paths, "resolve_source_dir", missing)
    written = []
    monkeypatch.setattr(store, "set", lambda key, value: written.append(key))
    assert mux.main(["on"]) == 1
    assert written == [], "the setting was written with no clone to apply it from"
    assert "no clone here" in capsys.readouterr().err


def test_apply_without_chezmoi_says_so_rather_than_pretending(monkeypatch, capsys):
    monkeypatch.setattr(plat, "find_chezmoi", lambda: None)
    mux._apply()
    out = capsys.readouterr().out
    assert "applying" in out
    assert "no chezmoi here" in out


def test_an_unreadable_rendered_config_is_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(mux, "rendered_cfg", lambda: tmp_path / "gone.lua")
    assert mux.rendered_mux() is None
