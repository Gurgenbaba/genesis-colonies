"""Noob protection / fair-attack factor for fleet attacks."""

from __future__ import annotations

import time
import uuid

import pytest

import game.db as gdb
from game.db import db
from game.fleet import (
    add_planet_ships,
    build_fleet_send_preview,
    check_noob_protection,
    get_noob_protection_status,
    send_fleet,
    validate_fleet_send,
    NOOB_PROTECTION_FACTOR,
)
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.ranking import RANKING_INACTIVE_AFTER_SEC, is_player_id_inactive


@pytest.fixture
def noob_db(tmp_path, monkeypatch):
    db_path = tmp_path / "noob_protection.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player():
    ok, err, user = create_user(f"noob_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid)
    return uid


def _foreign_player():
    ok, err, user = create_user(f"foreign_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    from game.db import begin_write_transaction, commit

    begin_write_transaction(conn)
    ensure_player_and_homeworld(uid, conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    row = conn.execute(
        "SELECT galaxy, system, position FROM planets WHERE id = ?;",
        (pid,),
    ).fetchone()
    coords = (int(row["galaxy"]), int(row["system"]), int(row["position"]))
    commit(conn)
    conn.close()
    return uid, pid, coords


def _set_score(player_id: int, score_total: int, *, conn) -> None:
    conn.execute(
        """
        INSERT INTO player_scores (player_id, score_total, score_buildings, score_research, updated_at)
        VALUES (?, ?, ?, ?, strftime('%s','now'))
        ON CONFLICT(player_id) DO UPDATE SET
            score_total = excluded.score_total,
            score_buildings = excluded.score_buildings,
            score_research = excluded.score_research,
            updated_at = excluded.updated_at;
        """,
        (int(player_id), str(int(score_total)), str(int(score_total)), '0'),
    )


def _set_last_seen(player_id: int, last_seen: int, *, conn) -> None:
    conn.execute(
        "UPDATE players SET last_seen = ? WHERE id = ?;",
        (int(last_seen), int(player_id)),
    )


def _set_active(player_id: int, *, conn) -> None:
    _set_last_seen(player_id, int(time.time()), conn=conn)


def _set_inactive(player_id: int, *, conn) -> None:
    _set_last_seen(player_id, int(time.time()) - RANKING_INACTIVE_AFTER_SEC - 3600, conn=conn)


def _fund_and_seed(attacker_id: int, *, conn) -> tuple[int, tuple[int, int, int]]:
    att_pid = int(get_planets_by_player(attacker_id, conn=conn)[0]["id"])
    cur = conn.cursor()
    cur.execute(
        "UPDATE planets SET metal = 500000, crystal = 500000, fuel_cells = 500000 WHERE id = ?;",
        (att_pid,),
    )
    cur.execute("UPDATE planet_buildings SET orbital_shipyard = 1 WHERE planet_id = ?;", (att_pid,))
    add_planet_ships(att_pid, attacker_id, {"falcon_interceptor": 10}, conn=conn)
    row = conn.execute("SELECT galaxy, system, position FROM planets WHERE id = ?;", (att_pid,)).fetchone()
    origin_coords = (int(row["galaxy"]), int(row["system"]), int(row["position"]))
    return att_pid, origin_coords


def test_noob_protection_allows_similar_scores(noob_db):
    atk = _player()
    def_id, _, _ = _foreign_player()
    conn = db()
    _set_active(atk, conn=conn)
    _set_active(def_id, conn=conn)
    _set_score(atk, 1000, conn=conn)
    _set_score(def_id, 3000, conn=conn)
    conn.commit()
    ok, info = check_noob_protection(atk, def_id, conn=conn)
    assert ok is True
    assert info["factor"] == NOOB_PROTECTION_FACTOR
    assert info["attacker_score"] == 1000
    assert info["defender_score"] == 3000
    assert info["defender_inactive"] is False
    conn.close()


def test_noob_protection_blocks_strong_vs_weak(noob_db):
    atk = _player()
    def_id, _, _ = _foreign_player()
    conn = db()
    _set_active(atk, conn=conn)
    _set_active(def_id, conn=conn)
    _set_score(atk, 10000, conn=conn)
    _set_score(def_id, 1000, conn=conn)
    conn.commit()
    ok, info = check_noob_protection(atk, def_id, conn=conn)
    assert ok is False
    assert info["attacker_score"] == 10000
    assert info["defender_score"] == 1000
    assert info["min_defender_score"] == 2000
    assert info["defender_inactive"] is False
    conn.close()


def test_noob_protection_blocks_weak_vs_strong(noob_db):
    atk = _player()
    def_id, _, _ = _foreign_player()
    conn = db()
    _set_active(atk, conn=conn)
    _set_active(def_id, conn=conn)
    _set_score(atk, 1000, conn=conn)
    _set_score(def_id, 10000, conn=conn)
    conn.commit()
    ok, info = check_noob_protection(atk, def_id, conn=conn)
    assert ok is False
    assert info["max_defender_score"] == 5000
    assert info["defender_inactive"] is False
    conn.close()


def test_noob_protection_status_at_factor_boundary(noob_db):
    atk = _player()
    def_id, _, _ = _foreign_player()
    conn = db()
    _set_active(atk, conn=conn)
    _set_active(def_id, conn=conn)
    _set_score(atk, 1000, conn=conn)
    _set_score(def_id, 5000, conn=conn)
    conn.commit()
    info = get_noob_protection_status(atk, def_id, conn=conn, factor=5)
    assert info["allowed"] is True
    _set_score(def_id, 5001, conn=conn)
    conn.commit()
    info = get_noob_protection_status(atk, def_id, conn=conn, factor=5)
    assert info["allowed"] is False
    conn.close()


def test_noob_protection_allows_attack_on_inactive_weak_defender(noob_db):
    atk = _player()
    def_id, _, _ = _foreign_player()
    conn = db()
    _set_active(atk, conn=conn)
    _set_inactive(def_id, conn=conn)
    _set_score(atk, 10000, conn=conn)
    _set_score(def_id, 1000, conn=conn)
    conn.commit()
    assert is_player_id_inactive(def_id, conn=conn) is True
    ok, info = check_noob_protection(atk, def_id, conn=conn)
    assert ok is True
    assert info["defender_inactive"] is True
    conn.close()


def test_noob_protection_allows_attack_on_inactive_strong_defender(noob_db):
    atk = _player()
    def_id, _, _ = _foreign_player()
    conn = db()
    _set_active(atk, conn=conn)
    _set_inactive(def_id, conn=conn)
    _set_score(atk, 1000, conn=conn)
    _set_score(def_id, 10000, conn=conn)
    conn.commit()
    ok, info = check_noob_protection(atk, def_id, conn=conn)
    assert ok is True
    assert info["defender_inactive"] is True
    conn.close()


def test_send_fleet_blocks_noob_protection(noob_db):
    attacker_id = _player()
    defender_id, def_pid, (dg, ds, dp) = _foreign_player()
    conn = db()
    att_pid, _ = _fund_and_seed(attacker_id, conn=conn)
    _set_active(attacker_id, conn=conn)
    _set_active(defender_id, conn=conn)
    _set_score(attacker_id, 50000, conn=conn)
    _set_score(defender_id, 2000, conn=conn)
    conn.commit()

    ok, reason, extra = send_fleet(
        player_id=attacker_id,
        origin_planet_id=att_pid,
        target_galaxy=dg,
        target_system=ds,
        target_position=dp,
        mission_type="attack",
        ships={"falcon_interceptor": 1},
        conn=conn,
    )
    assert ok is False
    assert reason == "noob_protection_blocked"
    assert extra and extra["noob_protection"]["attacker_score"] == 50000
    assert extra["noob_protection"]["defender_score"] == 2000
    conn.close()


def test_send_fleet_allows_attack_on_inactive_defender(noob_db):
    attacker_id = _player()
    defender_id, def_pid, (dg, ds, dp) = _foreign_player()
    conn = db()
    att_pid, _ = _fund_and_seed(attacker_id, conn=conn)
    _set_active(attacker_id, conn=conn)
    _set_inactive(defender_id, conn=conn)
    _set_score(attacker_id, 50000, conn=conn)
    _set_score(defender_id, 2000, conn=conn)
    conn.commit()

    ok, reason, extra = send_fleet(
        player_id=attacker_id,
        origin_planet_id=att_pid,
        target_galaxy=dg,
        target_system=ds,
        target_position=dp,
        mission_type="attack",
        ships={"falcon_interceptor": 1},
        conn=conn,
    )
    assert ok is True, reason
    assert reason != "noob_protection_blocked"
    conn.close()


def test_preview_blocks_noob_protection(noob_db):
    attacker_id = _player()
    defender_id, def_pid, (dg, ds, dp) = _foreign_player()
    conn = db()
    att_pid, _ = _fund_and_seed(attacker_id, conn=conn)
    _set_active(attacker_id, conn=conn)
    _set_active(defender_id, conn=conn)
    _set_score(attacker_id, 50000, conn=conn)
    _set_score(defender_id, 2000, conn=conn)
    conn.commit()
    origin = dict(conn.execute("SELECT * FROM planets WHERE id = ?;", (att_pid,)).fetchone())
    preview = build_fleet_send_preview(
        player_id=attacker_id,
        origin_planet=origin,
        target_galaxy=dg,
        target_system=ds,
        target_position=dp,
        mission_type="attack",
        ships={"falcon_interceptor": 1},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    assert preview["can_send"] is False
    assert preview["block_reason"] == "noob_protection_blocked"
    assert preview["noob_protection"]["factor"] == NOOB_PROTECTION_FACTOR
    conn.close()


def test_preview_allows_attack_on_inactive_defender(noob_db):
    attacker_id = _player()
    defender_id, def_pid, (dg, ds, dp) = _foreign_player()
    conn = db()
    att_pid, _ = _fund_and_seed(attacker_id, conn=conn)
    _set_active(attacker_id, conn=conn)
    _set_inactive(defender_id, conn=conn)
    _set_score(attacker_id, 50000, conn=conn)
    _set_score(defender_id, 2000, conn=conn)
    conn.commit()
    origin = dict(conn.execute("SELECT * FROM planets WHERE id = ?;", (att_pid,)).fetchone())
    preview = build_fleet_send_preview(
        player_id=attacker_id,
        origin_planet=origin,
        target_galaxy=dg,
        target_system=ds,
        target_position=dp,
        mission_type="attack",
        ships={"falcon_interceptor": 1},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    assert preview["can_send"] is True
    assert preview["block_reason"] != "noob_protection_blocked"
    assert preview["noob_protection"]["defender_inactive"] is True
    conn.close()


def test_spy_not_blocked_by_noob_protection(noob_db):
    attacker_id = _player()
    defender_id, def_pid, (dg, ds, dp) = _foreign_player()
    conn = db()
    att_pid, _ = _fund_and_seed(attacker_id, conn=conn)
    add_planet_ships(att_pid, attacker_id, {"veil_probe": 5}, conn=conn)
    _set_active(attacker_id, conn=conn)
    _set_active(defender_id, conn=conn)
    _set_score(attacker_id, 50000, conn=conn)
    _set_score(defender_id, 2000, conn=conn)
    conn.commit()
    ok, reason, _extra = validate_fleet_send(
        player_id=attacker_id,
        origin_planet_id=att_pid,
        target_galaxy=dg,
        target_system=ds,
        target_position=dp,
        mission_type="spy",
        ships={"veil_probe": 1},
        resources={},
        speed_percent=100,
        conn=conn,
    )
    assert ok is True
    assert reason == ""
    conn.close()


def test_noob_protection_arbitrary_precision_score_math(noob_db):
    atk = _player()
    def_id, _, _ = _foreign_player()
    conn = db()
    _set_active(atk, conn=conn)
    _set_active(def_id, conn=conn)
    huge = 10**500 + 3
    _set_score(atk, huge, conn=conn)
    _set_score(def_id, (huge + NOOB_PROTECTION_FACTOR - 1) // NOOB_PROTECTION_FACTOR, conn=conn)
    conn.commit()
    info = get_noob_protection_status(atk, def_id, conn=conn)
    assert info["attacker_score"] == huge
    assert info["min_defender_score"] == (huge + NOOB_PROTECTION_FACTOR - 1) // NOOB_PROTECTION_FACTOR
    assert info["max_defender_score"] == huge * NOOB_PROTECTION_FACTOR
    assert info["allowed"] is True
    conn.close()
