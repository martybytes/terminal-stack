"""Machine-local secrets, deliberately outside both config stores.

`state/secrets.json`, next to `token` and `history.db`. Named `keystore` rather than
`secrets` so it cannot be confused with the standard library module that `config.py`
imports.

Why a third store at all, when this repo has spent real effort reducing the number of
places settings live:

- **An environment variable cannot work here.** The daemon is autostarted from
  `HKCU\\...\\CurrentVersion\\Run`, so it inherits the *logon* environment and nothing
  else. A key exported in a shell, or even `setx` without a logoff, never reaches it. That
  is the same shape as the stale `AGENTMEMORY_SECRET` that silently destroyed 56 captures
  on 2026-08-21: it worked in a new shell and not in the running process.
- **Neither config store is an acceptable home for a key.** `config.json` is rendered from
  chezmoi `[data]`, which is tracked in git. `local.json` is untracked, but it sits in the
  same directory, is part of the config merge, and is the file people paste into a bug
  report. A secret that shows up in an effective-config dump is a secret that leaks.
- `load_or_create_token` (`config.py`) already established this exact pattern for the
  WSL-facing listener's shared secret: machine-local, state dir, never in config.

Values are read at use time, never merged into `Config`, and every function fails soft:
an unreadable or corrupt store returns "no value", so the caller falls back to the
environment variable exactly as it did before this module existed.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import tempfile
from pathlib import Path

from .config import state_dir

log = logging.getLogger(__name__)

# Secrets this daemon knows about. The UI offers exactly these, so an arbitrary key cannot
# be written through the settings endpoint.
ANTHROPIC_API_KEY = "anthropicApiKey"
KNOWN = (ANTHROPIC_API_KEY,)


def secrets_path() -> Path:
    return state_dir() / "secrets.json"


def _load() -> dict:
    try:
        raw = secrets_path().read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        # Never rewrite what we cannot parse: a hand-edited file with a typo should be
        # fixable by hand, not silently replaced.
        log.warning("secrets store is not valid JSON; ignoring it")
        return {}
    return data if isinstance(data, dict) else {}


def get(name: str) -> str:
    """The stored value, or "" when absent or unreadable. Never raises."""
    value = _load().get(name)
    return value.strip() if isinstance(value, str) else ""


def resolve(name: str, env_var: str = "") -> tuple[str, str]:
    """Return (value, source). Source is "store", "env", or "" when nothing was found.

    The store wins over the environment on purpose: the environment is the half that
    cannot be trusted to reach an autostarted daemon.
    """
    stored = get(name)
    if stored:
        return stored, "store"
    if env_var:
        from_env = os.environ.get(env_var, "").strip()
        if from_env:
            return from_env, "env"
    return "", ""


def set_value(name: str, value: str) -> bool:
    """Store or clear one secret. False when it could not be written.

    Atomic, and the file is made owner-only where the platform supports it.
    """
    if name not in KNOWN:
        log.warning("refusing to store an unknown secret name: %s", name)
        return False
    data = _load()
    if value:
        data[name] = value
    else:
        data.pop(name, None)
    path = secrets_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Temp file in the same directory so os.replace stays atomic (a cross-device move
        # is not), and never world-readable even briefly.
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".secrets-", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.write("\n")
            try:
                os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass  # Windows ACLs do not map; the profile directory is already per-user
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    except OSError as exc:
        log.warning("could not write the secrets store: %s", exc)
        return False
    log.info("secret %s %s", name, "stored" if value else "cleared")
    return True


def describe(name: str, env_var: str = "") -> dict:
    """Safe-to-render status for the UI: never the value, only where it came from."""
    value, source = resolve(name, env_var)
    return {
        "name": name,
        "set": bool(value),
        "source": source,
        # Enough to tell two keys apart in a screenshot without revealing either.
        "tail": value[-4:] if len(value) >= 8 else "",
        "envVar": env_var,
    }
