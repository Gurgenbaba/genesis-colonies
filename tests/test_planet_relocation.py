"""Planet relocation (evacuation move) tests."""

from __future__ import annotations

import time
import uuid

import pytest

import game.db as dbmod
import game.models as models
from game.galaxy import (
    RELOCATION_COOLDOWN_SECONDS,
    RELOCATION_DURATION_SECONDS,
    assign_free_coordinates,
    coordinate_is_available,
    finish_due_relocations,
    get_planet_coordinates,
    get_relocation_client_state,
    start_planet_relocation,
)
from game.models import create_user, db, get_planets_by_player, init_db
from game.planet_evolution.repository import get_context_planet, set_active_planet_id


@pytest.fixture()
def reloc_db(tmp_path, monkeypatch):
    db_path = tmp_path / "planet_relocation_test.db"
    monkeypatch.setenv("GC_DB_PATH", str(db_path))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-not-default-value-32chars")
    dbmod._DB_PATH = None
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    monkeypatch.setattr(models, "DB_PATH", db_path)
    import migrate

    migrate.ensure_db_exists()
    migrate.main()
    yield
    dbmod._DB_PATH = None


def _create_player() -> int:
    uname = f"reloc_{uuid.uuid4().hex[:8]}"
    ok, err, user = create_user(uname, "test-pass-123")
    assert ok, err
    return int(user["id"])


def _other_free_slot(conn, planet) -> tuple[int, int, int]:
    origin = get_planet_coordinates(planet)
    cur = (int(origin["galaxy"]), int(origin["system"]), int(origin["position"]))
    g, s, p = assign_free_coordinates(conn)
    if (g, s, p) != cur:
        return g, s, p
    for pos in range(1, 16):
        if pos == cur[2]:
            continue
        if coordinate_is_available(conn, cur[0], cur[1], pos):
            return cur[0], cur[1], pos
    pytest.fail("no alternate free slot for relocation test")


def test_start_relocation_requires_free_slot(reloc_db):
    uid = _create_player()
    conn = db()
    try:
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        coords = get_planet_coordinates(planet)
        taken_g, taken_s, taken_p = coords["galaxy"], coords["system"], coords["position"]

        ok, err, _ = start_planet_relocation(uid, taken_g, taken_s, taken_p, conn=conn)
        assert not ok
        assert err == "planet_relocation_same_slot"

        target = _other_free_slot(conn, planet)
        ok, err, data = start_planet_relocation(uid, target[0], target[1], target[2], conn=conn)
        assert ok, err
        assert data.get("active") is True
        assert data.get("target") == f"[{target[0]}:{target[1]}:{target[2]}]"

        ok2, err2, _ = start_planet_relocation(uid, target[0], target[1], target[2], conn=conn)
        assert not ok2
        assert err2 == "planet_relocation_already_active"
    finally:
        conn.close()


def test_finish_relocation_moves_planet_and_sets_cooldown(reloc_db):
    uid = _create_player()
    conn = db()
    try:
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        target = _other_free_slot(conn, planet)

        ok, err, _ = start_planet_relocation(uid, target[0], target[1], target[2], conn=conn)
        assert ok, err

        now = time.time() + RELOCATION_DURATION_SECONDS + 1
        moved = finish_due_relocations(conn, player_id=uid, now=now)
        assert moved == 1

        conn.commit()
        cur = conn.cursor()
        cur.execute("SELECT galaxy, system, position, relocation_cooldown_until FROM planets WHERE id = ?;", (pid,))
        row = cur.fetchone()
        assert int(row["galaxy"]) == target[0]
        assert int(row["system"]) == target[1]
        assert int(row["position"]) == target[2]
        assert float(row["relocation_cooldown_until"] or 0) > now - 1

        state = get_relocation_client_state(pid, conn=conn, now=now)
        assert state.get("active") is False
        assert state.get("can_start") is False
        assert int(state.get("cooldown_remaining_seconds") or 0) > 0
    finally:
        conn.close()


def test_cooldown_blocks_second_relocation(reloc_db):
    uid = _create_player()
    conn = db()
    try:
        planet = get_context_planet(uid, conn=conn)
        pid = int(planet["id"])
        target1 = _other_free_slot(conn, planet)
        ok, err, _ = start_planet_relocation(uid, target1[0], target1[1], target1[2], conn=conn)
        assert ok, err

        cur = conn.cursor()
        cur.execute(
            "UPDATE planet_relocations SET finish_at = ? WHERE planet_id = ? AND status = 'active';",
            (time.time() - 1, pid),
        )
        conn.commit()
        moved = finish_due_relocations(conn, player_id=uid, now=time.time())
        assert moved == 1
        conn.commit()

        state = get_relocation_client_state(pid, conn=conn, now=time.time())
        assert state.get("can_start") is False

        cur.execute("SELECT galaxy, system, position FROM planets WHERE id = ?;", (pid,))
        row = cur.fetchone()
        current = (int(row["galaxy"]), int(row["system"]), int(row["position"]))
        assert current == target1

        target2 = _other_free_slot(conn, planet)
        assert target2 != current

        ok2, err2, _ = start_planet_relocation(uid, target2[0], target2[1], target2[2], conn=conn)
        assert not ok2
        assert err2 == "planet_relocation_cooldown"

        cur.execute(
            "UPDATE planets SET relocation_cooldown_until = ? WHERE id = ?;",
            (time.time() - 1, pid),
        )
        conn.commit()
        ok3, err3, _ = start_planet_relocation(uid, target2[0], target2[1], target2[2], conn=conn)
        assert ok3, err3
    finally:
        conn.close()


def test_finish_fails_when_target_taken(reloc_db):
    uid1 = _create_player()
    uid2 = _create_player()
    conn = db()
    try:
        p1 = get_context_planet(uid1, conn=conn)
        p2 = get_context_planet(uid2, conn=conn)
        target = _other_free_slot(conn, p1)

        ok, err, _ = start_planet_relocation(uid1, target[0], target[1], target[2], conn=conn)
        assert ok, err

        # Another player colonizes the target slot before finish
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE planets SET galaxy = ?, system = ?, position = ?
            WHERE id = ?;
            """,
            (target[0], target[1], target[2], int(p2["id"])),
        )
        conn.commit()

        moved = finish_due_relocations(
            conn, player_id=uid1, now=time.time() + RELOCATION_DURATION_SECONDS + 1
        )
        assert moved == 0

        cur.execute("SELECT galaxy, system, position FROM planets WHERE id = ?;", (int(p1["id"]),))
        row = cur.fetchone()
        c1 = get_planet_coordinates(dict(row))
        orig = get_planet_coordinates(p1)
        assert (c1["galaxy"], c1["system"], c1["position"]) == (
            orig["galaxy"],
            orig["system"],
            orig["position"],
        )
    finally:
        conn.close()


def test_relocation_activity_links_to_overview_route():
    from game.overview_page import build_activity_lines

    acts = build_activity_lines(
        {},
        {},
        planet_relocation={
            "active": True,
            "target": "[1:2:3]",
            "remaining_seconds": 100,
            "finish_at": 9999999999,
        },
    )
    reloc = [a for a in acts if a.get("key") == "relocation"]
    assert len(reloc) == 1
    assert reloc[0]["href_key"] == "overview"


def test_player_has_seed_ark_empire_wide(reloc_db):
    from game.fleet import add_planet_ships
    from game.galaxy import player_has_seed_ark

    uid = _create_player()
    conn = db()
    try:
        assert player_has_seed_ark(uid, conn=conn) is False
        planet = get_context_planet(uid, conn=conn)
        add_planet_ships(int(planet["id"]), uid, {"seed_ark": 1}, conn=conn)
        conn.commit()
        assert player_has_seed_ark(uid, conn=conn) is True
    finally:
        conn.close()
