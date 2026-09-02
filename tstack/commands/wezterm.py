"""`tstack wezterm` - which WezTerm you have, what upstream has, what changed.

Replaces bootstrap/ts-wezterm.sh (90 lines) and the whole of bootstrap/_wezterm.sh
(446), which was already half Python: five of its functions existed only to pipe
JSON into an embedded `python3 -c` heredoc. bootstrap/_wezterm.sh survives as a
thin set of shims that call this, because the installers source it before this
package is reachable and are not part of this port.

WezTerm publishes two channels and the stack installs NEITHER automatically: the
wizard asks, `tstack update` offers, this command changes it on demand. Upstream's
newest stable is 20240203 (February 2024, no cut since), which is why nightly is
the pre-selected answer rather than the forced one.

The channel is NOT a saved setting. It is read back from the package manager
(brew cask / dpkg package), which cannot drift out of sync with reality the way a
stored value can. See docs/decisions.md.

Everything that touches the network fails OPEN and SILENT: a report that degrades
to "installed version and date" is fine; one that blocks an install or errors a
shell is not.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import platform as plat
from .. import proc

HELP = """tstack wezterm - WezTerm build info, upstream comparison, channel switching.

Usage:
  tstack wezterm [status]        the installed build + date, the latest per channel, what changed
  tstack wezterm changes         the full upstream changelog since your build (paged)
  tstack wezterm install <chan>  stable | nightly - switches channel, removing the other
  tstack wezterm upgrade         refresh the channel you are already on; never switches
  tstack wezterm -h              this help

Release names are <date>-<time>-<githash>, so the build date comes from
`wezterm --version` with no network call. Latest-stable comes from the GitHub
release; latest-nightly is the build date of the nightly asset for THIS platform,
because the nightly tag is a rolling one whose own date is meaningless and whose
assets are rebuilt per platform at different times.

"What changed" is sliced out of upstream's own docs/changelog.md by a heading
matching your version - no summarising, just the notes and a count. Nothing runs
on its own: installs and channel switches only happen when you ask for them."""

REPO = "wezterm/wezterm"
NET_TIMEOUT = 5
INFO = "==>"
WARN = "!!"

_VERSION = re.compile(r"^(?:wezterm )?([0-9]{8})-([0-9]{6})-([0-9a-f]+)")


# ------------------------------------------------------------- installed side


def version_parse(raw: str) -> tuple[str, str, str] | None:
    """(version, date, hash) out of a `wezterm --version` line.

    PURE and testable: the release naming is <YYYYMMDD>-<HHMMSS>-<githash>, so the
    build date needs no API call at all.
    """
    found = _VERSION.match((raw or "").strip())
    if not found:
        return None
    date, clock, commit = found.groups()
    return (f"{date}-{clock}-{commit}", date, commit)


def installed() -> tuple[str, str, str] | None:
    """(version, date, hash), or None when WezTerm is not installed.

    An unparseable version still reports the raw string: a hand-built WezTerm is
    something to name, not something to hide.
    """
    binary = shutil.which("wezterm")
    if not binary:
        return None
    got = _run([binary, "--version"], timeout=10)
    if not got or got.returncode != 0:
        return None
    raw = got.stdout.strip()
    parsed = version_parse(raw)
    if parsed:
        return parsed
    return (raw.removeprefix("wezterm "), "", "")


def fmt_date(value: str) -> str:
    """YYYYMMDD -> YYYY-MM-DD, for printing."""
    if len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def channel() -> str:
    """stable | nightly | unknown | none, read from the package manager.

    "unknown" means WezTerm is on PATH but no package manager here owns it (a
    hand-placed binary): report it, but never offer to upgrade or replace it.
    """
    if plat.kind() == plat.MACOS and shutil.which("brew"):
        for cask, name in (("wezterm@nightly", "nightly"), ("wezterm", "stable")):
            got = _run(["brew", "list", "--cask", cask], timeout=60)
            if got and got.returncode == 0:
                return name
    elif shutil.which("dpkg"):
        for package, name in (("wezterm-nightly", "nightly"), ("wezterm", "stable")):
            got = _run(["dpkg", "-s", package], timeout=30)
            if got and got.returncode == 0:
                return name
    return "unknown" if shutil.which("wezterm") else "none"


def terminals_channel(selection: str) -> str:
    """A wizard selection ("wezterm-nightly ghostty") -> the WezTerm channel."""
    words = f" {selection or ''} "
    if " wezterm-nightly " in words:
        return "nightly"
    if " wezterm-stable " in words:
        return "stable"
    return ""


def _run(argv: list[str], timeout: int = 30) -> subprocess.CompletedProcess | None:
    return proc.capture(argv, timeout=timeout)


# --------------------------------------------------------- upstream (network)


def _gh_api(path: str) -> dict | list | None:
    """One place for the API call, failing open.

    gh is authenticated (5000 req/hr) where it exists; bare curl is 60/hr per IP,
    which a busy day can exhaust - hence the preference.
    """
    if shutil.which("gh"):
        auth = _run(["gh", "auth", "status"], timeout=NET_TIMEOUT + 5)
        if auth and auth.returncode == 0:
            got = _run(["gh", "api", path], timeout=NET_TIMEOUT + 10)
            if got and got.returncode == 0:
                try:
                    return json.loads(got.stdout)
                except ValueError:
                    return None
    request = urllib.request.Request(
        f"https://api.github.com/{path}", headers={"Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=NET_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def latest_stable() -> tuple[str, str] | None:
    """(tag, YYYY-MM-DD) for the newest stable release."""
    body = _gh_api(f"repos/{REPO}/releases/latest")
    if not isinstance(body, dict):
        return None
    tag = body.get("tag_name") or ""
    if not tag:
        return None
    return (tag, (body.get("published_at") or "")[:10])


def nightly_asset_pattern() -> re.Pattern[str]:
    """The nightly asset THIS platform would actually download.

    Per-asset matters: the Debian10 nightly last built over a year ago while
    Debian12's built today, and the release object's own published_at is stuck in
    2019 because the tag is a rolling one.
    """
    if plat.kind() == plat.MACOS:
        return re.compile(r"^WezTerm-macos-nightly\.zip$")
    if plat.kind() == plat.WINDOWS:
        return re.compile(r"^WezTerm-nightly-setup\.exe$")
    ident = ""
    try:
        for line in Path("/etc/os-release").read_text(encoding="utf-8").splitlines():
            if line.startswith("ID="):
                ident = line.split("=", 1)[1].strip().strip('"') + ident
            elif line.startswith("VERSION_ID="):
                ident += line.split("=", 1)[1].strip().strip('"')
    except OSError:
        ident = ""
    table = {
        "ubuntu24": r"^wezterm-nightly\.Ubuntu24\.04\.deb$",
        "ubuntu22": r"^wezterm-nightly\.Ubuntu22\.04\.deb$",
        "ubuntu20": r"^wezterm-nightly\.Ubuntu20\.04\.deb$",
        "debian12": r"^wezterm-nightly\.Debian12\.deb$",
        "debian11": r"^wezterm-nightly\.Debian11\.deb$",
    }
    for prefix, pattern in table.items():
        if ident.startswith(prefix):
            return re.compile(pattern)
    return re.compile(r"^wezterm-nightly\.Debian12\.deb$")


def latest_nightly() -> str | None:
    """YYYY-MM-DD for this platform's newest nightly build."""
    body = _gh_api(f"repos/{REPO}/releases/tags/nightly")
    if not isinstance(body, dict):
        return None
    pattern = nightly_asset_pattern()
    assets = body.get("assets") or []
    best = ""
    for asset in assets:
        if pattern.match(asset.get("name", "")):
            best = max(best, (asset.get("updated_at") or "")[:10])
    if not best:
        # Unknown platform asset: fall back to the freshest asset overall.
        for asset in assets:
            best = max(best, (asset.get("updated_at") or "")[:10])
    return best or None


# ------------------------------------------------------------- what changed


def state_dir() -> Path:
    override = os.environ.get("_TS_STATE")
    if override:
        return Path(override)
    return plat.state_dir()


def changelog_path() -> Path:
    return state_dir() / "wezterm-changelog.md"


def changelog_fetch() -> Path | None:
    """Upstream's docs/changelog.md, cached.

    From raw.githubusercontent.com, which has no API rate limit, and cached
    because it is ~225 KB. Re-fetched at most once an hour: a stale copy beats no
    copy, which is the whole failure mode of a network call in a status command.
    """
    target = changelog_path()
    fresh = (
        target.is_file()
        and target.stat().st_size
        and not os.environ.get("TS_WEZ_FORCE_FETCH")
        and time.time() - target.stat().st_mtime < 3600
    )
    if fresh:
        return target
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        url = f"https://raw.githubusercontent.com/{REPO}/main/docs/changelog.md"
        with urllib.request.urlopen(url, timeout=NET_TIMEOUT) as response:
            body = response.read()
        if body:
            tmp = target.with_suffix(".md.tmp")
            tmp.write_bytes(body)
            tmp.replace(target)
    except (urllib.error.URLError, OSError, ValueError):
        pass
    if target.is_file() and target.stat().st_size:
        return target
    return None


def changes_text(version: str) -> str | None:
    """Everything newer than `version`.

    Upstream's release headings are exactly the strings `wezterm --version`
    prints, so the slice is an exact match rather than a guess: the sections above
    that heading, plus the accumulating Continuous/Nightly section.
    """
    path = changelog_fetch()
    if not path:
        return None
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    start = next((i + 1 for i, line in enumerate(lines) if line.startswith("## Changes")), None)
    if start is None:
        return None
    end = len(lines)
    if version:
        for i in range(start, len(lines)):
            if lines[i].startswith("### ") and version in lines[i]:
                end = i
                break
    out = lines[start:end]
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out)


def changes_tally(version: str) -> str:
    """One line: "Changed 22  New 30  Fixed 60". Empty when there is nothing."""
    text = changes_text(version)
    if not text:
        return ""
    counts: dict[str, int] = {}
    order: list[str] = []
    section = None
    for line in text.splitlines():
        heading = re.match(r"^#### +(.+?)\s*$", line)
        if heading:
            section = heading.group(1)
            if section not in counts:
                counts[section] = 0
                order.append(section)
            continue
        if section and line.startswith("* "):
            counts[section] += 1
    return "  ".join(f"{s} {counts[s]}" for s in order if counts[s])


def commits_since(commit: str) -> int | None:
    """Commits between the installed build and upstream main.

    The changelog cannot anchor a nightly (only stable releases get a heading), so
    the commit count is the honest answer there.
    """
    if not commit:
        return None
    body = _gh_api(f"repos/{REPO}/compare/{commit}...main")
    if not isinstance(body, dict):
        return None
    total = body.get("total_commits")
    return int(total) if total else None


# -------------------------------------------------------------- the report


def status() -> int:
    """Never fails: with no network it still prints the installed build and date,
    which is the part that always works."""
    got = installed()
    chan = channel()
    print(f"{INFO} WezTerm")
    if not got:
        print("    Installed : not installed")
        version = date = commit = ""
    else:
        version, date, commit = got
        line = f"    Installed : {version}"
        if date:
            line += f"  ({chan}, {fmt_date(date)})"
        print(line)
        if chan == "unknown":
            print("                not from a package manager here - left alone by install/upgrade")

    stable = latest_stable()
    nightly = latest_nightly()
    if not stable and not nightly:
        print("    Latest    : (offline - could not reach GitHub)")
        return 0
    if nightly:
        print(f"    nightly   : built {nightly}")
    if stable:
        tag, published = stable
        line = f"    stable    : {tag}  ({published})"
        if tag == version:
            line += "  - you are on it"
        print(line)

    if version:
        tally = changes_tally(version)
        commits = commits_since(commit)
        if commits or tally:
            line = "    Since your build:"
            if commits:
                line += f" {commits} commits"
            if commits and tally:
                line += " -"
            if tally:
                line += f" {tally}"
            print(line)
            if tally:
                print("    Full notes: tstack wezterm changes")
    return 0


def prompt_intro() -> str:
    """The compact block the wizard prints above the channel question."""
    lines = []
    got = installed()
    chan = channel()
    version = got[0] if got else ""
    if got:
        line = f"  Installed: WezTerm {got[0]}"
        if got[1]:
            line += f" ({chan}, {fmt_date(got[1])})"
        lines.append(line)
    stable = latest_stable()
    nightly = latest_nightly()
    if stable or nightly:
        line = "  Latest:   "
        if nightly:
            line += f" nightly built {nightly}"
        if stable and nightly:
            line += "  |"
        if stable:
            line += f" stable {stable[0]} ({stable[1]})"
        lines.append(line)
    if version:
        tally = changes_tally(version)
        if tally:
            lines.append(f"  Since your build: {tally}")
    return "\n".join(lines)


def show_changes() -> int:
    got = installed()
    if not got or not got[0]:
        print(
            "tstack wezterm: WezTerm is not installed, so there is no build to compare against.",
            file=sys.stderr,
        )
        return 1
    text = changes_text(got[0])
    if text is None:
        print("tstack wezterm: could not fetch upstream's changelog (offline?).", file=sys.stderr)
        return 1
    if not text:
        print(f"{INFO} Nothing newer than {got[0]} in upstream's changelog.")
        return 0
    body = f"# WezTerm changes since {got[0]}\n\n{text}\n"
    # The same reader the `doc` knowledge base uses, so long output behaves the
    # same way everywhere in the stack.
    if shutil.which("glow") and proc.feed(["glow", "-p", "-"], body) == 0:
        return 0
    pager = os.environ.get("PAGER") or "less -RF"
    if proc.feed(pager.split(), body) != 0:
        print(body)
    return 0


# ------------------------------------------------------- install / switch


def _brew_install(want: str, other: str, label: str) -> None:
    got = _run(["brew", "list", "--cask", other], timeout=60)
    if got and got.returncode == 0:
        print(f"{INFO} WezTerm: removing the {other} cask (switching channel)")
        removed = _run(["brew", "uninstall", "--cask", "--force", other], timeout=600)
        if not removed or removed.returncode != 0:
            print(f"{WARN} could not remove {other}; remove it by hand.")
    got = _run(["brew", "list", "--cask", want], timeout=60)
    if got and got.returncode == 0:
        print(f"{INFO} WezTerm ({label}): installed; checking for an upgrade")
        upgraded = _run(["brew", "upgrade", "--cask", want], timeout=1800)
        if not upgraded or upgraded.returncode != 0:
            print(f"{INFO} WezTerm ({label}): already at the latest.")
    else:
        print(f"{INFO} WezTerm ({label}): installing")
        added = _run(["brew", "install", "--cask", want], timeout=1800)
        if not added or added.returncode != 0:
            print(f"{WARN} WezTerm install failed; install it by hand later.")


def _apt_install(want: str, other: str) -> None:
    keyring = Path("/etc/apt/keyrings/wezterm-fury.gpg")
    if not (keyring.is_file() and keyring.stat().st_size):
        print(f"{INFO} WezTerm: adding the upstream apt repo")
        if not shutil.which("gpg"):
            _run(["sudo", "apt-get", "install", "-y", "gnupg"], timeout=600)
        _run(["sudo", "mkdir", "-p", "/etc/apt/keyrings"], timeout=30)
        # curl | gpg | tee, kept as a shell pipeline because that is what it is.
        added = subprocess.run(
            "curl -fsSL https://apt.fury.io/wez/gpg.key "
            "| sudo gpg --dearmor -o /etc/apt/keyrings/wezterm-fury.gpg",
            shell=True,
            check=False,
            start_new_session=True,
        )
        if added.returncode != 0:
            print(f"{WARN} WezTerm: could not fetch the repo key; skipping.")
            return
    listing = Path("/etc/apt/sources.list.d/wezterm.list")
    line = "deb [signed-by=/etc/apt/keyrings/wezterm-fury.gpg] https://apt.fury.io/wez/ * *"
    try:
        current = listing.read_text(encoding="utf-8") if listing.is_file() else ""
    except OSError:
        current = ""
    if line not in current:
        proc.capture(["sudo", "tee", str(listing)], stdin=line + "\n", timeout=60)
    _run(["sudo", "apt-get", "update", "-qq"], timeout=600)
    got = _run(["dpkg", "-s", other], timeout=30)
    if got and got.returncode == 0:
        print(f"{INFO} WezTerm: removing {other} (switching channel)")
        removed = _run(["sudo", "apt-get", "purge", "-y", other], timeout=600)
        if not removed or removed.returncode != 0:
            print(f"{WARN} could not remove {other}; remove it by hand.")
    done = _run(["sudo", "apt-get", "install", "-y", want], timeout=1800)
    if done and done.returncode == 0:
        version = installed()
        print(f"{INFO} WezTerm: {version[0] if version else 'installed'}")
    else:
        print(f"{WARN} WezTerm: apt install failed; see https://wezterm.org/install/linux.html")


def install(want: str) -> int:
    """Switching channel means REMOVING the other one first, in both directions:
    on macOS both casks own /Applications/WezTerm.app so the second install
    refuses, and on Debian the two packages conflict over /usr/bin/wezterm."""
    if want not in ("stable", "nightly"):
        print("usage: tstack wezterm install <stable|nightly>", file=sys.stderr)
        return 2
    # A hand-placed binary is not ours to replace.
    if channel() == "unknown":
        print(
            f"{INFO} WezTerm: installed outside a package manager "
            f"({shutil.which('wezterm')}); leaving it alone."
        )
        return 0
    if plat.kind() == plat.MACOS:
        if not shutil.which("brew"):
            print(f"{WARN} WezTerm: brew not found.")
            return 0
        if want == "nightly":
            _brew_install("wezterm@nightly", "wezterm", "nightly")
        else:
            _brew_install("wezterm", "wezterm@nightly", "stable")
    elif shutil.which("apt-get"):
        if want == "nightly":
            _apt_install("wezterm-nightly", "wezterm")
        else:
            _apt_install("wezterm", "wezterm-nightly")
    else:
        print(f"{INFO} WezTerm: no supported package manager here; see https://wezterm.org/install")
    return 0


def upgrade() -> int:
    """Refresh whatever channel is already installed. Never switches."""
    chan = channel()
    if chan in ("stable", "nightly"):
        return install(chan)
    if chan == "unknown":
        print(
            f"{INFO} WezTerm: installed outside a package manager; "
            "upgrade it the way you installed it."
        )
    else:
        print(f"{INFO} WezTerm: not installed. 'tstack wezterm install nightly' to add it.")
    return 0


def update_available() -> str:
    """A one-line reason when something newer exists on the installed channel.

    Empty otherwise, including offline and "unknown channel". `tstack update`
    gates its offer on this, so silence is the common case.
    """
    got = installed()
    if not got:
        return ""
    version, date, _ = got
    chan = channel()
    if chan == "stable":
        stable = latest_stable()
        if not stable or stable[0] == version:
            return ""
        return f"stable {stable[0]} ({stable[1]}) is newer than your {version}"
    if chan == "nightly":
        nightly = latest_nightly()
        if not nightly or not date:
            return ""
        if nightly.replace("-", "") <= date:
            return ""
        return f"a nightly built {nightly} is newer than your {fmt_date(date)} build"
    return ""


# ----------------------------------------------------------------- entry point


def main(argv: list[str]) -> int:
    command = argv[0] if argv else "status"
    if command in ("-h", "--help", "help"):
        print(HELP)
        return 0
    if command in ("", "status"):
        return status()
    if command == "changes":
        return show_changes()
    if command == "install":
        return install(argv[1] if len(argv) > 1 else "")
    if command == "upgrade":
        return upgrade()
    # Machine-readable verbs, for the shell that has not been ported yet
    # (_wezterm.sh's shims, the wizard, `tstack update`). Deliberately terse and
    # deliberately silent when there is no answer: every caller treats empty as
    # "nothing to say" and none of them may fail a shell.
    if command == "channel":
        print(channel())
        return 0
    if command == "installed":
        got = installed()
        if not got:
            return 1
        print("|".join(got))
        return 0
    if command == "update-available":
        line = update_available()
        if not line:
            return 1
        print(line)
        return 0
    if command == "intro":
        print(prompt_intro())
        return 0
    if command == "terminals-channel":
        print(terminals_channel(argv[1] if len(argv) > 1 else ""))
        return 0
    print(
        f"tstack wezterm: unknown command '{command}' (try: status, changes, install, upgrade, -h)",
        file=sys.stderr,
    )
    return 2
