"""Process commander skill arts: PNG/JPG → transparent WebP under skills/.

Reads static/img/classes/skills/_src/{skill_key}.png (or repo assets/),
defringes near-black/near-white, max-edge 512, writes
static/img/classes/skills/{skill_key}.webp.

Usage:
  python scripts/process_commander_skill_arts.py
  python scripts/process_commander_skill_arts.py --cleanup-src
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "static" / "img" / "classes" / "skills"
SRC_DIR = SKILL_DIR / "_src"
# GenerateImage often lands here in Cursor projects
ASSETS_FALLBACK = Path(
    r"C:\Users\gurge\.cursor\projects\c-Users-gurge-Desktop-RandomStuff-Coding-Genesis-Colonies\assets"
)

# Must match game.commander_class_catalog.SKILLS keys
SKILL_KEYS = (
    "vanguard_strike_doctrine",
    "vanguard_hull_focus",
    "vanguard_barrier",
    "vanguard_assault_protocol",
    "vanguard_apex_raider",
    "vanguard_war_sovereign",
    "forge_extraction",
    "forge_nanoforge",
    "forge_vaults",
    "forge_industrial_surge",
    "forge_planetforge",
    "forge_omniforge",
    "archivist_codex",
    "archivist_lab_network",
    "archivist_deep_archive",
    "archivist_synthesis",
    "archivist_omniscience",
    "archivist_prime_axiom",
    "admiral_warp_lanes",
    "admiral_hold_capacity",
    "admiral_fuel_thrift",
    "admiral_dockyard",
    "admiral_armada",
    "admiral_void_crown",
    "envoy_signal_net",
    "envoy_logistics_aid",
    "envoy_shield_doctrine",
    "envoy_rapid_response",
    "envoy_grand_mandate",
    "envoy_galactic_voice",
)


def defringe_rgba(
    im: Image.Image,
    *,
    thresh: int = 28,
    soft: int = 22,
    white: int = 248,
) -> Image.Image:
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    hard = float(thresh)
    soft_end = float(thresh + max(1, soft))
    white_hard = float(white)
    white_soft = float(max(1, soft))
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            mx = max(r, g, b)
            mn = min(r, g, b)
            if mx <= hard:
                px[x, y] = (r, g, b, 0)
            elif mx < soft_end:
                t = (mx - hard) / (soft_end - hard)
                px[x, y] = (r, g, b, int(round(a * t)))
            elif mn >= white_hard:
                px[x, y] = (r, g, b, 0)
            elif mn > white_hard - white_soft:
                t = (white_hard - mn) / white_soft
                px[x, y] = (r, g, b, int(round(a * max(0.0, t))))
    return rgba


def crop_to_content(im: Image.Image, *, pad: int = 4) -> Image.Image:
    bbox = im.split()[-1].getbbox()
    if not bbox:
        return im
    l, t, r, b = bbox
    return im.crop(
        (
            max(0, l - pad),
            max(0, t - pad),
            min(im.width, r + pad),
            min(im.height, b + pad),
        )
    )


def fit_max_edge(im: Image.Image, max_edge: int) -> Image.Image:
    m = max(im.size)
    if m <= max_edge:
        return im
    scale = max_edge / float(m)
    nw = max(1, int(round(im.width * scale)))
    nh = max(1, int(round(im.height * scale)))
    return im.resize((nw, nh), Image.Resampling.LANCZOS)


def resolve_src(key: str) -> Path | None:
    for base in (SRC_DIR, ASSETS_FALLBACK, SKILL_DIR):
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            p = base / f"{key}{ext}"
            if p.is_file():
                return p
    return None


def process_one(src: Path, dest: Path, *, max_edge: int, dry_run: bool) -> dict:
    with Image.open(src) as im:
        # Downscale first — pure-Python defringe is O(pixels)
        rgba = im.convert("RGBA")
        rgba = fit_max_edge(rgba, max_edge)
        rgba = defringe_rgba(rgba)
        rgba = crop_to_content(rgba)
        size = max(rgba.size)
        canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        x = (size - rgba.width) // 2
        y = (size - rgba.height) // 2
        canvas.paste(rgba, (x, y), rgba)
        canvas = fit_max_edge(canvas, max_edge)
        info = {"src": src.name, "dest": dest.name, "size": canvas.size, "bytes": 0}
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            canvas.save(dest, format="WEBP", quality=82, method=6)
            info["bytes"] = dest.stat().st_size
            if info["bytes"] > 130_000:
                canvas.save(dest, format="WEBP", quality=70, method=6)
                info["bytes"] = dest.stat().st_size
        return info


def gather_sources() -> None:
    """Copy from Cursor assets/ into _src if missing."""
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    if not ASSETS_FALLBACK.is_dir():
        return
    for key in SKILL_KEYS:
        dest = SRC_DIR / f"{key}.png"
        if dest.exists():
            continue
        src = ASSETS_FALLBACK / f"{key}.png"
        if src.is_file():
            shutil.copy2(src, dest)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-edge", type=int, default=512)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--cleanup-src", action="store_true", help="Remove _src after write")
    args = ap.parse_args()

    gather_sources()
    missing = []
    ok = 0
    for key in SKILL_KEYS:
        src = resolve_src(key)
        if not src:
            missing.append(key)
            continue
        dest = SKILL_DIR / f"{key}.webp"
        info = process_one(src, dest, max_edge=args.max_edge, dry_run=args.dry_run)
        print(
            f"{info['src']} -> {info['dest']} size={info['size']} bytes={info['bytes']}"
        )
        ok += 1

    if missing:
        print(f"ERROR missing sources: {', '.join(missing)}")
        return 1

    print(f"{'would write' if args.dry_run else 'wrote'} {ok} skill webps -> {SKILL_DIR}")

    if args.cleanup_src and not args.dry_run and SRC_DIR.is_dir():
        removed = 0
        for p in list(SRC_DIR.glob("*")):
            if p.is_file():
                p.unlink()
                removed += 1
        print(f"cleanup-src removed {removed} files")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
