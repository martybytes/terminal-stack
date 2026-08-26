#!/usr/bin/env bash
# Run the suite on real native-Linux targets, locally, in seconds.
#
#   tests/parity/run.sh              every target
#   tests/parity/run.sh debian13     one target
#   tests/parity/run.sh --shell debian13   a shell inside the target, to poke about
#
# Why this exists: WSL is not native Linux here. /mnt/c exists, interop exists,
# and tstack/platform.py reports `wsl` rather than `linux` on purpose -- so every
# native-Linux branch was only ever exercised by CI. That is a slow loop, and one
# nobody watches while actually writing the code.
#
# macOS is absent on purpose and cannot be added: containers share the host
# kernel, so Darwin cannot be containerised. The `bash32` target covers the part
# of macOS that actually bites this repo (bash 3.2 is what /bin/bash is there),
# and real macOS stays CI's job on macos-latest.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$root"

declare -A TARGETS=(
    [debian13]="debian:13-slim"
    [ubuntu2404]="ubuntu:24.04"
    # 22.04 ships fzf 0.29, which has no `become(...)` action. _doc_edit_bind
    # exists entirely for that, and this is the only place it gets exercised.
    [ubuntu2204]="ubuntu:22.04"
    # Handled specially below: syntax gate only, no Python in the image.
    [bash32]="bash:3.2"
)

shell_mode=0
if [ "${1:-}" = "--shell" ]; then shell_mode=1; shift; fi
wanted=("${@:-}")
[ -z "${wanted[0]:-}" ] && wanted=("${!TARGETS[@]}")

failed=()
for name in "${wanted[@]}"; do
    base="${TARGETS[$name]:-}"
    if [ -z "$base" ]; then
        echo "unknown target '$name'; have: ${!TARGETS[*]}" >&2
        exit 2
    fi
    image="tstack-parity:$name"

    # bash 3.2 is what /bin/bash is on macOS, and services/**/*.sh are required
    # to be clean under it. This target runs the syntax gate there and nothing
    # else -- there is no Python in the image and no suite to run.
    #
    # SCOPE, because assuming otherwise is worse than not having it: this catches
    # bash-4-only SYNTAX (declare -A, ${var^^}, mapfile, &>>). It does NOT
    # reproduce the locale-dependent multibyte trap macOS has, where the lead byte
    # of a UTF-8 character after a bare $var passes isalnum() and `set -u` aborts.
    # Verified: `bash -uc 'd=/tmp; echo "$d<U+2026>"'` succeeds in this image even
    # under LANG=en_US.UTF-8, because musl handles locales differently from
    # Darwin. That trap is covered instead by the test that greps for $var
    # followed by non-ASCII, which works on every platform.
    if [ "$name" = bash32 ]; then
        echo "==> $name (bash 3.2 syntax gate for services/**)"
        if docker run --rm -v "$root:/repo:ro" bash:3.2 bash -c '
                rc=0
                for f in /repo/services/*.sh /repo/services/stacks/*/*.sh; do
                    [ -e "$f" ] || continue
                    bash -n "$f" || rc=1
                done
                exit $rc
            '; then
            echo "    $name OK"
        else
            echo "    $name FAILED"
            failed+=("$name")
        fi
        continue
    fi

    echo "==> building $name ($base)"
    docker build -q -f tests/parity/Dockerfile --build-arg "BASE=$base" -t "$image" . >/dev/null

    if [ "$shell_mode" = 1 ]; then
        exec docker run --rm -it -v "$root:/repo:ro" "$image" \
            bash -c 'cp -a /repo/. /work/ && exec bash'
    fi

    echo "==> $name"
    # Read-only mount, copied to /work: a container must never write to the
    # developer's tree. git needs safe.directory because the copy is owned by a
    # different uid than the one that made it.
    if docker run --rm -v "$root:/repo:ro" "$image" bash -c '
            set -e
            cp -a /repo/. /work/
            git config --global --add safe.directory /work
            zsh -n dot_zshrc
            for f in bootstrap/*.sh services/*.sh services/stacks/*/*.sh \
                     install-*.sh run_after_90-sync-windows.sh run_before_*.sh; do
                [ -e "$f" ] || continue
                case "$f" in *.tmpl) continue ;; esac
                bash -n "$f"
            done
            python -m pytest tests/ -o addopts= -q
        '; then
        echo "    $name OK"
    else
        echo "    $name FAILED"
        failed+=("$name")
    fi
done

if [ ${#failed[@]} -gt 0 ]; then
    echo
    echo "parity FAILED on: ${failed[*]}" >&2
    exit 1
fi
echo
echo "parity OK on: ${wanted[*]}"
