#!/usr/bin/env python3
"""Generate 96px industrial collectible icons (GC-Coll-Img)."""

from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "img" / "collectibles"
SIZE = 96

# key -> (accent RGB, motif)
SPECS: dict[str, tuple[tuple[int, int, int], str]] = {
    "fragment_dna_common": ((72, 196, 140), "helix"),
    "fragment_dna_rare": ((70, 170, 255), "helix"),
    "fragment_dna_epic": ((196, 110, 255), "helix"),
    "fragment_alien": ((120, 255, 170), "eye"),
    "fragment_artifact_alpha": ((255, 196, 90), "shard"),
    "fragment_wreck_hull": ((160, 180, 200), "plate"),
    "fragment_wreck_reactor": ((255, 120, 70), "core"),
    "fleet_computer": ((90, 210, 255), "chip"),
    "fleet_hyperdrive_module": ((130, 150, 255), "drive"),
    "fleet_nav_chip": ((255, 210, 90), "compass"),
    "research_data_energy": ((255, 220, 80), "disk"),
    "research_data_mining": ((120, 220, 255), "disk"),
    "research_data_weapons": ((255, 110, 110), "disk"),
}


def _bg(accent: tuple[int, int, int]) -> Image.Image:
    im = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # Dark panel plate
    d.rectangle((4, 4, SIZE - 5, SIZE - 5), fill=(10, 16, 24, 255), outline=(*accent, 220), width=2)
    d.rectangle((8, 8, SIZE - 9, SIZE - 9), outline=(40, 55, 70, 200), width=1)
    # Corner ticks
    for x0, y0, x1, y1 in (
        (8, 8, 20, 8),
        (8, 8, 8, 20),
        (SIZE - 21, 8, SIZE - 9, 8),
        (SIZE - 9, 8, SIZE - 9, 20),
        (8, SIZE - 9, 20, SIZE - 9),
        (8, SIZE - 21, 8, SIZE - 9),
        (SIZE - 21, SIZE - 9, SIZE - 9, SIZE - 9),
        (SIZE - 9, SIZE - 21, SIZE - 9, SIZE - 9),
    ):
        d.line((x0, y0, x1, y1), fill=(*accent, 180), width=2)
    # Soft vignette center
    cx = cy = SIZE // 2
    for r in range(34, 8, -2):
        a = int(18 + (34 - r) * 1.2)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(accent[0], accent[1], accent[2], a))
    return im


def _draw_helix(d: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    cx = SIZE // 2
    for i in range(8):
        t = i / 7
        y = 22 + int(t * 52)
        amp = 14
        x1 = cx + int(math.sin(t * math.pi * 2) * amp)
        x2 = cx - int(math.sin(t * math.pi * 2) * amp)
        d.ellipse((x1 - 4, y - 4, x1 + 4, y + 4), fill=(*accent, 230))
        d.ellipse((x2 - 4, y - 4, x2 + 4, y + 4), fill=(220, 235, 255, 200))
        d.line((x1, y, x2, y), fill=(*accent, 140), width=1)


def _draw_eye(d: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    cx = cy = SIZE // 2
    d.ellipse((cx - 28, cy - 16, cx + 28, cy + 16), outline=(*accent, 230), width=2)
    d.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=(*accent, 220))
    d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=(8, 12, 18, 255))


def _draw_shard(d: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    pts = [(48, 18), (68, 40), (56, 78), (36, 72), (28, 42)]
    d.polygon(pts, fill=(*accent, 200), outline=(255, 240, 200, 230))
    d.line((48, 18, 46, 70), fill=(255, 255, 255, 120), width=1)


def _draw_plate(d: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    d.rectangle((26, 28, 70, 68), fill=(50, 60, 72, 255), outline=(*accent, 220), width=2)
    d.line((32, 40, 64, 40), fill=(*accent, 160), width=2)
    d.line((32, 50, 58, 50), fill=(180, 190, 200, 160), width=2)
    d.rectangle((34, 56, 48, 62), fill=(*accent, 180))


def _draw_core(d: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    cx = cy = SIZE // 2
    d.ellipse((cx - 22, cy - 22, cx + 22, cy + 22), outline=(*accent, 220), width=3)
    d.ellipse((cx - 12, cy - 12, cx + 12, cy + 12), fill=(*accent, 210))
    d.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), fill=(255, 240, 200, 240))
    for ang in (0, 60, 120, 180, 240, 300):
        rad = math.radians(ang)
        x0 = cx + int(math.cos(rad) * 14)
        y0 = cy + int(math.sin(rad) * 14)
        x1 = cx + int(math.cos(rad) * 26)
        y1 = cy + int(math.sin(rad) * 26)
        d.line((x0, y0, x1, y1), fill=(*accent, 180), width=2)


def _draw_chip(d: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    d.rectangle((30, 30, 66, 66), fill=(18, 28, 40, 255), outline=(*accent, 230), width=2)
    for i in range(4):
        y = 36 + i * 7
        d.line((34, y, 62, y), fill=(*accent, 160), width=1)
    d.rectangle((42, 42, 54, 54), fill=(*accent, 200))
    for x in (28, 68):
        for y in (36, 48, 60):
            d.line((x, y, 30 if x == 28 else 66, y), fill=(160, 180, 200, 180), width=1)


def _draw_drive(d: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    d.polygon([(22, 48), (40, 28), (72, 36), (72, 60), (40, 68)], fill=(24, 32, 52, 255), outline=(*accent, 230))
    d.ellipse((50, 40, 66, 56), fill=(*accent, 210))
    d.polygon([(18, 48), (28, 40), (28, 56)], fill=(200, 220, 255, 160))


def _draw_compass(d: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    cx = cy = SIZE // 2
    d.ellipse((cx - 24, cy - 24, cx + 24, cy + 24), outline=(*accent, 220), width=2)
    d.polygon([(cx, cy - 20), (cx + 6, cy), (cx, cy + 6), (cx - 6, cy)], fill=(*accent, 220))
    d.line((cx, cy - 26, cx, cy + 26), fill=(200, 210, 220, 100), width=1)
    d.line((cx - 26, cy, cx + 26, cy), fill=(200, 210, 220, 100), width=1)


def _draw_disk(d: ImageDraw.ImageDraw, accent: tuple[int, int, int]) -> None:
    cx = cy = SIZE // 2
    d.ellipse((cx - 26, cy - 26, cx + 26, cy + 26), fill=(20, 28, 40, 255), outline=(*accent, 230), width=2)
    d.ellipse((cx - 10, cy - 10, cx + 10, cy + 10), fill=(*accent, 200))
    d.arc((cx - 20, cy - 20, cx + 20, cy + 20), 30, 200, fill=(*accent, 160), width=2)


MOTIFS = {
    "helix": _draw_helix,
    "eye": _draw_eye,
    "shard": _draw_shard,
    "plate": _draw_plate,
    "core": _draw_core,
    "chip": _draw_chip,
    "drive": _draw_drive,
    "compass": _draw_compass,
    "disk": _draw_disk,
}


def _save_webp(im: Image.Image, path: Path) -> None:
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=82, method=6)
    path.write_bytes(buf.getvalue())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for key, (accent, motif) in SPECS.items():
        im = _bg(accent)
        MOTIFS[motif](ImageDraw.Draw(im), accent)
        png = OUT / f"{key}.png"
        webp = OUT / f"{key}.webp"
        im.save(png, "PNG", optimize=True)
        _save_webp(im, webp)
        print(f"{key}: png={png.stat().st_size} webp={webp.stat().st_size}")


if __name__ == "__main__":
    main()
