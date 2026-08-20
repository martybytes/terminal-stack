"""ttsd — terminal-stack TTS notification daemon (Windows tray).

Receives Claude Code / Cursor hook events over localhost HTTP, queues and
coalesces them, ducks or pauses music, and speaks a session-identifying
announcement through the stack's TTS engines (Kokoro / Chatterbox /
edge-tts / SAPI).

Hooks fall back to the classic direct-speak path (cc-tts-notify) whenever
this daemon is unreachable — the daemon is an upgrade, never a dependency.
"""

PROTOCOL_VERSION = 1
