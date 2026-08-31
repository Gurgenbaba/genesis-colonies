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

HOF_SORT_DESTROYED = "destroyed"
HOF_SORT_DEBRIS = "debris"
HOF_SORT_LOOT = "loot"
HOF_SORT_RECENT = "recent"
HOF_SORT_KEYS = frozenset({HOF_SORT_DESTROYED, HOF_SORT_DEBRIS, HOF_SORT_LOOT, HOF_SORT_RECENT})
HOF_SORT_DEFAULT = HOF_SORT_DESTROYED


def _normalize_hof_sort(raw: str | None) -> str:
    key = str(raw or HOF_SORT_DEFAULT).strip().lower()
    return key if key in HOF_SORT_KEYS else HOF_SORT_DEFAULT


def _loot_total(loot: Mapping[str, Any]) -> int:
    return (
        max(0, int(loot.get("metal") or 0))
        + max(0, int(loot.get("crystal") or 0))
        + max(0, int(loot.get("fuel_cells") or 0))
    )


def _debris_total(debris: Mapping[str, Any]) -> int:
    return max(0, int(debris.get("metal") or 0)) + max(0, int(debris.get("crystal") or 0))


def _sort_order_sql(sort: str) -> str:
    if sort == HOF_SORT_DEBRIS:
        return """
        ORDER BY
          (
            COALESCE(json_extract(debris_json, '$.metal'), 0)
            + COALESCE(json_extract(debris_json, '$.crystal'), 0)
          ) DESC,
          created_at DESC,
          id DESC
        """
    if sort == HOF_SORT_LOOT:
        return """
        ORDER BY
          (
            COALESCE(json_extract(loot_json, '$.metal'), 0)
            + COALESCE(json_extract(loot_json, '$.crystal'), 0)
            + COALESCE(json_extract(loot_json, '$.fuel_cells'), 0)
          ) DESC,
          created_at DESC,
          id DESC
        """
    if sort == HOF_SORT_RECENT:
        return "ORDER BY created_at DESC, id DESC"
    return "ORDER BY total_destroyed_score DESC, created_at DESC, id DESC"


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


def _format_created_at_short(ts: int) -> str:
    try:
        dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        return dt.strftime("%d.%m.")
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


def _is_backfill_combat_metadata(meta: Mapping[str, Any]) -> bool:
    """True for attack combat inbox metadata (not logistics fleet reports)."""
    if not meta:
        return False
    if meta.get("report_phase"):
        return False
    fleet_id = meta.get("fleet_id")
    try:
        if fleet_id is None or int(fleet_id) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    if meta.get("report_version"):
        return True
    if meta.get("attacker_losses") or meta.get("defender_losses"):
        return True
    mission = str(meta.get("mission_type") or "").strip().lower()
    if mission == "attack":
        return bool(meta.get("winner") or meta.get("result") or meta.get("rounds_fought"))
    return False


def _hof_payload_from_combat_metadata(meta: Mapping[str, Any]) -> Dict[str, Any] | None:
    """Map stored combat report metadata to ``record_hof_battle`` kwargs (no combat re-sim)."""
    from .combat import calculate_combat_debris
    from .messages import normalize_combat_metadata

    norm = normalize_combat_metadata(dict(meta))
    if not _is_backfill_combat_metadata(norm):
        return None

    atk_losses = dict(norm.get("attacker_losses") or {})
    def_losses = dict(norm.get("defender_losses") or {})
    debris_m, debris_c = calculate_combat_debris(atk_losses, def_losses)
    winner = str(norm.get("winner") or norm.get("result") or "")
    rounds = int(norm.get("rounds_fought") or len(norm.get("rounds") or []))

    target_planet_id = norm.get("defender_planet_id") or norm.get("target_planet_id")
    try:
        target_planet_id = int(target_planet_id) if target_planet_id else None
    except (TypeError, ValueError):
        target_planet_id = None

    return {
        "fleet_id": int(norm["fleet_id"]),
        "attacker_player_id": int(norm.get("attacker_id") or 0),
        "defender_player_id": int(norm.get("defender_id") or 0),
        "attacker_name": str(norm.get("attacker_name") or ""),
        "defender_name": str(norm.get("defender_name") or ""),
        "target_planet_id": target_planet_id,
        "target_name": str(norm.get("target_planet_name") or ""),
        "target_coords": str(norm.get("target_coords") or ""),
        "winner": winner,
        "rounds": rounds,
        "attacker_losses": atk_losses,
        "defender_losses": def_losses,
        "loot": dict(norm.get("loot") or {}),
        "debris": {"metal": int(debris_m), "crystal": int(debris_c)},
        "report_metadata": norm,
    }


def backfill_combat_hof(*, limit: int | None = None, conn) -> Dict[str, Any]:
    """
    Import historical attack combat reports from ``player_messages`` into HoF storage.

    Uses inbox ``metadata_json`` only — no combat resolver re-run. One row per ``fleet_id``
    (attacker perspective preferred when duplicate inbox copies exist). Prunes to top 250 after.
    """
    from .messages import _table_ready as messages_ready

    if not hof_schema_ready(conn):
        return {"ok": False, "error": "hof_schema_missing", "inserted": 0}
    if not messages_ready(conn):
        return {"ok": False, "error": "messages_schema_missing", "inserted": 0}

    cur = conn.cursor()
    cur.execute(f"SELECT fleet_id FROM {COMBAT_HOF_TABLE};")
    existing_fleet_ids = {int(row["fleet_id"]) for row in cur.fetchall()}

    cur.execute(
        """
        SELECT id, metadata_json, created_at
        FROM player_messages
        WHERE category = 'combat'
          AND (deleted_at IS NULL OR deleted_at = 0)
          AND json_extract(metadata_json, '$.fleet_id') IS NOT NULL
          AND json_extract(metadata_json, '$.report_phase') IS NULL
        ORDER BY
          CAST(json_extract(metadata_json, '$.fleet_id') AS INTEGER) ASC,
          CASE WHEN json_extract(metadata_json, '$.perspective') = 'attacker' THEN 0 ELSE 1 END ASC,
          created_at ASC,
          id ASC;
        """
    )

    seen_fleet_ids: set[int] = set()
    inserted = 0
    skipped_existing = 0
    skipped_invalid = 0
    scanned = 0
    max_candidates = int(limit) if limit is not None else None

    for row in cur.fetchall():
        if max_candidates is not None and len(seen_fleet_ids) >= max_candidates:
            break
        scanned += 1
        meta = _json_loads(row["metadata_json"])
        fleet_raw = meta.get("fleet_id")
        try:
            fleet_id = int(fleet_raw)
        except (TypeError, ValueError):
            skipped_invalid += 1
            continue
        if fleet_id in seen_fleet_ids:
            continue
        seen_fleet_ids.add(fleet_id)

        if fleet_id in existing_fleet_ids:
            skipped_existing += 1
            continue

        payload = _hof_payload_from_combat_metadata(meta)
        if payload is None:
            skipped_invalid += 1
            continue

        created_at = int(row["created_at"] or 0) or None
        if record_hof_battle(
            **payload,
            created_at=created_at,
            conn=conn,
            prune=False,
        ):
            inserted += 1
            existing_fleet_ids.add(fleet_id)

    pruned = prune_hof_entries_beyond_top(conn=conn) if inserted else 0
    return {
        "ok": True,
        "inserted": inserted,
        "skipped_existing": skipped_existing,
        "skipped_invalid": skipped_invalid,
        "scanned": scanned,
        "candidates": len(seen_fleet_ids),
        "pruned": pruned,
    }


HOF_SYNC_RUNTIME_KEY = "combat_hof_last_message_id"
HOF_SYNC_INTERVAL_SEC = 300


def sync_combat_hof_incremental(*, conn, limit: int = 40) -> Dict[str, Any]:
    """Import new combat inbox reports since last sync (no combat re-sim).

    GC-PROD-SQLITE-STALL-001B: expensive message scans run **outside** a write
    lock when the caller is not already in a transaction. Mutations use a short
    ``BEGIN IMMEDIATE`` only for inserts / cursor advance / prune.
    """
    from .db import begin_write_transaction, commit, in_transaction, rollback
    from .messages import _table_ready as messages_ready
    from .runtime_state import get_runtime_value, set_runtime_value

    if not hof_schema_ready(conn):
        return {"ok": False, "error": "hof_schema_missing", "inserted": 0}
    if not messages_ready(conn):
        return {"ok": False, "error": "messages_schema_missing", "inserted": 0}

    try:
        last_id = int(get_runtime_value(HOF_SYNC_RUNTIME_KEY, conn=conn) or 0)
    except (TypeError, ValueError):
        last_id = 0

    cur = conn.cursor()
    # Avoid full-table HoF preload (was O(hof rows) under the writer lock).
    # record_hof_battle uses INSERT OR IGNORE on fleet_id UNIQUE.
    cur.execute(
        """
        SELECT id, metadata_json, created_at
        FROM player_messages
        WHERE category = 'combat'
          AND id > ?
          AND (deleted_at IS NULL OR deleted_at = 0)
          AND json_extract(metadata_json, '$.fleet_id') IS NOT NULL
          AND json_extract(metadata_json, '$.report_phase') IS NULL
        ORDER BY id ASC
        LIMIT ?;
        """,
        (int(last_id), max(1, min(int(limit), 200))),
    )
    rows = list(cur.fetchall())

    candidates: List[Dict[str, Any]] = []
    skipped_invalid = 0
    max_id = last_id
    for row in rows:
        max_id = max(max_id, int(row["id"]))
        meta = _json_loads(row["metadata_json"])
        try:
            fleet_id = int(meta.get("fleet_id"))
        except (TypeError, ValueError):
            skipped_invalid += 1
            continue
        payload = _hof_payload_from_combat_metadata(meta)
        if payload is None:
            skipped_invalid += 1
            continue
        candidates.append(
            {
                "fleet_id": fleet_id,
                "payload": payload,
                "created_at": int(row["created_at"] or 0) or None,
            }
        )

    if not candidates and max_id <= last_id:
        return {
            "ok": True,
            "inserted": 0,
            "skipped_existing": 0,
            "skipped_invalid": skipped_invalid,
            "pruned": 0,
            "last_message_id": max_id,
        }

    own_tx = not in_transaction(conn)
    if own_tx:
        begin_write_transaction(conn)
    inserted = 0
    skipped_existing = 0
    pruned = 0
    try:
        for item in candidates:
            if record_hof_battle(
                **item["payload"],
                created_at=item["created_at"],
                conn=conn,
                prune=False,
            ):
                inserted += 1
            else:
                skipped_existing += 1
        pruned = prune_hof_entries_beyond_top(conn=conn) if inserted else 0
        if max_id > last_id:
            set_runtime_value(HOF_SYNC_RUNTIME_KEY, str(int(max_id)), conn=conn)
        if own_tx:
            commit(conn)
    except Exception:
        if own_tx:
            try:
                rollback(conn)
            except Exception:
                pass
        raise

    return {
        "ok": True,
        "inserted": inserted,
        "skipped_existing": skipped_existing,
        "skipped_invalid": skipped_invalid,
        "pruned": pruned,
        "last_message_id": max_id,
    }


def maybe_sync_combat_hof_incremental(*, conn, limit: int = 40) -> Dict[str, Any]:
    """Throttled HoF catch-up for reports missed by live record_hof_battle."""
    from .db import begin_write_transaction, commit, in_transaction, rollback
    from .runtime_state import get_runtime_value, set_runtime_value

    now = time.time()
    throttle_key = "combat_hof_last_sync_at"
    try:
        last_at = float(get_runtime_value(throttle_key, conn=conn) or 0)
    except (TypeError, ValueError):
        last_at = 0.0
    if last_at > 0 and (now - last_at) < float(HOF_SYNC_INTERVAL_SEC):
        return {"ok": True, "skipped": "interval", "inserted": 0}
    result = sync_combat_hof_incremental(conn=conn, limit=limit)
    # Persist throttle outside the sync write TX when possible (own short TX).
    own_tx = not in_transaction(conn)
    if own_tx:
        begin_write_transaction(conn)
    try:
        set_runtime_value(throttle_key, str(int(now)), conn=conn)
        if own_tx:
            commit(conn)
    except Exception:
        if own_tx:
            try:
                rollback(conn)
            except Exception:
                pass
        raise
    return result


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
    prune: bool = True,
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
    if inserted and prune:
        prune_hof_entries_beyond_top(conn=conn)
    return inserted


def _row_to_battle(row: Any, *, rank: int) -> Dict[str, Any]:
    loot = _json_loads(row["loot_json"])
    debris = _json_loads(row["debris_json"])
    report_metadata = _json_loads(row["report_metadata_json"])
    total_score = int(row["total_destroyed_score"] or 0)
    loot_total = _loot_total(loot)
    debris_total = _debris_total(debris)
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
        "loot_total": loot_total,
        "loot_total_fmt": fmt_int(loot_total),
        "loot_total_compact": fmt_int_compact(loot_total),
        "debris_total": debris_total,
        "debris_total_fmt": fmt_int(debris_total),
        "debris_total_compact": fmt_int_compact(debris_total),
        "loot": loot,
        "debris": debris,
        "report_metadata": report_metadata,
        "created_at": created_ts,
        "created_at_fmt": _format_created_at(created_ts),
        "created_at_short": _format_created_at_short(created_ts),
    }


def list_hof_battles(
    *,
    sort: str = HOF_SORT_DEFAULT,
    limit: int = COMBAT_HOF_DISPLAY_LIMIT,
    conn,
) -> List[Dict[str, Any]]:
    """Return battles for Hall of Fame display (read-only, category sort)."""
    if not hof_schema_ready(conn):
        return []

    sort_key = _normalize_hof_sort(sort)
    lim = max(1, min(int(limit), COMBAT_HOF_DISPLAY_LIMIT))
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT *
        FROM {COMBAT_HOF_TABLE}
        {_sort_order_sql(sort_key)}
        LIMIT ?;
        """,
        (lim,),
    )
    rows = cur.fetchall()
    return [_row_to_battle(row, rank=idx + 1) for idx, row in enumerate(rows)]


def list_top_battles(*, limit: int = COMBAT_HOF_DISPLAY_LIMIT, conn) -> List[Dict[str, Any]]:
    """Return up to ``limit`` battles sorted by destroyed value (desc), then date (desc)."""
    return list_hof_battles(sort=HOF_SORT_DESTROYED, limit=limit, conn=conn)


def _destroyed_rank_for_battle(row: Any, *, conn) -> int:
    score = int(row["total_destroyed_score"] or 0)
    created = int(row["created_at"] or 0)
    battle_id = int(row["id"])
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM {COMBAT_HOF_TABLE}
        WHERE total_destroyed_score > ?
           OR (total_destroyed_score = ? AND created_at > ?)
           OR (total_destroyed_score = ? AND created_at = ? AND id > ?);
        """,
        (score, score, created, score, created, battle_id),
    )
    return int(cur.fetchone()["c"] or 0) + 1


def get_player_hof_highlight(*, player_id: int, conn) -> Dict[str, Any] | None:
    """Best destroyed-value battle for a player and its global rank."""
    if not hof_schema_ready(conn):
        return None
    pid = int(player_id)
    if pid <= 0:
        return None

    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT *
        FROM {COMBAT_HOF_TABLE}
        WHERE attacker_player_id = ? OR defender_player_id = ?
        ORDER BY total_destroyed_score DESC, created_at DESC, id DESC
        LIMIT 1;
        """,
        (pid, pid),
    )
    row = cur.fetchone()
    if not row:
        return None

    rank = _destroyed_rank_for_battle(row, conn=conn)
    battle = _row_to_battle(row, rank=rank)
    return {
        "rank": rank,
        "battle": battle,
        "total_destroyed_score": battle["total_destroyed_score"],
        "total_destroyed_score_compact": battle["total_destroyed_score_compact"],
        "attacker_name": battle["attacker_name"],
        "defender_name": battle["defender_name"],
        "target_coords": battle["target_coords"],
    }


def build_hof_api_payload(
    *,
    sort: str = HOF_SORT_DEFAULT,
    player_id: int | None = None,
    limit: int = COMBAT_HOF_DISPLAY_LIMIT,
    conn,
) -> Dict[str, Any]:
    sort_key = _normalize_hof_sort(sort)
    battles = list_hof_battles(sort=sort_key, limit=limit, conn=conn)
    highlight = None
    if player_id is not None and int(player_id) > 0:
        highlight = get_player_hof_highlight(player_id=int(player_id), conn=conn)
    return {
        "ok": True,
        "ready": hof_schema_ready(conn),
        "sort": sort_key,
        "limit": max(1, min(int(limit), COMBAT_HOF_DISPLAY_LIMIT)),
        "battles": battles,
        "count": len(battles),
        "player_highlight": highlight,
    }
