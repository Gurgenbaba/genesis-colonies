"""
GC-536B — building card queue payload and static contracts.

Run: python -m pytest tests/test_buildings_card_queue.py -q
"""

from __future__ import annotations

from pathlib import Path

from game.buildings import get_buildings_panel_rows
from game.queue_card import STATUS_ACTIVE, STATUS_QUEUED

ROOT = Path(__file__).resolve().parents[1]


def _panel_row(rows_by_tab: dict, building_type: str) -> dict | None:
    for rows in rows_by_tab.values():
        for row in rows:
            if row.get("key") == building_type:
                return row
    return None


def test_gc748_card_asset_lazyload_contract():
    """GC-748: card hero images lazy-load below first row with stable dimensions."""
    progression = (ROOT / "templates" / "partials" / "progression_cards.html").read_text(encoding="utf-8")
    macro = progression.split("{% macro render_raster_picture")[1].split("{% endmacro %}")[0]
    assert 'width="{{ width|int }}"' in macro
    assert 'height="{{ height|int }}"' in macro
    assert 'decoding="async"' in macro
    assert 'loading="lazy"' in macro
    assert 'fetchpriority="high"' in macro

    for rel in (
        "templates/buildings.html",
        "templates/research.html",
        "templates/shipyard.html",
        "templates/defense.html",
    ):
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert "loop.index0 >= 3" in html, rel

    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    hero_img = css.split(".gc-bld-card-hero-img{")[1].split("}", 1)[0]
    assert "aspect-ratio: 16 / 9" in hero_img

    fleet = (ROOT / "templates" / "fleet.html").read_text(encoding="utf-8")
    assert "fleet-ship-tbl-img" in fleet
    assert 'decoding="async"' in fleet


    """GC-747B: buildings SSR/poll slimdown + CSS webp resource icons."""
    src = (ROOT / "static" / "main.js").read_text(encoding="utf-8")
    panel_fn = src.split("function gameStateIncludePanel()")[1].split("function gameStateWantPanelPoll")[0]
    assert 'page === "buildings"' not in panel_fn
    bind_tabs = src.split("function bindBuildingTabsOnce()")[1].split("function initBuildings()")[0]
    subnav_block = bind_tabs.split("#gc-nav-buildings-sub")[1].split('.building-tabs .tab-btn')[0]
    assert "GC.navigateTo(`/buildings?tab=" in subnav_block
    assert "activateBuildingTabByName(tab, subBtn)" not in subnav_block
    buildings_html = (ROOT / "templates" / "buildings.html").read_text(encoding="utf-8")
    assert "panel-resources" not in buildings_html
    assert 'render_building_table(rows_by_tab.get(active_tab' in buildings_html
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "Ferronit.webp" in css
    assert "Ferronit.png" not in css
    app_py = (ROOT / "app.py").read_text(encoding="utf-8")
    bv = app_py.split("def buildings_view()")[1].split("def upgrade")[0]
    assert "active_tab=active_tab" in bv
    assert "close_conn=False" in bv


def test_get_buildings_panel_rows_active_tab_only():
    """GC-747B: SSR loads one buildings tab, not all four."""
    planet = {"player_id": 1, "metal": 1000, "crystal": 1000}
    buildings = {"metal_mine": 1, "research_lab": 1, "orbital_shipyard": 1}
    rows = get_buildings_panel_rows(planet, buildings, active_tab="resources")
    assert list(rows.keys()) == ["resources"]
    assert len(rows["resources"]) >= 1
    assert all(r.get("tab") == "resources" for r in rows["resources"])
    assert "military" not in rows


def test_active_building_row_has_queue_job():
    planet = {"player_id": 1, "metal": 99999, "crystal": 99999}
    buildings = {"metal_mine": 3, "crystal_mine": 2}
    build_queue = {
        "planet_id": 1,
        "queue": [
            {
                "id": 10,
                "building_type": "metal_mine",
                "label_key": "building_metal_mine",
                "target_level": 4,
                "remaining": 50,
                "total": 100,
                "finish_time": 1_700_000_050.0,
            }
        ],
        "summary": {"count": 1, "limit": 3},
    }
    rows = get_buildings_panel_rows(planet, buildings, build_queue=build_queue)
    row = _panel_row(rows, "metal_mine")
    assert row is not None
    qj = row.get("queue_job")
    assert qj is not None
    assert qj["owner_key"] == "metal_mine"
    assert qj["status"] == STATUS_ACTIVE
    assert qj["queue_position"] == 1
    assert qj["target_level"] == 4
    assert qj["current_level"] == 3


def test_queued_building_row_has_queue_position():
    planet = {"player_id": 1, "metal": 99999, "crystal": 99999}
    buildings = {"metal_mine": 3, "crystal_mine": 2}
    build_queue = {
        "queue": [
            {
                "id": 10,
                "building_type": "metal_mine",
                "target_level": 4,
                "remaining": 50,
                "total": 100,
                "finish_time": 1_700_000_050.0,
            },
            {
                "id": 11,
                "building_type": "crystal_mine",
                "target_level": 3,
                "remaining": 150,
                "total": 80,
                "finish_time": 1_700_000_150.0,
            },
        ],
    }
    rows = get_buildings_panel_rows(planet, buildings, build_queue=build_queue)
    crystal = _panel_row(rows, "crystal_mine")
    assert crystal is not None
    qj = crystal["queue_job"]
    assert qj["status"] == STATUS_QUEUED
    assert qj["queue_position"] == 2


def test_build_queue_status_includes_card_jobs_by_owner_for_same_type():
    from game.queue_card import group_card_jobs_by_owner_key, map_build_queue_to_card_jobs

    build_queue = {
        "queue": [
            {
                "id": 10,
                "building_type": "metal_mine",
                "target_level": 4,
                "remaining": 40,
                "total": 100,
                "finish_time": 1_700_000_040.0,
            },
            {
                "id": 11,
                "building_type": "metal_mine",
                "target_level": 5,
                "remaining": 140,
                "total": 100,
                "finish_time": 1_700_000_140.0,
            },
        ],
    }
    card_jobs = map_build_queue_to_card_jobs(build_queue, now=1_700_000_000.0)
    by_owner = group_card_jobs_by_owner_key(card_jobs)
    assert len(by_owner["metal_mine"]) == 2
    assert sum(1 for j in by_owner["metal_mine"] if j["status"] == STATUS_ACTIVE) == 1


def test_building_without_job_has_no_queue_job():
    planet = {"player_id": 1, "metal": 99999, "crystal": 99999}
    buildings = {"metal_mine": 3}
    build_queue = {
        "queue": [
            {
                "id": 10,
                "building_type": "metal_mine",
                "target_level": 4,
                "remaining": 50,
                "total": 100,
                "finish_time": 1_700_000_050.0,
            }
        ],
    }
    rows = get_buildings_panel_rows(planet, buildings, build_queue=build_queue)
    solar = _panel_row(rows, "solar_plant")
    assert solar is not None
    assert "queue_job" not in solar


def test_queue_engine_unchanged_static():
    text = (ROOT / "game/queue_engine.py").read_text(encoding="utf-8")
    assert "queue_card" not in text


def test_buildings_template_card_queue_markers():
    html = (ROOT / "templates/buildings.html").read_text(encoding="utf-8")
    macro = (ROOT / "templates/partials/page_queue_compact.html").read_text(encoding="utf-8")
    assert "data-building-card" in html
    assert "data-building-type" in html
    assert "render_page_queue_compact" in html
    assert "build-queue-compact" in html
    assert "data-page-queue-compact-body" in macro
    assert "gc-page-queue-compact-active" in macro
    assert "gc-card-queue-block" in html
    assert "build-queue-root" not in html
    assert "gc-page-queue-panel" not in html


def test_main_js_updates_page_queue_compact():
    js = (ROOT / "static/main.js").read_text(encoding="utf-8")
    assert "_updatePageQueueCompact" in js
    assert "_updateBuildQueueCompact" in js
    assert "_updateResearchQueueCompact" in js
    assert "_updateShipyardQueueCompact" in js
    assert "_updateDefenseQueueCompact" in js
    assert "data-page-queue-compact-body" in js


def test_main_js_excludes_building_queue_from_global_hud():
    js = (ROOT / "static/main.js").read_text(encoding="utf-8")
    assert '_globalQueueHudDomain(j) !== "building"' in js
    assert "_updatePageQueueCompact" in js
