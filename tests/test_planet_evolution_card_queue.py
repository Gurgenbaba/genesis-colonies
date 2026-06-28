"""
GC-536E — planet-tech + ascension card queue payload and static contracts.

Run: python -m pytest tests/test_planet_evolution_card_queue.py -q
"""

from __future__ import annotations

from pathlib import Path

from game.planet_evolution.ascension import _attach_queue_jobs_to_ascension_cards
from game.planet_evolution.planet_research import _attach_queue_jobs_to_planet_tech_rows
from game.queue_card import (
    STATUS_ACTIVE,
    STATUS_QUEUED,
    group_card_jobs_by_owner_key,
    map_ascension_queue_to_card_jobs,
    map_planet_research_queue_to_card_jobs,
)

ROOT = Path(__file__).resolve().parents[1]

_NOW = 1_700_000_160.0


def _sample_planet_research_queue(*, multi: bool = False) -> dict:
    jobs = [
        {
            "id": 20,
            "tech_key": "industry_t1_automation",
            "label_key": "pe_research_industry_t1_automation",
            "target_level": 3,
            "remaining": 240,
            "total_seconds": 600,
            "finish_at": 1_700_000_400.0,
            "start_at": 1_700_000_000.0,
        }
    ]
    if multi:
        jobs.append(
            {
                "id": 21,
                "tech_key": "metallurgy_t2_refining",
                "label_key": "pe_research_metallurgy_t2_refining",
                "target_level": 2,
                "remaining": 860,
                "total_seconds": 480,
                "finish_at": 1_700_001_020.0,
                "start_at": 1_700_000_400.0,
            }
        )
    return {
        "queue": jobs,
        "summary": {"count": len(jobs), "limit": 3},
    }


def _sample_ascension_queue() -> dict:
    return {
        "queue": [
            {
                "id": 30,
                "ascension_key": "ascension_genesis",
                "label_key": "pe_ascension_genesis",
                "quest_stage": 1,
                "remaining_seconds": 180,
                "start_at": 1_700_000_000.0,
                "finish_at": 1_700_000_340.0,
            }
        ],
        "summary": {"count": 1, "limit": 1},
    }


def test_active_planet_tech_job_maps_to_card_job_with_target_level():
    card_jobs = map_planet_research_queue_to_card_jobs(_sample_planet_research_queue(), now=_NOW)
    assert len(card_jobs) == 1
    qj = card_jobs[0]
    assert qj["owner_type"] == "planet_research"
    assert qj["owner_key"] == "industry_t1_automation"
    assert qj["status"] == STATUS_ACTIVE
    assert qj["queue_position"] == 1
    assert qj["target_level"] == 3
    assert qj["current_level"] == 2


def test_queued_planet_tech_job_has_queue_position():
    card_jobs = map_planet_research_queue_to_card_jobs(
        _sample_planet_research_queue(multi=True),
        now=_NOW,
    )
    queued = next(j for j in card_jobs if j["owner_key"] == "metallurgy_t2_refining")
    assert queued["status"] == STATUS_QUEUED
    assert queued["queue_position"] == 2
    assert queued["progress_pct"] == 0


def test_planet_tech_row_without_job_has_no_queue_job():
    by_owner = group_card_jobs_by_owner_key(
        map_planet_research_queue_to_card_jobs(_sample_planet_research_queue(), now=_NOW)
    )
    rows = [{"tech_key": "industry_t1_automation"}, {"tech_key": "culture_t1_heritage"}]
    _attach_queue_jobs_to_planet_tech_rows(rows, by_owner)
    assert rows[0]["queue_job"]["status"] == STATUS_ACTIVE
    assert "queue_job" not in rows[1]


def test_active_ascension_job_maps_to_card_job_with_target_phase():
    card_jobs = map_ascension_queue_to_card_jobs(_sample_ascension_queue(), now=_NOW)
    assert len(card_jobs) == 1
    qj = card_jobs[0]
    assert qj["owner_type"] == "ascension"
    assert qj["owner_key"] == "ascension_genesis"
    assert qj["status"] == STATUS_ACTIVE
    assert qj["target_phase"] == 2


def test_ascension_card_without_job_has_no_queue_job():
    by_owner = group_card_jobs_by_owner_key(
        map_ascension_queue_to_card_jobs(_sample_ascension_queue(), now=_NOW)
    )
    cards = [{"ascension_key": "ascension_genesis"}, {"ascension_key": "ascension_void"}]
    _attach_queue_jobs_to_ascension_cards(cards, by_owner)
    assert cards[0]["queue_job"]["status"] == STATUS_ACTIVE
    assert "queue_job" not in cards[1]


def test_queue_engine_unchanged_static():
    text = (ROOT / "game/queue_engine.py").read_text(encoding="utf-8")
    assert "queue_card" not in text


def test_planet_evolution_template_card_queue_markers():
    html = (ROOT / "templates/planet_evolution.html").read_text(encoding="utf-8")
    assert "data-planet-tech-card" in html
    assert "data-tech-key" in html
    assert "data-ascension-card" in html
    assert "data-ascension-key" in html
    assert "pe-planet-tech-queue-list" in html
    assert "pe-planet-tech-queue-compact-count" in html
    assert "pe-planet-tech-queue-compact-label" in html
    assert "pe-ascension-queue-list" in html
    assert "pe-ascension-queue-compact-label" in html
    assert "gc-card-queue-block" in html
    assert "gc-card-queue-list" in html
    assert 'id="pe-research-queue"' not in html
    assert "pe-research-queue-cards" not in html
    assert "pe_research_job(" not in html
    assert "pe_visible_tech_cards" in html


def test_queued_planet_tech_wait_uses_finish_at():
    """Kanonische Queue-Regel: wartender Job = finish_at − now."""
    payload = _sample_planet_research_queue(multi=True)
    card_jobs = map_planet_research_queue_to_card_jobs(payload, now=_NOW)
    queued = next(j for j in card_jobs if j["owner_key"] == "metallurgy_t2_refining")
    expected_wait = max(0, int(payload["queue"][1]["finish_at"] - _NOW))
    assert queued["remaining_seconds"] == expected_wait


def test_planet_evolution_template_sets_ps_before_use():
    tpl = (ROOT / "templates/planet_evolution.html").read_text(encoding="utf-8")
    ps_set = tpl.find("{% set ps = planet_state")
    planet_id_use = tpl.find("data-planet-id=\"{{ ps.planet_id")
    assert ps_set >= 0
    assert planet_id_use >= 0
    assert ps_set < planet_id_use
    js = (ROOT / "static/main.js").read_text(encoding="utf-8")
    assert "renderPePlanetTechQueue" in js
    assert "renderPeAscensionQueue" in js
    assert "applyPlanetEvolutionState" in js
    assert "refreshPlanetEvolutionState" in js
    assert "gc-card-queue-glyph--planet-research" in js
    assert "gc-card-queue-block[data-gc-card-queue='1']" in js
    assert "syncPlanetEvolutionResearchTicker" in js
