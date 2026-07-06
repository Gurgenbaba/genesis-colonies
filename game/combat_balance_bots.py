"""
Live combat balance test bots — real fleet movements, no mass simulation.

Two reserved internal accounts fight each other via normal attack flow.
Owner: scenarios, ensure/reset/spawn, audit log, admin API helpers.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from game.db import db, table_exists

logger = logging.getLogger(__name__)

# Reserved bot identities (no DB flag — username + display name contract).
BOT_ALPHA_USERNAME = "gc_combat_bot_alpha"
BOT_BETA_USERNAME = "gc_combat_bot_beta"
BOT_ALPHA_DISPLAY_NAME = "Combat Bot Alpha"
BOT_BETA_DISPLAY_NAME = "Combat Bot Beta"
BOT_USERNAMES: Tuple[str, ...] = (BOT_ALPHA_USERNAME, BOT_BETA_USERNAME)
BOT_DISPLAY_NAMES: Tuple[str, ...] = (BOT_ALPHA_DISPLAY_NAME, BOT_BETA_DISPLAY_NAME)

# Isolated coordinates — adjacent slots for short but real flight times (within default galaxy_count).
BOT_GALAXY = 1
BOT_SYSTEM = 498
BOT_ALPHA_POSITION = 10
BOT_BETA_POSITION = 11

DEFAULT_COST_BUDGET = 220_000
BUDGET_MICRO = 55_000
BUDGET_LOW = 110_000
BUDGET_HIGH = 440_000
BUDGET_MEGA = 880_000
MIN_RUN_INTERVAL_SEC = 300
BOT_SCHEDULER_INTERVAL_SEC = 600
BOT_FUEL_CELLS = 50_000
BOT_INTERNAL_PASSWORD_BYTES = 32

SETTINGS_KEY_ENABLED = "combat_balance_bots_enabled"
SETTINGS_KEY_LAST_RUN = "combat_balance_bots_last_run_at"
SETTINGS_KEY_SCENARIO_INDEX = "combat_balance_bots_scenario_index"
RUNTIME_KEY_SCHEDULER_LAST = "combat_balance_bots_scheduler_last_at"

ScenarioBuilder = Callable[[int], Dict[str, int]]


@dataclass(frozen=True)
class CombatBalanceScenario:
    key: str
    label: str
    notes: str
    cost_budget: int
    attacker: str  # "alpha" | "beta"
    attacker_ships: ScenarioBuilder
    defender_ships: ScenarioBuilder
    defender_defense: ScenarioBuilder
    repeat_count: int = 1


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), separators=(",", ":"), ensure_ascii=False)


def _json_loads(raw: Any) -> Dict[str, Any]:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        parsed = json.loads(str(raw))
        return dict(parsed) if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def unit_score_cost(unit_key: str, *, kind: str = "ship") -> int:
    """Equal-cost budget unit — score_value from fleet/defense defs."""
    if kind == "defense":
        from .defense_defs import defense_score_value

        return max(1, int(defense_score_value(str(unit_key))))
    from .fleet_defs import ship_score_value

    return max(1, int(ship_score_value(str(unit_key))))


def count_for_budget(unit_key: str, budget: int, *, kind: str = "ship") -> int:
    cost = unit_score_cost(unit_key, kind=kind)
    return max(1, int(budget) // cost)


def ships_for_budget(ship_key: str, budget: int) -> Dict[str, int]:
    return {str(ship_key): count_for_budget(ship_key, budget, kind="ship")}


def defense_for_budget(defense_key: str, budget: int) -> Dict[str, int]:
    return {str(defense_key): count_for_budget(defense_key, budget, kind="defense")}


def mixed_defense_for_budget(spec: Mapping[str, float], budget: int) -> Dict[str, int]:
    """Split defense budget by weight fractions (equal-cost via score_value)."""
    weights = {str(k): max(0.0, float(v)) for k, v in spec.items()}
    total_w = sum(weights.values()) or 1.0
    out: Dict[str, int] = {}
    remaining = int(budget)
    keys = list(weights.keys())
    for idx, key in enumerate(keys):
        if idx == len(keys) - 1:
            share = remaining
        else:
            share = int(budget * (weights[key] / total_w))
            remaining -= share
        count = count_for_budget(key, max(unit_score_cost(key, kind="defense"), share), kind="defense")
        if count > 0:
            out[key] = count
    return out


def _split_hangar_defense_budget(
    ship_spec: Mapping[str, float],
    defense_spec: Mapping[str, float],
    budget: int,
) -> Tuple[Dict[str, int], Dict[str, int]]:
    half = max(1, int(budget) // 2)
    ships = mixed_ships_for_budget(ship_spec, half) if ship_spec else {}
    defense = mixed_defense_for_budget(defense_spec, budget - half) if defense_spec else {}
    return ships, defense


def _scenario(
    key: str,
    label: str,
    notes: str,
    *,
    cost_budget: int = DEFAULT_COST_BUDGET,
    attacker: str = "alpha",
    attacker_ships: ScenarioBuilder,
    defender_ships: ScenarioBuilder | None = None,
    defender_defense: ScenarioBuilder | None = None,
) -> CombatBalanceScenario:
    return CombatBalanceScenario(
        key=key,
        label=label,
        notes=notes,
        cost_budget=int(cost_budget),
        attacker=attacker,
        attacker_ships=attacker_ships,
        defender_ships=defender_ships or _empty,
        defender_defense=defender_defense or _empty,
    )


def mixed_ships_for_budget(spec: Mapping[str, float], budget: int) -> Dict[str, int]:
    """Split budget by weight fractions (must sum ~1.0)."""
    weights = {str(k): max(0.0, float(v)) for k, v in spec.items()}
    total_w = sum(weights.values()) or 1.0
    out: Dict[str, int] = {}
    remaining = int(budget)
    keys = list(weights.keys())
    for idx, key in enumerate(keys):
        if idx == len(keys) - 1:
            share = remaining
        else:
            share = int(budget * (weights[key] / total_w))
            remaining -= share
        count = count_for_budget(key, max(unit_score_cost(key), share))
        if count > 0:
            out[key] = count
    return out


def _empty(_budget: int) -> Dict[str, int]:
    return {}


def _mono_ship(ship_key: str) -> ScenarioBuilder:
    return lambda budget: ships_for_budget(ship_key, budget)


def _mono_defense(defense_key: str) -> ScenarioBuilder:
    return lambda budget: defense_for_budget(defense_key, budget)


def _weighted_ships(spec: Mapping[str, float]) -> ScenarioBuilder:
    return lambda budget: mixed_ships_for_budget(spec, budget)


def _weighted_defense(spec: Mapping[str, float]) -> ScenarioBuilder:
    return lambda budget: mixed_defense_for_budget(spec, budget)


def _defender_hangar_with_turrets(
    hangar_ship: str,
    turret_key: str,
    *,
    hangar_frac: float = 0.65,
    turret_frac: float = 0.35,
) -> Tuple[ScenarioBuilder, ScenarioBuilder]:
    """Defender budget split: hangar ships + planet turrets (equal-cost score_value)."""
    hf = max(0.05, min(0.95, float(hangar_frac)))
    tf = max(0.05, min(0.95, float(turret_frac)))
    norm = hf + tf
    hf, tf = hf / norm, tf / norm

    def ships(budget: int) -> Dict[str, int]:
        return ships_for_budget(hangar_ship, max(1, int(budget * hf)))

    def defense(budget: int) -> Dict[str, int]:
        return defense_for_budget(turret_key, max(1, int(budget * tf)))

    return ships, defense


# Combat-relevant ships for the automated matrix (equal-cost via score_value).
_MATRIX_COMBAT_SHIPS: Tuple[str, ...] = (
    "spark_drone",
    "falcon_interceptor",
    "ironclad_frigate",
    "eclipse_runner",
    "solar_skiff",
)

_MATRIX_DEFENSES: Tuple[str, ...] = (
    "slug_launcher",
    "sentinel_turret",
    "plasma_arc",
    "ion_bastion",
    "flak_array",
    "pulse_barrier",
    "orbital_shield",
)

_BUDGET_TIERS: Tuple[Tuple[str, int], ...] = (
    ("micro", BUDGET_MICRO),
    ("low", BUDGET_LOW),
    ("std", DEFAULT_COST_BUDGET),
    ("high", BUDGET_HIGH),
    ("mega", BUDGET_MEGA),
)

_DEFENDER_COUNTER_TURRET: Dict[str, str] = {
    "spark_drone": "sentinel_turret",
    "falcon_interceptor": "plasma_arc",
    "ironclad_frigate": "ion_bastion",
    "eclipse_runner": "flak_array",
    "solar_skiff": "slug_launcher",
}


def _raptor_vs_aegis_equal_cost(budget: int) -> Dict[str, int]:
    return ships_for_budget("falcon_interceptor", budget)


def _aegis_hangar_equal_cost(budget: int) -> Dict[str, int]:
    return ships_for_budget("ironclad_frigate", budget)


def _vanguard_equal_cost(budget: int) -> Dict[str, int]:
    return ships_for_budget("spark_drone", budget)


def _raptor_equal_cost(budget: int) -> Dict[str, int]:
    return ships_for_budget("falcon_interceptor", budget)


def _mixed_light_equal_cost(budget: int) -> Dict[str, int]:
    return mixed_ships_for_budget({"spark_drone": 0.6, "mule_courier": 0.4}, budget)


def _mass_raptor_equal_cost(budget: int) -> Dict[str, int]:
    return ships_for_budget("falcon_interceptor", budget)


def _ironclad_equal_cost(budget: int) -> Dict[str, int]:
    return ships_for_budget("ironclad_frigate", budget)


def _ion_bastion_defense_equal_cost(budget: int) -> Dict[str, int]:
    return defense_for_budget("ion_bastion", budget)


def _mixed_fleet_equal_cost(budget: int) -> Dict[str, int]:
    return mixed_ships_for_budget({"falcon_interceptor": 0.55, "spark_drone": 0.45}, budget)


def _defense_only_mixed(budget: int) -> Dict[str, int]:
    half = max(1, int(budget) // 2)
    sent = defense_for_budget("sentinel_turret", half)
    plasma = defense_for_budget("plasma_arc", budget - half)
    out: Dict[str, int] = {}
    for src in (sent, plasma):
        for k, v in src.items():
            out[k] = out.get(k, 0) + int(v)
    return out


def _cargo_escort_bad_case(budget: int) -> Dict[str, int]:
    return mixed_ships_for_budget({"mule_courier": 0.35, "falcon_interceptor": 0.65}, budget)


def _scout_screen_test(budget: int) -> Dict[str, int]:
    return mixed_ships_for_budget({"spark_drone": 0.7, "veil_probe": 0.3}, budget)


def _mixed_raptor_ironclad(budget: int) -> Dict[str, int]:
    return mixed_ships_for_budget({"falcon_interceptor": 0.55, "ironclad_frigate": 0.45}, budget)


def _mass_ironclad(budget: int) -> Dict[str, int]:
    return ships_for_budget("ironclad_frigate", budget)


def _flak_defense(budget: int) -> Dict[str, int]:
    return defense_for_budget("flak_array", budget)


def _mixed_heavy_defense(budget: int) -> Dict[str, int]:
    return mixed_defense_for_budget(
        {"ion_bastion": 0.4, "flak_array": 0.35, "plasma_arc": 0.25},
        budget,
    )


def _slug_wall(budget: int) -> Dict[str, int]:
    return defense_for_budget("slug_launcher", budget)


def _pulse_barrier_def(budget: int) -> Dict[str, int]:
    return defense_for_budget("pulse_barrier", budget)


def _plasma_defense(budget: int) -> Dict[str, int]:
    return defense_for_budget("plasma_arc", budget)


def _hangar_raptor_half(budget: int) -> Dict[str, int]:
    return mixed_ships_for_budget({"falcon_interceptor": 1.0}, max(1, budget // 2))


def _hangar_mixed_half(budget: int) -> Dict[str, int]:
    return mixed_ships_for_budget(
        {"falcon_interceptor": 0.65, "ironclad_frigate": 0.35},
        max(1, budget // 2),
    )


def _defense_mixed_half(budget: int) -> Dict[str, int]:
    return mixed_defense_for_budget(
        {"sentinel_turret": 0.35, "plasma_arc": 0.4, "ion_bastion": 0.25},
        max(1, budget // 2),
    )


def _vanguard_swarm(budget: int) -> Dict[str, int]:
    return mixed_ships_for_budget({"spark_drone": 0.85, "veil_probe": 0.15}, budget)


def _triple_mixed_fleet(budget: int) -> Dict[str, int]:
    return mixed_ships_for_budget(
        {"spark_drone": 0.25, "falcon_interceptor": 0.5, "ironclad_frigate": 0.25},
        budget,
    )


def _full_defense_layered(budget: int) -> Dict[str, int]:
    return mixed_defense_for_budget(
        {
            "slug_launcher": 0.15,
            "sentinel_turret": 0.2,
            "plasma_arc": 0.25,
            "ion_bastion": 0.2,
            "flak_array": 0.2,
        },
        budget,
    )


def _full_defense_layered(budget: int) -> Dict[str, int]:
    return mixed_defense_for_budget(
        {
            "slug_launcher": 0.15,
            "sentinel_turret": 0.2,
            "plasma_arc": 0.25,
            "ion_bastion": 0.2,
            "flak_array": 0.2,
        },
        budget,
    )


def _generate_matrix_scenarios() -> List[CombatBalanceScenario]:
    """Programmatic prüfstelle — ships, counts (via budget), defense on defenders."""
    out: List[CombatBalanceScenario] = []

    for ship in _MATRIX_COMBAT_SHIPS:
        out.append(
            _scenario(
                f"mirror_{ship}_std",
                f"Mirror: {ship}",
                f"Same mono stack both sides — {ship}.",
                attacker_ships=_mono_ship(ship),
                defender_ships=_mono_ship(ship),
            )
        )

    for atk in _MATRIX_COMBAT_SHIPS:
        for def_ship in _MATRIX_COMBAT_SHIPS:
            if atk == def_ship:
                continue
            out.append(
                _scenario(
                    f"pvp_{atk}_vs_{def_ship}_hangar",
                    f"{atk} vs {def_ship} (hangar only)",
                    f"Mono attacker vs mono hangar — no planet turrets.",
                    attacker_ships=_mono_ship(atk),
                    defender_ships=_mono_ship(def_ship),
                )
            )
            turret = _DEFENDER_COUNTER_TURRET.get(def_ship, "sentinel_turret")
            d_ships, d_def = _defender_hangar_with_turrets(
                def_ship, turret, hangar_frac=0.65, turret_frac=0.35
            )
            out.append(
                _scenario(
                    f"pvp_{atk}_vs_{def_ship}_defended",
                    f"{atk} vs {def_ship}+{turret}",
                    f"Hangar 65% + {turret} 35% on defender.",
                    attacker_ships=_mono_ship(atk),
                    defender_ships=d_ships,
                    defender_defense=d_def,
                )
            )

    for ship in _MATRIX_COMBAT_SHIPS:
        for defk in _MATRIX_DEFENSES:
            out.append(
                _scenario(
                    f"raid_{ship}_vs_{defk}",
                    f"{ship} vs {defk} wall",
                    f"Fleet-only attacker vs full-budget {defk}.",
                    attacker_ships=_mono_ship(ship),
                    defender_defense=_mono_defense(defk),
                )
            )
            d_ships, d_def = _defender_hangar_with_turrets(
                ship, defk, hangar_frac=0.5, turret_frac=0.5
            )
            out.append(
                _scenario(
                    f"raid_{ship}_vs_hangar_{defk}",
                    f"{ship} vs hangar+{defk}",
                    f"50% {ship} hangar + 50% {defk} on defender.",
                    attacker_ships=_mono_ship(ship),
                    defender_ships=d_ships,
                    defender_defense=d_def,
                )
            )

    for atk, def_ship in (
        ("falcon_interceptor", "ironclad_frigate"),
        ("spark_drone", "falcon_interceptor"),
        ("ironclad_frigate", "falcon_interceptor"),
        ("eclipse_runner", "ironclad_frigate"),
    ):
        for tier_name, budget in _BUDGET_TIERS:
            d_ships, d_def = _defender_hangar_with_turrets(
                def_ship, _DEFENDER_COUNTER_TURRET.get(def_ship, "plasma_arc"),
                hangar_frac=0.6,
                turret_frac=0.4,
            )
            out.append(
                _scenario(
                    f"duel_{atk}_vs_{def_ship}_{tier_name}",
                    f"{atk} vs {def_ship} ({tier_name})",
                    f"Budget tier {tier_name} ({budget}) — hangar + counter turrets.",
                    cost_budget=budget,
                    attacker_ships=_mono_ship(atk),
                    defender_ships=d_ships,
                    defender_defense=d_def,
                )
            )

    for atk in _MATRIX_COMBAT_SHIPS:
        for defk in ("flak_array", "ion_bastion", "orbital_shield"):
            for tier_name, budget in _BUDGET_TIERS:
                out.append(
                    _scenario(
                        f"duel_{atk}_vs_{defk}_{tier_name}",
                        f"{atk} vs {defk} ({tier_name})",
                        f"Budget tier {tier_name} ({budget}) — pure defense.",
                        cost_budget=budget,
                        attacker_ships=_mono_ship(atk),
                        defender_defense=_mono_defense(defk),
                    )
                )

    mixed_specs: Dict[str, Tuple[Mapping[str, float], str, str]] = {
        "light_swarm": ({"spark_drone": 0.75, "veil_probe": 0.25}, "ironclad_frigate", "flak_array"),
        "screen_hammer": (
            {"spark_drone": 0.3, "falcon_interceptor": 0.35, "ironclad_frigate": 0.35},
            "ironclad_frigate",
            "ion_bastion",
        ),
        "raptor_heavy": ({"falcon_interceptor": 0.7, "ironclad_frigate": 0.3}, "falcon_interceptor", "plasma_arc"),
        "expedition_mix": ({"solar_skiff": 0.4, "eclipse_runner": 0.6}, "eclipse_runner", "sentinel_turret"),
        "cargo_convoy": ({"mule_courier": 0.5, "falcon_interceptor": 0.5}, "mule_courier", "slug_launcher"),
        "atlas_escort": ({"atlas_hauler": 0.6, "ironclad_frigate": 0.4}, "atlas_hauler", "flak_array"),
        "vanguard_flood": ({"spark_drone": 0.9, "falcon_interceptor": 0.1}, "falcon_interceptor", "flak_array"),
        "raptor_wall": ({"falcon_interceptor": 0.85, "spark_drone": 0.15}, "ironclad_frigate", "plasma_arc"),
        "heavy_breach": ({"ironclad_frigate": 0.8, "eclipse_runner": 0.2}, "ironclad_frigate", "orbital_shield"),
        "triple_stack": (
            {"spark_drone": 0.25, "falcon_interceptor": 0.5, "ironclad_frigate": 0.25},
            "falcon_interceptor",
            "pulse_barrier",
        ),
        "skew_light": ({"spark_drone": 0.95, "falcon_interceptor": 0.05}, "ironclad_frigate", "flak_array"),
        "skew_heavy": ({"ironclad_frigate": 0.95, "falcon_interceptor": 0.05}, "falcon_interceptor", "ion_bastion"),
    }
    for mix_key, (spec, hangar, defk) in mixed_specs.items():
        d_ships, d_def = _defender_hangar_with_turrets(hangar, defk, hangar_frac=0.55, turret_frac=0.45)
        out.append(
            _scenario(
                f"mixed_{mix_key}_vs_defended",
                f"Mixed {mix_key} vs defended",
                f"Mixed attacker vs {hangar} hangar + {defk}.",
                attacker_ships=_weighted_ships(spec),
                defender_ships=d_ships,
                defender_defense=d_def,
            )
        )
        out.append(
            _scenario(
                f"mixed_{mix_key}_vs_fullgrid",
                f"Mixed {mix_key} vs full grid",
                f"Mixed attacker vs layered turret grid (high budget).",
                cost_budget=BUDGET_HIGH,
                attacker_ships=_weighted_ships(spec),
                defender_defense=_full_defense_layered,
            )
        )

    for tier_name, budget in _BUDGET_TIERS:
        out.append(
            _scenario(
                f"ironclad_vs_fullgrid_{tier_name}",
                f"Ironclad vs full grid ({tier_name})",
                f"Heavy fleet vs all turret tiers at {budget}.",
                cost_budget=budget,
                attacker_ships=_mono_ship("ironclad_frigate"),
                defender_defense=_full_defense_layered,
            )
        )
        out.append(
            _scenario(
                f"mixed_vs_mixed_def_{tier_name}",
                f"Mixed fleet vs mixed turrets ({tier_name})",
                f"Raptor+vanguard vs ion+flak+plasma at {budget}.",
                cost_budget=budget,
                attacker_ships=_mixed_fleet_equal_cost,
                defender_defense=_mixed_heavy_defense,
            )
        )
        out.append(
            _scenario(
                f"raptor_vs_layered_planet_{tier_name}",
                f"Raptor vs layered planet ({tier_name})",
                f"Mono falcon vs hangar+sentinel+plasma+ion split.",
                cost_budget=budget,
                attacker_ships=_mono_ship("falcon_interceptor"),
                defender_ships=_weighted_ships({"falcon_interceptor": 0.4, "ironclad_frigate": 0.1}),
                defender_defense=_weighted_defense(
                    {"sentinel_turret": 0.2, "plasma_arc": 0.15, "ion_bastion": 0.15}
                ),
            )
        )

    for defk in _MATRIX_DEFENSES:
        out.append(
            _scenario(
                f"def_grid_{defk}_vs_ironclad",
                f"Ironclad vs mono {defk}",
                f"Single turret type full budget vs ironclad stack.",
                attacker_ships=_mono_ship("ironclad_frigate"),
                defender_defense=_mono_defense(defk),
            )
        )

    return out


_CURATED_SCENARIOS: Tuple[CombatBalanceScenario, ...] = (
        _scenario(
            "raptor_vs_aegis_equal_cost",
            "Raptor vs Aegis Frigate (equal cost)",
            "falcon_interceptor vs ironclad_frigate hangar.",
            attacker_ships=_raptor_vs_aegis_equal_cost,
            defender_ships=_aegis_hangar_equal_cost,
        ),
        _scenario(
            "vanguard_vs_raptor_equal_cost",
            "Vanguard vs Raptor (equal cost)",
            "spark_drone swarm vs falcon_interceptor hangar.",
            attacker_ships=_vanguard_equal_cost,
            defender_ships=_raptor_equal_cost,
        ),
        _scenario(
            "ironclad_vs_raptor_equal_cost",
            "Aegis vs Raptor (equal cost)",
            "ironclad_frigate attacker vs falcon hangar — heavy vs screen.",
            attacker_ships=_ironclad_equal_cost,
            defender_ships=_raptor_equal_cost,
        ),
        _scenario(
            "raptor_vs_ironclad_beta_attack",
            "Raptor attack vs Aegis (Beta attacks)",
            "Beta bot attacks with falcon vs Alpha ironclad hangar.",
            attacker="beta",
            attacker_ships=_raptor_vs_aegis_equal_cost,
            defender_ships=_aegis_hangar_equal_cost,
        ),
        _scenario(
            "mixed_light_vs_mass_raptor_equal_cost",
            "Mixed light vs mass Raptor",
            "Vanguard + cargo vs mono falcon stack.",
            attacker_ships=_mixed_light_equal_cost,
            defender_ships=_mass_raptor_equal_cost,
        ),
        _scenario(
            "mixed_fleet_vs_mass_ironclad",
            "Mixed fleet vs mass Aegis",
            "Raptor + Aegis mix vs ironclad wall.",
            attacker_ships=_mixed_raptor_ironclad,
            defender_ships=_mass_ironclad,
        ),
        _scenario(
            "triple_mixed_vs_triple_mixed",
            "Triple mixed fleet mirror",
            "Scout + Raptor + Aegis vs same composition.",
            attacker_ships=_triple_mixed_fleet,
            defender_ships=_triple_mixed_fleet,
        ),
        _scenario(
            "bomber_vs_defense_equal_cost",
            "Ironclad vs Ion Bastion",
            "Heavy ship vs ion_bastion turret.",
            attacker_ships=_ironclad_equal_cost,
            defender_defense=_ion_bastion_defense_equal_cost,
        ),
        _scenario(
            "raptor_vs_aegis_defense_equal_cost",
            "Raptor vs Ion Bastion",
            "falcon_interceptor vs ion_bastion.",
            attacker_ships=_raptor_vs_aegis_equal_cost,
            defender_defense=_ion_bastion_defense_equal_cost,
        ),
        _scenario(
            "raptor_vs_flak_equal_cost",
            "Raptor vs Flak Array",
            "falcon vs flak_array — light-ship counter test.",
            attacker_ships=_raptor_vs_aegis_equal_cost,
            defender_defense=_flak_defense,
        ),
        _scenario(
            "vanguard_swarm_vs_flak",
            "Vanguard swarm vs Flak",
            "spark_drone screen vs flak_array.",
            attacker_ships=_vanguard_swarm,
            defender_defense=_flak_defense,
        ),
        _scenario(
            "ironclad_vs_pulse_barrier",
            "Ironclad vs Pulse Barrier",
            "Heavy puncher vs shield defense.",
            attacker_ships=_ironclad_equal_cost,
            defender_defense=_pulse_barrier_def,
        ),
        _scenario(
            "raptor_vs_slug_wall",
            "Raptor vs Slug launcher wall",
            "Early-game defense density vs falcon.",
            cost_budget=BUDGET_LOW,
            attacker_ships=_raptor_vs_aegis_equal_cost,
            defender_defense=_slug_wall,
        ),
        _scenario(
            "mixed_fleet_vs_mixed_defense",
            "Mixed fleet vs mixed turrets",
            "Raptor + Vanguard vs sentinel + plasma.",
            attacker_ships=_mixed_fleet_equal_cost,
            defender_defense=_defense_only_mixed,
        ),
        _scenario(
            "mixed_fleet_vs_heavy_defense",
            "Mixed fleet vs heavy defense layer",
            "Raptor + Vanguard vs ion + flak + plasma.",
            attacker_ships=_mixed_fleet_equal_cost,
            defender_defense=_mixed_heavy_defense,
        ),
        _scenario(
            "mixed_fleet_vs_full_defense_grid",
            "Mixed fleet vs full defense grid",
            "All turret tiers at equal cost budget.",
            cost_budget=BUDGET_HIGH,
            attacker_ships=_mixed_raptor_ironclad,
            defender_defense=_full_defense_layered,
        ),
        _scenario(
            "mixed_fleet_vs_hangar_and_defense",
            "Mixed fleet vs hangar + defense",
            "Attacker mix vs half-budget raptors + layered turrets.",
            attacker_ships=_mixed_fleet_equal_cost,
            defender_ships=_hangar_raptor_half,
            defender_defense=_defense_mixed_half,
        ),
        _scenario(
            "ironclad_vs_hangar_and_defense",
            "Ironclad vs hangar + defense",
            "Heavy attacker vs raptor/ironclad hangar + plasma/sentinel.",
            attacker_ships=_ironclad_equal_cost,
            defender_ships=_hangar_mixed_half,
            defender_defense=_defense_mixed_half,
        ),
        _scenario(
            "raptor_vs_plasma_hangar_combo",
            "Raptor vs Raptor + Plasma defense",
            "Mono raptor vs combined hangar and plasma_arc.",
            attacker_ships=_raptor_vs_aegis_equal_cost,
            defender_ships=_hangar_raptor_half,
            defender_defense=_plasma_defense,
        ),
        _scenario(
            "cargo_escort_bad_case",
            "Cargo escort bad case",
            "Mule + Raptor escort vs mass Raptor.",
            attacker_ships=_cargo_escort_bad_case,
            defender_ships=_mass_raptor_equal_cost,
        ),
        _scenario(
            "scout_screen_test",
            "Scout screen vs mass Raptor",
            "Vanguard + spy probes vs falcon stack.",
            attacker_ships=_scout_screen_test,
            defender_ships=_mass_raptor_equal_cost,
        ),
        _scenario(
            "mass_ironclad_vs_full_grid",
            "Mass Aegis vs full defense grid",
            "High-budget ironclad wall vs all turret tiers.",
            cost_budget=BUDGET_HIGH,
            attacker_ships=_mass_ironclad,
            defender_defense=_full_defense_layered,
        ),
)


def _build_scenario_registry() -> Dict[str, CombatBalanceScenario]:
    merged: Dict[str, CombatBalanceScenario] = {}
    for scenario in _CURATED_SCENARIOS:
        merged[scenario.key] = scenario
    for scenario in _generate_matrix_scenarios():
        merged.setdefault(scenario.key, scenario)
    return merged


COMBAT_BALANCE_SCENARIOS: Dict[str, CombatBalanceScenario] = _build_scenario_registry()
SCENARIO_KEYS: Tuple[str, ...] = tuple(COMBAT_BALANCE_SCENARIOS.keys())


def combat_balance_runs_schema_ready(conn=None) -> bool:
    own = conn is None
    if own:
        conn = db()
    try:
        return table_exists(conn, "combat_balance_runs")
    finally:
        if own:
            conn.close()


def ensure_combat_balance_runs_table(conn) -> None:
    if combat_balance_runs_schema_ready(conn):
        return
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS combat_balance_runs (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_key         TEXT NOT NULL,
            attacker_bot_id      INTEGER NOT NULL,
            defender_bot_id      INTEGER NOT NULL,
            fleet_movement_id    INTEGER,
            started_at           INTEGER NOT NULL,
            resolved_at          INTEGER,
            attacker_setup_json  TEXT NOT NULL DEFAULT '{}',
            defender_setup_json  TEXT NOT NULL DEFAULT '{}',
            result_json          TEXT,
            winner               TEXT,
            rounds               INTEGER,
            attacker_losses_json TEXT,
            defender_losses_json TEXT,
            debris_json          TEXT,
            loot_json            TEXT,
            notes                TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_combat_balance_runs_movement
            ON combat_balance_runs (fleet_movement_id);
        CREATE INDEX IF NOT EXISTS idx_combat_balance_runs_started
            ON combat_balance_runs (started_at DESC);
        """
    )


def _bot_username_for_player(player_id: int, *, conn) -> Optional[str]:
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE id = ? LIMIT 1;", (int(player_id),))
    row = cur.fetchone()
    if not row:
        return None
    return str(row["username"] or "")


def is_combat_balance_bot_player(player_id: int, *, conn) -> bool:
    if int(player_id) <= 0:
        return False
    username = _bot_username_for_player(int(player_id), conn=conn)
    if username in BOT_USERNAMES:
        return True
    cur = conn.cursor()
    cur.execute("SELECT name FROM players WHERE id = ? LIMIT 1;", (int(player_id),))
    row = cur.fetchone()
    if row and str(row["name"] or "") in BOT_DISPLAY_NAMES:
        return True
    return False


def is_bot_versus_bot_fight(
    attacker_player_id: int,
    defender_player_id: int,
    *,
    conn,
) -> bool:
    return is_combat_balance_bot_player(int(attacker_player_id), conn=conn) and is_combat_balance_bot_player(
        int(defender_player_id), conn=conn
    )


def combat_balance_bot_player_ids(*, conn) -> Set[int]:
    cur = conn.cursor()
    placeholders = ",".join("?" for _ in BOT_USERNAMES)
    cur.execute(
        f"SELECT id FROM users WHERE username IN ({placeholders});",
        BOT_USERNAMES,
    )
    ids = {int(r[0]) for r in cur.fetchall()}
    for name in BOT_DISPLAY_NAMES:
        cur.execute("SELECT id FROM players WHERE name = ?;", (name,))
        for r in cur.fetchall():
            ids.add(int(r[0]))
    return ids


def _save_setting_on_conn(key: str, value: str, *, conn) -> None:
    conn.execute(
        """
        INSERT INTO game_settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value;
        """,
        (str(key), str(value)),
    )


def is_combat_balance_bots_enabled(*, conn) -> bool:
    from .models import get_game_settings

    settings = get_game_settings(conn=conn) or {}
    return bool(int(settings.get(SETTINGS_KEY_ENABLED) or 0))


def set_combat_balance_bots_enabled(enabled: bool, *, conn) -> None:
    _save_setting_on_conn(SETTINGS_KEY_ENABLED, "1" if enabled else "0", conn=conn)


def _coord_taken(galaxy: int, system: int, position: int, *, conn, except_planet_id: int | None = None) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id FROM planets
        WHERE galaxy = ? AND system = ? AND position = ?
          AND (? IS NULL OR id != ?)
        LIMIT 1;
        """,
        (int(galaxy), int(system), int(position), except_planet_id, except_planet_id),
    )
    return cur.fetchone() is not None


def _bot_homeworld_coords_valid(galaxy: int, system: int, position: int, *, conn) -> bool:
    from .galaxy import GalaxyCoordinateError, validate_coordinates

    try:
        validate_coordinates(int(galaxy), int(system), int(position), conn=conn)
        return True
    except GalaxyCoordinateError:
        return False


def _relocate_bot_planet(
    planet_id: int,
    *,
    galaxy: int,
    system: int,
    position: int,
    conn,
) -> Tuple[int, int, int]:
    from .galaxy import clamp_galaxy, clamp_system, validate_coordinates

    g = clamp_galaxy(int(galaxy), conn=conn)
    s = clamp_system(int(system))
    p = int(position)
    validate_coordinates(g, s, p, conn=conn)
    if _coord_taken(g, s, p, conn=conn, except_planet_id=int(planet_id)):
        for alt in range(3, 20):
            if alt == p:
                continue
            try:
                validate_coordinates(g, s, alt, conn=conn)
            except Exception:
                continue
            if not _coord_taken(g, s, alt, conn=conn, except_planet_id=int(planet_id)):
                p = alt
                break
        else:
            raise RuntimeError("combat_bot_coords_unavailable")
    conn.execute(
        """
        UPDATE planets
        SET galaxy = ?, system = ?, position = ?,
            metal = 0, crystal = 0, fuel_cells = ?,
            name = CASE WHEN is_homeworld = 1 THEN name ELSE name END
        WHERE id = ?;
        """,
        (g, s, p, int(BOT_FUEL_CELLS), int(planet_id)),
    )
    return g, s, p


def _create_bot_account_on_conn(username: str, display_name: str, *, conn) -> int:
    """Insert bot user on the caller connection — never open a nested db() (SQLite lock safe)."""
    from .models import ensure_player_and_homeworld, hash_password
    from .ranking import ensure_player_score_row

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO users (username, password_hash, is_admin, email, email_verified)
        VALUES (?, ?, 0, NULL, 1);
        """,
        (username, hash_password(secrets.token_hex(BOT_INTERNAL_PASSWORD_BYTES))),
    )
    player_id = int(cur.lastrowid)
    ensure_player_and_homeworld(
        player_id,
        player_name=display_name,
        conn=conn,
        homeworld_placement="random",
    )
    ensure_player_score_row(player_id, conn=conn)
    return player_id


def _ensure_single_bot(
    username: str,
    display_name: str,
    coords: Tuple[int, int, int],
    *,
    conn,
) -> Dict[str, Any]:
    from .models import ensure_player_and_homeworld, get_planets_by_player

    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ? LIMIT 1;", (username,))
    row = cur.fetchone()
    if row:
        player_id = int(row[0])
    else:
        try:
            player_id = _create_bot_account_on_conn(username, display_name, conn=conn)
        except Exception as exc:
            cur.execute("SELECT id FROM users WHERE username = ? LIMIT 1;", (username,))
            row = cur.fetchone()
            if not row:
                raise RuntimeError(str(exc) or "combat_bot_create_failed") from exc
            player_id = int(row[0])

    ensure_player_and_homeworld(player_id, player_name=display_name, conn=conn)
    conn.execute("UPDATE players SET name = ? WHERE id = ?;", (display_name, player_id))

    planets = get_planets_by_player(player_id, conn=conn)
    if not planets:
        raise RuntimeError("combat_bot_missing_planet")
    planet_id = int(planets[0]["id"])
    cur.execute(
        "SELECT galaxy, system, position FROM planets WHERE id = ? LIMIT 1;",
        (planet_id,),
    )
    prow = cur.fetchone()
    needs_reloc = True
    if prow:
        needs_reloc = not _bot_homeworld_coords_valid(
            int(prow["galaxy"]),
            int(prow["system"]),
            int(prow["position"]),
            conn=conn,
        )
    g, s, p = coords
    if needs_reloc or (
        prow
        and (
            int(prow["galaxy"]) != int(g)
            or int(prow["system"]) != int(s)
            or int(prow["position"]) != int(p)
        )
    ):
        g, s, p = _relocate_bot_planet(
            planet_id,
            galaxy=coords[0],
            system=coords[1],
            position=coords[2],
            conn=conn,
        )
    else:
        g, s, p = int(prow["galaxy"]), int(prow["system"]), int(prow["position"])
    return {
        "player_id": player_id,
        "planet_id": planet_id,
        "username": username,
        "display_name": display_name,
        "coords": {"galaxy": g, "system": s, "position": p},
    }


def ensure_combat_balance_bots(*, conn) -> Dict[str, Any]:
    """Create or refresh the two internal combat bots and their homeworlds."""
    from .db import begin_write_transaction

    begin_write_transaction(conn)
    ensure_combat_balance_runs_table(conn)
    alpha = _ensure_single_bot(
        BOT_ALPHA_USERNAME,
        BOT_ALPHA_DISPLAY_NAME,
        (BOT_GALAXY, BOT_SYSTEM, BOT_ALPHA_POSITION),
        conn=conn,
    )
    beta = _ensure_single_bot(
        BOT_BETA_USERNAME,
        BOT_BETA_DISPLAY_NAME,
        (BOT_GALAXY, BOT_SYSTEM, BOT_BETA_POSITION),
        conn=conn,
    )
    bot_ids = {int(alpha["player_id"]), int(beta["player_id"])}
    if len(bot_ids) != 2:
        raise RuntimeError("combat_bot_count_invalid")
    return {"ok": True, "alpha": alpha, "beta": beta}


def _cleanup_bot_fleets(bot_ids: Sequence[int], *, conn) -> int:
    if not bot_ids:
        return 0
    from .fleet import fleet_schema_ready

    if not fleet_schema_ready(conn):
        return 0
    now = int(time.time())
    placeholders = ",".join("?" for _ in bot_ids)
    cur = conn.cursor()
    cur.execute(
        f"""
        UPDATE fleet_movements
        SET status = 'cancelled', updated_at = ?
        WHERE player_id IN ({placeholders})
          AND status IN ('outbound', 'holding', 'returning');
        """,
        (now, *[int(x) for x in bot_ids]),
    )
    return int(cur.rowcount or 0)


def reset_bot_planet(
    planet_id: int,
    player_id: int,
    *,
    ships: Mapping[str, int] | None = None,
    defense: Mapping[str, int] | None = None,
    conn,
) -> None:
    from .fleet import set_planet_ships
    from .models import defense_schema_ready, set_planet_defense

    conn.execute(
        "UPDATE planets SET metal = 0, crystal = 0, fuel_cells = ? WHERE id = ?;",
        (int(BOT_FUEL_CELLS), int(planet_id)),
    )
    set_planet_ships(int(planet_id), int(player_id), dict(ships or {}), conn=conn)
    if defense_schema_ready(conn):
        set_planet_defense(int(planet_id), dict(defense or {}), conn=conn)


def list_scenarios_payload() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for key in SCENARIO_KEYS:
        sc = COMBAT_BALANCE_SCENARIOS[key]
        budget = int(sc.cost_budget)
        atk = sc.attacker_ships(budget)
        def_ships = sc.defender_ships(budget)
        def_def = sc.defender_defense(budget)
        out.append(
            {
                "key": sc.key,
                "label": sc.label,
                "notes": sc.notes,
                "cost_budget": budget,
                "attacker": sc.attacker,
                "attacker_preview": atk,
                "defender_ships_preview": def_ships,
                "defender_defense_preview": def_def,
                "repeat_count": sc.repeat_count,
            }
        )
    return out


def _cooldown_remaining(*, conn, now: float | None = None) -> int:
    from .models import get_game_settings

    settings = get_game_settings(conn=conn) or {}
    last = int(settings.get(SETTINGS_KEY_LAST_RUN) or 0)
    ts = float(now if now is not None else time.time())
    elapsed = int(ts) - last
    return max(0, MIN_RUN_INTERVAL_SEC - elapsed)


def _touch_last_run(*, conn, now: float | None = None) -> None:
    _save_setting_on_conn(
        SETTINGS_KEY_LAST_RUN,
        str(int(now if now is not None else time.time())),
        conn=conn,
    )


def _has_pending_bot_run(*, conn) -> bool:
    if not combat_balance_runs_schema_ready(conn):
        return False
    row = conn.execute(
        """
        SELECT COUNT(*) AS c FROM combat_balance_runs
        WHERE resolved_at IS NULL AND fleet_movement_id IS NOT NULL;
        """
    ).fetchone()
    return bool(row and int(row["c"]) > 0)


def resolve_next_scenario_key(*, conn) -> str:
    from .models import get_game_settings

    settings = get_game_settings(conn=conn) or {}
    idx = int(settings.get(SETTINGS_KEY_SCENARIO_INDEX) or 0) % max(1, len(SCENARIO_KEYS))
    return SCENARIO_KEYS[idx]


def advance_scenario_index(*, conn) -> str:
    from .models import get_game_settings

    settings = get_game_settings(conn=conn) or {}
    idx = int(settings.get(SETTINGS_KEY_SCENARIO_INDEX) or 0) % max(1, len(SCENARIO_KEYS))
    nxt = (idx + 1) % len(SCENARIO_KEYS)
    _save_setting_on_conn(SETTINGS_KEY_SCENARIO_INDEX, str(nxt), conn=conn)
    return SCENARIO_KEYS[nxt]


def maybe_run_next_scheduled_scenario(*, conn, now: float | None = None) -> Dict[str, Any]:
    """
    Fleet-worker scheduler — one scenario per cooldown when auto mode is enabled.

    Never run from game-state / queue hot path (SQLite lock safety).
    """
    ts = float(now if now is not None else time.time())
    if not is_combat_balance_bots_enabled(conn=conn):
        return {"ok": True, "skipped": "disabled"}
    if _has_pending_bot_run(conn=conn):
        return {"ok": True, "skipped": "pending_run"}

    from .runtime_state import get_runtime_value, set_runtime_value

    last_raw = get_runtime_value(RUNTIME_KEY_SCHEDULER_LAST, conn=conn)
    try:
        last_at = float(last_raw or 0)
    except (TypeError, ValueError):
        last_at = 0.0
    if last_at > 0 and (ts - last_at) < float(BOT_SCHEDULER_INTERVAL_SEC):
        return {
            "ok": True,
            "skipped": "scheduler_interval",
            "next_in_sec": int(BOT_SCHEDULER_INTERVAL_SEC - (ts - last_at)),
        }

    if _cooldown_remaining(conn=conn, now=ts) > 0:
        return {"ok": True, "skipped": "scenario_cooldown", "cooldown_seconds": _cooldown_remaining(conn=conn, now=ts)}

    key = resolve_next_scenario_key(conn=conn)
    result = run_combat_balance_scenario(key, conn=conn, skip_cooldown=False)
    set_runtime_value(RUNTIME_KEY_SCHEDULER_LAST, str(int(ts)), conn=conn)
    if result.get("ok"):
        advance_scenario_index(conn=conn)
    return result


def run_combat_balance_scenario(
    scenario_key: str,
    *,
    conn,
    force: bool = False,
    skip_cooldown: bool = False,
) -> Dict[str, Any]:
    """Prepare bots, spawn loadouts, dispatch a real attack fleet movement."""
    from .db import begin_write_transaction
    from .fleet import build_fleet_send_preview, fleet_schema_ready, send_fleet

    key = str(scenario_key or "").strip()
    scenario = COMBAT_BALANCE_SCENARIOS.get(key)
    if not scenario:
        return {"ok": False, "error": "unknown_scenario", "scenario_key": key}

    if not force and not is_combat_balance_bots_enabled(conn=conn):
        return {"ok": False, "error": "combat_bots_disabled"}

    if not skip_cooldown and not force:
        remaining = _cooldown_remaining(conn=conn)
        if remaining > 0:
            return {"ok": False, "error": "cooldown_active", "cooldown_seconds": remaining}

    if not fleet_schema_ready(conn):
        return {"ok": False, "error": "fleet_unavailable"}

    bots = ensure_combat_balance_bots(conn=conn)
    alpha = bots["alpha"]
    beta = bots["beta"]
    bot_ids = [int(alpha["player_id"]), int(beta["player_id"])]

    pending = conn.execute(
        """
        SELECT COUNT(*) AS c FROM combat_balance_runs
        WHERE resolved_at IS NULL AND fleet_movement_id IS NOT NULL;
        """
    ).fetchone()
    if pending and int(pending["c"]) > 0:
        return {"ok": False, "error": "pending_run_in_flight"}

    _cleanup_bot_fleets(bot_ids, conn=conn)

    budget = int(scenario.cost_budget)
    attacker_info = alpha if scenario.attacker == "alpha" else beta
    defender_info = beta if scenario.attacker == "alpha" else alpha

    attacker_ships = scenario.attacker_ships(budget)
    defender_ships = scenario.defender_ships(budget)
    defender_defense = scenario.defender_defense(budget)

    if not attacker_ships:
        return {"ok": False, "error": "empty_attacker_setup"}

    reset_bot_planet(
        int(attacker_info["planet_id"]),
        int(attacker_info["player_id"]),
        ships=attacker_ships,
        conn=conn,
    )
    reset_bot_planet(
        int(defender_info["planet_id"]),
        int(defender_info["player_id"]),
        ships=defender_ships,
        defense=defender_defense,
        conn=conn,
    )

    def_coords = defender_info["coords"]
    origin = conn.execute(
        "SELECT * FROM planets WHERE id = ? LIMIT 1;",
        (int(attacker_info["planet_id"]),),
    ).fetchone()
    if not origin:
        return {"ok": False, "error": "origin_not_found"}

    preview = build_fleet_send_preview(
        player_id=int(attacker_info["player_id"]),
        origin_planet=dict(origin),
        target_galaxy=int(def_coords["galaxy"]),
        target_system=int(def_coords["system"]),
        target_position=int(def_coords["position"]),
        mission_type="attack",
        ships=attacker_ships,
        resources={},
        speed_percent=100,
        conn=conn,
    )
    if not preview.get("can_send"):
        return {
            "ok": False,
            "error": preview.get("block_reason") or "send_blocked",
            "preview": preview,
        }

    started_at = int(time.time())
    ensure_combat_balance_runs_table(conn)
    defender_setup = {"ships": defender_ships, "defense": defender_defense}
    attacker_setup = {"ships": attacker_ships}
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO combat_balance_runs (
            scenario_key, attacker_bot_id, defender_bot_id,
            started_at, attacker_setup_json, defender_setup_json, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?);
        """,
        (
            key,
            int(attacker_info["player_id"]),
            int(defender_info["player_id"]),
            started_at,
            _json_dumps(attacker_setup),
            _json_dumps(defender_setup),
            scenario.notes,
        ),
    )
    run_id = int(cur.lastrowid)

    ok, reason, extra = send_fleet(
        player_id=int(attacker_info["player_id"]),
        origin_planet_id=int(attacker_info["planet_id"]),
        target_galaxy=int(def_coords["galaxy"]),
        target_system=int(def_coords["system"]),
        target_position=int(def_coords["position"]),
        mission_type="attack",
        ships=attacker_ships,
        resources={},
        speed_percent=100,
        conn=conn,
    )
    if not ok:
        conn.execute("DELETE FROM combat_balance_runs WHERE id = ?;", (run_id,))
        return {"ok": False, "error": reason, "extra": extra}

    fleet = (extra or {}).get("fleet") or {}
    movement_id = int(fleet.get("id") or 0)
    conn.execute(
        "UPDATE combat_balance_runs SET fleet_movement_id = ? WHERE id = ?;",
        (movement_id, run_id),
    )
    _touch_last_run(conn=conn)

    return {
        "ok": True,
        "run_id": run_id,
        "scenario_key": key,
        "fleet_movement_id": movement_id,
        "flight_seconds": int(preview.get("flight_seconds") or fleet.get("flight_seconds") or 0),
        "attacker_setup": attacker_setup,
        "defender_setup": defender_setup,
        "attacker_bot_id": int(attacker_info["player_id"]),
        "defender_bot_id": int(defender_info["player_id"]),
    }


def finalize_combat_balance_run(
    fleet_movement_id: int,
    *,
    combat_result: Any,
    loot: Mapping[str, int] | None = None,
    conn,
    now: float | None = None,
) -> bool:
    """Persist audit row when a bot-vs-bot attack resolves."""
    if not combat_balance_runs_schema_ready(conn):
        return False
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM combat_balance_runs
        WHERE fleet_movement_id = ? AND resolved_at IS NULL
        LIMIT 1;
        """,
        (int(fleet_movement_id),),
    )
    row = cur.fetchone()
    if not row:
        return False

    from .combat import calculate_combat_debris

    debris_m, debris_c = calculate_combat_debris(
        combat_result.attacker_losses,
        combat_result.defender_losses,
    )
    result_payload = {
        "winner": str(combat_result.winner or ""),
        "rounds": len(combat_result.rounds or []),
    }
    resolved_at = int(now if now is not None else time.time())
    cur.execute(
        """
        UPDATE combat_balance_runs
        SET resolved_at = ?,
            winner = ?,
            rounds = ?,
            attacker_losses_json = ?,
            defender_losses_json = ?,
            debris_json = ?,
            loot_json = ?,
            result_json = ?
        WHERE id = ?;
        """,
        (
            resolved_at,
            str(combat_result.winner or ""),
            len(combat_result.rounds or []),
            _json_dumps(combat_result.attacker_losses or {}),
            _json_dumps(combat_result.defender_losses or {}),
            _json_dumps({"metal": int(debris_m), "crystal": int(debris_c)}),
            _json_dumps(dict(loot or {})),
            _json_dumps(result_payload),
            int(row["id"]),
        ),
    )
    return True


def list_combat_balance_results(*, conn, limit: int = 20) -> List[Dict[str, Any]]:
    if not combat_balance_runs_schema_ready(conn):
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT r.*,
               pa.name AS attacker_name,
               pd.name AS defender_name
        FROM combat_balance_runs r
        LEFT JOIN players pa ON pa.id = r.attacker_bot_id
        LEFT JOIN players pd ON pd.id = r.defender_bot_id
        ORDER BY r.started_at DESC
        LIMIT ?;
        """,
        (max(1, min(int(limit), 200)),),
    )
    out: List[Dict[str, Any]] = []
    for raw in cur.fetchall():
        d = dict(raw)
        out.append(
            {
                "id": int(d["id"]),
                "scenario_key": d.get("scenario_key"),
                "attacker_bot_id": int(d.get("attacker_bot_id") or 0),
                "defender_bot_id": int(d.get("defender_bot_id") or 0),
                "attacker_name": d.get("attacker_name"),
                "defender_name": d.get("defender_name"),
                "fleet_movement_id": d.get("fleet_movement_id"),
                "started_at": int(d.get("started_at") or 0),
                "resolved_at": d.get("resolved_at"),
                "winner": d.get("winner"),
                "rounds": d.get("rounds"),
                "attacker_setup": _json_loads(d.get("attacker_setup_json")),
                "defender_setup": _json_loads(d.get("defender_setup_json")),
                "attacker_losses": _json_loads(d.get("attacker_losses_json")),
                "defender_losses": _json_loads(d.get("defender_losses_json")),
                "debris": _json_loads(d.get("debris_json")),
                "loot": _json_loads(d.get("loot_json")),
                "notes": d.get("notes"),
            }
        )
    return out


def _bot_snapshot_entry(username: str, display_name: str, *, conn) -> Optional[Dict[str, Any]]:
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE username = ? LIMIT 1;", (username,))
    row = cur.fetchone()
    if not row:
        return None
    player_id = int(row[0])
    cur.execute(
        """
        SELECT id, galaxy, system, position
        FROM planets
        WHERE player_id = ? AND is_homeworld = 1
        LIMIT 1;
        """,
        (player_id,),
    )
    planet = cur.fetchone()
    if not planet:
        return None
    return {
        "player_id": player_id,
        "planet_id": int(planet["id"]),
        "username": username,
        "display_name": display_name,
        "coords": {
            "galaxy": int(planet["galaxy"]),
            "system": int(planet["system"]),
            "position": int(planet["position"]),
        },
    }


def get_combat_balance_bots_snapshot(*, conn) -> Dict[str, Any]:
    """Read-only admin status — does not create bots or start write transactions."""
    alpha = _bot_snapshot_entry(BOT_ALPHA_USERNAME, BOT_ALPHA_DISPLAY_NAME, conn=conn)
    beta = _bot_snapshot_entry(BOT_BETA_USERNAME, BOT_BETA_DISPLAY_NAME, conn=conn)
    return {
        "enabled": is_combat_balance_bots_enabled(conn=conn),
        "cooldown_seconds": _cooldown_remaining(conn=conn),
        "scheduler_interval_sec": int(BOT_SCHEDULER_INTERVAL_SEC),
        "scenario_count": len(SCENARIO_KEYS),
        "next_scenario_key": resolve_next_scenario_key(conn=conn),
        "pending_run": _has_pending_bot_run(conn=conn),
        "scenarios": list_scenarios_payload(),
        "bots_ready": alpha is not None and beta is not None,
        "alpha": alpha,
        "beta": beta,
    }


def admin_status_payload(*, conn) -> Dict[str, Any]:
    return {
        **get_combat_balance_bots_snapshot(conn=conn),
        "recent_results": list_combat_balance_results(conn=conn, limit=10),
    }
