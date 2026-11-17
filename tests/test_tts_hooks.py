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
    # The Windows python3 is an app-execution alias for the Python install manager. With no
    # LOCALAPPDATA it cannot find its Python, so it installs a fresh one into the cwd and
    # registers it under HKCU, and the reader returns the installer's output, not the value.
    passthrough = {k: os.environ[k] for k in ("LOCALAPPDATA", "USERPROFILE", "SYSTEMROOT")
                   if k in os.environ}
    return {
        **passthrough,
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
    assert exe.count("return declined") == 3, (
        "disabled, an SDK-driven session, and event-filtered all decline")


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


def _lib(tmp_path: Path, config: dict, script: str, **extra: str) -> subprocess.CompletedProcess:
    env = {**_lib_env(tmp_path, config), **extra}
    return subprocess.run(
        [BASH, "-c", f'. "{LIB}"; {script}'],  # type: ignore[list-item]
        env=env, cwd=tmp_path, capture_output=True, text=True, encoding="utf-8",
        timeout=60, check=False, start_new_session=True,
    )


@needs_bash
@pytest.mark.parametrize("entrypoint,speak_sdk,source,silenced", [
    ("sdk-ts", None, "claude", True),
    ("sdk-py", False, "claude", True),
    ("sdk-ts", True, "claude", False),
    ("cli", None, "claude", False),
    ("", None, "claude", False),
    ("sdk-ts", None, "cursor", False),
])
def test_sdk_driven_claude_sessions_are_silenced(tmp_path, entrypoint, speak_sdk, source,
                                                 silenced):
    """Obsidian's Claudian runs claude through the SDK with the user's hooks, and opened a
    new session -- a new ordinal and voice -- per chat. Twin of is_sdk_session."""
    cfg: dict = {"enabled": True}
    if speak_sdk is not None:
        cfg["sources"] = {"claude": {"speakSdk": speak_sdk}}
    got = _lib(tmp_path, cfg, f'cc_tts_sdk_silenced {source}',
               CLAUDE_CODE_ENTRYPOINT=entrypoint)
    assert (got.returncode == 0) is silenced, got.stderr


def test_every_claude_hook_script_checks_the_sdk_gate_before_handing_off():
    """The exe cannot see CLAUDE_CODE_ENTRYPOINT from WSL and a daemon POST carries no
    environment, so the scripts must decide before either."""
    hooks = ROOT / "dot_claude" / "hooks"
    for name in ("executable_cc-speak.sh", "executable_cc-speak-input.sh"):
        src = (hooks / name).read_text(encoding="utf-8")
        gate = src.index('cc_tts_sdk_silenced "$source" && exit 0')
        assert gate < src.index("cc_tts_windows_hook "), name


@needs_bash
def test_the_idle_reminder_leaves_no_state(tmp_path):
    """Stop already said the turn finished; idle_prompt repeated it as a question."""
    idle = json.dumps({"notification_type": "idle_prompt",
                       "message": "Claude is waiting for your input"})
    perm = json.dumps({"notification_type": "permission_prompt",
                       "message": "Claude needs your permission"})
    show = 'cc_tts_parse_input_state "$IN" notification; printf "[%s]" "$CC_TTS_PARSED_STATE"'
    assert _lib(tmp_path, {}, show, IN=idle).stdout == "[]"
    assert _lib(tmp_path, {}, show, IN=perm).stdout == "[question]"


def _transcript(tmp_path: Path, *kinds: str) -> str:
    """A transcript whose user entries were opened by each kind, in order."""
    rows = []
    for kind in kinds:
        content = "<task-notification>\n<task-id>b1</task-id>" if kind == "task" else "hi"
        rows.append({"type": "user", "message": {"content": content},
                     "origin": {"kind": "task-notification" if kind == "task" else "human"}})
        rows.append({"type": "assistant", "message": {"content": []}})
    path = tmp_path / "session.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path.as_posix()


@needs_bash
@pytest.mark.parametrize("kinds,speak_background,source,silenced", [
    (("human", "task"), None, "claude", True),
    (("task", "human"), None, "claude", False),
    (("human", "task"), True, "claude", False),
    (("human", "task"), None, "cursor", False),
])
def test_turns_a_background_task_started_are_silenced(tmp_path, kinds, speak_background,
                                                      source, silenced):
    """A finished background task opens a turn whose Stop sounded like an answer to you.
    Twin of turn_started_by_background in ttsd/hooks.py."""
    cfg: dict = {"enabled": True}
    if speak_background is not None:
        cfg["sources"] = {"claude": {"speakBackground": speak_background}}
    hook = json.dumps({"transcript_path": _transcript(tmp_path, *kinds)})
    got = _lib(tmp_path, cfg, f'cc_tts_background_silenced {source} "$IN"', IN=hook)
    assert (got.returncode == 0) is silenced, got.stderr


@needs_bash
def test_background_detection_fails_open(tmp_path):
    for hook in ("{}", json.dumps({"transcript_path": (tmp_path / "gone").as_posix()}), "x"):
        got = _lib(tmp_path, {"enabled": True}, 'cc_tts_background_silenced claude "$IN"',
                   IN=hook)
        assert got.returncode != 0, hook


def test_the_stop_hook_checks_the_background_gate_before_handing_off():
    """From WSL the exe cannot read a /home transcript, so the script decides first."""
    src = (ROOT / "dot_claude" / "hooks" / "executable_cc-speak.sh").read_text(
        encoding="utf-8")
    gate = src.index('cc_tts_background_silenced "$source" "$input" && exit 0')
    assert gate < src.index("cc_tts_windows_hook ")


@needs_bash
def test_a_speak_marker_is_spoken_whole_and_other_text_ends_on_a_word(tmp_path):
    """maxChars clipped the marker mid-word; the lead-in took a third of the budget."""
    sentence = ("Two read-only investigations are running: one traces the code path, "
                "the other gathers runtime evidence.")
    cfg = {"enabled": True, "maxChars": 60, "summarize": {"mode": "self"},
           "announce": {"includeProject": True}}
    hook = json.dumps({"last_assistant_message": f"Body.\n<!-- speak: {sentence} -->"})
    got = _lib(tmp_path, cfg, 'cc_tts_build_speech claude waiting terminal-stack',
               CC_TTS_HOOK_JSON=hook)
    assert got.stdout.endswith(sentence), got.stdout + got.stderr

    long_text = "Rebuilt the parser and every caller now passes its own tests cleanly."
    got = _lib(tmp_path, {"enabled": True, "maxChars": 40,
                          "announce": {"templates": {"waiting": long_text}}},
               "cc_tts_build_speech claude waiting terminal-stack")
    assert got.stdout.endswith("…"), got.stdout
    assert len(got.stdout) <= 40
    words = got.stdout.rstrip("…").split()[1:]  # drop the "claude." prefix
    assert words == long_text.split()[: len(words)]


_PWSH = shutil.which("pwsh") or shutil.which("pwsh.exe")

_SPLAT_CHECK = r"""
$ast = [System.Management.Automation.Language.Parser]::ParseFile($env:TS_SYNC, [ref]$null, [ref]$null)
$fn = $ast.Find({ $args[0] -is [System.Management.Automation.Language.FunctionDefinitionAst] `
    -and $args[0].Name -eq 'Get-TsTtsInstallArgs' }, $true)
. ([scriptblock]::Create($fn.Extent.Text))
$inst = Join-Path $env:TS_TMP 'inst.ps1'
Set-Content -LiteralPath $inst -Value @(
    '[CmdletBinding()]',
    'param([switch]$Uninstall, [switch]$Purge, [switch]$NoStart, [switch]$NoAutostart)',
    '"$NoStart/$NoAutostart"')
foreach ($on in $true, $false) { $a = Get-TsTtsInstallArgs $on; & $inst @a }
"""


@pytest.mark.skipif(_PWSH is None, reason="needs pwsh")
def test_the_sync_passes_the_tts_installer_arguments_it_binds(tmp_path):
    """An `if` yielding @() assigned $null and splatting it failed with "cannot be found
    that accepts argument '$null'"; '-NoStart' strings in an array bound no switch."""
    got = subprocess.run(
        [_PWSH, "-NoProfile", "-NonInteractive", "-Command", _SPLAT_CHECK],  # type: ignore[list-item]
        env={**os.environ, "TS_SYNC": str(ROOT / "scripts" / "sync-windows.ps1"),
             "TS_TMP": str(tmp_path)},
        capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)
    assert got.stdout.split() == ["False/False", "True/True"], got.stdout + got.stderr
    sync = (ROOT / "scripts" / "sync-windows.ps1").read_text(encoding="utf-8")
    assert "@('-NoStart', '-NoAutostart')" not in sync
