"""What is actually running here, so a question can default from fact.

The wizard used to offer Headroom and AgentMemory as blind on/off questions and
happily wire a machine to a service that was not running. The failure showed up
much later as an agent that silently retrieved nothing, because every vendor hook
does `fetch(...).catch(() => {})` then `exit(0)` -- so there was nothing in any
log to connect it back.

These probe first, and their REPORT is shown in the question. A default with no
evidence behind it is a default people override at random.

"ANSWERING" IS THE TEST, NEVER A 2xx. AgentMemory returns 404 on `/` and 401 on
`/agentmemory/health`; both prove a server is listening and speaking HTTP.
`curl -fsS` treats either as failure, which is why `tstack agents agentmemory
status` once reported the service down while it was up and serving.

Every probe returns LINES rather than printing them. The caller decides where
output goes -- and in this program that is the terminal, never stdout.
"""

from __future__ import annotations

import shutil
import urllib.error
import urllib.request

from .. import platform as plat

AGENTMEMORY_URL = "http://127.0.0.1:3111"
HEADROOM_URL = "http://127.0.0.1:8787"
KOKORO_URL = "http://127.0.0.1:8880"


def answers(url: str, timeout: float = 2.0) -> bool:
    """Any HTTP response means something is listening. Not a 2xx check."""
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def agentmemory() -> tuple[bool, str]:
    up = answers(f"{AGENTMEMORY_URL}/")
    if up:
        return (True, f"  AgentMemory: answering at {AGENTMEMORY_URL}")
    return (
        False,
        f"  AgentMemory: not reachable at {AGENTMEMORY_URL} (tstack services up agentmemory)",
    )


def headroom() -> tuple[bool, str]:
    # /readyz IS a readiness endpoint, so the strict form is the right one here.
    try:
        with urllib.request.urlopen(f"{HEADROOM_URL}/readyz", timeout=2) as response:
            up = 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        up = False
    if up:
        return (True, f"  Headroom: ready at {HEADROOM_URL}")
    return (False, f"  Headroom: not reachable at {HEADROOM_URL} (tstack services up headroom)")


def voice() -> tuple[str, list[str]]:
    """Which engine could speak here, and therefore what the default should be.

    macOS defaults to ON because `say` is a floor that cannot be missing --
    something can always speak there. Elsewhere it depends on a container being
    up, and promising speech a machine cannot produce is worse than not offering.
    """
    lines: list[str] = []
    if answers(f"{KOKORO_URL}/v1/models") or answers(f"{KOKORO_URL}/health"):
        lines.append(f"    kokoro: reachable at {KOKORO_URL}")
        best = "on"
    else:
        lines.append(f"    kokoro: not reachable at {KOKORO_URL} (needs the container)")
        best = "off"
    if plat.kind() == plat.MACOS and shutil.which("say"):
        lines.append("    say: always available on macOS - it is the floor")
        best = "on"
    if shutil.which("edge-tts"):
        lines.append("    edge-tts: installed (cloud voice, needs network)")
        best = "on"
    return (best, lines)
