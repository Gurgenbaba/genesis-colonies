"""Galactic directive mechanics merge — primary/secondary bundle (GC-720D).

Conflict rules:
- Numeric floats: combine (additive keys sum; multiplicative keys add delta from 1.0).
- Integer counts, bool, str, list: not scaled; on merge primary wins.
- Keys only in secondary are retained when absent from primary.
"""

from __future__ import annotations

import copy
import sqlite3
from typing import Any, Dict, List, Optional

from .state import get_active_directives_for_galaxy

SECONDARY_SCALE = 0.4

# GC-720E/E2 — keys consumed by EffectResolver.
GD_EFFECT_RESOLVER_ACTIVE_KEYS = frozenset({
    "metal_prod_factor",
    "crystal_prod_factor",
    "fuel_prod_factor",
    "mine_energy_factor",
    "solar_output_factor",
    "build_time_speed",
    "research_time_speed",
    "storage_factor",
    "weapon_bonus",
    "armor_bonus",
    "shield_bonus",
    "fleet_speed_multiplier",
    "cargo_multiplier",
    "fuel_efficiency_factor",
    "shipyard_time_speed",
    "defense_time_speed",
})

GD_EFFECT_RESOLVER_ADDITIVE_KEYS = frozenset({
    "weapon_bonus",
    "armor_bonus",
    "shield_bonus",
})

_ADDITIVE_KEYS = frozenset({
    "weapon_bonus",
    "armor_bonus",
    "shield_bonus",
})

_MULTIPLICATIVE_KEYS = frozenset({
    "colonize_cost_mult",
    "planet_xp_mult",
    "fuel_efficiency_factor",
})


def _is_multiplicative_key(key: str, parent_key: str) -> bool:
    if key in _ADDITIVE_KEYS:
        return False
    if parent_key == "queue_limits":
        return False
    if key in _MULTIPLICATIVE_KEYS:
        return True
    if key.endswith(("_factor", "_mult", "_speed")):
        return True
    if parent_key == "flags" and "mult" in key:
        return True
    if parent_key == "effect_resolver":
        return True
    return False


def _scale_leaf(key: str, value: Any, factor: float, parent_key: str) -> Any:
    if isinstance(value, (bool, str, list)):
        return copy.deepcopy(value)
    if isinstance(value, int):
        return value
    if not isinstance(value, (int, float)):
        return copy.deepcopy(value)
    if parent_key == "queue_limits" or key == "unlocks":
        return copy.deepcopy(value) if isinstance(value, list) else value
    fv = float(value)
    if _is_multiplicative_key(key, parent_key):
        return 1.0 + (fv - 1.0) * factor
    return fv * factor


def _scale_tree(node: Any, key: str, parent_key: str, factor: float) -> Any:
    if isinstance(node, dict):
        return {
            str(k): _scale_tree(v, str(k), key, factor)
            for k, v in node.items()
        }
    if isinstance(node, list):
        return copy.deepcopy(node)
    return _scale_leaf(key, node, factor, parent_key)


def scale_numeric_mechanics(
    mechanics: Optional[Dict[str, Any]],
    factor: float,
) -> Dict[str, Any]:
    """Return a copy with numeric float leaves scaled; ints/lists/strings/bools unchanged."""
    if not mechanics:
        return {}
    return {
        str(k): _scale_tree(v, str(k), "", factor)
        for k, v in mechanics.items()
    }


def _merge_numeric(key: str, primary: float, secondary: float, parent_key: str) -> float:
    if _is_multiplicative_key(key, parent_key):
        return float(primary) + (float(secondary) - 1.0)
    return float(primary) + float(secondary)


def _merge_nodes(primary: Any, secondary: Any, parent_key: str) -> Any:
    if isinstance(primary, dict) and isinstance(secondary, dict):
        merged = copy.deepcopy(primary)
        for key, sec_val in secondary.items():
            key_s = str(key)
            if key_s not in merged:
                merged[key_s] = copy.deepcopy(sec_val)
                continue
            merged[key_s] = _merge_nodes(merged[key_s], sec_val, key_s)
        return merged

    if isinstance(primary, bool) or isinstance(secondary, bool):
        return copy.deepcopy(primary) if primary is not None else copy.deepcopy(secondary)
    if isinstance(primary, int) or isinstance(secondary, int):
        return primary if primary is not None else secondary
    if isinstance(primary, float) and isinstance(secondary, float):
        return _merge_numeric(parent_key, primary, secondary, parent_key)

    if primary is not None:
        return copy.deepcopy(primary)
    return copy.deepcopy(secondary)


def merge_mechanics(
    primary: Optional[Dict[str, Any]],
    secondary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge primary (100%) with optional secondary contribution."""
    base = copy.deepcopy(primary or {})
    if not secondary:
        return base
    return _merge_nodes(base, secondary, "")


def _secondary_mechanics_for_definition(
    secondary_definition: Dict[str, Any],
) -> tuple[Dict[str, Any], str]:
    custom = secondary_definition.get("secondary_mechanics") or {}
    if custom:
        return copy.deepcopy(custom), "custom"
    base = secondary_definition.get("mechanics") or {}
    return scale_numeric_mechanics(base, SECONDARY_SCALE), "scaled"


def extract_active_effect_resolver_modifiers(
    mechanics: Optional[Dict[str, Any]],
) -> Dict[str, float]:
    """Return only EffectResolver-safe numeric modifiers from a merged mechanics bundle."""
    if not mechanics:
        return {}
    er = mechanics.get("effect_resolver") or {}
    if not isinstance(er, dict):
        return {}
    out: Dict[str, float] = {}
    for key, raw in er.items():
        key_s = str(key)
        if key_s not in GD_EFFECT_RESOLVER_ACTIVE_KEYS:
            continue
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        out[key_s] = float(raw)
    return out


def get_galaxy_directive_mechanics(
    galaxy: Any,
    conn: Optional[sqlite3.Connection] = None,
) -> Optional[Dict[str, Any]]:
    """Resolved mechanics bundle for a galaxy's active directives."""
    active = get_active_directives_for_galaxy(galaxy, conn=conn)
    if active is None:
        return None

    primary_def = active.get("primary_definition") or {}
    primary_mech = copy.deepcopy(primary_def.get("mechanics") or {})
    sources: List[str] = [f"primary:{active['primary']}"]

    secondary_key = active.get("secondary")
    secondary_def = active.get("secondary_definition")
    merged = primary_mech

    if secondary_key and secondary_def:
        secondary_mech, mode = _secondary_mechanics_for_definition(secondary_def)
        merged = merge_mechanics(primary_mech, secondary_mech)
        sources.append(f"secondary:{secondary_key}:{mode}")

    return {
        "galaxy": int(active["galaxy"]),
        "primary": active["primary"],
        "secondary": secondary_key,
        "mechanics": merged,
        "sources": sources,
    }


def get_directive_flags_for_galaxy(
    galaxy: Any,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, Any]:
    """Numeric/bool flags from merged directive mechanics (expedition, colonize, …)."""
    payload = get_galaxy_directive_mechanics(galaxy, conn=conn)
    if not payload:
        return {}
    mechanics = payload.get("mechanics") or {}
    flags = mechanics.get("flags") or {}
    if not isinstance(flags, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, raw in flags.items():
        if isinstance(raw, (int, float, bool)):
            out[str(key)] = raw
    return out


def get_planet_directive_er_modifiers(
    planet_id: Any,
    *,
    conn: Optional[sqlite3.Connection] = None,
) -> Dict[str, float]:
    """EffectResolver keys for the galaxy that owns ``planet_id``."""
    own_conn = conn is None
    if own_conn:
        from ..db import db

        conn = db()
    try:
        row = conn.execute(
            "SELECT galaxy FROM planets WHERE id = ? LIMIT 1;",
            (int(planet_id),),
        ).fetchone()
        if not row or row["galaxy"] is None:
            return {}
        payload = get_galaxy_directive_mechanics(int(row["galaxy"]), conn=conn)
        if not payload:
            return {}
        return extract_active_effect_resolver_modifiers(payload.get("mechanics"))
    finally:
        if own_conn:
            conn.close()
