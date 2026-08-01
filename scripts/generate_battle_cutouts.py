#!/usr/bin/env python3
"""Generate RGBA cutout variants for ships/defense battle theater art."""

from __future__ import annotations

from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / "static" / "img"


def _color_dist(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def make_cutout(src: Path, dst: Path, threshold: int = 55) -> tuple[Path, tuple[int, int], str]:
    im = Image.open(src).convert("RGBA")
    pixels = im.load()
    w, h = im.size

    # Seed flood-fill from edges using local pixel as bg reference.
    bg_mask = [[False] * w for _ in range(h)]
    q: deque[tuple[int, int, tuple[int, int, int]]] = deque()

    def try_seed(x: int, y: int) -> None:
        r, g, b, a = pixels[x, y]
        if a < 8:
            bg_mask[y][x] = True
            q.append((x, y, (r, g, b)))
            return
        # Dark space / vignette backgrounds
        if r + g + b <= 55:
            bg_mask[y][x] = True
            q.append((x, y, (r, g, b)))
            return
        # Bluish card backgrounds (defense art)
        if b >= r + 15 and b >= g and r + g + b <= 180:
            bg_mask[y][x] = True
            q.append((x, y, (r, g, b)))

    for x in range(w):
        try_seed(x, 0)
        try_seed(x, h - 1)
    for y in range(h):
        try_seed(0, y)
        try_seed(w - 1, y)

    while q:
        x, y, ref = q.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if nx < 0 or ny < 0 or nx >= w or ny >= h or bg_mask[ny][nx]:
                continue
            r, g, b, a = pixels[nx, ny]
            if a < 8 or _color_dist((r, g, b), ref) <= threshold or r + g + b <= 40:
                bg_mask[ny][nx] = True
                # slowly adapt reference so gradients stay removable
                nref = (
                    (ref[0] * 3 + r) // 4,
                    (ref[1] * 3 + g) // 4,
                    (ref[2] * 3 + b) // 4,
                )
                q.append((nx, ny, nref))

    out = Image.new("RGBA", (w, h))
    op = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if bg_mask[y][x]:
                # soft fringe: neighbors not bg keep partial alpha
                soft = False
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < w and 0 <= ny < h and not bg_mask[ny][nx]:
                        soft = True
                        break
                op[x, y] = (r, g, b, 90 if soft else 0)
            else:
                op[x, y] = (r, g, b, a)

    bbox = out.getbbox()
    if bbox:
        pad = 6
        x0, y0, x1, y1 = bbox
        x0 = max(0, x0 - pad)
        y0 = max(0, y0 - pad)
        x1 = min(w, x1 + pad)
        y1 = min(h, y1 + pad)
        out = out.crop((x0, y0, x1, y1))

    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst, "PNG", optimize=True)
    out.save(dst.with_suffix(".webp"), "WEBP", quality=90, method=4)
    return dst, out.size, out.mode


def main() -> None:
    pairs: list[tuple[Path, Path]] = []
    for folder in ("ships", "defense"):
        src_dir = ROOT / folder
        for png in sorted(src_dir.glob("*.png")):
            if png.name.startswith("_"):
                continue
            pairs.append((png, ROOT / folder / "cutout" / png.name))
    for src, dst in pairs:
        path, size, mode = make_cutout(src, dst)
        print(f"OK {path.relative_to(ROOT)} {mode} {size}")
    print(f"done {len(pairs)} cutouts")


if __name__ == "__main__":
    main()
