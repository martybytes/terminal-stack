#!/usr/bin/env bash
# Everything CI will check that this machine CAN check, before you push.
#
# WHY THIS EXISTS
#
# The gates in .githooks/ run on the working tree. CI runs on the MERGE of that
# tree with main, on four operating systems and six containers. Two of those
# differences have already cost a red PR each:
#
#   * A branch that is green alone can be red merged. CLAUDE.md has a hard
#     40,000-byte cap; main sat at 39,957 and two branches each trimmed the SAME
#     lines to fit, so the merge kept both additions and one copy of the savings
#     -- 40,234, and a PR blocked after the push. Nothing local looked at the
#     merge.
#   * `tomllib` is 3.11+. tests/parity/run.sh has run Ubuntu 22.04 (Python 3.10)
#     in about two seconds this whole time, and it was not run.
#
# So this is the deliberate pre-push step, not a hook. It is allowed to be slow,
# to touch the network and to want Docker; the hooks are not.
#
# WHAT IT CANNOT DO
#
# macOS and Windows. Containers share the host kernel, so Docker on Linux cannot
# run either, and no amount of local tooling will change that. Those two axes are
# covered by reading instead: test_no_shell_file_uses_a_gnu_only_spelling,
# test_no_test_shells_out_to_a_literal_bash and
# test_no_test_binds_a_unix_socket_under_tmp_path each catch the CLASS on any OS.
# What is left over genuinely needs CI, which is free on this public repo.
#
# Bash 3.2 clean: this repo runs on macOS, where /bin/bash is 3.2.
set -u

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root" || exit 1
# shellcheck source=/dev/null
. "$root/.githooks/_gates.sh"

PARITY=1
MERGE=1
BASE="origin/main"
for arg in "$@"; do
    case "$arg" in
        --no-parity) PARITY=0 ;;
        --no-merge)  MERGE=0 ;;
        --base=*)    BASE="${arg#--base=}" ;;
        -h|--help)
            echo 'scripts/preflight.sh [--no-parity] [--no-merge] [--base=<ref>]'
            echo
            echo '  Runs the gates, the suite, the Linux parity containers and a'
            echo '  test-merge against main. macOS and Windows are CI-only.'
            exit 0 ;;
        *) echo "preflight: unknown argument '$arg'" >&2; exit 2 ;;
    esac
done

failed=""
note() { printf '\n==> %s\n' "$1"; }
fail() { failed="$failed $1"; printf '!! %s FAILED\n' "$1"; }

# ---------------------------------------------------------------- the gates --
ruff="$(gate_runner ruff)"
mypy="$(gate_runner mypy)"
pytest="$(gate_runner pytest)"

note "lint / format / types"
if [ -n "$ruff" ]; then
    $ruff check tstack tests || fail "ruff check"
    $ruff format --check tstack || fail "ruff format"
else
    echo "   ruff NOT RUN - install it, or uv"
    fail "ruff (unavailable)"
fi
if [ -n "$mypy" ]; then
    $mypy || fail "mypy"
else
    echo "   mypy NOT RUN - install it, or uv"
    fail "mypy (unavailable)"
fi

# pytest-cov has to live in the SAME environment as pytest, so an ephemeral uvx
# run names it rather than probing for it here -- the rule .githooks/pre-push
# already writes down. Without it the run still happens, without the floor;
# silently dropping the whole suite would be worse than dropping the number.
case "$pytest" in
    uvx*) cov="uvx --quiet --from pytest --with pytest-cov pytest"; have_cov=1 ;;
    "")   cov=""; have_cov=0 ;;
    *)    cov="$pytest"
          if $pytest --co -q --cov >/dev/null 2>&1; then have_cov=1; else have_cov=0; fi ;;
esac

note "suite"
if [ -z "$pytest" ]; then
    echo "   pytest NOT RUN - install it, or uv"
    fail "pytest (unavailable)"
else
    if [ "$have_cov" = 1 ]; then
        set -- tests/ --cov -q
        runner="$cov"
    else
        echo "   pytest-cov missing - running WITHOUT the coverage floor."
        set -- tests/ -q
        runner="$pytest"
    fi
    if gate_needs_pythonpath "$runner"; then
        PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" $runner "$@" || fail "pytest"
    else
        $runner "$@" || fail "pytest"
    fi
fi

# ------------------------------------------------------- the parity containers
# Never prompts. `sudo -n docker` is how tests/parity/run.sh escalates, and on a
# box where that wants a password an unattended preflight would hang on it --
# so the reachability probe is the same non-interactive one, and a miss is a
# printed line rather than a wait. Omarchy leaves you out of the docker group on
# purpose (membership is equivalent to passwordless root);
# omarchy-setup-security-sudoless-docker is its documented opt-in.
if [ "$PARITY" -eq 1 ]; then
    note "parity containers (debian, ubuntu 24.04, ubuntu 22.04 = Python 3.10, arch, bash 3.2)"
    if docker info >/dev/null 2>&1 || sudo -n docker info >/dev/null 2>&1; then
        bash "$root/tests/parity/run.sh" || fail "parity"
    else
        echo "   SKIPPED - docker needs a password here, and preflight never prompts."
        echo "   Enable it with: omarchy-setup-security-sudoless-docker"
        echo "   Or run it yourself:  tests/parity/run.sh"
    fi
fi

# ------------------------------------------------------- the merge with main --
# The check the CLAUDE.md incident asked for. A throwaway worktree, so the tree
# you are standing in is never touched and an interrupted run cannot leave a
# half-merged checkout behind.
if [ "$MERGE" -eq 1 ]; then
    note "merge with $BASE"
    if ! git rev-parse --verify -q "$BASE" >/dev/null; then
        echo "   SKIPPED - no $BASE locally; fetch it first."
    else
        wt="$(mktemp -d "${TMPDIR:-/tmp}/ts-preflight-XXXXXX")"
        # Always clean up: a stale worktree makes every later run fail to add one.
        trap 'git worktree remove --force "$wt" >/dev/null 2>&1; rm -rf "$wt"' EXIT
        if git worktree add -q --detach "$wt" HEAD >/dev/null 2>&1; then
            if git -C "$wt" merge --no-commit --no-ff "$BASE" >/dev/null 2>&1; then
                echo "   merges cleanly"
            else
                conflicts="$(git -C "$wt" diff --name-only --diff-filter=U | tr '\n' ' ')"
                if [ -n "$conflicts" ]; then
                    echo "   CONFLICTS: $conflicts"
                    fail "merge (conflicts)"
                fi
            fi
            # Run the suite on the merge RESULT even when it conflicted: the
            # non-conflicting half is still what main is about to receive, and
            # the size gate that started all this lives there.
            if [ -n "$pytest" ]; then
                if gate_needs_pythonpath "$pytest"; then
                    ( cd "$wt" && PYTHONPATH="$wt" $pytest tests/ -q ) || fail "merged suite"
                else
                    ( cd "$wt" && $pytest tests/ -q ) || fail "merged suite"
                fi
            fi
        else
            echo "   SKIPPED - could not create a worktree"
        fi
    fi
fi

# ------------------------------------------------------------------ the verdict
printf '\n'
if [ -n "$failed" ]; then
    echo "preflight: FAILED -$failed"
    echo "macOS and Windows are still only covered by CI."
    exit 1
fi
echo "preflight: OK. macOS and Windows are still only covered by CI."
