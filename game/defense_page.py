"""Defense page — server-rendered context and API payload enrichment."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from .defense import (
    build_defense_api_payload,
    defense_queue_table_ready,
    defense_unlocked,
    get_defense_factory_level,
)
from .defense_defs import ACTIVE_DEFENSE_KEYS, DEFENSES, defense_defs_for_client, defense_icon_static_path
from .models import defense_schema_ready


def _planet_meta(planet_id: int, *, conn) -> Dict[str, Any]:
    cur = conn.cursor()
    cur.execute(
        "SELECT id, name, galaxy, system, position FROM planets WHERE id = ? LIMIT 1;",
        (int(planet_id),),
    )
    row = cur.fetchone()
    if not row:
        return {"planet_id": int(planet_id), "planet_name": "", "planet_coords": ""}
    coords = f"{int(row['galaxy'])}:{int(row['system'])}:{int(row['position'])}"
    name = str(row["name"] or "").strip() or coords
    return {
        "planet_id": int(row["id"]),
        "planet_name": name,
        "planet_coords": coords,
    }


def _locked_defense_catalog(
    player_id: int,
    planet_id: int,
    factory_level: int,
    *,
    conn,
) -> list[Dict[str, Any]]:
    from .defense_requirements import requirements_summary_for_client
    from .models import get_planet_buildings, get_planet_defense
    from .research import get_research_levels

    stock = get_planet_defense(int(planet_id), conn=conn)
    buildings = get_planet_buildings(int(planet_id), conn=conn)
    research = get_research_levels(user_id=int(player_id), conn=conn)
    out: list[Dict[str, Any]] = []
    for key in sorted(ACTIVE_DEFENSE_KEYS):
        if defense_unlocked(
            key,
            factory_level,
            player_id=player_id,
            planet_id=planet_id,
            conn=conn,
            buildings=buildings,
            research=research,
        ):
            continue
        spec = DEFENSES.get(key) or {}
        cost = spec.get("build_cost") or {}
        req_summary = requirements_summary_for_client(
            key, buildings=buildings, research=research
        )
        req_items = [
            {
                "kind": str(it.get("type") or ""),
                "key": str(it.get("key") or ""),
                "need": int(it.get("required") or 0),
                "have": int(it.get("current") or 0),
                "met": bool(it.get("met")),
            }
            for it in (req_summary.get("items") or [])
        ]
        out.append(
            {
                "defense_key": key,
                "name_key": str(spec.get("name_key") or f"defense_{key}"),
                "description_key": str(spec.get("description_key") or f"defense_{key}_desc"),
                "role": str(spec.get("role") or "turret"),
                "icon": defense_icon_static_path(key),
                "required_defense_factory_level": int(spec.get("required_defense_factory_level") or 99),
                "cost_metal": int(cost.get("metal") or 0),
                "cost_crystal": int(cost.get("crystal") or 0),
                "cost_fuel_cells": int(cost.get("fuel_cells") or 0),
                "build_seconds": 0,
                "stock": int(stock.get(key, 0) or 0),
                "unlocked": False,
                "requirements_items": req_items,
            }
        )
    return out


def build_defense_page_context(
    player_id: int,
    planet: Mapping[str, Any],
    *,
    conn,
    tab: str = "structures",
) -> Dict[str, Any]:
    """Mode-specific context for defense.html and initial client state."""
    pid = int(planet["id"])
    mode = str(tab or "structures").strip().lower()
    if mode not in {"structures", "troops"}:
        mode = "structures"

    meta = _planet_meta(pid, conn=conn)
    ready = defense_schema_ready(conn) and defense_queue_table_ready(conn)

    if not ready:
        return {
            "ready": False,
            "active_tab": mode,
            "defense_factory_level": 0,
            **meta,
        }

    # GC-PERF-DEFENSE-SSR-006: top-level Defense tabs are mutually exclusive
    # heavy surfaces. Build only the state that the requested tab can render.
    if mode == "troops":
        troops_state = None
        vault_state = None
        try:
            from .models import get_planet_buildings
            from .troops import build_troops_state, troop_queue_table_ready, troops_schema_ready
            from .vault_raid import build_vault_panel_state

            if troops_schema_ready(conn) and troop_queue_table_ready(conn):
                bld = get_planet_buildings(pid, conn=conn) or {}
                troops_state = build_troops_state(
                    pid,
                    barracks_level=int(bld.get("barracks") or 0),
                    conn=conn,
                )
            vault_state = build_vault_panel_state(int(player_id), conn=conn)
        except Exception:
            troops_state = None
            vault_state = None

        return {
            "ready": True,
            "active_tab": mode,
            "defense_factory_level": 0,
            **meta,
            "troops": troops_state,
            "vault": vault_state,
        }

    payload = build_defense_api_payload(int(player_id), pid, conn=conn)
    factory_level = int(payload.get("defense_factory_level") or 0)
    locked = _locked_defense_catalog(int(player_id), pid, factory_level, conn=conn)

    stock = payload.get("current_defense") or {}
    for entry in payload.get("buildable_defense") or []:
        dk = str(entry.get("defense_key") or "")
        entry["stock"] = int(stock.get(dk, 0) or 0)

    for entry in locked:
        dk = str(entry.get("defense_key") or "")
        entry["stock"] = int(stock.get(dk, 0) or 0)

    from .defense import _attach_queue_jobs_to_defense_rows

    by_owner = (payload.get("defense_queue") or {}).get("card_jobs_by_owner") or {}
    _attach_queue_jobs_to_defense_rows(locked, by_owner)

    return {
        "ready": True,
        "active_tab": mode,
        **payload,
        **meta,
        "locked_defense": locked,
        "defense_defs": {row["key"]: row for row in defense_defs_for_client()},
        "troops": None,
        "vault": None,
    }
