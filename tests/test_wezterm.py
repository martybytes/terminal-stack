"""`tstack wezterm`, with no WezTerm and no network.

Everything here fails open by design, so most of these assert what happens when a
thing is missing: no binary, no package manager, no GitHub, no changelog. The
"happy path" of a status report is the easy half.
"""

from __future__ import annotations

import pytest

from tstack import platform as plat
from tstack.commands import wezterm


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(wezterm, "_gh_api", lambda path: None)
    monkeypatch.setattr(wezterm, "changelog_fetch", lambda: None)


def test_help_is_ascii_only_and_names_every_verb():
    assert wezterm.HELP.isascii()
    for verb in ("status", "changes", "install", "upgrade"):
        assert f"tstack wezterm {verb}" in wezterm.HELP or f"[{verb}]" in wezterm.HELP


def test_an_unknown_verb_exits_two(capsys):
    assert wezterm.main(["nonsense"]) == 2
    assert "unknown command" in capsys.readouterr().err


def test_a_hand_built_wezterm_is_named_not_hidden(monkeypatch):
    class Got:
        returncode = 0
        stdout = "wezterm 20260101-local-build\n"

    monkeypatch.setattr(wezterm.shutil, "which", lambda name: "/usr/local/bin/wezterm")
    monkeypatch.setattr(wezterm, "_run", lambda argv, timeout=30: Got())
    assert wezterm.installed() == ("20260101-local-build", "", "")


def test_a_missing_wezterm_is_none(monkeypatch):
    monkeypatch.setattr(wezterm.shutil, "which", lambda name: None)
    assert wezterm.installed() is None
    assert wezterm.channel() == "none"


def test_a_binary_no_package_manager_owns_is_left_alone(monkeypatch, capsys):
    """A hand-placed binary is not ours to replace, and saying "unknown" is what
    stops install and upgrade touching it."""
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    monkeypatch.setattr(
        wezterm.shutil,
        "which",
        lambda name: "/usr/local/bin/wezterm" if name == "wezterm" else None,
    )
    assert wezterm.channel() == "unknown"
    assert wezterm.upgrade() == 0
    assert "upgrade it the way you installed it" in capsys.readouterr().out


def test_the_channel_comes_from_the_package_manager_not_a_saved_value(monkeypatch):
    """A stored channel can drift out of sync with what is actually installed;
    dpkg cannot."""
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    monkeypatch.setattr(wezterm.shutil, "which", lambda name: f"/usr/bin/{name}")

    def only(package):
        class Got:
            returncode = 0 if package in package_wanted else 1

        return Got()

    package_wanted = {"wezterm-nightly"}
    monkeypatch.setattr(wezterm, "_run", lambda argv, timeout=30: only(argv[-1]))
    assert wezterm.channel() == "nightly"
    package_wanted = {"wezterm"}
    assert wezterm.channel() == "stable"


def test_the_wizard_selection_maps_onto_a_channel():
    assert wezterm.terminals_channel("wezterm-nightly ghostty") == "nightly"
    assert wezterm.terminals_channel("wezterm-stable") == "stable"
    assert wezterm.terminals_channel("ghostty") == ""
    assert wezterm.terminals_channel("") == ""


def test_status_without_wezterm_still_reports_the_upstream_side(monkeypatch, offline, capsys):
    monkeypatch.setattr(wezterm, "installed", lambda: None)
    monkeypatch.setattr(wezterm, "channel", lambda: "none")
    assert wezterm.status() == 0
    out = capsys.readouterr().out
    assert "not installed" in out
    assert "offline" in out


def test_status_says_when_you_are_already_on_the_latest_stable(monkeypatch, capsys):
    monkeypatch.setattr(
        wezterm, "installed", lambda: ("20240203-110809-5046fc22", "20240203", "5046fc22")
    )
    monkeypatch.setattr(wezterm, "channel", lambda: "stable")
    monkeypatch.setattr(
        wezterm, "latest_stable", lambda: ("20240203-110809-5046fc22", "2024-02-03")
    )
    monkeypatch.setattr(wezterm, "latest_nightly", lambda: None)
    monkeypatch.setattr(wezterm, "changes_tally", lambda version: "")
    monkeypatch.setattr(wezterm, "commits_since", lambda commit: None)
    wezterm.status()
    assert "you are on it" in capsys.readouterr().out


def test_the_nightly_asset_is_chosen_per_platform(monkeypatch):
    """The Debian10 nightly last built over a year ago while Debian12's built
    today, so the asset for THIS platform is the only honest date."""
    monkeypatch.setattr(plat, "kind", lambda: plat.MACOS)
    assert wezterm.nightly_asset_pattern().match("WezTerm-macos-nightly.zip")
    monkeypatch.setattr(plat, "kind", lambda: plat.WINDOWS)
    assert wezterm.nightly_asset_pattern().match("WezTerm-nightly-setup.exe")


def test_the_nightly_date_is_the_assets_and_not_the_releases(monkeypatch):
    """The nightly tag is rolling, so the release object's own published_at is
    stuck in 2019."""
    monkeypatch.setattr(plat, "kind", lambda: plat.MACOS)
    monkeypatch.setattr(
        wezterm,
        "_gh_api",
        lambda path: {
            "published_at": "2019-01-01T00:00:00Z",
            "assets": [
                {"name": "WezTerm-macos-nightly.zip", "updated_at": "2026-08-25T04:00:00Z"},
                {"name": "wezterm-nightly.Debian12.deb", "updated_at": "2026-08-26T04:00:00Z"},
            ],
        },
    )
    assert wezterm.latest_nightly() == "2026-08-25"


def test_an_unknown_platform_asset_falls_back_to_the_freshest(monkeypatch):
    monkeypatch.setattr(plat, "kind", lambda: plat.MACOS)
    monkeypatch.setattr(
        wezterm,
        "_gh_api",
        lambda path: {"assets": [{"name": "something-else", "updated_at": "2026-08-24T00:00:00Z"}]},
    )
    assert wezterm.latest_nightly() == "2026-08-24"


def test_latest_stable_needs_a_tag(monkeypatch):
    monkeypatch.setattr(wezterm, "_gh_api", lambda path: {"published_at": "2024-02-03T00:00:00Z"})
    assert wezterm.latest_stable() is None
    monkeypatch.setattr(wezterm, "_gh_api", lambda path: None)
    assert wezterm.latest_stable() is None


def test_update_available_is_silent_unless_something_is_newer(monkeypatch):
    """`tstack update` gates its offer on this, so silence is the common case."""
    monkeypatch.setattr(
        wezterm, "installed", lambda: ("20260101-000000-abcdef", "20260101", "abcdef")
    )
    monkeypatch.setattr(wezterm, "channel", lambda: "nightly")

    monkeypatch.setattr(wezterm, "latest_nightly", lambda: "2026-01-01")
    assert wezterm.update_available() == "", "the same day is not newer"

    monkeypatch.setattr(wezterm, "latest_nightly", lambda: "2026-08-26")
    assert "built 2026-08-26" in wezterm.update_available()

    monkeypatch.setattr(wezterm, "channel", lambda: "unknown")
    assert wezterm.update_available() == "", "a hand-placed binary is never offered an upgrade"

    monkeypatch.setattr(wezterm, "installed", lambda: None)
    assert wezterm.update_available() == ""


def test_update_available_compares_tags_on_stable(monkeypatch):
    monkeypatch.setattr(wezterm, "installed", lambda: ("20230101-000000-aaa", "20230101", "aaa"))
    monkeypatch.setattr(wezterm, "channel", lambda: "stable")
    monkeypatch.setattr(
        wezterm, "latest_stable", lambda: ("20240203-110809-5046fc22", "2024-02-03")
    )
    assert "is newer than your 20230101-000000-aaa" in wezterm.update_available()
    monkeypatch.setattr(wezterm, "latest_stable", lambda: ("20230101-000000-aaa", "2023-01-01"))
    assert wezterm.update_available() == ""


def test_the_changelog_cache_is_reused_within_the_hour(monkeypatch, tmp_path):
    """A stale copy beats no copy: this is a ~225 KB fetch inside a status
    command."""
    monkeypatch.setattr(wezterm, "state_dir", lambda: tmp_path)
    cached = tmp_path / "wezterm-changelog.md"
    cached.write_text("## Changes\n\n### 1\n", encoding="utf-8")
    fetched = []
    monkeypatch.setattr(
        wezterm.urllib.request, "urlopen", lambda *a, **k: fetched.append(1) or None
    )
    assert wezterm.changelog_fetch() == cached
    assert fetched == []


def test_a_failed_fetch_with_no_cache_is_none_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(wezterm, "state_dir", lambda: tmp_path)

    def refuse(*a, **k):
        raise OSError("no network")

    monkeypatch.setattr(wezterm.urllib.request, "urlopen", refuse)
    assert wezterm.changelog_fetch() is None
    assert wezterm.changes_text("20240203-110809-5046fc22") is None
    assert wezterm.changes_tally("20240203-110809-5046fc22") == ""


def test_changes_reports_an_up_to_date_build_rather_than_an_empty_pager(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        wezterm, "installed", lambda: ("20240203-110809-5046fc22", "20240203", "5046fc22")
    )
    monkeypatch.setattr(wezterm, "changes_text", lambda version: "")
    assert wezterm.main(["changes"]) == 0
    assert "Nothing newer" in capsys.readouterr().out


def test_changes_without_wezterm_says_what_is_missing(monkeypatch, capsys):
    monkeypatch.setattr(wezterm, "installed", lambda: None)
    assert wezterm.main(["changes"]) == 1
    assert "no build to compare against" in capsys.readouterr().err


def test_install_rejects_anything_that_is_not_a_channel(capsys):
    assert wezterm.install("banana") == 2
    assert "stable|nightly" in capsys.readouterr().err


def test_install_with_no_package_manager_points_at_the_docs(monkeypatch, capsys):
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    monkeypatch.setattr(wezterm, "channel", lambda: "none")
    monkeypatch.setattr(wezterm.shutil, "which", lambda name: None)
    assert wezterm.install("nightly") == 0
    assert "wezterm.org/install" in capsys.readouterr().out


def test_the_machine_readable_verbs_are_silent_when_there_is_no_answer(monkeypatch, capsys):
    """_wezterm.sh's shims and `tstack update` all treat empty as "nothing to
    say", and none of them may fail a shell."""
    monkeypatch.setattr(wezterm, "installed", lambda: None)
    monkeypatch.setattr(wezterm, "update_available", lambda: "")
    assert wezterm.main(["installed"]) == 1
    assert wezterm.main(["update-available"]) == 1
    assert capsys.readouterr().out == ""

    monkeypatch.setattr(wezterm, "channel", lambda: "none")
    assert wezterm.main(["channel"]) == 0
    assert capsys.readouterr().out.strip() == "none"

    assert wezterm.main(["terminals-channel", "wezterm-stable"]) == 0
    assert capsys.readouterr().out.strip() == "stable"


def test_the_intro_block_degrades_to_nothing(monkeypatch):
    monkeypatch.setattr(wezterm, "installed", lambda: None)
    monkeypatch.setattr(wezterm, "channel", lambda: "none")
    monkeypatch.setattr(wezterm, "latest_stable", lambda: None)
    monkeypatch.setattr(wezterm, "latest_nightly", lambda: None)
    assert wezterm.prompt_intro() == ""


# ------------------------------------------------------------------ the network


def test_gh_is_preferred_over_bare_curl_when_it_is_authenticated(monkeypatch):
    """gh is 5000 requests an hour; an unauthenticated API call is 60 per IP,
    which a busy day can exhaust."""
    seen = []

    class Got:
        returncode = 0
        stdout = '{"tag_name": "x", "published_at": "2024-02-03T00:00:00Z"}'

    monkeypatch.setattr(wezterm.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(wezterm, "_run", lambda argv, timeout=30: seen.append(argv) or Got())
    monkeypatch.setattr(
        wezterm.urllib.request,
        "urlopen",
        lambda *a, **k: pytest.fail("the API was called while gh was available"),
    )
    assert wezterm.latest_stable() == ("x", "2024-02-03")
    assert seen[0][:2] == ["gh", "auth"]


def test_an_unauthenticated_gh_falls_through_to_the_api(monkeypatch):
    class Refused:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(wezterm.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(wezterm, "_run", lambda argv, timeout=30: Refused())

    def refuse(*a, **k):
        raise OSError("offline")

    monkeypatch.setattr(wezterm.urllib.request, "urlopen", refuse)
    assert wezterm._gh_api("repos/x/y") is None


def test_unparseable_json_is_none_rather_than_an_exception(monkeypatch):
    class Got:
        returncode = 0
        stdout = "not json"

    monkeypatch.setattr(wezterm.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(wezterm, "_run", lambda argv, timeout=30: Got())
    assert wezterm._gh_api("repos/x/y") is None


def test_commits_since_needs_a_hash_and_a_total(monkeypatch):
    assert wezterm.commits_since("") is None
    monkeypatch.setattr(wezterm, "_gh_api", lambda path: {"total_commits": 8})
    assert wezterm.commits_since("abc") == 8
    monkeypatch.setattr(wezterm, "_gh_api", lambda path: {"total_commits": 0})
    assert wezterm.commits_since("abc") is None
    monkeypatch.setattr(wezterm, "_gh_api", lambda path: None)
    assert wezterm.commits_since("abc") is None


def test_a_missing_binary_probe_is_none_not_an_exception(monkeypatch):
    def refuse(*a, **k):
        raise OSError("nope")

    monkeypatch.setattr(wezterm.subprocess, "run", refuse)
    assert wezterm._run(["no-such-binary"]) is None


def test_the_linux_nightly_asset_follows_os_release(monkeypatch, tmp_path):
    monkeypatch.setattr(plat, "kind", lambda: plat.LINUX)
    release = tmp_path / "os-release"
    release.write_text('ID=ubuntu\nVERSION_ID="22.04"\n', encoding="utf-8")
    real = wezterm.Path
    monkeypatch.setattr(wezterm, "Path", lambda p: release if "os-release" in str(p) else real(p))
    assert wezterm.nightly_asset_pattern().match("wezterm-nightly.Ubuntu22.04.deb")

    release.write_text("ID=debian\nVERSION_ID=12\n", encoding="utf-8")
    assert wezterm.nightly_asset_pattern().match("wezterm-nightly.Debian12.deb")

    # An unreadable /etc/os-release must degrade, not raise.
    missing = tmp_path / "gone"
    monkeypatch.setattr(wezterm, "Path", lambda p: missing if "os-release" in str(p) else real(p))
    assert wezterm.nightly_asset_pattern().match("wezterm-nightly.Debian12.deb")


# ------------------------------------------------------------------- installing


def test_brew_install_removes_the_other_cask_first(monkeypatch, capsys):
    """Both casks own /Applications/WezTerm.app, so the second install refuses."""
    calls = []

    def fake_run(argv, timeout=30):
        calls.append(argv)

        class Got:
            # The other cask is installed; the wanted one is not.
            returncode = 0 if argv[:4] == ["brew", "list", "--cask", "wezterm"] else 1

        return Got()

    monkeypatch.setattr(wezterm, "_run", fake_run)
    wezterm._brew_install("wezterm@nightly", "wezterm", "nightly")
    flat = [" ".join(c) for c in calls]
    removed = next(i for i, f in enumerate(flat) if "uninstall --cask --force wezterm" in f)
    added = next(i for i, f in enumerate(flat) if f.endswith("install --cask wezterm@nightly"))
    assert removed < added, flat


def test_brew_install_upgrades_what_is_already_there(monkeypatch, capsys):
    class Got:
        returncode = 0

    monkeypatch.setattr(wezterm, "_run", lambda argv, timeout=30: Got())
    wezterm._brew_install("wezterm", "wezterm@nightly", "stable")
    assert "checking for an upgrade" in capsys.readouterr().out


def test_apt_install_purges_the_conflicting_package(monkeypatch, tmp_path, capsys):
    """The two packages conflict over /usr/bin/wezterm."""
    calls = []

    class Got:
        returncode = 0

    monkeypatch.setattr(wezterm, "_run", lambda argv, timeout=30: calls.append(argv) or Got())
    monkeypatch.setattr(wezterm.shutil, "which", lambda name: f"/usr/bin/{name}")
    keyring = tmp_path / "wezterm-fury.gpg"
    keyring.write_bytes(b"x")
    listing = tmp_path / "wezterm.list"
    listing.write_text(
        "deb [signed-by=/etc/apt/keyrings/wezterm-fury.gpg] https://apt.fury.io/wez/ * *\n",
        encoding="utf-8",
    )
    real = wezterm.Path

    def fake_path(p):
        if "keyrings" in str(p):
            return keyring
        if "sources.list.d" in str(p):
            return listing
        return real(p)

    monkeypatch.setattr(wezterm, "Path", fake_path)
    monkeypatch.setattr(wezterm, "installed", lambda: ("v", "d", "h"))
    wezterm._apt_install("wezterm-nightly", "wezterm")
    flat = [" ".join(c) for c in calls]
    assert any("apt-get purge -y wezterm" in f for f in flat)
    assert any("apt-get install -y wezterm-nightly" in f for f in flat)


def test_install_on_macos_without_brew_says_so(monkeypatch, capsys):
    monkeypatch.setattr(plat, "kind", lambda: plat.MACOS)
    monkeypatch.setattr(wezterm, "channel", lambda: "none")
    monkeypatch.setattr(wezterm.shutil, "which", lambda name: None)
    assert wezterm.install("stable") == 0
    assert "brew not found" in capsys.readouterr().out


def test_upgrade_never_switches_channel(monkeypatch):
    asked = []
    monkeypatch.setattr(wezterm, "channel", lambda: "nightly")
    monkeypatch.setattr(wezterm, "install", lambda want: asked.append(want) or 0)
    assert wezterm.upgrade() == 0
    assert asked == ["nightly"]


def test_upgrade_with_nothing_installed_says_how_to_add_it(monkeypatch, capsys):
    monkeypatch.setattr(wezterm, "channel", lambda: "none")
    assert wezterm.upgrade() == 0
    assert "install nightly" in capsys.readouterr().out


# ------------------------------------------------------------------- the pager


def test_changes_pages_through_glow_when_it_is_there(monkeypatch):
    seen = []

    class Got:
        returncode = 0

    monkeypatch.setattr(wezterm, "installed", lambda: ("v", "d", "h"))
    monkeypatch.setattr(wezterm, "changes_text", lambda version: "* one\n")
    monkeypatch.setattr(wezterm.shutil, "which", lambda name: "/usr/bin/glow")
    monkeypatch.setattr(wezterm.subprocess, "run", lambda argv, **k: seen.append(argv) or Got())
    assert wezterm.show_changes() == 0
    assert seen == [["glow", "-p", "-"]]


def test_changes_falls_back_to_the_pager(monkeypatch):
    seen = []

    class Got:
        returncode = 0

    monkeypatch.setattr(wezterm, "installed", lambda: ("v", "d", "h"))
    monkeypatch.setattr(wezterm, "changes_text", lambda version: "* one\n")
    monkeypatch.setattr(wezterm.shutil, "which", lambda name: None)
    monkeypatch.setenv("PAGER", "less -RF")
    monkeypatch.setattr(wezterm.subprocess, "run", lambda argv, **k: seen.append(argv) or Got())
    assert wezterm.show_changes() == 0
    assert seen == [["less", "-RF"]]


def test_changes_prints_directly_when_there_is_no_pager_at_all(monkeypatch, capsys):
    monkeypatch.setattr(wezterm, "installed", lambda: ("v", "d", "h"))
    monkeypatch.setattr(wezterm, "changes_text", lambda version: "* one\n")
    monkeypatch.setattr(wezterm.shutil, "which", lambda name: None)

    def refuse(*a, **k):
        raise OSError("no pager")

    monkeypatch.setattr(wezterm.subprocess, "run", refuse)
    assert wezterm.show_changes() == 0
    assert "* one" in capsys.readouterr().out


def test_status_is_the_default_verb(monkeypatch):
    called = []
    monkeypatch.setattr(wezterm, "status", lambda: called.append(1) or 0)
    assert wezterm.main([]) == 0
    assert wezterm.main(["status"]) == 0
    assert called == [1, 1]


def test_install_and_upgrade_route_through_main(monkeypatch):
    monkeypatch.setattr(wezterm, "install", lambda want: 0 if want == "nightly" else 2)
    monkeypatch.setattr(wezterm, "upgrade", lambda: 0)
    assert wezterm.main(["install", "nightly"]) == 0
    assert wezterm.main(["install"]) == 2
    assert wezterm.main(["upgrade"]) == 0


def test_the_state_dir_honours_the_shell_override(monkeypatch, tmp_path):
    """_TS_STATE is what dot_zshrc and the bootstraps already set."""
    monkeypatch.setenv("_TS_STATE", str(tmp_path))
    assert wezterm.state_dir() == tmp_path
    assert wezterm.changelog_path() == tmp_path / "wezterm-changelog.md"
