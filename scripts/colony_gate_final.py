"""Final colony-gate comparison PL10 / PL12 / PL15 - measurement only.

Closes the open items of ``docs/GC_COLONY_GATE_PL10_VS_PL15.md``: the middle option PL12, expedition XP (dose-response, because
the real expedition XP goes to the *origin planet* of a movement and is uncapped), and a re-run with the outpost-XP fix of #556
(the "fix" suite runs the same scenarios in a scratch checkout that carries that fix; this branch does not contain it).

Nothing in ``game/`` is changed: the gate levels are the existing sandbox levers (``colony_gate_pl10`` / ``colony_gate_pl12``), they
patch ``COLONY_MATURITY_REQUIRED_LEVEL`` for one simulated run and restore it.  S11 (up to 11 planets), the three player styles,
policy v2, the UNI1 endgame curve, one homeworld seed (the seed does not change the simulated economy, see
``docs/GC_ASCENSION_R4_CHECKS.md``).  Arm ``never`` only: Ascension does not interact with the colony chain (``T200`` gave the same
dates within +-5 days in the PL10 / PL15 study).

    python scripts/colony_gate_final.py --suite base --workers 10 --out-json artifacts/colony_gate_final/base.json
    python scripts/colony_gate_final.py --suite fix  --workers 10 --out-json artifacts/colony_gate_final/fix.json   # scratch checkout with #556
    python scripts/colony_gate_final.py --report docs/GC_COLONY_GATE_FINAL_REPORT.md
"""

from __future__ import annotations

import argparse
import inspect
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import colony_gate_analysis as cga  # noqa: E402

ANALYSIS_VERSION = "colony-gate-final/1"
STYLES: Tuple[str, ...] = cga.STYLES
GATES: Dict[str, str] = {"PL15": "none", "PL12": "colony_gate_pl12", "PL10": "colony_gate_pl10"}  # label -> sandbox lever
GATE_ORDER: Tuple[str, ...] = ("PL15", "PL12", "PL10")
GATE_LEVEL = {"PL15": 15, "PL12": 12, "PL10": 10}
DAYS = 730.0
EXT_DAYS = 1460.0
BASE_RATES: Tuple[int, ...] = (0, 3, 6, 15)  # expeditions per day sent from the colony under development (dose-response)
FIX_RATES: Tuple[int, ...] = (0, 6)
EXT_RATES: Tuple[int, ...] = (0, 6)  # 48-month runs
SUITES: Tuple[str, ...] = ("base", "fix")
CHECKS: Tuple[str, ...] = ("365", "730", "1460")
CHECK_LABEL = {"365": "12 mo", "730": "24 mo", "1460": "48 mo"}
MILESTONES: Tuple[int, ...] = (2, 4, 6, 8, 11)
HABIT_CASUAL_RATE, HABIT_OPTIMIZER_RATE = 3, 15
DEFAULT_DIR = ROOT / "artifacts" / "colony_gate_final"


# ---------------------------------------------------------------------------
# Matrix / runner
# ---------------------------------------------------------------------------


def outpost_hold_applied() -> bool:
    """True if the checkout carries the outpost-XP fix of #556 (the level-0 hold in ``add_planet_xp``)."""
    from game.planet_evolution import planet_level

    return "held_until_established" in inspect.getsource(planet_level.add_planet_xp)


def build_specs(suite: str, days: float = DAYS, styles: Sequence[str] = STYLES) -> List[Dict[str, Any]]:
    if suite not in SUITES:
        raise ValueError(f"unknown suite {suite!r}")
    from scripts import player_journey_sim as pj

    plan: List[Tuple[int, float]] = [(rate, days) for rate in (BASE_RATES if suite == "base" else FIX_RATES)]
    if suite == "base" and days == DAYS:
        plan += [(rate, EXT_DAYS) for rate in EXT_RATES]
    mode, order = cga.ARMS["never"]
    out: List[Dict[str, Any]] = []
    for rate, horizon in plan:
        for style in styles:
            for gate in GATE_ORDER:
                suffix = f"-{int(horizon)}d" if horizon != DAYS else ""
                out.append(
                    {
                        "sid": f"S11-{style}-never-{gate}-x{rate}{suffix}",
                        "topology": "S11",
                        "policy": style,
                        "strategy": "v2",
                        "arm": "never",
                        "asc": mode,
                        "asc_skills": order,
                        "gate": gate,
                        "lever": GATES[gate],
                        "days": float(horizon),
                        "rng_seed": pj.ELIGIBLE_HOME_SEED,
                        "expeditions_per_day": int(rate),
                    }
                )
    return out


def run_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    res = cga.run_spec(spec)
    res["fix556"] = outpost_hold_applied()
    return res


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


def pick(results: Sequence[Dict[str, Any]], style: str, gate: str, rate: int = 0, days: float = DAYS) -> Optional[Dict[str, Any]]:
    for r in results:
        if r["style"] == style and r["gate"] == gate and int(r.get("expeditions_per_day", 0)) == int(rate) and abs(float(r["days"]) - days) < 1e-9:
            return r
    return None


def _day(res: Optional[Dict[str, Any]], n: int) -> Optional[float]:
    return None if res is None else cga.world_day(res, n)


def _diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return None if a is None or b is None else float(a) - float(b)


def timeline(results: Sequence[Dict[str, Any]], rate: int = 0) -> Dict[str, Dict[str, Dict[int, Optional[float]]]]:
    """style -> gate -> {n: day the n-th world exists}."""
    return {s: {g: {n: _day(pick(results, s, g, rate), n) for n in MILESTONES} for g in GATE_ORDER} for s in STYLES}


def economy_vs_pl15(results: Sequence[Dict[str, Any]], style: str, gate: str, rate: int = 0) -> Dict[str, Dict[str, Optional[float]]]:
    """Income change, cumulative-production change (percent) and lead (days) of ``gate`` against PL15 at 12 / 24 / 48 months."""
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for key in CHECKS:
        horizon = DAYS if float(key) <= DAYS else EXT_DAYS
        fast, ref = pick(results, style, gate, rate, horizon), pick(results, style, "PL15", rate, horizon)
        sf, sr = cga.snap(fast, key), cga.snap(ref, key)
        if not sf or not sr:
            out[key] = {"income_pct": None, "produced_pct": None, "lead_days": None}
            continue
        out[key] = {
            "income_pct": cga.pct(cga.income(sf), cga.income(sr)),
            "produced_pct": cga.pct(cga.produced(sf), cga.produced(sr)),
            "lead_days": None if fast is None or ref is None else cga.lead_days(fast, ref, key),
        }
    return out


def pl12_share(results: Sequence[Dict[str, Any]], style: str, rate: int = 0) -> Dict[str, Optional[float]]:
    """How much of the PL10 effect PL12 delivers: (PL15 - PL12) / (PL15 - PL10) for the 11th-world day, and (PL12 - PL15) / (PL10 - PL15) for production."""
    d15, d12, d10 = (_day(pick(results, style, g, rate), 11) for g in ("PL15", "PL12", "PL10"))
    gap10, gap12 = _diff(d15, d10), _diff(d15, d12)
    out: Dict[str, Optional[float]] = {"day_11th": None if not gap10 or gap12 is None else gap12 / gap10}
    for key in ("730", "1460"):
        days = EXT_DAYS if key == "1460" else DAYS
        p = {g: cga.snap(pick(results, style, g, rate, days), key) for g in ("PL15", "PL12", "PL10")}
        if not all(p.values()):
            out[f"produced_{key}"] = None
            continue
        gain10 = cga.produced(p["PL10"]) - cga.produced(p["PL15"])
        out[f"produced_{key}"] = None if not gain10 else (cga.produced(p["PL12"]) - cga.produced(p["PL15"])) / gain10
    return out


def dose_response(results: Sequence[Dict[str, Any]], style: str) -> List[Dict[str, Any]]:
    """Per expedition rate: 11th-world day per gate, the days PL12 / PL10 gain over PL15, production change at 24 months, expedition XP."""
    rows: List[Dict[str, Any]] = []
    for rate in sorted({int(r.get("expeditions_per_day", 0)) for r in results}):
        days = {g: _day(pick(results, style, g, rate), 11) for g in GATE_ORDER}
        if all(v is None for v in days.values()) and pick(results, style, "PL15", rate) is None:
            continue
        prod: Dict[str, Optional[float]] = {}
        base_snap = cga.snap(pick(results, style, "PL15", rate), "730")
        for g in ("PL12", "PL10"):
            s = cga.snap(pick(results, style, g, rate), "730")
            prod[g] = cga.pct(cga.produced(s), cga.produced(base_snap)) if s and base_snap else None
        ref = pick(results, style, "PL15", rate)
        rows.append(
            {
                "rate": rate,
                "day_11th": days,
                "gain_pl12": _diff(days["PL15"], days["PL12"]),
                "gain_pl10": _diff(days["PL15"], days["PL10"]),
                "produced_730": prod,
                "expedition_xp": int((ref or {}).get("xp_by_source", {}).get("expedition", 0)),
                "gate_share_pl15": cga.gate_share(cga.snap(ref, "730")),
            }
        )
    return rows


def fix_effect(base: Sequence[Dict[str, Any]], fixed: Sequence[Dict[str, Any]], style: str, gate: str, rate: int) -> Dict[str, Optional[float]]:
    """Effect of the #556 outpost-XP hold on one scenario: shift of the 4th / 11th world (days) and of the 24-month production (percent)."""
    a, b = pick(base, style, gate, rate), pick(fixed, style, gate, rate)
    if a is None or b is None:
        return {}
    sa, sb = cga.snap(a, "730"), cga.snap(b, "730")
    return {
        "shift_4th": _diff(_day(b, 4), _day(a, 4)),
        "shift_11th": _diff(_day(b, 11), _day(a, 11)),
        "produced_pct": cga.pct(cga.produced(sb), cga.produced(sa)) if sa and sb else None,
        "income_pct": cga.pct(cga.income(sb), cga.income(sa)) if sa and sb else None,
    }


def fix_summary(base: Sequence[Dict[str, Any]], fixed: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Mean / min / max over every (style, gate, rate) pair of the #556 effect; with no sign pattern the range is the simulator's noise, not an effect."""
    rows = [cga_row for style in STYLES for gate in GATE_ORDER for rate in FIX_RATES if (cga_row := fix_effect(base, fixed, style, gate, rate))]
    out: Dict[str, Dict[str, float]] = {}
    for key in ("shift_4th", "shift_11th", "produced_pct", "income_pct"):
        vals = [float(r[key]) for r in rows if r.get(key) is not None]
        if vals:
            out[key] = {"mean": sum(vals) / len(vals), "min": min(vals), "max": max(vals), "n": float(len(vals)), "positive": float(sum(1 for v in vals if v > 0))}
    return out


def fairness(results: Sequence[Dict[str, Any]], gate: str, casual_rate: int = 0, optimizer_rate: int = 0) -> Dict[str, Optional[float]]:
    """Casual relative to optimizer under one gate (>1 = casual later, <1 = casual behind)."""
    c, o = pick(results, "casual", gate, casual_rate), pick(results, "optimizer", gate, optimizer_rate)
    if c is None or o is None:
        return {}
    out: Dict[str, Optional[float]] = {"day_11th": cga.ratio(_day(c, 11), _day(o, 11))}
    for key in ("365", "730"):
        sc_, so_ = cga.snap(c, key), cga.snap(o, key)
        out[f"income_{key}"] = cga.ratio(cga.income(sc_), cga.income(so_)) if sc_ and so_ else None
        out[f"produced_{key}"] = cga.ratio(cga.produced(sc_), cga.produced(so_)) if sc_ and so_ else None
    return out


def invariants_ok(results: Sequence[Dict[str, Any]]) -> bool:
    return all(bool((r.get("invariants") or {}).get("ok", True)) for r in results)


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _d(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:,.0f}"


def _sd(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:+,.0f}"


def _p(v: Optional[float], digits: int = 0) -> str:
    return "n/a" if v is None else f"{v:+.{digits}f}%"


def _r(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:.2f}"


def _share(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{100.0 * v:.0f}%"


def render_markdown(base: Sequence[Dict[str, Any]], fixed: Optional[Sequence[Dict[str, Any]]] = None) -> str:
    L: List[str] = ["# Colony gate PL10 / PL12 / PL15 - final comparison (generated)", ""]
    L += [
        "> Measurement only. Generated by `scripts/colony_gate_final.py`; curated reading in `docs/GC_COLONY_GATE_FINAL.md`.",
        "",
        f"Scenarios: {len(base)} without the #556 outpost-XP fix" + (f", {len(fixed)} with it" if fixed else ", no run with the fix loaded") + f". Invariants hold in all runs: {invariants_ok(list(base) + list(fixed or []))}.",
        "",
        "S11, arm `never`, policy v2, UNI1 curve, one homeworld seed. `xN` = N expeditions per day launched from the colony under development (15 XP each, +75 per 10, no daily cap).",
        "",
        "## 1. Colony timeline without expeditions (day the n-th world exists)",
        "",
        "| Style | Gate | 2nd | 4th | 6th | 8th | 11th | Gate wait (24 mo) |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    tl = timeline(base, 0)
    for s in STYLES:
        for g in GATE_ORDER:
            snap730 = cga.snap(pick(base, s, g, 0), "730")
            L.append(f"| {s} | {g} | " + " | ".join(_d(tl[s][g][n]) for n in MILESTONES) + f" | {_share(cga.gate_share(snap730))} |")
    L += ["", "## 2. Economic lead over PL15 (no expeditions)", "", "| Style | Gate | Income 12 mo | Income 24 mo | Income 48 mo | Production 12 mo | Production 24 mo | Production 48 mo | Lead 24 / 48 mo (days) |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for s in STYLES:
        for g in ("PL12", "PL10"):
            e = economy_vs_pl15(base, s, g, 0)
            L.append(
                f"| {s} | {g} | " + " | ".join(_p(e[k]["income_pct"]) for k in CHECKS) + " | " + " | ".join(_p(e[k]["produced_pct"]) for k in CHECKS)
                + f" | {_d(e['730']['lead_days'])} / {_d(e['1460']['lead_days'])} |"
            )
    L += ["", "### How much of PL10 does PL12 deliver?", "", "| Style | 11th-world date | Production 24 mo | Production 48 mo |", "|---|---:|---:|---:|"]
    for s in STYLES:
        sh = pl12_share(base, s, 0)
        L.append(f"| {s} | {_share(sh['day_11th'])} | {_share(sh['produced_730'])} | {_share(sh['produced_1460'])} |")

    L += ["", "## 3. Expedition XP dose-response", "", "Same rate for every style, to isolate the XP intake of the colony under development. Day of the 11th world; `gain` = days earlier than PL15.", "", "| Style | Expeditions / day | Expedition XP (24 mo) | PL15 | PL12 | PL10 | Gain PL12 | Gain PL10 | Production 24 mo PL12 / PL10 vs PL15 | Gate wait PL15 |", "|---|---:|---:|---:|---:|---:|---:|---:|---|---:|"]
    for s in STYLES:
        for row in dose_response(base, s):
            d = row["day_11th"]
            L.append(
                f"| {s} | {row['rate']} | {_d(row['expedition_xp'])} | {_d(d['PL15'])} | {_d(d['PL12'])} | {_d(d['PL10'])} | {_sd(row['gain_pl12'])} | {_sd(row['gain_pl10'])}"
                f" | {_p(row['produced_730']['PL12'])} / {_p(row['produced_730']['PL10'])} | {_share(row['gate_share_pl15'])} |"
            )

    L += ["", "### 48 months with expeditions (x6)", "", "| Style | Gate | Income 24 mo | Income 48 mo | Production 24 mo | Production 48 mo |", "|---|---|---:|---:|---:|---:|"]
    for s in STYLES:
        for g in ("PL12", "PL10"):
            e = economy_vs_pl15(base, s, g, 6)
            L.append(f"| {s} | {g} | {_p(e['730']['income_pct'])} | {_p(e['1460']['income_pct'])} | {_p(e['730']['produced_pct'])} | {_p(e['1460']['produced_pct'])} |")

    L += ["", "## 4. Fairness: casual relative to optimizer", "", "`same` = both styles at the same expedition rate (x0); `habit` = casual launches x%d, optimizer x%d (the casual player hardly runs expeditions, the optimizer does).  >1 on the date = casual later, <1 on income / production = casual behind." % (HABIT_CASUAL_RATE, HABIT_OPTIMIZER_RATE), "", "| Gate | Mix | 11th world casual / optimizer | Date ratio | Income 24 mo | Production 24 mo |", "|---|---|---:|---:|---:|---:|"]
    for g in GATE_ORDER:
        for label, cr, orr in (("same (x0)", 0, 0), ("habit", HABIT_CASUAL_RATE, HABIT_OPTIMIZER_RATE)):
            c, o = pick(base, "casual", g, cr), pick(base, "optimizer", g, orr)
            f = fairness(base, g, cr, orr)
            L.append(f"| {g} | {label} | {_d(_day(c, 11))} / {_d(_day(o, 11))} | {_r(f.get('day_11th'))} | {_r(f.get('income_730'))} | {_r(f.get('produced_730'))} |")

    L += ["", "## 5. Outpost-XP fix (#556)", ""]
    if not fixed:
        L += ["No run with the fix is loaded.", ""]
    else:
        L += [
            "The fix holds a new colony at level 0 until its three establishment buildings exist and replays the XP then. Shift = with the fix minus without (days; production in percent at 24 months).",
            "",
            "| Style | Gate | Expeditions / day | Shift 4th world | Shift 11th world | Income 24 mo | Production 24 mo |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for s in STYLES:
            for g in GATE_ORDER:
                for rate in FIX_RATES:
                    e = fix_effect(base, fixed, s, g, rate)
                    if e:
                        L.append(f"| {s} | {g} | {rate} | {_sd(e['shift_4th'])} | {_sd(e['shift_11th'])} | {_p(e['income_pct'], 1)} | {_p(e['produced_pct'], 1)} |")
        sm = fix_summary(base, fixed)
        if sm:
            L += [
                "",
                f"Over all {int(sm['shift_4th']['n'])} pairs: 4th world {sm['shift_4th']['mean']:+.1f} days on average (range {sm['shift_4th']['min']:+.0f} … {sm['shift_4th']['max']:+.0f}, later in {int(sm['shift_4th']['positive'])}), "
                f"11th world {sm['shift_11th']['mean']:+.1f} days (range {sm['shift_11th']['min']:+.0f} … {sm['shift_11th']['max']:+.0f}, later in {int(sm['shift_11th']['positive'])}), "
                f"24-month production {sm['produced_pct']['mean']:+.1f}% (range {sm['produced_pct']['min']:+.1f}% … {sm['produced_pct']['max']:+.1f}%).",
            ]
        L += ["", "11th-world day with the fix (x0 / x6):", "", "| Style | PL15 | PL12 | PL10 |", "|---|---:|---:|---:|"]
        for s in STYLES:
            cells = []
            for g in GATE_ORDER:
                cells.append(f"{_d(_day(pick(fixed, s, g, 0), 11))} / {_d(_day(pick(fixed, s, g, 6), 11))}")
            L.append(f"| {s} | " + " | ".join(cells) + " |")
    L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def load_suite(path: Path) -> Optional[List[Dict[str, Any]]]:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["results"]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", choices=SUITES)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--days", type=float, default=DAYS)
    ap.add_argument("--out-json", default="")
    ap.add_argument("--report", default="", help="write the markdown report from the saved suites (no simulation)")
    ap.add_argument("--base-json", default=str(DEFAULT_DIR / "base.json"))
    ap.add_argument("--fix-json", default=str(DEFAULT_DIR / "fix.json"))
    args = ap.parse_args(argv)
    if args.report:
        base = load_suite(Path(args.base_json))
        if base is None:
            ap.error(f"no base suite at {args.base_json}")
        Path(args.report).write_text(render_markdown(base, load_suite(Path(args.fix_json))) + "\n", encoding="utf-8")
        return 0
    if not args.suite or not args.out_json:
        ap.error("--suite and --out-json are required unless --report is given")
    import os

    specs = build_specs(args.suite, args.days)
    workers = args.workers or max(1, (os.cpu_count() or 2) - 2)
    results = run_matrix(specs, workers)
    out = Path(args.out_json)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"meta": {"version": ANALYSIS_VERSION, "suite": args.suite, "fix556": outpost_hold_applied(), "scenarios": len(specs)}, "results": results}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
