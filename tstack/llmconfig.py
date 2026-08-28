"""AgentMemory's chat provider: read it, write it, and never guess at it.

This is the one piece of terminal-stack configuration that is NOT a saved
setting. `OPENAI_BASE_URL` and `OPENAI_MODEL` live in
`services/stacks/agentmemory/.env`, which is compose's interpolation source and
is gitignored per machine; the credential lives one level up in `services/.env`,
which loads AFTER it and is therefore the only place a key can win.

That is why the settings dashboard could not touch any of it: it is built off
`schema.py`, and none of these are in it. `tstack agents llm` reports the state;
this module is what lets something change it.

THE ASYMMETRY IS THE WHOLE DESIGN. Unset is a supported skip that every check
reports. Set-but-unreachable fails SILENTLY -- the calls return empty, fail XML
parsing, retry, and still log outcome:"success" -- so `clear()` exists as a
first-class operation and is not the same as writing an empty string.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import stacks

# The three that decide whether the four LLM-only features run, and the two
# display labels the console reads. `OPENAI_API_KEY` is deliberately in the
# repo-root file rather than this one.
BASE_URL = "OPENAI_BASE_URL"
MODEL = "OPENAI_MODEL"
PROVIDER_LABEL = "LLM_PROVIDER_LABEL"
ENDPOINT_LABEL = "LLM_ENDPOINT_LABEL"
API_KEY = "OPENAI_API_KEY"

UNCONFIGURED_PROVIDER = "none"
UNCONFIGURED_ENDPOINT = "no chat provider configured"

# What a chat model buys. `tstack agents llm` prints the same four, and they are
# stated here so a caller does not have to know them.
FEATURES = (
    ("compression", "long observations condensed before they are stored"),
    ("summary", "session summaries"),
    ("graph", "entity and relation extraction into the knowledge graph"),
    ("consolidation", "the periodic reflect pass that turns observations into insights"),
)


@dataclass(frozen=True)
class Provider:
    base_url: str = ""
    model: str = ""
    provider_label: str = ""
    endpoint_label: str = ""
    api_key_set: bool = False

    @property
    def configured(self) -> bool:
        """A base URL is what makes the features run at all.

        Not the model: an endpoint with an empty `OPENAI_MODEL` reads as
        configured everywhere and leaves every family off, which is why it is a
        separate question below.
        """
        return bool(self.base_url)

    @property
    def complete(self) -> bool:
        return bool(self.base_url and self.model)


def stack_env(source: Path) -> Path:
    return stacks.stack_dir(source, "agentmemory") / ".env"


def shared_env(source: Path) -> Path:
    """The repo-root services/.env, which loads after the stack one and is
    therefore the only place the credential can win."""
    return stacks.stack_root(source).parent / ".env"


def read(source: Path) -> Provider:
    stack = stack_env(source)
    return Provider(
        base_url=stacks.env_value(stack, BASE_URL) or "",
        model=stacks.env_value(stack, MODEL) or "",
        provider_label=stacks.env_value(stack, PROVIDER_LABEL) or "",
        endpoint_label=stacks.env_value(stack, ENDPOINT_LABEL) or "",
        api_key_set=bool(stacks.env_value(shared_env(source), API_KEY)),
    )


def _set_key(path: Path, key: str, value: str | None) -> bool:
    """Set a key, or remove it when `value` is None. True if the file changed.

    An ACTIVE line is replaced where it stands; otherwise the key is appended.
    A COMMENTED line is never touched -- in this file those are the three
    provider shapes the example documents, and uncommenting one to hold a value
    destroys the explanation that is most of that file's worth.

    That also keeps exactly one active line per key, which matters because
    `stacks.env_value` reads the first match: two actives and the answer depends
    on position.
    """
    try:
        # newline="" on purpose: universal-newline translation would silently
        # rewrite every CRLF line in a .env a Windows editor touched. Same rule
        # as stacks.replace_in_file and the agentmemory harness.
        with path.open("r", encoding="utf-8", newline="") as handle:
            body = handle.read()
    except OSError:
        return False

    # A uniformly-CRLF file is matched in its LF form and re-emitted as CRLF.
    # Without this a line-anchored `^KEY=.*$` swallows the \r -- `.` matches it
    # and `$` matches before the \n -- so the one line touched silently becomes
    # LF, half-converting a .env that a Windows editor also writes. Same rule and
    # same reason as stacks.replace_in_file.
    crlf = "\r\n" in body and body.count("\n") == body.count("\r\n")
    subject = body.replace("\r\n", "\n") if crlf else body

    active = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)

    if value is None:
        if not active.search(subject):
            return False
        # Removed, not commented. "No line at all" is exactly the state a fresh
        # clone ships, and commenting instead makes the file grow by four lines
        # on every configure/clear cycle. The value is not lost: the example
        # documents all three provider shapes a few lines above.
        updated = re.sub(rf"^{re.escape(key)}=.*\n?", "", subject, count=1, flags=re.MULTILINE)
    else:
        line = f"{key}={value}"
        if active.search(subject):
            updated = active.sub(lambda _m: line, subject, count=1)
        else:
            updated = subject + ("" if subject.endswith("\n") else "\n") + line + "\n"

    if updated == subject:
        return False
    if crlf:
        updated = updated.replace("\n", "\r\n")
    # Written via a temp file and replaced, so a crash cannot leave a partial
    # .env -- which compose would read, and which fails in the silent direction.
    temporary = path.with_name(path.name + ".tstack-tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(updated)
    temporary.replace(path)
    return True


def configure(source: Path, base_url: str, model: str, labels: tuple[str, str]) -> list[str]:
    """Point agentmemory at a provider. Returns what changed, for reporting."""
    stack = stack_env(source)
    changed = []
    for key, value in (
        (BASE_URL, base_url),
        (MODEL, model),
        (PROVIDER_LABEL, labels[0]),
        (ENDPOINT_LABEL, labels[1]),
    ):
        if _set_key(stack, key, value):
            changed.append(key)
    return changed


def clear(source: Path) -> list[str]:
    """Back to no provider -- a supported state, and the one a fresh clone ships.

    The labels are set rather than commented: the compose file defaults them to
    "OpenAI"/"OpenAI API", so leaving them absent makes the console name a
    provider this machine does not have.
    """
    stack = stack_env(source)
    changed = []
    for key in (BASE_URL, MODEL):
        if _set_key(stack, key, None):
            changed.append(key)
    for key, value in (
        (PROVIDER_LABEL, UNCONFIGURED_PROVIDER),
        (ENDPOINT_LABEL, UNCONFIGURED_ENDPOINT),
    ):
        if _set_key(stack, key, value):
            changed.append(key)
    return changed


def labels_for(base_url: str) -> tuple[str, str]:
    """Honest display labels derived from the endpoint.

    The console shows these, and its cost assessment reads the provider name: an
    unlabelled provider is assessed as PAID, which is the safe direction to be
    wrong in but wrong for a local runtime.
    """
    lowered = base_url.lower()
    if "api.openai.com" in lowered:
        return ("OpenAI", "OpenAI API")
    if ":11434" in lowered:
        return ("Ollama", "local Ollama")
    if ":1234" in lowered:
        return ("LM Studio", "local LM Studio")
    if "host.docker.internal" in lowered or "localhost" in lowered or "127.0.0.1" in lowered:
        return ("local runtime", "this machine")
    return ("OpenAI-compatible", base_url)
