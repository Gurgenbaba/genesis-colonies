"""GC-PG-HIGHSPEED-001A — Galaxy list_system bulk + write-free debris."""

from __future__ import annotations

import time

from game.combat import DEBRIS_FIELD_TTL_SECONDS, add_debris_field
from game.db import db
from game.galaxy import get_debris_for_system, list_system
from game.models import get_planets_by_player

pytest_plugins = ["tests.test_galaxy"]


def _player_planet_coords(galaxy_db):
    from tests.test_galaxy import _create_player

    uid = _create_player()
    planet = get_planets_by_player(uid)[0]
    from game.galaxy import get_planet_coordinates

    return uid, get_planet_coordinates(planet)


def test_get_debris_for_system_filters_expired_without_delete(galaxy_db):
    uid, coords = _player_planet_coords(galaxy_db)
    g, s, p = coords["galaxy"], coords["system"], coords["position"]
    conn = db()
    try:
        add_debris_field(g, s, p, 100, 50, conn=conn)
        stale_at = int(time.time() - DEBRIS_FIELD_TTL_SECONDS - 120)
        conn.execute(
            "UPDATE debris_fields SET updated_at = ? WHERE galaxy = ? AND system = ? AND position = ?;",
            (stale_at, g, s, p),
        )
        conn.commit()
        before = conn.execute(
            "SELECT COUNT(*) AS c FROM debris_fields WHERE galaxy = ? AND system = ?;",
            (g, s),
        ).fetchone()["c"]
        assert before >= 1
        debris = get_debris_for_system(g, s, conn)
        assert p not in debris
        after = conn.execute(
            "SELECT COUNT(*) AS c FROM debris_fields WHERE galaxy = ? AND system = ?;",
            (g, s),
        ).fetchone()["c"]
        assert after == before
    finally:
        conn.close()


def test_list_system_hides_expired_debris_without_read_delete(galaxy_db):
    uid, coords = _player_planet_coords(galaxy_db)
    g, s, p = coords["galaxy"], coords["system"], coords["position"]
    conn = db()
    try:
        add_debris_field(g, s, p, 200, 100, conn=conn)
        stale_at = int(time.time() - DEBRIS_FIELD_TTL_SECONDS - 60)
        conn.execute(
            "UPDATE debris_fields SET updated_at = ? WHERE galaxy = ? AND system = ? AND position = ?;",
            (stale_at, g, s, p),
        )
        conn.commit()
        data = list_system(g, s, conn=conn, viewer_player_id=uid)
        slot = next(row for row in data["slots"] if row["position"] == p)
        assert slot["has_debris"] is False
        remaining = conn.execute(
            "SELECT COUNT(*) AS c FROM debris_fields WHERE galaxy = ? AND system = ?;",
            (g, s),
        ).fetchone()["c"]
        assert remaining >= 1
    finally:
        conn.close()


def test_get_debris_for_system_does_not_call_expire():
    import ast
    import inspect

    from game.galaxy import get_debris_for_system

    tree = ast.parse(inspect.getsource(get_debris_for_system))
    names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
    }
    assert "expire_due_debris_fields" not in names
    src = inspect.getsource(get_debris_for_system)
    assert "updated_at >" in src


def test_list_system_structural_gates(galaxy_db, monkeypatch):
    """001A master gates: SQL <100, opens<=3, writes=0, no per-player N+1 patterns."""
    import game.galaxy as galaxy_mod

    uid, coords = _player_planet_coords(galaxy_db)
    g, s = int(coords["galaxy"]), int(coords["system"])

    opens = {"n": 0}
    real_db = galaxy_mod.db

    def counting_db(*args, **kwargs):
        opens["n"] += 1
        return real_db(*args, **kwargs)

    monkeypatch.setattr(galaxy_mod, "db", counting_db)

    statements: list[str] = []
    conn = real_db()

    def trace(sql: str) -> None:
        statements.append(sql)

    conn.set_trace_callback(trace)
    try:
        data = list_system(g, s, conn=conn, viewer_player_id=uid)
        assert len(data["slots"]) == 15
    finally:
        conn.set_trace_callback(None)
        conn.close()

    writes = [
        stmt
        for stmt in statements
        if stmt.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE", "REPLACE"))
    ]
    assert len(writes) == 0, writes[:5]
    assert len(statements) < 100, f"sql_count={len(statements)}"
    assert opens["n"] <= 3, f"opens={opens['n']}"

    # No per-player last_seen / pairwise alliance probes in the slot loop.
    last_seen_single = [
        stmt
        for stmt in statements
        if "last_seen" in stmt.lower()
        and "from players" in stmt.lower()
        and " in (" not in stmt.lower()
    ]
    assert last_seen_single == [], last_seen_single
    alliance_pair = [
        stmt
        for stmt in statements
        if "alliance_members am1" in stmt.lower() and "am2.player_id = ?" in stmt.lower()
    ]
    assert alliance_pair == [], alliance_pair


def test_add_debris_does_not_revive_expired_amounts(galaxy_db):
    uid, coords = _player_planet_coords(galaxy_db)
    g, s, p = coords["galaxy"], coords["system"], coords["position"]
    conn = db()
    try:
        add_debris_field(g, s, p, 1000, 500, conn=conn)
        stale_at = int(time.time() - DEBRIS_FIELD_TTL_SECONDS - 60)
        conn.execute(
            "UPDATE debris_fields SET updated_at = ? WHERE galaxy = ? AND system = ? AND position = ?;",
            (stale_at, g, s, p),
        )
        conn.commit()
        totals = add_debris_field(g, s, p, 10, 5, conn=conn)
        assert totals["metal"] == 10
        assert totals["crystal"] == 5
    finally:
        conn.close()
