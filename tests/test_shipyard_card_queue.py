"""
GC-536D — shipyard card queue payload and static contracts.

Run: python -m pytest tests/test_shipyard_card_queue.py -q
"""

from __future__ import annotations

from pathlib import Path

from game.queue_card import (
    STATUS_ACTIVE,
    STATUS_QUEUED,
    group_card_jobs_by_owner_key,
    map_shipyard_queue_to_card_jobs,
)
from game.shipyard import _attach_queue_jobs_to_ship_rows

ROOT = Path(__file__).resolve().parents[1]

_NOW = 1_700_000_160.0


def _sample_queue(*, multi: bool = False) -> dict:
    jobs = [
        {
            "id": 10,
            "ship_key": "mule_courier",
            "amount_total": 12,
            "order_remaining": 260,
            "order_total_seconds": 420,
            "finish_at": 1_700_000_420.0,
            "started_at": 1_700_000_000.0,
            "is_active": True,
        }
    ]
    if multi:
        jobs.append(
            {
                "id": 11,
                "ship_key": "seed_ark",
                "amount_total": 5,
                "order_remaining": 1124,
                "order_total_seconds": 900,
                "finish_at": 1_700_001_284.0,
                "started_at": 1_700_000_420.0,
                "is_active": False,
            }
        )
    return {
        "queue": jobs,
        "summary": {"count": len(jobs), "limit": 3},
    }


def test_active_shipyard_job_maps_to_card_job_with_amount():
    card_jobs = map_shipyard_queue_to_card_jobs(_sample_queue(), now=_NOW)
    assert len(card_jobs) == 1
    qj = card_jobs[0]
    assert qj["owner_key"] == "mule_courier"
    assert qj["status"] == STATUS_ACTIVE
    assert qj["queue_position"] == 1
    assert qj["target_amount"] == 12
    assert qj["ship_label_key"] == "fleet_ship_mule_courier"


def test_queued_shipyard_job_has_queue_position():
    card_jobs = map_shipyard_queue_to_card_jobs(_sample_queue(multi=True), now=_NOW)
    seed = next(j for j in card_jobs if j["owner_key"] == "seed_ark")
    assert seed["status"] == STATUS_QUEUED
    assert seed["queue_position"] == 2
    assert seed["target_amount"] == 5


def test_ship_row_without_job_has_no_queue_job():
    by_owner = group_card_jobs_by_owner_key(map_shipyard_queue_to_card_jobs(_sample_queue(), now=_NOW))
    ships = [{"ship_key": "mule_courier"}, {"ship_key": "scout_probe"}]
    _attach_queue_jobs_to_ship_rows(ships, by_owner)
    assert ships[0]["queue_job"]["status"] == STATUS_ACTIVE
    assert "queue_job" not in ships[1]


def test_attach_queue_job_preserves_target_amount():
    by_owner = group_card_jobs_by_owner_key(map_shipyard_queue_to_card_jobs(_sample_queue(), now=_NOW))
    ships = [{"ship_key": "mule_courier"}]
    _attach_queue_jobs_to_ship_rows(ships, by_owner)
    assert ships[0]["queue_job"]["target_amount"] == 12


def test_queue_engine_unchanged_static():
    text = (ROOT / "game/queue_engine.py").read_text(encoding="utf-8")
    assert "queue_card" not in text


def test_shipyard_template_card_queue_markers():
    html = (ROOT / "templates/shipyard.html").read_text(encoding="utf-8")
    assert "data-ship-card" in html
    assert "data-ship-key" in html
    assert "shipyard-queue-compact" in html
    assert "gc-card-queue-block" in html
    assert "data-shipyard-queue-list" not in html
