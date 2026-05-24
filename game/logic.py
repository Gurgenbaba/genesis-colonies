"""
Zentrale Logik-Fassade für Genesis Colonies.

Dieses Modul bündelt die wichtigsten Funktionen für app.py und Templates
und delegiert die eigentliche Arbeit an spezialisierte Module:

- game.resources:   Ressourcen-Tick, Produktion, Lager
- game.buildings:   Gebäude-Kosten, Bauzeiten, Build-Queue
- game.research:    Forschungs-Logik & Research-Queue
- game.techtree:    Tech-Tree-Daten (Gebäude + Forschung)

WICHTIG:
- Multi-User-fähig.
- Keine hardcodierten player_id/user_id Defaults.
"""

from __future__ import annotations

from typing import Dict, Any, Optional, Tuple

from .models import get_homeworld, get_research_levels
from . import resources as _res
from .resources import (
    update_resources as _update_resources,
    apply_resource_delta_unbounded as _apply_resource_delta_unbounded,
    get_building_production_per_hour as _core_get_bpph,
    get_storage_capacity as _core_get_storage_capacity,
)

from .buildings import (
    get_build_queue_status_for_planet,
    queue_build_for_planet as _queue_build_for_planet,
    complete_finished_builds_for_planet,  # finish + score trigger in buildings/models
)

from .research import (
    queue_research as _queue_research,  # signature: (player, tech_key, user_id=None)
    get_research_status as _get_research_status,
    get_research_modifiers as _get_research_modifiers,
    complete_finished_research as _complete_finished_research,
)

from .techtree import (
    get_techtree_data as _tt_get_techtree_data,
    get_building_tree_status as _tt_get_building_tree_status,
)


# ============================================================================ #
# RESSOURCEN
# ============================================================================ #

def update_planet_resources(planet: dict, conn=None):
    """
    Thin-Wrapper um game.resources.update_planet_resources.

    Rückgabe:
        (planet, buildings, ratio, energy_total, energy_used)

    ✅ conn-safe wenn resources.update_planet_resources(conn=...) unterstützt.
    """
    return _res.update_planet_resources(planet, conn=conn)


def update_resources(player: dict, conn=None):
    """
    Wrapper um resources.update_resources.

    Erwartet:
        player: dict mit mindestens player['id'] (players.id / user_id)

    Rückgabe:
        (player_view, buildings, ratio, energy_total, energy_used)

    ✅ conn-safe (wenn resources.py conn durchreicht).
    """
    return _update_resources(player, conn=conn)


def get_building_production_per_hour(
    buildings: Dict[str, int],
    ratio: float,
    user_id: Optional[int] = None,
    research: Optional[Dict[str, int]] = None,
    conn=None,
) -> Dict[str, int]:
    """
    Liefert die Produktion pro Stunde je Ressource.

    ✅ user_id strikt int
    ✅ research optional (sonst DB)
    ✅ mods aus research.get_research_modifiers (single source of truth)
    """
    user_id_int: Optional[int] = int(user_id) if user_id is not None else None

    if research is None:
        if user_id_int is not None:
            research = get_research_levels(user_id_int, conn=conn)
        else:
            research = {}

    mods = _get_research_modifiers(user_id_int, conn=conn) if user_id_int is not None else None

    return _core_get_bpph(
        buildings=buildings,
        ratio=ratio,
        research=research,
        mods=mods,
    )


def get_storage_capacity(
    buildings: Dict[str, int],
    user_id: Optional[int] = None,
    research: Optional[Dict[str, int]] = None,
    conn=None,
) -> Dict[str, int]:
    """
    Berechnet Lagerkapazitäten (Metall/Kristall).

    ✅ user_id strikt int
    ✅ research optional (sonst DB)
    ✅ mods aus research.get_research_modifiers
    """
    user_id_int: Optional[int] = int(user_id) if user_id is not None else None

    if research is None:
        if user_id_int is not None:
            research = get_research_levels(user_id_int, conn=conn)
        else:
            research = {}

    mods = _get_research_modifiers(user_id_int, conn=conn) if user_id_int is not None else None

    return _core_get_storage_capacity(
        buildings=buildings,
        research=research,
        mods=mods,
    )


def apply_resource_delta_unbounded(
    planet: dict,
    delta_metal: int = 0,
    delta_crystal: int = 0,
) -> None:
    """
    Admin-/Event-Helfer: Ressourcen ohne Cap anpassen.
    """
    return _apply_resource_delta_unbounded(
        planet,
        delta_metal=delta_metal,
        delta_crystal=delta_crystal,
    )


# ============================================================================ #
# BUILD QUEUE
# ============================================================================ #

def get_build_queue_status(user_id: int) -> Dict[str, Any]:
    """
    Liefert die Build-Queue für den aktuellen User (Homeworld).

    Wichtig:
    - Finish-Handling + Score Trigger ist in buildings/models enthalten.
    - Hier nur "anwenden + lesen".
    """
    user_id_int = int(user_id)

    planet = get_homeworld(player_id=user_id_int)
    planet_id = int(planet["id"])

    # ✅ fertige Builds anwenden (inkl. Score Trigger in buildings/models)
    complete_finished_builds_for_planet(planet_id)

    return get_build_queue_status_for_planet(planet_id)


def queue_build(
    player: dict,
    buildings: Dict[str, int],
    building_type: str,
) -> Tuple[bool, str, Any]:
    """
    Komfortfunktion für app.py (Upgrade-Route).

    Rückgabe:
        (ok, reason, payload)

    reason mapping:
        - not_enough_resources -> payload = (need_m, need_c)
        - queue_full
        - requirements
        - unknown_building
    """
    user_id = int(player.get("id"))
    planet = get_homeworld(player_id=user_id)

    ok, reason, payload = _queue_build_for_planet(
        planet=planet,
        buildings=buildings,
        building_type=building_type,
        user_id=user_id,
    )

    if not ok:
        if reason == "resources":
            need_m = int(payload.get("cost_metal", 0))
            need_c = int(payload.get("cost_crystal", 0))
            return False, "not_enough_resources", (need_m, need_c)
        if reason == "queue_full":
            return False, "queue_full", payload
        if reason == "requirements":
            return False, "requirements", payload
        if reason == "invalid":
            return False, "unknown_building", payload
        return False, reason, payload

    return True, "ok", payload


# ============================================================================ #
# RESEARCH
# ============================================================================ #

def queue_research(player: dict, tech_key: str):
    """
    Thin-Wrapper um game.research.queue_research.

    Erwartete Signatur in research.py:
        queue_research(player, tech_key, user_id=None)
    """
    return _queue_research(player, tech_key)


def get_research_status(
    user_id: int,
    buildings: Optional[Dict[str, int]] = None,
) -> dict:
    """
    Wrapper um game.research.get_research_status.

    - Finish-Handling + Score Trigger passiert in research/models.
    - UI bekommt stets frische Daten.
    """
    return _get_research_status(user_id=int(user_id), buildings=buildings)


def get_research_modifiers(user_id: int, conn=None) -> Dict[str, float]:
    """
    ✅ Einziger offizieller Mods-Endpunkt.
    """
    return _get_research_modifiers(int(user_id), conn=conn)


def complete_finished_research(user_id: int, conn=None) -> bool:
    """
    Exponiert research.complete_finished_research (optional fürs Polling/Finisher).
    """
    return _complete_finished_research(int(user_id), conn=conn)


# ============================================================================ #
# TECHTREE
# ============================================================================ #

def get_techtree_data(
    buildings: Optional[Dict[str, int]] = None,
    research: Optional[Dict[str, int]] = None,
    user_id: Optional[int] = None,
):
    """
    Wrapper um game.techtree.get_techtree_data.
    """
    return _tt_get_techtree_data(
        buildings=buildings,
        research=research,
        user_id=user_id,
    )


def get_building_tree_status(
    user_id: Optional[int] = None,
    buildings: Optional[Dict[str, int]] = None,
    research: Optional[Dict[str, int]] = None,
):
    """
    Wrapper um game.techtree.get_building_tree_status.
    """
    if user_id is not None and (buildings is None or research is None):
        return _tt_get_building_tree_status(user_id=int(user_id))

    return _tt_get_building_tree_status(
        buildings=buildings,
        research=research,
        user_id=int(user_id) if user_id is not None else None,
    )
