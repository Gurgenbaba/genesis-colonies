"""
GC-PERF-PG-PARITY-001 — Block A/B: Auth + Bootstrap + Homeworld + Economy Scope.

Same assertions on SQLite (always) and PostgreSQL when GC_TEST_POSTGRES_URL is set.
No local Docker — Postgres only via staging/test URL (see docs/GC_PERF_PG_PARITY_001.md).

Run:
  python -m pytest tests/test_gc_perf_pg_parity_001.py -v
  # separate shell with staging URL:
  $env:GC_DB_BACKEND="postgres"
  $env:GC_TEST_POSTGRES_URL="<staging public URL>"
  $env:DATABASE_URL=$env:GC_TEST_POSTGRES_URL
  python -m pytest tests/test_gc_perf_pg_parity_001.py -v -s
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

# Fixtures come from tests/conftest.py → pytest_plugins = ["pg_fixtures"]
from tests.pg_fixtures import requires_postgres

ROOT = Path(__file__).resolve().parents[1]


def test_ticket_doc_exists():
    assert (ROOT / "docs" / "GC_PERF_PG_PARITY_001.md").is_file()
    core = (ROOT / "docs" / "GC_PERF_CORE.md").read_text(encoding="utf-8")
    assert "GC-PERF-PG-PARITY-001" in core


def test_pg_fixtures_module_importable():
    from tests.pg_fixtures import (
        close_pg_pool,
        postgres_test_url,
        wipe_postgres_game_data,
    )

    assert callable(close_pg_pool)
    assert callable(wipe_postgres_game_data)
    assert isinstance(postgres_test_url(), str)


def _assert_auth_bootstrap_parity() -> None:
    from game.db import db, get_db_backend, table_exists
    from game.models import (
        BUILDING_KEYS,
        DEFAULT_GAME_SETTINGS,
        create_user,
        get_game_settings,
        get_homeworld,
        get_planet_buildings,
        get_user_by_username,
        hash_password,
        init_db,
        load_player,
        verify_password,
        verify_user,
    )
    from game.planet_evolution.dna import MAX_SQLITE_SIGNED_INT
    from game.planet_evolution.repository import get_active_planet_id

    backend = get_db_backend()
    conn = db()
    try:
        assert table_exists(conn, "users")
        assert table_exists(conn, "players")
        assert table_exists(conn, "planets")
        assert table_exists(conn, "planet_buildings")
        assert table_exists(conn, "game_settings")
        if backend == "postgres":
            # Runtime PRAGMAs are SQLite-only; PG path must not depend on them.
            cur = conn.cursor()
            cur.execute("SELECT 1 AS ok;")
            assert cur.fetchone()["ok"] == 1
    finally:
        conn.close()

    admin = get_user_by_username("admin")
    assert admin is not None
    assert int(admin["is_admin"]) == 1
    assert verify_password(admin["password_hash"], "admin")

    admin_id = int(admin["id"])
    admin_player = load_player(admin_id)
    assert admin_player is not None
    assert int(admin_player["id"]) == admin_id  # users.id == players.id

    home = get_homeworld(admin_id)
    assert home is not None
    assert int(home["is_homeworld"]) == 1
    assert home.get("name")
    assert int(home["player_id"]) == admin_id
    dna_seed = int(home.get("dna_seed") or 0)
    assert 0 <= dna_seed <= MAX_SQLITE_SIGNED_INT

    admin_active = int(get_active_planet_id(admin_id))
    assert admin_active == int(home["id"])

    settings = get_game_settings()
    for key in DEFAULT_GAME_SETTINGS:
        assert key in settings, f"missing game_settings key: {key}"
        assert settings[key] is not None and str(settings[key]) != ""

    uname = f"parity_{uuid.uuid4().hex[:10]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    assert user is not None
    assert user["id"]
    assert user["username"] == uname

    uid = int(user["id"])
    loaded = get_user_by_username(uname)
    assert loaded is not None
    assert int(loaded["id"]) == uid
    assert verify_user(uname, "test-pass-123") is not None
    assert verify_user(uname, "wrong-password") is None

    player = load_player(uid)
    assert player is not None
    assert int(player["id"]) == uid  # users.id == players.id
    assert player["name"] == uname

    hw = get_homeworld(uid)
    assert hw is not None
    assert int(hw["player_id"]) == uid
    assert int(hw["is_homeworld"]) == 1
    seed = int(hw.get("dna_seed") or 0)
    assert 0 <= seed <= MAX_SQLITE_SIGNED_INT

    # Start resources match seeded game_settings (same source ensure_player_and_homeworld uses).
    assert float(hw["metal"]) == float(settings["start_metal"])
    assert float(hw["crystal"]) == float(settings["start_crystal"])
    assert float(hw["fuel_cells"]) == float(settings["start_fuel_cells"])

    buildings = get_planet_buildings(int(hw["id"]))
    for key in BUILDING_KEYS:
        assert int(buildings.get(key, 0)) == 0, f"default building {key} must be 0"

    active = int(get_active_planet_id(uid))
    assert active == int(hw["id"])
    # Column should point at owned planet when present.
    conn = db()
    try:
        from game.db import column_exists

        if column_exists(conn, "players", "active_planet_id"):
            row = conn.execute(
                "SELECT active_planet_id FROM players WHERE id = ? LIMIT 1;",
                (uid,),
            ).fetchone()
            ap = row["active_planet_id"] if row else None
            assert ap is not None
            assert int(ap) == int(hw["id"])
    finally:
        conn.close()

    ok2, err2, _ = create_user(uname, "other-pass-456")
    assert ok2 is False
    assert err2
    assert (
        "vergeben" in str(err2).lower()
        or "already" in str(err2).lower()
        or "unique" in str(err2).lower()
    )

    h = hash_password("roundtrip-secret")
    assert verify_password(h, "roundtrip-secret")
    assert not verify_password(h, "nope")

    # Bootstrap / init_db idempotent: no duplicate admin, homeworlds, or settings.
    conn = db()
    try:
        users_before = int(conn.execute("SELECT COUNT(*) AS c FROM users;").fetchone()["c"])
        players_before = int(conn.execute("SELECT COUNT(*) AS c FROM players;").fetchone()["c"])
        planets_before = int(conn.execute("SELECT COUNT(*) AS c FROM planets;").fetchone()["c"])
        settings_before = int(
            conn.execute("SELECT COUNT(*) AS c FROM game_settings;").fetchone()["c"]
        )
        admin_homes_before = int(
            conn.execute(
                "SELECT COUNT(*) AS c FROM planets WHERE player_id = ? AND is_homeworld = 1;",
                (admin_id,),
            ).fetchone()["c"]
        )
    finally:
        conn.close()

    init_db()

    conn = db()
    try:
        assert int(conn.execute("SELECT COUNT(*) AS c FROM users;").fetchone()["c"]) == users_before
        assert (
            int(conn.execute("SELECT COUNT(*) AS c FROM players;").fetchone()["c"])
            == players_before
        )
        assert (
            int(conn.execute("SELECT COUNT(*) AS c FROM planets;").fetchone()["c"])
            == planets_before
        )
        assert (
            int(conn.execute("SELECT COUNT(*) AS c FROM game_settings;").fetchone()["c"])
            == settings_before
        )
        assert (
            int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM planets WHERE player_id = ? AND is_homeworld = 1;",
                    (admin_id,),
                ).fetchone()["c"]
            )
            == admin_homes_before
            == 1
        )
    finally:
        conn.close()


def test_parity_a_auth_bootstrap_sqlite(sqlite_parity_db):
    _assert_auth_bootstrap_parity()


@requires_postgres
def test_parity_a_auth_bootstrap_postgres(pg_parity_db):
    _assert_auth_bootstrap_parity()


def _assert_economy_scope_parity() -> None:
    """Block B: resources + context planet stay server-owned and consistent."""
    from game.db import db
    from game.live_state import get_request_context_planet
    from game.models import (
        create_user,
        get_homeworld,
        get_planets_by_player,
    )
    from game.planet_evolution.repository import get_active_planet_id
    from game.resources import update_planet_resources

    uname = f"econ_{uuid.uuid4().hex[:10]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    home = get_homeworld(uid)
    assert home is not None
    pid = int(home["id"])
    assert int(get_active_planet_id(uid)) == pid

    conn = db()
    try:
        planet, buildings, ratio, energy_total, energy_used = update_planet_resources(
            dict(home),
            conn=conn,
            skip_queue_finish=True,
        )
        assert int(planet["id"]) == pid
        assert isinstance(buildings, dict)
        assert float(ratio) >= 0.0
        assert int(energy_total) >= 0
        assert int(energy_used) >= 0
        metal = float(planet.get("metal") or 0)
        crystal = float(planet.get("crystal") or 0)
        assert metal >= 0.0
        assert crystal >= 0.0
        # After create, stock is at least start_* (tick may add tiny production).
        from game.models import get_game_settings

        settings = get_game_settings(conn)
        assert metal >= float(settings["start_metal"]) - 1.0
        assert crystal >= float(settings["start_crystal"]) - 1.0

        ctx = get_request_context_planet(uid, conn=conn)
        assert int(ctx["id"]) == pid
        planets = get_planets_by_player(uid, conn=conn)
        assert any(int(p["id"]) == pid for p in planets)
        assert len(planets) >= 1
    finally:
        conn.close()


def test_parity_b_economy_scope_sqlite(sqlite_parity_db):
    _assert_economy_scope_parity()


@requires_postgres
def test_parity_b_economy_scope_postgres(pg_parity_db):
    _assert_economy_scope_parity()


def _prepare_queue_planet(uid: int, planet_id: int) -> None:
    """Unlock lab/yard/defense factory + common research for queue parity."""
    from game.db import begin_write_transaction, commit, db

    conn = db()
    try:
        begin_write_transaction(conn)
        conn.execute(
            """
            UPDATE planets
            SET metal = ?, crystal = ?, fuel_cells = ?
            WHERE id = ?;
            """,
            (5_000_000, 5_000_000, 100_000, int(planet_id)),
        )
        conn.execute(
            """
            UPDATE planet_buildings
            SET research_lab = 10,
                command_center = 10,
                barracks = 10,
                shipyard = 2,
                orbital_shipyard = 2,
                defense_factory = 2
            WHERE planet_id = ?;
            """,
            (int(planet_id),),
        )
        for tech in (
            "energy_tech",
            "mining_tech",
            "drone_tech",
            "engine_tech",
            "navigation_tech",
            "weapon_tech",
            "armor_tech",
            "storage_tech",
            "fuel_efficiency",
            "shield_tech",
        ):
            conn.execute(
                """
                INSERT INTO research_levels (user_id, tech_key, level)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
                """,
                (int(uid), tech, 10),
            )
        commit(conn)
    finally:
        conn.close()


def _assert_queue_parity() -> None:
    """
    Block C: buildings, account research, shipyard, defense —
    finish-before-mutate, cancel-refund, reschedule, parallel enqueue.
    """
    import time

    from game.buildings import cancel_build_job_for_planet, get_upgrade_cost, queue_build_for_planet
    from game.db import commit, db
    from game.defense import build_defense
    from game.defense_api import cancel_defense_job
    from game.fleet import get_planet_ships
    from game.models import (
        create_user,
        get_build_queue_rows,
        get_homeworld,
        get_planet_buildings,
        get_research_levels,
        get_research_queue_rows,
    )
    from game.queue_engine import finish_due_work
    from game.queue_refund import REFUND_RATIO_PENDING
    from game.research import cancel_research_job, get_research_cost, queue_research
    from game.shipyard import build_ship, cancel_shipyard_job
    from game.shipyard_queue import queue_count as shipyard_queue_count

    uname = f"q_{uuid.uuid4().hex[:10]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    home = get_homeworld(uid)
    assert home is not None
    pid = int(home["id"])
    _prepare_queue_planet(uid, pid)
    planet = dict(get_homeworld(uid))
    buildings = get_planet_buildings(pid)

    # --- Buildings: enqueue → finish due → level up ---
    lvl0 = int(buildings.get("metal_mine") or 0)
    ok, reason, _ = queue_build_for_planet(planet, buildings, "metal_mine", user_id=uid)
    assert ok, reason
    rows = get_build_queue_rows(pid)
    assert len(rows) == 1
    job_id = int(rows[0]["id"])
    assert job_id > 0

    now = time.time()
    conn = db()
    try:
        conn.execute(
            "UPDATE build_queue SET start_time = ?, finish_time = ? WHERE id = ?;",
            (now - 100, now - 1, job_id),
        )
        commit(conn)
    finally:
        conn.close()

    finished = finish_due_work(player_id=uid, planet_id=pid, source="parity_c")
    assert int(finished["finished"]["buildings"]) == 1
    assert int(get_planet_buildings(pid).get("metal_mine") or 0) == lvl0 + 1
    assert get_build_queue_rows(pid) == []

    # Finish-before-mutate: due job must clear before new enqueue sees empty queue
    buildings = get_planet_buildings(pid)
    planet = dict(get_homeworld(uid))
    ok, reason, _ = queue_build_for_planet(planet, buildings, "crystal_mine", user_id=uid)
    assert ok, reason
    job_b = get_build_queue_rows(pid)[0]
    cost_m, cost_c = get_upgrade_cost("crystal_mine", int(buildings.get("crystal_mine") or 0))

    conn = db()
    try:
        row = conn.execute(
            "SELECT metal, crystal FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        metal_after_q = float(row["metal"])
        crystal_after_q = float(row["crystal"])
        # Force pending (not yet started) for full refund
        conn.execute(
            "UPDATE build_queue SET start_time = ?, finish_time = ? WHERE id = ?;",
            (now + 500, now + 600, int(job_b["id"])),
        )
        commit(conn)
    finally:
        conn.close()

    ok, reason, payload = cancel_build_job_for_planet(pid, int(job_b["id"]), user_id=uid)
    assert ok, reason
    assert payload.get("refund_ratio") == REFUND_RATIO_PENDING
    conn = db()
    try:
        row = conn.execute(
            "SELECT metal, crystal FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        assert float(row["metal"]) == pytest.approx(metal_after_q + cost_m, rel=0.01)
        assert float(row["crystal"]) == pytest.approx(crystal_after_q + cost_c, rel=0.01)
    finally:
        conn.close()
    assert get_build_queue_rows(pid) == []

    # --- Account research: enqueue + cancel refund ---
    player = {"id": uid}
    tech = "energy_tech"
    levels = get_research_levels(uid)
    lvl_tech = int(levels.get(tech) or 0)
    rm, rc = get_research_cost(tech, lvl_tech)
    ok, reason, _ = queue_research(player, tech, user_id=uid)
    assert ok, reason
    rq = get_research_queue_rows(uid)
    assert len(rq) >= 1
    rjob = int(rq[0]["id"])
    assert rjob > 0

    conn = db()
    try:
        conn.execute(
            "UPDATE research_queue SET start_at = ?, finish_at = ? WHERE id = ?;",
            (now + 800, now + 900, rjob),
        )
        # Keep as pending/future for full refund path
        commit(conn)
        row = conn.execute(
            "SELECT metal, crystal FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        m_before_refund = float(row["metal"])
        c_before_refund = float(row["crystal"])
    finally:
        conn.close()

    ok, reason, rpayload = cancel_research_job(uid, rjob)
    assert ok, reason
    assert rpayload.get("refund_ratio") == REFUND_RATIO_PENDING
    conn = db()
    try:
        row = conn.execute(
            "SELECT metal, crystal FROM planets WHERE id = ?;",
            (pid,),
        ).fetchone()
        assert float(row["metal"]) == pytest.approx(m_before_refund + rm, rel=0.01)
        assert float(row["crystal"]) == pytest.approx(c_before_refund + rc, rel=0.01)
    finally:
        conn.close()

    # --- Shipyard: enqueue two, cancel first → reschedule remaining ---
    conn = db()
    try:
        ok, reason, result = build_ship(
            player_id=uid, planet_id=pid, ship_key="mule_courier", amount=1, conn=conn
        )
        assert ok, reason
        ok2, reason2, result2 = build_ship(
            player_id=uid, planet_id=pid, ship_key="mule_courier", amount=1, conn=conn
        )
        assert ok2, reason2
        commit(conn)
        assert shipyard_queue_count(pid, conn=conn) == 2
        q = result2["shipyard_queue"]["queue"]
        assert len(q) == 2
        first_id = int(q[0]["id"])
        second_finish_before = float(q[1]["finish_at"])
        ok_c, reason_c, cancelled = cancel_shipyard_job(
            player_id=uid, planet_id=pid, job_id=first_id, conn=conn
        )
        assert ok_c, reason_c
        commit(conn)
        assert shipyard_queue_count(pid, conn=conn) == 1
        remaining = (cancelled or {}).get("shipyard_queue", {}).get("queue") or []
        assert len(remaining) == 1
        # Reschedule: remaining job must start sooner after head cancel
        assert float(remaining[0]["finish_at"]) <= second_finish_before + 1.0
        assert get_planet_ships(pid, conn=conn).get("mule_courier", 0) == 0
    finally:
        conn.close()

    # Finish shipyard job
    conn = db()
    try:
        row = conn.execute(
            "SELECT id FROM shipyard_queue WHERE planet_id = ? AND status = 'queued' LIMIT 1;",
            (pid,),
        ).fetchone()
        assert row is not None
        sid = int(row["id"])
        conn.execute(
            "UPDATE shipyard_queue SET started_at = ?, finish_at = ? WHERE id = ?;",
            (now - 50, now - 1, sid),
        )
        commit(conn)
    finally:
        conn.close()
    fin = finish_due_work(player_id=uid, planet_id=pid, source="parity_c_sy")
    assert int(fin["finished"]["shipyard"]) >= 1
    conn = db()
    try:
        ships = get_planet_ships(pid, conn=conn)
        assert int(ships.get("mule_courier") or 0) >= 1
        assert shipyard_queue_count(pid, conn=conn) == 0
    finally:
        conn.close()

    # --- Defense: enqueue + cancel ---
    conn = db()
    try:
        ok, reason, dresult = build_defense(
            player_id=uid, planet_id=pid, defense_key="slug_launcher", amount=2, conn=conn
        )
        assert ok, reason
        commit(conn)
        dq = (dresult or {}).get("defense_queue", {}).get("queue") or []
        assert len(dq) == 1
        did = int(dq[0]["id"])
        assert did > 0
        ok_d, reason_d = cancel_defense_job(
            player_id=uid, planet_id=pid, job_id=did, conn=conn
        )
        assert ok_d, reason_d
        commit(conn)
        left = conn.execute(
            "SELECT COUNT(*) AS c FROM defense_queue WHERE planet_id = ? AND status = 'queued';",
            (pid,),
        ).fetchone()
        assert int(left["c"]) == 0
    finally:
        conn.close()
    # Parallel enqueue: two builds without exceeding queue / duplicate overflow
    buildings = get_planet_buildings(pid)
    planet = dict(get_homeworld(uid))
    ok_a, reason_a, _ = queue_build_for_planet(planet, buildings, "metal_mine", user_id=uid)
    assert ok_a, reason_a
    buildings = get_planet_buildings(pid)
    planet = dict(get_homeworld(uid))
    ok_b, reason_b, _ = queue_build_for_planet(planet, buildings, "crystal_mine", user_id=uid)
    assert ok_b, reason_b
    assert len(get_build_queue_rows(pid)) == 2


def test_parity_c_queues_sqlite(sqlite_parity_db):
    _assert_queue_parity()


@requires_postgres
def test_parity_c_queues_postgres(pg_parity_db):
    _assert_queue_parity()


# ---------------------------------------------------------------------------
# Block D — Fleet + Combat + Expedition
# ---------------------------------------------------------------------------


def _parity_d_username(prefix: str) -> str:
    from game.name_policy import validate_player_name

    for i in range(128):
        candidate = f"{prefix}{uuid.uuid4().hex[:8]}{i:02d}"
        ok, _ = validate_player_name(candidate)
        if ok:
            return candidate
    raise AssertionError("could not allocate policy-safe username")


def _parity_d_fund(cur, planet_id: int, *, metal=50000, crystal=50000, fuel_cells=50000) -> None:
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
        (metal, crystal, fuel_cells, int(planet_id)),
    )


def _parity_d_seed_ships(conn, planet_id: int, player_id: int, ships: dict) -> None:
    from game.fleet import add_planet_ships

    add_planet_ships(planet_id, player_id, ships, conn=conn)


def _parity_d_coords(conn, planet_id: int) -> tuple[int, int, int]:
    row = conn.execute(
        "SELECT galaxy, system, position FROM planets WHERE id = ?;",
        (int(planet_id),),
    ).fetchone()
    return (int(row["galaxy"]), int(row["system"]), int(row["position"]))


def _parity_d_unlock_expansion(conn, uid: int, home_id: int) -> None:
    from game.planet_evolution.expansion_protocol import INTERSTELLAR_EXPANSION_TECH

    conn.execute("UPDATE planets SET planet_level = 25 WHERE id = ?;", (int(home_id),))
    conn.execute(
        """
        INSERT INTO research_levels (user_id, tech_key, level)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, tech_key) DO UPDATE SET level = excluded.level;
        """,
        (int(uid), INTERSTELLAR_EXPANSION_TECH, 6),
    )


def _parity_d_second_colony(conn, uid: int, home_id: int) -> int:
    from game.planet_evolution.service import colonize_planet

    _parity_d_unlock_expansion(conn, uid, home_id)
    ok, reason, extra = colonize_planet(
        uid,
        name="Parity Colony",
        galaxy=1,
        system=310,
        position=5,
        conn=conn,
        allow_legacy_coordinates=True,
        source="parity_d",
    )
    assert ok, reason
    return int(extra["planet_id"])


def _parity_d_foreign_planet() -> tuple[int, int, tuple[int, int, int]]:
    from game.db import begin_write_transaction, commit, db
    from game.models import create_user, ensure_player_and_homeworld, get_planets_by_player

    ok, err, user = create_user(_parity_d_username("frgn"), "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name="Foreign", conn=conn)
        pid = int(get_planets_by_player(uid, conn=conn)[0]["id"])
        coords = _parity_d_coords(conn, pid)
        commit(conn)
    finally:
        conn.close()
    return uid, pid, coords


def _assert_fleet_combat_parity() -> None:
    import json
    import time

    from game.db import begin_write_transaction, commit, db
    from game.fleet import get_planet_ships, process_fleet_tick, send_fleet
    from game.fleet_calc import loaded_resource_total
    from game.fleet_defs import EXPEDITION_POSITION
    from game.messages import get_message, list_messages
    from game.models import (
        add_planet_defense,
        create_user,
        ensure_player_and_homeworld,
        get_homeworld,
        get_planet_defense,
        get_planets_by_player,
    )

    ok, err, user = create_user(_parity_d_username("fld"), "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    conn = db()
    try:
        begin_write_transaction(conn)
        ensure_player_and_homeworld(uid, player_name="FleetAdmiral", conn=conn)
        home = get_homeworld(uid, conn=conn)
        assert home is not None
        pid = int(home["id"])
        cur = conn.cursor()
        _parity_d_fund(cur, pid)
        colony2 = _parity_d_second_colony(conn, uid, pid)
        g2, s2, p2 = _parity_d_coords(conn, colony2)
        cur.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (colony2,))
        before_colony = dict(cur.fetchone())
        _parity_d_seed_ships(conn, pid, uid, {"mule_courier": 5, "solar_skiff": 2, "ironclad_frigate": 12})
        commit(conn)

        # 1) Transport send → arrival credit → return ships home
        ok, reason, result = send_fleet(
            player_id=uid,
            origin_planet_id=pid,
            target_galaxy=g2,
            target_system=s2,
            target_position=p2,
            mission_type="transport",
            ships={"mule_courier": 1},
            resources={"metal": 2000, "crystal": 500},
            conn=conn,
        )
        assert ok, reason
        fleet_id = int(result["fleet"]["id"])
        assert fleet_id > 0
        cur.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
            (time.time() - 1, fleet_id),
        )
        commit(conn)
        tick1 = process_fleet_tick(player_id=uid, conn=conn)
        commit(conn)
        assert int(tick1.get("processed_arrivals") or 0) == 1
        cur.execute("SELECT status FROM fleet_movements WHERE id = ?;", (fleet_id,))
        assert cur.fetchone()["status"] == "returning"
        cur.execute("SELECT metal, crystal FROM planets WHERE id = ?;", (colony2,))
        after_colony = dict(cur.fetchone())
        assert int(after_colony["metal"]) == int(before_colony["metal"]) + 2000
        assert int(after_colony["crystal"]) == int(before_colony["crystal"]) + 500

        # 2) Double-tick idempotent on transport arrival
        tick2 = process_fleet_tick(player_id=uid, conn=conn)
        commit(conn)
        assert int(tick2.get("processed_arrivals") or 0) == 0
        cur.execute("SELECT metal FROM planets WHERE id = ?;", (colony2,))
        assert int(cur.fetchone()["metal"]) == int(after_colony["metal"])

        ships_before_return = int(get_planet_ships(pid, conn=conn).get("mule_courier") or 0)
        cur.execute(
            "UPDATE fleet_movements SET return_at = ? WHERE id = ?;",
            (time.time() - 1, fleet_id),
        )
        commit(conn)
        process_fleet_tick(player_id=uid, conn=conn)
        commit(conn)
        assert int(get_planet_ships(pid, conn=conn).get("mule_courier") or 0) == ships_before_return + 1
    finally:
        conn.close()

    # 3–5) Attack → combat messages + loot return + debris
    foreign_uid, foreign_pid, (fg, fs, fp) = _parity_d_foreign_planet()
    conn = db()
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        _parity_d_fund(cur, pid)
        _parity_d_fund(cur, foreign_pid, metal=80000, crystal=40000, fuel_cells=20000)
        _parity_d_seed_ships(
            conn, pid, uid, {"ironclad_frigate": 12, "mule_courier": 1}
        )
        add_planet_defense(foreign_pid, {"sentinel_turret": 8}, conn=conn)
        commit(conn)

        ok, reason, result = send_fleet(
            player_id=uid,
            origin_planet_id=pid,
            target_galaxy=fg,
            target_system=fs,
            target_position=fp,
            mission_type="attack",
            ships={"ironclad_frigate": 12, "mule_courier": 1},
            conn=conn,
        )
        assert ok, reason
        attack_id = int(result["fleet"]["id"])
        cur.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
            (time.time() - 1, attack_id),
        )
        commit(conn)
        process_fleet_tick(player_id=uid, conn=conn)
        commit(conn)

        msgs = list_messages(uid, category="combat")
        messages = msgs["data"]["messages"]
        assert len(messages) >= 1
        detail = get_message(uid, messages[0]["id"], mark_read=False)
        meta = detail["data"]["message"].get("metadata") or {}
        assert meta.get("result") in ("attacker", "defender", "draw")
        assert int(meta.get("rounds_fought") or 0) >= 1
        defender_msgs = list_messages(foreign_uid, category="combat")
        assert len(defender_msgs["data"]["messages"]) >= 1

        cur.execute(
            "SELECT status, resources_json, ships_json FROM fleet_movements WHERE id = ?;",
            (attack_id,),
        )
        row = cur.fetchone()
        assert row["status"] == "returning"
        loaded = json.loads(row["resources_json"] or "{}")
        loot_total = loaded_resource_total(loaded)
        assert loot_total > 0
        assert sum(get_planet_defense(foreign_pid, conn=conn).values()) < 8

        cur.execute(
            "SELECT metal, crystal FROM debris_fields WHERE galaxy = ? AND system = ? AND position = ?;",
            (fg, fs, fp),
        )
        debris = cur.fetchone()
        assert debris is not None
        assert float(debris["metal"]) > 0 or float(debris["crystal"]) > 0

        cur.execute(
            "SELECT metal FROM planets WHERE id = ?;",
            (pid,),
        )
        home_before = float(cur.fetchone()["metal"])
        cur.execute(
            "UPDATE fleet_movements SET return_at = ? WHERE id = ?;",
            (time.time() - 1, attack_id),
        )
        commit(conn)
        process_fleet_tick(player_id=uid, conn=conn)
        commit(conn)
        cur.execute("SELECT metal FROM planets WHERE id = ?;", (pid,))
        home_after = float(cur.fetchone()["metal"])
        assert home_after >= home_before + float(loaded.get("metal") or 0)

        # Attack arrival double-tick: no second processed arrival
        tick_again = process_fleet_tick(player_id=uid, conn=conn)
        commit(conn)
        assert int(tick_again.get("processed_arrivals") or 0) == 0
    finally:
        conn.close()

    # 6) Expedition send → hold → return loot path idempotent
    conn = db()
    try:
        begin_write_transaction(conn)
        cur = conn.cursor()
        _parity_d_fund(cur, pid)
        _parity_d_seed_ships(conn, pid, uid, {"solar_skiff": 2})
        g, s, _ = _parity_d_coords(conn, pid)
        commit(conn)
        ok, reason, result = send_fleet(
            player_id=uid,
            origin_planet_id=pid,
            target_galaxy=g,
            target_system=s,
            target_position=EXPEDITION_POSITION,
            mission_type="expedition",
            ships={"solar_skiff": 1},
            conn=conn,
        )
        assert ok, reason
        exp_id = int(result["fleet"]["id"])
        cur.execute(
            "UPDATE fleet_movements SET arrival_at = ? WHERE id = ?;",
            (time.time() - 1, exp_id),
        )
        commit(conn)
        t_arr = process_fleet_tick(player_id=uid, conn=conn)
        commit(conn)
        assert int(t_arr.get("processed_arrivals") or 0) == 1
        cur.execute("SELECT status FROM fleet_movements WHERE id = ?;", (exp_id,))
        assert cur.fetchone()["status"] == "holding"
        cur.execute(
            "UPDATE fleet_movements SET holding_until = ? WHERE id = ? AND status = 'holding';",
            (time.time() - 1, exp_id),
        )
        commit(conn)
        t_hold = process_fleet_tick(player_id=uid, conn=conn)
        commit(conn)
        assert int(t_hold.get("processed_holding") or 0) >= 1 or int(
            t_hold.get("processed_arrivals") or 0
        ) >= 1
        cur.execute(
            "SELECT status, resources_json FROM fleet_movements WHERE id = ?;",
            (exp_id,),
        )
        row_once = dict(cur.fetchone())
        assert row_once["status"] == "returning"
        rewards_once = json.loads(row_once["resources_json"] or "{}")
        t_dup = process_fleet_tick(player_id=uid, conn=conn)
        commit(conn)
        assert int(t_dup.get("processed_holding") or 0) == 0
        assert int(t_dup.get("processed_arrivals") or 0) == 0
        cur.execute("SELECT resources_json FROM fleet_movements WHERE id = ?;", (exp_id,))
        rewards_twice = json.loads(dict(cur.fetchone())["resources_json"] or "{}")
        assert rewards_once == rewards_twice
        cur.execute(
            "UPDATE fleet_movements SET return_at = ? WHERE id = ?;",
            (time.time() - 1, exp_id),
        )
        commit(conn)
        process_fleet_tick(player_id=uid, conn=conn)
        commit(conn)
        cur.execute("SELECT status FROM fleet_movements WHERE id = ?;", (exp_id,))
        done = cur.fetchone()
        assert done is None or done["status"] not in ("outbound", "holding", "returning")
    finally:
        conn.close()


def test_parity_d_fleet_combat_sqlite(sqlite_parity_db):
    _assert_fleet_combat_parity()


@requires_postgres
def test_parity_d_fleet_combat_postgres(pg_parity_db):
    _assert_fleet_combat_parity()
