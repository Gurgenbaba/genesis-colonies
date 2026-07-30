#!/usr/bin/env python3
"""GC-549 / GC-PERF-IMG-003 — Budget compress for static/img card assets.

Usage:
  python tools/optimize_images.py --dry-run
  python tools/optimize_images.py
  python tools/optimize_images.py --only buildings
"""

from __future__ import annotations

import argparse
import io
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
IMG_ROOT = ROOT / "static" / "img"

CARD_DIRS = (
    "ships",
    "research",
    "defense",
    "buildings",
    "res",
    "badges",
    "evo",
    "lootboxes",
    "vote",
    "pass",
    "bosses",
    "shop",
)
CARD_MAX_WIDTH = 360
CARD_MAX_WIDTH_BY_DIR = {
    "vote": 480,
    "pass": 480,
    "bosses": 512,
    "evo": 256,
    "badges": 256,
    "shop": 480,
}
CARD_WEBP_MAX = 80_000
CARD_PNG_MAX = 180_000
CARD_JPG_MAX = 180_000

LANDSCAPES_DIR = "landscapes"
LANDSCAPE_MAX_WIDTH = 1280
LANDSCAPE_WEBP_MAX = 160_000
LANDSCAPE_JPG_MAX = 220_000

RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _human_kb(n: int) -> str:
    return f"{n / 1024:.0f} KB"


def _resize_if_needed(im: Image.Image, max_width: int) -> Image.Image:
    w, h = im.size
    if w <= max_width:
        return im
    ratio = max_width / w
    return im.resize((max_width, max(1, int(h * ratio))), Image.Resampling.LANCZOS)


def _save_webp_budget(im: Image.Image, path: Path, *, max_bytes: int, dry_run: bool) -> int:
    work = im
    if work.mode not in ("RGB", "RGBA"):
        work = work.convert("RGBA" if "A" in work.getbands() else "RGB")
    for quality in (82, 78, 74, 70, 66, 62, 58, 54, 50, 46, 42):
        buf = io.BytesIO()
        work.save(buf, "WEBP", quality=quality, method=6)
        data = buf.getvalue()
        if len(data) <= max_bytes or quality <= 42:
            if not dry_run:
                path.write_bytes(data)
            return len(data)
    return 0


def _save_png_budget(im: Image.Image, path: Path, *, max_bytes: int, dry_run: bool) -> int:
    work = im
    if work.mode not in ("RGBA", "RGB"):
        work = work.convert("RGBA" if "A" in work.getbands() else "RGB")
    max_w = work.size[0]
    while max_w >= 160:
        trial = _resize_if_needed(work, max_w) if max_w < work.size[0] else work
        for compress in (9, 8, 7, 6):
            buf = io.BytesIO()
            trial.save(buf, "PNG", optimize=True, compress_level=compress)
            data = buf.getvalue()
            if len(data) <= max_bytes:
                if not dry_run:
                    path.write_bytes(data)
                return len(data)
        max_w = int(max_w * 0.85)
        work = _resize_if_needed(work, max_w)
    buf = io.BytesIO()
    work.save(buf, "PNG", optimize=True, compress_level=6)
    data = buf.getvalue()
    if not dry_run:
        path.write_bytes(data)
    return len(data)


def _save_jpeg_budget(im: Image.Image, path: Path, *, max_bytes: int, dry_run: bool) -> int:
    work = im.convert("RGB")
    max_w = work.size[0]
    while max_w >= 160:
        trial = _resize_if_needed(work, max_w) if max_w < work.size[0] else work
        for quality in (82, 78, 74, 70, 66, 62, 58, 54, 50, 46, 42):
            buf = io.BytesIO()
            trial.save(buf, "JPEG", quality=quality, optimize=True, subsampling=2)
            data = buf.getvalue()
            if len(data) <= max_bytes or quality <= 42:
                if not dry_run:
                    path.write_bytes(data)
                return len(data)
        max_w = int(max_w * 0.85)
        work = _resize_if_needed(work, max_w)
    buf = io.BytesIO()
    work.save(buf, "JPEG", quality=50, optimize=True, subsampling=2)
    data = buf.getvalue()
    if not dry_run:
        path.write_bytes(data)
    return len(data)


def card_max_width_for(path: Path) -> int:
    return int(CARD_MAX_WIDTH_BY_DIR.get(path.parent.name, CARD_MAX_WIDTH))


def optimize_card_file(path: Path, *, dry_run: bool = False) -> tuple[int, int]:
    """Compress source + ensure sibling WebP under budgets."""
    before = path.stat().st_size
    suffix = path.suffix.lower()
    # Skip responsive herocard variants and already-budgeted webp-only rewrites
    # when iterating webp that has a png/jpg sibling — we rewrite from source.
    if suffix == ".webp":
        for alt in (".png", ".jpg", ".jpeg"):
            if path.with_suffix(alt).is_file():
                return before, before
    max_width = card_max_width_for(path)
    with Image.open(path) as im:
        has_alpha = "A" in im.getbands() or (im.mode == "P" and "transparency" in im.info)
        base = im.convert("RGBA" if has_alpha and suffix == ".png" else "RGB")
        base = _resize_if_needed(base, max_width)
        if suffix == ".png":
            after = _save_png_budget(base, path, max_bytes=CARD_PNG_MAX, dry_run=dry_run)
            webp_path = path.with_suffix(".webp")
            _save_webp_budget(base, webp_path, max_bytes=CARD_WEBP_MAX, dry_run=dry_run)
        elif suffix in (".jpg", ".jpeg"):
            after = _save_jpeg_budget(base, path, max_bytes=CARD_JPG_MAX, dry_run=dry_run)
            webp_path = path.with_suffix(".webp")
            _save_webp_budget(base, webp_path, max_bytes=CARD_WEBP_MAX, dry_run=dry_run)
        else:
            after = _save_webp_budget(base, path, max_bytes=CARD_WEBP_MAX, dry_run=dry_run)
    return before, after


def optimize_landscape_file(path: Path, *, dry_run: bool = False) -> tuple[int, int, Path]:
    before = path.stat().st_size
    target = path if path.suffix.lower() != ".png" else path.with_suffix(".jpg")
    with Image.open(path) as im:
        im = im.convert("RGB")
        im = _resize_if_needed(im, LANDSCAPE_MAX_WIDTH)
        after = _save_jpeg_budget(im, target, max_bytes=LANDSCAPE_JPG_MAX, dry_run=dry_run)
        _save_webp_budget(im, target.with_suffix(".webp"), max_bytes=LANDSCAPE_WEBP_MAX, dry_run=dry_run)
        if not dry_run and target != path and path.exists():
            path.unlink()
    return before, after, target


def iter_card_files(base: Path) -> list[Path]:
    files: list[Path] = []
    for sub in CARD_DIRS:
        folder = base / sub
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in RASTER_SUFFIXES:
                continue
            # Skip responsive herocard-style variants if ever present
            if "-sm." in path.name or "-md." in path.name or "-lg." in path.name:
                continue
            files.append(path)
    return files


def iter_landscape_files(base: Path) -> list[Path]:
    folder = base / LANDSCAPES_DIR
    if not folder.is_dir():
        return []
    candidates = sorted(folder.glob("*-h.png")) + sorted(folder.glob("*-h.jpg"))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        if path.stem in seen:
            continue
        seen.add(path.stem)
        unique.append(path)
    return unique


def run_card_pass(files: list[Path], *, dry_run: bool) -> tuple[int, int]:
    total_before = 0
    total_after = 0
    for path in files:
        before, after = optimize_card_file(path, dry_run=dry_run)
        total_before += before
        total_after += after
        pct = (1 - after / before) * 100 if before else 0
        rel = path.relative_to(ROOT)
        print(f"{rel}  {_human_kb(before)} -> {_human_kb(after)}  ({pct:.0f}% smaller)")
    return total_before, total_after


def run_landscape_pass(files: list[Path], *, dry_run: bool) -> tuple[int, int]:
    total_before = 0
    total_after = 0
    for path in files:
        before, after, target = optimize_landscape_file(path, dry_run=dry_run)
        total_before += before
        total_after += after
        pct = (1 - after / before) * 100 if before else 0
        arrow = "->" if target == path else f"-> {target.name}"
        print(f"{path.name} {arrow} {_human_kb(after)} ({pct:.0f}% smaller, was {_human_kb(before)})")
    return total_before, total_after


def main() -> None:
    parser = argparse.ArgumentParser(description="Optimize static/img raster assets (GC-PERF-IMG).")
    parser.add_argument("--dry-run", action="store_true", help="Report sizes only; do not write files.")
    parser.add_argument(
        "--only",
        choices=("all", *CARD_DIRS, LANDSCAPES_DIR),
        default="all",
        help="Restrict to one asset group (default: all).",
    )
    args = parser.parse_args()

    run_cards = args.only in ("all", *CARD_DIRS)
    run_landscapes = args.only in ("all", LANDSCAPES_DIR)

    grand_before = 0
    grand_after = 0

    if run_cards:
        card_files = iter_card_files(IMG_ROOT)
        if args.only != "all" and args.only in CARD_DIRS:
            card_files = [p for p in card_files if p.parts[-2] == args.only]
        # Prefer sources (png/jpg) so we don't double-process webp siblings
        card_files = [p for p in card_files if p.suffix.lower() != ".webp"]
        if card_files:
            print(f"=== Card assets ({len(card_files)} files) ===")
            b, a = run_card_pass(card_files, dry_run=args.dry_run)
            grand_before += b
            grand_after += a
            print()

    if run_landscapes:
        landscape_files = iter_landscape_files(IMG_ROOT)
        if landscape_files:
            print(f"=== Landscapes ({len(landscape_files)} files, max {LANDSCAPE_MAX_WIDTH}px) ===")
            b, a = run_landscape_pass(landscape_files, dry_run=args.dry_run)
            grand_before += b
            grand_after += a
            print()

    if grand_before == 0:
        raise SystemExit("No raster files matched the selected scope.")

    pct = (1 - grand_after / grand_before) * 100 if grand_before else 0
    print(
        f"Total: {grand_before / 1024 / 1024:.2f} MB -> {grand_after / 1024 / 1024:.2f} MB "
        f"({pct:.0f}% smaller)"
    )
    if args.dry_run:
        print("(dry run — no files written)")


if __name__ == "__main__":
    main()
