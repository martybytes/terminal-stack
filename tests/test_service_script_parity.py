"""Keep the .ps1 and .sh script sets under services/ from drifting apart.

Every script in the absorbed service tree exists twice
(docs/service-conventions.md, "Scripts"). Nothing enforces that but this file,
because there is no CI here.

The tests read the divergence register in docs/service-conventions.md, so a
DELIBERATE difference passes and an unrecorded one fails. That distinction is
the whole point: without it the first intentional difference teaches everyone to
weaken the test.

SCOPE. The scan covers services/** and nothing else. Inside that tree pairing is
mandatory, which is the rule it was written under. It stops at the tree boundary
for two reasons: this repo has ~25 legitimately unpaired .sh (ts-mux.sh, wso.sh,
_doctor.sh, every dot_claude/hooks/*.sh, ...) and ~15 unpaired .ps1
(_merge_*.ps1, install-tts-daemon.ps1, ...), so an unscoped scan reports ~50
failures and teaches everyone to delete the file; and the rules here are not
this repo's rules — ts-agents takes positional arguments on the bash side and
named parameters on the pwsh side, deliberately, which the flag-mapping test
below would call a defect. terminal-stack's own twins are pinned by the
-h-byte-identical and AST tests in tests/test_agent_tools.py instead.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVICES = ROOT / "services"

# Sourced libraries and helpers, not executables, and deliberately unpaired:
# PowerShell has dot-sourcing and ConvertTo/FromJson built in.
UNPAIRED = {"_stack.sh", "_json.mjs", "entrypoint.sh"}


def sh_scripts():
    return sorted(p for p in SERVICES.rglob("*.sh") if p.name not in UNPAIRED)


def ps_scripts():
    return sorted(SERVICES.rglob("*.ps1"))


def read(p):
    return p.read_text(encoding="utf-8-sig", errors="replace")


def strip_comments(text):
    """Drop whole-line comments before scanning for banned constructs.

    _common.sh documents the bash-4 features it avoids *by name*, so a naive
    scan flags the very file that is doing the right thing.
    """
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))


# --------------------------------------------------------------------------
def test_every_script_has_a_twin():
    """The likeliest drift by far: a script added on one side only."""
    missing = []
    for p in ps_scripts():
        if not p.with_suffix(".sh").exists():
            missing.append(f"{p.relative_to(ROOT)} has no .sh twin")
    for p in sh_scripts():
        if not p.with_suffix(".ps1").exists():
            missing.append(f"{p.relative_to(ROOT)} has no .ps1 twin")
    assert not missing, "\n".join(missing)


def test_shared_constants_match_within_each_pair():
    """Ports, pins and safety limits must not be changed on one side only.

    Compared PER PAIR, not across the whole corpus: a corpus-wide presence check
    passes when a port is changed in one script but still mentioned in another,
    which is exactly the drift this is meant to catch.
    """
    shared = [
        # host ports
        "3110", "3111", "3112", "3113", "3114", "8880", "8931",
        # pins, limits and stable names
        "0.1.18", "268435456", "http://127.0.0.1:8931/mcp",
        "agentmemory_iii-data", "agent007memory_history",
    ]
    # Deliberately no bare "1000"/"3600" here: they are substrings of 100000,
    # "0.01 1000" and 3600000, so they match incidentally and the test cries
    # wolf. Only tokens distinctive enough to mean one thing belong in this list.
    problems = []
    for ps in ps_scripts():
        sh = ps.with_suffix(".sh")
        if not sh.exists():
            continue
        ps_text, sh_text = read(ps), read(sh)
        for token in shared:
            in_ps, in_sh = token in ps_text, token in sh_text
            if in_ps != in_sh:
                only, missing = (ps.name, sh.name) if in_ps else (sh.name, ps.name)
                problems.append(f"{token!r} is in {only} but not in {missing}")
    assert not problems, "\n".join(problems)


def test_reconcile_embedded_programs_are_identical():
    """~120 lines of JS and sh are copied verbatim into both. Easiest silent divergence."""
    ps = read(SERVICES / "stacks/agentmemory/reconcile-llm-queue.ps1").replace("\r\n", "\n")
    sh = read(SERVICES / "stacks/agentmemory/reconcile-llm-queue.sh").replace("\r\n", "\n")

    def between(text, start, end):
        i = text.index(start)
        return text[i:text.index(end, i) + len(end)]

    for name, start, end in [
        ("node analysis", 'const fs = require("fs");', "}));\n"),
        ("sh quarantine", "set -eu\nsrc=/data/queue_store", "sync\n"),
    ]:
        assert between(ps, start, end) == between(sh, start, end), \
            f"the embedded {name} program has diverged between the two files"


# --------------------------------------------------------------------------
def test_sh_scripts_are_bash_32_clean():
    """macOS ships bash 3.2 and always will (docs/service-conventions.md, "Scripts")."""
    banned = {
        r"\bdeclare\s+-A\b": "associative arrays",
        r"\bmapfile\b": "mapfile",
        r"\breadarray\b": "readarray",
        r"\$\{[A-Za-z_][A-Za-z0-9_]*,,": "${x,,} lowercasing",
        r"\$\{[A-Za-z_][A-Za-z0-9_]*\^\^": "${x^^} uppercasing",
        r";;&": ";;& fallthrough",
    }
    problems = []
    for p in list(sh_scripts()) + [SERVICES / "_stack.sh"]:
        text = strip_comments(read(p))
        for pattern, what in banned.items():
            if re.search(pattern, text):
                problems.append(f"{p.relative_to(ROOT)} uses {what} (bash 4+)")
    assert not problems, "\n".join(problems)


def test_sh_scripts_have_the_house_prologue():
    for p in sh_scripts():
        text = read(p)
        rel = p.relative_to(ROOT)
        assert text.startswith("#!/usr/bin/env bash"), f"{rel}: wrong or missing shebang"
        assert "set -euo pipefail" in text, f"{rel}: missing strict mode"
        assert "_common.sh" in text, f"{rel}: does not source _common.sh"
        assert re.search(r"twin of \S+\.ps1", text), f"{rel}: header does not name its .ps1 twin"


def test_sh_files_have_no_cr_and_no_bom():
    """A BOM sits before the shebang; a CR breaks `sh -c` under set -eu."""
    for p in list(sh_scripts()) + [SERVICES / "_stack.sh"]:
        raw = p.read_bytes()
        rel = p.relative_to(ROOT)
        assert not raw.startswith(b"\xef\xbb\xbf"), f"{rel}: has a UTF-8 BOM"
        assert b"\r" not in raw, f"{rel}: contains a CR byte"


# --------------------------------------------------------------------------
def _registered_divergences():
    """Script basenames named in the divergence register in docs/service-conventions.md."""
    text = (ROOT / "docs/service-conventions.md").read_text(encoding="utf-8")
    start = text.index("### Intentional divergences")
    table = text[start:text.index("\n## ", start)]
    return set(re.findall(r"`([A-Za-z0-9_.-]+\.(?:sh|ps1|mjs))`", table))


def test_the_divergence_register_exists_and_is_populated():
    assert len(_registered_divergences()) >= 5, \
        "docs/service-conventions.md's divergence register looks empty — the flag test below relies on it"


def test_every_ps1_flag_has_a_kebab_case_counterpart():
    """The 1:1 flag mapping is what lets every doc show one command instead of two."""
    problems = []
    registered = _registered_divergences()
    for ps in ps_scripts():
        sh = ps.with_suffix(".sh")
        if not sh.exists():
            continue
        text = read(ps)
        m = re.search(r"^param\s*\((.*?)^\)", text, re.S | re.M)
        if not m:
            continue
        sh_text = read(sh)
        for flag in re.findall(r"\$([A-Z][A-Za-z0-9]*)\s*(?:,|\)|=|$)", m.group(1)):
            kebab = "--" + re.sub(r"(?<!^)(?=[A-Z])", "-", flag).lower()
            if kebab not in sh_text and sh.name not in registered:
                problems.append(f"{ps.name} has -{flag} but {sh.name} has no {kebab}")
    assert not problems, "\n".join(problems)
