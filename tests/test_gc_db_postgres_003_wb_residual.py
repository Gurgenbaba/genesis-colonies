"""
GC-DB-POSTGRES-003-WB-RESIDUAL — World Boss PG AmbiguousColumn + CASE boolean.

Covers contribution UPSERT qualification and raid-state CASE WHEN ? = 1
for resonance_initiator_player_id / finisher_player_id.

Live PG: set GC_TEST_POSTGRES_URL (or postgresql DATABASE_URL).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests.pg_fixtures import close_pg_pool, requires_postgres

WB_SOURCE = ROOT / "game" / "world_boss.py"


def test_wb_residual_source_guards():
    source = WB_SOURCE.read_text(encoding="utf-8")
    assert "COALESCE(excluded.alliance_id, alliance_id)" not in source
    assert "COALESCE(\n                excluded.alliance_id,\n                world_boss_contributions.alliance_id\n            )" in source or (
        "COALESCE(excluded.alliance_id, world_boss_contributions.alliance_id)" in source
    )
    assert "WHEN ? = 1 THEN ? ELSE resonance_initiator_player_id END" in source
    assert "WHEN ? = 1 THEN ? ELSE finisher_player_id END" in source
    assert "WHEN ? THEN ? ELSE resonance_initiator_player_id END" not in source
    assert "WHEN ? THEN ? ELSE finisher_player_id END" not in source


def _seed_player(prefix: str) -> int:
    from game.models import create_user

    ok, reason, user = create_user(
        f"{prefix}_{int(time.time() * 1000) % 1_000_000}",
        "WbResid!xx99",
    )
    assert ok and user, reason
    return int(user["id"])


def _seed_event(conn, *, resonance_points: int = 0) -> int:
    now = time.time()
    # Prefer an existing catalog boss_key when definitions are loaded.
    row = conn.execute(
        "SELECT boss_key FROM world_boss_definitions WHERE active = 1 ORDER BY sort_order LIMIT 1;"
    ).fetchone()
    boss_key = str(row["boss_key"] if isinstance(row, dict) else row[0]) if row else "probe_boss"
    if not row:
        conn.execute(
            """
            INSERT INTO world_boss_definitions (
                boss_key, name_key, description_key, max_hp, duration_seconds,
                fleet_stacks_json, phases_json, loot_pool_key, spawn_weight, sort_order, active
            ) VALUES (?, 'n', 'd', 1000000, 172800, '{}', '[]', 'container_event_special', 1, 0, 1);
            """,
            (boss_key,),
        )
    conn.execute(
        """
        INSERT INTO world_boss_events (
            boss_key, status, galaxy, system, position,
            max_hp, current_hp, phase_index, fleet_stacks_json,
            starts_at, ends_at, created_at, updated_at,
            resonance_points, resonance_ends_at,
            resonance_initiator_player_id, finisher_player_id
        ) VALUES (
            ?, 'active', 1, 1, 8,
            1000000, 1000000, 0, '{}',
            ?, ?, ?, ?,
            ?, NULL, NULL, NULL
        );
        """,
        (boss_key, now, now + 172800, now, now, int(resonance_points)),
    )
    conn.commit()
    eid_row = conn.execute(
        "SELECT id FROM world_boss_events WHERE boss_key = ? ORDER BY id DESC LIMIT 1;",
        (boss_key,),
    ).fetchone()
    return int(eid_row["id"] if isinstance(eid_row, dict) else eid_row[0])


def _cleanup_event(conn, event_id: int) -> None:
    conn.execute("DELETE FROM world_boss_contributions WHERE event_id = ?;", (event_id,))
    conn.execute("DELETE FROM world_boss_events WHERE id = ?;", (event_id,))
    conn.commit()


@requires_postgres
def test_contribution_insert_and_conflict_alliance_postgres(pg_parity_db):
    from game.db import db
    from game.world_boss import _upsert_contribution, note_attack_dispatched

    conn = db()
    eid = None
    try:
        pid = _seed_player("wbc")
        eid = _seed_event(conn)
        now = time.time()

        # INSERT path
        _upsert_contribution(
            event_id=eid,
            player_id=pid,
            alliance_id=11,
            damage=10,
            now=now,
            conn=conn,
            alliance_xp=0,
            wave_delta=1,
        )
        conn.commit()
        row = conn.execute(
            "SELECT alliance_id, damage FROM world_boss_contributions WHERE event_id = ? AND player_id = ?;",
            (eid, pid),
        ).fetchone()
        assert int(row["alliance_id"]) == 11
        assert int(row["damage"]) == 10

        # CONFLICT keep existing alliance when excluded is NULL
        _upsert_contribution(
            event_id=eid,
            player_id=pid,
            alliance_id=None,
            damage=5,
            now=now + 1,
            conn=conn,
            alliance_xp=0,
            wave_delta=1,
        )
        conn.commit()
        row = conn.execute(
            "SELECT alliance_id, damage FROM world_boss_contributions WHERE event_id = ? AND player_id = ?;",
            (eid, pid),
        ).fetchone()
        assert int(row["alliance_id"]) == 11
        assert int(row["damage"]) == 15

        # CONFLICT replace with new alliance
        _upsert_contribution(
            event_id=eid,
            player_id=pid,
            alliance_id=22,
            damage=1,
            now=now + 2,
            conn=conn,
            alliance_xp=0,
            wave_delta=1,
        )
        conn.commit()
        row = conn.execute(
            "SELECT alliance_id FROM world_boss_contributions WHERE event_id = ? AND player_id = ?;",
            (eid, pid),
        ).fetchone()
        assert int(row["alliance_id"]) == 22

        # note_attack_dispatched conflict (AmbiguousColumn regression from Run 2)
        note_attack_dispatched(pid, eid, conn=conn, now=now + 3, alliance_id=33)
        conn.commit()
        row = conn.execute(
            "SELECT alliance_id, last_attack_at FROM world_boss_contributions WHERE event_id = ? AND player_id = ?;",
            (eid, pid),
        ).fetchone()
        assert int(row["alliance_id"]) == 33
        assert row["last_attack_at"] is not None
    finally:
        if eid is not None:
            try:
                _cleanup_event(conn, eid)
            except Exception:
                pass
        conn.close()
        close_pg_pool()


@requires_postgres
def test_raid_case_ordinary_resonance_defeat_postgres(pg_parity_db):
    from game.db import db
    from game.world_boss import (
        RAID_RESONANCE_THRESHOLD,
        _advance_world_boss_raid_after_hit,
        _upsert_contribution,
        get_world_boss_raid_state,
    )

    conn = db()
    eid = None
    try:
        pid = _seed_player("wbr")
        eid = _seed_event(conn, resonance_points=0)
        now = time.time()
        _upsert_contribution(
            event_id=eid,
            player_id=pid,
            alliance_id=None,
            damage=0,
            now=now,
            conn=conn,
            alliance_xp=0,
            wave_delta=1,
        )
        conn.commit()

        event = {
            "id": eid,
            "status": "active",
            "max_hp": 1_000_000,
            "current_hp": 1_000_000,
            "starts_at": now - 10_000,
            "ends_at": now + 100_000,
        }

        # Ordinary hit: no activation, no defeat — CASE predicates bind 0
        state0 = get_world_boss_raid_state(event, pid, conn=conn, now=now)
        after_ordinary = _advance_world_boss_raid_after_hit(
            event=event,
            player_id=pid,
            hit_mult=1,
            target_lock_before=0,
            target_lock_consumed=False,
            defeated=False,
            conn=conn,
            now=now,
            state_before=state0,
        )
        conn.commit()
        assert after_ordinary["resonance"]["active"] is False
        row = conn.execute(
            """
            SELECT resonance_initiator_player_id, finisher_player_id, resonance_points
            FROM world_boss_events WHERE id = ?;
            """,
            (eid,),
        ).fetchone()
        assert row["resonance_initiator_player_id"] is None
        assert row["finisher_player_id"] is None
        assert int(row["resonance_points"]) == 1

        # Resonance activation
        conn.execute(
            "UPDATE world_boss_events SET resonance_points = ? WHERE id = ?;",
            (RAID_RESONANCE_THRESHOLD - 1, eid),
        )
        conn.commit()
        state1 = get_world_boss_raid_state(event, pid, conn=conn, now=now + 1)
        after_res = _advance_world_boss_raid_after_hit(
            event=event,
            player_id=pid,
            hit_mult=1,
            target_lock_before=0,
            target_lock_consumed=False,
            defeated=False,
            conn=conn,
            now=now + 1,
            state_before=state1,
        )
        conn.commit()
        assert after_res["resonance"]["active"] is True
        assert after_res["resonance"]["initiator_player_id"] == pid
        row = conn.execute(
            "SELECT resonance_initiator_player_id, finisher_player_id FROM world_boss_events WHERE id = ?;",
            (eid,),
        ).fetchone()
        assert int(row["resonance_initiator_player_id"]) == pid
        assert row["finisher_player_id"] is None

        # Boss defeat sets finisher via CASE WHEN ? = 1
        state2 = get_world_boss_raid_state(event, pid, conn=conn, now=now + 2)
        after_def = _advance_world_boss_raid_after_hit(
            event=event,
            player_id=pid,
            hit_mult=1,
            target_lock_before=0,
            target_lock_consumed=False,
            defeated=True,
            conn=conn,
            now=now + 2,
            state_before=state2,
        )
        conn.commit()
        row = conn.execute(
            "SELECT finisher_player_id FROM world_boss_events WHERE id = ?;",
            (eid,),
        ).fetchone()
        assert int(row["finisher_player_id"]) == pid
        assert after_def is not None
    finally:
        if eid is not None:
            try:
                _cleanup_event(conn, eid)
            except Exception:
                pass
        conn.close()
        close_pg_pool()


@requires_postgres
def test_maintenance_bag_ok_after_wb_residual(pg_parity_db):
    from game.internal_cron import run_maintenance_bag

    payload = run_maintenance_bag(force=True, source="maintenance_worker")
    assert payload.get("ok") is True, payload
    blob = str(payload)
    assert "AmbiguousColumn" not in blob
    assert "DatatypeMismatch" not in blob
    close_pg_pool()
