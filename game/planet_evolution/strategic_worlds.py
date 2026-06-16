"""Strategic world metadata for free map fields (GC-581). Presentation only — no gameplay."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

STRATEGIC_WORLD_TYPES: Tuple[str, ...] = (
    "mining_world",
    "research_world",
    "industrial_world",
    "fortress_world",
    "expedition_zone",
    "ruins_world",
    "anomaly_zone",
    "wreckage_field",
)

STRATEGIC_WORLD_NAME_KEYS: Tuple[str, ...] = (
    "strategic_world_name_helios_prime",
    "strategic_world_name_titan_forge",
    "strategic_world_name_omega_rift",
    "strategic_world_name_nova_reach",
    "strategic_world_name_vega_haven",
    "strategic_world_name_crimson_drift",
    "strategic_world_name_azure_gate",
    "strategic_world_name_obsidian_crown",
    "strategic_world_name_solaris_belt",
    "strategic_world_name_meridian_deep",
    "strategic_world_name_aurora_span",
    "strategic_world_name_cobalt_nexus",
    "strategic_world_name_ember_void",
    "strategic_world_name_stellar_hollow",
    "strategic_world_name_quantum_shoal",
    "strategic_world_name_granite_outpost",
    "strategic_world_name_polaris_wake",
    "strategic_world_name_eclipse_harbor",
    "strategic_world_name_ion_citadel",
    "strategic_world_name_nebula_crown",
    "strategic_world_name_argent_field",
    "strategic_world_name_cinder_reach",
    "strategic_world_name_lumen_spire",
    "strategic_world_name_dusk_frontier",
)

STRATEGIC_WORLD_TYPE_DEFS: Dict[str, Dict[str, str]] = {
    "mining_world": {
        "type_key": "strategic_world_type_mining_world",
        "role_icon": "☀",
        "risk_level": "moderate",
        "risk_key": "strategic_world_risk_pirate_activity",
        "promise_key": "strategic_world_promise_mining_world",
        "reward_hint_key": "strategic_world_reward_mining_world",
        "future_action_key": "strategic_world_future_mining_world",
    },
    "research_world": {
        "type_key": "strategic_world_type_research_world",
        "role_icon": "🔬",
        "risk_level": "low",
        "risk_key": "strategic_world_risk_scan_interference",
        "promise_key": "strategic_world_promise_research_world",
        "reward_hint_key": "strategic_world_reward_research_world",
        "future_action_key": "strategic_world_future_research_world",
    },
    "industrial_world": {
        "type_key": "strategic_world_type_industrial_world",
        "role_icon": "🏭",
        "risk_level": "moderate",
        "risk_key": "strategic_world_risk_supply_raids",
        "promise_key": "strategic_world_promise_industrial_world",
        "reward_hint_key": "strategic_world_reward_industrial_world",
        "future_action_key": "strategic_world_future_industrial_world",
    },
    "fortress_world": {
        "type_key": "strategic_world_type_fortress_world",
        "role_icon": "🛡",
        "risk_level": "high",
        "risk_key": "strategic_world_risk_border_clashes",
        "promise_key": "strategic_world_promise_fortress_world",
        "reward_hint_key": "strategic_world_reward_fortress_world",
        "future_action_key": "strategic_world_future_fortress_world",
    },
    "trade_world": {
        "type_key": "strategic_world_type_trade_world",
        "role_icon": "⚖",
        "risk_level": "moderate",
        "risk_key": "strategic_world_risk_supply_raids",
        "promise_key": "strategic_world_promise_trade_world",
        "reward_hint_key": "strategic_world_reward_trade_world",
        "future_action_key": "strategic_world_future_trade_world",
    },
    "expedition_zone": {
        "type_key": "strategic_world_type_expedition_zone",
        "role_icon": "🌀",
        "risk_level": "high",
        "risk_key": "strategic_world_risk_unknown_signals",
        "promise_key": "strategic_world_promise_expedition_zone",
        "reward_hint_key": "strategic_world_reward_expedition_zone",
        "future_action_key": "strategic_world_future_expedition_zone",
    },
    "ruins_world": {
        "type_key": "strategic_world_type_ruins_world",
        "role_icon": "🏺",
        "risk_level": "moderate",
        "risk_key": "strategic_world_risk_ancient_traps",
        "promise_key": "strategic_world_promise_ruins_world",
        "reward_hint_key": "strategic_world_reward_ruins_world",
        "future_action_key": "strategic_world_future_ruins_world",
    },
    "anomaly_zone": {
        "type_key": "strategic_world_type_anomaly_zone",
        "role_icon": "⚫",
        "risk_level": "extreme",
        "risk_key": "strategic_world_risk_reality_tears",
        "promise_key": "strategic_world_promise_anomaly_zone",
        "reward_hint_key": "strategic_world_reward_anomaly_zone",
        "future_action_key": "strategic_world_future_anomaly_zone",
    },
    "wreckage_field": {
        "type_key": "strategic_world_type_wreckage_field",
        "role_icon": "🛰",
        "risk_level": "moderate",
        "risk_key": "strategic_world_risk_salvage_hazards",
        "promise_key": "strategic_world_promise_wreckage_field",
        "reward_hint_key": "strategic_world_reward_wreckage_field",
        "future_action_key": "strategic_world_future_wreckage_field",
    },
}


PLANET_ROLE_TO_EMPIRE_ROLE: Dict[str, str] = {
    "mining_world": "mining",
    "industrial_world": "shipyard",
    "research_world": "research",
    "fortress_world": "fortress",
    "trade_world": "trade",
    "ruins_world": "frontier",
}


def empire_role_key_for_planet_role(planet_role: str) -> str:
    """Map strategic `planet_role` to empire identity role key (GC-582D)."""
    return PLANET_ROLE_TO_EMPIRE_ROLE.get(str(planet_role or "").strip(), "general")


def _stable_mix(*parts: int) -> int:
    h = 2166136261
    for part in parts:
        h ^= int(part) & 0xFFFFFFFF
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def strategic_world_type_for_coords(world_x: float, world_y: float) -> str:
    h = _stable_mix(int(world_x), int(world_y), 581)
    return STRATEGIC_WORLD_TYPES[h % len(STRATEGIC_WORLD_TYPES)]


def strategic_world_name_key(world_x: float, world_y: float) -> str:
    h = _stable_mix(int(world_x), int(world_y), 581, 17)
    return STRATEGIC_WORLD_NAME_KEYS[h % len(STRATEGIC_WORLD_NAME_KEYS)]


def build_strategic_world_presentation_from_key(world_key: str) -> Dict[str, Any]:
    """Resolve presentation keys from a canonical world_key (GC-583B reports)."""
    from .world_colonization import WorldKeyError, parse_world_key

    parsed = parse_world_key(world_key)
    return build_strategic_world_presentation(
        parsed["world_x"],
        parsed["world_y"],
        world_type=parsed["world_type"],
    )


def build_strategic_world_presentation(
    world_x: float,
    world_y: float,
    *,
    world_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Localized presentation keys for inspector and fleet world-target UI (GC-582C)."""
    from .world_colonization import build_world_key, is_colonizable_world_type

    wx = float(world_x)
    wy = float(world_y)
    wt = str(world_type or strategic_world_type_for_coords(wx, wy))
    meta = STRATEGIC_WORLD_TYPE_DEFS.get(wt, STRATEGIC_WORLD_TYPE_DEFS["mining_world"])
    return {
        "world_key": build_world_key(wx, wy, world_type=wt),
        "world_type": wt,
        "name_key": strategic_world_name_key(wx, wy),
        "type_key": meta["type_key"],
        "role_icon": meta["role_icon"],
        "risk_level": meta["risk_level"],
        "risk_key": meta["risk_key"],
        "promise_key": meta["promise_key"],
        "reward_hint_key": meta["reward_hint_key"],
        "future_action_key": meta["future_action_key"],
        "is_colonizable": is_colonizable_world_type(wt),
    }


def build_strategic_world_field(world_x: float, world_y: float) -> Dict[str, Any]:
    """Build presentation payload for one neutral strategic world field."""
    from .world_colonization import (
        build_world_key,
        is_colonizable_world_type,
        is_expedition_world_type,
        is_prepared_expedition_world_type,
        is_salvage_world_type,
    )

    wx = float(world_x)
    wy = float(world_y)
    world_type = strategic_world_type_for_coords(wx, wy)
    meta = STRATEGIC_WORLD_TYPE_DEFS.get(world_type, STRATEGIC_WORLD_TYPE_DEFS["mining_world"])
    name_key = strategic_world_name_key(wx, wy)
    field_key = f"{world_type}:{int(wx)}:{int(wy)}"
    world_key = build_world_key(wx, wy, world_type=world_type)

    return {
        "node_kind": "world_field",
        "node_key": f"field:{field_key}",
        "field_key": field_key,
        "world_key": world_key,
        "world_type": world_type,
        "is_colonizable": is_colonizable_world_type(world_type),
        "is_expedition": is_expedition_world_type(world_type),
        "is_expedition_prepared": is_prepared_expedition_world_type(world_type),
        "is_salvage": is_salvage_world_type(world_type),
        "is_claimed": False,
        "name_key": name_key,
        "type_key": meta["type_key"],
        "role_icon": meta["role_icon"],
        "risk_level": meta["risk_level"],
        "risk_key": meta["risk_key"],
        "promise_key": meta["promise_key"],
        "reward_hint_key": meta["reward_hint_key"],
        "future_action_key": meta["future_action_key"],
        "owner_key": "strategic_world_owner_unclaimed",
        "is_own": False,
        "cluster_kind": "neutral",
        "_world_x": wx,
        "_world_y": wy,
    }


def list_strategic_world_type_defs() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for world_type in STRATEGIC_WORLD_TYPES:
        row = dict(STRATEGIC_WORLD_TYPE_DEFS[world_type])
        row["world_type"] = world_type
        rows.append(row)
    return rows
