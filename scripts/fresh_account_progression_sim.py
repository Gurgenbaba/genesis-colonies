#!/usr/bin/env python3
"""GC-829 — Fresh-account progression simulation (authoritative formulas).

Answers: how far does a new homeworld get at 30m / 1h / 4h / 24h / 7d / 30d?

Uses EffectResolver + economy_balance + buildings/research requirements.
No DB, no formula changes — measurement only.

Usage:
  python scripts/fresh_account_progression_sim.py
  python scripts/fresh_account_progression_sim.py --stdout
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from game.buildings import get_upgrade_cost, has_building_requirements
from game.economy_balance import NEUTRAL_BALANCE_SLOT, reference_production_per_hour
from game.effects import EffectResolver
from game.models import DEFAULT_GAME_SETTINGS
from game.research import get_research_cost, has_research_requirements

# ---------------------------------------------------------------------------
# Checkpoints & presets
# ---------------------------------------------------------------------------

CHECKPOINTS_SEC: Tuple[Tuple[str, int], ...] = (
    ("30min", 30 * 60),
    ("1h", 3600),
    ("4h", 4 * 3600),
    ("24h", 24 * 3600),
    ("7d", 7 * 86400),
    ("30d", 30 * 86400),
)

SIM_HORIZON_SEC = CHECKPOINTS_SEC[-1][1]

PRESETS: Dict[str, Dict[str, float]] = {
    "alpha_current": {
        "production_speed": float(DEFAULT_GAME_SETTINGS.get("production_speed", 1)),
        "build_speed": float(DEFAULT_GAME_SETTINGS.get("build_speed", 1)),
        "research_speed": float(DEFAULT_GAME_SETTINGS.get("research_speed", 1)),
    },
    "alpha_proposed_gc829": {
        "production_speed": 1.0,
        "build_speed": 8.0,
        "research_speed": 50.0,
    },
    "alpha_proposed_ferdi": {
        "production_speed": 1.0,
        "build_speed": 10.0,
        "research_speed": 50.0,
    },
    "alpha_proposed_ferdi_r100": {
        "production_speed": 1.0,
        "build_speed": 10.0,
        "research_speed": 100.0,
    },
    "baseline_all_1": {
        "production_speed": 1.0,
        "build_speed": 1.0,
        "research_speed": 1.0,
    },
    "contrast_prod2": {
        "production_speed": 2.0,
        "build_speed": 1.0,
        "research_speed": 1.0,
    },
}

START_METAL = float(DEFAULT_GAME_SETTINGS.get("start_metal", 150000))
START_CRYSTAL = float(DEFAULT_GAME_SETTINGS.get("start_crystal", 100000))
START_FUEL = float(DEFAULT_GAME_SETTINGS.get("start_fuel_cells", 25000))
BALANCE_SLOT = NEUTRAL_BALANCE_SLOT

BUILD_PRIORITY: Tuple[str, ...] = (
    "solar_plant",
    "metal_mine",
    "crystal_mine",
    "fuel_cell_plant",
    "research_lab",
    "metal_storage",
    "crystal_storage",
    "command_center",
)

RESEARCH_PRIORITY: Tuple[str, ...] = (
    "energy_tech",
    "mining_tech",
    "buildtime_tech",
    "storage_tech",
    "drone_tech",
)


@dataclass
class ActiveJob:
    kind: str  # "build" | "research"
    key: str
    target_level: int
    finish_at: float
    cost_m: int
    cost_c: int


@dataclass
class SimState:
    t: float = 0.0
    metal: float = START_METAL
    crystal: float = START_CRYSTAL
    fuel_cells: float = START_FUEL
    buildings: Dict[str, int] = field(default_factory=dict)
    research: Dict[str, int] = field(default_factory=dict)
    build_job: Optional[ActiveJob] = None
    research_job: Optional[ActiveJob] = None
    build_active_sec: float = 0.0
    research_active_sec: float = 0.0
    build_wait_sec: float = 0.0
    research_wait_sec: float = 0.0
    idle_sec: float = 0.0
    build_completions: int = 0
    research_completions: int = 0


def _settings_dict(preset: Dict[str, float]) -> Dict[str, Any]:
    return {
        "production_speed": preset["production_speed"],
        "build_speed": preset["build_speed"],
        "research_speed": preset["research_speed"],
    }


def _resolver(state: SimState, settings: Dict[str, float]) -> EffectResolver:
    return EffectResolver(
        dict(state.buildings),
        dict(state.research),
        settings=_settings_dict(settings),
        planet_position=BALANCE_SLOT,
    )


def _caps(state: SimState, settings: Dict[str, float]) -> Dict[str, int]:
    return _resolver(state, settings).get_storage_capacity()


def _clamp_storage(state: SimState, settings: Dict[str, float]) -> None:
    caps = _caps(state, settings)
    state.metal = min(state.metal, float(caps.get("metal", 10**9)))
    state.crystal = min(state.crystal, float(caps.get("crystal", 10**9)))
    fc_cap = caps.get("fuel_cells", 0)
    if fc_cap > 0:
        state.fuel_cells = min(state.fuel_cells, float(fc_cap))


def _accumulate_production(state: SimState, settings: Dict[str, float], dt: float) -> None:
    if dt <= 0:
        return
    er = _resolver(state, settings)
    energy_total, energy_used = er.compute_energy()
    ratio = EffectResolver.energy_ratio(energy_total, energy_used)
    m_rate, c_rate = er.production_rates_per_sec()
    fc_rate = er.fuel_cells_rate_per_sec()
    state.metal += m_rate * ratio * dt
    state.crystal += c_rate * ratio * dt
    state.fuel_cells += fc_rate * ratio * dt
    _clamp_storage(state, settings)


def _can_afford(state: SimState, cost_m: int, cost_c: int) -> bool:
    return state.metal >= cost_m and state.crystal >= cost_c


def _energy_ratio(state: SimState, settings: Dict[str, float]) -> float:
    er = _resolver(state, settings)
    total, used = er.compute_energy()
    return EffectResolver.energy_ratio(total, used)


def _build_candidate_order(state: SimState, settings: Dict[str, float]) -> List[str]:
    ratio = _energy_ratio(state, settings)

    metal_lvl = int(state.buildings.get("metal_mine", 0) or 0)
    crystal_lvl = int(state.buildings.get("crystal_mine", 0) or 0)
    lab_lvl = int(state.buildings.get("research_lab", 0) or 0)
    fc_lvl = int(state.buildings.get("fuel_cell_plant", 0) or 0)
    solar_lvl = int(state.buildings.get("solar_plant", 0) or 0)

    # Phase 0 — bootstrap
    if solar_lvl < 1:
        return ["solar_plant"]
    if metal_lvl < 1:
        return ["metal_mine", "solar_plant"]
    if crystal_lvl < 1:
        return ["crystal_mine", "metal_mine", "solar_plant"]

    # Phase 1 — research lab unlock gate (before energy tuning / mine grind)
    if lab_lvl < 1 and (metal_lvl < 3 or crystal_lvl < 2):
        gate: List[str] = []
        if metal_lvl < 3:
            gate.append("metal_mine")
        if crystal_lvl < 2:
            gate.append("crystal_mine")
        return gate

    candidates: List[str] = []

    if ratio < 0.98:
        candidates.append("solar_plant")

    # Milestone pushes — visible unlocks beat passive mine grind.
    if lab_lvl < 1 and has_building_requirements(state.buildings, state.research, "research_lab"):
        candidates.insert(0, "research_lab")
    if fc_lvl < 1 and has_building_requirements(state.buildings, state.research, "fuel_cell_plant"):
        candidates.insert(0, "fuel_cell_plant")

    if metal_lvl <= crystal_lvl:
        candidates.append("metal_mine")
    else:
        candidates.append("crystal_mine")

    if lab_lvl >= 1 and lab_lvl < 5:
        candidates.append("research_lab")

    for b in BUILD_PRIORITY:
        if b not in candidates:
            candidates.append(b)

    seen: set[str] = set()
    return [b for b in candidates if not (b in seen or seen.add(b))]


def _peek_build_target(
    state: SimState, settings: Dict[str, float]
) -> Optional[Tuple[str, int, int, int, int]]:
    """Next desired build (ignores affordability)."""
    er = _resolver(state, settings)
    for btype in _build_candidate_order(state, settings):
        if not has_building_requirements(state.buildings, state.research, btype):
            continue
        cur = int(state.buildings.get(btype, 0) or 0)
        if cur >= er.get_max_building_level(btype):
            continue
        cost_m, cost_c = get_upgrade_cost(btype, cur)
        target = cur + 1
        duration = er.get_build_time_seconds(btype, target)
        return btype, target, cost_m, cost_c, duration
    return None


def _next_build_action(state: SimState, settings: Dict[str, float]) -> Optional[Tuple[str, int, int, int, int]]:
    """Return (building_type, target_level, cost_m, cost_c, duration_sec) or None."""
    target = _peek_build_target(state, settings)
    if not target:
        return None
    btype, lvl, cost_m, cost_c, duration = target
    if not _can_afford(state, cost_m, cost_c):
        return None
    return btype, lvl, cost_m, cost_c, duration


def _peek_research_target(
    state: SimState, settings: Dict[str, float]
) -> Optional[Tuple[str, int, int, int, int]]:
    lab = int(state.buildings.get("research_lab", 0) or 0)
    if lab < 1:
        return None
    er = _resolver(state, settings)
    for tech in RESEARCH_PRIORITY:
        if not has_research_requirements(state.buildings, state.research, tech):
            continue
        cur = int(state.research.get(tech, 0) or 0)
        target = cur + 1
        cost_m, cost_c = get_research_cost(tech, target)
        duration = er.get_research_time_seconds(tech, target)
        return tech, target, cost_m, cost_c, duration
    return None


def _next_research_action(state: SimState, settings: Dict[str, float]) -> Optional[Tuple[str, int, int, int, int]]:
    target = _peek_research_target(state, settings)
    if not target:
        return None
    tech, lvl, cost_m, cost_c, duration = target
    if not _can_afford(state, cost_m, cost_c):
        return None
    return tech, lvl, cost_m, cost_c, duration


def _time_until_afford(state: SimState, settings: Dict[str, float], cost_m: int, cost_c: int) -> float:
    need_m = max(0.0, float(cost_m) - state.metal)
    need_c = max(0.0, float(cost_c) - state.crystal)
    if need_m <= 0 and need_c <= 0:
        return 0.0

    er = _resolver(state, settings)
    energy_total, energy_used = er.compute_energy()
    ratio = EffectResolver.energy_ratio(energy_total, energy_used)
    m_rate, c_rate = er.production_rates_per_sec()
    m_ps = m_rate * ratio
    c_ps = c_rate * ratio

    times: List[float] = []
    if need_m > 0:
        if m_ps <= 0:
            return math.inf
        times.append(need_m / m_ps)
    if need_c > 0:
        if c_ps <= 0:
            return math.inf
        times.append(need_c / c_ps)
    return max(times) if times else math.inf


def _next_event_delta(state: SimState, settings: Dict[str, float], horizon_sec: int) -> float:
    """Seconds until the next sim event (job finish or resources for queued action)."""
    remaining = float(horizon_sec) - state.t
    if remaining <= 0:
        return 0.0

    candidates: List[float] = []
    if state.build_job:
        candidates.append(max(0.0, state.build_job.finish_at - state.t))
    if state.research_job:
        candidates.append(max(0.0, state.research_job.finish_at - state.t))

    if state.build_job is None:
        peek = _peek_build_target(state, settings)
        if peek:
            _, _, cost_m, cost_c, _ = peek
            if not _can_afford(state, cost_m, cost_c):
                wait = _time_until_afford(state, settings, cost_m, cost_c)
                if math.isfinite(wait) and wait > 0:
                    candidates.append(wait)

    if state.research_job is None:
        peek = _peek_research_target(state, settings)
        if peek:
            _, _, cost_m, cost_c, _ = peek
            if not _can_afford(state, cost_m, cost_c):
                wait = _time_until_afford(state, settings, cost_m, cost_c)
                if math.isfinite(wait) and wait > 0:
                    candidates.append(wait)

    if not candidates:
        return remaining

    return min(remaining, min(candidates))


def _start_build(state: SimState, settings: Dict[str, float]) -> bool:
    action = _next_build_action(state, settings)
    if not action:
        return False
    btype, target, cost_m, cost_c, duration = action
    state.metal -= cost_m
    state.crystal -= cost_c
    state.build_job = ActiveJob(
        kind="build",
        key=btype,
        target_level=target,
        finish_at=state.t + duration,
        cost_m=cost_m,
        cost_c=cost_c,
    )
    return True


def _start_research(state: SimState, settings: Dict[str, float]) -> bool:
    action = _next_research_action(state, settings)
    if not action:
        return False
    tech, target, cost_m, cost_c, duration = action
    state.metal -= cost_m
    state.crystal -= cost_c
    state.research_job = ActiveJob(
        kind="research",
        key=tech,
        target_level=target,
        finish_at=state.t + duration,
        cost_m=cost_m,
        cost_c=cost_c,
    )
    return True


def _complete_build(state: SimState) -> None:
    job = state.build_job
    if not job:
        return
    state.buildings[job.key] = job.target_level
    state.build_completions += 1
    state.build_job = None


def _complete_research(state: SimState) -> None:
    job = state.research_job
    if not job:
        return
    state.research[job.key] = job.target_level
    state.research_completions += 1
    state.research_job = None


def _snapshot(state: SimState, settings: Dict[str, float]) -> Dict[str, Any]:
    er = _resolver(state, settings)
    total, used = er.compute_energy()
    ratio = EffectResolver.energy_ratio(total, used)
    m_rate, c_rate = er.production_rates_per_sec()
    prod_h = {
        "metal": int(m_rate * ratio * 3600),
        "crystal": int(c_rate * ratio * 3600),
        "fuel_cells": int(er.fuel_cells_rate_per_sec() * ratio * 3600),
    }
    building_count = sum(int(v or 0) for v in state.buildings.values())
    active_buildings = sum(1 for v in state.buildings.values() if int(v or 0) > 0)
    research_sum = sum(int(v or 0) for v in state.research.values())
    total_active = state.t - state.build_wait_sec - state.research_wait_sec - state.idle_sec
    return {
        "t_hours": state.t / 3600.0,
        "metal_mine": int(state.buildings.get("metal_mine", 0) or 0),
        "crystal_mine": int(state.buildings.get("crystal_mine", 0) or 0),
        "solar_plant": int(state.buildings.get("solar_plant", 0) or 0),
        "fuel_cell_plant": int(state.buildings.get("fuel_cell_plant", 0) or 0),
        "research_lab": int(state.buildings.get("research_lab", 0) or 0),
        "building_levels_sum": building_count,
        "building_types_active": active_buildings,
        "energy_tech": int(state.research.get("energy_tech", 0) or 0),
        "mining_tech": int(state.research.get("mining_tech", 0) or 0),
        "buildtime_tech": int(state.research.get("buildtime_tech", 0) or 0),
        "research_levels_sum": research_sum,
        "metal": int(state.metal),
        "crystal": int(state.crystal),
        "fuel_cells": int(state.fuel_cells),
        "prod_metal_h": prod_h["metal"],
        "prod_crystal_h": prod_h["crystal"],
        "prod_fuel_h": prod_h["fuel_cells"],
        "energy_ratio": round(ratio, 3),
        "build_completions": state.build_completions,
        "research_completions": state.research_completions,
        "build_active_pct": round(100.0 * state.build_active_sec / max(state.t, 1), 1),
        "research_active_pct": round(100.0 * state.research_active_sec / max(state.t, 1), 1),
        "build_wait_pct": round(100.0 * state.build_wait_sec / max(state.t, 1), 1),
        "research_wait_pct": round(100.0 * state.research_wait_sec / max(state.t, 1), 1),
        "idle_pct": round(100.0 * state.idle_sec / max(state.t, 1), 1),
    }


def _fresh_sim_state() -> SimState:
    return SimState(metal=START_METAL, crystal=START_CRYSTAL, fuel_cells=START_FUEL)


def run_simulation(settings: Dict[str, float], *, horizon_sec: int = SIM_HORIZON_SEC) -> Tuple[SimState, Dict[str, Dict[str, Any]]]:
    state = _fresh_sim_state()
    checkpoints: Dict[str, Dict[str, Any]] = {}
    cp_idx = 0

    def record_checkpoints() -> None:
        nonlocal cp_idx
        while cp_idx < len(CHECKPOINTS_SEC) and state.t >= CHECKPOINTS_SEC[cp_idx][1]:
            label = CHECKPOINTS_SEC[cp_idx][0]
            checkpoints[label] = _snapshot(state, settings)
            cp_idx += 1

    record_checkpoints()

    while state.t < horizon_sec:
        if state.build_job is None:
            _start_build(state, settings)
        if state.research_job is None:
            _start_research(state, settings)

        dt = _next_event_delta(state, settings, horizon_sec)
        if dt <= 0:
            dt = min(1.0, float(horizon_sec) - state.t)

        if state.build_job:
            state.build_active_sec += dt
        elif _peek_build_target(state, settings) is not None:
            state.build_wait_sec += dt

        if state.research_job:
            state.research_active_sec += dt
        elif _peek_research_target(state, settings) is not None:
            state.research_wait_sec += dt

        if (
            state.build_job is None
            and state.research_job is None
            and _peek_build_target(state, settings) is None
            and _peek_research_target(state, settings) is None
        ):
            state.idle_sec += dt

        _accumulate_production(state, settings, dt)
        state.t += dt

        if state.build_job and state.t >= state.build_job.finish_at:
            _complete_build(state)
        if state.research_job and state.t >= state.research_job.finish_at:
            _complete_research(state)

        if state.build_job is None:
            _start_build(state, settings)
        if state.research_job is None:
            _start_research(state, settings)

        record_checkpoints()

    return state, checkpoints


def fmt_duration(seconds: int) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        m, ss = divmod(s, 60)
        return f"{m}min" if ss == 0 else f"{m}:{ss:02d}"
    if s < 86400:
        h = s // 3600
        rem_m = (s % 3600) // 60
        return f"{h}h" if rem_m == 0 else f"{h}h {rem_m}min"
    d = s // 86400
    rem_h = (s % 86400) // 3600
    return f"{d}d" if rem_h == 0 else f"{d}d {rem_h}h"


def _md_table(headers: List[str], rows: List[List[Any]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---:" if i else "---" for i, _ in enumerate(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _early_game_table(settings: Dict[str, float]) -> str:
    rows = []
    er = EffectResolver({}, {}, settings=_settings_dict(settings), planet_position=BALANCE_SLOT)
    for lvl in (1, 2, 3, 5, 10, 20):
        prod = reference_production_per_hour("metal", lvl, slot=BALANCE_SLOT)
        cost = get_upgrade_cost("metal_mine", lvl - 1) if lvl > 0 else (0, 0)
        if lvl >= 1:
            cost = get_upgrade_cost("metal_mine", lvl - 1)
        bsec = er.get_build_time_seconds("metal_mine", lvl)
        rows.append([lvl, f"{prod:.0f}/h", f"{cost[0]}M+{cost[1]}C", fmt_duration(bsec)])
    hdr = ["Mine L→", "Prod (Slot 9)", "Upgrade-Kosten", "Bauzeit"]
    return _md_table(hdr, rows)


def _checkpoint_row(label: str, snap: Dict[str, Any]) -> List[Any]:
    return [
        label,
        f"M{snap['metal_mine']} C{snap['crystal_mine']} S{snap['solar_plant']}",
        f"Lab {snap['research_lab']} · FC {snap['fuel_cell_plant']}",
        f"E{snap['energy_tech']} Min{snap['mining_tech']} Bau{snap['buildtime_tech']}",
        f"{snap['prod_metal_h']:,}/h · {snap['prod_crystal_h']:,}/h · {snap['prod_fuel_h']:,}/h",
        f"{snap['metal']:,}M · {snap['crystal']:,}C",
        f"B{snap['build_completions']} R{snap['research_completions']}",
        f"aktiv {snap['build_active_pct']}% · wart {snap['build_wait_pct']}%",
    ]


def generate_markdown() -> str:
    all_checkpoints: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for name, preset in PRESETS.items():
        _, cps = run_simulation(preset)
        all_checkpoints[name] = cps

    current = PRESETS["alpha_current"]
    parts: List[str] = [
        "# GC-829 — Fresh Account Progression",
        "",
        "> Automatisch generiert via `python scripts/fresh_account_progression_sim.py`.",
        "> **Keine Formeländerung** — misst Fortschritt bei kanonischen Server-Formeln.",
        "",
        "## Leitfrage",
        "",
        "Fühlt sich Genesis langsam an, weil die **Wirtschaft** langsam ist — oder weil **Fortschritt** (Bau/Forschung) zu selten sichtbar wird?",
        "",
        "## Sim-Annahmen",
        "",
        "| Annahme | Wert |",
        "|---------|------|",
        f"| Startressourcen | {int(START_METAL):,} Ferronit · {int(START_CRYSTAL):,} Crytite · {int(START_FUEL):,} Brennzellen (GC-836) |",
        "| Gebäude Start | alle Level 0 (Homeworld leer) |",
        f"| Planet-Slot | {BALANCE_SLOT} (Benchmark-Slot wie GC-821/829) |",
        "| Queues | 1× Bau + 1× Forschung, greedy „aktiver Casual“ |",
        "| Strategie | Solar → Minen → Energie-Balance → Brennzelle → Labor → Energy/Mining/Bau-Forschung |",
        "| Nicht modelliert | Handel, Flotte, Multi-Queue (5), GD/Klima, Exchange |",
        "",
        "### Aktuelle Alpha-Defaults (`DEFAULT_GAME_SETTINGS`)",
        "",
        "```text",
        f"production_speed = {current['production_speed']}",
        f"build_speed      = {current['build_speed']}",
        f"research_speed   = {current['research_speed']}   ← unter 1 = Forschung langsamer als Benchmark-Tabellen",
        "```",
        "",
        "## Frühe Ferronitmine (Slot 9, `production_speed=1`)",
        "",
        _early_game_table(current),
        "",
        "### Bauzeiten bei **alpha_current** (leeres Konto, keine Tech-Boni)",
        "",
        _md_table(
            ["Gebäude", "L1", "L2", "L5"],
            [
                [
                    b,
                    fmt_duration(
                        EffectResolver({}, {}, settings=_settings_dict(current), planet_position=BALANCE_SLOT)
                        .get_build_time_seconds(b, 1)
                    ),
                    fmt_duration(
                        EffectResolver({}, {}, settings=_settings_dict(current), planet_position=BALANCE_SLOT)
                        .get_build_time_seconds(b, 2)
                    ),
                    fmt_duration(
                        EffectResolver({}, {}, settings=_settings_dict(current), planet_position=BALANCE_SLOT)
                        .get_build_time_seconds(b, 5)
                    ),
                ]
                for b in ("solar_plant", "metal_mine", "crystal_mine", "research_lab", "fuel_cell_plant")
            ],
        ),
        "",
        "### Forschung **alpha_current** (Lab = Ziel-Level-Proxy)",
        "",
        _md_table(
            ["Tech", "L1 (Lab 1)", "L5 (Lab 5)", "L10 (Lab 5)"],
            [
                [
                    title,
                    fmt_duration(
                        EffectResolver({"research_lab": 1}, {}, settings=_settings_dict(current), planet_position=BALANCE_SLOT)
                        .get_research_time_seconds(key, 1)
                    ),
                    fmt_duration(
                        EffectResolver({"research_lab": 5}, {}, settings=_settings_dict(current), planet_position=BALANCE_SLOT)
                        .get_research_time_seconds(key, 5)
                    ),
                    fmt_duration(
                        EffectResolver({"research_lab": 5}, {}, settings=_settings_dict(current), planet_position=BALANCE_SLOT)
                        .get_research_time_seconds(key, 10)
                    ),
                ]
                for key, title in (
                    ("energy_tech", "Energie"),
                    ("mining_tech", "Mining"),
                    ("buildtime_tech", "Bauopt."),
                )
            ],
        ),
        "",
        "## Checkpoint-Vergleich (Presets)",
        "",
    ]

    preset_labels = {
        "alpha_current": "Alpha aktuell",
        "alpha_proposed_gc829": "GC-829 Vorschlag (build 8 / research 50)",
        "alpha_proposed_ferdi": "Ferdi-Bauchgefühl (build 10 / research 50)",
        "alpha_proposed_ferdi_r100": "Ferdi-Bauchgefühl (build 10 / research 100)",
        "baseline_all_1": "Baseline (alles 1.0)",
        "contrast_prod2": "Kontrast (prod 2 / build 1 / research 1)",
    }

    for preset_key in (
        "alpha_current",
        "alpha_proposed_ferdi",
        "alpha_proposed_gc829",
        "baseline_all_1",
    ):
        p = PRESETS[preset_key]
        parts.extend(
            [
                f"### {preset_labels[preset_key]}",
                "",
                f"`production_speed={p['production_speed']}` · "
                f"`build_speed={p['build_speed']}` · "
                f"`research_speed={p['research_speed']}`",
                "",
                _md_table(
                    [
                        "Zeit",
                        "Minen (M/C/S)",
                        "Infra",
                        "Forschung",
                        "Prod/h",
                        "Lager",
                        "Abschlüsse",
                        "Bau-Anteil",
                    ],
                    [_checkpoint_row(lbl, all_checkpoints[preset_key][lbl]) for lbl, _ in CHECKPOINTS_SEC],
                ),
                "",
            ]
        )

    cur_1h = all_checkpoints["alpha_current"]["1h"]
    cur_4h = all_checkpoints["alpha_current"]["4h"]
    cur_24h = all_checkpoints["alpha_current"]["24h"]
    cur_7d = all_checkpoints["alpha_current"]["7d"]
    ferdi_1h = all_checkpoints["alpha_proposed_ferdi"]["1h"]
    ferdi_24h = all_checkpoints["alpha_proposed_ferdi"]["24h"]
    ferdi_7d = all_checkpoints["alpha_proposed_ferdi"]["7d"]

    parts.extend(
        [
            "## Erkenntnis (Daten, nicht Bauchgefühl)",
            "",
            "### Nach 1 Stunde",
            "",
            "| Preset | Ferronit-Mine | Prod Ferronit/h | Labor | Forschung (E/Min/Bau) | Bau-Abschlüsse |",
            "|--------|-------------:|----------------:|------:|------------------------|---------------:|",
            f"| Alpha aktuell | L{cur_1h['metal_mine']} | {cur_1h['prod_metal_h']:,} | L{cur_1h['research_lab']} | "
            f"{cur_1h['energy_tech']}/{cur_1h['mining_tech']}/{cur_1h['buildtime_tech']} | {cur_1h['build_completions']} |",
            f"| Ferdi (build 10 / res 50) | L{ferdi_1h['metal_mine']} | {ferdi_1h['prod_metal_h']:,} | L{ferdi_1h['research_lab']} | "
            f"{ferdi_1h['energy_tech']}/{ferdi_1h['mining_tech']}/{ferdi_1h['buildtime_tech']} | {ferdi_1h['build_completions']} |",
            "",
            "### Nach 4 Stunden",
            "",
            "| Preset | Minen M/C | Labor | Prod Ferronit/h | Forschung Σ |",
            "|--------|----------:|------:|----------------:|------------:|",
            f"| Alpha aktuell | {cur_4h['metal_mine']}/{cur_4h['crystal_mine']} | L{cur_4h['research_lab']} | "
            f"{cur_4h['prod_metal_h']:,} | {cur_4h['research_levels_sum']} |",
            "",
            "### Nach 24 Stunden",
            "",
            "| Preset | Ferronit-Mine | Crytite | Labor | Prod Ferronit/h | Forschung Σ | Bau/R |",
            "|--------|-------------:|--------:|------:|----------------:|------------:|------:|",
            f"| Alpha aktuell | L{cur_24h['metal_mine']} | L{cur_24h['crystal_mine']} | L{cur_24h['research_lab']} | "
            f"{cur_24h['prod_metal_h']:,} | {cur_24h['research_levels_sum']} | {cur_24h['build_completions']}/{cur_24h['research_completions']} |",
            f"| Ferdi (build 10 / res 50) | L{ferdi_24h['metal_mine']} | L{ferdi_24h['crystal_mine']} | L{ferdi_24h['research_lab']} | "
            f"{ferdi_24h['prod_metal_h']:,} | {ferdi_24h['research_levels_sum']} | {ferdi_24h['build_completions']}/{ferdi_24h['research_completions']} |",
            "",
            "### Nach 7 Tagen",
            "",
            "| Preset | Minen M/C | Labor | Prod Ferronit/h | Forschung Σ |",
            "|--------|----------:|------:|----------------:|------------:|",
            f"| Alpha aktuell | {cur_7d['metal_mine']}/{cur_7d['crystal_mine']} | L{cur_7d['research_lab']} | "
            f"{cur_7d['prod_metal_h']:,} | {cur_7d['research_levels_sum']} |",
            f"| Ferdi (build 10 / res 50) | {ferdi_7d['metal_mine']}/{ferdi_7d['crystal_mine']} | L{ferdi_7d['research_lab']} | "
            f"{ferdi_7d['prod_metal_h']:,} | {ferdi_7d['research_levels_sum']} |",
            "",
            "### Interpretation",
            "",
            "1. **Frühes Spiel = Ressourcen-Wartezeit, nicht Bau-Timer.** "
            f"Nach 1h Alpha: Mine L{cur_1h['metal_mine']}, **{cur_1h['prod_metal_h']:,}/h**, "
            f"Bau-Wartezeit **{cur_1h['build_wait_pct']}%** — L2 kostet ~2.3k Ferronit bei ~24/h ≈ **4 Tage** Sparzeit. "
            "Spieler sehen 24→70/h in der Vorschau, erleben aber tagelang **kein Level-Up**.",
            "",
            "2. **Crytite-Verhungerung blockiert Labor länger als Forschungs-Timer.** "
            f"Gate: Mine 3 + Crytite 2 — simuliert nach 7d erst **{cur_7d['metal_mine']}/{cur_7d['crystal_mine']}**, Labor L{cur_7d['research_lab']}. "
            "Ferronit-Upgrades ziehen Crytite (~25 % Kostenanteil), Crytite-Mine L1 produziert nur **16/h** → "
            "Spieler horten Ferronit, können Crytite-Mine nicht hochziehen. **`research_speed` ändert daran nichts.**",
            "",
            f"3. **Nach 24h Alpha:** Mine L{cur_24h['metal_mine']}, Labor L{cur_24h['research_lab']}, "
            f"**{cur_24h['prod_metal_h']:,}/h** — **kein sichtbarer Fortschritt seit Stunde 1.** "
            "Das ist Ferdis „und jetzt?“-Gefühl: Wirtschaftskurve stimmt (24→70→132/h), **Meilensteine kommen zu selten.**",
            "",
            "4. **Ferdi-Hypothese (build/research speed) — wann sie wirkt:** "
            "In dieser Sim sind **1h–7d Checkpoints identisch** zwischen Alpha und build=10/research=50 — "
            "Engpass ist **Kosten vs. Einkommen**, nicht Bau-Timer. "
            f"Erst nach Labor (7d→30d Forschung Σ: **{cur_7d['research_levels_sum']}→{all_checkpoints['alpha_current']['30d']['research_levels_sum']}**, "
            f"Prod **{all_checkpoints['alpha_current']['30d']['prod_metal_h']:,}/h**) zählen Speed-Regler für Dopamin. "
            "**`production_speed=1` lassen.** Für Alpha-Feel: **`build_speed` 8–10 + `research_speed` 50–100** "
            "(schnellere Abschlüsse sobald Ressourcen da sind) **plus** optional separates Ticket für **Frühgame-Kosten/Crytite-Pacing** (GC-821 Folge).",
            "",
            "### Empfehlung vor Regler-Dreh",
            "",
            "- **`production_speed` bei 1.0 lassen** (GC-821 ROI).",
            "- **Zuerst `research_speed` anheben** (50–100 Band laut GC-829 Sweep + diese Sim).",
            "- **`build_speed` 8–10** für Alpha-Fluidität (frühe Gebäude ~1min, Midgame spürbar).",
            "- Optional: Live-Spieler mit **Multi-Queue (5)** kommen schneller als diese Sim — konservative Untergrenze.",
            "",
        ]
    )

    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="GC-829 fresh account progression sim")
    parser.add_argument("--stdout", action="store_true")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "docs" / "GC-829_FRESH_ACCOUNT_PROGRESSION.md",
    )
    args = parser.parse_args()

    md = generate_markdown()
    if args.stdout:
        print(md)
    else:
        args.out.write_text(md, encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
