"""The one line the Windows gitconfig does not share with its canonical twin.

THE FAILURE THIS EXISTS FOR

After a `tstack update` every git command over ssh asked for the key passphrase
-- in PowerShell and in a fresh WezTerm alike -- while `ssh-add -l` in the same
pane listed both keys. Nothing was wrong with the agent. Unset, `core.sshCommand`
leaves git running Git for Windows' BUNDLED MSYS ssh, which cannot speak the
named pipe the Windows agent listens on. Measured in one pane, one environment:

    C:/Windows/System32/OpenSSH/ssh.exe  -T git@github.com  ->  authenticated
    C:/Program Files/Git/usr/bin/ssh.exe -T git@github.com  ->  Permission denied

Non-interactively that is a denial; interactively ssh falls back to prompting,
which is what a human sees. The fix has to be Windows-only -- the value is an
absolute Windows path, and the canonical copy is applied to WSL, macOS and native
Linux, where it would break git outright.

So the two files are identical EXCEPT that line, and that is a shape worth
pinning in both directions: a mirror that silently loses the line puts the
passphrase prompts back, and a canonical file that silently gains it breaks
every POSIX target. Until this change there was no gitconfig test at all.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "dot_config/git/terminal-stack.gitconfig"
MIRROR = ROOT / "windows/.config/git/terminal-stack.gitconfig"

SSH_LINE = "\tsshCommand = C:/Windows/System32/OpenSSH/ssh.exe"


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def test_both_files_exist() -> None:
    """A path assertion that cannot go vacuous when a file is moved."""
    assert CANONICAL.is_file(), CANONICAL
    assert MIRROR.is_file(), MIRROR


def test_the_windows_mirror_pins_git_to_native_openssh() -> None:
    """The whole point: without this, git prompts for the passphrase forever."""
    assert SSH_LINE in _lines(MIRROR)


def test_the_canonical_copy_never_sets_sshcommand() -> None:
    """It is applied to WSL, macOS and native Linux, where a C:/ path is fatal.

    Settings only -- the header names core.sshCommand to explain the exception,
    so a bare substring check would fail on its own documentation."""
    settings = [ln for ln in _lines(CANONICAL) if not ln.lstrip().startswith("#")]
    assert not [ln for ln in settings if "sshCommand" in ln]


def test_the_two_differ_by_exactly_the_sshcommand_block() -> None:
    """Everything else stays in lockstep. Strip the Windows-only block from the
    mirror and the two must be identical again -- if they are not, a real edit
    landed in one copy and never reached the other."""
    mirror = _lines(MIRROR)
    end = mirror.index(SSH_LINE)
    start = end
    while mirror[start - 1].lstrip().startswith("#"):
        start -= 1
    assert mirror[start].lstrip().startswith("# Which ssh git runs")
    assert mirror[start - 1] == "", "the block is separated by one blank line"
    stripped = mirror[: start - 1] + mirror[end + 1 :]
    assert stripped == _lines(CANONICAL)


def test_the_header_documents_the_divergence() -> None:
    """The header claimed 'byte-identical mirror' until this change. A stale
    invariant is worse than none -- someone copies the canonical file over and
    silently removes the fix. Both copies must carry the corrected wording."""
    for path in (CANONICAL, MIRROR):
        body = path.read_text(encoding="utf-8")
        assert "byte-identical mirror" not in body, path
        assert "core.sshCommand" in body, path
