"""Optimize planet landscape backgrounds under static/img/landscapes/."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
LANDSCAPES = ROOT / "static" / "img" / "landscapes"

# Fullscreen backgrounds with dark overlays — 1280px JPEG keeps the repo small.
MAX_WIDTH = 1280
JPEG_QUALITY = 78


def _target_path(path: Path) -> Path:
    if path.suffix.lower() == ".png":
        return path.with_suffix(".jpg")
    return path


def optimize_file(path: Path, *, dry_run: bool = False) -> tuple[int, int, Path]:
    before = path.stat().st_size
    target = _target_path(path)

    with Image.open(path) as im:
        im = im.convert("RGB")
        w, h = im.size
        if w > MAX_WIDTH:
            ratio = MAX_WIDTH / w
            im = im.resize((MAX_WIDTH, int(h * ratio)), Image.Resampling.LANCZOS)

        if dry_run:
            import io

            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True, subsampling=2)
            after = len(buf.getvalue())
            return before, after, target

        im.save(target, "JPEG", quality=JPEG_QUALITY, optimize=True, subsampling=2)
        after = target.stat().st_size
        if target != path and path.exists():
            path.unlink()
        return before, after, target


def main() -> None:
    parser = argparse.ArgumentParser(description="Compress planet landscape backgrounds.")
    parser.add_argument("--dry-run", action="store_true", help="Report sizes only.")
    args = parser.parse_args()

    files = sorted(LANDSCAPES.glob("*-h.png")) + sorted(LANDSCAPES.glob("*-h.jpg"))
    seen: set[str] = set()
    unique: list[Path] = []
    for path in files:
        stem = path.stem
        if stem in seen:
            continue
        seen.add(stem)
        unique.append(path)

    if not unique:
        raise SystemExit(f"No landscape files in {LANDSCAPES}")

    total_before = 0
    total_after = 0
    for path in unique:
        before, after, target = optimize_file(path, dry_run=args.dry_run)
        total_before += before
        total_after += after
        pct = (1 - after / before) * 100 if before else 0
        arrow = "->" if target == path else f"-> {target.name}"
        print(f"{path.name} {arrow} {after/1024:.0f} KB ({pct:.0f}% smaller, was {before/1024:.0f} KB)")

    print(
        f"\nTotal: {total_before/1024/1024:.2f} MB -> {total_after/1024/1024:.2f} MB "
        f"({(1-total_after/total_before)*100:.0f}% smaller)"
    )
    if args.dry_run:
        print("(dry run — no files written)")


if __name__ == "__main__":
    main()
