"""Mobile bottom nav must not cover the end of long pages (body is only 100vh tall)."""
from __future__ import annotations

import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1] / "static" / "style.css").read_text(encoding="utf-8")


def test_layout_reserves_bottom_nav_clearance_on_mobile():
    m = re.search(
        r"@media \(max-width: 768px\)\{.*?\.gc-body-ingame \.gc-layout\{\s*"
        r"padding-bottom: calc\(var\(--gc-bottom-nav-h\) \+ var\(--gc-safe-bottom\) \+ 12px\);",
        CSS,
        re.S,
    )
    assert m, ".gc-body-ingame .gc-layout must reserve nav height + safe area + gap at <=768px"
