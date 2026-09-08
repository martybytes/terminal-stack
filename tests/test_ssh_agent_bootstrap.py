"""The agent that no login on a headless box ever starts.

THE FAILURE THIS EXISTS FOR

`tests/test_ssh_auth_sock.py` covers the other half: `dot_zshrc` RECOVERS
`SSH_AUTH_SOCK` from a socket that exists. On a fresh WSL Ubuntu 24.04 install
(measured 09/07/2026) no socket ever existed, so the recovery block correctly did
nothing and every `ssh` and every `git push` prompted for the key passphrase,
with `ssh-add -l` answering "Could not open a connection to your authentication
agent". Two things had to be true at once:

  * `ssh-agent.service` is `static` on Ubuntu -- no [Install] section, so
    `systemctl --user enable` has nothing to write -- and is ordered
    `Before=graphical-session-pre.target`, which a login with no desktop never
    reaches. Nothing pulled the unit in.
  * Starting it by hand ALSO did nothing, silently: Debian and Ubuntu run the
    agent through `/usr/lib/openssh/agent-launch`, which exits 0 without
    starting anything when `SSH_AUTH_SOCK` is already set in the user manager's
    environment -- and `gpg-agent-ssh.socket`, enabled by default, sets exactly
    that. `systemctl --user status` said "Started". No socket appeared.

`common_ssh_agent` fixes both. These tests are behavioural: the block is
extracted from `_common-posix.sh` and run in a real bash with `systemctl` stubbed,
because the two branches are about what it CALLS and in which order.
"""

from __future__ import annotations

import contextlib
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.shell_support import BASH  # noqa: E402

POSIX_LIB = ROOT / "bootstrap/_common-posix.sh"
ZSHRC = ROOT / "dot_zshrc"

pytestmark = pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")


def _block() -> str:
    """The ssh-agent region lifted whole, plus the one predicate it calls from
    outside it.

    Extracting the region rather than each function keeps the test honest about
    what ships together. `_ts_in_container` is pulled in by name instead: it is a
    statement about the machine and belongs beside `_ts_is_wsl`, so moving it
    down here to make the extraction simpler would put it where it reads oddly.
    """
    src = POSIX_LIB.read_text(encoding="utf-8")
    helper = re.search(r"(?m)^_ts_in_container\(\) \{.*?^\}", src, re.S)
    assert helper, "_ts_in_container moved or was renamed; repoint this anchor"
    start = src.index("# ── ssh-agent ")
    return f"{helper.group(0)}\n{src[start : src.index('# Run all standard install steps.')]}"


@contextlib.contextmanager
def _runtime():
    """A fake $XDG_RUNTIME_DIR holding a real, bindable unix socket at
    `.pending`, which the `systemctl` stub renames into place to stand for "the
    unit started and the agent bound".

    NOT under pytest's `tmp_path`, for the reason spelled out in full in
    `tests/test_ssh_auth_sock.py`: `sun_path` is about 104 bytes and macOS hands
    out `/private/var/folders/...` which is most of that before the filename.
    """
    with (
        tempfile.TemporaryDirectory(dir="/tmp") as base,
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock,
    ):
        sock.bind(str(Path(base) / ".pending"))
        sock.listen(1)
        yield Path(base)


STUBS = """
INFO=""; WARN=""
_ts_is_wsl() { return "${TS_WSL:-1}"; }
ts_note_failure() { echo "NOTE_FAILURE:$1"; }
ssh-agent() { :; }
_appear() { mv "$TS_RT/.pending" "$TS_RT/openssh_agent" 2>/dev/null || true; }
_dropin_appear() {
    if [ -f "$HOME/.config/systemd/user/ssh-agent.service.d/10-terminal-stack.conf" ]; then
        _appear
    fi
}
systemctl() {
    printf '%s\\n' "$*" >> "$TS_CALLS"
    case "${2:-}" in
        cat)     [ "${TS_UNIT:-1}" = 1 ] ;;
        start)   ${TS_ON_START:-:} ;;
        restart) ${TS_ON_RESTART:-:} ;;
        *)       : ;;
    esac
}
"""


def _run(home: Path, runtime: Path, *, systemd=True, env=None) -> tuple[str, list[str]]:
    """Run common_ssh_agent and report (stdout, the systemctl calls it made)."""
    calls = home / "calls.txt"
    calls.write_text("", encoding="utf-8")
    if systemd:
        (runtime / "systemd").mkdir(exist_ok=True)
    script = STUBS + _block() + "\ncommon_ssh_agent\n"
    result = subprocess.run(
        [BASH, "-c", script],
        env={
            "HOME": str(home),
            "PATH": "/usr/bin:/bin",
            "XDG_RUNTIME_DIR": str(runtime),
            "TS_RT": str(runtime),
            "TS_CALLS": str(calls),
            **(env or {}),
        },
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        start_new_session=True,
    )
    assert result.returncode == 0, result.stderr
    made = [ln for ln in calls.read_text(encoding="utf-8").splitlines() if ln]
    return result.stdout, made


def _dropin(home: Path) -> Path:
    return home / ".config/systemd/user/ssh-agent.service.d/10-terminal-stack.conf"


def test_it_pulls_in_the_unit_that_a_headless_login_never_reaches(tmp_path):
    """`add-wants default.target` writes the .wants symlink the static unit has
    no [Install] section to write for itself. Without it the agent is gone again
    at the next login even if this run started one by hand."""
    with _runtime() as rt:
        out, calls = _run(tmp_path, rt, env={"TS_ON_START": "_appear"})

    assert "--user add-wants default.target ssh-agent.service" in calls, (
        "nothing enabled the unit for the next login:\n" + "\n".join(calls)
    )
    assert "ssh-agent running" in out
    assert not _dropin(tmp_path).exists(), "wrote the override on a unit that worked"


def test_a_unit_that_starts_and_creates_nothing_gets_the_override(tmp_path):
    """The agent-launch guard. `start` succeeds, no socket appears, and the only
    way past it is to stop going through agent-launch at all."""
    with _runtime() as rt:
        out, calls = _run(tmp_path, rt, env={"TS_ON_START": ":", "TS_ON_RESTART": "_dropin_appear"})

    conf = _dropin(tmp_path)
    assert conf.exists(), "silently gave up on the failure this step exists for"
    body = conf.read_text(encoding="utf-8")
    assert "ExecStart=\n" in body, "did not clear the packaged ExecStart; systemd would run both"
    assert "--user daemon-reload" in calls, "wrote a drop-in systemd was never told to read"
    assert "--user restart ssh-agent.service" in calls
    assert "ssh-agent running" in out


def test_it_never_disables_anyone_elses_agent(tmp_path):
    """The first fix tried on the box that found this was `systemctl --user
    disable gpg-agent-ssh.socket`, which works and is not ours to do: a machine
    that really does keep its ssh keys in gpg would lose them from every session.
    The override makes the two coexist -- `dot_zshrc` never overwrites a live
    SSH_AUTH_SOCK, so whichever socket a session inherits still wins."""
    with _runtime() as rt:
        _out, calls = _run(
            tmp_path, rt, env={"TS_ON_START": ":", "TS_ON_RESTART": "_dropin_appear"}
        )

    assert not [c for c in calls if "gpg" in c], "reached for somebody else's unit:\n" + "\n".join(
        calls
    )
    assert "disable" not in " ".join(calls)


def test_a_live_agent_is_left_strictly_alone(tmp_path):
    """A restart drops every key already loaded into the running agent, and the
    person is then back to typing passphrases -- the exact thing this step is for.
    Re-running the bootstrap must never do that."""
    with _runtime() as rt:
        (rt / ".pending").rename(rt / "openssh_agent")
        out, calls = _run(tmp_path, rt)

    assert "already running" in out
    assert not [c for c in calls if " start " in f" {c} " or " restart " in f" {c} "], (
        "restarted a healthy agent:\n" + "\n".join(calls)
    )
    assert "--user add-wants default.target ssh-agent.service" in calls, (
        "skipped the add-wants because a socket happened to exist this session"
    )


def test_without_a_systemd_user_manager_it_changes_nothing(tmp_path):
    """A container, or a WSL distro without `systemd=true`. There is no unit to
    enable and no session to enable it in; the parity bootstrap container runs
    this code and must come out the other side."""
    with _runtime() as rt:
        out, calls = _run(tmp_path, rt, systemd=False)

    assert calls == [], "talked to a systemd that is not there:\n" + "\n".join(calls)
    assert not _dropin(tmp_path).exists()
    assert out.strip() == "", "printed at a container"

    with _runtime() as rt:
        out, _calls = _run(
            tmp_path, rt, systemd=False, env={"TS_WSL": "0", "TS_CONTAINER_MARKERS": ""}
        )
    assert "doc ssh-config" in out, "left a WSL user with no systemd and no hint"


def test_the_hint_for_a_wsl_user_does_not_follow_the_code_into_a_container(tmp_path):
    """`_ts_is_wsl` reads /proc/version, and a container shares the host KERNEL --
    so on a WSL2 host every container matches it. `tests/parity/run.sh bootstrap`
    runs this file for real in exactly that shape, which is where the hint was
    landing: addressed to a person, printed at a build log."""
    with _runtime() as rt:
        marker = tmp_path / "dockerenv"
        marker.write_text("", encoding="utf-8")
        out, _calls = _run(
            tmp_path,
            rt,
            systemd=False,
            env={"TS_WSL": "0", "TS_CONTAINER_MARKERS": str(marker)},
        )
    assert out.strip() == "", f"printed a person's hint into a container: {out!r}"


def test_an_absent_unit_is_not_an_error(tmp_path):
    """Not every Linux ships a user-scope ssh-agent.service. Skipping is right;
    failing the install over it is not."""
    with _runtime() as rt:
        out, calls = _run(tmp_path, rt, env={"TS_UNIT": "0"})

    assert not [c for c in calls if "start" in c or "add-wants" in c]
    assert "NOTE_FAILURE" not in out


def test_it_creates_the_socket_names_zshrc_looks_for(tmp_path):
    """The two halves are useless apart. `dot_zshrc` probes two names in a fixed
    order and the bootstrap must create one of exactly those -- an agent bound
    anywhere else is an agent no shell will ever find."""
    probed = re.search(r"for _ts_sock in ([^\n]+); do", ZSHRC.read_text(encoding="utf-8"))
    assert probed, "the zshrc probe loop moved; repoint this anchor"
    names = re.findall(r'/([A-Za-z0-9_.-]+)"', probed.group(1))
    assert names == ["ssh-agent.socket", "openssh_agent"], names

    block = _block()
    assert 'for s in "$rt/ssh-agent.socket" "$rt/openssh_agent"' in block, (
        "the bootstrap and dot_zshrc no longer probe the same two names, in the same order"
    )

    with _runtime() as rt:
        _run(tmp_path, rt, env={"TS_ON_START": ":", "TS_ON_RESTART": "_dropin_appear"})
    body = _dropin(tmp_path).read_text(encoding="utf-8")
    assert "-a %t/openssh_agent" in body, "bound the agent where no shell looks for it"


def test_the_installer_runs_it():
    """A step nothing calls is a step that does not exist. `common_install_all`
    is the one orchestrator both linux-bootstrap.sh and wsl-bootstrap.sh reach."""
    src = POSIX_LIB.read_text(encoding="utf-8")
    body = re.search(r"(?m)^common_install_all\(\) \{.*?^\}", src, re.S)
    assert body, "common_install_all not found"
    assert "common_ssh_agent" in body.group(0)
