"""Alliance war meta — derived combat statistics for active diplomacy wars (GC-AL-WAR-02).

The canonical war lifecycle remains in ``game.alliance`` / ``alliance_diplomacy``.
This module only records combat-derived metadata and deliberately reuses the
canonical combat destruction score helper from ``game.scoring``.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from .db import get_db_backend, table_exists
from .scoring import compute_destroyed_raw_from_losses


def _now() -> int:
    return int(time.time())


def war_meta_schema_ready(conn) -> bool:
    return table_exists(conn, "alliance_war_stats") and table_exists(
        conn, "alliance_war_events"
    )


def _pair(alliance_a: int, alliance_b: int) -> tuple[int, int]:
    a = int(alliance_a)
    b = int(alliance_b)
    return (a, b) if a < b else (b, a)


def _as_bigint(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _loss_count(losses: Mapping[str, int] | None) -> int:
    return sum(_as_bigint(qty) for qty in (losses or {}).values())


def _player_alliance(player_id: int, conn) -> dict[str, Any] | None:
    if not table_exists(conn, "alliance_members") or not table_exists(conn, "alliances"):
        return None
    row = conn.execute(
        """
        SELECT a.id AS alliance_id, a.name, a.tag
        FROM alliance_members am
        JOIN alliances a ON a.id = am.alliance_id
        WHERE am.player_id = ?
        LIMIT 1;
        """,
        (int(player_id),),
    ).fetchone()
    return dict(row) if row else None


def _active_war_relation(alliance_a: int, alliance_b: int, conn) -> dict[str, Any] | None:
    if not table_exists(conn, "alliance_diplomacy"):
        return None
    low, high = _pair(alliance_a, alliance_b)
    if low <= 0 or high <= 0 or low == high:
        return None
    row = conn.execute(
        """
        SELECT alliance_id_low, alliance_id_high, relation, updated_at
        FROM alliance_diplomacy
        WHERE alliance_id_low = ? AND alliance_id_high = ? AND relation = 'war'
        LIMIT 1;
        """,
        (low, high),
    ).fetchone()
    return dict(row) if row else None


def _zero_stats(low: int, high: int, war_started_at: int) -> dict[str, Any]:
    return {
        "alliance_id_low": int(low),
        "alliance_id_high": int(high),
        "war_started_at": int(war_started_at),
        "low_score_raw": "0",
        "high_score_raw": "0",
        "low_units_destroyed": "0",
        "high_units_destroyed": "0",
        "low_wins": 0,
        "high_wins": 0,
        "draws": 0,
        "battle_count": 0,
        "last_battle_at": None,
        "updated_at": int(war_started_at),
    }


def _load_campaign_stats(low: int, high: int, war_started_at: int, conn) -> dict[str, Any]:
    if not war_meta_schema_ready(conn):
        return _zero_stats(low, high, war_started_at)
    row = conn.execute(
        """
        SELECT * FROM alliance_war_stats
        WHERE alliance_id_low = ? AND alliance_id_high = ?
        LIMIT 1;
        """,
        (int(low), int(high)),
    ).fetchone()
    if not row or int(row["war_started_at"] or 0) != int(war_started_at):
        return _zero_stats(low, high, war_started_at)
    return dict(row)


def _select_campaign_stats_for_update(
    low: int,
    high: int,
    conn,
):
    """Lock one aggregate row while Python performs arbitrary-precision math."""
    lock = " FOR UPDATE" if get_db_backend() == "postgres" else ""
    return conn.execute(
        f"""
        SELECT * FROM alliance_war_stats
        WHERE alliance_id_low = ? AND alliance_id_high = ?
        LIMIT 1{lock};
        """,
        (int(low), int(high)),
    ).fetchone()


def _ensure_campaign_stats(low: int, high: int, war_started_at: int, conn) -> dict[str, Any]:
    """Atomically seed + lock the pair before reading/updating its aggregate.

    SQLite already serializes writers through the GC write transaction. PostgreSQL
    additionally takes a row lock so concurrent fleet workers cannot overwrite
    each other's arbitrary-precision TEXT totals.
    """
    now = _now()
    conn.execute(
        """
        INSERT INTO alliance_war_stats (
            alliance_id_low, alliance_id_high, war_started_at,
            low_score_raw, high_score_raw,
            low_units_destroyed, high_units_destroyed,
            low_wins, high_wins, draws, battle_count,
            last_battle_at, updated_at
        ) VALUES (?, ?, ?, '0', '0', '0', '0', 0, 0, 0, 0, NULL, ?)
        ON CONFLICT(alliance_id_low, alliance_id_high) DO NOTHING;
        """,
        (int(low), int(high), int(war_started_at), now),
    )
    row = _select_campaign_stats_for_update(low, high, conn)
    if not row:
        raise RuntimeError("alliance_war_stats_seed_failed")
    current = dict(row)
    if int(current.get("war_started_at") or 0) != int(war_started_at):
        conn.execute(
            """
            UPDATE alliance_war_stats
            SET war_started_at = ?,
                low_score_raw = '0', high_score_raw = '0',
                low_units_destroyed = '0', high_units_destroyed = '0',
                low_wins = 0, high_wins = 0, draws = 0, battle_count = 0,
                last_battle_at = NULL, updated_at = ?
            WHERE alliance_id_low = ? AND alliance_id_high = ?;
            """,
            (int(war_started_at), now, int(low), int(high)),
        )
        return _zero_stats(low, high, war_started_at)
    return current


def _side_payload(stats: Mapping[str, Any], alliance_id: int, low: int) -> dict[str, Any]:
    is_low = int(alliance_id) == int(low)
    prefix = "low" if is_low else "high"
    return {
        "alliance_id": int(alliance_id),
        "score_raw": str(_as_bigint(stats.get(f"{prefix}_score_raw"))),
        "units_destroyed": str(_as_bigint(stats.get(f"{prefix}_units_destroyed"))),
        "wins": _as_bigint(stats.get(f"{prefix}_wins")),
    }


def get_active_war_stats_for_alliance_pair(
    alliance_id: int,
    other_alliance_id: int,
    *,
    conn,
) -> dict[str, Any] | None:
    """Read-only current-war scoreboard oriented as self/other."""
    relation = _active_war_relation(alliance_id, other_alliance_id, conn)
    if not relation:
        return None
    low, high = _pair(alliance_id, other_alliance_id)
    started = int(relation.get("updated_at") or 0)
    stats = _load_campaign_stats(low, high, started, conn)
    own = _side_payload(stats, int(alliance_id), low)
    other = _side_payload(stats, int(other_alliance_id), low)
    return {
        "active": True,
        "war_started_at": started,
        "battle_count": _as_bigint(stats.get("battle_count")),
        "draws": _as_bigint(stats.get("draws")),
        "last_battle_at": int(stats.get("last_battle_at") or 0) or None,
        "self": own,
        "other": other,
        "lead": "self"
        if _as_bigint(own["score_raw"]) > _as_bigint(other["score_raw"])
        else "other"
        if _as_bigint(other["score_raw"]) > _as_bigint(own["score_raw"])
        else "draw",
    }


def _combat_context(
    *,
    stats: Mapping[str, Any],
    low: int,
    attacker: Mapping[str, Any],
    defender: Mapping[str, Any],
    attacker_delta: int,
    defender_delta: int,
    attacker_units_delta: int,
    defender_units_delta: int,
) -> dict[str, Any]:
    attacker_id = int(attacker["alliance_id"])
    defender_id = int(defender["alliance_id"])
    atk = _side_payload(stats, attacker_id, low)
    deff = _side_payload(stats, defender_id, low)
    atk.update(
        {
            "name": str(attacker.get("name") or ""),
            "tag": str(attacker.get("tag") or ""),
            "score_delta_raw": str(_as_bigint(attacker_delta)),
            "units_delta": str(_as_bigint(attacker_units_delta)),
        }
    )
    deff.update(
        {
            "name": str(defender.get("name") or ""),
            "tag": str(defender.get("tag") or ""),
            "score_delta_raw": str(_as_bigint(defender_delta)),
            "units_delta": str(_as_bigint(defender_units_delta)),
        }
    )
    atk_score = _as_bigint(atk["score_raw"])
    def_score = _as_bigint(deff["score_raw"])
    return {
        "active": True,
        "war_started_at": int(stats.get("war_started_at") or 0),
        "battle_count": _as_bigint(stats.get("battle_count")),
        "draws": _as_bigint(stats.get("draws")),
        "last_battle_at": int(stats.get("last_battle_at") or 0) or None,
        "attacker": atk,
        "defender": deff,
        "lead": "attacker" if atk_score > def_score else "defender" if def_score > atk_score else "draw",
    }


def record_war_combat_report(
    *,
    attacker_player_id: int,
    defender_player_id: int,
    attacker_losses: Mapping[str, int] | None,
    defender_losses: Mapping[str, int] | None,
    result: str,
    fleet_id: Any,
    conn,
) -> dict[str, Any] | None:
    """Record one PvP fleet battle against the currently active alliance war.

    ``fleet_id`` is the idempotency key. Missing ids produce read-only context
    and never mutate statistics. All score deltas come from the canonical
    combat destruction helper; this module owns no parallel scoring formula.
    """
    if not war_meta_schema_ready(conn):
        return None
    attacker = _player_alliance(int(attacker_player_id), conn)
    defender = _player_alliance(int(defender_player_id), conn)
    if not attacker or not defender:
        return None
    attacker_aid = int(attacker["alliance_id"])
    defender_aid = int(defender["alliance_id"])
    if attacker_aid == defender_aid:
        return None
    relation = _active_war_relation(attacker_aid, defender_aid, conn)
    if not relation:
        return None

    low, high = _pair(attacker_aid, defender_aid)
    war_started_at = int(relation.get("updated_at") or 0)
    attacker_delta = compute_destroyed_raw_from_losses(defender_losses or {})
    defender_delta = compute_destroyed_raw_from_losses(attacker_losses or {})
    attacker_units = _loss_count(defender_losses)
    defender_units = _loss_count(attacker_losses)

    try:
        fid = int(fleet_id)
    except (TypeError, ValueError):
        fid = 0
    if fid <= 0:
        stats = _load_campaign_stats(low, high, war_started_at, conn)
        return _combat_context(
            stats=stats,
            low=low,
            attacker=attacker,
            defender=defender,
            attacker_delta=0,
            defender_delta=0,
            attacker_units_delta=0,
            defender_units_delta=0,
        )

    savepoint = "gc_alliance_war_meta"
    conn.execute(f"SAVEPOINT {savepoint};")
    try:
        stats = _ensure_campaign_stats(low, high, war_started_at, conn)
        now = _now()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO alliance_war_events (
                fleet_id, alliance_id_low, alliance_id_high, war_started_at,
                attacker_alliance_id, defender_alliance_id,
                attacker_score_raw, defender_score_raw,
                attacker_units_destroyed, defender_units_destroyed,
                result, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fleet_id) DO NOTHING;
            """,
            (
                fid,
                low,
                high,
                war_started_at,
                attacker_aid,
                defender_aid,
                str(attacker_delta),
                str(defender_delta),
                str(attacker_units),
                str(defender_units),
                str(result or "undecided"),
                now,
            ),
        )
        inserted = int(cur.rowcount or 0) > 0
        if inserted:
            low_score = _as_bigint(stats.get("low_score_raw"))
            high_score = _as_bigint(stats.get("high_score_raw"))
            low_units = _as_bigint(stats.get("low_units_destroyed"))
            high_units = _as_bigint(stats.get("high_units_destroyed"))
            low_wins = _as_bigint(stats.get("low_wins"))
            high_wins = _as_bigint(stats.get("high_wins"))
            draws = _as_bigint(stats.get("draws"))
            battles = _as_bigint(stats.get("battle_count")) + 1

            if attacker_aid == low:
                low_score += attacker_delta
                low_units += attacker_units
                high_score += defender_delta
                high_units += defender_units
            else:
                high_score += attacker_delta
                high_units += attacker_units
                low_score += defender_delta
                low_units += defender_units

            outcome = str(result or "undecided").strip().lower()
            if outcome == "attacker":
                if attacker_aid == low:
                    low_wins += 1
                else:
                    high_wins += 1
            elif outcome == "defender":
                if defender_aid == low:
                    low_wins += 1
                else:
                    high_wins += 1
            elif outcome == "draw":
                draws += 1

            conn.execute(
                """
                UPDATE alliance_war_stats
                SET low_score_raw = ?, high_score_raw = ?,
                    low_units_destroyed = ?, high_units_destroyed = ?,
                    low_wins = ?, high_wins = ?, draws = ?, battle_count = ?,
                    last_battle_at = ?, updated_at = ?
                WHERE alliance_id_low = ? AND alliance_id_high = ?
                  AND war_started_at = ?;
                """,
                (
                    str(low_score),
                    str(high_score),
                    str(low_units),
                    str(high_units),
                    low_wins,
                    high_wins,
                    draws,
                    battles,
                    now,
                    now,
                    low,
                    high,
                    war_started_at,
                ),
            )
        stats = _load_campaign_stats(low, high, war_started_at, conn)
        conn.execute(f"RELEASE SAVEPOINT {savepoint};")
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint};")
        conn.execute(f"RELEASE SAVEPOINT {savepoint};")
        raise

    return _combat_context(
        stats=stats,
        low=low,
        attacker=attacker,
        defender=defender,
        attacker_delta=attacker_delta if inserted else 0,
        defender_delta=defender_delta if inserted else 0,
        attacker_units_delta=attacker_units if inserted else 0,
        defender_units_delta=defender_units if inserted else 0,
    )
