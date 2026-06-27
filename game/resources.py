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
from typing import Any, Dict, Mapping, Tuple, Optional

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
    *,
    user_id: Optional[int] = None,
    conn=None,
) -> Dict[str, int]:
    """
    Liefert eine Übersicht der Produktion pro Stunde je Gebäude.

    Mit ``user_id``: planet scope + galaxy slot für GC-820 Slot/Temperatur-Modifier.
    """
    if user_id is not None:
        resolver = get_effect_resolver(
            int(user_id),
            buildings=buildings,
            research=research,
            conn=conn,
        )
    else:
        resolver = _resolver(buildings, research, mods)
    return resolver.get_building_production_per_hour(ratio)


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
    - Zuwachs stoppt an der Brennzellen-Kapazität (Basis-Lager wie Ferronit/Crytite, erweiterbar via fuel_storage).
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

def _refresh_planet_resource_balances(planet: dict, *, conn, planet_id: int) -> None:
    """Re-read balances after finish/tick may have credited cargo (GC-620K)."""
    from .db import lock_planet_for_update

    lock_planet_for_update(conn, int(planet_id))
    cur = conn.cursor()
    cur.execute(
        "SELECT metal, crystal, fuel_cells, last_update FROM planets WHERE id = ? LIMIT 1;",
        (int(planet_id),),
    )
    row = cur.fetchone()
    if not row:
        return
    planet["metal"] = row["metal"]
    planet["crystal"] = row["crystal"]
    planet["fuel_cells"] = row["fuel_cells"] if "fuel_cells" in row.keys() else 0
    if row["last_update"] is not None:
        planet["last_update"] = row["last_update"]


def _production_elapsed_seconds(planet: dict, *, now: float | None = None) -> tuple[float, int]:
    now_ts = float(now if now is not None else time.time())
    last_raw = planet.get("last_update")
    last = float(last_raw) if last_raw is not None else now_ts
    return now_ts, max(0, int(now_ts - last))


def _apply_production_tick(
    planet: dict,
    buildings: Dict[str, int],
    *,
    delta: int,
    resolver,
    ratio: float,
    research: Optional[Dict[str, int]],
    mods: Optional[Dict[str, float]],
    monotonic_floor: bool = True,
) -> None:
    """Apply in-memory production for elapsed seconds (optional monotonic floor vs DB row)."""
    if delta <= 0:
        return

    floor_metal = int(planet.get("metal") or 0)
    floor_crystal = int(planet.get("crystal") or 0)
    floor_fuel = int(planet.get("fuel_cells") or 0)

    m_rate, c_rate = resolver.production_rates_per_sec(ratio)
    fc_rate = resolver.fuel_cells_rate_per_sec(ratio)
    delta_metal = int(m_rate * delta)
    delta_crystal = int(c_rate * delta)
    delta_fuel_cells = int(fc_rate * delta)

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

    if not monotonic_floor:
        return

    new_metal = int(planet.get("metal") or 0)
    new_crystal = int(planet.get("crystal") or 0)
    new_fuel = int(planet.get("fuel_cells") or 0)
    if new_metal < floor_metal or new_crystal < floor_crystal or new_fuel < floor_fuel:
        import logging

        logging.getLogger(__name__).warning(
            "RESOURCE_REGRESSION planet_id=%s old_m=%s new_m=%s old_c=%s new_c=%s "
            "source=production_tick elapsed=%s",
            planet.get("id"),
            floor_metal,
            new_metal,
            floor_crystal,
            new_crystal,
            delta,
        )
    planet["metal"] = max(floor_metal, new_metal)
    planet["crystal"] = max(floor_crystal, new_crystal)
    planet["fuel_cells"] = max(floor_fuel, new_fuel)


def project_planet_resource_balances(planet: dict, *, conn, now: float | None = None) -> dict:
    """Read-only production accrual for poll/display paths (no DB persist)."""
    planet = dict(planet)
    planet_id = int(planet["id"])
    player_id = int(planet["player_id"])

    _now, delta = _production_elapsed_seconds(planet, now=now)
    buildings = get_planet_buildings(planet_id, conn=conn)
    research = get_research_levels(user_id=player_id, conn=conn)
    resolver = get_effect_resolver(
        player_id,
        buildings=buildings,
        research=research,
        conn=conn,
        force_refresh=True,
        planet=planet,
    )
    mods = resolver.get_modifiers()
    energy_total, energy_used = resolver.compute_energy()
    ratio = EffectResolver.energy_ratio(energy_total, energy_used)
    _apply_production_tick(
        planet,
        buildings,
        delta=delta,
        resolver=resolver,
        ratio=ratio,
        research=research,
        mods=mods,
        monotonic_floor=True,
    )
    return planet


def update_planet_resources(planet: dict, conn=None, *, skip_queue_finish: bool = False):
    """
    Conn-safe Update:
    - gleiche DB-Connection wird durchgereicht (wenn vorhanden)
    - verhindert "conn-mix" in /api/status und in Queue-Finishern

    skip_queue_finish: True when called from sync_derived_state_after_queue_finish only.
      Must stay True there — otherwise finish_due_work → sync → update_planet_resources would
      call finish_due_work_once again (double queue processing). sync never sets skip_queue_finish=False.
      Re-reads metal/crystal/fuel from DB first so fleet/combat credits are not overwritten.
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

        _refresh_planet_resource_balances(planet, conn=conn, planet_id=planet_id)

        now, delta = _production_elapsed_seconds(planet)

        buildings = get_planet_buildings(planet_id, conn=conn)
        research = get_research_levels(user_id=player_id, conn=conn)
        resolver = get_effect_resolver(
            player_id,
            buildings=buildings,
            research=research,
            conn=conn,
            force_refresh=True,
            planet=planet,
        )
        mods = resolver.get_modifiers()

        energy_total, energy_used = resolver.compute_energy()
        ratio = EffectResolver.energy_ratio(energy_total, energy_used)

        tick_start = float(planet.get("last_update") or now)
        prod_delta_metal = 0
        prod_delta_crystal = 0
        prod_delta_fuel = 0
        if delta > 0:
            m_rate, c_rate = resolver.production_rates_per_sec(ratio)
            fc_rate = resolver.fuel_cells_rate_per_sec(ratio)
            prod_delta_metal = int(m_rate * delta)
            prod_delta_crystal = int(c_rate * delta)
            prod_delta_fuel = int(fc_rate * delta)

        _apply_production_tick(
            planet,
            buildings,
            delta=delta,
            resolver=resolver,
            ratio=ratio,
            research=research,
            mods=mods,
            monotonic_floor=True,
        )

        if delta > 0 and (prod_delta_metal or prod_delta_crystal or prod_delta_fuel):
            try:
                from .directives.progress import emit_resource_produced_events

                emit_resource_produced_events(
                    player_id,
                    planet_id=planet_id,
                    tick_start=tick_start,
                    delta_metal=prod_delta_metal,
                    delta_crystal=prod_delta_crystal,
                    delta_fuel_cells=prod_delta_fuel,
                    conn=conn,
                    now=now,
                )
            except Exception:
                import logging

                logging.getLogger(__name__).exception(
                    "imperial_directives production progress failed player=%s planet=%s",
                    player_id,
                    planet_id,
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


# ==========================================================================
#   COMBAT LOOT / FLEET CARGO LOADING (GC-507)
# ==========================================================================

LOOT_RESOURCE_KEYS: Tuple[str, ...] = ("metal", "crystal", "fuel_cells")


def normalize_resource_stock(raw: Mapping[str, Any] | None) -> Dict[str, int]:
    """Normalize planet or pool amounts to non-negative integer resource dict."""
    src = raw or {}
    return {
        "metal": max(0, int(float(src.get("metal") or 0))),
        "crystal": max(0, int(float(src.get("crystal") or 0))),
        "fuel_cells": max(0, int(float(src.get("fuel_cells") or 0))),
    }


def calculate_plunder_pool(
    available: Mapping[str, Any],
    *,
    plunder_fraction: float = 0.5,
) -> Dict[str, int]:
    """Maximum stealable resources from a planet stock (before cargo cap)."""
    frac = max(0.0, min(1.0, float(plunder_fraction)))
    stock = normalize_resource_stock(available)
    if frac <= 0:
        return {key: 0 for key in LOOT_RESOURCE_KEYS}
    return {key: int(stock[key] * frac) for key in LOOT_RESOURCE_KEYS}


def load_resources_up_to_cargo(
    pool: Mapping[str, Any],
    remaining_cap: int,
) -> Dict[str, int]:
    """Fill cargo in Genesis order: Ferronit → Crytite → Brennzellen."""
    cap = max(0, int(remaining_cap))
    if cap <= 0:
        return {key: 0 for key in LOOT_RESOURCE_KEYS}
    avail = normalize_resource_stock(pool)
    loaded = {key: 0 for key in LOOT_RESOURCE_KEYS}
    for key in LOOT_RESOURCE_KEYS:
        if cap <= 0:
            break
        take = min(avail[key], cap)
        loaded[key] = take
        cap -= take
    return loaded


def merge_loaded_resources(
    current: Mapping[str, Any],
    added: Mapping[str, Any],
) -> Dict[str, int]:
    """Sum two resource maps (fleet cargo semantics)."""
    base = normalize_resource_stock(current)
    extra = normalize_resource_stock(added)
    return {
        key: base[key] + extra[key]
        for key in LOOT_RESOURCE_KEYS
    }


def get_planet_resource_stock(planet_id: int, *, conn) -> Dict[str, int]:
    """
    Tick production on target, then return collectable resource amounts.

    Always uses ``skip_queue_finish=True`` — safe inside fleet tick / combat loot
    where the caller already holds a write transaction (nested ``finish_due_work``
    would recurse ``process_fleet_tick`` and can SQLITE_BUSY).
    """
    from .db import lock_planet_for_update

    lock_planet_for_update(conn, int(planet_id))
    cur = conn.cursor()
    cur.execute("SELECT * FROM planets WHERE id = ? LIMIT 1;", (int(planet_id),))
    row = cur.fetchone()
    if not row:
        return {key: 0 for key in LOOT_RESOURCE_KEYS}
    planet, *_rest = update_planet_resources(
        dict(row),
        conn=conn,
        skip_queue_finish=True,
    )
    return normalize_resource_stock(planet)


def debit_planet_resources(
    planet_id: int,
    resources: Mapping[str, Any],
    *,
    conn,
) -> bool:
    """Debit metal/crystal/fuel_cells from a planet if balances allow (fleet-safe)."""
    from .fleet_calc import calculate_loaded_resources
    from .db import lock_planet_for_update

    loaded = calculate_loaded_resources(resources)
    if loaded["metal"] <= 0 and loaded["crystal"] <= 0 and loaded["fuel_cells"] <= 0:
        return True
    lock_planet_for_update(conn, int(planet_id))
    cur = conn.cursor()
    cur.execute(
        "SELECT metal, crystal, fuel_cells FROM planets WHERE id = ? LIMIT 1;",
        (int(planet_id),),
    )
    row = cur.fetchone()
    if not row:
        return False
    new_metal = float(row["metal"]) - loaded["metal"]
    new_crystal = float(row["crystal"]) - loaded["crystal"]
    new_fuel_cells = float(row["fuel_cells"] or 0) - loaded["fuel_cells"]
    if new_metal < 0 or new_crystal < 0 or new_fuel_cells < 0:
        return False
    cur.execute(
        "UPDATE planets SET metal = ?, crystal = ?, fuel_cells = ? WHERE id = ?;",
        (new_metal, new_crystal, new_fuel_cells, int(planet_id)),
    )
    return True