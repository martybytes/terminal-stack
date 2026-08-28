"""`tstack services` - the local Docker service stacks: bring them up, prove they work.

Replaces bootstrap/ts-stack.sh (635 lines) and bootstrap/ts-stack.ps1 (897), which
were a near-perfect duplicate of each other and drifted anyway. Two of those drifts
are fixed by the merge rather than by anyone noticing them:

1.  kokoro's toggle. The bash twin looked up `enabled` and `engine` where the keys
    are `ccTtsEnabled` and `ccTtsEngine`, so its lookup always missed and its
    `|| echo true` fallback reported TTS as on with kokoro on every POSIX machine,
    whatever the settings said. See stacks.stack_state.
2.  The WSL handoff. The bash twin re-exec'd the pwsh twin for up/down/restart/
    logs/config, because the Windows copy was the one that could reach the engine
    -- and gave up entirely on a machine with no pwsh 7, and never covered the
    other seven verbs at all. There is one implementation now, so it runs
    `docker.exe` through interop instead. See tstack/engine.py.

This is the ONLY thing in the repo that starts, stops or builds a container.
`tstack agents` may probe one and print a verb from here; it may never run docker.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import engine, paths, stacks, store

HELP = """tstack services - the local Docker service stacks: bring them up, prove they work.

Usage:
  tstack services [status]            one line per stack: state, health, published ports
  tstack services up [<stack>]        docker compose up -d
  tstack services down [<stack>]      docker compose down          (every volume kept)
  tstack services restart [<stack>]   down, then up
  tstack services logs <stack>        docker compose logs
  tstack services config [<stack>]    what compose actually resolves to on this machine
  tstack services bootstrap           first run here: .env files, secrets, volumes
  tstack services doctor              engine, .env files, health, ports, toggle drift
  tstack services test                take it all down, bring it back up, prove the chain
  tstack services backup [<stack>]    cold tar of every data volume, with a manifest
  tstack services reset [<stack>]     containers and locally built images, back to clean
  tstack services migrate-volumes     the one-time rename to the ts- volume names
  tstack services -h                  this help

  --dry-run          print the exact docker argv and change nothing
  -a, --all          include stacks whose saved terminal-stack setting is off
  -n, --tail <N>     logs: lines of history (default 50)
  -f, --follow       logs: follow (needs a single stack)
  --start-engine     doctor/up: launch the container engine and wait for it
  --build            up/restart: rebuild locally built images first
  -y, --yes          skip the migrate-volumes confirmation (NOT the destructive ones)
  --destroy-data     test/reset: also destroy volumes   [BACKS UP FIRST]
  --purge            reset: also the two memory volumes [EVERY MEMORY YOU HAVE]
  --no-colour

A stack is any directory under services/stacks/ holding a docker-compose.yml -
there is nothing to register. Which stacks take part comes from the saved
settings you already have: agentmemoryEnabled, headroomEnabled, playwrightEnabled
and, for kokoro, the TTS switch plus ccTts.engine. A stack whose setting is off
is skipped and reported as skipped, never as broken; naming it explicitly runs it
anyway, because asking by name is consent.

Every published port binds 127.0.0.1 only and none of these services
authenticate, which is why "tstack services doctor" audits the bindings even when
everything else is failing."""

VERBS = (
    "status",
    "up",
    "down",
    "restart",
    "logs",
    "config",
    "doctor",
    "bootstrap",
    "migrate-volumes",
    "test",
    "backup",
    "reset",
)

# Verbs that need the engine to do anything at all. `status` is deliberately not
# one of them: with the engine down it still reports the settings, which is what
# makes it usable while the engine is the thing that is broken.
NEEDS_ENGINE = ("up", "down", "restart", "logs", "config")


# ---------------------------------------------------------------------- output


class Out:
    """The services vocabulary (section/step/info/warn/pass/fail) and the doctor
    gutter (ok/bad/skip/note) in one place.

    Two dialects in one command is worse than either, but the absorbed services
    tree keeps its own OK/X/! gutter in services/**, so `tstack services` prints
    the doctor gutter and calls into the other for library-level steps.
    """

    def __init__(self, colour: bool, apply: bool) -> None:
        self.issues = 0
        self.apply = apply
        self.cyan = "\033[36m" if colour else ""
        self.green = "\033[32m" if colour else ""
        self.yellow = "\033[33m" if colour else ""
        self.dim = "\033[90m" if colour else ""
        self.reset = "\033[0m" if colour else ""
        # _config.sh's $WARN, which the status lines are formatted around.
        self.warn_glyph = f"{self.yellow}!!{self.reset}" if colour else "!!"

    def section(self, text: str) -> None:
        print(f"\n{self.cyan}=== {text} ==={self.reset}")

    def step(self, text: str) -> None:
        # '[DO]   ' and '[would]' are both 7 characters, so a message lands in the
        # same column either way -- the entire point of the tag.
        if self.apply:
            print(f"{self.green}[DO]    {text}{self.reset}")
        else:
            print(f"{self.yellow}[would] {text}{self.reset}")

    def info(self, text: str) -> None:
        print(f"{self.dim}       {text}{self.reset}")

    def warn(self, text: str) -> None:
        print(f"{self.yellow}  !    {text}{self.reset}")

    def passed(self, text: str) -> None:
        print(f"{self.green}  OK   {text}{self.reset}")

    def failed(self, text: str) -> None:
        self.issues += 1
        print(f"{self.yellow}  X    {text}{self.reset}")

    def ok(self, text: str) -> None:
        print(f"  ok  {text}")

    def bad(self, text: str) -> None:
        self.issues += 1
        print(f"  {self.warn_glyph} {text}")

    def skip(self, text: str) -> None:
        print(f"  --  {text}")

    def note(self, text: str) -> None:
        print(f"      {text}")


def _use_colour(no_colour: bool) -> bool:
    if no_colour or os.environ.get("NO_COLOR"):
        return False
    forced = os.environ.get("TSS_COLOR", "auto")
    if forced == "always":
        return True
    if forced == "never":
        return False
    if not sys.stdout.isatty():
        return False
    term = os.environ.get("TERM", "")
    return bool(term) and term != "dumb"


# ------------------------------------------------------------------------ args


class Args:
    def __init__(self) -> None:
        self.cmd = ""
        self.stack = ""
        self.tail = "50"
        self.follow = False
        self.all = False
        self.start_engine = False
        self.build = False
        self.destroy_data = False
        self.purge = False
        self.assume_yes = False
        self.dry_run = os.environ.get("TS_STACK_DRY_RUN", "0") == "1"
        self.no_colour = False


class Usage(Exception):
    """A bad command line. Always exit 2, never 1: the shell twin blurred those
    two and the difference is what a caller keys off."""


def parse(argv: list[str]) -> Args:
    args = Args()
    rest = list(argv)
    while rest:
        item = rest.pop(0)
        if item in VERBS:
            if args.cmd:
                raise Usage(f"tstack services: two commands given ({args.cmd}, {item})")
            args.cmd = item
        elif item == "--dry-run":
            args.dry_run = True
        elif item in ("-a", "--all"):
            args.all = True
        elif item in ("-f", "--follow"):
            args.follow = True
        elif item in ("-n", "--tail"):
            if not rest:
                raise Usage("tstack services: --tail needs a value")
            args.tail = rest.pop(0)
        elif item == "--start-engine":
            args.start_engine = True
        elif item == "--build":
            args.build = True
        elif item in ("-y", "--yes"):
            args.assume_yes = True
        elif item == "--destroy-data":
            args.destroy_data = True
        elif item == "--purge":
            args.purge = True
            args.destroy_data = True
        elif item in ("--no-colour", "--no-color"):
            args.no_colour = True
        elif item == "--stack":
            if not rest:
                raise Usage("tstack services: --stack needs a value")
            args.stack = rest.pop(0)
        elif item.startswith("-"):
            raise Usage(f"tstack services: unknown option: {item} (try -h)")
        else:
            if args.stack:
                raise Usage("tstack services: two stacks given")
            args.stack = item
    args.cmd = args.cmd or "status"
    if not args.tail.isdigit():
        raise Usage("tstack services: --tail wants a number")
    return args


# ----------------------------------------------------------------------- state


class Services:
    def __init__(self, source: Path, args: Args) -> None:
        self.source = source
        self.args = args
        self.out = Out(_use_colour(args.no_colour), apply=not args.dry_run)
        self.kind = engine.docker_kind()
        self.engine_ok = engine.is_up(self.kind) if not args.dry_run else False
        self.all_stacks = stacks.stack_list(source)
        self.compose = stacks.Compose(source, self.kind, dry_run=args.dry_run)
        self.stacks: list[str] = []

    # Which stacks take part. Naming one is consent, so it overrides its toggle.
    def selected(self) -> list[str]:
        if self.args.all:
            return list(self.stacks)
        return [s for s in self.stacks if not stacks.stack_state(s)]

    def dir(self, name: str) -> Path:
        return stacks.stack_dir(self.source, name)

    def advise(self, to_stderr: bool = False, indent: str = "") -> None:
        stream = sys.stderr if to_stderr else sys.stdout
        for line in engine.engine_advice(engine.os_name(), self.kind):
            print(f"{indent}{line}", file=stream)


# ----------------------------------------------------------------------- verbs


def cmd_status(svc: Services) -> None:
    out = svc.out
    for name in svc.stacks:
        state = stacks.stack_state(name)
        running = total = 0
        if svc.engine_ok:
            rc, ids = svc.compose.quiet(name, ["ps", "-q", "--status", "running"])
            running = len([x for x in ids.splitlines() if x.strip()]) if rc == 0 else 0
            rc, ids = svc.compose.quiet(name, ["ps", "-aq"])
            total = len([x for x in ids.splitlines() if x.strip()]) if rc == 0 else 0
        if state and total == 0:
            print(f"  --  {name:<15} {state}")
            continue
        if state:
            # Intent and reality disagree. A warn, not a failure: this is exactly
            # what a doctor exists to surface, and it is not "broken".
            print(f"  {out.warn_glyph}   {name:<15} running, but {state}")
            out.issues += 1
            print(
                f"      tstack config agents {name} on   (keep it)   |   "
                f"tstack services down {name}   (stop it)"
            )
            continue
        if not svc.engine_ok:
            print(f"      {name:<15} enabled (engine unreachable, state unknown)")
        elif total == 0:
            print(f"  {out.warn_glyph}   {name:<15} not created")
            out.issues += 1
        elif running == total:
            print(f"  ok  {name:<15} running ({running}/{total})  {_published(svc, name)}")
        else:
            print(f"  {out.warn_glyph}   {name:<15} partial ({running}/{total})")
            out.issues += 1


def _published(svc: Services, name: str) -> str:
    rc, blob = svc.compose.quiet(name, ["ps", "--format", "{{.Publishers}}"])
    if rc != 0:
        return ""
    ports = set()
    for chunk in blob.replace(",", "\n").splitlines():
        marker = "127.0.0.1:"
        if marker not in chunk:
            continue
        tail = chunk.split(marker, 1)[1]
        digits = ""
        for char in tail:
            if not char.isdigit():
                break
            digits += char
        if digits:
            ports.add(int(digits))
    return " ".join(str(p) for p in sorted(ports)) + (" " if ports else "")


def warn_unseeded(svc: Services) -> None:
    """Every action warns when a stack ships a .env.example but has no .env.

    Compose then silently falls back to the base file, which for kokoro means
    starting the GPU image with no GPU.
    """
    for name in svc.stacks:
        if not stacks.env_seeded(svc.dir(name)):
            svc.out.warn(
                f"{name}: .env.example exists but .env does not - "
                "the stack will start with the wrong profile"
            )


def cmd_config(svc: Services) -> None:
    for name in svc.selected():
        svc.out.section(name)
        svc.compose.run(name, ["config"])


def cmd_logs(svc: Services) -> None:
    if not svc.args.stack:
        raise Usage("tstack services: logs needs a stack name")
    argv = ["logs", "--tail", svc.args.tail]
    if svc.args.follow:
        argv.append("-f")
    svc.compose.run(svc.args.stack, argv)


def cmd_up(svc: Services) -> None:
    # A legacy volume with no ts- replacement means compose would create an EMPTY
    # one and start the stack reporting success, with every memory left behind in
    # a volume nothing mounts. Refuse, and name the one command.
    if not svc.args.dry_run:
        pending = stacks.volumes_pending(svc.kind)
        if pending:
            svc.out.bad("volumes still carry their pre-ts- names:")
            for old, new in pending:
                print(f"        {old} {new}")
            svc.out.note(
                "run:  tstack services migrate-volumes     (copies, verifies, keeps the old volume)"
            )
            raise SystemExit(1)
    warn_unseeded(svc)
    for name in svc.selected():
        svc.out.section(name)
        if not svc.compose.ok(name, _up_argv(svc)):
            svc.out.bad(f"up failed for {name}")


def _up_argv(svc: Services) -> list[str]:
    """`up -d`, plus `--build` when asked.

    Only two stacks in this tree build an image locally (the console, and
    headroom's gateway), and after editing their source `up` reuses the image it
    already has -- so the change appears to have done nothing. The alternative
    was `reset` then `up`, which also destroys the container. Not offered on
    `test`: that verb proves a clean bring-up, and rebuilding mid-proof would
    change what is being proved.
    """
    return ["up", "-d", "--build"] if svc.args.build else ["up", "-d"]


def cmd_down(svc: Services) -> None:
    # -v is NEVER in this argv. Volumes are only ever destroyed by an explicitly
    # gated path, and that is enforced by test, not by comment.
    #
    # REVERSE start order: a stack that joins another's network has to let go of
    # it first, or `down` on the owner leaves a network in use and the error names
    # neither stack.
    for name in reversed(svc.selected()):
        svc.out.section(name)
        if not svc.compose.ok(name, ["down"]):
            svc.out.bad(f"down failed for {name}")


def cmd_restart(svc: Services) -> None:
    # down + up, not `docker compose restart`: restart reuses the existing
    # container, so it does not pick up the changed .env or overlay that is the
    # reason anyone restarts.
    #
    # ALL down (reverse order) before ANY up, rather than down-then-up per stack:
    # restarting agentmemory while agent007memory still holds ts-agentmemory-net
    # leaves the console pointed at a container that no longer exists, and it only
    # recovers on its own restart timer.
    for name in reversed(svc.selected()):
        svc.out.section(name)
        svc.compose.run(name, ["down"])
    for name in svc.selected():
        svc.out.section(name)
        if not svc.compose.ok(name, _up_argv(svc)):
            svc.out.bad(f"restart failed for {name}")


def cmd_bootstrap(svc: Services) -> None:
    """First run on this machine. Idempotent by design: every step reports "left
    untouched" when it has already been done, so re-running after adding a stack is
    the normal way to use it."""
    out = svc.out
    out.section("per-machine .env files")
    for name in svc.all_stacks:
        _seed_env(svc, svc.dir(name))
    services_dir = svc.source / "services"
    if (services_dir / ".env").is_file():
        out.info("services/.env already exists - left untouched")
    elif (services_dir / ".env.example").is_file():
        out.step("copy services/.env.example -> .env")
        if out.apply:
            (services_dir / ".env").write_bytes((services_dir / ".env.example").read_bytes())

    out.section("generated secrets")
    # headroom refuses to `compose config` without these: both are :?-required,
    # deliberately, so a missing one fails loudly instead of starting an open data
    # plane. They are arbitrary strings, so there is no reason to make a human
    # paste them out of `openssl rand -hex 32`.
    for item in _generated_secrets(svc.source):
        _fill_secret(
            svc,
            svc.dir("headroom") / ".env",
            item["key"],
            item["placeholder"],
            int(item.get("bytes", 32)),
        )

    out.section("named volumes")
    # The external volumes have to exist before the first `up`, because external
    # means compose will not create them. This is where every memory you have ever
    # saved lives, so an existing one is never touched. Read out of the compose
    # files themselves rather than listed here.
    for volume in _external_volumes(svc.source) or ["ts-agentmemory-data"]:
        if not out.apply:
            out.step(f"docker volume create {volume} (if absent)")
            continue
        if stacks.volume_exists(svc.kind, volume):
            out.info(f"'{volume}' already exists - left untouched (this is where your data lives)")
            continue
        # Creating it here would DEFEAT the migration guard: pending pairs are only
        # reported while the new name is absent, so an empty replacement turns
        # "your memories are in the old volume" into a silent success.
        legacy = next((old for old, new in stacks.VOLUME_RENAMES if new == volume), "")
        if legacy and stacks.volume_exists(svc.kind, legacy):
            out.bad(f"'{legacy}' still holds this stack's data - NOT creating an empty '{volume}'")
            out.note("run:  tstack services migrate-volumes")
            continue
        out.step(f"docker volume create {volume}")
        rc, _ = stacks.docker(svc.kind, ["volume", "create", volume])
        if rc != 0:
            out.bad(f"docker volume create failed for {volume}")

    out.section("next")
    out.note("tstack services up        start the stacks your settings enable")
    out.note("tstack services doctor    check the engine, the .env files and the ports")


def _seed_env(svc: Services, directory: Path) -> None:
    example = directory / ".env.example"
    target = directory / ".env"
    if not example.is_file():
        return
    if target.is_file():
        svc.out.info(f"{directory.name}/.env already exists - left untouched")
        return
    svc.out.step(f"copy {directory.name}/.env.example -> .env")
    if not svc.out.apply:
        return
    target.write_bytes(example.read_bytes())
    svc.out.info("seeded with the default profile - review it before starting the stack")
    # kokoro is the one stack whose shipped default is wrong on most machines: its
    # .env.example carries Profile A (Blackwell, CUDA 12.8) uncommented, so a blind
    # copy hands a cu128 image and the NVIDIA device reservation to a Mac.
    # setup-kokoro-docker.sh already refuses GPU on darwin; this is the same
    # knowledge, applied to the file compose actually reads.
    if directory.name == "kokoro":
        ok, message = stacks.seed_kokoro_profile(target)
        (svc.out.info if ok else svc.out.warn)(message)


def _generated_secrets(source: Path) -> list[dict]:
    catalog = source / "bootstrap" / "agent-tools.json"
    try:
        body = json.loads(catalog.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    got = body.get("headroom", {}).get("generatedSecrets", [])
    return got if isinstance(got, list) else []


def _fill_secret(svc: Services, path: Path, key: str, placeholder: str, size: int) -> None:
    """Replace a still-placeholder value with real random bytes.

    Never rotates a value somebody set: that is what makes a re-run idempotent, and
    what stops a second bootstrap silently invalidating a live proxy token.
    """
    if not path.is_file():
        return
    current = stacks.env_value(path, key)
    if current and current != placeholder:
        svc.out.info(f"{key} already set - left untouched")
        return
    svc.out.step(f"generate {key} ({size} random bytes)")
    if not svc.out.apply:
        return
    secret = stacks.rand_hex(size)
    if not stacks.replace_in_file(path, f"^{key}=.*$", f"{key}={secret}"):
        svc.out.warn(f"could not set {key}")
        return
    # A fingerprint, never the value: a secret echoed to a terminal lives in
    # scrollback, and this one is also in `docker logs` until rotation.
    svc.out.info(f"{key} set ({stacks.secret_fingerprint(secret)})")


def _external_volumes(source: Path) -> list[str]:
    """Every `external: true` volume of every stack, from the source of truth.

    This used to name the console volume only when agentmemory's COMPOSE_FILE
    mentioned the console overlay, which stopped being true the moment the console
    became its own compose project.
    """
    found: set[str] = set()
    root = stacks.stack_root(source)
    if not root.is_dir():
        return []
    for compose_file in sorted(root.glob("*/docker-compose.yml")):
        try:
            lines = compose_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        in_volumes = False
        name = ""
        for line in lines:
            if line.startswith("volumes:"):
                in_volumes = True
                continue
            if line[:1].isalpha():
                in_volumes = False
            if not in_volumes:
                continue
            if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
                name = line.strip().rstrip(":")
                continue
            if name and "external:" in line and line.split("external:")[1].strip() == "true":
                found.add(name)
                name = ""
    return sorted(found)


def cmd_migrate_volumes(svc: Services) -> None:
    out = svc.out
    # With the engine down `docker volume inspect` fails for BOTH names, so an
    # empty pending list means "unknown", not "current". Saying otherwise is a
    # false all-clear about the one operation that touches data.
    if not svc.engine_ok:
        out.bad("the engine is unreachable, so the volume names cannot be read")
        svc.advise(indent="      ")
        raise SystemExit(1)
    pending = stacks.volumes_pending(svc.kind)
    if not pending:
        out.ok("volume names are already current")
        return
    out.section("migrate volumes")
    for old, new in pending:
        print(f"  would copy: {old} {new}")
    if svc.args.dry_run:
        out.note("no --dry-run: the copy runs in a container and leaves the old volume in place")
        return
    # Nothing is destroyed here, so this needs consent but not a typed phrase: the
    # old volume survives as the rollback.
    reply = (
        "y" if svc.args.assume_yes else _ask("Copy these now? The old volumes are kept. [y/N]: ")
    )
    if not reply.lower().startswith("y"):
        out.note("nothing copied")
        return
    for old, new in pending:
        if not _volume_copy(svc, old, new):
            out.bad(f"{old} -> {new} failed")
    out.note("when the stack is proven on the new volumes: docker volume rm <old>")


def _ask(prompt: str) -> str:
    """Read consent from the terminal, not from stdin.

    /dev/tty on purpose, exactly as the bash twin does: `tstack services ... | tee`
    must still be able to ask, and a piped stdin must never be able to answer a
    destructive prompt on the user's behalf.
    """
    try:
        with open("/dev/tty", "r+", encoding="utf-8") as tty:
            tty.write(prompt)
            tty.flush()
            return (tty.readline() or "").strip()
    except OSError:
        pass
    try:
        return input(prompt).strip()
    except (OSError, EOFError):
        return ""


def _volume_copy(svc: Services, old: str, new: str) -> bool:
    """Copy one volume's contents into a new volume, in a container, and verify the
    file count came across. The old volume is left ALONE: it is the rollback."""
    before = _count_files(svc, old, "/from")
    if before is None:
        svc.out.warn(f"{old}: could not be read")
        return False
    if stacks.docker(svc.kind, ["volume", "create", new])[0] != 0:
        return False
    # -a preserves modes and times; /data/.hmac is 0600 and must stay that way.
    rc, _ = stacks.docker(
        svc.kind,
        [
            "run",
            "--rm",
            "-v",
            f"{old}:/from:ro",
            "-v",
            f"{new}:/to",
            "alpine",
            "sh",
            "-c",
            "cp -a /from/. /to/ 2>/dev/null || cp -R /from/. /to/",
        ],
        timeout=1800,
    )
    if rc != 0:
        return False
    after = _count_files(svc, new, "/to")
    if before != after:
        svc.out.warn(
            f"{old} -> {new}: {before} files in, {after} out - "
            "NOT removing anything, and the new volume is suspect"
        )
        return False
    svc.out.passed(f"{old} -> {new} ({after} files)")
    return True


def _count_files(svc: Services, volume: str, mount: str) -> int | None:
    rc, out = stacks.docker(
        svc.kind,
        [
            "run",
            "--rm",
            "-v",
            f"{volume}:{mount}:ro",
            "alpine",
            "sh",
            "-c",
            f"find {mount} -type f | wc -l",
        ],
        timeout=600,
    )
    if rc != 0:
        return None
    text = out.strip()
    return int(text) if text.isdigit() else None


def cmd_test(svc: Services) -> None:
    out = svc.out
    # PHASE 0 - preflight. The only phase that runs while everything is still up,
    # so it has to be the exhaustive one: `compose config -q` names a missing
    # HEADROOM_PROXY_TOKEN here, not after the teardown.
    out.section("preflight")
    if not svc.engine_ok:
        out.bad("engine unreachable")
        svc.advise(indent="      ")
        raise SystemExit(2)
    out.ok("engine reachable")
    for name in svc.selected():
        if not stacks.env_seeded(svc.dir(name)):
            out.bad(f"{name}: .env missing - tstack services bootstrap")
            raise SystemExit(2)
        if svc.compose.quiet(name, ["config", "-q"])[0] == 0:
            out.ok(f"{name}: compose config parses")
        else:
            out.bad(f"{name}: compose config failed - a required value is missing")
            raise SystemExit(2)
    if stacks.volumes_pending(svc.kind):
        out.bad("volumes still carry their pre-ts- names - tstack services migrate-volumes")
        raise SystemExit(2)
    # The snapshot is what turns "the services came back" into "my data came
    # back". Counts only; nothing here reads a memory's content.
    out.note(f"snapshot: agentmemory API answered with {_snapshot_bytes()} bytes")

    # PHASE 1 - backup, only when something is about to be destroyed.
    if svc.args.destroy_data:
        out.section("backup")
        if not backup_all(svc):
            out.bad("backup failed - nothing was torn down")
            raise SystemExit(2)
    else:
        out.note("no --destroy-data: every volume is kept, so no backup is taken")

    # PHASE 2 - teardown.
    out.section("teardown")
    for name in svc.selected():
        svc.compose.run(name, ["down", "-v"] if svc.args.destroy_data else ["down"])

    # PHASE 3 - bring-up. Every stack starts before any is waited on, so the
    # start_periods overlap; only the console's depends_on serialises.
    out.section("bring-up")
    for name in svc.selected():
        if not svc.compose.ok(name, ["up", "-d"]):
            out.bad(f"up failed for {name}")

    # PHASE 4 - proof.
    out.section("health")
    for name in svc.selected():
        if not run_checks(svc, name):
            out.issues += 1

    out.section("integration")
    for name in svc.selected():
        script = svc.dir(name) / "ts-verify.sh"
        if not script.is_file():
            out.skip(f"{name}: no ts-verify.sh")
            continue
        got = subprocess.run(
            ["bash", str(script)], check=False, start_new_session=True, cwd=str(svc.dir(name))
        )
        if got.returncode == 0:
            out.ok(f"{name}: integration checks passed")
        else:
            out.bad(f"{name}: integration checks failed")

    # Never skipped by a toggle, and runs even when everything above failed: a
    # service reachable off-box is a security incident, not an outage.
    out.section("loopback audit")
    exposed = audit_loopback(svc)
    if not exposed:
        out.ok("every published port binds 127.0.0.1")
    else:
        out.bad("a container publishes beyond loopback:")
        for line in exposed:
            print(f"        {line}")


def _snapshot_bytes() -> int:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:3110/agentmemory/memories?limit=1", timeout=5
        ) as response:
            return len(response.read())
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def cmd_backup(svc: Services) -> None:
    if not svc.engine_ok:
        svc.out.bad("engine unreachable")
        raise SystemExit(2)
    svc.out.section("backup")
    if not backup_all(svc):
        svc.out.bad("backup failed")
        raise SystemExit(1)


def cmd_reset(svc: Services) -> None:
    # Levels, each destroying strictly more than the one above:
    #   (default)        containers, networks, and images BUILT here
    #   --destroy-data   also the three headroom volumes
    #   --purge          also the two memory volumes
    out = svc.out
    if not svc.engine_ok:
        out.bad("engine unreachable")
        raise SystemExit(2)
    if svc.args.destroy_data:
        out.section("backup first")
        if not backup_all(svc):
            out.bad("backup failed - nothing was destroyed")
            raise SystemExit(2)
        phrase = "destroy all memories" if svc.args.purge else "destroy headroom data"
        print(f"\nThis will DESTROY volumes. Type exactly: {phrase}")
        if _ask("") != phrase:
            out.note("phrase did not match - nothing was destroyed")
            raise SystemExit(1)
    out.section("reset")
    for name in svc.selected():
        svc.compose.run(name, ["down", "-v"] if svc.args.destroy_data else ["down"])
    if svc.args.purge:
        # The two memory volumes are `external: true`, so `down -v` cannot touch
        # them. That asymmetry is the safety property; removing them needs its own
        # code path, and this is it.
        for volume in stacks.MEMORY_VOLUMES:
            out.step(f"docker volume rm {volume}")
            if not svc.args.dry_run:
                stacks.docker(svc.kind, ["volume", "rm", volume])
    out.note("images pulled from a registry are kept (re-pulling kokoro is multi-GB)")


def cmd_doctor(svc: Services) -> None:
    out = svc.out
    out.section("engine")
    if svc.engine_ok:
        _, version = stacks.docker(svc.kind, ["version", "--format", "{{.Server.Version}}"])
        out.ok(f"engine reachable ({version.strip() or '?'})")
    else:
        out.bad(f"engine unreachable (kind: {svc.kind})")
        svc.advise(indent="      ")
    out.section("stacks")
    cmd_status(svc)
    out.section("volumes")
    if not svc.engine_ok:
        out.skip("volume names need the engine")
    else:
        pending = stacks.volumes_pending(svc.kind)
        if not pending:
            out.ok("volume names are current")
        else:
            out.bad("volumes still carry their pre-ts- names - tstack services migrate-volumes")
            for old, new in pending:
                print(f"        {old} {new}")
    out.section("configuration")
    for name in svc.stacks:
        if stacks.env_seeded(svc.dir(name)):
            out.ok(f"{name}: .env present or not needed")
        else:
            out.bad(f"{name}: .env.example exists but .env does not")
    if svc.engine_ok:
        for name in svc.selected():
            if svc.compose.quiet(name, ["config", "-q"])[0] == 0:
                out.ok(f"{name}: compose config parses")
            else:
                out.bad(f"{name}: compose config failed - a required value is missing")
    else:
        out.skip("compose config, health and the port audit need the engine")
    _doctor_memory_backend(svc)


def _doctor_memory_backend(svc: Services) -> None:
    out = svc.out
    out.section("memory backend")
    backend = store.get("memoryBackend", "agentmemory")
    derived = store.get("agentmemoryEnabled", "off")
    out.ok(f"backend: {backend}")
    # Derived state that has drifted is worse than either state on its own: it
    # means something wrote agentmemoryEnabled without going through
    # `tstack config memory`, and the machine is now half-configured for two
    # memory systems.
    expected = {"agentmemory": "on", "headroom": "off", "none": "off"}.get(backend)
    if expected is None or store.normalise(derived) != store.normalise(expected):
        out.bad(
            f"memoryBackend is '{backend}' but agentmemoryEnabled is '{derived}' - "
            f"fix: tstack config memory {backend}"
        )
    if not svc.engine_ok:
        return
    _, cmd = stacks.docker(
        svc.kind, ["inspect", "ts-headroom-proxy", "--format", "{{json .Config.Cmd}}"]
    )
    _, qdrant = stacks.docker(
        svc.kind, ["ps", "--filter", "name=ts-headroom-qdrant", "--format", "{{.Names}}"]
    )
    _, neo4j = stacks.docker(
        svc.kind, ["ps", "--filter", "name=ts-headroom-neo4j", "--format", "{{.Names}}"]
    )
    if backend == "headroom":
        if not cmd.strip():
            out.skip("headroom proxy is not running")
        elif "--memory" in cmd:
            out.ok("the proxy is running with --memory")
        else:
            # THE bug this whole setting came from: databases up, memory never
            # engaged, everything reporting healthy.
            out.bad(
                "memoryBackend is headroom but the proxy is running WITHOUT --memory: "
                "it stores nothing, and Qdrant and Neo4j will stay empty - "
                "tstack services restart headroom"
            )
        if not (qdrant.strip() and neo4j.strip()):
            out.bad(
                "headroom memory is selected but Qdrant/Neo4j are not both running - "
                "tstack services up headroom"
            )
    elif qdrant.strip() or neo4j.strip():
        print(
            f"  note: Qdrant/Neo4j are still running but this machine's memory backend is "
            f"'{backend}', so nothing writes to them."
        )
        print(
            "        Clear them out with:  tstack services down headroom && tstack services up headroom"
        )


# ---------------------------------------------------------------------- checks


def run_checks(svc: Services, stack: str) -> bool:
    files = stacks.check_files(svc.source, stack)
    if not files:
        svc.out.info(f"{stack}: no ts-checks.conf")
        return True
    ok = True
    for path in files:
        for check in stacks.read_checks(path):
            ok = _run_one_check(svc, stack, check) and ok
    return ok


def _run_one_check(svc: Services, stack: str, check: stacks.Check) -> bool:
    out = svc.out
    secs = int(check.secs) if check.secs.isdigit() else 60
    if check.kind == "health":
        if _wait_healthy(svc, check.id, secs):
            out.passed(f"{stack}/{check.id} healthy")
            return True
        out.failed(f"{stack}/{check.id} not healthy within {secs}s")
        _, logs = stacks.docker(svc.kind, ["logs", "--tail", "40", check.id])
        for line in logs.splitlines()[-40:]:
            print(f"        {line}")
        return False
    if check.kind == "http":
        # Any response means something is listening. A 404 or a 401 is not
        # "down" -- that distinction is why there are two kinds here.
        if _wait_http(check.target, secs, "any"):
            out.passed(f"{stack}/{check.id} answering")
            return True
        out.failed(f"{stack}/{check.id} no response from {check.target} in {secs}s")
        return False
    if check.kind == "http-ok":
        if _wait_http(check.target, secs, "2xx"):
            out.passed(f"{stack}/{check.id} 2xx")
            return True
        out.failed(f"{stack}/{check.id} not 2xx from {check.target} in {secs}s")
        return False
    if check.kind == "port":
        verdict = port_publication(svc, check.target)
        if verdict == 0:
            out.passed(f"{stack}/{check.id} published on 127.0.0.1:{check.target}")
            return True
        if verdict == 1:
            out.failed(f"{stack}/{check.id} port {check.target} is published BEYOND loopback")
        else:
            out.failed(f"{stack}/{check.id} port {check.target} is not published at all")
        return False
    out.warn(f"{stack}: unknown check kind '{check.kind}'")
    return True


def _wait_healthy(svc: Services, container: str, secs: int) -> bool:
    """A container is healthy when compose says so; one with NO healthcheck only
    has to be running."""
    waited = 0
    while waited < secs:
        _, state = stacks.docker(svc.kind, ["inspect", "-f", "{{.State.Status}}", container])
        _, health = stacks.docker(
            svc.kind,
            ["inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{end}}", container],
        )
        health = health.strip()
        if health == "healthy":
            return True
        if not health and state.strip() == "running":
            return True
        time.sleep(2)
        waited += 2
    return False


def _wait_http(url: str, secs: int, mode: str) -> bool:
    waited = 0
    while True:
        code = _http_code(url)
        if mode == "any" and code:
            return True
        if mode == "2xx" and 200 <= code < 300:
            return True
        if waited >= secs:
            return False
        time.sleep(2)
        waited += 2


def _http_code(url: str) -> int:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        return int(exc.code)
    except (urllib.error.URLError, OSError, ValueError):
        return 0


def port_publication(svc: Services, port: str) -> int:
    """0 loopback-only, 1 published beyond loopback, 2 NOT PUBLISHED AT ALL.

    Three outcomes, not two, because a check that cannot tell "absent" from "bad"
    reports the wrong one -- which is exactly what happened here.

    Docker collapses contiguous ports into a range, so 3113 appears as
    `127.0.0.1:3112-3113->3112-3113/tcp` and a literal `:3113->` finds nothing.
    """
    if not port.isdigit():
        return 2
    wanted = int(port)
    _, blob = stacks.docker(svc.kind, ["ps", "--format", "{{.Ports}}"])
    found = False
    for chunk in blob.replace(",", "\n").splitlines():
        line = chunk.strip()
        if "->" not in line or ":" not in line:
            continue
        addr, _, rest = line.partition(":")
        span = rest.split("->")[0]
        low, _, high = span.partition("-")
        high = high or low
        if not (low.isdigit() and high.isdigit()):
            continue
        if not int(low) <= wanted <= int(high):
            continue
        found = True
        if addr.strip() != "127.0.0.1":
            return 1
    return 0 if found else 2


def audit_loopback(svc: Services) -> list[str]:
    """Every published port of every container THIS STACK owns.

    Scoped to ts- containers on purpose: a developer's own projects legitimately
    publish on 0.0.0.0, and failing this check on them is noise -- which is how the
    one check that must never be skipped ends up ignored.
    """
    _, blob = stacks.docker(
        svc.kind, ["ps", "--filter", "name=ts-", "--format", "{{.Names}} {{.Ports}}"]
    )
    bad = []
    for chunk in blob.replace(",", "\n").splitlines():
        line = chunk.strip()
        if "->" not in line:
            continue
        if "127.0.0.1:" in line:
            continue
        bad.append(line)
    return bad


# ---------------------------------------------------------------------- backup


def backup_all(svc: Services) -> bool:
    out = svc.out
    directory = stacks.backup_dir()
    out.step(f"mkdir -p {directory}")
    if out.apply:
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            return False
        if not stacks.docker_shareable(directory):
            out.warn(
                f"{directory} cannot be bind-mounted by this engine - "
                "set TS_STACK_BACKUP_ROOT under $HOME"
            )
            return False
        (directory / "manifest.txt").write_text("", encoding="utf-8")
    ok = True
    for volume in stacks.data_volumes(svc.kind):
        ok = _backup_volume(svc, volume, directory) and ok
    if ok:
        out.info(f"restore with: tstack services restore {directory.name}")
    return ok


def _backup_volume(svc: Services, volume: str, directory: Path) -> bool:
    """tar one volume, then VERIFY the archive before anything is torn down.

    A backup that is only checked after the teardown is not a backup.
    """
    out = svc.out
    if not stacks.volume_exists(svc.kind, volume):
        out.info(f"{volume} does not exist - skipped")
        return True
    out.step(f"backup {volume}")
    if not out.apply:
        return True
    mount = engine.host_path(directory)
    rc, _ = stacks.docker(
        svc.kind,
        [
            "run",
            "--rm",
            "-v",
            f"{volume}:/from:ro",
            "-v",
            f"{mount}:/to",
            "alpine",
            "sh",
            "-c",
            f"tar -C /from -czf /to/{volume}.tgz .",
        ],
        timeout=3600,
    )
    if rc != 0:
        out.warn(f"{volume}: tar failed")
        return False
    rc, _ = stacks.docker(
        svc.kind,
        [
            "run",
            "--rm",
            "-v",
            f"{mount}:/to:ro",
            "alpine",
            "sh",
            "-c",
            f"tar -tzf /to/{volume}.tgz >/dev/null",
        ],
        timeout=1800,
    )
    if rc != 0:
        out.warn(f"{volume}: the archive does not read back")
        return False
    archive = directory / f"{volume}.tgz"
    size = archive.stat().st_size if archive.is_file() else 0
    if size <= 100:
        out.warn(f"{volume}: archive is suspiciously small ({size} bytes)")
        return False
    with (directory / "manifest.txt").open("a", encoding="utf-8") as manifest:
        manifest.write(f"{volume} {size} {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
    out.passed(f"{volume} -> {archive} ({size} bytes)")
    return True


# ------------------------------------------------------------------ entry point

_HANDLERS = {
    "status": cmd_status,
    "config": cmd_config,
    "logs": cmd_logs,
    "up": cmd_up,
    "down": cmd_down,
    "restart": cmd_restart,
    "bootstrap": cmd_bootstrap,
    "migrate-volumes": cmd_migrate_volumes,
    "test": cmd_test,
    "backup": cmd_backup,
    "reset": cmd_reset,
    "doctor": cmd_doctor,
}


def main(argv: list[str]) -> int:
    # Help before anything else: `tstack services -h` must work on a box where the
    # clone, the config store or docker is the very thing that is broken.
    if argv and argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0

    try:
        args = parse(argv)
    except Usage as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        source = paths.resolve_source_dir()
    except paths.CloneNotFound:
        print(
            "tstack services: cannot locate the service tree (set TERMINAL_STACK_DIR).",
            file=sys.stderr,
        )
        return 1
    if not stacks.stack_root(source).is_dir():
        print(
            "tstack services: cannot locate the service tree (set TERMINAL_STACK_DIR).",
            file=sys.stderr,
        )
        return 1

    svc = Services(source, args)
    if not svc.all_stacks:
        print(
            f"tstack services: no stacks found under {stacks.stack_root(source)}", file=sys.stderr
        )
        return 1

    if args.stack:
        if args.stack not in svc.all_stacks:
            have = " ".join(svc.all_stacks)
            print(f"tstack services: no stack named '{args.stack}' - have: {have}", file=sys.stderr)
            return 2
        svc.stacks = [args.stack]
        args.all = True  # naming a stack is consent
    else:
        svc.stacks = list(svc.all_stacks)

    # Usage errors before anything environmental. `logs` with no stack used to
    # exit 1 on WSL (the pwsh handoff had already happened) and 2 everywhere else,
    # for the same mistake -- a caller cannot key off that.
    if args.cmd == "logs" and not args.stack:
        print("tstack services: logs needs a stack name", file=sys.stderr)
        return 2

    # The engine, and the one path where it is a Windows process talking to a
    # POSIX one. Refuse before anything is torn down rather than after.
    if svc.kind == engine.WSL_SHIM and not args.dry_run:
        reason = engine.require_windows_visible(stacks.stack_root(source))
        if reason and args.cmd not in ("status",):
            print(f"tstack services: {reason}", file=sys.stderr)
            return 1

    if args.start_engine and not svc.engine_ok and svc.kind == engine.NATIVE:
        _start_engine(svc)

    if args.cmd in NEEDS_ENGINE and not svc.engine_ok and not args.dry_run:
        svc.out.warn("container engine unreachable")
        svc.advise(to_stderr=True)
        return 1
    if args.cmd == "status" and not svc.engine_ok and not args.dry_run:
        svc.out.warn("container engine unreachable - reporting the settings only")

    try:
        _HANDLERS[args.cmd](svc)
    except Usage as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except SystemExit as exc:
        return int(exc.code or 0)

    if args.cmd in ("doctor", "status"):
        print()
        if svc.out.issues == 0:
            print(f"tstack services {args.cmd}: all checks passed")
        else:
            print(f"tstack services {args.cmd}: {svc.out.issues} issue(s) found")
            return 1
    if args.dry_run:
        print("\nNothing changed (--dry-run).")
    return 0


def _start_engine(svc: Services) -> None:
    """Launch the engine and wait. Cold starts are slow; 60s produces false failures."""
    system = engine.os_name()
    if system == engine.DARWIN:
        svc.out.step("open -a Docker")
        if not svc.args.dry_run:
            subprocess.run(["open", "-a", "Docker"], check=False, start_new_session=True)
    elif system == engine.LINUX:
        svc.out.step("systemctl start docker")
        if not svc.args.dry_run:
            subprocess.run(
                ["sudo", "systemctl", "start", "docker"], check=False, start_new_session=True
            )
    for _ in range(90):
        if engine.is_up(svc.kind):
            svc.engine_ok = True
            return
        time.sleep(2)
