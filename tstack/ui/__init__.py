"""`tstack ui` - the settings dashboard.

Kept in its own package for one reason: it is the only part of `tstack` that
imports a third-party library. Everything else runs from the clone on the stdlib
alone, which is what lets a fresh machine run `tstack doctor` before anything is
installed. Textual is therefore OPTIONAL, imported nowhere but `app.py`, and
`tstack ui` says how to get it rather than raising ImportError at someone.

The split inside the package is deliberate too. `model.py` is pure - it turns the
schema plus the store into rows, filters them, and decides what a save would do -
and it is what the tests exercise. `app.py` is the Textual shell around it and
holds no rules of its own.
"""
