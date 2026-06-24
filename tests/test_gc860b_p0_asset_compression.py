"""
GC-860B — P0 asset compression budgets.

Run: python -m pytest tests/test_gc860b_p0_asset_compression.py -v
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "static" / "img"

MAX_ROOT = 500_000
HEROCARD_SM_MAX = 80_000
HEROCARD_MD_MAX = 150_000


def _compress_mod():
    spec = importlib.util.spec_from_file_location("compress_p0_assets", ROOT / "tools" / "compress_p0_assets.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_gc860b_compress_script_exists():
    assert (ROOT / "tools" / "compress_p0_assets.py").is_file()


def test_gc860b_p0_assets_on_disk_meet_budgets():
    """Requires assets generated via tools/compress_p0_assets.py."""
    for name in ("background", "map"):
        webp = IMG / f"{name}.webp"
        assert webp.is_file(), f"missing {webp}"
        assert webp.stat().st_size <= MAX_ROOT, f"{webp} over 500KB budget"

    sm = IMG / "herocards" / "herocard_08-sm.webp"
    md = IMG / "herocards" / "herocard_08-md.webp"
    assert sm.is_file() and md.is_file()
    assert sm.stat().st_size <= HEROCARD_SM_MAX
    assert md.stat().st_size <= HEROCARD_MD_MAX
    assert (IMG / "herocards" / "herocard_08.webp").stat().st_size <= HEROCARD_MD_MAX


def test_gc860b_herocard_png_fallback_shrunk():
    png = IMG / "herocards" / "herocard_08.png"
    assert png.stat().st_size <= MAX_ROOT
    from PIL import Image

    with Image.open(png) as im:
        assert im.size[0] <= 900


def test_gc860b_dry_run_exits_zero():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "compress_p0_assets.py"), "--dry-run"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    assert "herocard" in result.stdout


def test_gc860b_doc_exists():
    text = (ROOT / "docs" / "GC-860B_P0_ASSET_COMPRESSION.md").read_text(encoding="utf-8")
    assert "background" in text
    assert "herocard" in text.lower()
    assert "GC-860C" in text
