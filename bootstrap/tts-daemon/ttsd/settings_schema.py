"""One description of every setting, used by both the validator and the page.

The enums for these settings previously existed only in UI layers: `tray.py`'s tuples,
`_cc_tts.sh`'s case statements, and `_config.ps1`'s switch arms. `Config.write_local`
accepted any dotted path and any JSON value, so nothing checked that `summarize.mode` was
one of four strings or that `music.duckPercent` was a percentage. A settings form needs a
schema, and defining it once here means the page renders from the same list the server
validates against, so the two cannot drift.

Three flags carry information the daemon knows and a user cannot guess:

- `restart` marks a setting captured at `_build` time. `/v1/config/reload` returns `{"ok":
  true}` regardless, so writing one of these and saying nothing would be a lie.
- `scope="shell"` marks a setting the daemon never reads. It is live on the WSL and
  PowerShell hook fallback path, which is what speaks when the daemon is down, so hiding it
  would be wrong; mixing it in with daemon settings would imply it does something here.
- `undefaulted` marks a key that code reads but `DEFAULTS` never mentioned, the inverse of
  the `debounceSec` bug where a default existed and nothing read it.
"""

from __future__ import annotations

# (key, label, kind, options, group, note, flags)
#   kind: bool | int | float | str | enum | csv
#   flags: a set drawn from {"restart", "shell", "undefaulted"}
FIELDS: tuple[dict, ...] = tuple(
    dict(key=key, label=label, kind=kind, options=options, group=group, note=note,
         flags=set(flags))
    for key, label, kind, options, group, note, flags in (
        # ── what it says ───────────────────────────────────────────────────────
        ("summarize.mode", "Summarizer", "enum",
         ("template", "self", "haiku", "ollama"), "Speech",
         "Only applies to 'done' announcements. Questions, permissions and errors are "
         "always the template, and a coalesced multi-session line bypasses every mode.", ()),
        ("summarize.haiku.model", "Haiku model", "enum",
         ("claude-haiku-4-5", "claude-sonnet-5", "claude-opus-5"), "Speech",
         "A validated list on purpose: max_tokens is 60, which interacts badly with models "
         "that think by default.", ()),
        ("summarize.haiku.timeoutSec", "Haiku timeout", "float", None, "Speech",
         "Falls back to the template when it expires.", ()),
        ("summarize.ollama.url", "Ollama URL", "str", None, "Speech", "", ()),
        ("summarize.ollama.model", "Ollama model", "str", None, "Speech", "", ()),
        ("summarize.ollama.timeoutSec", "Ollama timeout", "float", None, "Speech",
         "A stopped Ollama costs this much delay on every 'done' before falling back.", ()),
        ("summarize.emptyMeansSilent", "Empty summary means silence", "bool", None, "Speech",
         "Only honoured for haiku and ollama, not for self or template.", ()),
        ("maxChars", "Max spoken characters", "int", None, "Speech", "", ()),
        ("events", "Speak on", "csv", None, "Speech",
         "waiting, error, question, permission.", ()),
        ("debounceSec", "Duplicate window (s)", "float", None, "Speech",
         "One user event can arrive as several hooks. 0 disables deduplication.", ()),

        # ── how it sounds ─────────────────────────────────────────────────────
        ("engine", "Engine", "enum", ("kokoro", "chatterbox", "auto"), "Voice", "", ()),
        ("excitement", "Excitement", "float", None, "Voice",
         "0 to 1. Drives kokoro speed and chatterbox exaggeration, and overrides "
         "kokoro.speed.", ()),
        ("kokoro.url", "Kokoro URL", "str", None, "Voice", "", ()),
        ("kokoro.voice", "Kokoro voice", "str", None, "Voice", "", ()),
        ("kokoro.format", "Kokoro format", "enum", ("mp3", "wav", "opus"), "Voice", "", ()),
        ("kokoro.timeoutSec", "Kokoro timeout", "float", None, "Voice", "", ()),
        ("chatterbox.url", "Chatterbox URL", "str", None, "Voice", "", ()),
        ("chatterbox.voice", "Chatterbox voice", "str", None, "Voice", "", ()),
        ("chatterbox.timeoutSec", "Chatterbox timeout", "float", None, "Voice", "", ()),
        ("edge.enabled", "edge-tts fallback", "bool", None, "Voice",
         "Used when the chosen engine is unreachable.", ()),
        ("edge.voice", "edge-tts voice", "str", None, "Voice", "", ()),

        # ── wording ───────────────────────────────────────────────────────────
        ("announce.templates.waiting", "Template: done", "str", None, "Wording",
         "{project} is substituted.", ()),
        ("announce.templates.error", "Template: error", "str", None, "Wording", "", ()),
        ("announce.templates.question", "Template: question", "str", None, "Wording", "", ()),
        ("announce.templates.permission", "Template: permission", "str", None, "Wording",
         "Only Cursor still sends this state; the Claude hook was removed.", ()),
        ("sources.claude.prefix", "Claude prefix", "str", None, "Wording", "", ()),
        ("sources.claude.prefixEnabled", "Say the Claude prefix", "bool", None, "Wording",
         "", ()),
        ("sources.cursor.prefix", "Cursor prefix", "str", None, "Wording", "", ()),
        ("sources.cursor.prefixEnabled", "Say the Cursor prefix", "bool", None, "Wording",
         "", ()),
        ("sources.codex.prefix", "Codex prefix", "str", None, "Wording", "", ()),
        ("sources.codex.prefixEnabled", "Say the Codex prefix", "bool", None, "Wording",
         "", ()),

        # ── music and quiet ───────────────────────────────────────────────────
        ("music.mode", "Music while speaking", "enum",
         ("duck", "smart", "pause", "off"), "Music", "", ()),
        ("music.duckPercent", "Duck to (%)", "int", None, "Music", "", ()),
        ("music.smartThresholdSec", "Smart threshold (s)", "float", None, "Music", "", ()),
        ("music.maxDuckSec", "Duck watchdog (s)", "float", None, "Music",
         "Restores the volume if a speak never finishes.", ()),
        ("quietHours.enabled", "Quiet hours", "bool", None, "Quiet hours", "", ()),
        ("quietHours.start", "Quiet from", "str", None, "Quiet hours", "HH:MM.", ()),
        ("quietHours.end", "Quiet until", "str", None, "Quiet hours", "HH:MM.", ()),
        ("quietHours.allowInteractive", "Let questions through quiet hours", "bool", None,
         "Quiet hours",
         "Applies to quiet hours only. The mute is absolute and ignores this.", ()),

        # ── behaviour of the daemon itself ────────────────────────────────────
        ("daemon.suppressFocused", "Skip 'done' for the focused pane", "bool", None,
         "Daemon", "", ()),
        ("daemon.postTimeoutMs", "Hook post timeout (ms)", "float", None, "Daemon",
         "How long a hook waits for the daemon before taking the direct path.", ()),
        ("daemon.idleRestoreSec", "Idle before unducking (s)", "float", None, "Daemon",
         "", ()),
        ("history.days", "Keep history for (days)", "float", None, "Daemon",
         "Read by the code but absent from the shipped defaults.", ("undefaulted",)),
        ("daemon.startWaitSec", "Wait for a started daemon (s)", "float", None, "Daemon",
         "", ("undefaulted",)),
        ("lock.waitSec", "Play lock wait (s)", "float", None, "Daemon",
         "The direct path waits this long, then speaks anyway rather than dropping audio.",
         ("undefaulted",)),
        ("lock.staleSec", "Play lock stale after (s)", "float", None, "Daemon", "",
         ("undefaulted",)),

        # ── captured at startup ───────────────────────────────────────────────
        ("hotkey", "Global mute hotkey", "str", None, "Needs a restart",
         "Empty disables it.", ("restart",)),
        ("daemon.port", "Port", "int", None, "Needs a restart", "", ("restart",)),
        ("voices.pool", "Voice pool", "csv", None, "Needs a restart", "", ("restart",)),
        ("voices.perSession", "A voice per session", "bool", None, "Needs a restart", "",
         ("restart",)),
        ("daemon.sessionTtlMin", "Session memory (min)", "float", None, "Needs a restart",
         "", ("restart",)),
        ("daemon.coalesceSec", "Coalesce window (s)", "float", None, "Needs a restart",
         "How long near-simultaneous 'done's wait to be merged into one line.",
         ("restart",)),
        ("daemon.coalesceCapSec", "Coalesce cap (s)", "float", None, "Needs a restart", "",
         ("restart",)),
        ("daemon.doneMaxAgeSec", "Drop 'done' older than (s)", "float", None,
         "Needs a restart", "", ("restart",)),
        ("daemon.interactiveMaxAgeSec", "Drop questions older than (s)", "float", None,
         "Needs a restart", "", ("restart",)),
        ("daemon.maxQueue", "Queue limit", "int", None, "Needs a restart", "", ("restart",)),
        ("daemon.cursor.holdSec", "Cursor hold (s)", "float", None, "Needs a restart", "",
         ("restart",)),
        ("daemon.cursor.cooldownSec", "Cursor cooldown (s)", "float", None,
         "Needs a restart", "", ("restart",)),

        # ── read only by the shell fallback ──────────────────────────────────
        ("announce.includeProject", "Say the project name", "bool", None,
         "Shell fallback only", "", ("shell",)),
        ("announce.messageMode", "Message mode", "enum", ("template", "hook"),
         "Shell fallback only", "", ("shell",)),
        ("player", "Player", "enum", ("auto", "windows", "ffplay"),
         "Shell fallback only", "", ("shell",)),
        ("daemon.hostOverride", "Daemon host override", "str", None,
         "Shell fallback only", "Used by WSL and Codex hooks to reach a non-default host.",
         ("shell",)),
    )
)

BY_KEY = {field["key"]: field for field in FIELDS}
GROUPS = tuple(dict.fromkeys(field["group"] for field in FIELDS))

# Ranges worth enforcing, since a form makes a typo cheap and the consequences silent.
_RANGES = {
    "excitement": (0.0, 1.0),
    "music.duckPercent": (0, 100),
    "maxChars": (20, 400),
    "debounceSec": (0.0, 120.0),
    "daemon.port": (1024, 65535),
    "daemon.maxQueue": (1, 200),
}

_EVENT_STATES = ("waiting", "error", "question", "permission")


def coerce(key: str, value):
    """Return the value in the shape the daemon expects, or raise ValueError."""
    field = BY_KEY.get(key)
    if field is None:
        raise ValueError("unknown setting")
    kind = field["kind"]

    if kind == "bool":
        if isinstance(value, bool):
            return value
        if str(value).strip().lower() in ("true", "1", "yes", "on"):
            return True
        if str(value).strip().lower() in ("false", "0", "no", "off", ""):
            return False
        raise ValueError("expected true or false")

    if kind in ("int", "float"):
        try:
            number = int(value) if kind == "int" else float(value)
        except (TypeError, ValueError):
            raise ValueError(f"expected a {kind}") from None
        low, high = _RANGES.get(key, (None, None))
        if low is not None and not (low <= number <= high):
            raise ValueError(f"expected {low} to {high}")
        return number

    if kind == "enum":
        text = str(value).strip()
        if text not in (field["options"] or ()):
            raise ValueError("expected one of " + ", ".join(field["options"] or ()))
        return text

    if kind == "csv":
        if isinstance(value, list):
            items = [str(v).strip() for v in value]
        else:
            items = [part.strip() for part in str(value).split(",")]
        items = [item for item in items if item]
        if key == "events":
            unknown = [item for item in items if item not in _EVENT_STATES]
            if unknown:
                raise ValueError("unknown event(s): " + ", ".join(unknown))
        return items

    text = str(value)
    if key in ("quietHours.start", "quietHours.end"):
        parts = text.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ValueError("expected HH:MM")
        if not (0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59):
            raise ValueError("expected a real time")
    if len(text) > 2000:
        raise ValueError("too long")
    return text


def validate(updates: dict) -> tuple[dict, dict]:
    """Split a submitted map into (clean, errors keyed by setting)."""
    clean: dict = {}
    errors: dict = {}
    for key, value in (updates or {}).items():
        try:
            clean[key] = coerce(key, value)
        except ValueError as exc:
            errors[key] = str(exc)
    return clean, errors


def public_schema() -> list[dict]:
    """The field list as the page needs it: JSON-safe, flags as a sorted list."""
    return [
        {
            "key": f["key"], "label": f["label"], "kind": f["kind"],
            "options": list(f["options"] or ()), "group": f["group"],
            "note": f["note"], "flags": sorted(f["flags"]),
            "range": list(_RANGES.get(f["key"], ())),
        }
        for f in FIELDS
    ]
