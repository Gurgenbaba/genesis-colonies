"""Chronicles hub — personal history sections (GC-700C, read-only).

Sections: PvP (combat inbox), Expeditionen (expedition inbox), Rekorde (aggregated).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from .db import table_exists
from .expedition_events import expedition_event_weight_audit
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
CHRONICLES_LIVE_SECTIONS = frozenset(CHRONICLES_SECTION_KEYS)

EXPEDITION_TAB_OVERVIEW = "overview"
EXPEDITION_TAB_ALL = "all"
EXPEDITION_TAB_LOOT = "loot"
EXPEDITION_TAB_PIRATES = "pirates"
EXPEDITION_TAB_HAZARDS = "hazards"
EXPEDITION_TAB_TREASURE = "treasure"
EXPEDITION_TAB_LEGENDARY = "legendary"
EXPEDITION_TAB_KEYS = frozenset(
    {
        EXPEDITION_TAB_OVERVIEW,
        EXPEDITION_TAB_ALL,
        EXPEDITION_TAB_LOOT,
        EXPEDITION_TAB_PIRATES,
        EXPEDITION_TAB_HAZARDS,
        EXPEDITION_TAB_TREASURE,
        EXPEDITION_TAB_LEGENDARY,
    }
)
EXPEDITION_TAB_DEFAULT = EXPEDITION_TAB_OVERVIEW
EXPEDITION_STATS_SCAN_LIMIT = 500
EXPEDITION_DISPLAY_LIMIT = 50
EXPEDITION_OVERVIEW_RECENT_LIMIT = 10

# Read-only mirror of expedition_events category table (no engine import of private state).
_EXPO_EVENT_CATEGORIES: Dict[str, str] = {
    "void_scan": "neutral",
    "sensor_glitch": "neutral",
    "mineral_deposit": "loot",
    "fuel_cache": "loot",
    "debris_salvage": "loot",
    "distress_beacon": "loot",
    "ancient_stash": "loot",
    "nav_interference": "delay",
    "ion_storm": "delay",
    "pirate_encounter": "combat",
    "ancient_minefield": "hazard",
    "lost_container": "treasure",
    "abandoned_convoy": "treasure",
    "ancient_derelict": "treasure",
    "spatial_rift": "legendary",
    "time_anomaly": "legendary",
    "ancient_beacon": "legendary",
}
_EXPO_HAZARD_EVENT_KEYS = frozenset({"ancient_minefield", "ion_storm", "nav_interference"})
_EXPO_LEGENDARY_EVENT_KEYS = frozenset({"spatial_rift", "time_anomaly", "ancient_beacon"})

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


def _normalize_expedition_tab(raw: str | None) -> str:
    key = str(raw or EXPEDITION_TAB_DEFAULT).strip().lower()
    return key if key in EXPEDITION_TAB_KEYS else EXPEDITION_TAB_DEFAULT


def _normalize_section_tab(section: str, raw: str | None) -> str:
    section_key = _normalize_section(section)
    if section_key == CHRONICLES_SECTION_PVP:
        return _normalize_pvp_tab(raw)
    if section_key == CHRONICLES_SECTION_EXPEDITIONS:
        return _normalize_expedition_tab(raw)
    return ""


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


def _expedition_event_category(event_key: str) -> str:
    return str(_EXPO_EVENT_CATEGORIES.get(str(event_key or "").strip(), "other"))


def _expedition_category_label_key(event_key: str) -> str:
    category = _expedition_event_category(event_key)
    if str(event_key) == "pirate_encounter":
        category = "combat"
    elif str(event_key) in _EXPO_LEGENDARY_EVENT_KEYS:
        category = "legendary"
    mapping = {
        "loot": "chronicles_expo_cat_loot",
        "combat": "chronicles_expo_cat_pirates",
        "hazard": "chronicles_expo_cat_hazards",
        "delay": "chronicles_expo_cat_hazards",
        "treasure": "chronicles_expo_cat_treasure",
        "legendary": "chronicles_expo_cat_legendary",
        "neutral": "chronicles_expo_cat_neutral",
    }
    return mapping.get(category, "chronicles_expo_cat_other")


def _expedition_rewards_total(rewards: Mapping[str, Any]) -> int:
    loot = dict(rewards or {})
    return (
        max(0, int(loot.get("metal") or 0))
        + max(0, int(loot.get("crystal") or 0))
        + max(0, int(loot.get("fuel_cells") or 0))
    )


def _format_losses_salvage(losses_total: int, salvaged_total: int) -> str:
    losses = max(0, int(losses_total))
    salvage = max(0, int(salvaged_total))
    if losses <= 0 and salvage <= 0:
        return "—"
    if losses > 0 and salvage > 0:
        return f"{fmt_int_compact(losses)} / +{fmt_int_compact(salvage)}"
    if losses > 0:
        return fmt_int_compact(losses)
    return f"+{fmt_int_compact(salvage)}"


def _expedition_from_row(row: Any) -> Dict[str, Any]:
    meta = _parse_metadata(row["metadata_json"])
    event_key = str(meta.get("event_key") or "")
    rewards = dict(meta.get("rewards") or {})
    loot_total = _expedition_rewards_total(rewards)
    losses_total = max(0, int(meta.get("losses_total") or 0))
    salvaged_total = max(0, int(meta.get("salvaged_total") or 0))
    created_ts = int(row["created_at"] or 0)
    story_tier = str(meta.get("story_tier") or "")
    is_legendary = (
        event_key in _EXPO_LEGENDARY_EVENT_KEYS
        or story_tier == "legendary"
        or _expedition_event_category(event_key) == "legendary"
    )
    return {
        "message_id": int(row["id"]),
        "subject": str(row["subject"] or ""),
        "created_at": created_ts,
        "created_at_fmt": _format_created_at(created_ts),
        "created_at_short": _format_created_at_short(created_ts),
        "event_key": event_key,
        "event_label_key": str(meta.get("event_label_key") or event_key or "expedition_event_void_scan"),
        "event_category": _expedition_event_category(event_key),
        "event_category_label_key": _expedition_category_label_key(event_key),
        "target_coords": str(meta.get("target_coords") or ""),
        "loot_total": loot_total,
        "loot_total_compact": fmt_int_compact(loot_total),
        "loot_total_fmt": fmt_int(loot_total),
        "losses_total": losses_total,
        "salvaged_total": salvaged_total,
        "losses_salvage_compact": _format_losses_salvage(losses_total, salvaged_total),
        "is_legendary": is_legendary,
        "is_read": bool(int(row["is_read"] or 0)),
        "report_metadata": meta,
    }


def _matches_expedition_tab(event: Mapping[str, Any], tab: str) -> bool:
    tab_key = _normalize_expedition_tab(tab)
    if tab_key in (EXPEDITION_TAB_OVERVIEW, EXPEDITION_TAB_ALL):
        return True
    event_key = str(event.get("event_key") or "")
    category = _expedition_event_category(event_key)
    if tab_key == EXPEDITION_TAB_LOOT:
        return category == "loot" or max(0, int(event.get("loot_total") or 0)) > 0
    if tab_key == EXPEDITION_TAB_PIRATES:
        return event_key == "pirate_encounter" or category == "combat"
    if tab_key == EXPEDITION_TAB_HAZARDS:
        return category == "hazard" or event_key in _EXPO_HAZARD_EVENT_KEYS
    if tab_key == EXPEDITION_TAB_TREASURE:
        return category == "treasure"
    if tab_key == EXPEDITION_TAB_LEGENDARY:
        return bool(event.get("is_legendary"))
    return True


def _fetch_expedition_rows(player_id: int, *, limit: int, conn: sqlite3.Connection) -> List[Any]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, subject, metadata_json, created_at, is_read
        FROM player_messages
        WHERE recipient_player_id = ?
          AND (deleted_at IS NULL OR deleted_at = 0)
          AND COALESCE(is_archived, 0) = 0
          AND category = 'expedition'
        ORDER BY created_at DESC, id DESC
        LIMIT ?;
        """,
        (int(player_id), max(1, int(limit))),
    )
    return cur.fetchall()


def _build_expedition_stats(events: List[Mapping[str, Any]]) -> Dict[str, Any]:
    stats = {
        "total_expeditions": len(events),
        "loot_total": 0,
        "legendary_finds": 0,
        "pirate_contacts": 0,
        "ship_losses_total": 0,
        "biggest_find": 0,
    }
    for event in events:
        loot = max(0, int(event.get("loot_total") or 0))
        stats["loot_total"] += loot
        if loot > int(stats["biggest_find"]):
            stats["biggest_find"] = loot
        if bool(event.get("is_legendary")):
            stats["legendary_finds"] += 1
        if str(event.get("event_key") or "") == "pirate_encounter":
            stats["pirate_contacts"] += 1
        stats["ship_losses_total"] += max(0, int(event.get("losses_total") or 0))

    loot_total = int(stats["loot_total"])
    biggest = int(stats["biggest_find"])
    losses = int(stats["ship_losses_total"])
    stats["loot_total"] = loot_total
    stats["loot_total_compact"] = fmt_int_compact(loot_total)
    stats["loot_total_fmt"] = fmt_int(loot_total)
    stats["biggest_find"] = biggest
    stats["biggest_find_compact"] = fmt_int_compact(biggest)
    stats["biggest_find_fmt"] = fmt_int(biggest)
    stats["ship_losses_total"] = losses
    stats["ship_losses_compact"] = fmt_int_compact(losses)
    stats["ship_losses_fmt"] = fmt_int(losses)
    return stats


def list_expedition_events(
    player_id: int,
    *,
    tab: str = EXPEDITION_TAB_DEFAULT,
    conn: sqlite3.Connection,
    display_limit: int = EXPEDITION_DISPLAY_LIMIT,
) -> List[Dict[str, Any]]:
    tab_key = _normalize_expedition_tab(tab)
    rows = _fetch_expedition_rows(int(player_id), limit=EXPEDITION_STATS_SCAN_LIMIT, conn=conn)
    events = [_expedition_from_row(row) for row in rows]
    filtered = [e for e in events if _matches_expedition_tab(e, tab_key)]
    lim = (
        EXPEDITION_OVERVIEW_RECENT_LIMIT
        if tab_key == EXPEDITION_TAB_OVERVIEW
        else max(1, int(display_limit))
    )
    return filtered[:lim]


def build_expedition_stats(player_id: int, *, conn: sqlite3.Connection) -> Dict[str, Any]:
    rows = _fetch_expedition_rows(int(player_id), limit=EXPEDITION_STATS_SCAN_LIMIT, conn=conn)
    events = [_expedition_from_row(row) for row in rows]
    return _build_expedition_stats(events)


def _build_expedition_section_payload(
    *,
    player_id: int,
    tab: str,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    tab_key = _normalize_expedition_tab(tab)
    ready = chronicles_schema_ready(conn)
    stats = build_expedition_stats(int(player_id), conn=conn) if ready else _build_expedition_stats([])
    events = list_expedition_events(int(player_id), tab=tab_key, conn=conn) if ready else []
    return {
        "ready": ready,
        "tab": tab_key,
        "stats": stats,
        "events": events,
        "count": len(events),
    }


def _record_card(
    *,
    key: str,
    label_key: str,
    value_compact: str = "—",
    value_fmt: str = "",
    subtitle: str = "",
    created_at_fmt: str = "—",
    message_id: int | None = None,
    report_category: str = "",
    report_metadata: Mapping[str, Any] | None = None,
    detail_label_key: str = "",
) -> Dict[str, Any]:
    meta = dict(report_metadata or {})
    has_record = value_compact not in ("", "—") or bool(subtitle)
    return {
        "key": key,
        "label_key": label_key,
        "value_compact": value_compact,
        "value_fmt": value_fmt or value_compact,
        "subtitle": subtitle,
        "created_at_fmt": created_at_fmt,
        "message_id": int(message_id) if message_id else None,
        "report_category": str(report_category or ""),
        "report_metadata": meta if meta else None,
        "detail_label_key": detail_label_key,
        "has_record": has_record,
    }


def _build_records_cards(
    battles: List[Mapping[str, Any]],
    expeditions: List[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    weights = expedition_event_weight_audit().get("weights_by_key") or {}

    best_battle = max(battles, key=lambda b: int(b.get("destroyed_total") or 0), default=None)
    best_expo = max(expeditions, key=lambda e: int(e.get("loot_total") or 0), default=None)
    best_debris = max(battles, key=lambda b: int(b.get("debris_total") or 0), default=None)
    loot_battles = [b for b in battles if int(b.get("loot_total") or 0) > 0]
    best_loot = max(loot_battles, key=lambda b: int(b.get("loot_total") or 0), default=None)

    rarest: Mapping[str, Any] | None = None
    if expeditions:
        rarest = min(
            expeditions,
            key=lambda e: int(weights.get(str(e.get("event_key") or ""), 999)),
        )

    pirate_events = [e for e in expeditions if str(e.get("event_key") or "") == "pirate_encounter"]
    worst_pirate = max(pirate_events, key=lambda e: int(e.get("losses_total") or 0), default=None)
    best_pirate_salvage = max(
        pirate_events,
        key=lambda e: int(e.get("salvaged_total") or 0),
        default=None,
    )

    cards: List[Dict[str, Any]] = []

    if best_battle and int(best_battle.get("destroyed_total") or 0) > 0:
        cards.append(
            _record_card(
                key="biggest_battle",
                label_key="chronicles_record_biggest_battle",
                value_compact=str(best_battle.get("destroyed_total_compact") or "—"),
                value_fmt=str(best_battle.get("destroyed_total") or ""),
                subtitle=str(best_battle.get("opponent_name") or "—"),
                created_at_fmt=str(best_battle.get("created_at_fmt") or "—"),
                message_id=int(best_battle.get("message_id") or 0) or None,
                report_category="combat",
                report_metadata=best_battle.get("report_metadata"),
                detail_label_key="chronicles_record_detail_battle",
            )
        )
    else:
        cards.append(
            _record_card(key="biggest_battle", label_key="chronicles_record_biggest_battle")
        )

    if best_expo and int(best_expo.get("loot_total") or 0) > 0:
        cards.append(
            _record_card(
                key="biggest_expo_find",
                label_key="chronicles_record_biggest_expo",
                value_compact=str(best_expo.get("loot_total_compact") or "—"),
                value_fmt=str(best_expo.get("loot_total_fmt") or ""),
                subtitle=str(best_expo.get("target_coords") or "—"),
                created_at_fmt=str(best_expo.get("created_at_fmt") or "—"),
                message_id=int(best_expo.get("message_id") or 0) or None,
                report_category="expedition",
                report_metadata=best_expo.get("report_metadata"),
                detail_label_key="chronicles_record_detail_expo",
            )
        )
    else:
        cards.append(
            _record_card(key="biggest_expo_find", label_key="chronicles_record_biggest_expo")
        )

    if best_debris and int(best_debris.get("debris_total") or 0) > 0:
        cards.append(
            _record_card(
                key="biggest_debris",
                label_key="chronicles_record_biggest_debris",
                value_compact=str(best_debris.get("debris_total_compact") or "—"),
                value_fmt=str(best_debris.get("debris_total") or ""),
                subtitle=str(best_debris.get("target_coords") or "—"),
                created_at_fmt=str(best_debris.get("created_at_fmt") or "—"),
                message_id=int(best_debris.get("message_id") or 0) or None,
                report_category="combat",
                report_metadata=best_debris.get("report_metadata"),
                detail_label_key="chronicles_record_detail_debris",
            )
        )
    else:
        cards.append(
            _record_card(key="biggest_debris", label_key="chronicles_record_biggest_debris")
        )

    if best_loot and int(best_loot.get("loot_total") or 0) > 0:
        cards.append(
            _record_card(
                key="biggest_loot",
                label_key="chronicles_record_biggest_loot",
                value_compact=str(best_loot.get("loot_total_compact") or "—"),
                value_fmt=str(best_loot.get("loot_total") or ""),
                subtitle=str(best_loot.get("opponent_name") or "—"),
                created_at_fmt=str(best_loot.get("created_at_fmt") or "—"),
                message_id=int(best_loot.get("message_id") or 0) or None,
                report_category="combat",
                report_metadata=best_loot.get("report_metadata"),
                detail_label_key="chronicles_record_detail_loot",
            )
        )
    else:
        cards.append(
            _record_card(key="biggest_loot", label_key="chronicles_record_biggest_loot")
        )

    if rarest and str(rarest.get("event_key") or ""):
        cards.append(
            _record_card(
                key="rarest_expo_event",
                label_key="chronicles_record_rarest_expo",
                value_compact=str(rarest.get("event_key") or "—"),
                value_fmt="",
                subtitle=str(rarest.get("target_coords") or "—"),
                created_at_fmt=str(rarest.get("created_at_fmt") or "—"),
                message_id=int(rarest.get("message_id") or 0) or None,
                report_category="expedition",
                report_metadata=rarest.get("report_metadata"),
                detail_label_key=str(rarest.get("event_label_key") or "chronicles_record_detail_expo"),
            )
        )
    else:
        cards.append(
            _record_card(key="rarest_expo_event", label_key="chronicles_record_rarest_expo")
        )

    pirate_losses = int(worst_pirate.get("losses_total") or 0) if worst_pirate else 0
    pirate_salvage = int(best_pirate_salvage.get("salvaged_total") or 0) if best_pirate_salvage else 0
    if pirate_losses > 0 or pirate_salvage > 0:
        ref = worst_pirate if pirate_losses >= pirate_salvage else best_pirate_salvage
        cards.append(
            _record_card(
                key="pirate_losses_salvage",
                label_key="chronicles_record_pirate_losses",
                value_compact=_format_losses_salvage(pirate_losses, pirate_salvage),
                value_fmt=_format_losses_salvage(pirate_losses, pirate_salvage),
                subtitle=str(ref.get("target_coords") or "—") if ref else "—",
                created_at_fmt=str(ref.get("created_at_fmt") or "—") if ref else "—",
                message_id=int(ref.get("message_id") or 0) if ref else None,
                report_category="expedition",
                report_metadata=ref.get("report_metadata") if ref else None,
                detail_label_key="chronicles_record_detail_pirate",
            )
        )
    else:
        cards.append(
            _record_card(
                key="pirate_losses_salvage",
                label_key="chronicles_record_pirate_losses",
            )
        )

    return cards


def _build_records_section_payload(
    *,
    player_id: int,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    ready = chronicles_schema_ready(conn)
    if not ready:
        empty_cards = _build_records_cards([], [])
        return {"ready": False, "cards": empty_cards, "count": 0}

    combat_rows = _fetch_combat_rows(int(player_id), limit=EXPEDITION_STATS_SCAN_LIMIT, conn=conn)
    expo_rows = _fetch_expedition_rows(int(player_id), limit=EXPEDITION_STATS_SCAN_LIMIT, conn=conn)
    battles = [_battle_from_row(row, player_id=int(player_id)) for row in combat_rows]
    expeditions = [_expedition_from_row(row) for row in expo_rows]
    cards = _build_records_cards(battles, expeditions)
    populated = sum(1 for card in cards if card.get("has_record"))
    return {"ready": True, "cards": cards, "count": populated}


def build_chronicles_api_payload(
    *,
    player_id: int,
    section: str = CHRONICLES_SECTION_DEFAULT,
    tab: str = PVP_TAB_DEFAULT,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    section_key = _normalize_section(section)
    tab_key = _normalize_section_tab(section_key, tab)
    schema_ready = chronicles_schema_ready(conn)

    pvp_payload: Dict[str, Any] = {
        "ready": False,
        "tab": PVP_TAB_DEFAULT,
        "stats": _build_pvp_stats([]),
        "battles": [],
        "count": 0,
    }
    expeditions_payload: Dict[str, Any] = {
        "ready": False,
        "tab": EXPEDITION_TAB_DEFAULT,
        "stats": _build_expedition_stats([]),
        "events": [],
        "count": 0,
    }
    records_payload: Dict[str, Any] = {
        "ready": False,
        "cards": _build_records_cards([], []),
        "count": 0,
    }

    if schema_ready:
        if section_key == CHRONICLES_SECTION_PVP:
            pvp_payload = _build_pvp_section_payload(
                player_id=int(player_id),
                tab=tab_key,
                conn=conn,
            )
        elif section_key == CHRONICLES_SECTION_EXPEDITIONS:
            expeditions_payload = _build_expedition_section_payload(
                player_id=int(player_id),
                tab=tab_key,
                conn=conn,
            )
        elif section_key == CHRONICLES_SECTION_RECORDS:
            records_payload = _build_records_section_payload(
                player_id=int(player_id),
                conn=conn,
            )

    active: Dict[str, Any]
    if section_key == CHRONICLES_SECTION_EXPEDITIONS:
        active = expeditions_payload
    elif section_key == CHRONICLES_SECTION_RECORDS:
        active = records_payload
    else:
        active = pvp_payload

    return {
        "ok": True,
        "ready": schema_ready,
        "section": section_key,
        "section_live": section_key in CHRONICLES_LIVE_SECTIONS,
        "tab": tab_key,
        "stats": active.get("stats") or {},
        "battles": active.get("battles") or [],
        "events": active.get("events") or [],
        "cards": active.get("cards") or [],
        "count": int(active.get("count") or 0),
        "pvp": pvp_payload,
        "expeditions": expeditions_payload,
        "records": records_payload,
    }
