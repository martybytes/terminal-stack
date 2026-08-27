---
description: Check a REVAMP-PLAN phase against the completion contract before advancing
---

Print the Definition of Done and tick each box explicitly. Do not advance with an
unticked box, and do not report a box as ticked without the evidence.

- [ ] full pytest suite green on **Windows pwsh** and **WSL Ubuntu**, same commit
- [ ] CI green for macOS and native Debian/Ubuntu (`.github/workflows/ci.yml`)
- [ ] characterization fixtures pass against the Python implementation
- [ ] shell twins deleted, `tstack/commands.conf` row flipped to `python`
- [ ] README, CLAUDE.md, AGENTS.md, ARCHITECTURE.md, INSTALL.md, docs/, docs/kb/
      and CHANGELOG `[Unreleased]` updated in the same commit
- [ ] coverage floor met and **raised**, ruff check, ruff format, mypy
- [ ] help text, prompts, errors and exit codes reviewed and tested
- [ ] branch merged `--no-ff`, phase branch pushed (not `main`)

Never weaken, skip, `xfail` or delete a test to tick a box. If a test fails,
either the code is wrong or its anchor moved - repoint the anchor and keep the
rule.
