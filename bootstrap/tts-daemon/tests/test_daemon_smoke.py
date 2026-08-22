"""Start a real daemon and talk to it.

This exists because a startup-path crash slipped past 124 unit tests twice: nothing else in
the suite ever calls `main()`, so a `NameError` on a line that only the daemon branch reaches
was invisible until a live run. It is slower than the rest of the suite by design, and it is
the only test here that binds a socket.

No audio: the daemon is started with `--no-tray`, and none of these requests reach an
engine.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get(url: str, token: str = "", timeout: float = 4.0):
    request = urllib.request.Request(url)
    if token:
        request.add_header("X-TS-Token", token)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return response.status, body


def _post(url: str, payload: dict, token: str = "", timeout: float = 6.0):
    request = urllib.request.Request(
        url, method="POST", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    if token:
        request.add_header("X-TS-Token", token)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


@pytest.fixture(scope="module")
def daemon(tmp_path_factory):
    home = tmp_path_factory.mktemp("ttsd-smoke")
    (home / ".claude" / "tts").mkdir(parents=True)
    (home / ".claude" / "tts" / "config.json").write_text(json.dumps({
        "enabled": True,
        "summarize": {"mode": "haiku"},
        "daemon": {"enabled": True},
    }), encoding="utf-8")

    port = _free_port()
    env = dict(os.environ)
    env.update(HOME=str(home), USERPROFILE=str(home), LOCALAPPDATA=str(home),
               PYTHONPATH=str(ROOT))
    env.pop("ANTHROPIC_API_KEY", None)   # the no-key case is the interesting one
    proc = subprocess.Popen(
        [sys.executable, "-m", "ttsd", "daemon", "--no-tray", "--port", str(port)],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True)

    base = f"http://127.0.0.1:{port}"
    token = ""
    for _ in range(60):
        if proc.poll() is not None:
            pytest.fail("the daemon exited during startup:\n" + (proc.stdout.read() or ""))
        try:
            _get(base + "/healthz")
            token = (home / "terminal-stack" / "tts-daemon" / "state" / "token").read_text(
                encoding="utf-8").strip()
            break
        except (OSError, urllib.error.URLError):
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.fail("the daemon never answered /healthz")

    yield base, token, home
    _post(base + "/v1/shutdown", {})
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_it_starts_and_reports_health(daemon):
    base, _, _ = daemon
    status, body = _get(base + "/healthz")
    assert status == 200
    assert json.loads(body)["ok"] is True


def test_the_page_carries_a_real_token(daemon):
    base, token, _ = daemon
    status, body = _get(base + "/ui")
    assert status == 200
    assert "__TS_TOKEN__" not in body, "the placeholder must be substituted"
    assert token and token in body


def test_a_foreign_host_header_is_refused(daemon):
    base, _, _ = daemon
    request = urllib.request.Request(base + "/v1/status", headers={"Host": "evil.example"})
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=4)
    assert caught.value.code == 403


def test_schema_and_effective_agree_on_keys(daemon):
    base, _, _ = daemon
    _, schema_body = _get(base + "/v1/config/schema")
    _, eff_body = _get(base + "/v1/config/effective")
    keys = {f["key"] for f in json.loads(schema_body)["fields"]}
    values = json.loads(eff_body)["values"]
    assert keys == set(values), "the page renders from the schema and reads from effective"
    assert values["summarize.mode"]["effective"] == "haiku"
    assert values["summarize.mode"]["layer"] == "saved"


def test_a_write_without_the_token_is_refused(daemon):
    base, _, home = daemon
    code, _ = _post(base + "/v1/config/set", {"updates": {"music.mode": "off"}})
    assert code == 401
    assert not (home / ".claude" / "tts" / "local.json").exists(), "and nothing was written"


def test_a_valid_write_lands_in_local_json_and_takes_effect(daemon):
    base, token, home = daemon
    code, body = _post(base + "/v1/config/set",
                       {"updates": {"music.mode": "pause", "excitement": 0.6}}, token)
    assert code == 200 and body["written"] == 2 and body["errors"] == {}

    saved = json.loads((home / ".claude" / "tts" / "local.json").read_text(encoding="utf-8"))
    assert saved["music"]["mode"] == "pause"

    _, eff = _get(base + "/v1/config/effective")
    music = json.loads(eff)["values"]["music.mode"]
    assert music["effective"] == "pause"
    assert music["layer"] == "local", "the page must be able to say an override is winning"


def test_invalid_values_are_rejected_without_writing_the_good_ones_away(daemon):
    base, token, home = daemon
    code, body = _post(base + "/v1/config/set", {"updates": {
        "music.duckPercent": 900, "summarize.mode": "gpt", "maxChars": 140}}, token)
    assert code == 200
    assert set(body["errors"]) == {"music.duckPercent", "summarize.mode"}
    assert body["written"] == 1, "the one valid field still saved"

    _, eff = _get(base + "/v1/config/effective")
    values = json.loads(eff)["values"]
    assert values["maxChars"]["effective"] == 140
    assert values["summarize.mode"]["effective"] == "haiku", "the bad value never landed"


def test_the_mute_route_now_needs_the_token(daemon):
    """A cross-site form POST could silence this machine before the token was required."""
    base, token, _ = daemon
    code, _ = _post(base + "/v1/mute", {"enabled": True})
    assert code == 401
    code, body = _post(base + "/v1/mute", {"enabled": True}, token)
    assert code == 200 and body["muted"] is True
    _post(base + "/v1/mute", {"enabled": False}, token)


def test_the_summarizer_test_reports_a_missing_key_instead_of_looking_fine(daemon):
    """The whole point: haiku with no key is otherwise indistinguishable from template."""
    base, token, _ = daemon
    code, body = _post(base + "/v1/summarizer/test", {}, token)
    assert code == 200
    assert body["mode"] == "haiku"
    assert body["ran"] == "template", "it fell back"
    assert body["fell_back"] is True
    assert "no API key" in body["reason"]
    assert "not set" in body["key"]
    assert body["line"], "and it still produced something to say"
    assert "coalesced" in body["note"], "the structural caveat travels with the result"


def test_storing_a_key_changes_what_the_test_reports(daemon):
    base, token, _ = daemon
    code, body = _post(base + "/v1/secrets/set",
                       {"name": "anthropicApiKey", "value": "sk-ant-not-a-real-key-1234"},
                       token)
    assert code == 200 and body["secret"]["set"] is True
    assert body["secret"]["source"] == "store"

    code, body = _post(base + "/v1/summarizer/test", {}, token)
    assert "secret store" in body["key"], body["key"]
    # The key is fake, so it still falls back, but now for a different and stated reason.
    assert body["fell_back"] is True
    assert "request failed" in body["reason"], body["reason"]

    _post(base + "/v1/secrets/set", {"name": "anthropicApiKey", "value": ""}, token)


def test_an_unknown_secret_name_is_refused(daemon):
    base, token, _ = daemon
    code, _ = _post(base + "/v1/secrets/set", {"name": "sshKey", "value": "x"}, token)
    assert code == 400


def test_the_history_summary_route_answers(daemon):
    base, _, _ = daemon
    status, body = _get(base + "/v1/history/summary")
    assert status == 200
    assert set(json.loads(body)) == {"spoken", "deduped", "dupes", "daemon_silent_for"}
