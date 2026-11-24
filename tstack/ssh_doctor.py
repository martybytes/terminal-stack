"""`tstack ssh doctor [--fix]`: the key problems that make ssh refuse a key or
ask for its passphrase again and again, on this PC and, from Windows, in WSL.

Every check reports. `--fix` repairs what it safely can and asks first:

  * file modes and CRLF are mechanical, and the files are backed up;
  * loading a key into the agent and adding a passphrase prompt on the
    terminal, so they are offered one at a time and never under --yes;
  * duplicate Host blocks are only reported: the stack never edits ~/.ssh/config.

The POSIX checks run as one shell probe, locally or through `wsl.exe`, so the
same code reads Ubuntu from Windows and a Linux box from itself. docs:
docs/kb/windows/ssh-server.md "Key doctor".
"""

from __future__ import annotations

import functools
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import platform as plat
from . import proc, ssh, ssh_acl

# (script, stdin) -> the finished process, or None when it could not run.
Shell = Callable[[str, "str | None"], "subprocess.CompletedProcess[str] | None"]


@dataclass
class Finding:
    side: str
    state: str  # ok | warn | info
    what: str
    detail: str = ""
    fix: Callable[[], bool] | None = None
    fix_says: str = ""
    interactive: bool = False  # prompts on the terminal: never under --yes


# ------------------------------------------------------------- ssh config


def _directives(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip().rstrip("\r")
        if not line or line.startswith("#"):
            continue
        if "=" in line.split(None, 1)[0]:
            key, _, value = line.partition("=")
        else:
            key, _, value = line.partition(" ")
        out.append((key.strip().lower(), value.strip()))
    return out


def duplicate_hosts(text: str) -> list[str]:
    """Host patterns that open more than one block. ssh takes the FIRST value of
    each keyword, so the later block's settings are silently ignored."""
    seen: set[str] = set()
    dups: list[str] = []
    for key, value in _directives(text):
        if key != "host":
            continue
        for pattern in value.split():
            if pattern in seen and pattern not in dups:
                dups.append(pattern)
            seen.add(pattern)
    return dups


def adds_keys_to_agent(text: str) -> bool:
    return any(
        key == "addkeystoagent" and value.lower() not in ("no", "")
        for key, value in _directives(text)
    )


def identity_files(text: str, home: Path) -> list[Path]:
    """IdentityFile paths that exist, in order, each once. Tokens (%d, ${X}) skipped."""
    out: list[Path] = []
    for key, value in _directives(text):
        if key != "identityfile":
            continue
        value = value.strip('"')
        if "%" in value or "$" in value:
            continue
        if value.startswith(("~/", "~\\")):
            path = home / value[2:]
        else:
            path = Path(value)
            if not path.is_absolute():
                path = home / ".ssh" / value
        if path.is_file() and path not in out:
            out.append(path)
    return out


# ----------------------------------------------------------- windows side


def ssh_add() -> str | None:
    if plat.kind() == plat.WINDOWS:
        native = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32/OpenSSH/ssh-add.exe"
        if native.is_file():
            return str(native)
    import shutil

    return shutil.which("ssh-add")


def agent_fingerprints() -> tuple[int, set[str]]:
    """(`ssh-add -l` exit code, SHA256 fingerprints). 0 keys, 1 empty, 2 no agent."""
    exe = ssh_add()
    if not exe:
        return 2, set()
    got = proc.capture([exe, "-l", "-E", "sha256"], timeout=15)
    if got is None:
        return 2, set()
    prints = {
        w for line in got.stdout.splitlines() for w in line.split() if w.startswith("SHA256:")
    }
    return got.returncode, prints


def _public_of(private: Path) -> ssh.Key | None:
    pub = private.with_name(private.name + ".pub")
    if not pub.is_file():
        return None
    return ssh.parse_key(pub.read_text(encoding="utf-8", errors="replace"), source=pub.name)


def _interactive(argv: list[str]) -> bool:
    """Run with the terminal attached: ssh-add and ssh-keygen ask for passphrases
    themselves, so a passphrase never passes through this process."""
    try:
        return subprocess.run(argv, check=False).returncode == 0
    except OSError:
        return False


def windows_findings() -> list[Finding]:
    side = "Windows"
    out: list[Finding] = []
    home = Path.home()
    ssh_dir = ssh.ssh_dir()
    cfg = ssh_dir / "config"
    text = cfg.read_text(encoding="utf-8", errors="replace") if cfg.is_file() else ""

    status, start = ssh._windows_service("ssh-agent")
    if status == "Running" and start == "Automatic":
        out.append(Finding(side, "ok", "ssh-agent service", "Running, Automatic"))
    else:
        out.append(Finding(side, "warn", "ssh-agent service",
                           f"{status or 'missing'}, {start or '-'}: keys cannot stay unlocked. "
                           "`tstack ssh setup` sets it to Automatic (admin)"))  # fmt: skip

    found = ssh_acl.exposed(ssh_dir)
    if found:
        out.append(Finding(side, "warn", "~/.ssh permissions", ssh_acl.summary(found),
                           fix=lambda: ssh_acl.fix(ssh_dir) and not ssh_acl.exposed(ssh_dir),
                           fix_says="make ~/.ssh private to you (icacls, no admin needed)"))  # fmt: skip
    else:
        out.append(Finding(side, "ok", "~/.ssh permissions", "private to you"))

    code, loaded = agent_fingerprints()
    if code == 2:
        out.append(Finding(side, "warn", "agent keys", "the agent does not answer"))
    else:
        missing: list[Path] = []
        for private in identity_files(text, home):
            key = _public_of(private)
            if key is not None and key.fingerprint not in loaded:
                missing.append(private)
        if missing:
            names = ", ".join(p.name for p in missing)
            exe = ssh_add() or "ssh-add"
            out.append(Finding(side, "warn", "agent keys",
                               f"not loaded: {names}. Each asks for its passphrase on use",
                               fix=lambda: _interactive([exe, *map(str, missing)]),
                               fix_says="ssh-add them: one passphrase each, kept across reboots",
                               interactive=True))  # fmt: skip
        else:
            out.append(
                Finding(
                    side, "ok", "agent keys", f"{len(loaded)} loaded, every IdentityFile among them"
                )
            )

    out += _config_findings(side, text, cfg.is_file())
    out += _passphrase_findings(side, _windows_no_passphrase(ssh_dir), _windows_keygen_p)
    return out


def _windows_no_passphrase(ssh_dir: Path) -> list[str]:
    if not ssh_dir.is_dir():
        return []
    paths = []
    for f in sorted(ssh_dir.iterdir()):
        if not f.is_file() or f.suffix == ".pub":
            continue
        try:
            head = f.read_bytes()[:100]
        except OSError:
            continue
        if b"PRIVATE KEY" in head and ssh.has_passphrase(f) is False:
            paths.append(str(f))
    return paths


def _windows_keygen_p(path: str) -> bool:
    keygen = ssh.ssh_keygen()
    return keygen is not None and _interactive([keygen, "-p", "-f", path])


def _config_findings(side: str, text: str, exists: bool) -> list[Finding]:
    if not exists:
        return [Finding(side, "info", "~/.ssh/config", "none")]
    out: list[Finding] = []
    if adds_keys_to_agent(text):
        out.append(
            Finding(side, "ok", "AddKeysToAgent", "set: a key unlocked once goes to the agent")
        )
    else:
        out.append(Finding(side, "warn", "AddKeysToAgent",
                           "not set: add `AddKeysToAgent yes` under `Host *` in ~/.ssh/config"))  # fmt: skip
    dups = duplicate_hosts(text)
    if dups:
        out.append(Finding(side, "warn", "duplicate Host",
                           f"{', '.join(dups)}: only the first block's values apply (not edited for you)"))  # fmt: skip
    return out


def _passphrase_findings(
    side: str, paths: list[str], keygen_p: Callable[[str], bool]
) -> list[Finding]:
    out: list[Finding] = []
    for path in paths:
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        out.append(Finding(side, "warn", "no passphrase",
                           f"{name}: anyone who copies the file can use it",
                           fix=functools.partial(keygen_p, path),
                           fix_says=f"add a passphrase to {name} (ssh-keygen -p)",
                           interactive=True))  # fmt: skip
    return out


# -------------------------------------------------------------- posix side

# One probe, the same on WSL-from-Windows and on a Linux or macOS box.
POSIX_PROBE = r"""d="$HOME/.ssh"
[ -d "$d" ] || { echo none; exit 0; }
m() { stat -c %a "$1" 2>/dev/null || stat -f %Lp "$1"; }
echo "dir $(m "$d") $d"
for f in "$d"/*; do
  [ -f "$f" ] && [ ! -L "$f" ] || continue
  case "$f" in *.pub|*/known_hosts*|*/authorized_keys*|*/config) continue;; esac
  head -c 100 "$f" 2>/dev/null | grep -q 'PRIVATE KEY' || continue
  echo "priv $(m "$f") $f"
  ssh-keygen -y -P '' -f "$f" </dev/null >/dev/null 2>&1 && echo "nopass 0 $f"
done
[ -f "$d/config" ] && echo "cfg $(m "$d/config") $d/config" && \
  grep -q "$(printf '\r')" "$d/config" && echo "crlf 0 $d/config"
[ -f "$d/authorized_keys" ] && echo "auth $(m "$d/authorized_keys") $d/authorized_keys"
exit 0
"""

# .bak.YYYYMMDD, then .1, .2: never clobber a same-day backup.
POSIX_CRLF_FIX = r"""f="$1"; b="$f.bak.$(date +%Y%m%d)"; n=1
while [ -e "$b" ]; do b="$f.bak.$(date +%Y%m%d).$n"; n=$((n+1)); done
cp -p "$f" "$b" && sed -i 's/\r$//' "$f"
"""


def parse_probe(out: str) -> dict[str, list[tuple[int, str]]]:
    """`<tag> <octal mode> <path>` lines, grouped by tag."""
    found: dict[str, list[tuple[int, str]]] = {}
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and parts[1].isdigit():
            found.setdefault(parts[0], []).append((int(parts[1], 8), parts[2]))
    return found


def posix_findings(side: str, sh: Shell, *, keygen_p: Callable[[str], bool],
                   bridge: Finding | None = None) -> list[Finding]:  # fmt: skip
    got = sh(POSIX_PROBE, None)
    if got is None or got.returncode != 0:
        return [Finding(side, "warn", "~/.ssh", "could not be read")]
    if got.stdout.strip() == "none":
        return [Finding(side, "info", "~/.ssh", "none"), *([bridge] if bridge else [])]
    probe = parse_probe(got.stdout)
    out: list[Finding] = []

    def chmod(argv: list[str]) -> Callable[[], bool]:
        return lambda: _ok(sh("chmod " + " ".join(_quote(a) for a in argv), None))

    loose = [p for mode, p in probe.get("priv", []) if mode & 0o077]
    writable = [
        p for tag in ("dir", "cfg", "auth") for mode, p in probe.get(tag, []) if mode & 0o022
    ]
    if loose or writable:
        names = [p.rsplit("/", 1)[-1] for p in loose + writable]
        fixes = ([chmod(["600", *loose])] if loose else []) + (
            [chmod(["go-w", *writable])] if writable else []
        )
        out.append(Finding(side, "warn", "file modes",
                           f"{', '.join(names)}: ssh refuses a key or config others can read or write",
                           fix=lambda: all([f() for f in fixes]),
                           fix_says="chmod 600 the private keys, go-w the rest"))  # fmt: skip
    else:
        out.append(
            Finding(
                side, "ok", "file modes", f"{len(probe.get('priv', []))} private key(s), all 600"
            )
        )

    for _, path in probe.get("crlf", []):
        out.append(Finding(side, "warn", "CRLF in config",
                           "Windows line endings: ssh reads `yes\\r` and rejects the line",
                           fix=functools.partial(_crlf_fix, sh, path),
                           fix_says="strip the CRs (backup taken)"))  # fmt: skip

    cfg = probe.get("cfg", [])
    text = ""
    if cfg:
        read = sh(f"cat {_quote(cfg[0][1])}", None)
        text = read.stdout if read is not None and read.returncode == 0 else ""
    out += _config_findings(side, text, bool(cfg))
    if bridge is not None:
        out.append(bridge)
    out += _passphrase_findings(side, [p for _, p in probe.get("nopass", [])], keygen_p)
    return out


def _crlf_fix(sh: Shell, path: str) -> bool:
    return _ok(sh(f"set -- {_quote(path)}\n" + POSIX_CRLF_FIX, None))


def _ok(got: subprocess.CompletedProcess[str] | None) -> bool:
    return got is not None and got.returncode == 0


def _quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


BRIDGE_SAYS = {
    0: ("ok", "the Windows agent's keys are usable here"),
    1: ("ok", "relaying, though the Windows agent holds no keys yet"),
    2: ("warn", "set up, but nothing answers: is the Windows ssh-agent running?"),
    3: ("warn", "not set up: Ubuntu keeps its own agent and asks for passphrases itself"),
}


def bridge_finding(state: int, fix: Callable[[], bool] | None) -> Finding:
    level, says = BRIDGE_SAYS.get(state, BRIDGE_SAYS[2])
    return Finding("WSL", level, "agent bridge", says,
                   fix=fix if level != "ok" else None,
                   fix_says="install npiperelay and socat, start the bridge unit")  # fmt: skip


# ------------------------------------------------------------------ collect


def collect() -> list[Finding]:
    kind = plat.kind()
    if kind == plat.WINDOWS:
        out = windows_findings()
        distro = ssh.wsl_default_distro()
        if not distro:
            return out

        def sh(script: str, stdin: str | None) -> subprocess.CompletedProcess[str] | None:
            return ssh.wsl(["sh", "-c", script], distro=distro, stdin=stdin, timeout=120)

        bridge = None
        if ssh.settings().get("sshAgentBridge") == "on":
            bridge = bridge_finding(
                ssh.wsl_bridge_state(distro), lambda: ssh.wsl_install_bridge(distro)[0]
            )
        return out + posix_findings(
            "WSL", sh, bridge=bridge,
            keygen_p=lambda p: _interactive(["wsl.exe", "-d", distro, "-e", "ssh-keygen", "-p", "-f", p]),
        )  # fmt: skip

    def local(script: str, stdin: str | None) -> subprocess.CompletedProcess[str] | None:
        return proc.capture(["sh", "-c", script], stdin=stdin, timeout=120)

    bridge = None
    if kind == plat.WSL:
        got = local(ssh.BRIDGE_PROBE_SCRIPT, None)
        state = int(got.stdout.strip()) if got is not None and got.stdout.strip().isdigit() else 2
        bridge = bridge_finding(state, None)
        if state != 0 and state != 1:
            bridge.detail += " (fix from PowerShell: tstack ssh doctor --fix)"
    side = "WSL" if kind == plat.WSL else "this machine"
    return posix_findings(side, local, bridge=bridge,
                          keygen_p=lambda p: _interactive(["ssh-keygen", "-p", "-f", p]))  # fmt: skip
