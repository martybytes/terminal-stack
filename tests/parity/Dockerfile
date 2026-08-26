# Parity target: run the suite on a REAL native Linux, not on WSL.
#
# WSL is not native Linux for this repo's purposes -- /mnt/c exists, interop
# exists, and tstack/platform.py deliberately reports `wsl` rather than `linux`.
# Every native-Linux branch was therefore only ever exercised by CI, which is a
# slow loop and one nobody watches while writing the code.
#
# Deliberately NOT a macOS target: containers share the host kernel, so Darwin
# cannot be containerised at all. tests/parity/Dockerfile.bash32 covers the part
# of macOS that actually bites this repo -- bash 3.2 -- and the rest stays CI's
# job on macos-latest.

ARG BASE=debian:13-slim
FROM ${BASE}

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

# zsh is not optional: dot_zshrc is zsh-only syntax that `bash -n` cannot check,
# and without zsh present that gate skips silently -- the exact failure mode this
# whole change set is about.
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        bash zsh git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# A venv, because Debian 13 and Ubuntu 24.04 mark the system Python
# externally-managed (PEP 668) and refuse a plain `pip install`.
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"
RUN pip install --no-cache-dir pytest pytest-cov hypothesis

# The repo is mounted read-only at /repo and copied to /work, so a container can
# never write to the developer's tree -- not the source, not .git, not a stray
# .pyc. A test that corrupts the machine it is meant to protect is not a test.
WORKDIR /work
CMD ["/bin/bash", "-c", "echo 'run via tests/parity/run.sh'"]
