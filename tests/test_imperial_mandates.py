"""Imperial Mandates — late-game colony capacity (GC-M2+)."""
from __future__ import annotations

import time
import uuid

import pytest

from game.admin_balance import save_balance_settings
from game.db import db
from game.logic import check_planet_cap_available, get_max_planets_per_player, get_planet_limit_block
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, init_db
from game.planet_evolution.expansion_protocol import (
    INTERSTELLAR_EXPANSION_TECH,
    build_expansion_launch_checklist,
    effective_max_worlds_for_homeworld_level,
    expansion_gameplay_cap,
    expansion_slots_unlocked,
)
from game.planet_evolution.imperial_mandates import (
    ARK_SLOT_MAX,
    SURVEY_EXPEDITIONS_REQUIRED,
    ensure_legacy_slots,
    ensure_player_mandate_state,
    legacy_expansion_slots_unlocked,
)


@pytest.fixture
def mandates_db(tmp_path, monkeypatch):
    db_path = tmp_path / "imperial_mandates.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    import game.db as gdb
    import game.models as models

    gdb._DB_PATH = None
    models.DB_PATH = str(db_path)
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(conn=None):
    own = conn is None
    if own:
        conn = db()
    ok, err, user = create_user(f"mandate_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="MandateTester", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _set_hw(conn, uid: int, level: int) -> None:
    hw = get_homeworld(uid, conn=conn)
    assert hw
    conn.execute("UPDATE planets SET planet_level = ? WHERE id = ?;", (int(level), int(hw["id"])))
    conn.commit()


def test_ark_slots_cap_at_six_no_extrapolation():
    assert expansion_slots_unlocked(30) == 6
    assert expansion_slots_unlocked(35) == 6
    assert expansion_slots_unlocked(50) == 6
    assert effective_max_worlds_for_homeworld_level(30) == 7
    assert effective_max_worlds_for_homeworld_level(35) == 7
    assert legacy_expansion_slots_unlocked(35) == 7
    assert legacy_expansion_slots_unlocked(40) == 8


def test_admin_default_is_eleven(mandates_db):
    conn = db()
    try:
        assert get_max_planets_per_player(conn=conn) == 11
    finally:
        conn.close()


def test_soft_lock_ark30_requires_mandate(mandates_db):
    uid = _player()
    conn = db()
    try:
        _set_hw(conn, uid, 30)
        cap = expansion_gameplay_cap(uid, conn=conn)
        assert cap["expansion_slots_unlocked"] == ARK_SLOT_MAX
        assert cap["late_slots"] == 0
        assert cap["gameplay_cap"] == 7
        ok, reason = check_planet_cap_available(uid, conn=conn)
        # only HW owned → under cap
        assert ok, reason
        # simulate 6 colonies already: owned=7 via inserting planets is heavy;
        # raise owned by checking reason when at cap via block
        block = get_planet_limit_block(uid, conn=conn)
        assert block["max"] == 7
        checklist = build_expansion_launch_checklist(uid, conn=conn)
        # With only HW, under cap — mandate item may still show when expansion_count >= ark
        # Force at-cap by setting admin low? Better: grant nothing and invent 6 colony rows.
        for i in range(6):
            conn.execute(
                """
                INSERT INTO planets (player_id, name, galaxy, system, position, is_homeworld, planet_level, last_update)
                VALUES (?, ?, 1, ?, ?, 0, 1, ?);
                """,
                (uid, f"Col{i}", 10 + i, 1 + i, time.time()),
            )
        conn.commit()
        ok2, reason2 = check_planet_cap_available(uid, conn=conn)
        assert not ok2
        assert reason2 == "imperial_mandate_required"
        checklist2 = build_expansion_launch_checklist(uid, conn=conn)
        keys = [i["key"] for i in checklist2["items"]]
        assert "imperial_mandate" in keys
        mandate = next(i for i in checklist2["items"] if i["key"] == "imperial_mandate")
        assert mandate["required"] == SURVEY_EXPEDITIONS_REQUIRED
        assert checklist2["blocked_reason_key"] == "imperial_mandate_required"
        # Ark required stays at 30, not 35
        ark_item = next(i for i in checklist2["items"] if i["key"] == "genesis_ark_level")
        assert ark_item["required"] == 30
        assert ark_item["met"] is True
    finally:
        conn.close()


def test_legacy_snapshot_preserves_extrapolated_cap(mandates_db):
    uid = _player()
    conn = db()
    try:
        _set_hw(conn, uid, 40)  # old formula: 8 ark slots → legacy 2
        legacy = ensure_legacy_slots(uid, conn=conn)
        assert legacy == 2
        conn.commit()
        legacy2 = ensure_legacy_slots(uid, conn=conn)
        assert legacy2 == 2  # idempotent
        state = ensure_player_mandate_state(uid, conn=conn)
        assert state["late_slots"] == 2
        assert "survey" in state["earned_mandates"]
        assert "presence" in state["earned_mandates"]
        cap = expansion_gameplay_cap(uid, conn=conn)
        assert cap["gameplay_cap"] == 9  # 1+6+2
        assert cap["gameplay_cap"] >= 9
    finally:
        conn.close()


def test_survey_mandate_unlocks_eighth_world(mandates_db):
    uid = _player()
    conn = db()
    try:
        _set_hw(conn, uid, 30)
        for i in range(6):
            conn.execute(
                """
                INSERT INTO planets (player_id, name, galaxy, system, position, is_homeworld, planet_level, last_update)
                VALUES (?, ?, 1, ?, ?, 0, 30, ?);
                """,
                (uid, f"Col{i}", 20 + i, 1, time.time()),
            )
        # Seed expedition completions
        now = time.time()
        for mid in range(1, SURVEY_EXPEDITIONS_REQUIRED + 1):
            conn.execute(
                """
                INSERT INTO expedition_daily_recorded
                    (movement_id, player_id, day_bucket, expo_value, recorded_at)
                VALUES (?, ?, 20260807, 10, ?);
                """,
                (10_000 + mid, uid, now),
            )
        conn.commit()
        ok, reason = check_planet_cap_available(uid, conn=conn)
        assert ok, reason
        cap = expansion_gameplay_cap(uid, conn=conn)
        assert cap["late_slots"] >= 1
        assert cap["gameplay_cap"] >= 8
    finally:
        conn.close()


def test_colony_maturity_blocks_second_colony_until_pe_30(mandates_db):
    from game.planet_evolution.expansion_protocol import COLONY_MATURITY_REQUIRED_LEVEL

    uid = _player()
    conn = db()
    try:
        _set_hw(conn, uid, 10)
        conn.execute(
            """
            INSERT INTO planets (player_id, name, galaxy, system, position, is_homeworld, planet_level, last_update)
            VALUES (?, 'YoungColony', 1, 50, 3, 0, 29, ?);
            """,
            (uid, time.time()),
        )
        conn.commit()
        ok, reason = check_planet_cap_available(uid, conn=conn)
        assert not ok
        assert reason == "colony_maturity_required"
        block = get_planet_limit_block(uid, conn=conn)
        assert block["colony_maturity"]["ok"] is False
        assert block["colony_maturity"]["mature_count"] == 0
        assert block["colony_maturity"]["colony_count"] == 1
        checklist = build_expansion_launch_checklist(uid, conn=conn)
        mat = next(i for i in checklist["items"] if i["key"] == "colony_maturity")
        assert mat["met"] is False
        assert mat["required"] == 1
        assert mat["underleveled"]
        assert mat["detail_names"]
        assert checklist["blocked_reason_key"] == "colony_maturity_required"

        conn.execute(
            "UPDATE planets SET planet_level = ? WHERE player_id = ? AND is_homeworld = 0;",
            (COLONY_MATURITY_REQUIRED_LEVEL, uid),
        )
        conn.commit()
        ok2, reason2 = check_planet_cap_available(uid, conn=conn)
        assert ok2, reason2
    finally:
        conn.close()


def test_colony_maturity_skipped_when_only_homeworld(mandates_db):
    uid = _player()
    conn = db()
    try:
        _set_hw(conn, uid, 5)
        ok, reason = check_planet_cap_available(uid, conn=conn)
        assert ok, reason
        block = get_planet_limit_block(uid, conn=conn)
        assert block["colony_maturity"]["ok"] is True
        assert block["colony_maturity"]["colony_count"] == 0
    finally:
        conn.close()

def test_owned_worlds_never_deleted_when_over_new_formula(mandates_db):
    """Grandfather: high HW + many worlds stay; only new foundings gated."""
    uid = _player()
    conn = db()
    try:
        _set_hw(conn, uid, 40)
        for i in range(8):
            conn.execute(
                """
                INSERT INTO planets (player_id, name, galaxy, system, position, is_homeworld, planet_level, last_update)
                VALUES (?, ?, 1, ?, ?, 0, 1, ?);
                """,
                (uid, f"LegacyCol{i}", 30 + i, 2, time.time()),
            )
        conn.commit()
        planets = conn.execute(
            "SELECT COUNT(*) AS n FROM planets WHERE player_id = ?;", (uid,)
        ).fetchone()
        assert int(planets["n"]) == 9  # 1 HW + 8
        cap = expansion_gameplay_cap(uid, conn=conn)
        # legacy 2 → cap 9; at cap
        assert int(cap["gameplay_cap"]) == 9
        ok, reason = check_planet_cap_available(uid, conn=conn)
        assert not ok
        # worlds still there
        assert int(
            conn.execute(
                "SELECT COUNT(*) AS n FROM planets WHERE player_id = ?;", (uid,)
            ).fetchone()["n"]
        ) == 9
    finally:
        conn.close()
