# Characterization fixtures

What the **shell** implementation of a subsystem actually did, captured before it
was replaced, so the Python port can be held to it.

This is the safety net for the port described in `REVAMP-PLAN.md`. A 14,000-line
rewrite in a repo whose signature failure is silent, correct-looking wrong
behaviour needs something better than "the tests still pass" - most of those
tests assert on shell *source text*, and pass trivially once the shell is gone.

## Shape

```
tests/characterize/<subsystem>/<case>.json
```

Each case records one invocation:

```json
{
  "argv": ["--quiet"],
  "env": {"TS_DOCTOR_QUIET": "1"},
  "sandbox": "empty-home",
  "exit_code": 1,
  "stdout_lines": ["..."],
  "stderr_lines": []
}
```

`sandbox` names a fixture environment built by `tests/characterize/sandbox.py`,
never the real one: a doctor run against your live machine records your Docker
state, your TTS settings and your clone paths, none of which reproduce anywhere
else.

## Recording

```sh
python -m tests.characterize.record doctor
```

Runs the shell implementation named in `tstack/commands.conf` and writes the
fixtures. Re-record only when the shell behaviour genuinely changed - a fixture
that is regenerated to match a regression is worse than no fixture.

## Verifying

`tests/test_characterize.py` replays every fixture against the **Python**
implementation and requires the same exit code and the same normalised output.
`pre-push` runs it.

## Normalisation

Absolute paths, timestamps, durations, SHAs and the sandbox root are replaced
with stable tokens before comparison; see `normalise()` in `sandbox.py`. Without
that, a fixture recorded on one machine can never pass on another, which is the
usual reason this kind of corpus gets deleted six weeks in.

## What is deliberately NOT pinned

Ordering of independent checks, colour codes, and anything gated on a service
being reachable. Those vary legitimately between machines. What is pinned is the
set of check ids, their severities, the exit code, and the wording of every
message a user is expected to act on.
