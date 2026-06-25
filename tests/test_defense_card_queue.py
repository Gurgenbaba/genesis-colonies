"""
GC-536 — defense card queue payload and static contracts.

Run: python -m pytest tests/test_defense_card_queue.py -q
"""

from __future__ import annotations

from pathlib import Path

from game.defense import _attach_queue_jobs_to_defense_rows
from game.queue_card import (
    STATUS_ACTIVE,
    STATUS_QUEUED,
    group_card_jobs_by_owner_key,
    map_defense_queue_to_card_jobs,
)

ROOT = Path(__file__).resolve().parents[1]

_NOW = 1_700_000_160.0


def _sample_queue(*, multi: bool = False) -> dict:
    jobs = [
        {
            "id": 40,
            "defense_key": "laser_turret",
            "amount_total": 8,
            "order_remaining": 180,
            "order_total_seconds": 360,
            "finish_at": 1_700_000_340.0,
            "started_at": 1_700_000_000.0,
            "start_at": 1_700_000_000.0,
            "is_active": True,
        }
    ]
    if multi:
        jobs.append(
            {
                "id": 41,
                "defense_key": "missile_battery",
                "amount_total": 3,
                "order_remaining": 920,
                "order_total_seconds": 480,
                "finish_at": 1_700_001_080.0,
                "start_at": 1_700_000_340.0,
                "is_active": False,
            }
        )
    return {
        "queue": jobs,
        "summary": {"count": len(jobs), "limit": 3},
    }


def test_active_defense_job_maps_to_card_job_with_amount():
    card_jobs = map_defense_queue_to_card_jobs(_sample_queue(), now=_NOW)
    assert len(card_jobs) == 1
    qj = card_jobs[0]
    assert qj["owner_type"] == "defense"
    assert qj["owner_key"] == "laser_turret"
    assert qj["status"] == STATUS_ACTIVE
    assert qj["queue_position"] == 1
    assert qj["target_amount"] == 8
    assert qj["defense_label_key"] == "defense_laser_turret"


def test_queued_defense_job_has_queue_position():
    card_jobs = map_defense_queue_to_card_jobs(_sample_queue(multi=True), now=_NOW)
    queued = next(j for j in card_jobs if j["owner_key"] == "missile_battery")
    assert queued["status"] == STATUS_QUEUED
    assert queued["queue_position"] == 2
    assert queued["target_amount"] == 3


def test_defense_row_without_job_has_no_queue_job():
    by_owner = group_card_jobs_by_owner_key(map_defense_queue_to_card_jobs(_sample_queue(), now=_NOW))
    rows = [{"defense_key": "laser_turret"}, {"defense_key": "shield_generator"}]
    _attach_queue_jobs_to_defense_rows(rows, by_owner)
    assert rows[0]["queue_job"]["status"] == STATUS_ACTIVE
    assert "queue_job" not in rows[1]


def test_queue_engine_unchanged_static():
    text = (ROOT / "game/queue_engine.py").read_text(encoding="utf-8")
    assert "queue_card" not in text


def test_defense_template_mini_queue_markers():
    html = (ROOT / "templates/defense.html").read_text(encoding="utf-8")
    partial = (ROOT / "templates/partials/page_mini_queue_strip.html").read_text(encoding="utf-8")
    assert "data-defense-card" in html
    assert "defense-mini-queue" in html
    assert "render_page_mini_queue_strip" in html
    assert "gc-mini-queue-strip" in partial
    assert "gc-card-queue-block" not in html
    assert "data-defense-queue-list" not in html
    assert "shipyard-job-active" not in html
