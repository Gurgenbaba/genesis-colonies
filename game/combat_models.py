"""Canonical combat unit stats — data layer for ``game.combat.simulate_battle`` (GC-416+).

Registry lookups and stack builders only; battle logic lives in ``game/combat.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Mapping, Optional

COMBAT_UNIT_SHIP = "ship"
COMBAT_UNIT_DEFENSE = "defense"
COMBAT_UNIT_TYPES: FrozenSet[str] = frozenset({COMBAT_UNIT_SHIP, COMBAT_UNIT_DEFENSE})


@dataclass(frozen=True, slots=True)
class CombatUnitStats:
    """Normalized combat profile for one ship or defense unit type."""

    unit_key: str
    unit_type: str
    attack: int
    shield: int
    hull: int
    score_value: int
    rapid_fire_targets: Dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CombatStack:
    """Amount × stats — input stack for ``simulate_battle``."""

    unit_key: str
    unit_type: str
    amount: int
    stats: CombatUnitStats


@dataclass(frozen=True, slots=True)
class CombatSide:
    """One battle participant — attacker or defender stack list."""

    role: str
    stacks: tuple[CombatStack, ...]


@dataclass(frozen=True, slots=True)
class CombatRound:
    """Per-round loss snapshot (cumulative totals are on ``CombatResult``)."""

    number: int
    attacker_losses: Dict[str, int]
    defender_losses: Dict[str, int]


@dataclass(frozen=True, slots=True)
class CombatResult:
    """Outcome of ``simulate_battle`` — pure data, no persistence."""

    winner: str
    rounds: tuple[CombatRound, ...]
    attacker_losses: Dict[str, int]
    defender_losses: Dict[str, int]


def make_combat_side(role: str, stacks: List[CombatStack] | tuple[CombatStack, ...]) -> CombatSide:
    """Build a side from resolver stacks (empty list allowed)."""
    return CombatSide(role=str(role or "").strip().lower(), stacks=tuple(stacks))


def _safe_int(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _score_from_build_cost(raw: Mapping[str, Any] | None) -> int:
    from .resource_score import score_from_cost_dict

    return score_from_cost_dict(raw)


def _normalize_rapid_fire(raw: Any, *, canonical_fn) -> Dict[str, int]:
    if not isinstance(raw, Mapping):
        return {}
    out: Dict[str, int] = {}
    for target_key, value in raw.items():
        key = canonical_fn(str(target_key or "").strip())
        if not key:
            continue
        rf = _safe_int(value, default=0)
        if rf >= 2:
            out[key] = rf
    return out


def _stats_from_spec(
    unit_key: str,
    unit_type: str,
    spec: Mapping[str, Any],
    *,
    canonical_target_fn,
) -> CombatUnitStats:
    score_value = _score_from_build_cost(spec.get("build_cost") or {})
    return CombatUnitStats(
        unit_key=str(unit_key),
        unit_type=str(unit_type),
        attack=_safe_int(spec.get("attack")),
        shield=_safe_int(spec.get("shield")),
        hull=_safe_int(spec.get("hull")),
        score_value=score_value,
        rapid_fire_targets=_normalize_rapid_fire(
            spec.get("rapid_fire_targets"),
            canonical_fn=canonical_target_fn,
        ),
    )


def combat_stats_for_ship(ship_key: str) -> Optional[CombatUnitStats]:
    from .fleet_defs import canonical_ship_key, get_ship

    key = canonical_ship_key(ship_key)
    spec = get_ship(key)
    if not spec:
        return None
    return _stats_from_spec(
        key,
        COMBAT_UNIT_SHIP,
        spec,
        canonical_target_fn=canonical_ship_key,
    )


def combat_stats_for_defense(defense_key: str) -> Optional[CombatUnitStats]:
    from .defense_defs import get_defense

    key = str(defense_key or "").strip()
    spec = get_defense(key)
    if not spec:
        return None
    return _stats_from_spec(
        key,
        COMBAT_UNIT_DEFENSE,
        spec,
        canonical_target_fn=lambda k: str(k or "").strip(),
    )


def resolve_combat_unit(unit_key: str, unit_type: str) -> Optional[CombatUnitStats]:
    """Unified lookup for resolver — unit_type is ``ship`` or ``defense``."""
    kind = str(unit_type or "").strip().lower()
    if kind == COMBAT_UNIT_SHIP:
        return combat_stats_for_ship(unit_key)
    if kind == COMBAT_UNIT_DEFENSE:
        return combat_stats_for_defense(unit_key)
    return None


def stacks_from_counts(
    counts: Mapping[str, int],
    *,
    unit_type: str,
) -> List[CombatStack]:
    """Build resolver-ready stacks from a stock map (planet_ships / planet_defense)."""
    stacks: List[CombatStack] = []
    for raw_key, raw_qty in counts.items():
        qty = _safe_int(raw_qty)
        if qty <= 0:
            continue
        stats = resolve_combat_unit(str(raw_key), unit_type)
        if stats is None:
            continue
        stacks.append(
            CombatStack(
                unit_key=stats.unit_key,
                unit_type=stats.unit_type,
                amount=qty,
                stats=stats,
            )
        )
    stacks.sort(key=lambda s: (s.unit_type, s.unit_key))
    return stacks


def rapid_fire_against(attacker: CombatUnitStats, defender_unit_key: str) -> int:
    """Rapid-fire factor vs a defender type (1 = no bonus; >=2 = resolver interprets)."""
    key = str(defender_unit_key or "").strip()
    if attacker.unit_type == COMBAT_UNIT_SHIP:
        from .fleet_defs import canonical_ship_key

        key = canonical_ship_key(key)
    return max(1, _safe_int(attacker.rapid_fire_targets.get(key), default=1))


def ship_combat_keys() -> FrozenSet[str]:
    from .fleet_defs import ACTIVE_SHIP_KEYS

    return ACTIVE_SHIP_KEYS


def defense_combat_keys() -> FrozenSet[str]:
    from .defense_defs import ACTIVE_DEFENSE_KEYS

    return ACTIVE_DEFENSE_KEYS


def validate_combat_registry() -> List[str]:
    """Return validation errors for active ship/defense combat profiles."""
    errors: List[str] = []
    for key in sorted(ship_combat_keys()):
        stats = combat_stats_for_ship(key)
        if stats is None:
            errors.append(f"ship missing combat profile: {key}")
            continue
        if stats.hull <= 0 and stats.attack <= 0 and stats.shield <= 0:
            errors.append(f"ship has no combat stats: {key}")
    for key in sorted(defense_combat_keys()):
        stats = combat_stats_for_defense(key)
        if stats is None:
            errors.append(f"defense missing combat profile: {key}")
            continue
        if stats.hull <= 0 and stats.attack <= 0 and stats.shield <= 0:
            errors.append(f"defense has no combat stats: {key}")
    return errors


def unit_display_name(unit_key: str, *, locale: str | None = None) -> str:
    """Player-facing ship or defense label — auto-detect kind, same source as fleet/defense UI."""
    from .defense_defs import defense_display_name, is_known_defense_key
    from .fleet_defs import ship_display_name

    key = str(unit_key or "").strip()
    if not key:
        return ""
    if is_known_defense_key(key):
        return defense_display_name(key, locale=locale)
    return ship_display_name(key, locale=locale)
