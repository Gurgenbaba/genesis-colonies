"""Pure combat simulation — battle engine with shield/hull and rapid fire (GC-500–GC-503)."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .combat_models import (
    CombatResult,
    CombatRound,
    CombatSide,
    CombatStack,
    CombatUnitStats,
    make_combat_side,
    rapid_fire_against,
)
from .fleet_defs import rapid_fire_bonus_shot_chance

WINNER_ATTACKER = "attacker"
WINNER_DEFENDER = "defender"
WINNER_DRAW = "draw"

DEFAULT_MAX_ROUNDS = 6
_MAX_RF_CHAIN = 64
# Below this per-stack firer count, keep exact per-hull shots (existing tests / small fleets).
# Above: aggregate Monte-Carlo path — same RF rules, O(stacks + kills) instead of O(hulls).
_EXACT_SHOT_THRESHOLD = 8_000


@dataclass
class CombatModifiers:
    """Combat tech multipliers per side (0.0 = no bonus). Sourced from EffectResolver when using player ids."""

    weapon_bonus: float = 0.0
    armor_bonus: float = 0.0
    shield_bonus: float = 0.0


def combat_modifiers_from_effect_resolver(resolver) -> CombatModifiers:
    """Build modifiers from :meth:`EffectResolver.get_combat_modifiers`."""
    raw = resolver.get_combat_modifiers()
    return CombatModifiers(
        weapon_bonus=float(raw.get("weapon_bonus", 0.0) or 0.0),
        armor_bonus=float(raw.get("armor_bonus", 0.0) or 0.0),
        shield_bonus=float(raw.get("shield_bonus", 0.0) or 0.0),
    )


def combat_modifiers_for_player(
    player_id: int,
    *,
    planet_id: int | None = None,
    conn=None,
) -> CombatModifiers:
    """Account research + alliance combat bonuses via EffectResolver."""
    from .effects.effect_resolver import get_effect_resolver
    from .models import get_planet_buildings, get_research_levels

    pid = int(player_id)
    if planet_id is not None:
        resolver = get_effect_resolver(
            pid,
            conn=conn,
            buildings=get_planet_buildings(int(planet_id), conn=conn),
            research=get_research_levels(pid, conn=conn),
            planet={"id": int(planet_id)},
        )
    else:
        resolver = get_effect_resolver(pid, conn=conn)
    return combat_modifiers_from_effect_resolver(resolver)


def _merge_combat_modifiers(
    base: CombatModifiers,
    extra: CombatModifiers | None,
) -> CombatModifiers:
    if extra is None:
        return base
    return CombatModifiers(
        weapon_bonus=float(base.weapon_bonus) + float(extra.weapon_bonus),
        armor_bonus=float(base.armor_bonus) + float(extra.armor_bonus),
        shield_bonus=float(base.shield_bonus) + float(extra.shield_bonus),
    )


def _resolve_side_modifiers(
    player_id: int | None,
    *,
    planet_id: int | None,
    override: CombatModifiers | None,
    conn=None,
) -> CombatModifiers:
    if player_id is None:
        return override or CombatModifiers()
    base = combat_modifiers_for_player(int(player_id), planet_id=planet_id, conn=conn)
    return _merge_combat_modifiers(base, override)


def combat_research_snapshot_for_player(
    player_id: int,
    *,
    planet_id: int | None = None,
    conn=None,
) -> Dict[str, Any]:
    """
    Account combat tech levels + effective bonuses used by ``simulate_battle``.
    Stored on combat report metadata for inbox UI.
    """
    from .models import get_research_levels

    pid = int(player_id)
    if pid <= 0:
        return {}
    levels = get_research_levels(pid, conn=conn)
    mods = combat_modifiers_for_player(pid, planet_id=planet_id, conn=conn)

    def _entry(tech_key: str, bonus: float) -> Dict[str, int]:
        return {
            "level": max(0, int(levels.get(tech_key) or 0)),
            "bonus_pct": max(0, int(round(float(bonus) * 100))),
        }

    return {
        "weapon_tech": _entry("weapon_tech", mods.weapon_bonus),
        "armor_tech": _entry("armor_tech", mods.armor_bonus),
        "shield_tech": _entry("shield_tech", mods.shield_bonus),
    }


def _format_combat_research_lines(
    research: Mapping[str, Any] | None,
    *,
    tr_fn,
) -> list[str]:
    """Plain-text lines for weapon/armor/shield tech in combat reports."""
    snap = dict(research or {})
    if not snap:
        return [tr_fn("combat_report_research_none", "No combat research bonuses")]
    lines: list[str] = []
    for tech_key, label_key in (
        ("weapon_tech", "tech_weapon_tech"),
        ("armor_tech", "tech_armor_tech"),
        ("shield_tech", "tech_shield_tech"),
    ):
        entry = snap.get(tech_key) if isinstance(snap.get(tech_key), Mapping) else {}
        level = max(0, int(entry.get("level") or 0))
        bonus_pct = max(0, int(entry.get("bonus_pct") or 0))
        label = tr_fn(label_key, tech_key)
        lines.append(
            tr_fn(
                "combat_report_research_line",
                "%(tech)s: L%(level)s → +%(bonus)s%%",
                tech=label,
                level=str(level),
                bonus=str(bonus_pct),
            )
        )
    return lines


@dataclass
class _UnitState:
    unit_key: str
    unit_type: str
    amount: int
    stats: CombatUnitStats
    current_shield: int
    current_hull: int


def battle_loser(winner: str) -> str | None:
    """Opposite side of ``winner``; ``None`` on draw."""
    if winner == WINNER_ATTACKER:
        return WINNER_DEFENDER
    if winner == WINNER_DEFENDER:
        return WINNER_ATTACKER
    return None


def _effective_shield(stats: CombatUnitStats, mods: CombatModifiers) -> int:
    bonus = max(0.0, float(mods.shield_bonus))
    return max(0, int(round(int(stats.shield) * (1.0 + bonus))))


def _effective_hull(stats: CombatUnitStats, mods: CombatModifiers) -> int:
    bonus = max(0.0, float(mods.armor_bonus))
    return max(0, int(round(int(stats.hull) * (1.0 + bonus))))


def _effective_attack(stats: CombatUnitStats, mods: CombatModifiers) -> int:
    bonus = max(0.0, float(mods.weapon_bonus))
    if int(stats.attack) <= 0:
        return 0
    return max(0, int(round(int(stats.attack) * (1.0 + bonus))))


def _side_from_stacks(
    stacks: Sequence[CombatStack],
    *,
    mods: CombatModifiers,
    defense_combat_mult: float = 0.0,
) -> List[_UnitState]:
    units: List[_UnitState] = []
    defense_factor = 1.0 + max(0.0, float(defense_combat_mult or 0.0))
    for stack in stacks:
        qty = max(0, int(stack.amount))
        if qty <= 0:
            continue
        stats = stack.stats
        if defense_factor != 1.0 and str(stack.unit_type) == "defense":
            from dataclasses import replace

            stats = replace(
                stats,
                attack=max(0, int(round(int(stats.attack) * defense_factor))),
                shield=max(0, int(round(int(stats.shield) * defense_factor))),
                hull=max(0, int(round(int(stats.hull) * defense_factor))),
            )
        shield = _effective_shield(stats, mods)
        hull = _effective_hull(stats, mods)
        units.append(
            _UnitState(
                unit_key=str(stack.unit_key),
                unit_type=str(stack.unit_type),
                amount=qty,
                stats=stats,
                current_shield=shield,
                current_hull=hull,
            )
        )
    return units


def _clone_units(units: Sequence[_UnitState]) -> List[_UnitState]:
    return [
        _UnitState(
            unit_key=u.unit_key,
            unit_type=u.unit_type,
            amount=max(0, int(u.amount)),
            stats=u.stats,
            current_shield=max(0, int(u.current_shield)),
            current_hull=max(0, int(u.current_hull)),
        )
        for u in units
        if int(u.amount) > 0
    ]


def _sorted_live_units(units: Sequence[_UnitState]) -> List[_UnitState]:
    return sorted(
        [u for u in units if int(u.amount) > 0],
        key=lambda u: (str(u.unit_type), str(u.unit_key)),
    )


def _total_units(units: Sequence[_UnitState]) -> int:
    return sum(max(0, int(u.amount)) for u in units)


def _pick_target(units: Sequence[_UnitState], rng: random.Random) -> Optional[_UnitState]:
    live = [u for u in units if int(u.amount) > 0]
    if not live:
        return None
    weights = [max(0, int(u.amount)) for u in live]
    total = sum(weights)
    if total <= 0:
        return None
    roll = rng.randrange(total)
    acc = 0
    for unit, weight in zip(live, weights):
        acc += weight
        if roll < acc:
            return unit
    return live[-1]


def _rapid_fire_multiplier(attacker: CombatUnitStats, target: _UnitState) -> int:
    """Multiplier from ``rapid_fire_targets`` on the attacker's combat profile (defs-backed)."""
    return rapid_fire_against(attacker, target.unit_key)


def _apply_damage_to_lead(unit: _UnitState, damage: int, *, mods: CombatModifiers) -> None:
    """
    Apply damage to the lead unit: shield first, remainder to hull.
    When hull <= 0 the unit is destroyed and the next copy is refreshed.
    """
    remaining = max(0, int(damage))
    if remaining <= 0 or unit.amount <= 0:
        return

    if unit.current_shield > 0:
        absorbed = min(unit.current_shield, remaining)
        unit.current_shield -= absorbed
        remaining -= absorbed

    if remaining > 0:
        unit.current_hull -= remaining

    if unit.current_hull <= 0:
        unit.amount -= 1
        if unit.amount > 0:
            unit.current_shield = _effective_shield(unit.stats, mods)
            unit.current_hull = _effective_hull(unit.stats, mods)
        else:
            unit.current_shield = 0
            unit.current_hull = 0


def _fire_ship_shots(
    attacker: _UnitState,
    defenders: List[_UnitState],
    *,
    attacker_mods: CombatModifiers,
    defender_mods: CombatModifiers,
    rng: random.Random,
) -> None:
    """One firing ship: first shot, then bonus shots per ``rapid_fire_bonus_shot_chance``."""
    attack = _effective_attack(attacker.stats, attacker_mods)
    if attack <= 0 or attacker.amount <= 0:
        return

    target = _pick_target(defenders, rng)
    if target is None:
        return

    mult = _rapid_fire_multiplier(attacker.stats, target)
    bonus_chance = rapid_fire_bonus_shot_chance(mult)
    shots = 0

    while shots < _MAX_RF_CHAIN and _total_units(defenders) > 0:
        tgt = _pick_target(defenders, rng)
        if tgt is None:
            break
        _apply_damage_to_lead(tgt, attack, mods=defender_mods)
        shots += 1
        if bonus_chance <= 0.0:
            break
        if rng.random() >= bonus_chance:
            break


def _binomial(rng: random.Random, n: int, p: float) -> int:
    """Binomial(n, p) sample. Normal approx for large n to stay O(1)."""
    nn = max(0, int(n))
    if nn <= 0:
        return 0
    pp = float(p)
    if pp <= 0.0:
        return 0
    if pp >= 1.0:
        return nn
    if nn <= 64:
        return sum(1 for _ in range(nn) if rng.random() < pp)
    mean = nn * pp
    var = nn * pp * (1.0 - pp)
    if var <= 0.0:
        return int(round(mean))
    sample = rng.gauss(mean, math.sqrt(var))
    return max(0, min(nn, int(sample + 0.5)))


def _multinomial(rng: random.Random, n: int, weights: Sequence[int]) -> List[int]:
    """Distribute n indistinguishable trials across weighted bins."""
    bins = len(weights)
    if bins <= 0:
        return []
    remaining = max(0, int(n))
    if remaining <= 0:
        return [0] * bins
    total_w = sum(max(0, int(w)) for w in weights)
    if total_w <= 0:
        out = [0] * bins
        out[-1] = remaining
        return out
    out: List[int] = []
    left_w = total_w
    for i, raw_w in enumerate(weights):
        if i == bins - 1:
            out.append(remaining)
            break
        w = max(0, int(raw_w))
        if remaining <= 0 or left_w <= 0 or w <= 0:
            out.append(0)
            left_w -= w
            continue
        k = _binomial(rng, remaining, w / left_w)
        out.append(k)
        remaining -= k
        left_w -= w
    return out


def _geometric_shot_count(rng: random.Random, ships: int, bonus_chance: float) -> int:
    """
    Total shots from ``ships`` firers with rapid-fire bonus chance ``bonus_chance``.
    Same rule as ``_fire_ship_shots``: first shot always, then keep going with p until fail/cap.
    """
    rem = max(0, int(ships))
    if rem <= 0:
        return 0
    p = float(bonus_chance)
    total = 0
    for _ in range(_MAX_RF_CHAIN):
        total += rem
        if rem <= 0 or p <= 0.0:
            break
        rem = _binomial(rng, rem, p)
    return total


def _shots_to_finish_hp(shield: int, hull: int, damage_per_shot: int) -> int:
    """How many identical shots destroy a unit starting at the given shield/hull."""
    dmg = max(0, int(damage_per_shot))
    if dmg <= 0:
        return 10**18
    # Shield does not regen between shots on the same lead unit, so HP is one pool.
    pool = max(0, int(shield)) + max(0, int(hull))
    if pool <= 0:
        return 0
    return (pool + dmg - 1) // dmg


def _apply_pool_damage_to_lead(
    unit: _UnitState,
    total_damage: int,
    *,
    mods: CombatModifiers,
) -> None:
    """Apply aggregated damage to the lead unit (shield then hull); may destroy and refresh."""
    remaining = max(0, int(total_damage))
    if remaining <= 0 or unit.amount <= 0:
        return
    if unit.current_shield > 0:
        absorbed = min(unit.current_shield, remaining)
        unit.current_shield -= absorbed
        remaining -= absorbed
    if remaining > 0:
        unit.current_hull -= remaining
    if unit.current_hull <= 0:
        unit.amount -= 1
        if unit.amount > 0:
            unit.current_shield = _effective_shield(unit.stats, mods)
            unit.current_hull = _effective_hull(unit.stats, mods)
        else:
            unit.current_shield = 0
            unit.current_hull = 0


def _apply_shots_bulk(
    unit: _UnitState,
    shots: int,
    damage_per_shot: int,
    *,
    mods: CombatModifiers,
) -> None:
    """Apply ``shots`` identical hits to a stack; O(1) in shot count (aggregate path)."""
    remaining_shots = max(0, int(shots))
    dmg = max(0, int(damage_per_shot))
    if remaining_shots <= 0 or dmg <= 0 or unit.amount <= 0:
        return

    full_shield = _effective_shield(unit.stats, mods)
    full_hull = _effective_hull(unit.stats, mods)
    if full_hull <= 0 and full_shield <= 0:
        return

    shots_per_fresh = _shots_to_finish_hp(full_shield, full_hull, dmg)
    if shots_per_fresh <= 0:
        unit.amount = 0
        unit.current_shield = 0
        unit.current_hull = 0
        return

    # Damaged lead first (not at full HP).
    if unit.current_shield != full_shield or unit.current_hull != full_hull:
        need = _shots_to_finish_hp(unit.current_shield, unit.current_hull, dmg)
        if need <= 0:
            unit.amount -= 1
            if unit.amount > 0:
                unit.current_shield = full_shield
                unit.current_hull = full_hull
            else:
                unit.current_shield = 0
                unit.current_hull = 0
                return
        elif remaining_shots < need:
            _apply_pool_damage_to_lead(unit, remaining_shots * dmg, mods=mods)
            return
        else:
            remaining_shots -= need
            unit.amount -= 1
            if unit.amount <= 0:
                unit.current_shield = 0
                unit.current_hull = 0
                return
            unit.current_shield = full_shield
            unit.current_hull = full_hull

    if remaining_shots >= shots_per_fresh and unit.amount > 0:
        kills = min(unit.amount, remaining_shots // shots_per_fresh)
        if kills > 0:
            unit.amount -= kills
            remaining_shots -= kills * shots_per_fresh
            if unit.amount <= 0:
                unit.current_shield = 0
                unit.current_hull = 0
                return
            unit.current_shield = full_shield
            unit.current_hull = full_hull

    if remaining_shots > 0 and unit.amount > 0:
        _apply_pool_damage_to_lead(unit, remaining_shots * dmg, mods=mods)


def _fire_stack_aggregate(
    attacker: _UnitState,
    defenders: List[_UnitState],
    *,
    attacker_mods: CombatModifiers,
    defender_mods: CombatModifiers,
    rng: random.Random,
) -> None:
    """
    Large-stack shooting: same RF first-target rule, but batch shot counts and HP apply.
    Used only when firer amount exceeds ``_EXACT_SHOT_THRESHOLD``.
    """
    attack = _effective_attack(attacker.stats, attacker_mods)
    ships = max(0, int(attacker.amount))
    if attack <= 0 or ships <= 0:
        return

    live = [u for u in defenders if int(u.amount) > 0]
    if not live:
        return

    weights = [max(0, int(u.amount)) for u in live]
    first_picks = _multinomial(rng, ships, weights)

    total_shots = 0
    for target, n_ships in zip(live, first_picks):
        if n_ships <= 0:
            continue
        mult = _rapid_fire_multiplier(attacker.stats, target)
        bonus_chance = rapid_fire_bonus_shot_chance(mult)
        total_shots += _geometric_shot_count(rng, n_ships, bonus_chance)

    if total_shots <= 0:
        return

    # Each RF shot re-picks a target — redistribute the shot pool by current weights.
    live = [u for u in defenders if int(u.amount) > 0]
    if not live:
        return
    weights = [max(0, int(u.amount)) for u in live]
    shot_dist = _multinomial(rng, total_shots, weights)
    for target, n_shots in zip(live, shot_dist):
        if n_shots > 0 and target.amount > 0:
            _apply_shots_bulk(target, n_shots, attack, mods=defender_mods)


def _shooting_phase(
    attackers: List[_UnitState],
    defenders: List[_UnitState],
    *,
    attacker_mods: CombatModifiers,
    defender_mods: CombatModifiers,
    rng: random.Random,
) -> None:
    """Each attacking hull fires once per round; rapid fire may grant extra shots."""
    for unit in _sorted_live_units(attackers):
        if _effective_attack(unit.stats, attacker_mods) <= 0:
            continue
        amount = int(unit.amount)
        if amount <= 0:
            continue
        if _total_units(defenders) <= 0:
            return
        if amount <= _EXACT_SHOT_THRESHOLD:
            for _ in range(amount):
                if _total_units(defenders) <= 0:
                    return
                _fire_ship_shots(
                    unit,
                    defenders,
                    attacker_mods=attacker_mods,
                    defender_mods=defender_mods,
                    rng=rng,
                )
        else:
            _fire_stack_aggregate(
                unit,
                defenders,
                attacker_mods=attacker_mods,
                defender_mods=defender_mods,
                rng=rng,
            )


def _loss_map(initial: Mapping[str, int], remaining: Sequence[_UnitState]) -> Dict[str, int]:
    rem: Dict[str, int] = {}
    for unit in remaining:
        rem[unit.unit_key] = rem.get(unit.unit_key, 0) + max(0, int(unit.amount))
    losses: Dict[str, int] = {}
    for key, start in initial.items():
        lost = max(0, int(start) - rem.get(key, 0))
        if lost > 0:
            losses[key] = lost
    return losses


def _initial_counts(units: Sequence[_UnitState]) -> Dict[str, int]:
    return {u.unit_key: u.amount for u in units}


def _round_losses(
    before_atk: Dict[str, int],
    before_def: Dict[str, int],
    atk_units: List[_UnitState],
    def_units: List[_UnitState],
) -> Tuple[Dict[str, int], Dict[str, int]]:
    return _loss_map(before_atk, atk_units), _loss_map(before_def, def_units)


def _merge_losses(into: Dict[str, int], delta: Mapping[str, int]) -> None:
    for key, qty in delta.items():
        lost = max(0, int(qty))
        if lost > 0:
            into[key] = into.get(key, 0) + lost


def _side_firepower(units: Sequence[_UnitState], mods: CombatModifiers) -> int:
    """Remaining firepower for tie-break (no rapid fire extrapolation)."""
    power = 0
    for unit in units:
        qty = max(0, int(unit.amount))
        if qty <= 0:
            continue
        attack = _effective_attack(unit.stats, mods)
        if attack > 0:
            power += qty * attack
    return power


def _reset_live_shields(units: Sequence[_UnitState], mods: CombatModifiers) -> None:
    """OGame-like round boundary: surviving lead units start each round with full shields."""
    for unit in units:
        if int(unit.amount) > 0:
            unit.current_shield = _effective_shield(unit.stats, mods)


def _resolve_elimination_winner(
    attacker_units: Sequence[_UnitState],
    defender_units: Sequence[_UnitState],
) -> str:
    atk_left = _total_units(attacker_units)
    def_left = _total_units(defender_units)
    if atk_left > 0 and def_left <= 0:
        return WINNER_ATTACKER
    if def_left > 0 and atk_left <= 0:
        return WINNER_DEFENDER
    if atk_left <= 0 and def_left <= 0:
        return WINNER_DRAW
    return WINNER_DRAW


def _resolve_winner(
    attacker_units: Sequence[_UnitState],
    defender_units: Sequence[_UnitState],
    *,
    atk_mods: CombatModifiers,
    def_mods: CombatModifiers,
) -> str:
    atk_left = _total_units(attacker_units)
    def_left = _total_units(defender_units)
    if atk_left > 0 and def_left <= 0:
        return WINNER_ATTACKER
    if def_left > 0 and atk_left <= 0:
        return WINNER_DEFENDER
    if atk_left <= 0 and def_left <= 0:
        return WINNER_DRAW
    atk_power = _side_firepower(attacker_units, atk_mods)
    def_power = _side_firepower(defender_units, def_mods)
    if atk_power > def_power:
        return WINNER_ATTACKER
    if def_power > atk_power:
        return WINNER_DEFENDER
    return WINNER_DRAW


def _normalize_side(
    side: CombatSide | Sequence[CombatStack],
    *,
    default_role: str,
) -> CombatSide:
    if isinstance(side, CombatSide):
        return side
    return make_combat_side(default_role, list(side))


def _run_round(
    atk_units: List[_UnitState],
    def_units: List[_UnitState],
    *,
    atk_mods: CombatModifiers,
    def_mods: CombatModifiers,
    rng: random.Random,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    One battle round: both sides fire from their round-start stacks, then losses are tracked.
    """
    before_atk = _initial_counts(atk_units)
    before_def = _initial_counts(def_units)
    atk_shooters = _clone_units(atk_units)
    def_shooters = _clone_units(def_units)

    _shooting_phase(
        atk_shooters,
        def_units,
        attacker_mods=atk_mods,
        defender_mods=def_mods,
        rng=rng,
    )
    _shooting_phase(
        def_shooters,
        atk_units,
        attacker_mods=def_mods,
        defender_mods=atk_mods,
        rng=rng,
    )

    return _round_losses(before_atk, before_def, atk_units, def_units)


def simulate_battle(
    attacker: CombatSide | Sequence[CombatStack],
    defender: CombatSide | Sequence[CombatStack],
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    rng: random.Random | None = None,
    attacker_modifiers: CombatModifiers | None = None,
    defender_modifiers: CombatModifiers | None = None,
    attacker_player_id: int | None = None,
    defender_player_id: int | None = None,
    attacker_planet_id: int | None = None,
    defender_planet_id: int | None = None,
    conn=None,
) -> CombatResult:
    """
    Run a combat simulation. Inputs are not mutated; no side effects.

    Per round: both sides fire from their round-start stacks (rapid fire + shield/hull per shot).
    Combat ends early only when one side is eliminated; otherwise the final
    winner is decided after the round cap by remaining firepower.
    Pass ``attacker_player_id`` / ``defender_player_id`` to apply account research via
    :class:`game.effects.effect_resolver.EffectResolver` (weapon_tech, armor_tech, shield_tech).
    Explicit ``*_modifiers`` are added on top of resolver bonuses.
    """
    atk_side = _normalize_side(attacker, default_role=WINNER_ATTACKER)
    def_side = _normalize_side(defender, default_role=WINNER_DEFENDER)
    atk_mods = _resolve_side_modifiers(
        attacker_player_id,
        planet_id=attacker_planet_id,
        override=attacker_modifiers,
        conn=conn,
    )
    def_mods = _resolve_side_modifiers(
        defender_player_id,
        planet_id=defender_planet_id,
        override=defender_modifiers,
        conn=conn,
    )
    battle_rng = rng if rng is not None else random.Random()

    defense_combat_mult = 0.0
    if defender_planet_id is not None:
        try:
            from .galactic_directives.mechanics import get_directive_flags_for_galaxy

            row = None
            if conn is not None:
                row = conn.execute(
                    "SELECT galaxy FROM planets WHERE id = ? LIMIT 1;",
                    (int(defender_planet_id),),
                ).fetchone()
            galaxy = int(row["galaxy"]) if row and row["galaxy"] is not None else 0
            if galaxy > 0:
                flags = get_directive_flags_for_galaxy(galaxy, conn=conn) or {}
                defense_combat_mult = float(flags.get("defense_combat_mult") or 0.0)
        except Exception:
            defense_combat_mult = 0.0

    atk_units = _side_from_stacks(atk_side.stacks, mods=atk_mods)
    def_units = _side_from_stacks(
        def_side.stacks,
        mods=def_mods,
        defense_combat_mult=defense_combat_mult,
    )

    if _total_units(atk_units) <= 0 and _total_units(def_units) <= 0:
        return CombatResult(
            winner=WINNER_DRAW,
            rounds=(),
            attacker_losses={},
            defender_losses={},
        )
    if _total_units(atk_units) <= 0:
        return CombatResult(
            winner=WINNER_DEFENDER,
            rounds=(),
            attacker_losses={},
            defender_losses={},
        )
    if _total_units(def_units) <= 0:
        return CombatResult(
            winner=WINNER_ATTACKER,
            rounds=(),
            attacker_losses={},
            defender_losses={},
        )

    total_atk_losses: Dict[str, int] = {}
    total_def_losses: Dict[str, int] = {}
    round_rows: List[CombatRound] = []
    rounds_limit = max(1, min(int(max_rounds), DEFAULT_MAX_ROUNDS))

    for round_no in range(1, rounds_limit + 1):
        if _total_units(atk_units) <= 0 or _total_units(def_units) <= 0:
            break
        _reset_live_shields(atk_units, atk_mods)
        _reset_live_shields(def_units, def_mods)

        round_atk_losses, round_def_losses = _run_round(
            atk_units,
            def_units,
            atk_mods=atk_mods,
            def_mods=def_mods,
            rng=battle_rng,
        )
        _merge_losses(total_atk_losses, round_atk_losses)
        _merge_losses(total_def_losses, round_def_losses)
        round_rows.append(
            CombatRound(
                number=round_no,
                attacker_losses=dict(round_atk_losses),
                defender_losses=dict(round_def_losses),
            )
        )

        winner = _resolve_elimination_winner(atk_units, def_units)
        if winner != WINNER_DRAW:
            break

    winner = _resolve_winner(atk_units, def_units, atk_mods=atk_mods, def_mods=def_mods)

    return CombatResult(
        winner=winner,
        rounds=tuple(round_rows),
        attacker_losses=dict(total_atk_losses),
        defender_losses=dict(total_def_losses),
    )


COMBAT_REPORT_VERSION = 2
COMBAT_PLUNDER_FRACTION = 0.5
DEBRIS_METAL_FRACTION = 0.3
DEBRIS_CRYSTAL_FRACTION = 0.3
DEBRIS_FIELD_TTL_SECONDS = 7 * 24 * 3600


def unit_build_cost_for_debris(unit_key: str) -> Tuple[int, int]:
    """Build-cost metal/crystal for one destroyed ship or defense unit."""
    from .defense_defs import get_defense, is_known_defense_key
    from .fleet_defs import canonical_ship_key, get_ship

    key = str(unit_key or "").strip()
    if is_known_defense_key(key):
        spec = get_defense(key) or {}
    else:
        spec = get_ship(canonical_ship_key(key)) or {}
    cost = spec.get("build_cost") or {}
    return max(0, int(cost.get("metal") or 0)), max(0, int(cost.get("crystal") or 0))


def calculate_debris_from_losses(losses: Mapping[str, int]) -> Tuple[int, int]:
    """Debris from destroyed units (fraction of build cost → Ferronit / Crytite)."""
    metal = 0
    crystal = 0
    for raw_key, raw_qty in losses.items():
        lost = max(0, int(raw_qty))
        if lost <= 0:
            continue
        unit_metal, unit_crystal = unit_build_cost_for_debris(str(raw_key))
        metal += int(unit_metal * lost * DEBRIS_METAL_FRACTION)
        crystal += int(unit_crystal * lost * DEBRIS_CRYSTAL_FRACTION)
    return metal, crystal


def calculate_combat_debris(
    attacker_losses: Mapping[str, int],
    defender_losses: Mapping[str, int],
) -> Tuple[int, int]:
    """Total debris from both sides' destroyed stacks."""
    m1, c1 = calculate_debris_from_losses(attacker_losses)
    m2, c2 = calculate_debris_from_losses(defender_losses)
    return m1 + m2, c1 + c2


def estimate_recycler_slots_needed(metal: int, crystal: int) -> int:
    """Display hint: harvest_reclaimer ships needed to carry all debris in one trip."""
    from .fleet_defs import SHIPS

    cargo = max(0, int((SHIPS.get("harvest_reclaimer") or {}).get("cargo") or 0))
    total = max(0, int(metal)) + max(0, int(crystal))
    if total <= 0 or cargo <= 0:
        return 0
    return (total + cargo - 1) // cargo


def build_combat_debris_metadata(
    attacker_losses: Mapping[str, int],
    defender_losses: Mapping[str, int],
) -> Dict[str, int] | None:
    """Structured debris block for combat report metadata (UX only, no DB)."""
    metal, crystal = calculate_combat_debris(attacker_losses, defender_losses)
    if metal <= 0 and crystal <= 0:
        return None
    return {
        "metal": int(metal),
        "crystal": int(crystal),
        "ttl": int(DEBRIS_FIELD_TTL_SECONDS),
        "recycler_slots_needed": estimate_recycler_slots_needed(metal, crystal),
    }


def debris_schema_ready(conn) -> bool:
    from .db import table_exists

    return table_exists(conn, "debris_fields")


def expire_due_debris_fields(
    *,
    conn,
    now: Optional[float] = None,
) -> int:
    """Hard-delete debris rows past ``DEBRIS_FIELD_TTL_SECONDS`` (from ``updated_at``).

    Returns the number of deleted rows.
    """
    if not debris_schema_ready(conn):
        return 0
    ts = float(now if now is not None else time.time())
    cutoff = ts - float(DEBRIS_FIELD_TTL_SECONDS)
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM debris_fields
        WHERE updated_at <= ?;
        """,
        (cutoff,),
    )
    return max(0, int(cur.rowcount or 0))


def add_debris_field(
    galaxy: int,
    system: int,
    position: int,
    metal: int,
    crystal: int,
    *,
    conn,
) -> Dict[str, int]:
    """Accumulate debris at coordinates; returns field totals after insert."""
    from .galaxy import validate_coordinates

    if not debris_schema_ready(conn):
        return {"metal": 0, "crystal": 0}
    g, s, p = int(galaxy), int(system), int(position)
    validate_coordinates(g, s, p)
    add_metal = max(0, int(metal))
    add_crystal = max(0, int(crystal))
    if add_metal <= 0 and add_crystal <= 0:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT metal, crystal FROM debris_fields
            WHERE galaxy = ? AND system = ? AND position = ?
            LIMIT 1;
            """,
            (g, s, p),
        )
        row = cur.fetchone()
        if row:
            return {
                "metal": max(0, int(float(row["metal"]))),
                "crystal": max(0, int(float(row["crystal"]))),
            }
        return {"metal": 0, "crystal": 0}

    now = int(time.time())
    cutoff = now - int(DEBRIS_FIELD_TTL_SECONDS)
    cur = conn.cursor()
    # Write-path hygiene: do not accumulate onto an expired row (Galaxy GET only filters).
    cur.execute(
        """
        DELETE FROM debris_fields
        WHERE galaxy = ? AND system = ? AND position = ?
          AND updated_at <= ?;
        """,
        (g, s, p, float(cutoff)),
    )
    cur.execute(
        """
        INSERT INTO debris_fields (galaxy, system, position, metal, crystal, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(galaxy, system, position) DO UPDATE SET
            metal = debris_fields.metal + excluded.metal,
            crystal = debris_fields.crystal + excluded.crystal,
            updated_at = excluded.updated_at;
        """,
        (g, s, p, float(add_metal), float(add_crystal), now),
    )
    cur.execute(
        """
        SELECT metal, crystal FROM debris_fields
        WHERE galaxy = ? AND system = ? AND position = ?
        LIMIT 1;
        """,
        (g, s, p),
    )
    row = cur.fetchone()
    if not row:
        return {"metal": add_metal, "crystal": add_crystal}
    return {
        "metal": max(0, int(float(row["metal"]))),
        "crystal": max(0, int(float(row["crystal"]))),
    }


def spawn_combat_debris_field(
    *,
    galaxy: int,
    system: int,
    position: int,
    attacker_losses: Mapping[str, int],
    defender_losses: Mapping[str, int],
    conn,
) -> Dict[str, int]:
    """Create or grow debris at the battle coordinates from combat losses."""
    metal, crystal = calculate_combat_debris(attacker_losses, defender_losses)
    return add_debris_field(galaxy, system, position, metal, crystal, conn=conn)


def get_debris_at_field(
    galaxy: int,
    system: int,
    position: int,
    *,
    conn,
    now: Optional[float] = None,
) -> Dict[str, int]:
    """Return metal/crystal at galaxy coordinates (0 if no field or TTL expired)."""
    if not debris_schema_ready(conn):
        return {"metal": 0, "crystal": 0}
    from .galaxy import validate_coordinates

    # Purge expired rows so harvest / fleet gates never see stale debris.
    expire_due_debris_fields(conn=conn, now=now)

    g, s, p = int(galaxy), int(system), int(position)
    validate_coordinates(g, s, p)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT metal, crystal FROM debris_fields
        WHERE galaxy = ? AND system = ? AND position = ?
        LIMIT 1;
        """,
        (g, s, p),
    )
    row = cur.fetchone()
    if not row:
        return {"metal": 0, "crystal": 0}
    return {
        "metal": max(0, int(float(row["metal"]))),
        "crystal": max(0, int(float(row["crystal"]))),
    }


def harvest_debris_at_field(
    galaxy: int,
    system: int,
    position: int,
    *,
    harvested: Mapping[str, int],
    conn,
) -> bool:
    """Atomically subtract harvested amounts from debris_fields."""
    if not debris_schema_ready(conn):
        return False
    metal_take = max(0, int(harvested.get("metal") or 0))
    crystal_take = max(0, int(harvested.get("crystal") or 0))
    if metal_take <= 0 and crystal_take <= 0:
        return True
    from .galaxy import validate_coordinates

    g, s, p = int(galaxy), int(system), int(position)
    validate_coordinates(g, s, p)
    now = int(time.time())
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE debris_fields
        SET metal = metal - ?,
            crystal = crystal - ?,
            updated_at = ?
        WHERE galaxy = ? AND system = ? AND position = ?
          AND metal >= ? AND crystal >= ?;
        """,
        (
            float(metal_take),
            float(crystal_take),
            now,
            g,
            s,
            p,
            float(metal_take),
            float(crystal_take),
        ),
    )
    if cur.rowcount != 1:
        return False
    cur.execute(
        """
        DELETE FROM debris_fields
        WHERE galaxy = ? AND system = ? AND position = ?
          AND metal <= 0 AND crystal <= 0;
        """,
        (g, s, p),
    )
    return True


def spawn_combat_debris_at_planet(
    planet_id: int,
    *,
    attacker_losses: Mapping[str, int],
    defender_losses: Mapping[str, int],
    conn,
) -> Dict[str, int]:
    """Spawn debris at the planet's galaxy slot after combat."""
    cur = conn.cursor()
    cur.execute(
        """
        SELECT galaxy, system, position FROM planets
        WHERE id = ? AND system IS NOT NULL AND position IS NOT NULL
        LIMIT 1;
        """,
        (int(planet_id),),
    )
    row = cur.fetchone()
    if not row:
        return {"metal": 0, "crystal": 0}
    return spawn_combat_debris_field(
        galaxy=int(row["galaxy"]),
        system=int(row["system"]),
        position=int(row["position"]),
        attacker_losses=attacker_losses,
        defender_losses=defender_losses,
        conn=conn,
    )


def combat_result_label(winner: str | None) -> str:
    """Map resolver winner id to inbox metadata ``result`` value."""
    if winner == WINNER_ATTACKER:
        return "attacker"
    if winner == WINNER_DEFENDER:
        return "defender"
    if winner == WINNER_DRAW:
        return "draw"
    return "undecided"


def combat_rounds_for_metadata(combat_result: Any | None) -> list[dict[str, Any]]:
    """Serialize per-round loss snapshots for permanent message metadata."""
    rows: list[dict[str, Any]] = []
    for rnd in getattr(combat_result, "rounds", ()) or ():
        rows.append(
            {
                "number": int(getattr(rnd, "number", 0) or 0),
                "attacker_losses": dict(getattr(rnd, "attacker_losses", {}) or {}),
                "defender_losses": dict(getattr(rnd, "defender_losses", {}) or {}),
            }
        )
    return rows


def _format_kv_section(title: str, lines: Sequence[str]) -> str:
    if not lines:
        return ""
    return f"{title}\n" + "\n".join(f"  {line}" for line in lines)


def _unit_label(unit_key: str, *, locale: str | None = None, tr_fn=None) -> str:
    key = str(unit_key or "").strip()
    resource_key = {
        "metal": "resource_metal",
        "crystal": "resource_crystal",
        "fuel_cells": "resource_fuel_cells",
    }.get(key)
    if resource_key and tr_fn is not None:
        return tr_fn(resource_key, key)
    from .combat_models import unit_display_name

    return unit_display_name(key, locale=locale)


def _format_stock_lines(
    stock: Mapping[str, int],
    *,
    tr_fn,
    fmt_int,
    empty_key: str,
    empty_default: str,
    locale: str | None = None,
) -> list[str]:
    entries = [(k, max(0, int(v))) for k, v in stock.items() if max(0, int(v)) > 0]
    if not entries:
        return [tr_fn(empty_key, empty_default)]
    lines: list[str] = []
    for key, qty in sorted(entries, key=lambda x: x[0]):
        lines.append(f"{_unit_label(key, locale=locale, tr_fn=tr_fn)} ×{fmt_int(qty)}")
    return lines


def apply_combat_loot(
    *,
    winner: str | None,
    target_planet_id: int,
    return_ships: Mapping[str, int],
    existing_resources: Mapping[str, Any] | None = None,
    conn=None,
    plunder_fraction: float = COMBAT_PLUNDER_FRACTION,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    """
    Plunder defender planet when attacker wins; load loot onto return flight up to cargo cap.
    Returns ``(loot_taken, fleet_resources_json)``.
    """
    from .fleet_calc import (
        calculate_loaded_resources,
        calculate_total_cargo,
        loaded_resource_total,
    )
    from .resources import (
        calculate_plunder_pool,
        debit_planet_resources,
        get_planet_resource_stock,
        load_resources_up_to_cargo,
        merge_loaded_resources,
    )

    current = calculate_loaded_resources(existing_resources)
    if str(winner or "") != WINNER_ATTACKER or int(target_planet_id) <= 0:
        return {}, current

    available = get_planet_resource_stock(int(target_planet_id), conn=conn)
    pool = calculate_plunder_pool(available, plunder_fraction=plunder_fraction)
    cargo_total = calculate_total_cargo(return_ships)
    remaining_cap = max(0, cargo_total - loaded_resource_total(current))
    loot = load_resources_up_to_cargo(pool, remaining_cap)
    if loaded_resource_total(loot) <= 0:
        return {}, current
    if not debit_planet_resources(int(target_planet_id), loot, conn=conn):
        return {}, current
    final = merge_loaded_resources(current, loot)
    return loot, calculate_loaded_resources(final)


def build_combat_report(
    *,
    attacker_id: int,
    attacker_name: str,
    defender_id: int,
    defender_name: str,
    coords: str,
    attacking_ships: Mapping[str, int],
    defending_ships: Mapping[str, int],
    defending_defense: Mapping[str, int] | None = None,
    combat_result: Any | None = None,
    attacker_losses: Mapping[str, int] | None = None,
    defender_losses: Mapping[str, int] | None = None,
    return_ships: Mapping[str, int] | None = None,
    loot: Mapping[str, int] | None = None,
    origin_coords: str | None = None,
    origin_planet_name: str | None = None,
    target_planet_name: str | None = None,
    attacker_planet_id: int | None = None,
    defender_planet_id: int | None = None,
    conn=None,
    locale: str | None = None,
    combat_kind: str | None = None,
    defender_research_override: Mapping[str, Any] | None = None,
    attacking_troops: Mapping[str, int] | None = None,
    defending_troops: Mapping[str, int] | None = None,
    vault_raid: Mapping[str, Any] | None = None,
) -> Tuple[str, Dict[str, Any]]:
    """Genesis-style combat report body + structured metadata for ``player_messages``."""
    from .i18n import fmt_int, tr
    from .troop_defs import normalize_troops

    loc = locale
    kind = str(combat_kind or "").strip().lower()
    expo_pirate = kind == "expedition_pirate"
    npc_research_override = (
        dict(defender_research_override) if defender_research_override else None
    )

    def _t(key: str, default: str | None = None, **kw: Any) -> str:
        return tr(key, default, locale=loc, **kw)

    def_def = dict(defending_defense or {})
    atk_troops = normalize_troops(attacking_troops)
    def_troops_in = normalize_troops(defending_troops)
    vault_meta = dict(vault_raid) if isinstance(vault_raid, Mapping) else None
    winner = getattr(combat_result, "winner", None) if combat_result is not None else None
    result_label = combat_result_label(winner)
    atk_loss = dict(attacker_losses or getattr(combat_result, "attacker_losses", None) or {})
    def_loss = dict(defender_losses or getattr(combat_result, "defender_losses", None) or {})
    ret = dict(return_ships or {})
    rounds_meta = combat_rounds_for_metadata(combat_result)

    winner_txt = {
        "attacker": _t("combat_report_winner_attacker", "Victory: attacker"),
        "defender": _t("combat_report_winner_defender", "Victory: defender"),
        "draw": _t("combat_report_winner_draw", "Outcome: draw"),
        "undecided": _t("combat_report_winner_undecided", "Outcome: undecided"),
    }.get(result_label, _t("combat_report_winner_undecided", "Outcome: undecided"))

    origin_coord_txt = str(origin_coords or "—")
    target_coord_txt = str(coords or "—")
    target_planet_txt = str(target_planet_name or "").strip()
    origin_planet_txt = str(origin_planet_name or "").strip()

    # Expo pirates: player tech applies; NPC may carry rolled combat tech (override).
    atk_research = (
        combat_research_snapshot_for_player(
            int(attacker_id),
            planet_id=int(attacker_planet_id) if attacker_planet_id else None,
            conn=conn,
        )
        if int(attacker_id) > 0
        else {}
    )
    if expo_pirate:
        def_research = npc_research_override
    else:
        def_research = (
            combat_research_snapshot_for_player(
                int(defender_id),
                planet_id=int(defender_planet_id) if defender_planet_id else None,
                conn=conn,
            )
            if int(defender_id) > 0
            else {}
        )

    body_lines: list[str] = [
        _t("combat_report_title", "═══ Combat report ═══"),
        _t(
            "combat_report_coords",
            "Battlefield: %(coords)s",
            coords=target_coord_txt,
        ),
        "",
        _format_kv_section(
            _t("combat_report_section_attacker", "Attacker"),
            [
                _t("combat_report_player", "Commander: %(name)s", name=str(attacker_name or "—")),
                _t(
                    "combat_report_origin_coords",
                    "Launched from: %(coords)s",
                    coords=origin_coord_txt,
                ),
                *(
                    [
                        _t(
                            "combat_report_origin_planet",
                            "Origin planet: %(name)s",
                            name=origin_planet_txt,
                        )
                    ]
                    if origin_planet_txt
                    else []
                ),
                *_format_stock_lines(
                    attacking_ships,
                    tr_fn=_t,
                    fmt_int=fmt_int,
                    empty_key="combat_report_fleet_empty",
                    empty_default="No attacking ships",
                    locale=loc,
                ),
                *(
                    [
                        _t("combat_report_section_attacking_troops", "Embarked ground troops"),
                        *_format_stock_lines(
                            atk_troops,
                            tr_fn=_t,
                            fmt_int=fmt_int,
                            empty_key="combat_report_troops_empty",
                            empty_default="No troops",
                            locale=loc,
                        ),
                    ]
                    if atk_troops
                    else []
                ),
            ],
        ),
        "",
        _format_kv_section(
            _t("combat_report_section_defender", "Defender"),
            [
                _t("combat_report_player", "Commander: %(name)s", name=str(defender_name or "—")),
                _t(
                    "combat_report_target_coords",
                    "Target planet: %(coords)s",
                    coords=target_coord_txt,
                ),
                *(
                    [
                        _t(
                            "combat_report_target_planet",
                            "Planet name: %(name)s",
                            name=target_planet_txt,
                        )
                    ]
                    if target_planet_txt
                    else []
                ),
                *_format_stock_lines(
                    defending_ships,
                    tr_fn=_t,
                    fmt_int=fmt_int,
                    empty_key="combat_report_defense_fleet_empty",
                    empty_default="No defending fleet",
                    locale=loc,
                ),
                *_format_stock_lines(
                    def_def,
                    tr_fn=_t,
                    fmt_int=fmt_int,
                    empty_key="combat_report_defense_structures_empty",
                    empty_default="No defensive structures",
                    locale=loc,
                ),
                *(
                    [
                        _t("combat_report_section_defending_troops", "Bunker ground troops"),
                        *_format_stock_lines(
                            def_troops_in,
                            tr_fn=_t,
                            fmt_int=fmt_int,
                            empty_key="combat_report_troops_empty",
                            empty_default="No troops",
                            locale=loc,
                        ),
                    ]
                    if def_troops_in
                    else []
                ),
            ],
        ),
        "",
        _format_kv_section(
            _t("combat_report_section_research", "Combat technology"),
            [
                _t("combat_report_section_attacker", "Attacker"),
                *_format_combat_research_lines(atk_research, tr_fn=_t),
                "",
                _t("combat_report_section_defender", "Defender"),
                *(
                    _format_combat_research_lines(def_research, tr_fn=_t)
                    if def_research
                    else [
                        _t(
                            "combat_report_research_npc_na",
                            "NPC force — no account combat technology.",
                        )
                    ]
                ),
            ],
        ),
        "",
        _format_kv_section(
            _t("combat_report_section_result", "Battle outcome"),
            [
                winner_txt,
                _t(
                    "combat_report_rounds_total",
                    "Rounds fought: %(count)s",
                    count=fmt_int(len(rounds_meta)),
                ),
            ],
        ),
    ]

    for rnd in rounds_meta:
        num = int(rnd.get("number") or 0)
        body_lines.append("")
        body_lines.append(
            _format_kv_section(
                _t("combat_report_section_round", "Round %(n)s", n=fmt_int(num)),
                [
                    *_format_stock_lines(
                        rnd.get("attacker_losses") or {},
                        tr_fn=_t,
                        fmt_int=fmt_int,
                        empty_key="combat_report_round_no_attacker_losses",
                        empty_default="No attacker losses this round",
                        locale=loc,
                    ),
                    *_format_stock_lines(
                        rnd.get("defender_losses") or {},
                        tr_fn=_t,
                        fmt_int=fmt_int,
                        empty_key="combat_report_round_no_defender_losses",
                        empty_default="No defender losses this round",
                        locale=loc,
                    ),
                ],
            )
        )

    body_lines.append("")
    body_lines.append(
        _format_kv_section(
            _t("combat_report_section_losses", "Total losses"),
            [
                *_format_stock_lines(
                    atk_loss,
                    tr_fn=_t,
                    fmt_int=fmt_int,
                    empty_key="combat_report_no_attacker_losses",
                    empty_default="No attacker losses",
                    locale=loc,
                ),
                *_format_stock_lines(
                    def_loss,
                    tr_fn=_t,
                    fmt_int=fmt_int,
                    empty_key="combat_report_no_defender_losses",
                    empty_default="No defender losses",
                    locale=loc,
                ),
            ],
        )
    )
    if ret:
        body_lines.append("")
        body_lines.append(
            _format_kv_section(
                _t("combat_report_section_return", "Returning fleet"),
                _format_stock_lines(
                    ret,
                    tr_fn=_t,
                    fmt_int=fmt_int,
                    empty_key="combat_report_return_empty",
                    empty_default="No ships returning",
                    locale=loc,
                ),
            )
        )

    loot_map = dict(loot or {})
    if any(int(loot_map.get(k) or 0) > 0 for k in ("metal", "crystal", "fuel_cells")):
        body_lines.append("")
        body_lines.append(
            _format_kv_section(
                _t("combat_report_section_loot", "Plundered cargo"),
                _format_stock_lines(
                    loot_map,
                    tr_fn=_t,
                    fmt_int=fmt_int,
                    empty_key="combat_report_loot_empty",
                    empty_default="No plunder",
                    locale=loc,
                ),
            )
        )

    debris_meta = build_combat_debris_metadata(atk_loss, def_loss)
    if debris_meta:
        debris_lines = _format_stock_lines(
            {"metal": debris_meta["metal"], "crystal": debris_meta["crystal"]},
            tr_fn=_t,
            fmt_int=fmt_int,
            empty_key="combat_report_debris_empty",
            empty_default="No debris",
            locale=loc,
        )
        slots_needed = int(debris_meta.get("recycler_slots_needed") or 0)
        if slots_needed > 0:
            debris_lines.append(
                _t(
                    "combat_report_debris_recycler_needed",
                    "Recyclers needed: %(count)s",
                    count=fmt_int(slots_needed),
                )
            )
        body_lines.append("")
        body_lines.append(
            _format_kv_section(
                _t("combat_report_section_debris", "Debris field"),
                debris_lines,
            )
        )

    if vault_meta and vault_meta.get("outcome") in ("breached", "held"):
        ground = vault_meta.get("ground") or {}
        steal = vault_meta.get("steal") or {}
        outcome = str(vault_meta.get("outcome"))
        vault_lines: list[str] = []
        if outcome == "breached":
            vault_lines.append(
                _t("combat_report_vault_breached", "Vault breached — bunker opened.")
            )
            tk_s = int(steal.get("timekeeper_stolen") or 0)
            boxes = steal.get("boxes_stolen") or []
            vault_lines.append(
                _t(
                    "combat_report_vault_steal",
                    "Timekeeper stolen: %(tk)ss · Containers: %(boxes)s",
                    tk=fmt_int(tk_s),
                    boxes=", ".join(str(b) for b in boxes) if boxes else "—",
                )
            )
        else:
            vault_lines.append(
                _t("combat_report_vault_held", "Vault held — raid failed.")
            )
        if ground.get("attacker_survivors") or ground.get("attacker_losses"):
            vault_lines.append(_t("combat_report_vault_atk_survivors", "Attacker troop survivors"))
            vault_lines.extend(
                _format_stock_lines(
                    ground.get("attacker_survivors") or {},
                    tr_fn=_t,
                    fmt_int=fmt_int,
                    empty_key="combat_report_troops_empty",
                    empty_default="None",
                    locale=loc,
                )
            )
        if ground.get("defender_survivors") is not None:
            vault_lines.append(_t("combat_report_vault_def_survivors", "Defender troop survivors"))
            vault_lines.extend(
                _format_stock_lines(
                    ground.get("defender_survivors") or {},
                    tr_fn=_t,
                    fmt_int=fmt_int,
                    empty_key="combat_report_troops_empty",
                    empty_default="None",
                    locale=loc,
                )
            )
        body_lines.append("")
        body_lines.append(
            _format_kv_section(
                _t("combat_report_section_vault", "Secret Vault Raid"),
                vault_lines,
            )
        )

    metadata: Dict[str, Any] = {
        "report_version": COMBAT_REPORT_VERSION,
        "target_coords": target_coord_txt if target_coord_txt != "—" else "",
        "origin_coords": origin_coord_txt if origin_coord_txt != "—" else "",
        "origin_planet_name": origin_planet_txt,
        "target_planet_name": target_planet_txt,
        "attacker_id": int(attacker_id),
        "attacker_name": str(attacker_name or ""),
        "defender_id": int(defender_id),
        "defender_name": str(defender_name or ""),
        "attacking_ships": dict(attacking_ships),
        "defending_ships": dict(defending_ships),
        "defending_defense": dict(def_def),
        "attacking_troops": dict(atk_troops),
        "defending_troops": dict(def_troops_in),
        "vault_raid": vault_meta,
        "result": result_label,
        "winner": result_label,
        "attacker_losses": atk_loss,
        "defender_losses": def_loss,
        "return_ships": ret,
        "loot": dict(loot_map),
        "rounds_fought": len(rounds_meta),
        "rounds": rounds_meta,
        "combat_research_applicable": True,
        "defender_combat_research_na": bool(expo_pirate and not def_research),
    }
    metadata["attacker_combat_research"] = atk_research
    metadata["defender_combat_research"] = def_research
    if debris_meta:
        metadata["debris"] = dict(debris_meta)
    return "\n".join(line for line in body_lines if line is not None).strip(), metadata


def publish_attack_combat_report(
    *,
    attacker_id: int,
    defender_id: int,
    coords: str,
    attacker_name: str,
    defender_name: str,
    attacking_ships: Mapping[str, int],
    defending_ships: Mapping[str, int],
    defending_defense: Mapping[str, int] | None = None,
    combat_result: Any | None = None,
    return_ships: Mapping[str, int] | None = None,
    loot: Mapping[str, int] | None = None,
    fleet_id: int | None = None,
    origin_coords: str | None = None,
    origin_planet_name: str | None = None,
    target_planet_name: str | None = None,
    attacker_planet_id: int | None = None,
    defender_planet_id: int | None = None,
    conn=None,
    attacker_locale: str | None = None,
    defender_locale: str | None = None,
    combat_kind: str | None = None,
    defender_research_override: Mapping[str, Any] | None = None,
    extra_metadata: Mapping[str, Any] | None = None,
    attacking_troops: Mapping[str, int] | None = None,
    defending_troops: Mapping[str, int] | None = None,
    vault_raid: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build report and deliver permanent inbox messages to attacker and defender."""
    body, metadata = build_combat_report(
        attacker_id=int(attacker_id),
        attacker_name=attacker_name,
        defender_id=int(defender_id),
        defender_name=defender_name,
        coords=coords,
        attacking_ships=attacking_ships,
        defending_ships=defending_ships,
        defending_defense=defending_defense,
        combat_result=combat_result,
        return_ships=return_ships,
        loot=loot,
        origin_coords=origin_coords,
        origin_planet_name=origin_planet_name,
        target_planet_name=target_planet_name,
        attacker_planet_id=attacker_planet_id,
        defender_planet_id=defender_planet_id,
        conn=conn,
        locale=attacker_locale,
        combat_kind=combat_kind,
        defender_research_override=defender_research_override,
        attacking_troops=attacking_troops,
        defending_troops=defending_troops,
        vault_raid=vault_raid,
    )
    if fleet_id is not None:
        metadata["fleet_id"] = int(fleet_id)
    kind = str(combat_kind or "").strip().lower()
    if kind:
        metadata["combat_kind"] = kind
    if extra_metadata:
        for key, value in dict(extra_metadata).items():
            # Expedition pirate debris / NPC research — always win over auto-build defaults.
            if key in ("debris", "defender_combat_research", "defender_combat_research_na") and value is not None:
                metadata[key] = value
            elif key not in metadata or metadata.get(key) in (None, "", 0, {}):
                metadata[key] = value
    from .messages import dispatch_combat_reports

    out = dispatch_combat_reports(
        attacker_id=int(attacker_id),
        defender_id=int(defender_id),
        coords=coords,
        body=body,
        metadata=metadata,
        conn=conn,
        attacker_locale=attacker_locale,
        defender_locale=defender_locale,
    )
    out["metadata"] = dict(metadata)
    return out


def remaining_stock(
    stock: Mapping[str, int],
    losses: Mapping[str, int],
    *,
    canonical_ship_keys: bool = False,
) -> Dict[str, int]:
    """Return unit counts still alive after applying ``losses`` (read-only on inputs)."""
    from .defense_defs import is_known_defense_key
    from .fleet_defs import canonical_ship_key, is_known_ship_key

    loss_map: Dict[str, int] = {}
    for raw_key, raw_qty in losses.items():
        lost = max(0, int(raw_qty))
        if lost <= 0:
            continue
        key = str(raw_key)
        if canonical_ship_keys and is_known_ship_key(key):
            key = canonical_ship_key(key)
        elif is_known_defense_key(key):
            key = str(key).strip()
        loss_map[key] = loss_map.get(key, 0) + lost

    out: Dict[str, int] = {}
    for raw_key, raw_qty in stock.items():
        key = str(raw_key)
        if canonical_ship_keys and is_known_ship_key(key):
            key = canonical_ship_key(key)
        remain = max(0, int(raw_qty) - int(loss_map.get(key, 0)))
        if remain > 0:
            out[key] = remain
    return out


def split_defender_losses(defender_losses: Mapping[str, int]) -> Tuple[Dict[str, int], Dict[str, int]]:
    """Split combined defender losses into ship vs defense unit keys."""
    from .defense_defs import is_known_defense_key
    from .fleet_defs import canonical_ship_key, is_known_ship_key

    ship_losses: Dict[str, int] = {}
    defense_losses: Dict[str, int] = {}
    for raw_key, raw_qty in defender_losses.items():
        lost = max(0, int(raw_qty))
        if lost <= 0:
            continue
        key = str(raw_key)
        if is_known_defense_key(key):
            defense_losses[key.strip()] = lost
        elif is_known_ship_key(key):
            ship_losses[canonical_ship_key(key)] = lost
    return ship_losses, defense_losses


def defender_stacks_from_planet(
    ships: Mapping[str, int],
    defense: Mapping[str, int],
) -> List[CombatStack]:
    """Build defender combat stacks from planet hangar + ``planet_defense`` stock."""
    from .combat_models import COMBAT_UNIT_DEFENSE, COMBAT_UNIT_SHIP, stacks_from_counts

    return list(
        stacks_from_counts(ships, unit_type=COMBAT_UNIT_SHIP)
        + stacks_from_counts(defense, unit_type=COMBAT_UNIT_DEFENSE)
    )


def attacker_stacks_from_fleet(ships: Mapping[str, int]) -> List[CombatStack]:
    """Build attacker combat stacks from outbound fleet ``ships_json``."""
    from .combat_models import COMBAT_UNIT_SHIP, stacks_from_counts
    from .fleet_defs import canonical_ship_key

    normalized: Dict[str, int] = {}
    for key, qty in ships.items():
        sk = canonical_ship_key(str(key))
        normalized[sk] = normalized.get(sk, 0) + max(0, int(qty))
    return stacks_from_counts(normalized, unit_type=COMBAT_UNIT_SHIP)


def battle_rng_for_movement(movement_id: int) -> random.Random:
    """Deterministic RNG seed per fleet movement for reproducible combat."""
    return random.Random(int(movement_id))


def simulate_combat_preview_from_spy(
    *,
    player_id: int,
    spy_metadata: Mapping[str, Any],
    conn=None,
) -> Dict[str, Any]:
    """
    DEV preview: run ``simulate_battle`` from spy intel + attacker hangar (no persistence).
    """
    from .galaxy import format_coordinates, get_planet_coordinates
    from .i18n import get_player_locale
    from .fleet import get_planet_ships
    from .models import db
    from .planet_evolution.repository import get_context_planet

    own_conn = False
    if conn is None:
        conn = db()
        own_conn = True

    try:
        planet = get_context_planet(int(player_id), conn=conn)
        origin_id = int(planet["id"])
        attacking_ships = dict(get_planet_ships(origin_id, conn=conn) or {})

        coords = str(spy_metadata.get("target_coords") or "").strip()
        target_planet_id = int(spy_metadata.get("target_planet_id") or 0)
        defender_id = 0
        if target_planet_id > 0:
            cur = conn.cursor()
            cur.execute(
                "SELECT player_id FROM planets WHERE id = ? LIMIT 1;",
                (target_planet_id,),
            )
            row = cur.fetchone()
            if row:
                defender_id = int(row["player_id"] or 0)

        defending_ships = dict(spy_metadata.get("ships") or {})
        def_block = spy_metadata.get("defense") or {}
        defending_defense = dict(def_block.get("units") or def_block.get("stock") or {})

        atk_stacks = attacker_stacks_from_fleet(attacking_ships)
        def_stacks = defender_stacks_from_planet(defending_ships, defending_defense)
        sim_seed = int(target_planet_id) * 6151 + int(player_id) + 17
        combat_result = simulate_battle(
            make_combat_side("attacker", atk_stacks),
            make_combat_side("defender", def_stacks),
            rng=random.Random(sim_seed),
            attacker_player_id=int(player_id),
            defender_player_id=int(defender_id) if defender_id > 0 else None,
            attacker_planet_id=origin_id,
            defender_planet_id=target_planet_id if target_planet_id > 0 else None,
            conn=conn,
        )

        return_ships = remaining_stock(
            attacking_ships,
            combat_result.attacker_losses,
            canonical_ship_keys=True,
        )

        from .fleet import _player_name

        attacker_name = _player_name(int(player_id), conn=conn)
        defender_name = str(spy_metadata.get("target_owner") or "—")
        origin_coord_txt = ""
        try:
            pc = get_planet_coordinates(planet)
            origin_coord_txt = format_coordinates(
                int(pc["galaxy"]),
                int(pc["system"]),
                int(pc["position"]),
            )
        except Exception:
            origin_coord_txt = ""

        locale = get_player_locale(int(player_id), conn=conn)
        _body, metadata = build_combat_report(
            attacker_id=int(player_id),
            attacker_name=attacker_name,
            defender_id=int(defender_id),
            defender_name=defender_name,
            coords=coords,
            attacking_ships=attacking_ships,
            defending_ships=defending_ships,
            defending_defense=defending_defense,
            combat_result=combat_result,
            return_ships=return_ships,
            loot={},
            origin_coords=origin_coord_txt,
            origin_planet_name=str(planet.get("name") or ""),
            target_planet_name=str(spy_metadata.get("target_planet") or ""),
            attacker_planet_id=origin_id,
            defender_planet_id=target_planet_id if target_planet_id > 0 else None,
            conn=conn,
            locale=locale,
        )
        metadata["perspective"] = "attacker"
        metadata["dev_simulated"] = True
        return metadata
    finally:
        if own_conn:
            conn.close()


def simulate_ground_raid(
    attacker_troops: Mapping[str, int],
    defender_troops: Mapping[str, int],
    *,
    barracks_level: int = 0,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """
    Secret Vault Raid ground phase — second combat phase after orbital win.
    Server-authoritative; fail fantasy ≈5–10% attacker survivors.
    """
    from .troop_defs import normalize_troops, troop_power

    rng = rng or random.Random()
    atk = normalize_troops(attacker_troops)
    dfn = normalize_troops(defender_troops)
    if not atk:
        return {
            "winner": WINNER_DEFENDER,
            "attacker_survivors": {},
            "defender_survivors": dict(dfn),
            "attacker_losses": {},
            "defender_losses": {},
            "reason": "no_troops",
        }

    atk_power = float(troop_power(atk, role="attack"))
    def_power = float(troop_power(dfn, role="defense"))
    def_power *= 1.0 + 0.03 * max(0, int(barracks_level or 0))

    atk_roll = atk_power * (0.9 + 0.2 * rng.random())
    def_roll = def_power * (0.9 + 0.2 * rng.random()) if def_power > 0 else 0.0

    if def_power <= 0 or atk_roll > def_roll:
        def_survivors: Dict[str, int] = {}
        def_losses: Dict[str, int] = {}
        for k, v in dfn.items():
            keep = max(0, int(round(v * 0.05)))
            def_survivors[k] = keep
            if v - keep > 0:
                def_losses[k] = v - keep
        atk_survivors: Dict[str, int] = {}
        atk_losses: Dict[str, int] = {}
        for k, v in atk.items():
            keep = max(1 if v > 0 else 0, int(round(v * (0.55 + 0.2 * rng.random()))))
            keep = min(v, keep)
            atk_survivors[k] = keep
            if v - keep > 0:
                atk_losses[k] = v - keep
        return {
            "winner": WINNER_ATTACKER,
            "attacker_survivors": {k: v for k, v in atk_survivors.items() if v > 0},
            "defender_survivors": {k: v for k, v in def_survivors.items() if v > 0},
            "attacker_losses": atk_losses,
            "defender_losses": def_losses,
            "reason": "vault_breached",
        }

    survivor_frac = 0.05 + 0.05 * rng.random()
    atk_survivors = {}
    atk_losses = {}
    for k, v in atk.items():
        keep = max(0, int(round(v * survivor_frac)))
        if v > 0 and keep <= 0 and survivor_frac > 0:
            keep = 1 if rng.random() < 0.35 else 0
        keep = min(v, keep)
        atk_survivors[k] = keep
        if v - keep > 0:
            atk_losses[k] = v - keep
    def_survivors = {}
    def_losses = {}
    for k, v in dfn.items():
        keep = max(0, int(round(v * (0.75 + 0.15 * rng.random()))))
        keep = min(v, keep)
        def_survivors[k] = keep
        if v - keep > 0:
            def_losses[k] = v - keep
    return {
        "winner": WINNER_DEFENDER,
        "attacker_survivors": {k: v for k, v in atk_survivors.items() if v > 0},
        "defender_survivors": {k: v for k, v in def_survivors.items() if v > 0},
        "attacker_losses": atk_losses,
        "defender_losses": def_losses,
        "reason": "vault_held",
    }


# Steal / snapshot owners remain in vault_raid; re-exported for combat-facing callers.
from .vault_raid import (  # noqa: E402
    VAULT_BOX_CAP,
    VAULT_TK_CAP_SEC,
    apply_vault_steal,
    vault_snapshot,
)
