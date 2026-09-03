"""One-shot GC-PERF-SHIPYARD-CATALOG-001 patch helper."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "game" / "shipyard.py"


def replace_block(src: str, start: str, end: str, new: str, label: str) -> str:
    i = src.find(start)
    if i < 0:
        raise SystemExit(f"{label}: start marker missing")
    j = src.find(end, i)
    if j < 0:
        raise SystemExit(f"{label}: end marker missing")
    return src[:i] + new.rstrip() + "\n\n\n" + src[j:]


def main() -> int:
    src = TARGET.read_text(encoding="utf-8")
    if "GC-PERF-SHIPYARD-CATALOG-001" in src:
        print("GC-PERF-SHIPYARD-CATALOG-001 already applied")
        return 0

    src = replace_block(
        src,
        "def _effective_build_seconds(\n",
        "def unit_build_seconds(\n",
        '''def _effective_build_seconds(
    ship_key: str,
    shipyard_level: int,
    *,
    conn=None,
    planet_id: int | None = None,
    build_time_speed: float | None = None,
) -> int:
    spec = get_ship(ship_key)
    if not spec:
        return 0
    base = max(1, int(spec.get("build_seconds") or 1))
    lvl = max(1, int(shipyard_level or 1))
    seconds = max(1, int(math.ceil(base * (BUILD_TIME_LEVEL_FACTOR ** (lvl - 1)))))
    speed = (
        max(0.000001, float(build_time_speed))
        if build_time_speed is not None
        else _shipyard_speed_multiplier(conn=conn)
        * _directive_time_speed(planet_id, "shipyard_time_speed", conn=conn)
    )
    return max(1, int(math.ceil(seconds / speed)))''',
        "effective build seconds",
    )

    src = replace_block(
        src,
        "def ship_unlocked(\n",
        "def _ship_catalog_entry(\n",
        '''def ship_unlocked(
    ship_key: str,
    shipyard_level: int,
    *,
    player_id: int | None = None,
    planet_id: int | None = None,
    conn=None,
    buildings: Mapping[str, Any] | None = None,
    research: Mapping[str, Any] | None = None,
) -> bool:
    spec = get_ship(ship_key)
    if not spec or spec.get("phase2_only"):
        return False
    need = int(spec.get("required_shipyard_level") or 99)
    if int(shipyard_level) < need:
        return False
    if player_id is not None and planet_id is not None:
        from .ship_requirements import check_ship_requirements

        if buildings is None:
            from .models import get_planet_buildings

            buildings = get_planet_buildings(int(planet_id), conn=conn)
        if research is None:
            from .models import get_research_levels

            research = get_research_levels(user_id=int(player_id), conn=conn)
        ok, _ = check_ship_requirements(ship_key, buildings=buildings, research=research)
        return ok
    return True''',
        "ship unlocked",
    )

    src = replace_block(
        src,
        "def _ship_catalog_entry(\n",
        "def list_buildable_ships(\n",
        '''def _ship_catalog_entry(
    ship_key: str,
    shipyard_level: int,
    *,
    player_id: int | None = None,
    planet_id: int | None = None,
    conn=None,
    buildings: Mapping[str, Any] | None = None,
    research: Mapping[str, Any] | None = None,
    unlocked: bool | None = None,
    forge_rank: int | None = None,
    build_time_speed: float | None = None,
    unit_cost: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    spec = get_ship(ship_key) or {}
    cost = dict(unit_cost) if unit_cost is not None else _unit_build_cost(
        ship_key, planet_id=planet_id, conn=conn
    )
    unlocked_value = (
        bool(unlocked)
        if unlocked is not None
        else ship_unlocked(
            ship_key,
            shipyard_level,
            player_id=player_id,
            planet_id=planet_id,
            conn=conn,
            buildings=buildings,
            research=research,
        )
    )
    forge_rank_value = (
        max(0, int(forge_rank))
        if forge_rank is not None
        else forge_rank_for_planet(planet_id, conn=conn)
    )
    entry: Dict[str, Any] = {
        "ship_key": ship_key,
        "role": ship_display_role(ship_key),
        "attack": int(spec.get("attack", 0) or 0),
        "shield": int(spec.get("shield", 0) or 0),
        "hull": int(spec.get("hull", 0) or 0),
        "required_shipyard_level": int(spec.get("required_shipyard_level") or 99),
        "unlocked": unlocked_value,
        "cost_metal": int(cost.get("metal") or 0),
        "cost_crystal": int(cost.get("crystal") or 0),
        "cost_fuel_cells": int(cost.get("fuel_cells") or 0),
        "build_seconds": _effective_build_seconds(
            ship_key,
            shipyard_level,
            conn=conn,
            planet_id=planet_id,
            build_time_speed=build_time_speed,
        ),
        "effective_batch_capacity": unit_batch_capacity(
            shipyard_level,
            base_unit_seconds_for_ship(ship_key),
            forge_rank_value,
        ),
        "max_build": 0,
        "can_build": False,
        "block_reason": "",
        "icon": ship_icon_static_path(ship_key),
        "owned_count": 0,
    }
    if player_id is not None and planet_id is not None:
        from .ship_requirements import requirements_summary_for_client

        if buildings is None:
            from .models import get_planet_buildings

            buildings = get_planet_buildings(int(planet_id), conn=conn)
        if research is None:
            from .models import get_research_levels

            research = get_research_levels(user_id=int(player_id), conn=conn)
        entry["requirements"] = requirements_summary_for_client(
            ship_key, buildings=buildings, research=research
        )
    return entry


def _build_shipyard_catalogs_shared(
    player_id: int,
    planet_id: int,
    *,
    conn=None,
) -> Dict[str, Any]:
    """GC-PERF-SHIPYARD-CATALOG-001: one canonical read snapshot per catalog payload."""
    own = conn is None
    if own:
        conn = db()
    try:
        from .models import get_planet_buildings, get_research_levels
        from .shipyard_queue import get_shipyard_queue_limit, queue_count, shipyard_queue_table_ready
        from .technical_data import resolve_unit_effect_context

        buildings = get_planet_buildings(int(planet_id), conn=conn)
        sy_level = max(
            0,
            int(buildings.get("orbital_shipyard") or 0),
            int(buildings.get("shipyard") or 0),
        )
        research = get_research_levels(user_id=int(player_id), conn=conn)
        resources = _resources_dict(int(planet_id), conn=conn)
        ships_inv = get_ship_inventory(int(player_id), int(planet_id), conn=conn)

        queue_full = False
        if shipyard_queue_table_ready(conn):
            queue_full = queue_count(planet_id, conn=conn) >= get_shipyard_queue_limit(
                conn=conn, planet_id=planet_id
            )

        try:
            from .planet_evolution.repository import get_context_planet

            planet_row = get_context_planet(int(player_id), conn=conn)
        except Exception:
            planet_row = None
        effect_ctx = resolve_unit_effect_context(
            buildings=buildings,
            research_levels=research,
            player_id=int(player_id),
            conn=conn,
            planet=planet_row,
        )
        forge_rank = forge_rank_for_planet(int(planet_id), conn=conn)
        build_time_speed = _shipyard_speed_multiplier(conn=conn) * _directive_time_speed(
            int(planet_id),
            "shipyard_time_speed",
            conn=conn,
            player_id=int(player_id),
        )

        buildable: List[Dict[str, Any]] = []
        locked: List[Dict[str, Any]] = []
        for key in sort_ship_keys_by_role(ACTIVE_SHIP_KEYS):
            unlocked = ship_unlocked(
                key,
                sy_level,
                player_id=player_id,
                planet_id=planet_id,
                conn=conn,
                buildings=buildings,
                research=research,
            )
            unit_cost = _unit_build_cost(key, planet_id=planet_id, conn=conn)
            entry = _ship_catalog_entry(
                key,
                sy_level,
                player_id=player_id,
                planet_id=planet_id,
                conn=conn,
                buildings=buildings,
                research=research,
                unlocked=unlocked,
                forge_rank=forge_rank,
                build_time_speed=build_time_speed,
                unit_cost=unit_cost,
            )
            from .technical_data import apply_combat_stats_to_catalog_entry

            apply_combat_stats_to_catalog_entry(entry, effect_ctx=effect_ctx)
            entry["owned_count"] = int(ships_inv.get(key, 0) or 0)
            if not unlocked:
                locked.append(entry)
                continue

            entry["max_build"] = max_build_amount_for_planet(
                resources["metal"],
                resources["crystal"],
                resources["fuel_cells"],
                key,
                sy_level,
                player_id=player_id,
                planet_id=planet_id,
                conn=conn,
                buildings=buildings,
                research=research,
                unlocked=True,
                unit_cost=unit_cost,
            )
            if queue_full:
                entry["block_reason"] = "queue_full"
                entry["can_build"] = False
            elif entry["max_build"] <= 0:
                entry["block_reason"] = "not_enough_resources"
                entry["can_build"] = False
            else:
                entry["block_reason"] = ""
                entry["can_build"] = True
            buildable.append(entry)

        return {
            "shipyard_level": sy_level,
            "resources": resources,
            "current_ships": ships_inv,
            "forge_rank": forge_rank,
            "build_time_speed": build_time_speed,
            "buildable_ships": buildable,
            "locked_ships": locked,
        }
    finally:
        if own and conn is not None:
            conn.close()


def list_buildable_ships(player_id: int, planet_id: int, *, conn=None) -> List[Dict[str, Any]]:
    return list(
        _build_shipyard_catalogs_shared(player_id, planet_id, conn=conn).get(
            "buildable_ships"
        )
        or []
    )''',
        "ship catalog + buildable",
    )

    src = replace_block(
        src,
        "def list_locked_ships(\n",
        "def max_build_amount_for_planet(\n",
        '''def list_locked_ships(player_id: int, planet_id: int, *, conn=None) -> List[Dict[str, Any]]:
    return list(
        _build_shipyard_catalogs_shared(player_id, planet_id, conn=conn).get(
            "locked_ships"
        )
        or []
    )''',
        "locked ships",
    )

    src = replace_block(
        src,
        "def max_build_amount_for_planet(\n",
        "def can_build_ship(\n",
        '''def max_build_amount_for_planet(
    metal_have: float,
    crystal_have: float,
    fuel_have: float,
    ship_key: str,
    shipyard_level: int,
    *,
    player_id: int | None = None,
    planet_id: int | None = None,
    conn=None,
    buildings: Mapping[str, Any] | None = None,
    research: Mapping[str, Any] | None = None,
    unlocked: bool | None = None,
    unit_cost: Mapping[str, Any] | None = None,
) -> int:
    sk = canonical_ship_key(ship_key)
    is_unlocked = (
        bool(unlocked)
        if unlocked is not None
        else ship_unlocked(
            sk,
            shipyard_level,
            player_id=player_id,
            planet_id=planet_id,
            conn=conn,
            buildings=buildings,
            research=research,
        )
    )
    if not is_unlocked:
        return 0
    cost = dict(unit_cost) if unit_cost is not None else _unit_build_cost(
        sk, planet_id=planet_id, conn=conn
    )
    if cost["metal"] <= 0 and cost["crystal"] <= 0 and cost["fuel_cells"] <= 0:
        return 0
    limits: List[int] = []
    if cost["metal"] > 0:
        limits.append(int(metal_have) // int(cost["metal"]))
    if cost["crystal"] > 0:
        limits.append(int(crystal_have) // int(cost["crystal"]))
    if cost["fuel_cells"] > 0:
        limits.append(int(fuel_have) // int(cost["fuel_cells"]))
    if not limits:
        return 0
    return max(0, min(limits))''',
        "max build",
    )

    src = replace_block(
        src,
        "def build_shipyard_api_payload(\n",
        "def build_shipyard_page_context(\n",
        '''def build_shipyard_api_payload(player_id: int, planet_id: int, *, conn=None) -> Dict[str, Any]:
    own = conn is None
    if own:
        conn = db()
    try:
        # GC-PERF-SHIPYARD-CATALOG-001: Buildable + Locked are two views of
        # one catalog snapshot, not two independent Buildings/Research/Effects scans.
        catalog = _build_shipyard_catalogs_shared(
            int(player_id), int(planet_id), conn=conn
        )
        sy_level = int(catalog.get("shipyard_level") or 0)
        resources = dict(catalog.get("resources") or {})
        buildable = list(catalog.get("buildable_ships") or [])
        locked = list(catalog.get("locked_ships") or [])
        ships = dict(catalog.get("current_ships") or {})
        forge_rank = int(catalog.get("forge_rank") or 0)

        from .shipyard_queue import shipyard_queue_for_client

        meta = _planet_meta(planet_id, conn=conn)
        queue = shipyard_queue_for_client(
            player_id, planet_id, sy_level, conn=conn
        )
        from .queue_card import (
            enrich_mini_queue_jobs_batch_size,
            group_card_jobs_by_owner_key,
            map_card_jobs_to_mini_queue_jobs,
            map_shipyard_queue_to_card_jobs,
        )

        card_jobs = map_shipyard_queue_to_card_jobs(queue)
        by_owner = group_card_jobs_by_owner_key(card_jobs)
        queue_payload = dict(queue)
        queue_payload["card_jobs_by_owner"] = by_owner
        queue_payload["mini_queue_jobs"] = enrich_mini_queue_jobs_batch_size(
            map_card_jobs_to_mini_queue_jobs(card_jobs, domain="shipyard"),
            domain="shipyard",
            shipyard_level=sy_level,
        )

        return {
            "orbital_shipyard_level": sy_level,
            "production_batch_capacity": orbital_production_batch_capacity(sy_level, forge_rank),
            "buildable_ships": buildable,
            "locked_ships": locked,
            "current_ships": ships,
            "resources": resources,
            "fuel_cells": resources.get("fuel_cells", 0),
            "shipyard_queue": queue_payload,
            **meta,
        }
    finally:
        if own and conn is not None:
            conn.close()''',
        "api payload",
    )

    TARGET.write_text(src, encoding="utf-8")
    print("applied GC-PERF-SHIPYARD-CATALOG-001")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
