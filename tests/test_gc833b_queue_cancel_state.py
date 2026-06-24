"""
GC-833B — Cancelled queue jobs must not appear in client payloads.

Run: python -m pytest tests/test_gc833b_queue_cancel_state.py -v
"""

from __future__ import annotations

import time

import pytest

import game.db as dbmod
import game.models as models
from game.buildings import cancel_build_job_for_planet, get_build_queue_status_for_planet, queue_build_for_planet
from game.models import get_build_queue_rows, get_homeworld, get_planet_buildings
from game.queue_card import map_build_queue_to_card_jobs


@pytest.fixture()
def cancel_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc833b.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    models.init_db()
    ok, err, info = models.create_user("gc833b_user", "secret123")
    assert ok, err
    uid = int(info["id"])
    planet = get_homeworld(player_id=uid)
    conn = models.db()
    conn.execute(
        "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
        (2_000_000, 2_000_000, int(planet["id"])),
    )
    conn.commit()
    conn.close()
    return uid, dict(planet)


def test_build_cancel_removes_job_from_db_and_payload(cancel_db):
    user_id, planet = cancel_db
    planet_id = int(planet["id"])
    buildings = get_planet_buildings(planet_id)

    ok, reason, _ = queue_build_for_planet(planet, buildings, "crystal_mine", user_id=user_id)
    assert ok and reason == "ok"
    job_id = int(get_build_queue_rows(planet_id)[0]["id"])

    now = time.time()
    conn = models.db()
    conn.execute(
        "UPDATE build_queue SET start_time = ?, finish_time = ? WHERE id = ?;",
        (now - 20, now + 80, job_id),
    )
    conn.commit()
    conn.close()

    ok, reason, _ = cancel_build_job_for_planet(planet_id, job_id, user_id=user_id)
    assert ok and reason == "ok"
    assert get_build_queue_rows(planet_id) == []

    from flask import Flask

    app = Flask("gc833b_cancel")
    with app.test_request_context("/"):
        payload = get_build_queue_status_for_planet(planet_id, conn=models.db(), skip_finish=True)

    assert payload["queue"] == []
    assert payload["summary"]["count"] == 0
    card_jobs = map_build_queue_to_card_jobs(payload, now=time.time())
    assert card_jobs == []
    assert "crystal_mine" not in (payload.get("card_jobs_by_owner") or {})


def test_build_cancel_active_refunds_and_leaves_no_due_zombie(cancel_db):
    user_id, planet = cancel_db
    planet_id = int(planet["id"])
    buildings = get_planet_buildings(planet_id)
    metal_before = float(
        models.db()
        .execute("SELECT metal FROM planets WHERE id = ?;", (planet_id,))
        .fetchone()["metal"]
    )

    ok, _, _ = queue_build_for_planet(planet, buildings, "metal_mine", user_id=user_id)
    assert ok
    job_id = int(get_build_queue_rows(planet_id)[0]["id"])
    metal_after_enqueue = float(
        models.db()
        .execute("SELECT metal FROM planets WHERE id = ?;", (planet_id,))
        .fetchone()["metal"]
    )
    assert metal_after_enqueue < metal_before

    ok, reason, payload = cancel_build_job_for_planet(planet_id, job_id, user_id=user_id)
    assert ok and reason == "ok"
    assert payload.get("refund_ratio", 0) > 0
    assert get_build_queue_rows(planet_id) == []

    metal_after_cancel = float(
        models.db()
        .execute("SELECT metal FROM planets WHERE id = ?;", (planet_id,))
        .fetchone()["metal"]
    )
    assert metal_after_cancel > metal_after_enqueue
