---
description: Record characterization fixtures from a shell subsystem before porting it
argument-hint: <subsystem>   e.g. doctor, config, services
---

Capture what the **existing shell implementation** of `$ARGUMENTS` actually does,
before any Python is written. This is the safety net for the port: without it, a
14,000-line rewrite in a repo whose signature failure is silent, correct-looking
wrong behaviour has nothing to check against.

1. Find the implementation from `tstack/commands.conf` (both columns).
2. For each meaningful invocation - no args, `-h`, each subcommand, the error
   paths - run it in a **throwaway store**, never the real one:
   - POSIX: a temp `HOME` with its own `chezmoi.toml`. Omit `windowsUsername` so
     the Windows mirror no-ops.
   - Windows: override `$env:LOCALAPPDATA` in a child pwsh.
   Recipes: `docs/verifying-changes.md` § 4.
3. Record stdout, stderr, exit code, and the resulting file contents into
   `tests/characterize/$ARGUMENTS/`.
4. Include the failure cases deliberately: missing clone, dangling
   `TERMINAL_STACK_DIR`, malformed config, unreachable Docker. Those are where a
   port silently diverges.

Fixtures are the contract. When the Python version lands it must reproduce them
exactly, and any deliberate difference gets an explicit, commented waiver.
