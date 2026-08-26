---
description: Verify every testable assertion in the guidance docs, as claim / verdict / evidence
argument-hint: "[file ...]  (default: CLAUDE.md ARCHITECTURE.md README.md AGENTS.md)"
---

Go through $ARGUMENTS (default `CLAUDE.md`, `ARCHITECTURE.md`, `README.md`,
`AGENTS.md`). For every assertion of the form "X is pinned by a test", "X is
gated by Y", or "never do Z because W", **cite the test or file that backs it, or
delete the claim**.

Output a table: claim, verdict, evidence. Verdicts are `TRUE`, `FALSE`,
`UNENFORCED` (the rule is real but nothing checks it), `HALF-ENFORCED` (one twin
pinned, the other not), or `STALE` (line numbers or paths that have moved).

Check mechanically, not by reading. Grep `tests/` for the named function or
string; open the file at the cited line.

Then fix: an `UNENFORCED` claim becomes a test, or the claim goes. A `FALSE` one
is corrected in place. Rationale and incident history move to
`docs/decisions.md`; the guidance file keeps the rule and a link.

Precedent: `docs/decisions.md` § "The claims audit". The 2026-08-25 pass found
eight bad claims, one of which meant the repo's only automated gate had never run.
