from __future__ import annotations

import sqlite3
from pathlib import Path

from game.alliance_war import (
    get_active_war_stats_for_alliance_pair,
    record_war_combat_report,
)
from game.scoring import compute_destroyed_raw_from_losses


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE alliances (
            id INTEGER PRIMARY KEY,
            tag TEXT NOT NULL,
            name TEXT NOT NULL
        );
        CREATE TABLE alliance_members (
            alliance_id INTEGER NOT NULL,
            player_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            PRIMARY KEY (alliance_id, player_id)
        );
        CREATE TABLE alliance_diplomacy (
            alliance_id_low INTEGER NOT NULL,
            alliance_id_high INTEGER NOT NULL,
            relation TEXT NOT NULL,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (alliance_id_low, alliance_id_high)
        );
        CREATE TABLE alliance_war_stats (
            alliance_id_low INTEGER NOT NULL,
            alliance_id_high INTEGER NOT NULL,
            war_started_at INTEGER NOT NULL,
            low_score_raw TEXT NOT NULL DEFAULT '0',
            high_score_raw TEXT NOT NULL DEFAULT '0',
            low_units_destroyed TEXT NOT NULL DEFAULT '0',
            high_units_destroyed TEXT NOT NULL DEFAULT '0',
            low_wins INTEGER NOT NULL DEFAULT 0,
            high_wins INTEGER NOT NULL DEFAULT 0,
            draws INTEGER NOT NULL DEFAULT 0,
            battle_count INTEGER NOT NULL DEFAULT 0,
            last_battle_at INTEGER,
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (alliance_id_low, alliance_id_high)
        );
        CREATE TABLE alliance_war_events (
            fleet_id INTEGER PRIMARY KEY,
            alliance_id_low INTEGER NOT NULL,
            alliance_id_high INTEGER NOT NULL,
            war_started_at INTEGER NOT NULL,
            attacker_alliance_id INTEGER NOT NULL,
            defender_alliance_id INTEGER NOT NULL,
            attacker_score_raw TEXT NOT NULL DEFAULT '0',
            defender_score_raw TEXT NOT NULL DEFAULT '0',
            attacker_units_destroyed TEXT NOT NULL DEFAULT '0',
            defender_units_destroyed TEXT NOT NULL DEFAULT '0',
            result TEXT NOT NULL,
            created_at INTEGER NOT NULL
        );
        INSERT INTO alliances(id, tag, name) VALUES
            (10, 'RED', 'Red Fleet'),
            (20, 'BLU', 'Blue Guard');
        INSERT INTO alliance_members(alliance_id, player_id, role) VALUES
            (10, 1, 'leader'),
            (20, 2, 'leader');
        INSERT INTO alliance_diplomacy(alliance_id_low, alliance_id_high, relation, updated_at)
            VALUES (10, 20, 'war', 1000);
        """
    )
    return conn


def _record(conn: sqlite3.Connection, fleet_id: int, *, qty: int = 5):
    return record_war_combat_report(
        attacker_player_id=1,
        defender_player_id=2,
        attacker_losses={"sentinel_turret": 2},
        defender_losses={"sentinel_turret": qty},
        result="attacker",
        fleet_id=fleet_id,
        conn=conn,
    )


def test_war_combat_records_canonical_score_and_stats() -> None:
    conn = _conn()
    meta = _record(conn, 9001)
    assert meta and meta["active"] is True
    expected = compute_destroyed_raw_from_losses({"sentinel_turret": 5})
    assert int(meta["attacker"]["score_raw"]) == expected
    assert int(meta["attacker"]["units_destroyed"]) == 5
    assert meta["attacker"]["wins"] == 1
    assert meta["battle_count"] == 1
    state = get_active_war_stats_for_alliance_pair(10, 20, conn=conn)
    assert state and int(state["self"]["score_raw"]) == expected


def test_same_fleet_id_is_idempotent() -> None:
    conn = _conn()
    first = _record(conn, 9001)
    second = _record(conn, 9001)
    assert first and second
    assert second["battle_count"] == 1
    assert second["attacker"]["score_raw"] == first["attacker"]["score_raw"]
    assert second["attacker"]["score_delta_raw"] == "0"
    assert conn.execute("SELECT COUNT(*) AS c FROM alliance_war_events").fetchone()["c"] == 1


def test_peace_stops_stats_and_rewar_starts_fresh_campaign() -> None:
    conn = _conn()
    _record(conn, 9001)
    conn.execute(
        "UPDATE alliance_diplomacy SET relation = 'neutral', updated_at = 1500 "
        "WHERE alliance_id_low = 10 AND alliance_id_high = 20"
    )
    assert _record(conn, 9002) is None
    conn.execute(
        "UPDATE alliance_diplomacy SET relation = 'war', updated_at = 2000 "
        "WHERE alliance_id_low = 10 AND alliance_id_high = 20"
    )
    zero = get_active_war_stats_for_alliance_pair(10, 20, conn=conn)
    assert zero and zero["war_started_at"] == 2000
    assert zero["battle_count"] == 0
    fresh = _record(conn, 9003, qty=1)
    assert fresh and fresh["war_started_at"] == 2000
    assert fresh["battle_count"] == 1
    expected = compute_destroyed_raw_from_losses({"sentinel_turret": 1})
    assert int(fresh["attacker"]["score_raw"]) == expected


def test_big_war_score_is_not_limited_to_sqlite_int64() -> None:
    conn = _conn()
    qty = 10**20
    meta = _record(conn, 9900, qty=qty)
    assert meta
    expected = compute_destroyed_raw_from_losses({"sentinel_turret": qty})
    assert expected > 2**63
    assert int(meta["attacker"]["score_raw"]) == expected
    stored = conn.execute(
        "SELECT low_score_raw FROM alliance_war_stats WHERE alliance_id_low = 10 AND alliance_id_high = 20"
    ).fetchone()["low_score_raw"]
    assert isinstance(stored, str)
    assert int(stored) == expected


def test_missing_fleet_id_never_mutates_stats() -> None:
    conn = _conn()
    meta = record_war_combat_report(
        attacker_player_id=1,
        defender_player_id=2,
        attacker_losses={},
        defender_losses={"sentinel_turret": 5},
        result="attacker",
        fleet_id=None,
        conn=conn,
    )
    assert meta and meta["battle_count"] == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM alliance_war_events").fetchone()["c"] == 0


def test_combat_report_dispatch_and_renderer_are_war_aware() -> None:
    messages_py = Path("game/messages.py").read_text(encoding="utf-8")
    messages_js = Path("static/js/messages.js").read_text(encoding="utf-8")
    assert "record_war_combat_report" in messages_py
    assert 'raw_meta["alliance_war"] = war_meta' in messages_py
    assert "renderAllianceWarPanel" in messages_js
    assert 't("alliance_relation_war", "War")' in messages_js


def test_postgres_path_serializes_war_aggregate_updates() -> None:
    source = Path("game/alliance_war.py").read_text(encoding="utf-8")
    assert 'get_db_backend() == "postgres"' in source
    assert 'FOR UPDATE' in source
    assert 'ON CONFLICT(alliance_id_low, alliance_id_high) DO NOTHING' in source
