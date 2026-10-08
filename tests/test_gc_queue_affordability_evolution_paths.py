"""Regression coverage for live building queue/affordability + PE extraction paths."""

from pathlib import Path
from game.queue_card import map_build_queue_to_card_jobs

ROOT = Path(__file__).resolve().parents[1]

def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")

def test_future_subsecond_build_job_stays_visible():
    jobs = map_build_queue_to_card_jobs(
        {"queue": [{"id": 77, "building_type": "metal_mine", "label_key": "building_metal_mine",
        "target_level": 4, "start_time": 999.25, "finish_time": 1000.25, "total": 1}]},
        now=1000.0,
    )
    assert len(jobs) == 1
    assert jobs[0]["status"] == "active"
    assert jobs[0]["remaining_seconds"] == 1

def test_buildings_live_affordability_requests_authoritative_panel_refresh():
    src = _read("static/main.js")
    helper = src.split("function maybeRefreshMountedBuildingAffordability(projected)")[1].split("function tickLiveResourceBar()")[0]
    ticker = src.split("function tickLiveResourceBar()")[1].split("function _resourceTickerIntervalMs()")[0]
    assert "data-action-state='warn'" in helper
    assert "resourceItems.length !== items.length" in helper
    assert 'forceCanonicalGameStateRefresh("buildings_affordability"' in helper
    assert "maybeRefreshMountedBuildingAffordability(projected)" in ticker

def test_techtree_surfaces_extraction_choice_consequences():
    tree = _read("game/techtree.py")
    tpl = _read("templates/techtree.html")
    de = _read("locales/de.json")
    assert '"key": "industry_t2_mining_path"' in tree
    assert '"unlock_label_keys": ["pe_industry_t3_orbital", "pe_orbital_t2"]' in tree
    assert '"unlock_label_keys": ["pe_industry_t3_mantle"]' in tree
    assert '"choice_merge_label_key": "pe_industry_t4_foundry"' in tree
    assert "item.choice_branches" in tpl
    assert '"techtree_choice_paths": "Folgepfade"' in de
