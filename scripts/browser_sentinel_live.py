#!/usr/bin/env python3
"""Production-safe Genesis Sentinel runner.

This wrapper deliberately disables every presentation-control click before
running the existing Sentinel in live mode. The live journey is therefore
limited to the real login flow plus authenticated GET navigation, DOM/UI
inspection, screenshots and runtime/network observation.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import browser_sentinel as sentinel  # noqa: E402

_ALLOWED_HOSTS = {"genesis-colonies.com", "www.genesis-colonies.com"}


def _validate_target() -> None:
    raw = os.environ.get("GC_SENTINEL_BASE_URL", "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in _ALLOWED_HOSTS:
        raise SystemExit(
            "FAIL: production Sentinel target must be HTTPS genesis-colonies.com"
        )


def _disable_live_click_probes() -> None:
    # Defense in depth: browser_sentinel's normal presentation-tab probes are
    # useful in disposable sandbox mode, but production Sentinel must never
    # click authenticated game controls.
    sentinel._probe_safe_controls = lambda page: []


def main() -> int:
    _validate_target()
    _disable_live_click_probes()
    sys.argv = [
        "browser_sentinel_live.py",
        "--mode",
        "live",
        "--artifacts",
        "artifacts/browser-live",
        "--fail-on",
        "none",
        "--route",
        "/overview",
    ]
    return sentinel.main()


if __name__ == "__main__":
    raise SystemExit(main())
