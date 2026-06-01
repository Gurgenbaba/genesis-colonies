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
from .queue_engine import finish_due_work_once
from .effects import EffectResolver, get_effect_resolver


# ==========================================================================
#   ENERGY & PRODUCTION
# ==========================================================================

def _resolver(
    buildings: Dict[str, int],
    research: Optional[Dict[str, int]] = None,
    mods: Optional[Dict[str, float]] = None,
) -> EffectResolver:
    research = research or {}
    resolver = EffectResolver(buildings, research)
    if mods is not None:
        resolver._mods = dict(mods)
    return resolver


def compute_energy(
    buildings: Dict[str, int],
    research: Optional[Dict[str, int]] = None,
    mods: Optional[Dict[str, float]] = None,
) -> Tuple[int, int]:
    """Delegates to EffectResolver (authoritative)."""
    return _resolver(buildings, research, mods).compute_energy()


def production_rates_per_sec(
    buildings: Dict[str, int],
    research: Optional[Dict[str, int]] = None,
    mods: Optional[Dict[str, float]] = None,
) -> Tuple[float, float]:
    """Delegates to EffectResolver (authoritative)."""
    return _resolver(buildings, research, mods).production_rates_per_sec()


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
    return _resolver(buildings, research, mods).get_building_production_per_hour(ratio)


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

    return _resolver(buildings, research, mods).get_storage_capacity()

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


def apply_fuel_production_delta(
    planet: dict,
    buildings: Dict[str, int],
    delta_fuel_cells: int = 0,
    research: Optional[Dict[str, int]] = None,
    mods: Optional[Dict[str, float]] = None,
) -> None:
    """
    Brennzellen-Produktion:
    - Zuwachs stoppt am Werks-Lager (wie Minen-Produktion).
    - Bestehendes Overflow (Tausch/Schrott/Rewards) wird nie abgeschnitten.
    """
    if delta_fuel_cells <= 0:
        return
    caps = get_storage_capacity(buildings, research=research, mods=mods)
    fuel_cap = int(caps.get("fuel_cells") or 0)
    current_fuel = max(0, int(float(planet.get("fuel_cells") or 0)))
    if fuel_cap > 0 and current_fuel >= fuel_cap:
        return
    if fuel_cap > 0:
        free_fuel = max(0, fuel_cap - current_fuel)
        delta_fuel_cells = min(int(delta_fuel_cells), free_fuel)
    if delta_fuel_cells <= 0:
        return
    planet["fuel_cells"] = max(0.0, float(current_fuel) + delta_fuel_cells)


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

def update_planet_resources(planet: dict, conn=None, *, skip_queue_finish: bool = False):
    """
    Conn-safe Update:
    - gleiche DB-Connection wird durchgereicht (wenn vorhanden)
    - verhindert "conn-mix" in /api/status und in Queue-Finishern

    skip_queue_finish: True when called from sync_derived_state_after_queue_finish only.
      Must stay True there — otherwise finish_due_work → sync → update_planet_resources would
      call finish_due_work_once again (double queue processing). sync never sets skip_queue_finish=False.
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
            from .db import begin_write_transaction

            begin_write_transaction(conn)

        if not skip_queue_finish:
            finish_due_work_once(
                player_id=player_id,
                planet_id=planet_id,
                conn=conn,
                source="resources",
            )
            from .live_state import mark_request_live_refreshed

            mark_request_live_refreshed()

        now = time.time()
        last_raw = planet.get("last_update")
        last = float(last_raw) if last_raw is not None else now
        delta = max(0, int(now - last))

        buildings = get_planet_buildings(planet_id, conn=conn)
        research = get_research_levels(user_id=player_id, conn=conn)
        resolver = get_effect_resolver(
            player_id,
            buildings=buildings,
            research=research,
            conn=conn,
            force_refresh=True,
        )
        mods = resolver.get_modifiers()

        energy_total, energy_used = resolver.compute_energy()
        ratio = EffectResolver.energy_ratio(energy_total, energy_used)

        settings = get_game_settings(conn=conn)
        prod_speed = float(settings.get("production_speed", 1.0) or 1.0)

        if delta > 0:
            m_rate, c_rate = resolver.production_rates_per_sec()
            fc_rate = resolver.fuel_cells_rate_per_sec()
            delta_metal = int(m_rate * ratio * delta * prod_speed)
            delta_crystal = int(c_rate * ratio * delta * prod_speed)
            delta_fuel_cells = int(fc_rate * ratio * delta * prod_speed)

            apply_production_delta(
                planet,
                buildings,
                delta_metal=delta_metal,
                delta_crystal=delta_crystal,
                research=research,
                mods=mods,
            )
            apply_fuel_production_delta(
                planet,
                buildings,
                delta_fuel_cells=delta_fuel_cells,
                research=research,
                mods=mods,
            )

        planet["last_update"] = now
        planet["energy_total"] = int(energy_total)
        planet["energy_used"] = int(energy_used)

        save_planet(planet, conn=conn)

        try:
            from .planet_evolution.repository import evolution_schema_ready

            if evolution_schema_ready(conn):
                from .planet_evolution.bootstrap import ensure_planet_evolution
                from .planet_evolution.tick import evolution_tick_planet

                ensure_planet_evolution(planet_id, conn)
                evolution_tick_planet(
                    conn,
                    planet_id,
                    now,
                    skip_research_finish=bool(skip_queue_finish),
                )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "planet evolution tick failed planet_id=%s", planet_id
            )

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
    Refresh resources for the player's active context planet (not homeworld-only).
    """
    from .planet_evolution.repository import get_context_planet

    player_id = int(player["id"])
    planet = get_context_planet(player_id, conn=conn)
    planet, buildings, ratio, energy_total, energy_used = update_planet_resources(planet, conn=conn)

    player_view = dict(player)
    player_view["metal"] = planet["metal"]
    player_view["crystal"] = planet["crystal"]
    player_view["fuel_cells"] = planet.get("fuel_cells", 0)
    player_view["energy_total"] = energy_total
    player_view["energy_used"] = energy_used

    return player_view, buildings, ratio, energy_total, energy_used


def sync_derived_state_after_queue_finish(
    *,
    planet_ids=None,
    player_ids=None,
    conn=None,
) -> int:
    """
    Persist authoritative derived state (energy, production tick, caps) after queue finish.
    Safe for cron/admin ticks without a player HTTP request.

    Recursion-safe: only calls update_planet_resources(..., skip_queue_finish=True).
    Never invokes finish_due_work_once (queue work already finished by the caller).
    """
    from .models import db as _db, get_homeworld

    own_conn = False
    if conn is None:
        conn = _db()
        own_conn = True

    synced: set[int] = set()
    count = 0

    try:
        if own_conn:
            from .db import begin_write_transaction

            begin_write_transaction(conn)

        for raw_pid in planet_ids or []:
            planet_id = int(raw_pid)
            if planet_id in synced:
                continue
            cur = conn.cursor()
            cur.execute("SELECT * FROM planets WHERE id = ? LIMIT 1;", (planet_id,))
            row = cur.fetchone()
            if not row:
                continue
            update_planet_resources(dict(row), conn=conn, skip_queue_finish=True)
            synced.add(planet_id)
            count += 1

        for raw_uid in player_ids or []:
            user_id = int(raw_uid)
            from .models import get_planets_by_player

            try:
                planets = get_planets_by_player(user_id, conn=conn)
            except Exception:
                continue
            for planet in planets:
                planet_id = int(planet["id"])
                if planet_id in synced:
                    continue
                update_planet_resources(dict(planet), conn=conn, skip_queue_finish=True)
                synced.add(planet_id)
                count += 1

        if own_conn:
            conn.commit()
    except Exception:
        if own_conn:
            conn.rollback()
        raise
    finally:
        if own_conn:
            conn.close()

    return count