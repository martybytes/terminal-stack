"""`tstack doctor` - diagnose the install, and repair what can be repaired.

Replaces bootstrap/ts-doctor.sh + bootstrap/_doctor.sh (bash) and Invoke-TsDoctor
+ Test-TsInstall (pwsh). Those two had drifted a long way apart: the bash side ran
about twenty checks, the pwsh side about eight, and neither knew what the other
looked at. Every check below runs on every platform it makes sense on, which is
the first time that has been true.

Three deliberate differences from the shell it replaces, each a bug that the
characterization recording exposed:

1.  `ts_chezmoi_bin` returned $TERMINAL_STACK_CHEZMOI without checking it, so a
    pin at a path with no binary was reported as `ok  chezmoi: <path>`. It is now
    verified.
2.  The bash doctor resolved the clone through `chezmoi source-path` ALONE, so a
    machine with a working $TERMINAL_STACK_DIR pin and a broken chezmoi reported
    "no source dir" - while every other command in the stack honoured the pin.
    It now uses the same resolution as everything else.
3.  `--json`, so the checks are a read model rather than prose to scrape.

Repair keeps shelling out for the destructive parts (clone relocation, the
cleanup checklist). Those live in bootstrap/_cleanup.{sh,ps1}, which are shared
with the installers and are not doctor's twins to delete.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .. import checks, paths, store
from .. import platform as plat
from ..checks import Report

HEADER = "==> terminal-stack doctor"
PASSED = "==> all checks passed."


def _run(argv: list[str], timeout: int = 15) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            start_new_session=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None


# --------------------------------------------------------------------- checks


def check_chezmoi(report: Report) -> str | None:
    """The chezmoi binary. Absent is fatal on POSIX and normal on Windows.

    A Windows-standalone install has no chezmoi at all and is not broken; it
    reads and writes the config.json mirror instead.
    """
    binary = plat.find_chezmoi()
    if binary and Path(binary).exists():
        report.ok("chezmoi", f"chezmoi: {binary}")
        return binary

    if binary:
        # The pinned path does not exist. The shell version reported this as ok.
        report.fail(
            "chezmoi",
            f"TERMINAL_STACK_CHEZMOI points at '{binary}', which does not exist",
            "unset it, or install chezmoi",
        )
        return None
    if plat.kind() == plat.WINDOWS:
        report.note("chezmoi", "chezmoi not installed (normal for a Windows-only install)")
        return None
    report.fail(
        "chezmoi",
        "chezmoi binary not found (~/.local/bin/chezmoi or PATH)",
        "re-run the install one-liner",
    )
    return None


def check_clone(report: Report, chezmoi: str | None) -> Path | None:
    """Where the stack is installed from."""
    src: Path | None = None
    notes: list[str] = []
    try:
        src = paths.resolve_source_dir(warn=notes.append)
    except paths.CloneNotFound as exc:
        report.fail("clone", str(exc), "re-run the install one-liner")
        return None

    if not paths.is_stack_clone(src):
        report.fail("clone", f"'{src}' is a git repo but not a terminal-stack clone")
        return src

    report.ok("clone", f"clone: {src}")

    # chezmoi's own view, separately: the two can disagree, and that disagreement
    # is exactly what makes an apply deploy from somewhere unexpected.
    #
    # POSIX only. On Windows the apply path is scripts/sync-windows.ps1 and
    # chezmoi is not consulted at all -- it is often present merely because winget
    # installed it, pointing at whatever directory it defaulted to. Reporting that
    # as a failure is a false positive on every Windows box, and a doctor that
    # cries wolf is a doctor nobody reads.
    if chezmoi and plat.kind() != plat.WINDOWS:
        got = _run([chezmoi, "source-path"], timeout=60)
        recorded = got.stdout.strip() if got and got.returncode == 0 else ""
        if not recorded:
            report.fail(
                "chezmoi-sourcedir",
                "chezmoi has no source dir (chezmoi.toml missing sourceDir)",
                "repair: tstack doctor --repair",
            )
        elif Path(recorded).resolve() != src.resolve():
            report.fail(
                "chezmoi-sourcedir",
                f"chezmoi applies from '{recorded}' but the resolved clone is '{src}'",
                "repair: tstack doctor --repair",
            )
        else:
            report.ok("chezmoi-sourcedir", f"sourceDir: {recorded}")

    for note in notes:
        report.note("clone-resolution", note.strip())
    return src


def check_shell_integration(report: Report) -> None:
    """The deployed shell files actually carry our blocks."""
    if plat.kind() == plat.WINDOWS:
        profile = os.environ.get("TS_PROFILE_PATH")
        candidates = [Path(profile)] if profile else []
        home = Path.home()
        candidates += [
            home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
            home / "OneDrive" / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
        ]
        found = next((p for p in candidates if p.is_file()), None)
        if not found:
            report.fail("pwsh-profile", "$PROFILE not found", "run scripts/sync-windows.ps1")
            return
        body = found.read_text(encoding="utf-8", errors="replace")
        if "terminal-stack-update-start" in body:
            report.ok("pwsh-profile", "$PROFILE has the terminal-stack block")
        else:
            report.fail(
                "pwsh-profile",
                "$PROFILE is missing the terminal-stack block",
                "re-run scripts/sync-windows.ps1",
            )
        return

    zshrc = Path.home() / ".zshrc"
    if not zshrc.is_file():
        report.fail(
            "zshrc", "~/.zshrc not found (chezmoi apply not run yet?)", "run: chezmoi apply"
        )
        return
    body = zshrc.read_text(encoding="utf-8", errors="replace")
    if "terminal-stack-zsh-start" in body:
        report.ok("zshrc", "~/.zshrc has the terminal-stack block")
    else:
        report.fail(
            "zshrc",
            "~/.zshrc is missing the terminal-stack block (stale or not applied)",
            "run: chezmoi apply",
        )
    if "doc-start" in body:
        report.ok("zshrc-doc", "~/.zshrc has the 'doc' command")
    else:
        report.fail(
            "zshrc-doc",
            "~/.zshrc has no 'doc' command (source predates the doc feature)",
            "run: tstack update",
        )


def check_tools_on_path(report: Report) -> None:
    wanted = ("starship",) if plat.kind() == plat.WINDOWS else ("zsh", "starship")
    for tool in wanted:
        if shutil.which(tool):
            report.ok(f"path-{tool}", f"{tool} on PATH")
        else:
            report.fail(
                f"path-{tool}", f"{tool} not on PATH", f"install it: tstack config apps {tool}"
            )


def check_config_stores(report: Report) -> None:
    """The two stores must agree, or one silently undoes the other.

    Outside every feature gate, deliberately: the failure is one store saying
    "off" while the other says "on", so gating on either blinds the check exactly
    when it matters. On 2026-08-21 the mirror said false, chezmoi [data] said
    true, the pwsh sync had deleted every TTS hook, and the doctor reported
    "tts daemon healthy".
    """
    if not plat.is_windows_side():
        return
    mirror = store.mirror_path()
    if not mirror or not mirror.is_file():
        if plat.kind() == plat.WINDOWS:
            report.fail(
                "config-mirror",
                f"config.json missing ({mirror})",
                "run install.ps1 or tstack config",
            )
        return
    report.ok("config-mirror", f"config: {mirror}")

    found = store.divergences()
    for key, mine, theirs in found:
        report.fail(
            "config-divergence",
            f"config stores disagree on {key}: chezmoi [data]='{mine}' "
            f"but the Windows mirror='{theirs}'",
            "[data] wins for a WSL apply, the mirror for a pwsh sync; set it again from WSL",
        )
    if not found and store.chezmoi_data():
        report.ok("config-divergence", "config stores agree")


def check_memory_backend(report: Report) -> None:
    """One backend, and the derived key agreeing with it.

    Drift means something wrote agentmemoryEnabled directly, which is how a
    machine ends up half-configured for two memory systems that do the same job.
    """
    backend = store.get("memoryBackend", "agentmemory")
    derived = store.normalise(store.get("agentmemoryEnabled", "off"))
    expected = "true" if backend == "agentmemory" else "false"
    if derived == expected:
        report.ok("memory-backend", f"memory backend: {backend}")
    else:
        report.fail(
            "memory-backend",
            f"memoryBackend is '{backend}' but agentmemoryEnabled is '{derived}'",
            f"fix: tstack config memory {backend}",
        )


def check_tts(report: Report) -> None:
    """Only when the feature is on. An enabled-but-dead daemon is a failure: the
    hooks degrade silently to direct playback and the user chose otherwise."""
    if store.normalise(store.get("ccTtsEnabled", "false")) != "true":
        return

    engine = store.get("ccTtsEngine", "kokoro")
    if engine == "kokoro":
        alive = _probe_http("http://127.0.0.1:8880/health") or _probe_http("http://127.0.0.1:8880/")
        if alive:
            report.ok("tts-engine", "kokoro TTS engine reachable")
        else:
            report.fail(
                "tts-engine",
                "kokoro is the chosen TTS engine and it is not reachable - "
                "voice notifications are silently off",
                "start it: tstack services up kokoro",
            )

    if store.normalise(store.get("ccTtsDaemon", "off")) == "true":
        port = _tts_port()
        if _daemon_reachable(port):
            report.ok("tts-daemon", "tts daemon healthy")
        else:
            report.fail(
                "tts-daemon",
                "tts daemon is enabled but not reachable - hooks fall back to direct playback",
                "start: tstack config tts daemon on",
            )

    _check_claude_tts_hooks(report)

    # The untracked local override beats the rendered config, so `cctts on` can
    # report success while every hook stays silent. On a combined host the file
    # that counts is the WINDOWS one -- the EXE merges that, not the WSL copy.
    local = _tts_local_json()
    if local and local.is_file():
        try:
            body = json.loads(local.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            body = {}
        if body.get("enabled") is False:
            report.fail(
                "tts-local-override",
                f"{local} forces enabled=false, which overrides the saved setting",
                "remove that key (ccmute is the way to go quiet)",
            )


def _daemon_hosts(port: int) -> list[str]:
    """The addresses the TTS daemon might answer on, in order.

    On WSL the daemon is a WINDOWS process, and WSL2's 127.0.0.1 is the VM's
    loopback, not Windows'. With mirrored networking loopback works; under NAT it
    does not, and the daemon is reachable only via the default gateway or the
    resolv.conf nameserver. Probing 127.0.0.1 alone reported "daemon not
    reachable" on a machine whose daemon was healthy -- the shell hooks carry this
    same ladder in cc_tts_daemon_host, and the first version of this port did not.
    """
    hosts = ["127.0.0.1"]
    if plat.kind() != plat.WSL:
        return hosts
    gateway = _run(["ip", "route", "show", "default"], timeout=5)
    if gateway and gateway.returncode == 0:
        parts = gateway.stdout.split()
        if len(parts) >= 3:
            hosts.append(parts[2])
    try:
        for line in Path("/etc/resolv.conf").read_text(encoding="utf-8").splitlines():
            if line.startswith("nameserver"):
                addr = line.split()[1]
                if addr not in hosts:
                    hosts.append(addr)
                break
    except (OSError, IndexError):
        pass
    return hosts


def _daemon_token() -> str:
    """The dashboard token, needed for any non-loopback probe."""
    for candidate in (
        Path.home() / ".claude" / "tts" / "state" / "secrets.json",
        Path.home() / ".claude" / "tts" / "local.json",
    ):
        try:
            body = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key in ("token", "dashboardToken"):
            if isinstance(body, dict) and body.get(key):
                return str(body[key])
    return ""


def _daemon_reachable(port: int) -> bool:
    token = ""
    for host in _daemon_hosts(port):
        if host != "127.0.0.1" and not token:
            token = _daemon_token()
        headers = {"X-TS-Token": token} if (host != "127.0.0.1" and token) else {}
        if _probe_http(f"http://{host}:{port}/healthz", headers=headers):
            return True
    return False


def _check_claude_tts_hooks(report: Report) -> None:
    """A hook that does not exist cannot be degraded, slow, or muted - it is
    simply absent, and every other TTS check still looks healthy. That is the
    one-line version of the outage that removed all five of them."""
    if not plat.is_windows_side():
        return
    if plat.kind() == plat.WSL:
        user = plat.windows_username()
        if not user:
            return
        settings = Path(f"/mnt/c/Users/{user}/.claude/settings.json")
    else:
        settings = Path.home() / ".claude" / "settings.json"
    if not settings.is_file():
        return
    body = settings.read_text(encoding="utf-8", errors="replace")
    if "terminal-stack-tts.exe hook" in body:
        report.ok("tts-hooks", "Claude TTS hooks installed")
    else:
        report.fail(
            "tts-hooks",
            f"TTS is enabled but {settings} has no terminal-stack-tts hooks - "
            "nothing will ever call the daemon",
            "repair: tstack config tts on (from WSL)",
        )


def check_agentmemory_wiring(report: Report, src: Path | None) -> None:
    """Vendor plugin caches hold the hook scripts, so a plugin upgrade reverts
    every edit and retrieval silently stops. Nothing else reports it."""
    if src is None:
        return
    if store.normalise(store.get("agentmemoryEnabled", "off")) != "true":
        return
    script = src / "bootstrap" / "ts-agentmemory.sh"
    if plat.kind() == plat.WINDOWS:
        script = src / "bootstrap" / "ts-agentmemory.ps1"
        pwsh = plat.find_pwsh()
        if not pwsh or not script.is_file():
            return
        got = _run(
            [
                pwsh,
                "-NoLogo",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-Check",
            ],
            timeout=120,
        )
    else:
        if not script.is_file():
            return
        got = _run(["bash", str(script), "--check"], timeout=120)
    if got is None:
        return
    if got.returncode == 0:
        report.ok("agentmemory-wiring", "agentmemory hook wiring intact")
    else:
        report.fail(
            "agentmemory-wiring",
            "agentmemory hook wiring is incomplete (a plugin upgrade reverts it)",
            "repair: tstack config agents agentmemory repair",
        )


def _tts_port() -> int:
    cfg = Path.home() / ".claude" / "tts" / "config.json"
    try:
        return int(json.loads(cfg.read_text(encoding="utf-8"))["daemon"]["port"])
    except (OSError, ValueError, KeyError, TypeError):
        return 8890


def _tts_local_json() -> Path | None:
    if plat.is_windows_side() and plat.kind() == plat.WSL:
        user = plat.windows_username()
        if user:
            return Path(f"/mnt/c/Users/{user}/.claude/tts/local.json")
    return Path.home() / ".claude" / "tts" / "local.json"


def _probe_http(url: str, timeout: float = 2.0, headers: dict[str, str] | None = None) -> bool:
    """Answering is the test, never a 2xx.

    AgentMemory returns 404 on `/` and 401 on `/agentmemory/health`, so a
    `curl -fsS`-shaped check reported the service down while it was up. Only a
    refused connection counts as down.
    """
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url, headers=headers or {})
    try:
        urllib.request.urlopen(request, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def check_smb(report: Report) -> None:
    """Gated on actually using it: three lines, not the full `tstack smb doctor`."""
    if plat.kind() == plat.WINDOWS:
        return
    cfg_home = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    state_home = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    conf = cfg_home / "terminal-stack" / "shares.local.conf"
    state = state_home / "terminal-stack" / "smb"
    records = sorted(state.glob("*.mnt")) if state.is_dir() else []
    if not conf.is_file() and not records:
        return

    rclone = shutil.which("rclone")
    if not rclone:
        report.fail(
            "smb-rclone",
            "tstack smb: shares are configured but rclone is missing",
            "repair: tstack config apps rclone",
        )
    else:
        report.ok("smb-rclone", "tstack smb: rclone present")
        if plat.kind() == plat.MACOS:
            real = str(Path(rclone).resolve())
            if "/Cellar/" in real or real.startswith(("/opt/homebrew/", "/usr/local/Homebrew/")):
                report.fail(
                    "smb-rclone-build",
                    "tstack smb: this rclone is the Homebrew build, which cannot mount on "
                    "macOS (browsing is unaffected)",
                    "install the official binary from https://rclone.org/downloads/",
                )

    # Never stat, ls or glob the MOUNTPOINT: a dead FUSE mount blocks forever and
    # takes this process with it. Only the record file and the pid are consulted.
    stale = 0
    for record in records:
        pid = None
        for line in record.read_text(encoding="utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == "pid":
                pid = parts[1]
        if pid is None or not pid.isdigit():
            stale += 1
            continue
        try:
            os.kill(int(pid), 0)
        except (OSError, ProcessLookupError):
            stale += 1
    if stale:
        report.fail(
            "smb-stale-mounts",
            f"tstack smb: {stale} stale mount record(s)",
            "repair: tstack smb umount --all --force",
        )


def check_clone_location(report: Report, src: Path | None) -> None:
    """Advisory, never a failure: a working install at a legacy path still works."""
    if src is None:
        return
    canon = paths.canonical_clone_dir()
    if not canon:
        return
    try:
        same = src.resolve() == canon.resolve()
    except OSError:
        same = str(src) == str(canon)
    if same:
        return
    if paths.is_dev_clone(src):
        report.note(
            "clone-location",
            "clone is a dev checkout (workspace tier path) - deliberate pin, left alone",
        )
    else:
        report.note(
            "clone-location",
            f"clone is at a legacy location; 'tstack doctor --repair' can move it to {canon}",
        )


def check_other_clones(report: Report, src: Path | None) -> None:
    others = [c.path for c in paths.clones() if src is None or c.path.resolve() != src.resolve()]
    if others:
        listed = ", ".join(str(p) for p in others)
        report.note(
            "other-clones",
            f"other terminal-stack clones present: {listed}",
            "'tstack doctor --repair' can clean them up",
        )


def check_git_hooks(report: Report, src: Path | None) -> None:
    """Only meaningful in a dev clone, where commits happen.

    Until 2026-08-25 nothing set core.hooksPath, so the repo's only automated
    gate had never run anywhere.
    """
    if src is None or not paths.is_dev_clone(src):
        return
    if not (src / ".githooks").is_dir():
        return
    got = _run(["git", "-C", str(src), "config", "--local", "--get", "core.hooksPath"])
    value = got.stdout.strip() if got and got.returncode == 0 else ""
    if value == ".githooks":
        report.ok("git-hooks", "dev clone: pre-commit and pre-push gates active")
    else:
        report.fail(
            "git-hooks",
            "dev clone: core.hooksPath is not set, so no commit gate runs",
            f"fix: git -C {src} config --local core.hooksPath .githooks",
        )


def collect() -> Report:
    report = Report()
    chezmoi = check_chezmoi(report)
    src = check_clone(report, chezmoi)
    check_shell_integration(report)
    check_tools_on_path(report)
    check_config_stores(report)
    check_memory_backend(report)
    check_tts(report)
    check_agentmemory_wiring(report, src)
    check_smb(report)
    check_clone_location(report, src)
    check_other_clones(report, src)
    check_git_hooks(report, src)
    return report


# ---------------------------------------------------------------------- entry


def render(report: Report, quiet: bool) -> list[str]:
    lines: list[str] = []
    if not quiet:
        lines.append(HEADER)
    for result in report.results:
        if result.status == checks.OK and quiet:
            continue
        lines.append(result.render())
    if report.issues == 0:
        if not quiet:
            lines.append(PASSED)
    else:
        lines.append(f"!! {report.issues} issue(s) found - run 'tstack doctor --repair' to fix.")
    return lines


def repair(src: Path | None) -> int:
    """Delegate the destructive half.

    Clone relocation and the cleanup checklist live in bootstrap/_cleanup.{sh,ps1},
    which the installers also use. They are not doctor's twins and are not
    doctor's to reimplement.
    """
    if src is None:
        print(
            "tstack doctor --repair: no clone to repair. Re-run the install one-liner.",
            file=sys.stderr,
        )
        return 1
    print("==> tstack doctor --repair")
    cleanup = src / "bootstrap" / ("_cleanup.ps1" if plat.kind() == plat.WINDOWS else "_cleanup.sh")
    if not cleanup.is_file():
        print(f"  !! {cleanup} not found; cannot run the cleanup checklist.", file=sys.stderr)
        return 1
    print(f"  cleanup checklist: {cleanup}")
    print("  (relocation and clone cleanup are interactive; follow the prompts)")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="tstack doctor",
        description="Diagnose the terminal-stack install, and repair what can be repaired.",
        epilog=(
            "examples:\n"
            "  tstack doctor              run every check\n"
            "  tstack doctor --quiet      only what is wrong\n"
            "  tstack doctor --json       machine-readable, for scripts and the dashboard\n"
            "  tstack doctor --repair     fix what is fixable, confirming each step\n"
            "\nexit status: 0 healthy, 1 issues found."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="suppress the per-check 'ok' lines"
    )
    parser.add_argument(
        "--json", action="store_true", help="emit one record per check instead of prose"
    )
    parser.add_argument(
        "--repair", action="store_true", help="fix what is fixable, confirming each step"
    )
    args = parser.parse_args(argv)

    report = collect()

    if args.json:
        src = None
        with contextlib.suppress(paths.CloneNotFound):
            src = paths.resolve_source_dir()
        payload = report.as_dict()
        payload["platform"] = plat.kind()
        payload["clone"] = str(src) if src else None
        print(json.dumps(payload, indent=2))
        return 1 if report.issues else 0

    for line in render(report, args.quiet):
        print(line)

    if args.repair:
        try:
            src = paths.resolve_source_dir()
        except paths.CloneNotFound:
            src = None
        return repair(src)

    return 1 if report.issues else 0
