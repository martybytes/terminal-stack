"""`tstack agents` - the user-global Headroom, Caveman and AgentMemory wiring.

Replaces bootstrap/ts-agents.sh (359 lines) and bootstrap/ts-agents.ps1 (431).
Docker services and project repositories are deliberately out of scope: this
command may PROBE a container and print a `tstack services` verb, but it may never
run docker to change one. `tests/test_agent_tools.py` enforces that as a substring
match over the whole file, so not even a comment may name the compose command.

The two twins had drifted, and the merge takes the union rather than either side:

- The pwsh status checked the Claude plugin list, the global skill file, the
  AgentMemory viewer and a TCP fallback; the bash status checked none of them.
- The bash status probed the AgentMemory REST URL with a plain request because
  that service answers 404 on `/` and 401 on `/health`, so `curl -fsS` reported it
  DOWN while it was up. That rule is kept and now applies on both platforms.

ONE THING IS NOT A MERGE. On a combined Windows/WSL install the GUI agents and
their user configuration live on WINDOWS: `~/.claude.json`, `~/.cursor/mcp.json`
and the Codex home are Windows-side files, and the `claude`/`codex` CLIs that own
them are Windows processes. The bash twin handled that by re-exec'ing the pwsh
twin through interop. There is one implementation now, so it re-execs ITSELF under
the Windows Python instead - same code, right side of the boundary.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import paths
from .. import platform as plat

HELP = """tstack agents - user-global Headroom, Caveman and AgentMemory wiring.

Usage:
  tstack agents [<tool>] [<action>] [<cursor-mode>]

  <tool>         all (default) | headroom | caveman | agentmemory
  <action>       status (default) | on | off | repair | uninstall | dashboard
  <cursor-mode>  mcp (default) | byok | off      (headroom only)

  status     what is wired up, and what is missing
  on         install/enable and wire this host's agents to it
  repair     the same, run again - a plugin upgrade silently reverts the wiring
  off        remove the client wiring; data, containers and secrets are untouched
  uninstall  also remove the terminal-stack-owned client pieces

Docker is out of scope here: this command probes a service and names the
`tstack services` verb, it never starts or stops one."""

TOOLS = ("all", "headroom", "caveman", "agentmemory")
ACTIONS = ("status", "on", "off", "repair", "uninstall", "dashboard")
CURSOR_MODES = ("mcp", "byok", "off")

CAVEMAN_START = "<!-- terminal-stack-caveman-start -->"
CAVEMAN_END = "<!-- terminal-stack-caveman-end -->"
CAVEMAN_RULE = (
    "Caveman is enabled globally. Apply the installed caveman skill to every "
    "response; use full mode unless the user asks otherwise."
)


class Out:
    """The gutter this subsystem has always used: two spaces, then ok/!!/nothing."""

    def __init__(self) -> None:
        self.failures = 0

    def info(self, message: str) -> None:
        print(f"  {message}")

    def good(self, message: str) -> None:
        print(f"  ok  {message}")

    def bad(self, message: str) -> None:
        self.failures += 1
        print(f"  !!  {message}")


# ------------------------------------------------------------------- platform


def user_root() -> Path:
    """The home directory whose agent configuration counts.

    On WSL that is the WINDOWS profile: `~/.claude.json` and `~/.cursor/mcp.json`
    belong to the GUI agents, which are Windows processes. Getting this wrong
    writes a registration into the WSL home that nothing ever reads.
    """
    if plat.kind() == plat.WSL:
        user = plat.windows_username()
        if user:
            candidate = Path(f"/mnt/c/Users/{user}")
            if candidate.is_dir():
                return candidate
    return Path.home()


def find_windows_python() -> str | None:
    """A Windows Python reachable from WSL, for the re-exec."""
    for name in ("python.exe", "python3.exe", "py.exe"):
        found = shutil.which(name)
        if found:
            return found
    user = plat.windows_username()
    if not user:
        return None
    roots = [
        Path(f"/mnt/c/Users/{user}/AppData/Local/Programs/Python"),
        Path("/mnt/c/Python314"),
        Path("/mnt/c/Python313"),
        Path("/mnt/c/Python312"),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in sorted(root.glob("**/python.exe")):
            return str(candidate)
    return None


def reexec_on_windows(argv: list[str]) -> int | None:
    """Re-run this command under the Windows Python. None when there is none.

    Same code, right side of the boundary. The bash twin re-exec'd the pwsh twin
    here, which is where the two implementations were free to drift.
    """
    if plat.kind() != plat.WSL or os.environ.get("TS_AGENTS_NO_INTEROP"):
        return None
    python = find_windows_python()
    if not python:
        return None
    try:
        source = paths.resolve_source_dir()
    except paths.CloneNotFound:
        return None
    entry = plat.to_windows_path(source / "tstack" / "main.py")
    if not entry:
        return None
    got = subprocess.run(
        [python, entry, "agents", *argv],
        check=False,
        start_new_session=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    return got.returncode


# ------------------------------------------------------------------- manifest


def manifest(source: Path) -> dict:
    """bootstrap/agent-tools.json - the one file where a port, URL, image tag or
    version pin is written down."""
    try:
        return json.loads((source / "bootstrap" / "agent-tools.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def dig(body: dict, dotted: str, default: object = "") -> object:
    node: object = body
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


# ------------------------------------------------------------------ probing


def http_answers(url: str, timeout: int = 2) -> bool:
    """Any HTTP response means something is listening.

    NOT a 2xx check: AgentMemory answers 404 on `/` and 401 on `/health`, so a
    strict probe reported the service DOWN while it was up and serving.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except urllib.error.HTTPError:
        return True
    except (urllib.error.URLError, OSError, ValueError):
        return False


def tcp_answers(host: str, port: int, timeout: float = 1.0) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _run(
    argv: list[str], timeout: int = 60, stdin: str | None = None
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def find_agent(name: str) -> str | None:
    """A vendor CLI. On WSL the Windows .exe counts, since that is the one whose
    configuration this command edits."""
    for candidate in (name, f"{name}.exe") if plat.kind() == plat.WSL else (name,):
        found = shutil.which(candidate)
        if found:
            return found
    return None


# ------------------------------------------------------------------ headroom


class Headroom:
    def __init__(self, source: Path, out: Out, cursor_mode: str) -> None:
        self.source = source
        self.out = out
        self.cursor_mode = cursor_mode
        self.body = manifest(source)
        self.mcp_reason = ""

    # -- token and proxy ----------------------------------------------------

    def token(self) -> str:
        """HEADROOM_PROXY_TOKEN, from the environment or the stack's own .env.

        The stack tree is always <clone>/services/, so there is nothing to search
        for. HEADROOM_ENV_FILE stays the documented override. Never printed.
        """
        env = os.environ.get("HEADROOM_PROXY_TOKEN")
        if env:
            return env
        override = os.environ.get("HEADROOM_ENV_FILE")
        path = (
            Path(override)
            if override
            else self.source / "services" / "stacks" / "headroom" / ".env"
        )
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("HEADROOM_PROXY_TOKEN="):
                    return line.split("=", 1)[1].strip()
        except OSError:
            return ""
        return ""

    def probe_auth(self) -> tuple[bool, str]:
        """(ok, why). Retried ONCE, and only on a connection failure.

        A real HTTP answer (401, 500) is conclusive. One 2s attempt reported a
        cold container as broken, and `on`/`repair` gate on this, so a slow first
        hit turned into "registrations were not changed" with nothing to act on.
        """
        token = self.token()
        if not token:
            return (False, "proxy token unavailable; set HEADROOM_PROXY_TOKEN or HEADROOM_ENV_FILE")
        proxy = str(dig(self.body, "headroom.proxyUrl"))
        for attempt in (1, 2):
            request = urllib.request.Request(
                f"{proxy}/stats", headers={"X-Headroom-Proxy-Token": token}
            )
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    if 200 <= response.status < 300:
                        return (True, "")
                    return (False, f"HTTP {response.status}")
            except urllib.error.HTTPError as exc:
                return (False, f"HTTP {exc.code}")
            except (urllib.error.URLError, OSError):
                if attempt == 2:
                    return (False, "unreachable")
        return (False, "unreachable")

    # -- the MCP server -----------------------------------------------------

    def mcp_spec(self) -> tuple[str, list[str]] | None:
        """(command, args) for the stdio MCP server, or None with a reason set."""
        self.mcp_reason = ""
        docker = shutil.which("docker")
        if not docker:
            self.mcp_reason = "docker command not installed"
            return None
        args = [
            "exec",
            "-i",
            str(dig(self.body, "headroom.mcp.container")),
            str(dig(self.body, "headroom.mcp.command")),
        ]
        extra = dig(self.body, "headroom.mcp.args", [])
        args += [str(a) for a in extra] if isinstance(extra, list) else []
        return (docker, args)

    def mcp_ready(self) -> bool:
        """A JSON-RPC initialize handshake, not a port check.

        Registering an MCP server that does not answer leaves every client
        retrying a broken command on every start, silently.
        """
        spec = self.mcp_spec()
        if not spec:
            return False
        command, args = spec
        initialize = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "terminal-stack", "version": "1"},
                },
            }
        )
        got = _run([command, *args], timeout=30, stdin=initialize + "\n")
        if not got or got.returncode != 0:
            self.mcp_reason = "docker MCP command failed"
            return False
        for line in got.stdout.splitlines():
            try:
                message = json.loads(line)
            except ValueError:
                continue
            result = message.get("result", {})
            if (
                message.get("id") == 1
                and result.get("serverInfo", {}).get("name") == "headroom"
                and result.get("capabilities", {}).get("tools") is not None
            ):
                return True
        self.mcp_reason = "initialize response was not a Headroom MCP server"
        return False

    # -- client registrations ----------------------------------------------

    def claude_registered(self, spec: tuple[str, list[str]]) -> bool:
        return _json_mcp_matches(user_root() / ".claude.json", "headroom", spec)

    def cursor_registered(self, spec: tuple[str, list[str]]) -> bool:
        return _json_mcp_matches(user_root() / ".cursor" / "mcp.json", "headroom", spec)

    def codex_registered(self, spec: tuple[str, list[str]]) -> bool:
        codex = find_agent("codex")
        if not codex:
            return False
        got = _run([codex, "mcp", "get", "headroom"], timeout=30)
        if not got or got.returncode != 0:
            return False
        text = got.stdout
        if not any(
            line.strip() == "transport: stdio" or line.strip().startswith("transport: stdio")
            for line in text.splitlines()
        ):
            return False
        if f"command: {spec[0]}" not in text:
            return False
        return all(arg in text for arg in spec[1])

    def register(self, add: bool) -> None:
        spec = self.mcp_spec()
        ready = bool(spec) and self.mcp_ready()
        claude = find_agent("claude")
        codex = find_agent("codex")

        if add and ready and spec:
            command, args = spec
            if claude:
                _run([claude, "mcp", "remove", "--scope", "user", "headroom"], timeout=60)
                _run(
                    [claude, "mcp", "add", "--scope", "user", "headroom", "--", command, *args],
                    timeout=60,
                )
            else:
                self.out.info("Claude Code not installed; skipped Headroom MCP registration")
            if codex:
                _run([codex, "mcp", "remove", "headroom"], timeout=60)
                _run([codex, "mcp", "add", "headroom", "--", command, *args], timeout=60)
            else:
                self.out.info("Codex not installed; skipped Headroom MCP registration")
            if self.cursor_mode == "mcp" and (user_root() / ".cursor").is_dir():
                _write_cursor_mcp("headroom", {"command": command, "args": args})
                self.out.good("Cursor Headroom MCP registered at user scope")
            elif self.cursor_mode == "byok":
                _write_cursor_mcp("headroom", None)
                self.out.info(
                    "Cursor BYOK selected: set the global provider base URL to "
                    "http://127.0.0.1:8787 and use a provider API key."
                )
                self.out.info(
                    "Cursor subscription traffic cannot be redirected through a custom base URL."
                )
            else:
                _write_cursor_mcp("headroom", None)
            return

        if claude:
            _run([claude, "mcp", "remove", "--scope", "user", "headroom"], timeout=60)
        if codex:
            _run([codex, "mcp", "remove", "headroom"], timeout=60)
        _write_cursor_mcp("headroom", None)
        if add:
            self.out.info(
                f"optional Headroom MCP failed its initialize handshake ({self.mcp_reason}); "
                "removed stale client registrations"
            )

    # -- report -------------------------------------------------------------

    def status(self) -> bool:
        print("Headroom:")
        proxy = str(dig(self.body, "headroom.proxyUrl"))
        ok, why = self.probe_auth()
        if ok:
            self.out.good(f"proxy authentication works at {proxy}")
        else:
            self.out.bad(f"proxy unusable at {proxy} ({why}) - tstack services runs the proxy")

        spec = self.mcp_spec()
        ready = bool(spec) and self.mcp_ready()
        if ready:
            self.out.good("MCP stdio initialize handshake works through Headroom container")
        else:
            self.out.info(f"MCP stdio initialize handshake failed ({self.mcp_reason})")

        if find_agent("claude"):
            if spec and self.claude_registered(spec):
                self.out.good("Claude user-scope MCP registration present")
            elif ready:
                self.out.bad("Claude user-scope MCP registration missing or stale")
            else:
                self.out.info(
                    "Claude Headroom MCP registration absent while MCP command is "
                    "unavailable (expected)"
                )
        if find_agent("codex"):
            if spec and self.codex_registered(spec):
                self.out.good("Codex user-scope MCP registration present")
            elif ready:
                self.out.bad("Codex user-scope MCP registration missing or stale")
            else:
                self.out.info(
                    "Codex Headroom MCP registration absent while MCP command is "
                    "unavailable (expected)"
                )
        if self.cursor_mode == "mcp" and (user_root() / ".cursor").is_dir():
            if spec and self.cursor_registered(spec):
                self.out.good("Cursor user-scope MCP registration present")
            else:
                self.out.bad("Cursor user-scope MCP registration missing or stale")

        self.out.info(f"dashboard: {dig(self.body, 'headroom.dashboardUrl')}")
        self.out.info(
            f"pinned compatibility: {dig(self.body, 'headroom.version')} "
            f"({dig(self.body, 'headroom.dockerImage')})"
        )
        return ok

    def run(self, action: str) -> int:
        if action == "dashboard":
            url = str(dig(self.body, "headroom.dashboardUrl"))
            _open_url(url)
            return 0
        if action == "status":
            return 0 if self.status() else 1
        if action in ("on", "repair"):
            ok, why = self.probe_auth()
            if not ok:
                tail = (
                    "leaving direct mode unchanged"
                    if action == "on"
                    else "registrations were not changed"
                )
                self.out.bad(f"Headroom proxy authentication failed ({why}); {tail}.")
                return 1
            self.register(add=True)
            self.status()
            return 0
        # off / uninstall
        self.register(add=False)
        self.out.info("Headroom routing and MCP registrations removed; Docker was not changed.")
        return 0


def _open_url(url: str) -> None:
    if plat.kind() == plat.WINDOWS:
        _run(["cmd.exe", "/c", "start", "", url], timeout=15)
    elif plat.kind() == plat.MACOS:
        _run(["open", url], timeout=15)
    elif shutil.which("xdg-open"):
        _run(["xdg-open", url], timeout=15)
    else:
        print(f"  {url}")


def _read_json(path: Path, default: dict) -> dict | None:
    """None means "present but unparseable", which must never be overwritten."""
    if not path.is_file():
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _backup(path: Path) -> None:
    """<path>.bak.YYYYMMDD, never clobbering a same-day backup."""
    if not path.is_file():
        return
    stamp = time.strftime("%Y%m%d")
    candidate = path.with_name(f"{path.name}.bak.{stamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak.{stamp}.{counter}")
        counter += 1
    candidate.write_bytes(path.read_bytes())


def _write_cursor_mcp(name: str, entry: dict | None) -> None:
    path = user_root() / ".cursor" / "mcp.json"
    body = _read_json(path, {"mcpServers": {}})
    if body is None:
        print(f"  !!  refusing to overwrite malformed JSON: {path}", file=sys.stderr)
        return
    servers = body.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        servers = {}
        body["mcpServers"] = servers
    if entry is None:
        servers.pop(name, None)
    else:
        servers[name] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    path.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def _json_mcp_matches(path: Path, name: str, spec: tuple[str, list[str]]) -> bool:
    body = _read_json(path, {})
    if not body:
        return False
    entry = body.get("mcpServers", {}).get(name, {})
    return entry.get("command") == spec[0] and list(entry.get("args", [])) == list(spec[1])


# ------------------------------------------------------------------- caveman


def codex_home() -> Path:
    override = os.environ.get("CODEX_HOME")
    if override:
        return Path(override)
    return user_root() / ".codex"


def caveman_rule(enable: bool) -> None:
    """The always-on rule in Codex's global AGENTS.md, between two markers.

    Marker-delimited, never whole-file: that file is the user's, and everything
    outside the markers has to survive.
    """
    path = codex_home() / "AGENTS.md"
    lines: list[str] = []
    if path.is_file():
        skip = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if CAVEMAN_START in line:
                skip = True
                continue
            if CAVEMAN_END in line:
                skip = False
                continue
            if not skip:
                lines.append(line)
    if enable:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [CAVEMAN_START, CAVEMAN_RULE, CAVEMAN_END]
    path.parent.mkdir(parents=True, exist_ok=True)
    _backup(path)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class Caveman:
    def __init__(self, source: Path, out: Out) -> None:
        self.source = source
        self.out = out
        self.body = manifest(source)

    def install(self) -> None:
        claude = find_agent("claude")
        if claude:
            for argv in (
                [
                    "plugin",
                    "marketplace",
                    "add",
                    str(dig(self.body, "caveman.claudeMarketplace")),
                    "--scope",
                    "user",
                ],
                ["plugin", "install", "caveman@caveman", "--scope", "user", "-y"],
                ["plugin", "enable", "caveman@caveman", "--scope", "user"],
            ):
                _run([claude, *argv], timeout=600)
        else:
            self.out.info("Claude Code not installed; skipped Caveman plugin")
        npx = find_agent("npx")
        if npx:
            _run(
                [
                    npx,
                    "-y",
                    "skills@latest",
                    "add",
                    str(dig(self.body, "caveman.source")),
                    "-g",
                    "-y",
                    "--copy",
                    "-a",
                    "codex",
                    "cursor",
                    "-s",
                    str(dig(self.body, "caveman.skill")),
                ],
                timeout=900,
            )
        else:
            self.out.info("npx not installed; skipped the global Codex/Cursor Caveman skill")
        caveman_rule(True)
        self.out.good(f"Caveman {dig(self.body, 'caveman.version')} enabled for installed agents")
        self.out.info(
            'Cursor: add this once in Settings > Rules > User Rules: "Always apply the '
            'global caveman skill; use full mode unless I ask otherwise."'
        )

    def remove(self, uninstall: bool) -> None:
        claude = find_agent("claude")
        if claude:
            if uninstall:
                _run(
                    [
                        claude,
                        "plugin",
                        "uninstall",
                        "caveman@caveman",
                        "--scope",
                        "user",
                        "--keep-data",
                        "-y",
                    ],
                    timeout=600,
                )
            else:
                _run(
                    [claude, "plugin", "disable", "caveman@caveman", "--scope", "user"],
                    timeout=600,
                )
        npx = find_agent("npx")
        if uninstall and npx:
            _run(
                [
                    npx,
                    "-y",
                    "skills@latest",
                    "remove",
                    "caveman",
                    "-g",
                    "-y",
                    "-a",
                    "codex",
                    "cursor",
                ],
                timeout=900,
            )
        caveman_rule(False)
        preserved = "" if uninstall else "; the downloaded global skill was preserved"
        self.out.info(
            f"Caveman automation removed{preserved}. "
            "Remove the Cursor User Rule manually if you added it."
        )

    def status(self) -> bool:
        print("Caveman:")
        rule = codex_home() / "AGENTS.md"
        present = rule.is_file() and CAVEMAN_START in rule.read_text(
            encoding="utf-8", errors="replace"
        )
        if present:
            self.out.good("Codex global always-on rule present")
        else:
            self.out.bad("Codex global always-on rule absent")
        claude = find_agent("claude")
        if claude:
            got = _run([claude, "plugin", "list", "--json"], timeout=120)
            if got and "caveman@caveman" in (got.stdout or ""):
                self.out.good("Claude Caveman plugin installed")
            else:
                self.out.bad("Claude Caveman plugin not installed")
        skill = user_root() / ".agents" / "skills" / "caveman" / "SKILL.md"
        if skill.is_file():
            self.out.good("global Codex/Cursor caveman skill installed")
        else:
            self.out.bad("global Codex/Cursor caveman skill missing")
        self.out.info(f"pinned version: {dig(self.body, 'caveman.version')}")
        return present

    def run(self, action: str) -> int:
        if action == "status":
            return 0 if self.status() else 1
        if action in ("on", "repair"):
            self.install()
            self.status()
            return 0
        if action in ("off", "uninstall"):
            self.remove(uninstall=action == "uninstall")
            return 0
        self.out.bad(f"Caveman has no '{action}' action")
        return 2


# --------------------------------------------------------------- agentmemory


class AgentMemory:
    def __init__(self, source: Path, out: Out) -> None:
        self.source = source
        self.out = out
        self.body = manifest(source)

    def adapter(self) -> list[str] | None:
        """The hook-wiring adapter, which is still shell on both sides."""
        if plat.kind() == plat.WINDOWS:
            script = self.source / "bootstrap" / "ts-agentmemory.ps1"
            pwsh = plat.find_pwsh()
            if not script.is_file() or not pwsh:
                return None
            return [
                pwsh,
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ]
        script = self.source / "bootstrap" / "ts-agentmemory.sh"
        return ["bash", str(script)] if script.is_file() else None

    def install(self) -> None:
        claude = find_agent("claude")
        if claude:
            source = f"{dig(self.body, 'agentmemory.source')}@{dig(self.body, 'agentmemory.ref')}"
            for argv in (
                ["plugin", "marketplace", "add", source, "--scope", "user"],
                ["plugin", "install", "agentmemory@agentmemory", "--scope", "user", "-y"],
                ["plugin", "enable", "agentmemory@agentmemory", "--scope", "user"],
            ):
                _run([claude, *argv], timeout=600)
        codex = find_agent("codex")
        if codex:
            _run(
                [
                    codex,
                    "plugin",
                    "marketplace",
                    "add",
                    str(dig(self.body, "agentmemory.source")),
                    "--ref",
                    str(dig(self.body, "agentmemory.ref")),
                ],
                timeout=600,
            )
            _run([codex, "plugin", "add", "agentmemory@agentmemory"], timeout=600)
        # Host-side hook wiring. Installing the plugin is only half the job:
        # without the deployment edits the hooks POST nothing and retrieval never
        # fires, and nothing logs it because every vendor hook does
        # fetch(...).catch(() => {}) then exits 0. Re-run on every on/repair,
        # because a plugin upgrade replaces the cache and silently reverts them.
        adapter = self.adapter()
        if adapter:
            got = subprocess.run([*adapter, "--apply"], check=False, start_new_session=True)
            if got.returncode != 0:
                self.out.bad("AgentMemory hook adapter reported problems (see above)")
        self.out.info(
            "AgentMemory plugin enabled. Docker, secrets and server feature flags were not changed."
        )

    def remove(self, uninstall: bool) -> None:
        # Undo the host-side wiring FIRST, while the plugin cache it patched is
        # still present: the restore reads the backups beside the vendor scripts.
        adapter = self.adapter()
        if adapter:
            subprocess.run([*adapter, "--undo", "--apply"], check=False, start_new_session=True)
        claude = find_agent("claude")
        if claude:
            if uninstall:
                _run(
                    [
                        claude,
                        "plugin",
                        "uninstall",
                        "agentmemory@agentmemory",
                        "--scope",
                        "user",
                        "--keep-data",
                        "-y",
                    ],
                    timeout=600,
                )
            else:
                _run(
                    [claude, "plugin", "disable", "agentmemory@agentmemory", "--scope", "user"],
                    timeout=600,
                )
        codex = find_agent("codex")
        if codex:
            _run([codex, "plugin", "remove", "agentmemory@agentmemory"], timeout=600)
        self.out.info(
            "AgentMemory client wiring removed; server, secret, container and data "
            "were not changed."
        )

    def status(self) -> bool:
        print("AgentMemory:")
        rest = str(dig(self.body, "agentmemory.restUrl"))
        viewer = str(dig(self.body, "agentmemory.viewerUrl"))
        # ANY answer proves something is listening. This service returns 404 on /
        # and 401 on /health, and a strict probe called it down while it was up.
        ok = http_answers(rest) or tcp_answers("127.0.0.1", 3111)
        if ok:
            self.out.good(f"REST server reachable at {rest}")
        else:
            self.out.bad(f"REST server not reachable at {rest} - tstack services runs it")
        if http_answers(viewer) or tcp_answers("127.0.0.1", 3113):
            self.out.good(f"viewer reachable at {viewer}")
        else:
            self.out.info(f"viewer not reachable at {viewer}")
        adapter = self.adapter()
        if adapter:
            got = subprocess.run(
                [*adapter, "--check"],
                capture_output=True,
                text=True,
                check=False,
                start_new_session=True,
            )
            if got.returncode == 0:
                self.out.good("agent hook wiring intact")
            else:
                self.out.bad("agent hook wiring incomplete - tstack agents agentmemory repair")
        self.out.info(f"pinned plugin version: {dig(self.body, 'agentmemory.version')}")
        return ok

    def run(self, action: str) -> int:
        if action == "status":
            return 0 if self.status() else 1
        if action in ("on", "repair"):
            self.install()
            self.status()
            return 0
        if action in ("off", "uninstall"):
            self.remove(uninstall=action == "uninstall")
            return 0
        self.out.bad(f"AgentMemory has no '{action}' action")
        return 2


# ----------------------------------------------------------------- entry point


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0

    tool = argv[0] if argv else "all"
    action = argv[1] if len(argv) > 1 else "status"
    cursor_mode = argv[2] if len(argv) > 2 else "mcp"
    if tool not in TOOLS:
        print(f"tstack agents: unknown tool '{tool}'", file=sys.stderr)
        return 2
    if action not in ACTIONS:
        print(f"tstack agents: unknown action '{action}'", file=sys.stderr)
        return 2
    if cursor_mode not in CURSOR_MODES:
        print("tstack agents: cursor mode must be mcp, byok, or off", file=sys.stderr)
        return 2

    # On a combined install the agents and their config live on Windows.
    handed_off = reexec_on_windows(argv)
    if handed_off is not None:
        return handed_off

    try:
        source = paths.resolve_source_dir()
    except paths.CloneNotFound as exc:
        print(f"tstack agents: {exc}", file=sys.stderr)
        return 1

    out = Out()
    runners = {
        "headroom": lambda: Headroom(source, out, cursor_mode).run(action),
        "caveman": lambda: Caveman(source, out).run(action),
        "agentmemory": lambda: AgentMemory(source, out).run(action),
    }
    if tool != "all":
        rc = runners[tool]()
        return 1 if out.failures else rc
    worst = 0
    for name in ("headroom", "caveman", "agentmemory"):
        if action == "dashboard" and name != "headroom":
            continue
        rc = runners[name]()
        worst = worst or rc
    return 1 if out.failures else worst
