#!/usr/bin/env python3
"""CLI: raise inactive players' storage buildings to at least target level (default 15)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.admin_api import INACTIVE_STORAGE_TARGET_LEVEL, apply_inactive_storage_boost


def main() -> int:
    parser = argparse.ArgumentParser(description="Boost inactive player storage buildings")
    parser.add_argument(
        "--target-level",
        type=int,
        default=INACTIVE_STORAGE_TARGET_LEVEL,
        help=f"Minimum storage level (default {INACTIVE_STORAGE_TARGET_LEVEL})",
    )
    args = parser.parse_args()
    payload = apply_inactive_storage_boost(target_level=int(args.target_level))
    print(payload)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
