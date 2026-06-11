#!/usr/bin/env python3
"""GC-555 — scan static/img and emit asset size report."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG_ROOT = ROOT / "static" / "img"
SKIP_EXT = {".mp3", ".wav", ".svg", ".webp", ".json"}
WARN_KB = 250
CRIT_KB = 500


def categorize(rel: Path) -> str:
    parts = rel.parts
    if len(parts) < 2:
        return "root"
    return parts[0]


def recommendation(kb: float, cat: str) -> str:
    if kb >= CRIT_KB:
        return "convert WebP + resize; lazy/async in templates"
    if kb >= WARN_KB:
        return "convert WebP; verify lazy loading"
    if cat == "landscapes":
        return "WebP preferred; single active landscape per page"
    if cat in ("buildings", "research"):
        return "WebP + lazy/async on cards"
    if cat in ("ships", "defense"):
        return "WebP; lazy on list cards"
    if cat == "vote":
        return "card banner; CSS background + overlay"
    return "ok"


def main() -> None:
    rows = []
    for path in sorted(IMG_ROOT.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext in SKIP_EXT:
            continue
        rel = path.relative_to(IMG_ROOT)
        size = path.stat().st_size
        kb = size / 1024
        cat = categorize(rel)
        flag = "critical" if kb >= CRIT_KB else ("warning" if kb >= WARN_KB else "ok")
        rows.append(
            {
                "path": f"static/img/{rel.as_posix()}",
                "format": ext.lstrip("."),
                "size_kb": round(kb, 1),
                "category": cat,
                "flag": flag,
                "recommendation": recommendation(kb, cat),
            }
        )

    rows.sort(key=lambda r: r["size_kb"], reverse=True)
    out = ROOT / "docs" / "GC-555_asset_report.json"
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Wrote {len(rows)} entries to {out}")
    print("\nTop 15:")
    for r in rows[:15]:
        print(f"  {r['size_kb']:7.1f} KB  [{r['flag']}]  {r['category']:12}  {r['path']}")


if __name__ == "__main__":
    main()
