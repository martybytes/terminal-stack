"""System-tray UI (pystray). Menu changes persist to ~/.claude/tts/local.json
and hot-apply via Config.reload()."""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

_MUSIC_MODES = ("duck", "smart", "pause", "off")
_SUMMARIZER_MODES = ("template", "self", "haiku", "ollama")


def build_icon(app, log_path, on_quit):
    import pystray
    from PIL import Image, ImageDraw

    def _image() -> Image.Image:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((8, 8, 56, 56), fill=(214, 138, 89, 255))  # peach — cc_working
        draw.ellipse((24, 24, 40, 40), fill=(30, 30, 46, 255))
        return img

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

    def _toggle_dnd(icon, item) -> None:
        app.dispatcher.set_dnd(not app.dispatcher.dnd_active())

    def _mute_hour(icon, item) -> None:
        app.dispatcher.set_dnd(True, minutes=60)

    def _test_speak(icon, item) -> None:
        import threading

        def _go() -> None:
            result = app.synth.synthesize("Terminal stack voice check.", "")
            if result and result.media is not None:
                app.audio.hold(None)
                try:
                    app.dispatcher.playback.play(result.media)
                finally:
                    app.audio.release()
            elif result:
                app.dispatcher.playback.speak_sapi(result.sapi_text)

        threading.Thread(target=_go, daemon=True).start()

    def _unduck(icon, item) -> None:
        app.audio.force_restore()

    def _reload(icon, item) -> None:
        app.cfg.reload()

    def _open_log(icon, item) -> None:
        try:
            os.startfile(log_path)  # noqa: S606 — user-invoked, fixed path
        except OSError as exc:
            log.warning("open log failed: %s", exc)

    menu = pystray.Menu(
        pystray.MenuItem("Do not disturb", _toggle_dnd,
                         checked=lambda item: app.dispatcher.dnd_active()),
        pystray.MenuItem("Mute for 1 hour", _mute_hour),
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
    return pystray.Icon("terminal-stack-ttsd", _image(), "terminal-stack TTS", menu)
