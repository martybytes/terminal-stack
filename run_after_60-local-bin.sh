#!/usr/bin/env bash
# run_after_60-local-bin.sh — clone the private ~/bin tools repo if it is absent.
#
# ~/bin is a separate private repo (martybytes/local-bin), NOT chezmoi-managed
# content. Its scripts are edited and committed in place, which is exactly what
# chezmoi's source->target model fights: a one-line fix would mean editing the
# source and applying before you could run it. A plain clone keeps `git commit`
# where the work happens.
#
# Deliberately not .chezmoiexternal.toml. A git-repo external runs `git pull` on a
# refresh period, which is built for vendored read-only content (fonts, plugins).
# Pointed at a repo you author in, it fights local commits and fails whenever the
# tree is dirty.
#
# run_after_ rather than run_once_: the only work here is a directory test, so
# running on every apply costs nothing and restores ~/bin if it is ever deleted.
# It never pulls — updating is `git -C ~/bin pull`, like any other clone.
#
# Chicken-and-egg: ~/bin contains ssh-key-helper, the tool used to create GitHub
# SSH keys in the first place, so on a brand-new machine the SSH clone cannot
# work yet. gh is tried as a fallback because its token auth does not need a key.
# If neither works this prints one line and moves on; rerun apply after keys are
# set up, or clone by hand.
#
# Never fails an apply. A missing tools directory is worth a line on stderr; it is
# not worth aborting the deployment of everything else.
set -eu

repo_ssh="git@github.com:martybytes/local-bin.git"
repo_nwo="martybytes/local-bin"
dest="$HOME/bin"

[ -e "$dest" ] && exit 0
command -v git >/dev/null 2>&1 || exit 0

if git clone --quiet "$repo_ssh" "$dest" 2>/dev/null; then
  printf 'local-bin: cloned to %s\n' "$dest"
  exit 0
fi

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  if gh repo clone "$repo_nwo" "$dest" -- --quiet 2>/dev/null; then
    printf 'local-bin: cloned to %s via gh\n' "$dest"
    exit 0
  fi
fi

printf 'local-bin: could not clone %s to %s — no GitHub SSH key or gh auth yet.\n' \
  "$repo_nwo" "$dest" >&2
printf 'local-bin: set up access, then rerun chezmoi apply or clone by hand.\n' >&2
exit 0
