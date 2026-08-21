"""System-tray UI (pystray). Menu changes persist to ~/.claude/tts/local.json
and hot-apply via Config.reload().

The mute is the exception: it lives in `mute.py`'s sentinel file rather than in config,
because a hook running in another process has to see it and it has to survive this
process dying. `Muted` is the menu default, so a plain left-click on the icon toggles it
without opening the menu at all -- the fastest path to silence when a call starts.
"""

from __future__ import annotations

import logging
import os

from . import mute

log = logging.getLogger(__name__)

_MUSIC_MODES = ("duck", "smart", "pause", "off")
_SUMMARIZER_MODES = ("template", "self", "haiku", "ollama")


def state_for(enabled: bool, muted: bool) -> tuple[bool, bool]:
    """(muted, disabled) for the icon. Disabled outranks muted.

    Module level and pure so it can be tested without pystray or PIL, which are imported
    inside build_icon and are not present outside the frozen build.
    """
    return (False, True) if not enabled else (muted, False)


def title_for(muted: bool, disabled: bool) -> str:
    if disabled:
        return "terminal-stack TTS: disabled (no hooks installed)"
    return "terminal-stack TTS — MUTED" if muted else "terminal-stack TTS"


def build_icon(app, log_path, on_quit):
    import pystray
    from PIL import Image, ImageDraw

    def _image(muted: bool = False, disabled: bool = False) -> Image.Image:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        # Three distinguishable states, because "the daemon is running" and "speech works"
        # are different claims and conflating them cost an afternoon: a healthy icon sat
        # there while the feature was switched off and no hooks existed.
        #   on       solid peach ring
        #   muted    grey ring with a slash: deliberately silenced, still armed
        #   disabled hollow outline, no slash: present but inert
        if disabled:
            draw.ellipse((8, 8, 56, 56), outline=(108, 112, 134, 255), width=5)
            return img
        body = (108, 112, 134, 255) if muted else (214, 138, 89, 255)  # overlay0 / peach
        draw.ellipse((8, 8, 56, 56), fill=body)
        draw.ellipse((24, 24, 40, 40), fill=(30, 30, 46, 255))
        if muted:
            draw.line((14, 50, 50, 14), fill=(243, 139, 168, 255), width=7)  # red slash
        return img

    def _tray_state() -> tuple[bool, bool]:
        return state_for(bool(app.cfg.get("enabled", False)), mute.is_muted())

    def _refresh(icon) -> None:
        muted, disabled = _tray_state()
        try:
            icon.icon = _image(muted, disabled)
            icon.title = title_for(muted, disabled)
        except Exception as exc:  # noqa: BLE001 — chrome; never take the daemon down
            log.debug("tray refresh failed: %s", exc)

    def _music_setter(mode: str):
        def _set(icon, item) -> None:
            app.cfg.write_local("music.mode", mode)
        return _set

    def _music_checked(mode: str):
        return lambda item: str(app.cfg.get("music.mode", "duck")) == mode

    def _summarizer_setter(mode: str):
        def _set(icon, item) -> None:
            app.cfg.write_local("summarize.mode", mode)
        return _set

    def _summarizer_checked(mode: str):
        return lambda item: str(app.cfg.get("summarize.mode", "template")) == mode

    def _toggle_mute(icon, item) -> None:
        if mute.is_muted():
            mute.unmute()
        else:
            mute.mute(by="tray")
            # Silence means now, not after this sentence.
            app.dispatcher.playback.stop()
        _refresh(icon)

    def _test_speak(icon, item) -> None:
        import threading

        def _go() -> None:
            result = app.synth.synthesize("Terminal stack voice check.", "")
            if result and result.media is not None:
                app.audio.hold(None)
                try:
                    if not app.dispatcher.playback.play(result.media):
                        app.dispatcher.playback.speak_sapi("Terminal stack voice check.")
                finally:
                    app.audio.release()
            elif result:
                app.dispatcher.playback.speak_sapi(result.sapi_text)

        threading.Thread(target=_go, daemon=True).start()

    def _unduck(icon, item) -> None:
        app.audio.force_restore()

    def _reload(icon, item) -> None:
        app.cfg.reload()
        _refresh(icon)  # `enabled` may have changed, which changes the icon

    def _open_log(icon, item) -> None:
        try:
            os.startfile(log_path)  # noqa: S606 — user-invoked, fixed path
        except OSError as exc:
            log.warning("open log failed: %s", exc)

    menu = pystray.Menu(
        # `default=True` makes a left-click on the icon run this without opening the menu.
        pystray.MenuItem("Muted", _toggle_mute, default=True,
                         checked=lambda item: mute.is_muted()),
        pystray.MenuItem("Music", pystray.Menu(*[
            pystray.MenuItem(mode.title(), _music_setter(mode),
                             checked=_music_checked(mode), radio=True)
            for mode in _MUSIC_MODES
        ])),
        pystray.MenuItem("Summarizer", pystray.Menu(*[
            pystray.MenuItem(mode.title(), _summarizer_setter(mode),
                             checked=_summarizer_checked(mode), radio=True)
            for mode in _SUMMARIZER_MODES
        ])),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Test speak", _test_speak),
        pystray.MenuItem("Unduck now", _unduck),
        pystray.MenuItem("Reload config", _reload),
        pystray.MenuItem("Open log", _open_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", lambda icon, item: on_quit(icon)),
    )
    muted_now, disabled_now = _tray_state()
    icon = pystray.Icon(
        "terminal-stack-ttsd", _image(muted_now, disabled_now),
        title_for(muted_now, disabled_now), menu)
    # The hotkey toggles the same sentinel from another thread; this lets it repaint the
    # icon, so the two surfaces never disagree about what the tray is showing.
    icon.ts_refresh = lambda: _refresh(icon)
    return icon
