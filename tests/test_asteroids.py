"""GC-AST — Galaxy asteroid belt tests."""

from __future__ import annotations

import json
import random
import time
import uuid

import pytest

from game import db as gdb
from game.asteroids import (
    ASTEROID_CATALOG,
    ASTEROID_RESOURCE_RANGE,
    INTER_WAVE_COOLDOWN_SEC,
    SPAWN_RUNTIME_KEY,
    TTL_SECONDS,
    _roll_loot,
    asteroid_schema_ready,
    build_asteroid_board_entries,
    build_schedule_info,
    expire_due_asteroids,
    get_active_asteroid_at,
    get_asteroids_for_system,
    insert_asteroid,
    list_active_asteroids,
    spawn_asteroid_belt,
    tick_asteroid_schedule,
    try_claim_harvest,
)
from game.db import begin_write_transaction, commit, db
from game.fleet import (
    add_planet_ships,
    evaluate_fleet_mission_target,
    process_fleet_tick,
    resolve_fleet_target,
    send_fleet,
)
from game.galaxy import list_system
from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player, init_db
from game.runtime_state import set_runtime_value


@pytest.fixture
def ast_db(tmp_path, monkeypatch):
    db_path = tmp_path / "asteroid_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("GC_SKIP_MIGRATION_CHECK", "1")
    gdb._DB_PATH = None
    init_db()
    import migrate

    migrate.main()
    yield
    gdb._DB_PATH = None


def _player(name="Admiral"):
    ok, err, user = create_user(f"ast_{uuid.uuid4().hex[:10]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name=name, conn=conn)
        commit(conn)
    finally:
        conn.close()
    return uid


def _home(uid):
    conn = db()
    try:
        row = get_planets_by_player(uid, conn=conn)[0]
        return int(row["id"]), int(row["galaxy"]), int(row["system"]), int(row["position"])
    finally:
        conn.close()


def _fund(planet_id: int):
    conn = db()
    try:
        begin_write_transaction(conn)
        conn.execute(
            "UPDATE planets SET metal = 500000, crystal = 500000, fuel_cells = 500000 WHERE id = ?;",
            (int(planet_id),),
        )
        commit(conn)
    finally:
        conn.close()


def test_asteroid_loot_rolls_each_resource_in_band():
    lo, hi = ASTEROID_RESOURCE_RANGE
    assert lo == 500_000
    assert hi == 5_000_000
    for key in ASTEROID_CATALOG:
        for seed in range(40):
            loot = _roll_loot(key, rng=random.Random(seed))
            for res in ("metal", "crystal", "fuel_cells"):
                assert lo <= int(loot[res]) <= hi, (key, seed, res, loot)


def _free_slot_near(galaxy: int, system: int) -> int:
    conn = db()
    try:
        occupied = {
            int(r["position"])
            for r in conn.execute(
                """
                SELECT position FROM planets
                WHERE galaxy = ? AND system = ? AND position BETWEEN 1 AND 15;
                """,
                (int(galaxy), int(system)),
            ).fetchall()
        }
        for pos in range(1, 16):
            if pos not in occupied:
                return pos
        raise AssertionError("no free slot")
    finally:
        conn.close()


def _fill_system(uid: int, galaxy: int, system: int, positions: list[int]) -> None:
    conn = db()
    try:
        begin_write_transaction(conn)
        now = time.time()
        for pos in positions:
            conn.execute(
                """
                INSERT INTO planets (
                    player_id, name, is_homeworld, metal, crystal, fuel_cells, last_update,
                    galaxy, system, position
                ) VALUES (?, ?, 0, 1000, 1000, 1000, ?, ?, ?, ?);
                """,
                (uid, f"Col{pos}", now, int(galaxy), int(system), int(pos)),
            )
        commit(conn)
    finally:
        conn.close()


def test_schema_ready_after_migration(ast_db):
    conn = db()
    try:
        assert asteroid_schema_ready(conn)
    finally:
        conn.close()


def test_spawn_prefers_dense_systems(ast_db):
    """Belt spawn lands in the densest classic system when slots are free."""
    uid = _player("Dense")
    _home_id, g, s, home_pos = _home(uid)
    extra = [p for p in range(1, 16) if p != home_pos][:6]
    _fill_system(uid, g, s, extra)

    conn = db()
    try:
        begin_write_transaction(conn)
        result = spawn_asteroid_belt(
            conn=conn,
            force=True,
            rng=random.Random(42),
            systems_limit=1,
            belt_size=(2, 2),
        )
        commit(conn)
        assert result["ok"], result
        spawned = result["spawned"]
        assert len(spawned) == 2
        assert all(int(a["galaxy"]) == g and int(a["system"]) == s for a in spawned)
        for a in spawned:
            assert a["total"] > 0
            assert a["status"] == "active"
    finally:
        conn.close()


def test_ensure_asteroids_present_bootstraps_empty_universe(ast_db):
    from game.asteroids import ensure_asteroids_present, list_active_asteroids

    uid = _player("Bootstrap")
    _home_id, g, s, home_pos = _home(uid)
    # Leave free slots in home system.
    conn = db()
    try:
        begin_write_transaction(conn)
        assert list_active_asteroids(conn=conn) == []
        result = ensure_asteroids_present(conn=conn)
        commit(conn)
        assert result["ok"], result
        assert result.get("skipped") is False
        assert len(result.get("spawned") or []) >= 1
        active = list_active_asteroids(conn=conn)
        assert len(active) >= 1
        # Second call is a no-op.
        again = ensure_asteroids_present(conn=conn)
        assert again.get("skipped") is True
        assert again.get("spawned") == []
    finally:
        conn.close()


def test_spawn_skips_full_dense_system_for_next(ast_db):
    """If densest system is full, spawn falls through to the next candidate."""
    uid = _player("FullDense")
    _home_id, g, s, home_pos = _home(uid)
    # Fill home system completely.
    extra = [p for p in range(1, 16) if p != home_pos]
    _fill_system(uid, g, s, extra)
    # Second system with one planet + free slots.
    other_system = int(s) + 1 if int(s) < 400 else int(s) - 1
    conn = db()
    try:
        begin_write_transaction(conn)
        now = time.time()
        conn.execute(
            """
            INSERT INTO planets (
                player_id, name, is_homeworld, metal, crystal, fuel_cells, last_update,
                galaxy, system, position
            ) VALUES (?, ?, 0, 1000, 1000, 1000, ?, ?, ?, ?);
            """,
            (uid, "Sparse", now, int(g), other_system, 3),
        )
        result = spawn_asteroid_belt(
            conn=conn,
            force=True,
            rng=random.Random(7),
            systems_limit=2,
            belt_size=(1, 1),
        )
        commit(conn)
        assert result["ok"], result
        spawned = result["spawned"]
        assert len(spawned) >= 1
        # Must not land in the completely full densest system.
        assert all(not (int(a["galaxy"]) == g and int(a["system"]) == s) for a in spawned)
        assert any(int(a["system"]) == other_system for a in spawned)
    finally:
        conn.close()


def test_ttl_expire_not_harvestable(ast_db):
    uid = _player("TTL")
    _home_id, g, s, _p = _home(uid)
    pos = _free_slot_near(g, s)
    now = time.time()
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="mixed_belt",
            now=now - TTL_SECONDS - 10,
            ttl_seconds=TTL_SECONDS,
            rng=random.Random(7),
        )
        assert ins["ok"]
        expired = expire_due_asteroids(conn=conn, now=now)
        commit(conn)
        assert ins["asteroid"]["id"] in expired
        assert get_active_asteroid_at(g, s, pos, conn=conn, now=now) is None
        claim = try_claim_harvest(
            g, s, pos, player_id=uid, cargo_capacity=20000, conn=conn, now=now
        )
        # Recently expired fields report `expired` (not silent `none`) for hunt clarity.
        assert claim["status"] == "expired"
    finally:
        conn.close()


def test_first_arrival_wins_second_misses(ast_db):
    uid_a = _player("Alpha")
    uid_b = _player("Beta")
    home_a, g, s, _ = _home(uid_a)
    pos = _free_slot_near(g, s)
    _fund(home_a)
    home_b, _, _, _ = _home(uid_b)
    _fund(home_b)

    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="ferronite_rock",
            rng=random.Random(1),
        )
        assert ins["ok"]
        pool_total = int(ins["asteroid"]["total"])
        add_planet_ships(home_a, uid_a, {"harvest_reclaimer": 20}, conn=conn)
        add_planet_ships(home_b, uid_b, {"harvest_reclaimer": 20}, conn=conn)
        commit(conn)

        begin_write_transaction(conn)
        ok1, err1, res1 = send_fleet(
            player_id=uid_a,
            origin_planet_id=home_a,
            mission_type="recycle",
            target_galaxy=g,
            target_system=s,
            target_position=pos,
            ships={"harvest_reclaimer": 20},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert ok1, err1
        mid1 = int(res1["fleet"]["id"])
        ok2, err2, res2 = send_fleet(
            player_id=uid_b,
            origin_planet_id=home_b,
            mission_type="recycle",
            target_galaxy=g,
            target_system=s,
            target_position=pos,
            ships={"harvest_reclaimer": 20},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert ok2, err2
        mid2 = int(res2["fleet"]["id"])
        # Force both arrivals due, but stay within asteroid TTL (2h).
        now = time.time() + 60
        conn.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id IN (?, ?);",
            (now - 5, mid1, mid2),
        )
        commit(conn)

        begin_write_transaction(conn)
        process_fleet_tick(player_id=uid_a, conn=conn, now=now)
        process_fleet_tick(player_id=uid_b, conn=conn, now=now)
        commit(conn)

        row1 = conn.execute(
            "SELECT status, resources_json FROM fleet_movements WHERE id = ?;",
            (mid1,),
        ).fetchone()
        row2 = conn.execute(
            "SELECT status, resources_json FROM fleet_movements WHERE id = ?;",
            (mid2,),
        ).fetchone()
        assert str(row1["status"]) == "returning"
        assert str(row2["status"]) == "returning"
        cargo1 = json.loads(row1["resources_json"] or "{}")
        cargo2 = json.loads(row2["resources_json"] or "{}")
        total1 = (
            int(cargo1.get("metal") or 0)
            + int(cargo1.get("crystal") or 0)
            + int(cargo1.get("fuel_cells") or 0)
        )
        total2 = (
            int(cargo2.get("metal") or 0)
            + int(cargo2.get("crystal") or 0)
            + int(cargo2.get("fuel_cells") or 0)
        )
        assert (total1 > 0) != (total2 > 0)
        assert max(total1, total2) > 0
        assert max(total1, total2) <= pool_total
        assert get_active_asteroid_at(g, s, pos, conn=conn) is None
    finally:
        conn.close()


def test_recycle_without_reclaimer_blocked(ast_db):
    uid = _player("NoRec")
    home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    _fund(home_id)
    conn = db()
    try:
        begin_write_transaction(conn)
        insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="crytite_shard",
            rng=random.Random(3),
        )
        add_planet_ships(home_id, uid, {"mule_courier": 5}, conn=conn)
        commit(conn)

        begin_write_transaction(conn)
        ok, err, _ = send_fleet(
            player_id=uid,
            origin_planet_id=home_id,
            mission_type="recycle",
            target_galaxy=g,
            target_system=s,
            target_position=pos,
            ships={"mule_courier": 5},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        commit(conn)
        assert not ok
        assert err in (
            "recycle_requires_reclaimer",
            "cargo_required_for_recycle",
        ) or "recycle" in str(err)
    finally:
        conn.close()


def test_resolve_target_asteroid_allows_recycle(ast_db):
    uid = _player("Target")
    _home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    conn = db()
    try:
        begin_write_transaction(conn)
        insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="fuel_ice",
            rng=random.Random(9),
        )
        commit(conn)
        info = resolve_fleet_target(uid, g, s, pos, conn=conn)
        assert info["target_type"] == "asteroid"
        assert "recycle" in info["allowed_missions"]
        ok, reason, _ = evaluate_fleet_mission_target(
            uid, "recycle", g, s, pos, conn=conn
        )
        assert ok, reason
        ok_atk, reason_atk, _ = evaluate_fleet_mission_target(
            uid, "attack", g, s, pos, conn=conn
        )
        assert not ok_atk
        assert reason_atk
    finally:
        conn.close()


def test_galaxy_list_system_asteroid_payload(ast_db):
    uid = _player("Galaxy")
    _home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    conn = db()
    try:
        begin_write_transaction(conn)
        insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="mixed_belt",
            rng=random.Random(11),
        )
        commit(conn)
        by_pos = get_asteroids_for_system(g, s, conn=conn)
        assert pos in by_pos
        system = list_system(g, s, conn=conn, viewer_player_id=uid)
        slot = next(sl for sl in system["slots"] if int(sl["position"]) == pos)
        assert slot.get("has_asteroid") is True
        assert slot.get("asteroid")
        assert int(slot["asteroid"]["total"]) > 0
        assert slot["asteroid"]["asteroid_key"] == "mixed_belt"
    finally:
        conn.close()


def test_tick_schedule_expires_and_can_spawn(ast_db):
    uid = _player("Cron")
    _home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    now = time.time()
    conn = db()
    try:
        begin_write_transaction(conn)
        insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="mixed_belt",
            now=now - TTL_SECONDS - 5,
            ttl_seconds=TTL_SECONDS,
            rng=random.Random(5),
        )
        set_runtime_value(SPAWN_RUNTIME_KEY, str(now - 100_000), conn=conn)
        tick = tick_asteroid_schedule(conn=conn, now=now)
        commit(conn)
        assert tick["ok"]
        assert tick["expired_ids"]
        active = list_active_asteroids(conn=conn, now=now)
        assert all(int(a["id"]) not in tick["expired_ids"] for a in active)
    finally:
        conn.close()


def test_claim_partial_cargo_still_removes_asteroid(ast_db):
    uid = _player("Partial")
    _home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="mixed_belt",
            rng=random.Random(99),
        )
        assert ins["ok"]
        assert int(ins["asteroid"]["total"]) > 20_000
        claim = try_claim_harvest(
            g,
            s,
            pos,
            player_id=uid,
            cargo_capacity=20_000,
            conn=conn,
        )
        commit(conn)
        assert claim["status"] == "claimed"
        harvested = claim["harvested"]
        taken = (
            int(harvested["metal"])
            + int(harvested["crystal"])
            + int(harvested["fuel_cells"])
        )
        assert taken == 20_000
        assert get_active_asteroid_at(g, s, pos, conn=conn) is None
    finally:
        conn.close()


def test_asteroid_board_entries_and_list_system(ast_db):
    uid = _player("Board")
    _home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    now = time.time()
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="ferronite_rock",
            now=now,
            ttl_seconds=TTL_SECONDS,
            rng=random.Random(7),
        )
        commit(conn)
        assert ins["ok"]
        board = build_asteroid_board_entries(
            conn=conn, now=now, current_galaxy=g, current_system=s
        )
        assert len(board) >= 1
        row = next(e for e in board if int(e["position"]) == pos)
        assert row["galaxy_href"].startswith("/galaxy?q=")
        assert row["is_current_system"] is True
        assert row["desc_key"]
        assert "ferronite" in row["name_key"]
    finally:
        conn.close()

    data = list_system(g, s, viewer_player_id=uid)
    assert "active_asteroid_board" in data
    assert any(int(e["position"]) == pos for e in data["active_asteroid_board"])


def test_asteroid_board_empty_when_none(ast_db):
    data = list_system(1, 1)
    assert data.get("active_asteroid_board") == []
    schedule = data.get("asteroid_schedule") or {}
    assert "next_eligible_at" in schedule
    assert "max_concurrent" in schedule


def test_asteroid_schedule_countdown_after_spawn(ast_db):
    """After a wave, next_eligible_at is last_spawn + cooldown (server-authoritative)."""
    now = time.time()
    conn = db()
    try:
        begin_write_transaction(conn)
        set_runtime_value(SPAWN_RUNTIME_KEY, str(now), conn=conn)
        commit(conn)
        info = build_schedule_info(conn=conn, now=now + 60)
        assert info["spawn_ready"] is False
        assert abs(float(info["next_eligible_at"]) - (now + INTER_WAVE_COOLDOWN_SEC)) < 1.0
        assert int(info["seconds_until_next"]) > 0
        later = build_schedule_info(conn=conn, now=now + INTER_WAVE_COOLDOWN_SEC + 5)
        # No active fields → under cap; cooldown elapsed → ready.
        assert later["spawn_ready"] is True
        assert int(later["seconds_until_next"]) == 0
    finally:
        conn.close()


def test_asteroid_board_marks_own_outbound_en_route(ast_db):
    """Send stamps engagement; board keeps the row with en-route lock."""
    from game.asteroids import player_engaged_asteroid_ids

    uid = _player("Hunter")
    other = _player("Spectator")
    home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    _fund(home_id)
    now = time.time()
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="mixed_belt",
            now=now,
            ttl_seconds=TTL_SECONDS,
            rng=random.Random(11),
        )
        assert ins["ok"]
        aid = int(ins["asteroid"]["id"])
        add_planet_ships(home_id, uid, {"harvest_reclaimer": 30}, conn=conn)
        commit(conn)

        begin_write_transaction(conn)
        ok, err, res = send_fleet(
            player_id=uid,
            origin_planet_id=home_id,
            mission_type="recycle",
            target_galaxy=g,
            target_system=s,
            target_position=pos,
            ships={"harvest_reclaimer": 10},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        commit(conn)
        assert ok, err
        fleet_id = int((res.get("fleet") or {}).get("id") or 0)
        assert fleet_id > 0
        assert aid in player_engaged_asteroid_ids(uid, conn=conn)
        mv = conn.execute(
            "SELECT resources_json, status FROM fleet_movements WHERE id = ?;",
            (fleet_id,),
        ).fetchone()
        payload = json.loads(mv["resources_json"] or "{}")
        assert int(payload.get("asteroid_id") or 0) == aid

        board_self = build_asteroid_board_entries(
            conn=conn, now=now, viewer_player_id=uid
        )
        row = next(e for e in board_self if int(e["position"]) == pos)
        assert row["viewer_en_route"] is True
        assert row["viewer_harvest_locked"] is True

        board_other = build_asteroid_board_entries(
            conn=conn, now=now, viewer_player_id=other
        )
        other_row = next(e for e in board_other if int(e["position"]) == pos)
        assert other_row.get("viewer_en_route") is False

        begin_write_transaction(conn)
        conn.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
            (now - 1, fleet_id),
        )
        commit(conn)
        begin_write_transaction(conn)
        process_fleet_tick(player_id=uid, now=now, conn=conn)
        commit(conn)
        mv2 = conn.execute(
            "SELECT resources_json, status FROM fleet_movements WHERE id = ?;",
            (fleet_id,),
        ).fetchone()
        assert str(mv2["status"]) == "returning"
        payload2 = json.loads(mv2["resources_json"] or "{}")
        assert int(payload2.get("asteroid_id") or 0) == aid
        assert aid in player_engaged_asteroid_ids(uid, conn=conn)
        assert get_active_asteroid_at(g, s, pos, conn=conn) is None
    finally:
        conn.close()


def test_asteroid_board_en_route_via_target_coords_when_stamped_id_stale(ast_db):
    """Outbound recycle must map to the live field at target coords (stale asteroid_id)."""
    from game.asteroids import viewer_asteroid_fleet_status_map

    uid = _player("CoordHunter")
    home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    _fund(home_id)
    now = time.time()
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="crytite_shard",
            now=now,
            ttl_seconds=TTL_SECONDS,
            rng=random.Random(42),
        )
        assert ins["ok"]
        live_aid = int(ins["asteroid"]["id"])
        add_planet_ships(home_id, uid, {"harvest_reclaimer": 20}, conn=conn)
        commit(conn)

        begin_write_transaction(conn)
        ok, err, res = send_fleet(
            player_id=uid,
            origin_planet_id=home_id,
            mission_type="recycle",
            target_galaxy=g,
            target_system=s,
            target_position=pos,
            ships={"harvest_reclaimer": 5},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        commit(conn)
        assert ok, err
        fleet_id = int((res.get("fleet") or {}).get("id") or 0)
        assert fleet_id > 0

        # Stamp a dead asteroid_id (respawn / TTL swap) while coords stay valid.
        begin_write_transaction(conn)
        raw = conn.execute(
            "SELECT resources_json FROM fleet_movements WHERE id = ?;",
            (fleet_id,),
        ).fetchone()["resources_json"]
        payload = json.loads(raw or "{}")
        payload["asteroid_id"] = live_aid + 99999
        conn.execute(
            "UPDATE fleet_movements SET resources_json = ? WHERE id = ?;",
            (json.dumps(payload), fleet_id),
        )
        commit(conn)

        fleet_map = viewer_asteroid_fleet_status_map(uid, conn=conn, now=now)
        assert live_aid in fleet_map
        assert fleet_map[live_aid]["fleet_status"] == "outbound"

        board = build_asteroid_board_entries(conn=conn, now=now, viewer_player_id=uid)
        row = next(e for e in board if int(e["id"]) == live_aid)
        assert row["viewer_en_route"] is True
        assert row["viewer_harvest_locked"] is True
    finally:
        conn.close()


def test_asteroid_anti_pop_blocks_same_slot_until_expires(ast_db):
    from game.asteroids import _blocked_spawn_coords, spawn_asteroid_belt

    uid = _player("Claimer")
    _home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    now = time.time()
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="ferronite_rock",
            now=now,
            ttl_seconds=TTL_SECONDS,
            rng=random.Random(3),
        )
        assert ins["ok"]
        expires = float(ins["asteroid"]["expires_at"])
        claim = try_claim_harvest(
            g, s, pos, player_id=uid, cargo_capacity=50_000_000, conn=conn, now=now + 10
        )
        assert claim["status"] == "claimed"
        commit(conn)
        blocked = _blocked_spawn_coords(conn, now=now + 10)
        assert (g, s, pos) in blocked
        begin_write_transaction(conn)
        set_runtime_value(SPAWN_RUNTIME_KEY, str(now - INTER_WAVE_COOLDOWN_SEC - 10), conn=conn)
        spawn_asteroid_belt(conn=conn, now=now + 20)
        commit(conn)
        assert get_active_asteroid_at(g, s, pos, conn=conn, now=now + 20) is None
        blocked_later = _blocked_spawn_coords(conn, now=expires + 5)
        assert (g, s, pos) not in blocked_later
    finally:
        conn.close()


def test_asteroid_stamped_expire_skips_debris(ast_db):
    uid = _player("Late")
    home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    _fund(home_id)
    now = time.time()
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="fuel_ice",
            now=now,
            ttl_seconds=30,
            rng=random.Random(9),
        )
        assert ins["ok"]
        add_planet_ships(home_id, uid, {"harvest_reclaimer": 5}, conn=conn)
        ok, err, res = send_fleet(
            player_id=uid,
            origin_planet_id=home_id,
            mission_type="recycle",
            target_galaxy=g,
            target_system=s,
            target_position=pos,
            ships={"harvest_reclaimer": 1},
            resources={},
            speed_percent=100,
            conn=conn,
        )
        assert ok, err
        fleet_id = int((res.get("fleet") or {}).get("id") or 0)
        conn.execute(
            "UPDATE asteroid_fields SET status = 'expired', expires_at = ? WHERE id = ?;",
            (now + 1, int(ins["asteroid"]["id"])),
        )
        conn.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
            (now + 5, fleet_id),
        )
        commit(conn)
        begin_write_transaction(conn)
        process_fleet_tick(player_id=uid, now=now + 6, conn=conn)
        commit(conn)
        mv = conn.execute(
            "SELECT status, resources_json FROM fleet_movements WHERE id = ?;",
            (fleet_id,),
        ).fetchone()
        assert str(mv["status"]) == "returning"
        payload = json.loads(mv["resources_json"] or "{}")
        assert int(payload.get("metal") or 0) == 0
        assert int(payload.get("asteroid_id") or 0) == int(ins["asteroid"]["id"])
    finally:
        conn.close()


def test_asteroid_board_shows_again_after_ttl_reserve(ast_db):
    """After TTL reserve ends, a later belt at the same coords is a new field."""
    uid = _player("Respawn")
    _home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    t0 = time.time()
    conn = db()
    try:
        begin_write_transaction(conn)
        ins1 = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="ferronite_rock",
            now=t0,
            ttl_seconds=60,
            rng=random.Random(3),
        )
        assert ins1["ok"]
        expires = float(ins1["asteroid"]["expires_at"])
        conn.execute(
            "UPDATE asteroid_fields SET status = 'claimed', claimed_at = ?, claimed_by_player_id = ? WHERE id = ?;",
            (t0 + 1, uid, int(ins1["asteroid"]["id"])),
        )
        t1 = expires + 10
        ins2 = insert_asteroid(
            conn=conn,
            galaxy=g,
            system=s,
            position=pos,
            asteroid_key="crytite_shard",
            now=t1,
            ttl_seconds=TTL_SECONDS,
            rng=random.Random(4),
        )
        commit(conn)
        assert ins2["ok"]
        board = build_asteroid_board_entries(conn=conn, now=t1, viewer_player_id=uid)
        assert any(int(e["id"]) == int(ins2["asteroid"]["id"]) for e in board)
    finally:
        conn.close()


def test_galaxy_asteroid_board_template_contract():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    board = (root / "templates/partials/galaxy_asteroid_board.html").read_text(
        encoding="utf-8"
    )
    ring = (root / "templates/partials/galaxy_ring_view.html").read_text(encoding="utf-8")
    qa = (root / "static/js/galaxy-quick-action.js").read_text(encoding="utf-8")
    assert "galaxy_asteroid_board.html" in ring
    assert "data-galaxy-asteroid-board" in board
    assert "galaxy-asteroid-help-modal" in board
    assert "data-galaxy-asteroid-board-toggle" in board
    assert "is-collapsed" in board
    assert "asteroid_schedule" in board
    assert "data-galaxy-asteroid-next-spawn" in board
    assert "galaxy_asteroid_next_spawn_in" in board
    assert "data-next-spawn-at" in board
    assert "galaxy_asteroid_en_route" in board
    assert "galaxy_asteroid_reclaimers_needed" in board or "recycler_slots_needed" in board
    assert "data-refresh-on-zero" in board
    # Board harvest CTA (not PJAX jump) — same GalaxyQuickAction recycle path as ring markers.
    assert "data-galaxy-ring-asteroid-recycle" in board
    assert "data-galaxy-ring-asteroid-wrap" in board
    assert "data-recycler-slots" in board
    assert "galaxy_asteroid_harvest" in board
    assert "galaxy-asteroid-board-jump" not in board
    assert "data-pjax" not in board.split("galaxy-asteroid-board-row-meta")[1].split("</ul>")[0]
    assert "resolveAvailableReclaimersAsync" in qa
    assert "handleAsteroidRecycleClick" in qa
    # Must match World Boss modal shell (dialog + overlay), not broken aliases.
    assert "gc-player-card-dialog" in board
    assert "gc-player-card-overlay" in board
    assert "gc-player-card-modal-dialog" not in board
    assert "openAsteroidHelp" in qa
    assert "initAsteroidBoardToggle" in qa
    assert "document.body.appendChild(modal)" in qa
    main_js = (root / "static/main.js").read_text(encoding="utf-8")
    pjax = main_js.split("async function applyPjaxPayload(url, payload, doc, opts = {})")[1].split(
        "function pjaxPayloadFromDoc"
    )[0]
    assert "initAsteroidBoardToggle" in pjax
    assert "invalidateGalaxyPjaxCache" in main_js.split("function applyActionState(json, reason)")[1].split(
        "function logStatusPollErrorOnce"
    )[0] or "invalidateGalaxyPjaxCache" in main_js.split("function applyActionState(json, reason)")[1][:2500]



def test_mega_belt_player_share_is_capped_at_ten_percent(ast_db):
    from game.asteroids import MEGA_BELT_PLAYER_SHARE, TIER_MEGA, mega_belt_player_share_state

    uid = _player("MegaShare")
    uid_other = _player("MegaOther")
    _home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(conn=conn, galaxy=g, system=s, position=pos, asteroid_key="mega_belt", tier=TIER_MEGA, rng=random.Random(123))
        assert ins["ok"]
        initial = {k: int(ins["asteroid"][k]) for k in ("metal", "crystal", "fuel_cells")}
        claim = try_claim_harvest(g, s, pos, player_id=uid, cargo_capacity=sum(initial.values()) * 2, conn=conn)
        assert claim["status"] == "claimed"
        expected = {k: int(initial[k] * MEGA_BELT_PLAYER_SHARE) for k in initial}
        assert {k: int(claim["harvested"][k]) for k in expected} == expected
        again = try_claim_harvest(g, s, pos, player_id=uid, cargo_capacity=sum(initial.values()) * 2, conn=conn)
        assert again["status"] == "quota_exhausted"
        assert sum(int(v or 0) for v in again["harvested"].values()) == 0
        other = try_claim_harvest(g, s, pos, player_id=uid_other, cargo_capacity=sum(initial.values()) * 2, conn=conn)
        assert other["status"] == "claimed"
        assert {k: int(other["harvested"][k]) for k in expected} == expected
        state = mega_belt_player_share_state(int(ins["asteroid"]["id"]), uid, conn=conn)
        assert state["quota_exhausted"] is True
        assert state["share_percent"] == pytest.approx(10.0, abs=0.01)
        assert get_active_asteroid_at(g, s, pos, conn=conn) is not None
        commit(conn)
    finally:
        conn.close()


def test_mega_belt_small_fleet_can_repeat_until_personal_share_is_full(ast_db):
    from game.asteroids import TIER_MEGA, mega_belt_player_share_state

    uid = _player("MegaSmall")
    _home_id, g, s, _ = _home(uid)
    pos = _free_slot_near(g, s)
    conn = db()
    try:
        begin_write_transaction(conn)
        ins = insert_asteroid(conn=conn, galaxy=g, system=s, position=pos, asteroid_key="mega_belt", tier=TIER_MEGA, rng=random.Random(321))
        assert ins["ok"]
        aid = int(ins["asteroid"]["id"])
        quota_total = int(mega_belt_player_share_state(aid, uid, conn=conn)["player_remaining_total"])
        assert quota_total > 10
        tiny_capacity = max(1, quota_total // 4)
        harvested_total = 0
        claims = 0
        while True:
            result = try_claim_harvest(g, s, pos, player_id=uid, cargo_capacity=tiny_capacity, conn=conn)
            if result["status"] == "quota_exhausted":
                break
            assert result["status"] == "claimed"
            harvested_total += sum(int(v or 0) for v in result["harvested"].values())
            claims += 1
            assert claims < 10
        assert claims >= 2
        assert harvested_total == quota_total
        state = mega_belt_player_share_state(aid, uid, conn=conn)
        assert state["quota_exhausted"] is True
        assert state["player_remaining_total"] == 0
        commit(conn)
    finally:
        conn.close()


def test_asteroid_viewer_lifecycle_distinguishes_return_and_clears_stale_engagement():
    from game.asteroids import enrich_asteroid_viewer_state

    asteroid = {"id": 77, "tier": "mega"}
    future = time.time() + 120
    outbound = enrich_asteroid_viewer_state(asteroid, engaged_ids={77}, fleet_map={77: {"fleet_status": "outbound", "arrival_at": future, "engaged": True}})
    assert outbound["viewer_en_route"] is True
    assert outbound["viewer_returning"] is False
    assert outbound["viewer_harvest_locked"] is True
    returning = enrich_asteroid_viewer_state(asteroid, engaged_ids={77}, fleet_map={77: {"fleet_status": "returning", "arrival_at": future, "engaged": True}})
    assert returning["viewer_en_route"] is False
    assert returning["viewer_returning"] is True
    assert returning["viewer_harvest_locked"] is True
    completed = enrich_asteroid_viewer_state(asteroid, engaged_ids={77}, fleet_map={})
    assert completed["viewer_has_engaged"] is True
    assert completed["viewer_engaged"] is False
    assert completed["viewer_en_route"] is False
    assert completed["viewer_returning"] is False
    assert completed["viewer_harvest_locked"] is False
