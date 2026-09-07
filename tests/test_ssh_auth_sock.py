"""The agent variable a multiplexer server cannot hand its panes.

THE FAILURE THIS EXISTS FOR

`ssh` worked from a terminal and failed in every herdr pane, with the agent
healthy the whole time. The cause is not herdr's: a long-lived server captures
its environment once, at start, and hands that same copy to every pane it will
ever spawn. `environment.d(5)` reaches only what the systemd user manager starts
AFTER it is read, so a variable added later never arrives. Measured on this
fleet -- herdr server started 09/04, the environment.d file that exports
SSH_AUTH_SOCK landed 09/06, and every pane opened since ran a shell without it.

What made it look like herdr's bug is that it was only half true. omarchy-dots
had already fixed the bash side in ~/.config/bash/rc.local; `dot_zshrc` had
nothing. Same machine, same variable removed:

    bash -ic  ->  SSH_AUTH_SOCK=/run/user/1000/ssh-agent.socket, 2 keys listed
    zsh  -ic  ->  SSH_AUTH_SOCK=[],  "Could not open a connection to your
                                      authentication agent."

herdr panes run zsh. So this is the zsh half of an existing fix, not a new idea,
and the tests below pin the four states that decide whether it is safe: a live
value must survive (`ssh -A`, 1Password), a dead one must be replaced (a path
from a previous login, inherited by a server that outlived it), and a machine
with no socket must be left exactly as it was -- which is what keeps this
correct on macOS, where launchd owns the variable, and away from Windows, where
a socket path in SSH_AUTH_SOCK breaks every ssh (`doc ssh-config`).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ZSHRC = ROOT / "dot_zshrc"


def _block() -> str:
    src = ZSHRC.read_text(encoding="utf-8")
    start = src.index("# SSH_AUTH_SOCK, for panes whose")
    return src[start : src.index("# Path to your Oh My Zsh installation.")]


def _resolve(tmp_path: Path, runtime_dir: Path | None, current: str | None) -> str:
    """Run the block alone in a bare zsh and report what SSH_AUTH_SOCK became."""
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "TERM": "dumb"}
    if runtime_dir is not None:
        env["XDG_RUNTIME_DIR"] = str(runtime_dir)
    if current is not None:
        env["SSH_AUTH_SOCK"] = current
    result = subprocess.run(
        [shutil.which("zsh") or "zsh", "-f", "-c", _block() + '\nprint -r -- "${SSH_AUTH_SOCK:-}"'],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=300,
        start_new_session=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.fixture
def runtime():
    """An $XDG_RUNTIME_DIR holding a real listening ssh-agent.socket.

    NOT under pytest's `tmp_path`. A unix socket's `sun_path` is about 104
    bytes, and macOS hands out `/private/var/folders/../pytest-of-runner/...`
    which is most of that before the filename -- the bind fails with "AF_UNIX
    path too long". `/tmp` is short on every platform this runs on, and on
    macOS it is the same `/private/tmp` by a shorter name.
    """
    import socket
    import tempfile

    base = tempfile.mkdtemp(dir="/tmp", prefix="ts-ssh-")
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(Path(base) / "ssh-agent.socket"))
    sock.listen(1)
    yield Path(base)
    sock.close()
    shutil.rmtree(base, ignore_errors=True)


pytestmark = pytest.mark.skipif(not shutil.which("zsh"), reason="zsh is unavailable")


def test_an_unset_variable_is_recovered_from_the_stable_socket_path(tmp_path, runtime):
    """The reported bug: a pane from a server that never had the variable."""
    assert _resolve(tmp_path, runtime, None) == str(runtime / "ssh-agent.socket")


def test_a_live_value_is_never_touched(tmp_path, runtime):
    """`ssh -A` forwarding and 1Password's IdentityAgent both arrive this way."""
    forwarded = runtime / "ssh-agent.socket"
    assert _resolve(tmp_path, runtime, str(forwarded)) == str(forwarded)


def test_a_dead_value_is_replaced(tmp_path, runtime):
    """A path from a previous login, inherited by a server that outlived it.
    Pointing at a socket that is gone is not a value worth protecting."""
    assert _resolve(tmp_path, runtime, "/nonexistent/agent.99") == str(runtime / "ssh-agent.socket")


def test_a_machine_with_no_socket_is_left_exactly_as_it_was(tmp_path):
    """macOS (launchd owns the variable, no $XDG_RUNTIME_DIR) and any server
    without the systemd unit. Setting a path we cannot verify would be worse
    than doing nothing -- on Windows it is what breaks ssh outright."""
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _resolve(tmp_path, empty, None) == ""
    assert _resolve(tmp_path, empty, "/some/forwarded.sock") == "/some/forwarded.sock"


def test_the_probe_does_not_fork(tmp_path):
    """This runs in every interactive zsh. `[[ -S ... ]]` is a builtin; a
    `test`/`stat`/`ls` spelling would be a process per shell."""
    # Comments in this block quote shell (`ssh -A`), so only real code counts.
    code = "\n".join(
        line for line in _block().splitlines() if line.strip() and not line.lstrip().startswith("#")
    )
    for forker in ("$(", "`", "stat ", "ls ", "/usr/bin/test"):
        assert forker not in code, f"{forker!r} would fork on every shell start"


def test_it_stays_in_step_with_the_bash_twin(tmp_path):
    """omarchy-dots owns the bash half. The socket PATH is the contract between
    them: if one ever names a different one, a machine gets two agents."""
    assert "${XDG_RUNTIME_DIR:-/run/user/$UID}/ssh-agent.socket" in _block()
