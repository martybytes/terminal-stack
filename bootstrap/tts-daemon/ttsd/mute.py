"""The absolute mute: one sentinel file that every speech path checks.

Existence is the check. The file's JSON body (`since`, `by`) is metadata for reporting
only, so the hot paths never parse it and WezTerm can decide with a plain `glob`.

Three properties are load-bearing, and the thing this replaces had none of them:

- **Absolute.** No priority exemption. The old tray "Do not disturb" routed through
  `quietHours.allowInteractive` (default true), so it silenced "done" announcements and let
  every question, permission prompt and error through — which is exactly backwards for
  someone who just answered a phone call.
- **Cross-process.** A file, not an attribute, because the hook that speaks when the daemon
  is unreachable is a *different process*. The old DND was one float on the dispatcher, so
  it could not be seen by the path that does most of the talking.
- **Persistent.** It survives a tray Quit, a crash, and a reboot. The old one did not, so a
  mute could lift itself without anyone touching it.

**Failure resolves to "not muted", the opposite of `history.py`'s bias.** A mute you cannot
lift is worse than one that fails audibly: if the state directory is unusable you hear
something and can act, whereas a mute that cannot be cleared is indistinguishable from the
feature being broken. An existence check gives that default for free.

Not to be confused with `enabled` in `~/.claude/tts/config.json`, which turns the feature
off structurally (and removes the hooks on the next apply). This is "be quiet for a while",
and it deliberately touches neither config store — writing those from the wrong shell is
what silently removed all five Claude TTS hooks on 2026-08-21.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from .config import state_dir

log = logging.getLogger(__name__)


def mute_path() -> Path:
    return state_dir() / "muted"


def is_muted() -> bool:
    """True when speech must be suppressed. Never raises; unknown means not muted."""
    try:
        return mute_path().exists()
    except OSError:
        return False


def state() -> dict:
    """`{}` when unmuted, else the sentinel's metadata (possibly empty values)."""
    path = mute_path()
    try:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    # A truncated or hand-made sentinel still means muted -- the metadata is the bonus,
    # never the signal.
    return data if isinstance(data, dict) else {"since": None, "by": ""}


def mute(by: str = "cli") -> bool:
    """Write the sentinel. False if it could not be written (caller should say so)."""
    path = mute_path()
    try:
        state_dir().mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps({"since": time.time(), "by": by}), encoding="utf-8")
        os.replace(tmp, path)  # atomic: no reader sees a half-written sentinel
        log.info("muted (by %s)", by)
        return True
    except OSError as exc:
        log.warning("could not mute: %s", exc)
        return False


def unmute() -> bool:
    """Remove the sentinel. A failure here is the one that matters -- say so loudly."""
    try:
        mute_path().unlink(missing_ok=True)
        log.info("unmuted")
        return True
    except OSError as exc:
        log.error("could not unmute, speech stays suppressed: %s", exc)
        return False


def toggle(by: str = "cli") -> bool:
    """Flip it. Returns the resulting muted state."""
    if is_muted():
        return not unmute()
    return mute(by)


def describe() -> str:
    """One line for humans: `ccmute`, `ts-doctor`, and the tray tooltip share this."""
    if not is_muted():
        return "tts: not muted"
    info = state()
    since = info.get("since")
    by = str(info.get("by") or "")
    when = ""
    if isinstance(since, (int, float)) and since > 0:
        mins = max(0, int((time.time() - since) / 60))
        when = f" since {time.strftime('%H:%M', time.localtime(since))} ({mins}m ago)"
    return f"tts: MUTED{when}{f' by {by}' if by else ''}"
