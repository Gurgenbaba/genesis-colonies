"""Command Center panel payloads for World Map selection (GC-592)."""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence
from urllib.parse import urlencode

from game.fleet import list_active_movements
from game.fleet_calc import enrich_movement_timing
from game.models import get_planet_owner_id
from game.number_format import fmt_int_compact
from game.resources import update_planet_resources

from .location_actions import build_location_actions
from .repository import get_planet_row

_ACTION_ALIASES: Dict[str, str] = {
    "mines": "buildings",
    "planet_tech": "evolution",
    "storage": "logistics",
    "routes": "logistics",
    "overview": "overview",
}

_QUICK_GRID: Sequence[tuple[str, str]] = (
    ("buildings", "location_action_buildings"),
    ("research", "location_action_research"),
    ("shipyard", "location_action_shipyard"),
    ("fleet", "location_action_fleet"),
    ("evolution", "location_action_evolution"),
    ("logistics", "location_action_storage"),
)

_ACTION_NAV_MODULE: Dict[str, str] = {
    "buildings": "buildings",
    "research": "research",
    "shipyard": "shipyard",
    "fleet": "fleet",
    "evolution": "planet_evolution",
    "logistics": "logistics",
}

_ACTION_QUEUE_SLOT: Dict[str, str] = {
    "buildings": "build",
    "research": "research",
    "shipyard": "shipyard",
}

_STATUS_FREE = "free"
_STATUS_QUEUE = "queue_active"
_STATUS_BLOCKED = "blocked"
_STATUS_RECOMMENDED = "recommended"

_FLEET_ICON_OUTBOUND = "▶"
_FLEET_ICON_RETURN = "↩"
_FLEET_ICON_HOLD = "🛡"

_ACTIVITY_FEED_LIMIT = 5
_FEED_HREF_BY_KIND: Dict[str, str] = {
    "build": "/buildings",
    "research": "/research",
    "shipyard": "/shipyard",
    "fleet": "/fleet",
    "combat": "/messages",
    "expedition": "/messages",
    "espionage": "/messages",
    "system": "/messages",
    "logistics": "/logistics",
}
_FEED_ICON_BY_KIND: Dict[str, str] = {
    "build": "🏗",
    "research": "🔬",
    "shipyard": "⚓",
    "fleet": "▶",
    "combat": "⚔",
    "expedition": "◌",
    "espionage": "👁",
    "system": "✉",
    "logistics": "📦",
}
_FEED_LABEL_BY_KIND: Dict[str, str] = {
    "build": "command_center_feed_build_active",
    "research": "command_center_feed_research_active",
    "shipyard": "command_center_feed_shipyard_active",
    "fleet": "command_center_feed_fleet_active",
    "combat": "command_center_feed_combat_report",
    "expedition": "command_center_feed_expedition_report",
    "espionage": "command_center_feed_spy_report",
    "system": "command_center_feed_message",
    "logistics": "command_center_feed_logistics",
}
_REPORT_MESSAGE_CATEGORIES = frozenset({"combat", "expedition", "espionage"})


def _rate_per_hour(rate_per_sec: float, ratio: float, prod_speed: float = 1.0) -> int:
    return int(max(0, float(rate_per_sec) * float(ratio) * float(prod_speed) * 3600.0))


def _format_rate(rate: int) -> str:
    if rate <= 0:
        return "+0/h"
    return f"+{fmt_int_compact(rate)}/h"


def _build_resources_block(
    planet: Mapping[str, Any],
    *,
    ratio: float,
    m_rate: float,
    c_rate: float,
    fc_rate: float,
    prod_speed: float,
) -> List[Dict[str, Any]]:
    return [
        {
            "key": "metal",
            "short": "Fe",
            "amount": fmt_int_compact(planet.get("metal", 0)),
            "rate": _format_rate(_rate_per_hour(m_rate, 1.0, prod_speed)),
        },
        {
            "key": "crystal",
            "short": "Cr",
            "amount": fmt_int_compact(planet.get("crystal", 0)),
            "rate": _format_rate(_rate_per_hour(c_rate, 1.0, prod_speed)),
        },
        {
            "key": "fuel_cells",
            "short": "Fuel",
            "amount": fmt_int_compact(planet.get("fuel_cells", 0)),
            "rate": _format_rate(_rate_per_hour(fc_rate, 1.0, prod_speed)),
        },
    ]


def _fleet_label(movement: Mapping[str, Any]) -> str:
    wt = movement.get("world_target") if isinstance(movement.get("world_target"), dict) else {}
    name = str(wt.get("target_name") or "").strip()
    if not name:
        name = str(movement.get("target_coords") or movement.get("origin_name") or "").strip()
    mission = str(movement.get("mission_type") or "transport")
    mission_key = f"fleet_mission_{mission}"
    if name:
        return f"{mission_key}|{name}"
    return mission_key


def _fleet_icon(phase: str, mission: str) -> str:
    phase_key = str(phase or "").lower()
    if phase_key == "returning":
        return _FLEET_ICON_RETURN
    if phase_key in ("holding", "hold", "stationed") or mission == "hold":
        return _FLEET_ICON_HOLD
    return _FLEET_ICON_OUTBOUND


def _build_fleets_block(
    planet_id: int,
    movements: Sequence[Mapping[str, Any]],
    *,
    now: float,
) -> List[Dict[str, Any]]:
    pid = int(planet_id)
    rows: List[Dict[str, Any]] = []
    for mv in movements or []:
        if not isinstance(mv, dict):
            continue
        origin_id = int(mv.get("origin_planet_id") or 0)
        target_id = int(mv.get("target_planet_id") or 0)
        if origin_id != pid and target_id != pid:
            continue
        enriched = enrich_movement_timing(mv, now=now)
        mission = str(mv.get("mission_type") or "transport")
        phase = str(enriched.get("phase") or enriched.get("leg_phase") or "")
        rows.append(
            {
                "icon": _fleet_icon(phase, mission),
                "label_key": _fleet_label(mv),
                "href": "/fleet",
            }
        )
    if not rows:
        rows.append(
            {
                "icon": _FLEET_ICON_HOLD,
                "label_key": "command_center_fleet_ready",
                "href": "/defense",
            }
        )
    return rows[:4]


def _recommended_action_keys(role_key: str, *, is_homeworld: bool) -> frozenset[str]:
    from .sidebar_nav import _HOMEWORLD_ROLE_KEYS, _ROLE_PROMINENT

    role = "homeworld" if is_homeworld else str(role_key or "general").strip().lower()
    if is_homeworld or role in _HOMEWORLD_ROLE_KEYS:
        return frozenset({"buildings", "research", "evolution"})

    out: set[str] = set()
    for nav_mod in _ROLE_PROMINENT.get(role, ()):
        for action_key, mapped in _ACTION_NAV_MODULE.items():
            if mapped == nav_mod:
                out.add(action_key)
                break
    return frozenset(out)


def _queue_summary_full(summary: Mapping[str, Any]) -> bool:
    count = int(summary.get("count") or 0)
    limit = int(summary.get("limit") or 1)
    return limit > 0 and count >= limit


def _fleet_has_active_movements(fleets: Sequence[Mapping[str, Any]]) -> bool:
    if not fleets:
        return False
    if len(fleets) == 1:
        label = str(fleets[0].get("label_key") or "")
        if label == "command_center_fleet_ready":
            return False
    return True


def _resolve_action_card_status(
    action_key: str,
    *,
    queue_row: Optional[Mapping[str, Any]],
    queue_full: bool,
    recommended: bool,
    fleet_active: bool,
    research_applies: bool,
) -> Dict[str, Any]:
    card: Dict[str, Any] = {
        "status": _STATUS_FREE,
        "status_key": "command_center_action_status_free",
    }

    if action_key == "fleet":
        if fleet_active:
            card["status"] = _STATUS_QUEUE
            card["status_key"] = "command_center_action_status_fleet_active"
        elif recommended:
            card["status"] = _STATUS_RECOMMENDED
            card["status_key"] = "command_center_action_status_recommended"
        return card

    if action_key == "research" and not research_applies:
        card["status_key"] = "command_center_action_status_other_planet"
        return card

    if action_key in _ACTION_QUEUE_SLOT:
        active = bool(queue_row and str(queue_row.get("state") or "") == "active")
        if queue_full and not active:
            card["status"] = _STATUS_BLOCKED
            card["status_key"] = "command_center_action_status_blocked"
            return card
        if active:
            card["status"] = _STATUS_QUEUE
            card["status_key"] = "command_center_action_status_queue_active"
            finish_at = int(queue_row.get("countdown_at") or queue_row.get("finish_at") or 0)
            if finish_at:
                card["countdown_at"] = finish_at
                card["remaining"] = int(queue_row.get("remaining") or 0)
            detail_key = str(queue_row.get("label_key") or "").strip()
            if detail_key:
                card["detail_key"] = detail_key
            return card

    if recommended:
        card["status"] = _STATUS_RECOMMENDED
        card["status_key"] = "command_center_action_status_recommended"
    return card


def _build_quick_actions(
    actions: Sequence[Mapping[str, str]],
    *,
    role_key: str,
    is_homeworld: bool,
    queues: Optional[Sequence[Mapping[str, Any]]] = None,
    queue_meta: Optional[Mapping[str, Any]] = None,
    fleets: Optional[Sequence[Mapping[str, Any]]] = None,
    research_applies: bool = True,
) -> List[Dict[str, Any]]:
    source = list(actions) if actions else build_location_actions(role_key, is_homeworld=is_homeworld)
    by_slot: Dict[str, Dict[str, str]] = {}
    for row in source:
        action_key = str(row.get("action_key") or "")
        slot = _ACTION_ALIASES.get(action_key, action_key)
        if slot in by_slot:
            continue
        by_slot[slot] = {
            "action_key": slot,
            "label_key": str(row.get("label_key") or ""),
            "href": str(row.get("href") or "/overview"),
            "icon": str(row.get("icon") or ""),
        }

    queue_by_key = {
        str(row.get("key") or ""): row
        for row in (queues or [])
        if isinstance(row, Mapping)
    }
    meta = dict(queue_meta or {})
    recommended = _recommended_action_keys(role_key, is_homeworld=is_homeworld)
    fleet_active = _fleet_has_active_movements(fleets or ())

    grid: List[Dict[str, Any]] = []
    for slot, fallback_label in _QUICK_GRID:
        picked = by_slot.get(slot)
        if not picked:
            continue
        queue_slot = _ACTION_QUEUE_SLOT.get(slot, "")
        queue_row = queue_by_key.get(queue_slot) if queue_slot else None
        slot_meta = meta.get(queue_slot) if queue_slot else {}
        queue_full = bool(slot_meta.get("full")) if isinstance(slot_meta, Mapping) else False

        card = {
            "action_key": slot,
            "label_key": picked.get("label_key") or fallback_label,
            "href": picked.get("href") or "/overview",
            "icon": picked.get("icon") or "",
        }
        card.update(
            _resolve_action_card_status(
                slot,
                queue_row=queue_row,
                queue_full=queue_full,
                recommended=slot in recommended,
                fleet_active=fleet_active,
                research_applies=research_applies,
            )
        )
        grid.append(card)
    return grid


def _fleet_prefill_href(
    mission: str,
    *,
    world_key: str = "",
    planet_id: int = 0,
    target_type: str = "",
) -> str:
    """Build canonical /fleet prefill URL (GC-598 — no new fleet pipeline)."""
    params: Dict[str, str] = {}
    m = str(mission or "").strip().lower()
    if m:
        params["mission"] = m
    wk = str(world_key or "").strip()
    if wk:
        params["world_key"] = wk
    pid = int(planet_id or 0)
    if pid:
        params["target_planet_id"] = str(pid)
    tt = str(target_type or "").strip()
    if tt:
        params["target_type"] = tt
    query = urlencode(params)
    return f"/fleet?{query}" if query else "/fleet"


def _mission_action_row(
    mission: str,
    *,
    label_key: str = "",
    enabled: bool = True,
    blocked_reason_key: str = "",
    world_key: str = "",
    planet_id: int = 0,
    target_type: str = "",
    action_key: str = "",
) -> Dict[str, Any]:
    m = str(mission or "").strip().lower()
    ak = str(action_key or m).strip().lower()
    row: Dict[str, Any] = {
        "action_key": ak,
        "mission": m,
        "label_key": label_key or f"fleet_mission_{m}",
        "enabled": bool(enabled),
        "blocked_reason_key": str(blocked_reason_key or ""),
        "href": _fleet_prefill_href(
            m,
            world_key=world_key,
            planet_id=planet_id,
            target_type=target_type,
        ),
    }
    if world_key:
        row["world_key"] = world_key
    if planet_id:
        row["planet_id"] = int(planet_id)
    if target_type:
        row["target_type"] = target_type
    return row


def _resolve_planet_world_key(planet_id: int, *, conn: sqlite3.Connection) -> str:
    pid = int(planet_id or 0)
    if not pid:
        return ""
    row = get_planet_row(pid, conn=conn)
    if not row:
        return ""
    return str(row.get("world_key") or "").strip()


def _build_colony_mission_actions(
    planet_id: int,
    *,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    """Own-colony fleet missions for World Inspector (GC-598)."""
    pid = int(planet_id or 0)
    if not pid:
        return []
    world_key = _resolve_planet_world_key(pid, conn=conn)
    target_type = "world_colony" if world_key else "planet"
    return [
        _mission_action_row(
            mission,
            world_key=world_key,
            planet_id=pid,
            target_type=target_type,
        )
        for mission in ("transport", "deploy", "collect")
    ]


def _build_foreign_mission_actions(
    *,
    world_key: str,
    planet_id: int,
    viewer_player_id: int,
    owner_player_id: int,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    """Spy / attack (or ally transport) for foreign map targets (GC-598)."""
    wk = str(world_key or "").strip()
    pid = int(planet_id or 0)
    if not wk and not pid:
        return []
    if not wk and pid:
        wk = _resolve_planet_world_key(pid, conn=conn)

    from game.fleet import are_players_allied

    viewer_id = int(viewer_player_id)
    owner_id = int(owner_player_id)
    if owner_id and are_players_allied(viewer_id, owner_id, conn=conn):
        return [
            _mission_action_row(
                "transport",
                world_key=wk,
                planet_id=pid,
                target_type="world_colony" if wk else "ally_planet",
            ),
        ]

    target_type = "enemy_colony" if wk else "foreign_planet"
    return [
        _mission_action_row(
            "spy",
            world_key=wk,
            planet_id=pid,
            target_type=target_type,
        ),
        _mission_action_row(
            "attack",
            world_key=wk,
            planet_id=pid,
            target_type=target_type,
        ),
    ]


def _build_expedition_site_mission_actions(
    node: Mapping[str, Any],
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    wk = str(node.get("world_key") or "").strip()
    if not wk or node.get("is_claimed"):
        return []

    if node.get("is_salvage") or expedition_site_kind(node) == "wreckage_field":
        from .world_colonization import build_world_salvage_preview

        preview = build_world_salvage_preview(int(player_id), wk, conn=conn)
        enabled = bool(preview.get("can_start_salvage"))
        blocked = str(preview.get("block_reason") or "no_expedition_ships") if not enabled else ""
        return [
            _mission_action_row(
                "expedition",
                label_key="strategic_world_btn_salvage",
                action_key="salvage",
                enabled=enabled,
                blocked_reason_key=blocked,
                world_key=wk,
                target_type="wreckage",
            ),
        ]

    if node.get("is_expedition") or expedition_site_kind(node) in {
        "expedition_zone",
        "anomaly_zone",
        "ruins_world",
    }:
        return [
            _mission_action_row(
                "expedition",
                label_key="strategic_world_btn_expedition",
                world_key=wk,
                target_type="expedition_world",
            ),
        ]
    return []


def _build_strategic_world_mission_actions(
    node: Mapping[str, Any],
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    if is_expedition_site_node(node):
        return _build_expedition_site_mission_actions(node, player_id, conn=conn)

    wk = str(node.get("world_key") or "").strip()
    if not wk or node.get("is_claimed") or not node.get("is_colonizable"):
        return []

    from .world_colonization import build_world_colonize_preview

    preview = build_world_colonize_preview(int(player_id), wk, conn=conn)
    enabled = bool(preview.get("can_colonize"))
    blocked = str(preview.get("block_reason") or "fleet_error_colony_limit_reached") if not enabled else ""
    return [
        _mission_action_row(
            "colonize",
            label_key="strategic_world_btn_colonize",
            enabled=enabled,
            blocked_reason_key=blocked,
            world_key=wk,
            target_type="strategic_world",
        ),
    ]


def _build_colony_primary_action(planet_id: int) -> Dict[str, Any]:
    pid = int(planet_id or 0)
    if not pid:
        return {"action_key": "none", "label_key": "", "enabled": False}
    return {
        "action_key": "open_colony",
        "label_key": "command_map_btn_open_colony",
        "planet_id": pid,
        "enabled": True,
    }


def _build_colony_status_block(
    planet_id: int,
    player_id: int,
    *,
    conn: sqlite3.Connection,
    now: float,
) -> Dict[str, Any]:
    """Planet level, queue indicators — server-only (GC-592)."""
    from game.buildings import get_build_queue_status_for_planet
    from game.overview_page import build_activity_lines
    from game.research import _research_resource_planet, get_research_status

    from .planet_level import level_progress

    pid = int(planet_id)
    uid = int(player_id)
    level, xp, xp_remaining = level_progress(pid, conn)

    build_queue = get_build_queue_status_for_planet(pid, conn=conn, skip_finish=True)
    bq_summary = build_queue.get("summary") if isinstance(build_queue.get("summary"), dict) else {}

    research: Dict[str, Any] = {"active": None, "summary": {"count": 0, "limit": 1}}
    research_applies = False
    try:
        resource_planet = _research_resource_planet(uid, conn)
        research_applies = int(resource_planet["id"]) == pid
        if research_applies:
            research = get_research_status(uid, conn=conn, skip_finish=True)
    except Exception:
        pass
    rs_summary = research.get("summary") if isinstance(research.get("summary"), dict) else {}

    shipyard_queue: Dict[str, Any] = {"queue": [], "summary": {"count": 0, "limit": 1}}
    try:
        from game.shipyard import get_shipyard_level
        from game.shipyard_queue import shipyard_queue_for_client, shipyard_queue_table_ready

        if shipyard_queue_table_ready(conn):
            sy_level = get_shipyard_level(uid, pid, conn=conn)
            shipyard_queue = shipyard_queue_for_client(uid, pid, sy_level, conn=conn)
    except Exception:
        pass
    sy_summary = shipyard_queue.get("summary") if isinstance(shipyard_queue.get("summary"), dict) else {}

    activities = build_activity_lines(
        build_queue,
        research,
        shipyard_queue=shipyard_queue,
    )
    queues = [row for row in activities if str(row.get("key") or "") in ("build", "research", "shipyard")]

    return {
        "progress": {
            "level": int(level),
            "xp": int(xp),
            "xp_remaining": int(xp_remaining),
        },
        "queues": queues,
        "queue_meta": {
            "build": {"full": _queue_summary_full(bq_summary)},
            "research": {
                "full": _queue_summary_full(rs_summary),
                "applies": research_applies,
            },
            "shipyard": {"full": _queue_summary_full(sy_summary)},
        },
        "research_applies": research_applies,
    }


def _colony_header_fields(
    planet: Mapping[str, Any],
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    from game.galaxy import GalaxyCoordinateError, get_planet_coordinates

    from .empire_identity import empire_identity_for_planet

    identity = empire_identity_for_planet(dict(planet), conn=conn)
    coords_formatted = ""
    try:
        coords_formatted = get_planet_coordinates(planet)["formatted"]
    except GalaxyCoordinateError:
        coords_formatted = ""

    return {
        "name": str(planet.get("name") or ""),
        "coordinates_formatted": coords_formatted,
        "role_label_key": str(
            identity.get("identity_title_key") or identity.get("empire_role_label_key") or ""
        ),
        "role_icon": str(identity.get("empire_role_icon") or ""),
    }


def _build_news_block(player_id: int, *, conn: sqlite3.Connection, limit: int = 3) -> List[Dict[str, str]]:
    try:
        from game.messages import list_messages

        payload = list_messages(int(player_id), limit=limit, offset=0)
        if not payload.get("ok"):
            return []
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        rows = data.get("messages")
        if not isinstance(rows, list):
            return []
        out: List[Dict[str, str]] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            subject = str(row.get("subject") or "").strip()
            if subject:
                out.append({"text": subject, "href": "/messages"})
            else:
                cat = str(row.get("category") or "system")
                out.append({"label_key": f"messages.category.{cat}", "href": "/messages"})
        return out
    except Exception:
        return []


def _feed_id(
    kind: str,
    *,
    label_key: Optional[str] = None,
    detail_key: Optional[str] = None,
    text: Optional[str] = None,
    countdown_at: Optional[int] = None,
) -> str:
    return "|".join(
        [
            str(kind or ""),
            str(label_key or ""),
            str(detail_key or ""),
            str(text or ""),
            str(countdown_at or ""),
        ]
    )


def _feed_entry(
    kind: str,
    *,
    label_key: Optional[str] = None,
    detail_key: Optional[str] = None,
    text: Optional[str] = None,
    href: Optional[str] = None,
    icon: Optional[str] = None,
    countdown_at: Optional[int] = None,
    remaining: Optional[int] = None,
    sort_rank: int = 50,
    sort_ts: float = 0.0,
    presentation: Optional[str] = None,
) -> Dict[str, Any]:
    slot = str(kind or "system").strip().lower()
    entry: Dict[str, Any] = {
        "kind": slot,
        "feed_id": _feed_id(
            slot,
            label_key=label_key,
            detail_key=detail_key,
            text=text,
            countdown_at=countdown_at,
        ),
        "icon": icon or _FEED_ICON_BY_KIND.get(slot, "•"),
        "label_key": label_key or _FEED_LABEL_BY_KIND.get(slot, "command_center_feed_message"),
        "detail_key": detail_key or None,
        "text": text or None,
        "href": href or _FEED_HREF_BY_KIND.get(slot, "/overview"),
        "countdown_at": int(countdown_at) if countdown_at else None,
        "remaining": int(remaining) if remaining is not None else None,
        "sort_rank": int(sort_rank),
        "sort_ts": float(sort_ts or 0.0),
    }
    if presentation:
        entry["presentation"] = str(presentation).strip()
    return entry


def _feed_entries_from_queues(queues: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in queues or []:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("key") or "").strip().lower()
        if key not in {"build", "research", "shipyard"} or str(row.get("state") or "") != "active":
            continue
        out.append(
            _feed_entry(
                key,
                detail_key=str(row.get("label_key") or "").strip() or None,
                countdown_at=int(row.get("countdown_at") or row.get("finish_at") or 0) or None,
                remaining=int(row.get("remaining") or 0),
                sort_rank=10,
                sort_ts=float(row.get("countdown_at") or row.get("finish_at") or 0),
            )
        )
    return out


def _feed_entries_from_fleets(
    planet_id: int,
    movements: Sequence[Mapping[str, Any]],
    *,
    now: float,
) -> List[Dict[str, Any]]:
    pid = int(planet_id)
    out: List[Dict[str, Any]] = []
    for mv in movements or []:
        if not isinstance(mv, Mapping):
            continue
        status = str(mv.get("status") or "")
        if status not in ("outbound", "holding", "returning"):
            continue
        origin_id = int(mv.get("origin_planet_id") or 0)
        target_id = int(mv.get("target_planet_id") or 0)
        if origin_id != pid and target_id != pid:
            continue
        enriched = enrich_movement_timing(mv, now=now)
        mission = str(mv.get("mission_type") or "transport")
        fleet_label = _fleet_label(mv)
        out.append(
            _feed_entry(
                "fleet",
                detail_key=fleet_label,
                icon=_fleet_icon(
                    str(enriched.get("phase") or enriched.get("leg_phase") or ""),
                    mission,
                ),
                countdown_at=int(enriched.get("countdown_at") or 0) or None,
                remaining=int(enriched.get("remaining_seconds") or 0),
                sort_rank=20,
                sort_ts=float(enriched.get("countdown_at") or now),
                presentation="expedition_launch" if mission == "expedition" else None,
            )
        )
    return out


def _feed_entries_from_messages(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    try:
        from game.messages import list_messages

        payload = list_messages(int(player_id), limit=max(limit * 2, 8), offset=0)
        if not payload.get("ok"):
            return []
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        rows = data.get("messages")
        if not isinstance(rows, list):
            return []
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        cat = str(row.get("category") or "system").strip().lower()
        subject = str(row.get("subject") or "").strip()
        created_at = float(row.get("created_at") or 0)
        if cat in _REPORT_MESSAGE_CATEGORIES:
            out.append(
                _feed_entry(
                    cat,
                    text=subject or None,
                    sort_rank=40,
                    sort_ts=created_at,
                    presentation="discovery" if cat == "expedition" else None,
                )
            )
            continue
        if cat == "system" and subject and len(out) < limit:
            out.append(
                _feed_entry(
                    "system",
                    text=subject,
                    sort_rank=45,
                    sort_ts=created_at,
                )
            )
        if len(out) >= limit:
            break
    return out[:limit]


def _build_activity_feed(
    planet_id: int,
    player_id: int,
    *,
    queues: Sequence[Mapping[str, Any]],
    movements: Sequence[Mapping[str, Any]],
    conn: sqlite3.Connection,
    now: float,
    limit: int = _ACTIVITY_FEED_LIMIT,
) -> List[Dict[str, Any]]:
    """Unified activity feed from queues, fleets, and inbox (GC-594)."""
    entries: List[Dict[str, Any]] = []
    entries.extend(_feed_entries_from_queues(queues))
    entries.extend(_feed_entries_from_fleets(planet_id, movements, now=now))
    entries.extend(_feed_entries_from_messages(player_id, conn=conn, limit=limit))

    def _sort_key(row: Mapping[str, Any]) -> tuple[int, float]:
        rank = int(row.get("sort_rank") or 99)
        ts = float(row.get("sort_ts") or 0.0)
        if row.get("countdown_at"):
            return (rank, float(row.get("countdown_at") or 0))
        return (rank, -ts)

    entries.sort(key=_sort_key)
    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for row in entries:
        token = "|".join(
            [
                str(row.get("kind") or ""),
                str(row.get("label_key") or ""),
                str(row.get("text") or ""),
                str(row.get("detail_key") or ""),
                str(row.get("countdown_at") or ""),
            ]
        )
        if token in seen:
            continue
        seen.add(token)
        deduped.append(row)
        if len(deduped) >= int(limit):
            break
    return deduped


def build_colony_command_center(
    planet_id: int,
    player_id: int,
    *,
    conn: sqlite3.Connection,
    role_key: str = "general",
    is_homeworld: bool = False,
    is_newly_colonized: bool = False,
    quick_actions: Optional[Sequence[Mapping[str, str]]] = None,
    fleet_movements: Optional[Sequence[Mapping[str, Any]]] = None,
) -> Dict[str, Any]:
    """Server snapshot for own-colony Command Center panel (GC-592A)."""
    pid = int(planet_id)
    uid = int(player_id)
    row = get_planet_row(pid, conn=conn)
    if not row or int(get_planet_owner_id(pid) or 0) != uid:
        return {}

    planet = dict(row)
    planet, _buildings, ratio, _et, _eu = update_planet_resources(planet, conn=conn, skip_queue_finish=True)
    from game.effects import get_effect_resolver
    from game.models import get_game_settings

    settings = get_game_settings(conn=conn)
    prod_speed = float(settings.get("production_speed", 1.0) or 1.0)

    resolver = get_effect_resolver(
        uid,
        buildings=_buildings,
        conn=conn,
        force_refresh=False,
    )
    m_rate, c_rate = resolver.production_rates_per_sec(ratio)
    fc_rate = resolver.fuel_cells_rate_per_sec(ratio)

    movements = fleet_movements if fleet_movements is not None else list_active_movements(uid, conn=conn)
    now = time.time()

    status_key = ""
    if is_newly_colonized:
        status_key = "command_map_badge_newly_colonized"

    status_block = _build_colony_status_block(pid, uid, conn=conn, now=now)
    header = _colony_header_fields(planet, conn=conn)
    fleet_rows = _build_fleets_block(pid, movements, now=now)

    payload = {
        "panel_kind": "colony",
        "planet_id": pid,
        "is_own": True,
        **header,
        "primary_action": _build_colony_primary_action(pid),
        "status_key": status_key,
        "progress": status_block.get("progress") or {},
        "queues": status_block.get("queues") or [],
        "resources": _build_resources_block(
            planet,
            ratio=float(ratio or 0),
            m_rate=float(m_rate or 0),
            c_rate=float(c_rate or 0),
            fc_rate=float(fc_rate or 0),
            prod_speed=prod_speed,
        ),
        "fleets": fleet_rows,
        "quick_actions": _build_quick_actions(
            quick_actions or [],
            role_key=str(role_key or "general"),
            is_homeworld=bool(is_homeworld),
            queues=status_block.get("queues") or [],
            queue_meta=status_block.get("queue_meta") or {},
            fleets=fleet_rows,
            research_applies=bool(status_block.get("research_applies")),
        ),
        "activity_feed": _build_activity_feed(
            pid,
            uid,
            queues=status_block.get("queues") or [],
            movements=movements,
            conn=conn,
            now=now,
        ),
        "news": _build_news_block(uid, conn=conn),
        "mission_actions": _build_colony_mission_actions(pid, conn=conn),
    }
    from game.world_inspector import attach_debris_to_inspector_payload

    attach_debris_to_inspector_payload(payload, conn=conn, planet_id=pid)
    wk = str(planet.get("world_key") or "").strip()
    if wk or not is_homeworld:
        from .expansion_phase import compact_expansion_phase_payload, resolve_expansion_phase

        payload["expansion_phase"] = compact_expansion_phase_payload(
            resolve_expansion_phase(player_id=uid, planet_id=pid, world_key=wk or None, conn=conn)
        )
    return payload


def _strategic_status_key(node: Mapping[str, Any]) -> str:
    if node.get("is_claimed"):
        return "strategic_world_inspector_status_settled"
    if node.get("is_expedition"):
        return str(node.get("familiarity_label_key") or "world_familiarity_unknown")
    if node.get("is_salvage"):
        return "strategic_world_inspector_status_salvage"
    if node.get("is_expedition_prepared"):
        return "strategic_world_inspector_status_prepared"
    if not node.get("is_colonizable"):
        return "strategic_world_inspector_status_not_colonizable"
    return "strategic_world_inspector_status"


def _build_strategic_details(node: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    risk_key = str(node.get("risk_key") or "").strip()
    if risk_key:
        rows.append(
            {
                "label_key": "expansion_site_inspector_risk",
                "value_key": risk_key,
                "tone": str(node.get("risk_level") or "low"),
            }
        )
    promise_key = str(node.get("promise_key") or "").strip()
    if promise_key:
        rows.append({"label_key": "expansion_site_inspector_promise", "value_key": promise_key})
    reward_key = str(node.get("reward_hint_key") or "").strip()
    if reward_key:
        rows.append({"label_key": "strategic_world_inspector_bonus", "value_key": reward_key})
    future_key = str(node.get("future_action_key") or "").strip()
    if future_key:
        rows.append({"label_key": "strategic_world_inspector_future", "value_key": future_key})
    return rows


def _build_familiarity_block(node: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    if not node.get("is_expedition"):
        return None
    next_ms = node.get("next_milestone")
    return {
        "label_key": str(node.get("familiarity_label_key") or "world_familiarity_unknown"),
        "status": str(node.get("familiarity_status") or "unknown"),
        "expedition_count": int(node.get("expedition_count") or 0),
        "next_milestone": int(next_ms) if next_ms is not None else None,
        "title_key": "world_progress_inspector_title",
        "outpost_prepared": str(node.get("familiarity_status") or "") == "outpost_prepared",
    }


def _build_expedition_activity_block(node: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    status = str(node.get("expedition_status") or "idle")
    if status == "idle":
        return None
    is_salvage = bool(node.get("is_salvage"))
    block: Dict[str, Any] = {"status": status, "is_salvage": is_salvage}
    if status == "expedition_active":
        block["status_key"] = (
            "world_salvage_status_active" if is_salvage else "world_expedition_status_active"
        )
    elif status == "expedition_returning":
        block["status_key"] = (
            "world_salvage_status_returning" if is_salvage else "world_expedition_status_returning"
        )
    elif status == "recently_reported":
        block["status_key"] = (
            "world_salvage_status_report" if is_salvage else "world_expedition_status_report"
        )
        event_key = str(node.get("expedition_event_label_key") or "").strip()
        if event_key:
            block["report_event_key"] = event_key
    eta_at = node.get("expedition_eta_at")
    if eta_at:
        block["eta_at"] = float(eta_at)
    return block


def _build_strategic_primary_action(
    node: Mapping[str, Any],
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    wk = str(node.get("world_key") or "").strip()
    none = {"action_key": "none", "label_key": "", "world_key": wk, "enabled": False, "blocked_reason_key": ""}
    if not wk or node.get("is_claimed"):
        return none

    if node.get("is_colonizable"):
        from .world_colonization import check_colony_limit_available

        ok_limit, limit_reason = check_colony_limit_available(int(player_id), conn=conn)
        return {
            "action_key": "colonize",
            "label_key": "strategic_world_btn_colonize",
            "world_key": wk,
            "enabled": ok_limit,
            "blocked_reason_key": str(limit_reason or "fleet_error_max_colonies_reached") if not ok_limit else "",
        }
    return none


def _build_strategic_hints(
    node: Mapping[str, Any],
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    hints: List[Dict[str, Any]] = []
    if node.get("is_colonizable") and not node.get("is_claimed"):
        from game.logic import get_planet_limit_block

        limit = get_planet_limit_block(int(player_id), conn=conn)
        hints.append({"label_key": "strategic_world_colony_limit", "vars": dict(limit)})
        if int(limit.get("current", 0)) >= int(limit.get("max", 1)):
            hints.append({"label_key": "fleet_error_max_colonies_reached"})
    if (
        not node.get("is_colonizable")
        and not node.get("is_claimed")
    ):
        hints.append({"label_key": "strategic_world_inspector_noncolonizable_hint"})
    return hints


EXPEDITION_SITE_WORLD_TYPES = frozenset(
    {
        "expedition_zone",
        "anomaly_zone",
        "ruins_world",
        "wreckage_field",
    }
)


def is_expedition_site_node(node: Mapping[str, Any]) -> bool:
    world_type = str(node.get("world_type") or "")
    if world_type in EXPEDITION_SITE_WORLD_TYPES:
        return True
    return bool(node.get("is_expedition") or node.get("is_salvage"))


def expedition_site_kind(node: Mapping[str, Any]) -> str:
    world_type = str(node.get("world_type") or "")
    if world_type in EXPEDITION_SITE_WORLD_TYPES:
        return world_type
    if node.get("is_salvage"):
        return "wreckage_field"
    return "expedition_zone"


def _expedition_site_status_key(node: Mapping[str, Any]) -> str:
    return f"command_center_expedition_status_{expedition_site_kind(node)}"


def _build_expedition_primary_action(node: Mapping[str, Any]) -> Dict[str, Any]:
    wk = str(node.get("world_key") or "").strip()
    none = {"action_key": "none", "label_key": "", "world_key": wk, "enabled": False, "blocked_reason_key": ""}
    if not wk or node.get("is_claimed"):
        return none
    if node.get("is_salvage") or expedition_site_kind(node) == "wreckage_field":
        return {
            "action_key": "salvage",
            "label_key": "strategic_world_btn_salvage",
            "world_key": wk,
            "enabled": True,
            "blocked_reason_key": "",
        }
    if node.get("is_expedition") or expedition_site_kind(node) in {
        "expedition_zone",
        "anomaly_zone",
        "ruins_world",
    }:
        return {
            "action_key": "expedition",
            "label_key": "strategic_world_btn_expedition",
            "world_key": wk,
            "enabled": True,
            "blocked_reason_key": "",
        }
    return none


def _build_expedition_hints(node: Mapping[str, Any]) -> List[Dict[str, Any]]:
    hints: List[Dict[str, Any]] = []
    if node.get("is_salvage") or expedition_site_kind(node) == "wreckage_field":
        hints.append({"label_key": "strategic_world_inspector_salvage_prepare", "salvage_prepare": True})
    action = _build_expedition_primary_action(node)
    if action.get("action_key") == "none":
        hints.append({"label_key": "command_center_expedition_unavailable_hint"})
    return hints


def build_expedition_site_command_center(
    node: Mapping[str, Any],
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Server snapshot for expedition / wreckage Command Center panel (GC-592D)."""
    if str(node.get("node_kind") or "") != "world_field":
        return {}
    if node.get("is_claimed"):
        return {}
    if not is_expedition_site_node(node):
        return {}

    wk = str(node.get("world_key") or "").strip()
    if not wk:
        return {}

    site_kind = expedition_site_kind(node)
    familiarity = _build_familiarity_block(node) if node.get("is_expedition") else None

    return {
        "panel_kind": "expedition_site",
        "site_kind": site_kind,
        "world_key": wk,
        "name_key": str(node.get("name_key") or ""),
        "type_key": str(node.get("type_key") or ""),
        "icon": str(node.get("role_icon") or "✦"),
        "status_key": _expedition_site_status_key(node),
        "risk_key": str(node.get("risk_key") or ""),
        "risk_level": str(node.get("risk_level") or "low"),
        "details": _build_strategic_details(node),
        "familiarity": familiarity,
        "expedition_activity": _build_expedition_activity_block(node),
        "primary_action": _build_expedition_primary_action(node),
        "mission_actions": _build_expedition_site_mission_actions(node, int(player_id), conn=conn),
        "hints": _build_expedition_hints(node),
    }


def build_strategic_world_command_center(
    node: Mapping[str, Any],
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Server snapshot for colonizable strategic world Command Center panel (GC-592B)."""
    if str(node.get("node_kind") or "") != "world_field":
        return {}
    if node.get("is_claimed"):
        return {}

    if is_expedition_site_node(node):
        return build_expedition_site_command_center(node, player_id, conn=conn)

    wk = str(node.get("world_key") or "").strip()
    if not wk:
        return {}

    return {
        "panel_kind": "strategic_world",
        "world_key": wk,
        "name_key": str(node.get("name_key") or ""),
        "type_key": str(node.get("type_key") or ""),
        "icon": str(node.get("role_icon") or "✦"),
        "status_key": _strategic_status_key(node),
        "details": _build_strategic_details(node),
        "familiarity": None,
        "expedition_activity": None,
        "primary_action": _build_strategic_primary_action(node, int(player_id), conn=conn),
        "mission_actions": _build_strategic_world_mission_actions(node, int(player_id), conn=conn),
        "hints": _build_strategic_hints(node, int(player_id), conn=conn),
        "expansion_phase": _strategic_world_expansion_phase(wk, int(player_id), conn=conn),
    }


def _strategic_world_expansion_phase(
    world_key: str,
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    from .expansion_phase import compact_expansion_phase_payload, resolve_expansion_phase

    return compact_expansion_phase_payload(
        resolve_expansion_phase(player_id=int(player_id), world_key=str(world_key), conn=conn)
    )


_FOREIGN_CC_FORBIDDEN_KEYS = frozenset(
    {
        "resources",
        "fleets",
        "quick_actions",
        "news",
        "production",
        "defense",
        "ships",
        "fleet_movements",
        "metal",
        "crystal",
        "fuel_cells",
    }
)

_FOREIGN_NODE_KINDS = frozenset({"foreign_world_colony", "foreign_empire", "foreign_colony"})


def _resolve_foreign_planet_refs(
    node: Mapping[str, Any],
    *,
    conn: sqlite3.Connection,
) -> tuple[int, str]:
    pid = int(node.get("planet_id") or 0)
    wk = str(node.get("world_key") or "").strip()
    if pid and not wk:
        row = get_planet_row(pid, conn=conn)
        if row:
            wk = str(row.get("world_key") or "").strip()
    return pid, wk


def _public_alliance_label(owner_player_id: int, *, conn: sqlite3.Connection) -> str:
    try:
        from game.alliance import get_player_alliance

        row = get_player_alliance(int(owner_player_id), conn=conn)
        if not row:
            return ""
        tag = str(row.get("tag") or row.get("alliance_tag") or "").strip()
        name = str(row.get("name") or row.get("alliance_name") or "").strip()
        if tag and name:
            return f"[{tag}] {name}"
        return tag or name
    except Exception:
        return ""


def _public_strength_label(owner_player_id: int, *, conn: sqlite3.Connection) -> str:
    try:
        from game.ranking import get_player_score_row

        row = get_player_score_row(int(owner_player_id), conn=conn)
        if not row:
            return ""
        total = int(row.get("score_total") or 0)
        if total <= 0:
            return ""
        return fmt_int_compact(total)
    except Exception:
        return ""


def _foreign_status_key(node: Mapping[str, Any]) -> str:
    kind = str(node.get("node_kind") or "")
    if kind == "foreign_empire":
        return "command_center_foreign_status_empire"
    return "foreign_world_colony_status_settled"


def _build_foreign_details(
    node: Mapping[str, Any],
    *,
    conn: sqlite3.Connection,
    owner_player_id: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    owner_name = str(node.get("owner_username") or "").strip()
    if owner_name:
        rows.append(
            {
                "label_key": "world_map_inspector_player",
                "value_text": owner_name,
            }
        )

    coords = str(node.get("coordinates_formatted") or "").strip()
    if coords:
        rows.append(
            {
                "label_key": "world_map_inspector_coords",
                "value_text": coords,
            }
        )

    role_key = str(
        node.get("empire_role_label_key")
        or node.get("identity_title_key")
        or node.get("strategic_type_key")
        or ""
    ).strip()
    if role_key:
        rows.append({"label_key": "command_center_foreign_role", "value_key": role_key})

    alliance = _public_alliance_label(owner_player_id, conn=conn)
    if alliance:
        rows.append(
            {
                "label_key": "command_center_foreign_alliance",
                "value_text": alliance,
            }
        )

    strength = _public_strength_label(owner_player_id, conn=conn)
    if strength:
        rows.append(
            {
                "label_key": "command_center_foreign_strength",
                "value_text": strength,
            }
        )

    if str(node.get("node_kind") or "") == "foreign_empire":
        count = max(0, int(node.get("colony_count") or 0))
        rows.append(
            {
                "label_key": "world_map_inspector_colonies",
                "value_text": str(count),
            }
        )
        empire_name = str(node.get("empire_display_name") or "").strip()
        if empire_name:
            rows.append(
                {
                    "label_key": "world_map_inspector_empire",
                    "value_text": empire_name,
                }
            )
        influence = int(node.get("influence_pct") or 0)
        if influence > 0:
            rows.append(
                {
                    "label_key": "world_map_inspector_influence",
                    "value_text": f"{influence}%",
                }
            )

    return rows


def _build_foreign_actions(
    *,
    world_key: str,
    planet_id: int,
    viewer_player_id: int,
    owner_player_id: int,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    return _build_foreign_mission_actions(
        world_key=world_key,
        planet_id=planet_id,
        viewer_player_id=viewer_player_id,
        owner_player_id=owner_player_id,
        conn=conn,
    )


def build_foreign_colony_command_center(
    node: Mapping[str, Any],
    viewer_player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Public-only Command Center payload for foreign colonies (GC-592C)."""
    kind = str(node.get("node_kind") or "")
    if kind not in _FOREIGN_NODE_KINDS:
        return {}

    owner_id = int(node.get("owner_player_id") or 0)
    viewer_id = int(viewer_player_id)
    if not owner_id or owner_id == viewer_id:
        return {}

    planet_id, world_key = _resolve_foreign_planet_refs(node, conn=conn)
    if not planet_id and not world_key:
        return {}

    icon = str(node.get("empire_role_icon") or "🌍")
    homeworld_name = str(node.get("homeworld_name") or node.get("name") or "").strip()
    name = homeworld_name or str(node.get("owner_username") or "").strip()
    type_key = str(node.get("strategic_type_key") or "").strip()
    role_key = str(node.get("empire_role_label_key") or node.get("identity_title_key") or "").strip()
    panel_kind = "foreign_empire" if kind == "foreign_empire" else "foreign_colony"

    payload: Dict[str, Any] = {
        "panel_kind": panel_kind,
        "node_key": str(node.get("node_key") or ""),
        "planet_id": planet_id,
        "world_key": world_key,
        "name": name,
        "empire_display_name": str(node.get("empire_display_name") or "").strip(),
        "homeworld_name": homeworld_name,
        "influence_pct": int(node.get("influence_pct") or 0),
        "colony_count": max(0, int(node.get("colony_count") or 0)),
        "owner_username": str(node.get("owner_username") or "").strip(),
        "icon": icon,
        "status_key": _foreign_status_key(node),
        "role_label_key": role_key,
        "type_label_key": type_key,
        "details": _build_foreign_details(node, conn=conn, owner_player_id=owner_id),
        "mission_actions": _build_foreign_mission_actions(
            world_key=world_key,
            planet_id=planet_id,
            viewer_player_id=viewer_id,
            owner_player_id=owner_id,
            conn=conn,
        ),
        "actions": _build_foreign_actions(
            world_key=world_key,
            planet_id=planet_id,
            viewer_player_id=viewer_id,
            owner_player_id=owner_id,
            conn=conn,
        ),
        "hints": [{"label_key": "command_center_foreign_public_hint"}],
    }

    for forbidden in _FOREIGN_CC_FORBIDDEN_KEYS:
        payload.pop(forbidden, None)

    from game.world_inspector import attach_debris_to_inspector_payload

    attach_debris_to_inspector_payload(payload, conn=conn, planet_id=int(planet_id or 0))
    return payload


def attach_command_centers_to_nodes(
    nodes: List[Dict[str, Any]],
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> None:
    """Mutates map nodes in-place with command_center payloads (GC-592A–D)."""
    movements = list_active_movements(int(player_id), conn=conn)
    for node in nodes:
        kind = str(node.get("node_kind") or "")
        if kind == "colony":
            if not node.get("is_own", True):
                continue
            pid = int(node.get("planet_id") or 0)
            if not pid:
                continue
            role_key = str(node.get("empire_role_key") or "general")
            node["command_center"] = build_colony_command_center(
                pid,
                int(player_id),
                conn=conn,
                role_key=role_key,
                is_homeworld=bool(node.get("is_homeworld")) or role_key == "homeworld",
                is_newly_colonized=bool(node.get("is_newly_colonized")),
                quick_actions=node.get("actions") or [],
                fleet_movements=movements,
            )
        elif kind == "world_field":
            cc = build_strategic_world_command_center(node, int(player_id), conn=conn)
            if cc:
                node["command_center"] = cc
        elif kind == "expansion_site":
            site_key = str(node.get("site_key") or "").strip()
            if site_key:
                from .expansion_phase import compact_expansion_phase_payload, resolve_expansion_phase

                node["expansion_phase"] = compact_expansion_phase_payload(
                    resolve_expansion_phase(
                        player_id=int(player_id),
                        world_key=site_key,
                        conn=conn,
                    )
                )
        elif kind in _FOREIGN_NODE_KINDS:
            cc = build_foreign_colony_command_center(node, int(player_id), conn=conn)
            if cc:
                node["command_center"] = cc
