"""
GC-860 — Global image asset audit tooling.

Run: python -m pytest tests/test_gc860_image_asset_audit.py -v
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _audit_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "audit_image_assets", ROOT / "tools" / "audit_image_assets.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_gc860_audit_script_runs():
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "audit_image_assets.py"), "--json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    rows = json.loads(result.stdout)
    assert len(rows) >= 100


def test_gc860_finds_heavy_building_png_with_webp_sibling():
    audit_assets = _audit_module().audit_assets

    rows = audit_assets()
    mine = next(r for r in rows if r["file"].endswith("buildings/metal_mine.png"))
    assert mine["bytes"] > 200_000
    assert mine["width"] == 512
    assert mine.get("webp_bytes", 0) > 0
    assert mine.get("webp_bytes", mine["bytes"]) < mine["bytes"]
    assert "WebP" in mine["recommendation"] or "overserved" in mine["recommendation"]


def test_gc860_building_render_hint():
    audit_assets = _audit_module().audit_assets

    rows = audit_assets()
    mine = next(r for r in rows if r["file"].endswith("buildings/metal_mine.webp"))
    assert "118" in mine["rendered_size"]


def test_gc860_doc_exists():
    text = (ROOT / "docs" / "GC-860_GLOBAL_IMAGE_ASSET_OPTIMIZATION.md").read_text(encoding="utf-8")
    assert "audit_image_assets.py" in text
    assert "GC-860B" in text
    assert "GIF" in text


def test_gc860_markdown_report_writes(tmp_path):
    mod = _audit_module()

    out = tmp_path / "report.md"
    mod.write_markdown(out, mod.audit_assets()[:30])
    body = out.read_text(encoding="utf-8")
    assert "GC-860" in body
    assert "PNG total" in body or "buildings/" in body
