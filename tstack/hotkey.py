"""Is a key chord already taken by another program's global hotkey? (Windows)

A program that calls RegisterHotKey for a chord gets that chord's key-DOWN
before any window does, system-wide. WezTerm then sees only the key-UP, so a
leader set to that chord never fires, with no error anywhere: the config loads,
`wezterm show-keys` lists the leader, and pressing it does nothing. Found on
2026-11-01 with `ctrl-backslash`, which this stack recommends as the leader
that "clashes with nothing" -- true of every shell and TUI, and of no use when
a tray app has claimed it.

The test is the one Windows offers: try to register the chord ourselves. It
fails with ERROR_HOTKEY_ALREADY_REGISTERED (1409) when someone holds it, and is
released at once when it succeeds. Windows has no API that names the holder.

Deliberately free of package-relative imports so the PowerShell side can run
it as a plain script (`python hotkey.py ctrl-backslash`) -- one implementation
for both the Python wizard/doctor and the pwsh `tstack config` menu.

Exit status of the script form: 0 free, 1 taken, 2 cannot tell (not Windows,
or a chord with no Windows key code).
"""

from __future__ import annotations

import sys

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_MODS = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "opt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "super": MOD_WIN,
    "cmd": MOD_WIN,
}

# Named keys, as the wizard stores them (`ctrl-backslash`, `alt-space`).
# Virtual-key codes for the US layout, which is what `phys:` names in the
# WezTerm config mean too (docs/decisions.md, "the key is spelled by name").
_NAMED_VK = {
    "space": 0x20,
    "backslash": 0xDC,
    "\\": 0xDC,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "escape": 0x1B,
    "esc": 0x1B,
    "backspace": 0x08,
    ";": 0xBA,
    "semicolon": 0xBA,
    "=": 0xBB,
    ",": 0xBC,
    "comma": 0xBC,
    "-": 0xBD,
    "minus": 0xBD,
    ".": 0xBE,
    "period": 0xBE,
    "/": 0xBF,
    "slash": 0xBF,
    "`": 0xC0,
    "grave": 0xC0,
    "[": 0xDB,
    "]": 0xDD,
    "'": 0xDE,
    "quote": 0xDE,
}


def parse(chord: str) -> tuple[int, int] | None:
    """`ctrl-backslash` -> (MOD_CONTROL, VK_OEM_5). None when it cannot be mapped."""
    parts = [p for p in chord.strip().lower().split("-") if p]
    # `ctrl--` would split to ['ctrl']; a trailing dash is the minus key.
    if chord.endswith("--"):
        parts.append("-")
    if len(parts) < 2:
        return None
    mods = 0
    for part in parts[:-1]:
        if part not in _MODS:
            return None
        mods |= _MODS[part]
    key = parts[-1]
    if key in _NAMED_VK:
        vk = _NAMED_VK[key]
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        vk = 0x70 + int(key[1:]) - 1
    else:
        return None
    return mods, vk


def held_elsewhere(chord: str) -> bool | None:
    """True when another program holds `chord` as a global hotkey.

    None when this cannot be known: not Windows, or a chord with no key code.
    A None must never be reported as "free" -- callers say nothing instead.
    """
    if sys.platform != "win32":
        return None
    parsed = parse(chord)
    if parsed is None:
        return None
    mods, vk = parsed
    import ctypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hotkey_id = 0x7A11  # any id; it is ours only for the instant below
    if user32.RegisterHotKey(None, hotkey_id, mods | MOD_NOREPEAT, vk):
        user32.UnregisterHotKey(None, hotkey_id)
        return False
    return ctypes.get_last_error() == ERROR_HOTKEY_ALREADY_REGISTERED


def label(chord: str) -> str:
    """`ctrl-backslash` -> `Ctrl+\\`, for messages."""
    names = {"backslash": "\\", "space": "Space", "ctrl": "Ctrl", "alt": "Alt", "shift": "Shift"}
    return "+".join(
        names.get(p, p.upper() if len(p) == 1 else p.capitalize()) for p in chord.split("-")
    )


def advice(chord: str) -> list[str]:
    """What to tell someone whose leader is taken. One list, every caller."""
    shown = label(chord)
    return [
        f"{shown} is already taken by another program on this PC (a global hotkey).",
        f"Windows hands {shown} to that program first, so WezTerm never sees it:",
        "your leader key will do nothing, even though the config is correct.",
        "",
        "Fix it one of two ways:",
        f"  1. Find the program that uses {shown} and change or turn off its",
        "     shortcut. Usual suspects: PowerToys, launchers (Wox, Flow Launcher,",
        "     Raycast), dictation tools (Wispr Flow), ChatGPT / Grok / other AI",
        "     desktop apps, screenshot tools (Snagit, ShareX), Stream Deck.",
        "     Quitting them one at a time from the tray and re-running",
        "     `tstack doctor` tells you which it is.",
        "  2. Pick a different leader:  tstack config leader ctrl-a",
        "     (any chord works; `tstack doctor` re-checks it for you).",
        "",
        "Once it is free, nothing needs re-applying: press the leader in WezTerm.",
    ]


def one_line_fix() -> str:
    """The same advice, for a one-line report such as `tstack doctor`."""
    return (
        "fix: turn that shortcut off in the program that owns it (PowerToys, Wox, Wispr Flow, "
        "an AI desktop app, Snagit, Stream Deck - quit them one at a time and re-run "
        "`tstack doctor`), or pick another leader: tstack config leader ctrl-a"
    )


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: hotkey.py <chord>   e.g. ctrl-backslash, alt-space, ctrl-a")
        print("exit: 0 free, 1 taken by another program, 2 cannot tell")
        return 0 if argv else 2
    held = held_elsewhere(argv[0])
    if held is None:
        return 2
    if held:
        for line in advice(argv[0]):
            print(line)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
