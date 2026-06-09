#!/usr/bin/env python3
"""GC-549 — Lossless-ish resize/compress for static/img card assets and landscapes."""

from __future__ import annotations

import argparse
import io
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
IMG_ROOT = ROOT / "static" / "img"

CARD_DIRS = ("ships", "research", "defense", "buildings", "res", "badges")
CARD_MAX_WIDTH = 512
PNG_COMPRESS_LEVEL = 9
JPEG_CARD_QUALITY = 85

LANDSCAPES_DIR = "landscapes"
LANDSCAPE_MAX_WIDTH = 1280
LANDSCAPE_JPEG_QUALITY = 78

RASTER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _human_kb(n: int) -> str:
    return f"{n / 1024:.0f} KB"


def _resize_if_needed(im: Image.Image, max_width: int) -> Image.Image:
    w, h = im.size
    if w <= max_width:
        return im
    ratio = max_width / w
    return im.resize((max_width, max(1, int(h * ratio))), Image.Resampling.LANCZOS)


def _save_raster(im: Image.Image, path: Path, *, dry_run: bool) -> int:
    suffix = path.suffix.lower()
    buf = io.BytesIO()

    if suffix == ".png":
        if im.mode not in ("RGBA", "LA"):
            if im.mode == "P" and "transparency" in im.info:
                im = im.convert("RGBA")
            elif "A" in im.getbands():
                im = im.convert("RGBA")
            else:
                im = im.convert("RGB")
        im.save(buf, "PNG", optimize=True, compress_level=PNG_COMPRESS_LEVEL)
    elif suffix == ".webp":
        has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        if has_alpha:
            im = im.convert("RGBA")
            im.save(buf, "WEBP", quality=82, method=6, lossless=False)
        else:
            im = im.convert("RGB")
            im.save(buf, "WEBP", quality=82, method=6)
    else:
        im = im.convert("RGB")
        im.save(buf, "JPEG", quality=JPEG_CARD_QUALITY, optimize=True, subsampling=2)

    data = buf.getvalue()
    if not dry_run:
        path.write_bytes(data)
    return len(data)


def _landscape_target(path: Path) -> Path:
    if path.suffix.lower() == ".png":
        return path.with_suffix(".jpg")
    return path


def optimize_card_file(path: Path, *, dry_run: bool = False) -> tuple[int, int]:
    before = path.stat().st_size
    with Image.open(path) as im:
        im = _resize_if_needed(im, CARD_MAX_WIDTH)
        after = _save_raster(im, path, dry_run=dry_run)
    return before, after


def optimize_landscape_file(path: Path, *, dry_run: bool = False) -> tuple[int, int, Path]:
    before = path.stat().st_size
    target = _landscape_target(path)

    with Image.open(path) as im:
        im = im.convert("RGB")
        im = _resize_if_needed(im, LANDSCAPE_MAX_WIDTH)

        if dry_run:
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=LANDSCAPE_JPEG_QUALITY, optimize=True, subsampling=2)
            return before, len(buf.getvalue()), target

        im.save(target, "JPEG", quality=LANDSCAPE_JPEG_QUALITY, optimize=True, subsampling=2)
        after = target.stat().st_size
        if target != path and path.exists():
            path.unlink()
        return before, after, target


def iter_card_files(base: Path) -> list[Path]:
    files: list[Path] = []
    for sub in CARD_DIRS:
        folder = base / sub
        if not folder.is_dir():
            continue
        for path in sorted(folder.rglob("*")):
            if path.suffix.lower() in RASTER_SUFFIXES:
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
    parser = argparse.ArgumentParser(description="Optimize static/img raster assets (GC-549).")
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
        if card_files:
            print(f"=== Card assets ({len(card_files)} files, max {CARD_MAX_WIDTH}px) ===")
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
