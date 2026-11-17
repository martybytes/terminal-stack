"""The SSH server: PowerShell on one port, Ubuntu (WSL) on another.

`tstack ssh` (tstack/commands/ssh.py) is the entry point; the wizard asks the
settings (tstack/wizard/flow.py `ssh_questions`) and the Windows installer
runs `tstack ssh setup --from-wizard` after saving them.

The split, and why:
  * This module PLANS. Everything that does not need admin happens here: the
    key sources, the user's own authorized_keys, rendering the sshd block,
    deciding the firewall rules, and verifying afterwards.
  * bootstrap/ssh-server.ps1 APPLIES the Windows half, elevated, from a plan
    file and nothing else. One UAC prompt per apply; declining it prints the
    exact commands instead. The stack never elevated before, so the elevated
    surface is kept to one script that takes data, not code.

Never locks you out: passwords are switched off only after a key login to the
new port has succeeded (or you say so, when no authorized key lives on this
PC to test with). docs/kb/windows/ssh-server.md; docs/decisions.md SSH server.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import shutil
import socket
import subprocess
import tempfile
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import platform as plat
from . import proc, ssh_acl, store

DEFAULTS: dict[str, str] = {
    "sshServer": "off",
    "sshTargets": "both",
    "sshWindowsPort": "22",
    "sshWslPort": "2222",
    "sshPasswordAuth": "off",
    "sshScope": "private",
    "sshAgentBridge": "on",
}

KEY_TYPES = (
    "ssh-ed25519",
    "ssh-rsa",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "sk-ssh-ed25519@openssh.com",
    "sk-ecdsa-sha2-nistp256@openssh.com",
)

# Tailscale hands out addresses from these ranges, IPv4 CGNAT and its IPv6 ULA.
TAILNET = ("100.64.0.0/10", "fd7a:115c:a1e0::/48")
RULE_GROUP = "terminal-stack ssh"
WSL_DROPIN = "/etc/ssh/sshd_config.d/10-terminal-stack.conf"
# Hyper-V firewall's id for WSL VMs; mirrored-mode inbound traffic to WSL is
# filtered by Hyper-V firewall rules carrying it, not by ordinary host rules.
WSL_VM_CREATOR = "{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}"
KEEPALIVE_TASK = "terminal-stack WSL sshd keep-alive"

# What each side answers to its proof command. A login that succeeds on the
# wrong server is not a proof: on 11/16/2026 the WSL "proof" reached Windows sshd,
# still on 2222, and switched WSL passwords off on the strength of it.
PROOF = {
    "windows": ("cmd /c echo %OS%", "Windows_NT"),  # cmd or pwsh as the login shell
    "wsl": ("uname -s", "Linux"),
}
BLOCK_START = "# ---- terminal-stack-start ---- (tstack ssh setup; edits here are replaced)"
BLOCK_END = "# ---- terminal-stack-end ----"


def settings() -> dict[str, str]:
    """This machine's saved SSH choices, defaults filled in."""
    return {k: (store.get(k, "") or d) for k, d in DEFAULTS.items()}


def save(values: dict[str, str]) -> None:
    for key in DEFAULTS:
        if key in values and values[key] != store.get(key, ""):
            store.set(key, values[key])


def wants_windows(s: dict[str, str]) -> bool:
    return s.get("sshServer") == "on" and s.get("sshTargets") in ("both", "windows")


def wants_wsl(s: dict[str, str]) -> bool:
    return s.get("sshServer") == "on" and s.get("sshTargets") in ("both", "wsl")


def port_problem(s: dict[str, str]) -> str | None:
    """Why the saved ports cannot work, or None."""
    for key in ("sshWindowsPort", "sshWslPort"):
        v = s.get(key, "")
        if not (v.isdigit() and 1 <= int(v) <= 65535):
            return f"{key} must be a port number from 1 to 65535, not {v!r}"
    if s.get("sshTargets") == "both" and s["sshWindowsPort"] == s["sshWslPort"]:
        return "the Windows and WSL ports must differ: both sides answer on this PC's address"
    return None


# ------------------------------------------------------------------ keys


@dataclass(frozen=True)
class Key:
    """One public key line, parsed. `blob` identifies it; the comment does not."""

    kind: str
    blob: str
    comment: str
    source: str = ""

    @property
    def line(self) -> str:
        return f"{self.kind} {self.blob}" + (f" {self.comment}" if self.comment else "")

    @property
    def fingerprint(self) -> str:
        raw = base64.b64decode(self.blob)
        digest = base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
        return f"SHA256:{digest}"

    @property
    def short(self) -> str:
        algo = self.kind.replace("ssh-", "").replace("-sha2-nistp", "")
        return f"{algo} {self.fingerprint[:20]}... {self.comment or '(no comment)'}"


def parse_key(line: str, source: str = "") -> Key | None:
    """A public key line, or None. Options before the type (authorized_keys
    syntax such as `from="..."`) are not accepted: the stack adds plain keys."""
    parts = line.strip().split(None, 2)
    if len(parts) < 2 or parts[0] not in KEY_TYPES:
        return None
    try:
        raw = base64.b64decode(parts[1], validate=True)
    except (binascii.Error, ValueError):
        return None
    # The blob repeats its own type as a length-prefixed string; a pasted line
    # whose two halves disagree is a copy/paste accident, not a key.
    fields, pos = [], 0
    while pos < len(raw):
        if pos + 4 > len(raw):
            return None
        n = int.from_bytes(raw[pos : pos + 4], "big")
        if pos + 4 + n > len(raw):
            return None  # truncated: a line cut short in a copy/paste
        fields.append(raw[pos + 4 : pos + 4 + n])
        pos += 4 + n
    if len(fields) < 2 or fields[0].decode("ascii", "replace") != parts[0]:
        return None
    return Key(parts[0], parts[1], parts[2].strip() if len(parts) > 2 else "", source)


def parse_keys(text: str, source: str = "") -> list[Key]:
    keys: list[Key] = []
    for line in text.splitlines():
        k = parse_key(line, source)
        if k is not None and all(k.blob != o.blob for o in keys):
            keys.append(k)
    return keys


def ssh_dir() -> Path:
    return Path.home() / ".ssh"


def local_keys() -> list[Key]:
    """This PC's public keys: every *.pub in ~/.ssh."""
    keys: list[Key] = []
    for pub in sorted(ssh_dir().glob("*.pub")):
        try:
            text = pub.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for k in parse_keys(text, source=pub.name):
            if all(k.blob != o.blob for o in keys):
                keys.append(k)
    return keys


def has_passphrase(private: Path) -> bool | None:
    """True/False, or None when it cannot be told (no ssh-keygen, unreadable)."""
    keygen = ssh_keygen()
    if not keygen or not private.is_file():
        return None
    got = proc.capture([keygen, "-y", "-P", "", "-f", str(private)], timeout=10, stdin="")
    if got is None:
        return None
    return got.returncode != 0


def github_keys(user: str, timeout: float = 10.0) -> list[Key]:
    """https://github.com/<user>.keys, parsed. Raises OSError with a reason."""
    user = user.strip().lstrip("@")
    if not user or not all(c.isalnum() or c == "-" for c in user):
        raise OSError(f"not a GitHub username: {user!r}")
    url = f"https://github.com/{user}.keys"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise OSError(f"GitHub answered {exc.code} for {user}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise OSError(f"could not reach GitHub: {exc}") from exc
    keys = parse_keys(text, source=f"github:{user}")
    return [Key(k.kind, k.blob, k.comment or f"github:{user}", k.source) for k in keys]


def ssh_keygen() -> str | None:
    if plat.kind() == plat.WINDOWS:
        native = (
            Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32/OpenSSH/ssh-keygen.exe"
        )
        if native.is_file():
            return str(native)
    return shutil.which("ssh-keygen")


def ssh_client() -> str | None:
    """System32 OpenSSH on Windows: it is the one that can reach the agent pipe."""
    if plat.kind() == plat.WINDOWS:
        native = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32/OpenSSH/ssh.exe"
        if native.is_file():
            return str(native)
    return shutil.which("ssh")


def generate_key(name: str, comment: str) -> tuple[Path, Key] | None:
    """A new ed25519 pair at ~/.ssh/id_ed25519_<name>. ssh-keygen asks for the
    passphrase itself, on the terminal, so it never passes through this process."""
    keygen = ssh_keygen()
    safe = "".join(c for c in name if c.isalnum() or c in "-_") or "remote"
    path = ssh_dir() / f"id_ed25519_{safe}"
    if not keygen or path.exists():
        return None
    ssh_dir().mkdir(mode=0o700, exist_ok=True)
    try:
        code = subprocess.run(
            [keygen, "-t", "ed25519", "-a", "64", "-f", str(path), "-C", comment], check=False
        ).returncode
    except OSError:
        return None
    if code != 0 or not path.with_suffix(".pub").is_file():
        return None
    key = parse_key(path.with_suffix(".pub").read_text(encoding="utf-8"), source=path.name + ".pub")
    return (path, key) if key else None


def merge_authorized(existing: str, keys: list[Key]) -> tuple[str, list[Key]]:
    """`existing` with each key appended unless its blob is already there.
    Every existing line survives, options and comments included."""
    blobs = set()
    for line in existing.splitlines():
        tokens = line.split()
        # The type may follow an options field (from="...",no-pty ...).
        for i, token in enumerate(tokens[:-1]):
            if token in KEY_TYPES:
                blobs.add(tokens[i + 1])
                break
    added = [k for k in keys if k.blob not in blobs]
    text = existing
    if added:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "".join(k.line + "\n" for k in added)
    return text, added


def authorized_keys_path() -> Path:
    return ssh_dir() / "authorized_keys"


def write_user_authorized(keys: list[Key]) -> list[Key]:
    """Merge keys into ~/.ssh/authorized_keys (no admin needed). Returns those added."""
    path = authorized_keys_path()
    existing = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    text, added = merge_authorized(existing, keys)
    if added:
        path.parent.mkdir(mode=0o700, exist_ok=True)
        if path.is_file():
            backup(path)
        path.write_text(text, encoding="utf-8", newline="\n")
        if plat.kind() != plat.WINDOWS:
            path.chmod(0o600)
    return added


def backup(path: Path) -> Path:
    """`<path>.bak.YYYYMMDD`, then .1, .2: never clobber a same-day backup."""
    import datetime

    stem = f"{path}.bak.{datetime.date.today():%Y%m%d}"
    target, n = Path(stem), 0
    while target.exists():
        n += 1
        target = Path(f"{stem}.{n}")
    shutil.copy2(path, target)
    return target


# ---------------------------------------------------------------- windows


def sshd_config_path() -> Path:
    return Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "ssh" / "sshd_config"


PORT_DISABLED = "# terminal-stack disabled: "


def windows_block(s: dict[str, str], password_auth: str) -> str:
    """The managed block, placed FIRST in sshd_config: sshd keeps the first value
    it reads for most keywords, so these win over any later line.

    Port is the exception: every Port line adds a listener. So splice_block also
    comments out the user's own Port lines, tagged so they can be told apart; on
    11/16/2026 sshd answered on BOTH 22 and the old 2222, and the WSL sshd could
    not bind 2222 under mirrored networking."""
    lines = [
        BLOCK_START,
        f"Port {s['sshWindowsPort']}",
        "PubkeyAuthentication yes",
        f"PasswordAuthentication {'yes' if password_auth == 'on' else 'no'}",
        BLOCK_END,
    ]
    return "\n".join(lines) + "\n"


def splice_block(config: str, block: str) -> str:
    """Replace the managed block, or put it at the very top."""
    lines = config.splitlines(keepends=True)
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith("# ---- terminal-stack-start")), None
    )
    end = next((i for i, ln in enumerate(lines) if ln.startswith(BLOCK_END)), None)
    if start is not None and end is not None and end >= start:
        rest = lines[:start] + lines[end + 1 :]
        head = start
    else:
        rest, head = lines, 0
    out = []
    for line in rest:
        if line.strip().lower().startswith("port ") and not line.lstrip().startswith("#"):
            line = PORT_DISABLED + line.lstrip()
        out.append(line)
    return "".join(out[:head]) + block + "".join(out[head:])


def admin_keys_file_active(config: str) -> bool:
    """Whether sshd sends members of Administrators to administrators_authorized_keys.

    Microsoft ships that `Match Group administrators` block on; this machine had
    it commented out, so admins log in with ~/.ssh/authorized_keys. Both are
    supported: the stack writes whichever file sshd actually reads."""
    in_match = False
    for raw in config.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("match "):
            in_match = "group administrators" in line.lower()
            continue
        if in_match and line.lower().startswith("authorizedkeysfile"):
            return "administrators_authorized_keys" in line
    return False


def firewall_rules(s: dict[str, str]) -> list[dict[str, str]]:
    """The managed inbound rules for each enabled side, per the chosen scope."""
    rules: list[dict[str, str]] = []
    sides = []
    if wants_windows(s):
        sides.append(("Windows", s["sshWindowsPort"], "host"))
    if wants_wsl(s):
        sides.append(("WSL", s["sshWslPort"], "hyperv"))
    for side, port, layer in sides:
        scope = s.get("sshScope", "private")
        base = {"Side": side, "Port": port, "Layer": layer}
        if scope in ("private", "lan-tailnet"):
            rules.append(
                dict(
                    base,
                    Name=f"terminal-stack sshd ({side})",
                    Profile="Private,Domain",
                    Remote="Any",
                )
            )
        if scope in ("tailnet", "lan-tailnet"):
            rules.append(
                dict(
                    base,
                    Name=f"terminal-stack sshd ({side}, tailnet)",
                    Profile="Any",
                    Remote=",".join(TAILNET),
                )
            )
        if scope == "any":
            rules.append(
                dict(base, Name=f"terminal-stack sshd ({side})", Profile="Any", Remote="Any")
            )
    return rules


def tailscale_ip() -> str:
    """This machine's tailnet IPv4, or "" when Tailscale is absent or down."""
    exe = shutil.which("tailscale")
    if not exe and plat.kind() == plat.WINDOWS:
        candidate = (
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Tailscale/tailscale.exe"
        )
        exe = str(candidate) if candidate.is_file() else None
    if not exe:
        return ""
    got = proc.capture([exe, "ip", "-4"], timeout=5)
    if got is None or got.returncode != 0:
        return ""
    return got.stdout.strip().splitlines()[0].strip() if got.stdout.strip() else ""


def lan_ips() -> list[str]:
    """IPv4 addresses other computers can use: not loopback, not tailnet, and on
    Windows not the virtual switches (vEthernet) WSL and Hyper-V create."""
    out: list[str] = []
    pwsh = plat.find_pwsh() if plat.kind() == plat.WINDOWS else None
    if pwsh:
        got = proc.capture(
            [pwsh, "-NoProfile", "-Command",
             "Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "
             "'vEthernet|Tailscale|Loopback' -and $_.IPAddress -notlike '169.254.*' } | "
             "ForEach-Object IPAddress"],
            timeout=20,
        )  # fmt: skip
        if got is not None and got.returncode == 0:
            return [ln.strip() for ln in got.stdout.splitlines() if ln.strip()]
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = str(info[4][0])
            if ip.startswith(("127.", "169.254.", "100.")) or ip in out:
                continue
            out.append(ip)
    except OSError:
        pass
    return out


@dataclass
class Plan:
    """Everything the elevated script needs, and nothing it could execute."""

    settings: dict[str, str]
    sshd_block: str
    sshd_block_final: str
    admin_keys: list[str] = field(default_factory=list)
    admin_keys_active: bool = False
    default_shell: str = ""
    firewall: list[dict[str, str]] = field(default_factory=list)
    verify: bool = True
    password_off_after_verify: bool = False
    password_off_without_verify: bool = False
    verify_user: str = ""
    verify_args: list[str] = field(default_factory=list)
    verify_expect: str = PROOF["windows"][1]
    ssh_exe: str = ""
    windows: bool = True
    keepalive_distro: str = ""
    keepalive_task: str = KEEPALIVE_TASK
    wsl_vm_creator: str = WSL_VM_CREATOR

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


def plan_windows(
    s: dict[str, str], keys: list[Key], *, force_password_off: bool = False, distro: str = ""
) -> Plan:
    """The Windows half as data. Passwords go off in two phases: the first write
    keeps them on, the script proves a key login on the new port, then the final
    block (no passwords) replaces it. `force_password_off` skips the proof, for
    when no authorized key is on this PC to prove it with."""
    config = (
        sshd_config_path().read_text(encoding="utf-8", errors="replace")
        if sshd_config_path().is_file()
        else ""
    )
    want_off = s.get("sshPasswordAuth", "off") == "off"
    first = "on" if want_off and not force_password_off else s.get("sshPasswordAuth", "off")
    pwsh = plat.find_pwsh() or ""
    user = os.environ.get("USERNAME", "")
    return Plan(
        settings=dict(s),
        sshd_block=windows_block(s, first),
        sshd_block_final=windows_block(s, s.get("sshPasswordAuth", "off")),
        admin_keys=[k.line for k in keys],
        admin_keys_active=admin_keys_file_active(config),
        default_shell=pwsh,
        firewall=firewall_rules(s),
        password_off_after_verify=want_off and not force_password_off,
        password_off_without_verify=want_off and force_password_off,
        verify_user=user,
        verify_args=verify_args(s["sshWindowsPort"], user),
        ssh_exe=ssh_client() or "",
        windows=wants_windows(s),
        keepalive_distro=distro if wants_wsl(s) else "",
    )


def verify_args(port: str, user: str, side: str = "windows") -> list[str]:
    """A non-interactive key login to localhost. `-F none` ignores ~/.ssh/config,
    whose `IdentitiesOnly yes` would otherwise hide every agent key."""
    null = "NUL" if plat.kind() == plat.WINDOWS else "/dev/null"
    return [
        "-F", "none",
        "-o", "BatchMode=yes",
        "-o", "PreferredAuthentications=publickey",
        "-o", "StrictHostKeyChecking=no",
        "-o", f"UserKnownHostsFile={null}",
        "-o", "ConnectTimeout=8",
        "-p", port,
        "-l", user,
        "127.0.0.1",
        PROOF[side][0],
    ]  # fmt: skip


def script_path() -> Path:
    return Path(__file__).resolve().parents[1] / "bootstrap" / "ssh-server.ps1"


def is_admin() -> bool:
    if plat.kind() != plat.WINDOWS:
        return False
    try:
        import ctypes

        windll = getattr(ctypes, "windll", None)  # Windows only; absent elsewhere
        return bool(windll and windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def manual_command(plan_file: Path) -> str:
    return (
        f'pwsh -NoProfile -ExecutionPolicy Bypass -File "{script_path()}" '
        f'-Plan "{plan_file}" -Result "{plan_file.with_suffix(".result.json")}"'
    )


def run_elevated(plan: Plan) -> tuple[dict | None, Path]:
    """Run the Windows half with one UAC prompt. Returns (result, plan file);
    result None means it did not run (declined, or no pwsh)."""
    workdir = Path(tempfile.mkdtemp(prefix="terminal-stack-ssh-"))
    plan_file = workdir / "plan.json"
    plan_file.write_text(plan.to_json(), encoding="utf-8")
    result_file = plan_file.with_suffix(".result.json")
    # Created HERE, by the user: a file the elevated process creates belongs to
    # Administrators, and the private temp dir's ACL then locks the caller out
    # (EPERM), which read as "the elevated script left no result" when it had run.
    result_file.write_text("", encoding="utf-8")
    pwsh = plat.find_pwsh()
    if not pwsh:
        return None, plan_file
    args = ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path()),
            "-Plan", str(plan_file), "-Result", str(result_file)]  # fmt: skip
    if is_admin():
        subprocess.run([pwsh, *args], check=False)
    else:
        quoted = ",".join("'" + a.replace("'", "''") + "'" for a in args)
        launcher = (
            f"try {{ Start-Process -FilePath '{pwsh}' -Verb RunAs -Wait -ArgumentList {quoted}; exit 0 }}"
            " catch { exit 5 }"
        )
        code = subprocess.run([pwsh, "-NoProfile", "-Command", launcher], check=False).returncode
        if code == 5:
            return None, plan_file
    try:
        return json.loads(result_file.read_text(encoding="utf-8-sig")), plan_file
    except PermissionError:
        detail = f"the elevated script ran, but its result is unreadable: {result_file}"
        return {
            "ok": False,
            "steps": [{"name": "result", "ok": False, "detail": detail}],
        }, plan_file
    except (OSError, ValueError):
        return {"ok": False, "steps": [{"name": "result", "ok": False,
                                        "detail": "the elevated script left no result"}]}, plan_file  # fmt: skip


# -------------------------------------------------------------------- wsl
#
# A real sshd inside Ubuntu, reached on the PC's own address through WSL's
# MIRRORED networking (Windows 11): scp, sftp, VS Code Remote and forwarding all
# land in Ubuntu. NAT would put it behind an address that changes every boot.
# Everything inside the distro runs as root through `wsl.exe -u root`, so no
# sudo password is ever needed; the user's own files are written as the user.


def wsl(argv: list[str], *, distro: str = "", root: bool = False, stdin: str | None = None,
        timeout: int = 120) -> subprocess.CompletedProcess[str] | None:  # fmt: skip
    """`wsl.exe [-d distro] [-u root] -e ...`, UTF-8 (wsl.exe speaks UTF-16 otherwise)."""
    cmd = ["wsl.exe"]
    if distro:
        cmd += ["-d", distro]
    if root:
        cmd += ["-u", "root"]
    cmd += ["-e", *argv]
    return proc.capture(cmd, timeout=timeout, stdin=stdin, env=dict(os.environ, WSL_UTF8="1"))


def wsl_default_distro() -> str:
    """The default distro: first in `wsl --list --quiet`. "" when WSL is absent."""
    if not shutil.which("wsl.exe") and plat.kind() != plat.WINDOWS:
        return ""
    got = proc.capture(
        ["wsl.exe", "--list", "--quiet"], timeout=20, env=dict(os.environ, WSL_UTF8="1")
    )
    if got is None or got.returncode != 0:
        return ""
    names = [ln.strip() for ln in (got.stdout or "").replace("\0", "").splitlines() if ln.strip()]
    names = [n for n in names if not n.startswith("docker-desktop")]
    return names[0] if names else ""


def wsl_user(distro: str) -> str:
    got = wsl(["id", "-un"], distro=distro, timeout=60)
    return got.stdout.strip() if got is not None and got.returncode == 0 else ""


def wsl_dropin(s: dict[str, str], password_auth: str) -> str:
    return (
        "# Managed by terminal-stack (tstack ssh setup). Replaced on every apply.\n"
        f"Port {s['sshWslPort']}\n"
        "PubkeyAuthentication yes\n"
        f"PasswordAuthentication {'yes' if password_auth == 'on' else 'no'}\n"
        "KbdInteractiveAuthentication no\n"
    )


# Ubuntu 24.04 starts sshd from ssh.socket, whose port a systemd generator reads
# out of sshd_config at daemon-reload: a changed Port needs the reload AND a
# restart of the socket, or the old port keeps answering.
WSL_SERVER_SCRIPT = r"""set -e
export DEBIAN_FRONTEND=noninteractive
if ! command -v sshd >/dev/null 2>&1 && [ ! -x /usr/sbin/sshd ]; then
    apt-get update -qq
    apt-get install -y -qq openssh-server >/dev/null
fi
mkdir -p /etc/ssh/sshd_config.d
grep -q '^Include /etc/ssh/sshd_config.d/\*.conf' /etc/ssh/sshd_config || \
    sed -i '1i Include /etc/ssh/sshd_config.d/*.conf' /etc/ssh/sshd_config
cat > "$1.new"
mv -f "$1.new" "$1"
/usr/sbin/sshd -t
systemctl daemon-reload
if systemctl list-unit-files ssh.socket >/dev/null 2>&1 && systemctl cat ssh.socket >/dev/null 2>&1; then
    systemctl enable ssh.socket >/dev/null 2>&1 || true
    systemctl restart ssh.socket
    systemctl restart ssh 2>/dev/null || true
else
    systemctl enable ssh >/dev/null 2>&1 || true
    systemctl restart ssh
fi
"""


def wsl_apply_server(distro: str, s: dict[str, str], password_auth: str) -> tuple[bool, str]:
    got = wsl(
        ["sh", "-c", WSL_SERVER_SCRIPT, "sh", WSL_DROPIN],
        distro=distro,
        root=True,
        stdin=wsl_dropin(s, password_auth),
        timeout=600,
    )
    if got is None:
        return False, "wsl.exe could not run"
    if got.returncode != 0:
        return False, (got.stderr or got.stdout).strip()[-400:]
    return True, ""


def wsl_authorize(distro: str, keys: list[Key]) -> tuple[list[Key], str]:
    """Merge keys into the WSL user's ~/.ssh/authorized_keys, as that user."""
    got = wsl(["sh", "-c", "cat ~/.ssh/authorized_keys 2>/dev/null || true"], distro=distro)
    if got is None or got.returncode != 0:
        return [], "could not read the WSL authorized_keys"
    text, added = merge_authorized(got.stdout, keys)
    if not added:
        return [], ""
    write = (
        "umask 077 && mkdir -p ~/.ssh && chmod 700 ~/.ssh && "
        "{ [ -f ~/.ssh/authorized_keys ] && cp -p ~/.ssh/authorized_keys ~/.ssh/authorized_keys.bak.$(date +%Y%m%d) || true; } && "
        "cat > ~/.ssh/authorized_keys.new && chmod 600 ~/.ssh/authorized_keys.new && "
        "mv -f ~/.ssh/authorized_keys.new ~/.ssh/authorized_keys"
    )
    done = wsl(["sh", "-c", write], distro=distro, stdin=text)
    if done is None or done.returncode != 0:
        return [], "could not write the WSL authorized_keys"
    return added, ""


def wslconfig_path() -> Path:
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".wslconfig"


def splice_ini(text: str, section: str, key: str, value: str) -> str:
    """Set `key=value` in `[section]`, every other byte kept. The stack never
    whole-file writes .wslconfig: memory, processors and the rest are the user's."""
    lines = text.splitlines()
    out: list[str] = []
    in_section = found_section = done = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_section and not done:
                blanks = 0
                while out and not out[-1].strip():
                    out.pop()
                    blanks += 1
                out.append(f"{key}={value}")
                out += [""] * blanks
                done = True
            in_section = stripped[1:-1].strip().lower() == section.lower()
            found_section = found_section or in_section
            out.append(line)
            continue
        if in_section and not done and stripped.split("=", 1)[0].strip().lower() == key.lower() \
                and not stripped.startswith(("#", ";")):  # fmt: skip
            out.append(f"{key}={value}")
            done = True
            continue
        out.append(line)
    if in_section and not done:
        out.append(f"{key}={value}")
        done = True
    if not found_section:
        if out and out[-1].strip():
            out.append("")
        out += [f"[{section}]", f"{key}={value}"]
    return "\n".join(out) + "\n"


def wslconfig_value(text: str, section: str, key: str) -> str:
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped[1:-1].strip().lower() == section.lower()
        elif in_section and "=" in stripped and not stripped.startswith(("#", ";")):
            k, v = stripped.split("=", 1)
            if k.strip().lower() == key.lower():
                return v.strip()
    return ""


def set_mirrored() -> bool:
    """networkingMode=mirrored in .wslconfig. True when it changed (needs a
    `wsl --shutdown` before it takes effect)."""
    path = wslconfig_path()
    text = path.read_text(encoding="utf-8-sig") if path.is_file() else ""
    if wslconfig_value(text, "wsl2", "networkingMode").lower() == "mirrored":
        return False
    if path.is_file():
        backup(path)
    path.write_text(
        splice_ini(text, "wsl2", "networkingMode", "mirrored"), encoding="utf-8", newline="\n"
    )
    return True


# ------------------------------------------------------------------ status


@dataclass
class Status:
    lines: list[tuple[str, str, str]] = field(default_factory=list)  # (state, what, detail)

    def add(self, state: str, what: str, detail: str = "") -> None:
        self.lines.append((state, what, detail))


def _windows_service(name: str) -> tuple[str, str]:
    pwsh = plat.find_pwsh()
    if not pwsh:
        return "", ""
    got = proc.capture(
        [pwsh, "-NoProfile", "-Command",
         f"$s = Get-Service {name} -ErrorAction SilentlyContinue; if ($s) {{ \"$($s.Status)|$($s.StartType)\" }}"],
        timeout=20,
    )  # fmt: skip
    if got is None or "|" not in got.stdout:
        return "", ""
    status, start = got.stdout.strip().split("|", 1)
    return status, start


def windows_status(s: dict[str, str]) -> Status:
    st = Status()
    status, start = _windows_service("sshd")
    if not status:
        st.add("no", "Windows sshd", "OpenSSH Server is not installed")
    else:
        st.add("ok" if status == "Running" else "warn", "Windows sshd", f"{status}, {start}")
    agent, agent_start = _windows_service("ssh-agent")
    st.add(
        "ok" if agent == "Running" and agent_start == "Automatic" else "warn",
        "Windows ssh-agent",
        f"{agent or 'missing'}, {agent_start or '-'}",
    )
    cfg = sshd_config_path()
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8", errors="replace")
        port = next(
            (
                ln.split()[1]
                for ln in text.splitlines()
                if ln.strip().lower().startswith("port ") and len(ln.split()) > 1
            ),
            "22",
        )
        managed = BLOCK_START.split(" (")[0] in text
        st.add(
            "ok" if port == s["sshWindowsPort"] or not wants_windows(s) else "warn",
            "Windows port",
            f"{port} (saved: {s['sshWindowsPort']}){'' if managed else ', not managed by the stack yet'}",
        )
        st.add(
            "info",
            "Admin keys file",
            "administrators_authorized_keys"
            if admin_keys_file_active(text)
            else "~/.ssh/authorized_keys",
        )
    keys = (
        parse_keys(authorized_keys_path().read_text(encoding="utf-8", errors="replace"))
        if authorized_keys_path().is_file()
        else []
    )
    st.add("info", "Authorized keys", f"{len(keys)} in ~/.ssh/authorized_keys")
    # A key other users can open is skipped by ssh, and an authorized_keys file
    # they can open is refused by sshd -- either one fails the key-login proof
    # for a reason that has nothing to do with the server.
    exposed = ssh_acl.exposed(ssh_dir())
    st.add(
        "warn" if exposed else "ok",
        "~/.ssh permissions",
        ssh_acl.summary(exposed) + "; fix: tstack doctor --repair" if exposed else "private",
    )
    return st


def windows_listener(port: str) -> str:
    """The process listening on a Windows TCP port, or "". Under mirrored
    networking WSL shares this port space, so a Windows listener blocks WSL."""
    pwsh = plat.find_pwsh() if plat.kind() == plat.WINDOWS else None
    if not pwsh or not port.isdigit():
        return ""
    got = proc.capture(
        [pwsh, "-NoProfile", "-Command",
         f"$c = Get-NetTCPConnection -State Listen -LocalPort {port} -ErrorAction SilentlyContinue |"
         " Select-Object -First 1; if ($c) { (Get-Process -Id $c.OwningProcess).ProcessName }"],
        timeout=20,
    )  # fmt: skip
    return got.stdout.strip() if got is not None and got.returncode == 0 else ""


def wsl_shutdown() -> None:
    proc.capture(["wsl.exe", "--shutdown"], timeout=120)


def start_keepalive() -> None:
    """Run the logon task now, so WSL (and its sshd) is up without a re-login."""
    proc.capture(["schtasks.exe", "/Run", "/TN", KEEPALIVE_TASK], timeout=30)


def verify_login(port: str, user: str, side: str = "windows") -> bool:
    """A key login to 127.0.0.1:<port> as <user> that lands on `side`."""
    client = ssh_client()
    if not client or not user:
        return False
    got = proc.capture([client, *verify_args(port, user, side)], timeout=30)
    return got is not None and got.returncode == 0 and PROOF[side][1] in (got.stdout or "")
