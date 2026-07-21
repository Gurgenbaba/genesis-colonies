"""
GC-PERF-PG-PARITY-001 — Block A: Auth + Bootstrap + Homeworld.

Runs the same assertions on SQLite (always) and PostgreSQL (when
GC_TEST_POSTGRES_URL is set and CREATEDB is allowed).

Run:
  python -m pytest tests/test_gc_perf_pg_parity_001.py -v
  GC_TEST_POSTGRES_URL=… python -m pytest tests/test_gc_perf_pg_parity_001.py -v
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
    from game.db import db, table_exists
    from game.models import (
        create_user,
        get_homeworld,
        get_user_by_username,
        hash_password,
        load_player,
        verify_password,
        verify_user,
    )
    from game.planet_evolution.dna import MAX_SQLITE_SIGNED_INT

    conn = db()
    try:
        assert table_exists(conn, "users")
        assert table_exists(conn, "players")
        assert table_exists(conn, "planets")
    finally:
        conn.close()

    admin = get_user_by_username("admin")
    assert admin is not None
    assert int(admin["is_admin"]) == 1
    assert verify_password(admin["password_hash"], "admin")

    admin_player = load_player(int(admin["id"]))
    assert admin_player is not None
    home = get_homeworld(int(admin["id"]))
    assert home is not None
    assert int(home["is_homeworld"]) == 1
    assert home.get("name")
    dna_seed = int(home.get("dna_seed") or 0)
    assert 0 <= dna_seed <= MAX_SQLITE_SIGNED_INT

    uname = f"parity_{uuid.uuid4().hex[:10]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    assert user is not None
    assert user["id"]
    assert user["username"] == uname

    loaded = get_user_by_username(uname)
    assert loaded is not None
    assert verify_user(uname, "test-pass-123") is not None
    assert verify_user(uname, "wrong-password") is None

    player = load_player(int(user["id"]))
    assert player is not None
    assert player["name"] == uname
    hw = get_homeworld(int(user["id"]))
    assert hw is not None
    assert int(hw["player_id"]) == int(user["id"])
    assert int(hw["is_homeworld"]) == 1
    seed = int(hw.get("dna_seed") or 0)
    assert 0 <= seed <= MAX_SQLITE_SIGNED_INT

    ok2, err2, _ = create_user(uname, "other-pass-456")
    assert ok2 is False
    assert err2
    assert "vergeben" in str(err2).lower() or "already" in str(err2).lower() or "unique" in str(err2).lower()

    # Fresh argon2 hash still verifies (hash helper parity)
    h = hash_password("roundtrip-secret")
    assert verify_password(h, "roundtrip-secret")
    assert not verify_password(h, "nope")


def test_parity_a_auth_bootstrap_sqlite(sqlite_parity_db):
    _assert_auth_bootstrap_parity()


@requires_postgres
def test_parity_a_auth_bootstrap_postgres(pg_parity_db):
    _assert_auth_bootstrap_parity()


def _assert_economy_scope_parity() -> None:
    """Block B: resources + context planet stay server-owned and consistent."""
    import uuid

    from game.db import db
    from game.live_state import get_request_context_planet
    from game.models import create_user, get_homeworld, get_planets_by_player
    from game.resources import update_planet_resources

    uname = f"econ_{uuid.uuid4().hex[:10]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    home = get_homeworld(uid)
    assert home is not None
    pid = int(home["id"])

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

        ctx = get_request_context_planet(uid, conn=conn)
        assert int(ctx["id"]) == pid
        planets = get_planets_by_player(uid, conn=conn)
        assert any(int(p["id"]) == pid for p in planets)
    finally:
        conn.close()


def test_parity_b_economy_scope_sqlite(sqlite_parity_db):
    _assert_economy_scope_parity()


@requires_postgres
def test_parity_b_economy_scope_postgres(pg_parity_db):
    _assert_economy_scope_parity()
