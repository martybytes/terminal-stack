# terminal-stack agent rules

Process rules: which clone, what to commit, how to push. Architecture and
invariants are in `CLAUDE.md`; the two are deliberately separate.

## Which clone

- Implement changes only in a workspace development clone of this repository.
- Never edit the installed runtime clone (`~/.local/share/terminal-stack` or
  `%LOCALAPPDATA%\terminal-stack\stack`) directly.
- Never deploy uncommitted runtime-clone contents with `chezmoi apply` or
  `scripts/sync-windows.ps1`.
- Validate in the development clone, commit and push the change, then use
  `tstack update` to bring the clean commit into the runtime clone and deploy it.
- **A dev clone cannot verify end to end.** `chezmoi source-path` points at the
  runtime clone, and dev clones at workspace tier paths are deliberately
  invisible to resolution, so `chezmoi apply` from a dev tree deploys the *old*
  code and proves nothing about your change.

## Branches

- **One branch per phase**, named for the work (`feat/…`, `fix/…`, `docs/…`).
- Merge with `git merge --no-ff` into `main`. Never commit straight to `main`,
  never force-push.
- **Push the phase branch, not `main`.** The user pulls it deliberately.
- The port described in `REVAMP-PLAN.md` is phased; each phase is its own branch
  and must meet the completion contract below before the next one starts.

## Every behaviour-changing turn

- Update the relevant user documentation **and** the matching `doc` knowledge-base
  topic under `docs/kb/`, in the same commit as the change.
- Add a `CHANGELOG.md` entry under `[Unreleased]`, in the right section.
- Run the validation gates (below), commit all in-scope changes, and push the
  branch so the user can test with `tstack update`.
- Do not leave completed implementation only in the development clone unless the
  user explicitly says not to commit or push.

## Gates

Local, before committing:

```sh
python3 -m ruff check tstack tests
python3 -m ruff format --check tstack
python3 -m mypy
python3 -m pytest tests/ --cov
```

`.githooks/pre-commit` runs the first four; `.githooks/pre-push` adds coverage and
the characterization fixtures. They only fire when the clone has
`core.hooksPath=.githooks` — `ts_install_git_hooks` sets it, and until 2026-08-25
nothing did, so the gate had never run anywhere. Check it in a fresh clone.

**Two platforms must both be green on the same commit**: native pwsh and WSL
Ubuntu. macOS and native Debian/Ubuntu are covered by
`.github/workflows/ci.yml`, which cannot be run from this machine.

- Do not use `chezmoi re-add` on templated terminal-stack targets; it replaces
  template directives with machine-rendered content. Full rule, including the
  cases where re-add *is* correct: `CLAUDE.md` § "The one `re-add` rule".

## Never weaken a gate to make it pass

Do not skip, `xfail`, delete or loosen a test to get green. If a test fails,
either the code is wrong or the test's anchor moved — repoint the anchor, keeping
the rule it enforces. A test that asserts a string appears in a file must fail
when that file is missing; use `repo_file()` in `tests/test_agent_tools.py` rather
than reading a path directly, or the assertion goes vacuous the day the file is
deleted.
