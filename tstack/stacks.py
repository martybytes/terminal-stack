"""Service stacks: discovery, start order, toggles, compose, volumes, checks.

Port of the `tstack services` half of services/_stack.sh (the 15 functions only
bootstrap/ts-stack.sh called) and of the same logic carried inline a second time
in bootstrap/ts-stack.ps1. The rest of _stack.sh stays where it is: it is the
library each stack's own ts-verify.sh sources, and those are not this port's
twins to delete.

A stack is any directory under services/stacks/ holding a docker-compose.yml.
There is no registry, which is why adding one requires no edit anywhere and why
services/** is a single .chezmoiignore line.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import engine, store

# ------------------------------------------------------------------- discovery


def stack_root(source: Path) -> Path:
    """Where the stacks live. TS_STACK_ROOT overrides it for the pytest fixtures."""
    override = os.environ.get("TS_STACK_ROOT")
    return Path(override) if override else source / "services" / "stacks"


def stack_dir(source: Path, name: str) -> Path:
    return stack_root(source) / name


def stack_list(source: Path) -> list[str]:
    """Every stack, in START order."""
    root = stack_root(source)
    if not root.is_dir():
        return []
    names = sorted(d.name for d in root.iterdir() if (d / "docker-compose.yml").is_file())
    return stack_order(root, names)


def stack_order(root: Path, names: list[str]) -> list[str]:
    """Lexical order, then each stack moved after whatever its `ts-after` names.

    Lexical alone is wrong the moment one stack joins another's network:
    agent007memory sorts BEFORE agentmemory ('0' < 'm'), and an external network
    cannot be joined before it exists. A stack declares what it must follow in an
    optional `ts-after` file, one name per line -- discovered like everything else
    here, never registered.

    Repeated passes rather than a real topological sort, exactly as the bash twin
    does: the input is a handful of stacks, and a cycle degrades to "leave the
    order alone" instead of hanging.
    """
    order = list(names)
    for _ in range(5):
        moved = False
        for name in list(order):
            after_file = root / name / "ts-after"
            if not after_file.is_file():
                continue
            try:
                lines = after_file.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for after in lines:
                after = after.strip()
                if not after or after.startswith("#") or after not in order:
                    continue
                if order.index(after) > order.index(name):
                    order.remove(name)
                    order.insert(order.index(after) + 1, name)
                    moved = True
        if not moved:
            break
    return order


# --------------------------------------------------------------------- toggles

# Which saved setting gates each stack, or "" for none. PURE, and the one place
# the mapping is written down.
_TOGGLES = {
    "agentmemory": "agentmemoryEnabled",
    # The console is part of the agentmemory feature, not a separate choice: a
    # machine that wants memories wants the proxy every client is pointed at.
    # Separate PROJECT, same switch.
    "agent007memory": "agentmemoryEnabled",
    "headroom": "headroomEnabled",
    "playwright": "playwrightEnabled",
    "kokoro": "ccTts",
}


def toggle_for(name: str) -> str:
    return _TOGGLES.get(name, "")


def stack_state(name: str) -> str:
    """ "" when this stack takes part here, else why it deliberately does not.

    kokoro is gated on the TTS engine as well as the switch, because a machine
    using edge or chatterbox has no use for a multi-gigabyte GPU image.

    THE BASH TWIN GOT THIS WRONG and the port fixes it. ts-stack.sh called
    `ts_cc_tts_get enabled` and `ts_cc_tts_get engine` -- but those keys are
    spelled ccTtsEnabled and ccTtsEngine, so the lookup missed, fell through to a
    default branch that runs the non-existent command `1`, and the `|| echo true`
    guard turned every failure into "TTS is on with kokoro". kokoro was therefore
    never once reported as off on macOS or Linux, whatever the settings said. The
    pwsh twin read the real values, so the two disagreed on every machine that
    had TTS off. This is exactly the drift the port exists to remove.
    """
    key = toggle_for(name)
    if not key:
        return ""
    if key == "ccTts":
        if store.normalise(store.get("ccTtsEnabled", "false")) != "true":
            return "voice notifications are off"
        chosen = store.get("ccTtsEngine", "kokoro")
        if chosen != "kokoro":
            return f"ccTts.engine={chosen}"
        return ""
    if store.normalise(store.get(key, "off")) in ("true", "on"):
        return ""
    return f"{key}=off"


# ------------------------------------------------------------------- env files


def env_value(path: Path, key: str) -> str | None:
    """One KEY=value out of an env file, or None. First match wins, as compose does."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.rstrip("\r").lstrip()
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def env_seeded(directory: Path) -> bool:
    """A stack shipping a .env.example with no .env is MIS-configured, not unconfigured.

    Compose silently falls back to the base file alone, which for kokoro means
    starting the GPU image with no GPU access.
    """
    if not (directory / ".env.example").is_file():
        return True
    return (directory / ".env").is_file()


def compose_files(directory: Path) -> list[str]:
    """Which compose files this stack will actually merge, per its .env.

    `docker compose ls` reports the files a project was *created* with, which goes
    stale the moment you add an overlay, so read the current intent instead.
    """
    sep = env_value(directory / ".env", "COMPOSE_PATH_SEPARATOR") or ":"
    spec = env_value(directory / ".env", "COMPOSE_FILE")
    if not spec:
        return ["docker-compose.yml"]
    return [part.strip() for part in spec.split(sep) if part.strip()]


def env_file_list(directory: Path) -> list[str]:
    """The --env-file list for a stack, in order.

    Compose reads these as INTERPOLATION sources; nothing here is injected into a
    container. Order is the whole point: `--env-file .billing.env` alone REPLACES
    .env as the interpolation source, so every ${...} default resolves to empty --
    which is how the console's provider panel went blank while everything reported
    healthy. Extras from `ts-envfiles` come first so the stack's own .env wins.

    `ts-envfiles` names interpolation sources ONLY. It is never an `env_file:`
    key, which would hand a container someone else's secrets.
    """
    out: list[str] = []
    extras = directory / "ts-envfiles"
    if extras.is_file():
        try:
            lines = extras.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if (directory / line).is_file():
                out.append(line)
    if (directory / ".env").is_file():
        out.append(".env")
    if (directory / ".billing.env").is_file():
        out.append(".billing.env")
    return out


# ------------------------------------------------------- the compose choke point


@dataclass
class Compose:
    """EVERY docker invocation goes through here.

    Which is what makes three invariants testable rather than merely intended:

      * `down` never receives -v (the two paths that do are explicit and gated)
      * the --env-file list keeps its order, .env before .billing.env
      * dry_run prints the exact argv and runs nothing
    """

    source: Path
    kind: str
    dry_run: bool = False

    def argv(self, stack: str, args: list[str]) -> list[str]:
        directory = stack_dir(self.source, stack)
        pre: list[str] = []
        # Only pass --env-file when there is something beyond the default .env:
        # compose reads .env on its own, and naming it for every stack would be
        # noise in the dry-run argv this is all inspected by.
        if (directory / "ts-envfiles").is_file() or (directory / ".billing.env").is_file():
            for name in env_file_list(directory):
                pre += ["--env-file", name]
        return [engine.binary_for(self.kind), "compose", *pre, *args]

    def run(
        self, stack: str, args: list[str], capture: bool = False
    ) -> subprocess.CompletedProcess[str]:
        argv = self.argv(stack, args)
        if self.dry_run:
            # Same shape as the bash twin's dry-run line, which is what every
            # --dry-run test and every human inspection reads. The binary is
            # named rather than assumed: on the WSL interop path it is docker.exe,
            # and printing an argv that is not the one that would run is worse
            # than printing nothing.
            print(f"({stack}) {' '.join(argv)}")
            return subprocess.CompletedProcess(argv, 0, "", "")
        directory = stack_dir(self.source, stack)
        return subprocess.run(
            argv,
            cwd=str(directory),
            capture_output=capture,
            text=True,
            check=False,
            start_new_session=True,
        )

    def ok(self, stack: str, args: list[str]) -> bool:
        return self.run(stack, args).returncode == 0

    def quiet(self, stack: str, args: list[str]) -> tuple[int, str]:
        got = self.run(stack, args, capture=True)
        return got.returncode, (got.stdout or "") + (got.stderr or "")


def docker(kind: str, args: list[str], timeout: int = 60) -> tuple[int, str]:
    """One docker call that is not a compose call. Returns (rc, stdout)."""
    try:
        out = subprocess.run(
            [engine.binary_for(kind), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return out.returncode, out.stdout


# --------------------------------------------------------------------- volumes

# One (old, new) pair per line of the bash twin's here-doc. The headroom three
# carry their old project prefix because they were plain named volumes under a
# project called headroom; the two agentmemory volumes are external, so they
# never had one.
VOLUME_RENAMES: tuple[tuple[str, str], ...] = (
    ("agentmemory_iii-data", "ts-agentmemory-data"),
    ("agent007memory_history", "ts-agentmemory-console-history"),
    ("headroom_headroom_workspace", "ts-headroom-workspace"),
    ("headroom_qdrant_data", "ts-headroom-qdrant"),
    ("headroom_neo4j_data", "ts-headroom-neo4j"),
)

# The two volumes holding every memory ever saved. `external: true`, so `down -v`
# cannot touch them -- that asymmetry IS the safety property.
MEMORY_VOLUMES: tuple[str, ...] = ("ts-agentmemory-data", "ts-agentmemory-console-history")

DATA_VOLUMES: tuple[str, ...] = (
    *MEMORY_VOLUMES,
    "ts-headroom-workspace",
    "ts-headroom-qdrant",
    "ts-headroom-neo4j",
)


def volume_exists(kind: str, name: str) -> bool:
    rc, _ = docker(kind, ["volume", "inspect", name], timeout=30)
    return rc == 0


def volumes_pending(kind: str) -> list[tuple[str, str]]:
    """Pairs still needing migration. Empty means nothing to do.

    With the engine down `docker volume inspect` fails for BOTH names, so callers
    must treat empty as "unknown" there, not "current": saying otherwise is a
    false all-clear about the one operation that touches data.
    """
    return [
        (old, new)
        for old, new in VOLUME_RENAMES
        if volume_exists(kind, old) and not volume_exists(kind, new)
    ]


def data_volumes(kind: str) -> list[str]:
    """Every volume this stack owns that exists, INCLUDING pre-ts- names.

    Listing only the new names made `backup` a no-op on exactly the machine that
    needed it most: the one about to migrate.
    """
    found = [v for v in DATA_VOLUMES if volume_exists(kind, v)]
    found += [old for old, _ in VOLUME_RENAMES if volume_exists(kind, old)]
    return found


# ---------------------------------------------------------------------- checks


@dataclass
class Check:
    kind: str
    id: str
    expect: str
    secs: str
    target: str


def check_files(source: Path, stack: str) -> list[Path]:
    """ts-checks.conf, plus one per compose OVERLAY this machine has selected.

    `docker-compose.<x>.yml` pairs with `ts-checks.<x>.conf` by name -- no
    registry, same rule as everything else here. Without it an overlay's services
    either go unchecked, or their checks sit in the base file and fail on every
    machine that has not enabled the overlay. headroom is the case that forced it:
    its Qdrant and Neo4j checks were asserted everywhere, and passed everywhere,
    while nothing had ever written to either.
    """
    directory = stack_dir(source, stack)
    out: list[Path] = []
    base = directory / "ts-checks.conf"
    if base.is_file():
        out.append(base)
    for name in compose_files(directory):
        match = re.fullmatch(r"docker-compose\.(.+)\.yml", name)
        if not match:
            continue
        overlay = directory / f"ts-checks.{match.group(1)}.conf"
        if overlay.is_file():
            out.append(overlay)
    return out


def read_checks(path: Path) -> list[Check]:
    out: list[Check] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 4)
        parts += [""] * (5 - len(parts))
        out.append(Check(*parts[:5]))
    return out


# --------------------------------------------------------------------- secrets


def rand_hex(chars: int = 32) -> str:
    """`chars` hex characters. Same length the bash twin produces."""
    return secrets.token_hex(chars)[:chars]


def replace_in_file(path: Path, pattern: str, replacement: str) -> bool:
    """Byte-exact whole-file regex replace. True when the file changed.

    Not sed: sed is line-oriented and appends a trailing newline to a file that
    lacked one, and `-i` needs `-i ''` on BSD while GNU rejects it. These rewrite
    files the rest of the stack also rewrites, so a one-byte difference would have
    them fight over the file forever. newline="" for the same reason: universal
    newline translation would silently rewrite a CRLF file to LF.
    """
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            before = handle.read()
    except OSError:
        return False
    after = re.sub(pattern, replacement, before, flags=re.MULTILINE)
    if after == before or not after:
        return False
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        handle.write(after)
    tmp.replace(path)
    return True


def secret_fingerprint(secret: str) -> str:
    """First six and last four. NEVER the value.

    A secret echoed to a terminal lives in scrollback, and this one is also in
    `docker logs` until it is rotated.
    """
    return f"{secret[:6]}...{secret[-4:]}"


# ---------------------------------------------------------------------- backup


def backup_dir() -> Path:
    """Where backups go.

    NOT C:\\DATA: that is one person's path. On macOS $HOME is also the only tree
    Docker Desktop shares by default, so a backup root outside it cannot be
    bind-mounted at all.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    root = os.environ.get("TS_STACK_BACKUP_ROOT")
    if root:
        return Path(root) / stamp
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "terminal-stack" / "stack-backups" / stamp
    xdg = os.environ.get("XDG_STATE_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "state"
    return base / "terminal-stack" / "stack-backups" / stamp


def docker_shareable(path: Path) -> bool:
    """Whether this engine can bind-mount the path at all.

    Windows and Linux share whole drives; macOS Docker Desktop shares a fixed list
    of trees, and a backup written outside them fails INSIDE the container as tar
    saying "Cannot open" -- after the stack is already down.
    """
    if engine.os_name() != engine.DARWIN:
        return True
    resolved = str(path.resolve()) + "/"
    home = str(Path.home().resolve())
    return resolved.startswith((home + "/", "/tmp/", "/private/", "/Volumes/"))
