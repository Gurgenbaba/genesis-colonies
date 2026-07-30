"""GC-PERF-IMG — global static image budgets and delivery contracts."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "static" / "img"

FRAME_PNG_MAX = 350_000
FRAME_WEBP_MAX = 120_000
EXPEDITION_PNG_MAX = 400_000
EXPEDITION_WEBP_MAX = 180_000
CARD_WEBP_MAX = 80_000
CARD_PNG_MAX = 180_000
LANDSCAPE_WEBP_MAX = 160_000


def test_perf_img_overview_sizes_match_srcset_max():
    from game.planet_visuals import OVERVIEW_HEROCARD_SIZES

    assert "840px" in OVERVIEW_HEROCARD_SIZES
    assert "1120px" not in OVERVIEW_HEROCARD_SIZES


def test_perf_img_frame_and_expedition_budgets():
    frame_png = IMG / "herocardsframe" / "frame.png"
    frame_webp = IMG / "herocardsframe" / "frame.webp"
    exp_png = IMG / "expedition" / "expedition.png"
    exp_webp = IMG / "expedition" / "expedition.webp"
    assert frame_png.is_file() and frame_webp.is_file()
    assert exp_png.is_file() and exp_webp.is_file()
    assert frame_png.stat().st_size <= FRAME_PNG_MAX
    assert frame_webp.stat().st_size <= FRAME_WEBP_MAX
    assert exp_png.stat().st_size <= EXPEDITION_PNG_MAX
    assert exp_webp.stat().st_size <= EXPEDITION_WEBP_MAX


def test_perf_img_shell_webp_siblings_exist():
    assert (IMG / "debris" / "asteroid.webp").is_file()
    assert (IMG / "debris" / "debris.webp").is_file()
    assert (IMG / "defense" / "slug_launcher.webp").is_file()
    for boss in ("planet_eater", "rogue_ai_nexus", "ancient_leviathan", "void_titan"):
        assert (IMG / "bosses" / f"{boss}.webp").is_file()


def test_perf_img_sample_card_webp_under_budget():
    samples = [
        IMG / "buildings" / "metal_mine.webp",
        IMG / "ships" / "falcon_interceptor.webp",
        IMG / "research" / "energieeffizienz.webp",
        IMG / "lootboxes" / "Generic_Supply_Container.webp",
    ]
    for path in samples:
        assert path.is_file(), f"missing {path}"
        assert path.stat().st_size <= CARD_WEBP_MAX, f"{path} over WebP budget"


def test_perf_img_sample_card_png_under_budget():
    samples = [
        IMG / "buildings" / "metal_mine.png",
        IMG / "defense" / "slug_launcher.png",
        IMG / "badges" / "default.png",
    ]
    for path in samples:
        if not path.is_file():
            continue
        assert path.stat().st_size <= CARD_PNG_MAX, f"{path} over PNG budget"


def test_perf_img_landscape_webp_under_budget():
    folder = IMG / "landscapes"
    webps = sorted(folder.glob("*-h.webp"))
    assert webps, "no landscape webp files"
    for path in webps:
        assert path.stat().st_size <= LANDSCAPE_WEBP_MAX, f"{path} over landscape WebP budget"


def test_perf_img_webp_static_preserves_query():
    from app import webp_static_filter

    assert webp_static_filter("/static/img/x.png?v=9") == "/static/img/x.webp?v=9"
    assert webp_static_filter("/static/img/x.jpg") == "/static/img/x.webp"


def test_perf_img_overview_template_preload_and_version():
    text = (ROOT / "templates" / "overview.html").read_text(encoding="utf-8")
    assert "data-gc-frame-preload" in text
    assert "GC_ASSET_VERSION" in text
    assert "840px" in text


def test_perf_img_galaxy_expedition_webp_wired():
    text = (ROOT / "templates" / "partials" / "galaxy_ring_view.html").read_text(encoding="utf-8")
    assert "expedition.webp" in text
    assert "asteroid.webp" in text
    assert "gc-galaxy-asteroid-img-webp" in text


def test_perf_img_gc_prefer_webp_helper():
    text = (ROOT / "static" / "js" / "core" / "gc.js").read_text(encoding="utf-8")
    assert "preferWebpStaticUrl" in text
    main = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    assert "GC.preferWebpStaticUrl" in main
    assert "Generic_Supply_Container.webp" in main


def test_perf_img_no_live_card_png_over_250kb_except_shell_fallbacks():
    """Live card folders must not ship >250KB PNG/JPG; shell PNG fallbacks allowed."""
    allow_dirs = {"herocards", "herocardsframe", "expedition"}
    allow_names = {"background.png", "map.png"}
    offenders = []
    for path in IMG.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            continue
        if path.stat().st_size < 250_000:
            continue
        if path.name in allow_names:
            continue
        if path.parent.name in allow_dirs:
            continue
        offenders.append(path.as_posix())
    assert not offenders, f"oversized live assets: {offenders}"
