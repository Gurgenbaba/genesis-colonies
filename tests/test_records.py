"""Universe records tests (GC-701)."""

from __future__ import annotations

import uuid

import pytest

from game import db as gdb
from game.db import db
from game.models import (
    create_user,
    ensure_player_and_homeworld,
    get_planets_by_player,
    init_db,
    save_planet_buildings,
    save_research_level,
)
from game.research import RESEARCH_TECHS
from game.records import (
    RECORD_BUILDING_KEYS,
    RECORD_DEFENSE_KEYS,
    RECORD_FLEET_KEYS,
    RECORD_TITAN_KEYS,
    RECORD_TROOP_KEYS,
    build_records_payload,
    _top_building_record,
)


@pytest.fixture
def records_db(tmp_path, monkeypatch):
    db_path = tmp_path / "records_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(name_prefix: str = "rec") -> tuple[int, int]:
    ok, err, user = create_user(f"{name_prefix}_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name=f"Cmd_{name_prefix}")
    conn = db()
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    conn.close()
    return uid, pid


def _record_by_key(payload: dict, group_key: str, record_key: str) -> dict:
    for group in payload["groups"]:
        if group["key"] == group_key:
            for rec in group["records"]:
                if rec["key"] == record_key:
                    return rec
    raise KeyError(f"{group_key}/{record_key}")


def test_build_records_payload_structure(records_db):
    conn = db()
    try:
        payload = build_records_payload(conn=conn)
        assert payload["ok"] is True
        assert payload["group_count"] == 7
        keys = [g["key"] for g in payload["groups"]]
        assert keys == [
            "buildings",
            "research",
            "empire",
            "fleet",
            "defense",
            "troops",
            "titans",
        ]
        building_group = payload["groups"][0]
        assert len(building_group["records"]) == len(RECORD_BUILDING_KEYS)
        research_group = payload["groups"][1]
        assert len(research_group["records"]) == len(RESEARCH_TECHS)
        fleet_group = next(g for g in payload["groups"] if g["key"] == "fleet")
        assert len(fleet_group["records"]) == len(RECORD_FLEET_KEYS)
        defense_group = next(g for g in payload["groups"] if g["key"] == "defense")
        assert len(defense_group["records"]) == len(RECORD_DEFENSE_KEYS)
        troop_group = next(g for g in payload["groups"] if g["key"] == "troops")
        assert len(troop_group["records"]) == len(RECORD_TROOP_KEYS)
        titan_group = next(g for g in payload["groups"] if g["key"] == "titans")
        assert len(titan_group["records"]) == len(RECORD_TITAN_KEYS) + 1
    finally:
        conn.close()


def test_top_building_record_picks_highest_level(records_db):
    uid_a, pid_a = _player("alpha")
    uid_b, pid_b = _player("beta")
    conn = db()
    try:
        save_planet_buildings(pid_a, {"metal_mine": 3})
        save_planet_buildings(pid_b, {"metal_mine": 7})
        conn.commit()

        rec = _top_building_record(conn, "metal_mine")
        assert rec["has_holder"] is True
        assert rec["value"] == 7
        assert rec["icon"] == "img/buildings/metal_mine.png"
        assert rec["player_id"] == uid_b
        assert rec["planet_id"] == pid_b
        assert rec["coords"].startswith("[")
    finally:
        conn.close()


def test_building_record_tie_breaks_by_lowest_planet_id(records_db):
    uid_a, pid_a = _player("tie_a")
    uid_b, pid_b = _player("tie_b")
    conn = db()
    try:
        save_planet_buildings(pid_a, {"crystal_mine": 5})
        save_planet_buildings(pid_b, {"crystal_mine": 5})
        conn.commit()

        rec = _top_building_record(conn, "crystal_mine")
        assert rec["value"] == 5
        assert rec["planet_id"] == min(pid_a, pid_b)
    finally:
        conn.close()


def test_research_record_highest_level(records_db):
    uid_a, _ = _player("res_a")
    uid_b, _ = _player("res_b")
    conn = db()
    try:
        save_research_level("weapon_tech", 2, uid_a)
        save_research_level("weapon_tech", 5, uid_b)
        conn.commit()

        payload = build_records_payload(conn=conn)
        rec = _record_by_key(payload, "research", "weapon_tech")
        assert rec["has_holder"] is True
        assert rec["value"] == 5
        assert rec["player_id"] == uid_b
        assert rec["planet_name"] == ""
    finally:
        conn.close()


def test_empire_planet_level_record(records_db):
    uid, pid = _player("lvl")
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE planets SET planet_level = 12 WHERE id = ?;", (pid,))
        conn.commit()

        payload = build_records_payload(conn=conn)
        rec = _record_by_key(payload, "empire", "planet_level")
        assert rec["has_holder"] is True
        assert rec["value"] == 12
        assert rec["player_id"] == uid
        assert rec["planet_id"] == pid
    finally:
        conn.close()


def test_empire_colonies_record(records_db):
    uid, pid = _player("col")
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO planets (player_id, name, galaxy, system, position, metal, crystal, last_update)
            VALUES (?, 'Colony II', 1, 1, 8, 1000, 1000, 0);
            """,
            (uid,),
        )
        cur.execute(
            """
            INSERT INTO planets (player_id, name, galaxy, system, position, metal, crystal, last_update)
            VALUES (?, 'Colony III', 1, 1, 9, 1000, 1000, 0);
            """,
            (uid,),
        )
        conn.commit()

        _player("lonely")

        payload = build_records_payload(conn=conn)
        rec = _record_by_key(payload, "empire", "colonies")
        assert rec["has_holder"] is True
        assert rec["value"] == 3
        assert rec["player_id"] == uid
    finally:
        conn.close()


def test_fleet_defense_titan_records(records_db):
    """GC-Rec-01: ship / defense counts and titan ownership records."""
    import time

    from game.models import set_planet_defense

    uid_a, pid_a = _player("fleet_a")
    uid_b, pid_b = _player("fleet_b")
    conn = db()
    try:
        now = time.time()
        conn.execute(
            """
            INSERT INTO planet_ships (player_id, planet_id, ship_key, amount, created_at, updated_at)
            VALUES (?, ?, 'falcon_interceptor', 40, ?, ?),
                   (?, ?, 'falcon_interceptor', 120, ?, ?)
            """,
            (uid_a, pid_a, now, now, uid_b, pid_b, now, now),
        )
        set_planet_defense(pid_a, {"plasma_arc": 10}, conn=conn)
        set_planet_defense(pid_b, {"plasma_arc": 55}, conn=conn)
        if conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='player_boss_companions'"
        ).fetchone():
            conn.execute(
                """
                INSERT INTO player_boss_companions (player_id, boss_key, tamed_at, tamed_event_id)
                VALUES (?, 'void_titan', ?, NULL),
                       (?, 'ancient_leviathan', ?, NULL),
                       (?, 'void_titan', ?, NULL)
                """,
                (uid_b, now, uid_b, now + 1, uid_a, now + 2),
            )
        conn.commit()

        payload = build_records_payload(conn=conn)
        fleet = _record_by_key(payload, "fleet", "falcon_interceptor")
        assert fleet["has_holder"] is True
        assert fleet["value"] == 120
        assert fleet["player_id"] == uid_b
        assert fleet["icon"] == "img/ships/falcon_interceptor.png"

        defense = _record_by_key(payload, "defense", "plasma_arc")
        assert defense["has_holder"] is True
        assert defense["value"] == 55
        assert defense["player_id"] == uid_b
        assert defense["icon"] == "img/defense/plasma_arc.png"

        total = _record_by_key(payload, "titans", "total_titans")
        assert total["has_holder"] is True
        assert total["value"] == 2
        assert total["player_id"] == uid_b

        void_rec = _record_by_key(payload, "titans", "void_titan")
        assert void_rec["has_holder"] is True
        # earliest tamed_at wins
        assert void_rec["player_id"] == uid_b
    finally:
        conn.close()


def test_zero_building_level_has_no_holder(records_db):
    conn = db()
    try:
        rec = _top_building_record(conn, "orbital_shipyard")
        assert rec["has_holder"] is False
        assert rec["value_fmt"] == "—"
    finally:
        conn.close()


def test_api_records_requires_login(records_db):
    import importlib

    import app as app_mod

    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    client = app_mod.app.test_client()
    resp = client.get("/api/records")
    assert resp.status_code in (401, 302)


def test_records_page_renders(records_db):
    import importlib

    import app as app_mod

    uid, _ = _player("page")
    app_mod.app.config["TESTING"] = True
    app_mod.app.config["WTF_CSRF_ENABLED"] = False
    client = app_mod.app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = uid
    resp = client.get("/records")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "records-page" in html
    assert "gc-records-workspace" in html
    assert 'data-records-tabs' in html
    assert 'data-records-tab="buildings"' in html
    assert 'data-records-tab="research"' in html
    assert 'data-records-tab="troops"' in html
    assert 'data-records-panel="buildings"' in html
    assert 'data-records-panel="troops"' in html
    assert "gc-records-tab" in html
    assert "Gebäude-Rekorde" in html or "Building records" in html


def test_main_js_records_tab_keys_include_troops():
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "static" / "main.js"
    text = src.read_text(encoding="utf-8")
    assert 'RECORDS_TAB_KEYS = ["buildings", "research", "empire", "fleet", "defense", "troops", "titans"]' in text
