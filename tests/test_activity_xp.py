"""Tests for Activity XP grants, caps, and idempotency."""

from __future__ import annotations

import pytest

from game.activity_xp import (
    EXPEDITION_BONUS_AMOUNT,
    SOURCE_BUILDING_FINISH,
    SOURCE_EXPEDITION,
    SOURCE_SPY,
    grant_activity_xp,
    grant_fleet_activity_xp,
    grant_queue_job_activity_xp,
    get_activity_xp_dashboard,
)
from game.models import create_user, db, ensure_player_and_homeworld, get_planets_by_player
from game.planet_evolution.planet_research import finish_planet_research_jobs


@pytest.fixture
def axp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "activity_xp_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    from game import db as gdb

    gdb._DB_PATH = None
    from game.models import init_db

    init_db()
    import migrate

    migrate.main()
    conn = db()
    conn.commit()
    conn.close()
    yield
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"axp_{id(conn)}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="AxpTester", conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    if own:
        conn.commit()
        conn.close()
    return uid, pid


def test_grant_activity_xp_writes_log_and_planet_xp(axp_db):
    conn = db()
    uid, pid = _player(conn=conn)
    conn.execute("UPDATE planets SET planet_xp = 0, planet_level = 1 WHERE id = ?;", (pid,))
    conn.commit()

    result = grant_activity_xp(uid, pid, SOURCE_SPY, conn=conn, idempotency_key="spy:test:1")
    assert result["granted"] is True
    assert result["amount"] == 2
    assert result["planet_xp"]["xp_gained"] == 2

    row = conn.execute("SELECT planet_xp FROM planets WHERE id = ?;", (pid,)).fetchone()
    assert int(row["planet_xp"]) == 2

    log = conn.execute(
        "SELECT * FROM activity_xp_log WHERE player_id = ? AND source_key = ?;",
        (uid, SOURCE_SPY),
    ).fetchone()
    assert log is not None
    assert int(log["amount"]) == 2
    assert log["idempotency_key"] == "spy:test:1"
    conn.close()


def test_idempotency_prevents_duplicate_grant(axp_db):
    conn = db()
    uid, pid = _player(conn=conn)
    conn.commit()

    first = grant_fleet_activity_xp(uid, pid, SOURCE_EXPEDITION, 9001, conn=conn)
    second = grant_fleet_activity_xp(uid, pid, SOURCE_EXPEDITION, 9001, conn=conn)
    assert first["granted"] is True
    assert second["granted"] is False
    assert second["reason"] == "idempotent_duplicate"

    count = conn.execute(
        "SELECT COUNT(*) AS c FROM activity_xp_log WHERE idempotency_key = ?;",
        (f"{SOURCE_EXPEDITION}:fleet:9001",),
    ).fetchone()["c"]
    assert int(count) == 1
    conn.close()


def test_daily_cap_blocks_spy_farm(axp_db):
    conn = db()
    uid, pid = _player(conn=conn)
    conn.commit()

    granted = 0
    for i in range(15):
        res = grant_fleet_activity_xp(uid, pid, SOURCE_SPY, 10000 + i, conn=conn)
        if res["granted"]:
            granted += 1
    assert granted == 10  # 2 XP * 10 = 20 cap

    blocked = grant_fleet_activity_xp(uid, pid, SOURCE_SPY, 20000, conn=conn)
    assert blocked["granted"] is False
    assert blocked["reason"] == "daily_cap"
    conn.close()


def test_tenth_expedition_grants_bonus(axp_db):
    conn = db()
    uid, pid = _player(conn=conn)
    conn.commit()

    total_xp = 0
    for i in range(10):
        res = grant_fleet_activity_xp(uid, pid, SOURCE_EXPEDITION, 5000 + i, conn=conn)
        assert res["granted"] is True
        total_xp += int(res["amount"])
        bonus = res.get("expedition_bonus") or {}
        if bonus.get("granted"):
            total_xp += int(bonus.get("amount") or 0)
        if i == 9:
            assert bonus.get("granted") is True
            assert int(bonus.get("amount") or 0) == EXPEDITION_BONUS_AMOUNT

    assert total_xp == 5 * 10 + EXPEDITION_BONUS_AMOUNT
    conn.close()


def test_planet_tech_xp_unchanged(axp_db):
    from game.planet_evolution.bootstrap import ensure_planet_evolution
    from game.planet_evolution.definitions import reload_definitions

    reload_definitions()
    conn = db()
    uid, pid = _player(conn=conn)
    ensure_planet_evolution(pid, conn)
    conn.execute("UPDATE planets SET planet_xp = 0, planet_level = 1 WHERE id = ?;", (pid,))
    conn.execute("UPDATE planet_buildings SET research_lab = 1 WHERE planet_id = ?;", (pid,))
    conn.execute(
        """
        INSERT INTO planet_research_queue
            (planet_id, tech_key, target_level, finish_at, start_at)
        VALUES (?, 'industry_t1_automation', 1, 1, 0);
        """,
        (pid,),
    )
    conn.commit()

    finished = finish_planet_research_jobs(conn, pid, now=2.0)
    assert finished == 1

    row = conn.execute("SELECT planet_xp FROM planets WHERE id = ?;", (pid,)).fetchone()
    assert int(row["planet_xp"]) == 40  # 25 + tier1*15

    axp_rows = conn.execute(
        "SELECT COUNT(*) AS c FROM activity_xp_log WHERE planet_id = ?;",
        (pid,),
    ).fetchone()["c"]
    assert int(axp_rows) == 0
    conn.close()


def test_queue_job_grant_once_per_job(axp_db):
    conn = db()
    uid, pid = _player(conn=conn)
    conn.commit()

    first = grant_queue_job_activity_xp(uid, pid, SOURCE_BUILDING_FINISH, 77, conn=conn)
    second = grant_queue_job_activity_xp(uid, pid, SOURCE_BUILDING_FINISH, 77, conn=conn)
    assert first["granted"] is True
    assert second["granted"] is False

    rows = conn.execute(
        "SELECT COUNT(*) AS c FROM activity_xp_log WHERE source_key = ? AND player_id = ?;",
        (SOURCE_BUILDING_FINISH, uid),
    ).fetchone()["c"]
    assert int(rows) == 1
    conn.close()


def test_activity_xp_dashboard_summary(axp_db):
    conn = db()
    uid, pid = _player(conn=conn)
    conn.commit()

    grant_fleet_activity_xp(uid, pid, SOURCE_EXPEDITION, 1, conn=conn)
    grant_fleet_activity_xp(uid, pid, SOURCE_SPY, 2, conn=conn)

    dash = get_activity_xp_dashboard(uid, pid, conn=conn)
    assert dash["visible"] is True
    assert dash["today_earned"] == 7
    assert dash["expedition_count_today"] == 1
    assert dash["expedition_progress"] == 1
    conn.close()
