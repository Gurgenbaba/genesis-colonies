#!/usr/bin/env python3
"""
GC-860B / GC-PERF-IMG — P0 + shell asset compression.

Scope: background, map, herocards, herocardsframe, expedition, landscapes, debris.

Usage:
  python tools/compress_p0_assets.py --dry-run
  python tools/compress_p0_assets.py
  python tools/compress_p0_assets.py --report docs/GC-860B_p0_compression_report.md
"""
from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow required: pip install Pillow") from exc

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "static" / "img"

# Budgets (bytes)
MAX_ROOT_VARIANT = 500_000
HEROCARD_SM_MAX = 80_000
HEROCARD_MD_MAX = 150_000
HEROCARD_LG_MAX = 280_000
FRAME_WEBP_MAX = 120_000
FRAME_PNG_MAX = 350_000
FRAME_MAX_W = 1024
EXPEDITION_WEBP_MAX = 180_000
EXPEDITION_PNG_MAX = 400_000
EXPEDITION_MAX_W = 960
LANDSCAPE_WEBP_MAX = 160_000
LANDSCAPE_JPG_MAX = 220_000
LANDSCAPE_MAX_W = 1280
DEBRIS_WEBP_MAX = 80_000
DEBRIS_JPG_MAX = 150_000
DEBRIS_MAX_W = 640

BACKGROUND_MAX_W = 1600
MAP_MAX_W = 1280
HEROCARD_SM_W = 320
HEROCARD_MD_W = 560
HEROCARD_LG_W = 840
HEROCARD_PNG_W = 560


@dataclass
class Result:
    path: str
    before: int
    after: int
    width: int
    height: int
    note: str = ""


def _human(n: int) -> str:
    return f"{n / 1024:.0f} KB"


def _resize(im: Image.Image, max_w: int) -> Image.Image:
    w, h = im.size
    if w <= max_w:
        return im
    ratio = max_w / w
    return im.resize((max_w, max(1, int(h * ratio))), Image.Resampling.LANCZOS)


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
    while max_w >= 320:
        trial = _resize(work, max_w) if max_w < work.size[0] else work
        for compress in (9, 8, 7, 6):
            buf = io.BytesIO()
            trial.save(buf, "PNG", optimize=True, compress_level=compress)
            data = buf.getvalue()
            if len(data) <= max_bytes:
                if not dry_run:
                    path.write_bytes(data)
                return len(data)
        max_w = int(max_w * 0.85)
        work = _resize(work, max_w)
    buf = io.BytesIO()
    work.save(buf, "PNG", optimize=True, compress_level=6)
    data = buf.getvalue()
    if not dry_run:
        path.write_bytes(data)
    return len(data)


def _save_jpeg_budget(im: Image.Image, path: Path, *, max_bytes: int, dry_run: bool) -> int:
    work = im.convert("RGB")
    max_w = work.size[0]
    while max_w >= 320:
        trial = _resize(work, max_w) if max_w < work.size[0] else work
        for quality in (82, 78, 74, 70, 66, 62, 58, 54, 50, 46, 42):
            buf = io.BytesIO()
            trial.save(buf, "JPEG", quality=quality, optimize=True, subsampling=2)
            data = buf.getvalue()
            if len(data) <= max_bytes or quality <= 42:
                if not dry_run:
                    path.write_bytes(data)
                return len(data)
        max_w = int(max_w * 0.85)
        work = _resize(work, max_w)
    buf = io.BytesIO()
    work.save(buf, "JPEG", quality=50, optimize=True, subsampling=2)
    data = buf.getvalue()
    if not dry_run:
        path.write_bytes(data)
    return len(data)


def _compress_root_pair(name: str, *, max_w: int, dry_run: bool) -> list[Result]:
    out: list[Result] = []
    png_path = IMG / f"{name}.png"
    webp_path = IMG / f"{name}.webp"
    if not png_path.is_file():
        return out
    before_png = png_path.stat().st_size
    with Image.open(png_path) as im:
        im = _resize(im.convert("RGB"), max_w)
        w, h = im.size
        after_png = _save_png_budget(im, png_path, max_bytes=MAX_ROOT_VARIANT, dry_run=dry_run)
        after_webp = _save_webp_budget(im, webp_path, max_bytes=MAX_ROOT_VARIANT, dry_run=dry_run)
    out.append(
        Result(
            f"static/img/{name}.png",
            before_png,
            after_png,
            w,
            h,
            note=f"max_w={max_w}",
        )
    )
    before_webp = webp_path.stat().st_size if webp_path.exists() else 0
    out.append(
        Result(
            f"static/img/{name}.webp",
            before_webp,
            after_webp,
            w,
            h,
            note="webp variant",
        )
    )
    return out


def _compress_herocard(path: Path, *, dry_run: bool) -> list[Result]:
    out: list[Result] = []
    if path.suffix.lower() != ".png":
        return out
    stem = path.stem
    before = path.stat().st_size
    with Image.open(path) as im:
        base = im.convert("RGBA") if "A" in im.getbands() else im.convert("RGB")
        sm_path = path.with_name(f"{stem}-sm.webp")
        md_path = path.with_name(f"{stem}-md.webp")
        lg_path = path.with_name(f"{stem}-lg.webp")
        legacy_webp = path.with_suffix(".webp")

        sm = _resize(base, HEROCARD_SM_W)
        md = _resize(base, HEROCARD_MD_W)
        lg = _resize(base, HEROCARD_LG_W)
        png_fb = _resize(base, HEROCARD_PNG_W)

        sm_b = _save_webp_budget(sm, sm_path, max_bytes=HEROCARD_SM_MAX, dry_run=dry_run)
        md_b = _save_webp_budget(md, md_path, max_bytes=HEROCARD_MD_MAX, dry_run=dry_run)
        lg_b = _save_webp_budget(lg, lg_path, max_bytes=HEROCARD_LG_MAX, dry_run=dry_run)
        legacy_b = (
            md_b
            if dry_run
            else _save_webp_budget(md, legacy_webp, max_bytes=HEROCARD_MD_MAX, dry_run=False)
        )
        png_b = _save_png_budget(png_fb, path, max_bytes=MAX_ROOT_VARIANT, dry_run=dry_run)

        out.extend(
            [
                Result(
                    f"static/img/herocards/{stem}.png",
                    before,
                    png_b,
                    png_fb.size[0],
                    png_fb.size[1],
                    "png fallback",
                ),
                Result(
                    f"static/img/herocards/{stem}-sm.webp",
                    0,
                    sm_b,
                    sm.size[0],
                    sm.size[1],
                    "small",
                ),
                Result(
                    f"static/img/herocards/{stem}-md.webp",
                    0,
                    md_b,
                    md.size[0],
                    md.size[1],
                    "medium",
                ),
                Result(
                    f"static/img/herocards/{stem}-lg.webp",
                    0,
                    lg_b,
                    lg.size[0],
                    lg.size[1],
                    "large",
                ),
                Result(
                    f"static/img/herocards/{stem}.webp",
                    0,
                    legacy_b,
                    md.size[0],
                    md.size[1],
                    "legacy=md",
                ),
            ]
        )
    return out


def _compress_named_pair(
    rel_dir: str,
    stem: str,
    *,
    src_suffix: str,
    max_w: int,
    webp_max: int,
    fallback_max: int,
    dry_run: bool,
) -> list[Result]:
    """Compress ``rel_dir/stem.{png|jpg}`` + sibling ``.webp``."""
    folder = IMG / rel_dir
    src = folder / f"{stem}{src_suffix}"
    webp_path = folder / f"{stem}.webp"
    if not src.is_file():
        return []
    before = src.stat().st_size
    before_webp = webp_path.stat().st_size if webp_path.is_file() else 0
    with Image.open(src) as im:
        has_alpha = "A" in im.getbands() or (im.mode == "P" and "transparency" in im.info)
        base = im.convert("RGBA" if has_alpha and src_suffix == ".png" else "RGB")
        base = _resize(base, max_w)
        w, h = base.size
        if src_suffix == ".png":
            after_src = _save_png_budget(base, src, max_bytes=fallback_max, dry_run=dry_run)
        else:
            after_src = _save_jpeg_budget(base, src, max_bytes=fallback_max, dry_run=dry_run)
        after_webp = _save_webp_budget(base, webp_path, max_bytes=webp_max, dry_run=dry_run)
    return [
        Result(f"static/img/{rel_dir}/{stem}{src_suffix}", before, after_src, w, h, "fallback"),
        Result(f"static/img/{rel_dir}/{stem}.webp", before_webp, after_webp, w, h, "webp"),
    ]


def _compress_landscapes(*, dry_run: bool) -> list[Result]:
    out: list[Result] = []
    folder = IMG / "landscapes"
    if not folder.is_dir():
        return out
    for jpg in sorted(folder.glob("*-h.jpg")):
        out.extend(
            _compress_named_pair(
                "landscapes",
                jpg.stem,
                src_suffix=".jpg",
                max_w=LANDSCAPE_MAX_W,
                webp_max=LANDSCAPE_WEBP_MAX,
                fallback_max=LANDSCAPE_JPG_MAX,
                dry_run=dry_run,
            )
        )
    return out


def run(*, dry_run: bool = False) -> list[Result]:
    results: list[Result] = []
    results.extend(_compress_root_pair("background", max_w=BACKGROUND_MAX_W, dry_run=dry_run))
    results.extend(_compress_root_pair("map", max_w=MAP_MAX_W, dry_run=dry_run))
    for path in sorted((IMG / "herocards").glob("herocard_*.png")):
        results.extend(_compress_herocard(path, dry_run=dry_run))
    # GC-PERF-IMG-001 — shell / galaxy heavyweights
    results.extend(
        _compress_named_pair(
            "herocardsframe",
            "frame",
            src_suffix=".png",
            max_w=FRAME_MAX_W,
            webp_max=FRAME_WEBP_MAX,
            fallback_max=FRAME_PNG_MAX,
            dry_run=dry_run,
        )
    )
    results.extend(
        _compress_named_pair(
            "expedition",
            "expedition",
            src_suffix=".png",
            max_w=EXPEDITION_MAX_W,
            webp_max=EXPEDITION_WEBP_MAX,
            fallback_max=EXPEDITION_PNG_MAX,
            dry_run=dry_run,
        )
    )
    results.extend(_compress_landscapes(dry_run=dry_run))
    for stem in ("asteroid", "debris"):
        results.extend(
            _compress_named_pair(
                "debris",
                stem,
                src_suffix=".jpg",
                max_w=DEBRIS_MAX_W,
                webp_max=DEBRIS_WEBP_MAX,
                fallback_max=DEBRIS_JPG_MAX,
                dry_run=dry_run,
            )
        )
    return results


def write_report(path: Path, results: list[Result]) -> None:
    lines = [
        "# GC-860B / GC-PERF-IMG — Shell Compression Report",
        "",
        "| file | before | after | dims | note |",
        "|------|-------:|------:|------|------|",
    ]
    for r in results:
        lines.append(
            f"| `{r.path}` | {_human(r.before)} | {_human(r.after)} | {r.width}×{r.height} | {r.note} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GC-860B / GC-PERF-IMG P0+shell asset compression")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--report", metavar="PATH")
    args = parser.parse_args(argv)

    results = run(dry_run=args.dry_run)
    for r in results:
        delta = f"{_human(r.before)} -> {_human(r.after)}" if r.before else _human(r.after)
        print(f"{r.path}: {delta} ({r.width}x{r.height}) {r.note}")

    if args.report:
        write_report(Path(args.report), results)
        print(f"Wrote {args.report}", file=sys.stderr)

    if args.dry_run:
        print("(dry run — no files written)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
