---
description: Run every gate on Windows pwsh and WSL Ubuntu against the same commit
---

Both platforms must be green on the **same commit**. `tstack/store.py` and the
config mirror only both execute across that boundary, so one platform passing
proves half the change.

Windows:

```
python3 -m ruff check tstack tests
python3 -m ruff format --check tstack
python3 -m mypy
python3 -m pytest tests/ --cov
pwsh -NoLogo -NoProfile -File <scratch>/parsecheck.ps1 -Root .
```

WSL (no sudo needed; `uv` is already installed by the stack):

```
wsl -e bash -lc 'uv venv --python 3.12 /tmp/tsvenv'
wsl -e bash -lc 'uv pip install --python /tmp/tsvenv/bin/python -q pytest pytest-cov hypothesis'
wsl -e bash -lc 'cd <clone> && /tmp/tsvenv/bin/python -m pytest tests/ -q'
wsl -e zsh -n <clone>/dot_zshrc
```

Report the pass/fail counts for each platform separately. Do not report a single
number. macOS and native Debian/Ubuntu are CI's job (`.github/workflows/ci.yml`)
and cannot be run here - say so rather than implying they were checked.
