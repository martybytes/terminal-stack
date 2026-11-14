"""The prompt's behaviour: transient (compact past prompts) and the blank line.

Three saved settings -- promptTransient (on), promptTransientStyle (bare) and
promptNewline (off) -- that reach five places: the zsh widget in dot_zshrc (via
the rendered prompt.zsh fragment), the pwsh starship hook in $PROFILE (via
config.json), starship.toml's add_newline on both sides (modify_starship.toml.tmpl
and the Windows `__PROMPT_NEWLINE__` token), and `tstack config prompt`. A key
that one layer forgets is a setting that saves and changes nothing, so the
wiring is pinned here as well as the behaviour.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.shell_support import BASH, bash_path  # noqa: E402
from tstack import platform as plat  # noqa: E402
from tstack import schema, store  # noqa: E402
from tstack.commands import config  # noqa: E402

KEYS = {"promptTransient": "on", "promptTransientStyle": "bare", "promptNewline": "off"}


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ------------------------------------------------------------------ the schema


def test_the_three_settings_and_their_defaults():
    for key, default in KEYS.items():
        assert schema.BY_KEY[key].default == default
    assert schema.BY_KEY["promptTransientStyle"].options == ("bare", "dir", "time", "dir-time")


@pytest.mark.parametrize("key", sorted(KEYS))
def test_every_layer_knows_every_key(key):
    default = KEYS[key]
    assert f'{key} = {{{{ index . "{key}" | default "{default}" | quote }}}}' in _read(
        ".chezmoi.toml.tmpl"
    )
    cfg_sh = _read("bootstrap/_config.sh")
    mirror_keys = cfg_sh[cfg_sh.index('TS_MIRROR_DATA_KEYS="') :]
    assert key in mirror_keys[: mirror_keys.index('\n"')]
    assert f'"{key}": "$(ts_prompt_setting_get {key})"' in cfg_sh
    # Save-TsConfig rebuilds config.json whole: a key it does not carry is deleted.
    cfg_ps = _read("bootstrap/_config.ps1")
    assert f"Name = '{key}'" in cfg_ps
    assert re.search(rf"^\s+{key}\s+= \$", cfg_ps, re.M)
    assert f"{key} = '{default}'" in cfg_ps


def test_the_windows_starship_template_and_both_syncs_carry_the_newline_token():
    assert "add_newline      = __PROMPT_NEWLINE__" in _read("windows/.config/starship.toml.tmpl")
    assert "'__PROMPT_NEWLINE__'" in _read("scripts/sync-windows.ps1")
    run_after = _read("run_after_90-sync-windows.sh")
    assert '"__PROMPT_NEWLINE__": os.environ.get("PROMPT_NEWLINE", "false")' in run_after
    assert 'PROMPT_NEWLINE="$PROMPT_NEWLINE"' in run_after


# --------------------------------------------------------- tstack config prompt


@pytest.fixture
def fake_store(monkeypatch):
    saved: dict[str, str] = {}
    monkeypatch.setattr(
        store, "get", lambda key, default=None: saved.get(key, KEYS.get(key, default or ""))
    )
    monkeypatch.setattr(store, "set", lambda key, value: saved.__setitem__(key, value))
    monkeypatch.setattr(config, "_apply", lambda out, dry: 0)
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    return saved


def _run(*argv: str) -> int:
    return config.main(["prompt", *argv])


def test_a_style_sets_the_style_and_turns_it_on(fake_store):
    fake_store["promptTransient"] = "off"
    assert _run("transient", "dir") == 0
    assert fake_store == {"promptTransient": "on", "promptTransientStyle": "dir"}


def test_transient_off_and_style_alias(fake_store):
    assert _run("transient", "off") == 0
    assert _run("transient", "style", "time") == 0
    assert fake_store == {"promptTransient": "on", "promptTransientStyle": "time"}


def test_newline_on(fake_store):
    assert _run("newline", "on") == 0
    assert fake_store == {"promptNewline": "on"}


def test_an_unchanged_value_saves_nothing(fake_store, capsys):
    assert _run("transient", "on") == 0
    assert fake_store == {}
    assert "already on" in capsys.readouterr().out


@pytest.mark.parametrize(
    "argv",
    [("transient", "loud"), ("transient", "style"), ("newline", "maybe")],
)
def test_a_bad_value_is_refused_and_saves_nothing(fake_store, argv):
    assert _run(*argv) == 2
    assert fake_store == {}


def test_status_lists_every_style_in_ascii(fake_store, capsys):
    assert _run("transient") == 0
    out = capsys.readouterr().out
    for name in ("bare", "dir", "time", "dir-time"):
        assert re.search(rf"^\s+[* ] {re.escape(name)}\s", out, re.M)
    assert out.isascii()


def test_windows_is_told_to_open_a_new_tab_not_exec_zsh(fake_store, monkeypatch, capsys):
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    assert _run("transient", "off") == 0
    out = capsys.readouterr().out
    assert "a NEW PowerShell tab" in out
    assert "exec zsh" not in out


# ---------------------------------------------------------- starship add_newline

CHEZMOI = shutil.which("chezmoi")


@pytest.mark.skipif(not CHEZMOI or not BASH or os.name == "nt", reason="needs chezmoi and bash")
@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, "add_newline = false"),
        ({"promptNewline": "on"}, "add_newline = true"),
    ],
)
def test_modify_starship_sets_add_newline_from_the_setting(tmp_path, data, expected):
    tmpl = _read("dot_config/modify_starship.toml.tmpl")
    rendered = subprocess.run(
        [
            CHEZMOI,
            "--source",
            str(ROOT),
            "--config",
            str(tmp_path / "none.toml"),
            "execute-template",
            "--override-data",
            json.dumps(data),
        ],
        input=tmpl,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
        start_new_session=True,
    ).stdout
    script = tmp_path / "modify.sh"
    script.write_text(rendered, encoding="utf-8")
    out = subprocess.run(
        [str(BASH), bash_path(script)],
        input="",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
        start_new_session=True,
    ).stdout
    lines = [ln for ln in out.splitlines() if ln.startswith("add_newline")]
    assert lines == [expected]


# ------------------------------------------------------------------- zsh widget

ZSH = shutil.which("zsh")
TMUX = shutil.which("tmux")


def _zsh_block() -> str:
    text = _read("dot_zshrc")
    start = text.index('[[ -r "$HOME/.config/terminal-stack/prompt.zsh" ]]')
    end = text.index("# ---- starship-stack-end ----", start)
    return text[start:end]


@pytest.mark.skipif(not ZSH, reason="zsh is unavailable")
@pytest.mark.parametrize(
    ("style", "pattern"),
    [
        ("bare", r"^❯ $"),
        ("dir", r"^here ❯ $"),
        ("time", r"^\d{1,2}:\d\d:\d\d [AP]M ❯ $"),
        ("dir-time", r"^here \d{1,2}:\d\d:\d\d [AP]M ❯ $"),
    ],
)
def test_each_style_expands_to_plain_text(tmp_path, style, pattern):
    here = tmp_path / "here"
    here.mkdir()
    script = (
        "_ts_agent_shell() { return 0 }\n"
        + _zsh_block()
        + f"\nTS_PROMPT_TRANSIENT_STYLE={style}; _ts_transient_prompt; print -rn -- ${{(%)REPLY}}"
    )
    got = subprocess.run(
        [ZSH, "-f", "-c", script],
        cwd=here,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "HOME": str(tmp_path), "TERM": "dumb"},
        timeout=30,
        check=True,
        start_new_session=True,
    ).stdout
    assert re.match(pattern, re.sub(r"\x1b\[[0-9;]*m", "", got)), repr(got)


@pytest.mark.skipif(not (ZSH and TMUX) or os.name == "nt", reason="needs zsh and tmux")
def test_a_finished_prompt_collapses_in_a_real_terminal(tmp_path):
    """Drive a real zsh in a detached tmux: the full prompt (with its blank
    line) must collapse to the arrow plus the command once Enter is pressed,
    Ctrl+C included."""
    rc = tmp_path / ".zshrc"
    rc.write_text(
        "_ts_agent_shell() { return 1 }\nPROMPT=$'\\nFULL-LINE-ONE\\nFULL> '\n" + _zsh_block(),
        encoding="utf-8",
    )
    sock = f"tstest{os.getpid()}"
    env = {**os.environ, "HOME": str(tmp_path), "ZDOTDIR": str(tmp_path), "TERM": "xterm-256color"}
    env.pop("TMUX", None)

    def tmux(*args: str) -> str:
        return subprocess.run(
            [TMUX, "-L", sock, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=30,
            check=False,
            start_new_session=True,
        ).stdout

    def screen_until(needle: str) -> str:
        deadline = time.monotonic() + 15
        text = ""
        while time.monotonic() < deadline:
            text = tmux("capture-pane", "-p")
            if needle in text:
                return text
            time.sleep(0.2)
        return text

    try:
        tmux("-f", "/dev/null", "new-session", "-d", "-x", "80", "-y", "24", f"{ZSH} -i")
        screen_until("FULL> ")
        tmux("send-keys", "echo one-done", "Enter")
        screen_until("one-done\n")
        tmux("send-keys", "echo abandoned")
        time.sleep(0.5)
        tmux("send-keys", "C-c")
        tmux("send-keys", "echo two-done", "Enter")
        text = screen_until("\ntwo-done")
    finally:
        tmux("kill-server")
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    assert "❯ echo one-done" in lines, text
    assert "❯ echo abandoned" in lines, text
    assert "❯ echo two-done" in lines, text
    # Only the live prompt is the full one; every finished one collapsed.
    assert sum(ln.startswith("FULL>") for ln in lines) == 1, text
    assert lines.count("FULL-LINE-ONE") == 1, text


# ------------------------------------------------------------------ pwsh hook

PWSH = shutil.which("pwsh")


def _pwsh_block() -> str:
    text = _read("windows/Documents/PowerShell/Microsoft.PowerShell_profile.ps1")
    start = text.index("    $tsPromptCfg = $null")
    end_marker = "        Enable-TransientPrompt\n    }\n"
    end = text.index(end_marker, start) + len(end_marker)
    return text[start:end]


@pytest.mark.skipif(not PWSH, reason="PowerShell 7 is unavailable")
@pytest.mark.parametrize(
    ("saved", "env_style", "expected"),
    [
        ({}, "", "enabled|❯ "),
        ({"promptTransientStyle": "dir"}, "", "enabled|here ❯ "),
        ({"promptTransient": "off"}, "", "not-enabled|"),
        ({"promptTransientStyle": "dir"}, "bare", "enabled|❯ "),
    ],
)
def test_the_pwsh_hook_follows_config_json(tmp_path, saved, env_style, expected):
    lad = tmp_path / "lad" / "terminal-stack"
    lad.mkdir(parents=True)
    (lad / "config.json").write_text(json.dumps(saved), encoding="utf-8")
    here = tmp_path / "here"
    here.mkdir()
    command = (
        "$global:TsEnabled = 'not-enabled'\n"
        "function Enable-TransientPrompt { $global:TsEnabled = 'enabled' }\n"
        + _pwsh_block()
        + f"\nSet-Location -LiteralPath '{here}'\n"
        "$t = if (Test-Path function:Invoke-Starship-TransientFunction) { Invoke-Starship-TransientFunction } else { '' }\n"
        '[Console]::Out.Write("$($global:TsEnabled)|" + ($t -replace "`e\\[[0-9;]*m", \'\'))\n'
    )
    env = {**os.environ, "LOCALAPPDATA": str(tmp_path / "lad"), "TS_PROMPT_TRANSIENT": ""}
    env["TS_PROMPT_TRANSIENT_STYLE"] = env_style
    got = subprocess.run(
        [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
        check=False,
        start_new_session=True,
    )
    assert got.stdout == expected, got
