"""
GC-536A: canonical queue card adapter contract.

Run: python -m pytest tests/test_queue_card_contract.py -q
"""

from __future__ import annotations

import math

from game.queue_card import (
    STATUS_ACTIVE,
    STATUS_QUEUED,
    card_queue_job_for_item,
    compute_progress_pct,
    group_card_jobs_by_owner_key,
    map_build_queue_to_card_jobs,
    map_research_queue_to_card_jobs,
    normalize_card_queue_job,
)


NOW = 1_700_000_000.0


def test_active_job_mapping():
    job = normalize_card_queue_job(
        owner_type="building",
        owner_key="metal_mine",
        job_id=7,
        queue_position=1,
        start_at=NOW,
        finish_at=NOW + 100,
        now=NOW + 38,
        label="building_metal_mine",
        target_level=5,
    )
    assert job["status"] == STATUS_ACTIVE
    assert job["queue_position"] == 1
    assert job["owner_type"] == "building"
    assert job["owner_key"] == "metal_mine"
    assert job["job_id"] == 7
    assert job["remaining_seconds"] == 62
    assert job["duration_seconds"] == 100
    assert job["target_level"] == 5
    assert "target_amount" not in job


def test_queued_job_mapping_with_queue_position():
    job = normalize_card_queue_job(
        owner_type="research",
        owner_key="energy_tech",
        job_id=12,
        queue_position=2,
        start_at=NOW + 200,
        finish_at=NOW + 500,
        now=NOW,
        label="Energy Tech",
    )
    assert job["status"] == STATUS_QUEUED
    assert job["queue_position"] == 2
    assert job["progress_pct"] == 0
    assert job["remaining_seconds"] == 500


def test_queued_job_wait_includes_predecessor_plus_own_duration():
    """Kanonische Queue-Regel: Job #2 zeigt finish−now, nicht start−now."""
    from game.queue_card import map_build_queue_to_card_jobs

    jobs = map_build_queue_to_card_jobs(
        {
            "queue": [
                {
                    "id": 1,
                    "building_type": "metal_mine",
                    "target_level": 2,
                    "remaining": 4,
                    "total": 10,
                    "finish_time": NOW + 4,
                },
                {
                    "id": 2,
                    "building_type": "crystal_mine",
                    "target_level": 2,
                    "remaining": 16,
                    "total": 12,
                    "finish_time": NOW + 16,
                },
            ]
        },
        now=NOW,
    )
    assert jobs[0]["remaining_seconds"] == 4
    assert jobs[1]["status"] == STATUS_QUEUED
    assert jobs[1]["remaining_seconds"] == 16
    assert jobs[1]["remaining_seconds"] != max(0, int(jobs[1]["start_at"] - NOW))


def test_progress_clamp_active():
    assert compute_progress_pct(status=STATUS_ACTIVE, remaining_seconds=0, duration_seconds=100) == 100
    assert compute_progress_pct(status=STATUS_ACTIVE, remaining_seconds=100, duration_seconds=100) == 0
    assert compute_progress_pct(status=STATUS_ACTIVE, remaining_seconds=50, duration_seconds=100) == 50
    # remaining longer than duration must not go negative
    assert compute_progress_pct(status=STATUS_ACTIVE, remaining_seconds=200, duration_seconds=100) == 0
    assert compute_progress_pct(status=STATUS_QUEUED, remaining_seconds=10, duration_seconds=100) == 0


def test_empty_list_from_missing_payload():
    assert map_build_queue_to_card_jobs(None) == []
    assert map_build_queue_to_card_jobs({}) == []
    assert map_build_queue_to_card_jobs({"queue": []}) == []
    assert map_research_queue_to_card_jobs({"queue": None}) == []


def test_missing_invalid_times_do_not_crash():
    job = normalize_card_queue_job(
        owner_type="building",
        owner_key="solar_plant",
        job_id=1,
        queue_position=1,
        start_at="not-a-time",
        finish_at=None,
        now=NOW,
    )
    assert job["start_at"] == 0.0
    assert job["finish_at"] == 0.0
    assert job["remaining_seconds"] == 0
    assert job["progress_pct"] == 0

    job_nan = normalize_card_queue_job(
        owner_type="building",
        owner_key="solar_plant",
        job_id=2,
        queue_position=1,
        start_at=NOW,
        finish_at=float("nan"),
        now=NOW,
    )
    assert job_nan["finish_at"] == 0.0
    assert math.isfinite(job_nan["remaining_seconds"])


def test_map_build_queue_to_card_jobs():
    payload = {
        "planet_id": 1,
        "queue": [
            {
                "id": 10,
                "building_type": "metal_mine",
                "label_key": "building_metal_mine",
                "target_level": 4,
                "remaining": 40,
                "total": 100,
                "finish_time": NOW + 40,
            },
            {
                "id": 11,
                "building_type": "crystal_mine",
                "label_key": "building_crystal_mine",
                "target_level": 3,
                "remaining": 140,
                "total": 100,
                "finish_time": NOW + 140,
            },
        ],
    }
    jobs = map_build_queue_to_card_jobs(payload, now=NOW)
    assert len(jobs) == 2
    assert jobs[0]["owner_key"] == "metal_mine"
    assert jobs[0]["status"] == STATUS_ACTIVE
    assert jobs[1]["status"] == STATUS_QUEUED
    assert jobs[1]["queue_position"] == 2


def test_group_and_lookup_by_owner_key():
    jobs = map_build_queue_to_card_jobs(
        {
            "queue": [
                {
                    "id": 1,
                    "building_type": "metal_mine",
                    "target_level": 2,
                    "remaining": 10,
                    "total": 50,
                    "finish_time": NOW + 10,
                },
                {
                    "id": 2,
                    "building_type": "metal_mine",
                    "target_level": 3,
                    "remaining": 70,
                    "total": 50,
                    "finish_time": NOW + 70,
                },
            ]
        },
        now=NOW,
    )
    grouped = group_card_jobs_by_owner_key(jobs)
    assert len(grouped["metal_mine"]) == 2
    first = card_queue_job_for_item(grouped, "metal_mine")
    assert first is not None
    assert first["status"] == STATUS_ACTIVE
    assert card_queue_job_for_item(grouped, "missing") is None
