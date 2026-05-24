#!/usr/bin/env python3
"""
Genesis Colonies — lokale Icon-Generierung (stdlib only, kein Pillow).
Erzeugt PNG an exakt den von Templates/Config referenzierten Pfaden
und SVG unter static/icons/ für Ressourcen.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

BUILDINGS = [
    "metal_mine", "crystal_mine", "solar_plant", "research_lab", "academy",
    "metal_storage", "crystal_storage", "command_center", "shipyard",
    "defense_factory", "barracks", "radar_array", "shield_generator",
    "terraformer", "nanofactory", "geothermal_nexus", "planet_core_nexus",
]

RESEARCH = {
    "energieeffizienz.png": (255, 196, 0),
    "metallveredelung.png": (127, 255, 217),
    "bauoptimierung.png": (140, 180, 255),
    "lagertechnik.png": (180, 140, 255),
    "drohnenoptimierung.png": (100, 220, 200),
    "hyperraum-navigation.png": (70, 229, 255),
    "kryo-antriebstechnik.png": (120, 200, 255),
    "waffenentwicklung.png": (255, 120, 120),
    "panzerungstechnik.png": (180, 180, 200),
    "schildtechnologie.png": (120, 255, 220),
}

BUILDING_COLORS = {
    "metal_mine": (127, 255, 217),
    "crystal_mine": (70, 229, 255),
    "solar_plant": (255, 196, 0),
    "research_lab": (140, 200, 255),
    "academy": (160, 140, 255),
    "metal_storage": (100, 200, 170),
    "crystal_storage": (80, 190, 230),
    "command_center": (200, 200, 220),
    "shipyard": (255, 160, 90),
    "defense_factory": (255, 110, 110),
    "barracks": (255, 140, 100),
    "radar_array": (120, 255, 180),
    "shield_generator": (100, 220, 255),
    "terraformer": (150, 255, 150),
    "nanofactory": (180, 160, 255),
    "geothermal_nexus": (255, 180, 80),
    "planet_core_nexus": (255, 100, 180),
    "default": (120, 190, 255),
}


def write_png(path: Path, width: int, height: int, rgb: tuple[int, int, int], accent: tuple[int, int, int] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    accent = accent or tuple(min(255, c + 40) for c in rgb)
    bg = (8, 14, 28)
    pixels = []
    cx, cy = width / 2, height / 2
    for y in range(height):
        row = b"\x00"
        for x in range(width):
            dx = (x - cx) / (width * 0.45)
            dy = (y - cy) / (height * 0.45)
            dist = dx * dx + dy * dy
            if dist <= 1.0:
                t = max(0.0, 1.0 - dist)
                r = int(bg[0] + (rgb[0] - bg[0]) * t)
                g = int(bg[1] + (rgb[1] - bg[1]) * t)
                b = int(bg[2] + (rgb[2] - bg[2]) * t)
                if abs(x - cx) < width * 0.08 or abs(y - cy) < height * 0.08:
                    r, g, b = accent
                row += bytes((r, g, b))
            else:
                row += bytes(bg)
        pixels.append(row)
    raw = b"".join(pixels)
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)


def write_resource_svg(path: Path, label: str, primary: str, secondary: str, symbol: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-hidden="true">
  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{primary}"/>
      <stop offset="100%" stop-color="{secondary}"/>
    </linearGradient>
    <filter id="glow"><feGaussianBlur stdDeviation="2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <rect x="4" y="4" width="56" height="56" rx="14" fill="#070e20" stroke="{primary}" stroke-opacity="0.45"/>
  <circle cx="32" cy="32" r="18" fill="url(#g)" filter="url(#glow)" opacity="0.92"/>
  <text x="32" y="38" text-anchor="middle" font-size="22" fill="#060b16" font-family="Segoe UI Emoji, Apple Color Emoji, sans-serif">{symbol}</text>
  <title>{label}</title>
</svg>
"""
    path.write_text(svg, encoding="utf-8")


def main() -> None:
    resources = {
        "ferronit": ("#7fffd9", "#23f2a6", "⛏"),
        "crytite": ("#46e5ff", "#7fffd9", "💎"),
        "energy": ("#ffc400", "#ffe58a", "⚡"),
    }
    for name, (p, s, sym) in resources.items():
        rgb_map = {
            "ferronit": (127, 255, 217),
            "crytite": (70, 229, 255),
            "energy": (255, 196, 0),
        }
        write_resource_svg(STATIC / "icons" / f"{name}.svg", name, p, s, sym)
        write_png(STATIC / "icons" / f"{name}.png", 64, 64, rgb_map[name])

    for key, rgb in BUILDING_COLORS.items():
        fname = "default.png" if key == "default" else f"{key}.png"
        write_png(STATIC / "img" / "buildings" / fname, 96, 96, rgb)

    for fname, rgb in RESEARCH.items():
        write_png(STATIC / "img" / "research" / fname, 96, 96, rgb)

    print(f"Generated icons under {STATIC}")


if __name__ == "__main__":
    main()
