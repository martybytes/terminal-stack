"""The "never silence" contract of the TTS hooks, and the paths they run from.

Driven through the real cc-tts-lib.sh with a fake `jq`, against a temporary
config directory. No audio, no Windows.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.shell_support import BASH

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "dot_claude" / "hooks" / "cc-tts-lib.sh"
needs_bash = pytest.mark.skipif(BASH is None, reason="needs bash")


def _lib_env(tmp_path: Path, config: dict) -> dict[str, str]:
    cfg_dir = tmp_path / ".claude" / "tts"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return {
        "HOME": str(tmp_path),
        "PATH": os.environ.get("PATH", ""),
        "CC_TTS_CONFIG_DIR": str(cfg_dir),
        "CC_TTS_CONFIG_BASE": str(cfg_dir / "config.json"),
        "CC_TTS_CONFIG_LOCAL": str(cfg_dir / "local.json"),
        "CC_TTS_LEGACY": str(tmp_path / "nope.json"),
    }


def _json(tmp_path: Path, config: dict, key: str, default: str, *, jq: bool) -> str:
    env = _lib_env(tmp_path, config)
    if not jq:
        # A PATH with no jq on it: bash's own directory plus python3's, which the
        # fallback reader needs (on macOS they are not the same directory).
        py = shutil.which("python3") or ""
        dirs = {str(Path(BASH).parent), str(Path(py).parent) if py else ""}  # type: ignore[arg-type]
        env["PATH"] = os.pathsep.join(d for d in dirs if d)
    elif not any((Path(d) / "jq").exists() for d in env["PATH"].split(os.pathsep)):
        pytest.skip("jq is not installed")
    got = subprocess.run(
        [BASH, "-c", f'. "{LIB}"; cc_tts_json {key} "{default}"'],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        start_new_session=True,
    )
    return got.stdout.strip()


@needs_bash
@pytest.mark.parametrize("jq", [True, False], ids=["jq", "python"])
def test_a_missing_key_reads_as_its_default_in_both_readers(tmp_path, jq):
    """With jq installed the default was DEAD: `jq -r ".k // empty"` exits 0 on a
    missing key, so the `|| echo default` never ran and `.engine` read as ""."""
    cfg = {"enabled": True}
    assert _json(tmp_path, cfg, ".engine", "kokoro", jq=jq) == "kokoro"
    assert _json(tmp_path, cfg, ".daemon.port", "8890", jq=jq) == "8890"


@needs_bash
@pytest.mark.parametrize("jq", [True, False], ids=["jq", "python"])
def test_a_real_false_is_false_not_the_default(tmp_path, jq):
    cfg = {"enabled": False, "player": "ffplay"}
    assert _json(tmp_path, cfg, ".enabled", "true", jq=jq) == "false"
    assert _json(tmp_path, cfg, ".player", "auto", jq=jq) == "ffplay"


def test_the_merged_config_is_written_atomically():
    """Every hook rewrites .merged.json; two fire together. Open-and-truncate let
    one read a half-written file, `.enabled` read as false, and the announcement
    was dropped."""
    src = LIB.read_text(encoding="utf-8")
    assert "os.replace(tmp_p, out_p)" in src
    assert "json.dump(cfg, f, indent=2)\nos.replace" in src or "os.replace(tmp_p, out_p)" in src
    assert re.search(r'mv -f "\$merged\.\$\$" "\$merged"', src), "the cp fallback must rename too"


def test_the_windows_exe_is_asked_to_report_a_config_decline():
    lib = LIB.read_text(encoding="utf-8")
    assert "CC_TTS_REPORT_DISABLED=1" in lib and "WSLENV=" in lib
    exe = (ROOT / "bootstrap/tts-daemon/ttsd/hooks.py").read_text(encoding="utf-8")
    assert 'declined = 75 if os.environ.get("CC_TTS_REPORT_DISABLED") else 0' in exe
    assert exe.count("return declined") == 2, "disabled AND event-filtered both decline"


def test_a_missing_config_is_a_quiet_exit_not_a_failing_hook():
    notify = (ROOT / "dot_claude/hooks/executable_cc-tts-notify.sh").read_text(encoding="utf-8")
    assert 'echo "cc-tts-notify: missing config" >&2; exit 0; }' in notify


def test_hook_paths_use_the_profile_folder_quoted():
    """C:/Users/<USERNAME> is not always the profile folder (truncated
    Microsoft-account names, user.DOMAIN), and a space in it split the command."""
    tmpl = (ROOT / "windows/.claude/settings.json.tmpl").read_text(encoding="utf-8")
    assert "C:/Users/__WIN_USER__" not in tmpl
    rendered = tmpl.replace("__WIN_HOME__", "C:/Users/John Smith").replace(
        "__THEME_RESOLVED__", "dark"
    )
    rendered = re.sub(r"__CC_TTS_[A-Z_]+__", "", rendered)
    data = json.loads(rendered)
    assert (
        data["statusLine"]["command"] == 'bash "C:/Users/John Smith/.claude/statusline-command.sh"'
    )
    ps = (ROOT / "scripts/sync-windows.ps1").read_text(encoding="utf-8")
    assert "'__WIN_HOME__'" in ps and "$env:USERPROFILE" in ps
    assert "C:/Users/$WinUser/AppData" not in ps
    sh = (ROOT / "run_after_90-sync-windows.sh").read_text(encoding="utf-8")
    assert '"__WIN_HOME__": os.environ.get("WIN_HOME", "")' in sh
    assert "C:/Users/'\"$WIN_USER\"'/AppData" not in sh
    assert "echo %USERPROFILE%" in sh
