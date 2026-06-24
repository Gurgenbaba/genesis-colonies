"""GC-831 — Queue cancel refunds (build, research, shipyard pending)."""

from __future__ import annotations

import time

import pytest

import game.db as dbmod
import game.models as models
from game.buildings import cancel_build_job_for_planet, get_upgrade_cost, queue_build_for_planet
from game.models import get_build_queue_rows, get_homeworld, get_planet_buildings
from game.queue_refund import REFUND_RATIO_ACTIVE, REFUND_RATIO_PENDING
from game.research import cancel_research_job, get_research_cost, queue_research


@pytest.fixture()
def refund_db(tmp_path, monkeypatch):
    db_file = tmp_path / "gc831.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_file))
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    monkeypatch.setattr(models, "DB_PATH", db_file)
    models.init_db()
    ok, err, info = models.create_user("gc831_user", "secret123")
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


def _metal_crystal(planet_id: int) -> tuple[float, float]:
    conn = models.db()
    row = conn.execute(
        "SELECT metal, crystal FROM planets WHERE id = ?;",
        (int(planet_id),),
    ).fetchone()
    conn.close()
    return float(row["metal"]), float(row["crystal"])


def test_build_cancel_pending_refunds_full_cost(refund_db):
    user_id, planet = refund_db
    planet_id = int(planet["id"])
    buildings = get_planet_buildings(planet_id)
    metal_before, crystal_before = _metal_crystal(planet_id)

    ok, reason, _ = queue_build_for_planet(planet, buildings, "metal_mine", user_id=user_id)
    assert ok and reason == "ok"

    metal_after_queue, crystal_after_queue = _metal_crystal(planet_id)
    job = get_build_queue_rows(planet_id)[0]
    cost_m, cost_c = get_upgrade_cost("metal_mine", int(buildings.get("metal_mine", 0) or 0))
    assert metal_before - metal_after_queue == pytest.approx(cost_m, rel=0.01)
    assert crystal_before - crystal_after_queue == pytest.approx(cost_c, rel=0.01)

    now = time.time()
    conn = models.db()
    conn.execute(
        "UPDATE build_queue SET start_time = ?, finish_time = ? WHERE id = ?;",
        (now + 500, now + 600, int(job["id"])),
    )
    conn.commit()
    conn.close()

    ok, reason, payload = cancel_build_job_for_planet(planet_id, int(job["id"]), user_id=user_id)
    assert ok and reason == "ok"
    assert payload["refund_ratio"] == REFUND_RATIO_PENDING

    metal_after, crystal_after = _metal_crystal(planet_id)
    assert metal_after - metal_after_queue == pytest.approx(cost_m, rel=0.01)
    assert crystal_after - crystal_after_queue == pytest.approx(cost_c, rel=0.01)


def test_build_cancel_active_refunds_half_cost(refund_db):
    user_id, planet = refund_db
    planet_id = int(planet["id"])
    buildings = get_planet_buildings(planet_id)

    ok, reason, _ = queue_build_for_planet(planet, buildings, "crystal_mine", user_id=user_id)
    assert ok and reason == "ok"

    metal_after_queue, crystal_after_queue = _metal_crystal(planet_id)
    job = get_build_queue_rows(planet_id)[0]
    cost_m, cost_c = get_upgrade_cost("crystal_mine", int(buildings.get("crystal_mine", 0) or 0))

    now = time.time()
    conn = models.db()
    conn.execute(
        "UPDATE build_queue SET start_time = ?, finish_time = ? WHERE id = ?;",
        (now - 30, now + 120, int(job["id"])),
    )
    conn.commit()
    conn.close()

    ok, reason, payload = cancel_build_job_for_planet(planet_id, int(job["id"]), user_id=user_id)
    assert ok and reason == "ok"
    assert payload["refund_ratio"] == REFUND_RATIO_ACTIVE

    metal_after, crystal_after = _metal_crystal(planet_id)
    assert metal_after - metal_after_queue == pytest.approx(cost_m * REFUND_RATIO_ACTIVE, rel=0.01)
    assert crystal_after - crystal_after_queue == pytest.approx(cost_c * REFUND_RATIO_ACTIVE, rel=0.01)


def test_research_cancel_pending_refunds_full_cost(refund_db):
    user_id, planet = refund_db
    planet_id = int(planet["id"])
    player = models.load_player(user_id)
    assert player is not None

    conn = models.db()
    conn.execute(
        "UPDATE planet_buildings SET research_lab = 3 WHERE planet_id = ?;",
        (planet_id,),
    )
    conn.commit()
    conn.close()

    metal_before, crystal_before = _metal_crystal(planet_id)
    ok, reason, _ = queue_research(player, "energy_tech", user_id=user_id)
    assert ok and reason == "ok"

    metal_after_queue, crystal_after_queue = _metal_crystal(planet_id)
    cost_m, cost_c = get_research_cost("energy_tech", 1)
    assert metal_before - metal_after_queue == pytest.approx(cost_m, rel=0.01)

    from game.models import get_research_queue_rows

    job = get_research_queue_rows(user_id)[0]
    now = time.time()
    conn = models.db()
    conn.execute(
        "UPDATE research_queue SET start_at = ?, finish_at = ? WHERE id = ?;",
        (now + 400, now + 500, int(job["id"])),
    )
    conn.commit()
    conn.close()

    ok, reason, payload = cancel_research_job(user_id, int(job["id"]))
    assert ok and reason == "ok"
    assert payload["refund_ratio"] == REFUND_RATIO_PENDING

    metal_after, _ = _metal_crystal(planet_id)
    assert metal_after - metal_after_queue == pytest.approx(cost_m, rel=0.01)


def test_max_queue_jobs_store_paid_cost_snapshots(refund_db):
    user_id, planet = refund_db
    planet_id = int(planet["id"])
    buildings = get_planet_buildings(planet_id)
    lvl = int(buildings.get("metal_mine", 0) or 0)

    ok, reason, payload = queue_build_for_planet(
        planet, buildings, "metal_mine", user_id=user_id, queue_mode="max"
    )
    assert ok and reason == "ok"
    assert int(payload.get("jobs_queued") or 1) >= 2

    rows = get_build_queue_rows(planet_id)
    for i, row in enumerate(rows):
        expected_m, expected_c = get_upgrade_cost("metal_mine", lvl + i)
        assert int(row["cost_metal"]) == int(expected_m)
        assert int(row["cost_crystal"]) == int(expected_c)
