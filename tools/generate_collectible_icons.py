#!/usr/bin/env python3
"""Pack AI-generated collectible masters into static/img/collectibles (GC-Coll-Img).

Source masters live in the Cursor assets folder as ``{key}_gen.png``.
Re-run after regenerating art; does not invent placeholder geometry.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "img" / "collectibles"
DEFAULT_ASSETS = Path.home() / ".cursor" / "projects" / "c-Users-gurge-Desktop-RandomStuff-Coding-Genesis-Colonies" / "assets"
SIZE = 256

KEYS = [
    "fragment_dna_common",
    "fragment_dna_rare",
    "fragment_dna_epic",
    "fragment_alien",
    "fragment_artifact_alpha",
    "fragment_wreck_hull",
    "fragment_wreck_reactor",
    "fleet_computer",
    "fleet_hyperdrive_module",
    "fleet_nav_chip",
    "research_data_energy",
    "research_data_mining",
    "research_data_weapons",
]


def fit_square(im: Image.Image, size: int) -> Image.Image:
    im = im.convert("RGBA")
    w, h = im.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 255))
    canvas.paste(im, ((side - w) // 2, (side - h) // 2), im)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


def save_webp(im: Image.Image, path: Path, budget: int = 45_000) -> int:
    best = b""
    for q in (85, 80, 75, 70, 65, 60, 55):
        buf = io.BytesIO()
        im.save(buf, "WEBP", quality=q, method=6)
        best = buf.getvalue()
        if len(best) <= budget:
            break
    path.write_bytes(best)
    return len(best)


def main() -> None:
    assets = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ASSETS
    OUT.mkdir(parents=True, exist_ok=True)
    for key in KEYS:
        src = assets / f"{key}_gen.png"
        if not src.is_file():
            raise SystemExit(f"missing master: {src}")
        im = fit_square(Image.open(src), SIZE)
        png = OUT / f"{key}.png"
        webp = OUT / f"{key}.webp"
        im.save(png, "PNG", optimize=True, compress_level=9)
        wb = save_webp(im, webp)
        print(f"{key}: png={png.stat().st_size // 1024}KB webp={wb // 1024}KB")


if __name__ == "__main__":
    main()
