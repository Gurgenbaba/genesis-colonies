"""Espionage intel — probe tiers, accuracy, and structured spy reports."""

from __future__ import annotations

import random
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .fleet_defs import get_ship
from .galaxy import format_coordinates

SPY_INTEL_TIER_TARGET = 1
SPY_INTEL_TIER_RESOURCES = 2
SPY_INTEL_TIER_FUEL = 3
SPY_INTEL_TIER_FLEET = 4
SPY_INTEL_TIER_DEFENSE = 5
SPY_INTEL_TIER_BUILDINGS = 5
SPY_INTEL_TIER_ACTIVITY = 6
SPY_REPORT_VERSION = 2

SPY_RESEARCH_KEY = "espionage_tech"
SPY_ACCURACY_BASE = 0.50
SPY_ACCURACY_PER_LEVEL = 0.10


def probe_count(ships: Mapping[str, int]) -> int:
    total = 0
    for key, amount in ships.items():
        spec = get_ship(str(key))
        if spec and str(spec.get("role") or "") == "spy":
            total += int(amount or 0)
    return max(0, total)


def spy_research_level(player_id: int, *, conn) -> int:
    from .models import get_research_levels
    from .research import RESEARCH_TECHS

    if SPY_RESEARCH_KEY not in RESEARCH_TECHS:
        return 0
    levels = get_research_levels(int(player_id), conn=conn)
    return max(0, int(levels.get(SPY_RESEARCH_KEY, 0) or 0))


def spy_accuracy(player_id: int, *, snapshot: Mapping[str, Any], conn) -> float:
    """1.0 = exact intel. Own colonies are always fully accurate."""
    owner_id = int(snapshot.get("owner_id") or 0)
    if owner_id and int(player_id) == owner_id:
        return 1.0
    level = spy_research_level(int(player_id), conn=conn)
    return min(1.0, SPY_ACCURACY_BASE + SPY_ACCURACY_PER_LEVEL * level)


def _apply_spy_accuracy(value: int, accuracy: float, *, seed: int) -> int:
    exact = max(0, int(value))
    if accuracy >= 1.0 or exact <= 0:
        return exact
    rng = random.Random(int(seed))
    spread = max(1, int(round(exact * (1.0 - accuracy))))
    low = max(0, exact - spread)
    high = exact + spread
    return max(0, int(rng.randint(low, high)))


def _ship_priority(ship_key: str, qty: int) -> int:
    spec = get_ship(str(ship_key)) or {}
    power = int(spec.get("attack") or 0) + int(spec.get("hull") or 0) + int(spec.get("cargo") or 0)
    return int(qty) * max(1, power)


def _defense_priority(defense_key: str, qty: int) -> int:
    from .defense import defense_combat_priority

    return int(qty) * max(1, defense_combat_priority(str(defense_key)))


def _select_partial_items(
    items: Mapping[str, int],
    *,
    max_items: int,
    seed: int,
    priority_fn,
) -> Dict[str, int]:
    if max_items <= 0 or not items:
        return {}
    ranked = sorted(
        ((str(key), int(val or 0)) for key, val in items.items() if int(val or 0) > 0),
        key=lambda pair: (-priority_fn(pair[0], pair[1]), pair[0]),
    )
    if len(ranked) <= max_items:
        return {key: qty for key, qty in ranked}
    rng = random.Random(int(seed))
    pool = list(ranked)
    rng.shuffle(pool)
    pool.sort(key=lambda pair: (-priority_fn(pair[0], pair[1]), pair[0]))
    selected = pool[:max_items]
    return {key: qty for key, qty in selected}


def target_planet_snapshot(planet_id: int, *, conn) -> Dict[str, Any]:
    from .db import table_exists
    from .defense import get_planet_defense_intel

    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.id, p.name, p.player_id, p.metal, p.crystal, p.fuel_cells,
               p.energy_total, p.energy_used,
               p.galaxy, p.system, p.position, pl.name AS owner_name
        FROM planets p
        INNER JOIN players pl ON pl.id = p.player_id
        WHERE p.id = ?
        LIMIT 1;
        """,
        (int(planet_id),),
    )
    row = cur.fetchone()
    if not row:
        return {}
    data = dict(row)
    coords = format_coordinates(int(data["galaxy"]), int(data["system"]), int(data["position"]))
    buildings: Dict[str, int] = {}
    cur.execute("SELECT * FROM planet_buildings WHERE planet_id = ? LIMIT 1;", (int(planet_id),))
    brow = cur.fetchone()
    if brow:
        for key in brow.keys():
            if key in ("id", "planet_id", "player_id"):
                continue
            try:
                lvl = int(brow[key] or 0)
            except (TypeError, ValueError):
                continue
            if lvl > 0:
                buildings[str(key)] = lvl
    from .fleet import get_planet_ships

    ships = get_planet_ships(int(planet_id), conn=conn)
    energy_total = int(data.get("energy_total") or 0)
    energy_used = int(data.get("energy_used") or 0)
    defense = get_planet_defense_intel(int(planet_id), conn=conn)
    return {
        "planet_id": int(planet_id),
        "planet_name": str(data.get("name") or ""),
        "owner_id": int(data["player_id"]),
        "owner_name": str(data.get("owner_name") or ""),
        "coords": coords,
        "resources": {
            "metal": int(float(data.get("metal") or 0)),
            "crystal": int(float(data.get("crystal") or 0)),
            "fuel_cells": int(float(data.get("fuel_cells") or 0)),
        },
        "energy": {
            "total": energy_total,
            "used": energy_used,
            "balance": energy_total - energy_used,
        },
        "buildings": buildings,
        "ships": ships,
        "defense": defense,
        "activity": _target_fleet_activity(int(planet_id), conn=conn),
    }


def _target_fleet_activity(planet_id: int, *, conn) -> List[Dict[str, Any]]:
    from .db import table_exists

    if not table_exists(conn, "fleet_movements"):
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT mission_type, status, target_galaxy, target_system, target_position
        FROM fleet_movements
        WHERE origin_planet_id = ?
          AND status IN ('outbound', 'holding', 'returning')
        ORDER BY departure_at DESC
        LIMIT 8;
        """,
        (int(planet_id),),
    )
    rows: List[Dict[str, Any]] = []
    for row in cur.fetchall():
        data = dict(row)
        rows.append(
            {
                "mission": str(data.get("mission_type") or ""),
                "status": str(data.get("status") or ""),
                "coords": format_coordinates(
                    int(data["target_galaxy"]),
                    int(data["target_system"]),
                    int(data["target_position"]),
                ),
            }
        )
    return rows


def resolve_spy_intel(
    snapshot: Mapping[str, Any],
    probe_count: int,
    *,
    viewer_id: int,
    conn,
) -> Dict[str, Any]:
    probes = max(0, int(probe_count))
    planet_id = int(snapshot.get("planet_id") or 0)
    resources = snapshot.get("resources") or {}
    ships = snapshot.get("ships") or {}
    buildings = snapshot.get("buildings") or {}
    energy = snapshot.get("energy") or {}
    activity = snapshot.get("activity") or []
    defense_raw = snapshot.get("defense") or {}

    accuracy = spy_accuracy(int(viewer_id), snapshot=snapshot, conn=conn)
    own_colony = int(viewer_id) == int(snapshot.get("owner_id") or 0)

    tiers = {
        "target": probes >= SPY_INTEL_TIER_TARGET,
        "resources": probes >= SPY_INTEL_TIER_RESOURCES,
        "fuel": probes >= SPY_INTEL_TIER_FUEL,
        "fleet": probes >= SPY_INTEL_TIER_FLEET,
        "defense": probes >= SPY_INTEL_TIER_DEFENSE,
        "buildings": probes >= SPY_INTEL_TIER_BUILDINGS,
        "activity": probes >= SPY_INTEL_TIER_ACTIVITY,
    }

    visible_resources: Dict[str, int] = {}
    if tiers["resources"]:
        visible_resources["metal"] = int(resources.get("metal") or 0)
        visible_resources["crystal"] = int(resources.get("crystal") or 0)
    if tiers["fuel"]:
        visible_resources["fuel_cells"] = int(resources.get("fuel_cells") or 0)

    visible_ships: Dict[str, int] = {}
    if tiers["fleet"] and ships:
        max_types = max(1, probes - SPY_INTEL_TIER_FLEET + 1)
        visible_ships = _select_partial_items(
            ships,
            max_items=max_types,
            seed=planet_id * 9973 + probes,
            priority_fn=_ship_priority,
        )

    stock = dict(defense_raw.get("stock") or {})
    visible_defense: Dict[str, Any] = {}
    if tiers["defense"]:
        visible_units: Dict[str, int] = {}
        if own_colony:
            visible_units = {k: int(v) for k, v in stock.items() if int(v or 0) > 0}
        elif stock:
            max_types = max(1, probes - SPY_INTEL_TIER_DEFENSE + 1)
            visible_units = _select_partial_items(
                stock,
                max_items=max_types,
                seed=planet_id * 8831 + probes,
                priority_fn=_defense_priority,
            )
        seed_base = planet_id * 6151 + int(viewer_id)
        total_units = sum(int(v or 0) for v in visible_units.values())
        from .defense import summarize_defense_stock

        exact = summarize_defense_stock(visible_units if visible_units else stock)
        visible_defense = {
            "units": {
                k: _apply_spy_accuracy(
                    int(v),
                    accuracy,
                    seed=seed_base + sum(ord(c) for c in str(k)),
                )
                for k, v in sorted(visible_units.items())
            },
            "total_units": _apply_spy_accuracy(int(exact["total_units"]), accuracy, seed=seed_base + 1),
            "defense_power": _apply_spy_accuracy(int(exact["defense_power"]), accuracy, seed=seed_base + 2),
            "shield_power": _apply_spy_accuracy(int(exact["shield_power"]), accuracy, seed=seed_base + 3),
            "accuracy_pct": int(round(accuracy * 100)),
            "exact": own_colony,
        }
        if total_units <= 0 and not own_colony:
            visible_defense["total_units"] = 0
            visible_defense["defense_power"] = 0
            visible_defense["shield_power"] = 0

    visible_buildings: Dict[str, int] = {}
    if tiers["buildings"] and buildings:
        max_types = max(1, probes - SPY_INTEL_TIER_BUILDINGS + 1)
        visible_buildings = _select_partial_items(
            buildings,
            max_items=max_types,
            seed=planet_id * 7919 + probes,
            priority_fn=lambda key, lvl: int(lvl),
        )

    visible_energy = None
    if tiers["buildings"]:
        visible_energy = {
            "total": int(energy.get("total") or 0),
            "used": int(energy.get("used") or 0),
            "balance": int(energy.get("balance") or 0),
        }

    visible_activity: List[Dict[str, Any]] = []
    if tiers["activity"] and activity:
        max_rows = max(1, probes - SPY_INTEL_TIER_ACTIVITY + 1)
        visible_activity = list(activity[:max_rows])

    return {
        "intel_tiers": tiers,
        "spy_accuracy": accuracy,
        "resources": visible_resources,
        "ships": visible_ships,
        "defense": visible_defense,
        "buildings": visible_buildings,
        "energy": visible_energy,
        "activity": visible_activity,
    }


def _format_kv_section(title: str, lines: Sequence[str]) -> str:
    if not lines:
        return ""
    return f"{title}\n" + "\n".join(f"  {line}" for line in lines)


def build_spy_report_body(
    snapshot: Mapping[str, Any],
    probe_count: int,
    *,
    viewer_id: int = 0,
    conn=None,
    locale: str | None = None,
) -> Tuple[str, Dict[str, Any]]:
    from .db import db as db_conn
    from .i18n import fmt_int, tr
    from .messages import append_spy_defense_report_lines

    own_conn = conn is None
    if own_conn:
        conn = db_conn()
    try:
        return _build_spy_report_body_impl(
            snapshot,
            probe_count,
            viewer_id=int(viewer_id),
            conn=conn,
            locale=locale,
            tr_fn=tr,
            fmt_int=fmt_int,
            append_defense=append_spy_defense_report_lines,
        )
    finally:
        if own_conn and conn is not None:
            conn.close()


def _build_spy_report_body_impl(
    snapshot: Mapping[str, Any],
    probe_count: int,
    *,
    viewer_id: int,
    conn,
    locale: str | None,
    tr_fn,
    fmt_int,
    append_defense,
) -> Tuple[str, Dict[str, Any]]:
    loc = locale

    def _t(key, default=None, **kw):
        return tr_fn(key, default, locale=loc, **kw)

    coords = str(snapshot.get("coords") or "")
    owner = str(snapshot.get("owner_name") or "")
    planet_name = str(snapshot.get("planet_name") or "")
    intel = resolve_spy_intel(snapshot, probe_count, viewer_id=int(viewer_id), conn=conn)
    tiers = intel["intel_tiers"]

    body_lines: List[str] = []
    if tiers["target"]:
        body_lines.append(
            _t(
                "fleet_spy_report_target",
                "Target: %(coords)s — %(owner)s (%(planet)s)",
                coords=coords,
                owner=owner,
                planet=planet_name or _t("fleet_spy_report_unknown_planet", "Unknown colony"),
            )
        )
        body_lines.append(
            _t(
                "fleet_spy_report_probes",
                "Probes deployed: %(count)s",
                count=fmt_int(probe_count),
            )
        )

    resource_lines: List[str] = []
    visible_resources = intel["resources"] or {}
    if tiers["resources"]:
        resource_lines.append(
            f"{_t('resource_metal', 'Ferronit')}: {fmt_int(visible_resources.get('metal', 0))}"
        )
        resource_lines.append(
            f"{_t('resource_crystal', 'Crytite')}: {fmt_int(visible_resources.get('crystal', 0))}"
        )
    if tiers["fuel"]:
        resource_lines.append(
            f"{_t('resource_fuel_cells', 'Fuel Cells')}: {fmt_int(visible_resources.get('fuel_cells', 0))}"
        )
    if resource_lines:
        body_lines.append(_format_kv_section(_t("fleet_spy_report_section_resources", "Resources"), resource_lines))
    elif probe_count >= SPY_INTEL_TIER_TARGET:
        body_lines.append(_t("fleet_spy_report_resources_locked", "Resources: insufficient probe data"))

    ship_lines: List[str] = []
    visible_ships = intel["ships"] or {}
    if tiers["fleet"]:
        if visible_ships:
            for key, qty in sorted(visible_ships.items()):
                from .fleet_defs import ship_display_name

                label = ship_display_name(str(key))
                ship_lines.append(f"{label} ×{fmt_int(qty)}")
        else:
            ship_lines.append(_t("fleet_spy_report_fleet_empty", "No ships detected in orbit"))
        body_lines.append(_format_kv_section(_t("fleet_spy_report_section_fleet", "Orbital fleet"), ship_lines))
    elif probe_count >= SPY_INTEL_TIER_RESOURCES:
        body_lines.append(_t("fleet_spy_report_fleet_locked", "Orbital fleet: insufficient probe data"))

    append_defense(
        body_lines,
        intel.get("defense") or {},
        tiers=tiers,
        probe_count=int(probe_count),
        tr=_t,
        fmt_int=fmt_int,
    )

    building_lines: List[str] = []
    visible_buildings = intel["buildings"] or {}
    visible_energy = intel["energy"]
    if tiers["buildings"]:
        if visible_buildings:
            for key, lvl in sorted(visible_buildings.items()):
                label = _t(f"building_{key}", str(key))
                building_lines.append(f"{label} L{fmt_int(lvl)}")
        else:
            building_lines.append(_t("fleet_spy_report_buildings_empty", "No surface installations detected"))
        if visible_energy:
            building_lines.append(
                _t(
                    "fleet_spy_report_energy",
                    "Energy balance: %(balance)s (generated %(total)s / used %(used)s)",
                    balance=fmt_int(visible_energy.get("balance", 0)),
                    total=fmt_int(visible_energy.get("total", 0)),
                    used=fmt_int(visible_energy.get("used", 0)),
                )
            )
        body_lines.append(
            _format_kv_section(_t("fleet_spy_report_section_buildings", "Surface installations"), building_lines)
        )
    elif probe_count >= SPY_INTEL_TIER_FLEET:
        body_lines.append(_t("fleet_spy_report_buildings_locked", "Surface installations: insufficient probe data"))

    activity_lines: List[str] = []
    visible_activity = intel["activity"] or []
    if tiers["activity"]:
        if visible_activity:
            for row in visible_activity:
                mission_key = f"fleet_mission_{row.get('mission', '')}"
                mission_label = _t(mission_key, str(row.get("mission") or ""))
                activity_lines.append(
                    _t(
                        "fleet_spy_report_activity_row",
                        "%(mission)s → %(coords)s (%(status)s)",
                        mission=mission_label,
                        coords=str(row.get("coords") or ""),
                        status=str(row.get("status") or ""),
                    )
                )
        else:
            activity_lines.append(_t("fleet_spy_report_activity_empty", "No outbound fleet activity detected"))
        body_lines.append(
            _format_kv_section(_t("fleet_spy_report_section_activity", "Fleet activity"), activity_lines)
        )
    elif probe_count >= SPY_INTEL_TIER_BUILDINGS:
        body_lines.append(_t("fleet_spy_report_activity_locked", "Fleet activity: insufficient probe data"))

    metadata: Dict[str, Any] = {
        "report_version": SPY_REPORT_VERSION,
        "target_coords": coords,
        "target_owner": owner,
        "target_planet": planet_name,
        "target_planet_id": int(snapshot.get("planet_id") or 0),
        "probe_count": int(probe_count),
        "intel_tiers": tiers,
        "spy_accuracy_pct": int(round(float(intel.get("spy_accuracy") or 0) * 100)),
        "resources": intel["resources"],
        "ships": intel["ships"],
        "defense": intel["defense"],
        "buildings": intel["buildings"],
        "energy": intel["energy"],
        "activity": intel["activity"],
    }
    return "\n\n".join(line for line in body_lines if line), metadata
