#!/usr/bin/env bash
# Run the suite on real native-Linux targets, locally, in seconds.
#
#   tests/parity/run.sh              every suite target
#   tests/parity/run.sh debian13     one target
#   tests/parity/run.sh --shell omarchy    a shell inside the target, to poke about
#   tests/parity/run.sh bootstrap          RUN linux-bootstrap.sh (Debian), end to end
#   tests/parity/run.sh ubuntu-bootstrap   ... and on Ubuntu
#   tests/parity/run.sh omarchy-bootstrap  RUN linux-bootstrap.sh (pacman), end to end
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

# The docker CLI, which on some hosts needs sudo to reach the daemon. Omarchy
# deliberately does NOT put the install user in the `docker` group -- its
# install/config/docker.sh records the reasoning, that group membership is
# equivalent to passwordless root -- so on the very platform the arch/omarchy
# targets below exist to gate, a bare `docker` is permission-denied and the
# whole parity run is unavailable.
#
# A ROOTLESS daemon is checked before sudo, because it is this user's own and
# needs no elevation at all -- the third answer to that trade, next to the group
# and to sudoless Docker. `docker context use rootless` already makes a bare
# `docker` find it, so the first branch usually wins; the socket probe is for a
# box that has the daemon and has not made it the default context, which would
# otherwise escalate for nothing.
#
# Escalates only when neither of those reaches a daemon AND a passwordless
# `sudo docker info` works: nothing here prompts, and nothing here changes the
# machine's security posture. If none works the first docker call fails with its
# own message, which is the right one to read.
DOCKER=(docker)
rootless_sock="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/docker.sock"
if docker info >/dev/null 2>&1; then
    :
elif [ -S "$rootless_sock" ] && DOCKER_HOST="unix://$rootless_sock" docker info >/dev/null 2>&1; then
    DOCKER=(env "DOCKER_HOST=unix://$rootless_sock" docker)
    echo "==> using the rootless daemon at $rootless_sock"
elif sudo -n docker info >/dev/null 2>&1; then
    DOCKER=(sudo docker)
    echo "==> using 'sudo docker' (the daemon is not reachable as this user)"
fi

declare -A TARGETS=(
    [debian13]="debian:13-slim"
    [ubuntu2404]="ubuntu:24.04"
    # 22.04 ships fzf 0.29, which has no `become(...)` action. _doc_edit_bind
    # exists entirely for that, and this is the only place it gets exercised.
    [ubuntu2204]="ubuntu:22.04"
    # Handled specially below: syntax gate only, no Python in the image.
    [bash32]="bash:3.2"
    # Handled specially below: runs the INSTALLER, not the suite. Not in the
    # default set -- it installs packages and wants the network, so it is opted
    # into rather than paid for on every run.
    [bootstrap]="debian:13-slim"
    # The same installer on Ubuntu. Debian and Ubuntu diverge on package
    # availability and Python version, and the ~/.claude tree that had never
    # deployed needs proving on both rather than on whichever one was handy.
    [ubuntu-bootstrap]="ubuntu:24.04"
    # Arch family. `arch` is plain archlinux with none of the `omarchy-*`
    # commands present, which is the case _common-arch.sh has to keep working
    # for and the one a developer on an Omarchy laptop never hits by accident.
    # `omarchy` adds Omarchy's os-release, its pacman repo and the real
    # omarchy-pkg-* helpers. Both build from Dockerfile.arch.
    [arch]="archlinux:latest"
    [omarchy]="archlinux:latest"
    # The installer, for real, on pacman. Opted into like the apt one.
    [arch-bootstrap]="archlinux:latest"
    [omarchy-bootstrap]="archlinux:latest"
)

# Which Dockerfile builds a target, and the DISTRO build-arg it wants. Absent
# means the Debian defaults.
declare -A DOCKERFILE=(
    [arch]=tests/parity/Dockerfile.arch
    [omarchy]=tests/parity/Dockerfile.arch
    [arch-bootstrap]=tests/parity/Dockerfile.arch-bootstrap
    [omarchy-bootstrap]=tests/parity/Dockerfile.arch-bootstrap
)
declare -A DISTRO_ARG=(
    [arch]=arch
    [omarchy]=omarchy
    [arch-bootstrap]=arch
    [omarchy-bootstrap]=omarchy
)

# The default set. `bootstrap` is deliberately absent; name it to run it.
DEFAULT_TARGETS=(debian13 ubuntu2404 ubuntu2204 arch omarchy bash32)

shell_mode=0
if [ "${1:-}" = "--shell" ]; then shell_mode=1; shift; fi
wanted=("${@:-}")
[ -z "${wanted[0]:-}" ] && wanted=("${DEFAULT_TARGETS[@]}")

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
    # Run the installer for real. The suite targets above prove the code
    # PARSES and that its names RESOLVE; this proves it RUNS. `bash -n` cannot
    # see an unset variable and a static resolver cannot see an empty catalog,
    # which is how the wizard came to be invoked with no TERMINAL_STACK_DIR and
    # offer no tools at all.
    # Run the installer for real. The suite targets prove the code PARSES and
    # that its names RESOLVE; this proves it RUNS. `bash -n` cannot see an unset
    # variable and a static resolver cannot see an empty catalog -- which is how
    # `USER` came to be read unguarded under `set -u` (fine in a login shell,
    # fatal under `docker run`, `su -c`, cron or systemd) and how the wizard came
    # to be invoked with no clone pinned.
    if [ "${name}" = bootstrap ] || [ "${name%-bootstrap}" != "$name" ]; then
        echo "==> $name (linux-bootstrap.sh, for real, on $base)"
        dockerfile="${DOCKERFILE[$name]:-tests/parity/Dockerfile.bootstrap}"
        build_args=(--build-arg "BASE=$base")
        [ -n "${DISTRO_ARG[$name]:-}" ] && build_args+=(--build-arg "DISTRO=${DISTRO_ARG[$name]}")
        "${DOCKER[@]}" build -q -f "$dockerfile" "${build_args[@]}" -t "$image" . >/dev/null
        # Every answer through the environment, so the questionnaire never
        # blocks. TS_APPS=none keeps the RUN about control flow -- wizard, config
        # save, chezmoi apply -- rather than about spending ten minutes pulling
        # thirty packages; the recommended set is still resolved and asserted on
        # inside bootstrap-check.sh, which is where the interesting bug lives.
        if "${DOCKER[@]}" run --rm -v "$root:/repo:ro"                 -e TS_ASSUME_YES=1 -e TS_HEADLESS_RESOLVED=1                 -e TS_PROFILE=shell -e TS_DEVELOPMENT=no -e TS_APPS=none                 -e TS_THEME=dark -e TS_LEADER=ctrl-space -e TS_TMUX=ctrl-b                 -e TS_ATUIN=off -e TS_CC_TTS=off -e TS_MEMORY_BACKEND=none                 -e TS_HEADROOM=off -e TS_CAVEMAN=off -e TS_AGENTMEMORY=off                 "$image" bash /repo/tests/parity/bootstrap-check.sh; then
            echo "    $name OK"
        else
            echo "    $name FAILED"
            failed+=("$name")
        fi
        continue
    fi

    if [ "$name" = bash32 ]; then
        echo "==> $name (bash 3.2 syntax gate for services/**)"
        # SCOPE WIDENED. This used to check services/** only, which left the
        # installer itself -- the part that actually changed -- unchecked on the
        # one bash version macOS ships. macOS cannot be containerised (containers
        # share the host kernel), so this target plus the GNU-only lint in
        # tests/test_agent_tools.py are the whole macOS story outside CI.
        if "${DOCKER[@]}" run --rm -v "$root:/repo:ro" bash:3.2 bash -c '
                rc=0
                for f in /repo/services/*.sh /repo/services/stacks/*/*.sh \
                         /repo/bootstrap/*.sh /repo/run_*.sh /repo/install-*.sh; do
                    [ -e "$f" ] || continue
                    case "$f" in *.tmpl) continue ;; esac
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
    dockerfile="${DOCKERFILE[$name]:-tests/parity/Dockerfile}"
    build_args=(--build-arg "BASE=$base")
    [ -n "${DISTRO_ARG[$name]:-}" ] && build_args+=(--build-arg "DISTRO=${DISTRO_ARG[$name]}")
    "${DOCKER[@]}" build -q -f "$dockerfile" "${build_args[@]}" -t "$image" . >/dev/null

    if [ "$shell_mode" = 1 ]; then
        exec "${DOCKER[@]}" run --rm -it -v "$root:/repo:ro" "$image" \
            bash -c 'cp -a /repo/. /work/ && exec bash'
    fi

    echo "==> $name"
    # Read-only mount, copied to /work: a container must never write to the
    # developer's tree. git needs safe.directory because the copy is owned by a
    # different uid than the one that made it.
    if "${DOCKER[@]}" run --rm -v "$root:/repo:ro" "$image" bash -c '
            set -e
            cp -a /repo/. /work/
            git config --global --add safe.directory /work
            # Drop everything git ignores, so the container sees what a CLEAN
            # CHECKOUT sees. Copying the tree verbatim inherits the developer`s
            # untracked files -- services/stacks/*/.env among them -- and that
            # made a test that only passes on an installed machine green here and
            # red on every CI runner. Uncommitted *tracked* changes stay, which
            # is the whole point of running this against the working tree.
            git -C /work ls-files --others --ignored --exclude-standard -z \
                | xargs -0 -r rm -f --
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
