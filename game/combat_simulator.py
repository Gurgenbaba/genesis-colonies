"""Combat simulator (GC-700A) — wraps ``simulate_battle`` only; no DB side effects."""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .combat import (
    COMBAT_PLUNDER_FRACTION,
    WINNER_ATTACKER,
    WINNER_DEFENDER,
    WINNER_DRAW,
    CombatModifiers,
    attacker_stacks_from_fleet,
    calculate_combat_debris,
    combat_rounds_for_metadata,
    defender_stacks_from_planet,
    remaining_stock,
    simulate_battle,
    split_defender_losses,
    unit_build_cost_for_debris,
)
from .combat_models import make_combat_side
from .defense_defs import ACTIVE_DEFENSE_KEYS, get_defense, is_known_defense_key
from .fleet_calc import calculate_total_cargo
from .fleet_defs import ACTIVE_SHIP_KEYS, get_ship
from .resources import calculate_plunder_pool, load_resources_up_to_cargo

MAX_UNIT_COUNT = 1_000_000_000
MAX_ITERATIONS = 500
DEFAULT_PLAYER_ITERATIONS = 50
DEFAULT_ADMIN_ITERATIONS = 300
TECH_BONUS_PER_LEVEL = 0.05
# Soft cap for Monte-Carlo when fleets are huge (aggregate combat is fast; still bound CPU).
_MAX_MC_HULL_EVENTS = 2_000_000_000
_MEGA_FLEET_HULLS = 250_000
_MEGA_FLEET_MAX_ITERATIONS = 50


@dataclass
class SimulationInput:
    attacker_ships: Dict[str, int]
    defender_ships: Dict[str, int]
    defender_defense: Dict[str, int]
    attacker_modifiers: CombatModifiers
    defender_modifiers: CombatModifiers
    defender_resources: Dict[str, int]
    calculate_loot: bool
    seed: Optional[int] = None
    iterations: int = 1
    ignored_keys: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _safe_nonneg_int(value: Any, *, cap: int = MAX_UNIT_COUNT) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(int(cap), n))


def _sanitize_unit_map(
    raw: Any,
    *,
    allowed_keys: frozenset[str],
    canonical_fn=None,
) -> Tuple[Dict[str, int], List[str]]:
    if not isinstance(raw, Mapping):
        return {}, []
    out: Dict[str, int] = {}
    ignored: List[str] = []
    for raw_key, raw_qty in raw.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        if canonical_fn is not None:
            key = canonical_fn(key)
        qty = _safe_nonneg_int(raw_qty)
        if qty <= 0:
            continue
        if key not in allowed_keys:
            ignored.append(str(raw_key))
            continue
        out[key] = out.get(key, 0) + qty
    return out, ignored


def _sanitize_resource_map(raw: Any) -> Dict[str, int]:
    if not isinstance(raw, Mapping):
        return {"metal": 0, "crystal": 0, "fuel_cells": 0}
    return {
        "metal": _safe_nonneg_int(raw.get("metal")),
        "crystal": _safe_nonneg_int(raw.get("crystal")),
        "fuel_cells": _safe_nonneg_int(raw.get("fuel_cells")),
    }


def _tech_levels_to_modifiers(raw: Any) -> CombatModifiers:
    if not isinstance(raw, Mapping):
        return CombatModifiers()
    if any(k in raw for k in ("weapon_bonus", "armor_bonus", "shield_bonus")):
        return CombatModifiers(
            weapon_bonus=max(0.0, float(raw.get("weapon_bonus") or 0.0)),
            armor_bonus=max(0.0, float(raw.get("armor_bonus") or 0.0)),
            shield_bonus=max(0.0, float(raw.get("shield_bonus") or 0.0)),
        )
    weapon_lvl = _safe_nonneg_int(raw.get("weapon") or raw.get("weapon_tech"), cap=999)
    armor_lvl = _safe_nonneg_int(raw.get("armor") or raw.get("armor_tech"), cap=999)
    shield_lvl = _safe_nonneg_int(raw.get("shield") or raw.get("shield_tech"), cap=999)
    return CombatModifiers(
        weapon_bonus=weapon_lvl * TECH_BONUS_PER_LEVEL,
        armor_bonus=armor_lvl * TECH_BONUS_PER_LEVEL,
        shield_bonus=shield_lvl * TECH_BONUS_PER_LEVEL,
    )


def _loss_build_value(losses: Mapping[str, int]) -> int:
    total = 0
    for key, qty in losses.items():
        lost = max(0, int(qty))
        if lost <= 0:
            continue
        metal, crystal = unit_build_cost_for_debris(str(key))
        total += (metal + crystal) * lost
    return total


def _resource_total(stock: Mapping[str, int]) -> int:
    return sum(max(0, int(v)) for v in stock.values())


def _side_has_combat_ships(ships: Mapping[str, int]) -> bool:
    for key, qty in ships.items():
        if max(0, int(qty)) <= 0:
            continue
        spec = get_ship(str(key)) or {}
        if max(0, int(spec.get("attack") or 0)) > 0:
            return True
    return False


def _side_firepower(ships: Mapping[str, int], defense: Mapping[str, int], mods: CombatModifiers) -> int:
    from .combat import _effective_attack, _effective_hull, _effective_shield
    from .combat_models import combat_stats_for_defense, combat_stats_for_ship

    total = 0
    for key, qty in ships.items():
        q = max(0, int(qty))
        if q <= 0:
            continue
        stats = combat_stats_for_ship(str(key))
        if stats is None:
            continue
        total += _effective_attack(stats, mods) * q
    for key, qty in defense.items():
        q = max(0, int(qty))
        if q <= 0:
            continue
        stats = combat_stats_for_defense(str(key))
        if stats is None:
            continue
        total += _effective_attack(stats, mods) * q
    return total


def _side_tank(ships: Mapping[str, int], defense: Mapping[str, int], mods: CombatModifiers) -> int:
    from .combat import _effective_hull, _effective_shield
    from .combat_models import combat_stats_for_defense, combat_stats_for_ship

    total = 0
    for key, qty in ships.items():
        q = max(0, int(qty))
        if q <= 0:
            continue
        stats = combat_stats_for_ship(str(key))
        if stats is None:
            continue
        total += (_effective_hull(stats, mods) + _effective_shield(stats, mods)) * q
    for key, qty in defense.items():
        q = max(0, int(qty))
        if q <= 0:
            continue
        stats = combat_stats_for_defense(str(key))
        if stats is None:
            continue
        total += (_effective_hull(stats, mods) + _effective_shield(stats, mods)) * q
    return total


def build_simulation_input(payload: Mapping[str, Any], user_id: int) -> Tuple[Optional[SimulationInput], Optional[str], Dict[str, Any]]:
    """
    Validate and normalize simulator payload.
    Returns ``(input, error_key, field_errors)``.
    """
    from .fleet_defs import canonical_ship_key

    field_errors: Dict[str, Any] = {}
    ignored: List[str] = []

    atk_ships, atk_ignored = _sanitize_unit_map(
        payload.get("attacker_ships") or payload.get("attacker") or {},
        allowed_keys=ACTIVE_SHIP_KEYS,
        canonical_fn=canonical_ship_key,
    )
    def_ships, def_ship_ignored = _sanitize_unit_map(
        payload.get("defender_ships") or payload.get("defender") or {},
        allowed_keys=ACTIVE_SHIP_KEYS,
        canonical_fn=canonical_ship_key,
    )
    def_defense, def_def_ignored = _sanitize_unit_map(
        payload.get("defender_defense") or payload.get("defense") or {},
        allowed_keys=ACTIVE_DEFENSE_KEYS,
    )
    ignored.extend(atk_ignored + def_ship_ignored + def_def_ignored)

    strict = bool(payload.get("strict_keys"))
    if strict and ignored:
        field_errors["units"] = ignored
        return None, "unknown_unit_keys", field_errors

    try:
        iterations = int(payload.get("iterations") or 1)
    except (TypeError, ValueError):
        iterations = 1
    iterations = max(1, min(MAX_ITERATIONS, iterations))

    seed_raw = payload.get("seed")
    seed: Optional[int] = None
    if seed_raw not in (None, ""):
        try:
            seed = int(seed_raw)
        except (TypeError, ValueError):
            field_errors["seed"] = "invalid"
            return None, "invalid_seed", field_errors

    calculate_loot = payload.get("calculate_loot", True)
    if calculate_loot in (0, "0", False, "false"):
        calculate_loot = False
    else:
        calculate_loot = bool(calculate_loot)

    sim_input = SimulationInput(
        attacker_ships=atk_ships,
        defender_ships=def_ships,
        defender_defense=def_defense,
        attacker_modifiers=_tech_levels_to_modifiers(payload.get("attacker_tech") or {}),
        defender_modifiers=_tech_levels_to_modifiers(payload.get("defender_tech") or {}),
        defender_resources=_sanitize_resource_map(payload.get("defender_resources") or payload.get("resources") or {}),
        calculate_loot=calculate_loot,
        seed=seed,
        iterations=iterations,
        ignored_keys=sorted(set(ignored)),
    )

    if not atk_ships and not def_ships and not def_defense:
        return None, "empty_battle", field_errors

    warnings = list(sim_input.warnings)
    if ignored:
        warnings.append("unknown_unit_keys_ignored")
    if not _side_has_combat_ships(atk_ships):
        warnings.append("no_attacker_combat_ships")
    if not _side_has_combat_ships(def_ships) and not def_defense:
        warnings.append("no_defender_combat_units")

    atk_fp = _side_firepower(atk_ships, {}, sim_input.attacker_modifiers)
    def_tank = _side_tank(def_ships, def_defense, sim_input.defender_modifiers)
    if def_tank > 0 and atk_fp > 0 and def_tank >= atk_fp * 8:
        warnings.append("shield_wall_risk")
    if atk_fp > 0 and def_tank > 0 and atk_fp >= def_tank * 12:
        warnings.append("overkill_risk")

    sim_input.warnings = warnings
    _ = user_id  # reserved for future player-scoped presets; simulator never reads live enemy data
    return sim_input, None, field_errors


def _preview_loot(
    *,
    winner: str,
    attacker_ships: Mapping[str, int],
    attacker_losses: Mapping[str, int],
    defender_resources: Mapping[str, int],
) -> Tuple[Dict[str, int], Dict[str, int], int]:
    pool = calculate_plunder_pool(defender_resources, plunder_fraction=COMBAT_PLUNDER_FRACTION)
    if winner != WINNER_ATTACKER:
        return {k: 0 for k in pool}, pool, 0
    return_ships = remaining_stock(attacker_ships, attacker_losses, canonical_ship_keys=True)
    cargo_cap = calculate_total_cargo(return_ships)
    loot = load_resources_up_to_cargo(pool, cargo_cap)
    return loot, pool, cargo_cap


def _run_single(sim: SimulationInput, rng: random.Random) -> Dict[str, Any]:
    atk_stacks = attacker_stacks_from_fleet(sim.attacker_ships)
    def_stacks = defender_stacks_from_planet(sim.defender_ships, sim.defender_defense)
    combat_result = simulate_battle(
        make_combat_side(WINNER_ATTACKER, atk_stacks),
        make_combat_side(WINNER_DEFENDER, def_stacks),
        rng=rng,
        attacker_modifiers=sim.attacker_modifiers,
        defender_modifiers=sim.defender_modifiers,
    )
    def_ship_losses, def_defense_losses = split_defender_losses(combat_result.defender_losses)
    debris_metal, debris_crystal = calculate_combat_debris(
        combat_result.attacker_losses,
        combat_result.defender_losses,
    )
    loot = {"metal": 0, "crystal": 0, "fuel_cells": 0}
    plunder_pool = {"metal": 0, "crystal": 0, "fuel_cells": 0}
    cargo_cap = 0
    if sim.calculate_loot:
        loot, plunder_pool, cargo_cap = _preview_loot(
            winner=combat_result.winner,
            attacker_ships=sim.attacker_ships,
            attacker_losses=combat_result.attacker_losses,
            defender_resources=sim.defender_resources,
        )

    atk_loss_value = _loss_build_value(combat_result.attacker_losses)
    loot_value = _resource_total(loot)
    net_value = loot_value - atk_loss_value

    return {
        "winner": combat_result.winner,
        "attacker_losses": dict(combat_result.attacker_losses),
        "defender_losses": dict(combat_result.defender_losses),
        "defender_ship_losses": dict(def_ship_losses),
        "defender_defense_losses": dict(def_defense_losses),
        "debris": {"metal": debris_metal, "crystal": debris_crystal},
        "loot": dict(loot),
        "plunder_pool": dict(plunder_pool),
        "cargo_cap": cargo_cap,
        "rounds": combat_rounds_for_metadata(combat_result),
        "net_value": net_value,
        "attacker_loss_value": atk_loss_value,
        "loot_value": loot_value,
    }


def run_combat_simulation(payload: Mapping[str, Any], user_id: int) -> Dict[str, Any]:
    sim, err, field_errors = build_simulation_input(payload, user_id)
    if err or sim is None:
        out: Dict[str, Any] = {"ok": False, "error": err or "invalid_input"}
        if field_errors:
            out["field_errors"] = field_errors
        return out

    rng = random.Random(sim.seed) if sim.seed is not None else random.Random()
    run = _run_single(sim, rng)
    warnings = list(sim.warnings)
    if sim.calculate_loot and run["cargo_cap"] <= 0 and _resource_total(sim.defender_resources) > 0:
        warnings.append("no_cargo_capacity")
    if (
        run["winner"] == WINNER_ATTACKER
        and sim.calculate_loot
        and _resource_total(run["plunder_pool"]) > _resource_total(run["loot"])
    ):
        warnings.append("cannot_loot_all_resources")
    if run["winner"] == WINNER_DRAW:
        warnings.append("draw_outcome")

    return {
        "ok": True,
        "result": _attach_display(
            {
                "mode": "single",
                "iterations": 1,
                "warnings": sorted(set(warnings)),
                "ignored_keys": list(sim.ignored_keys),
                "summary": summarize_simulation_results([run]),
                "sample_battle": run,
            },
            sim,
        ),
    }


def run_monte_carlo_simulation(
    payload: Mapping[str, Any],
    user_id: int,
    iterations: int = 100,
) -> Dict[str, Any]:
    merged = dict(payload)
    merged["iterations"] = iterations
    sim, err, field_errors = build_simulation_input(merged, user_id)
    if err or sim is None:
        out: Dict[str, Any] = {"ok": False, "error": err or "invalid_input"}
        if field_errors:
            out["field_errors"] = field_errors
        return out

    hulls = (
        sum(max(0, int(v)) for v in sim.attacker_ships.values())
        + sum(max(0, int(v)) for v in sim.defender_ships.values())
        + sum(max(0, int(v)) for v in sim.defender_defense.values())
    )
    # Bound worst-case CPU if someone asks for 500 iters of billion-scale fleets.
    if hulls > 0:
        # Six rounds × two sides ≈ 12 firing waves; keep product under budget.
        budget_iters = max(1, int(_MAX_MC_HULL_EVENTS // max(1, hulls * 12)))
        if budget_iters < sim.iterations:
            sim.iterations = budget_iters
            sim.warnings = list(sim.warnings) + ["iterations_clamped_for_fleet_size"]
        # Mega fleets: keep Battle Lab responsive (~seconds, not minutes).
        if hulls >= _MEGA_FLEET_HULLS and sim.iterations > _MEGA_FLEET_MAX_ITERATIONS:
            sim.iterations = _MEGA_FLEET_MAX_ITERATIONS
            sim.warnings = list(sim.warnings) + ["iterations_clamped_for_fleet_size"]

    base_seed = sim.seed if sim.seed is not None else random.randrange(1, 2_000_000_000)
    runs: List[Dict[str, Any]] = []
    for i in range(sim.iterations):
        runs.append(_run_single(sim, random.Random(base_seed + i * 9973)))

    summary = summarize_simulation_results(runs)
    warnings = list(sim.warnings)
    draw_rate = float(summary["winner_probabilities"].get("draw") or 0.0)
    if draw_rate >= 0.15:
        warnings.append("draw_risk")
    if sim.calculate_loot:
        no_cargo = sum(1 for r in runs if int(r.get("cargo_cap") or 0) <= 0)
        if no_cargo >= sim.iterations * 0.5 and _resource_total(sim.defender_resources) > 0:
            warnings.append("no_cargo_capacity")
        partial_loot = sum(
            1
            for r in runs
            if r.get("winner") == WINNER_ATTACKER
            and _resource_total(r.get("plunder_pool") or {}) > _resource_total(r.get("loot") or {})
        )
        if partial_loot >= max(1, sim.iterations // 4):
            warnings.append("cannot_loot_all_resources")

    sample_idx = summary.get("median_index", 0)
    sample_battle = runs[sample_idx] if runs else {}

    return {
        "ok": True,
        "result": _attach_display(
            {
                "mode": "monte_carlo",
                "iterations": sim.iterations,
                "iterations_requested": int(iterations),
                "seed": base_seed,
                "warnings": sorted(set(warnings)),
                "ignored_keys": list(sim.ignored_keys),
                "summary": summary,
                "sample_battle": sample_battle,
            },
            sim,
        ),
    }


def summarize_simulation_results(results: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    if not results:
        return {
            "winner_probabilities": {"attacker": 0.0, "defender": 0.0, "draw": 0.0},
            "average_attacker_losses": {},
            "average_defender_ship_losses": {},
            "average_defender_defense_losses": {},
            "average_debris": {"metal": 0, "crystal": 0},
            "average_loot": {"metal": 0, "crystal": 0, "fuel_cells": 0},
            "best": None,
            "worst": None,
            "median": None,
            "median_index": 0,
        }

    n = len(results)
    win_counts = {WINNER_ATTACKER: 0, WINNER_DEFENDER: 0, WINNER_DRAW: 0}
    atk_loss_acc: Dict[str, float] = {}
    def_ship_acc: Dict[str, float] = {}
    def_def_acc: Dict[str, float] = {}
    debris_m = debris_c = 0.0
    loot_m = loot_c = loot_f = 0.0

    for run in results:
        winner = str(run.get("winner") or WINNER_DRAW)
        win_counts[winner if winner in win_counts else WINNER_DRAW] += 1
        for key, qty in (run.get("attacker_losses") or {}).items():
            atk_loss_acc[key] = atk_loss_acc.get(key, 0.0) + max(0, int(qty))
        for key, qty in (run.get("defender_ship_losses") or {}).items():
            def_ship_acc[key] = def_ship_acc.get(key, 0.0) + max(0, int(qty))
        for key, qty in (run.get("defender_defense_losses") or {}).items():
            def_def_acc[key] = def_def_acc.get(key, 0.0) + max(0, int(qty))
        debris = run.get("debris") or {}
        debris_m += float(debris.get("metal") or 0)
        debris_c += float(debris.get("crystal") or 0)
        loot = run.get("loot") or {}
        loot_m += float(loot.get("metal") or 0)
        loot_c += float(loot.get("crystal") or 0)
        loot_f += float(loot.get("fuel_cells") or 0)

    def _avg(acc: Dict[str, float]) -> Dict[str, int]:
        return {k: int(round(v / n)) for k, v in sorted(acc.items()) if v > 0}

    net_values = [int(r.get("net_value") or 0) for r in results]
    sorted_runs = sorted(enumerate(results), key=lambda x: int(x[1].get("net_value") or 0))
    best_idx, best_run = sorted_runs[-1]
    worst_idx, worst_run = sorted_runs[0]
    median_val = statistics.median(net_values)
    median_idx = min(range(n), key=lambda i: abs(net_values[i] - median_val))

    atk_loss_value_sum = loot_value_sum = cargo_cap_sum = 0.0
    cargo_fill_samples: List[float] = []
    for run in results:
        atk_loss_value_sum += float(run.get("attacker_loss_value") or 0)
        loot_value_sum += float(run.get("loot_value") or 0)
        cargo_cap_sum += float(run.get("cargo_cap") or 0)
        if str(run.get("winner") or "") == WINNER_ATTACKER:
            pool_total = _resource_total(run.get("plunder_pool") or {})
            loot_total = _resource_total(run.get("loot") or {})
            if pool_total > 0:
                cargo_fill_samples.append(min(1.0, loot_total / pool_total))

    cargo_fill_pct: Optional[int] = None
    if cargo_fill_samples:
        cargo_fill_pct = int(round(statistics.mean(cargo_fill_samples) * 100))

    return {
        "winner_probabilities": {
            WINNER_ATTACKER: round(win_counts[WINNER_ATTACKER] / n, 4),
            WINNER_DEFENDER: round(win_counts[WINNER_DEFENDER] / n, 4),
            WINNER_DRAW: round(win_counts[WINNER_DRAW] / n, 4),
        },
        "average_attacker_losses": _avg(atk_loss_acc),
        "average_defender_ship_losses": _avg(def_ship_acc),
        "average_defender_defense_losses": _avg(def_def_acc),
        "average_debris": {"metal": int(round(debris_m / n)), "crystal": int(round(debris_c / n))},
        "average_loot": {
            "metal": int(round(loot_m / n)),
            "crystal": int(round(loot_c / n)),
            "fuel_cells": int(round(loot_f / n)),
        },
        "best": {"index": best_idx, "net_value": int(best_run.get("net_value") or 0), "winner": best_run.get("winner")},
        "worst": {"index": worst_idx, "net_value": int(worst_run.get("net_value") or 0), "winner": worst_run.get("winner")},
        "median": {"index": median_idx, "net_value": int(net_values[median_idx]), "winner": results[median_idx].get("winner")},
        "median_index": median_idx,
        "average_economics": {
            "attacker_loss_value": int(round(atk_loss_value_sum / n)),
            "loot_value": int(round(loot_value_sum / n)),
            "net_value": int(net_values[median_idx]),
            "cargo_cap": int(round(cargo_cap_sum / n)),
            "cargo_fill_pct": cargo_fill_pct,
        },
    }


WARNING_I18N_KEYS: Dict[str, str] = {
    "unknown_unit_keys_ignored": "combat_sim_warning_unknown_units",
    "no_attacker_combat_ships": "combat_sim_warning_no_attacker_combat",
    "no_defender_combat_units": "combat_sim_warning_no_defender_combat",
    "shield_wall_risk": "combat_sim_warning_shield_wall",
    "overkill_risk": "combat_sim_warning_overkill",
    "no_cargo_capacity": "combat_sim_warning_no_cargo",
    "cannot_loot_all_resources": "combat_sim_warning_partial_loot",
    "draw_risk": "combat_sim_warning_draw_risk",
    "draw_outcome": "combat_sim_warning_draw_outcome",
    "iterations_clamped_for_fleet_size": "combat_sim_warning_iterations_clamped",
}

UNSCANNED_FIELD_LABELS: Dict[str, str] = {
    "resources": "combat_sim_field_resources",
    "fuel_cells": "combat_sim_field_fuel",
    "fleet": "combat_sim_field_fleet",
    "defense": "combat_sim_field_defense",
    "research": "combat_sim_field_research",
}


def _unit_name_key(unit_key: str, *, unit_type: str = "ship") -> str:
    if unit_type == "defense" or is_known_defense_key(str(unit_key)):
        spec = get_defense(str(unit_key)) or {}
        return str(spec.get("name_key") or f"defense_{unit_key}")
    from .fleet_defs import canonical_ship_key

    key = canonical_ship_key(str(unit_key))
    spec = get_ship(key) or {}
    return str(spec.get("name_key") or f"fleet_ship_{key}")


def _loss_rows(stock: Mapping[str, int]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for raw_key, raw_qty in sorted(stock.items()):
        qty = max(0, int(raw_qty))
        if qty <= 0:
            continue
        key = str(raw_key)
        unit_type = "defense" if is_known_defense_key(key) else "ship"
        rows.append(
            {
                "unit_key": key,
                "unit_type": unit_type,
                "name_key": _unit_name_key(key, unit_type=unit_type),
                "quantity": qty,
            }
        )
    return rows


def _attacker_is_cargo_only(sim: SimulationInput) -> bool:
    if not any(max(0, int(v)) for v in sim.attacker_ships.values()):
        return False
    return not _side_has_combat_ships(sim.attacker_ships)


def build_simulation_verdict(
    sim: SimulationInput,
    summary: Mapping[str, Any],
    warnings: Sequence[str],
) -> Dict[str, Any]:
    probs = dict(summary.get("winner_probabilities") or {})
    atk_p = float(probs.get(WINNER_ATTACKER) or 0.0)
    def_p = float(probs.get(WINNER_DEFENDER) or 0.0)
    draw_p = float(probs.get(WINNER_DRAW) or 0.0)
    reason_keys: List[str] = []
    warn_set = set(warnings or ())

    if not any(max(0, int(v)) for v in sim.attacker_ships.values()):
        reason_keys.append("reason_attacker_empty")
    elif not _side_has_combat_ships(sim.attacker_ships):
        reason_keys.append("reason_no_combat_ships")
    if _attacker_is_cargo_only(sim):
        reason_keys.append("reason_cargo_only")
    has_def_units = any(max(0, int(v)) for v in sim.defender_ships.values()) or any(
        max(0, int(v)) for v in sim.defender_defense.values()
    )
    if not has_def_units:
        reason_keys.append("reason_defender_empty")
    if "shield_wall_risk" in warn_set:
        reason_keys.append("reason_shield_wall")
    if "no_cargo_capacity" in warn_set:
        reason_keys.append("reason_no_cargo")
    if "cannot_loot_all_resources" in warn_set:
        reason_keys.append("reason_partial_loot")
    if draw_p >= 0.15 or "draw_risk" in warn_set:
        reason_keys.append("reason_draw_risk")

    if atk_p <= 0.02 and def_p <= 0.02 and draw_p >= 0.5:
        verdict_key = "combat_sim_verdict_no_fight"
    elif atk_p <= 0.02:
        verdict_key = "combat_sim_verdict_attacker_loses"
    elif atk_p >= 0.75:
        verdict_key = "combat_sim_verdict_attacker_wins"
    elif def_p >= 0.75:
        verdict_key = "combat_sim_verdict_defender_wins"
    elif draw_p >= 0.25:
        verdict_key = "combat_sim_verdict_draw_likely"
    else:
        verdict_key = "combat_sim_verdict_open"

    return {
        "verdict_key": verdict_key,
        "reason_keys": reason_keys,
        "win_chance_pct": {
            WINNER_ATTACKER: int(round(atk_p * 100)),
            WINNER_DEFENDER: int(round(def_p * 100)),
            WINNER_DRAW: int(round(draw_p * 100)),
        },
    }


def build_simulation_recommendation(
    sim: SimulationInput,
    summary: Mapping[str, Any],
    warnings: Sequence[str],
) -> Dict[str, str]:
    """Player-facing one-line recommendation for Battle Lab."""
    warn_set = set(warnings or ())
    probs = dict(summary.get("winner_probabilities") or {})
    atk_p = float(probs.get(WINNER_ATTACKER) or 0.0)
    def_p = float(probs.get(WINNER_DEFENDER) or 0.0)
    draw_p = float(probs.get(WINNER_DRAW) or 0.0)
    econ = dict(summary.get("average_economics") or {})
    net = int(econ.get("net_value") or (summary.get("median") or {}).get("net_value") or 0)

    if not any(max(0, int(v)) for v in sim.attacker_ships.values()):
        return {"key": "combat_sim_rec_no_attack_power", "tone": "negative"}
    if _attacker_is_cargo_only(sim):
        return {"key": "combat_sim_rec_cargo_only", "tone": "warning"}
    if "no_attacker_combat_ships" in warn_set:
        return {"key": "combat_sim_rec_need_combat_ships", "tone": "negative"}
    if draw_p >= 0.25 or "draw_risk" in warn_set:
        return {"key": "combat_sim_rec_draw_trap", "tone": "warning"}
    if "no_cargo_capacity" in warn_set or "cannot_loot_all_resources" in warn_set:
        return {"key": "combat_sim_rec_need_cargo", "tone": "warning"}
    if def_p >= 0.55 or atk_p <= 0.25:
        return {"key": "combat_sim_rec_too_risky", "tone": "negative"}
    if net < 0 and atk_p < 0.65:
        return {"key": "combat_sim_rec_too_risky", "tone": "negative"}
    if atk_p >= 0.55 and net >= 0:
        return {"key": "combat_sim_rec_attack_worthwhile", "tone": "positive"}
    if atk_p >= 0.45 and net >= 0 and "overkill_risk" not in warn_set:
        return {"key": "combat_sim_rec_attack_worthwhile", "tone": "positive"}
    return {"key": "combat_sim_rec_assess", "tone": "neutral"}


def build_sample_battle_timeline(sample_battle: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for rnd in sample_battle.get("rounds") or ():
        if not isinstance(rnd, Mapping):
            continue
        rows.append(
            {
                "round": int(rnd.get("number") or 0),
                "attacker_losses": _loss_rows(rnd.get("attacker_losses") or {}),
                "defender_losses": _loss_rows(rnd.get("defender_losses") or {}),
            }
        )
    return rows


def build_warning_display(
    warnings: Sequence[str],
    summary: Optional[Mapping[str, Any]] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    econ = dict((summary or {}).get("average_economics") or {})
    cargo_pct = econ.get("cargo_fill_pct")
    for key in sorted(set(warnings or ())):
        label_key = WARNING_I18N_KEYS.get(str(key), f"combat_sim_warning_{key}")
        row: Dict[str, Any] = {"key": str(key), "label_key": label_key}
        if key == "cannot_loot_all_resources" and cargo_pct is not None:
            row["label_key"] = "combat_sim_warning_partial_loot_pct"
            row["params"] = {"pct": int(cargo_pct)}
        out.append(row)
    return out


def _loss_rows_for_deployed(
    deployed: Mapping[str, int],
    expected_losses: Mapping[str, int],
    *,
    side: str,
) -> List[Dict[str, Any]]:
    """Per-unit loss table for all deployed units (including zero losses)."""
    rows: List[Dict[str, Any]] = []
    keys = sorted(set(deployed.keys()) | set(expected_losses.keys()))
    for raw_key in keys:
        deployed_qty = max(0, int(deployed.get(raw_key) or 0))
        if deployed_qty <= 0:
            continue
        lost = max(0, int(expected_losses.get(raw_key) or 0))
        key = str(raw_key)
        unit_type = "defense" if is_known_defense_key(key) else "ship"
        if side == "attacker":
            severity = "none" if lost <= 0 else ("low" if lost / deployed_qty <= 0.05 else ("medium" if lost / deployed_qty <= 0.25 else "high"))
        else:
            ratio = lost / deployed_qty if deployed_qty else 0.0
            severity = "none" if lost <= 0 else ("low" if ratio < 0.25 else ("medium" if ratio < 0.75 else "high"))
        rows.append(
            {
                "unit_key": key,
                "unit_type": unit_type,
                "name_key": _unit_name_key(key, unit_type=unit_type),
                "deployed": deployed_qty,
                "quantity": lost,
                "severity": severity,
            }
        )
    return rows


def _defender_deployed(sim: SimulationInput) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for src in (sim.defender_ships, sim.defender_defense):
        for key, qty in src.items():
            q = max(0, int(qty))
            if q > 0:
                out[str(key)] = out.get(str(key), 0) + q
    return out


def _loss_value_for_map(losses: Mapping[str, int]) -> int:
    return _loss_build_value(losses)


def _estimate_win_probability(sim: SimulationInput, *, iterations: int = 20, seed: int = 9001) -> float:
    wins = 0
    for i in range(max(1, iterations)):
        run = _run_single(sim, random.Random(seed + i * 9973))
        if str(run.get("winner") or "") == WINNER_ATTACKER:
            wins += 1
    return wins / max(1, iterations)


def _dominant_attacker_combat_ship(sim: SimulationInput) -> Optional[str]:
    from .combat_models import combat_stats_for_ship

    best_key: Optional[str] = None
    best_score = 0
    for key, qty in sim.attacker_ships.items():
        q = max(0, int(qty))
        if q <= 0:
            continue
        stats = combat_stats_for_ship(str(key))
        if stats is None or int(getattr(stats, "attack", 0) or 0) <= 0:
            continue
        score = int(getattr(stats, "attack", 0) or 0) * q
        if score > best_score:
            best_score = score
            best_key = str(key)
    return best_key


def _dominant_cargo_ship(sim: SimulationInput) -> Optional[str]:
    best_key: Optional[str] = None
    best_qty = 0
    for key, qty in sim.attacker_ships.items():
        q = max(0, int(qty))
        if q <= 0:
            continue
        spec = get_ship(str(key)) or {}
        if max(0, int(spec.get("cargo") or 0)) <= 0:
            continue
        if q > best_qty:
            best_qty = q
            best_key = str(key)
    return best_key


def _sim_with_attacker_ships(sim: SimulationInput, ships: Mapping[str, int]) -> SimulationInput:
    return SimulationInput(
        attacker_ships=dict(ships),
        defender_ships=dict(sim.defender_ships),
        defender_defense=dict(sim.defender_defense),
        attacker_modifiers=sim.attacker_modifiers,
        defender_modifiers=sim.defender_modifiers,
        defender_resources=dict(sim.defender_resources),
        calculate_loot=sim.calculate_loot,
        seed=sim.seed,
        iterations=sim.iterations,
        ignored_keys=list(sim.ignored_keys),
        warnings=list(sim.warnings),
    )


def _minimum_winning_ship_count(
    sim: SimulationInput,
    ship_key: str,
    *,
    target: float = 0.95,
    iterations: int = 18,
) -> Optional[int]:
    original = max(0, int(sim.attacker_ships.get(ship_key) or 0))
    if original < 2:
        return None
    lo, hi = 1, original
    best: Optional[int] = None
    while lo <= hi:
        mid = (lo + hi) // 2
        ships = dict(sim.attacker_ships)
        ships[ship_key] = mid
        probe = _sim_with_attacker_ships(sim, ships)
        if _estimate_win_probability(probe, iterations=iterations, seed=7711 + mid) >= target:
            best = mid
            hi = mid - 1
        else:
            lo = mid + 1
    if best is not None and best < original:
        return best
    return None


def build_outcome_banner(verdict: Mapping[str, Any]) -> Dict[str, Any]:
    probs = dict(verdict.get("win_chance_pct") or {})
    atk = int(probs.get(WINNER_ATTACKER) or 0)
    def_p = int(probs.get(WINNER_DEFENDER) or 0)
    draw = int(probs.get(WINNER_DRAW) or 0)
    key = str(verdict.get("verdict_key") or "combat_sim_verdict_open")
    if atk >= def_p and atk >= draw and atk >= 50:
        banner_key = "battle_lab_banner_attacker_wins"
    elif def_p >= atk and def_p >= draw and def_p >= 50:
        banner_key = "battle_lab_banner_defender_wins"
    elif draw >= max(atk, def_p) and draw >= 25:
        banner_key = "battle_lab_banner_draw"
    else:
        banner_key = "battle_lab_banner_open"
    primary_pct = max(atk, def_p, draw)
    if atk >= def_p and atk >= draw:
        primary_pct = atk
    elif def_p >= draw:
        primary_pct = def_p
    else:
        primary_pct = draw
    return {"banner_key": banner_key, "primary_win_pct": primary_pct, "attacker_win_pct": atk}


def build_outcome_meter(
    summary: Mapping[str, Any],
    verdict: Mapping[str, Any],
    recommendation: Mapping[str, Any],
) -> Dict[str, Any]:
    probs = dict(summary.get("winner_probabilities") or {})
    atk_p = float(probs.get(WINNER_ATTACKER) or 0.0)
    econ = dict(summary.get("average_economics") or {})
    net = int(econ.get("net_value") or 0)
    atk_loss_val = int(econ.get("attacker_loss_value") or 0)
    score = int(round(atk_p * 65 + min(25, max(0, net) / 4000) - min(25, atk_loss_val / 4000)))
    score = max(0, min(100, score))
    tone = str(recommendation.get("tone") or "neutral")
    if score >= 78 and net >= 0 and tone == "positive":
        label_key = "battle_lab_meter_excellent"
        tone = "positive"
    elif score >= 55 and net >= 0:
        label_key = "battle_lab_meter_good"
        tone = "positive" if net > 0 else "neutral"
    elif score >= 35:
        label_key = "battle_lab_meter_risky"
        tone = "warning"
    else:
        label_key = "battle_lab_meter_bad"
        tone = "negative"
    return {
        "score": score,
        "label_key": label_key,
        "tone": tone,
        "net_value": net,
    }


def build_analysis_bullets(
    sim: SimulationInput,
    summary: Mapping[str, Any],
    warnings: Sequence[str],
    recommendation: Mapping[str, Any],
    atk_loss_rows: Sequence[Mapping[str, Any]],
    def_loss_rows: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    warn_set = set(warnings or ())
    econ = dict(summary.get("average_economics") or {})
    cargo_pct = econ.get("cargo_fill_pct")
    bullets: List[Dict[str, Any]] = []

    rec_key = str(recommendation.get("key") or "combat_sim_rec_assess")
    bullets.append({"key": rec_key, "icon": "check", "tone": recommendation.get("tone", "neutral")})

    own_lost = sum(max(0, int(r.get("quantity") or 0)) for r in atk_loss_rows)
    if own_lost <= 0:
        bullets.append({"key": "battle_lab_bullet_no_own_losses", "icon": "check", "tone": "positive"})
    else:
        top = max(atk_loss_rows, key=lambda r: int(r.get("quantity") or 0), default=None)
        if top and int(top.get("quantity") or 0) > 0:
            bullets.append(
                {
                    "key": "battle_lab_bullet_own_losses",
                    "icon": "warn",
                    "tone": "warning",
                    "params": {
                        "qty": int(top.get("quantity") or 0),
                        "unit_key": str(top.get("unit_key") or ""),
                        "unit_name_key": str(top.get("name_key") or ""),
                    },
                }
            )

    def_lost = sum(max(0, int(r.get("quantity") or 0)) for r in def_loss_rows)
    if def_lost > 0:
        top_def = max(def_loss_rows, key=lambda r: int(r.get("quantity") or 0), default=None)
        if top_def and int(top_def.get("quantity") or 0) > 0:
            bullets.append(
                {
                    "key": "battle_lab_bullet_enemy_loses",
                    "icon": "check",
                    "tone": "positive",
                    "params": {
                        "qty": int(top_def.get("quantity") or 0),
                        "unit_key": str(top_def.get("unit_key") or ""),
                        "unit_name_key": str(top_def.get("name_key") or ""),
                    },
                }
            )
    else:
        bullets.append({"key": "battle_lab_bullet_enemy_no_losses", "icon": "warn", "tone": "warning"})

    if "shield_wall_risk" in warn_set:
        bullets.append({"key": "battle_lab_bullet_shield_wall", "icon": "warn", "tone": "warning"})
    else:
        bullets.append({"key": "battle_lab_bullet_no_shield_wall", "icon": "check", "tone": "positive"})

    if "cannot_loot_all_resources" in warn_set and cargo_pct is not None:
        bullets.append(
            {
                "key": "battle_lab_bullet_loot_partial",
                "icon": "warn",
                "tone": "warning",
                "params": {"pct": int(cargo_pct)},
            }
        )
    elif "no_cargo_capacity" in warn_set:
        bullets.append({"key": "battle_lab_bullet_no_cargo", "icon": "warn", "tone": "warning"})
    else:
        bullets.append({"key": "battle_lab_bullet_loot_full", "icon": "check", "tone": "positive"})

    return bullets


def build_battle_advice(
    sim: SimulationInput,
    summary: Mapping[str, Any],
    warnings: Sequence[str],
) -> List[Dict[str, Any]]:
    """Strategic tips — optional quick probe sims when flags match."""
    warn_set = set(warnings or ())
    advice: List[Dict[str, Any]] = []
    probs = dict(summary.get("winner_probabilities") or {})
    atk_p = float(probs.get(WINNER_ATTACKER) or 0.0)
    econ = dict(summary.get("average_economics") or {})
    cargo_pct = econ.get("cargo_fill_pct")

    if "cannot_loot_all_resources" in warn_set and cargo_pct is not None and int(cargo_pct) < 100:
        pool = calculate_plunder_pool(sim.defender_resources, plunder_fraction=COMBAT_PLUNDER_FRACTION)
        pool_total = _resource_total(pool)
        cargo_cap = max(0, int(econ.get("cargo_cap") or 0))
        shortfall = max(0, pool_total - cargo_cap)
        hauler_key = _dominant_cargo_ship(sim) or "atlas_hauler"
        hauler_spec = get_ship(hauler_key) or get_ship("atlas_hauler") or {}
        hauler_cargo = max(1, int(hauler_spec.get("cargo") or 25000))
        extra = int(math.ceil(shortfall / hauler_cargo)) if shortfall > 0 else 0
        if extra > 0:
            advice.append(
                {
                    "key": "battle_lab_advice_more_haulers",
                    "params": {
                        "count": extra,
                        "pct": int(cargo_pct),
                        "unit_key": hauler_key,
                        "unit_name_key": _unit_name_key(hauler_key),
                    },
                }
            )

    if "overkill_risk" in warn_set:
        ship_key = _dominant_attacker_combat_ship(sim) or _dominant_cargo_ship(sim)
        if ship_key:
            sent = max(0, int(sim.attacker_ships.get(ship_key) or 0))
            minimum = _minimum_winning_ship_count(sim, ship_key)
            if minimum is not None and minimum < sent:
                advice.append(
                    {
                        "key": "battle_lab_advice_overkill_fleet",
                        "params": {
                            "sent": sent,
                            "enough": minimum,
                            "unit_key": ship_key,
                            "unit_name_key": _unit_name_key(ship_key),
                        },
                    }
                )

    if 0.55 <= atk_p <= 0.92 and "overkill_risk" not in warn_set:
        combat_key = _dominant_attacker_combat_ship(sim)
        if combat_key:
            add = 8
            ships = dict(sim.attacker_ships)
            ships[combat_key] = max(0, int(ships.get(combat_key) or 0)) + add
            probe = _sim_with_attacker_ships(sim, ships)
            new_p = _estimate_win_probability(probe, iterations=18, seed=8800)
            if new_p - atk_p >= 0.05:
                advice.append(
                    {
                        "key": "battle_lab_advice_add_combat",
                        "params": {
                            "count": add,
                            "from_pct": int(round(atk_p * 100)),
                            "to_pct": int(round(new_p * 100)),
                            "unit_key": combat_key,
                            "unit_name_key": _unit_name_key(combat_key),
                        },
                    }
                )

    return advice[:3]


def _role_hint_key(role: str, stats: Any, *, unit_type: str) -> str:
    if unit_type == "defense":
        atk = int(getattr(stats, "attack", 0) or 0)
        hull = int(getattr(stats, "hull", 0) or 0)
        if atk <= max(10, hull // 8) and hull >= 400:
            return "combat_values_hint_shieldwall"
        return "combat_values_hint_defense"
    r = str(role or "").lower()
    if r == "cargo":
        return "combat_values_hint_cargo"
    if r == "combat":
        return "combat_values_hint_combat"
    if r in ("spy", "scout"):
        return "combat_values_hint_probe"
    if r == "recycle":
        return "combat_values_hint_recycle"
    if r == "expedition":
        return "combat_values_hint_expedition"
    if r == "colony":
        return "combat_values_hint_colony"
    if int(getattr(stats, "attack", 0) or 0) <= 0:
        return "combat_values_hint_probe"
    return "combat_values_hint_combat"


def _rapid_fire_rows(stats: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    targets = dict(getattr(stats, "rapid_fire_targets", None) or {})
    for target_key, mult in sorted(targets.items()):
        m = max(0, int(mult))
        if m < 2:
            continue
        rows.append(
            {
                "target_key": str(target_key),
                "name_key": _unit_name_key(str(target_key), unit_type="ship"),
                "multiplier": m,
            }
        )
    return rows


def _combat_value_unit_row(
    unit_key: str,
    count: int,
    mods: CombatModifiers,
    *,
    unit_type: str,
) -> Optional[Dict[str, Any]]:
    from .combat import _effective_attack, _effective_hull, _effective_shield
    from .combat_models import combat_stats_for_defense, combat_stats_for_ship

    qty = max(0, int(count))
    key = str(unit_key)
    if unit_type == "defense":
        stats = combat_stats_for_defense(key)
        spec = get_defense(key) or {}
        role = "defense"
    else:
        stats = combat_stats_for_ship(key)
        spec = get_ship(key) or {}
        role = str(spec.get("role") or "utility")
    if stats is None:
        return None

    atk_base = int(stats.attack)
    sh_base = int(stats.shield)
    hull_base = int(stats.hull)
    atk_eff = _effective_attack(stats, mods)
    sh_eff = _effective_shield(stats, mods)
    hull_eff = _effective_hull(stats, mods)
    cargo = max(0, int(spec.get("cargo") or 0)) if unit_type == "ship" else 0
    low_combat = atk_eff <= 0 or role in ("cargo", "spy", "scout", "recycle", "colony")

    return {
        "unit_key": key,
        "name_key": _unit_name_key(key, unit_type=unit_type),
        "unit_type": unit_type,
        "count": qty,
        "attack_base": atk_base,
        "attack_effective": atk_eff,
        "total_attack": atk_eff * qty,
        "shield_base": sh_base,
        "shield_effective": sh_eff,
        "total_shield": sh_eff * qty,
        "hull_base": hull_base,
        "hull_effective": hull_eff,
        "total_hull": hull_eff * qty,
        "total_tank": (sh_eff + hull_eff) * qty,
        "role": role,
        "role_hint_key": _role_hint_key(role, stats, unit_type=unit_type),
        "role_label_key": f"combat_values_role_{role}" if role else "combat_values_role_utility",
        "rapid_fire": _rapid_fire_rows(stats),
        "low_combat": low_combat,
        "cargo_capacity": cargo * qty if cargo else 0,
    }


def _build_side_combat_values(
    ships: Mapping[str, int],
    defense: Mapping[str, int],
    mods: CombatModifiers,
    *,
    include_zero: bool,
    include_defense: bool = True,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for key in sorted(ACTIVE_SHIP_KEYS):
        qty = max(0, int(ships.get(key) or 0))
        if qty <= 0 and not include_zero:
            continue
        row = _combat_value_unit_row(key, qty, mods, unit_type="ship")
        if row:
            rows.append(row)
    if include_defense:
        for key in sorted(ACTIVE_DEFENSE_KEYS):
            qty = max(0, int(defense.get(key) or 0))
            if qty <= 0 and not include_zero:
                continue
            row = _combat_value_unit_row(key, qty, mods, unit_type="defense")
            if row:
                rows.append(row)
    return rows


def _deployed_combat_values(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows if max(0, int(r.get("count") or 0)) > 0]


def build_combat_values_why(sim: SimulationInput) -> List[Dict[str, Any]]:
    bullets: List[Dict[str, Any]] = []
    atk_fp = _side_firepower(sim.attacker_ships, {}, sim.attacker_modifiers)
    def_fp = _side_firepower(sim.defender_ships, sim.defender_defense, sim.defender_modifiers)
    atk_tank = _side_tank(sim.attacker_ships, {}, sim.attacker_modifiers)
    def_tank = _side_tank(sim.defender_ships, sim.defender_defense, sim.defender_modifiers)

    if atk_fp > def_tank and def_tank > 0:
        bullets.append({"key": "combat_values_why_more_attack"})
    elif atk_fp > 0 and def_tank <= 0:
        bullets.append({"key": "combat_values_why_defender_no_tank"})
    elif atk_fp <= def_tank and atk_fp > 0:
        bullets.append({"key": "combat_values_why_defender_tougher"})

    if def_fp <= max(1, atk_fp // 10) and def_tank > atk_fp:
        bullets.append({"key": "combat_values_why_defender_low_attack"})

    cargo_units = 0
    combat_units = 0
    for key, qty in sim.attacker_ships.items():
        q = max(0, int(qty))
        if q <= 0:
            continue
        spec = get_ship(str(key)) or {}
        if str(spec.get("role") or "") == "cargo":
            cargo_units += q
        elif max(0, int(spec.get("attack") or 0)) > 0:
            combat_units += q
    if cargo_units > 0:
        bullets.append({"key": "combat_values_why_cargo_role", "params": {"count": cargo_units}})

    bullets.append({"key": "combat_values_why_shield_hull_order"})
    return bullets[:6]


def build_combat_values(sim: SimulationInput) -> Dict[str, Any]:
    from .combat_models import combat_stats_for_ship

    attacker_all = _build_side_combat_values(
        {k: max(0, int(sim.attacker_ships.get(k) or 0)) for k in ACTIVE_SHIP_KEYS},
        {},
        sim.attacker_modifiers,
        include_zero=True,
        include_defense=False,
    )
    defender_all = _build_side_combat_values(
        {k: max(0, int(sim.defender_ships.get(k) or 0)) for k in ACTIVE_SHIP_KEYS},
        {k: max(0, int(sim.defender_defense.get(k) or 0)) for k in ACTIVE_DEFENSE_KEYS},
        sim.defender_modifiers,
        include_zero=True,
        include_defense=True,
    )

    atk_fp = _side_firepower(sim.attacker_ships, {}, sim.attacker_modifiers)
    def_fp = _side_firepower(sim.defender_ships, sim.defender_defense, sim.defender_modifiers)
    atk_tank = _side_tank(sim.attacker_ships, {}, sim.attacker_modifiers)
    def_tank = _side_tank(sim.defender_ships, sim.defender_defense, sim.defender_modifiers)

    why = build_combat_values_why(sim)
    for key, qty in sim.attacker_ships.items():
        if max(0, int(qty)) <= 0:
            continue
        stats = combat_stats_for_ship(str(key))
        if stats and stats.rapid_fire_targets:
            why.append({"key": "combat_values_why_rapid_fire"})
            break
    for dkey, qty in sim.defender_defense.items():
        if max(0, int(qty)) <= 0:
            continue
        from .combat_models import combat_stats_for_defense

        dstats = combat_stats_for_defense(str(dkey))
        if dstats and dstats.rapid_fire_targets:
            why.append({"key": "combat_values_why_rapid_fire"})
            break

    return {
        "attacker": _deployed_combat_values(attacker_all),
        "defender": _deployed_combat_values(defender_all),
        "attacker_all": attacker_all,
        "defender_all": defender_all,
        "totals": {
            "attacker_attack": atk_fp,
            "defender_attack": def_fp,
            "attacker_tank": atk_tank,
            "defender_tank": def_tank,
        },
        "why": why[:6],
    }


def _loss_chip_data(rows: Sequence[Mapping[str, Any]], *, chip_id: str) -> Dict[str, Any]:
    lost_rows = [r for r in rows if max(0, int(r.get("quantity") or 0)) > 0]
    if not lost_rows:
        return {"id": chip_id, "mode": "none"}
    if len(lost_rows) == 1:
        row = lost_rows[0]
        return {
            "id": chip_id,
            "mode": "single",
            "unit_key": str(row.get("unit_key") or ""),
            "unit_type": str(row.get("unit_type") or "ship"),
            "quantity": int(row.get("quantity") or 0),
            "name_key": str(row.get("name_key") or ""),
        }
    units = sorted(
        (
            {
                "unit_key": str(r.get("unit_key") or ""),
                "unit_type": str(r.get("unit_type") or "ship"),
                "quantity": int(r.get("quantity") or 0),
                "name_key": str(r.get("name_key") or ""),
            }
            for r in lost_rows
        ),
        key=lambda u: u["quantity"],
        reverse=True,
    )
    return {"id": chip_id, "mode": "multi", "count": len(units), "units": units}


def build_compact_summary(
    headline: Mapping[str, Any],
    atk_rows: Sequence[Mapping[str, Any]],
    def_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    loot = dict(headline.get("loot") or {})
    debris = dict(headline.get("debris") or {})
    loot_m = max(0, int(loot.get("metal") or 0))
    loot_c = max(0, int(loot.get("crystal") or 0))
    loot_f = max(0, int(loot.get("fuel_cells") or 0))
    debris_m = max(0, int(debris.get("metal") or 0))
    debris_c = max(0, int(debris.get("crystal") or 0))
    net = int(headline.get("expected_profit") or 0)

    chips: List[Dict[str, Any]] = [
        _loss_chip_data(atk_rows, chip_id="own"),
        _loss_chip_data(def_rows, chip_id="enemy"),
    ]

    if loot_m + loot_c + loot_f <= 0:
        chips.append({"id": "loot", "mode": "none"})
    else:
        chips.append(
            {
                "id": "loot",
                "mode": "values",
                "metal": loot_m,
                "crystal": loot_c,
                "fuel": loot_f,
            }
        )

    if debris_m + debris_c <= 0:
        chips.append({"id": "debris", "mode": "none"})
    else:
        chips.append(
            {
                "id": "debris",
                "mode": "values",
                "metal": debris_m,
                "crystal": debris_c,
            }
        )

    net_label = f"+{net}" if net > 0 else str(net)
    chips.append({"id": "net", "mode": "value", "raw": net, "label": net_label})

    return {"chips": chips, "net_value": net}


def build_simulation_narrative(
    sim: SimulationInput,
    summary: Mapping[str, Any],
    warnings: Sequence[str],
    verdict: Mapping[str, Any],
    recommendation: Mapping[str, Any],
    atk_losses: Mapping[str, int],
    combined_def_losses: Mapping[str, int],
) -> Dict[str, Any]:
    atk_rows = _loss_rows_for_deployed(sim.attacker_ships, atk_losses, side="attacker")
    def_rows = _loss_rows_for_deployed(_defender_deployed(sim), combined_def_losses, side="defender")
    meter = build_outcome_meter(summary, verdict, recommendation)
    headline_stub = {
        "loot": summary.get("average_loot") or {},
        "debris": summary.get("average_debris") or {},
        "expected_profit": int((summary.get("average_economics") or {}).get("net_value") or (summary.get("median") or {}).get("net_value") or 0),
    }
    return {
        "banner": build_outcome_banner(verdict),
        "meter": meter,
        "compact_summary": build_compact_summary(headline_stub, atk_rows, def_rows),
        "attacker_losses": atk_rows,
        "defender_losses": def_rows,
        "attacker_loss_value": _loss_value_for_map(atk_losses),
        "defender_loss_value": _loss_value_for_map(combined_def_losses),
        "analysis": build_analysis_bullets(sim, summary, warnings, recommendation, atk_rows, def_rows),
        "advice": build_battle_advice(sim, summary, warnings),
    }


def build_simulation_display(
    sim: SimulationInput,
    summary: Mapping[str, Any],
    sample_battle: Mapping[str, Any],
    warnings: Sequence[str],
    *,
    iterations: int = 1,
) -> Dict[str, Any]:
    verdict = build_simulation_verdict(sim, summary, warnings)
    recommendation = build_simulation_recommendation(sim, summary, warnings)
    atk_losses = dict(summary.get("average_attacker_losses") or {})
    def_ship = dict(summary.get("average_defender_ship_losses") or {})
    def_def = dict(summary.get("average_defender_defense_losses") or {})
    combined_def_losses = dict(def_ship)
    for k, v in def_def.items():
        combined_def_losses[k] = combined_def_losses.get(k, 0) + max(0, int(v))

    median = dict(summary.get("median") or {})
    loot = dict(summary.get("average_loot") or {})
    debris = dict(summary.get("average_debris") or {})
    econ = dict(summary.get("average_economics") or {})

    narrative = build_simulation_narrative(
        sim, summary, warnings, verdict, recommendation, atk_losses, combined_def_losses
    )

    return {
        "verdict": verdict,
        "recommendation": recommendation,
        "narrative": narrative,
        "iterations": max(1, int(iterations)),
        "headline": {
            "attacker_win_pct": verdict["win_chance_pct"][WINNER_ATTACKER],
            "defender_win_pct": verdict["win_chance_pct"][WINNER_DEFENDER],
            "draw_pct": verdict["win_chance_pct"][WINNER_DRAW],
            "expected_profit": int(econ.get("net_value") or median.get("net_value") or 0),
            "attacker_loss_total": sum(max(0, int(v)) for v in atk_losses.values()),
            "defender_loss_total": sum(max(0, int(v)) for v in combined_def_losses.values()),
            "attacker_loss_value": int(econ.get("attacker_loss_value") or 0),
            "loot_value": int(econ.get("loot_value") or 0),
            "cargo_cap": int(econ.get("cargo_cap") or 0),
            "cargo_fill_pct": econ.get("cargo_fill_pct"),
            "loot": loot,
            "debris": debris,
        },
        "average_losses": {
            "attacker": _loss_rows(atk_losses),
            "defender_ships": _loss_rows(def_ship),
            "defender_defense": _loss_rows(def_def),
            "defender_combined": _loss_rows(combined_def_losses),
        },
        "sample_timeline": build_sample_battle_timeline(sample_battle),
        "sample_winner": str(sample_battle.get("winner") or ""),
        "warnings": build_warning_display(warnings, summary),
        "combat_values": build_combat_values(sim),
    }


def _attach_display(result: Dict[str, Any], sim: SimulationInput) -> Dict[str, Any]:
    iterations = max(1, int(result.get("iterations") or 1))
    result["display"] = build_simulation_display(
        sim,
        result.get("summary") or {},
        result.get("sample_battle") or {},
        result.get("warnings") or (),
        iterations=iterations,
    )
    return result


def build_unit_catalog() -> Dict[str, Any]:
    """Ship/defense rows for UI — stats from canonical registries only."""
    from .combat_models import combat_stats_for_defense, combat_stats_for_ship

    ships = []
    for key in sorted(ACTIVE_SHIP_KEYS):
        spec = get_ship(key) or {}
        stats = combat_stats_for_ship(key)
        ships.append(
            {
                "key": key,
                "name_key": spec.get("name_key") or f"fleet_ship_{key}",
                "attack": int(getattr(stats, "attack", 0) or 0),
                "shield": int(getattr(stats, "shield", 0) or 0),
                "hull": int(getattr(stats, "hull", 0) or 0),
                "cargo": int(spec.get("cargo") or 0),
                "build_cost": dict(spec.get("build_cost") or {}),
            }
        )
    defenses = []
    for key in sorted(ACTIVE_DEFENSE_KEYS):
        spec = get_defense(key) or {}
        stats = combat_stats_for_defense(key)
        defenses.append(
            {
                "key": key,
                "name_key": spec.get("name_key") or f"defense_{key}",
                "attack": int(getattr(stats, "attack", 0) or 0),
                "shield": int(getattr(stats, "shield", 0) or 0),
                "hull": int(getattr(stats, "hull", 0) or 0),
                "build_cost": dict(spec.get("build_cost") or {}),
            }
        )
    return {"ships": ships, "defenses": defenses}


def build_unit_efficiency_table() -> List[Dict[str, Any]]:
    """Admin balancing — damage/hull/cost metrics from registries."""
    rows: List[Dict[str, Any]] = []
    catalog = build_unit_catalog()
    for group, unit_type in (("ships", "ship"), ("defenses", "defense")):
        for unit in catalog.get(group) or []:
            cost = unit.get("build_cost") or {}
            cost_val = max(1, int(cost.get("metal") or 0) + int(cost.get("crystal") or 0))
            attack = max(0, int(unit.get("attack") or 0))
            hull = max(0, int(unit.get("hull") or 0))
            rows.append(
                {
                    "key": unit["key"],
                    "unit_type": unit_type,
                    "attack": attack,
                    "hull": hull,
                    "shield": max(0, int(unit.get("shield") or 0)),
                    "cost": cost_val,
                    "damage_per_cost": round(attack / cost_val, 6),
                    "hull_per_cost": round(hull / cost_val, 6),
                    "loss_value": cost_val,
                }
            )
    return rows


def build_combat_simulator_defaults(
    player_id: int,
    *,
    conn=None,
) -> Dict[str, Any]:
    """Attacker auto-fill from context planet + account research (no live enemy data)."""
    from .fleet import get_planet_ships
    from .galaxy import format_coordinates, get_planet_coordinates
    from .models import get_research_levels
    from .planet_evolution.repository import get_context_planet

    user_id = int(player_id)
    planet = get_context_planet(user_id, conn=conn)
    pid = int(planet["id"])
    research = get_research_levels(user_id, conn=conn)
    coords = get_planet_coordinates(planet)
    attacker_tech = {
        "weapon_tech": max(0, int(research.get("weapon_tech") or 0)),
        "armor_tech": max(0, int(research.get("armor_tech") or 0)),
        "shield_tech": max(0, int(research.get("shield_tech") or 0)),
    }
    return {
        "context_planet": {
            "id": pid,
            "name": str(planet.get("name") or ""),
            "coords": format_coordinates(
                int(coords.get("galaxy") or 1),
                int(coords.get("system") or 1),
                int(coords.get("position") or 1),
            ),
        },
        "attacker_ships": dict(get_planet_ships(pid, conn=conn) or {}),
        "attacker_tech": attacker_tech,
    }


def _parse_message_metadata(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    try:
        import json

        parsed = json.loads(str(raw))
        return dict(parsed) if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def list_combat_simulator_spy_reports(
    player_id: int,
    *,
    limit: int = 30,
    conn=None,
) -> Dict[str, Any]:
    """Recent espionage inbox rows for the logged-in player only."""
    from .messages import _not_deleted_sql

    own_conn = conn is None
    if own_conn:
        from .models import db

        conn = db()
    reports: List[Dict[str, Any]] = []
    try:
        lim = max(1, min(int(limit or 30), 100))
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT id, subject, created_at, metadata_json
            FROM player_messages
            WHERE recipient_player_id = ?
              AND category = 'espionage'
              AND {_not_deleted_sql()}
            ORDER BY created_at DESC, id DESC
            LIMIT ?;
            """,
            (int(player_id), lim),
        )
        for row in cur.fetchall():
            data = dict(row)
            meta = _parse_message_metadata(data.get("metadata_json"))
            tiers = dict(meta.get("intel_tiers") or {})
            intel_keys: List[str] = []
            for tier_key in ("fleet", "defense", "resources", "fuel", "research"):
                if tiers.get(tier_key):
                    intel_keys.append(tier_key)
            created_at = int(data.get("created_at") or 0)
            reports.append(
                {
                    "id": int(data.get("id") or 0),
                    "subject": str(data.get("subject") or ""),
                    "created_at": created_at,
                    "target_coords": str(meta.get("target_coords") or ""),
                    "target_owner": str(meta.get("target_owner") or ""),
                    "target_planet": str(meta.get("target_planet") or ""),
                    "probe_count": max(0, int(meta.get("probe_count") or 0)),
                    "intel_tier_keys": intel_keys,
                    "intel_tier_count": len(intel_keys),
                }
            )
    finally:
        if own_conn and conn is not None:
            conn.close()
    return {"reports": reports}


def parse_spy_report_metadata_for_defender(metadata: Mapping[str, Any]) -> Dict[str, Any]:
    """
    Map stored spy report metadata to defender simulator fields.
    Uses report snapshot only — never queries target planet live state.
    """
    from .fleet_defs import canonical_ship_key

    meta = dict(metadata or {})
    tiers = dict(meta.get("intel_tiers") or {})
    scanned_fields: Dict[str, bool] = {}
    unscanned_fields: List[str] = []

    defender_ships: Dict[str, int] = {}
    defender_defense: Dict[str, int] = {}
    defender_resources = {"metal": 0, "crystal": 0, "fuel_cells": 0}
    defender_tech = {"weapon_tech": 0, "armor_tech": 0, "shield_tech": 0}

    has_resources = bool(tiers.get("resources"))
    has_fuel = bool(tiers.get("fuel"))
    if has_resources or has_fuel:
        res = meta.get("resources") or {}
        if has_resources:
            defender_resources["metal"] = _safe_nonneg_int(res.get("metal"))
            defender_resources["crystal"] = _safe_nonneg_int(res.get("crystal"))
            scanned_fields["resources"] = True
        else:
            unscanned_fields.append("resources")
        if has_fuel:
            defender_resources["fuel_cells"] = _safe_nonneg_int(res.get("fuel_cells"))
            scanned_fields["fuel_cells"] = True
        else:
            unscanned_fields.append("fuel_cells")
    else:
        unscanned_fields.extend(["resources", "fuel_cells"])

    if tiers.get("fleet"):
        defender_ships, _ignored = _sanitize_unit_map(
            meta.get("ships") or {},
            allowed_keys=ACTIVE_SHIP_KEYS,
            canonical_fn=canonical_ship_key,
        )
        scanned_fields["fleet"] = True
    else:
        unscanned_fields.append("fleet")

    if tiers.get("defense"):
        defense_block = meta.get("defense") if isinstance(meta.get("defense"), Mapping) else {}
        units = defense_block.get("units") if isinstance(defense_block.get("units"), Mapping) else {}
        defender_defense, _ignored = _sanitize_unit_map(units, allowed_keys=ACTIVE_DEFENSE_KEYS)
        scanned_fields["defense"] = True
    else:
        unscanned_fields.append("defense")

    research_block = meta.get("defender_research") or meta.get("research") or {}
    if isinstance(research_block, Mapping) and tiers.get("research"):
        defender_tech = {
            "weapon_tech": _safe_nonneg_int(research_block.get("weapon_tech") or research_block.get("weapon"), cap=999),
            "armor_tech": _safe_nonneg_int(research_block.get("armor_tech") or research_block.get("armor"), cap=999),
            "shield_tech": _safe_nonneg_int(research_block.get("shield_tech") or research_block.get("shield"), cap=999),
        }
        scanned_fields["research"] = True
    else:
        unscanned_fields.append("research")

    field_known = {
        "metal": has_resources,
        "crystal": has_resources,
        "fuel_cells": has_fuel,
        "fleet": bool(tiers.get("fleet")),
        "defense": bool(tiers.get("defense")),
        "weapon_tech": bool(tiers.get("research")),
        "armor_tech": bool(tiers.get("research")),
        "shield_tech": bool(tiers.get("research")),
    }
    known_label_keys: List[str] = []
    if field_known["fleet"]:
        known_label_keys.append("combat_sim_field_fleet")
    if field_known["defense"]:
        known_label_keys.append("combat_sim_field_defense")
    if has_resources or has_fuel:
        known_label_keys.append("combat_sim_field_resources")
    if field_known["weapon_tech"]:
        known_label_keys.append("combat_sim_field_research")
    unknown_label_keys = [
        UNSCANNED_FIELD_LABELS.get(str(f), f"combat_sim_field_{f}") for f in unscanned_fields
    ]

    return {
        "defender_ships": defender_ships,
        "defender_defense": defender_defense,
        "defender_resources": defender_resources,
        "defender_tech": defender_tech,
        "scanned_fields": scanned_fields,
        "unscanned_fields": unscanned_fields,
        "field_known": field_known,
        "known_label_keys": known_label_keys,
        "unknown_label_keys": unknown_label_keys,
        "intel_tiers": tiers,
        "target": {
            "coords": str(meta.get("target_coords") or ""),
            "owner": str(meta.get("target_owner") or ""),
            "planet": str(meta.get("target_planet") or ""),
            "planet_id": max(0, int(meta.get("target_planet_id") or 0)),
        },
        "probe_count": max(0, int(meta.get("probe_count") or 0)),
        "spy_accuracy_pct": max(0, int(meta.get("spy_accuracy_pct") or 0)),
    }


def import_spy_report_for_simulator(
    player_id: int,
    message_id: int,
    *,
    conn=None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load owned espionage message metadata and map to defender payload."""
    from .messages import _not_deleted_sql

    own_conn = conn is None
    if own_conn:
        from .models import db

        conn = db()
    try:
        mid = int(message_id)
        if mid <= 0:
            return None, "invalid_message_id"
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT id, recipient_player_id, category, metadata_json, subject, created_at
            FROM player_messages
            WHERE id = ?
              AND recipient_player_id = ?
              AND {_not_deleted_sql()}
            LIMIT 1;
            """,
            (mid, int(player_id)),
        )
        row = cur.fetchone()
        if not row:
            return None, "not_found"
        category = str(row["category"] or "").strip().lower()
        if category != "espionage":
            return None, "not_espionage_report"
        meta = _parse_message_metadata(row["metadata_json"])
        if not meta:
            return None, "empty_spy_metadata"
        defender_payload = parse_spy_report_metadata_for_defender(meta)
        return {
            "message_id": mid,
            "subject": str(row["subject"] or ""),
            "created_at": int(row["created_at"] or 0),
            "defender": defender_payload,
        }, None
    finally:
        if own_conn and conn is not None:
            conn.close()


def build_combat_simulator_page_context(
    player_id: int,
    *,
    conn=None,
    is_admin: bool = False,
    spy_report_id: Optional[int] = None,
) -> Dict[str, Any]:
    """SSR context — attacker auto-fill from context planet; optional spy report import."""
    defaults = build_combat_simulator_defaults(player_id, conn=conn)
    catalog = build_unit_catalog()

    imported_bundle: Optional[Dict[str, Any]] = None
    spy_import_error: Optional[str] = None
    defender_preset: Dict[str, Any] = {
        "defender_ships": {},
        "defender_defense": {},
        "defender_tech": {"weapon_tech": 0, "armor_tech": 0, "shield_tech": 0},
        "defender_resources": {"metal": 0, "crystal": 0, "fuel_cells": 0},
    }
    active_spy_report_id: Optional[int] = None

    if spy_report_id is not None:
        try:
            mid = int(spy_report_id)
        except (TypeError, ValueError):
            mid = 0
        if mid > 0:
            imported_bundle, spy_import_error = import_spy_report_for_simulator(
                player_id, mid, conn=conn
            )
            if imported_bundle and not spy_import_error:
                active_spy_report_id = mid
                defender = dict(imported_bundle.get("defender") or {})
                defender_preset = {
                    "defender_ships": dict(defender.get("defender_ships") or {}),
                    "defender_defense": dict(defender.get("defender_defense") or {}),
                    "defender_tech": dict(
                        defender.get("defender_tech")
                        or {"weapon_tech": 0, "armor_tech": 0, "shield_tech": 0}
                    ),
                    "defender_resources": dict(
                        defender.get("defender_resources")
                        or {"metal": 0, "crystal": 0, "fuel_cells": 0}
                    ),
                    "field_known": dict(defender.get("field_known") or {}),
                    "unscanned_fields": list(defender.get("unscanned_fields") or ()),
                    "unknown_label_keys": list(defender.get("unknown_label_keys") or ()),
                    "known_label_keys": list(defender.get("known_label_keys") or ()),
                    "target": dict(defender.get("target") or {}),
                }

    ctx_planet = dict(defaults.get("context_planet") or {})
    attacker_route = _format_attacker_route_label(ctx_planet)
    defender_route = _format_defender_route_label(defender_preset.get("target") or {}, from_spy=bool(active_spy_report_id))

    return {
        "ready": True,
        "planet_id": int(ctx_planet.get("id") or 0),
        "is_admin": bool(is_admin),
        "default_iterations": DEFAULT_ADMIN_ITERATIONS if is_admin else DEFAULT_PLAYER_ITERATIONS,
        "catalog": catalog,
        "defaults": defaults,
        "auto_fill_attacker": True,
        "spy_report_id": active_spy_report_id,
        "spy_import_error": spy_import_error,
        "imported_spy": imported_bundle,
        "route_labels": {
            "attacker": attacker_route,
            "defender": defender_route,
            "from_spy": bool(active_spy_report_id),
        },
        "presets": {
            "attacker_ships": dict(defaults.get("attacker_ships") or {}),
            "defender_ships": dict(defender_preset.get("defender_ships") or {}),
            "defender_defense": dict(defender_preset.get("defender_defense") or {}),
            "attacker_tech": dict(defaults.get("attacker_tech") or {}),
            "defender_tech": dict(defender_preset.get("defender_tech") or {}),
            "defender_resources": dict(defender_preset.get("defender_resources") or {}),
            "defender_field_known": dict(defender_preset.get("field_known") or {}),
            "defender_meta": {
                "target": dict(defender_preset.get("target") or {}),
                "unscanned_fields": list(defender_preset.get("unscanned_fields") or ()),
                "unknown_label_keys": list(defender_preset.get("unknown_label_keys") or ()),
                "known_label_keys": list(defender_preset.get("known_label_keys") or ()),
            },
        },
        "unit_efficiency": build_unit_efficiency_table() if is_admin else [],
    }


def _format_attacker_route_label(context_planet: Mapping[str, Any]) -> str:
    name = str(context_planet.get("name") or "").strip()
    coords = str(context_planet.get("coords") or "").strip()
    if name and coords:
        return f"{name} [{coords}]"
    return name or coords or ""


def _format_defender_route_label(target: Mapping[str, Any], *, from_spy: bool = False) -> str:
    parts = []
    owner = str(target.get("owner") or "").strip()
    planet = str(target.get("planet") or "").strip()
    coords = str(target.get("coords") or "").strip()
    if owner:
        parts.append(owner)
    if planet:
        parts.append(planet)
    if coords:
        parts.append(f"[{coords}]")
    if parts:
        return " · ".join(parts)
    return ""


def handle_combat_simulator_run(payload: Mapping[str, Any], user_id: int, *, is_admin: bool = False) -> Dict[str, Any]:
    """Route handler entry — single or monte-carlo based on iterations."""
    try:
        iterations = int(payload.get("iterations") or 1)
    except (TypeError, ValueError):
        iterations = 1
    iterations = max(1, min(MAX_ITERATIONS, iterations))
    if not is_admin and iterations > 100:
        iterations = 100
    if iterations <= 1:
        single_payload = dict(payload)
        single_payload["iterations"] = 1
        return run_combat_simulation(single_payload, user_id)
    mc_payload = dict(payload)
    mc_payload["iterations"] = iterations
    return run_monte_carlo_simulation(mc_payload, user_id, iterations=iterations)
