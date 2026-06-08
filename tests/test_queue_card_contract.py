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
    card_queue_job_identity,
    card_queue_jobs_for_item,
    compute_progress_pct,
    group_card_jobs_by_owner_key,
    map_build_queue_to_card_jobs,
    map_defense_queue_to_card_jobs,
    map_research_queue_to_card_jobs,
    map_shipyard_queue_to_card_jobs,
    normalize_card_queue_job,
    reconcile_card_queue_jobs,
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


def test_card_queue_jobs_for_item_returns_all_same_owner_jobs():
    payload = {
        "queue": [
            {
                "id": 10,
                "ship_key": "hauler",
                "amount_total": 1,
                "order_remaining": 60,
                "order_total_seconds": 60,
                "finish_at": NOW + 60,
                "started_at": NOW,
                "is_active": True,
            },
            {
                "id": 11,
                "ship_key": "hauler",
                "amount_total": 1,
                "order_remaining": 120,
                "order_total_seconds": 60,
                "finish_at": NOW + 120,
                "started_at": NOW + 60,
                "is_active": False,
            },
            {
                "id": 12,
                "ship_key": "hauler",
                "amount_total": 1,
                "order_remaining": 180,
                "order_total_seconds": 60,
                "finish_at": NOW + 180,
                "started_at": NOW + 120,
                "is_active": False,
            },
        ]
    }
    jobs = map_shipyard_queue_to_card_jobs(payload, now=NOW)
    grouped = group_card_jobs_by_owner_key(jobs)
    assert len(grouped["hauler"]) == 3
    all_jobs = card_queue_jobs_for_item(grouped, "hauler")
    assert len(all_jobs) == 3
    assert [j["job_id"] for j in all_jobs] == [10, 11, 12]
    assert all_jobs[0]["status"] == STATUS_ACTIVE
    assert all_jobs[1]["status"] == STATUS_QUEUED
    assert all_jobs[0]["remaining_seconds"] < all_jobs[1]["remaining_seconds"] < all_jobs[2]["remaining_seconds"]


def test_card_queue_job_identity_is_job_based_not_type_only():
    job_a = normalize_card_queue_job(
        owner_type="defense",
        owner_key="laser_turret",
        job_id=5,
        queue_position=1,
        start_at=NOW,
        finish_at=NOW + 30,
        now=NOW,
        target_amount=1,
    )
    job_b = normalize_card_queue_job(
        owner_type="defense",
        owner_key="laser_turret",
        job_id=6,
        queue_position=2,
        start_at=NOW + 30,
        finish_at=NOW + 60,
        now=NOW,
        target_amount=1,
    )
    assert card_queue_job_identity(job_a) != card_queue_job_identity(job_b)
    assert ":5:" in card_queue_job_identity(job_a)
    assert ":6:" in card_queue_job_identity(job_b)


def test_defense_same_unit_multiple_jobs_grouped():
    payload = {
        "queue": [
            {
                "id": 21,
                "defense_key": "laser_turret",
                "amount_total": 1,
                "order_remaining": 40,
                "order_total_seconds": 40,
                "finish_at": NOW + 40,
                "started_at": NOW,
            },
            {
                "id": 22,
                "defense_key": "laser_turret",
                "amount_total": 1,
                "order_remaining": 80,
                "order_total_seconds": 40,
                "finish_at": NOW + 80,
                "started_at": NOW + 40,
            },
        ]
    }
    jobs = map_defense_queue_to_card_jobs(payload, now=NOW)
    grouped = group_card_jobs_by_owner_key(jobs)
    assert len(card_queue_jobs_for_item(grouped, "laser_turret")) == 2


def test_gc537_reconcile_collapsed_positions_only_one_active():
    """GC-537: duplicate queue_position must not yield multiple active cards."""
    raw = [
        normalize_card_queue_job(
            owner_type="shipyard",
            owner_key="hauler",
            job_id=1,
            queue_position=1,
            start_at=NOW,
            finish_at=NOW + 30,
            now=NOW,
        ),
        normalize_card_queue_job(
            owner_type="shipyard",
            owner_key="hauler",
            job_id=2,
            queue_position=1,
            start_at=NOW,
            finish_at=NOW + 90,
            now=NOW,
            remaining_seconds=0,
        ),
        normalize_card_queue_job(
            owner_type="shipyard",
            owner_key="hauler",
            job_id=3,
            queue_position=1,
            start_at=NOW,
            finish_at=NOW + 150,
            now=NOW,
            remaining_seconds=0,
        ),
    ]
    jobs = reconcile_card_queue_jobs(raw, now=NOW)
    active = [j for j in jobs if j["status"] == STATUS_ACTIVE]
    queued = [j for j in jobs if j["status"] == STATUS_QUEUED]
    assert len(active) == 1
    assert len(queued) == 2
    assert active[0]["job_id"] == 1
    assert queued[0]["remaining_seconds"] == 90
    assert queued[1]["remaining_seconds"] == 150


def test_gc537_three_same_shipyard_jobs_sequential_status():
    payload = {
        "queue": [
            {
                "id": 10,
                "ship_key": "hauler",
                "amount_total": 1,
                "order_remaining": 25,
                "order_total_seconds": 60,
                "finish_at": NOW + 25,
                "started_at": NOW,
                "is_active": True,
            },
            {
                "id": 11,
                "ship_key": "hauler",
                "amount_total": 1,
                "order_remaining": 85,
                "order_total_seconds": 60,
                "finish_at": NOW + 85,
                "started_at": NOW + 25,
                "is_active": True,
            },
            {
                "id": 12,
                "ship_key": "hauler",
                "amount_total": 1,
                "order_remaining": 145,
                "order_total_seconds": 60,
                "finish_at": NOW + 145,
                "started_at": NOW + 85,
                "is_active": True,
            },
        ]
    }
    jobs = map_shipyard_queue_to_card_jobs(payload, now=NOW)
    grouped = group_card_jobs_by_owner_key(jobs)
    all_jobs = card_queue_jobs_for_item(grouped, "hauler")
    assert len(all_jobs) == 3
    assert sum(1 for j in all_jobs if j["status"] == STATUS_ACTIVE) == 1
    assert all_jobs[0]["status"] == STATUS_ACTIVE
    assert all_jobs[1]["status"] == STATUS_QUEUED
    assert all_jobs[2]["status"] == STATUS_QUEUED
    assert all_jobs[0]["remaining_seconds"] < all_jobs[1]["remaining_seconds"] < all_jobs[2]["remaining_seconds"]
