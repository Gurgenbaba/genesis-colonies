#!/usr/bin/env python3
"""Ascension milestones in the sandbox: First Awakening, record tiers, repeat resets (measurement only, no game change).

``rank1_fast`` (restart 75 % + rebuild cost x0.40 + one strong first Deep Yield rank) is a reference candidate with two weaknesses
(reward study, empire fairness): its first reset pays back in 556-802 days, and a second reset is strictly worse than none.  This
module prices three families of *counterfactual rule sets* (sandbox patch of the Nodebuster owner for one run, never a game change):

* **A - First Awakening**: a one-time, non-stacking output bonus once a mine has ascended, and cheaper first rebuilds.
* **B - Reconstruction milestones**: better rebuild options (restart level, rebuild cost) at higher record tiers.
* **C - Depth Breakthrough**: rewards are a function of the mine's *record depth* (``best_depth``), never of the number of resets.  The
  record only moves when a reset happens at a new depth, so repeating a reset at the same depth earns nothing by construction.

Acceptance (the user's, operationalised in ``criteria``): the first reset pays back within 6-12 months for every style; the second and
third reset have a visible benefit; no farming strategy is dominant over 72 months; ``never`` stays legitimate.

Run::

    python scripts/ascension_milestones_analysis.py --topology S1 --workers 10 --out-json artifacts/ascension_milestones/s1.json --out-md docs/GC_ASCENSION_MILESTONES_REPORT.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import ascension_empire_fairness as ef  # noqa: E402
from scripts import ascension_rewards_analysis as ar  # noqa: E402
from scripts.ascension_rewards_analysis import Candidate  # noqa: E402

ANALYSIS_VERSION = "ascension-milestones/1"
STYLES = ar.STYLES
DAYS = 2190.0

# First-reset window the user asked for: 6-12 months
PAYBACK_FAST_DAYS = 182
PAYBACK_OK_DAYS = 365
REPEAT_MIN_GAIN = 0.02  # the second reset must add at least this much cumulative production (vs `never`) over stopping after the first (median style)
REPEAT_MIN_STYLE = -0.02  # ... and no style may lose more than this by it
FARM_MARGIN = 0.02  # a farm may not beat the best sensible policy of its style by more than this

REFS: Tuple[str, ...] = ("canon", "rank1_fast", "fast_p10", "keep90_p10")
_NEW: Tuple[Candidate, ...] = (
    # A - First Awakening: one-time bonus once a mine has ascended (no AP), restart 75 %, rebuild cost x0.40
    Candidate("aw15", "A: awakening +15 % output, restart 75 %, cost x0.40", rebuild_cost_bps=4000, restart_pct=75, awaken_bps=1500),
    Candidate("aw20", "A: awakening +20 % output, restart 75 %, cost x0.40", rebuild_cost_bps=4000, restart_pct=75, awaken_bps=2000),
    Candidate("aw15_soft", "A: awakening +15 %, cheaper first rebuild (restart 85 %, cost x0.30)", rebuild_cost_bps=3000, restart_pct=85, awaken_bps=1500, cost_floor_bps=2500),
    Candidate("aw10_soft", "A: awakening +10 %, cheaper first rebuild (restart 85 %, cost x0.30)", rebuild_cost_bps=3000, restart_pct=85, awaken_bps=1000, cost_floor_bps=2500),
    # C - Depth Breakthrough on top of aw15: record tiers every 50 levels above L200 (max 3)
    Candidate("c_yield", "A+C: aw15 + output +5 % per record tier", rebuild_cost_bps=4000, restart_pct=75, awaken_bps=1500, tier_step=50, tier_cap=3, tier_yield_bps=500),
    Candidate("c_rebuild", "A+B+C: aw15 + restart +4 pp and cost -5 pp per record tier", rebuild_cost_bps=4000, restart_pct=75, awaken_bps=1500, tier_step=50, tier_cap=3, tier_restart_pp=4, tier_cost_bps=500, cost_floor_bps=2500),
    Candidate("c_both", "A+B+C: aw15 + output +3 %, restart +4 pp, cost -5 pp per record tier", rebuild_cost_bps=4000, restart_pct=75, awaken_bps=1500, tier_step=50, tier_cap=3, tier_yield_bps=300, tier_restart_pp=4, tier_cost_bps=500, cost_floor_bps=2500),
    Candidate("c_both25", "c_both with a record tier every 25 levels (finer steps)", rebuild_cost_bps=4000, restart_pct=75, awaken_bps=1500, tier_step=25, tier_cap=3, tier_yield_bps=300, tier_restart_pp=4, tier_cost_bps=500, cost_floor_bps=2500),
    Candidate("cs_both", "soft base (awakening +10 %, restart 80 %, cost x0.35) + tiers (+4 % output, +3 pp, -4 pp)", rebuild_cost_bps=3500, restart_pct=80, awaken_bps=1000, tier_step=50, tier_cap=3, tier_yield_bps=400, tier_restart_pp=3, tier_cost_bps=400, cost_floor_bps=2500),
)
# Round 2 (after the first screen: a second reset never paid because later rebuilds are as costly as the first and the tier rewards were small):
# generous rebuilds that get cheaper and faster with every record tier, a bigger output reward per tier, AP only for record progress (no AP loop
# at zero cost: a reset without a new record earns nothing), and ablations of each part.
_SOFT = dict(rebuild_cost_bps=3000, cost_floor_bps=1000, restart_pct=85, rebuild_time_bps=7000, time_floor_bps=2000)
_ROUND2: Tuple[Candidate, ...] = (
    Candidate("m1", "awakening +8 %, soft rebuild (restart 85 %, cost x0.30, time x0.70); per record tier +4 % output, -6 pp cost, -10 pp time; AP only for record progress", awaken_bps=800, tier_step=50, tier_cap=3, tier_yield_bps=400, tier_cost_bps=600, tier_time_bps=1000, ap_by_record=True, **_SOFT),
    Candidate("m2", "m1 + a fading rebuild surge (+50 % at level 0, 0 at the record)", awaken_bps=800, tier_step=50, tier_cap=3, tier_yield_bps=400, tier_cost_bps=600, tier_time_bps=1000, ap_by_record=True, surge_bps=5000, **_SOFT),
    Candidate("m3", "m1 with +6 % output per record tier", awaken_bps=800, tier_step=50, tier_cap=3, tier_yield_bps=600, tier_cost_bps=600, tier_time_bps=1000, ap_by_record=True, **_SOFT),
    Candidate("m4", "flatter: awakening +6 %, per tier +6 % output, -7 pp cost, -10 pp time", awaken_bps=600, tier_step=50, tier_cap=3, tier_yield_bps=600, tier_cost_bps=700, tier_time_bps=1000, ap_by_record=True, **_SOFT),
    Candidate("m5", "m1 with canonical AP (per reset, not per record)", awaken_bps=800, tier_step=50, tier_cap=3, tier_yield_bps=400, tier_cost_bps=600, tier_time_bps=1000, **_SOFT),
    Candidate("m6", "m1 with a record tier every 25 levels (finer steps)", awaken_bps=800, tier_step=25, tier_cap=3, tier_yield_bps=400, tier_cost_bps=600, tier_time_bps=1000, ap_by_record=True, **_SOFT),
    Candidate("m7", "m1 without the output reward per tier (only generous rebuilds)", awaken_bps=800, tier_step=50, tier_cap=3, tier_cost_bps=600, tier_time_bps=1000, ap_by_record=True, **_SOFT),
    Candidate("m8", "m1 without the awakening (tiers only)", tier_step=50, tier_cap=3, tier_yield_bps=400, tier_cost_bps=600, tier_time_bps=1000, ap_by_record=True, **_SOFT),
)
# Round 3 (after the second screen: the second reset roughly breaks even, the third never pays because the canonical rule restarts every reset BELOW L200, so a
# deeper record means a longer climb and a deeper output dip): keep a SHARE of the record instead (restart ceiling lifted; safe because AP and tiers follow the
# record, so a reset without a new record earns nothing), and spend a smaller total reward budget (best response must stay <= 1.25).
_KEEP = dict(rebuild_cost_bps=3000, cost_floor_bps=1000, restart_pct=85, rebuild_time_bps=7000, time_floor_bps=2000, restart_ceiling=9999, ap_by_record=True, tier_step=50)
_ROUND3: Tuple[Candidate, ...] = (
    Candidate("n1", "keep 85 % of the record (may exceed L200), cost x0.30, time x0.70; awakening +6 %; per record tier (max 3) +4 % output, -6 pp cost, -10 pp time", awaken_bps=600, tier_cap=3, tier_yield_bps=400, tier_cost_bps=600, tier_time_bps=1000, **_KEEP),
    Candidate("n2", "n1 with +6 % output per record tier", awaken_bps=600, tier_cap=3, tier_yield_bps=600, tier_cost_bps=600, tier_time_bps=1000, **_KEEP),
    Candidate("n3", "n1 with +2 pp more of the record kept per tier (85 -> 91 %)", awaken_bps=600, tier_cap=3, tier_yield_bps=400, tier_restart_pp=2, tier_cost_bps=600, tier_time_bps=1000, **_KEEP),
    Candidate("n4", "two tiers only: awakening +6 %, per tier +6 % output (total at most +18 %)", awaken_bps=600, tier_cap=2, tier_yield_bps=600, tier_cost_bps=600, tier_time_bps=1000, **_KEEP),
    Candidate("n5", "n2 with awakening +4 % (total at most +22 %)", awaken_bps=400, tier_cap=3, tier_yield_bps=600, tier_cost_bps=600, tier_time_bps=1000, **_KEEP),
)
# Round 4 (after the third screen: keeping a share of the record makes the second and third reset pay, but the first reset needs an awakening of about +8 %
# and the whole reward budget must stay small enough that the best response of the strongest style is <= 1.25): sweep awakening, tier reward and tier cap.
_KEEP2 = dict(_KEEP, tier_restart_pp=2, tier_cost_bps=600, tier_time_bps=1000)
_ROUND4: Tuple[Candidate, ...] = (
    Candidate("q1", "keep 85 % (+2 pp per tier); awakening +8 %, +3 % output per tier (max 3): at most +17 %", awaken_bps=800, tier_cap=3, tier_yield_bps=300, **_KEEP2),
    Candidate("q2", "keep 85 % (+2 pp per tier); awakening +8 %, +4 % output per tier (max 2): at most +16 %", awaken_bps=800, tier_cap=2, tier_yield_bps=400, **_KEEP2),
    Candidate("q3", "keep 85 % (+2 pp per tier); awakening +8 %, +3 % output per tier (max 2): at most +14 %", awaken_bps=800, tier_cap=2, tier_yield_bps=300, **_KEEP2),
    Candidate("q4", "keep 85 % (+2 pp per tier); awakening +8 %, +4 % output per tier (max 3): at most +20 %", awaken_bps=800, tier_cap=3, tier_yield_bps=400, **_KEEP2),
    Candidate("q5", "keep 85 % (+2 pp per tier); awakening +7 %, +4 % output per tier (max 2): at most +15 %", awaken_bps=700, tier_cap=2, tier_yield_bps=400, **_KEEP2),
)
# Round 5 (q5 is closest: first reset 346 days, repeats pay, no farm - but the casual style's best response is 1.31): a smaller output budget paid for by
# even cheaper and faster later rebuilds, and the same budget with a different split.
_ROUND5: Tuple[Candidate, ...] = (
    Candidate("r1", "keep 85 % (+3 pp per tier); awakening +7 %, +3 % output per tier (max 2): at most +13 %, rebuilds -8 pp cost / -15 pp time per tier", awaken_bps=700, tier_cap=2, tier_yield_bps=300, **dict(_KEEP, tier_restart_pp=3, tier_cost_bps=800, tier_time_bps=1500)),
    Candidate("r2", "keep 85 % (+2 pp per tier); awakening +7 %, +4 % output only at the first tier (cap 1): at most +11 %", awaken_bps=700, tier_cap=1, tier_yield_bps=400, **_KEEP2),
    Candidate("r3", "keep 85 % (+3 pp per tier); awakening +9 %, +2 % output per tier (max 2), rebuilds -8 pp cost / -15 pp time per tier: at most +13 %", awaken_bps=900, tier_cap=2, tier_yield_bps=200, **dict(_KEEP, tier_restart_pp=3, tier_cost_bps=800, tier_time_bps=1500)),
    Candidate("r4", "r1 with +2.5 % output per tier: at most +12 %", awaken_bps=700, tier_cap=2, tier_yield_bps=250, **dict(_KEEP, tier_restart_pp=3, tier_cost_bps=800, tier_time_bps=1500)),
)
CANDIDATES: Dict[str, Candidate] = {k: ar.CANDIDATES[k] for k in REFS} | {c.key: c for c in _NEW + _ROUND2 + _ROUND3 + _ROUND4 + _ROUND5}
ORDER: Tuple[str, ...] = tuple(CANDIDATES)

ARMS_BY_TOPOLOGY: Dict[str, Tuple[str, ...]] = {
    "S1": ("O200", "P200", "O200x4", "L200+50x2", "L200+50x3", "L200+50", "L200+25"),
    "S11": ("O200", "P200", "H200", "M200", "O200x4", "L200+50x2", "L200+50x3"),
}
ARM_LABEL = {
    "O200": "every mine once at L200",
    "P200": "selective: only the metal mine of every planet, once",
    "H200": "selective: only the homeworld's mines, once",
    "M200": "one single mine in the whole empire",
    "O250": "every mine once, late: at L250 (collects the tiers of a deeper record with one reset)",
    "O300": "every mine once, late: at L300",
    "O200x4": "farm: four resets per mine at L200",
    "L200+50x2": "second reset after +50 levels over the record",
    "L200+50x3": "second and third reset (+50 levels over the record each)",
    "L200+50": "naive ladder without a cap (+50 per reset)",
    "L200+25": "naive fine ladder without a cap (+25 per reset)",
}
SENSIBLE_ARMS: Tuple[str, ...] = ("O200", "P200", "L200+50x2", "L200+50x3", "O250", "O300")  # what a player who understands the rules would pick between (a late single reset collects several tiers at once; only run for the main candidates)


# ---------------------------------------------------------------------------
# Matrix / runner
# ---------------------------------------------------------------------------


# The references need fewer arms at empire scale (the empire study ran them): canon is the loss, fast_p10 the farm reference.
S11_REF_ARMS: Dict[str, Tuple[str, ...]] = {"canon": ("O200",), "fast_p10": ("O200", "O200x4")}


def build_matrix(topology: str = "S1", days: float = DAYS, quick: bool = False, candidates: Sequence[str] = ORDER, arms: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    styles = ("active",) if quick else STYLES
    out: List[Dict[str, Any]] = []
    for style in styles:
        out.append({"sid": f"{topology}-{style}-never", "topology": topology, "style": style, "arm": "never", "cand": "canon", "days": float(days)})
        for cand in candidates:
            cand_arms = tuple(arms) if arms else (S11_REF_ARMS.get(cand, ARMS_BY_TOPOLOGY[topology]) if topology == "S11" else ARMS_BY_TOPOLOGY[topology])
            for arm in cand_arms:
                out.append({"sid": f"{topology}-{style}-{arm}-{cand}", "topology": topology, "style": style, "arm": arm, "cand": cand, "days": float(days)})
    return out


def run_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """One scenario, executed in a worker process (the sandbox owns process-global state)."""
    from scripts import player_journey_sim as pj

    cand = CANDIDATES[spec["cand"]]
    topology = spec.get("topology", "S1")
    seed = spec.get("seed", pj.ELIGIBLE_HOME_SEED if topology == "S11" else None)
    sc = pj.Scenario(spec["sid"], topology, spec["style"], "mid", "none", float(spec["days"]), rng_seed=seed, strategy=spec.get("strategy", "v2"), asc=spec["arm"], asc_skills=cand.ap_order, lever=spec.get("lever", "none"))
    with ar.rules_context(cand):
        res = pj.run_scenario(sc)
    days = float(spec["days"])
    snaps: Dict[str, Any] = {}
    for key in ar.CHECK_KEYS:
        if float(key) > days + 1e-9:
            continue
        c = res["checkpoints"].get("day%s" % key)
        if c is None and abs(float(key) - days) < 1e-9:
            c = res["final"]
        if c is not None:
            slim = ar._slim(c)
            for k in ("worlds", "mine_depth_median"):
                if k in c:
                    slim[k] = c[k]
            snaps[key] = slim
    peak_of = lambda r: int(r.get("peak_depth_max", r["mine_depth_max"]))  # noqa: E731
    series = [(int(r["day"]), int(r["empire_metal_h"]) + int(r["empire_crystal_h"]), peak_of(r), int(r.get("ascensions_total", 0)), int(r.get("worlds", 1))) for r in res["daily"][::5]]
    runs = [
        {k: r.get(k) for k in ("world", "mine", "run", "day", "from_level", "ap_gain", "reset_level", "best_depth", "income_before_h", "income_after_h", "rebuild_to_best_days", "income_recovered_days")}
        for r in res.get("ascension_runs", [])
    ]
    skill_log = [{k: s.get(k) for k in ("world", "mine", "day", "skill", "rank", "cost")} for s in res.get("ascension_skill_log", [])]
    out = {
        "sid": spec["sid"], "topology": topology, "style": spec["style"], "arm": spec["arm"], "cand": spec["cand"], "days": days, "variant": spec.get("variant", ""),
        "status": res["status"], "wall_seconds": res["wall_seconds"], "snapshots": snaps, "series": series, "runs": runs, "skill_log": skill_log,
        "founded_days": [e["day"] for e in res["colony_log"] if e["event"] == "founded"], "invariants": res["invariants"],
    }
    if spec.get("diag"):  # where did the time and the resources go? (spend by category, queue occupancy, colony pipeline)
        diag: Dict[str, Any] = {}
        for key in ar.CHECK_KEYS:
            c = res["checkpoints"].get("day%s" % key)
            if c is None and abs(float(key) - days) < 1e-9:
                c = res["final"]
            if c is not None:
                pw = c.get("per_world", [])
                diag[key] = {
                    "spend_metal": c.get("spend_metal"), "spend_crystal": c.get("spend_crystal"), "research_queue_busy_pct": c.get("research_queue_busy_pct"),
                    "colony_pipeline_sec": c.get("colony_pipeline_sec"), "worlds": c.get("worlds"),
                    "planet_queue_busy_pct": [w.get("queue_busy_pct") for w in pw], "planet_levels": c.get("planet_levels"),
                    "wasted_metal": sum(float(w.get("wasted_metal") or 0) for w in pw), "storage_full_days": sum(float(w.get("storage_full_days") or 0) for w in pw),
                }
        out["diag"] = diag
    return out


def run_matrix(specs: List[Dict[str, Any]], workers: int, progress: bool = True) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    started = time.time()
    specs = sorted(specs, key=lambda s: (s["style"] != "optimizer", s["sid"]))
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
# Aggregation (pure functions over slim results; unit-tested)
# ---------------------------------------------------------------------------


def produced(res: Optional[Dict[str, Any]], ref: Optional[Dict[str, Any]], key: str = "2190") -> Optional[float]:
    if not res or not ref:
        return None
    return ar.metrics(res, ref).get(f"produced_{key}")


def reset_day(res: Optional[Dict[str, Any]], run_no: int) -> Optional[float]:
    """First day on which any mine of the run is reset for the ``run_no``-th time."""
    days = [float(r["day"]) for r in (res or {}).get("runs", []) if int(r.get("run") or 0) == run_no]
    return min(days) if days else None


def marginal(results: Sequence[Dict[str, Any]], cand: str, hi_arm: str, lo_arm: str, run_no: int) -> Dict[str, Dict[str, Optional[float]]]:
    """Value of the ``run_no``-th reset: ``hi_arm`` against ``lo_arm`` (same candidate, same style), cumulative production vs `never` at 72 months and payback days."""
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for style in STYLES:
        hi, lo, ref = ar.find(results, style, hi_arm, cand), ar.find(results, style, lo_arm, cand), ar.reference(results, style)
        if not (hi and lo and ref):
            continue
        a, b = produced(hi, ref), produced(lo, ref)
        t = reset_day(hi, run_no)
        pay = None
        if t is not None:
            pay = ar._since(ar.sustained_from(ar.cumulative_ratios(hi, lo), t, 1.0), t)
        out[style] = {"gain": None if a is None or b is None else a - b, "day": t, "payback_day": pay}
    return out


def first_reset(results: Sequence[Dict[str, Any]], cand: str) -> Dict[str, Dict[str, Any]]:
    return ar.style_metrics(results, "O200", cand)


def best_response(results: Sequence[Dict[str, Any]], cand: str, key: str = "2190") -> Dict[str, Optional[float]]:
    """The best cumulative production vs `never` each style can reach with a sensible policy (first reset only, selective, or up to three resets)."""
    out: Dict[str, Optional[float]] = {}
    for style in STYLES:
        ref = ar.reference(results, style)
        vals = [produced(ar.find(results, style, arm, cand), ref, key) for arm in SENSIBLE_ARMS]
        vals = [v for v in vals if v is not None]
        out[style] = max(vals) if vals else None
    return out


def criteria(results: Sequence[Dict[str, Any]], cand: str) -> Dict[str, Any]:
    first = first_reset(results, cand)
    if not first:
        return {}
    pay = ar.agg([v["payback_day"] for v in first.values()])
    all_paid = all(v["payback_day"] is not None for v in first.values())
    slowest = pay[2] if (pay and all_paid) else None
    k1 = "no" if slowest is None else ("fast" if slowest <= PAYBACK_FAST_DAYS else ("ok" if slowest <= PAYBACK_OK_DAYS else "no"))
    # the first step of a player who starts with the metal mines only (arm P200) may be quicker than the whole-empire campaign (arm O200)
    sel = ar.style_metrics(results, "P200", cand)
    best_start = [min([p for p in (first[st]["payback_day"], sel.get(st, {}).get("payback_day")) if p is not None] or [None]) if st in first else None for st in STYLES]
    slowest_start = None if any(p is None for p in best_start) or not best_start else max(best_start)
    k1_start = "no" if slowest_start is None else ("fast" if slowest_start <= PAYBACK_FAST_DAYS else ("ok" if slowest_start <= PAYBACK_OK_DAYS else "no"))
    # repeat resets: value of the second and third reset
    m2, m3 = marginal(results, cand, "L200+50x2", "O200", 2), marginal(results, cand, "L200+50x3", "L200+50x2", 3)
    g2 = ar.agg([v["gain"] for v in m2.values()])
    g3 = ar.agg([v["gain"] for v in m3.values()])
    p2 = ar.agg([v["payback_day"] for v in m2.values()])
    k2 = None if not (g2 and g3) else bool(g2[0] >= REPEAT_MIN_GAIN and g3[0] >= 0.0 and g2[1] >= REPEAT_MIN_STYLE)
    # guard: a farm is not the best way to play
    farm: Dict[str, Optional[float]] = {}
    for style in STYLES:
        ref = ar.reference(results, style)
        f = produced(ar.find(results, style, "O200x4", cand), ref)
        best = best_response(results, cand).get(style)
        farm[style] = None if f is None or best is None else f - best
    farm_vals = [v for v in farm.values() if v is not None]
    ladders = [produced(ar.find(results, s, arm, cand), ar.reference(results, s)) for s in STYLES for arm in ("L200+50", "L200+25")]
    ladders = [v for v in ladders if v is not None]
    k3 = None if not farm_vals else bool(max(farm_vals) <= FARM_MARGIN and (not ladders or max(ladders) <= ar.STYLE_MAX))
    # never stays legitimate: the median first-reset policy within the window at 48 months and nobody above the limit with the best response
    finals = ar.agg([v["produced_1460"] for v in first.values()])
    br72, br48 = best_response(results, cand, "2190"), best_response(results, cand, "1460")
    top = max([v for v in list(br72.values()) + list(br48.values()) if v is not None] or [0.0])
    k4 = bool(finals and ar.C3_LOW <= finals[0] <= ar.C3_HIGH and top <= ar.STYLE_MAX)
    out = {
        "k1_payback": k1, "slowest_payback": slowest, "payback_days": pay, "k1_best_start": k1_start, "slowest_best_start": slowest_start,
        "k2_repeats": k2, "gain2": g2, "gain3": g3, "payback2": p2,
        "k3_no_farm": k3, "farm_vs_best": farm,
        "k4_never_legit": k4, "produced_1460": finals, "best_response_72": br72, "max_style_ratio": top,
    }
    out["all_pass"] = bool(k1 in ("fast", "ok") and k2 and k3 and k4)
    return out


def selective(results: Sequence[Dict[str, Any]], cand: str, arms: Sequence[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for arm in arms:
        ms = ar.style_metrics(results, arm, cand)
        if ms:
            out[arm] = {"produced_1460": ar.agg([v["produced_1460"] for v in ms.values()]), "produced_2190": ar.agg([v["produced_2190"] for v in ms.values()]), "payback": ar.agg([v["payback_day"] for v in ms.values()]), "max_style": ef._max_style(ms)}
    return out


def meta_block(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "version": ANALYSIS_VERSION,
        "topology": specs[0].get("topology", "S1") if specs else "S1",
        "scenarios": len(specs),
        "days": max(float(s["days"]) for s in specs),
        "candidates": {k: asdict(c) for k, c in CANDIDATES.items()},
        "thresholds": {**ar.thresholds(), "payback_fast": PAYBACK_FAST_DAYS, "payback_ok": PAYBACK_OK_DAYS, "repeat_min_gain": REPEAT_MIN_GAIN, "repeat_min_style": REPEAT_MIN_STYLE, "farm_margin": FARM_MARGIN},
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _cand_text(c: Dict[str, Any]) -> str:
    parts = []
    if c["restart_pct"]:
        parts.append(f"restart {c['restart_pct']} %")
    if c["rebuild_cost_bps"] != 10000:
        parts.append(f"cost x{c['rebuild_cost_bps'] / 10000:g}")
    if c.get("rebuild_time_bps", 10000) != 10000:
        parts.append(f"time x{c['rebuild_time_bps'] / 10000:g}")
    if c.get("surge_bps"):
        parts.append(f"fading surge +{c['surge_bps'] / 100:g} %")
    if c.get("ap_by_record"):
        parts.append("AP only for record progress")
    if c.get("restart_ceiling", 199) > 199:
        parts.append("restart may exceed L200")
    if c["awaken_bps"]:
        parts.append(f"awakening +{c['awaken_bps'] / 100:g} %")
    if c["first_yield_bps"]:
        parts.append(f"first Deep Yield rank +{c['first_yield_bps'] / 100:g} % for 1 AP")
    if c["prestige_bps"]:
        parts.append(f"prestige +{c['prestige_bps'] / 100:g} % per Ascension (max {c['prestige_cap']})")
    if c["ap_flat"]:
        parts.append(f"+{c['ap_flat']} AP")
    if c["tier_cap"] and (c["tier_yield_bps"] or c["tier_restart_pp"] or c["tier_cost_bps"]):
        t = []
        if c["tier_yield_bps"]:
            t.append(f"+{c['tier_yield_bps'] / 100:g} % output")
        if c["tier_restart_pp"]:
            t.append(f"+{c['tier_restart_pp']} pp restart")
        if c["tier_cost_bps"]:
            t.append(f"-{c['tier_cost_bps'] / 100:g} pp cost")
        if c.get("tier_time_bps"):
            t.append(f"-{c['tier_time_bps'] / 100:g} pp time")
        parts.append(f"per record tier ({c['tier_step']} levels, max {c['tier_cap']}): " + ", ".join(t))
    return "; ".join(parts) or "canonical rules"


def render_markdown(data: Dict[str, Any]) -> str:
    results, meta = data["results"], data["meta"]
    topology = meta.get("topology", "S1")
    th = meta["thresholds"]
    cands = [k for k in ORDER if ar.find(results, "active", "O200", k)]
    scope = "S1 journeys (one planet, two production mines)" if topology == "S1" else "S11 journeys (homeworld seed with eligible DNA, up to 11 planets / 22 production mines, PL15 gate)"
    L: List[str] = [
        f"# Ascension milestones - generated tables ({topology})",
        "",
        f"Version `{meta['version']}`.  {scope}, casual / active / optimizer, policy v2, UNI1 endgame curve, {meta['days']:g} days.  Every number is relative to `never` (keep building, canonical rules) of the same style; cells show the median across the three styles and, in brackets, the range.",
        "Candidates are **counterfactual rule sets applied as a sandbox patch** of the Nodebuster owner for one run; nothing here is a game change.  Generated by `scripts/ascension_milestones_analysis.py`; the curated reading is in `docs/GC_ASCENSION_MILESTONES.md`.",
        "",
        "## 1. Candidates",
        "",
        "| Key | Rule |",
        "|---|---|",
    ]
    for k in cands:
        L.append(f"| `{k}` | {_cand_text(meta['candidates'][k])} |")
    L += [
        "",
        "Record tiers are a function of `best_depth` only: the record moves only when a reset happens at a new depth, so a repeated reset at the same depth earns no tier.  Bounded by construction: every bonus is one-time per mine or capped by the tier cap, discounts apply only up to the best depth, the restart level stays below L200, the rebuild cost never falls below the stated floor.",
        "",
        "## 2. The first reset (arm `O200`)",
        "",
        "| Candidate | Cliff | Recovered (days) | Payback (days), median (range) | Slowest style | Real advantage (days) | Cum. production 24 / 48 / 72 mo |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for k in cands:
        ms = first_reset(results, k)
        if not ms:
            continue
        v = list(ms.values())
        pays = [x["payback_day"] for x in v]
        slow = "-" if any(p is None for p in pays) else f"{max(pays):.0f}"
        L.append(
            f"| `{k}` | {ar._g(ar.agg([x['cliff'] for x in v]))} | {ar._gd(ar.agg([x['recovered_days'] for x in v]))} | {ar._gd(ar.agg(pays))} | {slow} | {ar._gd(ar.agg([x['real_advantage_day'] for x in v]))} | "
            f"{ar._g(ar.agg([x['produced_730'] for x in v]))} / {ar._g(ar.agg([x['produced_1460'] for x in v]))} / {ar._g(ar.agg([x['produced_2190'] for x in v]))} |"
        )
    L += [
        "",
        "## 3. The second and third reset, and the farm",
        "",
        "*Gain 2nd* = cumulative production vs `never` at 72 months of `L200+50x2` minus `O200` (what the second reset adds); *gain 3rd* = `L200+50x3` minus `L200+50x2`; *payback 2nd* = days after the second reset until `L200+50x2` is level with `O200` for good.  *Farm vs best* = `O200x4` minus the best sensible policy of the style (first reset only, selective, two or three resets), worst style; it must not be positive.  *Naive ladders* = uncapped `L200+50` / `L200+25` at 72 months, highest style.",
        "",
        "| Candidate | Gain 2nd | Gain 3rd | Payback 2nd (days) | Farm vs best (worst style) | Naive ladders (highest) | Best response 72 mo (highest style) |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for k in cands:
        c = criteria(results, k)
        if not c:
            continue
        ladders = [produced(ar.find(results, s, arm, k), ar.reference(results, s)) for s in STYLES for arm in ("L200+50", "L200+25")]
        ladders = [v for v in ladders if v is not None]
        farm = [v for v in c["farm_vs_best"].values() if v is not None]
        br = [v for v in c["best_response_72"].values() if v is not None]
        farm_txt = "-" if not farm else format(max(farm), "+.2f")
        L.append(
            f"| `{k}` | {ar._g(c['gain2'], '{:+.2f}')} | {ar._g(c['gain3'], '{:+.2f}')} | {ar._gd(c['payback2'])} | {farm_txt} | {ar._r(max(ladders) if ladders else None)} | {ar._r(max(br) if br else None)} |"
        )
    sel_arms = [a for a in ("P200", "H200", "M200", "O250", "O300") if any(r["arm"] == a for r in results)]
    if sel_arms:
        L += ["", "## 4. Selective and late resets", "", "`P200` = only the metal mine of every planet, `H200` = only the homeworld, `M200` = one single mine in the empire, `O250` / `O300` = every mine once but late (at L250 / L300; run for the main candidates only).  Cumulative production vs `never` at 48 / 72 months, median (range); payback in days after the first reset.", "", "| Candidate | " + " | ".join(f"`{a}` 48 / 72 mo | `{a}` payback" for a in sel_arms) + " |", "|---|" + "---|---|" * len(sel_arms)]
        for k in cands:
            s = selective(results, k, sel_arms)
            cells = []
            for a in sel_arms:
                x = s.get(a)
                cells += [f"{ar._g(x['produced_1460'])} / {ar._g(x['produced_2190'])}", ar._gd(x["payback"])] if x else ["-", "-"]
            L.append(f"| `{k}` | " + " | ".join(cells) + " |")
    L += [
        "",
        "## 5. Acceptance",
        "",
        f"Thresholds (this analysis' operationalisation): **K1** first-reset payback within {th['payback_ok']} days for every style (judged on the slowest; `fast` = within {th['payback_fast']}); **K2** the second reset adds at least {th['repeat_min_gain']:g} (median style, no style loses more than {abs(th['repeat_min_style']):g}) and the third reset adds at least 0; **K3** no farm: `O200x4` does not beat the best sensible policy of any style by more than {th['farm_margin']:g}, and the uncapped ladders stay below {th['style_max']:g}; **K4** `never` stays legitimate: median first-reset policy within {th['c3'][0]:g}-{th['c3'][1]:g} at 48 months and no style above {th['style_max']:g} with its best sensible policy.",
        "",
        "*K1 best start* = the same check when each style starts with the faster of the whole-empire reset (`O200`) and the metal mines only (`P200`); `All` uses the strict K1.",
        "",
        "| Candidate | K1 first reset | K1 best start | K2 repeats | K3 no farm | K4 never legit | All | Slowest payback (days) | Slowest, best start | Cum. 48 mo | Best response (highest) |",
        "|---|---|---|---|---|---|---|---:|---:|---:|---:|",
    ]
    for k in cands:
        c = criteria(results, k)
        if not c:
            continue
        slow_txt = "-" if c["slowest_payback"] is None else format(c["slowest_payback"], ".0f")
        start_txt = "-" if c["slowest_best_start"] is None else format(c["slowest_best_start"], ".0f")
        L.append(
            f"| `{k}` | {c['k1_payback']} | {c['k1_best_start']} | {ar._yes(c['k2_repeats'])} | {ar._yes(c['k3_no_farm'])} | {ar._yes(c['k4_never_legit'])} | {'**yes**' if c['all_pass'] else 'no'} | {slow_txt} | {start_txt} | {ar._g(c['produced_1460'])} | {ar._r(c['max_style_ratio'])} |"
        )
    L += ["", "## 6. Limits", "", "* Fixed reset policies (`O`, `P`, `H`, `M`, `L`); a smarter timing might do better.  Thresholds are this analysis' operationalisation.", "* One homeworld seed in S11; the baseline includes the outpost-XP defect (#556 not applied).", "* Candidates are rule sets, not proposals; tier steps, caps and floors are sandbox values."]
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--topology", default="S1", choices=sorted(ARMS_BY_TOPOLOGY))
    ap.add_argument("--quick", action="store_true", help="active style only")
    ap.add_argument("--days", type=float, default=None)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--candidates", default="", help="comma separated subset of candidate keys")
    ap.add_argument("--arms", default="", help="comma separated subset of arms")
    ap.add_argument("--resume", default="", help="JSON of an earlier run: scenarios already in it are not run again, new ones are merged in")
    ap.add_argument("--out-json", default="")
    ap.add_argument("--out-md", default="")
    ap.add_argument("--render-from", default="", help="re-render markdown from a saved JSON (no simulation)")
    args = ap.parse_args(argv)
    if args.render_from:
        data = json.loads(Path(args.render_from).read_text(encoding="utf-8"))
    else:
        days = args.days if args.days is not None else (730.0 if args.quick else DAYS)
        keys = tuple(k for k in args.candidates.split(",") if k) or ORDER
        arms = tuple(a for a in args.arms.split(",") if a) or None
        specs = build_matrix(args.topology, days, args.quick, keys, arms)
        known: List[Dict[str, Any]] = []
        todo = specs
        if args.resume:
            known = json.loads(Path(args.resume).read_text(encoding="utf-8"))["results"]
            have = {r["sid"] for r in known}
            todo = [s for s in specs if s["sid"] not in have]
        results = ar.merge_results(known, run_matrix(todo, args.workers or min(10, max(1, len(todo)))) if todo else [])
        data = {"meta": meta_block(specs), "results": results}
    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    md = render_markdown(data)
    if args.out_md:
        Path(args.out_md).write_text(md + "\n", encoding="utf-8")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
