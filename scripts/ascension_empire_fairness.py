#!/usr/bin/env python3
"""Ascension reward fairness at empire scale (S11: up to 11 planets, 22 production mines).  Measurement only, no game change.

The reward study (``ascension_rewards_analysis``) priced candidate rule sets on S1 - one planet, two production mines.  Its best
candidate, ``rank1_fast`` (restart at 75 % of the best depth + rebuild cost x0.40 + a one-time strong first Deep Yield rank), is a
*per-mine* reward.  An 11-planet account owns 22 such mines, so the open question is whether the reward scales unfairly:
does one mine, several parallel resets or the whole empire profit disproportionally, and does the reward stay un-farmable?

Scopes (policies of ``player_journey_sim``; every reset is a real canonical Nodebuster call):

* ``M200``  one single reset of one single mine in the whole empire (the first mine that reaches L200)
* ``G200``  every mine once, but only ONE rebuild at a time in the whole empire (serial; a mine that is ready waits for its turn and keeps building)
* ``O200``  every mine once, one rebuild at a time per planet (planets in parallel: the whole empire resets as it matures)
* ``O200x4`` four resets per mine (the farm), ``L200+25`` a ladder (each further reset must beat the record by 25 levels)

Run::

    python scripts/ascension_empire_fairness.py --workers 10 --out-json artifacts/ascension_empire/latest.json --out-md docs/GC_ASCENSION_EMPIRE_FAIRNESS_REPORT.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import ascension_rewards_analysis as ar  # noqa: E402

ANALYSIS_VERSION = "ascension-empire-fairness/1"
STYLES = ar.STYLES
DAYS = 2190.0
REFERENCE_CAND = "rank1_fast"
SCOPE_ARMS: Tuple[str, ...] = ("M200", "G200", "O200")
GUARD_ARMS: Tuple[str, ...] = ("O200x4", "L200+25")
SCOPE_LABEL = {
    "M200": "one mine (single reset in the empire)",
    "G200": "serial (one rebuild at a time in the empire)",
    "O200": "planets in parallel (whole empire)",
    "O200x4": "farm (4 resets per mine)",
    "L200+25": "ladder (+25 levels per reset)",
}
# candidate -> arms.  canon: what the game does today at scale; fast_p10: the stacking-prestige reference that S1 showed to be farmable
PLAN: Dict[str, Tuple[str, ...]] = {
    "canon": ("O200",),
    "rank1_fast": SCOPE_ARMS + GUARD_ARMS,
    "fast_p10": ("O200", "O200x4"),
}
CAND_ORDER: Tuple[str, ...] = ("canon", "rank1_fast", "fast_p10")


# ---------------------------------------------------------------------------
# Matrix / runner
# ---------------------------------------------------------------------------


def build_matrix(days: float = DAYS, quick: bool = False, plan: Optional[Dict[str, Sequence[str]]] = None) -> List[Dict[str, Any]]:
    plan = plan or PLAN
    styles = ("active",) if quick else STYLES
    out: List[Dict[str, Any]] = []
    for style in styles:
        out.append({"sid": f"S11-{style}-never", "style": style, "arm": "never", "cand": "canon", "days": float(days)})
        for cand in CAND_ORDER:
            for arm in plan.get(cand, ()):
                out.append({"sid": f"S11-{style}-{arm}-{cand}", "style": style, "arm": arm, "cand": cand, "days": float(days)})
    return out


def run_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """One scenario, executed in a worker process (the sandbox owns process-global state)."""
    from scripts import player_journey_sim as pj

    cand = ar.CANDIDATES[spec["cand"]]
    sc = pj.Scenario(
        spec["sid"], "S11", spec["style"], "mid", "none", float(spec["days"]),
        rng_seed=pj.ELIGIBLE_HOME_SEED, strategy="v2", asc=spec["arm"], asc_skills=cand.ap_order,
    )
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
            for k in ("worlds", "mine_depth_median", "mine_depth_min", "mine_depth_max"):
                if k in c:
                    slim[k] = c[k]
            snaps[key] = slim
    peak_of = lambda r: int(r.get("peak_depth_max", r["mine_depth_max"]))  # noqa: E731
    series = [(int(r["day"]), int(r["empire_metal_h"]) + int(r["empire_crystal_h"]), peak_of(r), int(r.get("ascensions_total", 0)), int(r["worlds"])) for r in res["daily"][::5]]
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
        "founded_days": [e["day"] for e in res["colony_log"] if e["event"] == "founded"],
        "snapshots": snaps,
        "series": series,
        "runs": runs,
        "skill_log": skill_log,
        "invariants": res["invariants"],
    }


def run_matrix(specs: List[Dict[str, Any]], workers: int, progress: bool = True) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    started = time.time()
    specs = sorted(specs, key=lambda s: (s["style"] != "optimizer", s["sid"]))  # the slowest style first keeps the pool busy to the end
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


def max_parallel_rebuilds(runs: Sequence[Dict[str, Any]], horizon: float) -> int:
    """Largest number of mines that rebuild at the same time (a rebuild that never finished lasts to the horizon)."""
    events: List[Tuple[float, int]] = []
    for r in runs:
        start = float(r["day"])
        dur = r.get("rebuild_to_best_days")
        end = start + float(dur) if dur is not None else float(horizon)
        events.append((start, 1))
        events.append((end, -1))
    events.sort(key=lambda e: (e[0], e[1]))  # a rebuild that ends at the moment another starts does not overlap it
    cur = best = 0
    for _t, d in events:
        cur += d
        best = max(best, cur)
    return best


def resets_by(series: Sequence[Sequence[float]], day: float) -> int:
    best = 0
    for row in series:
        if float(row[0]) <= day + 1e-9:
            best = int(row[3])
    return best


def extras(res: Dict[str, Any]) -> Dict[str, Any]:
    runs = sorted(res.get("runs", []), key=lambda r: float(r["day"]))
    horizon = float(res.get("days") or ar.DAYS)
    first = runs[0] if runs else None
    return {
        "resets": len(runs),
        "planets": len({r["world"] for r in runs}),
        "mines": len({(r["world"], r["mine"]) for r in runs}),
        "max_parallel": max_parallel_rebuilds(runs, horizon),
        "first_world": None if not first else first["world"],
        "first_from_level": None if not first else first["from_level"],
        "resets_by_730": resets_by(res["series"], 730.0),
        "resets_by_1460": resets_by(res["series"], 1460.0),
        "resets_by_2190": resets_by(res["series"], 2190.0),
        "worlds_at_first_reset": None if not first else sum(1 for d in res.get("founded_days", []) if float(d) <= float(first["day"])) + 1,
    }


def style_ext(results: Sequence[Dict[str, Any]], arm: str, cand: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for style in STYLES:
        r, ref = ar.find(results, style, arm, cand), ar.reference(results, style)
        if r and ref:
            out[style] = ar.metrics(r, ref) | extras(r)
    return out


def _max_style(ms: Dict[str, Dict[str, Any]], keys: Sequence[str] = ("produced_1460", "produced_2190")) -> Optional[float]:
    vals = [float(v[k]) for v in ms.values() for k in keys if v.get(k) is not None]
    return max(vals) if vals else None


def _pay_class(ms: Dict[str, Dict[str, Any]]) -> str:
    """Payback class judged on the SLOWEST style ("for every style"), like the S1 study."""
    pay = ar.agg([v["payback_day"] for v in ms.values()])
    if not ms or not pay or not all(v["payback_day"] is not None for v in ms.values()):
        return "no"
    return "good" if pay[2] <= ar.C2_PAYBACK_DAYS else ("ok" if pay[2] <= ar.C2_PAYBACK_DAYS_OK else "no")


def criteria(results: Sequence[Dict[str, Any]], cand: str = REFERENCE_CAND) -> Dict[str, Any]:
    """Empire-scale fairness of one candidate: scale (O200), scope (M200 / G200 / O200) and the guard (farm, ladder)."""
    scopes = {arm: style_ext(results, arm, cand) for arm in SCOPE_ARMS + GUARD_ARMS}
    out: Dict[str, Any] = {"cand": cand, "scopes": {}}
    for arm, ms in scopes.items():
        if not ms:
            continue
        out["scopes"][arm] = {
            "produced_1460": ar.agg([v["produced_1460"] for v in ms.values()]),
            "produced_2190": ar.agg([v["produced_2190"] for v in ms.values()]),
            "max_style": _max_style(ms),
            "payback": ar.agg([v["payback_day"] for v in ms.values()]),
            "payback_class": _pay_class(ms),
            "worst_ratio": ar.agg([v["worst_ratio"] for v in ms.values()]),
            "real_advantage": ar.agg([v["real_advantage_day"] for v in ms.values()]),
            "resets": ar.agg([v["resets"] for v in ms.values()]),
            "planets": ar.agg([v["planets"] for v in ms.values()]),
            "max_parallel": ar.agg([v["max_parallel"] for v in ms.values()]),
        }
    o = out["scopes"].get("O200")
    out["scale_ok"] = None if not (o and o["produced_1460"]) else bool(ar.C3_LOW <= o["produced_1460"][0] <= ar.C3_HIGH and (o["max_style"] or 0) <= ar.STYLE_MAX)
    scope_vals = [out["scopes"][a]["max_style"] for a in SCOPE_ARMS if a in out["scopes"] and out["scopes"][a]["max_style"] is not None]
    out["scope_ok"] = None if not scope_vals else bool(max(scope_vals) <= ar.STYLE_MAX)
    out["payback_class"] = None if not o else o["payback_class"]
    # parallel vs serial: does it pay to reset the whole empire at once?
    g = out["scopes"].get("G200")
    out["parallel_gain"] = None if not (o and g and o["produced_1460"] and g["produced_1460"]) else o["produced_1460"][0] - g["produced_1460"][0]
    # guard: extra resets must not pay for any style and must not push a style over the limit
    farm_pays: List[str] = []
    one, four = style_ext(results, "O200", cand), style_ext(results, "O200x4", cand)
    for style in STYLES:
        if style in one and style in four and one[style]["produced_2190"] is not None and four[style]["produced_2190"] is not None:
            if float(four[style]["produced_2190"]) - float(one[style]["produced_2190"]) > ar.FARM_GAIN:
                farm_pays.append(style)
    guard_vals = [out["scopes"][a]["max_style"] for a in GUARD_ARMS if a in out["scopes"] and out["scopes"][a]["max_style"] is not None]
    out["farm_pays_for"] = farm_pays
    out["guard_ok"] = None if not (guard_vals or four) else bool(not farm_pays and (not guard_vals or max(guard_vals) <= ar.STYLE_MAX))
    parts = [out["scale_ok"], out["scope_ok"], out["guard_ok"]]
    out["all_pass"] = bool(all(p is True for p in parts) and out["payback_class"] in ("good", "ok"))
    return out


def vs_s1(results: Sequence[Dict[str, Any]], s1_results: Sequence[Dict[str, Any]], cand: str, arm: str = "O200") -> Dict[str, Any]:
    """Cumulative production vs never, S11 against the S1 study (same candidate, same arm), per checkpoint key (median over the styles)."""
    out: Dict[str, Any] = {}
    s11 = ar.style_metrics(results, arm, cand)
    s1 = ar.style_metrics(s1_results, arm, cand)
    for key in ("730", "1460", "2190"):
        a = ar.agg([v.get(f"produced_{key}") for v in s11.values()])
        b = ar.agg([v.get(f"produced_{key}") for v in s1.values()])
        out[key] = {"s11": a, "s1": b}
    return out


def meta_block(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "version": ANALYSIS_VERSION,
        "scenarios": len(specs),
        "days": max(float(s["days"]) for s in specs),
        "plan": {k: list(v) for k, v in PLAN.items()},
        "candidates": {k: ar.asdict(ar.CANDIDATES[k]) for k in CAND_ORDER},
        "thresholds": ar.thresholds(),
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def render_markdown(data: Dict[str, Any], s1_results: Optional[Sequence[Dict[str, Any]]] = None) -> str:
    results = data["results"]
    meta = data["meta"]
    th = ar.thresholds()
    cands = [c for c in CAND_ORDER if any(r["cand"] == c and r["arm"] != "never" for r in results)]
    crit = criteria(results, REFERENCE_CAND) if REFERENCE_CAND in cands else {}
    L: List[str] = [
        "# Ascension reward fairness at empire scale - generated tables",
        "",
        f"Version `{meta['version']}`.  S11 journeys (homeworld seed with eligible DNA, up to 11 planets / 22 production mines), casual / active / optimizer, policy v2, UNI1 endgame curve, {meta['days']:g} days.  Every number is relative to `never` (keep building, canonical rules) of the same style; cells show the median across the three styles and, in brackets, the range.",
        "Candidates are **counterfactual rule sets applied as a sandbox patch** of the Nodebuster owner for one run; nothing here is a game change.  Generated by `scripts/ascension_empire_fairness.py`; the curated reading is in `docs/GC_ASCENSION_EMPIRE_FAIRNESS.md`.",
        "",
        "## 1. Scopes",
        "",
        "| Arm | Meaning |",
        "|---|---|",
    ]
    for arm, text in SCOPE_LABEL.items():
        L.append(f"| `{arm}` | {text} |")
    L += [
        "",
        "## 2. Reference candidate by scope",
        "",
        f"`{REFERENCE_CAND}` = {ar.CANDIDATES[REFERENCE_CAND].label}.  *Resets* / *planets* = resets done and planets touched during the run, *max parallel* = largest number of mines rebuilding at the same time, *worst* = lowest empire income ratio in the 400 days after the first reset, *payback* = days after the first reset until the cumulative production is level with `never` for good, *real advantage* = days until income is >= 110 % of `never` for good.  `-` = not within the horizon.",
        "",
        "| Arm | Resets | Planets | Max parallel | Worst vs never | Payback (days) | Real advantage (days) | Cum. production 24 / 48 / 72 mo | Highest style (48 / 72 mo) |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    for arm in SCOPE_ARMS + GUARD_ARMS:
        ms = style_ext(results, arm, REFERENCE_CAND)
        if not ms:
            continue
        v = list(ms.values())
        L.append(
            f"| `{arm}` | {ar._gd(ar.agg([x['resets'] for x in v]))} | {ar._gd(ar.agg([x['planets'] for x in v]))} | {ar._gd(ar.agg([x['max_parallel'] for x in v]))} | {ar._g(ar.agg([x['worst_ratio'] for x in v]))} | "
            f"{ar._gd(ar.agg([x['payback_day'] for x in v]))} | {ar._gd(ar.agg([x['real_advantage_day'] for x in v]))} | "
            f"{ar._g(ar.agg([x['produced_730'] for x in v]))} / {ar._g(ar.agg([x['produced_1460'] for x in v]))} / {ar._g(ar.agg([x['produced_2190'] for x in v]))} | {ar._r(_max_style(ms))} |"
        )
    L += ["", "## 3. All candidates, arm `O200` (the whole empire, planets in parallel) and the farm", "", "| Candidate | Arm | Resets | Payback (days) | Cum. production 24 / 48 / 72 mo | Casual / active / optimizer at 72 mo |", "|---|---|---:|---:|---|---|"]
    for cand in cands:
        for arm in ("O200", "O200x4"):
            ms = style_ext(results, arm, cand)
            if not ms:
                continue
            v = list(ms.values())
            per = " / ".join(ar._r(ms[s]["produced_2190"]) if s in ms else "-" for s in STYLES)
            L.append(
                f"| `{cand}` | `{arm}` | {ar._gd(ar.agg([x['resets'] for x in v]))} | {ar._gd(ar.agg([x['payback_day'] for x in v]))} | "
                f"{ar._g(ar.agg([x['produced_730'] for x in v]))} / {ar._g(ar.agg([x['produced_1460'] for x in v]))} / {ar._g(ar.agg([x['produced_2190'] for x in v]))} | {per} |"
            )
    L += ["", "## 4. Does it scale?  Empire (S11) against one planet (S1)", ""]
    if s1_results:
        L += ["Cumulative production vs `never`, arm `O200`, median (range) over the styles.", "", "| Candidate | 24 mo S1 / S11 | 48 mo S1 / S11 | 72 mo S1 / S11 |", "|---|---|---|---|"]
        for cand in cands:
            cmp = vs_s1(results, s1_results, cand)
            cells = [f"{ar._g(cmp[k]['s1'])} / {ar._g(cmp[k]['s11'])}" for k in ("730", "1460", "2190")]
            L.append(f"| `{cand}` | " + " | ".join(cells) + " |")
    else:
        L.append("(no S1 reference loaded: pass `--s1-json artifacts/ascension_rewards/latest.json`)")
    L += ["", "## 5. Verdict for the reference candidate", ""]
    if crit:
        s = crit["scopes"]
        L += [
            f"Thresholds (this analysis' operationalisation, shared with the S1 study): cumulative production within {th['c3'][0]:g}-{th['c3'][1]:g} of `never` at 48 months (median) and no style above {th['style_max']:g} at 48 / 72 months; payback within {th['c2_payback_days']} days (good) or {th['c2_payback_days_ok']} days (ok) for every style; extra resets do not pay (no style gains more than {th['farm_gain']:g} from 4 resets over a single one).",
            "",
            "| Check | Result |",
            "|---|---|",
            f"| Scale: the whole empire (`O200`) stays within the window | {ar._yes(crit['scale_ok'])} |",
            f"| Scope: no scope (one mine / serial / parallel) pushes a style above {th['style_max']:g} | {ar._yes(crit['scope_ok'])} |",
            f"| Payback of the whole empire, judged on the slowest style | {crit['payback_class']} (median / range: {ar._gd(s['O200']['payback']) if 'O200' in s else '-'} days) |",
            f"| Guard: farming and the ladder do not pay | {ar._yes(crit['guard_ok'])}{'' if not crit['farm_pays_for'] else ' (farming pays for: ' + ', '.join(crit['farm_pays_for']) + ')'} |",
            f"| **All** | **{ar._yes(crit['all_pass'])}** |",
            "",
            f"Parallel vs serial: cumulative production at 48 months differs by {ar._r(crit['parallel_gain'], 3)} (`O200` minus `G200`)." if crit.get("parallel_gain") is not None else "",
        ]
    L += ["", "## 6. Limits", "", "* One homeworld seed (eligible DNA), one reward family, fixed policies; no Research-Lab Ascension, Stellar Forge, loot or Timekeeper.  Several DNA seeds belong to the PL10 robustness step.", "* The baseline includes the outpost-XP defect (#556 not applied); it affects colony founding, not the mine rules priced here.", "* `G200` is serial in the sense of the policy: a mine that is ready waits for the empire-wide rebuild slot and keeps building meanwhile, so it resets deeper than L200.", "* Thresholds are this analysis' operationalisation."]
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="active style only")
    ap.add_argument("--days", type=float, default=None)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--resume", default="", help="JSON of an earlier run: scenarios already in it are not run again, new ones are merged in")
    ap.add_argument("--s1-json", default="", help="JSON of the S1 reward study, for the scale comparison")
    ap.add_argument("--out-json", default="")
    ap.add_argument("--out-md", default="")
    ap.add_argument("--render-from", default="", help="re-render markdown from a saved JSON (no simulation)")
    args = ap.parse_args(argv)
    if args.render_from:
        data = json.loads(Path(args.render_from).read_text(encoding="utf-8"))
    else:
        days = args.days if args.days is not None else (730.0 if args.quick else DAYS)
        specs = build_matrix(days, args.quick)
        known: List[Dict[str, Any]] = []
        todo = specs
        if args.resume:
            known = json.loads(Path(args.resume).read_text(encoding="utf-8"))["results"]
            have = {r["sid"] for r in known}
            todo = [s for s in specs if s["sid"] not in have]
        results = ar.merge_results(known, run_matrix(todo, args.workers or min(10, max(1, len(todo)))) if todo else [])
        data = {"meta": meta_block(specs), "results": results}
    s1 = json.loads(Path(args.s1_json).read_text(encoding="utf-8"))["results"] if args.s1_json else None
    if args.out_json:
        Path(args.out_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out_json).write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    md = render_markdown(data, s1)
    if args.out_md:
        Path(args.out_md).write_text(md + "\n", encoding="utf-8")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
