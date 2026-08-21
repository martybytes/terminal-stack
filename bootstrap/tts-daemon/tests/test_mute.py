"""The absolute mute: sentinel semantics, every enforcement point, and barge-in.

No audio, no COM, no daemon. `LOCALAPPDATA` is redirected so the real state directory is
never touched, and the modules' cached fail-open latches are reloaded between cases.
"""

import importlib
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ttsd import history, hotkey, mute
from ttsd.events import Event


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    importlib.reload(mute)
    importlib.reload(history)
    return tmp_path


def ev(key="claude:s1", state="question", source="claude", project="alpha"):
    return Event(source=source, event=state, state=state,
                 session_key=key, project_name=project)


# ── the sentinel ──────────────────────────────────────────────────────────────

def test_mute_unmute_round_trip(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert mute.is_muted() is False
    assert mute.mute(by="tray") is True
    assert mute.is_muted() is True
    assert mute.state()["by"] == "tray"
    assert mute.unmute() is True
    assert mute.is_muted() is False


def test_mute_survives_a_process_restart(tmp_path, monkeypatch):
    """The whole point of a file: the old DND was a float that died with the daemon."""
    _isolate(tmp_path, monkeypatch)
    mute.mute(by="hotkey")
    importlib.reload(mute)  # stands in for a fresh process
    assert mute.is_muted() is True


def test_toggle_reports_the_resulting_state(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert mute.toggle() is True
    assert mute.toggle() is False


def test_a_corrupt_sentinel_still_means_muted(tmp_path, monkeypatch):
    """Existence is the signal; the JSON body is only metadata."""
    _isolate(tmp_path, monkeypatch)
    mute.mute()
    mute.mute_path().write_text("not json at all", encoding="utf-8")
    assert mute.is_muted() is True
    assert mute.state() == {"since": None, "by": ""}
    assert "MUTED" in mute.describe()


def test_an_unusable_state_dir_reads_as_not_muted(tmp_path, monkeypatch):
    """Fails open toward speech: a mute you cannot lift is worse than one that fails."""
    blocker = tmp_path / "blocked"
    blocker.write_text("a file where the state directory should be", encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(blocker))
    importlib.reload(mute)
    assert mute.is_muted() is False
    assert mute.mute() is False, "reports the failure rather than pretending"
    assert mute.is_muted() is False, "and speech is still allowed through"


def test_the_written_sentinel_is_valid_json_metadata(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    mute.mute(by="api")
    body = json.loads(mute.mute_path().read_text(encoding="utf-8"))
    assert body["by"] == "api" and body["since"] > 0


# ── enforcement: the dispatcher ───────────────────────────────────────────────

class _Cfg:
    def __init__(self, **over):
        self.values = {"events": ["waiting", "error", "question", "permission"],
                       "debounceSec": 5, "quietHours.allowInteractive": True}
        self.values.update(over)

    def get(self, dotted, default=None):
        return self.values.get(dotted, default)


def _dispatcher(cfg):
    from ttsd.pipeline import Dispatcher
    return Dispatcher(cfg, scheduler=None, registry=None, summarizer=None,
                      synth=None, playback=None, audio=None, wez=None)


def test_muted_silences_questions_and_errors(tmp_path, monkeypatch):
    """The exact case the old DND let through.

    `Do not disturb` routed through `quietHours.allowInteractive` (default true), so it
    muted 'done' announcements and spoke every question, permission prompt and error --
    backwards for someone who just answered a call.
    """
    _isolate(tmp_path, monkeypatch)
    import ttsd.pipeline as pipeline
    importlib.reload(pipeline)
    disp = _dispatcher(_Cfg())

    assert disp._suppress(ev(state="question")) is False, "not muted yet"
    mute.mute(by="tray")
    for state in ("question", "permission", "error", "waiting"):
        assert disp._suppress(ev(state=state)) is True, f"{state} must be silenced"

    decisions = [r["decision"] for r in history.recent(10)]
    assert decisions.count(history.MUTED) == 4


def test_unmuting_restores_speech(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    import ttsd.pipeline as pipeline
    importlib.reload(pipeline)
    disp = _dispatcher(_Cfg())
    mute.mute()
    assert disp._suppress(ev()) is True
    mute.unmute()
    assert disp._suppress(ev(key="claude:fresh")) is False


def test_dnd_active_now_reports_the_sentinel(tmp_path, monkeypatch):
    """/healthz and /v1/status keep their field; it just means something durable now."""
    _isolate(tmp_path, monkeypatch)
    import ttsd.pipeline as pipeline
    importlib.reload(pipeline)
    disp = _dispatcher(_Cfg())
    assert disp.dnd_active() is False
    mute.mute()
    assert disp.dnd_active() is True


# ── enforcement: the hook process ─────────────────────────────────────────────

def test_submit_hook_is_silent_and_leaves_a_row(tmp_path, monkeypatch):
    """The earliest gate: before the daemon POST, before any worker is spawned."""
    _isolate(tmp_path, monkeypatch)
    import ttsd.hooks as hooks
    importlib.reload(hooks)

    class _Enabled:
        def get(self, dotted, default=None):
            return True if dotted == "enabled" else default

    monkeypatch.setattr(hooks, "Config", _Enabled)
    monkeypatch.setattr(hooks, "_post", lambda *a, **k: pytest_fail())
    monkeypatch.setattr(hooks, "_spawn_direct", lambda *a, **k: pytest_fail())

    def pytest_fail():
        raise AssertionError("a muted hook must not reach the daemon or a worker")

    mute.mute(by="cli")
    raw = json.dumps({"session_id": "s1", "cwd": "C:/work/alpha",
                      "last_assistant_message": "done"}).encode("utf-8")
    assert hooks.submit_hook("claude", "stop", "waiting", raw) == 0
    assert any(r["decision"] == history.MUTED for r in history.recent(5))


def test_direct_speak_is_silent_when_muted(tmp_path, monkeypatch):
    """The detached worker is a separate process; it may start after the mute lands."""
    _isolate(tmp_path, monkeypatch)
    import ttsd.hooks as hooks
    importlib.reload(hooks)

    class _Enabled:
        def get(self, dotted, default=None):
            return True if dotted == "enabled" else default

    monkeypatch.setattr(hooks, "Config", _Enabled)
    monkeypatch.setattr(hooks, "Synth", lambda cfg: (_ for _ in ()).throw(
        AssertionError("a muted worker must not synthesize")))
    mute.mute()
    assert hooks.direct_speak({"v": 1, "source": "claude", "state": "question",
                               "session_key": "claude:s1"}) == 0


# ── barge-in ──────────────────────────────────────────────────────────────────

class _FakePlayer:
    def __init__(self):
        self.paused = False

    def pause(self):
        self.paused = True


def test_stop_cuts_off_the_utterance_in_flight():
    from ttsd.playback import Playback

    pb = Playback()
    player, ended = _FakePlayer(), threading.Event()
    pb._active = (player, ended)

    assert pb.stop() is True
    assert player.paused is True, "the player was asked to stop"
    assert ended.is_set(), "and play()'s wait was released so its finally can close it"


def test_stop_is_harmless_with_nothing_playing():
    from ttsd.playback import Playback

    assert Playback().stop() is False


def test_stop_survives_a_player_that_throws():
    """Cross-thread COM can fail; the sentence finishing is the acceptable fallback."""
    from ttsd.playback import Playback

    class _Angry:
        def pause(self):
            raise RuntimeError("RPC_E_WRONG_THREAD")

    pb = Playback()
    ended = threading.Event()
    pb._active = (_Angry(), ended)
    assert pb.stop() is True
    assert ended.is_set(), "the waiter is still released"


# ── the hotkey spec parser (pure logic; no Windows needed) ────────────────────

def test_hotkey_parses_a_chord():
    parsed = hotkey.parse("ctrl+alt+shift+m")
    assert parsed is not None
    mods, vk = parsed
    assert vk == ord("M")
    assert mods & 0x0002 and mods & 0x0001 and mods & 0x0004  # ctrl, alt, shift
    assert mods & 0x4000, "MOD_NOREPEAT, so holding the chord fires once"


def test_hotkey_accepts_named_keys_and_is_case_insensitive():
    assert hotkey.parse("CTRL+F9")[1] == 0x78
    assert hotkey.parse("win+space")[1] == 0x20


def test_hotkey_rejects_specs_that_would_hijack_the_keyboard():
    assert hotkey.parse("m") is None, "a bare key would be captured system-wide"
    assert hotkey.parse("") is None
    assert hotkey.parse("ctrl+shift") is None, "modifiers with no key"
    assert hotkey.parse("ctrl+nosuchkey") is None
    assert hotkey.parse("ctrl+a+b") is None, "two keys is a typo, not a chord"


# ── tray state: three distinguishable claims ─────────────────────────────────
#
# "the daemon is running" and "speech works" are different claims, and conflating them is
# what let a healthy tray icon sit above a feature that was switched off with no hooks
# installed. state_for/title_for are module level and pure precisely so this is testable
# without pystray or PIL, neither of which exists outside the frozen build.

def test_tray_state_precedence():
    from ttsd.tray import state_for

    assert state_for(enabled=True, muted=False) == (False, False), "armed"
    assert state_for(enabled=True, muted=True) == (True, False), "silenced but armed"
    # Disabled outranks muted: if it cannot speak at all, the mute is not the story.
    assert state_for(enabled=False, muted=True) == (False, True)
    assert state_for(enabled=False, muted=False) == (False, True)


def test_tray_titles_name_the_actual_problem():
    from ttsd.tray import state_for, title_for

    assert title_for(*state_for(True, False)) == "terminal-stack TTS"
    assert "MUTED" in title_for(*state_for(True, True))
    disabled = title_for(*state_for(False, True))
    assert "disabled" in disabled and "no hooks" in disabled, (
        "the tooltip has to say why it is silent, not just that it is")
