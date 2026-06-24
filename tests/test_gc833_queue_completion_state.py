"""
GC-833 — Global queue completion / zombie-state contract.

Run: python -m pytest tests/test_gc833_queue_completion_state.py -v
"""

from __future__ import annotations

import time
import uuid
from unittest.mock import patch

import pytest

from game.buildings import get_build_queue_status_for_planet
from game.live_state import coerce_skip_finish, mark_request_live_refreshed
from game.models import (
    create_user,
    get_homeworld,
    get_planet_buildings,
    init_db,
    save_planet_buildings,
)
from game.queue_card import (
    STATUS_ACTIVE,
    filter_client_visible_card_jobs,
    is_queue_job_client_visible,
    map_build_queue_to_card_jobs,
    normalize_card_queue_job,
)


@pytest.fixture()
def player_planet(tmp_path, monkeypatch):
    db_file = tmp_path / "gc833.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")

    import game.db as dbmod
    import game.models as models

    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    init_db()

    uname = f"gc833_{uuid.uuid4().hex[:8]}"
    ok, _, user = create_user(uname, "test-pass-123")
    assert ok and user
    pid = int(user["id"])
    planet = get_homeworld(player_id=pid)
    save_planet_buildings(int(planet["id"]), {"metal_mine": 1, "crystal_mine": 1})
    return pid, int(planet["id"])


def test_coerce_skip_finish_runs_finish_before_request_refresh():
    from flask import Flask

    app = Flask("gc833_coerce")
    with app.test_request_context("/"):
        assert coerce_skip_finish(True) is False
        assert coerce_skip_finish(False) is False
        mark_request_live_refreshed()
        assert coerce_skip_finish(True) is True
        assert coerce_skip_finish(False) is True


def test_forbidden_zombie_job_not_client_visible():
    now = 1_700_000_000.0
    zombie = normalize_card_queue_job(
        owner_type="building",
        owner_key="metal_mine",
        job_id=1,
        queue_position=1,
        start_at=now - 100,
        finish_at=now,
        now=now,
        label="building_metal_mine",
        target_level=2,
    )
    assert zombie["status"] == STATUS_ACTIVE
    assert zombie["remaining_seconds"] == 0
    assert zombie["progress_pct"] == 100
    assert is_queue_job_client_visible(zombie, now=now) is False
    assert filter_client_visible_card_jobs([zombie], now=now) == []


def test_map_build_queue_filters_due_active_job():
    now = 1_700_000_000.0
    jobs = map_build_queue_to_card_jobs(
        {
            "queue": [
                {
                    "id": 9,
                    "building_type": "metal_mine",
                    "target_level": 2,
                    "remaining": 0,
                    "total": 60,
                    "finish_time": now,
                }
            ]
        },
        now=now,
    )
    assert jobs == []


def test_build_queue_read_finishes_due_job_without_prior_refresh(player_planet):
    player_id, planet_id = player_planet
    from game.db import db
    from game.models import add_build_job

    now = time.time()
    add_build_job(
        planet_id,
        "metal_mine",
        now - 65,
        now - 5,
        cost_metal=100,
        cost_crystal=50,
    )

    from flask import Flask

    from game.models import commit

    app = Flask("gc833_finish")
    conn = db()
    with app.test_request_context("/"):
        payload = get_build_queue_status_for_planet(planet_id, conn=conn, skip_finish=True)
        commit(conn)

    assert payload["queue"] == []
    assert payload["summary"]["count"] == 0
    levels = get_planet_buildings(planet_id)
    assert int(levels.get("metal_mine") or 0) >= 2


def test_build_queue_read_skips_second_finish_after_refresh(player_planet):
    player_id, planet_id = player_planet
    from game.db import db
    from game.models import add_build_job

    now = time.time()
    add_build_job(
        planet_id,
        "crystal_mine",
        now,
        now + 120,
        cost_metal=100,
        cost_crystal=50,
    )

    from flask import Flask

    app = Flask("gc833_skip")
    with app.test_request_context("/"):
        mark_request_live_refreshed()
        with patch("game.queue_engine.finish_active_planet_due_work") as mock_finish:
            get_build_queue_status_for_planet(planet_id, conn=db(), skip_finish=True)
            mock_finish.assert_not_called()
