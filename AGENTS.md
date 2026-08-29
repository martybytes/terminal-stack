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

`develop` is the default branch and the integration branch. `main` is the
release branch: **protected**, and reachable only through a pull request whose
CI is green.

- **One branch per phase**, named for the work (`feat/…`, `fix/…`, `docs/…`),
  cut from `develop`.
- Merge with `git merge --no-ff` into `develop`. Never commit straight to
  `main`, never force-push.
- **Push the phase branch, not `develop` or `main`.** The user pulls it
  deliberately.
- `develop` → `main` is a pull request, always. Protection on `main` requires
  one and requires every CI check to pass, so this is not a convention that can
  be forgotten — but note that admins are exempt, which makes it a rule you keep
  rather than one that keeps you.
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
`core.hooksPath=.githooks` - `ts_install_git_hooks` sets it, and until 2026-08-25
nothing did, so the gate had never run anywhere. `tstack doctor` now reports it
for the dev clone you are standing in, which is the only place it can be wrong.

**The hooks find their tools three ways** (`.githooks/_gates.sh`): an importable
module, then a binary on PATH, then `uvx`. Only the second shape is what this
stack installs - `TS_APPS_RECOMMENDED` carries `ruff` and `uv` as formulae, and
`ruff` has no importable module at all - so probing for the module alone printed
"NOT RUN" for every gate and exited 0. If you add a gate, resolve it through
`gate_runner` rather than a bare `import` probe; `tests/test_githooks.py` pins it.

**On macOS, `brew install powershell`.** 5 test files gate on pwsh being present
and skip silently without it, including the AST scan for the `$foo`/`$Foo`
collision that once killed the entire Windows wizard. They run pure PowerShell
with `USERPROFILE`/`LOCALAPPDATA` overridden, so macOS pwsh satisfies all five.

**Two platforms must both be green on the same commit**: native pwsh and WSL
Ubuntu. Whichever machine you are on covers at most one of the four targets
directly, so say which you ran rather than implying the rest: a Windows box has
pwsh and WSL but no macOS and no native Linux; a Mac has macOS and, with the brew
install above, pwsh - but no WSL, and `tests/parity/run.sh` needs bash 4+ for
`declare -A` so it cannot run there either. `.github/workflows/ci.yml` is the only
thing that covers all four.

Native Linux is not one of those two, and WSL is not a stand-in for it -
`tstack/platform.py` reports `wsl` there on purpose. Run it for real:

```sh
tests/parity/run.sh
```

Debian 13, Ubuntu 24.04, Ubuntu 22.04 and a bash 3.2 syntax gate, in containers, in
about two seconds, each on its *own* Python. That last part is why it exists: the
repo's floor is Python 3.10, which is what Ubuntu 22.04 ships, while CI has 3.12 and
this machine has 3.14. Same jobs run in CI. Details: `docs/verifying-changes.md` § 0.

- Do not use `chezmoi re-add` on templated terminal-stack targets; it replaces
  template directives with machine-rendered content. Full rule, including the
  cases where re-add *is* correct: `CLAUDE.md` § "The one `re-add` rule".

## Never weaken a gate to make it pass

Do not skip, `xfail`, delete or loosen a test to get green. If a test fails,
either the code is wrong or the test's anchor moved - repoint the anchor, keeping
the rule it enforces. A test that asserts a string appears in a file must fail
when that file is missing; use `repo_file()` in `tests/test_agent_tools.py` rather
than reading a path directly, or the assertion goes vacuous the day the file is
deleted.
