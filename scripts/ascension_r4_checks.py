#!/usr/bin/env python3
"""Robustness checks of the Ascension candidate ``r4`` (measurement only, no game change).

``r4`` ("Record Milestones": awakening +7 %, keep 85 % of the record, two record tiers, AP only for record progress) meets the four
acceptance checks of ``ascension_milestones_analysis`` on the boundary of each.  This module runs the suites that test how much that is
worth:

* ``grid``     the neighbourhood of r4 (awakening x tier reward, kept share, rebuild cost): where do the checks hold, and with what margin?
* ``stress``   farming stress: a button-masher (policy ``A200``), micro ladders (``L200+1`` / ``L200+10``), crystal-only, very late resets
* ``strategy`` the older player strategy (pj-policy/1: goal list + patience) instead of pj-policy/2 (payback ranked)
* ``gates``    the colonisation gate PL10 / PL12 (PL15 is the base run) on 11 planets
* ``casual``   why does the whole-empire reset take the casual style 507 days and the metal-only start 329?  (spend by category, queue occupancy)

The world seed is not a suite: it changes the homeworld's coordinates and DNA only, and a probe showed that one planet and 11 planets give the
identical economy for every seed (see ``tests/test_ascension_r4_checks.py``).

Run::

    python scripts/ascension_r4_checks.py --suite casual --workers 11 --out-json artifacts/ascension_r4/casual.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import ascension_milestones_analysis as mi  # noqa: E402
from scripts import ascension_rewards_analysis as ar  # noqa: E402
from scripts.ascension_rewards_analysis import Candidate  # noqa: E402

ANALYSIS_VERSION = "ascension-r4-checks/1"
STYLES = ar.STYLES
DAYS = 2190.0
R4 = mi.CANDIDATES["r4"]
SUITES: Tuple[str, ...] = ("casual", "grid", "stress", "strategy", "gates")

GRID_ARMS: Tuple[str, ...] = ("O200", "P200", "L200+50x2", "L200+50x3", "O250", "O300", "O200x4")
STRESS_ARMS_S1: Tuple[str, ...] = ("A200", "L200+1", "L200+10", "C200", "O350", "O400")
STRESS_ARMS_S11: Tuple[str, ...] = ("A200", "L200+10", "C200")
STRATEGY_ARMS: Tuple[str, ...] = ("O200", "P200", "L200+50x2", "L200+50x3", "O300", "O200x4")
GATE_LEVERS: Dict[str, str] = {"PL10": "colony_gate_pl10", "PL12": "colony_gate_pl12"}
CASUAL_ARMS: Tuple[str, ...] = ("O200", "P200", "C200")


def grid_candidates() -> Dict[str, Candidate]:
    """r4 and its neighbours: awakening 6-8 % x tier reward 2-3 % (r4 = 7 % / 2.5 %, r1 = 7 % / 3 %) and one step in kept share and rebuild cost."""
    out: Dict[str, Candidate] = {}
    for a in (600, 650, 700, 750, 800):
        for y in (200, 250, 300):
            if (a, y) in ((700, 250), (700, 300)):  # r4, r1 exist
                continue
            out[f"g{a}_{y}"] = replace(R4, key=f"g{a}_{y}", label=f"r4 with awakening +{a / 100:g} %, +{y / 100:g} % output per tier", awaken_bps=a, tier_yield_bps=y)
    for pct in (80, 90):
        out[f"gk{pct}"] = replace(R4, key=f"gk{pct}", label=f"r4 keeping {pct} % of the record", restart_pct=pct)
    for cost in (2500, 3500):
        out[f"gc{cost // 100}"] = replace(R4, key=f"gc{cost // 100}", label=f"r4 with rebuild cost x{cost / 10000:g}", rebuild_cost_bps=cost)
    return out


def all_candidates() -> Dict[str, Candidate]:
    return {k: mi.CANDIDATES[k] for k in ("canon", "rank1_fast", "m1", "r1", "r4")} | grid_candidates()


def _spec(sid: str, topology: str, style: str, arm: str, cand: str, days: float, **extra: Any) -> Dict[str, Any]:
    cands = all_candidates()
    out = {"sid": sid, "topology": topology, "style": style, "arm": arm, "cand": cand, "days": float(days), "cand_params": asdict(cands[cand])}
    out.update(extra)
    return out


def build_specs(suite: str, days: float = DAYS) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if suite == "grid":
        # never and r4 / r1 already exist in artifacts/ascension_milestones/s1.json (merged on resume); only the new neighbours run here
        for style in STYLES:
            for cand in grid_candidates():
                for arm in GRID_ARMS:
                    out.append(_spec(f"S1-{style}-{arm}-{cand}", "S1", style, arm, cand, days))
    elif suite == "stress":
        for style in STYLES:
            for cand in ("r4", "rank1_fast", "m1"):
                for arm in STRESS_ARMS_S1:
                    out.append(_spec(f"S1-{style}-{arm}-{cand}", "S1", style, arm, cand, days))
            for arm in STRESS_ARMS_S11:
                out.append(_spec(f"S11-{style}-{arm}-r4", "S11", style, arm, "r4", days))
    elif suite == "strategy":
        for style in STYLES:
            out.append(_spec(f"S1v1-{style}-never", "S1", style, "never", "canon", days, strategy="v1", variant="v1"))
            for cand in ("rank1_fast", "m1", "r4"):
                for arm in STRATEGY_ARMS:
                    out.append(_spec(f"S1v1-{style}-{arm}-{cand}", "S1", style, arm, cand, days, strategy="v1", variant="v1"))
    elif suite == "gates":
        for gate, lever in GATE_LEVERS.items():
            for style in STYLES:
                out.append(_spec(f"S11{gate}-{style}-never", "S11", style, "never", "canon", days, lever=lever, variant=gate))
                for cand in ("rank1_fast", "r4"):
                    for arm in ("O200", "P200") + (("L200+50x2", "L200+50x3") if cand == "r4" else ()):
                        out.append(_spec(f"S11{gate}-{style}-{arm}-{cand}", "S11", style, arm, cand, days, lever=lever, variant=gate))
    elif suite == "casual":
        for style in STYLES:
            out.append(_spec(f"S11d-{style}-never", "S11", style, "never", "canon", 1460.0, diag=True, variant="diag"))
            for arm in CASUAL_ARMS:
                out.append(_spec(f"S11d-{style}-{arm}-r4", "S11", style, arm, "r4", 1460.0, diag=True, variant="diag"))
    else:
        raise ValueError(f"unknown suite {suite!r}")
    return out


def run_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """Like the milestone runner, but the candidate travels with the spec (grid neighbours are not registered anywhere)."""
    from scripts import ascension_milestones_analysis as m

    params = spec.get("cand_params")
    if params:
        m.CANDIDATES[spec["cand"]] = Candidate(**params)  # worker-local registration: each scenario runs in its own call
    return m.run_spec(spec)


def run_matrix(specs: List[Dict[str, Any]], workers: int) -> List[Dict[str, Any]]:
    import time
    from concurrent.futures import ProcessPoolExecutor, as_completed

    results: List[Dict[str, Any]] = []
    started = time.time()
    specs = sorted(specs, key=lambda s: (-float(s["days"]), s["topology"] != "S11", s["style"] != "optimizer", s["sid"]))  # the slowest first keeps the pool busy
    if workers <= 1:
        for i, spec in enumerate(specs, 1):
            results.append(run_spec(spec))
            print(f"[{i}/{len(specs)}] {spec['sid']} ({time.time() - started:.0f}s)", file=sys.stderr, flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(run_spec, s): s for s in specs}
            for i, fut in enumerate(as_completed(futures), 1):
                results.append(fut.result())
                print(f"[{i}/{len(specs)}] {futures[fut]['sid']} ({time.time() - started:.0f}s)", file=sys.stderr, flush=True)
    results.sort(key=lambda r: r["sid"])
    return results


# ---------------------------------------------------------------------------
# Analysis (pure functions over slim results; unit-tested)
# ---------------------------------------------------------------------------

K1_LIMIT = mi.PAYBACK_OK_DAYS
K2_MIN_GAIN = mi.REPEAT_MIN_GAIN


def load(path: Path) -> List[Dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["results"] if Path(path).exists() else []


def by_variant(results: Sequence[Dict[str, Any]], variant: str) -> List[Dict[str, Any]]:
    return [r for r in results if (r.get("variant") or "") == variant]


def margins(c: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Distance of a candidate to each limit (positive = inside the limit): payback days, gain of the 2nd reset, best response."""
    return {
        "k1_days": None if c.get("slowest_payback") is None else K1_LIMIT - c["slowest_payback"],
        "k2_gain": None if not c.get("gain2") else c["gain2"][0] - K2_MIN_GAIN,
        "k4_ratio": None if c.get("max_style_ratio") is None else ar.STYLE_MAX - c["max_style_ratio"],
    }


def grid_rows(results: Sequence[Dict[str, Any]], names: Sequence[str]) -> List[Dict[str, Any]]:
    cands = all_candidates()
    rows: List[Dict[str, Any]] = []
    for name in names:
        c = mi.criteria(results, name)
        if not c:
            continue
        cand = cands.get(name) or mi.CANDIDATES[name]
        rows.append({"cand": name, "awaken_bps": cand.awaken_bps, "tier_yield_bps": cand.tier_yield_bps, "restart_pct": cand.restart_pct, "rebuild_cost_bps": cand.rebuild_cost_bps, "criteria": c, "margins": margins(c)})
    return rows


def grid_summary(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """How many neighbours of r4 pass, and how far inside the limits r4 itself is."""
    passing = [r["cand"] for r in rows if r["criteria"].get("all_pass")]
    near = [r for r in rows if r["cand"] != "r4"]
    return {"neighbours": len(near), "neighbours_passing": [r["cand"] for r in near if r["criteria"].get("all_pass")], "passing": passing, "r4_margins": next((r["margins"] for r in rows if r["cand"] == "r4"), None)}


def passes_with(c: Dict[str, Any], *, k2_min_gain: float = K2_MIN_GAIN, k4_max: float = ar.STYLE_MAX, k1_max: float = K1_LIMIT) -> bool:
    """The four checks with alternative limits (the structure of the checks stays: slowest style, repeats, farm, never legit)."""
    if not c:
        return False
    k1 = c.get("slowest_payback") is not None and c["slowest_payback"] <= k1_max
    g2, g3 = c.get("gain2"), c.get("gain3")
    k2 = bool(g2 and g3 and g2[0] >= k2_min_gain and g3[0] >= 0.0 and g2[1] >= mi.REPEAT_MIN_STYLE)
    median48 = c.get("produced_1460")
    k4 = bool(median48 and ar.C3_LOW <= median48[0] <= ar.C3_HIGH and c.get("max_style_ratio") is not None and c["max_style_ratio"] <= k4_max)
    return bool(k1 and k2 and c.get("k3_no_farm") and k4)


SWEEP_K2: Tuple[float, ...] = (0.0, 0.01, 0.02)
SWEEP_K4: Tuple[float, ...] = (1.25, 1.30)


def threshold_sweep(rows: Sequence[Dict[str, Any]]) -> Dict[Tuple[float, float], List[str]]:
    """Which candidates pass if the second-reset gain must be at least K2 and the best response may be at most K4?  Shows how much the verdict owes to the chosen limits."""
    return {(k2, k4): [r["cand"] for r in rows if passes_with(r["criteria"], k2_min_gain=k2, k4_max=k4)] for k2 in SWEEP_K2 for k4 in SWEEP_K4}


def stress_rows(results: Sequence[Dict[str, Any]], cand: str, arms: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """Each stress arm against the best sensible policy of the same style: cumulative production vs `never`, resets, AP earned."""
    best72 = mi.best_response(results, cand, "2190")
    out: Dict[str, Dict[str, Any]] = {}
    for arm in arms:
        ms = ar.style_metrics(results, arm, cand)
        if not ms:
            continue
        gap = {s: (None if ms[s]["produced_2190"] is None or best72.get(s) is None else ms[s]["produced_2190"] - best72[s]) for s in ms}
        out[arm] = {
            "produced_1460": ar.agg([v["produced_1460"] for v in ms.values()]),
            "produced_2190": ar.agg([v["produced_2190"] for v in ms.values()]),
            "resets": ar.agg([v["ap"]["runs"] for v in ms.values()]),
            "ap_2190": ar.agg([v["ap"]["ap_total_by"].get("2190") for v in ms.values()]),
            "gap_vs_best": gap,
            "worst_gap": max([g for g in gap.values() if g is not None] or [None]) if any(g is not None for g in gap.values()) else None,
        }
    return out


def _eleventh(res: Optional[Dict[str, Any]]) -> Optional[float]:
    founded = (res or {}).get("founded_days") or []
    return float(founded[-1]) if len(founded) >= 10 else None


def gate_rows(results: Sequence[Dict[str, Any]], cand: str) -> Dict[str, Any]:
    """First-reset economics inside one gate variant (the variant's own `never` is the reference)."""
    first, sel = ar.style_metrics(results, "O200", cand), ar.style_metrics(results, "P200", cand)
    if not first:
        return {}
    pays = [v["payback_day"] for v in first.values()]
    spay = [v["payback_day"] for v in sel.values()] if sel else []
    c = mi.criteria(results, cand)
    return {
        "o200_payback": ar.agg(pays), "o200_slowest": None if any(p is None for p in pays) else max(pays),
        "p200_payback": ar.agg(spay) if spay else None, "p200_slowest": None if not spay or any(p is None for p in spay) else max(spay),
        "o200_1460": ar.agg([v["produced_1460"] for v in first.values()]), "o200_2190": ar.agg([v["produced_2190"] for v in first.values()]),
        "k2": c.get("k2_repeats"), "gain2": c.get("gain2"), "gain3": c.get("gain3"), "best_response": c.get("max_style_ratio"), "k1_best_start": c.get("k1_best_start"),
        "eleventh_world_days": {st: _eleventh(ar.find(results, st, "never", "canon")) for st in STYLES},
    }


def _gb(x: Optional[float]) -> str:
    return "-" if not x else f"{x / 1e0:.3g}"


def casual_rows(results: Sequence[Dict[str, Any]], style: str = "casual") -> Dict[str, Dict[str, Any]]:
    """Where do time and resources go while the empire resets?  Per arm: resets by 12 / 24 months, spend by category relative to `never`, queue occupancy, 11th world."""
    ref = ar.find(results, style, "never", "canon")
    out: Dict[str, Dict[str, Any]] = {}
    for arm in ("never",) + CASUAL_ARMS:
        r = ref if arm == "never" else ar.find(results, style, arm, "r4")
        if not r:
            continue
        runs = sorted(r.get("runs", []), key=lambda x: float(x["day"]))
        d = r.get("diag") or {}
        metal = [x for x in runs if x["mine"] == "metal_mine"]
        crystal = [x for x in runs if x["mine"] == "crystal_mine"]
        row: Dict[str, Any] = {
            "resets": len(runs), "resets_by_365": sum(1 for x in runs if float(x["day"]) <= 365), "resets_by_730": sum(1 for x in runs if float(x["day"]) <= 730),
            "campaign_days": None if not runs else float(runs[-1]["day"]) - float(runs[0]["day"]),
            "metal_cliff": ar.agg([x["income_after_h"] / x["income_before_h"] for x in metal if x.get("income_before_h")]),
            "crystal_cliff": ar.agg([x["income_after_h"] / x["income_before_h"] for x in crystal if x.get("income_before_h")]),
            "rebuild_days_metal": ar.agg([x.get("rebuild_to_best_days") for x in metal]), "rebuild_days_crystal": ar.agg([x.get("rebuild_to_best_days") for x in crystal]),
            "eleventh_world_day": (r.get("founded_days") or [None])[-1] if len(r.get("founded_days") or []) >= 10 else None,
        }
        if arm != "never" and ref:
            row["metrics"] = ar.metrics(r, ref)
        for key in ("365", "730", "1095"):
            if key in d:
                dd = d[key]
                row[f"spend_mines_{key}"] = (dd.get("spend_metal") or {}).get("mines", 0) + (dd.get("spend_crystal") or {}).get("mines", 0)
                row[f"spend_research_{key}"] = (dd.get("spend_metal") or {}).get("research", 0) + (dd.get("spend_crystal") or {}).get("research", 0)
                row[f"research_queue_busy_{key}"] = dd.get("research_queue_busy_pct")
                row[f"planet_queue_busy_{key}"] = None if not dd.get("planet_queue_busy_pct") else sum(dd["planet_queue_busy_pct"]) / len(dd["planet_queue_busy_pct"])
                row[f"gate_sec_{key}"] = (dd.get("colony_pipeline_sec") or {}).get("gate:colony_maturity_required")
        out[arm] = row
    return out


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _fm(x: Optional[float], fmt: str) -> str:
    return "-" if x is None else format(x, fmt)


def render_markdown(data: Dict[str, List[Dict[str, Any]]]) -> str:
    """``data`` maps a source name to its results: s1 / s11 (milestone runs) and the suites grid / stress / strategy / gates / casual."""
    s1, s11 = data.get("s1", []), data.get("s11", [])
    L: List[str] = [
        "# Robustness checks of Ascension candidate r4 - generated tables",
        "",
        f"Version `{ANALYSIS_VERSION}`.  Casual / active / optimizer, policy v2 unless stated, UNI1 endgame curve, 72 months (casual diagnosis: 48 months).  Every number is relative to `never` of the same style and variant.  Candidates are **counterfactual rule sets applied as a sandbox patch**; nothing here is a game change.  Generated by `scripts/ascension_r4_checks.py`; the curated reading is in `docs/GC_ASCENSION_R4_CHECKS.md`.",
        "",
    ]
    # 1. neighbourhood
    grid = data.get("grid", [])
    if grid:
        names = ["r4", "r1"] + list(grid_candidates())
        rows = grid_rows(s1 + grid, names)
        summ = grid_summary(rows)
        L += [
            "## 1. Parameter neighbourhood of r4 (S1)",
            "",
            "Margin = distance to the limit (positive: inside): K1 days below 365, K2 gain of the second reset above 0.02, K4 best response below 1.25.  `r1` is r4 with +3 % output per tier.",
            "",
            "| Candidate | Awakening | Tier output | Kept | Rebuild cost | K1 slowest (days) | K2 gain 2nd / 3rd | K3 | K4 best response | All | Margin K1 / K2 / K4 |",
            "|---|---:|---:|---:|---:|---:|---|---|---:|---|---|",
        ]
        for r in rows:
            c, m = r["criteria"], r["margins"]
            L.append(
                f"| `{r['cand']}` | +{r['awaken_bps'] / 100:g} % | +{r['tier_yield_bps'] / 100:g} % | {r['restart_pct']} % | x{r['rebuild_cost_bps'] / 10000:g} | {_fm(c.get('slowest_payback'), '.0f')} | "
                f"{ar._g(c.get('gain2'), '{:+.2f}')} / {ar._g(c.get('gain3'), '{:+.2f}')} | {ar._yes(c.get('k3_no_farm'))} | {ar._r(c.get('max_style_ratio'), 3)} | {'**yes**' if c.get('all_pass') else 'no'} | "
                f"{_fm(m['k1_days'], '+.0f')} / {_fm(m['k2_gain'], '+.3f')} / {_fm(m['k4_ratio'], '+.3f')} |"
            )
        passing = ", ".join("`" + n + "`" for n in summ["neighbours_passing"]) or "none"
        L += ["", f"{len(summ['neighbours_passing'])} of {summ['neighbours']} neighbours pass all four checks ({passing}).", ""]
        L += ["How much of that verdict is owed to the limits?  Candidates passing all four checks if the second-reset gain must be at least K2 and the best response may be at most K4 (the base limits are K2 = 0.02, K4 = 1.25):", "", "| K2 min gain | K4 max | Passing | Candidates |", "|---:|---:|---:|---|"]
        for (k2, k4), ok in threshold_sweep(rows).items():
            L.append(f"| {k2:.2f} | {k4:.2f} | {len(ok)} of {len(rows)} | {', '.join('`' + n + '`' for n in ok) or 'none'} |")
        L.append("")
    # 2. strategy
    strat = data.get("strategy", [])
    if strat:
        v1 = by_variant(strat, "v1")
        L += ["## 2. Player strategy: pj-policy/2 (payback ranked, base) vs pj-policy/1 (goal list + patience) (S1)", "", "| Candidate | Strategy | K1 slowest (days) | K1 | K2 | K3 | K4 | Gain 2nd / 3rd | Best response | Cum. 48 / 72 mo (`O200`) |", "|---|---|---:|---|---|---|---|---|---:|---|"]
        for name in ("rank1_fast", "m1", "r4"):
            for label, res in (("v2", s1), ("v1", v1)):
                c = mi.criteria(res, name)
                if not c:
                    continue
                fo = ar.style_metrics(res, "O200", name)
                L.append(
                    f"| `{name}` | {label} | {_fm(c['slowest_payback'], '.0f')} | {c['k1_payback']} | {ar._yes(c['k2_repeats'])} | {ar._yes(c['k3_no_farm'])} | {ar._yes(c['k4_never_legit'])} | {ar._g(c['gain2'], '{:+.2f}')} / {ar._g(c['gain3'], '{:+.2f}')} | {ar._r(c['max_style_ratio'], 3)} | "
                    f"{ar._g(ar.agg([v['produced_1460'] for v in fo.values()]))} / {ar._g(ar.agg([v['produced_2190'] for v in fo.values()]))} |"
                )
        L.append("")
    # 3. gates
    gates = data.get("gates", [])
    if gates or s11:
        L += ["## 3. Colonisation gate PL10 / PL12 / PL15 (S11)", "", "PL15 is the base run of the milestone study.  *Best start* = the faster of the whole-empire reset and the metal mines only, per style.", "",
              "| Gate | Candidate | 11th world, `never` (day; casual / active / optimizer) | `O200` slowest (days) | `P200` slowest (days) | K1 best start | `O200` cum. 48 / 72 mo | K2 | Best response |", "|---|---|---|---:|---:|---|---|---|---:|"]
        for gate, res in (("PL10", by_variant(gates, "PL10")), ("PL12", by_variant(gates, "PL12")), ("PL15", s11)):
            for name in ("rank1_fast", "r4"):
                g = gate_rows(res, name)
                if not g:
                    continue
                eleventh = " / ".join(_fm(g["eleventh_world_days"].get(st), ".0f") for st in STYLES)
                L.append(
                    f"| {gate} | `{name}` | {eleventh} | {_fm(g['o200_slowest'], '.0f')} | {_fm(g['p200_slowest'], '.0f')} | {g['k1_best_start']} | {ar._g(g['o200_1460'])} / {ar._g(g['o200_2190'])} | {ar._yes(g['k2'])} | {ar._r(g['best_response'], 3)} |"
                )
        L.append("")
    # 4. stress
    stress = data.get("stress", [])
    if stress:
        L += ["## 4. Farming stress", "",
              "`A200` = the button-masher (resets whenever a mine is at or above L200, once a week per mine, never stops building), `L200+1` / `L200+10` = micro ladders (every +1 / +10 levels over the record), `C200` = crystal mines only, `O350` / `O400` = one very late reset (never reached = same as `never`).  *Gap* = cumulative production at 72 months minus the best sensible policy of the style (worst style); a positive gap would be a dominant strategy.", "",
              "| Topology | Candidate | Arm | Resets | AP earned | Cum. 48 mo | Cum. 72 mo | Gap vs best (worst style) |", "|---|---|---|---:|---:|---|---|---:|"]
        for topo, base, arms, names in (("S1", s1, STRESS_ARMS_S1, ("r4", "rank1_fast", "m1")), ("S11", s11, STRESS_ARMS_S11, ("r4",))):
            pool = [r for r in stress if r["topology"] == topo] + [r for r in base if r["arm"] in ("never", "O200", "P200", "L200+50x2", "L200+50x3", "O250", "O300")]
            for name in names:
                rows = stress_rows(pool, name, arms)
                for arm in arms:
                    x = rows.get(arm)
                    if not x:
                        continue
                    L.append(f"| {topo} | `{name}` | `{arm}` | {ar._gd(x['resets'])} | {ar._gd(x['ap_2190'])} | {ar._g(x['produced_1460'])} | {ar._g(x['produced_2190'])} | {_fm(x['worst_gap'], '+.2f')} |")
        L.append("")
    # 5. casual
    casual = data.get("casual", [])
    if casual:
        L += ["## 5. Why is the casual whole-empire reset slow? (S11, r4)", "",
              "Reset schedule and cost per arm.  *Cliff* = income of the planet right after a reset relative to a moment before, per mine type; *rebuild* = days until the mine is back at its record; spend is cumulative metal + crystal by category at 24 months, relative to `never` of the same style.", "",
              "| Style | Arm | Resets (12 / 24 mo) | Campaign (days) | Metal cliff | Crystal cliff | Rebuild metal / crystal (days) | Mines spend 24 mo | Research spend 24 mo | Planet queue busy 24 mo | 11th world (day) | Payback (days) | Cum. 24 / 48 mo |", "|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---:|---|"]
        for style in STYLES:
            rows = casual_rows(casual, style)
            ref = rows.get("never")
            for arm in ("never",) + CASUAL_ARMS:
                x = rows.get(arm)
                if not x:
                    continue
                rel = lambda key: "-" if not ref or not ref.get(key) or not x.get(key) else f"{x[key] / ref[key]:.2f}"  # noqa: E731
                m = x.get("metrics") or {}
                L.append(
                    f"| {style} | `{arm}` | {x['resets_by_365']} / {x['resets_by_730']} | {_fm(x['campaign_days'], '.0f')} | {ar._g(x['metal_cliff'])} | {ar._g(x['crystal_cliff'])} | {ar._gd(x['rebuild_days_metal'])} / {ar._gd(x['rebuild_days_crystal'])} | "
                    f"{rel('spend_mines_730')} | {rel('spend_research_730')} | {_fm(x.get('planet_queue_busy_730'), '.0f')} % | {_fm(x['eleventh_world_day'], '.0f')} | {_fm(m.get('payback_day'), '.0f')} | {_fm(m.get('produced_730'), '.2f')} / {_fm(m.get('produced_1460'), '.2f')} |"
                )
        L.append("")
    L += ["## 6. Limits", "", "* The world seed is not a suite: it pins only the homeworld's coordinates and DNA, and the simulated economy is identical for every seed (tested).  Per-planet world-type multipliers, trait effects and specialisations are not modelled, so planet-to-planet variation of the mine economy is outside this model.",
          "* Policies are fixed; a smarter or a clumsier player than the policies here may exist.  Thresholds are this analysis' operationalisation.", "* The baseline includes the outpost-XP defect (#556 not applied); one homeworld seed (eligible DNA) in S11."]
    return "\n".join(L)


def load_all(root: Path = ROOT) -> Dict[str, List[Dict[str, Any]]]:
    return {
        "s1": load(root / "artifacts/ascension_milestones/s1.json"), "s11": load(root / "artifacts/ascension_milestones/s11.json"),
        **{name: load(root / f"artifacts/ascension_r4/{name}.json") for name in SUITES},
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", choices=SUITES)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--days", type=float, default=None)
    ap.add_argument("--resume", default="", help="JSON of an earlier run: scenarios already in it are not run again, new ones are merged in")
    ap.add_argument("--out-json", default="")
    ap.add_argument("--report", default="", help="write the markdown report from the saved suites (no simulation) to this path")
    args = ap.parse_args(argv)
    if args.report:
        Path(args.report).write_text(render_markdown(load_all()) + "\n", encoding="utf-8")
        return 0
    if not args.suite or not args.out_json:
        ap.error("--suite and --out-json are required unless --report is given")
    specs = build_specs(args.suite, args.days if args.days is not None else DAYS)
    known: List[Dict[str, Any]] = []
    todo = specs
    if args.resume and Path(args.resume).exists():
        known = json.loads(Path(args.resume).read_text(encoding="utf-8"))["results"]
        have = {r["sid"] for r in known}
        todo = [s for s in specs if s["sid"] not in have]
    results = ar.merge_results(known, run_matrix(todo, args.workers or min(11, max(1, len(todo)))) if todo else [])
    Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out_json).write_text(json.dumps({"meta": {"version": ANALYSIS_VERSION, "suite": args.suite, "scenarios": len(specs)}, "results": results}, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
