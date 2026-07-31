"""Convert commander role icons (JPG/GIF near-black matte) to transparent WebP.

Prefer *.jpg over *.gif. Widescreen sources keep aspect (max edge --max-edge).
Square pad when --square. Cleanup removes jpg/gif/svg/bulk after success.

Usage:
  python scripts/process_commander_role_icons.py --cleanup --max-edge 640
  python scripts/process_commander_role_icons.py --dry-run
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ICON_DIR = ROOT / "static" / "img" / "classes" / "icons"

ALIASES = {"amor": "armor"}

ROLE_KEYS = (
    "weapon",
    "armor",
    "shield",
    "raid",
    "production",
    "build",
    "storage",
    "industry",
    "research",
    "codex",
    "data",
    "lab",
    "fleet",
    "cargo",
    "fuel",
    "shipyard",
    "scan",
    "support",
    "signal",
)


def defringe_rgba(
    im: Image.Image,
    *,
    thresh: int = 40,
    soft: int = 28,
    white: int = 245,
) -> Image.Image:
    """Near-black and near-white backgrounds → transparent with soft fringe."""
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


def crop_to_content(im: Image.Image, *, pad: int = 8) -> Image.Image:
    alpha = im.split()[-1]
    bbox = alpha.getbbox()
    if not bbox:
        return im
    l, t, r, b = bbox
    l = max(0, l - pad)
    t = max(0, t - pad)
    r = min(im.width, r + pad)
    b = min(im.height, b + pad)
    return im.crop((l, t, r, b))


def fit_max_edge(im: Image.Image, max_edge: int) -> Image.Image:
    w, h = im.size
    m = max(w, h)
    if m <= max_edge:
        return im
    scale = max_edge / float(m)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    return im.resize((nw, nh), Image.Resampling.LANCZOS)


def square_pad(im: Image.Image, size: int) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    src = im.copy()
    src.thumbnail((size, size), Image.Resampling.LANCZOS)
    x = (size - src.width) // 2
    y = (size - src.height) // 2
    canvas.paste(src, (x, y), src)
    return canvas


def resolve_sources() -> dict[str, Path]:
    """Prefer JPG, then GIF."""
    found: dict[str, Path] = {}
    for pattern in ("*.jpg", "*.jpeg", "*.gif"):
        for path in sorted(ICON_DIR.glob(pattern)):
            stem = path.stem.lower()
            key = ALIASES.get(stem, stem)
            if key in ROLE_KEYS and key not in found:
                found[key] = path
    return found


def process_one(
    src: Path,
    dest: Path,
    *,
    thresh: int,
    soft: int,
    max_edge: int,
    square: int | None,
    dry_run: bool,
) -> dict:
    with Image.open(src) as im:
        try:
            im.seek(0)
        except EOFError:
            pass
        rgba = defringe_rgba(im, thresh=thresh, soft=soft)
        rgba = crop_to_content(rgba, pad=6)
        if square:
            rgba = square_pad(rgba, square)
        else:
            rgba = fit_max_edge(rgba, max_edge)
        corner = rgba.getpixel((0, 0))
        mid = rgba.getpixel((rgba.width // 2, rgba.height // 2))
        info = {
            "src": src.name,
            "dest": dest.name,
            "corner_a": corner[3],
            "mid_a": mid[3],
            "size": rgba.size,
            "bytes": 0,
        }
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            rgba.save(dest, format="WEBP", lossless=True, method=6)
            info["bytes"] = dest.stat().st_size
        return info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--thresh", type=int, default=40)
    ap.add_argument("--soft", type=int, default=28)
    ap.add_argument("--max-edge", type=int, default=640, help="Max edge for widescreen WebP")
    ap.add_argument(
        "--square",
        type=int,
        default=0,
        help="If >0, force square pad to this size instead of widescreen",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove *.jpg/*.jpeg/*.gif/*.svg and icon_bulk.png after write",
    )
    args = ap.parse_args()

    sources = resolve_sources()
    missing = [k for k in ROLE_KEYS if k not in sources]
    if missing:
        print(f"ERROR missing sources for: {', '.join(missing)}")
        return 1

    square = int(args.square) or None
    ok = 0
    for key in ROLE_KEYS:
        src = sources[key]
        dest = ICON_DIR / f"{key}.webp"
        info = process_one(
            src,
            dest,
            thresh=args.thresh,
            soft=args.soft,
            max_edge=args.max_edge,
            square=square,
            dry_run=args.dry_run,
        )
        print(
            f"{info['src']} -> {info['dest']} "
            f"corner_a={info['corner_a']} mid_a={info['mid_a']} "
            f"size={info['size']} bytes={info['bytes']}"
        )
        ok += 1

    print(f"{'would write' if args.dry_run else 'wrote'} {ok} webp icons -> {ICON_DIR}")

    if args.cleanup and not args.dry_run:
        removed = 0
        for pat in ("*.jpg", "*.jpeg", "*.gif", "*.svg"):
            for p in list(ICON_DIR.glob(pat)):
                p.unlink(missing_ok=True)
                removed += 1
        bulk = ICON_DIR / "icon_bulk.png"
        if bulk.exists():
            bulk.unlink()
            removed += 1
        print(f"cleanup removed {removed} files")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
