"""The desktop agent apps: Herdr app, Orca and T3 Code.

They are route-listed (ts_app_is_desktop / Test-TsAppIsDesktop) because no one
package manager has all three anywhere: casks on macOS, winget plus herdr.dev's
script on Windows, .debs on Debian, AppImages on Arch (AUR-only there, and the
stack never runs an AUR helper).

The behavioural tests stub `uname`, `brew`, `curl`, `sudo` and `apt-get` on a
private PATH, so they run on every CI leg whatever the host is.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.shell_support import BASH, bash_path  # noqa: E402
from tstack import apps  # noqa: E402
from tstack import platform as plat  # noqa: E402

DESKTOP = ["herdr-app", "orca", "t3code"]


@pytest.fixture(autouse=True)
def _dev_clone(monkeypatch):
    monkeypatch.setenv("TERMINAL_STACK_DIR", str(ROOT))
    apps.clear_cache()
    yield
    apps.clear_cache()


# ------------------------------------------------------------------ catalog


def test_desktop_group_is_the_three_apps_opt_in_and_never_on_wsl():
    rows = [a for a in apps.catalog() if a.group == "desktop"]
    assert [a.id for a in rows] == DESKTOP
    for a in rows:
        assert a.classes == "none", f"{a.id} must never be pre-ticked (servers)"
        assert a.platforms == "desktop"
        assert a.installable(plat.MACOS)
        assert a.installable(plat.LINUX)
        assert a.installable(plat.WINDOWS)
        assert not a.installable(plat.WSL), "a WSL install writes nothing under /mnt/c"
    assert not set(DESKTOP) & set(apps.recommended())
    assert not set(DESKTOP) & set(apps.sysadmin())


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_bash_route_list_is_exactly_the_desktop_group():
    ids = " ".join(a.id for a in apps.catalog())
    got = subprocess.run(
        [
            BASH,
            "-c",
            ". bootstrap/_config.sh >/dev/null 2>&1; "
            f'for i in {ids}; do ts_app_is_desktop "$i" && echo "$i"; done',
        ],
        cwd=ROOT,
        start_new_session=True,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert got.stdout.split() == DESKTOP


def test_pwsh_route_list_names_the_same_ids():
    ps = (ROOT / "bootstrap/_config.ps1").read_text(encoding="utf-8")
    assert "$script:TsDesktopApps = @('herdr-app', 'orca', 't3code')" in ps
    # The two winget ids verified against winget-pkgs; herdr-app has none.
    assert "orca       = 'StablyAI.Orca'" in ps
    assert "t3code     = 'T3Tools.T3Code'" in ps
    assert "herdr-app  =" not in ps.split("$script:TsWingetIds = @{", 1)[1].split("}", 1)[0]


def test_no_aur_helper_in_the_desktop_route():
    """All three are AUR-only on Arch; the stack never runs an AUR helper."""
    sh = (ROOT / "bootstrap/_config.sh").read_text(encoding="utf-8")
    block = sh[sh.index("ts_app_is_desktop() {") : sh.index("ts_install_desktops() {")]
    assert "yay " not in block and "paru " not in block
    assert "--adopt" not in block and "--force" not in block


def test_neither_distro_half_defines_the_desktop_route():
    for half in ("_common-debian.sh", "_common-arch.sh"):
        text = (ROOT / "bootstrap" / half).read_text(encoding="utf-8")
        assert "ts_install_desktop_app()" not in text
        assert 'ts_install_desktops "$apps"' in text, half


# ------------------------------------------------------------------ behaviour


def _stubs(
    tmp: Path, *, os_name: str, machine: str, apt: bool = False, pacman: bool = False
) -> Path:
    """A PATH dir with uname/brew/curl/sudo/apt-get stubs that log to calls.log."""
    bin_dir = tmp / "bin"
    bin_dir.mkdir()
    log = tmp / "calls.log"
    releases = tmp / "releases.json"
    releases.write_text(
        json.dumps(
            {
                "assets": [
                    {"browser_download_url": f"https://example.invalid/{n}"}
                    for n in (
                        "orca-ide_1.4.261_amd64.deb",
                        "orca-ide_1.4.261_arm64.deb",
                        "orca-linux-arm64.AppImage",
                        "orca-linux.AppImage",
                        "T3-Code-0.1.9-amd64.deb",
                        "T3-Code-0.1.9-arm64.AppImage",
                        "T3-Code-0.1.9-x86_64.AppImage",
                    )
                ]
            },
            indent=1,
        )
    )
    scripts = {
        "uname": f'case "$1" in -s) echo {os_name} ;; -m) echo {machine} ;; *) echo {os_name} ;; esac',
        "brew": f'echo "brew $*" >> "{log}"',
        "sudo": f'echo "sudo $*" >> "{log}"; "$@"',
        # -o FILE URL -> write a fake payload; a bare URL -> the releases JSON.
        "curl": (
            f'echo "curl $*" >> "{log}"\n'
            'out=""; while [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift ;; esac; shift; done\n'
            f'if [ -n "$out" ]; then echo payload > "$out"; else cat "{releases}"; fi'
        ),
        "ldconfig": "echo libfuse.so.2",
    }
    if apt:
        scripts["apt-get"] = f'echo "apt-get $*" >> "{log}"'
    if pacman:
        # Arch is told apart by pacman: a CI runner has a real apt-get on PATH.
        scripts["pacman"] = f'echo "pacman $*" >> "{log}"'
    for name, body in scripts.items():
        p = bin_dir / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(0o755)
    log.touch()
    return bin_dir


def _run(tmp: Path, bin_dir: Path, body: str, **env: str) -> subprocess.CompletedProcess:
    base = {
        # bash_path: a raw C:\ path splits on its colon, and the stubs never run.
        "PATH": f"{bash_path(bin_dir)}:/usr/bin:/bin",
        "HOME": str(tmp / "home"),
        "XDG_DATA_HOME": str(tmp / "home/.local/share"),
        "TS_HEADLESS_RESOLVED": "0",
    }
    base.update(env)
    (tmp / "home").mkdir(exist_ok=True)
    return subprocess.run(
        [BASH, "-c", ". bootstrap/_config.sh >/dev/null 2>&1; " + body],
        cwd=ROOT,
        start_new_session=True,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=base,
    )


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_macos_leaves_a_hand_installed_bundle_alone_and_casks_the_rest(tmp_path):
    apps_dir = tmp_path / "Applications"
    (apps_dir / "T3 Code (Beta).app").mkdir(parents=True)
    (apps_dir / "Herdr.app").mkdir()
    bin_dir = _stubs(tmp_path, os_name="Darwin", machine="arm64")
    got = _run(
        tmp_path,
        bin_dir,
        'ts_install_desktops "herdr-app orca t3code"',
        TS_APPLICATIONS_DIR=str(apps_dir),
    )
    calls = (tmp_path / "calls.log").read_text()
    assert "t3code: already installed; leaving it alone" in got.stdout
    assert "herdr-app: already installed; leaving it alone" in got.stdout
    # The TAP, never the bare `orca` cask (Plotly's).
    assert calls.strip() == "brew install --cask stablyai/orca/orca"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_macos_intel_skips_herdr_app_which_has_no_intel_build(tmp_path):
    bin_dir = _stubs(tmp_path, os_name="Darwin", machine="x86_64")
    got = _run(
        tmp_path,
        bin_dir,
        "ts_install_desktop_app herdr-app",
        TS_APPLICATIONS_DIR=str(tmp_path / "none"),
    )
    assert "no Intel macOS build" in got.stdout
    assert (tmp_path / "calls.log").read_text() == ""


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_debian_installs_the_matching_deb_through_apt(tmp_path):
    bin_dir = _stubs(tmp_path, os_name="Linux", machine="x86_64", apt=True)
    got = _run(tmp_path, bin_dir, 'ts_install_desktops "orca t3code"')
    calls = (tmp_path / "calls.log").read_text()
    assert "orca-ide_1.4.261_amd64.deb" in calls, got.stdout + got.stderr
    assert "T3-Code-0.1.9-amd64.deb" in calls
    assert calls.count("sudo apt-get install -y ") == 2
    assert "arm64" not in calls


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_arch_installs_appimages_with_a_launcher_entry(tmp_path):
    bin_dir = _stubs(tmp_path, os_name="Linux", machine="aarch64", pacman=True)
    got = _run(tmp_path, bin_dir, 'ts_install_desktops "orca t3code"')
    share = tmp_path / "home/.local/share"
    calls = (tmp_path / "calls.log").read_text()
    assert "orca-linux-arm64.AppImage" in calls, got.stdout + got.stderr
    assert "T3-Code-0.1.9-arm64.AppImage" in calls
    for app_id in ("orca", "t3code"):
        img = share / f"terminal-stack/apps/{app_id}.AppImage"
        assert img.is_file()
        # NTFS has no exec bit: under Git Bash `chmod +x` succeeds and changes nothing.
        if sys.platform != "win32":
            assert img.stat().st_mode & 0o111
        entry = (share / f"applications/{app_id}.desktop").read_text()
        # as_posix on both sides: on Windows HOME is backslashed and the script appends with "/".
        assert f'Exec="{img.as_posix()}" %U' in entry.replace("\\", "/")
    # Now present: a second run downloads nothing.
    (tmp_path / "calls.log").write_text("")
    again = _run(tmp_path, bin_dir, 'ts_install_desktops "orca t3code"')
    assert (tmp_path / "calls.log").read_text() == ""
    assert again.stdout.count("leaving it alone") == 2


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_the_orca_screen_reader_on_path_is_not_the_orca_app(tmp_path):
    bin_dir = _stubs(tmp_path, os_name="Linux", machine="x86_64")
    reader = bin_dir / "orca"
    reader.write_text("#!/bin/sh\nexit 0\n")
    reader.chmod(0o755)
    got = _run(tmp_path, bin_dir, "ts_desktop_app_present orca && echo yes || echo no")
    assert got.stdout.strip() == "no"


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_wsl_and_headless_install_nothing(tmp_path):
    bin_dir = _stubs(tmp_path, os_name="Linux", machine="x86_64", apt=True)
    wsl = _run(tmp_path, bin_dir, "_ts_is_wsl() { return 0; }; ts_install_desktop_app orca")
    assert "Windows side" in wsl.stdout
    headless = _run(
        tmp_path, bin_dir, "ts_is_headless() { return 0; }; ts_install_desktop_app t3code"
    )
    assert "headless" in headless.stdout
    assert (tmp_path / "calls.log").read_text() == ""


@pytest.mark.skipif(not BASH, reason="compatible bash is unavailable")
def test_pending_uses_presence_not_path_for_desktop_apps(tmp_path):
    apps_dir = tmp_path / "Applications"
    (apps_dir / "Orca.app").mkdir(parents=True)
    bin_dir = _stubs(tmp_path, os_name="Darwin", machine="arm64")
    got = _run(
        tmp_path,
        bin_dir,
        "ts_data_get_apps() { echo 'orca t3code'; }; ts_apps_pending",
        TS_APPLICATIONS_DIR=str(apps_dir),
    )
    pending = got.stdout.split()
    assert "orca" not in pending
    assert "t3code" in pending
