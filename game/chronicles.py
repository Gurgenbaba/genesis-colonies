"""Chronicles hub — personal history sections (GC-700C-R1, read-only).

Phase 1: ``section=pvp`` from combat inbox. Expedition/records sections follow later.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from .db import table_exists
from .messages import normalize_combat_metadata
from .number_format import fmt_int, fmt_int_compact
from .scoring import compute_destroyed_raw_from_losses

CHRONICLES_SECTION_PVP = "pvp"
CHRONICLES_SECTION_EXPEDITIONS = "expeditions"
CHRONICLES_SECTION_RECORDS = "records"
CHRONICLES_SECTION_KEYS = frozenset(
    {
        CHRONICLES_SECTION_PVP,
        CHRONICLES_SECTION_EXPEDITIONS,
        CHRONICLES_SECTION_RECORDS,
    }
)
CHRONICLES_SECTION_DEFAULT = CHRONICLES_SECTION_PVP
CHRONICLES_LIVE_SECTIONS = frozenset({CHRONICLES_SECTION_PVP})

PVP_TAB_OVERVIEW = "overview"
PVP_TAB_RECENT = "recent"
PVP_TAB_WINS = "wins"
PVP_TAB_LOSSES = "losses"
PVP_TAB_ATTACKS = "attacks"
PVP_TAB_DEFENSES = "defenses"
PVP_TAB_KEYS = frozenset(
    {
        PVP_TAB_OVERVIEW,
        PVP_TAB_RECENT,
        PVP_TAB_WINS,
        PVP_TAB_LOSSES,
        PVP_TAB_ATTACKS,
        PVP_TAB_DEFENSES,
    }
)
PVP_TAB_DEFAULT = PVP_TAB_OVERVIEW
PVP_STATS_SCAN_LIMIT = 500
PVP_DISPLAY_LIMIT = 50
PVP_OVERVIEW_RECENT_LIMIT = 10


def _normalize_section(raw: str | None) -> str:
    key = str(raw or CHRONICLES_SECTION_DEFAULT).strip().lower()
    return key if key in CHRONICLES_SECTION_KEYS else CHRONICLES_SECTION_DEFAULT


def _normalize_pvp_tab(raw: str | None) -> str:
    key = str(raw or PVP_TAB_DEFAULT).strip().lower()
    return key if key in PVP_TAB_KEYS else PVP_TAB_DEFAULT


def chronicles_schema_ready(conn) -> bool:
    return table_exists(conn, "player_messages")


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


def _parse_metadata(raw: Any) -> Dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw))
        return dict(parsed) if isinstance(parsed, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def _loot_total(loot: Mapping[str, Any]) -> int:
    return (
        max(0, int(loot.get("metal") or 0))
        + max(0, int(loot.get("crystal") or 0))
        + max(0, int(loot.get("fuel_cells") or 0))
    )


def _debris_total(debris: Mapping[str, Any]) -> int:
    return max(0, int(debris.get("metal") or 0)) + max(0, int(debris.get("crystal") or 0))


def _resolve_perspective(meta: Mapping[str, Any], player_id: int) -> str:
    perspective = str(meta.get("perspective") or "").strip().lower()
    if perspective in ("attacker", "defender"):
        return perspective
    pid = int(player_id)
    atk_id = int(meta.get("attacker_id") or 0)
    def_id = int(meta.get("defender_id") or 0)
    if pid and pid == atk_id:
        return "attacker"
    if pid and pid == def_id:
        return "defender"
    return ""


def _viewer_outcome(meta: Mapping[str, Any], player_id: int) -> str:
    winner = str(meta.get("result") or meta.get("winner") or "undecided").strip().lower()
    if winner == "draw":
        return "draw"
    if winner == "undecided":
        return "open"
    perspective = _resolve_perspective(meta, player_id)
    if not perspective:
        return "open"
    if winner == perspective:
        return "victory"
    return "defeat"


def _outcome_label_key(outcome: str) -> str:
    mapping = {
        "victory": "pvp_outcome_victory",
        "defeat": "pvp_outcome_defeat",
        "draw": "pvp_outcome_draw",
        "open": "pvp_outcome_open",
    }
    return mapping.get(str(outcome or ""), "pvp_outcome_open")


def _destroyed_dealt(meta: Mapping[str, Any], perspective: str) -> int:
    if perspective == "attacker":
        return compute_destroyed_raw_from_losses(dict(meta.get("defender_losses") or {}))
    if perspective == "defender":
        return compute_destroyed_raw_from_losses(dict(meta.get("attacker_losses") or {}))
    return 0


def _destroyed_lost(meta: Mapping[str, Any], perspective: str) -> int:
    if perspective == "attacker":
        return compute_destroyed_raw_from_losses(dict(meta.get("attacker_losses") or {}))
    if perspective == "defender":
        return compute_destroyed_raw_from_losses(dict(meta.get("defender_losses") or {}))
    return 0


def _opponent_name(meta: Mapping[str, Any], perspective: str) -> str:
    if perspective == "attacker":
        return str(meta.get("defender_name") or "—")
    if perspective == "defender":
        return str(meta.get("attacker_name") or "—")
    return "—"


def _battle_from_row(row: Any, *, player_id: int) -> Dict[str, Any]:
    meta = normalize_combat_metadata(_parse_metadata(row["metadata_json"]))
    perspective = _resolve_perspective(meta, player_id)
    outcome = _viewer_outcome(meta, player_id)
    loot = dict(meta.get("loot") or {})
    debris = dict(meta.get("debris") or {})
    loot_total = _loot_total(loot)
    debris_total = _debris_total(debris)
    destroyed_dealt = _destroyed_dealt(meta, perspective)
    destroyed_lost = _destroyed_lost(meta, perspective)
    created_ts = int(row["created_at"] or 0)
    return {
        "message_id": int(row["id"]),
        "subject": str(row["subject"] or ""),
        "created_at": created_ts,
        "created_at_fmt": _format_created_at(created_ts),
        "created_at_short": _format_created_at_short(created_ts),
        "perspective": perspective,
        "perspective_label_key": "pvp_perspective_attacker"
        if perspective == "attacker"
        else "pvp_perspective_defender"
        if perspective == "defender"
        else "",
        "outcome": outcome,
        "outcome_label_key": _outcome_label_key(outcome),
        "opponent_name": _opponent_name(meta, perspective),
        "target_coords": str(meta.get("target_coords") or ""),
        "target_planet_name": str(meta.get("target_planet_name") or ""),
        "destroyed_dealt": destroyed_dealt,
        "destroyed_dealt_compact": fmt_int_compact(destroyed_dealt),
        "destroyed_lost": destroyed_lost,
        "destroyed_lost_compact": fmt_int_compact(destroyed_lost),
        "destroyed_total": destroyed_dealt + destroyed_lost,
        "destroyed_total_compact": fmt_int_compact(destroyed_dealt + destroyed_lost),
        "loot_total": loot_total,
        "loot_total_compact": fmt_int_compact(loot_total),
        "debris_total": debris_total,
        "debris_total_compact": fmt_int_compact(debris_total),
        "is_read": bool(int(row["is_read"] or 0)),
        "report_metadata": meta,
    }


def _matches_pvp_tab(battle: Mapping[str, Any], tab: str) -> bool:
    key = _normalize_pvp_tab(tab)
    if key in (PVP_TAB_OVERVIEW, PVP_TAB_RECENT):
        return True
    if key == PVP_TAB_WINS:
        return str(battle.get("outcome") or "") == "victory"
    if key == PVP_TAB_LOSSES:
        return str(battle.get("outcome") or "") == "defeat"
    if key == PVP_TAB_ATTACKS:
        return str(battle.get("perspective") or "") == "attacker"
    if key == PVP_TAB_DEFENSES:
        return str(battle.get("perspective") or "") == "defender"
    return True


def _fetch_combat_rows(player_id: int, *, limit: int, conn: sqlite3.Connection) -> List[Any]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, subject, metadata_json, created_at, is_read
        FROM player_messages
        WHERE recipient_player_id = ?
          AND (deleted_at IS NULL OR deleted_at = 0)
          AND COALESCE(is_archived, 0) = 0
          AND category = 'combat'
        ORDER BY created_at DESC, id DESC
        LIMIT ?;
        """,
        (int(player_id), max(1, int(limit))),
    )
    return cur.fetchall()


def _build_pvp_stats(battles: List[Mapping[str, Any]]) -> Dict[str, Any]:
    stats = {
        "total_battles": len(battles),
        "wins": 0,
        "losses": 0,
        "draws": 0,
        "attacks": 0,
        "defenses": 0,
        "loot_gained_total": 0,
        "destroyed_dealt_total": 0,
        "destroyed_lost_total": 0,
    }
    for battle in battles:
        outcome = str(battle.get("outcome") or "")
        perspective = str(battle.get("perspective") or "")
        if outcome == "victory":
            stats["wins"] += 1
        elif outcome == "defeat":
            stats["losses"] += 1
        elif outcome == "draw":
            stats["draws"] += 1
        if perspective == "attacker":
            stats["attacks"] += 1
        elif perspective == "defender":
            stats["defenses"] += 1
        loot_total = max(0, int(battle.get("loot_total") or 0))
        if outcome == "victory" and perspective == "attacker" and loot_total > 0:
            stats["loot_gained_total"] += loot_total
        stats["destroyed_dealt_total"] += max(0, int(battle.get("destroyed_dealt") or 0))
        stats["destroyed_lost_total"] += max(0, int(battle.get("destroyed_lost") or 0))

    loot_gained = int(stats["loot_gained_total"])
    dealt = int(stats["destroyed_dealt_total"])
    lost = int(stats["destroyed_lost_total"])
    stats["loot_gained_total"] = loot_gained
    stats["loot_gained_compact"] = fmt_int_compact(loot_gained)
    stats["loot_gained_fmt"] = fmt_int(loot_gained)
    stats["destroyed_dealt_total"] = dealt
    stats["destroyed_dealt_compact"] = fmt_int_compact(dealt)
    stats["destroyed_dealt_fmt"] = fmt_int(dealt)
    stats["destroyed_lost_total"] = lost
    stats["destroyed_lost_compact"] = fmt_int_compact(lost)
    stats["destroyed_lost_fmt"] = fmt_int(lost)
    return stats


def _combat_rank(player_id: int, *, conn: sqlite3.Connection) -> Optional[int]:
    if not table_exists(conn, "player_scores"):
        return None
    cur = conn.cursor()
    cur.execute(
        "SELECT rank_combat FROM player_scores WHERE player_id = ? LIMIT 1;",
        (int(player_id),),
    )
    row = cur.fetchone()
    if not row or row["rank_combat"] is None:
        return None
    try:
        rank = int(row["rank_combat"])
    except (TypeError, ValueError):
        return None
    return rank if rank > 0 else None


def list_pvp_battles(
    player_id: int,
    *,
    tab: str = PVP_TAB_DEFAULT,
    conn: sqlite3.Connection,
    display_limit: int = PVP_DISPLAY_LIMIT,
) -> List[Dict[str, Any]]:
    tab_key = _normalize_pvp_tab(tab)
    rows = _fetch_combat_rows(int(player_id), limit=PVP_STATS_SCAN_LIMIT, conn=conn)
    battles = [_battle_from_row(row, player_id=int(player_id)) for row in rows]
    filtered = [b for b in battles if _matches_pvp_tab(b, tab_key)]
    lim = PVP_OVERVIEW_RECENT_LIMIT if tab_key == PVP_TAB_OVERVIEW else max(1, int(display_limit))
    return filtered[:lim]


def build_pvp_stats(player_id: int, *, conn: sqlite3.Connection) -> Dict[str, Any]:
    rows = _fetch_combat_rows(int(player_id), limit=PVP_STATS_SCAN_LIMIT, conn=conn)
    battles = [_battle_from_row(row, player_id=int(player_id)) for row in rows]
    stats = _build_pvp_stats(battles)
    stats["combat_rank"] = _combat_rank(int(player_id), conn=conn)
    return stats


def _build_pvp_section_payload(
    *,
    player_id: int,
    tab: str,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    tab_key = _normalize_pvp_tab(tab)
    ready = chronicles_schema_ready(conn)
    stats = build_pvp_stats(int(player_id), conn=conn) if ready else _build_pvp_stats([])
    battles = list_pvp_battles(int(player_id), tab=tab_key, conn=conn) if ready else []
    return {
        "ready": ready,
        "tab": tab_key,
        "stats": stats,
        "battles": battles,
        "count": len(battles),
    }


def build_chronicles_api_payload(
    *,
    player_id: int,
    section: str = CHRONICLES_SECTION_DEFAULT,
    tab: str = PVP_TAB_DEFAULT,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    section_key = _normalize_section(section)
    live = section_key in CHRONICLES_LIVE_SECTIONS
    pvp_payload: Dict[str, Any] = {
        "ready": False,
        "tab": _normalize_pvp_tab(tab),
        "stats": _build_pvp_stats([]),
        "battles": [],
        "count": 0,
    }
    if live and section_key == CHRONICLES_SECTION_PVP:
        pvp_payload = _build_pvp_section_payload(
            player_id=int(player_id),
            tab=tab,
            conn=conn,
        )

    return {
        "ok": True,
        "ready": chronicles_schema_ready(conn),
        "section": section_key,
        "section_live": live,
        "tab": pvp_payload.get("tab") if section_key == CHRONICLES_SECTION_PVP else "",
        "stats": pvp_payload.get("stats") or {},
        "battles": pvp_payload.get("battles") or [],
        "count": int(pvp_payload.get("count") or 0),
        "pvp": pvp_payload,
    }
