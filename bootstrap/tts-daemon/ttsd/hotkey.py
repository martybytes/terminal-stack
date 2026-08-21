"""A system-wide hotkey for the mute, so it works while Teams has focus.

`RegisterHotKey` plus a `GetMessageW` loop, in ctypes rather than a library: every
dependency here gets frozen into the EXE, and this needs no more than user32.

Two constraints the shape follows from:

- **`RegisterHotKey` delivers `WM_HOTKEY` to the thread that registered it**, so the
  registration and the message loop have to live on the same thread. Hence one thread that
  does both, rather than registering from the caller.
- **A taken combination is not an error.** Another application may already own the chord;
  we log once and the daemon carries on. The tray, `ccmute` and the sentinel file all still
  work, so losing the hotkey costs a convenience, not the feature.

This only exists while the daemon is running. That is why the hotkey is not the mute
mechanism — `mute.py`'s sentinel is — and why nothing here is load-bearing.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes

log = logging.getLogger(__name__)

_MODS = {
    "alt": 0x0001,
    "ctrl": 0x0002,
    "control": 0x0002,
    "shift": 0x0004,
    "win": 0x0008,
    "super": 0x0008,
}
_MOD_NOREPEAT = 0x4000  # holding the chord down must not fire it repeatedly
_WM_HOTKEY = 0x0312
_HOTKEY_ID = 0xA17E

# Only the keys worth naming; single characters and digits map to their own code.
_NAMED_KEYS = {
    "space": 0x20, "pause": 0x13, "insert": 0x2D, "delete": 0x2E,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "escape": 0x1B, "esc": 0x1B, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    **{f"f{n}": 0x6F + n for n in range(1, 25)},  # VK_F1 = 0x70
}


def parse(spec: str) -> tuple[int, int] | None:
    """`'ctrl+alt+shift+m'` to `(modifiers, virtual_key)`, or None if unusable."""
    parts = [p.strip().lower() for p in str(spec or "").split("+") if p.strip()]
    if not parts:
        return None
    mods, key = 0, None
    for part in parts:
        if part in _MODS:
            mods |= _MODS[part]
        elif key is None:
            key = part
        else:
            log.warning("hotkey %r names more than one key; ignoring it", spec)
            return None
    if key is None:
        return None
    if key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
    elif len(key) == 1 and (key.isalnum()):
        vk = ord(key.upper())
    else:
        log.warning("hotkey %r has an unrecognised key %r", spec, key)
        return None
    if not mods:
        # A bare key would be captured system-wide, which is never what anyone wants.
        log.warning("hotkey %r needs at least one modifier; ignoring it", spec)
        return None
    return mods | _MOD_NOREPEAT, vk


def start(spec: str, on_press) -> threading.Thread | None:
    """Register `spec` and call `on_press()` on each press. None if not registered."""
    parsed = parse(spec)
    if parsed is None:
        return None
    mods, vk = parsed

    def _run() -> None:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
        except OSError as exc:
            log.debug("no user32, hotkey unavailable: %s", exc)
            return
        if not user32.RegisterHotKey(None, _HOTKEY_ID, mods, vk):
            log.warning("mute hotkey %r could not be registered (error %s) — probably "
                        "owned by another app; tray and ccmute still work",
                        spec, ctypes.get_last_error())
            return
        log.info("mute hotkey registered: %s", spec)
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == _WM_HOTKEY:
                    try:
                        on_press()
                    except Exception as exc:  # noqa: BLE001 — one bad press must not end the loop
                        log.exception("mute hotkey handler failed: %s", exc)
        finally:
            try:
                user32.UnregisterHotKey(None, _HOTKEY_ID)
            except OSError:
                pass

    thread = threading.Thread(target=_run, name="ttsd-hotkey", daemon=True)
    thread.start()
    return thread
