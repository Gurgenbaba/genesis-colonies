"""GC-600 — Defense System Phase 1 (build queue, planet scope, GC-000 envelope)."""

from __future__ import annotations

import importlib
import os
import time
import uuid

import pytest

from game import db as gdb
from game.db import db
from game.defense import (
    build_defense,
    defense_queue_table_ready,
    finish_due_defense_jobs_for_planet,
    list_defense_queue_rows,
)
from game.defense_api import cancel_defense_job
from game.models import (
    create_user,
    defense_schema_ready,
    ensure_player_and_homeworld,
    get_planet_defense,
    get_planets_by_player,
    init_db,
)
from game.planet_evolution.service import colonize_planet


@pytest.fixture
def defense_db(tmp_path, monkeypatch):
    db_path = tmp_path / "defense_phase1.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"def_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Defender", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _fund_planet(cur, planet_id: int, *, metal=500_000, crystal=500_000):
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ? WHERE id = ?;",
        (metal, crystal, int(planet_id)),
    )


def _grant_defense_prereqs(cur, planet_id: int, user_id: int, *, factory_level: int = 1) -> None:
    cur.execute(
        "UPDATE planet_buildings SET defense_factory = ? WHERE planet_id = ?;",
        (int(factory_level), int(planet_id)),
    )
    cur.execute(
        """
        INSERT INTO research_levels (user_id, tech_key, level)
        VALUES (?, 'weapon_tech', 2)
        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
        """,
        (int(user_id),),
    )


def _login_client(defense_db, monkeypatch):
    import game.db as dbmod
    import game.models as models

    db_path = os.environ.get("GC_DB_PATH")
    dbmod.DB_PATH = db_path
    models.DB_PATH = db_path
    import app as app_module

    importlib.reload(app_module)

    conn = db()
    uid = _player(conn=conn)
    uname = conn.execute("SELECT username FROM users WHERE id = ?;", (uid,)).fetchone()["username"]
    conn.close()

    client = app_module.app.test_client()
    client.post("/login", data={"username": uname, "password": "test-pass-123"})
    return client, uid, app_module


def test_defense_schema_and_queue_ready(defense_db):
    conn = db()
    assert defense_schema_ready(conn)
    assert defense_queue_table_ready(conn)
    conn.close()


def test_build_defense_requires_factory(defense_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    _fund_planet(conn.cursor(), pid)
    conn.commit()
    ok, reason, _ = build_defense(
        player_id=uid, planet_id=pid, defense_key="sentinel_turret", amount=1, conn=conn
    )
    assert not ok
    assert reason == "defense_factory_required"
    conn.close()


def test_build_defense_delivers_to_planet_stock(defense_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _grant_defense_prereqs(cur, pid, uid)
    conn.commit()

    ok, reason, result = build_defense(
        player_id=uid, planet_id=pid, defense_key="sentinel_turret", amount=2, conn=conn
    )
    assert ok, reason
    assert result["defense_queue"]["summary"]["count"] == 1

    cur.execute(
        "UPDATE defense_queue SET finish_at = ? WHERE planet_id = ?;",
        (time.time() - 1, pid),
    )
    conn.commit()
    finish_due_defense_jobs_for_planet(conn, pid, uid, now=time.time())
    stock = get_planet_defense(pid, conn=conn)
    assert stock.get("sentinel_turret", 0) >= 2
    conn.close()


def test_defense_stock_is_planet_scoped(defense_db):
    conn = db()
    uid = _player(conn=conn)
    home = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    ok, reason, extra = colonize_planet(
        uid, name="Outpost", galaxy=1, system=301, position=8, conn=conn
    )
    assert ok, reason
    colony = int(extra["planet_id"])
    cur = conn.cursor()
    _fund_planet(cur, home)
    _fund_planet(cur, colony)
    _grant_defense_prereqs(cur, home, uid)
    _grant_defense_prereqs(cur, colony, uid)
    conn.commit()

    ok, reason, _ = build_defense(
        player_id=uid,
        planet_id=home,
        defense_key="sentinel_turret",
        amount=1,
        conn=conn,
    )
    assert ok, reason
    cur.execute(
        "UPDATE defense_queue SET finish_at = ? WHERE planet_id = ?;",
        (time.time() - 1, home),
    )
    conn.commit()
    finish_due_defense_jobs_for_planet(conn, home, uid, now=time.time())

    assert get_planet_defense(home, conn=conn).get("sentinel_turret", 0) >= 1
    assert get_planet_defense(colony, conn=conn).get("sentinel_turret", 0) == 0
    conn.close()


def test_cancel_first_job_reschedules_follower(defense_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _grant_defense_prereqs(cur, pid, uid)
    conn.commit()

    now = time.time()
    ok1, _, _ = build_defense(
        player_id=uid, planet_id=pid, defense_key="sentinel_turret", amount=1, conn=conn
    )
    ok2, _, _ = build_defense(
        player_id=uid, planet_id=pid, defense_key="sentinel_turret", amount=1, conn=conn
    )
    assert ok1 and ok2
    rows_before = list_defense_queue_rows(pid, conn=conn)
    assert len(rows_before) == 2
    follower_id = int(rows_before[1]["id"])
    follower_finish_before = float(rows_before[1]["finish_at"])

    ok_cancel, reason_cancel = cancel_defense_job(
        player_id=uid, planet_id=pid, job_id=int(rows_before[0]["id"]), conn=conn
    )
    assert ok_cancel, reason_cancel
    conn.commit()

    rows_after = list_defense_queue_rows(pid, conn=conn)
    assert len(rows_after) == 1
    assert int(rows_after[0]["id"]) == follower_id
    assert float(rows_after[0]["started_at"]) <= now + 2
    assert float(rows_after[0]["finish_at"]) <= follower_finish_before + 2
    conn.close()


def test_api_defense_build_returns_state(defense_db, monkeypatch):
    import app as app_mod

    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _grant_defense_prereqs(cur, pid, uid)
    conn.commit()
    conn.close()

    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid

    res = client.post(
        "/api/defense/build",
        json={"defense_key": "sentinel_turret", "amount": 1, "planet_id": pid},
        headers={"Content-Type": "application/json"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert "state" in data
    assert data["state"]["ok"] is True
    assert "queue" in data
    assert "defenses" in data
    assert data["queue"]["summary"]["count"] >= 1


def test_main_js_defense_uses_apply_action_state_and_cleanup():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "static" / "main.js").read_text(encoding="utf-8")
    assert "GC.registerCleanup(stopDefenseTimers)" in src
    assert '"/api/defense/build"' in src
    assert '"/api/defense/cancel"' in src
    assert 'applyActionState(res, "defense_build")' in src
    assert 'applyActionState(res, "defense_cancel")' in src
    assert "GC.modules.defense = initDefense" in src
