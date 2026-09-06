"""Distro detection, and the Arch/Omarchy half of the installer contract.

The bug these exist for: `install-linux.sh` died on every Arch host at
`sudo apt-get update` -- the FIRST thing `common_install_all` called -- before
the questionnaire, before chezmoi, before anything was written. Nothing in the
repo executed an install path on a non-apt machine, and nothing even named Arch,
so the whole platform failed with `sudo: apt-get: command not found` as its
entire explanation.

`tests/parity/run.sh arch omarchy` and `arch-bootstrap` / `omarchy-bootstrap`
are the containers that RUN it. These are the static and behavioural gates that
run everywhere, including on the macOS and Windows CI legs where no pacman
exists.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.shell_support import BASH  # noqa: E402
from tstack import apps  # noqa: E402
from tstack import platform as plat  # noqa: E402


@pytest.fixture(autouse=True)
def _dev_clone(monkeypatch):
    """Point the catalog reader at THIS checkout, not whatever clone is
    installed -- the same fixture tests/test_apps_catalog.py uses, and for the
    same reason: without it apps.catalog() is empty and every assertion that
    iterates it passes vacuously."""
    monkeypatch.setenv("TERMINAL_STACK_DIR", str(ROOT))
    apps.clear_cache()
    yield
    apps.clear_cache()


DETECT = ROOT / "bootstrap/_detect.sh"
ARCH_LIB = ROOT / "bootstrap/_common-arch.sh"
DEBIAN_LIB = ROOT / "bootstrap/_common-debian.sh"
POSIX_LIB = ROOT / "bootstrap/_common-posix.sh"

# The contract _common-posix.sh documents. Each distro half must supply all of
# it; neither may supply anything else that posix already owns.
CONTRACT = (
    "common_pkg_prereqs",
    "common_install_selected_apps",
    "common_install_terminals",
    "common_zsh_base",
    "common_login_shell_zsh",
    "common_chezmoi",
    "common_starship",
)
SHARED = (
    "common_require_non_root",
    "common_oh_my_zsh",
    "common_nerd_font_jetbrains",
    "common_tty_prompt",
    "common_workspace_config",
    "common_git_include",
    "common_install_all",
)


def _defined(path: Path) -> set[str]:
    """Top-level function names defined in a shell library."""
    text = path.read_text(encoding="utf-8")
    return set(re.findall(r"(?m)^([a-zA-Z_][a-zA-Z0-9_]*)\(\)", text))


def _detect(expr: str, **env: str) -> str:
    """Evaluate an expression against _detect.sh with os-release forced."""
    got = subprocess.run(
        [BASH, "-c", f". bootstrap/_detect.sh; {expr}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        start_new_session=True,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", **env},
    )
    return got.stdout.strip()


# ── detection ─────────────────────────────────────────────────────────────────

# id, id_like, is_arch, is_omarchy. The real values, from live boxes: Omarchy
# 4.0.1 answers omarchy/arch; Ubuntu answers ubuntu/debian.
DISTRO_CASES = [
    ("omarchy", "arch", True, True),
    ("arch", "", True, False),
    ("cachyos", "arch", True, False),
    ("endeavouros", "arch", True, False),
    ("debian", "", False, False),
    ("ubuntu", "debian", False, False),
    ("linuxmint", "ubuntu debian", False, False),
    ("fedora", "", False, False),
    # An unknown derivative that only declares its family. ID_LIKE is
    # space-separated, which is why membership is tested with padding rather
    # than equality -- `arch` must match inside "arch something".
    ("someotherarch", "arch base", True, False),
    ("", "", False, False),
]


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
@pytest.mark.parametrize(("did", "like", "is_arch", "is_om"), DISTRO_CASES)
def test_bash_and_python_agree_on_every_distro(monkeypatch, did, like, is_arch, is_om):
    """Two readers of /etc/os-release, one answer.

    They cannot both be checked against the live box -- there is only one distro
    under any given test run -- so both are driven through the same overrides.
    Disagreement here is how the picker offered a tool the installer's catalog
    lacked, one platform axis over.
    """
    env = {"TS_DISTRO_ID": did, "TS_DISTRO_LIKE": like}
    assert _detect("ts_distro_id", **env) == did
    assert (_detect("ts_is_arch && echo yes || echo no", **env) == "yes") is is_arch
    assert (_detect("ts_is_omarchy && echo yes || echo no", **env) == "yes") is is_om

    monkeypatch.setenv("TS_DISTRO_ID", did)
    monkeypatch.setenv("TS_DISTRO_LIKE", like)
    plat.clear_distro_cache()
    try:
        assert plat.distro() == did
        assert plat.is_arch() is is_arch
        assert plat.is_omarchy() is is_om
    finally:
        plat.clear_distro_cache()


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_the_package_manager_picks_the_installer_library():
    """`ts_common_lib` is the line whose absence was the whole bug."""
    assert _detect("ts_common_lib", TS_PKG_MANAGER="pacman") == "_common-arch.sh"
    assert _detect("ts_common_lib", TS_PKG_MANAGER="apt") == "_common-debian.sh"
    # An unknown manager falls back to apt rather than to nothing: a host with
    # neither gets a named error from linux-bootstrap.sh, not a missing file.
    assert _detect("ts_common_lib", TS_PKG_MANAGER="none") == "_common-debian.sh"
    for lib in ("_common-arch.sh", "_common-debian.sh"):
        assert (ROOT / "bootstrap" / lib).is_file(), f"ts_common_lib names a missing {lib}"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_os_release_says_which_manager_before_the_binary_does():
    """A box can carry a package manager it does not run on -- WSL sees the
    Windows-side tooling, and a Debian box can have pacman installed as a
    curiosity. Picking by `command -v` alone is how the wrong installer gets
    chosen; os-release decides first."""
    # Arch id + pacman present -> pacman, even though this test box may also
    # have apt. Driven through TS_PKG_MANAGER's absence, so the real logic runs.
    got = _detect("ts_is_arch && echo arch || echo other", TS_DISTRO_ID="arch")
    assert got == "arch"
    got = _detect("ts_is_debianish && echo deb || echo other", TS_DISTRO_ID="ubuntu")
    assert got == "deb"


# ── the contract ──────────────────────────────────────────────────────────────


def test_both_distro_halves_supply_the_whole_contract():
    for lib in (ARCH_LIB, DEBIAN_LIB):
        missing = [fn for fn in CONTRACT if fn not in _defined(lib)]
        assert not missing, f"{lib.name} does not define {missing}"


def test_neither_distro_half_redefines_what_posix_owns():
    """A redefinition is a silent fork of the shared behaviour -- and for
    common_install_all it would be a fork of the ORDERING, which encodes two
    separate incidents (persistence before optional installs; chezmoi before
    persistence)."""
    posix = _defined(POSIX_LIB)
    for fn in SHARED:
        assert fn in posix, f"_common-posix.sh no longer defines {fn}"
    for lib in (ARCH_LIB, DEBIAN_LIB):
        clashes = sorted(_defined(lib) & set(SHARED))
        assert not clashes, f"{lib.name} redefines shared {clashes}"


def _code_only(path: Path) -> str:
    """The file with comment lines and trailing comments removed.

    Both libraries talk ABOUT the other package manager at length -- explaining
    why Arch needs no `batcat` symlink, why the apt side needs a GitHub fallback
    -- and that prose is the most useful part of them. Only executable lines can
    be evidence of reaching for the wrong tool.
    """
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        out.append(line.split("#", 1)[0] if " #" in line else line)
    return "\n".join(out)


def test_each_distro_half_speaks_only_its_own_package_manager():
    """apt in the pacman file is a copy-paste that would fail exactly the way
    the original bug did, one level down."""
    arch = _code_only(ARCH_LIB)
    for banned in ("apt-get", "apt install", "dpkg", "add-apt-repository"):
        assert banned not in arch, f"_common-arch.sh reaches for {banned}"
    deb = _code_only(DEBIAN_LIB)
    for banned in ("pacman", "omarchy-pkg-add", "yay "):
        assert banned not in deb, f"_common-debian.sh reaches for {banned}"


def test_the_installer_never_runs_apt_unguarded():
    """THE regression test for the original bug.

    `install-linux.sh` ran `sudo apt-get update` with no check at all, so every
    Arch host died on line one of the bootstrap. Every apt call in the installer
    entry point must sit under a `command -v apt-get` guard.
    """
    text = (ROOT / "install-linux.sh").read_text(encoding="utf-8")
    guard = text.index("command -v apt-get")
    for match in re.finditer(r"^\s*sudo apt-get", text, re.M):
        assert match.start() > guard, (
            "install-linux.sh runs apt-get before testing that apt-get exists"
        )
    # And the pacman arm has to actually be there, or the guard just turns a
    # crash into a different kind of nothing.
    assert "sudo pacman" in text


# ── the Arch package mapping ──────────────────────────────────────────────────


def _linux_catalog_ids() -> list[str]:
    """Catalog ids a Linux box could install, minus the AI route.

    The `ai` group is an install ROUTE, not a package: its members go to
    ts_install_ai_cli and no package manager carries any of them.
    """
    return [
        a.id for a in apps.catalog() if a.group != "ai" and a.platforms in ("all", "posix", "linux")
    ]


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_every_installable_catalog_id_has_an_arch_package():
    """A tool that silently does not install is this repo's recurring failure.

    `ts_arch_pkg` returning non-zero means "no case arm", which the installer
    reports and skips. That is the right behaviour at runtime and the wrong
    state to ship: adding a row to apps.conf must not quietly cost Arch users
    the tool.
    """
    ids = _linux_catalog_ids()
    assert ids, "the catalog reader returned nothing; the rest of this is vacuous"
    script = f". bootstrap/_common-arch.sh >/dev/null 2>&1\nfor i in {' '.join(ids)}; do\n"
    script += '  ts_arch_pkg "$i" >/dev/null 2>&1 || echo "$i"\ndone\n'
    got = subprocess.run(
        [BASH, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        start_new_session=True,
    )
    unmapped = got.stdout.split()
    assert not unmapped, f"no Arch package mapping for: {unmapped} (add them to ts_arch_pkg)"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_the_arch_package_names_that_differ_from_their_id():
    """Six ids are not their own package name on Arch. Getting one wrong is a
    pacman error at install time, which is loud -- but getting one SILENTLY
    right-looking (e.g. `tldr`, which exists as a different project) is not."""
    script = ". bootstrap/_common-arch.sh >/dev/null 2>&1\n"
    for app_id in ("delta", "gh", "tldr", "node", "pipx", "poetry", "tmux", "llmfit"):
        script += f'printf "%s=%s\\n" {app_id} "$(ts_arch_pkg {app_id})"\n'
    got = subprocess.run(
        [BASH, "-c", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        start_new_session=True,
    )
    mapped = dict(line.split("=", 1) for line in got.stdout.strip().splitlines())
    assert mapped["delta"] == "git-delta"
    assert mapped["gh"] == "github-cli"
    assert mapped["tldr"] == "tealdeer"
    assert mapped["node"] == "nodejs"
    assert mapped["pipx"] == "python-pipx"
    assert mapped["poetry"] == "python-poetry"
    # The common case: the id IS the package.
    assert mapped["tmux"] == "tmux"
    # The one catalog entry Arch does not package at all; empty, not an error,
    # so the GitHub-release fallback handles it.
    assert mapped["llmfit"] == ""


# ── Omarchy's opinions ────────────────────────────────────────────────────────


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_omarchy_login_shell_is_left_alone_and_plain_arch_is_not():
    """Behavioural, not a grep: run common_login_shell_zsh with chsh stubbed and
    see whether it fires.

    Omarchy is bash-first by construction -- ~/.bashrc sources
    $OMARCHY_PATH/default/bash/rc, which is where its aliases, functions and
    shell init live -- and it ships an official `omarchy-zsh` package rather
    than expecting a chsh. Changing the login shell during a dotfiles install
    would take all of that away silently.
    """
    fn = re.search(
        r"(?m)^common_login_shell_zsh\(\) \{.*?^\}", ARCH_LIB.read_text(encoding="utf-8"), re.S
    )
    assert fn, "common_login_shell_zsh not found in _common-arch.sh"

    def run(distro_id: str) -> str:
        script = (
            'INFO=""; WARN=""\n'
            f'ts_is_omarchy() {{ [ "{distro_id}" = omarchy ]; }}\n'
            'getent() { echo "u:x:1:1::/home/u:/bin/bash"; }\n'
            'sudo() { if [ "$1" = chsh ]; then echo "CHSH-RAN"; fi; }\n'
            f"{fn.group(0)}\n"
            "common_login_shell_zsh\n"
        )
        return subprocess.run(
            [BASH, "-c", script],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            start_new_session=True,
        ).stdout

    omarchy = run("omarchy")
    assert "CHSH-RAN" not in omarchy, "the bootstrap chsh'd on Omarchy"
    assert "bash-first" in omarchy, "it changed nothing and did not say why"

    plain = run("arch")
    assert "CHSH-RAN" in plain, "plain Arch stopped switching to zsh"


def test_omarchy_owns_the_runtime_managers():
    """Omarchy standardises on mise. A second version manager competes for the
    same binaries with PATH order deciding the winner -- and an id that is
    offered, ticked and then skipped is one `ts_apps_pending` reports missing on
    every update, forever."""
    assert {"fnm", "node", "python"} == apps.MISE_OWNED
    arch = ARCH_LIB.read_text(encoding="utf-8")
    assert "mise" in arch, "_common-arch.sh does not mention mise at all"
    # uv/pipx/ruff/ipython are TOOLS, not version managers, and Omarchy's own
    # `dev-env python` installs uv. They must stay in the catalog.
    for keep in ("uv", "pipx", "ruff", "ipython"):
        assert keep not in apps.MISE_OWNED


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_the_mise_veto_agrees_between_bash_and_python():
    """Two readers of one rule. They disagreed once already, on the platform
    axis, and the picker offered a tool the installer's catalog lacked."""
    got = subprocess.run(
        [
            BASH,
            "-c",
            'TS_DISTRO_ID=omarchy . bootstrap/_config.sh >/dev/null 2>&1; echo "$TS_APPS_ALL"',
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        start_new_session=True,
        env={"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "TERMINAL_STACK_DIR": str(ROOT)},
    )
    offered = set(got.stdout.split())
    assert offered, "the bash catalog came back empty; the rest of this is vacuous"
    for vetoed in apps.MISE_OWNED:
        assert vetoed not in offered, f"bash still offers {vetoed} on Omarchy"
    assert "uv" in offered, "the veto took uv with it"


# ── tmux: one path, never both ────────────────────────────────────────────────


def test_the_two_tmux_paths_are_mutually_exclusive():
    """tmux reads ~/.tmux.conf OR $XDG_CONFIG_HOME/tmux/tmux.conf, and on tmux
    3.7c the XDG one wins when both exist (probed in a scratch $HOME: prefix
    C-Space from the XDG file beat prefix C-a from ~/.tmux.conf).

    Omarchy ships its config at the XDG path, so the stack writing ~/.tmux.conf
    there produced a file tmux never read -- applied, shown in the diff, and
    inert. Both files present is the silently-wrong state, so .chezmoiignore has
    to name each in the other's branch.
    """
    ignore = (ROOT / ".chezmoiignore").read_text(encoding="utf-8")
    block = ignore[ignore.index("tmux: ONE of the two paths") :]
    block = block[: block.index("{{ end }}")]
    assert '"distroId"' in block and "omarchy" in block
    assert ".tmux.conf" in block and ".config/tmux/**" in block
    # The gate has two arms; one arm would ignore a file on every machine.
    assert "{{ else }}" in block


def test_both_tmux_paths_share_one_body():
    """Two hand-maintained copies of a tmux config is the drift this repo keeps
    paying for. The body is a chezmoi shared template; each path is a wrapper."""
    core = ROOT / ".chezmoitemplates/tmux-core"
    theme = ROOT / ".chezmoitemplates/tmux-theme"
    assert core.is_file() and theme.is_file()
    home = (ROOT / "dot_tmux.conf.tmpl").read_text(encoding="utf-8")
    xdg = (ROOT / "dot_config/tmux/tmux.conf.tmpl").read_text(encoding="utf-8")
    for body in (home, xdg):
        assert '{{ template "tmux-core" . }}' in body
    assert '{{ template "tmux-theme" . }}' in home
    # Each wrapper may carry only the ONE setting that is genuinely per-path --
    # anything more is a copy of the shared body starting to grow. Off Omarchy
    # the old C-b binding is released; on Omarchy it is kept as the second
    # prefix, because Omarchy ships prefix C-Space + prefix2 C-b and herdr
    # mirrors that config deliberately.
    allowed = {
        "dot_tmux.conf.tmpl": {"unbind C-b"},
        "dot_config/tmux/tmux.conf.tmpl": {"set -g prefix2 C-b"},
    }
    for body, name in ((home, "dot_tmux.conf.tmpl"), (xdg, "dot_config/tmux/tmux.conf.tmpl")):
        stray = [
            line
            for line in body.splitlines()
            if line.startswith(("set -g", "setw -g", "set -s", "set -as", "bind", "unbind"))
            and line.strip() not in allowed[name]
        ]
        assert not stray, f"{name} carries settings of its own: {stray}"


def test_the_omarchy_tmux_config_sources_omarchys_own():
    """Replacing it would silently drop Alt+Enter splits, Alt+1..9 window
    switching and the Super+/ keybindings popup -- and `omarchy-theme-set-tmux`
    would then be re-tinting a bar the stack had overwritten."""
    xdg = (ROOT / "dot_config/tmux/tmux.conf.tmpl").read_text(encoding="utf-8")
    assert "source-file -q /usr/share/omarchy/config/tmux/tmux.conf" in xdg
    # `-q` is load-bearing: without it a missing file is an error, and this
    # template also renders on plain Arch, where Omarchy is not installed.
    assert "source-file -q " in xdg
    # Sourced BEFORE the stack's own settings, or the stack's prefix loses.
    assert xdg.index("source-file") < xdg.index('{{ template "tmux-core" . }}')
    # The stack's baked light/dark status bar is NOT applied on Omarchy: it
    # would pin the bar while every other surface follows the active theme.
    assert '{{ if not $omarchy }}{{ template "tmux-theme" . }}{{ end -}}' in xdg


# ── wezterm ───────────────────────────────────────────────────────────────────


def test_wezterm_knows_pacman():
    """Without a pacman arm, channel() fell through to "unknown" on Arch --
    WezTerm on PATH, no package manager owning it -- and install() then refused
    to touch an ordinary `extra/wezterm`, reporting it as hand-placed."""
    src = (ROOT / "tstack/commands/wezterm.py").read_text(encoding="utf-8")
    assert 'shutil.which("pacman")' in src
    assert '"wezterm-git"' in src, "the Arch nightly package is not named"
    assert "_pacman_install" in src
    # It must NOT run an AUR helper on its own: wezterm-git builds from source,
    # unattended, inside what the user thinks is a dotfiles install.
    body = src[src.index("def _pacman_install") : src.index("def install(")]
    assert "yay -S wezterm-git" in body, "the command is not even printed"
    assert not re.search(r'_run\(\[\s*"yay"', body), "it shells out to yay by itself"


# ── parity coverage ───────────────────────────────────────────────────────────


def test_the_parity_runner_covers_arch_and_omarchy():
    """The gate that would have caught the original bug. `bash -n` cannot see an
    unset variable and a static resolver cannot see an empty catalog; only
    running the installer on a non-apt machine finds a hard-coded apt call."""
    run_sh = (ROOT / "tests/parity/run.sh").read_text(encoding="utf-8")
    for target in ("[arch]", "[omarchy]", "[arch-bootstrap]", "[omarchy-bootstrap]"):
        assert target in run_sh, f"no parity target {target}"
    # The suite targets run by default; the bootstrap ones are opted into, the
    # same bargain the Debian bootstrap target strikes (it installs packages and
    # wants the network).
    default = re.search(r"DEFAULT_TARGETS=\(([^)]*)\)", run_sh).group(1).split()
    assert "arch" in default and "omarchy" in default
    assert "arch-bootstrap" not in default and "omarchy-bootstrap" not in default
    for f in ("Dockerfile.arch", "Dockerfile.arch-bootstrap"):
        assert (ROOT / "tests/parity" / f).is_file(), f"missing tests/parity/{f}"
