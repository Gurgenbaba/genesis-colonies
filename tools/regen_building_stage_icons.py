# -*- coding: utf-8 -*-
"""Generate circular vignette stage prop thumbs for the buildings planet stage."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "static" / "img" / "buildings"
OUT = ROOT / "static" / "img" / "buildings" / "stage"
SIDE = 256
FILL = 0.9

OVERRIDES = {
    "orbital_shipyard": "shipyard.png",
    "fuel_storage": "fuel_cell_storage.png",
}
KEYS = [
    "metal_mine",
    "crystal_mine",
    "solar_plant",
    "fuel_cell_plant",
    "metal_storage",
    "crystal_storage",
    "fuel_storage",
    "research_lab",
    "academy",
    "orbital_shipyard",
    "defense_factory",
    "barracks",
    "radar_array",
    "command_center",
    "shield_generator",
    "terraformer",
    "nanofactory",
    "geothermal_nexus",
    "planet_core_nexus",
]


def alpha_coverage(im: Image.Image) -> float:
    a = im.split()[-1]
    hist = a.histogram()
    solid = sum(hist[32:])
    return solid / float(max(1, SIDE * SIDE))


def ellipse_mask(side: int) -> Image.Image:
    mask = Image.new("L", (side, side), 0)
    draw = ImageDraw.Draw(mask)
    pad = max(2, int(side * 0.02))
    draw.ellipse((pad, pad, side - 1 - pad, side - 1 - pad), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(radius=max(1, int(side * 0.018))))


def vignette_from_original(im: Image.Image, side: int = SIDE) -> Image.Image:
    im = im.convert("RGBA")
    w, h = im.size
    side0 = min(w, h)
    left = (w - side0) // 2
    top = max(0, (h - side0) // 2 - int(side0 * 0.05))
    if top + side0 > h:
        top = h - side0
    sq = im.crop((left, top, left + side0, top + side0))
    target = max(1, int(side * FILL))
    resized = sq.resize((target, target), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    off = (side - target) // 2
    canvas.paste(resized, (off, off), resized)
    r, g, b, a = canvas.split()
    from PIL import ImageChops

    a2 = ImageChops.multiply(a, ellipse_mask(side))
    rgb = ImageEnhance.Contrast(Image.merge("RGB", (r, g, b))).enhance(1.08)
    rgb = ImageEnhance.Color(rgb).enhance(1.05)
    r, g, b = rgb.split()
    return Image.merge("RGBA", (r, g, b, a2))


def normalize_fill(im: Image.Image, fill: float = FILL) -> Image.Image:
    bb = im.getbbox()
    if not bb:
        return im
    cropped = im.crop(bb)
    cw, ch = cropped.size
    target = max(1, int(SIDE * fill))
    scale = target / max(cw, ch)
    nw, nh = max(1, int(cw * scale)), max(1, int(ch * scale))
    resized = cropped.resize((nw, nh), Image.Resampling.LANCZOS)
    out = Image.new("RGBA", (SIDE, SIDE), (0, 0, 0, 0))
    out.paste(resized, ((SIDE - nw) // 2, (SIDE - nh) // 2), resized)
    r, g, b, a = out.split()
    from PIL import ImageChops

    a2 = ImageChops.multiply(a, ellipse_mask(SIDE))
    return Image.merge("RGBA", (r, g, b, a2))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for key in KEYS:
        name = OVERRIDES.get(key, f"{key}.png")
        src = SRC / name
        im = Image.open(src).convert("RGBA")
        out = normalize_fill(vignette_from_original(im))
        path = OUT / f"{key}.webp"
        out.save(path, "WEBP", quality=92, method=6)
        print(f"{key:20} vignette cov={alpha_coverage(out):.3f} bbox={out.getbbox()}")


if __name__ == "__main__":
    main()
