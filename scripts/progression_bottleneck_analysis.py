#!/usr/bin/env python3
"""GC progression-bottleneck analysis (measurement only, no gameplay change).

Question: why does the build queue run only a few percent of the time, and which brakes really
limit progression after 6 / 12 / 24 months?

Method (everything is executed by ``scripts/player_journey_sim.py`` through the canonical owners
in a throw-away sandbox; nothing here touches a live database or a production formula):

1. **Exclusive time ledger.**  Every second of every world's life is attributed to exactly one
   cause: queue running, waiting for metal / crystal (binding resource), waiting for a depot
   upgrade, energy drag on the wait, missing research prerequisite, nothing to build, or *player
   latency* (the purchase was already affordable but the player was not acting).  The ledger sums
   to the world's age (tested).  Research and the colony pipeline get their own ledgers.
2. **Production losses.**  Metal/crystal/fuel lost to full depots and to energy shortage.
3. **Counterfactual levers.**  Simulation-only switches that remove or scale one brake
   (instant construction, instant research, free research cost, free energy, unlimited depots,
   no PL15 colony chain, +25 % income).  The progression gained when a brake is removed is its
   cost.  Levers are measurements, not proposals and not player routes.
4. **Two legal decision policies.**  ``pj-policy/1`` (goal list + 6 h patience) and the improved
   ``pj-policy/2`` (payback-ranked purchases, saving for the best one, dynamic priority by
   bottleneck; same costs, same queue depth, same action windows).  The gap between them is the
   part of the idle time that is a *policy artefact* rather than a game rule.

Run:
  python scripts/progression_bottleneck_analysis.py --out-json artifacts/progression_bottlenecks/latest.json \
      --out-md docs/GC_PROGRESSION_BOTTLENECK_REPORT.md
  python scripts/progression_bottleneck_analysis.py --quick --stdout     # 60-day smoke run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ANALYSIS_VERSION = "progression-bottlenecks/1"
STYLES: Tuple[str, ...] = ("casual", "active", "optimizer")
TOPOLOGIES: Tuple[str, ...] = ("S1", "S11")
STRATEGIES: Tuple[str, ...] = ("v1", "v2")
DAYS = 730.0
CHECK_DAYS: Tuple[str, ...] = ("182.5", "365", "730")
CHECK_LABEL = {"182.5": "6 months (182.5 d)", "365": "12 months (365 d)", "730": "24 months (730 d)"}
MINE_MILESTONES: Tuple[int, ...] = (50, 100, 150, 200)

# ledger columns in report order: (key, header)
LEDGER_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("busy", "Queue running"),
    ("wait_metal", "Wait metal"),
    ("wait_crystal", "Wait crystal"),
    ("wait_storage_build", "Wait depot build"),
    ("wait_energy_drag", "Energy drag"),
    ("research_prerequisite", "Research prereq."),
    ("no_goal", "Nothing to build"),
    ("player_not_acting", "Player latency"),
)
RULE_CAUSES = ("wait_metal", "wait_crystal", "wait_storage_build", "wait_energy_drag", "research_prerequisite", "storage_cap_below_cost", "no_goal")

COLONY_LEVERS = frozenset({"no_colony_chain", "colony_gate_pl10", "colony_gate_pl5", "colony_xp_x1.1", "colony_xp_x1.25"})
NOT_REACHED_DAY = 731  # milestone not reached inside the 730-day horizon

LEVER_BRAKE = {
    "instant_build": "Construction duration",
    "instant_research": "Research duration",
    "free_research_cost": "Research resource sink",
    "free_energy": "Energy supply",
    "free_storage": "Depot capacity",
    "no_colony_chain": "Serial PL15 colony chain",
    "income_x1.25": "Income vs cost growth (elasticity, +25 % income)",
    "build_time_x0.88": "Candidate: -12 % construction time",
    "research_time_x0.88": "Candidate: -12 % research time",
    "colony_gate_pl10": "Candidate: colony gate at PL10 (instead of PL15)",
    "colony_gate_pl5": "Candidate: colony gate at PL5 (instead of PL15)",
    "auto_start": "Candidate: reserve the next purchase, start when funds arrive",
    "res_cost_x0.9": "Candidate resonance: -10 % research cost",
    "mine_cost_x0.9": "Candidate resonance: -10 % mine/solar upgrade cost",
    "storage_cap_x1.1": "Candidate resonance: +10 % depot capacity",
    "colony_xp_x1.1": "Candidate resonance: +10 % colony planet XP",
    "colony_xp_x1.25": "Candidate: +25 % colony planet XP",
}


# ---------------------------------------------------------------------------
# Scenario matrix and worker
# ---------------------------------------------------------------------------


def build_matrix(days: float, quick: bool, levers: Optional[List[str]] = None, with_baseline: bool = True) -> List[Dict[str, Any]]:
    from scripts import player_journey_sim as pj

    if levers is None:
        levers = [k for k in pj.LEVERS if k != "none" and k not in pj.ASCENSION_ONLY_LEVERS]
        if quick:
            levers = ["instant_build", "free_storage", "no_colony_chain"]
    styles = ("active",) if quick else STYLES
    out: List[Dict[str, Any]] = []
    for strategy in STRATEGIES:
        for topo in TOPOLOGIES:
            for style in styles:
                for lever in (["none"] if with_baseline else []) + list(levers):
                    if lever in COLONY_LEVERS and topo != "S11":
                        continue
                    sid = f"{topo}-{style}-{strategy}" + ("" if lever == "none" else f"-{lever}")
                    out.append(
                        {
                            "sid": sid,
                            "topology": topo,
                            "policy": style,
                            "strategy": strategy,
                            "lever": lever,
                            "days": float(days),
                            # S11 uses the homeworld whose DNA offers specialisations (mandate route via ascension);
                            # the economy does not depend on DNA, only the apex-mandate route does.
                            "rng_seed": pj.ELIGIBLE_HOME_SEED if topo == "S11" else None,
                        }
                    )
    return out


def _slim_snapshot(c: Dict[str, Any]) -> Dict[str, Any]:
    keep = (
        "day", "worlds", "established", "mine_depth_max", "mine_depth_median", "mine_depth_min", "crystal_depth_max",
        "empire_metal_h", "empire_crystal_h", "empire_fuel_h", "hw_planet_level", "planet_levels", "research",
        "research_time_ledger_sec", "colony_pipeline_sec", "elapsed_sec", "spend_metal", "spend_crystal",
        "spend_fuel_cells", "xp_by_source", "research_queue_busy_pct",
    )
    out = {k: c.get(k) for k in keep if k in c}
    pw_keep = (
        "idx", "climate", "outpost", "age_sec", "time_ledger_sec", "wasted_metal", "wasted_crystal", "wasted_fuel",
        "produced_metal", "produced_crystal", "produced_fuel", "lost_to_energy_metal", "lost_to_energy_crystal",
        "lost_to_energy_fuel", "energy_low_days", "storage_full_days", "planet_level", "queue_busy_pct",
    )
    out["per_world"] = [{k: w.get(k) for k in pw_keep} for w in c.get("per_world", [])]
    return out


def run_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Run one scenario (executed in a worker process: the sandbox owns process-global state)."""
    from scripts import player_journey_sim as pj

    sc = pj.Scenario(
        spec["sid"], spec["topology"], spec["policy"], "mid", "none", float(spec["days"]),
        rng_seed=spec.get("rng_seed"), lever=spec["lever"], strategy=spec["strategy"],
    )
    res = pj.run_scenario(sc)
    days = float(spec["days"])
    snaps: Dict[str, Any] = {}
    for key, label in (("182.5", "day182.5"), ("365", "day365")):
        if float(key) <= days and res["checkpoints"].get(label):
            snaps[key] = _slim_snapshot(res["checkpoints"][label])
    snaps[("%g" % days) if ("%g" % days) in CHECK_DAYS else "end"] = _slim_snapshot(res["final"])
    milestones: Dict[str, Optional[int]] = {}
    for level in MINE_MILESTONES:
        milestones[str(level)] = next((int(r["day"]) for r in res["daily"] if int(r["mine_depth_max"]) >= level), None)
    founded = [e["day"] for e in res["colony_log"] if e["event"] == "founded"]
    return {
        "sid": spec["sid"],
        "topology": spec["topology"],
        "policy": spec["policy"],
        "strategy": spec["strategy"],
        "policy_version": res["policy_version"],
        "lever": spec["lever"],
        "lever_label": res["lever_label"],
        "days": days,
        "status": res["status"],
        "wall_seconds": res["wall_seconds"],
        "snapshots": snaps,
        "mine_milestone_day": milestones,
        "colonies_founded_day": founded,
        "mandates_earned": [dict(e) for e in res.get("mandates", {}).get("earned", [])],
        "blockers": {k: {"first_day": v["first_day"], "days_observed": v["days_observed"]} for k, v in res["blockers"].items()},
        "invariants": res["invariants"],
        "daily_mine_depth": [(int(r["day"]), int(r["mine_depth_max"]), int(r["worlds"])) for r in res["daily"][::5]],
    }


def run_matrix(specs: List[Dict[str, Any]], workers: int, progress: bool = True) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    started = time.time()
    if workers <= 1:
        for i, spec in enumerate(specs, 1):
            results.append(run_spec(spec))
            if progress:
                print(f"[{i}/{len(specs)}] {spec['sid']} ({time.time() - started:.0f}s)", file=sys.stderr, flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_spec, s): s for s in specs}
            for i, fut in enumerate(as_completed(futures), 1):
                results.append(fut.result())
                if progress:
                    print(f"[{i}/{len(specs)}] {futures[fut]['sid']} ({time.time() - started:.0f}s)", file=sys.stderr, flush=True)
    results.sort(key=lambda r: r["sid"])
    return results


# ---------------------------------------------------------------------------
# Aggregation helpers (pure functions over slim results; unit-tested)
# ---------------------------------------------------------------------------


def find(results: List[Dict[str, Any]], topology: str, style: str, strategy: str, lever: str = "none") -> Optional[Dict[str, Any]]:
    for r in results:
        if r["topology"] == topology and r["policy"] == style and r["strategy"] == strategy and r["lever"] == lever:
            return r
    return None


def snap(res: Optional[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    if not res:
        return None
    s = res["snapshots"].get(key)
    if s is None and key == "730":
        s = res["snapshots"].get("end")
    return s


def income(s: Dict[str, Any]) -> float:
    return float(s["empire_metal_h"]) + float(s["empire_crystal_h"])


def ledger_shares(s: Dict[str, Any]) -> Dict[str, float]:
    """Share (percent) of all world-seconds per cause; sums to 100 over the keys incl. storage_cap_below_cost."""
    total_age = sum(float(w["age_sec"]) for w in s["per_world"])
    out: Dict[str, float] = {}
    if total_age <= 0:
        return out
    for w in s["per_world"]:
        for k, v in (w.get("time_ledger_sec") or {}).items():
            out[k] = out.get(k, 0.0) + float(v)
    return {k: 100.0 * v / total_age for k, v in out.items()}


def ledger_delta_shares(end: Dict[str, Any], start: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Ledger shares of the interval (start, end] only, e.g. months 12-24."""
    start_by = {w["idx"]: w for w in (start["per_world"] if start else [])}
    total = 0.0
    acc: Dict[str, float] = {}
    for w in end["per_world"]:
        s0 = start_by.get(w["idx"])
        age = float(w["age_sec"]) - (float(s0["age_sec"]) if s0 else 0.0)
        if age <= 0:
            continue
        total += age
        for k, v in (w.get("time_ledger_sec") or {}).items():
            acc[k] = acc.get(k, 0.0) + float(v) - (float((s0.get("time_ledger_sec") or {}).get(k, 0.0)) if s0 else 0.0)
    return {k: 100.0 * v / total for k, v in acc.items()} if total > 0 else {}


def ledger_conservation_error(s: Dict[str, Any]) -> float:
    """Largest |sum(causes) - age| / age over worlds (must be ~0)."""
    worst = 0.0
    for w in s["per_world"]:
        age = float(w["age_sec"])
        if age <= 0:
            continue
        worst = max(worst, abs(sum((w.get("time_ledger_sec") or {}).values()) - age) / age)
    return worst


def production_losses(s: Dict[str, Any]) -> Dict[str, float]:
    """Percent of the potential production lost to full depots / energy shortage, per resource."""
    out: Dict[str, float] = {}
    for res_key in ("metal", "crystal", "fuel"):
        produced = sum(float(w[f"produced_{res_key}"]) for w in s["per_world"])
        wasted = sum(float(w[f"wasted_{res_key}"]) for w in s["per_world"])
        lost_e = sum(float(w[f"lost_to_energy_{res_key}"]) for w in s["per_world"])
        potential = produced + wasted
        out[f"depot_{res_key}"] = 100.0 * wasted / potential if potential > 0 else 0.0
        out[f"energy_{res_key}"] = 100.0 * lost_e / (produced + wasted + lost_e) if (produced + wasted + lost_e) > 0 else 0.0
    return out


def shares_of(dct: Dict[str, float]) -> Dict[str, float]:
    total = sum(float(v) for v in dct.values())
    return {k: 100.0 * float(v) / total for k, v in dct.items()} if total > 0 else {}


def rel(a: float, b: float) -> Optional[float]:
    return 100.0 * (a - b) / b if b else None


def milestone_delta(results: List[Dict[str, Any]], topology: str, strategy: str, lever: str, level: int) -> Optional[float]:
    """Mean over play styles of (day the best mine reaches `level` with the lever) - (baseline day); negative = faster."""
    diffs: List[float] = []
    for style in STYLES:
        base, var = find(results, topology, style, strategy), find(results, topology, style, strategy, lever)
        if not base or not var:
            continue
        b = base["mine_milestone_day"].get(str(level))
        v = var["mine_milestone_day"].get(str(level))
        diffs.append(float(v if v is not None else NOT_REACHED_DAY) - float(b if b is not None else NOT_REACHED_DAY))
    return mean(diffs) if diffs else None


def eleventh_world_delta(results: List[Dict[str, Any]], topology: str, strategy: str, lever: str) -> Tuple[Optional[float], Optional[float]]:
    """(baseline mean day of the 11th world, mean change with the lever); days beyond the horizon count as 731."""
    base_days: List[float] = []
    diffs: List[float] = []
    for style in STYLES:
        base, var = find(results, topology, style, strategy), find(results, topology, style, strategy, lever)
        if not base or not var:
            continue
        b = float(base["colonies_founded_day"][9]) if len(base["colonies_founded_day"]) >= 10 else float(NOT_REACHED_DAY)
        v = float(var["colonies_founded_day"][9]) if len(var["colonies_founded_day"]) >= 10 else float(NOT_REACHED_DAY)
        base_days.append(b)
        diffs.append(v - b)
    return (mean(base_days), mean(diffs)) if diffs else (None, None)


def lever_deltas(results: List[Dict[str, Any]], topology: str, strategy: str, lever: str, key: str) -> Dict[str, Optional[float]]:
    """Mean over play styles of the relative change vs the same baseline: income and best mine depth, plus world delta."""
    d_inc: List[float] = []
    d_depth: List[float] = []
    d_worlds: List[float] = []
    for style in STYLES:
        base = snap(find(results, topology, style, strategy), key)
        var = snap(find(results, topology, style, strategy, lever), key)
        if not base or not var:
            continue
        v = rel(income(var), income(base))
        if v is not None:
            d_inc.append(v)
        v = rel(float(var["mine_depth_max"]), float(base["mine_depth_max"]))
        if v is not None:
            d_depth.append(v)
        d_worlds.append(float(var["worlds"]) - float(base["worlds"]))
    return {
        "income_pct": mean(d_inc) if d_inc else None,
        "depth_pct": mean(d_depth) if d_depth else None,
        "worlds_delta": mean(d_worlds) if d_worlds else None,
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _f(v: Optional[float], digits: int = 1, sign: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.{digits}f}" if sign else f"{v:.{digits}f}"


def _human(n: float) -> str:
    n = float(n)
    for threshold, suffix in ((1e15, "Qa"), (1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(n) >= threshold:
            return f"{n / threshold:.1f}{suffix}"
    return f"{int(n):,}"


def render_markdown(data: Dict[str, Any]) -> str:
    results: List[Dict[str, Any]] = data["results"]
    meta = data["meta"]
    L: List[str] = [
        "# GC - Progression Bottleneck Report (generated)",
        "",
        "> Generated by `python scripts/progression_bottleneck_analysis.py` - **measurement only**: no balance value, formula or live system is changed; every number comes from the sandboxed simulator (`scripts/player_journey_sim.py`) running the canonical economy owners.",
        f"> Code `{meta['code_sha'][:12]}` · analysis `{meta['analysis_version']}` · {meta['scenarios']} scenarios x {meta['days']:g} days · economy curve `{meta['economy_curve']}`.",
        "",
        "Policies: **v1** = `pj-policy/1` (goal list, 6 h patience; the policy of the earlier player-journey report). **v2** = `pj-policy/2` (improved but legal: payback-ranked purchases, saving for the best one, dynamic priority by bottleneck; same costs, queue depth and action windows). Play styles: casual (2 windows/day), active (4/day), optimizer (acts at every event). All runs: mid-climate homeworld, no paid accelerators, no loot, no expedition income.",
        "",
        "## 1. Where does the build-queue time go? (exclusive time ledger)",
        "",
        "Every second of every world's life is attributed to exactly one cause. *Queue running* = a construction is in progress. When the queue is empty the cause is: waiting for the **binding** resource (metal or crystal) of the next purchase, waiting for a depot upgrade the purchase needs, **energy drag** (the part of the wait caused by an energy ratio below 1), a missing research prerequisite, nothing left to build, or **player latency** (the purchase was already affordable but the player was not acting - action windows). Values are the empire's world-seconds share (all worlds weighted by age).",
        "",
        "Rules vs artefacts: *wait metal/crystal*, *depot build*, *energy drag* and *research prerequisite* come from the game rules. *Player latency* comes from the play pattern (windows). *Nothing to build* is a policy/content limit. Deuterium (fuel cells) does not appear: no building or research costs fuel (only Ark, ships and mandates do, see section 4).",
        "",
    ]
    for strategy in STRATEGIES:
        for topo in TOPOLOGIES:
            L += [f"### {strategy} - {'one planet (S1)' if topo == 'S1' else 'up to eleven planets (S11)'}", "", "| Style | Horizon | Worlds | " + " | ".join(h for _, h in LEDGER_COLUMNS) + " |", "|---|---|---:|" + "---:|" * len(LEDGER_COLUMNS)]
            for style in STYLES:
                res = find(results, topo, style, strategy)
                for key in CHECK_DAYS:
                    s = snap(res, key)
                    if not s:
                        continue
                    sh = ledger_shares(s)
                    cap = sh.get("storage_cap_below_cost", 0.0)
                    row = [(f"{_f(sh.get(k, 0.0) + (cap if k == 'no_goal' else 0.0))}%") for k, _ in LEDGER_COLUMNS]
                    L.append(f"| {style} | {CHECK_LABEL[key]} | {s['worlds']} | " + " | ".join(row) + " |")
            L.append("")
    L += ["### Months 12-24 only (late game, share of world-seconds between day 365 and day 730)", "", "| Policy | Topology | Style | Worlds @730 | " + " | ".join(h for _, h in LEDGER_COLUMNS) + " |", "|---|---|---|---:|" + "---:|" * len(LEDGER_COLUMNS)]
    for strategy in STRATEGIES:
        for topo in TOPOLOGIES:
            for style in STYLES:
                res = find(results, topo, style, strategy)
                end, mid = snap(res, "730"), snap(res, "365")
                if not end or not mid:
                    continue
                sh = ledger_delta_shares(end, mid)
                cap = sh.get("storage_cap_below_cost", 0.0)
                row = [(f"{_f(sh.get(k, 0.0) + (cap if k == 'no_goal' else 0.0))}%") for k, _ in LEDGER_COLUMNS]
                L.append(f"| {strategy} | {topo} | {style} | {end['worlds']} | " + " | ".join(row) + " |")
    L += [
        "",
        "`Nothing to build` includes the (small) time in which the next purchase exceeded the depot and no depot upgrade was possible.",
        "",
        "### Read-out: rule-bound vs policy-bound idle time (12 months, share of world-seconds)",
        "",
        "| Policy | Topology | Style | Queue running | Rule-bound wait (resources, depot, energy, research) | Player latency | Nothing to build |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for strategy in STRATEGIES:
        for topo in TOPOLOGIES:
            for style in STYLES:
                s = snap(find(results, topo, style, strategy), "365")
                if not s:
                    continue
                sh = ledger_shares(s)
                rule = sum(sh.get(k, 0.0) for k in RULE_CAUSES if k != "no_goal" and k != "storage_cap_below_cost")
                L.append(f"| {strategy} | {topo} | {style} | {_f(sh.get('busy', 0.0))}% | {_f(rule)}% | {_f(sh.get('player_not_acting', 0.0))}% | {_f(sh.get('no_goal', 0.0) + sh.get('storage_cap_below_cost', 0.0))}% |")

    # losses
    L += ["", "## 2. Production lost to full depots and energy shortage", "", "Percent of the potential production of each resource (cumulative since day 0, all worlds).", "", "| Policy | Topology | Style | Horizon | Depot loss metal | crystal | fuel | Energy loss metal | crystal | fuel |", "|---|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for strategy in STRATEGIES:
        for topo in TOPOLOGIES:
            for style in STYLES:
                res = find(results, topo, style, strategy)
                for key in CHECK_DAYS:
                    s = snap(res, key)
                    if not s:
                        continue
                    pl = production_losses(s)
                    L.append(f"| {strategy} | {topo} | {style} | {CHECK_LABEL[key]} | {_f(pl['depot_metal'], 2)}% | {_f(pl['depot_crystal'], 2)}% | {_f(pl['depot_fuel'], 2)}% | {_f(pl['energy_metal'], 2)}% | {_f(pl['energy_crystal'], 2)}% | {_f(pl['energy_fuel'], 2)}% |")

    # research ledger
    L += ["", "## 3. Research queue (account level)", "", "| Policy | Topology | Style | Horizon | Running | Wait metal | Wait crystal | Energy drag | Nothing to research | Player latency |", "|---|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for strategy in STRATEGIES:
        for topo in TOPOLOGIES:
            for style in STYLES:
                res = find(results, topo, style, strategy)
                for key in CHECK_DAYS:
                    s = snap(res, key)
                    if not s:
                        continue
                    sh = shares_of(s.get("research_time_ledger_sec") or {})
                    L.append(f"| {strategy} | {topo} | {style} | {CHECK_LABEL[key]} | {_f(sh.get('busy', 0.0))}% | {_f(sh.get('wait_metal', 0.0))}% | {_f(sh.get('wait_crystal', 0.0))}% | {_f(sh.get('wait_energy_drag', 0.0))}% | {_f(sh.get('no_goal', 0.0))}% | {_f(sh.get('player_not_acting', 0.0))}% |")
    L += ["", "Research levels reached (12 months, active style):", "", "| Policy | Topology | mining_tech | crystal_tech | energy_tech | storage_tech | buildtime_tech |", "|---|---|---:|---:|---:|---:|---:|"]
    for strategy in STRATEGIES:
        for topo in TOPOLOGIES:
            s = snap(find(results, topo, "active", strategy), "365")
            if s:
                r = s.get("research") or {}
                L.append(f"| {strategy} | {topo} | {r.get('mining_tech', 0)} | {r.get('crystal_tech', 0)} | {r.get('energy_tech', 0)} | {r.get('storage_tech', 0)} | {r.get('buildtime_tech', 0)} |")

    # colony pipeline
    L += ["", "## 4. Colonisation pipeline (S11): what is the next colony waiting for?", "", "Share of the horizon spent in each state of the expansion pipeline (state = last evaluated gate; the player re-checks at every window, continuously for the optimizer).", ""]
    states: List[str] = []
    for r in results:
        if r["topology"] != "S11" or r["lever"] != "none":
            continue
        for key in CHECK_DAYS:
            s = snap(r, key)
            if s:
                for st in (s.get("colony_pipeline_sec") or {}):
                    if st not in states:
                        states.append(st)
    states.sort()
    L += ["| Policy | Style | Horizon | Worlds | " + " | ".join(f"`{st}`" for st in states) + " |", "|---|---|---|---:|" + "---:|" * len(states)]
    for strategy in STRATEGIES:
        for style in STYLES:
            res = find(results, "S11", style, strategy)
            for key in CHECK_DAYS:
                s = snap(res, key)
                if not s:
                    continue
                sh = shares_of(s.get("colony_pipeline_sec") or {})
                L.append(f"| {strategy} | {style} | {CHECK_LABEL[key]} | {s['worlds']} | " + " | ".join(f"{_f(sh.get(st, 0.0))}%" for st in states) + " |")
    L += ["", "Colony founding days (days since start):", "", "| Policy | Style | Lever | Founded on day | Worlds @730 | Status |", "|---|---|---|---|---:|---|"]
    for r in results:
        if r["topology"] == "S11" and r["lever"] in ("none", "no_colony_chain"):
            s = snap(r, "730")
            L.append(f"| {r['strategy']} | {r['policy']} | {r['lever']} | {', '.join('%g' % d for d in r['colonies_founded_day']) or '-'} | {s['worlds'] if s else '-'} | `{r['status']}` |")

    # progress metrics
    L += ["", "## 5. Progress at 6 / 12 / 24 months and days to mine milestones", "", "Income = empire metal + crystal per hour. Mine depth = best metal-mine level.", "", "| Policy | Topology | Style | Depth 6 mo | 12 mo | 24 mo | Income 12 mo (M+C/h) | Income 24 mo | Day of L50 | L100 | L150 | L200 |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for strategy in STRATEGIES:
        for topo in TOPOLOGIES:
            for style in STYLES:
                res = find(results, topo, style, strategy)
                if not res:
                    continue
                s6, s12, s24 = snap(res, "182.5"), snap(res, "365"), snap(res, "730")
                ms = res["mine_milestone_day"]
                L.append(
                    f"| {strategy} | {topo} | {style} | L{s6['mine_depth_max'] if s6 else '-'} | L{s12['mine_depth_max'] if s12 else '-'} | L{s24['mine_depth_max'] if s24 else '-'} | "
                    f"{_human(income(s12)) if s12 else '-'} | {_human(income(s24)) if s24 else '-'} | " + " | ".join(str(ms.get(str(m)) if ms.get(str(m)) is not None else "-") for m in MINE_MILESTONES) + " |"
                )

    # stagnation and latency
    L += ["", "### Stagnation: growth between month 12 and month 24", "", "| Policy | Topology | Style | Income x (24 mo / 12 mo) | Best depth 12 mo -> 24 mo | Worlds 12 mo -> 24 mo |", "|---|---|---|---:|---:|---:|"]
    for strategy in STRATEGIES:
        for topo in TOPOLOGIES:
            for style in STYLES:
                res = find(results, topo, style, strategy)
                s12, s24 = snap(res, "365"), snap(res, "730")
                if s12 and s24:
                    ratio = income(s24) / income(s12) if income(s12) else 0.0
                    L.append(f"| {strategy} | {topo} | {style} | {ratio:.2f} | L{s12['mine_depth_max']} -> L{s24['mine_depth_max']} | {s12['worlds']} -> {s24['worlds']} |")
    L += ["", "### Cost of player latency (play pattern, not a rule): income relative to the always-online optimizer", "", "| Policy | Topology | Style | 6 mo | 12 mo | 24 mo |", "|---|---|---|---:|---:|---:|"]
    for strategy in STRATEGIES:
        for topo in TOPOLOGIES:
            ref = find(results, topo, "optimizer", strategy)
            for style in ("casual", "active"):
                res = find(results, topo, style, strategy)
                cells = []
                for key in CHECK_DAYS:
                    a, b = snap(res, key), snap(ref, key)
                    cells.append(f"{100.0 * income(a) / income(b):.0f}%" if a and b and income(b) else "n/a")
                L.append(f"| {strategy} | {topo} | {style} | " + " | ".join(cells) + " |")

    # policy gap
    L += ["", "## 6. Policy artefact: improved legal policy v2 vs v1 (same rules)", "", "Relative change of v2 against v1 (income = empire M+C per hour; worlds = absolute difference).", "", "| Topology | Style | Income 6 mo | 12 mo | 24 mo | Best depth 12 mo | Worlds 12 mo | Worlds 24 mo |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for topo in TOPOLOGIES:
        for style in STYLES:
            a, b = find(results, topo, style, "v1"), find(results, topo, style, "v2")
            cells = []
            for key in CHECK_DAYS:
                sa, sb = snap(a, key), snap(b, key)
                cells.append(_f(rel(income(sb), income(sa)), 0, True) + "%" if sa and sb else "n/a")
            s1, s2 = snap(a, "365"), snap(b, "365")
            e1, e2 = snap(a, "730"), snap(b, "730")
            L.append(
                f"| {topo} | {style} | {cells[0]} | {cells[1]} | {cells[2]} | "
                f"{_f(rel(float(s2['mine_depth_max']), float(s1['mine_depth_max'])), 0, True) + '%' if s1 and s2 else 'n/a'} | "
                f"{(s2['worlds'] - s1['worlds']) if s1 and s2 else 'n/a'} | {(e2['worlds'] - e1['worlds']) if e1 and e2 else 'n/a'} |"
            )

    # levers
    L += ["", "## 7. Counterfactual levers: what does each brake cost?", "", "Each lever removes or scales one brake (simulation only). Values are the mean over the three play styles of the relative change against the same baseline policy. A large positive number = a real brake; a number near zero = the removed brake was not limiting.", ""]
    for strategy in STRATEGIES:
        for topo in TOPOLOGIES:
            L += [f"### {strategy} - {topo}", "", "| Lever | Brake / candidate | Income 6 mo | 12 mo | 24 mo | Worlds delta 12 mo | Days to L150 (delta) | Days to L200 (delta) | 11th world (delta days) |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
            rows: List[Tuple[float, str]] = []
            for lever in LEVER_BRAKE:
                if lever in COLONY_LEVERS and topo != "S11":
                    continue
                d6 = lever_deltas(results, topo, strategy, lever, "182.5")
                d12 = lever_deltas(results, topo, strategy, lever, "365")
                d24 = lever_deltas(results, topo, strategy, lever, "730")
                if d12["income_pct"] is None:
                    continue
                m150 = milestone_delta(results, topo, strategy, lever, 150)
                m200 = milestone_delta(results, topo, strategy, lever, 200)
                base11, d11 = eleventh_world_delta(results, topo, strategy, lever) if topo == "S11" else (None, None)
                line = (
                    f"| `{lever}` | {LEVER_BRAKE[lever]} | {_f(d6['income_pct'], 1, True)}% | {_f(d12['income_pct'], 1, True)}% | {_f(d24['income_pct'], 1, True)}% | "
                    f"{_f(d12['worlds_delta'], 1, True)} | {_f(m150, 0, True)} | {_f(m200, 0, True)} | {('%s (base %.0f)' % (_f(d11, 0, True), base11)) if d11 is not None else '-'} |"
                )
                rows.append((float(d12["income_pct"]) + 10.0 * float(d12["worlds_delta"] or 0.0), line))
            rows.sort(key=lambda x: -x[0])
            L += [line for _, line in rows]
            L.append("")

    L += ["### Candidate mechanics by play style (policy v2, change of empire income against the same style without the lever)", "", "| Topology | Candidate | Style | Income 6 mo | 12 mo | 24 mo | Days to L200 (delta) |", "|---|---|---|---:|---:|---:|---:|"]
    for topo in TOPOLOGIES:
        for lever in ("auto_start", "colony_gate_pl10", "colony_gate_pl5", "colony_xp_x1.1", "colony_xp_x1.25", "build_time_x0.88", "research_time_x0.88", "res_cost_x0.9", "mine_cost_x0.9", "storage_cap_x1.1"):
            if lever in COLONY_LEVERS and topo != "S11":
                continue
            for style in STYLES:
                base, var = find(results, topo, style, "v2"), find(results, topo, style, "v2", lever)
                if not base or not var:
                    continue
                cells = []
                for key in CHECK_DAYS:
                    a, b = snap(var, key), snap(base, key)
                    cells.append((_f(rel(income(a), income(b)), 1, True) + "%") if a and b else "n/a")
                b200, v200 = base["mine_milestone_day"].get("200"), var["mine_milestone_day"].get("200")
                d200 = _f(float(v200 if v200 is not None else NOT_REACHED_DAY) - float(b200 if b200 is not None else NOT_REACHED_DAY), 0, True)
                L.append(f"| {topo} | `{lever}` | {style} | " + " | ".join(cells) + f" | {d200} |")
    L += ["", "Income of windowed players **with** `auto_start` relative to the always-online optimizer **without** it (policy v2):", "", "| Topology | Style | Baseline 6 / 12 / 24 mo | With `auto_start` 6 / 12 / 24 mo |", "|---|---|---|---|"]
    for topo in TOPOLOGIES:
        ref = find(results, topo, "optimizer", "v2")
        for style in ("casual", "active"):
            base, var = find(results, topo, style, "v2"), find(results, topo, style, "v2", "auto_start")
            if not (ref and base and var):
                continue

            def share(r: Dict[str, Any]) -> str:
                out = []
                for key in CHECK_DAYS:
                    a, b = snap(r, key), snap(ref, key)
                    out.append(f"{100.0 * income(a) / income(b):.0f}%" if a and b and income(b) else "n/a")
                return " / ".join(out)

            L.append(f"| {topo} | {style} | {share(base)} | {share(var)} |")
    L += [""]

    L += ["## 8. Invariants and assumptions", ""]
    bad = [r["sid"] for r in results if not r["invariants"]["ok"]]
    L.append("* Invariants (no negative stock, no duplicate completion, no queue overflow, admin cap respected): " + ("all scenarios OK." if not bad else "VIOLATIONS in " + ", ".join(bad)))
    worst = max((ledger_conservation_error(s) for r in results for s in r["snapshots"].values()), default=0.0)
    L.append(f"* Ledger conservation (sum of causes = world age): worst relative error {worst:.2e}.")
    L += [f"* {item}" for item in data.get("assumptions", [])]
    L += ["", "## Reproduce", "", "```bash", "python scripts/progression_bottleneck_analysis.py --out-json artifacts/progression_bottlenecks/latest.json --out-md docs/GC_PROGRESSION_BOTTLENECK_REPORT.md", "```", ""]
    return "\n".join(L)


ASSUMPTIONS = [
    "Baseline rules are the current `main` behaviour, including the open outpost-XP defect (colonies become unrestricted through colonise XP, PR #556 is not applied).",
    "Economy curve `uni1` = the same endgame production curve as the record-mine control; costs, timers, storage and energy come from EffectResolver / economy_balance / buildings / research.",
    "S11 uses the homeworld whose DNA has eligible specialisations so that mandates run through the ascension route; the economy itself does not depend on DNA.",
    "Expedition round trip 3 h, colony transit 2 h, no loot, no paid accelerators, no Timekeeper skips, research paid from the best-stocked established world (assumptions of the player-journey simulator).",
    "Player latency is an assumption about when the player is online (casual 09:00 and 21:00, active 07/12/17/22, optimizer always). It is not a measurement of real players.",
    "The colony pipeline state is the last evaluated gate; windowed styles can overstate a gate by at most one window (about 6-12 h per colony).",
    "Levers are counterfactual measurements: they say what a brake costs, not that it should be removed.",
]


def meta_block(specs: List[Dict[str, Any]], days: float, curve: str) -> Dict[str, Any]:
    from scripts import player_journey_sim as pj

    return {
        "analysis_version": ANALYSIS_VERSION,
        "sim_version": pj.SIM_VERSION,
        "policy_versions": pj.STRATEGY_VERSIONS,
        "code_sha": pj.code_sha(),
        "scenarios": len(specs),
        "days": days,
        "economy_curve": curve,
        "levers": pj.LEVERS,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="GC progression-bottleneck analysis (measurement only)")
    parser.add_argument("--days", type=float, default=DAYS)
    parser.add_argument("--quick", action="store_true", help="active style only, three levers (smoke run)")
    parser.add_argument("--workers", type=int, default=max(1, min(10, (os.cpu_count() or 2) - 2)))
    parser.add_argument("--levers", default=None, help="comma-separated lever subset (use with --merge-into)")
    parser.add_argument("--merge-into", type=Path, default=None, help="run only --levers (no baselines) and merge the results into this JSON by scenario id")
    parser.add_argument("--render-from", type=Path, default=None, help="re-render Markdown from an existing JSON result")
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--out-md", type=Path, default=None)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args(argv)

    if args.render_from:
        data = json.loads(args.render_from.read_text(encoding="utf-8"))
    elif args.merge_into:
        data = json.loads(args.merge_into.read_text(encoding="utf-8"))
        levers = [x for x in (args.levers or "").split(",") if x]
        fresh = run_matrix(build_matrix(args.days, False, levers=levers, with_baseline=False), args.workers)
        keep = {r["sid"]: r for r in data["results"]}
        keep.update({r["sid"]: r for r in fresh})
        data["results"] = sorted(keep.values(), key=lambda r: r["sid"])
        data["meta"]["scenarios"] = len(data["results"])
        args.out_json = args.out_json or args.merge_into
    else:
        specs = build_matrix(args.days, args.quick)
        results = run_matrix(specs, args.workers)
        data = {"meta": meta_block(specs, args.days, "uni1"), "assumptions": ASSUMPTIONS, "results": results}
    md = render_markdown(data)
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md, encoding="utf-8")
    if args.stdout or not (args.out_json or args.out_md):
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
