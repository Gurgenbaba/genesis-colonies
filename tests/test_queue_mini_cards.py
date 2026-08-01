"""
GC-QUEUE-MINI-CARDS — shipyard / defense mini-queue payload contracts.

Run: python -m pytest tests/test_queue_mini_cards.py -v
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

import game.db as gdb
from game.db import db
from game.defense import build_defense, build_defense_api_payload
from game.defense_api import cancel_defense_job
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.queue_card import (
    STATUS_ACTIVE,
    map_build_queue_to_card_jobs,
    map_card_jobs_to_mini_queue_jobs,
    map_defense_queue_to_card_jobs,
    map_research_queue_to_card_jobs,
    map_shipyard_queue_to_card_jobs,
)
from game.shipyard import build_ship, build_shipyard_api_payload, cancel_shipyard_job

ROOT = Path(__file__).resolve().parents[1]

_NOW = 1_700_000_160.0


def test_shipyard_mini_queue_uses_amount_remaining_not_total():
    """After progressive delivery, ×N must show remaining — not original amount_total."""
    queue = {
        "queue": [
            {
                "id": 10,
                "ship_key": "mule_courier",
                "amount": 600,
                "amount_total": 1000,
                "amount_remaining": 600,
                "units_delivered": 400,
                "order_remaining": 260,
                "order_total_seconds": 420,
                "finish_at": 1_700_000_420.0,
                "started_at": 1_700_000_000.0,
                "is_active": True,
            }
        ],
        "summary": {"count": 1, "limit": 3},
    }
    card_jobs = map_shipyard_queue_to_card_jobs(queue, now=_NOW)
    mini = map_card_jobs_to_mini_queue_jobs(card_jobs, domain="shipyard", now=_NOW)
    assert card_jobs[0]["target_amount"] == 600
    assert mini[0]["amount"] == 600


def _shipyard_queue(*, multi: bool = False) -> dict:
    jobs = [
        {
            "id": 10,
            "ship_key": "mule_courier",
            "amount_total": 1000,
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
                "amount_total": 500,
                "order_remaining": 1124,
                "order_total_seconds": 900,
                "finish_at": 1_700_001_284.0,
                "started_at": 1_700_000_420.0,
                "is_active": False,
            }
        )
    return {"queue": jobs, "summary": {"count": len(jobs), "limit": 3}}


def _defense_queue(*, multi: bool = False) -> dict:
    jobs = [
        {
            "id": 40,
            "defense_key": "laser_turret",
            "amount_total": 8,
            "order_remaining": 180,
            "order_total_seconds": 360,
            "finish_at": 1_700_000_340.0,
            "started_at": 1_700_000_000.0,
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
    return {"queue": jobs, "summary": {"count": len(jobs), "limit": 3}}


@pytest.fixture
def mini_sy_db(tmp_path, monkeypatch):
    db_path = tmp_path / "mini_sy.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


@pytest.fixture
def mini_def_db(tmp_path, monkeypatch):
    db_path = tmp_path / "mini_def.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _sy_player(conn):
    ok, err, user = create_user(f"mq_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, conn=conn)
    return uid


def _setup_shipyard(conn, uid, pid):
    from tests.test_shipyard import _grant_ship_test_prereqs

    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET metal = 500000, crystal = 500000, fuel_cells = 5000 WHERE id = ?;",
        (pid,),
    )
    cur.execute(
        "UPDATE planet_buildings SET orbital_shipyard = 2 WHERE planet_id = ?;",
        (pid,),
    )
    _grant_ship_test_prereqs(cur, pid, uid)
    conn.commit()


def _setup_defense(conn, uid, pid):
    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET metal = 500000, crystal = 500000 WHERE id = ?;",
        (pid,),
    )
    cur.execute(
        "UPDATE planet_buildings SET defense_factory = 1 WHERE planet_id = ?;",
        (pid,),
    )
    cur.execute(
        """
        INSERT INTO research_levels (user_id, tech_key, level)
        VALUES (?, 'weapon_tech', 2)
        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
        """,
        (int(uid),),
    )
    conn.commit()


def test_shipyard_mini_queue_payload_fields():
    card_jobs = map_shipyard_queue_to_card_jobs(_shipyard_queue(), now=_NOW)
    mini = map_card_jobs_to_mini_queue_jobs(card_jobs, domain="shipyard", now=_NOW)
    assert len(mini) == 1
    job = mini[0]
    assert job["job_id"] == 10
    assert job["domain"] == "shipyard"
    assert job["owner_key"] == "mule_courier"
    assert job["amount"] == 1000
    assert job["position"] == 1
    assert job["is_active"] is True
    assert job["remaining_seconds"] == 260
    assert job["image_url"].endswith("mule_courier.png")
    assert job["cancelable"] is True


def test_defense_mini_queue_payload_fields():
    card_jobs = map_defense_queue_to_card_jobs(_defense_queue(), now=_NOW)
    mini = map_card_jobs_to_mini_queue_jobs(card_jobs, domain="defense", now=_NOW)
    assert len(mini) == 1
    job = mini[0]
    assert job["job_id"] == 40
    assert job["domain"] == "defense"
    assert job["owner_key"] == "laser_turret"
    assert job["amount"] == 8
    assert job["position"] == 1
    assert job["is_active"] is True
    assert job["remaining_seconds"] == 180
    assert "/static/img/defense/laser_turret.png" in job["image_url"]


def test_research_mini_queue_resolves_storage_tech_icon():
    research = {
        "queue": [
            {
                "id": 7,
                "tech_key": "storage_tech",
                "key": "storage_tech",
                "label": "Lagertechnik",
                "target_level": 2,
                "remaining": 120,
                "total_seconds": 770,
                "finish_at": _NOW + 120,
                "start_at": _NOW,
                "position": 1,
            }
        ]
    }
    card_jobs = map_research_queue_to_card_jobs(research, now=_NOW)
    mini = map_card_jobs_to_mini_queue_jobs(card_jobs, domain="research", now=_NOW)
    assert len(mini) == 1
    assert mini[0]["owner_key"] == "storage_tech"
    assert mini[0]["label"] == "storage_tech"
    assert mini[0]["image_url"] == "/static/img/research/lagertechnik.png"


def test_building_mini_queue_resolves_icon_alias():
    build_queue = {
        "queue": [
            {
                "id": 3,
                "building_type": "orbital_shipyard",
                "target_level": 2,
                "remaining": 90,
                "total": 300,
                "finish_time": _NOW + 90,
            }
        ]
    }
    card_jobs = map_build_queue_to_card_jobs(build_queue, now=_NOW)
    mini = map_card_jobs_to_mini_queue_jobs(card_jobs, domain="building", now=_NOW)
    assert len(mini) == 1
    assert mini[0]["owner_key"] == "orbital_shipyard"
    assert mini[0]["image_url"] == "/static/img/buildings/shipyard.png"


def test_waiting_job_remaining_is_finish_minus_now_not_start():
    card_jobs = map_shipyard_queue_to_card_jobs(_shipyard_queue(multi=True), now=_NOW)
    mini = map_card_jobs_to_mini_queue_jobs(card_jobs, domain="shipyard", now=_NOW)
    queued = next(j for j in mini if j["owner_key"] == "seed_ark")
    assert queued["is_active"] is False
    assert queued["position"] == 2
    assert queued["remaining_seconds"] == int(1_700_001_284.0 - _NOW)


def test_mini_queue_renumbers_positions_after_sort():
    card_jobs = map_defense_queue_to_card_jobs(_defense_queue(multi=True), now=_NOW)
    mini = map_card_jobs_to_mini_queue_jobs(card_jobs, domain="defense", now=_NOW)
    positions = [j["position"] for j in mini]
    assert positions == [1, 2]


def test_due_jobs_excluded_from_mini_queue():
    card_jobs = map_shipyard_queue_to_card_jobs(_shipyard_queue(), now=_NOW)
    zombie = dict(card_jobs[0])
    zombie["finish_at"] = _NOW - 5
    zombie["remaining_seconds"] = 0
    zombie["status"] = STATUS_ACTIVE
    mini = map_card_jobs_to_mini_queue_jobs([zombie], domain="shipyard", now=_NOW)
    assert mini == []


def test_shipyard_api_payload_includes_mini_queue_jobs(mini_sy_db):
    conn = db()
    uid = _sy_player(conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _setup_shipyard(conn, uid, pid)
    ok, _, _ = build_ship(player_id=uid, planet_id=pid, ship_key="mule_courier", amount=2, conn=conn)
    assert ok
    conn.commit()
    payload = build_shipyard_api_payload(uid, pid, conn=conn)
    mini = payload["shipyard_queue"].get("mini_queue_jobs") or []
    assert mini
    assert mini[0]["job_id"] > 0
    assert mini[0]["remaining_seconds"] > 0
    conn.close()


def test_cancel_shipyard_removes_job_from_mini_queue_payload(mini_sy_db):
    conn = db()
    uid = _sy_player(conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _setup_shipyard(conn, uid, pid)
    ok, _, result = build_ship(player_id=uid, planet_id=pid, ship_key="mule_courier", amount=1, conn=conn)
    assert ok and result
    job_id = int(result["shipyard_queue"]["queue"][0]["id"])
    conn.commit()
    before = build_shipyard_api_payload(uid, pid, conn=conn)
    assert before["shipyard_queue"]["mini_queue_jobs"]
    ok_c, _, _ = cancel_shipyard_job(player_id=uid, planet_id=pid, job_id=job_id, conn=conn)
    assert ok_c
    conn.commit()
    after = build_shipyard_api_payload(uid, pid, conn=conn)
    assert not after["shipyard_queue"].get("mini_queue_jobs")
    conn.close()


def test_cancel_defense_removes_job_from_mini_queue_payload(mini_def_db):
    conn = db()
    uid = _sy_player(conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _setup_defense(conn, uid, pid)
    ok, _, result = build_defense(
        player_id=uid, planet_id=pid, defense_key="sentinel_turret", amount=1, conn=conn
    )
    assert ok and result
    job_id = int(result["defense_queue"]["queue"][0]["id"])
    conn.commit()
    before = build_defense_api_payload(uid, pid, conn=conn)
    assert before["defense_queue"]["mini_queue_jobs"]
    ok_c, _ = cancel_defense_job(player_id=uid, planet_id=pid, job_id=job_id, conn=conn)
    assert ok_c
    conn.commit()
    after = build_defense_api_payload(uid, pid, conn=conn)
    assert not after["defense_queue"].get("mini_queue_jobs")
    conn.close()


def test_templates_use_mini_queue_strip_not_card_queue():
    shipyard = (ROOT / "templates/shipyard.html").read_text(encoding="utf-8")
    defense = (ROOT / "templates/defense.html").read_text(encoding="utf-8")
    partial = (ROOT / "templates/partials/page_mini_queue_strip.html").read_text(encoding="utf-8")
    macros = (ROOT / "templates/partials/card_queue_macros.html").read_text(encoding="utf-8")
    assert "render_page_mini_queue_strip" in shipyard
    assert "shipyard-mini-queue" in shipyard
    assert "gc-card-queue-block" not in shipyard
    assert "shipyard_no_buildable" not in shipyard
    assert "render_page_mini_queue_strip" in defense
    assert "defense-mini-queue" in defense
    assert "gc-card-queue-block" not in defense
    assert "data-defense-queue-slot" not in defense
    assert "gc-mini-queue-strip" in partial
    # Central strip owns TK + cancel for unit queues.
    assert "render_timekeeper_apply_btn" in partial
    assert "data-gc-timekeeper-apply" in macros
    assert "gc-mini-queue-card__cancel" in partial
    assert "data-shipyard-queue-cancel" in shipyard
    assert "data-defense-queue-cancel" in defense


def test_mini_queue_includes_batch_size():
    from game.queue_card import enrich_mini_queue_jobs_batch_size, map_card_jobs_to_mini_queue_jobs
    from game.shipyard import base_unit_seconds_for_ship, production_job_duration_seconds, unit_batch_capacity

    card_jobs = map_shipyard_queue_to_card_jobs(_shipyard_queue(), now=_NOW)
    mini = enrich_mini_queue_jobs_batch_size(
        map_card_jobs_to_mini_queue_jobs(card_jobs, domain="shipyard", now=_NOW),
        domain="shipyard",
        shipyard_level=1,
    )
    cap = unit_batch_capacity(1, base_unit_seconds_for_ship("mule_courier"))
    assert mini[0]["batch_size"] == cap
    unit = 100
    assert production_job_duration_seconds(unit_seconds=unit, amount=3, batch_capacity=cap) == unit * (
        (3 + cap - 1) // cap
    )
    assert production_job_duration_seconds(unit_seconds=unit, amount=4, batch_capacity=cap) == unit * (
        (4 + cap - 1) // cap
    )


def test_shipyard_batch_duration_at_yard_capacity():
    """Yard parallel slots per cycle drive ceil(amount/cap) cycle count."""
    from game.shipyard import orbital_production_batch_capacity, production_job_duration_seconds

    cap = orbital_production_batch_capacity(1)
    unit = 100
    assert cap == 7
    assert production_job_duration_seconds(unit_seconds=unit, amount=7, batch_capacity=cap) == unit
    assert production_job_duration_seconds(unit_seconds=unit, amount=8, batch_capacity=cap) == unit * 2


def test_shipyard_level2_batch_capacity():
    from game.shipyard import orbital_production_batch_capacity

    assert orbital_production_batch_capacity(2) == 15


def test_main_js_exposes_render_mini_queue_strip():
    js = (ROOT / "static/main.js").read_text(encoding="utf-8")
    assert "GC.renderMiniQueueStrip = function renderMiniQueueStrip" in js
    assert "gc-mini-queue-card__cancel" in js
    assert "shipyardActionReasonText" in js
    assert "shipyard_error_cancel_failed" in (ROOT / "locales/de.json").read_text(encoding="utf-8")
