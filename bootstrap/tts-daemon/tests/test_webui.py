"""The dashboard page is a constant, so the things it depends on can be asserted cheaply."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ttsd.webui import PAGE


def test_the_page_is_self_contained():
    """No CDN, no external font, no remote anything: the daemon serves this offline."""
    remote = re.findall(r"""(?:src|href)\s*=\s*["']https?://[^"']+""", PAGE)
    assert remote == [], remote
    assert "cdn" not in PAGE.lower()


def test_every_element_the_script_touches_exists():
    """A renamed id would fail silently in the browser; catch it here instead."""
    referenced = set(re.findall(r"""\$\(['"]([\w-]+)['"]\)""", PAGE))
    declared = set(re.findall(r'''id="([\w-]+)"''', PAGE))
    missing = sorted(referenced - declared)
    assert missing == [], missing


def test_it_talks_only_to_routes_the_server_serves():
    from ttsd import server

    source = Path(server.__file__).read_text(encoding="utf-8")
    for path in sorted(set(re.findall(r"""['"](/v1/[\w/]+)""", PAGE))):
        assert path in source, f"the page calls {path} but the server never mentions it"


def test_the_empty_timeline_does_not_claim_all_is_well():
    """history fails open and returns [], so an empty result is ambiguous by design."""
    assert "history database is unreadable" in PAGE


def test_the_three_tabs_are_present():
    for tab in ("status", "timeline", "log"):
        assert f'data-tab="{tab}"' in PAGE
