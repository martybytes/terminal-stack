"""Docker Desktop's WSL integration: telling when it is stale, and recycling it.

THE FAULT. After a Docker Desktop update (and sometimes after a plain restart of
Docker Desktop), this dialog comes up and its Restart button fails the same way:

    running wsl distro proxy in Ubuntu distro: waiting 1m0s for the backend
    socket: running wslexec: ... wsl.exe -d ubuntu -u root -e test -s
    /mnt/wsl/docker-desktop/shared-sockets/host-services/backend.sock: exit status 1

The shared tmpfs under /mnt/wsl belongs to the WSL UTILITY VM, not to Docker
Desktop. The update restarts Docker's backend but the VM keeps running, so the
new backend comes up against the old VM's empty shared directory and never
republishes backend.sock into it. The distro proxy polls for a minute and dies.
"Restart the WSL integration" only re-runs that poll. The one fix is

    docker desktop stop  ->  wsl --shutdown  ->  docker desktop start

which is `tstack services repair`. Two things ride along because they bite in the
same moment: the elevated installer can recreate the Docker WSL disk owned by
Administrators (MountDisk/HCS/E_ACCESSDENIED, engine never starts), and every
container stops with the VM, so the ones that were running are started again.

Never: reset to factory defaults, or `wsl --unregister docker-desktop`. Both
destroy every image and volume, and neither fixes this.

Windows only for the repair, because `wsl --shutdown` from inside WSL kills the
process running it halfway through. Detection works on both sides: inside WSL the
socket is a local path; on Windows it is asked through wsl.exe, and only of a
distro that is already running -- an empty shared directory is NORMAL while every
integrated distro is stopped (Docker publishes only while one runs), so a stopped
distro is "unknown", never "stale".
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import platform as plat
from . import proc

SHARED_SOCK = "/mnt/wsl/docker-desktop/shared-sockets/host-services/backend.sock"
DOCKER_SOCK = "/var/run/docker.sock"

Done = subprocess.CompletedProcess[str] | None

# integration_status() answers
HEALTHY = "healthy"
STALE = "stale"
UNKNOWN = "unknown"  # no integrated distro running, or nothing to ask
NOT_APPLICABLE = "n/a"  # not Windows/WSL, no Docker Desktop, integration off

ENGINE_WAIT = 240  # a cold Docker Desktop start; 60s produces false failures
INTEGRATION_WAIT = 150  # the proxy itself waits 60s per attempt


class Host:
    """Every side effect, in one seam, so the tests can script a whole repair."""

    def run(self, argv: list[str], timeout: int = 60) -> Done:
        env = dict(os.environ, WSL_UTF8="1")  # wsl.exe speaks UTF-16 without it
        return proc.capture(argv, timeout=timeout, env=env)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def monotonic(self) -> float:
        return time.monotonic()

    def is_socket(self, path: str) -> bool:
        try:
            return stat.S_ISSOCK(os.stat(path).st_mode)
        except OSError:
            return False

    def settings_path(self) -> Path | None:
        appdata = os.environ.get("APPDATA")
        return Path(appdata) / "Docker" / "settings-store.json" if appdata else None

    def backend_running(self) -> bool:
        got = self.run(["tasklist.exe", "/FI", "IMAGENAME eq com.docker.backend.exe", "/NH"], 15)
        return "com.docker.backend" in _out(got)


def _ok(got: Done) -> bool:
    return bool(got is not None and got.returncode == 0)


def _out(got: Done) -> str:
    return (got.stdout or "") if got is not None else ""


def _lines(got: Done) -> list[str]:
    if got is None or got.returncode != 0:
        return []
    text = (got.stdout or "").replace("\0", "")
    return [line.strip() for line in text.splitlines() if line.strip()]


# ------------------------------------------------------------------ detection


def wsl_distros(host: Host, running: bool = False) -> list[str]:
    argv = ["wsl.exe", "--list", "--quiet"] + (["--running"] if running else [])
    return _lines(host.run(argv, 20))


def integrated_distros(host: Host) -> list[str]:
    """The distros Docker Desktop integrates with, from its own settings.

    `wsl --list --quiet` puts the default distro first, which is what
    EnableIntegrationWithDefaultWslDistro means. docker-desktop's own distros are
    never a target: they are the engine, not a client of it.
    """
    path = host.settings_path()
    if path is None or not path.is_file():
        return []
    try:
        cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    names = [str(d) for d in cfg.get("IntegratedWslDistros") or [] if d]
    if cfg.get("EnableIntegrationWithDefaultWslDistro"):
        every = wsl_distros(host)
        if every:
            names.append(every[0])
    seen: list[str] = []
    for name in names:
        if name.lower().startswith("docker-desktop"):
            continue
        if name.lower() not in (s.lower() for s in seen):
            seen.append(name)
    return seen


@dataclass
class DistroState:
    distro: str
    reachable: bool = False
    backend_sock: bool = False
    docker_sock: bool = False
    cli: bool = False
    server: str = ""

    def line(self) -> str:
        if self.cli:
            return f"{self.distro}: docker works inside the distro (server {self.server})"
        return (
            f"{self.distro}: reachable={self.reachable} backend.sock={self.backend_sock} "
            f"docker.sock={self.docker_sock} docker-cli={self.cli}"
        )


def probe_distro(host: Host, distro: str) -> DistroState:
    """Ground truth from inside the distro. Boots it, which Docker's agent does anyway."""
    st = DistroState(distro)
    st.reachable = _ok(host.run(["wsl.exe", "-d", distro, "-e", "true"], 60))
    if not st.reachable:
        return st
    test = ["wsl.exe", "-d", distro, "-u", "root", "-e", "test", "-S"]
    st.backend_sock = _ok(host.run([*test, SHARED_SOCK], 20))
    st.docker_sock = _ok(host.run([*test, DOCKER_SOCK], 20))
    got = host.run(
        ["wsl.exe", "-d", distro, "-e", "docker", "version", "--format", "{{.Server.Version}}"], 30
    )
    if _ok(got) and _out(got).strip():
        st.cli = True
        st.server = _out(got).strip()
    return st


def integration_status(host: Host | None = None) -> tuple[str, list[str]]:
    """(HEALTHY|STALE|UNKNOWN|NOT_APPLICABLE, the distros that decided it).

    Never boots a distro and never starts anything: doctor and the wizard call it.
    """
    host = host or Host()
    kind = plat.kind()
    if kind == plat.WSL:
        # This distro is running by definition. The integration's mark is the
        # shared mount existing at all; without it Docker Desktop is not
        # integrating here, which is a setting, not this fault.
        if not Path("/mnt/wsl/docker-desktop").is_dir():
            return (NOT_APPLICABLE, [])
        name = os.environ.get("WSL_DISTRO_NAME", "this distro")
        return (HEALTHY if host.is_socket(SHARED_SOCK) else STALE, [name])
    if kind != plat.WINDOWS:
        return (NOT_APPLICABLE, [])
    if not shutil.which("wsl.exe") or not host.backend_running():
        return (NOT_APPLICABLE, [])
    targets = integrated_distros(host)
    if not targets:
        return (NOT_APPLICABLE, [])
    running = {d.lower() for d in wsl_distros(host, running=True)}
    live = [d for d in targets if d.lower() in running]
    if not live:
        return (UNKNOWN, targets)
    test = ["-u", "root", "-e", "test", "-S", SHARED_SOCK]
    stale = [d for d in live if not _ok(host.run(["wsl.exe", "-d", d, *test], 20))]
    return (STALE, stale) if stale else (HEALTHY, live)


def wait_status(host: Host, seconds: int) -> tuple[str, list[str]]:
    """integration_status, polled: a freshly started backend publishes within ~a minute."""
    deadline = host.monotonic() + seconds
    while True:
        status = integration_status(host)
        if status[0] != STALE or host.monotonic() >= deadline:
            return status
        host.sleep(5)


# ------------------------------------------------------------------ disk check

# To attach a VHDX, wslservice grants the utility VM's SID access by rewriting the
# file's DACL while impersonating YOU, which needs ownership or WRITE_DAC. The
# elevated installer can recreate a disk owned by Administrators; a normal token
# holds Administrators as deny-only, so the attach fails with E_ACCESSDENIED.
# ACLs are pwsh's job, so this one check is a pwsh snippet that returns JSON.
_DISK_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$me = [Security.Principal.WindowsIdentity]::GetCurrent()
$roots = @()
$link = Join-Path $env:LOCALAPPDATA 'Docker\wsl'
if (Test-Path $link) {
  $i = Get-Item $link -Force
  if ($i.LinkType) { $roots += [string]$i.Target } else { $roots += $link }
}
Get-ChildItem HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss | ForEach-Object {
  $p = Get-ItemProperty $_.PSPath
  if ($p.DistributionName -eq 'docker-desktop') {
    $parent = Split-Path ($p.BasePath -replace '^\\\\\?\\', '') -Parent
    if ($parent) { $roots += $parent }
  }
}
$bad = @()
foreach ($r in ($roots | Select-Object -Unique)) {
  foreach ($t in @(Get-ChildItem $r -Recurse -Filter *.vhdx -File)) {
    $acl = Get-Acl $t.FullName
    $mine = $acl.Access | Where-Object {
      $_.AccessControlType -eq 'Allow' -and
      ($_.IdentityReference.Value -eq $me.Name -or $_.IdentityReference.Value -eq $me.User.Value) -and
      (($_.FileSystemRights -band [Security.AccessControl.FileSystemRights]::ChangePermissions) -ne 0)
    }
    if (-not ($acl.Owner -eq $me.Name -or $mine)) { $bad += [string]$t.DirectoryName }
  }
}
[pscustomobject]@{ me = $me.Name; dirs = @($bad | Select-Object -Unique) } | ConvertTo-Json -Compress
"""


def disk_fix_lines(host: Host) -> list[str]:
    """The elevated icacls lines that make every Docker WSL disk attachable; [] if fine.

    Never elevates and never runs them: that is the user's call, from an admin shell.
    A pwsh that cannot run counts as fine -- this is a second opinion, not a gate.
    """
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        return []
    got = host.run([shell, "-NoProfile", "-NonInteractive", "-Command", _DISK_PS], 120)
    if not _ok(got):
        return []
    try:
        data = json.loads(_out(got).strip().splitlines()[-1])
    except (ValueError, IndexError):
        return []
    me = data.get("me") or ""
    dirs = data.get("dirs") or []
    if isinstance(dirs, str):  # ConvertTo-Json unwraps a one-element array
        dirs = [dirs]
    out: list[str] = []
    for d in dirs:
        out.append(f'icacls "{d}" /setowner "{me}" /T /C')
        out.append(f'icacls "{d}" /grant "{me}:(OI)(CI)F" /T /C')
    return out


# ---------------------------------------------------------------------- repair


@dataclass
class Container:
    name: str
    restart: str = ""


@dataclass
class Repair:
    """`tstack services repair`, step by step. say/ask are the terminal."""

    say: Callable[[str], None]
    ask: Callable[[str], str | None]
    host: Host = field(default_factory=Host)
    assume_yes: bool = False
    update: bool = False
    hello_world: bool = True
    distros: list[str] = field(default_factory=list)

    # -- helpers --

    def confirm(self, prompt: str, default_yes: bool = True) -> bool:
        if self.assume_yes:
            self.say(f"  {prompt} (--yes)")
            return True
        answer = self.ask(f"  {prompt} {'[Y/n]' if default_yes else '[y/N]'} ")
        if answer is None:
            return False
        answer = answer.strip().lower()
        return answer in ("y", "yes") or (default_yes and answer == "")

    def docker(self, *args: str, timeout: int = 60) -> Done:
        return self.host.run(["docker", *args], timeout)

    def engine_up(self) -> bool:
        return _ok(self.docker("info", "--format", "{{.ServerVersion}}", timeout=30))

    def engine_name(self) -> str:
        got = self.docker("version", "--format", "{{.Server.Platform.Name}}", timeout=30)
        return _out(got).strip() if _ok(got) else ""

    def wait(self, ready: Callable[[], bool], seconds: int, every: int = 5) -> bool:
        deadline = self.host.monotonic() + seconds
        while True:
            if ready():
                return True
            if self.host.monotonic() >= deadline:
                return False
            self.host.sleep(every)

    def snapshot(self) -> list[Container]:
        ids = _lines(self.docker("ps", "-q", timeout=30))
        if not ids:
            return []
        got = self.docker("inspect", *ids, timeout=60)
        try:
            rows = json.loads(_out(got)) if _ok(got) else []
        except ValueError:
            rows = []
        return [
            Container(
                str(r.get("Name", "")).lstrip("/"),
                str(((r.get("HostConfig") or {}).get("RestartPolicy") or {}).get("Name", "")),
            )
            for r in rows
            if r.get("Name")
        ]

    # -- the steps --

    def recycle(self) -> bool:
        self.say("  >> docker desktop stop")
        self.docker("desktop", "stop", timeout=180)
        if not self.wait(lambda: not self.host.backend_running(), 60, every=2):
            self.say("  [WARN] com.docker.backend still running after 60s - continuing anyway")

        self.say("  >> wsl --shutdown   (a fresh WSL VM is a fresh shared-socket mount)")
        self.host.run(["wsl.exe", "--shutdown"], 120)
        self.host.sleep(3)
        still = wsl_distros(self.host, running=True)
        if still:
            self.say(f"  [WARN] still running after shutdown: {', '.join(still)}")
        else:
            self.say("  [ OK ] every WSL distro stopped")

        fix = disk_fix_lines(self.host)
        if fix:
            self.say(
                "  [FAIL] a Docker WSL disk is not attachable by you (MountDisk E_ACCESSDENIED:"
            )
            self.say(
                "         the elevated installer re-owned it). The engine will not start until"
            )
            self.say(
                "         these run from an ELEVATED PowerShell (Docker is stopped, so now is safe):"
            )
            for line in fix:
                self.say(f"           {line}")
            self.ask("  Press Enter once they have run ")
            if disk_fix_lines(self.host):
                self.say("  [FAIL] disk ownership is still wrong")
            else:
                self.say("  [ OK ] disk ownership fixed")
        else:
            self.say("  [ OK ] every Docker WSL disk is attachable (no E_ACCESSDENIED risk)")

        self.say("  >> docker desktop start")
        self.docker("desktop", "start", timeout=300)
        if self.wait(self.engine_up, ENGINE_WAIT):
            self.say(f"  [ OK ] engine is up: {self.engine_name()}")
            return True
        self.say(f"  [FAIL] the engine did not come up within {ENGINE_WAIT // 60} minutes")
        return False

    def verify(self, targets: list[str]) -> list[DistroState]:
        states: list[DistroState] = []

        def all_cli() -> bool:
            nonlocal states
            states = [probe_distro(self.host, d) for d in targets]
            return all(s.cli for s in states)

        self.wait(all_cli, INTEGRATION_WAIT, every=10)
        for s in states:
            self.say(f"  [{' OK ' if s.cli else 'FAIL'}] {s.line()}")
        return states

    def restore(self, before: list[Container]) -> None:
        if not before:
            self.say("  no containers were running before - nothing to restore")
            return
        self.host.sleep(10)  # restart-policy containers come back on their own
        now = set(_lines(self.docker("ps", "--format", "{{.Names}}", timeout=30)))
        missing = [c for c in before if c.name not in now]
        if not missing:
            self.say(f"  [ OK ] all {len(before)} previously running container(s) are running")
            return
        names = ", ".join(f"{c.name} [restart={c.restart or 'no'}]" for c in missing)
        self.say(f"  [WARN] {len(missing)} container(s) that were running are not: {names}")
        if not self.confirm("Start them again?"):
            return
        for c in missing:
            if _ok(self.docker("start", c.name, timeout=120)):
                self.say(f"  [ OK ] started {c.name}")
            else:
                self.say(f"  [FAIL] could not start {c.name} - check: docker logs {c.name}")

    def run(self) -> int:
        if plat.kind() == plat.WSL:
            self.say("tstack services repair: run it from PowerShell on Windows, not from WSL -")
            self.say("  it runs `wsl --shutdown`, which would kill this shell halfway through.")
            return 1
        if plat.kind() != plat.WINDOWS:
            self.say("tstack services repair: Docker Desktop's WSL integration is Windows-only.")
            return 1
        if not shutil.which("docker"):
            self.say("tstack services repair: docker is not on PATH (is Docker Desktop installed?)")
            return 1

        self.say("== 1. Current state")
        before: list[Container] = []
        version_before = ""
        if self.engine_up():
            version_before = self.engine_name()
            before = self.snapshot()
            self.say(f"  [ OK ] engine running: {version_before}")
            listed = ", ".join(c.name for c in before) or "(none)"
            self.say(f"  running containers: {listed}")
        else:
            self.say("  [WARN] the engine is not running (fine mid-update or mid-recovery)")
        targets = self.distros or integrated_distros(self.host)
        self.say(f"  distros to verify: {', '.join(targets) or '(none - WSL integration is off)'}")
        running = wsl_distros(self.host, running=True)
        self.say(f"  WSL distros running: {', '.join(running) or '(none)'}")
        self.say("")
        self.say("  This STOPS Docker Desktop and runs `wsl --shutdown`:")
        self.say("    - every open WSL terminal closes (save work in WSL first)")
        self.say("    - every container stops; the ones running now are started again")

        if self.update:
            self.say("== 2. Update Docker Desktop")
            if not self.confirm("Ready to update?"):
                self.say("  aborted - nothing changed.")
                return 0
            self.say('  In Docker Desktop, click "Update version" and let it install. If the')
            self.say('  "unexpectedly stopped" WSL dialog appears, IGNORE it (its Restart button')
            self.say("  cannot work yet). Wait until Docker Desktop has relaunched.")
            if not self.assume_yes:
                self.ask("  Press Enter when done ")
            version_now = self.engine_name()
            if version_before and version_now == version_before:
                self.say(f"  [WARN] still '{version_now}' - the update may not have applied")
                if not self.confirm("Run the repair anyway?"):
                    return 0
            elif version_now:
                self.say(f"  [ OK ] now running: {version_now}")
        elif not self.confirm("Run the repair now (stop Docker, wsl --shutdown, start)?"):
            self.say("  aborted - nothing changed.")
            return 0

        self.say("== 3. Recycle Docker Desktop on a fresh WSL VM")
        if not before and self.engine_up():  # it came up during the update
            before = self.snapshot()
        engine_ok = self.recycle()

        states: list[DistroState] = []
        hello_failed = False
        if engine_ok and targets:
            self.say("== 4. Verify WSL integration")
            states = self.verify(targets)
            if not all(s.cli for s in states):
                self.say("  [WARN] integration did not come up; recycling once more")
                engine_ok = self.recycle()
                if engine_ok:
                    states = self.verify(targets)
            if self.hello_world and states and all(s.cli for s in states):
                d = targets[0]
                got = self.host.run(
                    ["wsl.exe", "-d", d, "-e", "docker", "run", "--rm", "hello-world"], 300
                )
                blob = (got.stdout or "") + (got.stderr or "") if got else ""
                if "Hello from Docker" in blob:
                    self.say(f"  [ OK ] {d}: docker run hello-world works")
                else:
                    self.say(f"  [FAIL] {d}: hello-world failed")
                    hello_failed = True

        if engine_ok:
            self.say("== 5. Containers")
            self.restore(before)

        self.say("== Result")
        failed = (not engine_ok) or hello_failed or any(not s.cli for s in states)
        if not failed:
            self.say(f"  [ OK ] {self.engine_name()} is healthy and the WSL integration works.")
            self.say(
                '  A stale "unexpectedly stopped" dialog from before can be closed with its X.'
            )
            self.say("  Agents connected to MCP servers in containers need to reconnect (/mcp).")
            return 0
        self.say("  [FAIL] not fully healthy. Do NOT reset Docker Desktop to factory defaults or")
        self.say("         `wsl --unregister docker-desktop`: both destroy every image and volume.")
        self.say("  See: doc windows/docker-desktop")
        return 1


STALE_ADVICE = (
    "Docker Desktop's WSL integration is stale (backend.sock never reached the distro); "
    "its Restart button cannot fix this"
)
STALE_FIX = "fix: tstack services repair  (from PowerShell; closes every WSL shell)"
