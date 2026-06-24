"""
GC-859 — Inventory building hero raster assets (size + dimensions).

Run: python tools/audit_building_hero_images.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMG_DIR = ROOT / "static" / "img" / "buildings"

BUILDING_KEYS = (
    "metal_mine",
    "crystal_mine",
    "solar_plant",
    "fuel_cell_plant",
    "metal_storage",
    "crystal_storage",
    "fuel_storage",
    "fuel_cell_storage",
    "research_lab",
    "academy",
    "orbital_shipyard",
    "shipyard",
    "defense_factory",
    "barracks",
    "radar_array",
    "command_center",
    "shield_generator",
    "terraformer",
    "nanofactory",
    "geothermal_nexus",
    "planet_core_nexus",
    "default",
)

ABOVE_FOLD_RESOURCES = ("metal_mine", "crystal_mine", "solar_plant")


def _dims(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return int(im.size[0]), int(im.size[1])
    except Exception:
        return None


def audit() -> list[dict]:
    rows: list[dict] = []
    for key in BUILDING_KEYS:
        for ext in (".webp", ".png"):
            path = IMG_DIR / f"{key}{ext}"
            if not path.is_file():
                continue
            w, h = _dims(path) or (0, 0)
            rows.append(
                {
                    "building": key,
                    "file": f"static/img/buildings/{key}{ext}",
                    "format": ext.lstrip("."),
                    "width": w,
                    "height": h,
                    "bytes": path.stat().st_size,
                    "referenced_by": "get_building_icon → buildings.html hero",
                    "above_the_fold_candidate": key in ABOVE_FOLD_RESOURCES and ext == ".webp",
                    "flags": [
                        f
                        for f, ok in (
                            (">300KB", path.stat().st_size > 300_000),
                            (">1000px", w > 1000),
                            ("png_primary_risk", ext == ".png"),
                        )
                        if ok
                    ],
                }
            )
    return rows


def main() -> int:
    rows = audit()
    print(json.dumps(rows, indent=2))
    png_heavy = [r for r in rows if r["format"] == "png" and r["bytes"] > 300_000]
    print(f"\n# PNG >300KB: {len(png_heavy)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
