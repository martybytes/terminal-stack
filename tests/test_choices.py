"""Live options: what a setting may be set to on THIS machine, right now.

The settings schema knows a type and a fixed option list. It cannot know the 68
voices a running kokoro serves or the presets the installed starship ships, and
hardcoding either is how a list goes stale with nobody noticing. So a `Setting`
names a provider and `tstack/choices.py` is where one is asked.

Nothing here touches the network or a real binary: every probe is stubbed. What
is under test is the SHAPE of each answer and, more importantly, what happens
when a probe finds nothing -- which is the normal state of a machine whose kokoro
is stopped or whose starship is not installed yet.
"""

from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import choices, schema, store  # noqa: E402


class Fake:
    def __init__(self, out: str = "", code: int = 0) -> None:
        self.stdout = out
        self.stderr = ""
        self.returncode = code


def test_every_declared_provider_exists():
    """A `Setting` naming a provider nothing implements would offer an empty
    picker forever, and look exactly like a service being down."""
    declared = {s.choices for s in schema.SETTINGS if s.choices}
    assert declared, "at least one setting should declare live options"
    known = {choices.STARSHIP, choices.KOKORO_VOICES, choices.SAY_VOICES}
    assert declared <= known, f"unimplemented provider(s): {sorted(declared - known)}"


def test_the_settings_that_need_live_options_declare_one():
    """These three are `kind="text"` precisely because their valid values are not
    a fixed list -- which is what made them blind text boxes in the dashboard."""
    for key, provider in (
        ("starshipPreset", choices.STARSHIP),
        ("ccTtsKokoroVoice", choices.KOKORO_VOICES),
        ("ccTtsSayVoice", choices.SAY_VOICES),
    ):
        assert schema.BY_KEY[key].choices == provider, key


def test_a_provider_that_finds_nothing_returns_an_empty_list_not_an_error(monkeypatch):
    """The normal state of a machine whose kokoro is stopped, or whose starship
    the bootstrap has not installed yet. A caller falls back to a text box."""
    monkeypatch.setattr(choices.shutil, "which", lambda _n: None)

    def refuse(*a, **k):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(choices.urllib.request, "urlopen", refuse)
    assert choices.options(choices.STARSHIP) == [
        choices.Choice(
            choices.STACK_PROMPT, choices.STACK_PROMPT, "this stack's own two-line prompt"
        )
    ], "the stack's own prompt is always offerable; it needs no starship to name"
    assert choices.options(choices.KOKORO_VOICES) == []
    assert choices.options(choices.SAY_VOICES) == []
    assert choices.preview(choices.STARSHIP, "tokyo-night") is None
    assert choices.options("no-such-provider") == []


def test_the_preset_list_drops_the_trailing_blank_line(monkeypatch):
    """`starship preset --list` ends with one, and passing it through puts an
    empty entry in every menu."""
    monkeypatch.setattr(choices.shutil, "which", lambda _n: "/usr/bin/starship")
    monkeypatch.setattr(choices, "_run", lambda *a, **k: Fake("tokyo-night\njetpack\n\n"))
    assert choices.starship_presets() == ["tokyo-night", "jetpack"]
    values = [c.value for c in choices.options(choices.STARSHIP)]
    assert values == [choices.STACK_PROMPT, "tokyo-night", "jetpack"]


def test_voices_are_read_from_either_server_shape(monkeypatch):
    """The docker image answers `{"voices":[...]}` and mlx-audio
    `{"object":"list","data":[...]}`. Matching the id pattern rather than a key
    means one reader covers both, and a third shape would too."""
    for body in (
        b'{"voices":[{"id":"af_heart","name":"af_heart"},{"id":"am_adam"}]}',
        b'{"object":"list","data":[{"id":"am_adam"},{"id":"af_heart"}]}',
    ):

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self, _b=body):
                return _b

        monkeypatch.setattr(choices.urllib.request, "urlopen", lambda *a, **k: Response())
        assert choices.kokoro_voices() == ["af_heart", "am_adam"]


def test_the_voices_query_names_a_model_only_when_one_is_configured(monkeypatch):
    """mlx-audio 400s without `?model=`; the docker image has no such parameter,
    and the default request must stay the one that is known to work."""
    seen: list[str] = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"{}"

    def capture(url, timeout=0):
        seen.append(url)
        return Response()

    monkeypatch.setattr(choices.urllib.request, "urlopen", capture)
    monkeypatch.setattr(
        store, "get", lambda k, d=None: {"ccTtsKokoroModel": "kokoro"}.get(k, d or "")
    )
    choices.kokoro_voices()
    assert "?model=" not in seen[-1]

    monkeypatch.setattr(
        store,
        "get",
        lambda k, d=None: "mlx-community/Kokoro-82M-bf16" if k == "ccTtsKokoroModel" else (d or ""),
    )
    choices.kokoro_voices()
    assert seen[-1].endswith("?model=mlx-community/Kokoro-82M-bf16")


def test_say_voices_keep_the_language_and_put_english_first(monkeypatch):
    """The name alone does not tell you Daniel is en_GB, and a list that opens on
    Turkish is a list nobody scrolls."""
    listing = (
        "Albert              en_US    # sample\n"
        "Amelie              fr_CA    # bonjour\n"
        "Daniel              en_GB    # hello\n"
        "Bad line\n"
    )
    monkeypatch.setattr(choices.shutil, "which", lambda _n: "/usr/bin/say")
    monkeypatch.setattr(choices, "_run", lambda *a, **k: Fake(listing))
    got = choices.say_voices()
    assert [c.value for c in got] == ["Albert", "Daniel", "Amelie"]
    assert got[0].note == "en_US"

    # ...and the picker offers "no voice at all", which is a real configuration:
    # an unset ccTtsSayVoice MEANS the system voice.
    offered = choices.options(choices.SAY_VOICES)
    assert offered[0].value == "" and "system voice" in offered[0].label


def test_the_kokoro_naming_scheme_is_explained_rather_than_assumed():
    """`af_heart` tells you nothing until someone says the first letter is the
    language and the second the gender."""
    assert choices._voice_hint("af_heart") == "American female"
    assert choices._voice_hint("bm_george") == "British male"
    # `z` IS a language (Mandarin); the second letter not being f/m just means
    # the gender is unknown, and half an answer beats none.
    assert choices._voice_hint("zz") == "Mandarin"
    assert choices._voice_hint("qq") == ""
    assert choices._voice_hint("x") == ""


def test_only_the_providers_that_can_be_heard_or_seen_say_so():
    """Advertising `s hear it` on a prompt preset is a small lie, and the menu
    reads it straight off these."""
    assert choices.can_sample(choices.KOKORO_VOICES)
    assert choices.can_sample(choices.SAY_VOICES)
    assert not choices.can_sample(choices.STARSHIP)
    assert choices.can_preview(choices.STARSHIP)
    assert not choices.can_preview(choices.SAY_VOICES)
    assert choices.sample(choices.STARSHIP, "tokyo-night") == (
        False,
        "nothing to hear for this setting",
    )


def test_a_sample_never_raises_out_of_a_keypress(monkeypatch):
    """This is reached from a keystroke in a dashboard. A traceback out of a
    Textual event handler leaves a corrupted terminal, so every failure has to
    come back as (False, why)."""
    monkeypatch.setattr(choices.shutil, "which", lambda _n: None)
    played, message = choices.sample(choices.SAY_VOICES, "Albert")
    assert not played and "not available" in message

    def refuse(*a, **k):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(choices.urllib.request, "urlopen", refuse)
    played, message = choices.sample(choices.KOKORO_VOICES, "af_heart")
    assert not played and "is the kokoro container up" in message


def test_synthesised_but_unplayable_is_not_reported_as_played(monkeypatch, tmp_path):
    """Finding no audio player is a different answer from playing it, and
    conflating them is how "why did nothing happen" becomes unanswerable."""
    audio = b"ID3fake"

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return audio

    monkeypatch.setattr(choices.urllib.request, "urlopen", lambda *a, **k: Response())
    monkeypatch.setattr(choices.shutil, "which", lambda _n: None)
    played, message = choices.sample(choices.KOKORO_VOICES, "af_heart")
    assert not played
    assert "no audio player" in message


def test_the_preview_uses_the_plain_ansi_path(monkeypatch):
    """With STARSHIP_SHELL set, starship emits that shell's escaping, which a
    preview prints as literal punctuation instead of colour. Empty -- not unset
    -- selects the plain-ANSI path."""
    seen: dict = {}

    def fake_run(argv, **kwargs):
        seen.update(kwargs.get("env") or {})
        return Fake("PROMPT>")

    monkeypatch.setattr(choices.shutil, "which", lambda _n: "/usr/bin/starship")
    monkeypatch.setattr(choices, "_run", lambda *a, **k: Fake('format = "x"'))
    monkeypatch.setattr(choices.subprocess, "run", fake_run)
    assert choices.starship_preview("tokyo-night") == "PROMPT>"
    assert seen.get("STARSHIP_SHELL") == "", "empty, not absent"
    assert "STARSHIP_CONFIG" in seen


def test_the_stack_prompt_previews_the_deployed_file(monkeypatch, tmp_path):
    """There is no `starship preset terminal-stack`; ours is the file chezmoi
    deployed. Absent (before the first apply) is None, not a crash."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(choices.shutil, "which", lambda _n: "/usr/bin/starship")
    assert choices.starship_preview(choices.STACK_PROMPT) is None

    config = tmp_path / ".config"
    config.mkdir()
    (config / "starship.toml").write_text('format = "x"', encoding="utf-8")
    monkeypatch.setattr(choices.subprocess, "run", lambda *a, **k: Fake("OURS>"))
    assert choices.starship_preview(choices.STACK_PROMPT) == "OURS>"


def test_preset_configs_are_written_by_redirect_not_by_the_o_flag():
    """`starship preset -o <file>` refuses to overwrite an existing file, and
    the temp file has already been created. The command fails, the file stays
    empty, and the preview silently renders nothing."""
    body = (ROOT / "tstack/choices.py").read_text(encoding="utf-8")
    assert '"-o"' not in body and "'-o'" not in body
    assert '_run([exe, "preset", name])' in body
