#!/usr/bin/env python3
"""GC-555 — enrich asset report with WebP sibling sizes."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT = ROOT / "docs" / "GC-555_asset_report.json"


def main() -> None:
    rows = json.loads(REPORT.read_text(encoding="utf-8"))
    for row in rows:
        src = ROOT / row["path"]
        webp = src.with_suffix(".webp")
        if webp.is_file():
            webp_kb = round(webp.stat().st_size / 1024, 1)
            row["webp_kb"] = webp_kb
            row["saved_kb"] = round(row["size_kb"] - webp_kb, 1)
            row["saved_pct"] = round(100 * row["saved_kb"] / row["size_kb"], 1) if row["size_kb"] else 0
    REPORT.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Enriched {len(rows)} rows")


if __name__ == "__main__":
    main()
