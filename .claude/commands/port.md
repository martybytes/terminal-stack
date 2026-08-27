---
description: Port one subsystem from the shell twins to Python
argument-hint: <subsystem>   e.g. doctor, config, services
---

Port `$ARGUMENTS` from its bash + PowerShell twins to a single Python module.
Order and rationale: `REVAMP-PLAN.md`.

Preconditions - stop if either is unmet:
- `tests/characterize/$ARGUMENTS/` exists and passes against the **shell**
  implementation (`/characterize $ARGUMENTS` first).
- Both platforms are currently green.

Then:
1. Write `tstack/commands/$ARGUMENTS.py` exposing `main(argv) -> int`.
2. Add `--json` output. Structure it as a read model, not a print statement.
3. Make the characterization fixtures pass against the Python version.
4. Flip **both** columns of that row in `tstack/commands.conf` to `python`.
5. Delete the shell twins. Repoint - do not delete - any test that asserted
   against them; `impl_paths()` in `tests/test_agent_tools.py` resolves through
   the registry so most follow automatically.
6. Raise the coverage floor in `pyproject.toml`. Never lower it.

Invariants that survive every port:
- Config writes go through the one writer. A second one is how this repo lost
  five TTS hooks in a day.
- `chezmoi init` still runs after a save, so the derived keys regenerate.
- Standalone writers stay standalone: flipping mux must not re-state every other
  choice.
- Errors say what failed, why, and the exact next action. No bare tracebacks.
- `NO_COLOR`, non-TTY, `--quiet`, `--verbose` and `--dry-run` all honoured.
