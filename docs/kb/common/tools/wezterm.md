# WezTerm (terminal emulator)

GPU-accelerated terminal and multiplexer. The one this stack ships a config for:
the hand-drawn fancy tab bar, the pane-nav keys, the Claude pane tints and the
optional mux domain are all `.wezterm.lua`, deployed by chezmoi.

## Two channels, and you pick

Upstream publishes a **stable** release and a **nightly** rolling build. Stable is
`20240203-110809` — February 2024, with **no cut since** — so nightly is what
@wez uses daily, what upstream's own docs describe as "usually the best available
version", and what this stack's Lua targets. Nightly is therefore the
pre-selected answer at install.

**Nothing is automatic.** The wizard asks, `tstack update` offers when something newer
exists on the channel you are already on, and `tstack config wezterm` changes it on
demand. No path installs, upgrades or switches without a yes.

| Command | What it does |
|---|---|
| `tstack config wezterm` | your build + date, newest on each channel, what changed since |
| `tstack wezterm` | the same, as a standalone command |
| `tstack config wezterm changes` | the full upstream changelog since your build, paged |
| `tstack config wezterm install nightly` | switch channel — removes the other package first |
| `tstack config wezterm install stable` | the other direction |
| `tstack config wezterm upgrade` | refresh the channel you are on; never switches |
| `wezterm --version` | the raw build string |

Sample:

```
==> WezTerm
    Installed : 20240203-110809-5046fc22  (stable, 2024-02-03)
    nightly   : built 2026-08-23
    stable    : 20240203-110809-5046fc22  (2024-02-03)  — you are on it
    Since your build: 909 commits — Changed 20  New 32  Fixed 74  Updated 9
    Full notes: tstack config wezterm changes
```

## Where those numbers come from

Nothing is summarised or inferred — it is all upstream's own data:

- **Your build date is in the release name.** WezTerm names releases
  `<YYYYMMDD>-<HHMMSS>-<githash>`, so `wezterm --version` dates your build with
  no network call at all.
- **Latest stable** is the `releases/latest` tag and its publish date.
- **Latest nightly** is the build date of the nightly asset *for your platform* —
  not the nightly release's own date, which is stuck in 2019 because the tag is a
  rolling one. This matters: the Debian10 nightly last built over a year ago
  while Debian12's built today.
- **What changed** is sliced out of upstream's `docs/changelog.md` at the heading
  matching your version — their notes, counted, not rewritten. For a nightly
  there is no heading to anchor on, so the commit count from GitHub's compare API
  is the honest answer instead.

Offline, all of it degrades to "installed version and date" rather than failing.

## The channel is not a saved setting

It is read back from the package manager — `brew list --cask wezterm@nightly` vs
`wezterm`, `winget list --id wez.wezterm.nightly` vs `wez.wezterm`, `dpkg -s
wezterm-nightly` vs `wezterm`. So it cannot drift out of sync with what is
actually installed, and a manual `brew install --cask wezterm@nightly` is picked
up on its own. A WezTerm no package manager here owns reports channel `unknown`:
its version is still shown, and install/upgrade leave it alone.

Switching removes the other channel first — both casks own
`/Applications/WezTerm.app`, both apt packages own `/usr/bin/wezterm`, so they
cannot coexist.

## Installing it in the first place

macOS `brew install --cask wezterm@nightly`; Windows `winget install --id
wez.wezterm.nightly`; Debian/Ubuntu via upstream's apt repo (`apt.fury.io/wez`),
which carries both channels so `apt upgrade` keeps it current. WSL never installs
one — the GUI lives on the Windows side. See `doc wezterm/panes`, `doc
wezterm/tabs` and `doc wezterm/dev-config` for the config itself, and `tstack mux -h`
for the multiplexer domain.
