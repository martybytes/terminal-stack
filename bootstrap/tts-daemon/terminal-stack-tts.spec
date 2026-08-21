# PyInstaller spec for the console-free terminal-stack TTS hook and daemon.

import subprocess
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH)
version_path = root / "build" / "ttsd-build-version.txt"
version_path.parent.mkdir(parents=True, exist_ok=True)
try:
    version = subprocess.run(
        ["git", "-C", str(root.parent.parent), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=10, check=True,
    ).stdout.strip()
except (OSError, subprocess.SubprocessError):
    version = "unknown"
version_path.write_text(version + "\n", encoding="utf-8")

datas = [(str(version_path), ".")]
binaries = []
hiddenimports = collect_submodules("winrt")

for package in ("comtypes", "edge_tts", "mutagen", "PIL", "psutil",
                "pycaw", "pystray", "winrt"):
    package_data, package_binaries, package_hidden = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    [str(root / "ttsd_entry.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="terminal-stack-tts",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
