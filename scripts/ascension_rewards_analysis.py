#!/usr/bin/env python3
"""Ascension reward candidates in the sandbox (measurement only, no game change).

The Ascension report showed that the first reset loses money at every fixed threshold: one Ascension at L200 grants 1 AP and costs
a rebuild of about 90 days.  This module prices *counterfactual reward rules* - never a game change - to find out which early
reward would make the first reset an interesting decision without making it mandatory and without turning repeated resets into
an unlimited multiplier.

Mechanism.  A candidate is a set of parameters applied as a sandbox patch of the leaf rule functions of the canonical Nodebuster
owner (``ascension_points_for_depth``, ``rebuild_cost_bps``, ``reset_start_level``, ``rebuild_production_bonus_bps``) for the
duration of one simulated run, under the simulator's universe lock, and restored afterwards.  Everything else (queue rules, prices,
production formula, skill catalogue, prerequisites, AP accounting) is the canonical owner; the simulator's invariants check that
AP earned equals the awards *of the candidate rule* and AP spent equals the canonical skill costs.

Structural properties that stay true for every candidate (and bound the multiplier): rebuild discounts and the surge apply only
to levels up to the best depth (+ the Breakthrough window), never beyond; permanent output bonuses come only from skills, which
have maximum ranks; the restart level stays below L200.

Metrics (per style, against ``never`` in the same universe): cumulative production, income ratio over time, worst income ratio
during the first rebuild, payback day (cumulative production catches up), first day of a *real* advantage (income >= 110 % of
``never`` from then on), AP access (AP after N days, day of the first skill rank), and the long-horizon behaviour of repeated resets.

Run::

    python scripts/ascension_rewards_analysis.py --out-json artifacts/ascension_rewards/latest.json --out-md docs/GC_ASCENSION_REWARDS_REPORT.md
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ANALYSIS_VERSION = "ascension-rewards/1"
STYLES: Tuple[str, ...] = ("casual", "active", "optimizer")
DAYS = 2190.0  # 72 months: long enough to see whether repeated resets saturate
CHECK_KEYS: Tuple[str, ...] = ("365", "730", "1095", "1460", "2190")
CHECK_LABEL = {"365": "12 mo", "730": "24 mo", "1095": "36 mo", "1460": "48 mo", "2190": "72 mo"}
ARMS: Tuple[str, ...] = ("never", "O200", "O250", "O300", "T200", "L200+25", "O200x4", "O200x8")
RESET_ARMS: Tuple[str, ...] = ("O200", "O250", "O300", "T200", "L200+25", "O200x4", "O200x8")
FARM_ARMS: Tuple[str, ...] = ("O200", "O200x4", "O200x8")
REAL_ADVANTAGE = 1.10  # "a real advantage": income at least 10 % above `never` from that day on
ASCENSION_MIN_LEVEL = 200  # mirrors nodebuster.ASCENSION_MIN_LEVEL (checked by a test)


@dataclass(frozen=True)
class Candidate:
    """Counterfactual reward rule set.  ``canon`` is the game."""

    key: str
    label: str
    rebuild_cost_bps: int = 10000  # base rebuild cost before skills (canonical 10000); skills still subtract 550 bps / Frugal rank, floor 3500
    restart_pct: int = 0  # restart at least this share of the best depth (canonical 0: only Reconstruction / Overdrive raise it); always < L200
    surge_bps: int = 0  # FADING mine-output surge while climbing back to the best depth: +surge at level 0, linearly to +0 at the best depth
    ap_flat: int = 0  # extra AP on every run (canonical 0)
    ap_step: int = 25  # one extra AP per `ap_step` levels above L200 (canonical 25)
    prestige_bps: int = 0  # permanent mine-output bonus per completed Ascension of that mine ...
    prestige_cap: int = 0  # ... counted up to this many Ascensions (the multiplier is bounded by prestige_bps x prestige_cap)
    first_yield_bps: int = 0  # first Deep Yield rank gives this much output (canonical +250 bps) and costs 1 AP (canonical 2); later ranks unchanged
    ap_order: str = "rebuild_first"  # AP spending order of the simulated player

    def is_canon(self) -> bool:
        return (self.rebuild_cost_bps, self.restart_pct, self.surge_bps, self.ap_flat, self.ap_step, self.prestige_bps * self.prestige_cap, self.first_yield_bps) == (10000, 0, 0, 0, 25, 0, 0)

    def prestige_max_bps(self) -> int:
        return int(self.prestige_bps) * int(self.prestige_cap)


CANDIDATES: Dict[str, Candidate] = {
    c.key: c
    for c in (
        Candidate("canon", "canonical rules (the game)"),
        Candidate("cost40", "rebuild cost x0.40 from the first reset", rebuild_cost_bps=4000),
        Candidate("restart75", "restart at 75 % of the best depth (L150 after L200)", restart_pct=75),
        Candidate("fade100", "fading rebuild surge, +100 % at level 0 down to +0 at the best depth", surge_bps=10000),
        Candidate("prestige", "+5 % mine output per Ascension of that mine, at most 3 (+15 %)", prestige_bps=500, prestige_cap=3),
        Candidate("ap3", "+2 AP per run (L200: 3 AP)", ap_flat=2),
        Candidate("ap_steep", "1 extra AP per 10 levels instead of 25", ap_step=10),
        Candidate("soft", "restart 50 % + rebuild cost x0.50 + fading surge +50 %", rebuild_cost_bps=5000, restart_pct=50, surge_bps=5000),
        Candidate("soft_p", "soft + prestige +5 % per Ascension (max 3)", rebuild_cost_bps=5000, restart_pct=50, surge_bps=5000, prestige_bps=500, prestige_cap=3),
        Candidate("fast_p", "restart 75 % + cost x0.40 + prestige +5 % (max 3) + 2 AP", rebuild_cost_bps=4000, restart_pct=75, prestige_bps=500, prestige_cap=3, ap_flat=2),
        Candidate("prestige10", "+10 % mine output per Ascension of that mine, at most 3 (+30 %)", prestige_bps=1000, prestige_cap=3),
        Candidate("fast_p10", "restart 75 % + cost x0.40 + prestige +10 % (max 3) + 2 AP", rebuild_cost_bps=4000, restart_pct=75, prestige_bps=1000, prestige_cap=3, ap_flat=2),
        # second round: ablations of fast_p10 (what does each component contribute?) and two neighbours
        Candidate("fast_p7", "restart 75 % + cost x0.40 + prestige +7 % (max 3, +21 %) + 2 AP", rebuild_cost_bps=4000, restart_pct=75, prestige_bps=700, prestige_cap=3, ap_flat=2),
        Candidate("abl_no_prestige", "fast_p10 without prestige: restart 75 % + cost x0.40 + 2 AP", rebuild_cost_bps=4000, restart_pct=75, ap_flat=2),
        Candidate("abl_no_restart", "fast_p10 without the restart level: cost x0.40 + prestige +10 % + 2 AP", rebuild_cost_bps=4000, prestige_bps=1000, prestige_cap=3, ap_flat=2),
        Candidate("abl_no_cost", "fast_p10 without the cost discount: restart 75 % + prestige +10 % + 2 AP", restart_pct=75, prestige_bps=1000, prestige_cap=3, ap_flat=2),
        Candidate("abl_no_ap", "fast_p10 without extra AP: restart 75 % + cost x0.40 + prestige +10 %", rebuild_cost_bps=4000, restart_pct=75, prestige_bps=1000, prestige_cap=3),
        Candidate("keep90_p10", "restart 90 % + cost x0.40 + prestige +10 % (max 3) + 2 AP", rebuild_cost_bps=4000, restart_pct=90, prestige_bps=1000, prestige_cap=3, ap_flat=2),
        # third round: the window between fast_p7 and fast_p10, and a strong first skill rank bought with the first AP
        Candidate("fast_p8", "restart 75 % + cost x0.40 + prestige +8 % (max 3, +24 %) + 2 AP", rebuild_cost_bps=4000, restart_pct=75, prestige_bps=800, prestige_cap=3, ap_flat=2),
        Candidate("rank1_yield", "first Deep Yield rank = +10 % output for 1 AP (instead of +2.5 % for 2 AP), AP into Deep Yield first", first_yield_bps=1000, ap_order="yield_first"),
        Candidate("rank1_fast", "rank1_yield + restart 75 % + cost x0.40", first_yield_bps=1000, ap_order="yield_first", rebuild_cost_bps=4000, restart_pct=75),
    )
}
MAIN_ORDER: Tuple[str, ...] = tuple(CANDIDATES)


# ---------------------------------------------------------------------------
# The sandbox patch (rule functions of the canonical owner)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def rules_context(candidate: Candidate):
    """Apply a candidate to the Nodebuster rule functions for the duration of a run; restored afterwards.  Canonical = no patch."""
    from game.mine_evolution import nodebuster as nb
    from game.mine_evolution.formulas import is_evolvable_mine
    from scripts import player_journey_sim as pj

    with pj.SIM_LOCK:
        if candidate.is_canon():
            yield
            return
        names = (
            "ascension_points_for_depth", "rebuild_cost_bps", "reset_start_level",
            "rebuild_production_multiplier_for", "production_multiplier_for", "production_bonus_bps", "skill_point_cost",
        )
        saved = {n: getattr(nb, n) for n in names}
        min_level = int(nb.ASCENSION_MIN_LEVEL)

        def points(level: int) -> int:
            depth = int(level or 0)
            if depth < min_level:
                return 0
            above = depth - min_level
            return 1 + int(candidate.ap_flat) + above // int(candidate.ap_step) + above // 100

        def cost_bps(skills: Dict[str, int]) -> int:
            frugal = max(0, int(skills.get("frugal_rebuild", 0) or 0))
            overdrive = max(0, int(skills.get("overdrive", 0) or 0))
            return max(3500, int(candidate.rebuild_cost_bps) - 550 * frugal - 250 * overdrive)

        def start_level(skills: Dict[str, int], best_depth: int = 0) -> int:
            canonical = saved["reset_start_level"](skills, best_depth)
            floor = (int(best_depth or 0) * int(candidate.restart_pct)) // 100
            return min(min_level - 1, max(int(canonical), floor))

        def rebuild_multiplier(planet_id: int, building_type: str, current_level: int, *, conn=None, profiles=None) -> float:
            canonical = saved["rebuild_production_multiplier_for"](planet_id, building_type, current_level, conn=conn, profiles=profiles)
            if candidate.surge_bps <= 0 or not is_evolvable_mine(str(building_type or "")):
                return canonical
            data = profiles if profiles is not None else nb.get_profiles_for_planet(int(planet_id), conn=conn)
            state = nb.get_state(int(planet_id), str(building_type), conn=conn, profiles=data)
            best = int(state.get("best_depth") or 0)
            if int(state.get("ascension_count") or 0) <= 0 or best <= 0 or int(current_level or 0) >= best:
                return canonical
            fade = (best - int(current_level or 0)) / float(best)
            return canonical * (1.0 + candidate.surge_bps / 10000.0 * fade)

        def production_multiplier(planet_id: int, building_type: str, *, conn=None, profiles=None) -> float:
            canonical = saved["production_multiplier_for"](planet_id, building_type, conn=conn, profiles=profiles)
            if candidate.prestige_max_bps() <= 0 or not is_evolvable_mine(str(building_type or "")):
                return canonical
            data = profiles if profiles is not None else nb.get_profiles_for_planet(int(planet_id), conn=conn)
            state = nb.get_state(int(planet_id), str(building_type), conn=conn, profiles=data)
            n = min(int(candidate.prestige_cap), int(state.get("ascension_count") or 0))
            return canonical * (1.0 + candidate.prestige_bps * n / 10000.0)

        def production_bonus(skills: Dict[str, int]) -> int:
            canonical = int(saved["production_bonus_bps"](skills))
            rank = max(0, int(skills.get("deep_yield", 0) or 0))
            if candidate.first_yield_bps <= 0 or rank <= 0:
                return canonical
            return canonical - 250 + int(candidate.first_yield_bps)  # rank 1 pays first_yield_bps instead of 250, later ranks add 250 each as before

        def skill_cost(skill_key: str, current_rank: int) -> int:
            if candidate.first_yield_bps > 0 and str(skill_key) == "deep_yield" and int(current_rank or 0) == 0:
                return 1
            return int(saved["skill_point_cost"](skill_key, current_rank))

        nb.ascension_points_for_depth = points
        nb.production_bonus_bps = production_bonus
        nb.skill_point_cost = skill_cost
        nb.rebuild_cost_bps = cost_bps
        nb.reset_start_level = start_level
        nb.rebuild_production_multiplier_for = rebuild_multiplier
        nb.production_multiplier_for = production_multiplier
        try:
            yield
        finally:
            for n, fn in saved.items():
                setattr(nb, n, fn)


# ---------------------------------------------------------------------------
# Matrix / runner
# ---------------------------------------------------------------------------


def build_matrix(days: float = DAYS, quick: bool = False, candidates: Sequence[str] = MAIN_ORDER) -> List[Dict[str, Any]]:
    styles = ("active",) if quick else STYLES
    out: List[Dict[str, Any]] = []
    for style in styles:
        out.append({"sid": f"S1-{style}-never", "style": style, "arm": "never", "cand": "canon", "days": float(days)})
        for cand in candidates:
            for arm in RESET_ARMS:
                out.append({"sid": f"S1-{style}-{arm}-{cand}", "style": style, "arm": arm, "cand": cand, "days": float(days)})
    return out


def _slim(c: Dict[str, Any]) -> Dict[str, Any]:
    asc = c.get("ascension") or {}
    per_world = c.get("per_world", [])
    return {
        "day": c.get("day"),
        "empire_metal_h": c.get("empire_metal_h"),
        "empire_crystal_h": c.get("empire_crystal_h"),
        "peak_depth_max": c.get("peak_depth_max", c.get("mine_depth_max")),
        "produced": sum(float(w.get("produced_metal") or 0) + float(w.get("produced_crystal") or 0) for w in per_world),
        "ascensions_total": int(asc.get("ascensions_total") or 0),
        "ap_earned_total": int(asc.get("ap_earned_total") or 0),
        "ap_spent_total": int(asc.get("ap_spent_total") or 0),
        "skills": _skill_totals(asc),
    }


def _skill_totals(asc: Dict[str, Any]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for m in asc.get("mines", []):
        for k, v in (m.get("skills") or {}).items():
            out[k] = out.get(k, 0) + int(v)
    return out


def run_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """One scenario, executed in a worker process (the sandbox owns process-global state)."""
    from scripts import player_journey_sim as pj

    cand = CANDIDATES[spec["cand"]]
    sc = pj.Scenario(spec["sid"], "S1", spec["style"], "mid", "none", float(spec["days"]), strategy="v2", asc=spec["arm"], asc_skills=cand.ap_order)
    with rules_context(cand):
        res = pj.run_scenario(sc)
    days = float(spec["days"])
    snaps: Dict[str, Any] = {}
    for key in CHECK_KEYS:
        if float(key) > days + 1e-9:
            continue
        c = res["checkpoints"].get("day%s" % key)
        if c is None and abs(float(key) - days) < 1e-9:
            c = res["final"]
        if c is not None:
            snaps[key] = _slim(c)
    peak_of = lambda r: int(r.get("peak_depth_max", r["mine_depth_max"]))  # noqa: E731
    series = [(int(r["day"]), int(r["empire_metal_h"]) + int(r["empire_crystal_h"]), peak_of(r), int(r.get("ascensions_total", 0))) for r in res["daily"][::5]]
    runs = [
        {k: r.get(k) for k in ("world", "mine", "run", "day", "from_level", "ap_gain", "reset_level", "best_depth", "income_before_h", "income_after_h", "rebuild_to_best_days", "income_recovered_days")}
        for r in res.get("ascension_runs", [])
    ]
    skill_log = [{k: s.get(k) for k in ("world", "mine", "day", "skill", "rank", "cost")} for s in res.get("ascension_skill_log", [])]
    return {
        "sid": spec["sid"],
        "style": spec["style"],
        "arm": spec["arm"],
        "cand": spec["cand"],
        "days": days,
        "status": res["status"],
        "wall_seconds": res["wall_seconds"],
        "snapshots": snaps,
        "series": series,
        "runs": runs,
        "skill_log": skill_log,
        "invariants": res["invariants"],
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
# Aggregation (pure functions over slim results; unit-tested)
# ---------------------------------------------------------------------------

# Operationalisation of the three design criteria (the thresholds are this analysis' choice, printed in the report)
C1_CLIFF = 2.0 / 3.0  # the first reset leaves at least two thirds of the income the empire had a moment before ...
C1_RECOVER_DAYS = 30  # ... and the empire is back at its own pre-reset income within 30 days (median style)
C2_PAYBACK_DAYS = 365  # cumulative production catches up with `never` within a year of the first reset (good) ...
C2_PAYBACK_DAYS_OK = 730  # ... or two years (acceptable)
C3_LOW, C3_HIGH = 0.85, 1.15  # `never` stays legitimate: the median style ends within -15 % / +15 % of it in cumulative production at 48 months ...
STYLE_MAX = 1.25  # ... and no style is pushed above +25 % (by a single reset, by farming, by a treadmill or a ladder, at 48 or 72 months)
FARM_GAIN = 0.05  # extra resets "pay" for a style if 4 or 8 resets per mine beat a single reset by more than this (cumulative production at 72 months)
GUARD_HIGH = STYLE_MAX


def find(results: Sequence[Dict[str, Any]], style: str, arm: str, cand: str) -> Optional[Dict[str, Any]]:
    for r in results:
        if r["style"] == style and r["arm"] == arm and r["cand"] == cand:
            return r
    return None


def reference(results: Sequence[Dict[str, Any]], style: str) -> Optional[Dict[str, Any]]:
    return find(results, style, "never", "canon")


def snap(res: Optional[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    return None if not res else res["snapshots"].get(key)


def income(s: Dict[str, Any]) -> float:
    return float(s["empire_metal_h"]) + float(s["empire_crystal_h"])


def first_reset_day(res: Dict[str, Any]) -> Optional[float]:
    days = [float(r["day"]) for r in res.get("runs", [])]
    return min(days) if days else None


def cumulative(series: Sequence[Sequence[float]]) -> List[Tuple[int, float]]:
    """Cumulative production (income per hour x 24 h, trapezoid over the sampled days)."""
    out: List[Tuple[int, float]] = []
    total = 0.0
    prev: Optional[Tuple[float, float]] = None
    for d, inc, *_rest in series:
        d, inc = float(d), float(inc)
        if prev is not None:
            total += 0.5 * (prev[1] + inc) * 24.0 * (d - prev[0])
        out.append((int(d), total))
        prev = (d, inc)
    return out


def ratio_series(a: Sequence[Sequence[float]], ref: Sequence[Sequence[float]]) -> List[Tuple[int, float]]:
    refmap = {int(d): float(v) for d, v, *_r in ref}
    return [(int(d), float(v) / refmap[int(d)]) for d, v, *_r in a if int(d) in refmap and refmap[int(d)] > 0]


def income_ratios(res: Dict[str, Any], ref: Dict[str, Any]) -> List[Tuple[int, float]]:
    return ratio_series(res["series"], ref["series"])


def cumulative_ratios(res: Dict[str, Any], ref: Dict[str, Any]) -> List[Tuple[int, float]]:
    ca, cr = cumulative(res["series"]), cumulative(ref["series"])
    return [(d, v) for d, v in ratio_series([(d, c) for d, c in ca], [(d, c) for d, c in cr]) if d > 0]


def sustained_from(ratios: Sequence[Tuple[int, float]], after_day: float, threshold: float) -> Optional[int]:
    """First sampled day after ``after_day`` from which the ratio stays >= threshold until the end of the run (None if it never does)."""
    ok: Optional[int] = None
    for d, v in ratios:
        if d <= after_day:
            continue
        if v >= threshold:
            if ok is None:
                ok = d
        else:
            ok = None
    return ok


def first_reach(ratios: Sequence[Tuple[int, float]], after_day: float, threshold: float) -> Optional[int]:
    """First sampled day after ``after_day`` at which the ratio is >= threshold (not necessarily staying)."""
    for d, v in ratios:
        if d > after_day and v >= threshold:
            return d
    return None


def worst_after(ratios: Sequence[Tuple[int, float]], after_day: float, window_days: float) -> Tuple[Optional[float], Optional[int]]:
    """(lowest income ratio, its day) within ``window_days`` after ``after_day``."""
    pts = [(v, d) for d, v in ratios if after_day <= d <= after_day + window_days]
    if not pts:
        return None, None
    v, d = min(pts)
    return v, d


def ratio_at_day(ratios: Sequence[Tuple[int, float]], day: float) -> Optional[float]:
    best: Optional[Tuple[float, float]] = None
    for d, v in ratios:
        if best is None or abs(d - day) < best[0]:
            best = (abs(d - day), v)
    return None if best is None or best[0] > 5.0 else best[1]


def ap_access(res: Dict[str, Any]) -> Dict[str, Any]:
    runs = sorted(res.get("runs", []), key=lambda r: float(r["day"]))
    gains = [int(r.get("ap_gain") or 0) for r in runs]
    skills = sorted(res.get("skill_log", []), key=lambda s: float(s["day"]))
    snaps = res["snapshots"]
    return {
        "first_run_ap": gains[0] if gains else None,
        "runs": len(runs),
        "ap_total_by": {k: int(snaps[k]["ap_earned_total"]) for k in ("730", "1460", "2190") if k in snaps},
        "ap_spent_by": {k: int(snaps[k]["ap_spent_total"]) for k in ("730", "1460", "2190") if k in snaps},
        "first_skill_day": float(skills[0]["day"]) if skills else None,
        "first_skill": skills[0]["skill"] if skills else None,
        "skills_730": snaps["730"]["skills"] if "730" in snaps else {},
    }


def metrics(res: Dict[str, Any], ref: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the report needs about one reset run against `never` of the same style."""
    t0 = first_reset_day(res)
    inc = income_ratios(res, ref)
    cum = cumulative_ratios(res, ref)
    out: Dict[str, Any] = {"first_reset_day": t0, "ap": ap_access(res), "invariants_ok": bool(res["invariants"].get("ok", True))}
    first = sorted(res.get("runs", []), key=lambda r: float(r["day"]))[:1]
    out["cliff"] = None if not first or not first[0].get("income_before_h") else float(first[0]["income_after_h"]) / float(first[0]["income_before_h"])
    out["recovered_days"] = None if not first else first[0].get("income_recovered_days")
    for key in CHECK_KEYS:
        a, b = snap(res, key), snap(ref, key)
        out[f"income_{key}"] = None if not a or not b else income(a) / income(b)
        out[f"produced_{key}"] = None if not a or not b or not b["produced"] else a["produced"] / b["produced"]
    if t0 is None:
        out.update({"worst_ratio": None, "worst_day": None, "income_breakeven_day": None, "real_advantage_day": None, "payback_day": None})
        return out
    worst, wd = worst_after(inc, t0, 400.0)
    out.update(
        {
            "worst_ratio": worst,
            "worst_day": wd,
            "income_breakeven_day": _since(sustained_from(inc, t0, 1.0), t0),
            "real_advantage_day": _since(sustained_from(inc, t0, REAL_ADVANTAGE), t0),
            "payback_day": _since(sustained_from(cum, t0, 1.0), t0),
        }
    )
    for off in (180, 365, 730):
        out[f"income_plus_{off}"] = ratio_at_day(inc, t0 + off)
    return out


def _since(day: Optional[int], t0: float) -> Optional[float]:
    return None if day is None else float(day) - float(t0)


def agg(values: Sequence[Optional[float]]) -> Optional[Tuple[float, float, float]]:
    """(median, min, max) of the defined values, None if there are none."""
    vals = [float(v) for v in values if v is not None]
    return (float(median(vals)), min(vals), max(vals)) if vals else None


def style_metrics(results: Sequence[Dict[str, Any]], arm: str, cand: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for style in STYLES:
        r, ref = find(results, style, arm, cand), reference(results, style)
        if r and ref:
            out[style] = metrics(r, ref)
    return out


def criteria(results: Sequence[Dict[str, Any]], cand: str) -> Dict[str, Any]:
    """The three design criteria for one candidate (medians over the styles, first-reset arm O200) plus the guards."""
    m = style_metrics(results, "O200", cand)
    if not m:
        return {}
    cliff = agg([v["cliff"] for v in m.values()])
    rec = agg([v["recovered_days"] for v in m.values()])
    c1 = bool(cliff and rec and cliff[0] >= C1_CLIFF and rec[0] <= C1_RECOVER_DAYS)
    pay = agg([v["payback_day"] for v in m.values()])
    all_paid = all(v["payback_day"] is not None for v in m.values())
    c2 = "no"
    if pay and all_paid:
        c2 = "good" if pay[0] <= C2_PAYBACK_DAYS else ("ok" if pay[0] <= C2_PAYBACK_DAYS_OK else "no")
    finals = agg([v["produced_1460"] for v in m.values()])
    top = max([v[f"produced_{k}"] for v in m.values() for k in ("1460", "2190") if v[f"produced_{k}"] is not None] or [0.0])
    c3 = bool(finals and C3_LOW <= finals[0] <= C3_HIGH and top <= STYLE_MAX)
    guard = guard_metrics(results, cand)
    return {
        "c1_valuable": c1,
        "cliff": cliff,
        "recovered_days": rec,
        "c2_payback": c2,
        "c3_never_legit": c3,
        "guard_ok": guard.get("ok"),
        "payback_days": pay,
        "produced_1460": finals,
        "max_style_ratio": top,
        "guard": guard,
        "farming": guard.get("farming"),
        "all_pass": bool(c1 and c2 in ("good", "ok") and c3 and guard.get("ok")),
    }


def farming_metrics(results: Sequence[Dict[str, Any]], cand: str) -> Dict[str, Any]:
    """Is it worth resetting more than once?  Cumulative production vs `never` for 1 / 4 / 8 resets per mine (then keep building), per style."""
    out: Dict[str, Any] = {"arms": {}, "pays_for": [], "max_style_ratio": None}
    per: Dict[str, Dict[str, float]] = {}
    for arm in FARM_ARMS:
        ms = style_metrics(results, arm, cand)
        if not ms:
            continue
        out["arms"][arm] = {k: agg([v[f"produced_{k}"] for v in ms.values()]) for k in ("1460", "2190")} | {"ap_2190": agg([v["ap"]["ap_total_by"].get("2190") for v in ms.values()])}
        for style, v in ms.items():
            if v["produced_2190"] is not None:
                per.setdefault(style, {})[arm] = float(v["produced_2190"])
    for style, vals in per.items():
        one = vals.get("O200")
        many = [vals[a] for a in ("O200x4", "O200x8") if a in vals]
        if one is not None and many and max(many) - one > FARM_GAIN:
            out["pays_for"].append(style)
    all_vals = [x for vals in per.values() for x in vals.values()]
    out["max_style_ratio"] = max(all_vals) if all_vals else None
    one_m = (out["arms"].get("O200") or {}).get("2190")
    gains = [(out["arms"][a]["2190"][0] - one_m[0]) for a in ("O200x4", "O200x8") if one_m and (out["arms"].get(a) or {}).get("2190")]
    out["extra_reset_gain"] = max(gains) if gains else (0.0 if out["arms"] else None)
    out["farming_pays"] = None if not out["arms"] else bool(out["pays_for"])
    return out


def guard_metrics(results: Sequence[Dict[str, Any]], cand: str) -> Dict[str, Any]:
    """Repeated resets (treadmill T200, ladder L200+25): they must not beat `never` by more than GUARD_HIGH at 72 months nor still be rising."""
    out: Dict[str, Any] = {"arms": {}}
    ok = True
    seen = False
    for arm in ("T200", "L200+25"):
        ms = style_metrics(results, arm, cand)
        if not ms:
            continue
        seen = True
        p72 = agg([v["produced_2190"] for v in ms.values()])
        i72 = agg([v["income_2190"] for v in ms.values()])
        i48 = agg([v["income_1460"] for v in ms.values()])
        runs = agg([v["ap"]["runs"] for v in ms.values()])
        ap72 = agg([v["ap"]["ap_total_by"].get("2190") for v in ms.values()])
        rising = any(v["income_2190"] is not None and v["income_1460"] is not None and v["income_2190"] > v["income_1460"] * 1.05 and v["income_2190"] > GUARD_HIGH for v in ms.values())
        arm_ok = bool(p72 and i72 and p72[2] <= GUARD_HIGH and i72[2] <= GUARD_HIGH and not rising)
        ok = ok and arm_ok
        out["arms"][arm] = {"produced_2190": p72, "income_2190": i72, "income_1460": i48, "runs": runs, "ap_2190": ap72, "ok": arm_ok}
    farm = farming_metrics(results, cand)
    if farm["arms"]:
        ok = ok and not farm["pays_for"] and (farm["max_style_ratio"] is not None and farm["max_style_ratio"] <= STYLE_MAX)
    out["farming"] = farm
    out["ok"] = ok if seen else None
    return out


def thresholds() -> Dict[str, Any]:
    return {
        "c1_cliff": round(C1_CLIFF, 3), "c1_recover_days": C1_RECOVER_DAYS, "c2_payback_days": C2_PAYBACK_DAYS, "c2_payback_days_ok": C2_PAYBACK_DAYS_OK,
        "c3": [C3_LOW, C3_HIGH], "style_max": STYLE_MAX, "farm_gain": FARM_GAIN, "real_advantage": REAL_ADVANTAGE,
    }


def merge_results(old: Sequence[Dict[str, Any]], new: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Union by scenario id; a new result replaces an old one."""
    by = {r["sid"]: r for r in old}
    by.update({r["sid"]: r for r in new})
    return [by[k] for k in sorted(by)]


def meta_block(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "version": ANALYSIS_VERSION,
        "scenarios": len(specs),
        "days": max(float(s["days"]) for s in specs),
        "candidates": {k: asdict(c) for k, c in CANDIDATES.items()},
        "thresholds": thresholds(),
    }


def ap_runs_needed(cand_key: str) -> Dict[str, Any]:
    """Resets of one mine needed for tree milestones under a candidate's AP rule (pure arithmetic on the canonical skill costs)."""
    from game.mine_evolution import nodebuster as nb

    def total(skill: str, ranks: int) -> int:
        return sum(nb.skill_point_cost(skill, r) for r in range(ranks))

    core5 = ("frugal_rebuild", "rapid_rebuild", "reconstruction", "deep_yield", "deep_storage")
    milestones = {
        "Frugal + Rapid rank 3": total("frugal_rebuild", 3) + total("rapid_rebuild", 3),
        "Deep Yield rank 4 (+10 %)": total("deep_yield", 4),
        "five core skills rank 5 (Overdrive gate)": sum(total(k, 5) for k in core5),
        "whole tree": sum(total(k, int(cfg["max_rank"])) for k, cfg in nb.SKILL_CATALOG.items()),
    }
    with rules_context(CANDIDATES[cand_key]):
        per_run = {d: int(nb.ascension_points_for_depth(d)) for d in (200, 250, 300)}
    return {"per_run": per_run, "runs": {name: {d: -(-cost // per_run[d]) for d in per_run} for name, cost in milestones.items()}, "ap": milestones}


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _r(v: Optional[float], digits: int = 2) -> str:
    return "-" if v is None else f"{v:.{digits}f}"


def _g(a: Optional[Tuple[float, float, float]], fmt: str = "{:.2f}") -> str:
    if a is None:
        return "-"
    med, lo, hi = a
    return fmt.format(med) if abs(hi - lo) < 1e-9 else f"{fmt.format(med)} ({fmt.format(lo)}-{fmt.format(hi)})"


def _gd(a: Optional[Tuple[float, float, float]]) -> str:
    return _g(a, "{:.0f}")


def _gp(a: Optional[Tuple[float, float, float]]) -> str:
    return "-" if a is None else _g(tuple(100 * x for x in a), "{:.0f}")  # type: ignore[arg-type]


def _yes(flag: Optional[bool]) -> str:
    return "n/a" if flag is None else ("yes" if flag else "no")


def render_markdown(data: Dict[str, Any]) -> str:
    results = data["results"]
    meta = data["meta"]
    th = thresholds()  # definitions live in code; the stored JSON carries the data only
    candidate_defs = {k: asdict(c) for k, c in CANDIDATES.items()}
    cands = [k for k in MAIN_ORDER if find(results, "active", "O200", k)]
    L: List[str] = [
        "# Ascension reward candidates - generated tables",
        "",
        f"Version `{meta['version']}`.  S1 journeys (one planet), casual / active / optimizer, policy v2, UNI1 endgame curve, {meta['days']:g} days, AP order `rebuild_first` (candidates with a strong first Deep Yield rank: `yield_first`).  Every number is relative to `never` (keep building, canonical rules) of the same style; cells show the median across the three styles and, in brackets, the range.",
        "Candidates are **counterfactual rule sets applied as a sandbox patch** of the Nodebuster owner for one run; nothing here is a game change.  Generated by `scripts/ascension_rewards_analysis.py`; the curated reading is in `docs/GC_ASCENSION_REWARDS.md`.",
        "",
        "## 1. Candidates",
        "",
        "| Key | Rule | Rebuild cost | Restart level | Fading surge | AP per run | Prestige (permanent) |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for k in cands:
        c = candidate_defs[k]
        ap = "canonical" if (c["ap_flat"], c["ap_step"]) == (0, 25) else f"+{c['ap_flat']} flat, +1 per {c['ap_step']} levels"
        pr = "-" if not c["prestige_bps"] else f"+{c['prestige_bps'] / 100:g} % per Ascension, max {c['prestige_cap']} (+{c['prestige_bps'] * c['prestige_cap'] / 100:g} %)"
        if c.get("first_yield_bps"):
            pr = (pr + "; " if pr != "-" else "") + f"first Deep Yield rank +{c['first_yield_bps'] / 100:g} % for 1 AP"
        L.append(f"| `{k}` | {c['label']} | x{c['rebuild_cost_bps'] / 10000:g} | {c['restart_pct']} % of best | {'-' if not c['surge_bps'] else '+' + str(c['surge_bps'] // 100) + ' %'} | {ap} | {pr} |")
    L += [
        "",
        "Bounded by construction: rebuild discounts and the surge apply only up to the best depth (never beyond it), the surge fades to zero *at* the best depth (an abrupt end would make the next level reduce output and stall the climb), prestige is capped, the restart level stays below L200, and every other permanent bonus is a skill with a maximum rank.",
        "",
        "## 2. The first reset (arm `O200`: one reset per mine at L200, then keep building)",
        "",
        "*Cliff* = the empire's income right after the first reset relative to a moment before it; *recovered* = days until the empire is back at its own pre-reset income; the other columns are ratios vs `never`: *worst* = lowest income ratio in the 400 days after the reset (this mixes the cliff with the reference's growth, and includes the second mine's reset), *payback* = days after the reset until the cumulative production is level with `never` for good, *real advantage* = days until income is >= 110 % of `never` for good.  `-` = not within 72 months.",
        "",
        "| Candidate | First reset (day) | AP at first reset | Cliff | Recovered (days) | Worst vs never | Income +180 d | Income +365 d | Income +730 d | Payback (days) | Real advantage (days) | Cum. production 24 / 48 / 72 mo |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for k in cands:
        ms = style_metrics(results, "O200", k)
        if not ms:
            continue
        v = list(ms.values())
        L.append(
            f"| `{k}` | {_gd(agg([x['first_reset_day'] for x in v]))} | {_gd(agg([x['ap']['first_run_ap'] for x in v]))} | {_g(agg([x['cliff'] for x in v]))} | {_gd(agg([x['recovered_days'] for x in v]))} | {_g(agg([x['worst_ratio'] for x in v]))} | "
            f"{_g(agg([x.get('income_plus_180') for x in v]))} | {_g(agg([x.get('income_plus_365') for x in v]))} | {_g(agg([x.get('income_plus_730') for x in v]))} | "
            f"{_gd(agg([x['payback_day'] for x in v]))} | {_gd(agg([x['real_advantage_day'] for x in v]))} | "
            f"{_g(agg([x['produced_730'] for x in v]))} / {_g(agg([x['produced_1460'] for x in v]))} / {_g(agg([x['produced_2190'] for x in v]))} |"
        )
    L += [
        "",
        "## 3. Does a later first reset pay sooner? (cumulative payback in days after the reset)",
        "",
        "| Candidate | `O200` | `O250` | `O300` | Income at 48 mo `O200` / `O250` / `O300` |",
        "|---|---:|---:|---:|---|",
    ]
    for k in cands:
        row = []
        incs = []
        for arm in ("O200", "O250", "O300"):
            ms = style_metrics(results, arm, k)
            row.append(_gd(agg([x["payback_day"] for x in ms.values()])) if ms else "-")
            incs.append(_g(agg([x["income_1460"] for x in ms.values()])) if ms else "-")
        L.append(f"| `{k}` | {row[0]} | {row[1]} | {row[2]} | {' / '.join(incs)} |")
    L += [
        "",
        "## 4. AP access",
        "",
        "AP earned by the whole account (both mines of the planet; trees are per mine) and the first skill rank, arm `O200`.",
        "",
        "| Candidate | AP at first reset | Day of first skill rank | AP earned by 24 mo | AP spent by 24 mo | Skills bought by 24 mo (all mines) |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for k in cands:
        ms = style_metrics(results, "O200", k)
        if not ms:
            continue
        v = list(ms.values())
        skills: Dict[str, int] = {}
        for x in v:
            for name, rank in x["ap"]["skills_730"].items():
                skills[name] = max(skills.get(name, 0), int(rank))
        sk = ", ".join(f"{n} {r}" for n, r in sorted(skills.items())) or "-"
        L.append(f"| `{k}` | {_gd(agg([x['ap']['first_run_ap'] for x in v]))} | {_gd(agg([x['ap']['first_skill_day'] for x in v]))} | {_gd(agg([x['ap']['ap_total_by'].get('730') for x in v]))} | {_gd(agg([x['ap']['ap_spent_by'].get('730') for x in v]))} | {sk} |")
    L += ["", "Resets of one mine needed for tree milestones (AP per run at L200 / L250 / L300 under the candidate's rule; the canonical skill costs; trees are per mine):", "", "| Candidate | AP per run | Frugal + Rapid 3 | Deep Yield 4 | Overdrive gate (50 AP) | Whole tree (339 AP) |", "|---|---|---:|---:|---:|---:|"]
    for k in cands:
        a = ap_runs_needed(k)
        cells = [" / ".join(str(a["runs"][name][d]) for d in (200, 250, 300)) for name in a["runs"]]
        L.append(f"| `{k}` | {' / '.join(str(a['per_run'][d]) for d in (200, 250, 300))} | " + " | ".join(cells) + " |")
    L += [
        "",
        "## 5. Design criteria",
        "",
        f"Thresholds are this analysis' operationalisation (medians over the three styles unless stated): **C1** the first reset feels valuable = the cliff leaves >= {th['c1_cliff']:.2f} of the income before the reset and the empire is back at it within {th['c1_recover_days']} days; **C2** the deficit is recoverable = cumulative payback within {th['c2_payback_days']} days (good) or {th['c2_payback_days_ok']} days (ok), for every style; **C3** `never` stays legitimate = cumulative production of the one-reset policy at 48 months within {th['c3'][0]:g}-{th['c3'][1]:g} of `never` and no style above {th['style_max']:g} at 48 or 72 months; **Guard** no multiplier by repetition = no style above {th['style_max']:g} with a treadmill (`T200`), a ladder (`L200+25`) or {4}/{8} resets per mine, and extra resets do not pay (no style gains more than {th['farm_gain']:g} from 4 or 8 resets over a single one).",
        "",
        "| Candidate | C1 valuable | Cliff / recovered (days) | C2 payback | C3 never legit | Guard | All four | Payback (days) | Cum. production 48 mo |",
        "|---|---|---|---|---|---|---|---:|---:|",
    ]
    for k in cands:
        c = criteria(results, k)
        if not c:
            continue
        L.append(f"| `{k}` | {_yes(c['c1_valuable'])} | {_g(c['cliff'])} / {_gd(c['recovered_days'])} | {c['c2_payback']} | {_yes(c['c3_never_legit'])} | {_yes(c['guard_ok'])} | {'**yes**' if c['all_pass'] else 'no'} | {_gd(c['payback_days'])} | {_g(c['produced_1460'])} |")
    L += [
        "",
        "## 6. Guard: repeated resets",
        "",
        "`T200` ascends a mine every time it is back at L200 (a treadmill / AP farm); `L200+25` is a ladder: every further reset needs the previous best depth + 25.  Ratios vs `never`, median (range) across styles.",
        "",
        "| Candidate | Arm | Resets (account) | AP earned by 72 mo | Income 48 mo | Income 72 mo | Cum. production 72 mo | Within guard |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for k in cands:
        g = guard_metrics(results, k)
        for arm, a in g.get("arms", {}).items():
            L.append(f"| `{k}` | `{arm}` | {_gd(a['runs'])} | {_gd(a['ap_2190'])} | {_g(a['income_1460'])} | {_g(a['income_2190'])} | {_g(a['produced_2190'])} | {_yes(a['ok'])} |")
    L += [
        "",
        "Is it worth resetting more than once?  Arms `O200`, `O200x4`, `O200x8`: every mine is reset 1 / 4 / 8 times at L200 (a farm for AP and prestige), then keeps building.  Cumulative production vs `never` at 48 / 72 months, median (range).  *Farming pays for* lists the styles that gain more than the threshold from 4 or 8 resets over a single one.",
        "",
        "| Candidate | 1 reset 48 / 72 mo | 4 resets 48 / 72 mo | 8 resets 48 / 72 mo | AP earned by 72 mo (1 / 4 / 8 resets) | Farming pays for | Highest style ratio |",
        "|---|---|---|---|---|---|---:|",
    ]
    for k in cands:
        f = farming_metrics(results, k)
        if not f["arms"]:
            continue
        cells = []
        aps = []
        for arm in FARM_ARMS:
            a = f["arms"].get(arm)
            cells.append("-" if not a else f"{_g(a['1460'])} / {_g(a['2190'])}")
            aps.append("-" if not a else _gd(a["ap_2190"]))
        L.append(f"| `{k}` | {cells[0]} | {cells[1]} | {cells[2]} | {' / '.join(aps)} | {', '.join(f['pays_for']) or 'nobody'} | {_r(f['max_style_ratio'])} |")
    bad = [r["sid"] for r in results if not r["invariants"].get("ok", True)]
    L += ["", "## 7. Simulator invariants", "", "none violated (AP earned equals the awards of the active candidate rule, AP spent equals the canonical skill costs)" if not bad else "\n".join(f"* {sid}" for sid in bad), ""]
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="active style only, 730-day smoke run")
    ap.add_argument("--days", type=float, default=None)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--candidates", default="", help="comma separated subset of candidate keys")
    ap.add_argument("--resume", default="", help="JSON of an earlier run: scenarios already in it are not run again, new ones are merged in")
    ap.add_argument("--out-json", default="")
    ap.add_argument("--out-md", default="")
    ap.add_argument("--render-from", default="", help="re-render markdown from a saved JSON (no simulation)")
    args = ap.parse_args(argv)
    if args.render_from:
        data = json.loads(Path(args.render_from).read_text(encoding="utf-8"))
    else:
        days = args.days if args.days is not None else (730.0 if args.quick else DAYS)
        keys = tuple(k for k in args.candidates.split(",") if k) or MAIN_ORDER
        specs = build_matrix(days, args.quick, keys)
        known: List[Dict[str, Any]] = []
        if args.resume:
            known = json.loads(Path(args.resume).read_text(encoding="utf-8"))["results"]
            have = {r["sid"] for r in known}
            todo = [s for s in specs if s["sid"] not in have]
        else:
            todo = specs
        results = merge_results(known, run_matrix(todo, args.workers or min(10, max(1, len(todo)))) if todo else [])
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
