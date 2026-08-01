#!/usr/bin/env python3
"""Resize + WebP for static/img/politics (GC-Pol-Img)."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
POL = ROOT / "static" / "img" / "politics"

# (relative glob/path prefix, max_width, max_height, webp_budget, png_budget)
RULES = [
    ("chamber/chamber_backdrop.png", 960, 640, 90_000, 180_000),
    ("chamber/senate_hero.png", 512, 192, 50_000, 120_000),
    ("chamber/tab_*.png", 128, 128, 12_000, 30_000),
    ("chamber/mandate_ring.png", 128, 128, 12_000, 30_000),
    ("chamber/resolution_mark.png", 128, 128, 12_000, 30_000),
    ("directives/*.png", 512, 288, 70_000, 140_000),
    ("blocs/*.png", 128, 128, 12_000, 30_000),
]


def _fit(im: Image.Image, max_w: int, max_h: int) -> Image.Image:
    w, h = im.size
    scale = min(max_w / w, max_h / h, 1.0)
    if scale >= 0.999:
        return im
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    return im.resize((nw, nh), Image.Resampling.LANCZOS)


def _save_webp(im: Image.Image, path: Path, budget: int) -> int:
    work = im
    if work.mode not in ("RGB", "RGBA"):
        work = work.convert("RGBA" if "A" in work.getbands() else "RGB")
    best = b""
    for q in (82, 76, 70, 64, 58, 52, 46, 40):
        buf = io.BytesIO()
        work.save(buf, "WEBP", quality=q, method=6)
        data = buf.getvalue()
        best = data
        if len(data) <= budget:
            break
    path.write_bytes(best)
    return len(best)


def _save_png(im: Image.Image, path: Path, budget: int) -> int:
    work = im
    if work.mode not in ("RGBA", "RGB"):
        work = work.convert("RGBA" if "A" in work.getbands() else "RGB")
    best = b""
    cur = work
    for _ in range(8):
        for compress in (9, 7, 6):
            buf = io.BytesIO()
            cur.save(buf, "PNG", optimize=True, compress_level=compress)
            data = buf.getvalue()
            best = data
            if len(data) <= budget:
                path.write_bytes(data)
                return len(data)
        w, h = cur.size
        if w <= 96 and h <= 96:
            break
        cur = cur.resize((max(64, int(w * 0.85)), max(64, int(h * 0.85))), Image.Resampling.LANCZOS)
    path.write_bytes(best)
    return len(best)


def _match_paths(pattern: str) -> list[Path]:
    return sorted(POL.glob(pattern))


def main() -> None:
    total_before = 0
    total_after = 0
    for pattern, max_w, max_h, webp_budget, png_budget in RULES:
        for png_path in _match_paths(pattern):
            if not png_path.is_file():
                continue
            before = png_path.stat().st_size
            total_before += before
            im = Image.open(png_path)
            im.load()
            fitted = _fit(im, max_w, max_h)
            png_bytes = _save_png(fitted, png_path, png_budget)
            webp_path = png_path.with_suffix(".webp")
            webp_bytes = _save_webp(fitted, webp_path, webp_budget)
            total_after += png_bytes
            print(
                f"{png_path.relative_to(POL)}: {before/1024:.0f}KB -> png {png_bytes/1024:.0f}KB "
                f"+ webp {webp_bytes/1024:.0f}KB ({fitted.size[0]}x{fitted.size[1]})"
            )
    print(f"PNG total: {total_before/1024/1024:.2f}MB -> {total_after/1024/1024:.2f}MB")


if __name__ == "__main__":
    main()
