"""
Tech-Tree-Helfer für Genesis Colonies.

Ziele:
- Keine doppelte Pflege von Requirements:
  nutzt BUILDING_REQUIREMENTS, RESEARCH_TECHS, fleet_defs, defense_defs.
- Liefert strukturierte Kategorien für techtree.html.
- Bietet Kompatibilitäts-Wrapper für get_building_tree_status().
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .buildings import (
    BUILDING_ICON,
    BUILDING_ORDER,
    BUILDING_REQUIREMENTS,
    BUILDING_TAB,
)
from .defense_defs import ACTIVE_DEFENSE_KEYS, DEFENSES, DEFENSE_ORDER
from .fleet_defs import ACTIVE_SHIP_KEYS, SHIPS, get_ship
from .models import (
    get_planet_buildings,
    get_planet_defense,
    get_research_levels,
)
from .fleet import get_planet_ships
from .planet_evolution.constants import SPECIALIZATION_UNLOCK_LEVEL
from .planet_evolution.repository import get_context_planet, get_planet_row
from .research import RESEARCH_TECHS, resolve_buildings_for_research
from .ship_requirements import check_ship_requirements

# ---------------------------------------------------------------------------
# Öffentliche Config-Objekte (werden über logic.py re-exportiert)
# ---------------------------------------------------------------------------

TECHTREE_BUILDINGS: Dict[str, Dict[str, Any]] = {
    key: {
        "key": key,
        "tab": BUILDING_TAB.get(key, "infrastructure"),
        "requirements": (BUILDING_REQUIREMENTS.get(key, {}) or {}),
        "icon": BUILDING_ICON.get(key, f"img/buildings/{key}.png"),
    }
    for key in BUILDING_ORDER
}

TECHTREE_RESEARCH: Dict[str, Dict[str, Any]] = RESEARCH_TECHS

# Research whose primary gameplay effect is prepared (EffectResolver / docs/EFFECTS.md).
RESEARCH_PREPARED_EFFECT_KEYS = frozenset({"navigation_tech", "engine_tech"})

# Buildings whose primary effect is prepared until scan engine consumes it.
BUILDING_PREPARED_EFFECT_KEYS = frozenset({"radar_array"})

SHIP_ROLE_LABEL_KEYS: Dict[str, str] = {
    "scout": "techtree_role_scout",
    "cargo": "techtree_role_cargo",
    "combat": "techtree_role_combat",
    "colony": "techtree_role_colonize",
    "expedition": "techtree_role_expedition",
    "spy": "techtree_role_scout",
    "recycle": "techtree_role_support",
    "utility": "techtree_role_support",
}

DEFENSE_ROLE_LABEL_KEYS: Dict[str, str] = {
    "turret": "techtree_role_turret",
    "shield": "techtree_role_shield",
}

BUILDING_TAB_LABEL_KEYS: Dict[str, str] = {
    "resources": "techtree_cat_resources",
    "research": "techtree_cat_research",
    "military": "techtree_cat_military",
    "infrastructure": "techtree_cat_infrastructure",
}

PE_TRACK_DEFS: Tuple[Dict[str, Any], ...] = (
    {
        "key": "planet_dna",
        "label_key": "techtree_pe_dna",
        "description_key": "techtree_pe_dna_desc",
        "unlock_level": 3,
    },
    {
        "key": "planet_level",
        "label_key": "techtree_pe_level",
        "description_key": "techtree_pe_level_desc",
        "unlock_level": 1,
    },
    {
        "key": "traits",
        "label_key": "techtree_pe_traits",
        "description_key": "techtree_pe_traits_desc",
        "unlock_level": 3,
    },
    {
        "key": "specialization",
        "label_key": "techtree_pe_specialization",
        "description_key": "techtree_pe_specialization_desc",
        "unlock_level": SPECIALIZATION_UNLOCK_LEVEL,
    },
    {
        "key": "policies",
        "label_key": "techtree_pe_policies",
        "description_key": "techtree_pe_policies_desc",
        "unlock_level": 5,
    },
    {
        "key": "planet_research",
        "label_key": "techtree_pe_research",
        "description_key": "techtree_pe_research_desc",
        "unlock_level": 3,
    },
    {
        "key": "ascension",
        "label_key": "techtree_pe_ascension",
        "description_key": "techtree_pe_ascension_desc",
        "unlock_level": 25,
    },
)

# ---------------------------------------------------------------------------
# Interne Helpers
# ---------------------------------------------------------------------------

def _label_key_for_requirement(kind: str, key: str) -> str:
    if kind == "building":
        return f"building_{key}"
    cfg = RESEARCH_TECHS.get(key) or {}
    return str(cfg.get("label_key") or key)


def _expand_requirements(
    base_requirements: Dict[str, Any],
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    if not base_requirements:
        return result

    for b_key, need_lvl in sorted((base_requirements.get("buildings") or {}).items()):
        required = int(need_lvl)
        current = int(buildings.get(b_key, 0) or 0)
        result.append(
            {
                "kind": "building",
                "key": b_key,
                "label_key": _label_key_for_requirement("building", b_key),
                "required_level": required,
                "current_level": current,
                "met": current >= required,
            }
        )

    for r_key, need_lvl in sorted((base_requirements.get("research") or {}).items()):
        required = int(need_lvl)
        current = int(research_levels.get(r_key, 0) or 0)
        result.append(
            {
                "kind": "research",
                "key": r_key,
                "label_key": _label_key_for_requirement("research", r_key),
                "required_level": required,
                "current_level": current,
                "met": current >= required,
            }
        )

    return result


def _check_requirements(
    base_requirements: Dict[str, Any],
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
) -> bool:
    if not base_requirements:
        return True

    for b_key, need_lvl in (base_requirements.get("buildings") or {}).items():
        if int(buildings.get(b_key, 0) or 0) < int(need_lvl):
            return False

    for r_key, need_lvl in (base_requirements.get("research") or {}).items():
        if int(research_levels.get(r_key, 0) or 0) < int(need_lvl):
            return False

    return True


def _progressive_status(
    *,
    level: int = 0,
    count: int = 0,
    requirements_met: bool,
    planned: bool = False,
) -> str:
    if planned:
        return "planned"
    if level > 0 or count > 0:
        return "unlocked"
    if requirements_met:
        return "available"
    return "locked"


def _section_progress(items: List[Dict[str, Any]]) -> Tuple[int, int]:
    total = len(items)
    unlocked = sum(1 for item in items if item.get("status") == "unlocked")
    return unlocked, total


def _ensure_context(
    buildings: Optional[Dict[str, int]],
    research: Optional[Dict[str, int]],
    user_id: Optional[int],
) -> Tuple[Dict[str, int], Dict[str, int], Optional[int], Optional[int]]:
    planet_id: Optional[int] = None

    if buildings is not None and research is not None:
        if user_id is not None:
            buildings = resolve_buildings_for_research(buildings, int(user_id))
            try:
                planet = get_context_planet(player_id=int(user_id))
                planet_id = int(planet["id"])
            except Exception:
                planet_id = None
        return buildings, research, user_id, planet_id

    if user_id is None:
        raise RuntimeError(
            "_ensure_context: weder (buildings, research) noch user_id gesetzt – "
            "Multi-User-Setup benötigt explizite IDs."
        )

    planet = get_context_planet(player_id=int(user_id))
    planet_id = int(planet["id"])
    buildings_db = get_planet_buildings(planet_id)
    research_db = get_research_levels(int(user_id))
    buildings_db = resolve_buildings_for_research(buildings_db, int(user_id))

    return buildings_db, research_db, int(user_id), planet_id


def _build_building_items(buildings: Dict[str, int], research: Dict[str, int]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for key in BUILDING_ORDER:
        cfg = TECHTREE_BUILDINGS.get(key, {})
        req_cfg = cfg.get("requirements") or {}
        req_list = _expand_requirements(req_cfg, buildings, research)
        reqs_met = _check_requirements(req_cfg, buildings, research)
        level = int(buildings.get(key, 0) or 0)
        tab = str(cfg.get("tab") or "infrastructure")
        prepared = key in BUILDING_PREPARED_EFFECT_KEYS

        items.append(
            {
                "key": key,
                "kind": "building",
                "label_key": f"building_{key}",
                "category": tab,
                "category_label_key": BUILDING_TAB_LABEL_KEYS.get(tab, "techtree_cat_infrastructure"),
                "level": level,
                "icon": cfg.get("icon"),
                "requirements": req_list,
                "requirements_met": reqs_met,
                "status": _progressive_status(level=level, requirements_met=reqs_met),
                "effect_status": "prepared" if prepared else "active",
            }
        )
    return items


def _build_research_items(buildings: Dict[str, int], research: Dict[str, int]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for key in sorted(RESEARCH_TECHS.keys()):
        cfg = RESEARCH_TECHS.get(key) or {}
        lvl = int(research.get(key, 0) or 0)
        req_cfg = cfg.get("requirements") or {}
        req_list = _expand_requirements(req_cfg, buildings, research)
        reqs_met = _check_requirements(req_cfg, buildings, research)
        icon_file = cfg.get("icon")
        prepared = key in RESEARCH_PREPARED_EFFECT_KEYS

        items.append(
            {
                "key": key,
                "kind": "research",
                "label_key": str(cfg.get("label_key") or key),
                "description_key": cfg.get("description_key"),
                "category": cfg.get("category"),
                "level": lvl,
                "icon": f"img/research/{icon_file}" if icon_file else None,
                "requirements": req_list,
                "requirements_met": reqs_met,
                "status": _progressive_status(level=lvl, requirements_met=reqs_met),
                "effect_status": "prepared" if prepared else "active",
            }
        )
    return items


def _build_ship_items(
    buildings: Dict[str, int],
    research: Dict[str, int],
    ship_stock: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    stock = ship_stock or {}

    ship_keys = sorted(ACTIVE_SHIP_KEYS)
    for key in ship_keys:
        spec = get_ship(key) or {}
        req_cfg = spec.get("requirements") or {}
        req_list = _expand_requirements(req_cfg, buildings, research)
        ok, _missing = check_ship_requirements(key, buildings=buildings, research=research)
        count = int(stock.get(key, 0) or 0)
        role = str(spec.get("role") or "utility")
        cost = spec.get("build_cost") or {}

        items.append(
            {
                "key": key,
                "kind": "ship",
                "label_key": str(spec.get("name_key") or f"fleet_ship_{key}"),
                "description_key": spec.get("description_key"),
                "role": role,
                "role_label_key": SHIP_ROLE_LABEL_KEYS.get(role, "techtree_role_support"),
                "level": count,
                "icon": f"img/ships/{key}.png",
                "requirements": req_list,
                "requirements_met": ok,
                "status": _progressive_status(count=count, requirements_met=ok),
                "effect_status": "active",
                "build_cost": {
                    "metal": int(cost.get("metal") or 0),
                    "crystal": int(cost.get("crystal") or 0),
                    "fuel_cells": int(cost.get("fuel_cells") or 0),
                },
            }
        )

    # Prepared hulls (not in ACTIVE_SHIP_KEYS).
    for key, spec in sorted(SHIPS.items()):
        if key in ACTIVE_SHIP_KEYS or not spec.get("phase2_only"):
            continue
        req_cfg = spec.get("requirements") or {}
        req_list = _expand_requirements(req_cfg, buildings, research)
        role = str(spec.get("role") or "utility")
        cost = spec.get("build_cost") or {}
        items.append(
            {
                "key": key,
                "kind": "ship",
                "label_key": str(spec.get("name_key") or f"fleet_ship_{key}"),
                "description_key": spec.get("description_key"),
                "role": role,
                "role_label_key": SHIP_ROLE_LABEL_KEYS.get(role, "techtree_role_support"),
                "level": 0,
                "icon": f"img/ships/{key}.png",
                "requirements": req_list,
                "requirements_met": False,
                "status": "planned",
                "effect_status": "prepared",
                "build_cost": {
                    "metal": int(cost.get("metal") or 0),
                    "crystal": int(cost.get("crystal") or 0),
                    "fuel_cells": int(cost.get("fuel_cells") or 0),
                },
            }
        )

    return items


def _build_defense_items(
    buildings: Dict[str, int],
    research: Dict[str, int],
    *,
    defense_ready: bool,
    defense_stock: Optional[Dict[str, int]] = None,
) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    stock = defense_stock or {}

    for key in DEFENSE_ORDER:
        spec = DEFENSES.get(key) or {}
        req_cfg = spec.get("requirements") or {}
        req_list = _expand_requirements(req_cfg, buildings, research)
        reqs_met = _check_requirements(req_cfg, buildings, research)
        count = int(stock.get(key, 0) or 0)
        role = str(spec.get("role") or "turret")
        cost = spec.get("build_cost") or {}
        planned = not defense_ready

        items.append(
            {
                "key": key,
                "kind": "defense",
                "label_key": str(spec.get("name_key") or f"defense_{key}"),
                "description_key": spec.get("description_key"),
                "role": role,
                "role_label_key": DEFENSE_ROLE_LABEL_KEYS.get(role, "techtree_role_turret"),
                "level": count,
                "icon": f"img/defense/{key}.png",
                "requirements": req_list,
                "requirements_met": reqs_met,
                "status": _progressive_status(
                    count=count,
                    requirements_met=reqs_met,
                    planned=planned,
                ),
                "effect_status": "prepared" if planned else "active",
                "build_cost": {
                    "metal": int(cost.get("metal") or 0),
                    "crystal": int(cost.get("crystal") or 0),
                },
            }
        )
    return items


def _build_pe_items(planet_id: Optional[int]) -> List[Dict[str, Any]]:
    planet_level = 1
    dna_tier = 0
    if planet_id is not None:
        row = get_planet_row(int(planet_id)) or {}
        planet_level = max(1, int(row.get("planet_level") or 1))
        dna_tier = max(0, int(row.get("dna_reveal_tier") or 0))

    items: List[Dict[str, Any]] = []
    for track in PE_TRACK_DEFS:
        unlock_level = int(track.get("unlock_level") or 1)
        if track["key"] == "planet_level":
            status = "unlocked"
        elif track["key"] in ("planet_dna", "traits") and dna_tier >= 1:
            status = "unlocked"
        elif planet_level >= unlock_level:
            status = "unlocked"
        else:
            status = "locked"

        items.append(
            {
                "key": track["key"],
                "kind": "planet_evolution",
                "label_key": track["label_key"],
                "description_key": track.get("description_key"),
                "level": planet_level if track["key"] == "planet_level" else 0,
                "requirements": [
                    {
                        "kind": "planet_level",
                        "key": "planet_level",
                        "label_key": "techtree_pe_req_level",
                        "required_level": unlock_level,
                        "current_level": planet_level,
                        "met": planet_level >= unlock_level,
                    }
                ],
                "requirements_met": planet_level >= unlock_level,
                "status": status,
                "effect_status": "active",
            }
        )
    return items


def _wrap_section(
    key: str,
    label_key: str,
    hint_key: str,
    icon: str,
    items: List[Dict[str, Any]],
    *,
    default_collapsed: bool,
) -> Dict[str, Any]:
    unlocked, total = _section_progress(items)
    return {
        "key": key,
        "label_key": label_key,
        "hint_key": hint_key,
        "icon": icon,
        "default_collapsed": default_collapsed,
        "progress_unlocked": unlocked,
        "progress_total": total,
        "nodes": items,
    }


# ---------------------------------------------------------------------------
# Öffentliche Funktionen
# ---------------------------------------------------------------------------

def get_techtree_data(
    buildings: Optional[Dict[str, int]] = None,
    research: Optional[Dict[str, int]] = None,
    user_id: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Liefert Legacy-Daten (building_nodes, research_nodes) für Abwärtskompatibilität.
    """
    ctx = get_techtree_page_context(buildings=buildings, research=research, user_id=user_id)
    return ctx["building_nodes"], ctx["research_nodes"]


def get_techtree_page_context(
    buildings: Optional[Dict[str, int]] = None,
    research: Optional[Dict[str, int]] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Vollständiger Tech-Tree-Kontext: kategorisierte Sektionen + Legacy-Nodes.
    """
    buildings, research, uid, planet_id = _ensure_context(buildings, research, user_id)

    ship_stock: Dict[str, int] = {}
    defense_stock: Dict[str, int] = {}
    defense_ready = True

    if planet_id is not None:
        try:
            ship_stock = get_planet_ships(int(planet_id)) or {}
        except Exception:
            ship_stock = {}
        try:
            defense_stock = get_planet_defense(int(planet_id)) or {}
        except Exception:
            defense_stock = {}
        try:
            from .models import defense_schema_ready
            from .defense import defense_queue_table_ready

            defense_ready = bool(defense_schema_ready() and defense_queue_table_ready())
        except Exception:
            defense_ready = True

    building_items = _build_building_items(buildings, research)
    research_items = _build_research_items(buildings, research)
    ship_items = _build_ship_items(buildings, research, ship_stock)
    defense_items = _build_defense_items(
        buildings,
        research,
        defense_ready=defense_ready,
        defense_stock=defense_stock,
    )
    pe_items = _build_pe_items(planet_id)

    sections = [
        _wrap_section(
            "research",
            "techtree_section_research",
            "techtree_research_hint",
            "research",
            research_items,
            default_collapsed=False,
        ),
        _wrap_section(
            "ships",
            "techtree_section_ships",
            "techtree_ships_hint",
            "ships",
            ship_items,
            default_collapsed=False,
        ),
        _wrap_section(
            "buildings",
            "techtree_section_buildings",
            "techtree_buildings_hint",
            "buildings",
            building_items,
            default_collapsed=True,
        ),
        _wrap_section(
            "defense",
            "techtree_section_defense",
            "techtree_defense_hint",
            "defense",
            defense_items,
            default_collapsed=True,
        ),
        _wrap_section(
            "planet_evolution",
            "techtree_section_pe",
            "techtree_pe_hint",
            "planet",
            pe_items,
            default_collapsed=True,
        ),
    ]

    building_nodes = [
        {
            "key": item["key"],
            "tab": item.get("category"),
            "category": item.get("category"),
            "level": item.get("level", 0),
            "icon": item.get("icon"),
            "requirements": item.get("requirements") or [],
            "requirements_met": item.get("requirements_met", False),
        }
        for item in building_items
    ]

    research_nodes = [
        {
            "key": item["key"],
            "level": item.get("level", 0),
            "category": item.get("category"),
            "label_key": item.get("label_key"),
            "description_key": item.get("description_key"),
            "icon": (item.get("icon") or "").replace("img/research/", "") if item.get("icon") else None,
            "icon_path": item.get("icon"),
            "requirements": item.get("requirements") or [],
            "requirements_met": item.get("requirements_met", False),
            "effect_status": item.get("effect_status"),
            "status": item.get("status"),
        }
        for item in research_items
    ]

    return {
        "sections": sections,
        "building_nodes": building_nodes,
        "research_nodes": research_nodes,
        "defense_ready": defense_ready,
    }


def get_building_tree_status(
    buildings: Optional[Dict[str, int]] = None,
    research: Optional[Dict[str, int]] = None,
    user_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Kompakter Wrapper, falls irgendwo nur die Gebäude-Baumdaten gebraucht werden."""
    building_nodes, _ = get_techtree_data(
        buildings=buildings,
        research=research,
        user_id=user_id,
    )
    return building_nodes
