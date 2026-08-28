#!/usr/bin/env bash
# How to run a Python dev tool on THIS machine. Sourced by pre-commit and
# pre-push so the answer is worked out once.
#
# Three shapes, and the stack itself produces the second one:
#
#   1. an importable module   python3 -m ruff   (pip install --user)
#   2. a binary on PATH       ruff              (brew / winget)
#   3. uvx                    uvx ruff          (uv is in the catalog too)
#
# Shape 2 is the common case and used to be invisible. `TS_APPS_RECOMMENDED`
# installs `ruff` and `uv` as FORMULAE, not as site-packages, so `import ruff`
# fails on every machine this stack provisions -- and both hooks probed only for
# the module. The result was a hook that printed "NOT RUN" for all four gates and
# exited 0: the precise failure pre-commit's own comment warns about ("a gate you
# believe is running and is not is worse than no gate"), one level up.
#
# `ruff` has no importable module at all, so shape 1 can never work for it.
#
# Prints the runner, rather than running it, because the caller owns cwd and
# argv. That matters for pytest: `python3 -m pytest` puts the working directory
# on sys.path and `uvx pytest` does not, and tests/ has no __init__.py while its
# modules import each other -- so the caller exports PYTHONPATH for shapes 2/3.
#
# Bash 3.2 clean: this runs on macOS, where /bin/bash is 3.2.

# gate_runner <module> [package] -> argv prefix on stdout, empty when unavailable
gate_runner() {
    module="$1"
    package="${2:-$1}"
    if python3 -c "import $module" >/dev/null 2>&1; then
        printf 'python3 -m %s' "$module"
    elif command -v "$module" >/dev/null 2>&1; then
        printf '%s' "$module"
    elif command -v uvx >/dev/null 2>&1; then
        printf 'uvx --quiet --from %s %s' "$package" "$module"
    fi
}

# gate_needs_pythonpath <runner> -> 0 when the runner will NOT add cwd to sys.path
gate_needs_pythonpath() {
    case "$1" in
        "python3 -m "*) return 1 ;;
        *) return 0 ;;
    esac
}
