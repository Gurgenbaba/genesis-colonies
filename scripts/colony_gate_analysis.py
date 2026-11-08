#!/usr/bin/env python3
"""PL10 vs PL15 colony-maturity gate under the corrected, uncapped mine progression (measurement only).

Question
--------
Colony n+1 can only be launched once every existing colony reached planet level 15 (``COLONY_MATURITY_REQUIRED_LEVEL``).
The progression-bottleneck report measured a PL10 gate in the *capped* model (mines stopped at L200).  The Ascension report
showed that under ``nodebuster-v1`` mines have no queue cap.  This module repeats the comparison in the corrected model:

* S11 journeys (up to 11 planets), casual / active / optimizer, policy v2, UNI1 endgame curve, 730 days;
* gate PL15 (the game) against PL10 (the existing sandbox lever ``colony_gate_pl10``, never a game change);
* arms ``never`` (keep building) and ``T200`` (ascend every mine at L200), plus ``legacy`` (the previous report's capped model)
  as a correction table.

It measures the 11th-world date, the economic lead (income, cumulative production, days ahead), casual fairness (casual / optimizer
ratios under each gate) and whether late colonies stay shallow ("colony spam").  No game value, formula or save game is touched.

Run::

    python scripts/colony_gate_analysis.py --out-json artifacts/colony_gate/latest.json --out-md docs/GC_COLONY_GATE_PL10_VS_PL15_REPORT.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ascension_analysis import _slim_snapshot  # noqa: E402

ANALYSIS_VERSION = "colony-gate-analysis/1"
STYLES: Tuple[str, ...] = ("casual", "active", "optimizer")
GATES: Dict[str, str] = {"PL15": "none", "PL10": "colony_gate_pl10"}  # label -> sandbox lever
GATE_ORDER: Tuple[str, ...] = ("PL15", "PL10")
ARMS: Dict[str, Tuple[str, str]] = {  # arm -> (asc mode, AP order)
    "legacy": ("legacy", "rebuild_first"),
    "never": ("never", "rebuild_first"),
    "T200": ("T200", "rebuild_first"),
}
MAIN_ARMS: Tuple[str, ...] = ("never", "T200")
REFERENCE_ARM = "legacy"
DAYS = 730.0
EXT_DAYS = 1460.0  # `never` only: does the lead of a lower gate persist or fade once both empires are complete?
CHECK_KEYS: Tuple[str, ...] = ("182.5", "365", "730")
EXT_KEYS: Tuple[str, ...] = ("1095", "1460")
CHECK_LABEL = {"182.5": "6 mo", "365": "12 mo", "730": "24 mo", "1095": "36 mo", "1460": "48 mo"}
PIPELINE_STATES: Tuple[Tuple[str, str], ...] = (
    ("gate:colony_maturity_required", "colony maturity gate"),
    ("gate:planet_evolution_colony_slot_required", "homeworld slot gate"),
    ("ark_building_or_flying", "ark building / flying"),
    ("seed_ark_unaffordable:metal", "seed ark unaffordable"),
    ("target_reached", "all colonies founded"),
)
WORLD_MILESTONES: Tuple[int, ...] = (2, 4, 6, 8, 11)
TARGET_WORLDS = 11


# ---------------------------------------------------------------------------
# Matrix / runner
# ---------------------------------------------------------------------------


def build_matrix(days: float = DAYS, quick: bool = False, arms: Sequence[str] = tuple(ARMS), extended: bool = True) -> List[Dict[str, Any]]:
    from scripts import player_journey_sim as pj

    styles = ("active",) if quick else STYLES
    out: List[Dict[str, Any]] = []
    plan: List[Tuple[str, str, float]] = [(style, arm, days) for style in styles for arm in arms]
    if extended and not quick:
        plan += [(style, "never", EXT_DAYS) for style in styles]
    for style, arm, horizon in plan:
        mode, order = ARMS[arm]
        suffix = f"-{int(horizon)}d" if horizon == EXT_DAYS else ""
        for gate in GATE_ORDER:
            out.append(
                {
                    "sid": f"S11-{style}-{arm}-{gate}{suffix}",
                    "topology": "S11",
                    "policy": style,
                    "strategy": "v2",
                    "arm": arm,
                    "asc": mode,
                    "asc_skills": order,
                    "gate": gate,
                    "lever": GATES[gate],
                    "days": float(horizon),
                    "rng_seed": pj.ELIGIBLE_HOME_SEED,
                }
            )
    return out


def _snap(c: Dict[str, Any]) -> Dict[str, Any]:
    out = _slim_snapshot(c)
    for k in ("mine_depth_median", "mine_depth_min", "hw_planet_level", "planet_levels", "mine_depth_by_world", "colony_pipeline_sec", "ascensions_total"):
        if k in c:
            out[k] = c[k]
    return out


def run_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """One scenario, executed in a worker process (the sandbox owns process-global state)."""
    from scripts import player_journey_sim as pj

    sc = pj.Scenario(
        spec["sid"], spec["topology"], spec["policy"], "mid", "none", float(spec["days"]),
        rng_seed=spec.get("rng_seed"), strategy=spec["strategy"], asc=spec["asc"], asc_skills=spec["asc_skills"], lever=spec.get("lever", "none"),
    )
    res = pj.run_scenario(sc)
    days = float(spec["days"])
    snaps: Dict[str, Any] = {}
    for key in CHECK_KEYS + EXT_KEYS:
        if float(key) > days + 1e-9:
            continue
        c = res["checkpoints"].get("day%s" % key)
        if c is None and abs(float(key) - days) < 1e-9:
            c = res["final"]
        if c is not None:
            snaps[key] = _snap(c)
    snaps["end"] = _snap(res["final"])
    peak_of = lambda r: int(r.get("peak_depth_max", r["mine_depth_max"]))  # noqa: E731
    series = [
        (int(r["day"]), int(r["empire_metal_h"]) + int(r["empire_crystal_h"]), peak_of(r), int(r.get("ascensions_total", 0)), int(r["worlds"]))
        for r in res["daily"][::5]
    ]
    return {
        "sid": spec["sid"],
        "style": spec["policy"],
        "arm": spec["arm"],
        "gate": spec["gate"],
        "days": days,
        "status": res["status"],
        "wall_seconds": res["wall_seconds"],
        "founded_days": [e["day"] for e in res["colony_log"] if e["event"] == "founded"],
        "gate_audit": res.get("gate_audit", []),
        "snapshots": snaps,
        "series": series,
        "invariants": res["invariants"],
    }


def run_matrix(specs: List[Dict[str, Any]], workers: int, progress: bool = True) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    started = time.time()
    specs = sorted(specs, key=lambda s: (-float(s["days"]), s["sid"]))
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


def find(results: Sequence[Dict[str, Any]], style: str, arm: str, gate: str, days: float = DAYS) -> Optional[Dict[str, Any]]:
    """Result of one scenario at the requested horizon (24 months unless the extended 48-month run is asked for)."""
    for r in results:
        if r["style"] == style and r["arm"] == arm and r["gate"] == gate and abs(float(r["days"]) - days) < 1e-9:
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


def produced(s: Dict[str, Any]) -> float:
    """Gross production (metal + crystal) of the whole empire since day 0."""
    return sum(float(w.get("produced_metal") or 0) + float(w.get("produced_crystal") or 0) for w in s.get("per_world", []))


def peak_depth(s: Dict[str, Any]) -> int:
    asc = s.get("ascension") or {}
    return int(asc.get("peak_depth_max") or s.get("peak_depth_max") or max(int(s.get("mine_depth_max") or 0), int(s.get("crystal_depth_max") or 0)))


def world_day(res: Dict[str, Any], n: int) -> Optional[float]:
    """Day on which the n-th world exists (world 1 = homeworld = day 0); None if not reached within the horizon."""
    if n <= 1:
        return 0.0
    founded = res.get("founded_days", [])
    return float(founded[n - 2]) if len(founded) >= n - 1 else None


def days_per_colony(res: Dict[str, Any]) -> Optional[float]:
    """Mean spacing between the 2nd and the last founded colony (the first colony is launched at once)."""
    f = res.get("founded_days", [])
    return (float(f[-1]) - float(f[0])) / (len(f) - 1) if len(f) >= 2 else None


def gate_share(s: Optional[Dict[str, Any]]) -> Optional[float]:
    """Share of elapsed time spent waiting at the colony-maturity gate."""
    if not s or not s.get("colony_pipeline_sec"):
        return None
    total = float(s.get("elapsed_sec") or 0)
    return None if total <= 0 else float(s["colony_pipeline_sec"].get("gate:colony_maturity_required", 0.0)) / total


def pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Relative change of a versus b in percent."""
    if a is None or b in (None, 0):
        return None
    return 100.0 * (float(a) / float(b) - 1.0)


def lead_days(fast: Dict[str, Any], ref: Dict[str, Any], key: str) -> Optional[int]:
    """How many days earlier ``fast`` reaches the income ``ref`` has at checkpoint ``key`` (None if it never does before then)."""
    target_snap = snap(ref, key)
    if not target_snap:
        return None
    target = income(target_snap)
    key_day = float(key)
    for d, inc, *_rest in fast["series"]:
        if float(d) <= key_day and float(inc) >= target:
            return int(round(key_day - float(d)))
    return None


def depth_summary(s: Optional[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    if not s or not s.get("mine_depth_by_world"):
        return None
    depths = [int(x) for x in s["mine_depth_by_world"]]
    return {"min": float(min(depths)), "median": float(median(depths)), "max": float(max(depths)), "worlds": float(len(depths))}


def ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return None if a is None or not b else float(a) / float(b)


def fairness(results: Sequence[Dict[str, Any]], arm: str, gate: str) -> Dict[str, Optional[float]]:
    """Casual relative to optimizer under one gate: 11th-world day (>1 = casual later), income and cumulative production (<1 = casual behind)."""
    c, o = find(results, "casual", arm, gate), find(results, "optimizer", arm, gate)
    if not c or not o:
        return {}
    out: Dict[str, Optional[float]] = {"day_11th_ratio": ratio(world_day(c, TARGET_WORLDS), world_day(o, TARGET_WORLDS))}
    for key in ("365", "730"):
        sc_, so_ = snap(c, key), snap(o, key)
        out[f"income_{key}"] = ratio(income(sc_), income(so_)) if sc_ and so_ else None
        out[f"produced_{key}"] = ratio(produced(sc_), produced(so_)) if sc_ and so_ else None
    return out


def pipeline_shares(s: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Share of elapsed time in each colony-pipeline state (what limits the next colony)."""
    if not s or not s.get("colony_pipeline_sec"):
        return {}
    total = float(s.get("elapsed_sec") or 0) or 1.0
    return {label: float(s["colony_pipeline_sec"].get(key, 0.0)) / total for key, label in PIPELINE_STATES}


def meta_block(specs: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"version": ANALYSIS_VERSION, "scenarios": len(specs), "days": DAYS, "extended_days": EXT_DAYS if any(float(s["days"]) == EXT_DAYS for s in specs) else None, "gates": GATES, "arms": sorted({s["arm"] for s in specs})}


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _d(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:,.0f}"


def _p(v: Optional[float], digits: int = 0) -> str:
    return "n/a" if v is None else f"{v:+.{digits}f}%"


def _r(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:.2f}"


def _h(v: Optional[float]) -> str:
    if v is None:
        return "-"
    n = float(v)
    for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(n) >= div:
            return f"{n / div:.1f}{unit}"
    return f"{n:.0f}"


def render_markdown(data: Dict[str, Any]) -> str:
    results = data["results"]
    L: List[str] = [
        "# PL10 vs PL15 colony gate - generated tables",
        "",
        f"Version `{data['meta']['version']}`.  S11 journeys (up to 11 planets), policy v2, UNI1 endgame curve, {data['meta']['days']:g} days, homeworld seed with eligible DNA.",
        "Gate `PL15` = the game (colony n+1 needs every colony at planet level 15); `PL10` = sandbox lever `colony_gate_pl10`.  Arms: `never` = keep building (canonical queue rules, no mine cap), `T200` = ascend each mine at L200, `legacy` = the progression report's capped model (reference only).",
        "Generated by `scripts/colony_gate_analysis.py`; the curated reading is in `docs/GC_COLONY_GATE_PL10_VS_PL15.md`.",
        "",
    ]
    n = 1
    # 1. colony timeline
    L += [f"## {n}. Colony timeline", "", "Day on which the n-th world exists, days between colonies, share of time waiting at the maturity gate (up to day 730).", "", "| Style | Arm | Gate | 2nd | 4th | 6th | 8th | 11th world | Days / colony | Gate wait (24 mo) |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for arm in MAIN_ARMS + (REFERENCE_ARM,):
        for style in STYLES:
            for gate in GATE_ORDER:
                r = find(results, style, arm, gate)
                if not r:
                    continue
                cells = [_d(world_day(r, m)) for m in WORLD_MILESTONES]
                gs = gate_share(snap(r, "730"))
                L.append(f"| {style} | `{arm}` | {gate} | " + " | ".join(cells) + f" | {_d(days_per_colony(r))} | {'n/a' if gs is None else f'{100 * gs:.0f}%'} |")
    n += 1
    # 2/3. economic lead
    for arm in MAIN_ARMS:
        L += ["", f"## {n}. Economic lead of PL10 over PL15 - arm `{arm}`", "", "Income = empire metal + crystal per hour.  Production = cumulative gross output since day 0.  Lead = days earlier PL10 reaches the income PL15 has at that checkpoint.", "", "| Style | Checkpoint | Worlds PL15 / PL10 | Income PL15 | Income PL10 | Change | Production PL15 | Production PL10 | Change | Deepest mine PL15 / PL10 | Lead |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for style in STYLES:
            a, b = find(results, style, arm, "PL15"), find(results, style, arm, "PL10")
            if not a or not b:
                continue
            for key in CHECK_KEYS:
                sa, sb = snap(a, key), snap(b, key)
                if not sa or not sb:
                    continue
                L.append(
                    f"| {style} | {CHECK_LABEL[key]} | {sa['worlds']} / {sb['worlds']} | {_h(income(sa))} | {_h(income(sb))} | {_p(pct(income(sb), income(sa)))} | {_h(produced(sa))} | {_h(produced(sb))} | {_p(pct(produced(sb), produced(sa)))} | L{peak_depth(sa)} / L{peak_depth(sb)} | {_d(lead_days(b, a, key))} d |"
                )
        n += 1
    # 4. fairness
    L += [f"## {n}. Casual fairness", "", "Casual relative to optimizer under each gate.  11th-world ratio > 1 means the casual player gets there later; income / production ratios < 1 mean the casual player is behind.  A gate that is fair to casual players moves these ratios towards 1.", "", "| Arm | Gate | 11th world casual / active / optimizer | Day ratio | Income 12 mo ratio | Income 24 mo ratio | Production 24 mo ratio |", "|---|---|---|---:|---:|---:|---:|"]
    for arm in MAIN_ARMS + (REFERENCE_ARM,):
        for gate in GATE_ORDER:
            f = fairness(results, arm, gate)
            if not f:
                continue
            days = " / ".join(_d(world_day(find(results, s, arm, gate), TARGET_WORLDS)) for s in STYLES if find(results, s, arm, gate))
            L.append(f"| `{arm}` | {gate} | {days} | {_r(f['day_11th_ratio'])} | {_r(f['income_365'])} | {_r(f['income_730'])} | {_r(f['produced_730'])} |")
    cross = [(find(results, "casual", "never", "PL10"), find(results, "optimizer", "never", "PL15"))]
    if all(cross[0]):
        c10, o15 = cross[0]
        s_c, s_o = snap(c10, "730"), snap(o15, "730")
        L += ["", f"Casual with PL10 against optimizer with PL15 (`never`): 11th world day {_d(world_day(c10, TARGET_WORLDS))} vs {_d(world_day(o15, TARGET_WORLDS))}; income at 24 months {_h(income(s_c))} vs {_h(income(s_o))} (ratio {_r(ratio(income(s_c), income(s_o)))}); cumulative production {_r(ratio(produced(s_c), produced(s_o)))}."]
    L += ["", "Change of each style when the gate drops from PL15 to PL10 (income at 24 months and day of the 11th world):", "", "| Arm | Style | 11th world PL15 -> PL10 | Income 24 mo change | Production 24 mo change |", "|---|---|---:|---:|---:|"]
    for arm in MAIN_ARMS:
        for style in STYLES:
            a, b = find(results, style, arm, "PL15"), find(results, style, arm, "PL10")
            if not a or not b:
                continue
            sa, sb = snap(a, "730"), snap(b, "730")
            L.append(f"| `{arm}` | {style} | {_d(world_day(a, TARGET_WORLDS))} -> {_d(world_day(b, TARGET_WORLDS))} | {_p(pct(income(sb), income(sa)))} | {_p(pct(produced(sb), produced(sa)))} |")
    n += 1
    # 5. maturity of late colonies
    L += ["", f"## {n}. Do the late colonies stay shallow?", "", "Mine depth (metal mine) across the empire's worlds and planet levels, arm `never`.  `median / best` close to the PL15 value means PL10 does not create a field of stunted worlds.", "", "| Style | Gate | Checkpoint | Worlds | Planet levels (home, then colonies) | Metal mine min / median / best | Median / best |", "|---|---|---|---:|---|---|---:|"]
    for style in STYLES:
        for gate in GATE_ORDER:
            r = find(results, style, "never", gate)
            if not r:
                continue
            for key in ("365", "730"):
                s = snap(r, key)
                ds = depth_summary(s)
                if not s or not ds:
                    continue
                pl = ", ".join(str(x) for x in s.get("planet_levels", []))
                L.append(f"| {style} | {gate} | {CHECK_LABEL[key]} | {int(ds['worlds'])} | {pl} | L{ds['min']:.0f} / L{ds['median']:.0f} / L{ds['max']:.0f} | {ds['median'] / ds['max']:.2f} |")
    n += 1
    # 5b. what limits the next colony
    L += ["", f"## {n}. What limits the colony chain once the gate drops?", "", "Share of the 24 months spent in each colony-pipeline state, arm `never`.  `all colonies founded` means the chain is complete.", "", "| Style | Gate | " + " | ".join(label for _k, label in PIPELINE_STATES) + " |", "|---|---|" + "---:|" * len(PIPELINE_STATES)]
    for style in STYLES:
        for gate in GATE_ORDER:
            sh = pipeline_shares(snap(find(results, style, "never", gate), "730"))
            if sh:
                L.append(f"| {style} | {gate} | " + " | ".join(f"{100 * sh[label]:.0f}%" for _k, label in PIPELINE_STATES) + " |")
    n += 1
    # 6. correction
    L += ["", f"## {n}. Correction of the earlier (capped) result", "", "Same gate comparison in the progression report's capped model (`legacy`, mines stop at L200) and in the corrected model (`never`).", "", "| Style | Model | 11th world PL15 -> PL10 | Income 12 mo change | Income 24 mo change |", "|---|---|---:|---:|---:|"]
    for style in STYLES:
        for arm in (REFERENCE_ARM, "never"):
            a, b = find(results, style, arm, "PL15"), find(results, style, arm, "PL10")
            if not a or not b:
                continue
            s365a, s365b, s730a, s730b = snap(a, "365"), snap(b, "365"), snap(a, "730"), snap(b, "730")
            L.append(
                f"| {style} | `{arm}` | {_d(world_day(a, TARGET_WORLDS))} -> {_d(world_day(b, TARGET_WORLDS))} | {_p(pct(income(s365b), income(s365a)) if s365a and s365b else None)} | {_p(pct(income(s730b), income(s730a)) if s730a and s730b else None)} |"
            )
    n += 1
    ext = [r for r in results if abs(float(r["days"]) - EXT_DAYS) < 1e-9]
    if ext:
        L += ["", f"## {n}. Does the lead persist? (arm `never`, 48-month run)", "", "Change of PL10 against PL15 and the days PL10 is ahead.  A lead measured in days is a head start, not a different endgame; the relative advantage shrinks as growth slows.", "", "| Style | Checkpoint | Worlds PL15 / PL10 | Income change | Production change | Deepest mine PL15 / PL10 | Lead |", "|---|---|---:|---:|---:|---:|---:|"]
        for style in STYLES:
            a, b = find(results, style, "never", "PL15", EXT_DAYS), find(results, style, "never", "PL10", EXT_DAYS)
            if not a or not b:
                continue
            for key in ("730", "1095", "1460"):
                sa, sb = snap(a, key), snap(b, key)
                if not sa or not sb:
                    continue
                L.append(f"| {style} | {CHECK_LABEL[key]} | {sa['worlds']} / {sb['worlds']} | {_p(pct(income(sb), income(sa)))} | {_p(pct(produced(sb), produced(sa)))} | L{peak_depth(sa)} / L{peak_depth(sb)} | {_d(lead_days(b, a, key))} d |")
        n += 1
    inv = [(r["sid"], r["invariants"].get("violations")) for r in results if not (r.get("invariants") or {}).get("ok", True)]
    L += ["", f"## {n}. Simulator invariants", "", "none violated" if not inv else "\n".join(f"* {sid}: {v}" for sid, v in inv), ""]
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--quick", action="store_true", help="active style only, 400-day smoke run")
    ap.add_argument("--days", type=float, default=None)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--out-json", default="")
    ap.add_argument("--out-md", default="")
    ap.add_argument("--render-from", default="", help="re-render markdown from a saved JSON (no simulation)")
    args = ap.parse_args(argv)
    if args.render_from:
        data = json.loads(Path(args.render_from).read_text(encoding="utf-8"))
    else:
        days = args.days if args.days is not None else (400.0 if args.quick else DAYS)
        specs = build_matrix(days, args.quick)
        workers = args.workers or min(10, len(specs))
        results = run_matrix(specs, workers)
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
