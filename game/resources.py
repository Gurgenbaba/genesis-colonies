"""
Ressourcen- und Produktions-Logik für Genesis Colonies.

Enthält:
- Energie-Berechnung (Solar + Minen-Verbrauch, inkl. Energy-Tech)
- Produktionsraten (Ferronit/Crytite) inkl. Mining-Tech + Drohnen-Tech
- Lagerkapazität (Storage-Tech + Terraformer)
- Tick-Update: Fertige Jobs anwenden + Produktion seit last_update
- Overflow-Regel: Rewards/Farming dürfen Overflow erzeugen; Produktion cappt nur Zuwachs

WICHTIG:
- Multi-User: planet['player_id'] ist Pflicht
- Research-Mods bevorzugt über get_research_modifiers()
"""

from __future__ import annotations

import time
from typing import Dict, Tuple, Optional

from .models import (
    get_planet_buildings,
    get_research_levels,
    get_game_settings,
    save_planet,
)
from .buildings import complete_finished_builds_for_planet
from .research import complete_finished_research, get_research_modifiers


# ==========================================================================
#   ENERGY & PRODUCTION
# ==========================================================================

def compute_energy(
    buildings: Dict[str, int],
    research: Optional[Dict[str, int]] = None,
    mods: Optional[Dict[str, float]] = None,
) -> Tuple[int, int]:
    """
    Berechnet:
    - energy_total: erzeugte Energie (Solar)
    - energy_used: verbrauchte Energie (Minen)

    Research-Effekte:
    - Wenn 'mods' übergeben wird, wird mine_energy_factor aus get_research_modifiers()
      verwendet.
    - Wenn kein 'mods' gesetzt ist, wird als Fallback direkt aus 'research["energy_tech"]'
      gerechnet (Formel identisch zu get_research_modifiers).
    """
    if research is None:
        research = {}

    solar_lvl = int(buildings.get("solar_plant", 0) or 0)
    metal_lvl = int(buildings.get("metal_mine", 0) or 0)
    crystal_lvl = int(buildings.get("crystal_mine", 0) or 0)

    # Beispiel-Formeln
    energy_total = int(20 * (solar_lvl ** 1.4)) if solar_lvl > 0 else 0

    energy_metal = int(10 * (metal_lvl ** 1.25)) if metal_lvl > 0 else 0
    energy_crystal = int(6 * (crystal_lvl ** 1.25)) if crystal_lvl > 0 else 0
    energy_used = energy_metal + energy_crystal

    # Energieeffizienz
    if mods is not None:
        mine_energy_factor = float(mods.get("mine_energy_factor", 1.0) or 1.0)
        energy_used = int(energy_used * mine_energy_factor)
    else:
        eff_lvl = int(research.get("energy_tech", 0) or 0)
        if eff_lvl > 0:
            energy_factor = max(0.4, 1.0 - 0.05 * eff_lvl)
            energy_used = int(energy_used * energy_factor)

    return energy_total, energy_used


def production_rates_per_sec(
    buildings: Dict[str, int],
    research: Optional[Dict[str, int]] = None,
    mods: Optional[Dict[str, float]] = None,
) -> Tuple[float, float]:
    """
    Basis-Produktionsraten pro Sekunde (vor Energie- und Speed-Faktoren).

    Berücksichtigt:
    - Minenlevel
    - Research-Effekte:

      Variante A (empfohlen):
        - über 'mods' (get_research_modifiers):
          metal_prod_factor, crystal_prod_factor

      Variante B (Fallback):
        - mining_tech (+10 % Metall, +4 % Crytite pro Stufe)
        - drone_tech  (+3 % auf beide Ressourcen pro Stufe)
    """
    if research is None:
        research = {}

    metal_lvl = int(buildings.get("metal_mine", 0) or 0)
    crystal_lvl = int(buildings.get("crystal_mine", 0) or 0)

    # Basis-Formeln
    metal_rate = 0.04 * (metal_lvl ** 1.4) if metal_lvl > 0 else 0.0
    crystal_rate = 0.03 * (crystal_lvl ** 1.35) if crystal_lvl > 0 else 0.0

    # Fallback-Levels
    mining_lvl = int(research.get("mining_tech", 0) or 0)
    drones_lvl = int(research.get("drone_tech", 0) or 0)

    if mods is not None:
        metal_factor = float(mods.get("metal_prod_factor", 1.0) or 1.0)
        crystal_factor = float(mods.get("crystal_prod_factor", 1.0) or 1.0)
        metal_rate *= metal_factor
        crystal_rate *= crystal_factor
    else:
        if mining_lvl > 0:
            metal_rate *= (1.0 + 0.10 * mining_lvl)
            crystal_rate *= (1.0 + 0.04 * mining_lvl)

        if drones_lvl > 0:
            bonus = 1.0 + 0.03 * drones_lvl
            metal_rate *= bonus
            crystal_rate *= bonus

    return metal_rate, crystal_rate


def get_building_production_per_hour(
    buildings: Dict[str, int],
    ratio: float,
    research: Optional[Dict[str, int]] = None,
    mods: Optional[Dict[str, float]] = None,
) -> Dict[str, int]:
    """
    Liefert eine Übersicht der Produktion pro Stunde je Gebäude.

    Research:
      - Wenn 'mods' gesetzt ist, werden die zentralen Faktoren aus
        get_research_modifiers() verwendet.
      - Andernfalls Fallback auf 'research'-Dict (Formeln identisch).
    """
    settings = get_game_settings()
    prod_speed = float(settings.get("production_speed", 1.0) or 1.0)

    metal_rate, crystal_rate = production_rates_per_sec(
        buildings,
        research=research,
        mods=mods,
    )

    metal_ph = int(metal_rate * float(ratio) * 3600 * prod_speed)
    crystal_ph = int(crystal_rate * float(ratio) * 3600 * prod_speed)

    return {
        "metal_mine": metal_ph,
        "crystal_mine": crystal_ph,
        "solar_plant": 0,

        "research_lab": 0,
        "academy": 0,

        "metal_storage": 0,
        "crystal_storage": 0,

        "command_center": 0,
        "shipyard": 0,
        "defense_factory": 0,
        "barracks": 0,
        "radar_array": 0,
        "shield_generator": 0,

        "terraformer": 0,
        "nanofactory": 0,
        "geothermal_nexus": 0,
        "planet_core_nexus": 0,
    }


# ==========================================================================
#   STORAGE CAPACITY & RESOURCE-DELTA-HELPER
# ==========================================================================

def get_storage_capacity(
    buildings: Dict[str, int],
    research: Optional[Dict[str, int]] = None,
    mods: Optional[Dict[str, float]] = None,
    *,
    user_id: Optional[int] = None,
    conn=None,
) -> Dict[str, int]:
    """
    Berechnet die Lagerkapazität (Metall / Kristall) basierend auf:
    - Storage-Gebäude
    - storage_tech (oder mods.storage_factor)
    - Terraformer (+5 % pro Stufe)

    NEU (optional):
    - user_id + conn: falls research nicht übergeben wird, wird research automatisch geladen.
    """
    if research is None:
        research = {}
        if user_id is not None:
            try:
                from .models import get_research_levels
                research = get_research_levels(int(user_id), conn=conn)
            except Exception:
                research = {}

    terra_lvl = int(buildings.get("terraformer", 0) or 0)
    terra_factor = 1.0 + 0.05 * terra_lvl

    if mods is not None:
        storage_factor = float(mods.get("storage_factor", 1.0) or 1.0)
    else:
        storage_lvl = int(research.get("storage_tech", 0) or 0)
        storage_factor = 1.0 + 0.25 * storage_lvl

    storage_bonus = storage_factor * terra_factor

    base = 100_000
    grow = 1.8

    m_lvl = int(buildings.get("metal_storage", 0) or 0)
    c_lvl = int(buildings.get("crystal_storage", 0) or 0)

    m_cap = base * (grow ** max(0, m_lvl - 1)) if m_lvl > 0 else base
    c_cap = base * (grow ** max(0, c_lvl - 1)) if c_lvl > 0 else base

    return {
        "metal": int(m_cap * storage_bonus),
        "crystal": int(c_cap * storage_bonus),
    }

def apply_production_delta(
    planet: dict,
    buildings: Dict[str, int],
    delta_metal: int = 0,
    delta_crystal: int = 0,
    research: Optional[Dict[str, int]] = None,
    mods: Optional[Dict[str, float]] = None,
) -> None:
    """
    PRODUKTIONS-Delta:
    - Produktion darf NICHT über die Lagerkapazität hinauswachsen.
    - Bereits vorhandener Overflow (z.B. durch Farming/Rewards) wird NIE abgeschnitten.
    """
    caps = get_storage_capacity(buildings, research=research, mods=mods)
    metal_cap = max(0, int(caps.get("metal", 0) or 0))
    crystal_cap = max(0, int(caps.get("crystal", 0) or 0))

    current_metal = max(0, int(planet.get("metal", 0) or 0))
    current_crystal = max(0, int(planet.get("crystal", 0) or 0))

    if delta_metal > 0:
        free_metal = max(0, metal_cap - current_metal)
        delta_metal = min(int(delta_metal), free_metal)

    if delta_crystal > 0:
        free_crystal = max(0, crystal_cap - current_crystal)
        delta_crystal = min(int(delta_crystal), free_crystal)

    planet["metal"] = current_metal + int(delta_metal)
    planet["crystal"] = current_crystal + int(delta_crystal)


def apply_resource_delta_unbounded(
    planet: dict,
    delta_metal: int = 0,
    delta_crystal: int = 0,
) -> None:
    """
    ALLGEMEINES Resource-Delta OHNE Cap:
    - Für Farming, Events, Geschenke, Admin-Rewards gedacht.
    - Darf Overflow erzeugen.
    """
    current_metal = int(planet.get("metal", 0) or 0)
    current_crystal = int(planet.get("crystal", 0) or 0)

    planet["metal"] = max(0, current_metal + int(delta_metal))
    planet["crystal"] = max(0, current_crystal + int(delta_crystal))


# ==========================================================================
#   RESOURCE UPDATE
# ==========================================================================

def update_planet_resources(planet: dict, conn=None):
    """
    Conn-safe Update:
    - gleiche DB-Connection wird durchgereicht (wenn vorhanden)
    - verhindert "conn-mix" in /api/status und in Queue-Finishern
    """
    planet = dict(planet)  # ✅ wichtig (sqlite row -> dict)

    planet_id = int(planet["id"])

    if "player_id" not in planet:
        raise RuntimeError("Planet hat kein 'player_id' – Multi-User-Setup fehlerhaft.")

    player_id = int(planet["player_id"])

    from .models import db as _db
    own_conn = False
    if conn is None:
        conn = _db()
        own_conn = True

    try:
        if own_conn:
            conn.execute("BEGIN IMMEDIATE")

        # ✅ Fertige Jobs anwenden (muss conn-safe sein)
        complete_finished_builds_for_planet(planet_id, conn=conn)
        complete_finished_research(user_id=player_id, conn=conn)

        now = time.time()
        last_raw = planet.get("last_update")
        last = float(last_raw) if last_raw is not None else now
        delta = max(0, int(now - last))

        buildings = get_planet_buildings(planet_id, conn=conn)
        research = get_research_levels(user_id=player_id, conn=conn)
        mods = get_research_modifiers(player_id, conn=conn)

        energy_total, energy_used = compute_energy(buildings, research, mods=mods)
        ratio = 1.0 if energy_total >= energy_used else max(0.0, float(energy_total) / max(1.0, float(energy_used)))

        settings = get_game_settings(conn=conn)
        prod_speed = float(settings.get("production_speed", 1.0) or 1.0)

        if delta > 0:
            m_rate, c_rate = production_rates_per_sec(buildings, research, mods=mods)
            delta_metal = int(m_rate * ratio * delta * prod_speed)
            delta_crystal = int(c_rate * ratio * delta * prod_speed)

            apply_production_delta(
                planet,
                buildings,
                delta_metal=delta_metal,
                delta_crystal=delta_crystal,
                research=research,
                mods=mods,
            )

        planet["last_update"] = now
        planet["energy_total"] = int(energy_total)
        planet["energy_used"] = int(energy_used)

        save_planet(planet, conn=conn)

        if own_conn:
            conn.commit()

        return planet, buildings, ratio, int(energy_total), int(energy_used)

    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()


def update_resources(player: dict, conn=None):
    """
    Haupt-Aufruf aus app.py:
    - aktualisiert Homeworld-Ressourcen des jeweiligen Spielers
    - mapt relevante Werte in das player-Objekt, das im Template landet

    NEU: optional conn, damit /api/status nicht zig Connections öffnet.
    """
    from .models import get_homeworld  # lazy import, um Zyklus zu vermeiden

    player_id = int(player["id"])

    # ✅ gleiche Connection nutzen, falls übergeben
    planet = get_homeworld(player_id=player_id, conn=conn)

    # ⚠️ update_planet_resources muss idealerweise auch conn akzeptieren
    # Wenn deine resources.py das noch nicht kann: unten ist der Mini-Patch.
    planet, buildings, ratio, energy_total, energy_used = update_planet_resources(planet, conn=conn)

    player_view = dict(player)
    player_view["metal"] = planet["metal"]
    player_view["crystal"] = planet["crystal"]
    player_view["energy_total"] = energy_total
    player_view["energy_used"] = energy_used

    return player_view, buildings, ratio, energy_total, energy_used