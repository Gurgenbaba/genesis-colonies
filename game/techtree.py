"""
Tech-Tree-Helfer für Genesis Colonies.

Ziele:
- Keine doppelte Pflege von Requirements:
  nutzt BUILDING_REQUIREMENTS aus game.buildings
  und RESEARCH_TECHS aus game.research.
- Liefert strukturierte Daten für techtree.html.
- Bietet einen Kompatibilitäts-Wrapper für get_building_tree_status(),
  der wahlweise mit (buildings, research) oder user_id arbeitet.
"""

from __future__ import annotations

from typing import Dict, List, Tuple, Any, Optional

from .buildings import (
    BUILDING_REQUIREMENTS,
    BUILDING_ORDER,
    BUILDING_TAB,
)
from .research import RESEARCH_TECHS
from .models import (
    get_homeworld,
    get_planet_buildings,
    get_research_levels,
)

# ---------------------------------------------------------------------------
# Öffentliche Config-Objekte (werden über logic.py re-exportiert)
# ---------------------------------------------------------------------------

# Für Gebäude: reine Meta-Config für den Tech-Tree
TECHTREE_BUILDINGS: Dict[str, Dict[str, Any]] = {
    key: {
        "key": key,
        "tab": BUILDING_TAB.get(key, "infrastructure"),
        "requirements": (BUILDING_REQUIREMENTS.get(key, {}) or {}),
        # Standard-Icon-Pfad: static/img/buildings/<key>.png
        "icon": f"img/buildings/{key}.png",
    }
    for key in BUILDING_ORDER
}

# Für Forschung: Alias auf RESEARCH_TECHS – Änderungen dort sind hier sofort sichtbar
TECHTREE_RESEARCH: Dict[str, Dict[str, Any]] = RESEARCH_TECHS


# ---------------------------------------------------------------------------
# Interne Helpers
# ---------------------------------------------------------------------------

def _expand_requirements(
    base_requirements: Dict[str, Any],
    buildings: Dict[str, int],
    research_levels: Dict[str, int],
) -> List[Dict[str, Any]]:
    """
    Wandelt die Config-Requirements

      {
        "buildings": {"metal_mine": 5, ...},
        "research":  {"energy_tech": 2, ...}
      }

    in eine flache Liste um, die im Template komfortabel nutzbar ist.

    Jedes Element hat:
      {
        "kind": "building" | "research",
        "key": "<config-key>",
        "required_level": int,
        "current_level": int,
        "met": bool
      }
    """
    result: List[Dict[str, Any]] = []
    if not base_requirements:
        return result

    # Gebäude-Requirements
    for b_key, need_lvl in (base_requirements.get("buildings") or {}).items():
        required = int(need_lvl)
        current = int(buildings.get(b_key, 0) or 0)
        result.append(
            {
                "kind": "building",
                "key": b_key,
                "required_level": required,
                "current_level": current,
                "met": current >= required,
            }
        )

    # Forschungs-Requirements
    for r_key, need_lvl in (base_requirements.get("research") or {}).items():
        required = int(need_lvl)
        current = int(research_levels.get(r_key, 0) or 0)
        result.append(
            {
                "kind": "research",
                "key": r_key,
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
    """
    Prüft generisch die Struktur:

    {
      "buildings": { "metal_mine": 5, ... },
      "research":  { "energy_tech": 2, ... }
    }
    """
    if not base_requirements:
        return True

    for b_key, need_lvl in (base_requirements.get("buildings") or {}).items():
        if int(buildings.get(b_key, 0) or 0) < int(need_lvl):
            return False

    for r_key, need_lvl in (base_requirements.get("research") or {}).items():
        if int(research_levels.get(r_key, 0) or 0) < int(need_lvl):
            return False

    return True


def _ensure_context(
    buildings: Optional[Dict[str, int]],
    research: Optional[Dict[str, int]],
    user_id: Optional[int],
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    Sorgt dafür, dass wir Gebäude- und Research-Daten haben.

    Varianten:
    - buildings und research sind beide gesetzt -> werden direkt genutzt.
    - sonst MUSS user_id gesetzt sein, dann werden Homeworld + Research
      für diesen Spieler aus der DB geladen.
    """
    if buildings is not None and research is not None:
        return buildings, research

    if user_id is None:
        raise RuntimeError(
            "_ensure_context: weder (buildings, research) noch user_id gesetzt – "
            "Multi-User-Setup benötigt explizite IDs."
        )

    planet = get_homeworld(player_id=int(user_id))
    buildings_db = get_planet_buildings(int(planet["id"]))
    research_db = get_research_levels(int(user_id))

    return buildings_db, research_db


# ---------------------------------------------------------------------------
# Öffentliche Funktionen
# ---------------------------------------------------------------------------

def get_techtree_data(
    buildings: Optional[Dict[str, int]] = None,
    research: Optional[Dict[str, int]] = None,
    user_id: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Liefert die Daten für den Tech-Tree-Screen.

    Rückgabe:
      (building_nodes, research_nodes)
    """
    buildings, research = _ensure_context(buildings, research, user_id)

    # Gebäude-Nodes
    building_nodes: List[Dict[str, Any]] = []
    for key in BUILDING_ORDER:
        cfg = TECHTREE_BUILDINGS.get(key, {})
        req_cfg = cfg.get("requirements") or {}

        req_list = _expand_requirements(req_cfg, buildings, research)

        building_nodes.append(
            {
                "key": key,
                "tab": cfg.get("tab", "infrastructure"),
                "level": int(buildings.get(key, 0) or 0),
                "icon": cfg.get("icon"),
                "requirements_raw": req_cfg,
                "requirements": req_list,
                "requirements_met": _check_requirements(req_cfg, buildings, research),
            }
        )

    # Forschungs-Nodes (stabil: nach key sortiert, damit UI nicht „springt“)
    research_nodes: List[Dict[str, Any]] = []
    for key in sorted(TECHTREE_RESEARCH.keys()):
        cfg = TECHTREE_RESEARCH.get(key) or {}
        lvl = int(research.get(key, 0) or 0)

        req_cfg = cfg.get("requirements") or {}
        req_list = _expand_requirements(req_cfg, buildings, research)

        icon_file = cfg.get("icon")
        icon_path = f"img/research/{icon_file}" if icon_file else None

        research_nodes.append(
            {
                "key": key,
                "level": lvl,
                "category": cfg.get("category"),
                "label": cfg.get("label", key),
                "label_key": cfg.get("label_key"),
                "description": cfg.get("description", ""),
                "description_key": cfg.get("description_key"),
                "icon": icon_file,
                "icon_path": icon_path,
                "requirements_raw": req_cfg,
                "requirements": req_list,
                "requirements_met": _check_requirements(req_cfg, buildings, research),
            }
        )

    return building_nodes, research_nodes


def get_building_tree_status(
    buildings: Optional[Dict[str, int]] = None,
    research: Optional[Dict[str, int]] = None,
    user_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Kompakter Wrapper, falls irgendwo nur die Gebäude-Baumdaten gebraucht werden.
    """
    building_nodes, _ = get_techtree_data(
        buildings=buildings,
        research=research,
        user_id=user_id,
    )
    return building_nodes
