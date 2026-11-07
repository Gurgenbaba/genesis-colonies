"""P0: XP must not turn an unestablished level-0 outpost into a legacy full colony.

Before the fix `add_planet_xp` read `planet_level or 1`, so the first XP grant on a level-0 outpost
(colonize XP of 300, or one 3-XP building finish) wrote level >= 1. `is_legacy_full_colony()` then
returned True, the outpost-only mechanics flags dropped and the next planet load revealed
`dna_reveal_tier = 1` before the establishment milestones (docs/EXPANSION_PROTOCOL.md).

Contract after the fix: XP is kept but the level is held at 0 until the outpost is established;
existing saves (any stored level >= 1) behave exactly as before; DNA is never re-rolled.
"""

from __future__ import annotations

import json
import uuid

import pytest

from game.activity_xp import SOURCE_COLONIZE, grant_activity_xp, grant_fleet_activity_xp
from game.db import db
from game.models import create_user, ensure_player_and_homeworld, get_homeworld, init_db
from game.planet_evolution.bootstrap import ensure_planet_evolution
from game.planet_evolution.expansion_phase import is_establishment_complete
from game.planet_evolution.expansion_protocol import (
    INTERSTELLAR_EXPANSION_TECH,
    bootstrap_legacy_establishment,
    is_legacy_full_colony,
    is_outpost_planet,
    sync_establishment_state,
)
from game.planet_evolution.planet_level import add_planet_xp, xp_threshold_for_level
from game.planet_evolution.repository import get_planet_dna
from game.planet_evolution.service import colonize_planet
from game.planet_evolution.strategic_worlds import strategic_world_type_for_coords
from game.planet_evolution.world_colonization import (
    build_world_key,
    is_colonizable_world_type,
    parse_world_key,
    sector_coords,
)


@pytest.fixture
def outpost_db(tmp_path, monkeypatch):
    db_path = tmp_path / "outpost_xp_hold.db"
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


def _binding() -> dict:
    for wx in range(700, 5000, 40):
        for wy in range(700, 5000, 40):
            wt = strategic_world_type_for_coords(float(wx), float(wy))
            if is_colonizable_world_type(wt):
                key = build_world_key(float(wx), float(wy), world_type=wt)
                sx, sy = sector_coords(float(wx), float(wy))
                return {
                    "world_key": key,
                    "world_x": float(wx),
                    "world_y": float(wy),
                    "sector_x": int(sx),
                    "sector_y": int(sy),
                    "planet_role": parse_world_key(key)["planet_role"],
                    "origin_world_key": key,
                }
    raise AssertionError("no colonizable coordinates")


def _outpost(conn) -> tuple[int, int]:
    ok, err, user = create_user(f"outxp_{uuid.uuid4().hex[:8]}", "test-pass-123")
    assert ok, err
    uid = int(user["id"])
    ensure_player_and_homeworld(uid, player_name="OutpostXp", conn=conn)
    hw = get_homeworld(uid, conn=conn)
    conn.execute("UPDATE planets SET planet_level = 5 WHERE id = ?;", (int(hw["id"]),))
    conn.execute(
        "INSERT INTO research_levels (user_id, tech_key, level) VALUES (?, ?, 1) "
        "ON CONFLICT(user_id, tech_key) DO UPDATE SET level = 1;",
        (uid, INTERSTELLAR_EXPANSION_TECH),
    )
    conn.commit()
    ok, reason, extra = colonize_planet(uid, name="Frontier", galaxy=1, system=300, position=1, world_binding=_binding(), conn=conn)
    assert ok, reason
    return uid, int(extra["planet_id"])


def _row(conn, pid: int) -> dict:
    return dict(conn.execute("SELECT planet_level, planet_xp, dna_reveal_tier, dna_seed FROM planets WHERE id = ?;", (pid,)).fetchone())


def _dna_blob(conn, pid: int) -> str:
    return json.dumps(get_planet_dna(pid, conn=conn), sort_keys=True, default=str)


def _finish_milestones(conn, pid: int) -> None:
    conn.execute("UPDATE planet_buildings SET command_center = 3, solar_plant = 1, radar_array = 1 WHERE planet_id = ?;", (pid,))
    conn.commit()


def test_xp_is_held_at_level_zero_and_dna_stays_hidden(outpost_db):
    conn = db()
    try:
        uid, pid = _outpost(conn)
        before = _row(conn, pid)
        dna_before = _dna_blob(conn, pid)
        assert (before["planet_level"], before["planet_xp"], before["dna_reveal_tier"]) == (0, 0, 0)

        first = grant_activity_xp(uid, pid, "building_finish", conn=conn, idempotency_key="hold:b1", now=1_000_000.0)
        assert first["granted"] and first["amount"] == 3
        assert first["planet_xp"]["held_until_established"] is True
        colonize = grant_fleet_activity_xp(uid, pid, SOURCE_COLONIZE, 4242, conn=conn, now=1_000_100.0)
        assert colonize["granted"] and colonize["amount"] == 300
        conn.commit()
        ensure_planet_evolution(pid, conn)  # the player opens the new world
        conn.commit()

        after = _row(conn, pid)
        assert after["planet_level"] == 0, "XP must not lift an unestablished outpost"
        assert after["planet_xp"] == 303, "XP is kept, only the level is held"
        assert after["dna_reveal_tier"] == 0, "DNA stays hidden until establishment"
        assert is_outpost_planet(pid, conn=conn)
        assert not is_legacy_full_colony(pid, conn=conn)
        assert not is_establishment_complete(pid, conn=conn)
        assert after["dna_seed"] == before["dna_seed"] and _dna_blob(conn, pid) == dna_before, "no DNA re-roll"
    finally:
        conn.close()


def test_establishment_replays_held_xp_once_and_reveals_dna(outpost_db):
    conn = db()
    try:
        uid, pid = _outpost(conn)
        grant_fleet_activity_xp(uid, pid, SOURCE_COLONIZE, 4243, conn=conn, now=2_000_000.0)
        conn.commit()
        dna_before = _dna_blob(conn, pid)

        _finish_milestones(conn, pid)
        assert sync_establishment_state(pid, conn=conn)
        conn.commit()

        row = _row(conn, pid)
        assert row["planet_xp"] == 300
        assert row["planet_level"] == 2, "300 held XP replay to level 2 (threshold %d)" % xp_threshold_for_level(2)
        assert row["dna_reveal_tier"] >= 1
        assert not is_outpost_planet(pid, conn=conn)
        assert is_establishment_complete(pid, conn=conn)
        assert _dna_blob(conn, pid) == dna_before

        # idempotent: a second sync neither double-counts XP nor changes the level
        sync_establishment_state(pid, conn=conn)
        conn.commit()
        assert _row(conn, pid)["planet_xp"] == 300 and _row(conn, pid)["planet_level"] == 2
    finally:
        conn.close()


def test_existing_saves_at_level_one_or_more_keep_legacy_behaviour(outpost_db):
    conn = db()
    try:
        uid, pid = _outpost(conn)
        # a colony saved before the fix: the first XP had already written level 1 / 2
        conn.execute("UPDATE planets SET planet_level = 1, planet_xp = 3 WHERE id = ?;", (pid,))
        conn.commit()
        assert is_legacy_full_colony(pid, conn=conn)
        assert not is_outpost_planet(pid, conn=conn)

        assert bootstrap_legacy_establishment(pid, conn=conn)  # unchanged legacy promotion
        assert _row(conn, pid)["dna_reveal_tier"] == 1

        res = add_planet_xp(pid, 300, conn, skip_diversity=True)
        conn.commit()
        assert "held_until_established" not in res
        assert res["planet_level"] == 2 and _row(conn, pid)["planet_xp"] == 303
    finally:
        conn.close()


def test_homeworld_and_established_colonies_level_as_before(outpost_db):
    conn = db()
    try:
        uid, pid = _outpost(conn)
        hw = get_homeworld(uid, conn=conn)
        conn.execute("UPDATE planets SET planet_level = 1, planet_xp = 0 WHERE id = ?;", (int(hw["id"]),))
        conn.commit()
        res = add_planet_xp(int(hw["id"]), 300, conn, skip_diversity=True)
        assert res["planet_level"] == 2 and "held_until_established" not in res

        _finish_milestones(conn, pid)
        sync_establishment_state(pid, conn=conn)
        conn.commit()
        assert _row(conn, pid)["planet_level"] >= 1
        res2 = add_planet_xp(pid, 600, conn, skip_diversity=True)
        assert "held_until_established" not in res2 and res2["levels_gained"] >= 1
    finally:
        conn.close()


def test_held_xp_keeps_directive_and_diversity_multipliers(outpost_db, monkeypatch):
    """Holding the level must not change how much XP a grant is worth (multipliers unchanged)."""
    import game.galactic_directives.mechanics as mech

    conn = db()
    try:
        uid, pid = _outpost(conn)

        monkeypatch.setattr(mech, "get_directive_flags_for_galaxy", lambda galaxy, conn=None: {"planet_xp_mult": 2.0})
        res = add_planet_xp(pid, 100, conn, skip_diversity=True)
        assert res["held_until_established"] and res["xp_gained"] == 200, "directive multiplier applies to held XP"
        assert _row(conn, pid)["planet_xp"] == 200 and _row(conn, pid)["planet_level"] == 0

        # a cap at level 1 means "no bonus from level 1 on": the pre-fix reading of a level-0 row was level 1
        monkeypatch.setattr(
            mech,
            "get_directive_flags_for_galaxy",
            lambda galaxy, conn=None: {"planet_xp_mult": 2.0, "planet_xp_mult_cap_level": 1},
        )
        res = add_planet_xp(pid, 100, conn, skip_diversity=True)
        assert res["xp_gained"] == 100
        assert _row(conn, pid)["planet_xp"] == 300 and _row(conn, pid)["planet_level"] == 0

        # replaying on establishment adds no extra XP and no multiplier on top
        monkeypatch.setattr(mech, "get_directive_flags_for_galaxy", lambda galaxy, conn=None: {"planet_xp_mult": 2.0})
        _finish_milestones(conn, pid)
        assert sync_establishment_state(pid, conn=conn)
        conn.commit()
        row = _row(conn, pid)
        assert row["planet_xp"] == 300 and row["planet_level"] == 2
    finally:
        conn.close()
