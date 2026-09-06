"""Omarchy's zsh base, and the collision that aborts an rc silently.

`omarchy-zsh` is Omarchy's own official zsh configuration, and on an Omarchy box
it is the right base: it is the zsh half of the aliases, functions and
environment the desktop's bash rc provides, so `zsh -l` stops being a different
machine from the one Super+Return opens.

THE FAILURE THIS MODULE EXISTS FOR

zsh expands aliases at PARSE time. Omarchy defines `c` and `cy` as aliases; this
stack defines both as functions. Defining a function whose name is a live alias
is a parse error -- and a parse error in an rc does not stop at that line, it
abandons THE REST OF THE FILE. Measured in the omarchy parity container with
omarchy-zsh installed and dot_zshrc as ~/.zshrc:

    /root/.zshrc:470: defining function based on alias `cy'
    /root/.zshrc:470: parse error near `()'
    ws=none  doc=none  tstack=none        <- everything after line 470

Guarding the definition in `if ... fi` does NOT help: zsh parses the whole block
before evaluating the condition. `\\cy()` does -- the backslash suppresses alias
expansion, so the block parses on every platform and the guard decides only
whether the function is defined.

The repo has met this exact shape before, which is why dot_zshrc does not load
oh-my-zsh's `z` plugin: "(eval):...: defining function based on alias `z'".
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ZSHRC = ROOT / "dot_zshrc"

# Every alias omarchy-zsh defines, from omarchy-zsh 1.5.0-2. Enumerated by
# sourcing its zoptions/envs/aliases/functions in the omarchy parity container
# and printing ${(k)aliases}. Hard-coded because the package is in Omarchy's own
# pacman repo and the suite must run on macOS and Windows too; the container is
# where the list is checked against reality.
OMARCHY_ALIASES = frozenset(
    {
        "..", "...", "....", "c", "cd", "cx", "cy", "d", "decompress", "eff", "ff",
        "g", "gcad", "gcam", "gcm", "ic", "icx", "ix", "ls", "lsa", "lt", "lta",
        "r", "run-help", "t", "which-command",
    }
)


def _function_names(text: str) -> set[str]:
    """Top-level `name() {` definitions, with any alias-suppressing backslash."""
    return set(re.findall(r"(?m)^\\?([a-zA-Z0-9_.-]+)\(\)", text))


def _escaped_function_names(text: str) -> set[str]:
    return set(re.findall(r"(?m)^\\([a-zA-Z0-9_.-]+)\(\)", text))


def test_every_collision_with_an_omarchy_alias_is_escaped():
    """THE regression test.

    A stack function whose name is an Omarchy alias must be written `\\name()`.
    Without the backslash the rc dies at that line and every later definition --
    ws, doc, tstack, the cc wrappers -- is silently absent on an Omarchy box with
    omarchy-zsh installed, and only there.
    """
    text = ZSHRC.read_text(encoding="utf-8")
    collisions = _function_names(text) & OMARCHY_ALIASES
    escaped = _escaped_function_names(text)
    unescaped = sorted(collisions - escaped)
    assert not unescaped, (
        "these dot_zshrc functions share a name with an omarchy-zsh ALIAS and are "
        f"not escaped: {unescaped}. Write them as \\{unescaped[0]}() and guard them "
        'with [[ -z "$_TS_OMARCHY_ZSH" ]] -- an unescaped definition is a parse '
        "error that abandons the rest of the rc."
    )


def test_the_escaped_definitions_are_also_guarded():
    """Escaping alone only fixes the PARSE. Defining the function anyway would
    still shadow nothing (the alias wins at call time) while looking as though it
    had -- so the guard is what makes the deferral real and visible."""
    lines = ZSHRC.read_text(encoding="utf-8").splitlines()
    for name in sorted(_escaped_function_names("\n".join(lines))):
        # Anchored to the start of a line: the prose above these definitions
        # names `\c()` literally, and an unanchored search found the COMMENT.
        idx = next(i for i, ln in enumerate(lines) if ln.startswith(f"\\{name}()"))
        window = "\n".join(lines[max(0, idx - 3) : idx])
        assert '[[ -z "$_TS_OMARCHY_ZSH" ]]' in window, (
            f"\\{name}() is escaped but not guarded on $_TS_OMARCHY_ZSH"
        )


def test_the_omarchy_base_is_sourced_without_its_inits():
    """`inits` runs starship, zoxide, mise and fzf init -- all of which this rc
    does itself, and the prompt is a saved setting (`tstack config prompt`).
    Sourcing both registers two sets of precmd hooks for one prompt."""
    text = ZSHRC.read_text(encoding="utf-8")
    block = text[text.index("_TS_OMARCHY_ZSH=") :]
    block = block[: block.index("# ---- terminal-stack-zsh-start ----")]
    for wanted in ("zoptions", "envs", "aliases", "functions"):
        assert wanted in block, f"the Omarchy zsh base does not source {wanted}"
    assert "inits" not in block, "sourcing Omarchy's inits double-initialises the prompt"
    # Detected by the FILE, not the distro: dot_zshrc is not a chezmoi template
    # (CLAUDE.md, the re-add rule) and has to stay correct on five platforms.
    assert "/usr/share/omarchy-zsh/shell/all" in block
    assert "os-release" not in block


def test_oh_my_zsh_is_sourced_only_when_it_is_there():
    """The bootstrap does not install oh-my-zsh on Omarchy any more, and an
    unguarded `source $ZSH/oh-my-zsh.sh` on a machine without it prints an error
    on every single shell."""
    text = ZSHRC.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if "oh-my-zsh.sh" in ln and "source" in ln)
    guarded = '[[ -r "$ZSH/oh-my-zsh.sh" ]]' in text
    assert guarded, f"unguarded oh-my-zsh source: {line.strip()}"


def test_syntax_highlighting_is_last_of_all():
    """It wraps every ZLE widget defined before it and nothing after, which is
    why omarchy-zsh's own aggregate ends with this exact line and says so. It has
    to come after ~/.zshrc.local too -- a user's own widgets are widgets."""
    text = ZSHRC.read_text(encoding="utf-8")
    hl = text.index("zsh-syntax-highlighting.zsh")
    local = text.index('source "$HOME/.zshrc.local"')
    assert local < hl, "syntax highlighting must load after ~/.zshrc.local"
    assert text[hl:].strip().endswith("zsh-syntax-highlighting.zsh"), (
        "something was added after the syntax-highlighting source"
    )


def test_the_bootstrap_picks_the_right_base_and_leaves_the_generator_alone():
    """`omarchy-setup-zsh` generates its own ~/.zshrc, and chezmoi owns that file
    whole-file. Running it would hand the file to the other tool."""
    arch = (ROOT / "bootstrap/_common-arch.sh").read_text(encoding="utf-8")
    body = arch[arch.index("common_zsh_base()") :]
    body = body[: body.index("\n}\n")]
    assert "ts_is_omarchy" in body, "plain Arch must still get oh-my-zsh"
    assert "omarchy-zsh" in body
    assert "common_oh_my_zsh" in body, "there is no fallback if the package install fails"
    # The generator is named only to say it is not run.
    assert "omarchy-setup-zsh" in arch
    for line in arch.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert not stripped.startswith("omarchy-setup-zsh"), "the bootstrap runs the generator"

    debian = (ROOT / "bootstrap/_common-debian.sh").read_text(encoding="utf-8")
    assert "common_zsh_base() { common_oh_my_zsh; }" in debian
