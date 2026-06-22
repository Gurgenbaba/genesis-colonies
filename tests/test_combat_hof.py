"""Combat Hall of Fame tests (GC-700A)."""

from __future__ import annotations

import json
import time
import uuid

import pytest

from game import db as gdb
from game.db import db
from game.combat_hof import (
    COMBAT_HOF_RETENTION_LIMIT,
    HOF_SORT_DEBRIS,
    HOF_SORT_LOOT,
    HOF_SORT_RECENT,
    backfill_combat_hof,
    build_hof_api_payload,
    combat_qualifies_for_hof,
    get_player_hof_highlight,
    hof_schema_ready,
    list_hof_battles,
    list_top_battles,
    prune_hof_entries_beyond_top,
    record_hof_battle,
)
from game.combat import COMBAT_REPORT_VERSION
from game.fleet import add_planet_ships, process_fleet_tick, send_fleet
from game.fleet_defs import EXPEDITION_POSITION
from game.messages import create_message, list_messages, notify_combat, notify_expedition
from game.models import (
    add_planet_defense,
    create_user,
    ensure_player_and_homeworld,
    get_planets_by_player,
    init_db,
)


@pytest.fixture
def hof_db(tmp_path, monkeypatch):
    db_path = tmp_path / "hof_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
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
    ok, err, user = create_user(f"hof_user_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="Admiral", conn=conn)
    if own:
        conn.commit()
        conn.close()
    return uid


def _fund_planet(cur, planet_id: int, *, metal=50000, crystal=50000, fuel_cells=50000):
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
        (metal, crystal, fuel_cells, int(planet_id)),
    )


def _seed_ships(planet_id: int, player_id: int, ships: dict, *, conn):
    add_planet_ships(int(planet_id), int(player_id), dict(ships), conn=conn)


def _planet_coords(planet_id: int, *, conn) -> tuple[int, int, int]:
    cur = conn.cursor()
    cur.execute("SELECT galaxy, system, position FROM planets WHERE id = ?;", (int(planet_id),))
    row = cur.fetchone()
    return int(row["galaxy"]), int(row["system"]), int(row["position"])


def _foreign_planet_standalone():
    ok, err, user = create_user(f"foreign_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    from game.db import begin_write_transaction, commit

    begin_write_transaction(conn)
    ensure_player_and_homeworld(uid, player_name="Foreign", conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    coords = _planet_coords(pid, conn=conn)
    commit(conn)
    conn.close()
    return uid, pid, coords


def test_hof_schema_ready(hof_db):
    conn = db()
    try:
        assert hof_schema_ready(conn) is True
    finally:
        conn.close()


def test_combat_qualifies_for_hof():
    assert combat_qualifies_for_hof(0) is True
    assert combat_qualifies_for_hof(1) is True
    assert combat_qualifies_for_hof(999_999) is True


def test_record_hof_battle_idempotent_on_fleet_id(hof_db):
    conn = db()
    try:
        ok1 = record_hof_battle(
            fleet_id=42,
            attacker_player_id=1,
            defender_player_id=2,
            attacker_name="Alpha",
            defender_name="Beta",
            target_planet_id=9,
            target_name="Colony IX",
            target_coords="[2:2:8]",
            winner="attacker",
            rounds=3,
            attacker_losses={"ironclad_frigate": 2},
            defender_losses={"sentinel_turret": 5},
            loot={"metal": 1000, "crystal": 500},
            debris={"metal": 300, "crystal": 200},
            report_metadata={"report_version": 2, "target_coords": "[2:2:8]"},
            conn=conn,
        )
        ok2 = record_hof_battle(
            fleet_id=42,
            attacker_player_id=1,
            defender_player_id=2,
            attacker_name="Alpha",
            defender_name="Beta",
            target_planet_id=9,
            target_name="Colony IX",
            target_coords="[2:2:8]",
            winner="defender",
            rounds=6,
            attacker_losses={"ironclad_frigate": 99},
            defender_losses={"sentinel_turret": 99},
            loot={},
            debris={},
            report_metadata={},
            conn=conn,
        )
        conn.commit()
        assert ok1 is True
        assert ok2 is False

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM combat_hall_of_fame WHERE fleet_id = 42;")
        assert int(cur.fetchone()["c"]) == 1
        cur.execute(
            "SELECT winner, rounds FROM combat_hall_of_fame WHERE fleet_id = 42 LIMIT 1;"
        )
        row = cur.fetchone()
        assert row["winner"] == "attacker"
        assert int(row["rounds"]) == 3
    finally:
        conn.close()


def test_list_top_battles_sorted_by_destroyed_score(hof_db):
    conn = db()
    try:
        record_hof_battle(
            fleet_id=1,
            attacker_player_id=1,
            defender_player_id=2,
            attacker_name="A",
            defender_name="B",
            target_planet_id=1,
            target_name="P1",
            target_coords="[1:1:1]",
            winner="attacker",
            rounds=2,
            attacker_losses={"ironclad_frigate": 1},
            defender_losses={},
            loot={},
            debris={},
            report_metadata={},
            created_at=100,
            conn=conn,
        )
        record_hof_battle(
            fleet_id=2,
            attacker_player_id=3,
            defender_player_id=4,
            attacker_name="C",
            defender_name="D",
            target_planet_id=2,
            target_name="P2",
            target_coords="[1:1:2]",
            winner="defender",
            rounds=4,
            attacker_losses={"ironclad_frigate": 20},
            defender_losses={"sentinel_turret": 20},
            loot={},
            debris={},
            report_metadata={},
            created_at=200,
            conn=conn,
        )
        conn.commit()

        battles = list_top_battles(limit=100, conn=conn)
        assert len(battles) == 2
        assert battles[0]["fleet_id"] == 2
        assert battles[0]["rank"] == 1
        assert battles[1]["fleet_id"] == 1
        assert battles[1]["rank"] == 2
        assert battles[0]["total_destroyed_score"] >= battles[1]["total_destroyed_score"]
    finally:
        conn.close()


def test_attack_creates_single_hof_entry(hof_db):
    foreign_uid, foreign_pid, (g, s, p) = _foreign_planet_standalone()
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    cur = conn.cursor()
    _fund_planet(cur, pid)
    attack_sent = 12
    _seed_ships(pid, uid, {"ironclad_frigate": attack_sent}, conn=conn)
    add_planet_defense(foreign_pid, {"sentinel_turret": 8}, conn=conn)
    conn.commit()

    ok, _, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=p,
        mission_type="attack",
        ships={"ironclad_frigate": attack_sent},
        conn=conn,
    )
    assert ok
    fleet_id = result["fleet"]["id"]
    cur.execute("UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;", (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    cur.execute("SELECT COUNT(*) AS c FROM combat_hall_of_fame WHERE fleet_id = ?;", (fleet_id,))
    assert int(cur.fetchone()["c"]) == 1

    cur.execute(
        """
        SELECT total_destroyed_score, report_metadata_json, winner, rounds
        FROM combat_hall_of_fame WHERE fleet_id = ? LIMIT 1;
        """,
        (fleet_id,),
    )
    row = cur.fetchone()
    assert int(row["total_destroyed_score"]) > 0
    meta = json.loads(row["report_metadata_json"])
    assert int(meta.get("report_version") or 0) == 2
    assert meta.get("target_coords")
    assert row["winner"] in ("attacker", "defender", "draw")
    assert int(row["rounds"]) >= 1

    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()
    cur.execute("SELECT COUNT(*) AS c FROM combat_hall_of_fame WHERE fleet_id = ?;", (fleet_id,))
    assert int(cur.fetchone()["c"]) == 1

    msgs = list_messages(uid, category="combat")
    assert len(msgs["data"]["messages"]) >= 1
    conn.close()


def test_expedition_does_not_create_hof_entry(hof_db):
    conn = db()
    uid = _player(conn=conn)
    pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
    g, s, _ = _planet_coords(pid, conn=conn)
    cur = conn.cursor()
    _fund_planet(cur, pid)
    _seed_ships(pid, uid, {"solar_skiff": 2}, conn=conn)
    conn.commit()

    ok, _, result = send_fleet(
        player_id=uid,
        origin_planet_id=pid,
        target_galaxy=g,
        target_system=s,
        target_position=EXPEDITION_POSITION,
        mission_type="expedition",
        ships={"solar_skiff": 1},
        conn=conn,
    )
    assert ok
    fleet_id = result["fleet"]["id"]
    cur.execute("UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;", (time.time() - 1, fleet_id))
    conn.commit()
    process_fleet_tick(player_id=uid, conn=conn)
    conn.commit()

    cur.execute("SELECT COUNT(*) AS c FROM combat_hall_of_fame WHERE fleet_id = ?;", (fleet_id,))
    assert int(cur.fetchone()["c"]) == 0
    conn.close()


def test_record_hof_battle_persists_zero_score_candidate(hof_db):
    conn = db()
    try:
        ok = record_hof_battle(
            fleet_id=99,
            attacker_player_id=1,
            defender_player_id=2,
            attacker_name="A",
            defender_name="B",
            target_planet_id=1,
            target_name="P",
            target_coords="[1:1:1]",
            winner="draw",
            rounds=0,
            attacker_losses={},
            defender_losses={},
            loot={},
            debris={},
            report_metadata={"report_version": 2, "target_coords": "[1:1:1]"},
            conn=conn,
        )
        conn.commit()
        assert ok is True
        cur = conn.cursor()
        cur.execute(
            "SELECT total_destroyed_score FROM combat_hall_of_fame WHERE fleet_id = 99 LIMIT 1;"
        )
        assert int(cur.fetchone()["total_destroyed_score"]) == 0
    finally:
        conn.close()


def test_prune_hof_entries_beyond_top_keeps_best_250(hof_db):
    conn = db()
    try:
        for idx in range(1, 261):
            record_hof_battle(
                fleet_id=idx,
                attacker_player_id=1,
                defender_player_id=2,
                attacker_name="A",
                defender_name="B",
                target_planet_id=1,
                target_name="P",
                target_coords="[1:1:1]",
                winner="attacker",
                rounds=1,
                attacker_losses={},
                defender_losses={"sentinel_turret": idx},
                loot={},
                debris={},
                report_metadata={},
                created_at=idx,
                conn=conn,
            )
        conn.commit()

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM combat_hall_of_fame;")
        assert int(cur.fetchone()["c"]) == COMBAT_HOF_RETENTION_LIMIT

        cur.execute(
            """
            SELECT MIN(total_destroyed_score) AS min_score
            FROM combat_hall_of_fame;
            """
        )
        min_kept = int(cur.fetchone()["min_score"])
        assert min_kept >= 11

        cur.execute("SELECT COUNT(*) AS c FROM combat_hall_of_fame WHERE fleet_id <= 10;")
        assert int(cur.fetchone()["c"]) == 0

        top = list_top_battles(limit=100, conn=conn)
        assert len(top) == 100
        assert top[0]["fleet_id"] == 260
        assert top[0]["total_destroyed_score"] >= top[-1]["total_destroyed_score"]
    finally:
        conn.close()


def test_prune_hof_noop_when_under_retention_limit(hof_db):
    conn = db()
    try:
        record_hof_battle(
            fleet_id=1,
            attacker_player_id=1,
            defender_player_id=2,
            attacker_name="A",
            defender_name="B",
            target_planet_id=1,
            target_name="P",
            target_coords="[1:1:1]",
            winner="attacker",
            rounds=1,
            attacker_losses={},
            defender_losses={"sentinel_turret": 1},
            loot={},
            debris={},
            report_metadata={},
            conn=conn,
        )
        conn.commit()
        removed = prune_hof_entries_beyond_top(conn=conn)
        assert removed == 0
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM combat_hall_of_fame;")
        assert int(cur.fetchone()["c"]) == 1
    finally:
        conn.close()


def _combat_report_metadata(
    *,
    fleet_id: int,
    perspective: str = "attacker",
    attacker_id: int = 1,
    defender_id: int = 2,
    attacker_losses: dict | None = None,
    defender_losses: dict | None = None,
) -> dict:
    return {
        "report_version": COMBAT_REPORT_VERSION,
        "fleet_id": int(fleet_id),
        "perspective": perspective,
        "mission_type": "attack",
        "attacker_id": int(attacker_id),
        "defender_id": int(defender_id),
        "attacker_name": "Alpha",
        "defender_name": "Beta",
        "target_coords": "[1:2:3]",
        "target_planet_name": "Colony",
        "winner": "attacker",
        "result": "attacker",
        "attacker_losses": dict(attacker_losses or {"ironclad_frigate": 1}),
        "defender_losses": dict(defender_losses or {"sentinel_turret": 4}),
        "loot": {"metal": 500, "crystal": 200},
        "rounds": [],
        "rounds_fought": 2,
    }


def _seed_combat_inbox(
    *,
    attacker_id: int,
    defender_id: int,
    fleet_id: int,
    conn,
    include_defender_copy: bool = True,
):
    meta = _combat_report_metadata(
        fleet_id=fleet_id,
        perspective="attacker",
        attacker_id=attacker_id,
        defender_id=defender_id,
    )
    notify_combat(attacker_id, "Combat report", "Body attacker", metadata=meta, conn=conn)
    if include_defender_copy:
        def_meta = {**meta, "perspective": "defender"}
        notify_combat(defender_id, "Attack report", "Body defender", metadata=def_meta, conn=conn)


def test_backfill_combat_hof_creates_entries_from_old_reports(hof_db):
    atk = _player()
    defn = _player()
    conn = db()
    try:
        _seed_combat_inbox(attacker_id=atk, defender_id=defn, fleet_id=501, conn=conn)
        conn.commit()

        result = backfill_combat_hof(conn=conn)
        conn.commit()
        assert result["ok"] is True
        assert result["inserted"] == 1

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM combat_hall_of_fame WHERE fleet_id = 501;")
        assert int(cur.fetchone()["c"]) == 1
        cur.execute(
            """
            SELECT attacker_name, defender_name, total_destroyed_score, winner, rounds
            FROM combat_hall_of_fame WHERE fleet_id = 501 LIMIT 1;
            """
        )
        row = cur.fetchone()
        assert row["attacker_name"] == "Alpha"
        assert row["defender_name"] == "Beta"
        assert int(row["total_destroyed_score"]) > 0
        assert row["winner"] == "attacker"
        assert int(row["rounds"]) == 2
    finally:
        conn.close()


def test_backfill_combat_hof_deduplicates_attacker_defender_reports(hof_db):
    atk = _player()
    defn = _player()
    conn = db()
    try:
        _seed_combat_inbox(attacker_id=atk, defender_id=defn, fleet_id=502, conn=conn)
        conn.commit()

        result = backfill_combat_hof(conn=conn)
        conn.commit()
        assert result["inserted"] == 1

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM combat_hall_of_fame WHERE fleet_id = 502;")
        assert int(cur.fetchone()["c"]) == 1
    finally:
        conn.close()


def test_backfill_combat_hof_ignores_non_combat_messages(hof_db):
    pid = _player()
    conn = db()
    try:
        create_message(pid, "System note", "Hello", category="system", conn=conn)
        notify_expedition(
            pid,
            "Expedition",
            "Nothing found",
            metadata={"fleet_id": 503, "mission_type": "expedition"},
            conn=conn,
        )
        create_message(
            pid,
            "Transport",
            "Arrived",
            category="system",
            metadata={
                "fleet_id": 504,
                "mission_type": "transport",
                "report_phase": "arrival",
            },
            conn=conn,
        )
        conn.commit()

        result = backfill_combat_hof(conn=conn)
        conn.commit()
        assert result["ok"] is True
        assert result["inserted"] == 0

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS c FROM combat_hall_of_fame;")
        assert int(cur.fetchone()["c"]) == 0
    finally:
        conn.close()


def test_backfill_combat_hof_skips_existing_fleet_ids(hof_db):
    atk = _player()
    defn = _player()
    conn = db()
    try:
        record_hof_battle(
            fleet_id=505,
            attacker_player_id=atk,
            defender_player_id=defn,
            attacker_name="Existing",
            defender_name="Row",
            target_planet_id=None,
            target_name="P",
            target_coords="[1:1:1]",
            winner="attacker",
            rounds=1,
            attacker_losses={},
            defender_losses={"sentinel_turret": 1},
            loot={},
            debris={},
            report_metadata={},
            conn=conn,
        )
        _seed_combat_inbox(attacker_id=atk, defender_id=defn, fleet_id=505, conn=conn)
        conn.commit()

        result = backfill_combat_hof(conn=conn)
        conn.commit()
        assert result["inserted"] == 0
        assert result["skipped_existing"] == 1

        cur = conn.cursor()
        cur.execute("SELECT attacker_name FROM combat_hall_of_fame WHERE fleet_id = 505 LIMIT 1;")
        assert cur.fetchone()["attacker_name"] == "Existing"
    finally:
        conn.close()


def test_list_top_battles_respects_limit(hof_db):
    conn = db()
    try:
        for idx in range(1, 105):
            record_hof_battle(
                fleet_id=idx,
                attacker_player_id=1,
                defender_player_id=2,
                attacker_name="A",
                defender_name="B",
                target_planet_id=1,
                target_name="P",
                target_coords="[1:1:1]",
                winner="attacker",
                rounds=1,
                attacker_losses={},
                defender_losses={"sentinel_turret": idx},
                loot={},
                debris={},
                report_metadata={},
                created_at=idx,
                conn=conn,
            )
        conn.commit()
        battles = list_top_battles(limit=100, conn=conn)
        assert len(battles) == 100
    finally:
        conn.close()


def test_list_hof_battles_sort_categories(hof_db):
    conn = db()
    try:
        record_hof_battle(
            fleet_id=11,
            attacker_player_id=10,
            defender_player_id=20,
            attacker_name="LowLoot",
            defender_name="Def",
            target_planet_id=1,
            target_name="P",
            target_coords="[2:3:4]",
            winner="attacker",
            rounds=1,
            attacker_losses={"ironclad_frigate": 50},
            defender_losses={},
            loot={"metal": 1000, "crystal": 0, "fuel_cells": 0},
            debris={"metal": 5000, "crystal": 1000},
            report_metadata={},
            created_at=300,
            conn=conn,
        )
        record_hof_battle(
            fleet_id=12,
            attacker_player_id=11,
            defender_player_id=21,
            attacker_name="HighLoot",
            defender_name="Def2",
            target_planet_id=2,
            target_name="P2",
            target_coords="[5:6:7]",
            winner="attacker",
            rounds=1,
            attacker_losses={"ironclad_frigate": 1},
            defender_losses={},
            loot={"metal": 900000, "crystal": 100000, "fuel_cells": 0},
            debris={"metal": 100, "crystal": 100},
            report_metadata={},
            created_at=100,
            conn=conn,
        )
        record_hof_battle(
            fleet_id=13,
            attacker_player_id=12,
            defender_player_id=22,
            attacker_name="Recent",
            defender_name="Def3",
            target_planet_id=3,
            target_name="P3",
            target_coords="[8:9:10]",
            winner="draw",
            rounds=1,
            attacker_losses={},
            defender_losses={},
            loot={},
            debris={},
            report_metadata={},
            created_at=900,
            conn=conn,
        )
        conn.commit()

        debris_top = list_hof_battles(sort=HOF_SORT_DEBRIS, limit=10, conn=conn)
        assert debris_top[0]["fleet_id"] == 11
        assert debris_top[0]["debris_total"] > debris_top[1]["debris_total"]

        loot_top = list_hof_battles(sort=HOF_SORT_LOOT, limit=10, conn=conn)
        assert loot_top[0]["fleet_id"] == 12
        assert loot_top[0]["loot_total"] > loot_top[1]["loot_total"]

        recent = list_hof_battles(sort=HOF_SORT_RECENT, limit=10, conn=conn)
        assert recent[0]["fleet_id"] == 13
    finally:
        conn.close()


def test_get_player_hof_highlight_rank(hof_db):
    conn = db()
    try:
        for idx, score in enumerate((5, 20, 40), start=1):
            record_hof_battle(
                fleet_id=100 + idx,
                attacker_player_id=900 if idx == 2 else idx,
                defender_player_id=800 + idx,
                attacker_name=f"Atk{idx}",
                defender_name=f"Def{idx}",
                target_planet_id=idx,
                target_name="P",
                target_coords=f"[1:1:{idx}]",
                winner="attacker",
                rounds=1,
                attacker_losses={"ironclad_frigate": score},
                defender_losses={},
                loot={},
                debris={},
                report_metadata={},
                created_at=idx,
                conn=conn,
            )
        conn.commit()

        highlight = get_player_hof_highlight(player_id=900, conn=conn)
        assert highlight is not None
        assert highlight["battle"]["fleet_id"] == 102
        assert highlight["rank"] == 2

        payload = build_hof_api_payload(sort=HOF_SORT_LOOT, player_id=900, conn=conn)
        assert payload["sort"] == HOF_SORT_LOOT
        assert payload["player_highlight"]["rank"] == 2
    finally:
        conn.close()
