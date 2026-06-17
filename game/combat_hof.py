"""Combat Hall of Fame — persistent public top battles (GC-700A)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from .db import table_exists
from .number_format import fmt_int, fmt_int_compact
from .scoring import compute_destroyed_raw_from_losses

COMBAT_HOF_TABLE = "combat_hall_of_fame"
COMBAT_HOF_DISPLAY_LIMIT = 100
COMBAT_HOF_RETENTION_LIMIT = 250


def hof_schema_ready(conn) -> bool:
    return table_exists(conn, COMBAT_HOF_TABLE)


def combat_qualifies_for_hof(total_destroyed_score: int) -> bool:
    """Every completed attack combat is an automatic HoF candidate (no manual curation)."""
    _ = int(total_destroyed_score)
    return True


def _json_dumps(payload: Mapping[str, Any] | None) -> str:
    return json.dumps(dict(payload or {}), ensure_ascii=False, separators=(",", ":"))


def _json_loads(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw))
        return dict(parsed) if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _format_created_at(ts: int) -> str:
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return dt.strftime("%d.%m.%Y %H:%M UTC")
    except (TypeError, ValueError, OSError, OverflowError):
        return "—"


def prune_hof_entries_beyond_top(*, keep: int = COMBAT_HOF_RETENTION_LIMIT, conn) -> int:
    """
    Drop stored HoF candidates outside the retention window.

    Keeps the top ``keep`` rows by ``total_destroyed_score DESC, created_at DESC``.
    Display still uses ``list_top_battles(limit=100)`` — no manual admin curation.
    """
    if not hof_schema_ready(conn):
        return 0

    retain = max(COMBAT_HOF_DISPLAY_LIMIT, int(keep))
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) AS c FROM {COMBAT_HOF_TABLE};")
    total = int(cur.fetchone()["c"] or 0)
    if total <= retain:
        return 0

    cur.execute(
        f"""
        DELETE FROM {COMBAT_HOF_TABLE}
        WHERE id NOT IN (
            SELECT id
            FROM {COMBAT_HOF_TABLE}
            ORDER BY total_destroyed_score DESC, created_at DESC, id DESC
            LIMIT ?
        );
        """,
        (retain,),
    )
    return int(cur.rowcount or 0)


def record_hof_battle(
    *,
    fleet_id: int,
    attacker_player_id: int,
    defender_player_id: int,
    attacker_name: str,
    defender_name: str,
    target_planet_id: int | None,
    target_name: str,
    target_coords: str,
    winner: str,
    rounds: int,
    attacker_losses: Mapping[str, int],
    defender_losses: Mapping[str, int],
    loot: Mapping[str, int] | None = None,
    debris: Mapping[str, int] | None = None,
    report_metadata: Mapping[str, Any] | None = None,
    created_at: int | None = None,
    conn,
) -> bool:
    """
    Persist one automatic HoF candidate per attack fleet (``fleet_id`` UNIQUE).

    Server computes ``total_destroyed_score`` from combat losses; no player/admin input.
    Idempotent on tick retry via INSERT OR IGNORE.
    """
    if not hof_schema_ready(conn):
        return False

    atk_score = compute_destroyed_raw_from_losses(attacker_losses)
    def_score = compute_destroyed_raw_from_losses(defender_losses)
    total_score = int(atk_score) + int(def_score)

    now = int(created_at if created_at is not None else time.time())
    cur = conn.cursor()
    cur.execute(
        f"""
        INSERT OR IGNORE INTO {COMBAT_HOF_TABLE} (
            fleet_id,
            attacker_player_id,
            defender_player_id,
            attacker_name,
            defender_name,
            target_planet_id,
            target_name,
            target_coords,
            winner,
            rounds,
            attacker_loss_score,
            defender_loss_score,
            total_destroyed_score,
            loot_json,
            debris_json,
            report_metadata_json,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        (
            int(fleet_id),
            int(attacker_player_id),
            int(defender_player_id),
            str(attacker_name or ""),
            str(defender_name or ""),
            int(target_planet_id) if target_planet_id else None,
            str(target_name or ""),
            str(target_coords or ""),
            str(winner or ""),
            max(0, int(rounds)),
            int(atk_score),
            int(def_score),
            int(total_score),
            _json_dumps(loot),
            _json_dumps(debris),
            _json_dumps(report_metadata),
            now,
        ),
    )
    inserted = cur.rowcount > 0
    if inserted:
        prune_hof_entries_beyond_top(conn=conn)
    return inserted


def _row_to_battle(row: Any, *, rank: int) -> Dict[str, Any]:
    loot = _json_loads(row["loot_json"])
    debris = _json_loads(row["debris_json"])
    report_metadata = _json_loads(row["report_metadata_json"])
    total_score = int(row["total_destroyed_score"] or 0)
    created_ts = int(row["created_at"] or 0)
    return {
        "id": int(row["id"]),
        "rank": int(rank),
        "fleet_id": int(row["fleet_id"]),
        "attacker_player_id": int(row["attacker_player_id"] or 0),
        "defender_player_id": int(row["defender_player_id"] or 0),
        "attacker_name": str(row["attacker_name"] or ""),
        "defender_name": str(row["defender_name"] or ""),
        "target_planet_id": int(row["target_planet_id"]) if row["target_planet_id"] else None,
        "target_name": str(row["target_name"] or ""),
        "target_coords": str(row["target_coords"] or ""),
        "winner": str(row["winner"] or ""),
        "rounds": int(row["rounds"] or 0),
        "attacker_loss_score": int(row["attacker_loss_score"] or 0),
        "defender_loss_score": int(row["defender_loss_score"] or 0),
        "total_destroyed_score": total_score,
        "total_destroyed_score_fmt": fmt_int(total_score),
        "total_destroyed_score_compact": fmt_int_compact(total_score),
        "loot": loot,
        "debris": debris,
        "report_metadata": report_metadata,
        "created_at": created_ts,
        "created_at_fmt": _format_created_at(created_ts),
    }


def list_top_battles(*, limit: int = COMBAT_HOF_DISPLAY_LIMIT, conn) -> List[Dict[str, Any]]:
    """Return up to ``limit`` battles sorted by destroyed value (desc), then date (desc)."""
    if not hof_schema_ready(conn):
        return []

    lim = max(1, min(int(limit), COMBAT_HOF_DISPLAY_LIMIT))
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT *
        FROM {COMBAT_HOF_TABLE}
        ORDER BY total_destroyed_score DESC, created_at DESC, id DESC
        LIMIT ?;
        """,
        (lim,),
    )
    rows = cur.fetchall()
    return [_row_to_battle(row, rank=idx + 1) for idx, row in enumerate(rows)]


def build_hof_api_payload(*, limit: int = COMBAT_HOF_DISPLAY_LIMIT, conn) -> Dict[str, Any]:
    battles = list_top_battles(limit=limit, conn=conn)
    return {
        "ok": True,
        "ready": hof_schema_ready(conn),
        "limit": max(1, min(int(limit), COMBAT_HOF_DISPLAY_LIMIT)),
        "battles": battles,
        "count": len(battles),
    }
