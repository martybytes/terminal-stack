#!/usr/bin/env bash
# _wezterm.sh — WezTerm channel facts: what is installed, what upstream has, and
# what changed in between. Sourced (never executed) by ts-wezterm.sh, _wizard.sh,
# mac-bootstrap.sh and _common-debian.sh. Do not `exit` here — return non-zero.
#
# WezTerm publishes two channels and the stack installs NEITHER automatically:
# the wizard asks, tstack update offers, tstack config changes it. Upstream's newest
# stable is 20240203 (February 2024, no cut since), which is why nightly is the
# pre-selected answer rather than the forced one — see docs/decisions.md
# § "Why the WezTerm channel is a question, and why it is not a saved setting".
#
# The channel is NOT a saved setting. It is read back from the package manager
# (brew cask / winget id / dpkg package), which cannot drift out of sync with
# reality the way a stored value can, and costs no chezmoi [data] key.
#
# Everything that touches the network fails OPEN and SILENT: a report that
# degrades to "installed version and date" is fine, one that blocks an install
# or errors a shell is not.

: "${INFO:=$'\033[1;34m==>\033[0m'}"
: "${WARN:=$'\033[1;33m!!\033[0m'}"

TS_WEZ_REPO="wezterm/wezterm"
TS_WEZ_STATE="${_TS_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/terminal-stack}"
TS_WEZ_NET_TIMEOUT=5

# Map a wizard selection ("wezterm-nightly ghostty") onto the WezTerm channel, or
# empty when WezTerm was not picked. Lives here rather than in _wizard.sh so that
# every installer has it: _config.sh sources this file, _wizard.sh it does not.
ts_terminals_channel() {
    case " ${1:-} " in
        *" wezterm-nightly "*) echo nightly ;;
        *" wezterm-stable "*)  echo stable ;;
        *)                     echo "" ;;
    esac
}

# ── installed side (no network) ────────────────────────────────────────────────

# Parse a `wezterm --version` line into "version|date|hash". Pure and testable:
# the release naming is <YYYYMMDD>-<HHMMSS>-<githash>, so the build date needs no
# API call at all.
ts_wez_version_parse() {
    printf '%s\n' "${1:-}" | sed -n \
        's/^\(wezterm \)\{0,1\}\([0-9]\{8\}\)-\([0-9]\{6\}\)-\([0-9a-f]\{1,\}\).*$/\2-\3-\4|\2|\4/p'
}

# "version|date|hash", or empty when WezTerm is not installed / unparseable.
ts_wezterm_installed() {
    command -v wezterm >/dev/null 2>&1 || return 1
    local raw; raw="$(wezterm --version 2>/dev/null)" || return 1
    local parsed; parsed="$(ts_wez_version_parse "$raw")"
    [ -n "$parsed" ] || { printf '%s||\n' "${raw#wezterm }"; return 0; }
    printf '%s\n' "$parsed"
}

# YYYYMMDD -> YYYY-MM-DD, for printing.
ts_wez_fmt_date() {
    case "${1:-}" in
        [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) printf '%s-%s-%s\n' "${1:0:4}" "${1:4:2}" "${1:6:2}" ;;
        *) printf '%s\n' "${1:-}" ;;
    esac
}

# stable | nightly | unknown | none — read from the package manager, never stored.
# "unknown" means WezTerm is on PATH but no package manager here owns it (a
# hand-placed binary): report it, but never offer to upgrade or replace it.
ts_wezterm_channel() {
    if [ "$(uname -s 2>/dev/null)" = Darwin ] && command -v brew >/dev/null 2>&1; then
        brew list --cask wezterm@nightly >/dev/null 2>&1 && { echo nightly; return 0; }
        brew list --cask wezterm         >/dev/null 2>&1 && { echo stable;  return 0; }
    elif command -v dpkg >/dev/null 2>&1; then
        dpkg -s wezterm-nightly >/dev/null 2>&1 && { echo nightly; return 0; }
        dpkg -s wezterm         >/dev/null 2>&1 && { echo stable;  return 0; }
    fi
    command -v wezterm >/dev/null 2>&1 && { echo unknown; return 0; }
    echo none
}

# ── upstream side (network, fail-open) ─────────────────────────────────────────

# One place for the API call. gh is authenticated (5000 req/hr) where it exists;
# bare curl is 60/hr per IP, which a busy day can exhaust — hence the preference.
_ts_gh_api() {
    local path="$1"
    if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
        gh api "$path" 2>/dev/null && return 0
    fi
    curl -fsSL --max-time "$TS_WEZ_NET_TIMEOUT" \
        -H 'Accept: application/vnd.github+json' \
        "https://api.github.com/$path" 2>/dev/null
}

# PYTHONIOENCODING is not optional. WezTerm's changelog is full of box-drawing
# and other non-Latin-1 characters, and on Windows python3 defaults stdout to
# the ANSI code page (cp1252), where printing one raises UnicodeEncodeError and
# takes the whole tally with it. Nothing about the slice is locale-dependent, so
# the encoding is pinned rather than detected.
_ts_wez_py() { command -v python3 >/dev/null 2>&1 && PYTHONIOENCODING=utf-8 python3 "$@"; }

# "tag|YYYY-MM-DD" for the newest stable release.
ts_wezterm_latest_stable() {
    local json; json="$(_ts_gh_api "repos/$TS_WEZ_REPO/releases/latest")" || return 1
    [ -n "$json" ] || return 1
    printf '%s' "$json" | _ts_wez_py -c '
import json,sys
try: d = json.load(sys.stdin)
except Exception: raise SystemExit(1)
tag = d.get("tag_name") or ""
pub = (d.get("published_at") or "")[:10]
if not tag: raise SystemExit(1)
print(f"{tag}|{pub}")'
}

# The nightly release asset this platform would actually download. Its updated_at
# is the real build time; the release object's own published_at is stuck in 2019
# because the tag is a rolling one. Per-asset matters: the Debian10 nightly last
# built over a year ago while Debian12's built today.
ts_wez_nightly_asset_pattern() {
    case "$(uname -s 2>/dev/null)" in
        Darwin) echo '^WezTerm-macos-nightly\.zip$' ;;
        Linux)
            local id=""
            [ -r /etc/os-release ] && id="$(. /etc/os-release 2>/dev/null; echo "${ID:-}${VERSION_ID:-}")"
            case "$id" in
                ubuntu24*) echo '^wezterm-nightly\.Ubuntu24\.04\.deb$' ;;
                ubuntu22*) echo '^wezterm-nightly\.Ubuntu22\.04\.deb$' ;;
                ubuntu20*) echo '^wezterm-nightly\.Ubuntu20\.04\.deb$' ;;
                debian12*) echo '^wezterm-nightly\.Debian12\.deb$' ;;
                debian11*) echo '^wezterm-nightly\.Debian11\.deb$' ;;
                *)         echo '^wezterm-nightly\.Debian12\.deb$' ;;
            esac ;;
        *) echo '^WezTerm-nightly-setup\.exe$' ;;
    esac
}

# "YYYY-MM-DD" for this platform's newest nightly build.
ts_wezterm_latest_nightly() {
    local json; json="$(_ts_gh_api "repos/$TS_WEZ_REPO/releases/tags/nightly")" || return 1
    [ -n "$json" ] || return 1
    printf '%s' "$json" | TS_WEZ_PAT="$(ts_wez_nightly_asset_pattern)" _ts_wez_py -c '
import json,os,re,sys
try: d = json.load(sys.stdin)
except Exception: raise SystemExit(1)
pat = re.compile(os.environ.get("TS_WEZ_PAT", "nightly"))
best = ""
for a in d.get("assets", []):
    if pat.match(a.get("name","")):
        best = max(best, (a.get("updated_at") or "")[:10])
if not best:   # unknown platform asset: fall back to the freshest asset overall
    for a in d.get("assets", []):
        best = max(best, (a.get("updated_at") or "")[:10])
if not best: raise SystemExit(1)
print(best)'
}

# ── what changed (upstream changelog, no LLM) ──────────────────────────────────

# Upstream keeps a curated docs/changelog.md whose release headings are exactly
# the version strings wezterm --version prints, so the slice is an exact match
# rather than a guess. Fetched from raw.githubusercontent.com, which has no API
# rate limit, and cached because it is ~225 KB.
ts_wez_changelog_path() { printf '%s/wezterm-changelog.md\n' "$TS_WEZ_STATE"; }

ts_wez_changelog_fetch() {
    local f; f="$(ts_wez_changelog_path)"
    # Re-fetch at most once an hour; a stale copy beats no copy.
    if [ -s "$f" ] && [ -z "${TS_WEZ_FORCE_FETCH:-}" ]; then
        local age; age="$(_ts_wez_py -c "
import os,time,sys
try: print(int(time.time() - os.path.getmtime(sys.argv[1])))
except Exception: print(999999)" "$f" 2>/dev/null || echo 999999)"
        [ "${age:-999999}" -lt 3600 ] 2>/dev/null && { printf '%s\n' "$f"; return 0; }
    fi
    mkdir -p "$TS_WEZ_STATE" 2>/dev/null || true
    if curl -fsSL --max-time "$TS_WEZ_NET_TIMEOUT" \
        "https://raw.githubusercontent.com/$TS_WEZ_REPO/main/docs/changelog.md" \
        -o "$f.tmp" 2>/dev/null && [ -s "$f.tmp" ]; then
        mv -f "$f.tmp" "$f"
    else
        rm -f "$f.tmp" 2>/dev/null || true
    fi
    [ -s "$f" ] || return 1
    printf '%s\n' "$f"
}

# Everything newer than <version>: the release sections above its heading, plus
# the accumulating "Continuous/Nightly" section. Prints the markdown slice.
ts_wez_changes_text() {
    local version="${1:-}" f
    f="$(ts_wez_changelog_fetch)" || return 1
    TS_WEZ_VER="$version" _ts_wez_py -c '
import os,sys
ver = os.environ.get("TS_WEZ_VER","")
lines = open(sys.argv[1], encoding="utf-8").read().splitlines()
start = None
for i, l in enumerate(lines):
    if l.startswith("## Changes"):
        start = i + 1
        break
if start is None: raise SystemExit(1)
end = len(lines)
if ver:
    for i in range(start, len(lines)):
        if lines[i].startswith("### ") and ver in lines[i]:
            end = i
            break
out = [l for l in lines[start:end]]
while out and not out[0].strip(): out.pop(0)
while out and not out[-1].strip(): out.pop()
print("\n".join(out))' "$f"
}

# One-line tally: "Changed 22  New 30  Fixed 60  Updated 8". Empty when the
# changelog is unavailable or nothing is newer.
ts_wez_changes_tally() {
    local text; text="$(ts_wez_changes_text "${1:-}")" || return 1
    printf '%s' "$text" | _ts_wez_py -c '
import re,sys
section = None
counts = {}
order = []
for line in sys.stdin.read().splitlines():
    m = re.match(r"^#### +(.+?)\s*$", line)
    if m:
        section = m.group(1)
        if section not in counts:
            counts[section] = 0
            order.append(section)
        continue
    if section and re.match(r"^\* ", line):
        counts[section] += 1
parts = [f"{s} {counts[s]}" for s in order if counts[s]]
if parts: print("  ".join(parts))'
}

# Commits between the installed build and upstream main. The changelog cannot
# anchor a nightly (only stable releases get a heading), so the commit count is
# the honest answer there.
ts_wez_commits_since() {
    local hash="${1:-}"
    [ -n "$hash" ] || return 1
    local json; json="$(_ts_gh_api "repos/$TS_WEZ_REPO/compare/$hash...main")" || return 1
    [ -n "$json" ] || return 1
    printf '%s' "$json" | _ts_wez_py -c '
import json,sys
try: d = json.load(sys.stdin)
except Exception: raise SystemExit(1)
n = d.get("total_commits")
if not n: raise SystemExit(1)
print(n)'
}

# ── the report ─────────────────────────────────────────────────────────────────

# Multi-line status block. Never fails: with no network it still prints the
# installed build and its date, which is the part that always works.
ts_wezterm_status() {
    local inst ver date hash channel
    inst="$(ts_wezterm_installed 2>/dev/null || true)"
    channel="$(ts_wezterm_channel)"
    ver="${inst%%|*}"; date="$(printf '%s' "$inst" | cut -d'|' -f2)"; hash="${inst##*|}"

    echo "$INFO WezTerm"
    if [ -z "$inst" ]; then
        echo "    Installed : not installed"
    else
        printf '    Installed : %s' "$ver"
        [ -n "$date" ] && printf '  (%s, %s)' "$channel" "$(ts_wez_fmt_date "$date")"
        printf '\n'
        [ "$channel" = unknown ] && \
            echo "                not from a package manager here — left alone by install/upgrade"
    fi

    local st ni
    st="$(ts_wezterm_latest_stable 2>/dev/null || true)"
    ni="$(ts_wezterm_latest_nightly 2>/dev/null || true)"
    if [ -z "$st" ] && [ -z "$ni" ]; then
        echo "    Latest    : (offline — could not reach GitHub)"
        return 0
    fi
    [ -n "$ni" ] && echo "    nightly   : built $ni"
    if [ -n "$st" ]; then
        local stag sdate; stag="${st%%|*}"; sdate="${st##*|}"
        printf '    stable    : %s  (%s)' "$stag" "$sdate"
        [ "$stag" = "$ver" ] && printf '  — you are on it'
        printf '\n'
    fi

    # What changed since this build.
    if [ -n "$ver" ]; then
        local tally commits
        tally="$(ts_wez_changes_tally "$ver" 2>/dev/null || true)"
        commits="$(ts_wez_commits_since "$hash" 2>/dev/null || true)"
        if [ -n "$commits" ] || [ -n "$tally" ]; then
            printf '    Since your build:'
            [ -n "$commits" ] && printf ' %s commits' "$commits"
            [ -n "$commits" ] && [ -n "$tally" ] && printf ' —'
            [ -n "$tally" ] && printf ' %s' "$tally"
            printf '\n'
            [ -n "$tally" ] && echo "    Full notes: tstack config wezterm changes"
        fi
    fi
}

# A single compact line for the wizard prompt's intro. Empty when there is
# nothing useful to say.
ts_wezterm_prompt_intro() {
    local inst ver channel st ni out=""
    inst="$(ts_wezterm_installed 2>/dev/null || true)"
    channel="$(ts_wezterm_channel)"
    ver="${inst%%|*}"
    if [ -n "$inst" ]; then
        local date; date="$(printf '%s' "$inst" | cut -d'|' -f2)"
        out="  Installed: WezTerm $ver"
        [ -n "$date" ] && out="$out ($channel, $(ts_wez_fmt_date "$date"))"
    fi
    st="$(ts_wezterm_latest_stable 2>/dev/null || true)"
    ni="$(ts_wezterm_latest_nightly 2>/dev/null || true)"
    if [ -n "$st" ] || [ -n "$ni" ]; then
        local line="  Latest:   "
        [ -n "$ni" ] && line="$line nightly built $ni"
        [ -n "$st" ] && [ -n "$ni" ] && line="$line  |"
        [ -n "$st" ] && line="$line stable ${st%%|*} (${st##*|})"
        out="${out:+$out
}$line"
    fi
    if [ -n "$ver" ]; then
        local tally; tally="$(ts_wez_changes_tally "$ver" 2>/dev/null || true)"
        [ -n "$tally" ] && out="${out:+$out
}  Since your build: $tally"
    fi
    printf '%s\n' "$out"
}

# ── install / switch channel ───────────────────────────────────────────────────
# Switching channel means REMOVING the other one first, in both directions: on
# macOS both casks own /Applications/WezTerm.app so the second install refuses,
# and on Debian the two packages conflict over /usr/bin/wezterm.

_ts_wez_brew_install() {
    local want="$1" other="$2" want_name="$3"
    if brew list --cask "$other" >/dev/null 2>&1; then
        echo "$INFO WezTerm: removing the $other cask (switching channel)"
        brew uninstall --cask --force "$other" \
            || echo "$WARN could not remove $other; remove it by hand."
    fi
    if brew list --cask "$want" >/dev/null 2>&1; then
        echo "$INFO WezTerm ($want_name): installed; checking for an upgrade"
        brew upgrade --cask "$want" 2>/dev/null || echo "$INFO WezTerm ($want_name): already at the latest."
    else
        echo "$INFO WezTerm ($want_name): installing"
        brew install --cask "$want" || echo "$WARN WezTerm install failed; install it by hand later."
    fi
}

_ts_wez_apt_install() {
    local want="$1" other="$2"
    if [ ! -s /etc/apt/keyrings/wezterm-fury.gpg ]; then
        echo "$INFO WezTerm: adding the upstream apt repo"
        command -v gpg >/dev/null 2>&1 || sudo apt-get install -y gnupg >/dev/null 2>&1 || true
        sudo mkdir -p /etc/apt/keyrings
        curl -fsSL https://apt.fury.io/wez/gpg.key \
            | sudo gpg --dearmor -o /etc/apt/keyrings/wezterm-fury.gpg \
            || { echo "$WARN WezTerm: could not fetch the repo key; skipping."; return 0; }
    fi
    local list=/etc/apt/sources.list.d/wezterm.list
    local line='deb [signed-by=/etc/apt/keyrings/wezterm-fury.gpg] https://apt.fury.io/wez/ * *'
    if [ ! -f "$list" ] || ! grep -qF "$line" "$list" 2>/dev/null; then
        printf '%s\n' "$line" | sudo tee "$list" >/dev/null
    fi
    sudo apt-get update -qq
    if dpkg -s "$other" >/dev/null 2>&1; then
        echo "$INFO WezTerm: removing $other (switching channel)"
        sudo apt-get purge -y "$other" >/dev/null 2>&1 \
            || echo "$WARN could not remove $other; remove it by hand."
    fi
    if sudo apt-get install -y "$want" >/dev/null 2>&1; then
        echo "$INFO WezTerm: $(wezterm --version 2>/dev/null || echo installed)"
    else
        echo "$WARN WezTerm: apt install failed; see https://wezterm.org/install/linux.html"
    fi
}

# ts_wezterm_install <stable|nightly>
ts_wezterm_install() {
    local channel="${1:-}"
    case "$channel" in stable|nightly) ;; *)
        echo "ts_wezterm_install: expected stable|nightly" >&2; return 2 ;;
    esac
    # A hand-placed binary is not ours to replace.
    if [ "$(ts_wezterm_channel)" = unknown ]; then
        echo "$INFO WezTerm: installed outside a package manager ($(command -v wezterm)); leaving it alone."
        return 0
    fi
    if [ "$(uname -s 2>/dev/null)" = Darwin ]; then
        command -v brew >/dev/null 2>&1 || { echo "$WARN WezTerm: brew not found."; return 0; }
        case "$channel" in
            nightly) _ts_wez_brew_install wezterm@nightly wezterm         nightly ;;
            stable)  _ts_wez_brew_install wezterm         wezterm@nightly stable  ;;
        esac
    elif command -v apt-get >/dev/null 2>&1; then
        case "$channel" in
            nightly) _ts_wez_apt_install wezterm-nightly wezterm         ;;
            stable)  _ts_wez_apt_install wezterm         wezterm-nightly ;;
        esac
    else
        echo "$INFO WezTerm: no supported package manager here; see https://wezterm.org/install"
    fi
}

# Refresh whatever channel is already installed. Never switches.
ts_wezterm_upgrade() {
    local channel; channel="$(ts_wezterm_channel)"
    case "$channel" in
        stable|nightly) ts_wezterm_install "$channel" ;;
        unknown) echo "$INFO WezTerm: installed outside a package manager; upgrade it the way you installed it." ;;
        *)       echo "$INFO WezTerm: not installed. 'tstack config wezterm install nightly' to add it." ;;
    esac
}

# Is there something newer than the installed build on its own channel? Prints a
# one-line reason when yes, nothing when no / unknown / offline. This is what
# tstack update gates its offer on, so silence is the common case.
ts_wezterm_update_available() {
    local inst channel ver date
    inst="$(ts_wezterm_installed 2>/dev/null || true)"
    [ -n "$inst" ] || return 1
    channel="$(ts_wezterm_channel)"
    ver="${inst%%|*}"; date="$(printf '%s' "$inst" | cut -d'|' -f2)"
    case "$channel" in
        stable)
            local st; st="$(ts_wezterm_latest_stable 2>/dev/null || true)"
            [ -n "$st" ] || return 1
            [ "${st%%|*}" = "$ver" ] && return 1
            printf 'stable %s (%s) is newer than your %s\n' "${st%%|*}" "${st##*|}" "$ver" ;;
        nightly)
            local ni built; ni="$(ts_wezterm_latest_nightly 2>/dev/null || true)"
            [ -n "$ni" ] || return 1
            built="$(printf '%s' "$ni" | tr -d '-')"
            [ -n "$date" ] || return 1
            [ "$built" -gt "$date" ] 2>/dev/null || return 1
            printf 'a nightly built %s is newer than your %s build\n' "$ni" "$(ts_wez_fmt_date "$date")" ;;
        *) return 1 ;;
    esac
}
