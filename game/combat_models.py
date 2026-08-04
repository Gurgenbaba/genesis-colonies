"""Canonical combat unit stats — data layer for ``game.combat.simulate_battle`` (GC-416+).

Registry lookups and stack builders only; battle logic lives in ``game/combat.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Mapping, Optional

COMBAT_UNIT_SHIP = "ship"
COMBAT_UNIT_DEFENSE = "defense"
COMBAT_UNIT_TROOP = "troop"
COMBAT_UNIT_TYPES: FrozenSet[str] = frozenset(
    {COMBAT_UNIT_SHIP, COMBAT_UNIT_DEFENSE, COMBAT_UNIT_TROOP}
)


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


def _canonical_matchup_key(unit_key: str, unit_type: str) -> str:
    if str(unit_type or "").strip().lower() == COMBAT_UNIT_SHIP:
        from .fleet_defs import canonical_ship_key

        return canonical_ship_key(unit_key)
    return str(unit_key or "").strip()


def _resolve_combat_unit_ref(raw_key: str) -> Optional[tuple[str, str, Mapping[str, Any]]]:
    from .defense_defs import get_defense
    from .fleet_defs import canonical_ship_key, get_ship

    ship_key = canonical_ship_key(str(raw_key or "").strip())
    ship_spec = get_ship(ship_key)
    if ship_spec:
        return ship_key, COMBAT_UNIT_SHIP, ship_spec
    defense_key = str(raw_key or "").strip()
    defense_spec = get_defense(defense_key)
    if defense_spec:
        return defense_key, COMBAT_UNIT_DEFENSE, defense_spec
    return None


def _unit_name_key(unit_key: str, unit_type: str) -> str:
    ref = _resolve_combat_unit_ref(unit_key)
    if not ref:
        key = str(unit_key or "").strip()
        return f"fleet_ship_{key}" if unit_type == COMBAT_UNIT_SHIP else f"defense_{key}"
    key, kind, spec = ref
    if kind == COMBAT_UNIT_SHIP:
        return str(spec.get("name_key") or f"fleet_ship_{key}")
    return str(spec.get("name_key") or f"defense_{key}")


def _unit_icon_path(unit_key: str, unit_type: str) -> str:
    if unit_type == COMBAT_UNIT_SHIP:
        from .fleet_defs import ship_icon_static_path

        return ship_icon_static_path(unit_key)
    if unit_type == COMBAT_UNIT_TROOP:
        from .troop_defs import troop_icon_static_path

        return troop_icon_static_path(unit_key)
    from .defense_defs import defense_icon_static_path

    return defense_icon_static_path(unit_key)


def _rapid_fire_lookup(source: CombatUnitStats, target_key: str, target_type: str) -> int:
    lookup = _canonical_matchup_key(target_key, target_type)
    return max(0, _safe_int(source.rapid_fire_targets.get(lookup), default=0))


def build_rapid_fire_matchup_payload(unit_key: str, unit_type: str) -> Dict[str, Any]:
    """
    Technical-data slice — rapid-fire advantages and counters for one unit.

    Derived only from canonical ship/defense ``rapid_fire_targets`` (no parallel lists).
    """
    kind = str(unit_type or "").strip().lower()
    if kind == COMBAT_UNIT_SHIP:
        stats = combat_stats_for_ship(unit_key)
    elif kind == COMBAT_UNIT_DEFENSE:
        stats = combat_stats_for_defense(unit_key)
    else:
        return {"rapid_fire_against": [], "vulnerable_to": []}
    if stats is None:
        return {"rapid_fire_against": [], "vulnerable_to": []}

    self_key = _canonical_matchup_key(unit_key, kind)

    against: List[Dict[str, Any]] = []
    seen_against: set[tuple[str, str]] = set()
    for target_key, mult in sorted(
        stats.rapid_fire_targets.items(),
        key=lambda item: (-int(item[1]), str(item[0])),
    ):
        rf = int(mult)
        if rf < 2:
            continue
        ref = _resolve_combat_unit_ref(target_key)
        if not ref:
            continue
        tk, tt, _spec = ref
        token = (tk, tt)
        if token in seen_against:
            continue
        seen_against.add(token)
        against.append(
            {
                "target_key": tk,
                "target_type": tt,
                "name_key": _unit_name_key(tk, tt),
                "rapid_fire": rf,
                "icon": _unit_icon_path(tk, tt),
            }
        )

    vulnerable: List[Dict[str, Any]] = []
    seen_vulnerable: set[tuple[str, str]] = set()
    for source_key in sorted(ship_combat_keys()):
        source = combat_stats_for_ship(source_key)
        if source is None:
            continue
        rf = _rapid_fire_lookup(source, self_key, kind)
        if rf < 2:
            continue
        token = (source.unit_key, source.unit_type)
        if token in seen_vulnerable:
            continue
        seen_vulnerable.add(token)
        vulnerable.append(
            {
                "source_key": source.unit_key,
                "source_type": source.unit_type,
                "name_key": _unit_name_key(source.unit_key, source.unit_type),
                "rapid_fire": rf,
                "icon": _unit_icon_path(source.unit_key, source.unit_type),
            }
        )
    for source_key in sorted(defense_combat_keys()):
        source = combat_stats_for_defense(source_key)
        if source is None:
            continue
        rf = _rapid_fire_lookup(source, self_key, kind)
        if rf < 2:
            continue
        token = (source.unit_key, source.unit_type)
        if token in seen_vulnerable:
            continue
        seen_vulnerable.add(token)
        vulnerable.append(
            {
                "source_key": source.unit_key,
                "source_type": source.unit_type,
                "name_key": _unit_name_key(source.unit_key, source.unit_type),
                "rapid_fire": rf,
                "icon": _unit_icon_path(source.unit_key, source.unit_type),
            }
        )
    vulnerable.sort(key=lambda row: (-int(row["rapid_fire"]), str(row["name_key"])))

    return {"rapid_fire_against": against, "vulnerable_to": vulnerable}


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
    """Player-facing ship, defense, or troop label — same source as fleet/defense/barracks UI."""
    from .defense_defs import defense_display_name, is_known_defense_key
    from .fleet_defs import ship_display_name
    from .troop_defs import is_known_troop_key, troop_display_name

    key = str(unit_key or "").strip()
    if not key:
        return ""
    if is_known_troop_key(key):
        return troop_display_name(key, locale=locale)
    if is_known_defense_key(key):
        return defense_display_name(key, locale=locale)
    return ship_display_name(key, locale=locale)
