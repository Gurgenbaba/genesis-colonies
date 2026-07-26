"""Expansion Protocol — dual-gate colonization (GC-921–GC-929).

See docs/EXPANSION_PROTOCOL.md. Gates read Genesis Ark level + Interstellar Expansion tech.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

import sqlite3

from ..models import get_homeworld, get_planet_buildings, get_planets_by_player, get_research_levels
from .expansion_gates import EXPANSION_SITES, get_homeworld_level
from .expansion_phase import is_establishment_complete
from .repository import get_planet_row
from .world_colonization import parse_world_key

INTERSTELLAR_EXPANSION_TECH = "interstellar_expansion"
INTERSTELLAR_EXPANSION_MAX_LEVEL = 6

# Nth expansion world (1 = first colony after homeworld).
EXPANSION_SLOT_GATES: Tuple[Dict[str, int], ...] = (
    {"expansion_index": 1, "homeworld_level": 5, "expansion_tech": 1},
    {"expansion_index": 2, "homeworld_level": 10, "expansion_tech": 2},
    {"expansion_index": 3, "homeworld_level": 15, "expansion_tech": 3},
    {"expansion_index": 4, "homeworld_level": 20, "expansion_tech": 4},
    {"expansion_index": 5, "homeworld_level": 25, "expansion_tech": 5},
    {"expansion_index": 6, "homeworld_level": 30, "expansion_tech": 6},
)

WORLD_TYPE_GATES: Dict[str, Dict[str, int]] = {
    "mining_world": {"homeworld_level": 5, "expansion_tech": 1},
    "industrial_world": {"homeworld_level": 5, "expansion_tech": 1},
    "research_world": {"homeworld_level": 5, "expansion_tech": 1},
    "trade_world": {"homeworld_level": 10, "expansion_tech": 2},
    "fortress_world": {"homeworld_level": 10, "expansion_tech": 2},
    "volcanic_world": {"homeworld_level": 20, "expansion_tech": 3},
    "ice_world": {"homeworld_level": 30, "expansion_tech": 4},
    "ancient_world": {"homeworld_level": 40, "expansion_tech": 5},
    "void_world": {"homeworld_level": 60, "expansion_tech": 6},
}

WORLD_TYPE_START_FLAGS: Dict[str, Dict[str, Any]] = {
    "mining_world": {
        "world_start_metal_mult": 1.15,
        "world_start_crystal_mult": 0.92,
    },
    "industrial_world": {
        "world_start_buildtime_mult": 0.94,
        "world_start_metal_mult": 1.05,
    },
    "research_world": {
        "world_start_planet_research_speed": 0.12,
        "world_start_energy_demand_mult": 1.08,
    },
    "fortress_world": {
        "world_start_defense_bonus": 0.1,
        "world_start_metal_mult": 0.9,
    },
    "trade_world": {
        "world_start_trade_route_bonus": 0.08,
        "world_start_crystal_mult": 1.1,
    },
    "volcanic_world": {
        "world_start_energy_surplus": True,
        "world_start_metal_mult": 0.75,
        "world_start_crystal_mult": 0.5,
    },
    "ice_world": {
        "world_start_fuel_mult": 1.25,
        "world_start_crystal_mult": 1.2,
        "world_start_energy_demand_mult": 1.2,
    },
    "ancient_world": {
        "world_start_ancient_events": True,
        "world_start_metal_mult": 0.6,
    },
}

OUTPOST_ALLOWED_BUILDINGS = frozenset(
    {
        "metal_mine",
        "crystal_mine",
        "fuel_cell_plant",
        "solar_plant",
        "metal_storage",
        "crystal_storage",
        "fuel_storage",
        "command_center",
        "radar_array",
    }
)

OUTPOST_DISABLED_BUILDINGS = frozenset(
    {
        "orbital_shipyard",
        "shipyard",
        "research_lab",
        "academy",
        "defense_factory",
        "missile_silo",
        "planetary_shield",
        "laser_turret",
        "ion_cannon",
        "gauss_cannon",
        "plasma_turret",
    }
)

OUTPOST_MAX_BUILDING_SLOTS = 5


def interstellar_expansion_level(player_id: int, *, conn: sqlite3.Connection) -> int:
    levels = get_research_levels(int(player_id), conn=conn) or {}
    return max(0, min(INTERSTELLAR_EXPANSION_MAX_LEVEL, int(levels.get(INTERSTELLAR_EXPANSION_TECH) or 0)))


def count_expansion_worlds(player_id: int, *, conn: sqlite3.Connection) -> int:
    planets = get_planets_by_player(int(player_id), conn=conn) or []
    return sum(1 for p in planets if not bool(p.get("is_homeworld")))


def expansion_slots_unlocked(homeworld_level: int) -> int:
    """Colony slots (excluding homeworld) unlocked at this Genesis Ark level (GC-976A)."""
    hw = max(0, int(homeworld_level or 0))
    unlocked = 0
    for gate in EXPANSION_SLOT_GATES:
        if hw >= int(gate["homeworld_level"]):
            unlocked = int(gate["expansion_index"])
    return unlocked


def effective_max_worlds_for_homeworld_level(homeworld_level: int) -> int:
    """Total owned worlds allowed (homeworld + colonies) from HW progression."""
    return 1 + expansion_slots_unlocked(homeworld_level)


def next_expansion_slot_homeworld_level(expansion_colonies: int) -> int:
    """HW level required to unlock the next colony after expansion_colonies."""
    next_index = max(1, int(expansion_colonies) + 1)
    return int(_slot_gate_for_next_expansion(next_index)["homeworld_level"])


def expansion_gameplay_cap(player_id: int, *, conn: sqlite3.Connection) -> Dict[str, int]:
    """HW-derived colony cap merged with admin safety ceiling (GC-976A)."""
    from game.logic import get_max_planets_per_player

    uid = int(player_id)
    hw_level = get_homeworld_level(uid, conn=conn)
    slots = expansion_slots_unlocked(hw_level)
    effective = effective_max_worlds_for_homeworld_level(hw_level)
    # GC-720J: expansion directive may grant extra colony slots (galaxy of homeworld).
    try:
        from game.galactic_directives.mechanics import get_directive_flags_for_galaxy

        hw = get_homeworld(uid, conn=conn) or {}
        galaxy = int(hw.get("galaxy") or 0)
        if galaxy > 0:
            flags = get_directive_flags_for_galaxy(galaxy, conn=conn) or {}
            effective += max(0, int(flags.get("max_colonies_bonus") or 0))
    except Exception:
        pass
    admin = int(get_max_planets_per_player(conn=conn))
    return {
        "homeworld_level": int(hw_level),
        "expansion_slots_unlocked": int(slots),
        "effective_max_worlds": int(effective),
        "admin_ceiling": admin,
        "gameplay_cap": min(effective, admin),
    }


def _expansion_slot_cap_reached(expansion_colonies: int, slots_unlocked: int) -> bool:
    """True when no further colonies are allowed at the current HW slot unlock tier."""
    colonies = max(0, int(expansion_colonies))
    slots = max(0, int(slots_unlocked))
    if slots <= 0:
        return colonies > 0
    return colonies >= slots


def _slot_gate_for_next_expansion(next_index: int) -> Dict[str, int]:
    idx = max(1, int(next_index))
    for gate in EXPANSION_SLOT_GATES:
        if int(gate["expansion_index"]) == idx:
            return dict(gate)
    last = EXPANSION_SLOT_GATES[-1]
    extra = idx - int(last["expansion_index"])
    return {
        "expansion_index": idx,
        "homeworld_level": int(last["homeworld_level"]) + extra * 5,
        "expansion_tech": min(INTERSTELLAR_EXPANSION_MAX_LEVEL, int(last["expansion_tech"]) + extra),
    }


def _world_type_from_target(
    *,
    world_key: str | None = None,
    world_type: str | None = None,
    site_key: str | None = None,
) -> Optional[str]:
    wt = str(world_type or "").strip()
    if wt:
        return wt
    wk = str(world_key or "").strip()
    if wk:
        if wk in EXPANSION_SITES:
            return str(EXPANSION_SITES[wk].get("site_type") or "outpost")
        try:
            return str(parse_world_key(wk).get("world_type") or "")
        except Exception:
            return None
    sk = str(site_key or "").strip()
    if sk in EXPANSION_SITES:
        return str(EXPANSION_SITES[sk].get("site_type") or "outpost")
    return None


def _gate_requirements(
    *,
    next_expansion_index: int,
    world_key: str | None = None,
    world_type: str | None = None,
    site_key: str | None = None,
) -> Dict[str, int]:
    slot = _slot_gate_for_next_expansion(next_expansion_index)
    req_hw = int(slot.get("homeworld_level") or 5)
    req_tech = int(slot.get("expansion_tech") or 1)

    sk = str(site_key or "").strip()
    if not sk and world_key and str(world_key) in EXPANSION_SITES:
        sk = str(world_key)
    if sk in EXPANSION_SITES:
        req_hw = max(req_hw, int(EXPANSION_SITES[sk].get("required_homeworld_level") or 1))

    wt = _world_type_from_target(world_key=world_key, world_type=world_type, site_key=site_key)
    if wt and wt in WORLD_TYPE_GATES:
        type_gate = WORLD_TYPE_GATES[wt]
        req_hw = max(req_hw, int(type_gate.get("homeworld_level") or 1))
        req_tech = max(req_tech, int(type_gate.get("expansion_tech") or 1))

    return {
        "homeworld_level": req_hw,
        "expansion_tech": req_tech,
        "expansion_index": int(next_expansion_index),
    }


def evaluate_expansion_gates(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    world_key: str | None = None,
    world_type: str | None = None,
    site_key: str | None = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Dual-gate check — Genesis Ark level + Interstellar Expansion tech."""
    uid = int(player_id)
    hw_level = get_homeworld_level(uid, conn=conn)
    tech_level = interstellar_expansion_level(uid, conn=conn)
    next_index = count_expansion_worlds(uid, conn=conn) + 1
    req = _gate_requirements(
        next_expansion_index=next_index,
        world_key=world_key,
        world_type=world_type,
        site_key=site_key,
    )

    meta: Dict[str, Any] = {
        "homeworld_level": hw_level,
        "expansion_tech_level": tech_level,
        "required_homeworld_level": int(req["homeworld_level"]),
        "required_expansion_tech": int(req["expansion_tech"]),
        "expansion_index": int(req["expansion_index"]),
        "world_type": _world_type_from_target(world_key=world_key, world_type=world_type, site_key=site_key),
    }

    if hw_level < int(req["homeworld_level"]):
        return False, "expansion_gate_homeworld_level", meta
    if tech_level < int(req["expansion_tech"]):
        return False, "expansion_gate_interstellar_tech", meta

    wt = meta.get("world_type")
    if wt and wt in WORLD_TYPE_GATES:
        type_gate = WORLD_TYPE_GATES[str(wt)]
        if hw_level < int(type_gate["homeworld_level"]) or tech_level < int(type_gate["expansion_tech"]):
            return False, "expansion_gate_world_type", meta

    return True, "", meta


def can_found_colony(
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Tuple[bool, str]:
    """Galaxy colonize cap — min(admin ceiling, HW evolution slots). No world-map/outpost gates."""
    from game.logic import get_max_planets_per_player
    from .repository import evolution_schema_ready

    uid = int(player_id)
    planets = get_planets_by_player(uid, conn=conn) or []
    total = len(planets)
    admin = int(get_max_planets_per_player(conn=conn))

    if total >= admin:
        return False, "colony_limit_reached"

    if evolution_schema_ready(conn):
        cap = expansion_gameplay_cap(uid, conn=conn)
        evolution_max = int(cap["effective_max_worlds"])
    else:
        evolution_max = 1

    if total >= evolution_max:
        return False, "planet_evolution_colony_slot_required"

    return True, ""


def can_found_expansion_world(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    world_key: str | None = None,
    world_type: str | None = None,
    site_key: str | None = None,
) -> Tuple[bool, str]:
    """Gate matrix + HW progression cap + admin safety ceiling (grandfathering)."""
    uid = int(player_id)
    cap = expansion_gameplay_cap(uid, conn=conn)
    expansion_count = count_expansion_worlds(uid, conn=conn)
    slots_unlocked = int(cap["expansion_slots_unlocked"])
    if _expansion_slot_cap_reached(expansion_count, slots_unlocked):
        return False, "expansion_slot_cap_reached"

    ok, reason, _meta = evaluate_expansion_gates(
        uid,
        conn=conn,
        world_key=world_key,
        world_type=world_type,
        site_key=site_key,
    )
    if not ok:
        return False, reason

    total = len(get_planets_by_player(uid, conn=conn) or [])
    if total >= int(cap["admin_ceiling"]):
        return False, "expansion_admin_ceiling_reached"
    return True, ""


def get_expansion_limit_block(
    player_id: int,
    *,
    conn: sqlite3.Connection,
) -> Dict[str, Any]:
    """Expansion-focused limit block for game-state / empire."""
    uid = int(player_id)
    planets = get_planets_by_player(uid, conn=conn) or []
    expansion_count = sum(1 for p in planets if not bool(p.get("is_homeworld")))
    total = len(planets)
    cap = expansion_gameplay_cap(uid, conn=conn)
    hw_level = int(cap["homeworld_level"])
    slots_unlocked = int(cap["expansion_slots_unlocked"])
    effective = int(cap["effective_max_worlds"])
    admin = int(cap["admin_ceiling"])
    gameplay_cap = int(cap["gameplay_cap"])
    tech_level = interstellar_expansion_level(uid, conn=conn)
    next_index = expansion_count + 1
    req = _gate_requirements(next_expansion_index=next_index)
    ok, reason, _meta = evaluate_expansion_gates(uid, conn=conn)
    under_cap = total < gameplay_cap
    next_unlock_level = (
        next_expansion_slot_homeworld_level(expansion_count)
        if expansion_count >= slots_unlocked
        else None
    )

    return {
        "current": int(expansion_count),
        "owned_worlds": int(total),
        "admin_ceiling": admin,
        "at_admin_ceiling": bool(total >= admin),
        "expansion_slots_unlocked": slots_unlocked,
        "effective_max_worlds": effective,
        "homeworld_level": hw_level,
        "expansion_tech_level": int(tech_level),
        "required_homeworld_level": int(req["homeworld_level"]),
        "required_expansion_tech": int(req["expansion_tech"]),
        "next_unlock_homeworld_level": next_unlock_level,
        "can_expand": bool(ok and under_cap),
        "gate_reason": str(reason or ""),
        "max": int(gameplay_cap),
    }


def _seed_ark_available(player_id: int, *, conn: sqlite3.Connection) -> bool:
    from ..fleet import get_planet_ships

    hw = get_homeworld(int(player_id), conn=conn)
    if not hw:
        return False
    ships = get_planet_ships(int(hw["id"]), conn=conn) or {}
    return int(ships.get("seed_ark") or 0) >= 1


def build_expansion_launch_checklist(
    player_id: int,
    *,
    conn: sqlite3.Connection,
    world_key: str | None = None,
    world_type: str | None = None,
    site_key: str | None = None,
) -> Dict[str, Any]:
    """Command Map site inspector checklist (GC-926)."""
    uid = int(player_id)
    ok_gates, gate_reason, meta = evaluate_expansion_gates(
        uid,
        conn=conn,
        world_key=world_key,
        world_type=world_type,
        site_key=site_key,
    )
    hw_level = int(meta.get("homeworld_level") or 0)
    tech_level = int(meta.get("expansion_tech_level") or 0)
    req_hw = int(meta.get("required_homeworld_level") or 5)
    req_tech = int(meta.get("required_expansion_tech") or 1)
    seed_ready = _seed_ark_available(uid, conn=conn)

    items: List[Dict[str, Any]] = [
        {
            "key": "genesis_ark_level",
            "label_key": "expansion_checklist_genesis_ark_level",
            "met": hw_level >= req_hw,
            "current": hw_level,
            "required": req_hw,
        },
        {
            "key": "interstellar_expansion",
            "label_key": "expansion_checklist_interstellar_tech",
            "met": tech_level >= req_tech,
            "current": tech_level,
            "required": req_tech,
        },
        {
            "key": "seed_ark",
            "label_key": "expansion_checklist_seed_ark",
            "met": seed_ready,
        },
    ]

    from game.logic import check_planet_cap_available

    total = len(get_planets_by_player(uid, conn=conn) or [])
    cap = expansion_gameplay_cap(uid, conn=conn)
    gameplay_cap = int(cap["gameplay_cap"])
    under_cap = total < gameplay_cap
    can_launch = bool(ok_gates and seed_ready and under_cap)
    if not under_cap:
        if _expansion_slot_cap_reached(
            count_expansion_worlds(uid, conn=conn),
            int(cap["expansion_slots_unlocked"]),
        ):
            gate_reason = gate_reason or "expansion_slot_cap_reached"
        else:
            gate_reason = gate_reason or "expansion_admin_ceiling_reached"

    items.append(
        {
            "key": "launch",
            "label_key": "expansion_checklist_launch",
            "met": can_launch,
        }
    )

    return {
        "items": items,
        "can_launch": can_launch,
        "blocked_reason_key": str(gate_reason or "") if not can_launch else "",
        "homeworld_level": hw_level,
        "expansion_tech_level": tech_level,
        "required_homeworld_level": req_hw,
        "required_expansion_tech": req_tech,
        "seed_ark_ready": seed_ready,
    }


def is_legacy_full_colony(
    planet_id: int,
    *,
    planet: Mapping[str, Any] | None = None,
    conn: sqlite3.Connection,
) -> bool:
    """Colonies that predate frontier-outpost gates — must stay fully playable (GC-976 legacy)."""
    pid = int(planet_id)
    row = planet if planet is not None else (get_planet_row(pid, conn=conn) or {})
    if int(row.get("is_homeworld") or 0) == 1:
        return True
    if int(row.get("planet_level") or 0) >= 1:
        return True
    if int(row.get("dna_reveal_tier") or 0) >= 1:
        return True

    try:
        buildings = get_planet_buildings(pid, conn=conn) or {}
    except Exception:
        buildings = {}

    for btype in OUTPOST_DISABLED_BUILDINGS:
        if int(buildings.get(btype) or 0) >= 1:
            return True

    distinct_slots = sum(1 for level in buildings.values() if int(level or 0) > 0)
    if distinct_slots > OUTPOST_MAX_BUILDING_SLOTS:
        return True
    return False


def bootstrap_legacy_establishment(planet_id: int, *, conn: sqlite3.Connection) -> bool:
    """Promote pre-outpost colonies that already matured before establishment milestones existed."""
    pid = int(planet_id)
    planet = get_planet_row(pid, conn=conn) or {}
    if int(planet.get("is_homeworld") or 0) == 1:
        return False

    wk = str(planet.get("world_key") or planet.get("origin_world_key") or "").strip()
    if not wk:
        return False
    if not is_legacy_full_colony(pid, planet=planet, conn=conn):
        return False
    if is_establishment_complete(pid, conn=conn):
        return False

    changed = False
    if int(planet.get("dna_reveal_tier") or 0) < 1:
        conn.execute(
            "UPDATE planets SET dna_reveal_tier = 1 WHERE id = ? AND dna_reveal_tier < 1;",
            (pid,),
        )
        changed = True
    if int(planet.get("planet_level") or 0) < 1:
        conn.execute(
            "UPDATE planets SET planet_level = 1 WHERE id = ? AND planet_level < 1;",
            (pid,),
        )
        changed = True

    from .mechanics import compile_planet_mechanics

    compile_planet_mechanics(pid, conn)
    return changed


def is_outpost_planet(planet_id: int, *, conn: sqlite3.Connection) -> bool:
    planet = get_planet_row(int(planet_id), conn=conn) or {}
    if int(planet.get("is_homeworld") or 0) == 1:
        return False
    wk = str(planet.get("world_key") or planet.get("origin_world_key") or "").strip()
    if not wk:
        return False
    if is_legacy_full_colony(int(planet_id), planet=planet, conn=conn):
        return False
    return not is_establishment_complete(int(planet_id), conn=conn)


def is_building_allowed_in_outpost(
    planet_id: int,
    building_type: str,
    *,
    conn: sqlite3.Connection,
) -> Tuple[bool, str]:
    if not is_outpost_planet(planet_id, conn=conn):
        return True, ""
    btype = str(building_type or "").strip()
    if btype in OUTPOST_DISABLED_BUILDINGS:
        return False, "outpost_building_restricted"
    if btype not in OUTPOST_ALLOWED_BUILDINGS:
        return False, "outpost_building_restricted"

    buildings = get_planet_buildings(int(planet_id), conn=conn) or {}
    total_slots = sum(int(v or 0) for v in buildings.values())
    current = int(buildings.get(btype) or 0)
    if current <= 0 and total_slots >= OUTPOST_MAX_BUILDING_SLOTS:
        return False, "outpost_building_slots_full"
    return True, ""


def apply_outpost_mechanics_flags(
    planet_id: int,
    compiled: Dict[str, Any],
    *,
    conn: sqlite3.Connection,
) -> None:
    if not is_outpost_planet(planet_id, conn=conn):
        return
    flags = compiled.setdefault("flags", {})
    flags["outpost_mode"] = True
    flags["colony_maturity"] = "frontier_outpost"
    flags["disabled_buildings"] = sorted(OUTPOST_DISABLED_BUILDINGS)
    flags["max_building_slots"] = OUTPOST_MAX_BUILDING_SLOTS
    flags["trade_route_auto"] = "genesis_ark"

    planet = get_planet_row(int(planet_id), conn=conn) or {}
    wt = str(planet.get("planet_role") or "").strip()
    if not wt:
        wk = str(planet.get("world_key") or "").strip()
        try:
            wt = str(parse_world_key(wk).get("world_type") or "") if wk else ""
        except Exception:
            wt = ""
    start = WORLD_TYPE_START_FLAGS.get(wt) or {}
    for key, val in start.items():
        flags[key] = val


def sync_establishment_state(planet_id: int, *, conn: sqlite3.Connection) -> bool:
    """Refresh outpost flags / DNA reveal when establishment milestones complete (GC-928)."""
    from .mechanics import compile_planet_mechanics

    pid = int(planet_id)
    planet = get_planet_row(pid, conn=conn) or {}
    if bool(planet.get("is_homeworld")):
        return False

    wk = str(planet.get("world_key") or planet.get("origin_world_key") or "").strip()
    if not wk:
        return False

    if not is_establishment_complete(pid, conn=conn):
        compile_planet_mechanics(pid, conn)
        return False

    changed = False
    reveal = int(planet.get("dna_reveal_tier") or 0)
    level = int(planet.get("planet_level") if planet.get("planet_level") is not None else 1)

    if reveal < 1:
        conn.execute(
            "UPDATE planets SET dna_reveal_tier = 1 WHERE id = ? AND dna_reveal_tier < 1;",
            (pid,),
        )
        changed = True
    if level < 1:
        conn.execute(
            "UPDATE planets SET planet_level = 1 WHERE id = ? AND planet_level < 1;",
            (pid,),
        )
        changed = True

    compile_planet_mechanics(pid, conn)
    return changed


def interstellar_expansion_reach_label(level: int) -> str:
    """i18n key for tech tier reach (presentation)."""
    lvl = max(0, min(INTERSTELLAR_EXPANSION_MAX_LEVEL, int(level or 0)))
    if lvl <= 0:
        return "interstellar_expansion_reach_0"
    return f"interstellar_expansion_reach_{lvl}"
