"""
GC-860C — P0 image template rollout (srcset/sizes, map WebP primary).

Run: python -m pytest tests/test_gc860c_image_template_rollout.py -v
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_gc860c_herocard_variant_helpers():
    from game.planet_visuals import (
        HEROCARD_WEBP_WIDTHS,
        format_static_srcset,
        herocard_variant_webp_relpath,
        herocard_webp_srcset_for_position,
        herocard_webp_srcset_parts_for_position,
    )

    assert herocard_variant_webp_relpath(8, "sm") == "img/herocards/herocard_08-sm.webp"
    assert herocard_variant_webp_relpath(8, "md") == "img/herocards/herocard_08-md.webp"
    assert herocard_variant_webp_relpath(8, "lg") == "img/herocards/herocard_08-lg.webp"

    parts = herocard_webp_srcset_parts_for_position(8)
    assert len(parts) == 3
    assert parts[0] == ("img/herocards/herocard_08-sm.webp", HEROCARD_WEBP_WIDTHS["sm"])
    assert parts[1] == ("img/herocards/herocard_08-md.webp", HEROCARD_WEBP_WIDTHS["md"])
    assert parts[2] == ("img/herocards/herocard_08-lg.webp", HEROCARD_WEBP_WIDTHS["lg"])

    srcset = format_static_srcset(parts, lambda _endpoint, filename: f"/static/{filename}")
    assert "/static/img/herocards/herocard_08-sm.webp 320w" in srcset
    assert "/static/img/herocards/herocard_08-md.webp 560w" in srcset
    assert "/static/img/herocards/herocard_08-lg.webp 840w" in srcset

    full = herocard_webp_srcset_for_position(8, lambda _endpoint, filename: f"/static/{filename}")
    assert full == srcset


def test_gc860c_planet_theme_includes_srcset_parts():
    from game.planet_visuals import OVERVIEW_HEROCARD_SIZES, planet_theme_for_planet

    theme = planet_theme_for_planet({"position": 3})
    parts = theme["herocard_webp_srcset_parts"]
    assert parts[0][0].endswith("-sm.webp")
    assert parts[-1][0].endswith("-lg.webp")
    assert theme["herocard_webp_sizes"] == OVERVIEW_HEROCARD_SIZES
    assert theme["herocard_fallback_width"] == 560


def test_gc860c_overview_template_responsive_herocard():
    overview = _read("templates/overview.html")
    assert "herocard_srcset_parts" in overview
    assert 'sizes="{{ herocard_sizes }}"' in overview
    assert "320w" in overview or "herocard_webp_srcset_parts" in overview
    assert 'width="{{ herocard_w }}"' in overview
    assert 'width="1400"' not in overview
    assert "data-planet-position" in overview


def test_gc860c_map_css_webp_primary():
    css = _read("static/style.css")
    block = css.split(".galaxy-command-map-bg{")[1].split(".galaxy-command-map-bg::before")[0]
    before = css.split(".galaxy-command-map-bg::before{")[1].split(".galaxy-command-map-bg::after")[0]
    for chunk in (block, before):
        assert "map.webp" in chunk
        assert 'type("image/webp")' in chunk
        assert "map.png" in chunk


def test_gc860c_main_js_herocard_srcset_from_state():
    src = _read("static/main.js")
    hero_fn = src.split("function applyPlanetHeroThemeFromState(data)")[1].split(
        "function bootstrapPlanetLandscapeFromBoot"
    )[0]
    assert "herocard_webp_srcset" in hero_fn
    assert "herocard_webp_sizes" in hero_fn
    assert "source.sizes" in hero_fn
    assert "dataset.planetPosition" in hero_fn


def test_gc860c_herocard_srcset_url_builder():
    from flask import url_for

    from app import app
    from game.planet_visuals import herocard_webp_srcset_for_position

    with app.test_request_context("/"):
        srcset = herocard_webp_srcset_for_position(8, url_for)
    assert "herocard_08-sm.webp" in srcset
    assert "herocard_08-md.webp" in srcset
    assert "herocard_08-lg.webp" in srcset
    assert "320w" in srcset
    assert "560w" in srcset
    assert "840w" in srcset


def test_gc860c_app_exposes_srcset_in_game_state():
    app_src = _read("app.py")
    assert "herocard_webp_srcset" in app_src
    assert "herocard_webp_sizes" in app_src
    assert "herocard_webp_srcset_for_position" in app_src


def test_gc860c_variant_files_exist():
    for variant in ("sm", "md", "lg"):
        path = ROOT / "static" / "img" / "herocards" / f"herocard_08-{variant}.webp"
        assert path.is_file(), f"missing {path.name}"
        assert path.stat().st_size < 150_000
