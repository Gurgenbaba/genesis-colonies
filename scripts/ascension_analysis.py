#!/usr/bin/env python3
"""GC mine-Ascension long-horizon analysis (measurement only, no gameplay change).

Question: what happens when a player reaches Ascension and rebuilds - and when is an Ascension
economically better than simply continuing to build the mine?

Method.  Everything is executed by ``scripts/player_journey_sim.py`` (asc-model/1) in a throw-away
sandbox through the canonical owners; nothing here touches a live database, a production formula or
a save game.

* **Reset, AP, skills, rebuild discount, rebuild surge, tail bonus, deep storage** are performed by
  ``game.mine_evolution.nodebuster.ascend_mine`` / ``purchase_skill`` against the sandbox DB and read back
  through the production formula / ``EffectResolver`` hooks.  There is no second Ascension engine.
* **Mine queue rules** follow the authoritative Buildings owner under ``nodebuster-v1``: production mines
  and the solar plant have *no* level cap (queue sentinel 2^31-1).  The nexus buildings only matter
  for the depot cap.  The ``legacy`` arm keeps the resolver's L200 nexus cap of the bottleneck report
  (pj/1) purely as a reference.
* **Arms** (all policy v2, same costs / queue depth / action windows):
  ``legacy`` (reference), ``never`` (keep building, never reset), ``T200/T225/T250/T300`` (ascend each
  production mine the first time it is at depth >= T, one mine per planet rebuilds at a time) and two
  AP spending orders (``y`` = yield first).  No reset is ever forced: an arm that does not reach its
  threshold simply stays at zero Ascensions.

Run:
  python scripts/ascension_analysis.py --out-json artifacts/ascension/latest.json \
      --out-md docs/GC_ASCENSION_SIMULATION_REPORT.md
  python scripts/ascension_analysis.py --quick --stdout          # 60-day smoke run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.progression_bottleneck_analysis import (  # noqa: E402
    _f,
    _human,
    ledger_conservation_error,
    ledger_delta_shares,
    production_losses,
    rel,
)

ANALYSIS_VERSION = "ascension-analysis/1"
STYLES: Tuple[str, ...] = ("casual", "active", "optimizer")
TOPOLOGIES: Tuple[str, ...] = ("S1", "S11")
DAYS = 730.0
EXTENDED_DAYS = 2190.0  # S1 only, beyond the requested 24 months: where does Ascension start to pay?
CHECK_KEYS: Tuple[str, ...] = ("182.5", "365", "730")
EXT_KEYS: Tuple[str, ...] = ("1095", "1460", "2190")
CHECK_LABEL = {"182.5": "6 mo", "365": "12 mo", "730": "24 mo", "1095": "36 mo", "1460": "48 mo", "2190": "72 mo"}
MINE_MILESTONES: Tuple[int, ...] = (50, 100, 150, 200, 225, 250, 300)

# arm key -> (asc mode, AP order, description)
ARMS: Dict[str, Tuple[str, str, str]] = {
    "legacy": ("legacy", "rebuild_first", "reference: resolver nexus cap L200, no Ascension (model of the bottleneck report)"),
    "never": ("never", "rebuild_first", "canonical queue rules, never ascend: keep building"),
    "T200": ("T200", "rebuild_first", "ascend each mine at the first possible depth (L200)"),
    "T225": ("T225", "rebuild_first", "ascend at depth >= 225 (2 AP per run)"),
    "T250": ("T250", "rebuild_first", "ascend at depth >= 250 (3 AP per run)"),
    "T300": ("T300", "rebuild_first", "ascend at depth >= 300 (6 AP per run)"),
    "T200y": ("T200", "yield_first", "T200 with AP into Deep Yield first"),
    "T250y": ("T250", "yield_first", "T250 with AP into Deep Yield first"),
    "T400": ("T400", "rebuild_first", "ascend at depth >= 400 (11 AP per run); extended horizon only"),
}
MAIN_ARMS: Tuple[str, ...] = ("legacy", "never", "T200", "T225", "T250", "T300", "T200y", "T250y")
EXT_ARMS: Tuple[str, ...] = ("never", "T200", "T250", "T300", "T400")
SENSITIVITY_ARMS: Tuple[str, ...] = ("never", "T200")
PLAYER_RULE_CAUSES = ("wait_metal", "wait_crystal", "wait_storage_build", "wait_energy_drag", "research_prerequisite", "storage_cap_below_cost", "no_goal")


# ---------------------------------------------------------------------------
# Matrix / runner
# ---------------------------------------------------------------------------


def build_matrix(days: float = DAYS, quick: bool = False, extended: bool = True, subset: str = "main") -> List[Dict[str, Any]]:
    from scripts import player_journey_sim as pj

    styles = ("active",) if quick else STYLES
    out: List[Dict[str, Any]] = []

    def add(topo: str, style: str, arm: str, horizon: float) -> None:
        mode, order, _doc = ARMS[arm]
        suffix = f"-{int(horizon)}d" if horizon == EXTENDED_DAYS else ""
        out.append(
            {
                "sid": f"{topo}-{style}-{arm}{suffix}",
                "topology": topo,
                "policy": style,
                "strategy": "v2",
                "arm": arm,
                "asc": mode,
                "asc_skills": order,
                "days": float(horizon),
                "rng_seed": pj.ELIGIBLE_HOME_SEED if topo == "S11" else None,
            }
        )

    if subset == "outpost":  # sensitivity to the not-yet-integrated outpost-XP fix (run in a checkout that has the fix)
        for style in STYLES:
            for arm in SENSITIVITY_ARMS:
                add("S11", style, arm, days)
        return out
    arms = ("legacy", "never", "T200") if quick else MAIN_ARMS
    for topo in TOPOLOGIES:
        for style in styles:
            for arm in arms:
                add(topo, style, arm, days)
    if extended and not quick:
        for style in STYLES:
            for arm in EXT_ARMS:
                add("S1", style, arm, EXTENDED_DAYS)
    return out


def _slim_asc(a: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not a:
        return None
    mines = [
        {k: m[k] for k in ("world", "mine", "level", "peak_depth", "ascensions", "ap_earned", "ap_spent", "ap_unspent", "best_depth", "skills", "rebuilding")}
        for m in a.get("mines", [])
        if m["ascensions"] > 0 or m["peak_depth"] >= 150
    ]
    out = {k: a[k] for k in ("mode", "skill_order", "ascensions_total", "ascensions_max_single_mine", "ap_earned_total", "ap_spent_total", "peak_depth_max", "mines_rebuilding")}
    out["mines"] = mines
    return out


def _slim_snapshot(c: Dict[str, Any]) -> Dict[str, Any]:
    keep = (
        "day", "worlds", "established", "mine_depth_max", "crystal_depth_max", "peak_depth_max", "empire_metal_h",
        "empire_crystal_h", "empire_fuel_h", "elapsed_sec", "spend_metal", "spend_crystal", "research_queue_busy_pct",
    )
    out = {k: c.get(k) for k in keep if k in c}
    pw_keep = (
        "idx", "outpost", "age_sec", "time_ledger_sec", "wasted_metal", "wasted_crystal", "wasted_fuel", "produced_metal",
        "produced_crystal", "produced_fuel", "lost_to_energy_metal", "lost_to_energy_crystal", "lost_to_energy_fuel",
        "energy_low_days", "storage_full_days", "planet_level", "queue_busy_pct", "buildings", "metal_h", "crystal_h",
    )
    out["per_world"] = [{k: w.get(k) for k in pw_keep} for w in c.get("per_world", [])]
    out["ascension"] = _slim_asc(c.get("ascension"))
    return out


def run_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """One scenario, executed in a worker process (the sandbox owns process-global state)."""
    from scripts import player_journey_sim as pj

    sc = pj.Scenario(
        spec["sid"], spec["topology"], spec["policy"], "mid", "none", float(spec["days"]),
        rng_seed=spec.get("rng_seed"), strategy=spec["strategy"], asc=spec["asc"], asc_skills=spec["asc_skills"],
    )
    res = pj.run_scenario(sc)
    days = float(spec["days"])
    snaps: Dict[str, Any] = {}
    for key in CHECK_KEYS + EXT_KEYS:
        label = "day%s" % key
        if float(key) <= days:
            c = res["checkpoints"].get(label)
            if c is None and abs(float(key) - days) < 1e-9:
                c = res["final"]
            if c is not None:
                snaps[key] = _slim_snapshot(c)
    if "end" not in snaps:
        snaps["end"] = _slim_snapshot(res["final"])
    peak_of = lambda r: int(r.get("peak_depth_max", r["mine_depth_max"]))  # noqa: E731
    milestones = {str(lvl): next((int(r["day"]) for r in res["daily"] if peak_of(r) >= lvl), None) for lvl in MINE_MILESTONES}
    founded = [e["day"] for e in res["colony_log"] if e["event"] == "founded"]
    series = [
        (int(r["day"]), int(r["empire_metal_h"]) + int(r["empire_crystal_h"]), peak_of(r), int(r.get("ascensions_total", 0)), int(r["worlds"]))
        for r in res["daily"][::5]
    ]
    return {
        "sid": spec["sid"],
        "topology": spec["topology"],
        "policy": spec["policy"],
        "arm": spec["arm"],
        "asc": spec["asc"],
        "asc_skills": spec["asc_skills"],
        "days": days,
        "status": res["status"],
        "wall_seconds": res["wall_seconds"],
        "snapshots": snaps,
        "mine_milestone_day": milestones,
        "colonies_founded_day": founded,
        "ascension_runs": res.get("ascension_runs", []),
        "ascension_skill_log": res.get("ascension_skill_log", []),
        "ascension_rejections": res.get("ascension_rejections", {}),
        "invariants": res["invariants"],
        "series": series,
    }


def run_matrix(specs: List[Dict[str, Any]], workers: int, progress: bool = True) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    started = time.time()
    # longest scenarios first so the pool stays busy
    specs = sorted(specs, key=lambda s: (-float(s["days"]) * (4 if s["topology"] == "S11" else 1), s["sid"]))
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


def find(results: List[Dict[str, Any]], topology: str, style: str, arm: str, days: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Result of one scenario; `days=None` selects the main (requested-horizon) run, never the extended one."""
    for r in results:
        if r["topology"] != topology or r["policy"] != style or r["arm"] != arm:
            continue
        if days is None:
            if abs(float(r["days"]) - EXTENDED_DAYS) > 1e-9:
                return r
        elif abs(float(r["days"]) - days) < 1e-9:
            return r
    return None


def snap(res: Optional[Dict[str, Any]], key: str) -> Optional[Dict[str, Any]]:
    if not res:
        return None
    s = res["snapshots"].get(key)
    if s is None and abs(float(key) - float(res["days"])) < 1e-9:
        s = res["snapshots"].get("end")
    return s


def income(s: Dict[str, Any]) -> float:
    return float(s["empire_metal_h"]) + float(s["empire_crystal_h"])


def peak_depth(s: Dict[str, Any]) -> int:
    asc = s.get("ascension") or {}
    return int(asc.get("peak_depth_max") or s.get("peak_depth_max") or max(int(s.get("mine_depth_max") or 0), int(s.get("crystal_depth_max") or 0)))


def asc_counts(s: Dict[str, Any]) -> Tuple[int, int, int, int]:
    """(ascensions total, max on a single mine, AP earned, AP spent)."""
    a = s.get("ascension") or {}
    return int(a.get("ascensions_total") or 0), int(a.get("ascensions_max_single_mine") or 0), int(a.get("ap_earned_total") or 0), int(a.get("ap_spent_total") or 0)


def ascension_days(res: Dict[str, Any]) -> List[float]:
    return sorted(float(r["day"]) for r in res.get("ascension_runs", []))


def nth_ascension_day(res: Dict[str, Any], n: int) -> Optional[float]:
    days = ascension_days(res)
    return days[n - 1] if len(days) >= n else None


def third_on_one_mine_day(res: Dict[str, Any]) -> Optional[float]:
    """Day of the third completed Ascension of any single (planet, mine) pair, if any."""
    per: Dict[Tuple[int, str], List[float]] = {}
    for r in res.get("ascension_runs", []):
        per.setdefault((int(r["world"]), str(r["mine"])), []).append(float(r["day"]))
    thirds = [sorted(v)[2] for v in per.values() if len(v) >= 3]
    return min(thirds) if thirds else None


def rebuild_stats(res: Dict[str, Any]) -> Dict[str, Optional[float]]:
    runs = res.get("ascension_runs", [])
    done = [float(r["rebuild_to_best_days"]) for r in runs if r.get("rebuild_to_best_days") is not None]
    rec = [float(r["income_recovered_days"]) for r in runs if r.get("income_recovered_days") is not None]
    cliff = [100.0 * (1.0 - float(r["income_after_h"]) / float(r["income_before_h"])) for r in runs if float(r.get("income_before_h") or 0) > 0]
    return {
        "runs": len(runs),
        "rebuilt": len(done),
        "rebuild_days_median": median(done) if done else None,
        "income_recovered_median": median(rec) if rec else None,
        "income_cliff_pct_median": median(cliff) if cliff else None,
    }


def crossing_day(series: List[List[float]], ref_series: List[List[float]], after_day: float = 0.0) -> Optional[int]:
    """First sampled day after `after_day` from which the arm's income stays >= the reference arm's until the end; None if it never does."""
    ref = {int(d): float(inc) for d, inc, *_ in ref_series}
    ok: Optional[int] = None
    for d, inc, *_ in series:
        d = int(d)
        if d <= after_day or d not in ref:
            continue
        if float(inc) >= ref[d]:
            if ok is None:
                ok = d
        else:
            ok = None
    return ok


def delta_vs(results: List[Dict[str, Any]], topology: str, style: str, arm: str, ref_arm: str, key: str, days: Optional[float] = None) -> Dict[str, Optional[float]]:
    a, b = snap(find(results, topology, style, arm, days), key), snap(find(results, topology, style, ref_arm, days), key)
    if not a or not b:
        return {"income_pct": None, "depth_delta": None}
    return {"income_pct": rel(income(a), income(b)), "depth_delta": float(peak_depth(a) - peak_depth(b))}


def interval_shares(res: Dict[str, Any], start_key: Optional[str], end_key: str) -> Dict[str, float]:
    end = snap(res, end_key)
    start = snap(res, start_key) if start_key else None
    return ledger_delta_shares(end, start) if end else {}


def skill_rank_totals(s: Dict[str, Any]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for m in (s.get("ascension") or {}).get("mines", []):
        for k, v in (m.get("skills") or {}).items():
            out[k] = out.get(k, 0) + int(v)
    return out


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _pct(v: Optional[float], digits: int = 0) -> str:
    return "n/a" if v is None else f"{v:+.{digits}f}%"


def _day(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:.0f}"


def render_markdown(data: Dict[str, Any]) -> str:
    results = data["results"]
    ext = data.get("extended", [])
    L: List[str] = []
    L += [
        "# GC - Mine Ascension long-horizon simulation (measurement only)",
        "",
        f"Analysis `{data['meta']['analysis_version']}`, simulator `{data['meta']['sim_version']}` / `{data['meta']['asc_model_version']}`, "
        f"code `{data['meta']['code_sha'][:10]}`.  Generated by `scripts/ascension_analysis.py`; **no game value, formula or save game is changed.**",
        "",
        "Everything below runs the canonical owners (`nodebuster.ascend_mine`, `purchase_skill`, `EffectResolver`, production formula, Buildings queue "
        "rules) in a throw-away sandbox.  Policy v2 (payback-ranked purchases) for every arm; same costs, queue depth and action windows.  "
        "**The baseline contains the outpost-XP defect fixed in PR #556 (not integrated); section 9 measures its influence.**",
        "",
        "## Arms",
        "",
        "| Arm | Rule |",
        "|---|---|",
    ]
    for arm, (_mode, order, doc) in ARMS.items():
        if arm in {r["arm"] for r in results} | {r["arm"] for r in ext}:
            L.append(f"| `{arm}` | {doc} (AP order `{order}`) |")
    L += [""]

    # 1. Income and depth by arm
    L += ["## 1. Production, mine depth and Ascensions by arm", "", "Income = empire metal + crystal per hour. Depth = deepest production mine ever reached. Asc = completed Ascensions (all mines) / most on one mine.", ""]
    for topo in TOPOLOGIES:
        L += [f"### {topo}", "", "| Style | Arm | 6 mo depth | income/h | Asc | 12 mo depth | income/h | Asc | 24 mo depth | income/h | Asc (max/mine) | AP earned / spent |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for style in STYLES:
            for arm in MAIN_ARMS:
                r = find(results, topo, style, arm)
                if not r:
                    continue
                cells: List[str] = []
                for key in CHECK_KEYS:
                    s = snap(r, key)
                    if not s:
                        cells += ["n/a", "n/a", "n/a"]
                        continue
                    tot, mx, _e, _s = asc_counts(s)
                    cells += [f"L{peak_depth(s)}", _human(income(s)), (f"{tot} ({mx})" if key == "730" else str(tot))]
                s24 = snap(r, "730")
                ap = asc_counts(s24)[2:] if s24 else (0, 0)
                L.append(f"| {style} | `{arm}` | " + " | ".join(cells) + f" | {ap[0]} / {ap[1]} |")
        L += [""]

    # 2. Does ascending pay?
    L += ["## 2. Ascend or keep building? (change against `never`, same style and topology)", "", "Income = empire metal + crystal per hour; depth = deepest mine ever reached. Break-even = first day from which the arm's income stays at or above `never`.", "", "| Topology | Style | Arm | Income 6 mo | 12 mo | 24 mo | Depth vs never 24 mo | Break-even day |", "|---|---|---|---:|---:|---:|---:|---:|"]
    for topo in TOPOLOGIES:
        for style in STYLES:
            ref = find(results, topo, style, "never")
            for arm in ("T200", "T225", "T250", "T300", "T200y", "T250y"):
                r = find(results, topo, style, arm)
                if not r or not ref:
                    continue
                cells = [_pct(delta_vs(results, topo, style, arm, "never", k)["income_pct"]) for k in CHECK_KEYS]
                dd = delta_vs(results, topo, style, arm, "never", "730")["depth_delta"]
                first = nth_ascension_day(r, 1)
                be = "no ascension" if first is None else _day(crossing_day(r["series"], ref["series"], first))
                L.append(f"| {topo} | {style} | `{arm}` | " + " | ".join(cells) + f" | {_f(dd, 0, True)} | {be} |")
    L += [""]

    # 3. Feasibility of three Ascensions
    L += ["## 3. Are three Ascensions reachable within 24 months?", "", "Day of the 1st / 2nd / 3rd Ascension of any mine, and of the 3rd Ascension of one single mine. `-` = not reached inside 730 days (a result, not a failure).", "", "| Topology | Style | Arm | 1st | 2nd | 3rd (any mine) | 3rd on one mine | Total | Max on one mine |", "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for topo in TOPOLOGIES:
        for style in STYLES:
            for arm in ("T200", "T225", "T250", "T300", "T200y", "T250y"):
                r = find(results, topo, style, arm)
                if not r:
                    continue
                s = snap(r, "730")
                tot, mx, _e, _s = asc_counts(s) if s else (0, 0, 0, 0)
                L.append(f"| {topo} | {style} | `{arm}` | {_day(nth_ascension_day(r, 1))} | {_day(nth_ascension_day(r, 2))} | {_day(nth_ascension_day(r, 3))} | {_day(third_on_one_mine_day(r))} | {tot} | {mx} |")
    L += [""]

    # 4. Rebuild
    L += ["## 4. Reset and rebuild", "", "Per arm: completed Ascensions, share that climbed back through the previous best depth inside the horizon, median rebuild time, median time until the planet's metal+crystal income is back at its pre-reset level, and the median income cliff directly after the reset.", "", "| Topology | Style | Arm | Runs | Rebuilt | Rebuild days (median) | Income back (median days) | Income cliff after reset |", "|---|---|---|---:|---:|---:|---:|---:|"]
    for topo in TOPOLOGIES:
        for style in STYLES:
            for arm in ("T200", "T225", "T250", "T300", "T200y", "T250y"):
                r = find(results, topo, style, arm)
                if not r or not r.get("ascension_runs"):
                    continue
                st = rebuild_stats(r)
                L.append(f"| {topo} | {style} | `{arm}` | {st['runs']} | {st['rebuilt']} | {_f(st['rebuild_days_median'], 0)} | {_f(st['income_recovered_median'], 0)} | {_f(st['income_cliff_pct_median'], 0)}% |")
    L += [""]

    # 5. AP and skills
    L += ["## 5. Ascension Points and skills (24 months)", "", "AP are granted only by the canonical award (`1 + (depth-200)//25 + (depth-200)//100`); skills are bought only through `purchase_skill`. Unspent AP are saved for the next priority skill.", "", "| Topology | Style | Arm | AP earned | AP spent | Skill ranks bought (all mines) |", "|---|---|---|---:|---:|---|"]
    for topo in TOPOLOGIES:
        for style in STYLES:
            for arm in ("T200", "T225", "T250", "T300", "T200y", "T250y"):
                r = find(results, topo, style, arm)
                s = snap(r, "730") if r else None
                if not s:
                    continue
                tot, _mx, earned, spent = asc_counts(s)
                if tot == 0:
                    continue
                sk = skill_rank_totals(s)
                L.append(f"| {topo} | {style} | `{arm}` | {earned} | {spent} | " + (", ".join(f"{k} {v}" for k, v in sorted(sk.items())) or "-") + " |")
    L += [""]

    # 6. Queue utilisation and the cap correction
    L += ["## 6. Queue utilisation and the L200-cap correction", "", "Share of all world-seconds by cause. `legacy` is the bottleneck-report model (resolver nexus cap, nothing to build after L200); `never` follows the canonical queue rules.", "", "| Topology | Style | Arm | Months | Queue running | Wait metal | Wait crystal | Wait depot | Research prereq | Nothing to build | Player not acting |", "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for topo in TOPOLOGIES:
        for style in STYLES:
            for arm in ("legacy", "never", "T200", "T250"):
                r = find(results, topo, style, arm)
                if not r:
                    continue
                for label, a, b in (("0-6", None, "182.5"), ("6-12", "182.5", "365"), ("12-24", "365", "730")):
                    sh = interval_shares(r, a, b)
                    if not sh:
                        continue
                    g = lambda k: sh.get(k, 0.0)  # noqa: E731
                    L.append(
                        f"| {topo} | {style} | `{arm}` | {label} | {g('busy'):.0f}% | {g('wait_metal'):.0f}% | {g('wait_crystal'):.0f}% | {g('wait_storage_build') + g('storage_cap_below_cost'):.0f}% | "
                        f"{g('research_prerequisite'):.0f}% | {g('no_goal'):.0f}% | {g('player_not_acting'):.0f}% |"
                    )
    L += [""]

    # 7. Production losses
    L += ["## 7. Production lost to full depots / energy (24 months)", "", "| Topology | Style | Arm | Depot loss metal | crystal | Energy loss metal | crystal |", "|---|---|---|---:|---:|---:|---:|"]
    for topo in TOPOLOGIES:
        for style in STYLES:
            for arm in ("legacy", "never", "T200"):
                r = find(results, topo, style, arm)
                s = snap(r, "730") if r else None
                if not s:
                    continue
                pl = production_losses(s)
                L.append(f"| {topo} | {style} | `{arm}` | {pl['depot_metal']:.1f}% | {pl['depot_crystal']:.1f}% | {pl['energy_metal']:.1f}% | {pl['energy_crystal']:.1f}% |")
    L += [""]

    # 8. Extended horizon
    if ext:
        L += ["## 8. Extended horizon (S1, beyond the requested 24 months)", "", "Exploration only: one planet, up to 72 months, to find where an Ascension starts to pay. Income change against `never` of the same style.", "", "| Style | Arm | Depth 24 mo | 36 mo | 48 mo | 72 mo | Income vs never 36 mo | 48 mo | 72 mo | Ascensions (72 mo) | Break-even day |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for style in STYLES:
            ref = find(ext, "S1", style, "never", EXTENDED_DAYS)
            for arm in EXT_ARMS:
                r = find(ext, "S1", style, arm, EXTENDED_DAYS)
                if not r:
                    continue
                depth = [f"L{peak_depth(snap(r, k))}" if snap(r, k) else "n/a" for k in ("730", "1095", "1460", "2190")]
                d = [_pct(delta_vs(ext, "S1", style, arm, "never", k, EXTENDED_DAYS)["income_pct"]) if arm != "never" else "-" for k in ("1095", "1460", "2190")]
                s = snap(r, "2190")
                tot = asc_counts(s)[0] if s else 0
                first = nth_ascension_day(r, 1)
                be = "-" if arm == "never" else ("no ascension" if first is None else _day(crossing_day(r["series"], ref["series"], first) if ref else None))
                L.append(f"| {style} | `{arm}` | " + " | ".join(depth) + " | " + " | ".join(d) + f" | {tot} | {be} |")
        L += [""]

    # 9. Outpost fix sensitivity
    sens = data.get("outpost_fix_sensitivity")
    if sens:
        L += ["## 9. Influence of the outpost-XP fix (PR #556)", "", "Same scenarios in a checkout with the fix applied; columns are the change of the fixed run against the unfixed baseline of this report.", "", "| Style | Arm | 11th world day (base -> fixed) | Income 12 mo | Income 24 mo | Peak depth 24 mo |", "|---|---|---|---:|---:|---:|"]
        for style in STYLES:
            for arm in SENSITIVITY_ARMS:
                base, fixed = find(results, "S11", style, arm), find(sens, "S11", style, arm)
                if not base or not fixed:
                    continue
                b11 = base["colonies_founded_day"][9] if len(base["colonies_founded_day"]) >= 10 else None
                f11 = fixed["colonies_founded_day"][9] if len(fixed["colonies_founded_day"]) >= 10 else None
                cells = []
                for key in ("365", "730"):
                    a, b = snap(fixed, key), snap(base, key)
                    cells.append(_pct(rel(income(a), income(b))) if a and b else "n/a")
                a24, b24 = snap(fixed, "730"), snap(base, "730")
                dd = (peak_depth(a24) - peak_depth(b24)) if a24 and b24 else None
                L.append(f"| {style} | `{arm}` | {_day(b11)} -> {_day(f11)} | {cells[0]} | {cells[1]} | {_f(dd, 0, True)} |")
        L += [""]

    # 10. Invariants
    bad = [r["sid"] for r in results + ext if not r["invariants"]["ok"]]
    err = max([ledger_conservation_error(snap(r, "730") or r["snapshots"]["end"]) for r in results] or [0.0])
    L += ["## 10. Invariants", "", f"* scenarios: {len(results) + len(ext)}; invariant violations: {len(bad)} {bad[:5] if bad else ''}", f"* time-ledger conservation error (worst world): {err:.2e}", "* AP earned equals the sum of the canonical awards of the completed runs; AP spent equals the canonical cost of the owned skill ranks (checked daily inside the simulator).", ""]
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

ASSUMPTIONS = [
    "Policy v2 for every arm; the Ascension arms only add the reset rule and the AP spending order. The same action windows, queue depth and costs apply.",
    "The ascension policy is deliberately simple and legal: ascend a production mine the first time it is at depth >= T with an empty mine queue; only one mine per planet rebuilds at a time (income continuity); AP are spent in a fixed strict-priority order.",
    "No forced resets: an arm that never reaches its threshold shows zero Ascensions.",
    "Mine and solar queue caps follow the Buildings owner under nodebuster-v1 (no cap); the geothermal nexus is built only to lift the depot cap.",
    "Not modelled: Research-Lab Ascension, Stellar Forge, Trader, fleet fuel use, military sinks, loot, Timekeeper/Battle-Pass skips, alliance/commander/booster modifiers.",
]


def meta_block(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    from scripts import player_journey_sim as pj

    return {
        "analysis_version": ANALYSIS_VERSION,
        "sim_version": pj.SIM_VERSION,
        "asc_model_version": pj.ASC_MODEL_VERSION,
        "code_sha": pj.code_sha(),
        "scenarios": len(specs),
        "assumptions": ASSUMPTIONS,
        "not_modelled": pj.NOT_MODELLED,
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="active style, three arms, 400-day smoke run")
    ap.add_argument("--days", type=float, default=None)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--no-extended", action="store_true")
    ap.add_argument("--subset", choices=("main", "outpost"), default="main")
    ap.add_argument("--out-json", default="")
    ap.add_argument("--out-md", default="")
    ap.add_argument("--render-from", default="", help="re-render markdown from a saved JSON (no simulation)")
    ap.add_argument("--sensitivity-json", default="", help="JSON of a --subset outpost run made in a checkout with the outpost-XP fix")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args(argv)

    if args.render_from:
        data = json.loads(Path(args.render_from).read_text(encoding="utf-8"))
    else:
        days = args.days if args.days is not None else (400.0 if args.quick else DAYS)
        specs = build_matrix(days, args.quick, extended=not args.no_extended, subset=args.subset)
        workers = args.workers or min(10, len(specs))
        results = run_matrix(specs, workers)
        main_rows = [r for r in results if abs(float(r["days"]) - days) < 1e-9]
        ext_rows = [r for r in results if abs(float(r["days"]) - days) >= 1e-9]
        data = {"meta": meta_block(specs), "results": main_rows, "extended": ext_rows}
    if args.sensitivity_json:
        sens = json.loads(Path(args.sensitivity_json).read_text(encoding="utf-8"))
        data["outpost_fix_sensitivity"] = sens["results"]
    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    md = render_markdown(data) if args.subset == "main" else ""
    if args.out_md and md:
        Path(args.out_md).write_text(md + "\n", encoding="utf-8")
    if args.stdout and md:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
