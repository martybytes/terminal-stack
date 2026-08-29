"""A bash function name is resolved when it is called, and not before.

`tests/test_shell_symbols.py` already resolves `ts_`/`_ts_` names statically.
That prefix filter is why `tstack config prompt` could ship as four calls to
four functions that no longer existed anywhere in the tree.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _sh_sources() -> list[Path]:
    files = [p for p in ROOT.rglob("*.sh") if ".git" not in p.parts]
    files.append(ROOT / "dot_zshrc")
    return [p for p in files if p.is_file()]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def _rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


_HEREDOC = re.compile(r"""<<-?\s*["']?([A-Za-z_][A-Za-z0-9_]*)["']?""")

# Command position: start of line, after a case arm's `)`, or after then/else/do.
# Anything followed by = += ( . ) [ or : is a variable, an array element, a
# module path, a case PATTERN or a label -- not a call.
_CALL = re.compile(
    r"(?:^[ \t]*|\)[ \t]+|\b(?:then|else|do)[ \t]+)"
    r"([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b(?![ \t]*[=+(.)\[:])"
)

_DEFINITION = re.compile(r"^\s*(?:function\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{", re.M)


def _code_lines(text: str):
    """(lineno, line) for real shell code, with heredoc bodies excluded.

    `bootstrap/` embeds Python, jq and awk in heredocs, and their identifiers
    look exactly like shell helper calls (`os.path.join(stable_dir, ...)`,
    `ascii_downcase`). Skipping the bodies is what keeps this specific enough to
    be worth having.
    """
    terminator: str | None = None
    for lineno, line in enumerate(text.splitlines(), 1):
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        found = _HEREDOC.search(line)
        if found:
            terminator = found.group(1)
            continue
        yield lineno, line


def test_no_bash_script_calls_a_local_helper_that_no_longer_exists():
    """`tstack config prompt` was four calls to four functions that were gone.

    `prompt_status`, `prompt_list`, `prompt_preview` and `prompt_set` went out
    with the ghostty port as collateral damage; zero definitions remained
    repo-wide and all four call sites stayed. Under `set -euo pipefail` the verb
    exited 127 with `prompt_status: command not found`, while `ts-config.sh -h`
    went on advertising it.

    The sibling check in `test_shell_symbols.py` resolves only `ts_`/`_ts_`
    names, which is exactly why these four were invisible to it.
    """
    defined: set[str] = set()
    for path in _sh_sources():
        defined |= {m.group(1) for m in _DEFINITION.finditer(_read(path))}

    dangling = []
    for path in _sh_sources():
        if path.parts[len(ROOT.parts)] != "bootstrap":
            continue
        for lineno, line in _code_lines(_read(path)):
            if line.lstrip().startswith("#"):
                continue
            for m in _CALL.finditer(line.split(" #")[0]):
                name = m.group(1)
                if name not in defined:
                    dangling.append(
                        f"{_rel(path)}:{lineno} calls {name}(), which is defined nowhere"
                    )

    assert not dangling, "\n" + "\n".join(dangling)
