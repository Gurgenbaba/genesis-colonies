"""Expansion site unlock gates — homeworld level drives Command Map growth (GC-562, GC-567)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import sqlite3

from ..models import get_homeworld
from .planet_level import level_progress

# Ordered by required_homeworld_level — static definitions, no migration.
# layout_radius_world = distance from own hub on 4000×4000 canvas (GC-571F).
EXPANSION_SITES: Dict[str, Dict[str, Any]] = {
    "frontier_ix": {
        "label_key": "expansion_site_frontier_ix",
        "required_homeworld_level": 5,
        "region_key": "outer_rim",
        "layout_slot": "center",
        "layout_bearing_deg": 0,
        "layout_radius_world": 720.0,
        "role_icon": "🌌",
        "site_type": "outpost",
        "type_key": "expansion_site_type_outpost",
        "promise_key": "expansion_site_promise_frontier_ix",
        "risk_level": "low",
        "risk_key": "expansion_site_risk_low",
        "reward_hint_key": "expansion_site_reward_frontier_ix",
        "future_role_key": "expansion_site_future_role_frontier_ix",
    },
    "ancient_relay": {
        "label_key": "expansion_site_ancient_relay",
        "required_homeworld_level": 10,
        "region_key": "ancient_sector",
        "layout_slot": "west",
        "layout_bearing_deg": 55,
        "layout_radius_world": 840.0,
        "role_icon": "🏛",
        "site_type": "relay",
        "type_key": "expansion_site_type_relay",
        "promise_key": "expansion_site_promise_ancient_relay",
        "risk_level": "moderate",
        "risk_key": "expansion_site_risk_moderate",
        "reward_hint_key": "expansion_site_reward_ancient_relay",
        "future_role_key": "expansion_site_future_role_ancient_relay",
    },
    "archive_nexus": {
        "label_key": "expansion_site_archive_nexus",
        "required_homeworld_level": 15,
        "region_key": "ancient_sector",
        "layout_slot": "east",
        "layout_bearing_deg": 75,
        "layout_radius_world": 960.0,
        "role_icon": "📜",
        "site_type": "archive",
        "type_key": "expansion_site_type_archive",
        "promise_key": "expansion_site_promise_archive_nexus",
        "risk_level": "moderate",
        "risk_key": "expansion_site_risk_moderate",
        "reward_hint_key": "expansion_site_reward_archive_nexus",
        "future_role_key": "expansion_site_future_role_archive_nexus",
    },
    "abyss_gate": {
        "label_key": "expansion_site_abyss_gate",
        "required_homeworld_level": 20,
        "region_key": "dark_expanse",
        "layout_slot": "west",
        "layout_bearing_deg": 350,
        "layout_radius_world": 1080.0,
        "role_icon": "🕳",
        "site_type": "gate",
        "type_key": "expansion_site_type_gate",
        "promise_key": "expansion_site_promise_abyss_gate",
        "risk_level": "high",
        "risk_key": "expansion_site_risk_high",
        "reward_hint_key": "expansion_site_reward_abyss_gate",
        "future_role_key": "expansion_site_future_role_abyss_gate",
    },
    "void_frontier": {
        "label_key": "expansion_site_void_frontier",
        "required_homeworld_level": 25,
        "region_key": "dark_expanse",
        "layout_slot": "east",
        "layout_bearing_deg": 20,
        "layout_radius_world": 1200.0,
        "role_icon": "🌑",
        "site_type": "frontier",
        "type_key": "expansion_site_type_frontier",
        "promise_key": "expansion_site_promise_void_frontier",
        "risk_level": "extreme",
        "risk_key": "expansion_site_risk_extreme",
        "reward_hint_key": "expansion_site_reward_void_frontier",
        "future_role_key": "expansion_site_future_role_void_frontier",
    },
}


def get_homeworld_level(player_id: int, *, conn: sqlite3.Connection) -> int:
    hw = get_homeworld(player_id=int(player_id), conn=conn)
    if not hw:
        return 1
    level, _xp, _remaining = level_progress(int(hw["id"]), conn)
    return int(level)


def is_expansion_site_unlocked(site_key: str, homeworld_level: int) -> bool:
    site = EXPANSION_SITES.get(str(site_key))
    if not site:
        return False
    return int(homeworld_level) >= int(site.get("required_homeworld_level") or 1)


def _site_metadata(site: Dict[str, Any]) -> Dict[str, Any]:
    region_key = str(site.get("region_key") or "outer_rim")
    return {
        "site_type": str(site.get("site_type") or "outpost"),
        "type_key": str(site.get("type_key") or "expansion_site_type_outpost"),
        "promise_key": str(site.get("promise_key") or ""),
        "risk_level": str(site.get("risk_level") or "low"),
        "risk_key": str(site.get("risk_key") or "expansion_site_risk_low"),
        "reward_hint_key": str(site.get("reward_hint_key") or ""),
        "future_role_key": str(site.get("future_role_key") or ""),
        "region_label_key": f"imperium_region_{region_key}",
    }


def _site_row(site_key: str, site: Dict[str, Any], *, homeworld_level: int) -> Dict[str, Any]:
    required = int(site.get("required_homeworld_level") or 1)
    unlocked = homeworld_level >= required
    newly_discovered = unlocked and homeworld_level == required
    meta = _site_metadata(site)
    return {
        "node_kind": "expansion_site",
        "site_key": site_key,
        "name_key": str(site.get("label_key") or site_key),
        "label_key": str(site.get("label_key") or site_key),
        "required_homeworld_level": required,
        "region_key": str(site.get("region_key") or "outer_rim"),
        "is_locked": not unlocked,
        "is_unlocked": unlocked,
        "is_newly_discovered": newly_discovered,
        "layout_slot": str(site.get("layout_slot") or "center"),
        "layout_bearing_deg": float(site.get("layout_bearing_deg") or 0),
        "layout_radius_world": float(site.get("layout_radius_world") or 720),
        "role_icon": str(site.get("role_icon") or "🌌"),
        "empire_role_icon": "🔒" if not unlocked else str(site.get("role_icon") or "🌌"),
        **meta,
        "identity_title_key": str(site.get("label_key") or site_key),
        "empire_role_label_key": str(meta.get("type_key") or site.get("label_key") or site_key),
        "empire_subtitle_key": (
            str(meta.get("promise_key") or site.get("label_key") or site_key)
            if not unlocked
            else (
                "expansion_site_newly_discovered" if newly_discovered else str(meta.get("future_role_key") or site.get("label_key") or site_key)
            )
        ),
    }


def list_expansion_sites_for_player(
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> List[Dict[str, Any]]:
    level = get_homeworld_level(int(player_id), conn=conn)
    rows: List[Dict[str, Any]] = []
    for site_key in sorted(EXPANSION_SITES.keys(), key=lambda k: EXPANSION_SITES[k]["required_homeworld_level"]):
        rows.append(_site_row(site_key, EXPANSION_SITES[site_key], homeworld_level=level))
    return rows


def get_next_expansion_unlock(homeworld_level: int) -> Optional[Dict[str, Any]]:
    """Next locked expansion site (lowest level requirement above current)."""
    candidates: List[Dict[str, Any]] = []
    for site_key, site in EXPANSION_SITES.items():
        required = int(site.get("required_homeworld_level") or 1)
        if homeworld_level >= required:
            continue
        candidates.append(
            {
                "site_key": site_key,
                "label_key": str(site.get("label_key") or site_key),
                "required_homeworld_level": required,
                "region_key": str(site.get("region_key") or "outer_rim"),
                "role_icon": str(site.get("role_icon") or "🌌"),
                "levels_remaining": max(0, required - int(homeworld_level)),
                **_site_metadata(site),
            }
        )
    if not candidates:
        return None
    candidates.sort(key=lambda row: int(row["required_homeworld_level"]))
    return candidates[0]


def build_expansion_unlock_block(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    viewing_homeworld: bool = True,
    site_key: str | None = None,
    world_key: str | None = None,
    world_type: str | None = None,
) -> Dict[str, Any]:
    level = get_homeworld_level(int(player_id), conn=conn)
    sites = list_expansion_sites_for_player(player_id, conn=conn)
    next_unlock = get_next_expansion_unlock(level)
    newly_discovered = [
        {
            "site_key": str(site.get("site_key") or ""),
            "label_key": str(site.get("label_key") or site.get("site_key") or ""),
            "required_homeworld_level": int(site.get("required_homeworld_level") or 0),
            "role_icon": str(site.get("role_icon") or "🌌"),
        }
        for site in sites
        if site.get("is_newly_discovered")
    ]
    from .expansion_protocol import (
        build_expansion_launch_checklist,
        get_expansion_limit_block,
        interstellar_expansion_level,
    )

    limit = get_expansion_limit_block(int(player_id), conn=conn)
    checklist = build_expansion_launch_checklist(
        int(player_id),
        conn=conn,
        site_key=site_key,
        world_key=world_key,
        world_type=world_type,
    )
    target_count = count_reachable_colonize_targets(int(player_id), conn=conn)
    can_launch = bool(checklist.get("can_launch"))
    return {
        "visible": True,
        "homeworld_level": level,
        "expansion_tech_level": interstellar_expansion_level(int(player_id), conn=conn),
        "on_homeworld": bool(viewing_homeworld),
        "show_genesis_ark_hint": bool(not viewing_homeworld and next_unlock),
        "next_unlock": next_unlock,
        "newly_discovered": newly_discovered,
        "sites": sites,
        "expansion_limit": limit,
        "launch_checklist": checklist,
        "colonize_cta": {
            "visible": bool(viewing_homeworld),
            "enabled": can_launch,
            "href": "/galaxy?view=command_map&action=colonize",
            "has_targets": target_count > 0,
            "target_count": int(target_count),
        },
    }


def count_reachable_colonize_targets(
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> int:
    """Colonizable, unclaimed world_field nodes passing per-world expansion gates (GC-931)."""
    from .command_map import build_command_map_payload
    from .expansion_protocol import evaluate_expansion_gates

    uid = int(player_id)
    payload = build_command_map_payload(uid, conn=conn)
    count = 0
    for node in payload.get("nodes") or []:
        if str(node.get("node_kind") or "") != "world_field":
            continue
        if not node.get("is_colonizable") or node.get("is_claimed"):
            continue
        wk = str(node.get("world_key") or "").strip()
        wt = str(node.get("world_type") or "").strip()
        ok, _, _ = evaluate_expansion_gates(
            uid,
            conn=conn,
            world_key=wk or None,
            world_type=wt or None,
        )
        if ok:
            count += 1
    return count


def build_expansion_summary(player_id: int, *, conn: sqlite3.Connection) -> Dict[str, Any]:
    level = get_homeworld_level(int(player_id), conn=conn)
    sites = list_expansion_sites_for_player(player_id, conn=conn)
    return {
        "homeworld_level": level,
        "next_unlock": get_next_expansion_unlock(level),
        "sites": sites,
        "total_count": len(sites),
        "unlocked_count": sum(1 for site in sites if site.get("is_unlocked")),
    }
