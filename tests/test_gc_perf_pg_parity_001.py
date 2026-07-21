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
