"""The check model shared by `doctor` and anything that reports health.

A check produces a `Result`, not a printed line. That separation is what makes
`--json` a read model rather than a second rendering of the same prose, and it
is why every message can be asserted by id instead of by matching text.

Severities, and what each one means for the exit code:

    OK    the thing is right. Suppressed by --quiet.
    FAIL  something is wrong and actionable. Counts toward the exit status.
    NOTE  worth saying, not a failure. Never counts.

NOTE exists because the shell version needed it and got it right: a leftover
clone, a mute, or a legacy clone location are all things you want told about
while `tstack doctor` still reports a healthy install. Folding them into FAIL
would train people to ignore the exit code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

OK = "ok"
FAIL = "fail"
NOTE = "note"


@dataclass(frozen=True)
class Result:
    check: str  # stable id, safe to assert on; never the prose
    status: str  # OK | FAIL | NOTE
    message: str
    hint: str = ""  # the exact next action, when there is one

    def as_dict(self) -> dict[str, str]:
        out = {"check": self.check, "status": self.status, "message": self.message}
        if self.hint:
            out["hint"] = self.hint
        return out

    def render(self) -> str:
        """One line, matching the shell's shape so the two are comparable."""
        if self.status == OK:
            return f"  ok  {self.message}"
        if self.status == NOTE:
            text = f"  note: {self.message}"
        else:
            text = f"  !! {self.message}"
        # A NOTE's hint renders too. It used to be dropped, which meant the one
        # thing a hint is for -- "the exact next action" -- reached --json only:
        # the ssh symlink note named the symptom and swallowed the fsutil
        # command, and `other-clones` swallowed its repair line the same way.
        return f"{text}; {self.hint}" if self.hint else text


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)

    def ok(self, check: str, message: str) -> None:
        self.results.append(Result(check, OK, message))

    def fail(self, check: str, message: str, hint: str = "") -> None:
        self.results.append(Result(check, FAIL, message, hint))

    def note(self, check: str, message: str, hint: str = "") -> None:
        self.results.append(Result(check, NOTE, message, hint))

    @property
    def issues(self) -> int:
        return sum(1 for r in self.results if r.status == FAIL)

    def as_dict(self) -> dict[str, object]:
        return {
            "issues": self.issues,
            "checks": [r.as_dict() for r in self.results],
        }
