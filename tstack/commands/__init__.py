"""Ported subcommands, one module per tstack/commands.conf entry.

A module here exposes `main(argv: list[str]) -> int` and nothing else. It is
reached only when both implementation columns for its name read `python`, so
adding a module and flipping the table are one change, not two.

Empty in phase 0 by design: the dispatcher, the shims, the registry and the test
harness land first, with every subcommand still routed to its shell
implementation. `doctor` is the first port. See REVAMP-PLAN.md.
"""
