#!/usr/bin/env python3
"""
Genesis Colonies — Icon Generator v1.6 (stdlib only)

Erzeugt PNG an exakt den von Templates/Config referenzierten Pfaden.
Optional zusätzlich SVG-Varianten (Ressourcen + Gebäude + Forschung).

Stile:
  - Ressourcen: kompakte HUD-Chips mit klarem Symbol + Glow
  - Gebäude:    hexagonale Plattform, architektonische Silhouette
  - Forschung:  orbitaler Ring-Rahmen, Tech-/Wissenschaftssymbolik
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path
from typing import Callable, Iterable, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

RGB = Tuple[int, int, int]

BUILDINGS = [
    "metal_mine", "crystal_mine", "solar_plant", "research_lab", "academy",
    "metal_storage", "crystal_storage", "command_center", "shipyard",
    "defense_factory", "barracks", "radar_array", "shield_generator",
    "terraformer", "nanofactory", "geothermal_nexus", "planet_core_nexus",
]

RESEARCH_FILES = [
    "energieeffizienz.png",
    "metallveredelung.png",
    "bauoptimierung.png",
    "lagertechnik.png",
    "drohnenoptimierung.png",
    "hyperraum-navigation.png",
    "kryo-antriebstechnik.png",
    "waffenentwicklung.png",
    "panzerungstechnik.png",
    "schildtechnologie.png",
]

# Theme palette (aligned with style.css tokens)
BG = (6, 11, 22)
PANEL = (7, 14, 32)
METAL = (127, 255, 217)
CRYSTAL = (70, 229, 255)
ENERGY = (255, 196, 0)
NEON = (35, 242, 166)
MUTED = (120, 190, 255)


def clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def lerp_rgb(c1: RGB, c2: RGB, t: float) -> RGB:
    t = clamp(t)
    return (
        int(lerp(c1[0], c2[0], t)),
        int(lerp(c1[1], c2[1], t)),
        int(lerp(c1[2], c2[2], t)),
    )


def brighten(c: RGB, amt: float = 0.25) -> RGB:
    return tuple(min(255, int(v + 255 * amt)) for v in c)  # type: ignore


def dim(c: RGB, amt: float = 0.35) -> RGB:
    return tuple(int(v * (1 - amt)) for v in c)  # type: ignore


class Canvas:
    """Simple RGB canvas with alpha blending."""

    def __init__(self, size: int, bg: RGB = BG) -> None:
        self.size = size
        self.bg = bg
        self.pixels = [[[float(c) for c in bg] for _ in range(size)] for _ in range(size)]

    def blend(self, x: int, y: int, color: RGB, alpha: float = 1.0) -> None:
        if not (0 <= x < self.size and 0 <= y < self.size):
            return
        alpha = clamp(alpha)
        px = self.pixels[y][x]
        for i in range(3):
            px[i] = px[i] * (1 - alpha) + color[i] * alpha

    def stroke_line(self, x0: float, y0: float, x1: float, y1: float, color: RGB, w: float = 1.6) -> None:
        dist = math.hypot(x1 - x0, y1 - y0)
        steps = max(int(dist * 3), 1)
        for i in range(steps + 1):
            t = i / steps
            x = lerp(x0, x1, t)
            y = lerp(y0, y1, t)
            self.fill_disc(x, y, w / 2, color)

    def fill_disc(self, cx: float, cy: float, r: float, color: RGB, alpha: float = 1.0) -> None:
        s = self.size
        x0 = max(0, int(cx - r - 2))
        x1 = min(s - 1, int(cx + r + 2))
        y0 = max(0, int(cy - r - 2))
        y1 = min(s - 1, int(cy + r + 2))
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                d = math.hypot(x - cx, y - cy)
                if d <= r:
                    self.blend(x, y, color, alpha)

    def glow_disc(self, cx: float, cy: float, r: float, color: RGB, spread: float = 4.0) -> None:
        s = self.size
        x0 = max(0, int(cx - r - spread - 2))
        x1 = min(s - 1, int(cx + r + spread + 2))
        y0 = max(0, int(cy - r - spread - 2))
        y1 = min(s - 1, int(cy + r + spread + 2))
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                d = math.hypot(x - cx, y - cy)
                if d <= r + spread:
                    if d <= r:
                        self.blend(x, y, color, 0.95)
                    else:
                        t = 1 - (d - r) / spread
                        self.blend(x, y, color, 0.22 * t)

    def fill_polygon(self, pts: Sequence[Tuple[float, float]], color: RGB, alpha: float = 1.0) -> None:
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        y_min = max(0, int(min(ys)))
        y_max = min(self.size - 1, int(max(ys)) + 1)

        def edge(xa, ya, xb, yb, y):
            if ya == yb:
                return xa
            if ya > yb:
                xa, ya, xb, yb = xb, yb, xa, ya
            if y < ya or y >= yb:
                return None
            t = (y - ya) / (yb - ya)
            return xa + (xb - xa) * t

        for y in range(y_min, y_max + 1):
            xs = []
            n = len(pts)
            for i in range(n):
                xa, ya = pts[i]
                xb, yb = pts[(i + 1) % n]
                x = edge(xa, ya, xb, yb, y + 0.5)
                if x is not None:
                    xs.append(x)
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                x_start = int(math.floor(xs[i]))
                x_end = int(math.ceil(xs[i + 1]))
                for x in range(max(0, x_start), min(self.size, x_end + 1)):
                    self.blend(x, y, color, alpha)

    def fill_round_rect(self, x: float, y: float, w: float, h: float, rad: float, color: RGB, alpha: float = 1.0) -> None:
        x2, y2 = x + w, y + h
        for py in range(self.size):
            for px in range(self.size):
                cx = clamp(px, x + rad, x2 - rad)
                cy = clamp(py, y + rad, y2 - rad)
                dx = px - cx if px < x + rad or px > x2 - rad else 0
                dy = py - cy if py < y + rad or py > y2 - rad else 0
                if px >= x and px <= x2 and py >= y and py <= y2:
                    if dx == 0 and dy == 0:
                        self.blend(px, py, color, alpha)
                    elif math.hypot(dx, dy) <= rad:
                        self.blend(px, py, color, alpha)

    def ring(self, cx: float, cy: float, r: float, thickness: float, color: RGB, alpha: float = 1.0) -> None:
        s = self.size
        for y in range(s):
            for x in range(s):
                d = abs(math.hypot(x - cx, y - cy) - r)
                if d <= thickness / 2:
                    self.blend(x, y, color, alpha)

    def hex_points(self, cx: float, cy: float, r: float) -> list[Tuple[float, float]]:
        return [
            (cx + r * math.cos(math.radians(60 * i - 30)), cy + r * math.sin(math.radians(60 * i - 30)))
            for i in range(6)
        ]

    def draw_hex_frame(self, cx: float, cy: float, r: float, stroke: RGB, fill: RGB | None = None) -> None:
        pts = self.hex_points(cx, cy, r)
        if fill:
            self.fill_polygon(pts, fill, 0.85)
        for i in range(6):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % 6]
            self.stroke_line(x0, y0, x1, y1, stroke, 1.8)

    def to_png(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw_rows = []
        for row in self.pixels:
            raw = b"\x00"
            for px in row:
                raw += bytes(int(clamp(v, 0, 255)) for v in px)
            raw_rows.append(raw)
        raw = b"".join(raw_rows)

        def chunk(tag: bytes, data: bytes) -> bytes:
            crc = zlib.crc32(tag + data) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = struct.pack(">IIBBBBB", self.size, self.size, 8, 2, 0, 0, 0)
        png = sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
        path.write_bytes(png)


def write_svg(path: Path, body: str, view: str = "0 0 96 96") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="{view}" role="img" aria-hidden="true">
{body}
</svg>"""
    path.write_text(svg, encoding="utf-8")


# ---------------------------------------------------------------------------
# Ressourcen-Stil (64×64 HUD-Chip)
# ---------------------------------------------------------------------------

def draw_resource_chip(c: Canvas, accent: RGB, inner_draw: Callable[[Canvas, float, float, float], None]) -> None:
    s = c.size
    cx = cy = s / 2
    c.fill_round_rect(4, 4, s - 8, s - 8, 10, PANEL, 0.95)
    c.ring(cx, cy, s * 0.28, 2.2, accent, 0.55)
    c.glow_disc(cx, cy, s * 0.12, accent, spread=5)
    inner_draw(c, cx, cy, s * 0.22, accent)


def draw_pickaxe(c: Canvas, cx: float, cy: float, r: float, color: RGB) -> None:
    c.stroke_line(cx - r, cy + r * 0.2, cx + r * 0.9, cy - r * 0.9, color, r * 0.22)
    c.stroke_line(cx - r * 0.2, cy - r, cx + r, cy - r * 0.1, color, r * 0.22)
    c.fill_disc(cx + r * 0.55, cy - r * 0.55, r * 0.18, brighten(color))


def draw_crystal(c: Canvas, cx: float, cy: float, r: float, color: RGB) -> None:
    pts = [
        (cx, cy - r * 1.2),
        (cx + r * 0.85, cy - r * 0.15),
        (cx + r * 0.55, cy + r * 1.05),
        (cx - r * 0.55, cy + r * 1.05),
        (cx - r * 0.85, cy - r * 0.15),
    ]
    c.fill_polygon(pts, dim(color, 0.2), 0.95)
    c.fill_polygon([(cx, cy - r), (cx + r * 0.45, cy + r * 0.35), (cx - r * 0.45, cy + r * 0.35)], brighten(color), 0.85)
    c.stroke_line(cx, cy - r * 1.1, cx, cy + r, color, r * 0.08)


def draw_bolt(c: Canvas, cx: float, cy: float, r: float, color: RGB) -> None:
    pts = [
        (cx + r * 0.15, cy - r),
        (cx - r * 0.35, cy + r * 0.05),
        (cx + r * 0.05, cy + r * 0.05),
        (cx - r * 0.2, cy + r),
        (cx + r * 0.45, cy - r * 0.15),
        (cx + r * 0.05, cy - r * 0.15),
    ]
    c.fill_polygon(pts, color, 0.95)
    c.glow_disc(cx, cy, r * 0.35, color, 3)


def resource_svg(name: str, accent: str, symbol_path: str) -> str:
    return f"""  <defs>
    <linearGradient id="g" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="{accent}" stop-opacity="0.95"/>
      <stop offset="100%" stop-color="#060b16"/>
    </linearGradient>
    <filter id="gl"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <rect x="4" y="4" width="56" height="56" rx="12" fill="#070e20" stroke="{accent}" stroke-opacity="0.5"/>
  <circle cx="32" cy="32" r="17" fill="none" stroke="{accent}" stroke-opacity="0.45" stroke-width="1.5"/>
  <g filter="url(#gl)" stroke="{accent}" stroke-width="2" fill="{accent}" stroke-linecap="round" stroke-linejoin="round">
    {symbol_path}
  </g>"""


RESOURCES = {
    "ferronit": (METAL, draw_pickaxe, resource_svg("ferronit", "#7fffd9", '<path d="M18 38 L42 18 M24 20 L44 34" fill="none"/>')),
    "crytite": (CRYSTAL, draw_crystal, resource_svg("crytite", "#46e5ff", '<polygon points="32,14 44,28 38,46 26,46 20,28" fill-opacity="0.35"/>')),
    "energy": (ENERGY, draw_bolt, resource_svg("energy", "#ffc400", '<polygon points="34,14 26,32 32,32 28,50 40,30 34,30"/>')),
}


# ---------------------------------------------------------------------------
# Gebäude-Stil (96×96 Hex-Plattform)
# ---------------------------------------------------------------------------

def building_base(c: Canvas, accent: RGB) -> None:
    s = c.size
    cx = cy = s / 2
    c.draw_hex_frame(cx, cy, s * 0.38, accent, fill=lerp_rgb(PANEL, accent, 0.08))
    c.ring(cx, cy, s * 0.30, 1.4, dim(accent, 0.15), 0.6)


def draw_building_mine(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2, c.size * 0.14
    for i in range(-2, 3):
        c.stroke_line(cx + i * r * 0.55, cy + r, cx + i * r * 0.25, cy - r * 1.2, accent, 2)
    c.fill_disc(cx, cy + r * 0.9, r * 0.35, brighten(accent))


def draw_building_crystal(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    draw_crystal(c, c.size / 2, c.size / 2 + 2, c.size * 0.13, accent)


def draw_building_solar(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2, c.size * 0.12
    c.fill_disc(cx, cy, r * 0.55, accent, 0.9)
    for deg in range(0, 360, 45):
        rad = math.radians(deg)
        c.stroke_line(cx, cy, cx + math.cos(rad) * r * 1.5, cy + math.sin(rad) * r * 1.5, brighten(accent), 1.6)


def draw_building_lab(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 4, c.size * 0.11
    c.fill_round_rect(cx - r, cy - r * 1.4, r * 2, r * 2.2, 3, dim(accent, 0.1), 0.9)
    c.fill_disc(cx, cy - r * 0.8, r * 0.55, accent, 0.75)
    c.stroke_line(cx - r * 0.5, cy + r, cx + r * 0.5, cy + r, accent, 2)


def draw_building_storage(c: Canvas, accent: RGB, crystal: bool = False) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 2, c.size * 0.13
    c.fill_round_rect(cx - r * 1.1, cy - r, r * 2.2, r * 2, 4, dim(accent, 0.15), 0.92)
    if crystal:
        draw_crystal(c, cx, cy - r * 0.1, r * 0.55, accent)
    else:
        c.fill_disc(cx, cy, r * 0.45, accent, 0.85)


def draw_building_tower(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 6, c.size * 0.1
    c.stroke_line(cx, cy + r, cx, cy - r * 1.6, accent, 2.4)
    c.fill_disc(cx, cy - r * 1.5, r * 0.35, brighten(accent))
    c.stroke_line(cx - r, cy - r * 0.4, cx + r, cy - r * 0.4, accent, 1.6)


def draw_building_shipyard(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 8, c.size * 0.11
    pts = [(cx, cy - r * 1.8), (cx + r, cy + r), (cx - r, cy + r)]
    c.fill_polygon(pts, accent, 0.9)
    c.stroke_line(cx - r * 1.2, cy + r, cx + r * 1.2, cy + r, accent, 2)


def draw_building_factory(c: Canvas, accent: RGB, weapon: bool = False) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2, c.size * 0.12
    c.fill_round_rect(cx - r * 1.2, cy - r * 0.4, r * 2.4, r * 1.5, 3, dim(accent, 0.1), 0.9)
    if weapon:
        c.stroke_line(cx, cy - r, cx, cy + r * 0.5, accent, 2.2)
        c.stroke_line(cx - r, cy, cx + r, cy, accent, 2.2)
    else:
        for i in range(3):
            c.fill_disc(cx - r + i * r, cy + r * 0.2, r * 0.22, accent)


def draw_building_barracks(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 4, c.size * 0.11
    for dx in (-1, 1):
        c.fill_round_rect(cx + dx * r * 0.9 - r * 0.55, cy - r, r * 1.1, r * 1.6, 2, dim(accent, 0.12), 0.92)


def draw_building_radar(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 6, c.size * 0.12
    c.stroke_line(cx - r * 1.1, cy + r, cx + r * 1.1, cy + r, accent, 2)
    c.ring(cx, cy, r * 0.9, 1.5, accent, 0.85)
    c.stroke_line(cx, cy, cx + r, cy - r * 0.6, accent, 2)


def draw_building_shield(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 4, c.size * 0.14
    pts = [(cx, cy - r * 1.3), (cx + r * 1.1, cy), (cx, cy + r * 1.1), (cx - r * 1.1, cy)]
    c.fill_polygon(pts, dim(accent, 0.05), 0.85)
    c.ring(cx, cy - r * 0.1, r * 0.85, 1.6, accent, 0.9)


def draw_building_terraform(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 2, c.size * 0.12
    c.fill_disc(cx, cy, r, dim(accent, 0.1), 0.9)
    c.ring(cx, cy, r * 1.15, 1.2, accent, 0.75)


def draw_building_nano(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2, c.size * 0.1
    for ox, oy in [(-1, -1), (1, -1), (-1, 1), (1, 1), (0, 0)]:
        c.fill_disc(cx + ox * r * 1.1, cy + oy * r * 1.1, r * 0.35, accent, 0.88)
        if ox or oy:
            c.stroke_line(cx, cy, cx + ox * r * 1.1, cy + oy * r * 1.1, dim(accent, 0.2), 1.2)


def draw_building_geothermal(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 4, c.size * 0.11
    c.fill_disc(cx, cy, r * 0.55, brighten(accent), 0.9)
    for i in range(3):
        c.ring(cx, cy, r * (0.8 + i * 0.35), 1.2, accent, 0.55 - i * 0.12)


def draw_building_core(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2, c.size * 0.11
    for i in range(4):
        c.ring(cx, cy, r * (0.5 + i * 0.28), 1.3, accent, 0.85 - i * 0.12)
    c.fill_disc(cx, cy, r * 0.35, brighten(accent))


def draw_building_default(c: Canvas, accent: RGB) -> None:
    building_base(c, accent)
    cx, cy = c.size / 2, c.size / 2
    c.fill_disc(cx, cy, c.size * 0.08, accent, 0.9)


BUILDING_DRAW: dict[str, Tuple[RGB, Callable[[Canvas, RGB], None]]] = {
    "metal_mine": (METAL, draw_building_mine),
    "crystal_mine": (CRYSTAL, draw_building_crystal),
    "solar_plant": (ENERGY, draw_building_solar),
    "research_lab": (MUTED, draw_building_lab),
    "academy": ((160, 140, 255), draw_building_lab),
    "metal_storage": ((100, 200, 170), lambda c, a: draw_building_storage(c, a, False)),
    "crystal_storage": ((80, 190, 230), lambda c, a: draw_building_storage(c, a, True)),
    "command_center": ((200, 200, 220), draw_building_tower),
    "shipyard": ((255, 160, 90), draw_building_shipyard),
    "defense_factory": ((255, 110, 110), lambda c, a: draw_building_factory(c, a, True)),
    "barracks": ((255, 140, 100), draw_building_barracks),
    "radar_array": ((120, 255, 180), draw_building_radar),
    "shield_generator": ((100, 220, 255), draw_building_shield),
    "terraformer": ((150, 255, 150), draw_building_terraform),
    "nanofactory": ((180, 160, 255), draw_building_nano),
    "geothermal_nexus": ((255, 180, 80), draw_building_geothermal),
    "planet_core_nexus": ((255, 100, 180), draw_building_core),
    "default": (MUTED, draw_building_default),
}


def building_svg(accent: str, inner: str) -> str:
    return f"""  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#070e20"/><stop offset="100%" stop-color="{accent}" stop-opacity="0.18"/>
    </linearGradient>
  </defs>
  <polygon points="48,8 84,28 84,68 48,88 12,68 12,28" fill="url(#bg)" stroke="{accent}" stroke-width="2" stroke-opacity="0.65"/>
  <g stroke="{accent}" stroke-width="2" fill="{accent}" fill-opacity="0.35" stroke-linecap="round">{inner}</g>"""


# ---------------------------------------------------------------------------
# Forschung-Stil (96×96 Orbital-Ring)
# ---------------------------------------------------------------------------

def research_base(c: Canvas, accent: RGB) -> None:
    s = c.size
    cx = cy = s / 2
    c.ring(cx, cy, s * 0.36, 2.0, accent, 0.55)
    c.ring(cx, cy, s * 0.28, 1.2, dim(accent, 0.2), 0.45)
    c.glow_disc(cx, cy, s * 0.06, accent, 4)
    for deg in (30, 150, 270):
        rad = math.radians(deg)
        px = cx + math.cos(rad) * s * 0.36
        py = cy + math.sin(rad) * s * 0.36
        c.fill_disc(px, py, 2.2, brighten(accent))


def draw_research_coil(c: Canvas, accent: RGB) -> None:
    research_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2, c.size * 0.12
    c.ring(cx, cy, r * 0.9, 2, accent, 0.85)
    c.ring(cx, cy, r * 0.55, 1.6, accent, 0.75)


def draw_research_ingot(c: Canvas, accent: RGB) -> None:
    research_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 2, c.size * 0.12
    pts = [(cx - r, cy + r), (cx + r, cy + r), (cx + r * 0.7, cy - r), (cx - r * 0.7, cy - r)]
    c.fill_polygon(pts, accent, 0.9)


def draw_research_crane(c: Canvas, accent: RGB) -> None:
    research_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 6, c.size * 0.11
    c.stroke_line(cx - r, cy + r, cx - r, cy - r * 1.4, accent, 2.2)
    c.stroke_line(cx - r, cy - r * 1.2, cx + r, cy - r * 0.5, accent, 2)
    c.stroke_line(cx + r, cy - r * 0.5, cx + r, cy + r * 0.2, accent, 1.6)


def draw_research_crates(c: Canvas, accent: RGB) -> None:
    research_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 4, c.size * 0.1
    for dy, sc in [(0, 1.0), (-1, 0.75)]:
        w = r * 1.6 * sc
        c.fill_round_rect(cx - w / 2, cy + dy * r * 0.55 - r * sc, w, r * 1.2 * sc, 2, dim(accent, 0.05), 0.9)


def draw_research_drone(c: Canvas, accent: RGB) -> None:
    research_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2, c.size * 0.1
    c.fill_disc(cx, cy, r * 0.45, accent, 0.85)
    for dx, dy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
        c.fill_disc(cx + dx * r * 1.2, cy + dy * r * 1.2, r * 0.35, accent, 0.8)


def draw_research_nav(c: Canvas, accent: RGB) -> None:
    research_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2, c.size * 0.11
    for dx, dy in [(-1, 0), (1, -0.5), (0.5, 1)]:
        c.fill_disc(cx + dx * r * 1.1, cy + dy * r * 1.1, r * 0.25, accent)
        c.stroke_line(cx, cy, cx + dx * r * 1.1, cy + dy * r * 1.1, dim(accent, 0.15), 1.2)


def draw_research_engine(c: Canvas, accent: RGB) -> None:
    research_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 4, c.size * 0.11
    c.fill_round_rect(cx - r, cy - r * 0.3, r * 2, r * 1.2, 3, dim(accent, 0.08), 0.9)
    for i in range(3):
        c.stroke_line(cx - r * 0.6 + i * r * 0.6, cy + r, cx - r * 0.8 + i * r * 0.5, cy + r * 1.3, accent, 1.6)


def draw_research_weapon(c: Canvas, accent: RGB) -> None:
    research_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2, c.size * 0.12
    c.ring(cx, cy, r, 1.5, accent, 0.85)
    c.stroke_line(cx - r, cy, cx + r, cy, accent, 2)
    c.stroke_line(cx, cy - r, cx, cy + r, accent, 2)


def draw_research_armor(c: Canvas, accent: RGB) -> None:
    research_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2, c.size * 0.12
    for i in range(3):
        c.fill_round_rect(cx - r * 1.1 + i * r * 0.35, cy - r + i * r * 0.25, r * 1.3, r * 1.4, 2, dim(accent, i * 0.08), 0.88)


def draw_research_shield(c: Canvas, accent: RGB) -> None:
    research_base(c, accent)
    cx, cy, r = c.size / 2, c.size / 2 + 2, c.size * 0.13
    pts = [(cx, cy - r * 1.2), (cx + r, cy + r * 0.2), (cx, cy + r), (cx - r, cy + r * 0.2)]
    c.fill_polygon(pts, dim(accent, 0.05), 0.85)
    c.ring(cx, cy, r * 0.75, 1.4, accent, 0.85)


RESEARCH_DRAW: dict[str, Tuple[RGB, Callable[[Canvas, RGB], None]]] = {
    "energieeffizienz.png": (ENERGY, draw_research_coil),
    "metallveredelung.png": (METAL, draw_research_ingot),
    "bauoptimierung.png": ((140, 180, 255), draw_research_crane),
    "lagertechnik.png": ((180, 140, 255), draw_research_crates),
    "drohnenoptimierung.png": ((100, 220, 200), draw_research_drone),
    "hyperraum-navigation.png": (CRYSTAL, draw_research_nav),
    "kryo-antriebstechnik.png": ((120, 200, 255), draw_research_engine),
    "waffenentwicklung.png": ((255, 120, 120), draw_research_weapon),
    "panzerungstechnik.png": ((180, 180, 200), draw_research_armor),
    "schildtechnologie.png": (NEON, draw_research_shield),
}


def research_svg(accent: str, inner: str) -> str:
    return f"""  <circle cx="48" cy="48" r="34" fill="none" stroke="{accent}" stroke-opacity="0.55" stroke-width="2"/>
  <circle cx="48" cy="48" r="26" fill="none" stroke="{accent}" stroke-opacity="0.25" stroke-width="1.2"/>
  <g stroke="{accent}" stroke-width="2" fill="{accent}" fill-opacity="0.35" stroke-linecap="round">{inner}</g>"""


RESEARCH_SVG_INNER = {
    "energieeffizienz.png": '<circle cx="48" cy="48" r="10" fill="none"/><circle cx="48" cy="48" r="6" fill="none"/>',
    "metallveredelung.png": '<polygon points="36,58 60,58 52,36 44,36"/>',
    "bauoptimierung.png": '<path d="M32 62 L32 30 L62 42 L62 52" fill="none"/>',
    "lagertechnik.png": '<rect x="34" y="44" width="28" height="14" rx="2"/><rect x="38" y="34" width="20" height="10" rx="2"/>',
    "drohnenoptimierung.png": '<circle cx="48" cy="48" r="6"/><circle cx="30" cy="32" r="4"/><circle cx="66" cy="32" r="4"/><circle cx="30" cy="64" r="4"/><circle cx="66" cy="64" r="4"/>',
    "hyperraum-navigation.png": '<circle cx="34" cy="48" r="3"/><circle cx="58" cy="40" r="3"/><circle cx="52" cy="60" r="3"/>',
    "kryo-antriebstechnik.png": '<rect x="36" y="42" width="24" height="12" rx="2"/><path d="M38 58 L42 64 M48 58 L48 66 M54 58 L50 64" fill="none"/>',
    "waffenentwicklung.png": '<circle cx="48" cy="48" r="10" fill="none"/><path d="M38 48 H58 M48 38 V58" fill="none"/>',
    "panzerungstechnik.png": '<rect x="34" y="40" width="28" height="16" rx="2"/><rect x="38" y="46" width="20" height="12" rx="2"/>',
    "schildtechnologie.png": '<path d="M48 34 C58 40 58 56 48 62 C38 56 38 40 48 34 Z"/>',
}


BUILDING_SVG_INNER = {
    "metal_mine": '<path d="M36 58 L42 36 L48 58 M48 58 L54 36 L60 58" fill="none"/>',
    "crystal_mine": '<polygon points="48,32 58,46 52,62 44,62 38,46"/>',
    "solar_plant": '<circle cx="48" cy="48" r="8"/><g stroke-width="1.5"><path d="M48 32 V28 M48 68 V64 M32 48 H28 M68 48 H64"/></g>',
    "default": '<circle cx="48" cy="48" r="6"/>',
}


def render_building(key: str, size: int = 96) -> Canvas:
    accent, draw_fn = BUILDING_DRAW.get(key, BUILDING_DRAW["default"])
    c = Canvas(size)
    draw_fn(c, accent)
    return c


def render_research(fname: str, size: int = 96) -> Canvas:
    accent, draw_fn = RESEARCH_DRAW[fname]
    c = Canvas(size)
    draw_fn(c, accent)
    return c


def main() -> None:
    accent_hex_map = {"ferronit": "#7fffd9", "crytite": "#46e5ff", "energy": "#ffc400"}
    resource_inner = {
        "ferronit": '<path d="M18 38 L42 18 M24 20 L44 34" fill="none"/>',
        "crytite": '<polygon points="32,14 44,28 38,46 26,46 20,28" fill-opacity="0.35"/>',
        "energy": '<polygon points="34,14 26,32 32,32 28,50 40,30 34,30"/>',
    }

    # --- Ressourcen (64px PNG + SVG) ---
    for name, (accent, draw_fn, _svg_tpl) in RESOURCES.items():
        c = Canvas(64)
        draw_resource_chip(c, accent, draw_fn)
        c.to_png(STATIC / "icons" / f"{name}.png")
        write_svg(
            STATIC / "icons" / f"{name}.svg",
            resource_svg(name, accent_hex_map[name], resource_inner[name]),
            "0 0 64 64",
        )

    # --- Gebäude ---
    for key in BUILDINGS:
        render_building(key).to_png(STATIC / "img" / "buildings" / f"{key}.png")
        accent_hex = "#%02x%02x%02x" % BUILDING_DRAW.get(key, BUILDING_DRAW["default"])[0]
        inner = BUILDING_SVG_INNER.get(key, BUILDING_SVG_INNER["default"])
        write_svg(STATIC / "img" / "buildings" / f"{key}.svg", building_svg(accent_hex, inner))

    render_building("default").to_png(STATIC / "img" / "buildings" / "default.png")
    write_svg(STATIC / "img" / "buildings" / "default.svg", building_svg("#78beff", BUILDING_SVG_INNER["default"]))

    # --- Forschung ---
    for fname in RESEARCH_FILES:
        render_research(fname).to_png(STATIC / "img" / "research" / fname)
        accent = RESEARCH_DRAW[fname][0]
        accent_hex = "#%02x%02x%02x" % accent
        inner = RESEARCH_SVG_INNER[fname]
        write_svg(STATIC / "img" / "research" / fname.replace(".png", ".svg"), research_svg(accent_hex, inner))

    print(f"[v1.6] Generated sci-fi icons under {STATIC}")


if __name__ == "__main__":
    main()
