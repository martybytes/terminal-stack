"""The Omarchy desktop integration: three files, and the rules about them.

These files live OUTSIDE chezmoi's target tree, in Omarchy's own extension
points, which is what makes them worth testing here: chezmoi cannot notice they
have drifted, and the desktop cannot tell you they are broken. A theme hook that
fails takes no visible action -- `omarchy theme set` still succeeds -- so a
silent regression here looks exactly like everything working.
"""

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tstack import omarchy  # noqa: E402
from tstack import platform as plat  # noqa: E402


@pytest.fixture
def box(tmp_path, monkeypatch):
    """An Omarchy-shaped machine rooted in tmp_path."""
    home = tmp_path / "home"
    (home / ".config").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(home / ".local" / "state"))
    monkeypatch.setenv("TS_DISTRO_ID", "omarchy")
    monkeypatch.setenv("TS_DISTRO_LIKE", "arch")
    plat.clear_distro_cache()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    yield home
    plat.clear_distro_cache()


def _lines():
    out: list[str] = []
    return out, out.append


# ---- the artefacts, as values ----------------------------------------------


def test_every_artefact_carries_the_ownership_marker_on_one_line(box):
    """`_is_ours` greps for the marker, so a marker split across two lines makes
    the file read as somebody else's.

    That is not hypothetical: the WezTerm template shipped with the marker
    wrapped, so every sync politely skipped its own file and the template could
    never be refreshed after an upgrade. It looked like success -- "up to date".
    """
    for art in omarchy.artefacts():
        assert any(omarchy.OURS in line for line in art.content.splitlines()), (
            f"{art.path.name}: the marker is not on any single line"
        )


def test_the_wezterm_template_speaks_omarchys_template_language(box):
    tpl = next(a for a in omarchy.artefacts() if a.path.name == "wezterm.lua.tpl")
    # Omarchy substitutes `{{ key }}` with sed. Doubled braces are the scar of an
    # f-string: they would reach Omarchy as literal `{{{{` and substitute nothing.
    assert "{{{{" not in tpl.content
    for key in ("mode", "background", "foreground", "cursor", "accent", "muted"):
        assert "{{ " + key + " }}" in tpl.content, f"template does not use {{{{ {key} }}}}"

    # Eight and eight, or WezTerm rejects the scheme. Sliced by line rather than
    # by regex: `.*?` up to the first `}` stops inside the first `{{ key }}`.
    def block(name: str) -> str:
        lines = tpl.content.splitlines()
        start = next(i for i, ln in enumerate(lines) if ln.strip().startswith(f"{name} = {{"))
        end = next(i for i in range(start + 1, len(lines)) if lines[i].strip() == "},")
        return "\n".join(lines[start + 1 : end])

    assert len(re.findall(r"\{\{ \w+ \}\}", block("ansi"))) == 8
    assert len(re.findall(r"\{\{ \w+ \}\}", block("brights"))) == 8
    # It has to be loadable Lua once rendered: balanced braces, and a `return`.
    assert tpl.content.count("{") == tpl.content.count("}")
    assert tpl.content.lstrip().splitlines()[0].startswith("--")
    assert "\nreturn {" in tpl.content


def test_the_hooks_resolve_the_clone_at_run_time(box):
    """A baked absolute path breaks the day `tstack doctor --repair` relocates
    the clone -- on every theme change, with nothing to connect it to the move."""
    hooks = [a for a in omarchy.artefacts() if a.path.parent.name.endswith(".d")]
    assert len(hooks) == 2
    for hook in hooks:
        assert "TERMINAL_STACK_DIR" in hook.content
        assert 'main.py" omarchy' in hook.content
        # No absolute path into this checkout, ever.
        assert str(ROOT) not in hook.content
        # A hook that errors on every desktop event is worse than no hook.
        assert "|| exit 0" in hook.content
        assert hook.executable


def test_the_update_hook_reports_and_does_not_pull(box):
    """`tstack update` is a zsh function carrying the dirty-clone refusal, the
    rollback point and the duplicate-clone warning. A bash hook can neither call
    it nor honestly reimplement it."""
    hook = next(a for a in omarchy.artefacts() if a.path.parent.name == "post-update.d")
    assert "update-check" in hook.content
    for forbidden in ("git pull", "chezmoi apply", "rollback-sha"):
        assert forbidden not in hook.content, f"the update hook does {forbidden!r} itself"


# ---- sync, off, on ----------------------------------------------------------


def test_sync_installs_then_does_nothing(box):
    _, say = _lines()
    assert omarchy.sync(say) == 0
    for art in omarchy.artefacts():
        assert art.path.exists(), art.path
        if art.executable:
            assert art.path.stat().st_mode & stat.S_IXUSR

    out2, say2 = _lines()
    assert omarchy.sync(say2) == 0
    assert not [line for line in out2 if line.startswith("  write")], (
        "a second sync rewrote files that had not changed"
    )
    assert any("up to date" in line for line in out2)


def test_sync_never_clobbers_a_file_that_is_not_ours(box):
    """Somebody else's hook with the same name is a deliberate act. Silently
    overwriting it is the failure this repo keeps writing tests about."""
    art = omarchy.artefacts()[1]
    art.path.parent.mkdir(parents=True, exist_ok=True)
    art.path.write_text("#!/bin/bash\n# mine, thanks\n", encoding="utf-8")

    out, say = _lines()
    assert omarchy.sync(say) == 0
    assert art.path.read_text(encoding="utf-8") == "#!/bin/bash\n# mine, thanks\n"
    assert any("not ours" in line for line in out)


def test_sync_refreshes_a_stale_file_that_is_ours(box):
    """The other half of the rule: ours, and out of date, must be rewritten --
    otherwise an upgrade never reaches the installed hooks."""
    omarchy.sync(lambda _m: None)
    art = omarchy.artefacts()[1]
    art.path.write_text(f"#!/bin/bash\n# {omarchy.OURS}\n# ancient version\n", encoding="utf-8")
    out, say = _lines()
    assert omarchy.sync(say) == 0
    assert art.path.read_text(encoding="utf-8") == art.content
    assert any("write" in line for line in out)


def test_off_removes_only_ours_and_is_remembered(box):
    omarchy.sync(lambda _m: None)
    stranger = omarchy.config_home() / "omarchy" / "hooks" / "theme-set.d" / "someone-else"
    stranger.write_text("#!/bin/bash\n", encoding="utf-8")

    assert omarchy.turn_off(lambda _m: None) == 0
    for art in omarchy.artefacts():
        assert not art.path.exists(), f"{art.path} survived off"
    assert stranger.exists(), "off removed a file that was not ours"
    assert omarchy.off_sentinel().exists()
    assert not omarchy.enabled()

    # And an apply must not quietly reinstate what someone removed.
    out, say = _lines()
    assert omarchy.sync(say) == 0
    assert not any(a.path.exists() for a in omarchy.artefacts())
    assert any("is off" in line for line in out)

    assert omarchy.turn_on(lambda _m: None) == 0
    assert all(a.path.exists() for a in omarchy.artefacts())
    assert not omarchy.off_sentinel().exists()


def test_every_verb_refuses_politely_off_omarchy(tmp_path, monkeypatch):
    monkeypatch.setenv("TS_DISTRO_ID", "debian")
    plat.clear_distro_cache()
    try:
        for action in (omarchy.sync, omarchy.status, omarchy.turn_on, omarchy.turn_off):
            out, say = _lines()
            assert action(say) == 2, action.__name__
            assert any("not an Omarchy host" in line for line in out)
    finally:
        plat.clear_distro_cache()


# ---- the hook verbs' contract ----------------------------------------------


def test_the_hook_verbs_cannot_take_the_desktop_down(box, monkeypatch):
    """`omarchy theme set` and `omarchy update` run these. Whatever goes wrong
    inside, they must not fail the operation the user actually asked for."""
    from tstack.commands import omarchy as cmd

    def boom(*_a, **_k):
        raise RuntimeError("the store is unreachable")

    monkeypatch.setattr(cmd.omarchy, "theme_mode", boom)
    assert cmd.main(["theme-changed", "tokyo-night"]) == 0
    monkeypatch.setattr(cmd.paths, "resolve_source_dir", boom)
    assert cmd.main(["update-check"]) == 0


def test_the_theme_hook_touches_the_wezterm_config(box, monkeypatch):
    """WezTerm watches its OWN config, not the generated theme file beside it, so
    a theme change reaches a running instance only if the config is touched."""
    from tstack.commands import omarchy as cmd

    config = box / ".wezterm.lua"
    config.write_text("-- config\n", encoding="utf-8")
    os.utime(config, (0, 0))
    monkeypatch.setattr(cmd.omarchy, "theme_mode", lambda: "dark")
    monkeypatch.setattr(cmd.store, "get", lambda key, default="": default)

    assert cmd.main(["theme-changed", "tokyo-night"]) == 0
    assert config.stat().st_mtime > 0, "the WezTerm config was not touched"


# ---- how the rest of the tree hooks into it --------------------------------


def test_the_apply_hook_self_no_ops_off_omarchy():
    """Same bargain run_after_90-sync-windows.sh strikes: one source tree, every
    platform, and the script decides for itself whether it has work."""
    body = (ROOT / "run_after_50-omarchy-integration.sh").read_text(encoding="utf-8")
    assert "grep -qi '^ID=omarchy' /etc/os-release" in body
    assert "exit 0" in body
    # Non-fatal: the dotfiles are the deliverable, this is a convenience on top.
    assert "omarchy sync || true" in body


def test_wezterm_lands_on_omarchy_but_not_on_other_linux():
    """The gate's old comment said native-Linux hosts here are headless. Omarchy
    is a Hyprland desktop with wezterm in `extra`, and the flagship config was
    the one thing the stack did not deploy there."""
    ignore = (ROOT / ".chezmoiignore").read_text(encoding="utf-8")
    block = ignore[ignore.index("WezTerm GUI config") :]
    block = block[: block.index("{{ end }}")]
    assert '"distroId"' in block and "omarchy" in block
    assert ".wezterm.lua" in block and ".wezterm/**" in block
    # Ghostty stays macOS-only: Omarchy owns ~/.config/ghostty/config.
    after = ignore[ignore.index("WezTerm GUI config") :]
    assert ".config/ghostty/**" in after


def test_the_wezterm_config_overlays_the_generated_theme():
    """Three guards, because this file must load on a machine with no Omarchy, no
    such file, and no guarantee the file is well-formed."""
    lua = (ROOT / "dot_wezterm.lua.tmpl").read_text(encoding="utf-8")
    body = lua[lua.index("local function omarchy_overlay") :]
    body = body[: body.index("P = omarchy_overlay(P)")]
    assert "pcall(dofile" in body, "an unguarded dofile takes the whole config down"
    assert "type(t) ~= 'table'" in body
    assert "type(t.background) ~= 'string'" in body
    assert body.count("return p") >= 3, "a failed load must leave the baked palette"
    # It has to run AFTER the baked palette is chosen, or there is nothing to
    # overlay onto.
    assert lua.index("local P = pick_palette(THEME_MODE)") < lua.index("P = omarchy_overlay(P)")
    # The Claude state tints are semantic washes, not theme colours.
    assert "cc_working" not in body and "cc_error" not in body


def test_docker_advice_points_at_omarchys_own_opt_in(monkeypatch):
    """Omarchy declines the docker group on purpose (install/config/docker.sh:
    membership is equivalent to passwordless root). Telling a user to
    `usermod -aG docker` there is telling them to undo that, without saying so."""
    from tstack import engine

    monkeypatch.setenv("TS_DISTRO_ID", "omarchy")
    plat.clear_distro_cache()
    try:
        advice = "\n".join(engine.engine_advice(engine.LINUX, engine.DENIED))
        assert "omarchy-setup-security-sudoless-docker" in advice
        assert "sudo docker" in advice
        assert "usermod" not in advice
    finally:
        plat.clear_distro_cache()

    monkeypatch.setenv("TS_DISTRO_ID", "debian")
    plat.clear_distro_cache()
    try:
        advice = "\n".join(engine.engine_advice(engine.LINUX, engine.DENIED))
        assert "usermod -aG docker" in advice, "the ordinary Linux advice went missing"
    finally:
        plat.clear_distro_cache()


def test_the_shell_does_not_overwrite_omarchys_editor():
    """EDITOR=omarchy-launch-editor is not a preference: it is the launcher
    `omarchy-launch-config-editor` and the Super-key binding use, and SUDO_EDITOR
    is derived from it. Overwriting it was a desktop-level break caused by a
    shell-level default."""
    rc = (ROOT / "dot_zshrc").read_text(encoding="utf-8")
    block = rc[rc.index("# micro (a nano alternative)") :]
    block = block[: block.index("# Git muscle-memory overrides")]
    assert '"${EDITOR:-}" == omarchy-launch-editor*' in block
    # Matched on the value, not the distro: dot_zshrc is not a template and has
    # to stay correct on five platforms.
    assert "os-release" not in block
    assert "export EDITOR='micro'" in block, "the ordinary default went missing"


def test_omarchy_is_registered_as_a_posix_only_command():
    conf = (ROOT / "tstack/commands.conf").read_text(encoding="utf-8")
    row = next(ln for ln in conf.splitlines() if ln.split()[:1] == ["omarchy"])
    _, posix, windows = row.split()[:3]
    assert posix == "python"
    # There is no Omarchy on Windows, and `-` says so plainly rather than
    # reporting "not found".
    assert windows == "-"
