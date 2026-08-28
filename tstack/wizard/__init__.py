"""The install questionnaire, once, in Python.

Replaces `bootstrap/_wizard.sh` and the `Read-Ts*` half of
`bootstrap/_config.ps1` -- two implementations of the same fourteen questions
that had to be kept in agreement by hand, and had not been: the pwsh tick-list
applied a multi-answer all-or-nothing while bash applied the valid tokens and
warned about the rest.

WHAT THIS MODULE MAY NOT DO

It never writes. No `store.set`, no `chezmoi`, no installs. It collects answers
and hands them back; the four bootstraps keep their existing setter sequences,
which is what preserves the documented invariant that answers are saved before
anything that can fail. A test greps this package for the writers to keep it
true.
"""

from .flow import Answers, collect

__all__ = ["Answers", "collect"]
