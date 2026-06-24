#!/usr/bin/env python3
"""
GC-860 — Global image asset audit (static/img/**).

Usage:
  python tools/audit_image_assets.py
  python tools/audit_image_assets.py --json
  python tools/audit_image_assets.py --markdown docs/GC-860_image_audit_report.md
  python tools/audit_image_assets.py --min-kb 100

Output columns:
  file | bytes | width x height | used_in | rendered_size | recommendation
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMG_ROOT = ROOT / "static" / "img"
RASTER_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
SOURCE_GLOBS = (
    "templates/**/*.html",
    "game/**/*.py",
    "static/**/*.css",
    "static/**/*.js",
    "app.py",
)

# CSS/layout hints — not measured in browser; audit guidance only.
RENDER_HINTS: dict[str, str] = {
    "buildings": "~210×118 (gc-bld-card-hero, max-height 118px)",
    "research": "~210×118 (research card hero)",
    "ships": "~210×118 (shipyard card hero)",
    "defense": "~210×118 (defense card hero)",
    "res": "~24–32px (HUD resource icons)",
    "badges": "~48–64px (profile badge)",
    "lootboxes": "~80–120px (inventory tiles)",
    "landscapes": "viewport-wide (overview planet background)",
    "herocards": "~280×160 (overview commander card)",
    "herocardsframe": "~frame overlay",
    "vote": "~300×80 (vote provider banner)",
    "evo": "~64px (planet evolution icons)",
    "root": "page-level (background / map)",
}

CARD_CATEGORIES = frozenset({"buildings", "research", "ships", "defense"})
TARGET_CARD_MAX_W = 320
TARGET_CARD_MAX_H = 180


def _category(rel: Path) -> str:
    parts = rel.parts
    return parts[0] if len(parts) > 1 else "root"


def _dims(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image

        with Image.open(path) as im:
            return int(im.size[0]), int(im.size[1])
    except Exception:
        return 0, 0


def _load_sources() -> dict[str, str]:
    out: dict[str, str] = {}
    for pattern in SOURCE_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            try:
                out[path.relative_to(ROOT).as_posix()] = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
    return out


def _find_used_in(rel_posix: str, sources: dict[str, str], *, limit: int = 3) -> list[str]:
    name = Path(rel_posix).name
    stem = Path(rel_posix).stem
    short = rel_posix.replace("static/", "")
    hits: list[str] = []
    for file, text in sources.items():
        if name in text or short in text or stem in text and f"img/" in text:
            hits.append(file)
            if len(hits) >= limit:
                break
    return hits


def _webp_sibling(path: Path) -> Path | None:
    if path.suffix.lower() == ".webp":
        return None
    sib = path.with_suffix(".webp")
    return sib if sib.is_file() else None


def _recommend(
    *,
    rel: Path,
    path: Path,
    cat: str,
    width: int,
    height: int,
    size: int,
    used_in: list[str],
) -> str:
    ext = path.suffix.lower()
    kb = size / 1024.0
    webp = _webp_sibling(path) if ext != ".webp" else None
    recs: list[str] = []

    if ext == ".gif":
        recs.append("avoid GIF for photos; prefer WebP/PNG")
    if cat in CARD_CATEGORIES and width > TARGET_CARD_MAX_W + 40:
        recs.append(f"overserved vs {RENDER_HINTS[cat]}; target ~{TARGET_CARD_MAX_W}×{TARGET_CARD_MAX_H} WebP")
    if ext in (".png", ".jpg", ".jpeg") and kb >= 250:
        if webp:
            recs.append("WebP sibling exists — use WebP primary in template")
        else:
            recs.append("generate WebP sibling (GC-860B)")
    if ext in (".png", ".jpg", ".jpeg") and kb >= 100 and cat in CARD_CATEGORIES:
        recs.append("lazy/low below fold; eager/high first row only")
    if ext == ".webp" and kb <= 80 and cat in CARD_CATEGORIES:
        recs.append("ok for card hero")
    if cat == "root" and kb >= 500:
        recs.append("compress + image-set WebP in CSS")
    if cat == "landscapes" and width > 1400:
        recs.append("cap width ~1280 JPEG/WebP")
    if not recs:
        if ext == ".webp":
            recs.append("ok")
        elif webp:
            recs.append("prefer WebP delivery")
        else:
            recs.append("ok / optional WebP")
    return "; ".join(dict.fromkeys(recs))


def audit_assets(*, min_bytes: int = 0) -> list[dict]:
    sources = _load_sources()
    rows: list[dict] = []
    for path in sorted(IMG_ROOT.rglob("*")):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in RASTER_EXT:
            continue
        rel = path.relative_to(IMG_ROOT)
        size = path.stat().st_size
        if size < min_bytes:
            continue
        w, h = _dims(path)
        cat = _category(rel)
        rel_posix = f"static/img/{rel.as_posix()}"
        used = _find_used_in(rel_posix, sources)
        row = {
            "file": rel_posix,
            "bytes": size,
            "width": w,
            "height": h,
            "format": ext.lstrip("."),
            "category": cat,
            "used_in": used,
            "rendered_size": RENDER_HINTS.get(cat, "unknown"),
            "recommendation": _recommend(
                rel=rel,
                path=path,
                cat=cat,
                width=w,
                height=h,
                size=size,
                used_in=used,
            ),
        }
        webp = _webp_sibling(path) if ext != ".webp" else None
        if webp:
            row["webp_bytes"] = webp.stat().st_size
            row["webp_savings_bytes"] = max(0, size - webp.stat().st_size)
        rows.append(row)
    rows.sort(key=lambda r: r["bytes"], reverse=True)
    return rows


def _print_table(rows: list[dict]) -> None:
    print(f"{'file':<52} {'bytes':>8}  {'dims':>11}  {'used_in':<28} recommendation")
    print("-" * 140)
    for r in rows:
        dims = f"{r['width']}x{r['height']}"
        used = ", ".join(r["used_in"][:2]) or "—"
        if len(r["used_in"]) > 2:
            used += ", …"
        print(
            f"{r['file']:<52} {r['bytes']:>8}  {dims:>11}  {used:<28} {r['recommendation']}"
        )


def _page_weight_estimates(rows: list[dict]) -> dict[str, int]:
    """Rough bytes if all category assets loaded once (PNG vs WebP)."""
    by_cat: dict[str, dict[str, int]] = {}
    for r in rows:
        cat = r["category"]
        bucket = by_cat.setdefault(cat, {"png": 0, "webp": 0})
        if r["format"] == "webp":
            bucket["webp"] += r["bytes"]
        elif r["format"] in ("png", "jpg", "jpeg"):
            bucket["png"] += r["bytes"]
            if r.get("webp_bytes"):
                bucket["webp"] += int(r["webp_bytes"])
    return {cat: vals["png"] for cat, vals in by_cat.items()}


def write_markdown(path: Path, rows: list[dict]) -> None:
    heavy = [r for r in rows if r["bytes"] >= 250_000]
    overserved = [
        r
        for r in rows
        if r["category"] in CARD_CATEGORIES and r["width"] > TARGET_CARD_MAX_W + 40
    ]
    lines = [
        "# GC-860 — Image Asset Audit Report",
        "",
        f"Generated by `python tools/audit_image_assets.py --markdown {path.as_posix()}`",
        "",
        f"- Raster files scanned: **{len(rows)}**",
        f"- Files ≥250 KB: **{len(heavy)}**",
        f"- Card heroes overserved (w>{TARGET_CARD_MAX_W + 40}): **{len(overserved)}**",
        "",
        "## Top 20 by bytes",
        "",
        "| file | bytes | WxH | rendered_size | recommendation |",
        "|------|------:|-----|---------------|----------------|",
    ]
    for r in rows[:20]:
        lines.append(
            f"| `{r['file']}` | {r['bytes']:,} | {r['width']}×{r['height']} | {r['rendered_size']} | {r['recommendation']} |"
        )
    lines.extend(["", "## Buildings tab weight (all PNG vs WebP siblings)", ""])
    bld_png = sum(r["bytes"] for r in rows if r["category"] == "buildings" and r["format"] == "png")
    bld_webp = sum(
        r.get("webp_bytes") or r["bytes"]
        for r in rows
        if r["category"] == "buildings" and r["format"] == "png"
    )
    lines.append(f"- PNG total (if all loaded): **{bld_png / 1024:.0f} KB**")
    lines.append(f"- WebP siblings total: **{bld_webp / 1024:.0f} KB**")
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GC-860 global image asset audit")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of table")
    parser.add_argument("--markdown", metavar="PATH", help="Write markdown summary")
    parser.add_argument("--min-kb", type=float, default=0, help="Only assets >= N KB")
    args = parser.parse_args(argv)

    min_bytes = int(args.min_kb * 1024)
    rows = audit_assets(min_bytes=min_bytes)

    if args.markdown:
        write_markdown(Path(args.markdown), rows)
        print(f"Wrote {args.markdown}", file=sys.stderr)

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        _print_table(rows[:50] if not args.markdown else rows[:25])
        if len(rows) > 50 and not args.markdown:
            print(f"\n… {len(rows) - 50} more (use --json for full list)", file=sys.stderr)
        weights = _page_weight_estimates(rows)
        print("\n# Category PNG totals (if all raster PNG/JPG loaded once):", file=sys.stderr)
        for cat, total in sorted(weights.items(), key=lambda x: -x[1]):
            if total:
                print(f"  {cat:16} {total / 1024:7.0f} KB", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
