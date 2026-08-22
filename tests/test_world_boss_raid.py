"""GC-WB-RAID-002 focused raid pacing tests."""
from __future__ import annotations

import sqlite3

from game.world_boss import (
    RAID_MULTI_ACTION_CAP_FRACTION,
    RAID_RESONANCE_THRESHOLD,
    RAID_SINGLE_ACTION_CAP_FRACTION,
    _advance_world_boss_raid_after_hit,
    _apply_raid_containment,
    _apply_raid_damage_rules,
    get_world_boss_raid_state,
    scale_instant_hit_damage,
)


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE world_boss_events (
            id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            resonance_points INTEGER NOT NULL DEFAULT 0,
            resonance_ends_at REAL,
            resonance_initiator_player_id INTEGER,
            finisher_player_id INTEGER,
            updated_at REAL
        );
        CREATE TABLE world_boss_contributions (
            event_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            damage INTEGER NOT NULL DEFAULT 0,
            waves INTEGER NOT NULL DEFAULT 0,
            target_lock INTEGER NOT NULL DEFAULT 0,
            updated_at REAL,
            PRIMARY KEY(event_id, player_id)
        );
        INSERT INTO world_boss_events(id,status,resonance_points,updated_at)
        VALUES (1,'active',0,0);
        INSERT INTO world_boss_contributions(event_id,player_id,damage,waves,target_lock,updated_at)
        VALUES (1,7,0,0,0,0);
        """
    )
    return conn


def _event(now=1000.0):
    return {
        "id": 1,
        "status": "active",
        "max_hp": 1_000_000,
        "current_hp": 1_000_000,
        "starts_at": now,
        "ends_at": now + 48 * 3600,
    }


def test_opening_containment_piecewise():
    hp = 1_000_000
    assert _apply_raid_containment(50_000, 0, hp) == 50_000
    # Crossing 5%: first 10k is full, remaining 30k only 25% effective.
    assert _apply_raid_containment(40_000, 40_000, hp) == 17_500
    # Above 10% contribution only 5% effective.
    assert _apply_raid_containment(100_000, 100_000, hp) == 5_000


def test_strict_action_caps_even_with_large_raw_damage():
    conn = _conn()
    try:
        event = _event()
        # After containment window so only strict cap is relevant.
        one, meta1, _ = _apply_raid_damage_rules(
            999_999_999, hit_mult=1, event=event, player_id=7, conn=conn, now=event["starts_at"] + 3 * 3600
        )
        five, meta5, _ = _apply_raid_damage_rules(
            999_999_999, hit_mult=5, event=event, player_id=7, conn=conn, now=event["starts_at"] + 3 * 3600
        )
        assert one <= int(event["max_hp"] * RAID_SINGLE_ACTION_CAP_FRACTION)
        assert five <= int(event["max_hp"] * RAID_MULTI_ACTION_CAP_FRACTION)
        assert meta1["action_cap_fraction"] == RAID_SINGLE_ACTION_CAP_FRACTION
        assert meta5["action_cap_fraction"] == RAID_MULTI_ACTION_CAP_FRACTION
    finally:
        conn.close()


def test_x5_scaler_is_never_above_12_5_percent():
    class Rng:
        def random(self):
            return 1.0

    hp = 1_000_000
    out = scale_instant_hit_damage(500_000, hit_mult=5, max_hp=hp, rng=Rng())
    assert out <= int(hp * RAID_MULTI_ACTION_CAP_FRACTION)


def test_resonance_activates_and_target_lock_charges():
    conn = _conn()
    try:
        event = _event()
        conn.execute(
            "UPDATE world_boss_events SET resonance_points = ? WHERE id = 1",
            (RAID_RESONANCE_THRESHOLD - 1,),
        )
        state_before = get_world_boss_raid_state(event, 7, conn=conn, now=event["starts_at"] + 3 * 3600)
        state_after = _advance_world_boss_raid_after_hit(
            event=event,
            player_id=7,
            hit_mult=1,
            target_lock_before=0,
            target_lock_consumed=False,
            defeated=False,
            conn=conn,
            now=event["starts_at"] + 3 * 3600,
            state_before=state_before,
        )
        assert state_after["resonance"]["active"] is True
        assert state_after["resonance"]["initiator_player_id"] == 7
        assert state_after["target_lock"]["charge"] == 20
    finally:
        conn.close()


def test_last_stand_is_derived_from_event_lifetime():
    conn = _conn()
    try:
        event = _event()
        at = event["starts_at"] + (event["ends_at"] - event["starts_at"]) * 0.75 + 1
        state = get_world_boss_raid_state(event, 7, conn=conn, now=at)
        assert state["last_stand"]["active"] is True
        assert state["containment"]["active"] is False
    finally:
        conn.close()
