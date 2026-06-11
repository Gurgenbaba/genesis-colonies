#!/usr/bin/env python3
"""GC-555 — generate WebP siblings for static/img raster assets."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow required: pip install Pillow") from exc

ROOT = Path(__file__).resolve().parent.parent
IMG_ROOT = ROOT / "static" / "img"
RASTER = {".png", ".jpg", ".jpeg"}
MAX_DIM_OVERSIZE = 1920
OVERSIZE_KB = 400
QUALITY = 82


def should_resize(path: Path) -> bool:
    return path.stat().st_size / 1024 >= OVERSIZE_KB


def convert_one(src: Path) -> tuple[int, int]:
    """Return (bytes_before, bytes_after)."""
    dst = src.with_suffix(".webp")
    before = src.stat().st_size
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return before, dst.stat().st_size

    img = Image.open(src)
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")

    if should_resize(src):
        w, h = img.size
        longest = max(w, h)
        if longest > MAX_DIM_OVERSIZE:
            scale = MAX_DIM_OVERSIZE / longest
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)

    img.save(dst, "WEBP", quality=QUALITY, method=6)
    return before, dst.stat().st_size


def main() -> int:
    converted = 0
    saved = 0
    for src in sorted(IMG_ROOT.rglob("*")):
        if not src.is_file() or src.suffix.lower() not in RASTER:
            continue
        before, after = convert_one(src)
        if after > 0:
            converted += 1
            saved += max(0, before - after)
    print(f"WebP: {converted} files, saved {saved / 1024 / 1024:.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
